# Post-flip curation & ops playbook

The working procedures for identity-touching curation and johnson-side
landings, post phase-3 flip (2026-09-08). Grounded in the recorded
applications: the Four Last Songs fold (10 rows), the Bella folds (3), the
Strauss batch (28), the Krönelein fold (1), the Flecha recording overrides,
the Matheo-Flecha parser fix. The phase-3 record
(`docs/successor-events-phase3-record.md`) carries the narrative; this doc is
the operational recipe.

## 1. The fold procedure (work/composer curation)

The unit of work: a maintainer-ratified set of composer-scoped ledger rows
that merge fragmented spellings onto a canonical identity.

1. **Measure first.** `ttn2_query.load_groups()` over the current corpus:
   the groups per family, their airings, their registered slugs
   (`ttn_site_registry.json`). The canonical = the most-carried spelling,
   opus-anchored where present. If the canonical is ambiguous — SKIP and
   ask; never guess (the Krönelein precedent).
2. **The ledger rows.** Append to the tracked `ttn2_ledger.json` (ids past
   the max), then re-import to the store
   (`uv run python ttn2_ledger.py import` — the store reads the tracked JSON,
   not vice versa):
   - work:  `kind=work_alias, scope="<composer_key>", method="curation-scoped",
     variant_key=<fragment's canonical_key>, target=<canonical display>,
     target_key=<canonical key>`
   - composer: `kind=composer_alias, scope="global", method="composer-fold"`
   - evidence: the maintainer verification + date. Recording-PID pins are
     the strongest class; title/repertoire evidence alone flags a caveat.
   - Pre-checks: the target derives; no dead rows (a variant the canonical
     key already covers naturally — check `canonical_key`'s trailing-paren
     drop before adding a fold); the dedup guard (kind, scope, variant_key).
3. **The entity builder.** `uv run python ttn2_entities.py` — the fragment
   keys leave `work_entity_key`; the entities stay (append-only).
4. **The one-group verification.** `load_groups()`: ONE group per work under
   the canonical key; the fragment keys absent; the airings = the sum.
5. **The remap batch.** The orphaned slugs (their keys folded away) →
   `--remap-file` (works) / `--composer --remap-file` (composers), redirects
   to the survivor, **never --retire** when the identity merges. Dry-run →
   apply. The admin path (load + apply + dump) does NOT run the build — the
   unrelated drift artifacts don't block it.
6. **The suite.** `uv run python -m pytest -q` (~2,715 tests, ~8-12 min).

Recording-level composer corrections (the segment metadata itself wrong —
e.g. the feed crediting the singer as composer, or inconsistent per-recording
spellings) are NOT ledger rows: they are `RECORDING_COMPOSER_OVERRIDES` in
`ttn_segment_meta.py` (recording_pid → composer; zero blast radius — a
recording maps to one work). The per-track composer on episode pages renders
`rec_meta` verbatim, so the override is the only thing that fixes the display.

## 2. The johnson landing recipe (parser/identity fixes)

The nightly pipeline: pull → backup → segments --retry-absent → update →
successor-refresh (ingest → ledger import → match) → entity builder → drift
gate → successor build → render → registry commit → rsync deploy → curls.

**Trap 1 — the nightly has NO reparse stage.** `update`'s scrape skips cached
episodes; stored `raw_json` is never re-derived automatically. A parser fix
is invisible on johnson until a manual `ttn_data.py rebuild` (the reparse +
the warm) runs there. The reparse `--dry-run` first; the delta must be the
predicted class only.

**Trap 2 — the drift batch must exist before the identity change lands.**
An identity re-key orphans the registered slugs minted under the old key;
the drift gate stalls the nightly (abort-before-deploy; auto-remap is
DELETED — the legacy-view mismatch). Build the `--remap-file` from the
registry's affected slugs BEFORE pushing the change, ship it to johnson
(scratch/ is gitignored — heredoc-write it), apply, then the nightly runs
clean.

**Trap 3 — the settle guard.** The scrape AND the segments skip episodes
whose broadcast end is <1h past; a manual early run cannot pull an
in-progress night (it self-heals at the next scheduled run). `--pids`
bypasses for deliberate heals.

**The manual chain** (when a fix must land between nightlies, as pi on
johnson):

```
git pull --ff-only
uv run ttn_data.py rebuild            # only for parser fixes
uv run python ttn2_ingest.py && \
uv run python ttn2_ledger.py import && \
uv run python ttn2_match.py           # the successor-refresh
uv run python ttn2_entities.py
uv run ttn_data.py site --check       # the drift gate; apply the remap batch if needed
bash ttn_nightly.sh                   # the idempotent wrapper: build + render + deploy + curls
```

Every stage aborts on failure (set -e) BEFORE the deploy — a stalled run
leaves the site on the prior render, never a broken one.

**Timing:** don't push master or run manual builds in the ~03:15-03:45 ET
window (the nightly ships master; the pull/registry-commit race). The manual
runs are safe any other time — the pipeline is idempotent.

## 3. The johnson diagnostics recipe

- **ssh as `pi@johnson.local`** (key-based). The default user (nsweeney)
  hits the permission wall: `ttn.sqlite` isn't world-readable and the WAL
  side-files need directory write access.
- **Remote python without quote hell**: feed a heredoc to the remote shell —
  `ssh pi@johnson.local 'cd /home/pi/notturnometer && ~/.local/bin/uv run python -' <<'EOF' ... EOF`
- **The batch files don't ship**: `scratch/` is gitignored — heredoc-write
  any remap/retire file to the remote scratch before applying it there.
- **The authoritative record**: `scratch/nightly/YYYY-MM-DD.log` (30-day
  prune). An ssh'd long command may return empty output — read the log, not
  the pipe.
- **uv's path**: `/home/pi/.local/bin/uv` for non-login shells; the nightly
  resolves uv itself.
