#!/usr/bin/env bash
# ttn_local.sh -- the dev-box entry point for the nightly pipeline.
#
# Runs the SAME pipeline as the build server's cron job (ttn_nightly.sh) and
# stops short of shipping: no deploy.env needed, no rsync to a web host, no
# live curl, and the registry diff is reported rather than committed.
#
# Why a wrapper rather than a copy: ttn_nightly.sh is the one definition of
# the pipeline. A copied "local variant" drifts from the build server's the
# moment either side is edited, and a dev box validating a stale pipeline is
# worse than none. Every stage -- backup, segments retry, update, the
# successor-refresh chain, the drift gate, the site build and render -- runs
# identically; only the tail differs.
#
#   ./ttn_local.sh              # full pipeline, local only
#   ./ttn_local.sh --dry-run    # prints the plan (scraper's own estimate gate)
#
# Logs land in scratch/nightly/YYYY-MM-DD.log, same as the cron run. Note the
# build is heavy: ~5 min update, ~1-2 min successor refresh, ~5 min site build,
# and the render streams ~53k pages. Run it when you intend to wait.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")"
exec bash ./ttn_nightly.sh --no-deploy "$@"
