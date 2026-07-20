#!/usr/bin/env bash
# ttn_nightly.sh -- the johnson nightly pipeline, run from cron:
#
#   pull -> segments --retry-absent -> update (scrape/segments/warm)
#        -> site (build + render + pagefind) -> registry commit+push
#        -> rsync deploy -> live check
#
# set -e means any failing stage aborts the run BEFORE the deploy, so a
# broken build never replaces the live site (a registry-drift failure after
# an unremapped alias edit lands here: the site just stays on yesterday's
# render until the remap is pushed). Logs: scratch/nightly/YYYY-MM-DD.log,
# pruned after 30 days. Designed for johnson (the build host); the Pi never
# runs this.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

# cron's PATH is bare. uv lives in ~/.local/bin; node/npx (for the pagefind
# post-pass) live under fnm's per-version install dir -- the `fnm` shell
# shim only exists in interactive sessions, so resolve the newest installed
# version directly and survive upgrades.
NODE_BIN=$(ls -d "$HOME"/.local/share/fnm/node-versions/*/installation/bin 2>/dev/null | sort -V | tail -1)
export PATH="$HOME/.local/bin${NODE_BIN:+:$NODE_BIN}:$PATH"

LOGDIR="scratch/nightly"
mkdir -p "$LOGDIR"
exec >>"$LOGDIR/$(date +%F).log" 2>&1
find "$LOGDIR" -name '*.log' -mtime +30 -delete
echo "=== nightly start $(date -Is)"

# Pick up anything pushed from the Pi (alias edits, template changes, ...).
git pull --ff-only

# Re-attempt recently-marked-absent segments BEFORE update, so an episode
# scraped before the BBC populated its segments.json heals the next night
# (update alone never re-attempts) and the recovered rows are covered by
# update's warm. Small set (~32 episodes, <1 min).
uv run ttn_data.py segments --retry-absent

uv run ttn_data.py update
uv run ttn_data.py site

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

rsync -az --delete dist/ notturnometer@opal10.opalstack.com:apps/notturnometer/

curl -sf -o /dev/null --max-time 30 https://notturnometer.com/
echo "=== nightly ok $(date -Is)"
