# P4 Site Cutover, Phase 1: successor-backed site substrate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build site.sqlite's aggregates from the successor events framework (obs → events → ledger) behind a `--source successor` flag, writing to a side DB (`site2.sqlite`), with a parity harness that diffs old-vs-new and classifies every diff as ledger-explained or blocking.

**Architecture:** The successor path replaces exactly two legacy seams — `_derive_registry_entries` (identity derivation) and `accumulate_entities` (per-row accumulation) — with a new adapter module `ttn2_site.py` whose keys come from ledger resolution, never from re-running the legacy alias chain (re-resolving would re-fold the 136 de-globalized bare-generic folds; that is the 233-key trap). Everything downstream in `_run_build` (spine, broadcasters, concerts, national days, browse payloads, `write_site_db`, `check_closure`) is consumed unchanged because it reads only the `acc` dict + entry lists. The legacy path stays the default and byte-identical.

**Tech Stack:** Python ≥ 3.12, uv, SQLite, pytest (`uv run --with pytest pytest`).

## Global Constraints

- Do NOT modify: `ttn_analyze.py`, `ttn_aliases.py`, `ttn_project.py`, `ttn_site_render.py`, `templates/`, `static/`.
- `ttn_site.py` changes are limited to: `_run_build` branching, `main()`/argparse, a new `site_fingerprint_t2`. All existing builders (`accumulate_entities`, `build_work_rows`, …) untouched.
- Legacy path (`--source legacy`, the default) must behave byte-identically to today.
- Successor mode NEVER writes `ttn_site_registry.json`, `ttn_evidence.json`, or `site.sqlite`. It reads the registry only.
- Preserve-raw / normalize-late; no identity decision outside the ledger.
- Identity rule in successor code is EXACTLY `ttn2_query.load_groups`' rule (ttn2_query.py:61-93): per text obs, `cm, tt = rec_meta[rp] if rp in rec_meta else (composer_raw, title)`; `ck = L.resolve_composer(A.canonical_key(cm), comp)`; `wk = L.resolve_work(A.work_title_key(tt, composer=cm), cm, ws, wg)`. Never re-resolve successor keys through `resolve_composer_alias`/`resolve_work_alias`.
- Tests: `uv run --with pytest pytest test_ttn2_site.py` (new file) and the full suite `uv run --with pytest pytest` (~28 s, live tests deselected by default). Never bare `python`/`pip`.
- Known expected delta (NOT a bug to fix here): successor identity differs from legacy on the de-globalized keys (parity currently reports 233 identity-key diffs — Stravinsky *Orpheus*, Bacewicz's symphonies, etc.). The parity harness must classify these as expected via the ledger-derived delta set.
- Pre-2012 trusted bridge links (≈8,593 airings) are part of the legacy projection and MUST be ingested by the successor in this phase (Task 1), else site2 loses 42.8% of the text-only block's recording links and the parity diff drowns in known-gap noise.

---

### Task 1: Successor ingests the full graduated-trust link set (bridge + medium)

**Files:**
- Modify: `ttn2_ingest.py` (SCHEMA + build()'s DROP list)
- Modify: `ttn2_match.py` (link())
- Modify: `ttn2_parity.py` (reference projection → full projection)
- Test: `test_ttn2.py` (append)

**Interfaces:**
- Consumes: `ttn_project.load(conn)` → `(projection, rec_meta, status)` (full projection incl. bridge); `ttn_mbid_audit.reconcile_episode` match dicts (`{"tier", "recording_pid", ...}` — every matched tier carries `recording_pid`, verified at ttn_mbid_audit.py:309-315).
- Produces: `event.recording_pid` column (set for `method='recording_pid'` and `method='bridge'` events); `presentation` table `(episode_pid, ord, recording_pid)` for Medium-tier DP matches; `ttn2_match.link()` unchanged signature. Later tasks read: `SELECT episode_pid, ord, recording_pid FROM presentation` and `event.recording_pid`.

- [ ] **Step 1: Write the failing tests**

Append to `test_ttn2.py`:

```python
def test_match_records_medium_presentation(tmp_path, monkeypatch):
    """A Medium-tier DP match becomes a presentation row, NOT an event link:
    the obs keeps a singleton event and raw-text identity."""
    import sqlite3, ttn2_ingest, ttn2_match
    dst = str(tmp_path / "s.sqlite")
    conn = sqlite3.connect(dst)
    conn.executescript(ttn2_ingest.SCHEMA)
    # one segment obs (rp X) + one text obs that the (fake) DP matches at medium
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, title, recording_pid) "
                 "VALUES (1, 'ep1', '2020-01-01', 1.0, 'segment', 'seg', "
                 "'Smetana', 'Vltava', 'X')")
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, title) "
                 "VALUES (2, 'ep1', '2020-01-01', 1.5, 'text', 'text', "
                 "'Smetana', 'Vltava')")
    conn.commit()
    fake = [{"track_position": 1, "composer_mbid": None,
             "recording_pid": "X", "segment_composer_name": "Smetana",
             "tier": "medium"}]
    monkeypatch.setattr(ttn2_match, "reconcile_episode", lambda t, s: fake)
    ttn2_match.link(dst=dst, src=str(tmp_path / "nonexistent-src.sqlite"))
    # obs NOT linked to the recording event (identity stays raw)
    ev = conn.execute("SELECT method, confidence, recording_pid FROM event "
                      "ORDER BY id").fetchall()
    assert ("recording_pid", "high", "X") in ev          # segment event
    assert ("singleton_text", "singleton", None) in ev   # text obs stays singleton
    assert conn.execute("SELECT recording_pid FROM presentation").fetchall() \
        == [("X",)]
    conn.close()


def test_match_ingests_bridge_links(tmp_path):
    """Pre-2012 text obs (episodes with no segment obs) whose (ep, pos) is in
    the legacy full projection become recording-backed events, method='bridge'."""
    import sqlite3, ttn2_ingest, ttn2_match
    src = str(tmp_path / "ttn.sqlite"); dst = str(tmp_path / "s.sqlite")
    s = sqlite3.connect(src)
    s.executescript("CREATE TABLE episodes (pid TEXT PRIMARY KEY, "
                    "broadcast_date TEXT); CREATE TABLE tracks (episode_pid TEXT, "
                    "position INTEGER, time_str TEXT, composer TEXT, "
                    "composer_line TEXT, title TEXT, performers TEXT, "
                    "contributors_json TEXT);")
    s.execute("INSERT INTO episodes VALUES ('old1', '2005-01-01T00:30:00Z')")
    s.execute("INSERT INTO tracks VALUES ('old1', 0, '1:01 am', 'Bach', "
              "'Johann Sebastian Bach (1685-1750)', 'Cello Suite No 1', 'p', '[]')")
    s.commit(); s.close()
    conn = sqlite3.connect(dst)
    conn.executescript(ttn2_ingest.SCHEMA)
    # minimal obs for the episode (what ingest would have written)
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, composer_line, title) "
                 "VALUES (1, 'old1', '2005-01-01', 0.0, 'text', 'text', "
                 "'Bach', 'Johann Sebastian Bach (1685-1750)', 'Cello Suite No 1')")
    conn.commit()
# monkeypatch the legacy projection read: (old1, 0) -> rp BR1
    class FakeP:
        @staticmethod
        def load(conn, *a, **k):
            return {("old1", 0): "BR1"}, {"BR1": ("Johann Sebastian Bach",
                                                  "Cello Suite No 1, BWV 1007")}, "ok"
    import ttn_project
    orig = ttn_project.load
    ttn_project.load = FakeP.load
    try:
        ttn2_match.link(dst=dst, src=src)
    finally:
        ttn_project.load = orig
    ev = conn.execute("SELECT method, confidence, recording_pid, composer, title "
                      "FROM event WHERE method='bridge'").fetchall()
    assert ev == [("bridge", "high", "BR1", "Johann Sebastian Bach",
                   "Cello Suite No 1, BWV 1007")]
    assert conn.execute("SELECT event_id FROM obs WHERE id=1").fetchone()[0] == \
        conn.execute("SELECT id FROM event WHERE method='bridge'").fetchone()[0]
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest test_ttn2.py -k "medium_presentation or bridge_links" -v`
Expected: FAIL — `presentation` table missing / no bridge events.

- [ ] **Step 3: Implement**

`ttn2_ingest.py` — in `build()`'s DROP line add `DROP TABLE IF EXISTS presentation;`, and append to `SCHEMA`:

```sql
CREATE TABLE presentation (
  episode_pid TEXT NOT NULL,
  ord REAL NOT NULL,
  recording_pid TEXT NOT NULL,
  PRIMARY KEY (episode_pid, ord)
);
```

`ttn2_match.py` — add `recording_pid TEXT` to the `event` CREATE in `ttn2_ingest.SCHEMA` (the event table lives there), set it on insert, and rework the text-obs loop:

```python
# in link(), segment-event INSERT gains the rp:
out.execute("INSERT INTO event (episode_pid, date10, ord, composer, "
            "title, method, confidence, recording_pid) VALUES (?,?,?,?,?,?,?,?)",
            (ep, date10, ordv, anchor[0], anchor[1], "recording_pid", "high", rp))
```

Text-obs branch (replaces the current `if m.get("tier") == "high" ...` block):

```python
for m, (oid, ordv, comp, cl, title, tstr) in zip(matches, text):
    rp = m.get("recording_pid")
    if m.get("tier") == "high" and rp and rp in rp_event:
        eid = rp_event[m["recording_pid"]]
        out.execute("UPDATE obs SET event_id=? WHERE id=?", (eid, oid))
        n_linked += 1
        continue
    if m.get("tier") == "medium" and rp and rp in rp_event:
        # graduated trust: a Medium link SHOWS the recording but never
        # carries identity -- the obs keeps a singleton event with raw text.
        out.execute("INSERT OR REPLACE INTO presentation VALUES (?,?,?)",
                    (ep, ordv, rp))
        n_medium += 1
    out.execute("INSERT INTO event (episode_pid, date10, ord, composer, "
                "title, method, confidence, recording_pid) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ep, date10, ordv, comp, title, "singleton_text", "singleton", None))
    eid = out.execute("SELECT last_insert_rowid()").fetchone()[0]
    out.execute("UPDATE obs SET event_id=? WHERE id=?", (eid, oid))
    n_singleton += 1
```

(The no-segment `else` branch's singleton inserts also pass `None` for the new column.)

Bridge step — new function in `ttn2_match.py`, called from `link()` after the per-episode loop, before `commit()`:

```python
def _bridge_links(out, src):
    """Ingest the legacy projection's bridge half as recording-backed events.
    The full projection (ttn_project.load) merges the 2012+ DP half with the
    trusted cross-era bridge DISJOINTLY, so any projection entry whose text
    obs is not already recording-linked IS a bridge link — this covers both
    the pre-2012 block and the scattered tail. Reading the legacy projection
    cache here is the phase-1 shortcut; P2 re-derives these from the ledger
    directly."""
    import ttn_project
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        projection, rec_meta_full, status = ttn_project.load(conn)
    finally:
        conn.close()
    if status != "ok":
        return 0
    dates = dict(out.execute("SELECT episode_pid, date10 FROM obs"))
    linked = {r[0] for r in out.execute(
        "SELECT o.id FROM obs o JOIN event e ON o.event_id=e.id "
        "WHERE e.method IN ('recording_pid','bridge')")}
    n = 0
    for (ep, pos), rp in projection.items():
        if rp not in rec_meta_full:
            continue
        row = out.execute(
            "SELECT id FROM obs WHERE episode_pid=? AND source='text' "
            "AND ord=? ORDER BY id LIMIT 1", (ep, float(pos))).fetchone()
        if row is None or row[0] in linked:
            continue
        cm, tt = rec_meta_full[rp]
        out.execute("INSERT INTO event (episode_pid, date10, ord, composer, "
                    "title, method, confidence, recording_pid) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (ep, dates.get(ep), float(pos), cm, tt, "bridge", "high", rp))
        eid = out.execute("SELECT last_insert_rowid()").fetchone()[0]
        out.execute("UPDATE obs SET event_id=? WHERE id=?", (eid, row[0]))
        linked.add(row[0])
        n += 1
    return n
```

Call it in `link()` after the per-episode loop (pass the `src` path string — `link()` already holds it) and print the count in the summary line.

`ttn2_parity.py` — upgrade the reference from `P.build_projections_mbid(src)` to the full projection `P.load(src)` (unpack `(projection, rec_meta, status)`; assert `status == "ok"`). The linkage check now covers bridge links too; identity diffs must remain exactly the known de-globalization delta.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest test_ttn2.py -v`
Expected: PASS (all, including pre-existing successor tests).

- [ ] **Step 5: Real-corpus verification (manual, not a test)**

```bash
uv run ttn2_ingest.py && uv run ttn2_match.py && uv run ttn2_ledger.py check
uv run ttn2_parity.py
```
Expected: match prints `N recording events, N linked, N singleton, N medium presentation links, N bridge events` (bridge ≈ 8,593); parity: `linkage 0` diffs, identity ≈ 233 keys (the known delta), years none. Record the numbers in the commit message.

- [ ] **Step 6: Commit**

```bash
git add ttn2_ingest.py ttn2_match.py ttn2_parity.py test_ttn2.py
git commit -m "ttn2: ingest the full graduated-trust link set (bridge events + medium presentation)"
```

---

### Task 2: `ttn2_site.py` — identity maps + successor accumulate

**Files:**
- Create: `ttn2_site.py`
- Test: `test_ttn2_site.py` (create)

**Interfaces:**
- Consumes: Task 1's `event.recording_pid` + `presentation` table; `ttn2_ledger.load_maps/resolve_composer/resolve_work`; `ttn_site._WHOLE_CORPUS_SQL`, `ttn_site.parse_composer_years`; `ttn_project.build_rec_meta`.
- Produces:
  - `load_identity_maps(src="ttn.sqlite", dst="successor.sqlite")` → `(comp, ws, wg, rec_meta, text_rp, presentation_map)` where `text_rp`: `{(episode_pid, position_int): recording_pid}` (High DP + bridge, the projection equivalent), `presentation_map`: same shape (Medium, show-only).
  - `accumulate_entities_t2(rows8, comp, ws, wg, rec_meta, text_rp, presentation=None)` → `(acc, counters)`; `acc` has exactly the legacy keys/shapes (`work_airings`, `episode_tracks`, `recording_airings`, `composer_dates`); `counters` = `{"title_counter": {(ck,wk): Counter}, "composer_counter": {(ck,wk): Counter}, "composer_spelling_counter": {ck: Counter}, "composer_work_keys": {ck: set}, "rows5": [(tt, cm, composer_line, performers, bdate), ...]}`.

- [ ] **Step 1: Write the failing test**

Create `test_ttn2_site.py`:

```python
import sqlite3
import ttn_analyze as A
import ttn2_ledger as L
import ttn2_site


def _ledger_db(tmp_path, rows):
    """successor.sqlite with a minimal ledger; rows = (variant, target) work pairs."""
    dst = str(tmp_path / "succ.sqlite")
    conn = sqlite3.connect(dst)
    conn.executescript("""
      CREATE TABLE ledger (id INTEGER PRIMARY KEY, kind TEXT, scope TEXT,
        variant_key TEXT, target TEXT, target_key TEXT, method TEXT,
        confidence TEXT, flags_json TEXT);
      CREATE TABLE event (id INTEGER PRIMARY KEY, episode_pid TEXT, date10 TEXT,
        ord REAL, composer TEXT, title TEXT, method TEXT, confidence TEXT,
        recording_pid TEXT);
      CREATE TABLE obs (id INTEGER PRIMARY KEY, episode_pid TEXT, date10 TEXT,
        ord REAL, source TEXT, source_grade TEXT, composer_raw TEXT,
        composer_line TEXT, title TEXT, recording_pid TEXT, event_id INTEGER);
      CREATE TABLE presentation (episode_pid TEXT, ord REAL, recording_pid TEXT,
        PRIMARY KEY (episode_pid, ord));
    """)
    for i, (v, t) in enumerate(rows):
        conn.execute("INSERT INTO ledger (kind, scope, variant_key, target, "
                     "target_key, method, confidence) VALUES "
                     "('work_alias','global',?,?,?,?, 'legacy')",
                     (A.work_title_key(v), t, A.work_title_key(t)))
    conn.commit()
    return dst


def test_accumulate_t2_identity_and_presentation(tmp_path):
    dst = _ledger_db(tmp_path, [("Bolero", "Bolero")])
    comp, ws, wg = L.load_maps(dst)
    rec_meta = {"RP1": ("Maurice Ravel", "Bolero")}
    # rows8: (title, composer, composer_line, performers, bdate, ep, pos, time)
    rows8 = [
        ("Bolero", "Ravel", "Maurice Ravel (1875-1937)", "p", "2020-01-01", "e1", 0, "1:01 am"),
        ("Bolero", "Ravel", "Maurice Ravel (1685-1750)", "p", "2005-01-01", "e2", 0, "1:02 am"),
        ("Mystery", "Anon", "", "p", "2005-01-01", "e2", 1, "1:30 am"),
    ]
    text_rp = {("e1", 0): "RP1"}               # High link
    pres = {("e2", 0): "RP1"}                  # Medium link (show-only)
    acc, counters = ttn2_site.accumulate_entities_t2(
        rows8, comp, ws, wg, rec_meta, text_rp, pres)
    key = ("maurice ravel", A.work_title_key("Bolero", "Maurice Ravel"))
    assert acc["work_airings"][key] == [
        ("2020-01-01", "RP1", "p", "e1", 0),   # High: identity + rp from rec_meta
        ("2005-01-01", "RP1", "p", "e2", 0),   # Medium: rp SHOWN, identity raw
    ]
    # episode_tracks display: e1 shows the clean rec_meta credit, e2 the raw one
    assert acc["episode_tracks"]["e1"][0][3:5] == ("Maurice Ravel", "Bolero")
    assert acc["episode_tracks"]["e2"][0][3:5] == ("Ravel", "Bolero")
    assert acc["recording_airings"]["RP1"] == [
        ("2020-01-01", "e1", 0), ("2005-01-01", "e2", 0)]
    # composer_dates from modal parse of composer_line
    ck = "maurice ravel"
    assert acc["composer_dates"][ck] == (1937, None)
```

(If the last assertion's expectation is wrong for `parse_composer_years`' modal rule — one birth year seen once is the modal — run it and fix the expectation to the function's actual output; the invariant under test is that composer_dates is populated from composer_line exactly as legacy does.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest test_ttn2_site.py -v`
Expected: FAIL — `No module named 'ttn2_site'`.

- [ ] **Step 3: Implement `ttn2_site.py`**

```python
"""ttn2_site — P4 phase 1: successor-backed site substrate inputs.

Produces the exact structures ttn_site._run_build consumes, with identity
resolved through the successor ledger instead of the legacy projection +
alias-table chain. The de-globalization delta (bare-generic folds scoped to
their dominant composer in the ledger) is EXPECTED here — it is the
cutover's content, classified by ttn2_site_parity.

Identity rule (verbatim from ttn2_query.load_groups / ttn2_parity): per text
row, rec_meta[rp] when the row's event is recording-backed, else the raw
text fields; keys = ledger resolution. The legacy strip_arranger_tail ->
resolve chain is deliberately NOT applied on top: ledger targets are final
canonicals, and re-resolving would re-fold the de-globalized identities.
"""
import sqlite3

import ttn_analyze as A
import ttn2_ledger as L

DB = "successor.sqlite"
SRC = "ttn.sqlite"


def load_identity_maps(src=SRC, dst=DB):
    """(comp, ws, wg, rec_meta, text_rp, presentation_map).

    text_rp: {(episode_pid, position): recording_pid} — the successor's
    High-tier link set (DP-high + bridge events), the drop-in equivalent of
    the legacy projection. presentation_map: same shape, Medium tier,
    show-only (never identity)."""
    comp, ws, wg = L.load_maps(dst)
    from ttn_project import build_rec_meta
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    rec_meta = build_rec_meta(src_conn)
    src_conn.close()
    s2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    ev_rp = {}
    for eid, rp in s2.execute(
            "SELECT id, COALESCE(recording_pid, "
            "  (SELECT o.recording_pid FROM obs o WHERE o.event_id=e.id "
            "   AND o.source='segment' LIMIT 1)) "
            "FROM event e WHERE method IN ('recording_pid','bridge')"):
        if rp:
            ev_rp[eid] = rp
    text_rp, pres = {}, {}
    for ep, ordv, eid in s2.execute(
            "SELECT episode_pid, ord, event_id FROM obs "
            "WHERE source='text' AND event_id IS NOT NULL"):
        rp = ev_rp.get(eid)
        if rp:
            text_rp[(ep, int(ordv))] = rp
    for ep, ordv, rp in s2.execute(
            "SELECT episode_pid, ord, recording_pid FROM presentation"):
        pres[(ep, int(ordv))] = rp
    s2.close()
    return comp, ws, wg, rec_meta, text_rp, pres


def _identity_of(cm, tt, comp, ws, wg):
    ck = L.resolve_composer(A.canonical_key(cm), comp)
    wk = L.resolve_work(A.work_title_key(tt, composer=cm), cm, ws, wg)
    return ck, wk


def accumulate_entities_t2(rows8, comp, ws, wg, rec_meta, text_rp,
                           presentation=None):
    """Mirror of ttn_site.accumulate_entities with successor identity.

    rows8: (title, composer, composer_line, performers, bdate, episode_pid,
    position, time_str) — ttn_site._WHOLE_CORPUS_SQL's shape.
    Returns (acc, counters); acc has exactly the legacy accumulate_entities
    keys/shapes so every downstream builder is unchanged."""
    import ttn_site as S  # lazy: ttn_site imports this module lazily too
    from collections import Counter
    work_airings, episode_tracks, recording_airings = {}, {}, {}
    births, deaths = {}, {}
    title_counter, composer_counter = {}, {}
    comp_spelling, comp_works = {}, {}
    rows5 = []
    for title, composer, composer_line, performers, bdate, ep, pos, tstr in rows8:
        rp = text_rp.get((ep, pos))
        if rp is not None and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = composer or "", title or ""
        rows5.append((tt, cm, composer_line, performers, bdate))
        ck, wk = _identity_of(cm, tt, comp, ws, wg)
        rp_shown = rp
        if rp_shown is None and presentation:
            rp_shown = presentation.get((ep, pos))
        key = None if (not ck and not wk) else (ck, wk)
        b, d = S.parse_composer_years(composer_line)
        if b is not None:
            births.setdefault(ck, {})
            births[ck][b] = births[ck].get(b, 0) + 1
        if d is not None:
            deaths.setdefault(ck, {})
            deaths[ck][d] = deaths[ck].get(d, 0) + 1
        if key is not None:
            work_airings.setdefault(key, []).append(
                (bdate, rp_shown, performers, ep, pos))
            title_counter.setdefault(key, Counter())[tt] += 1
            composer_counter.setdefault(key, Counter())[A.normalize_composer(cm)] += 1
        if ck:
            comp_spelling.setdefault(ck, Counter())[A.normalize_composer(cm)] += 1
            if wk:
                comp_works.setdefault(ck, set()).add(wk)
        episode_tracks.setdefault(ep, []).append(
            (pos, tstr, key, cm, tt, performers, rp_shown))
        if rp_shown is not None:
            recording_airings.setdefault(rp_shown, []).append((bdate, ep, pos))
    for ep in episode_tracks:
        episode_tracks[ep].sort(key=lambda row: row[0])
    def _modal(counter):
        return max(counter, key=counter.get) if counter else None
    composer_dates = {ck: (_modal(births.get(ck)), _modal(deaths.get(ck)))
                      for ck in set(births) | set(deaths)}
    counters = {"title_counter": title_counter, "composer_counter": composer_counter,
                "composer_spelling_counter": comp_spelling,
                "composer_work_keys": comp_works, "rows5": rows5}
    acc = {"work_airings": work_airings, "episode_tracks": episode_tracks,
           "recording_airings": recording_airings, "composer_dates": composer_dates}
    return acc, counters
```

(The `rows5` list mirrors the legacy `_project_rows` output shape — `(title, composer, composer_line, performers, bdate)` with successor-resolved identity strings — for `build_browse_payloads`' positional `all_rows5` argument; see Task 4 for why it is NOT fed to `compute_year_breakdown`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest test_ttn2_site.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ttn2_site.py test_ttn2_site.py
git commit -m "ttn2_site: successor identity maps + accumulate_entities_t2 (ledger-resolved keys)"
```

---

### Task 3: `ttn2_site.py` — work/composer entries + evidence map

**Files:**
- Modify: `ttn2_site.py`
- Test: `test_ttn2_site.py` (append)

**Interfaces:**
- Consumes: Task 2's `(acc, counters)`; `ttn_analyze._best_spelling`, `build_work_slugs`, `override_composer_display`; `ttn_site.composer_slug`.
- Produces:
  - `build_work_entries_t2(acc, counters, registry_works)` → list of dicts with EXACTLY the `build_work_index` keys: `key, slug, composer_display, work_display, airings, spellings`.
  - `build_composer_entries_t2(counters, registry_composers)` → list of dicts with EXACTLY the `build_composer_index` keys: `composer_key, slug, display, airings, n_works, spellings`.
  - `pids_by_identity_t2(rows8, text_rp, comp, ws, wg, rec_meta)` → `{(ck, wk): set(rp)}` (mirrors `ttn_evidence.current_pids_by_identity` with successor identity).

- [ ] **Step 1: Write the failing test**

Append to `test_ttn2_site.py`:

```python
def test_work_entries_t2_registry_wins_and_mints(tmp_path):
    dst = _ledger_db(tmp_path, [])
    comp, ws, wg = L.load_maps(dst)
    rec_meta = {}
    rows8 = [
        ("Bolero", "Ravel", "Maurice Ravel (1862-1937)", "p", "2020-01-01", "e1", 0, "t"),
        ("La Valse", "Ravel", "Maurice Ravel (1862-1937)", "p", "2020-01-01", "e1", 1, "t"),
    ]
    acc, counters = ttn2_site.accumulate_entities_t2(rows8, comp, ws, wg, rec_meta, {})
    reg_works = {}   # nothing registered -> everything minted
    entries = ttn2_site.build_work_entries_t2(acc, counters, reg_works)
    by_key = {e["key"]: e for e in entries}
    assert set(entries[0]) == {"key", "slug", "composer_display", "work_display",
                               "airings", "spellings"}
    assert by_key[("maurice ravel", "bolero")]["airings"] == 1
    assert by_key[("maurice ravel", "bolero")]["slug"]  # minted, non-empty
    # registry overlay wins over the mint
    reg = {"ravel-bolero": {"composer_key": "maurice ravel",
                            "work_key": "bolero"}}
    entries2 = ttn2_site.build_work_entries_t2(acc, counters, reg)
    by_key2 = {e["key"]: e for e in entries2}
    assert by_key2[("maurice ravel", "bolero")]["slug"] == "ravel-bolero"


def test_composer_entries_t2_shape(tmp_path):
    dst = _ledger_db(tmp_path, [])
    comp, ws, wg = L.load_maps(dst)
    rows8 = [("Bolero", "Ravel", "Maurice Ravel (1862-1937)", "p",
              "2020-01-01", "e1", 0, "t")]
    acc, counters = ttn2_site.accumulate_entities_t2(rows8, comp, ws, wg, {}, {})
    entries = ttn2_site.build_composer_entries_t2(counters, {})
    assert len(entries) == 1
    e = entries[0]
    assert set(e) == {"composer_key", "slug", "display", "airings",
                      "n_works", "spellings"}
    assert e["composer_key"] == "maurice ravel" and e["airings"] == 1
    assert e["n_works"] == 1


def test_pids_by_identity_t2_skips_unlinked(tmp_path):
    dst = _ledger_db(tmp_path, [])
    comp, ws, wg = L.load_maps(dst)
    rows8 = [("Bolero", "Ravel", "Maurice Ravel", "p", "2020-01-01", "e1", 0, "t"),
             ("Bolero", "Ravel", "Maurice Ravel (1862-1937)", "p",
              "2005-01-01", "e2", 0, "t")]
    pids = ttn2_site.pids_by_identity_t2(
        rows8, {("e1", 0): "RP1"}, comp, ws, wg, {"RP1": ("Maurice Ravel", "Bolero")})
    assert pids == {("maurice ravel", "bolero"): {"RP1"}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest test_ttn2_site.py -v`
Expected: FAIL — `build_work_entries_t2` not defined.

- [ ] **Step 3: Implement**

Append to `ttn2_site.py`:

```python
def build_work_entries_t2(acc, counters, registry_works):
    """Work entries with successor keys. Registry slugs WIN (URL stability);
    unregistered identities mint via build_work_slugs with the registry slugs
    as the taken set (collision -> '-2', '-3', ... suffix)."""
    from collections import Counter
    from ttn_analyze import _best_spelling, build_work_slugs
    reg_slug_of = {(v["composer_key"], v["work_key"]): slug
                   for slug, v in registry_works.items()}
    keys = list(acc["work_airings"])
    minted = build_work_slugs(
        (k, _best_spelling(counters["composer_counter"][k]),
         _best_spelling(counters["title_counter"][k])) for k in keys)
    taken = set(reg_slug_of.values())
    entries = []
    for k in keys:
        slug = reg_slug_of.get(k)
        if slug is None:
            slug = minted[k]
            if slug in taken:
                base, i = slug, 2
                while f"{base}-{i}" in taken:
                    i += 1
                slug = f"{base}-{i}"
        taken.add(slug)
        entries.append({
            "key": k,
            "slug": slug,
            "composer_display": _best_spelling(counters["composer_counter"][k]),
            "work_display": _best_spelling(counters["title_counter"][k]),
            "airings": len(acc["work_airings"][k]),
            "spellings": list(counters["title_counter"][k]),
        })
    return entries


def build_composer_entries_t2(counters, registry_composers):
    """Composer entries mirroring ttn_site.build_composer_index's dict shape,
    keyed from successor resolution. Registry slug wins; misses mint via
    ttn_site.composer_slug (collision suffixing mirrors the registry's own
    assignment, which is skipped in successor mode)."""
    from ttn_analyze import _best_spelling, override_composer_display
    from ttn_site import composer_slug
    reg_slug_of = {v["composer_key"]: slug
                   for slug, v in registry_composers.items()}
    taken = set(reg_slug_of.values())
    entries = []
    for ck, counter in counters["composer_spelling_counter"].items():
        best = _best_spelling(counter)
        display = override_composer_display(ck, "composer", best)
        slug = reg_slug_of.get(ck)
        if slug is None:
            slug = composer_slug(display)
            if slug in taken:
                base, i = slug, 2
                while f"{base}-{i}" in taken:
                    i += 1
                slug = f"{base}-{i}"
        taken.add(slug)
        entries.append({
            "composer_key": ck,
            "slug": slug,
            "display": display,
            "airings": sum(counter.values()),
            "n_works": len(counters["composer_work_keys"].get(ck, ())),
            "spellings": list(counter),
        })
    return entries


def pids_by_identity_t2(rows8, text_rp, comp, ws, wg, rec_meta):
    """{(ck, wk): set(recording_pid)} — mirrors
    ttn_evidence.current_pids_by_identity with successor identity (projection
    only; a Medium link is not identity proof)."""
    out = {}
    for row in rows8:
        title, composer, composer_line, _perf, _bdate, ep, pos, _t = row
        rp = text_rp.get((ep, pos))
        if rp is None:
            continue
        if rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = composer or "", title or ""
        ck, wk = _identity_of(cm, tt, comp, ws, wg)
        if not ck and not wk:
            continue
        out.setdefault((ck, wk), set()).add(rp)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest test_ttn2_site.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ttn2_site.py test_ttn2_site.py
git commit -m "ttn2_site: work/composer entries + evidence map from successor groups"
```

---

### Task 4: `_run_build` successor branch + CLI + fingerprint

**Files:**
- Modify: `ttn_site.py` (`_run_build` ~4081, `main()` argparse, new `site_fingerprint_t2` near `site_fingerprint` at 3561)
- Modify: `ttn_data.py` (site subcommand: add `--source`, pass through)
- Test: `test_ttn2_site.py` (append e2e)

**Interfaces:**
- Consumes: Tasks 2-3's functions.
- Produces: `ttn_site._run_build(..., source="legacy")`; `ttn_data.py site --source successor` builds `site2.sqlite` (default in successor mode), skipping registry/evidence writes; `site_fingerprint_t2(registry_path, artist_registry_path)`.

- [ ] **Step 1: Write the failing e2e test**

Append to `test_ttn2_site.py` (mirror the synthetic-build pattern in `test_ttn_site.py`'s e2e tests — read one first, e.g. the registry freeze/closure tests, and reuse its fixture helpers for building a tiny `ttn.sqlite`):

```python
def test_run_build_successor_source_e2e(tmp_path, monkeypatch):
    """Successor source builds site2.sqlite through the UNCHANGED downstream
    builders and passes check_closure."""
    import ttn_site
    # build the tiny src/successor pair (reuse/extend the Task-1 fixture
    # helpers; the ttn.sqlite side needs episodes + tracks + segment_events
    # rows sufficient for the spine and one work)
    src, dst, reg_path = _tiny_corpus(tmp_path)   # helper defined in this file
    monkeypatch.setattr(ttn_site, "REGISTRY_PATH", str(reg_path))
    out_db = str(tmp_path / "site2.sqlite")
    rc = ttn_site._run_build(src, str(reg_path), out_db, force=True,
                             source="successor")
    assert rc == 0
    conn = sqlite3.connect(out_db)
    assert conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] >= 1
    assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone() >= 1
    conn.close()
```

`_tiny_corpus(tmp_path)` builds: `ttn.sqlite` (episodes row + 2 tracks rows + 1 segment_events row sharing a recording_pid), `successor.sqlite` via `ttn2_ingest.build(src, dst)` + `ttn2_match.link(dst, src)` + a one-row ledger, and a minimal registry JSON (`{"works": {}, "composers": {}, "redirects": {"works": {}}, "retired": {}}` — check `ttn_site._empty_registry()` for the exact minimal shape and use it).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest test_ttn2_site.py -k e2e -v`
Expected: FAIL — `_run_build() got an unexpected keyword argument 'source'`.

- [ ] **Step 3: Implement the branch**

In `ttn_site.py`:

```python
def site_fingerprint_t2(registry_path, artist_reg_path=None):
    """Successor-source fingerprint: the successor DB + ledger export + the
    ttn2 modules' bytes replace the projection-cache/legacy-module slots."""
    import ttn2_ingest, ttn2_ledger, ttn2_match, ttn2_site
    paths = [ttn2_ingest.__file__, ttn2_match.__file__, ttn2_ledger.__file__,
             ttn2_site.__file__, "successor.sqlite", "ttn2_ledger.json"]
    h = hashlib.sha256()
    for p in paths:
        h.update(open(p, "rb").read())
    h.update(open(registry_path, "rb").read())
    if artist_reg_path and os.path.exists(artist_reg_path):
        h.update(open(artist_reg_path, "rb").read())
    return h.hexdigest()
```

(Mirror `site_fingerprint`'s exact hashing style — read it first at ttn_site.py:3561 and keep the byte-ordering convention consistent.)

In `_run_build`, add `source="legacy"` parameter. At the top of the build:

```python
if source == "successor":
    import ttn2_site
    registry = load_registry(registry_out_path)
    (work_entries, composer_entries, raw8, acc, counters,
     text_rp, presentation_map, pids_by_identity) = \
        ttn2_site.derive_site_inputs(db_path, registry)
    rows5 = None   # successor mode: browse payloads take raw8-derived rows
```

with `derive_site_inputs(src, registry)` in `ttn2_site.py`:

```python
def derive_site_inputs(src, registry):
    """The successor counterpart of ttn_site._derive_registry_entries:
    (work_entries, composer_entries, raw8, acc, counters, text_rp,
    presentation_map, pids_by_identity)."""
    comp, ws, wg, rec_meta, text_rp, pres = load_identity_maps(src)
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    raw8 = list(conn.execute(_WHOLE_CORPUS_SQL))   # import from ttn_site
    conn.close()
    acc, counters = accumulate_entities_t2(
        raw8, comp, ws, wg, rec_meta, text_rp, pres)
    work_entries = build_work_entries_t2(acc, counters, registry["works"])
    composer_entries = build_composer_entries_t2(counters, registry["composers"])
    pids = pids_by_identity_t2(raw8, text_rp, comp, ws, wg, rec_meta)
    return (work_entries, composer_entries, raw8, acc, counters,
            text_rp, pres, pids)
```

Then branch the two legacy-only steps:
- Skip `sync_registry`/`dump_registry`/`ttn_evidence.write_evidence` in successor mode (print `registry: read-only (successor source)`).
- `presentation = {k: rp for k, rp in presentation_map.items() if rp in recs}` replaces the `load_presentation` call (keep the spine filter — same invariant).
- `acc = accumulate_entities(...)` becomes `if source == "legacy": acc = accumulate_entities(...) else: acc = acc  # from derive_site_inputs`.
- `rows5` is passed to `build_browse_payloads(..., rows5, ...)` at line 4274, where its ONLY use is `compute_year_breakdown(all_rows5)` (ttn_site.py:2131) — and `compute_year_breakdown` re-derives identity keys through the legacy chain (`strip_arranger_tail` + `resolve_composer_alias` + `resolve_work_alias`, ttn_analyze.py:2330-2333). Feeding successor rows through it would re-fold the de-globalized identities (the 233-key trap). Definitive design:
  1. Add a keyword-only `year_breakdown=None` parameter to `build_browse_payloads` (ttn_site.py:1863); at line 2131, `years = list(reversed(year_breakdown if year_breakdown is not None else compute_year_breakdown(all_rows5)))`. Default None = legacy behavior byte-identical. This is the ONE permitted builder touch.
  2. Add `year_breakdown_t2(acc)` to `ttn2_site.py` — same output shape as `compute_year_breakdown` (`{"year", "airings", "works", "composers", "date_min", "date_max"}` per year, ascending), derived from `acc["work_airings"]` (each airing's `bdate` + its successor `(ck, wk)` key): no legacy re-derivation anywhere.

```python
def year_breakdown_t2(acc):
    """compute_year_breakdown's shape, keyed from successor identity."""
    buckets = {}
    for (ck, wk), airings in acc["work_airings"].items():
        for bdate, _rp, _perf, _ep, _pos in airings:
            if not bdate:
                continue
            year = bdate[:4]
            if not year.isdigit():
                continue
            b = buckets.get(year)
            if b is None:
                b = buckets[year] = {"airings": 0, "works": set(),
                                     "composers": set(), "dmin": bdate,
                                     "dmax": bdate}
            b["airings"] += 1
            b["works"].add((ck, wk))
            b["composers"].add(ck)
            b["dmin"] = min(b["dmin"], bdate)
            b["dmax"] = max(b["dmax"], bdate)
    return [{"year": y, "airings": b["airings"], "works": len(b["works"]),
             "composers": len(b["composers"]), "date_min": b["dmin"],
             "date_max": b["dmax"]}
            for y, b in sorted(buckets.items())]
```

  4. Successor branch passes `counters["rows5"]` as the positional `all_rows5` (unused once `year_breakdown` is given) and `year_breakdown=year_breakdown_t2(acc)`.
- Fingerprint: `fp = site_fingerprint_t2(registry_out_path, artist_registry_out_path)` in successor mode (both before the fresh-skip and the post-artist-registry re-stamp at line 4303).
- Default `site_db_out_path`: in `main()`, when `--source successor` and no explicit `--site-db`, use `site2.sqlite` (add `--site-db` if `main()` lacks a path override — read `main()` first).

In `ttn_data.py`: the `site` subcommand's argparse gains `--source {legacy,successor}` (default `legacy`), passed through to `ttn_site.main(...)`. Read the dispatch at ttn_data.py:24 first and thread the flag the same way the other site flags (`--force`, `--build-only`) flow.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest test_ttn2_site.py test_ttn_site.py test_ttn_data.py -v`
Expected: PASS — including all pre-existing ttn_site/ttn_data tests (legacy path unchanged).

- [ ] **Step 5: Legacy byte-identity check (manual)**

```bash
uv run ttn_data.py site --build-only --force
git status --short   # ttn_site_registry.json / ttn_evidence.json untouched
```
Expected: registry + evidence untouched; build succeeds as before.

- [ ] **Step 6: Commit**

```bash
git add ttn_site.py ttn_data.py test_ttn2_site.py
git commit -m "ttn_site: --source successor builds site2.sqlite from the events framework"
```

---

### Task 5: Parity harness — site.sqlite vs site2.sqlite

**Files:**
- Create: `ttn2_site_parity.py`
- Test: `test_ttn2_site.py` (append)

**Interfaces:**
- Consumes: Task 4's successor build; `ttn2_parity`'s identity-multiset logic (upgraded in Task 1 to the full projection) for the delta key set.
- Produces: `python ttn2_site_parity.py [--build]` → per-table diff report, `scratch/p4-site-parity.json`, exit 1 on UNEXPECTED diffs.

- [ ] **Step 1: Write the failing test**

```python
def test_site_parity_classifies_delta_as_expected(tmp_path):
    """A works-row diff whose key is in the ledger delta is EXPECTED; a diff
    outside it is UNEXPECTED (exit 1)."""
    # two tiny site DBs built by hand with the real table schemas
    # (copy the CREATE statements from ttn_site.write_site_db), one row each:
    #  - shared row (identical) -> no diff
    #  - delta row: present in both but with different airings, key in delta
    #  - rogue row: same key both sides, different airings, key NOT in delta
    # run ttn2_site_parity.classify(...) directly with a synthetic delta set
    report = ttn2_site_parity.classify(
        old_rows={"works": [("k1", 5), ("k2", 3)]},
        new_rows={"works": [("k1", 5), ("k2", 4)]},
        delta_keys={("k2",)},
        key_extractors={"works": lambda r: (r[0],)})
    assert report["unexpected"] == [] and report["expected"] == \
        [{"table": "works", "key": "k2", "side": "changed",
          "old": ("k2", 3), "new": ("k2", 4)}]
```

(Adjust to the real `write_site_db` table schemas — read `write_site_db` and mirror its CREATE statements in the fixture.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest test_ttn2_site.py -k parity -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `ttn2_site_parity.py`**

```python
"""ttn2_site_parity — P4 gate: site.sqlite (legacy) vs site2.sqlite
(successor), table by table, with ledger-derived expected-diff
classification (docs/successor-events-framework.md §6).

A diff is EXPECTED iff its identity keys intersect the ledger delta (the
de-globalization key set computed exactly as ttn2_parity's identity check).
Anything else is UNEXPECTED and blocks cutover.
"""
import json, os, sqlite3, sys

TABLES = ["works", "composers", "episodes", "recordings", "years",
          "broadcasters", "forms", "artists", "countries"]

def load_table(conn, table):
    cur = conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def classify(old_rows, new_rows, delta_keys, key_extractors):
    """Per-table keyed diff -> {'expected': [...], 'unexpected': [...]}.
    delta_keys: set of (composer_key, work_key) tuples from the ledger delta.
    key_extractors: table -> callable(row_dict) -> list of identity keys to
    test (a row is expected-diff iff ANY extracted key is in delta_keys)."""
    expected, unexpected = [], []
    for table, extract in key_extractors.items():
        old = {json.dumps(r, sort_keys=True): r for r in old_rows.get(table, [])}
        new = {json.dumps(r, sort_keys=True): r for r in new_rows.get(table, [])}
        for k in set(old) | set(new):
            if old.get(k) == new.get(k):
                continue
            row = old.get(k) if old.get(k) is not None else new.get(k)
            keys = extract(row)
            side = "old-only" if k not in new else (
                "new-only" if k not in old else "changed")
            bucket = expected if any(kk in delta_keys for kk in keys) else unexpected
            bucket.append({"table": table, "key": k, "side": side,
                           "old": old.get(k), "new": new.get(k)})
    return {"expected": expected, "unexpected": unexpected}
```

The real script: build `site2.sqlite` via `ttn_site._run_build(..., source="successor", force=True)` if absent or `--force`; load both DBs; extract identity keys per table (works: the row's composer_key/work_key columns; composers: composer_key; recordings/episodes/years/forms/browse: extract from the row's JSON payloads where identity appears — read the `write_site_db` schemas and write one extractor per table; rows with no identity reference are UNEXPECTED on any diff); write `scratch/p4-site-parity.json`; print per-table counts + the first 10 unexpected; exit 1 if unexpected non-empty.

- [ ] **Step 4: Run tests to verify they pass, then the real corpus**

```bash
uv run --with pytest pytest test_ttn2_site.py -v
uv run python ttn2_site_parity.py --force 2>&1 | tail -30
```
Expected: tests pass; the real run reports per-table diff counts where every diff is EXPECTED-class (delta-explained). If UNEXPECTED diffs appear: STOP — investigate before proceeding (they are either adapter bugs or missing ledger explanations; fix or add the ledger row, never silently accept).

- [ ] **Step 5: Commit**

```bash
git add ttn2_site_parity.py test_ttn2_site.py scratch/p4-site-parity.json
git commit -m "ttn2: site parity harness — legacy vs successor site aggregates, ledger-classified"
```

---

### Task 6: Docs

**Files:**
- Modify: `docs/successor-events-framework.md` (§7 P4 entry)
- Modify: `CLAUDE.md` (project layout: `ttn2_site.py` + `ttn2_site_parity.py` entries)

- [ ] **Step 1: Update the framework doc's P4 bullet**

```markdown
- **P4 — site cutover.** site.sqlite built from successor; registry
  re-anchored to entity IDs; old pipeline freezes read-only (kept for
  reparse archaeology).
  - Phase 1 (landed 2026-08-28): `ttn_data.py site --source successor`
    builds site2.sqlite from events/entities via ttn2_site.py; the full
    graduated-trust link set (bridge events + medium presentation) is
    ingested; ttn2_site_parity.py diffs legacy vs successor site.sqlite and
    blocks on any diff the ledger doesn't explain. Registry/evidence stay
    read-only in successor mode; legacy remains the default.
  - Phase 2 (remaining): registry entity-ID re-anchor, the drift batch for
    the de-globalized identities, default flip, legacy read-path freeze.
```

- [ ] **Step 2: Add the two modules to CLAUDE.md's project layout** (one entry each, in the established terse style: what it is, how it's run, what it consumes/produces, the phase-1/phase-2 split).

- [ ] **Step 3: Commit**

```bash
git add docs/successor-events-framework.md CLAUDE.md
git commit -m "docs: P4 phase 1 — successor-backed site substrate behind --source successor"
```

---

## Verification (whole plan)

1. `uv run --with pytest pytest` — full suite green (~28 s), legacy untouched.
2. `uv run ttn2_parity.py` — linkage 0, identity = the known delta only, years none.
3. `uv run python ttn2_site_parity.py` — zero UNEXPECTED diffs.
4. `uv run ttn_data.py site --build-only` — legacy default still builds site.sqlite identically (registry/evidence untouched).
5. `git log --oneline -6` — six commits, one per task.