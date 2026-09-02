# P4 Phase 3 — The Flip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the site to the successor build safely: the entity-layer builder lands (the flip's prerequisite), the mint-time + anchor-consistency defenses gate the nightly's registry sync, a 5-green-night shadow window proves the successor build on live feeds, and one flip commit switches the default + reverts the nightly hold.

**Architecture:** `ttn2_entities.py` derives the entity layer from the ledger resolution of the text obs (one entity per resolved (composer_key, work_key) group; ids assigned once and FROZEN — append-only, rebuilds reconcile by key). The nightly's successor-side registry sync gains two defenses: the mint-time corroboration gate (mint iff MBID-present OR dual-lineage-agrees; gated identities defer to a printed review queue) and the anchor-consistency check (a mismatching anchor is ignored + reported). The shadow window runs both builds nightly with the parity verdict; the green criterion is the unexpected set exactly equal to the parked aggregate-ripple snapshot (12 composers + 3 browse). The flip commit changes the `--source` default and deletes the hold guard's `exit 0`.

**Tech Stack:** Python ≥ 3.12, uv, SQLite, pytest (`uv run python -m pytest` — bare `pytest` after `--with` fails to spawn on this box), bash (the nightly).

**Spec:** `docs/specs/2026-08-31-p4-phase3-flip-design.md` (approved).

## Global Constraints

- The registry file stays human-readable, atomic-dumped, and entity-anchored (the phase-2 semantics unchanged).
- The nightly hold stays ACTIVE until Task 6's flip commit — every stage before it must leave the hold intact (the site stays on the legacy render).
- The read-only freeze: ttn_analyze/ttn_aliases/ttn_project take no code changes in this plan; the legacy chain's resolution is the parity reference and the dual-lineage check's second lineage.
- The ledger is the decisions record: the mint gate defers, never auto-mints; the review queue is the human's.
- The composer entity stamping stays PROHIBITED (the phase-2 ruling; no composer entity table).
- The parity gate's green criterion: the unexpected set exactly equals the parked aggregate-ripple snapshot (12 composers + 3 browse, recorded at the phase-2 close) — no NEW unexpected.
- Tests: `uv run python -m pytest` (the working form); never bare `python`/`pip`.
- The implementer CANNOT run `git commit` on agent dispatches — the controller commits.

---

### Task 1: The entity-layer builder (`ttn2_entities.py`)

**Files:**
- Create: `ttn2_entities.py`
- Test: `test_ttn2.py` (append)

**Interfaces:**
- Consumes: `ttn2_query.load_groups(src, dst)` → `{(ck, wk): {"airings": N, "display": (cm, tt), ...}}` (the ledger resolution of the text obs — one entity per group); successor.sqlite's existing `work_entity(id, name)` + `work_entity_key(composer_key, work_key, work_entity_id)` rows (the id high-water mark + the reconcile-by-key source).
- Produces: `build_entities(src="ttn.sqlite", dst="successor.sqlite", groups=None)` → rebuilds `work_entity` + `work_entity_key` idempotently: existing (ck, wk) keys keep their entity ids (reconcile BY KEY); new groups append ids past the high-water mark (sorted by key for determinism); the entity `name` = the group's display (the corpus-majority (cm, tt)). Disappeared groups (keys in the tables but absent from the current groups): left in place (append-only — a rebuild never deletes; the ratification owns removals). Returns (n_entities, n_keys, n_appended).

- [ ] **Step 1: Write the failing tests**

```python
def test_build_entities_freezes_existing_ids(tmp_path):
    """Existing (ck, wk) keys keep their entity ids across a rebuild;
    new groups append past the high-water mark."""
    # fixture: successor.sqlite with work_entity (1, 'X') + work_entity_key
    # ('a', 'w', 1); load_groups monkeypatched to return TWO groups:
    # ('a','w') [existing] + ('b','v') [new].
    # build_entities(dst) -> the ('a','w') key KEEPS entity 1; the new group
    # appends entity 2; n_appended == 1.


def test_build_entities_rebuild_is_byte_stable(tmp_path):
    """A rebuild over identical input is a no-op: the tables' rows are
    byte-identical (sorted comparison) and a re-run appends 0."""
    # build twice over the same groups; assert the second run's
    # n_appended == 0 and the SELECTed rows compare equal.


def test_build_entities_disappeared_groups_survive(tmp_path):
    """A key in the tables but absent from the current groups stays
    (append-only — the ratification owns removals)."""


def test_build_entities_count_parity_matches_load_groups(tmp_path):
    """len(work_entity_key rows) == len(load_groups()) after a build."""
```

(Flesh the fixtures per the established synthetic-successor patterns in test_ttn2.py; `load_groups` is monkeypatched for determinism except the parity test, which runs the real one over the fixture's tiny corpus.)

- [ ] **Step 2: Run to verify FAIL** (`No module named 'ttn2_entities'`).
- [ ] **Step 3: Implement** — `build_entities` reads the existing tables (the high-water mark + the key→id map), calls `load_groups` (injected), sorts the new group keys, appends, rebuilds both tables (DELETE + re-INSERT inside one transaction; the entity names = the groups' displays). CLI: `uv run python ttn2_entities.py` runs the build against the real DBs + prints the counts.
- [ ] **Step 4: Verify PASS** + full suite.
- [ ] **Step 5: Commit** — `ttn2: the entity-layer builder (ledger-derived, id-frozen, append-only)`.

---

### Task 2: The mint-time defense (the sync gate's corroboration arm)

**Files:**
- Modify: `ttn_site.py` (`sync_registry` ~2846: the new-identity mint loop gains the gate; a `mint_gate=None` parameter)
- Modify: `ttn_nightly.sh` (the successor-side sync passes the real gate — post-shadow-window wiring, staged with Task 4; this task lands the parameter + the default-off wiring)
- Test: `test_ttn_site.py` (append)

**Interfaces:**
- Consumes: `sync_registry`'s new-identity mint loop (the `new_identities` iteration in `_sync_namespace` — the mint happens caller-side via `record_key`; the gate rides the CALLER: `_run_build`'s successor branch filters the successor-side derived entries' NEW identities through the corroboration callable before `sync_registry` sees them — the gated identities are REMOVED from the derived entries and reported).
- Produces: `mint_gate(ck, wk) -> bool` (True = corroborated, mint; False = defer); `ttn2_query.mint_gate_candidate(src, dst, ck, wk) -> bool` — the corroboration check: the MBID arm (any obs of the identity carries composer_mbid) OR the dual-lineage arm (the legacy chain's derived key-set contains the identity — a helper computing the legacy derived key-set once per run, cached). The gated identities: `_run_build`'s report gains `mint_deferred: [(ck, wk, slug)]`; the nightly's sync report prints them (the review queue).

- [ ] **Step 1: Write the failing tests**

```python
def test_mint_gate_candidate_mbid_arm(tmp_path):
    """An identity whose obs carry composer_mbid corroborates via the MBID
    arm (no dual-lineage check needed)."""

def test_mint_gate_candidate_dual_lineage_arm(tmp_path):
    """An identity absent from the legacy derived key-set and MBID-less is
    gated (False); present in both chains -> True."""

def test_run_build_successor_mint_gate_defers(tmp_path, monkeypatch):
    """A gated identity in the successor-side derived entries is removed
    pre-sync and reported in mint_deferred; the registry never sees it."""
```

(Fixtures: the synthetic successor corpus patterns; the legacy derived key-set monkeypatched or computed over the fixture corpus.)

- [ ] **Step 2: Verify FAIL.**
- [ ] **Step 3: Implement** — `ttn2_query.mint_gate_candidate` (the MBID query + the legacy key-set helper, cached per call); `_run_build`'s successor branch: the derived entries' NEW identities (absent from the registry) pass through `mint_gate_candidate` before `sync_registry`; the gated ones are pulled from the entries + reported. `sync_registry` itself is UNTOUCHED (the gate rides the caller — the pre-flip tests keep mint-all semantics via the default None).
- [ ] **Step 4: Verify PASS** + full suite + the real-corpus probe: the successor-side `_run_build` with the gate live — report how many of the current would-be-new mints gate (expect ~0: the phase-2 ratified identities are all dual-lineage-stable now; the gate's first real test is the post-flip nights).
- [ ] **Step 5: Commit** — `registry: the mint-time defense — corroboration-gated mints (MBID or dual-lineage), gated identities defer to the review queue`.

---

### Task 3: The anchor-consistency defense

**Files:**
- Modify: `ttn_site.py` (the entity pass ~2918-2947: the anchor trust check)
- Test: `test_ttn_site.py` (append)

**Interfaces:**
- Consumes: the sync's entity pass (the anchor trust: `anchors.get(slug)`).
- Produces: the anchor-consistency check — the anchor's `legacy_ck`/`legacy_wk` vs the entry's stored `composer_key`/`work_key`: mismatch → the anchor is IGNORED (the entry drifts per the unanchored/stale path) + the sync report gains `anchor_mismatch: [(slug, anchor_keys, stored_keys)]`. The repair-anchors pass reconciles the table.

- [ ] **Step 1: Failing test** — an orphan whose anchor's legacy keys DON'T match its stored strings: the anchor is ignored (the entry drifts unanchored) + the report carries anchor_mismatch. (The weber/Huygens class: the stale anchor id + the drifted strings.)
- [ ] **Step 2: Verify FAIL.**
- [ ] **Step 3: Implement** — the entity pass's anchor read gains the string check; the mismatch arm skips the anchor (the entry drifts) + appends to the report list; the pass's docstring names the weber/Huygens class.
- [ ] **Step 4: Verify PASS** + full suite.
- [ ] **Step 5: Commit** — `registry: the anchor-consistency defense — mismatching anchors ignored + reported (the weber/Huygens poison class)`.

---

### Task 4: The shadow-window wiring (the nightly's dual-build + the verdict)

**Files:**
- Modify: `ttn_nightly.sh` (the hold guard's `exit 0` → the dual-build block: the legacy site build (UNCHANGED behavior — the render holds) + the successor site2 build + the parity verdict + the green check)
- Modify: `ttn_site.py` OR a small `ttn2_parity_nightly.py` if the green check needs a comparator (the unexpected set vs the parked snapshot)
- Test: the parity comparator's test (if the comparator is a function); the nightly script itself is shell-tested manually.

**Interfaces:**
- Consumes: the parity gate (`ttn2_site_parity.py --force` — its report JSON's unexpected list); the parked snapshot (the phase-2 close's 15 rows, recorded at `scratch/p4-site-parity.json` — the comparator embeds the parked set as a literal, versioned in the repo at `docs/plans/parked-aggregate-ripple.json` so the nightly's check is self-contained).
- Produces: the nightly's shadow block — after `update`: (1) the legacy `site` build (UNCHANGED — the render holds), (2) `ttn2_site_parity.py --force` (site2 rebuilt + the diff), (3) the green check: the report JSON's unexpected set == the parked set → log `SHADOW GREEN (n/5)` + increment a counter file (`scratch/shadow-green-count`); a new unexpected → log `SHADOW RED: <diffs>` + reset the counter. The flip commit (Task 6) lands after the counter hits 5.

- [ ] **Step 1: The parked snapshot file** — extract the phase-2 close's 15 unexpected rows from `scratch/p4-site-parity.json` into `docs/plans/parked-aggregate-ripple.json` (tracked; the nightly's comparator reads it).
- [ ] **Step 2: The comparator** — a small function (in ttn2_site_parity.py: `shadow_verdict(report_path, parked_path) -> (green: bool, new_unexpected: list)`): the report JSON's unexpected set vs the parked set — set-equality on the (table, key) pairs. Test-pinned (green, new-diff, missing-diff arms).
- [ ] **Step 3: The nightly wiring** — the hold's `exit 0` replaced by the shadow block: the legacy build (unchanged), the successor build + the parity + the verdict + the counter. The hold's comment documents the window (reverted at Task 6's flip).
- [ ] **Step 4: Verify** — run the nightly's shadow block manually once (the parity over the current state: expect GREEN — the unexpected set == the parked 15); the counter increments; the full suite green.
- [ ] **Step 5: Commit** — `nightly: the shadow window — dual-build + the parity verdict + the green counter (the flip waits for 5 green nights)`.

---

### Task 5: The shadow run (OPERATIONAL — 5 nights, no code)

**Procedure** (the maintainer + the controller):
- [ ] Each morning after the nightly: check `scratch/shadow-green-count` (johnson-side: the count lives on the nightly host — the nightly logs carry the verdict; the check is the log grep).
- [ ] A RED night: investigate the new unexpected diffs (the samples in the nightly log) before proceeding — a red night pauses the window (the counter resets).
- [ ] 5 consecutive green nights → Task 6's flip commit is authorized.

---

### Task 6: The flip commit + the post-flip verification

**Files:**
- Modify: `ttn_nightly.sh` (the shadow block → the successor-side render + the registry sync; the legacy build dropped)
- Modify: `ttn_data.py` OR `ttn_site.py` (the `--source` default → `successor`; the legacy stays as the explicit flag)
- Modify: `docs/successor-events-framework.md` (the phase state) + CLAUDE.md (the nightly's shape + the hold revert)

**Interfaces:**
- Consumes: Tasks 1-4 (the builder run johnson-side BEFORE the flip: the entity tables materialized on the nightly host — the builder is in the nightly's shadow block too, appending any new groups nightly).
- Produces: the site renders successor-side; the registry sync mints gate-deferred; the legacy render drops.

- [ ] **Step 1: The builder in the nightly's shadow block** — `uv run python ttn2_entities.py` after the parity check (the entity tables materialize nightly; the append-only semantics make it idempotent). Verify johnson-side: the builder's first run on the nightly host (the entity tables from scratch — the count parity vs the groups).
- [ ] **Step 2: The flip commit** — the hold block → the successor-side steps (the site build successor-source + the render from site2 + the registry sync successor-side with the mint gate); the legacy build dropped; the default flipped. Verify the render path successor-side LOCALLY first (a manual render from site2 → a dist spot-check: the URL set unchanged).
- [ ] **Step 3: Push + the first post-flip nightly** — the render + the registry commit resume successor-side; the live curl check; the mint gate's first live defers (if any) print in the sync report.
- [ ] **Step 4: The post-flip verification** — the URL set unchanged (the registered slugs identical — the flip changes the source, not the slugs); `site --check` green; the suite green; the parity's works table 0-unexpected.
- [ ] **Step 5: Commit + push** — `nightly: the flip — the site renders successor-side; the hold reverted`.

---

### Task 7: Docs

- [ ] The framework doc §7: the phase-3 state (the builder landed, the defenses live, the shadow window green ×5, the flip landed; phase 4 = the cleanup queue). CLAUDE.md: the nightly's shape post-flip + the entity builder.
- [ ] Commit: `docs: P4 phase 3 landed — the flip`.

---

### Task 8 (phase 4 seed): the cleanup queue handoff

- [ ] Record the phase-4 queue in the framework doc's phase-4 bullet: the tier-3 redirect queue (~47+), the fold-ripple mirrors, the vacated-key mints cleanup, the Atlanta-chorus performer-credit correction, the kyurkchiyski fold, the composer entity table (if ever).
- [ ] Commit with Task 7.

---

## Verification (whole plan)

1. The full suite green at every task boundary.
2. The shadow window: 5 consecutive green nights (the parked-15 criterion).
3. The flip: the site renders successor-side, the URL set unchanged, `site --check` green.
4. The parity gate post-flip: the works table 0-unexpected (the legacy reference read-only).
