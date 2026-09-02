# P4 phase 3 — the flip (design)

Status: approved design, 2026-08-31. Implementation plan follows in
`docs/plans/` (tracked). Phase 2 record:
`docs/successor-events-phase1-record.md` + the SDD ledger. Framework:
`docs/successor-events-framework.md` §7.

## Context

Phase 2 landed the entity-anchored registry (additive `entity_id`; the
(ck, wk) strings as a derived cache; the sync gate on anchors + entities;
the evidence-heal machinery deleted) and cleared the 151-slug drift batch
through 10 maintainer-ratified stages + a corrective round, with the
airing-level verification method as the standard tool. The nightly hold is
active: scrape/segments/update keep the data current; the site render +
registry commit are paused until the flip. Final parity verdict: works
0-unexpected; 15 aggregate-ripple rows parked (the maintainer's ruling —
the flip dissolves the legacy view).

The phase-3 queue (12 items) decomposes: **core flip + defenses** (this
phase) and **post-flip hygiene** (phase 4): the tier-3 redirect queue
(~47+), the fold-ripple mirrors, the vacated-key mints cleanup, the
Atlanta-chorus performer-credit correction, the kyurkchiyski fold, the
composer entity table (if ever).

## Decisions (made interactively 2026-08-31)

1. **Scope**: core flip + defenses; the cleanup = phase 4, post-flip
   hygiene on the live successor.
2. **The entity-layer builder**: ledger-derived, id-frozen. Entities derive
   from the ledger resolution of the text obs (the `load_groups` rule — one
   entity per resolved (composer_key, work_key) group); ids assigned once
   and FROZEN (append-only: existing ids never renumber; rebuilds reconcile
   by key, not row order). Rejected: match-derived (two derivation paths;
   the ghost-key class lived at the match/mint boundary) and dropping
   entity ids (abandons the framework's design mid-flip).
3. **The freeze**: read-only. The legacy modules (ttn_analyze/ttn_aliases/
   ttn_project) take no code changes and no identity decisions (the alias
   folds move to the ledger exclusively); the parity gate keeps running
   (the legacy chain stays the reconciliation reference); the corpus
   ingestion continues unchanged (scrape/segments/reparse); the legacy CLI
   tools keep working read-only. Rejected: hard freeze (the parity gate's
   legacy reference dies) and no-freeze (the ghost-key class keeps a live
   path into the registry).
4. **The mint-time defense**: mint iff MBID-present on the identity's obs
   OR dual-lineage agrees (the identity derives in both the legacy chain's
   resolution and the successor's ledger resolution). A gated identity:
   DEFER to a review queue (printed in the nightly's sync report); the
   maintainer ratifies (the work-recordings panel as evidence); the slug
   mints after. Rejected: mint-unanchored (defeats the defense) and
   drop-until-corroborated (the bacewicz-class data-lag defers would hang).
5. **The flip shape**: B — shadow-verify. The builder + the defenses land
   and verify by gate; the nightly runs BOTH builds + the parity verdict
   for a 5-green-night shadow window (the legacy render holds); then one
   flip commit (the default change + the hold revert). Rejected:
   gate-verified (the first live run lands on the deployed site) and
   immediate (rejected by the phase-2 experience).

## Design

### 1. The entity-layer builder (`ttn2_entities.py`, new)

One derivation: the ledger resolution of the text obs → one entity per
resolved (composer_key, work_key) group; ids assigned once, then
**append-only frozen**.

- Derivation: the same rule `load_groups` uses (per-obs identity via the
  ledger + rec_meta) — one scan, one entity per group.
- Id freeze: the builder reads the existing `work_entity`/
  `work_entity_key` rows first; a group whose key already maps to an
  entity keeps that id (rebuilds reconcile BY KEY, never by row order);
  new groups append ids past the high-water mark. The phase-2
  renumbering breakage class dies at the root.
- Idempotent: a rebuild over identical input is a no-op (byte-stable
  tables). A rebuild after new airings only appends.
- Composer entities: **prohibited** (the phase-2 ruling stands — no
  composer entity table; `apply_anchor --composer` keeps its prohibition
  comment; the need defines the phase-4+ work).
- Verification: the rebuild-over-identical-input test (byte-stable ids);
  the append-only test (a new group appends, existing ids untouched);
  the count parity against `load_groups`.

### 2. The mint-time defense (the nightly's successor-side sync)

Mint iff **MBID present on the identity's obs OR dual-lineage agrees**.

- Dual-lineage: the identity derives in BOTH the legacy chain's resolution
  (ttn_analyze's chain, read-only, still the parity reference) AND the
  successor's ledger resolution. Both are computable over the same corpus
  post-freeze.
- A gated identity: no slug; printed in the nightly's sync report review
  queue (the slug, the registered keys, the evidence pointers). The
  maintainer ratifies (the work-recordings panel as evidence); the slug
  mints via the existing `--anchor-file` path.
- The ghost-key class (the dirty-window phantom: Martinů's H.289/H.305 on
  other composers' symphony records) blocks exactly here — a phantom
  derives in one lineage only (the frozen legacy chain's stale read vs the
  clean successor fetch), fails corroboration, defers.
- The MBID arm: an identity whose obs carry an MBID is corroborated
  without the dual-lineage check (the strong signal).

### 3. The anchor-consistency defense (at reanchor time)

Before the sync gate trusts an anchor: the anchor's `legacy_ck`/`legacy_wk`
must match the entry's stored strings. Mismatch → the anchor is ignored +
reported in the sync output (the repair-anchors pass fixes the table).
Two lines + a test. The weber/Huygens poison class (a stale anchor id
baked into a present entry migrates into the frozen git-tracked registry)
blocks here.

### 4. The flip mechanics

- `ttn_data.py site`'s default → `--source successor`; the legacy path
  stays as the explicit `--source legacy` (unfrozen but unsupported).
- The shadow window: the nightly builds BOTH (the legacy `site` + the
  successor `site2`), runs the parity verdict, prints it; the legacy
  render holds. **Green criterion: the unexpected set is exactly the
  parked aggregate-ripple snapshot (the 12 composers + 3 browse rows,
  recorded at the phase-2 close) — no NEW unexpected.** 5 consecutive
  green nights (the mint gate's first real runs, the ghost-key class
  exercised on live feeds) → the flip commit.
- The flip commit: the default change + the hold guard's `exit 0` deleted
  (the render + registry commit resume successor-side). The registry sync
  post-flip: successor-side, mint-gated (§2), entity-aware (the new slugs
  anchor at mint via the builder's ids).
- The nightly's runtime: roughly doubles for the shadow window
  (sequential builds — the Pi's RAM is per-process).

### 5. What does NOT happen in phase 3 (the phase-4 queue, recorded)

The tier-3 redirect queue (~47+), the fold-ripple mirrors, the vacated-key
mints cleanup, the Atlanta-chorus performer-credit correction, the
kyurkchiyski fold, the composer entity table. The `ttn_analyze` CLI keeps
working read-only.

### 6. Verification

- The builder: the id-freeze tests + the count parity + the idempotence.
- The defenses: the gate tests (the corroboration arms, the mismatch arm).
- The shadow window: the parity verdict green ×5 (the nightly's own log).
- The flip commit: the site renders successor-side, `site --check` green,
  the URL set unchanged (the flip changes the source, not the slugs).
- The parity gate keeps running post-flip (the legacy reference) — the
  read-only freeze's guarantee.

### 7. Sequencing (plan sketch)

1. The entity-layer builder (`ttn2_entities.py`) + tests.
2. The mint-time defense (the nightly's sync gate) + tests.
3. The anchor-consistency defense (the sync gate) + tests.
4. The shadow window wiring (the nightly's dual-build + the verdict).
5. The 5-green-night shadow run (the maintainer watches the nightly logs).
6. The flip commit (the default change + the hold revert) + the post-flip
   verification.
7. Docs (the framework doc phase state; CLAUDE.md).
