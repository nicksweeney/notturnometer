#!/usr/bin/env bash
# ttn_nightly.sh -- the nightly pipeline, run from cron:
#
#   pull -> segments --retry-absent -> update (scrape/segments/warm)
#        -> successor-refresh (ingest/ledger-import/match -> successor.sqlite)
#        -> entities -> successor site (build + render + search catalogue)
#        -> registry commit+push
#        -> rsync deploy -> live check
#
# set -e means any failing stage aborts the run BEFORE the deploy, so a
# broken build never replaces the live site (a registry-drift failure after
# an unremapped alias edit lands here: the site just stays on yesterday's
# render until the remap is pushed). Logs: scratch/nightly/YYYY-MM-DD.log,
# pruned after 30 days. Designed for the build host; the Pi never
# runs this.
#
# --no-deploy runs the identical data + build pipeline on a DEV box and stops
# short of shipping: no deploy.env requirement, no rsync, no live curl, and
# NO registry commit/push (a local commit that is never pushed would diverge
# from origin and break tomorrow's --ff-only pull, so in no-deploy mode the
# registry diff is only REPORTED for review). The one script definition is
# deliberate: a copied variant would silently drift from the build server's.
# ttn_local.sh is the dev-box entry point.
set -euo pipefail

DEPLOY=1
for arg in "$@"; do
    case "$arg" in
        --no-deploy) DEPLOY=0 ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")"

# cron's PATH is bare. uv lives in ~/.local/bin.
export PATH="$HOME/.local/bin:$PATH"

LOGDIR="scratch/nightly"
mkdir -p "$LOGDIR"
# `date -Is` is GNU-only; BSD/macOS rejects -I. Fall back to an explicit
# ISO-8601 UTC stamp so the log line reads the same on either platform.
_NOW() { date -Iseconds 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ; }
exec >>"$LOGDIR/$(date +%F).log" 2>&1
find "$LOGDIR" -name '*.log' -mtime +30 -delete
echo "=== nightly start $(_NOW)"

# The deploy target (user@host:path) is NOT committed -- this is a public
# repo, and the rsync dest discloses the live-site account. It lives in an
# untracked deploy.env beside this script. Create it on the build host with:
#     echo 'TTN_DEPLOY_DEST=user@host:path/' > deploy.env
# Guarded early (before the ~hour build) so a missing dest fails fast and
# never after a full rebuild it can't ship. SKIPPED entirely under --no-deploy.
if [ "$DEPLOY" = 1 ]; then
    [ -f deploy.env ] && . ./deploy.env
    : "${TTN_DEPLOY_DEST:?deploy.env must set TTN_DEPLOY_DEST (rsync dest); refusing to deploy}"
else
    echo "=== --no-deploy: dev run, no rsync to a web host, no live check ==="
fi

# Pick up anything pushed from the Pi (alias edits, template changes, ...).
# SELF-REPLACE GUARD: bash reads this file incrementally from its own fd, so
# a pull that updates ttn_nightly.sh mid-run leaves the running bash holding
# a stale read offset into new bytes -- the remainder of the run can execute
# a corrupted splice. Detect a changed script and exec the new one from byte
# zero. The pull is the ONLY self-modifying step, and it sits before every
# heavy stage, so a restart re-runs nothing expensive (the pull is then a
# no-op; the log append at the top just continues).
_SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
# sha256sum on Linux, shasum -a 256 on macOS (the dev box); absent either way,
# skip the guard rather than abort the run under `set -e`.
if command -v sha256sum >/dev/null 2>&1; then
    _SUM() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
    _SUM() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
    _SUM() { echo "no-hash-tool"; }
fi
_SELF_SUM_BEFORE="$(_SUM "$_SELF")"
git pull --ff-only
if [ "$(_SUM "$_SELF")" != "$_SELF_SUM_BEFORE" ]; then
    echo "=== ttn_nightly.sh updated mid-run; restarting from the new script ==="
    exec bash "$_SELF"
fi

# Nightly source-DB backup BEFORE any stage mutates ttn.sqlite. The corpus is
# mostly re-scrapable, but raw_json preserves what the BBC served at fetch
# time -- expired/edited episode pages are unrecoverable, so the DB is the
# only durable record of those bytes. sqlite3 .backup via the python module
# (no sqlite3 CLI on the host): consistent snapshot even if a stage crashed
# mid-write yesterday, ~1.3s. Gzipped ~70MB (5:1); keep 14 -> ~1GB steady.
BACKUP_DIR="scratch/backups"
mkdir -p "$BACKUP_DIR"
python3 - "$BACKUP_DIR" <<'PYEOF'
import glob
import gzip
import os
import shutil
import sqlite3
import sys
import time

backup_dir = sys.argv[1]
stamp = time.strftime("%Y-%m-%d")
gz_path = os.path.join(backup_dir, f"ttn-{stamp}.db.gz")
tmp_db = os.path.join(backup_dir, f".ttn-{stamp}.db.tmp")
tmp_gz = gz_path + ".tmp"

conn = sqlite3.connect("ttn.sqlite")
try:
    out = sqlite3.connect(tmp_db)
    try:
        conn.backup(out)
    finally:
        out.close()
    with open(tmp_db, "rb") as fin, \
            gzip.open(tmp_gz, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout, length=16 * 1024 * 1024)
finally:
    conn.close()
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
os.replace(tmp_gz, gz_path)

# prune to 14 newest (same-day rerun overwrites its own stamp first)
for old in sorted(glob.glob(os.path.join(backup_dir, "ttn-*.db.gz")))[:-14]:
    os.remove(old)
print(f"backup: {gz_path} ({os.path.getsize(gz_path) / 1e6:.0f} MB)")
PYEOF

# Re-attempt recently-marked-absent segments BEFORE update, so an episode
# scraped before the BBC populated its segments.json heals the next night
# (update alone never re-attempts) and the recovered rows are covered by
# update's warm. Small set (~32 episodes, <1 min).
uv run ttn_data.py segments --retry-absent

uv run ttn_data.py update

# Successor-refresh: rebuild successor.sqlite (derived, gitignored -- it only
# ever existed on the dev box, so a fresh build host has none) from the
# just-updated ttn.sqlite. The entity gate and successor site build consume it,
# so it
# must exist BEFORE the drift gate below. ORDER MATTERS: ttn2_ingest.build()
# DROPs the ledger table and does NOT re-import it; `ttn2_ledger.py import`
# restores the 4,535 decisions from the tracked ttn2_ledger.json (the
# decisions record); ttn2_match rebuilds events (DELETE+rebuild).
# work_entity/work_entity_key are NOT touched by ingest -- the entity builder
# before the site build reconciles by key against them. ~1-2 min on the build
# host; a failure aborts before deploy, same as every other stage.
uv run python ttn2_ingest.py
uv run python ttn2_ledger.py import
uv run python ttn2_match.py

# P4 phase-3 post-flip: materialize entities before the successor-side build.
uv run python ttn2_entities.py

# Read-only drift gate FIRST, right after warm has finished: catch identity
# orphans before the ~5-min site build rather than an hour late. Exits
# non-zero without touching the registry or site.sqlite.
CHECK_LOG=$(mktemp)
if ! uv run ttn_data.py site --check 2>"$CHECK_LOG"; then
    cat "$CHECK_LOG"
    # successor identity is not the legacy auto-remap view; manual batches
    # are the repair path, so never rewrite the frozen registry here.
    echo "=== successor site --check failed: manual remap required ==="
    rm -f "$CHECK_LOG"
    exit 1
fi
rm -f "$CHECK_LOG"

# The successor build uses a different identity keyspace; the legacy
# auto-remap helper is deliberately not safe under this gate. A drift failure
# aborts and requires a reviewed manual batch.
uv run ttn_data.py site --source successor

# The site build syncs the git-tracked slug registries; a new episode can
# mint new work/composer/artist slugs. Commit them back (named paths only)
# so the Pi stays in sync and tomorrow's --ff-only pull doesn't collide.
# A failed push (e.g. a race with a Pi-side push) is a warning, not an
# abort: the local commit keeps the tree clean and retries tomorrow.
if ! git diff --quiet -- ttn_site_registry.json ttn_site_artist_registry.json; then
    if [ "$DEPLOY" = 1 ]; then
        git add ttn_site_registry.json ttn_site_artist_registry.json
        git commit -m "Nightly registry sync ($(date +%F))"
        git push || echo "WARN: registry push failed; deploying anyway (push retries tomorrow)"
    else
        # Dev box: REPORT, never commit. A local commit here would never be
        # pushed, and would then collide with the build server's next nightly
        # sync on the --ff-only pull. Leave the diff in the tree for review.
        echo "=== registry changed (--no-deploy: NOT committed, review by hand) ==="
        git diff --stat -- ttn_site_registry.json ttn_site_artist_registry.json
    fi
fi

# Belt-and-braces artifact sanity on top of the render's own crawl gate.
test -s dist/index.html
test -s dist/sitemap.xml

if [ "$DEPLOY" = 1 ]; then
    rsync -az --delete dist/ "$TTN_DEPLOY_DEST"

    curl -sf -o /dev/null --max-time 30 https://notturnometer.com/
    # A degraded catalogue (render_site's search_docs=None path) 404s this
    # forever with set -e never firing -- every search box on the live site
    # fetches it, gets a 404, and silently hides itself. -I: headers only,
    # never pull the 5.4 MB body nightly.
    curl -sfI -o /dev/null --max-time 30 https://notturnometer.com/search-index.json
    echo "=== nightly ok $(_NOW)"
else
    # Local stand-ins for the two live checks: prove the render produced a
    # catalogue and a populated index rather than silently degrading.
    test -s dist/search-index.json
    echo "search-index.json: $(python3 -c "import json;print(len(json.load(open('dist/search-index.json'))))" 2>/dev/null || echo UNREADABLE) documents"
    echo "pages rendered: $(find dist -name index.html | wc -l | tr -d ' ')"
    echo "=== local nightly ok (NOT deployed) $(_NOW)"
fi
