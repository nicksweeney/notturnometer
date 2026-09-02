#!/usr/bin/env bash
# ttn_nightly.sh -- the nightly pipeline, run from cron:
#
#   pull -> segments --retry-absent -> update (scrape/segments/warm)
#        -> site (build + render + search catalogue) -> registry commit+push
#        -> rsync deploy -> live check
#
# set -e means any failing stage aborts the run BEFORE the deploy, so a
# broken build never replaces the live site (a registry-drift failure after
# an unremapped alias edit lands here: the site just stays on yesterday's
# render until the remap is pushed). Logs: scratch/nightly/YYYY-MM-DD.log,
# pruned after 30 days. Designed for the build host; the Pi never
# runs this.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

# cron's PATH is bare. uv lives in ~/.local/bin.
export PATH="$HOME/.local/bin:$PATH"

LOGDIR="scratch/nightly"
mkdir -p "$LOGDIR"
exec >>"$LOGDIR/$(date +%F).log" 2>&1
find "$LOGDIR" -name '*.log' -mtime +30 -delete
echo "=== nightly start $(date -Is)"

# The deploy target (user@host:path) is NOT committed -- this is a public
# repo, and the rsync dest discloses the live-site account. It lives in an
# untracked deploy.env beside this script. Create it on the build host with:
#     echo 'TTN_DEPLOY_DEST=user@host:path/' > deploy.env
# Guarded early (before the ~hour build) so a missing dest fails fast and
# never after a full rebuild it can't ship.
[ -f deploy.env ] && . ./deploy.env
: "${TTN_DEPLOY_DEST:?deploy.env must set TTN_DEPLOY_DEST (rsync dest); refusing to deploy}"

# Pick up anything pushed from the Pi (alias edits, template changes, ...).
# SELF-REPLACE GUARD: bash reads this file incrementally from its own fd, so
# a pull that updates ttn_nightly.sh mid-run leaves the running bash holding
# a stale read offset into new bytes -- the remainder of the run can execute
# a corrupted splice. Detect a changed script and exec the new one from byte
# zero. The pull is the ONLY self-modifying step, and it sits before every
# heavy stage, so a restart re-runs nothing expensive (the pull is then a
# no-op; the log append at the top just continues).
_SELF="$(readlink -f "$0")"
_SELF_SUM_BEFORE="$(sha256sum "$_SELF")"
git pull --ff-only
if [ "$(sha256sum "$_SELF")" != "$_SELF_SUM_BEFORE" ]; then
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

# P4 phase-3 shadow window (2026-09-02): the flip waits for 5 consecutive
# green nights (scratch/shadow-green-count). The legacy build below is
# UNCHANGED -- the site stays on the legacy render; the successor build +
# parity + the class-based verdict run alongside (the mint gate defers
# uncorroborated new identities to the review queue; the anchor-consistency
# defense ignores mismatching anchors). Reverted at Task 6's flip.

# Read-only drift gate FIRST, right after warm has finished: catch identity
# orphans before the ~5-min site build rather than an hour late. Exits
# non-zero without touching the registry or site.sqlite.
CHECK_LOG=$(mktemp)
if ! uv run ttn_data.py site --check 2>"$CHECK_LOG"; then
    cat "$CHECK_LOG"
    echo "=== site --check failed: attempting auto-remap ==="
    if uv run ttn_auto_remap.py <"$CHECK_LOG"; then
        echo "=== auto-remap succeeded ==="
    else
        echo "=== auto-remap could not resolve all orphans ==="
        rm -f "$CHECK_LOG"
        exit 1
    fi
fi
rm -f "$CHECK_LOG"

# Site build may fail on registry drift (orphaned slugs from title-projection
# changes).  Auto-remap: find the same composer's works in the current corpus,
# score token overlap on the work key, remap if exactly one strong match.
# Retries once; unresolved orphans still abort the build.
SITE_LOG=$(mktemp)
if ! uv run ttn_data.py site 2>"$SITE_LOG"; then
    echo "--- site build stderr ---"
    cat "$SITE_LOG"
    echo "--- end site build stderr ---"
    echo "=== site build failed, attempting auto-remap ==="
    if uv run ttn_auto_remap.py <"$SITE_LOG"; then
        echo "=== auto-remap succeeded, retrying site build ==="
        uv run ttn_data.py site
    else
        echo "=== auto-remap could not resolve all orphans ==="
        rm -f "$SITE_LOG"
        exit 1
    fi
fi
rm -f "$SITE_LOG"

# P4 phase-3 shadow block: the successor build + parity + the class-based
# verdict + the entity builder. The parity exits 1 on unexpected diffs --
# EXPECTED during the window (the aggregate-ripple rows); the verdict below
# is the gate. A parity CRASH (no 'parity verdict:' line -- a build failure,
# not a diff verdict) aborts: the report would be stale and a stale verdict
# could count a broken night green.
PARITY_LOG=$(mktemp)
set +e
uv run python ttn2_site_parity.py --force 2>&1 | tee "$PARITY_LOG"
PARITY_RC=${PIPESTATUS[0]}
set -e
if ! grep -q "parity verdict:" "$PARITY_LOG"; then
    echo "=== parity build failed (rc=$PARITY_RC) -- aborting ==="
    rm -f "$PARITY_LOG"
    exit 1
fi
rm -f "$PARITY_LOG"

# The entity tables materialize nightly (append-only, idempotent -- the
# flip's registry sync anchors new slugs via the builder's ids).
uv run python ttn2_entities.py

# The class-based green check (maintainer ruling 2026-09-02): GREEN = no
# unexpected row OUTSIDE the aggregate-ripple class (known-parked OR
# ripple-shaped); RED = any identity-level diff. The counter gates the flip.
SHADOW_OUT=$(uv run python -c "
import ttn2_site_parity as SP
green, nu = SP.shadow_verdict('scratch/p4-site-parity.json',
                              'docs/plans/parked-aggregate-ripple.json')
print('GREEN' if green else 'RED')
for e in nu:
    print(e['table'] + ' ' + e['key'] + ' [' + e['side'] + ']')
")
SHADOW_VERDICT=$(echo "$SHADOW_OUT" | head -1)
if [ "$SHADOW_VERDICT" = "GREEN" ]; then
    COUNT_FILE="scratch/shadow-green-count"
    mkdir -p scratch
    N=0
    [ -f "$COUNT_FILE" ] && N=$(cat "$COUNT_FILE")
    N=$((N + 1))
    echo "$N" > "$COUNT_FILE"
    echo "=== SHADOW GREEN ($N/5) ==="
else
    echo "=== SHADOW RED: ==="
    echo "$SHADOW_OUT" | tail -n +2
    rm -f scratch/shadow-green-count
    echo "=== shadow counter reset (0/5) ==="
fi

# The site build syncs the git-tracked slug registries; a new episode can
# mint new work/composer/artist slugs. Commit them back (named paths only)
# so the Pi stays in sync and tomorrow's --ff-only pull doesn't collide.
# A failed push (e.g. a race with a Pi-side push) is a warning, not an
# abort: the local commit keeps the tree clean and retries tomorrow.
if ! git diff --quiet -- ttn_site_registry.json ttn_site_artist_registry.json; then
    git add ttn_site_registry.json ttn_site_artist_registry.json
    git commit -m "Nightly registry sync ($(date +%F))"
    git push || echo "WARN: registry push failed; deploying anyway (push retries tomorrow)"
fi

# Belt-and-braces artifact sanity on top of the render's own crawl gate.
test -s dist/index.html
test -s dist/sitemap.xml

rsync -az --delete dist/ "$TTN_DEPLOY_DEST"

curl -sf -o /dev/null --max-time 30 https://notturnometer.com/
# A degraded catalogue (render_site's search_docs=None path) 404s this
# forever with set -e never firing -- every search box on the live site
# fetches it, gets a 404, and silently hides itself. -I: headers only, never
# pull the 5.4 MB body nightly.
curl -sfI -o /dev/null --max-time 30 https://notturnometer.com/search-index.json
echo "=== nightly ok $(date -Is)"
