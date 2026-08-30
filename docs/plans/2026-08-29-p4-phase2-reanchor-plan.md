# P4 Phase 2 — Registry Re-anchor + Drift Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-anchor the slug registry to entity IDs (additive `entity_id`, derived string cache) and clear the 151-slug string-key drift via three maintainer-ratified batches — preparing phase 3 (default flip + legacy freeze).

**Architecture:** The ledger's anchor table (`ttn2_ledger.json` `anchor` key, 20,044 slugs) becomes the slug→entity authority; registry entries gain an optional `entity_id` and their (composer_key, work_key) strings become a derived cache refreshed from the anchor entity's dominant member key at sync time. `sync_registry`'s gate re-keys on entities (anchor exists + entity resolves via `work_entity_key` member rows); string drift downgrades to informational; the evidence-heal machinery is deleted. The drift batch is a new `ttn2_query drift-batch` generator emitting evidence-backed ratification batches consumed by the existing registry CLI patterns.

**Tech Stack:** Python ≥ 3.12, uv, SQLite, pytest (`uv run --with pytest python -m pytest` — note: bare `pytest` after `--with` fails to spawn on this box).

**Spec:** `docs/specs/2026-08-29-p4-phase2-reanchor-design.md` (approved).

## Global Constraints

- The legacy site build path stays the default; the parity gate (`ttn2_site_parity.py`) stays green throughout (it reads successor groups, not the registry).
- The registry file stays human-readable and atomic-dumped (`dump_registry`'s pid-unique tmp + `os.replace`, sorted keys, indent=2 — unchanged).
- `entity_id` is OPTIONAL on load everywhere (the `.get` discipline — a partial edit must never wipe other entries' anchors, mirroring the `retired` precedent).
- Corrupt registry / corrupt ledger JSON = hard error (unchanged).
- No successor.sqlite schema changes; no `ttn_nightly.sh` changes (phase 3).
- Human-ratify-not-auto: no entry gains `entity_id` without a ratified batch.
- Tests: `uv run --with pytest python -m pytest` (the working form on this box); never bare `python`/`pip`.
- If any workspace cleanup happens during this plan, the `archiving-process-narratives` skill applies (archive ledgers/reports before deletion).

---

### Task 1: Registry schema — optional `entity_id` on entries

**Files:**
- Modify: `ttn_site.py` (`load_registry` ~2684: per-entry shape check)
- Test: `test_ttn_site.py` (append)

**Interfaces:**
- Produces: registry entries optionally carrying `"entity_id": int`. `load_registry` validates: if an entry dict has `entity_id`, it must be an int (else ValueError naming the slug). No other consumer changes yet.

- [ ] **Step 1: Write the failing tests**

```python
def test_load_registry_accepts_entity_id(tmp_path):
    reg = {"version": 1,
           "works": {"ravel:bolero": {"composer_key": "maurice ravel",
                                      "work_key": "bolero",
                                      "published": "2026-01-01",
                                      "entity_id": 123}},
           "composers": {}, "redirects": {"works": {}, "composers": {}}}
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(reg))
    loaded = ttn_site.load_registry(str(p))
    assert loaded["works"]["ravel:bolero"]["entity_id"] == 123


def test_load_registry_rejects_non_int_entity_id(tmp_path):
    reg = {"version": 1,
           "works": {"ravel:bolero": {"composer_key": "maurice ravel",
                                      "work_key": "bolero",
                                      "published": "2026-01-01",
                                      "entity_id": "123"}},
           "composers": {}, "redirects": {"works": {}, "composers": {}}}
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(reg))
    with pytest.raises(ValueError, match="entity_id"):
        ttn_site.load_registry(str(p))


def test_dump_load_roundtrip_preserves_entity_id(tmp_path):
    reg = ttn_site._empty_registry()
    reg["works"]["x:y"] = {"composer_key": "x", "work_key": "y",
                           "published": "2026-01-01", "entity_id": 7}
    p = str(tmp_path / "reg.json")
    ttn_site.dump_registry(reg, p)
    assert ttn_site.load_registry(p)["works"]["x:y"]["entity_id"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest python -m pytest test_ttn_site.py -k entity_id -v`
Expected: the round-trip passes (dump/load are JSON-generic) but the shape-check tests fail (no validation exists).

- [ ] **Step 3: Implement**

In `load_registry`, after the existing top-level shape checks, add a per-entry walk:

```python
    for ns in ("works", "composers"):
        for slug, entry in data[ns].items():
            if "entity_id" in entry and not isinstance(entry["entity_id"], int):
                raise ValueError(
                    f"{path}: {ns}/{slug}: entity_id must be an int")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest python -m pytest test_ttn_site.py -v`
Expected: all green (the full registry suite included — the walk is additive).

- [ ] **Step 5: Commit**

```bash
git add ttn_site.py test_ttn_site.py
git commit -m "registry: optional entity_id on entries (validated int)"
```

---

### Task 2: sync_registry entity gate + derived refresh + evidence-heal deletion

**Files:**
- Modify: `ttn2_ledger.py` (add `load_anchors(json_path="ttn2_ledger.json")`)
- Modify: `ttn_site.py` (`sync_registry` ~2846: gate rewrite; delete the evidence-heal pre-pass 2907-2953 and the `evidence`/`current_pids` parameters; `_run_build`/`_run_check` call sites drop the evidence arguments)
- Test: `test_ttn_site.py` (append), `test_ttn2.py` (load_anchors test)

**Interfaces:**
- Consumes: `ttn2_ledger.load_anchors()` → `{slug: {"work_entity_id": int, "legacy_ck": str, "legacy_wk": str}}` (reads the tracked JSON's `anchor` key); an `entity_view` dict `{entity_id: (dominant_ck, dominant_wk)}` supplied by the caller.
- Produces: `sync_registry(registry, work_entries, composer_entries, today, entity_view=None, anchors=None)` → `(new_registry, report)` where report gains `"reanchored": [(slug, old_ck, old_wk, new_ck, new_wk)]` and loses `"rekeyed"`. An orphaned entry WITH `entity_id` resolving in `entity_view` is refreshed (not an orphan); an orphaned entry without `entity_id`, or whose entity is absent from `entity_view`, remains an orphan (drift error). Also `ttn2_query.load_entity_view(dst="successor.sqlite", groups=None)` → `{entity_id: (dominant_ck, dominant_wk)}` (dominant member = highest group airings, ties lexicographic).

- [ ] **Step 1: Write the failing tests**

```python
def _reg_with(slug, ck, wk, entity_id=None):
    entry = {"composer_key": ck, "work_key": wk, "published": "2026-01-01"}
    if entity_id is not None:
        entry["entity_id"] = entity_id
    return {"version": 1,
            "works": {slug: entry},
            "composers": {},
            "redirects": {"works": {}, "composers": {}},
            "retired": {"works": {}, "composers": {}}}


def test_sync_registry_reanchors_anchored_orphan():
    """An orphan whose entry carries a resolving entity_id is refreshed from
    the entity's dominant member key — informational, not a drift error."""
    reg = _reg_with("anon:old-keys", "anonymous", "old stale key", entity_id=5)
    entity_view = {5: ("anonymous", "fresh resolved key")}
    new, report = ttn_site.sync_registry(reg, [], [], "2026-08-29",
                                         entity_view=entity_view, anchors={})
    e = new["works"]["anon:old-keys"]
    assert (e["composer_key"], e["work_key"]) == ("anonymous", "fresh resolved key")
    assert ("anon:old-keys", "anonymous", "old stale key",
            "anonymous", "fresh resolved key") in report["reanchored"]


def test_sync_registry_unanchored_orphan_still_drifts():
    reg = _reg_with("anon:old-keys", "anonymous", "old stale key")
    with pytest.raises(ttn_site.RegistryDriftError):
        ttn_site.sync_registry(reg, [], [], "2026-08-29",
                               entity_view={5: ("a", "b")}, anchors={})


def test_sync_registry_stale_entity_drifts():
    """entity_id present but the entity has no member keys -> drift error."""
    reg = _reg_with("anon:old-keys", "anonymous", "old stale key", entity_id=9)
    with pytest.raises(ttn_site.RegistryDriftError):
        ttn_site.sync_registry(reg, [], [], "2026-08-29",
                               entity_view={5: ("a", "b")}, anchors={})


def test_sync_registry_anchored_present_identity_gets_entity_id():
    """A present identity whose entry lacks entity_id but has an anchor is
    annotated (informational) — the anchor pass, not the drift gate."""
    reg = _reg_with("ravel:bolero", "maurice ravel", "bolero")
    anchors = {"ravel:bolero": {"work_entity_id": 11, "legacy_ck": "maurice ravel",
                                "legacy_wk": "bolero"}}
    entity_view = {11: ("maurice ravel", "bolero")}
    new, report = ttn_site.sync_registry(reg, [], [], "2026-08-29",
                                         entity_view=entity_view, anchors=anchors)
    assert new["works"]["ravel:bolero"]["entity_id"] == 11
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest python -m pytest test_ttn_site.py -k "reanchor or unanchored_orphan or stale_entity or anchored_present" -v`
Expected: FAIL — `sync_registry() got an unexpected keyword argument 'entity_view'`.

- [ ] **Step 3: Implement**

`ttn2_ledger.py` — the anchor accessor (reads the tracked JSON; the decisions record, not successor.sqlite):

```python
def load_anchors(path="ttn2_ledger.json"):
    """{slug: {work_entity_id, legacy_ck, legacy_wk}} from the tracked
    export's anchor key. Corrupt/missing = the caller's hard-error path."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return {a["slug"]: a for a in doc.get("anchor", [])}
```

`ttn_site.py` — `sync_registry` rewrite (signature: `evidence=None, current_pids=None` → `entity_view=None, anchors=None`):

1. Delete the evidence-heal pre-pass (the block from `# Evidence pre-pass:` through `work_orphans.remove(slug)` — ttn_site.py:2907-2953) and the `rekeyed` report key.
2. After the two `_sync_namespace` calls, insert the entity pass:

```python
    reanchored = []
    unanchored = []
    for ns, new_entries, orphans in (("works", new_works, work_orphans),
                                     ("composers", new_composers,
                                      composer_orphans)):
        for slug in sorted(orphans):
            entry = new_entries[slug]
            eid = entry.get("entity_id")
            if eid is None:
                eid = (anchors or {}).get(slug, {}).get("work_entity_id")
            if eid is None:
                continue                      # stays an orphan -> drift error
            view = (entity_view or {}).get(eid)
            if view is None:
                continue                      # stale anchor -> drift error
            old_ck, old_wk = entry["composer_key"], entry["work_key"]
            new_ck, new_wk = view
            entry["composer_key"], entry["work_key"] = new_ck, new_wk
            entry["entity_id"] = eid
            reanchored.append((slug, old_ck, old_wk, new_ck, new_wk))
            orphans.remove(slug)
```

3. The drift error message gains the unanchored/stale distinction (count only — the sorted slug lists stay).
4. The report: `"reanchored": reanchored` replaces `"rekeyed": rekeyed`.
5. Present-identity annotation: after the entity pass, annotate any registered entry whose slug has an anchor and whose anchor entity resolves (the entry is present, not an orphan — it just predates the anchor):

```python
    for slug, anchor in (anchors or {}).items():
        for ns_entries in (new_works, new_composers):
            entry = ns_entries.get(slug)
            if (entry is not None and "entity_id" not in entry
                    and anchor["work_entity_id"] in (entity_view or {})):
                entry["entity_id"] = anchor["work_entity_id"]
```

(The predicate is exactly: slug anchored AND the anchor's entity resolves in the entity view. Never touch entries whose entity does not resolve.)

6. Call sites: `_run_build` and `_run_check` drop `evidence=ttn_evidence.load_evidence(), current_pids=pids_by_identity` and gain `entity_view=ttn2_query.load_entity_view(), anchors=ttn2_ledger.load_anchors()` (lazy imports inside the function). `load_entity_view(dst="successor.sqlite", groups=None)` is implemented IN THIS TASK (it is hermetically testable with an injected groups dict — Task 3's generator reuses it): load `work_entity_key` rows from successor.sqlite, join against the groups' airings (groups loaded once via `ttn2_query.load_groups` when not injected), dominant member = highest airings, ties lexicographic. The `ttn_evidence` import and the evidence write block in `_run_build` (post-sync `write_evidence`) are DELETED with the machinery.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest python -m pytest test_ttn_site.py test_ttn2.py -v` then the full suite.
Expected: all green; the pre-existing evidence-heal tests (if any pin `rekeyed`) are UPDATED to the reanchor semantics — a pinned test that contradicts the approved design is amended, with the amendment noted in the report.

- [ ] **Step 5: Commit**

```bash
git add ttn_site.py ttn2_ledger.py test_ttn_site.py test_ttn2.py
git commit -m "registry: sync_registry entity gate + derived refresh; evidence-heal deleted"
```

---

### Task 3: `load_entity_view` + the drift-batch generator

**Files:**
- Modify: `ttn2_query.py` (add `load_entity_view`, `cmd_drift_batch`, subcommand wiring)
- Test: `test_ttn2.py` or `test_ttn2_site.py` (append)

**Interfaces:**
- Consumes: `load_entity_view` + `load_groups` from Task 2 (dominant-member resolution), `ttn2_ledger.load_anchors`, `ttn_site.load_registry`.
- Produces:
  - `ttn2_query drift-batch [--registry ttn_site_registry.json] [--out-dir DIR]` → writes `drift-batch-1-mechanical.txt`, `drift-batch-2-review.txt`, `drift-batch-3-retire.txt` (slug-per-line, `# ` evidence comment above each) + a summary to stdout. Classification: for each registry work slug whose stored identity is absent from the successor groups: anchor exists + entity resolves + registered composer == dominant composer + near-key (difflib ≥0.5) between registered wk and dominant wk → tier 1; anchor + resolves, no near-key → tier 2; anchor + no resolving member → tier 3 (retire candidate); no anchor → tier 3 with a no-anchor reason.

- [ ] **Step 1: Write the failing tests**

```python
def test_load_entity_view_dominant_member(tmp_path):
    import sqlite3
    dst = str(tmp_path / "s.sqlite")
    conn = sqlite3.connect(dst)
    conn.executescript("""
      CREATE TABLE work_entity (id INTEGER PRIMARY KEY, name TEXT);
      CREATE TABLE work_entity_key (composer_key TEXT, work_key TEXT,
        work_entity_id INTEGER, PRIMARY KEY(composer_key, work_key));""")
    conn.execute("INSERT INTO work_entity VALUES (5, 'Bolero')")
    conn.execute("INSERT INTO work_entity_key VALUES ('maurice ravel', 'bolero', 5)")
    conn.execute("INSERT INTO work_entity_key VALUES ('maurice ravel', 'bolero arr', 5)")
    conn.commit(); conn.close()
    groups = {("maurice ravel", "bolero"): {"airings": 30},
              ("maurice ravel", "bolero arr"): {"airings": 3}}
    view = ttn2_query.load_entity_view(dst, groups=groups)
    assert view[5] == ("maurice ravel", "bolero")   # 30 airings wins


def test_drift_batch_tiers(tmp_path, monkeypatch):
    """Registry orphans classify into the three tiers; batch files emit
    slug-per-line with # evidence comments."""
    # synthetic registry with 3 orphans (mechanical / review / dissolved)
    # + successor groups where only the mechanical one's entity resolves.
    # monkeypatch ttn2_query.load_groups + the registry path.
    # Assert: three files exist, the mechanical slug is in file 1, the
    # review slug in file 2, the dissolved slug in file 3 with a retire
    # reason comment.
```

(Flesh the fixture from the existing `test_ttn2_site.py` synthetic patterns; the classification predicate is the interface under test.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest python -m pytest test_ttn2.py test_ttn2_site.py -k "entity_view or drift_batch" -v`
Expected: FAIL — attribute missing.

- [ ] **Step 3: Implement** per the Interfaces block. The generator reads the registry via `ttn_site.load_registry` (lazy import), the anchors via `ttn2_ledger.load_anchors`, the groups via `load_groups`, the entity view via `load_entity_view`. Tier predicates exactly as in Interfaces. Batch-file format: one slug per line; above each, `# registered: (ck, wk) -> entity N: (dominant_ck, dominant_wk) [N airings]` (tier 3: `# retire candidate: <reason>`).

- [ ] **Step 4: Run tests to verify they pass**, then the full suite.

- [ ] **Step 5: Real-corpus smoke (manual)**: `uv run python ttn2_query.py drift-batch --out-dir scratch/drift-batch` — report the tier counts vs the estimate (88/51/12). Commit.

```bash
git add ttn2_query.py test_ttn2.py test_ttn2_site.py
git commit -m "ttn2: entity view + drift-batch generator (tier classification, batch files)"
```

---

### Task 4: The three ratification batches (curation gates)

**Files:**
- Modify: `ttn_site.py` (new admin action `apply_anchor` alongside `apply_remap`/`apply_retire`: sets `entity_id` + derived strings on the named slugs, PURE registry-in/out; CLI wiring `--anchor-file` mirroring `--remap-file`)
- Test: `test_ttn_site.py` (append)

**Interfaces:**
- Consumes: Task 3's batch files.
- Produces: `apply_anchor(registry, namespace, slug, entity_id, ck, wk)` → new registry (entry gains entity_id + refreshed strings; unknown slug → RegistryActionError); `--anchor-file` lines: `SLUG|entity_id|dominant_ck|dominant_wk`.

- [ ] **Step 1: Failing test** — `apply_anchor` sets entity_id + strings; unknown slug raises; batch-file wiring round-trips.
- [ ] **Step 2: Verify fail**, **Step 3: implement** (mirror `apply_remap`'s structure exactly — PURE, RegistryActionError, batch-file parsing with blank/`#` skip), **Step 4: verify pass**.

- [ ] **Step 5: Batch 1 (mechanical ~88)** — review `drift-batch-1-mechanical.txt`; convert to `--anchor-file` lines; run `ttn_data.py site --check` (expect the 88 leave the orphan list); ratify.
- [ ] **Step 6: kyurkchiyski fold** — the composer alias pair (`Kyurkchiiski` → `Krasimir Kyurkchiyski` spelling family; verify the exact corpus spellings first via `ttn_curate.py composer-duplicates`) into `_COMPOSER_ALIAS_PAIRS` + ledger re-import; warm; its drift case re-classifies.
- [ ] **Step 7: Batch 2 (review ~51)** — side-by-side evidence per slug; ratify or remap per case.
- [ ] **Step 8: Batch 3 (dissolved ~12)** — `--retire-file` with reasons.
- [ ] **Step 9: Convergence** — re-run the generator: unanchored+orphaned → 0; `site --check` green; full suite green.

Each batch: commit (`registry: drift batch N ratified (N slugs)`).

---

### Task 5: Ride-alongs

**Files:**
- Modify: `ttn2_query.py` (ev_rp COALESCE + strip/normalize via `ttn2_site._identity_of` in `load_groups`)

- [ ] **Step 1**: `load_groups`' ev_rp gains the COALESCE form (`COALESCE(e.recording_pid, segment-obs join)` — bridge events have no segment obs) and identity via `T2._identity_of(cm, tt, comp, ws, wg, composer_line)` (import `ttn2_site` lazily; the one-implementation pattern from phase 1).
- [ ] **Step 2**: focused + full suite; the fragmentation/work-recordings outputs may shift (the bridge-identity + strip classes) — report the delta, do not chase it (documented divergence, reconciled at the layer level).
- [ ] **Step 3: Commit**: `ttn2_query: reconcile the curation layer with the site layer (COALESCE ev_rp, shared identity chain)`.

---

### Task 6: Docs

- [ ] Framework doc §7: phase-2 state (re-anchor landed, drift batch cleared, flip/freeze = phase 3). CLAUDE.md: the registry section gains the entity_id/derived-cache semantics + the `--anchor-file` admin action.
- [ ] Commit: `docs: P4 phase 2 landed — registry entity-anchored, drift batch cleared`.

---

## Verification (whole plan)

1. Full suite green (`uv run --with pytest python -m pytest`).
2. `ttn_data.py site --check` green with the entity gate (0 orphans).
3. The generator re-run: 0 unanchored registry slugs.
4. Parity gate unchanged (0 unexplained).
5. The nightly's next run: legacy build green (untouched path), registry merge clean.
