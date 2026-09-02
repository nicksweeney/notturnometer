import json
import sqlite3
from collections import Counter

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
                     (A.work_title_key(v), t, A.work_title_key(t),
                      "legacy-global"))
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
    wk = A.work_title_key("Bolero", "Maurice Ravel")
    assert acc["work_airings"][("maurice ravel", wk)] == [
        ("2020-01-01", "RP1", "p", "e1", 0),   # High: identity + rp from rec_meta
    ]
    # Medium: rp SHOWN, identity RAW — the e2 row keys under its raw text
    # resolved through the ledger ("ravel"), never rec_meta's credit; the
    # presentation link shows the recording only.
    assert acc["work_airings"][("ravel", A.work_title_key("Bolero", "Ravel"))] == [
        ("2005-01-01", "RP1", "p", "e2", 0),
    ]
    # unlinked row: no rp shown, raw text keys through the ledger
    assert acc["work_airings"][("anon", A.work_title_key("Mystery", "Anon"))] == [
        ("2005-01-01", None, "p", "e2", 1),
    ]
    # episode_tracks display: e1 shows the clean rec_meta credit, e2 the raw one
    assert acc["episode_tracks"]["e1"][0][3:5] == ("Maurice Ravel", "Bolero")
    assert acc["episode_tracks"]["e2"][0][3:5] == ("Ravel", "Bolero")
    assert acc["recording_airings"]["RP1"] == [
        ("2020-01-01", "e1", 0), ("2005-01-01", "e2", 0)]
    # composer_dates from modal parse of composer_line, keyed by each row's
    # identity (e1's line under 'maurice ravel', e2's under raw 'ravel')
    ck = "maurice ravel"
    assert acc["composer_dates"][ck] == (1875, 1937)
    assert acc["composer_dates"]["ravel"] == (1685, 1750)


def test_work_entries_t2_registry_wins_and_mints(tmp_path):
    dst = _ledger_db(tmp_path, [])
    comp, ws, wg = L.load_maps(dst)
    rec_meta = {}
    # composer field carries the parsed full name (real rows8 shape); the
    # raw-field identity path then keys under 'maurice ravel'.
    rows8 = [
        ("Bolero", "Maurice Ravel", "Maurice Ravel (1862-1937)", "p",
         "2020-01-01", "e1", 0, "t"),
        ("La Valse", "Maurice Ravel", "Maurice Ravel (1862-1937)", "p",
         "2020-01-01", "e1", 1, "t"),
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
    rows8 = [("Bolero", "Maurice Ravel", "Maurice Ravel (1862-1937)", "p",
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


def test_work_entries_t2_mint_dodges_registry_slug():
    # a mint colliding with a slug already held by the registry suffixes '-2'
    k = ("maurice ravel", "bolero")
    acc = {"work_airings": {k: [("2020-01-01", None, "p", "e1", 0)]}}
    counters = {
        "title_counter": {k: Counter({"Bolero": 1})},
        "composer_counter": {k: Counter({"Maurice Ravel": 1})},
    }
    reg = {"ravel:bolero": {"composer_key": "another", "work_key": "x"}}
    entries = ttn2_site.build_work_entries_t2(acc, counters, reg)
    assert entries[0]["slug"] == "ravel:bolero-2"


def test_composer_entries_t2_mint_dodges_registry_slug():
    ck = "maurice ravel"
    counters = {
        "composer_spelling_counter": {ck: Counter({"Maurice Ravel": 1})},
        "composer_work_keys": {ck: {"bolero"}},
    }
    reg = {"maurice-ravel": {"composer_key": "someone-else"}}
    entries = ttn2_site.build_composer_entries_t2(counters, reg)
    assert entries[0]["slug"] == "maurice-ravel-2"


# --- Task 4: _run_build successor-source e2e ---------------------------------


def _tiny_corpus(tmp_path):
    """The tiny src/successor pair the e2e build consumes: ttn.sqlite with one
    episode, two tracks and one segment_events row whose recording_pid the DP
    matcher links the Mozart track to at HIGH tier (the segment's
    version_offset is 0 == the first track's offset, so temporal cost is 0 and
    the surname+title agree); successor.sqlite via ttn2_ingest.build +
    ttn2_match.link + one benign self-identity ledger row (same shape Task 2's
    helper uses, so load_maps exercises a non-empty ledger); and a minimal
    registry JSON (ttn_site._empty_registry's shape). Returns
    (src, dst, reg_path).

    The successor stack's relative-path defaults (ttn2_site.DB ==
    'successor.sqlite', site_fingerprint_t2's successor.sqlite /
    ttn2_ledger.json slots) resolve against the CALLER's cwd -- the e2e test
    monkeypatch.chdir(tmp_path)s, so these tmp files ARE those defaults."""
    import json

    import ttn2_ingest
    import ttn2_match
    import ttn_site

    src = str(tmp_path / "ttn.sqlite")
    dst = str(tmp_path / "successor.sqlite")
    conn = sqlite3.connect(src)
    # Same minimal schema as test_ttn_site._make_fixture_db (dual-lineage).
    conn.executescript("""
      CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT,
        title TEXT, subtitle TEXT, segments_raw_json TEXT);
      CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_pid TEXT, position INT, time_str TEXT, composer TEXT,
        composer_line TEXT, contributors_json TEXT, title TEXT,
        performers TEXT);
      CREATE TABLE segment_events (episode_pid TEXT, position INT,
        version_offset INT, composer_name TEXT, track_title TEXT,
        composer_mbid TEXT, recording_pid TEXT, event_pid TEXT,
        composer_pid TEXT, duration_seconds INT, record_id TEXT,
        record_label TEXT, contributions_json TEXT);
    """)
    conn.execute("INSERT INTO episodes VALUES ('ep1', '2020-01-01T01:00:00Z', "
                 "'Through the Night', 'Mozart and Beethoven from Berlin', NULL)")
    conn.execute("INSERT INTO tracks (episode_pid, position, time_str, composer, "
                 "composer_line, title, performers) VALUES "
                 "('ep1', 0, '01:00 AM', 'Wolfgang Amadeus Mozart', "
                 "'Wolfgang Amadeus Mozart', 'Requiem', 'LSO')")
    conn.execute("INSERT INTO tracks (episode_pid, position, time_str, composer, "
                 "composer_line, title, performers) VALUES "
                 "('ep1', 1, '02:00 AM', 'Ludwig van Beethoven', "
                 "'Ludwig van Beethoven', 'Symphony No 5', 'Berlin Phil')")
    conn.execute("INSERT INTO segment_events (episode_pid, position, "
                 "version_offset, composer_name, track_title, recording_pid, "
                 "event_pid, duration_seconds, record_label) VALUES "
                 "('ep1', 1, 0, 'Wolfgang Amadeus Mozart', 'Requiem', "
                 "'recM', 'evt1', 1800, 'GBBBC')")
    conn.commit()
    conn.close()

    ttn2_ingest.build(src, dst)
    ttn2_match.link(dst, src)
    led = sqlite3.connect(dst)
    wk = A.work_title_key("Requiem")
    led.execute("INSERT INTO ledger (kind, scope, variant_key, target, "
                "target_key, method, confidence) VALUES "
                "('work_alias', 'global', ?, 'Requiem', ?, 'legacy-global', "
                "'legacy')", (wk, wk))
    led.commit()
    led.close()

    reg_path = tmp_path / "registry.json"
    reg_path.write_text(json.dumps(ttn_site._empty_registry()), encoding="utf-8")
    return src, dst, str(reg_path)


def test_run_build_successor_source_e2e(tmp_path, monkeypatch):
    """Successor source builds site2.sqlite through the UNCHANGED downstream
    builders and passes check_closure."""
    import ttn2_query
    import ttn_project
    import ttn_site
    monkeypatch.chdir(tmp_path)   # successor's relative-path defaults resolve here
    # Keep ttn2_match's bridge re-linker off the real (repo) projection cache:
    # a missing cache degrades to 0 bridge links, which this corpus doesn't need.
    monkeypatch.setattr(ttn_project, "PROJECTION_PATH",
                        str(tmp_path / "no-such-cache.json"))
    # The mint gate (P4 phase 3, task 2) is covered by its own tests in
    # test_ttn_site.py; this test's intent is the downstream builders, so the
    # gate is stubbed to mint-all (a missing projection cache would otherwise
    # defer this corpus's identities -- the safe direction, but not this
    # test's subject).
    monkeypatch.setattr(ttn2_query, "mint_gate_candidate",
                        lambda src, dst, ck, wk: True)
    src, _dst, reg_path = _tiny_corpus(tmp_path)
    monkeypatch.setattr(ttn_site, "REGISTRY_PATH", str(reg_path))
    out_db = str(tmp_path / "site2.sqlite")
    rc = ttn_site._run_build(src, str(reg_path), out_db, force=True,
                             source="successor")
    assert rc == 0
    conn = sqlite3.connect(out_db)
    assert conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] >= 1
    # (brief's snippet compared fetchone()'s tuple to an int -- adjusted to the
    # scalar, the same shape as the works assertion above)
    assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] >= 1
    conn.close()


# --- Task 5: site parity harness ---------------------------------------------


def test_site_fingerprint_t2_covers_db_path(tmp_path):
    """The t2 fingerprint covers the legacy corpus DB (successor mode reads
    raw8/rec_meta from it): a corpus change without a successor re-ingest
    must not fresh-skip a stale site2.sqlite."""
    import ttn_site
    db_a = tmp_path / "a.sqlite"
    db_b = tmp_path / "b.sqlite"
    db_a.write_bytes(b"corpus A")
    db_b.write_bytes(b"corpus B")
    reg = tmp_path / "reg.json"
    reg.write_text("{}", encoding="utf-8")
    fp_a = ttn_site.site_fingerprint_t2(str(reg), db_path=str(db_a))
    fp_b = ttn_site.site_fingerprint_t2(str(reg), db_path=str(db_b))
    assert fp_a != fp_b                          # the corpus DB is covered
    assert fp_a == ttn_site.site_fingerprint_t2(str(reg), db_path=str(db_a))


def test_site_fingerprint_t2_covers_shared_module_bytes(tmp_path, monkeypatch):
    """The shared legacy modules the successor build executes are hashed
    (fix wave 2026-08-29): editing a covered module's bytes must change the
    fingerprint -- an edit to a shared module cannot fresh-skip a stale
    site2.sqlite. ttn_analyze's slot is monkeypatched to a temp file so the
    edit is observable without touching the repo."""
    import ttn_site
    mod = tmp_path / "ttn_analyze.py"
    mod.write_bytes(b"v1")
    monkeypatch.setattr(ttn_site, "_ANALYZE_MODULE_PATH", str(mod))
    reg = tmp_path / "reg.json"
    reg.write_text("{}", encoding="utf-8")
    fp1 = ttn_site.site_fingerprint_t2(str(reg))
    mod.write_bytes(b"v2 -- edited shared module")
    fp2 = ttn_site.site_fingerprint_t2(str(reg))
    assert fp1 != fp2                            # module bytes are covered
    assert fp2 == ttn_site.site_fingerprint_t2(str(reg))


def test_site_parity_classifies_delta_as_expected():
    """A works-row diff whose key is in the ledger delta is EXPECTED; a diff
    outside it is UNEXPECTED (exit 1)."""
    import ttn2_site_parity
    # (adjusted from the brief's snippet: the extractor returns a LIST of
    # identity keys -- the bare 1-tuple would iterate its characters in the
    # membership test -- and rows pair by their stable PK, since row-JSON
    # pairing can never emit a 'changed' entry holding old AND new.)
    report = ttn2_site_parity.classify(
        old_rows={"works": [("k1", 5), ("k2", 3)]},
        new_rows={"works": [("k1", 5), ("k2", 4)]},
        delta_keys={("k2",)},
        key_extractors={"works": lambda r: [(r[0],)]},
        pk_extractors={"works": lambda r: r[0]})
    assert report["unexpected"] == [] and report["expected"] == \
        [{"table": "works", "key": "k2", "side": "changed",
          "old": ("k2", 3), "new": ("k2", 4)}]


def test_site_parity_extractors_on_tiny_dbs(tmp_path):
    """End-to-end over the real site schema (write_site_db + load_table +
    the real per-table extractors): shared row -> no diff; a delta-key row
    diff in works/composers/episodes is EXPECTED; a diff outside the delta
    is UNEXPECTED."""
    import ttn_site
    import ttn2_site_parity

    def works_row(slug, cslug, ck, wk, airings):
        return (slug, cslug, ck, wk, f"Work {wk}", f"Composer {ck}", None,
                airings, 0, airings, "2012-01-01", "2020-01-01", "[]")

    def composers_row(airings, works_json):
        return ("c-2", "ck2", "Composer ck2", airings, 1, works_json, "{}")

    def episodes_row(recording_pid):
        tracks = [{"pos": 0, "work_slug": "w-delta", "composer_slug": "c-2",
                   "recording_pid": recording_pid}]
        return ("ep1", "2020-01-01", "Night", None, json.dumps(tracks),
                "[]", None, None)

    shared = works_row("w-shared", "c-1", "ck1", "wk1", 5)
    delta_old = works_row("w-delta", "c-2", "ck2", "wk2", 3)
    delta_new = works_row("w-delta", "c-2", "ck2", "wk2", 4)
    rogue_old = works_row("w-rogue", "c-3", "ck3", "wk3", 5)
    rogue_new = works_row("w-rogue", "c-3", "ck3", "wk3", 6)
    wj_old = json.dumps([{"slug": "w-delta", "display": "Work wk2",
                          "airings": 3}])
    wj_new = json.dumps([{"slug": "w-delta", "display": "Work wk2",
                          "airings": 4}])

    legacy = str(tmp_path / "legacy.sqlite")
    succ = str(tmp_path / "site2.sqlite")
    ttn_site.write_site_db(legacy, {
        "works": [shared, delta_old, rogue_old],
        "composers": [composers_row(3, wj_old)],
        "episodes": [episodes_row(None)]}, "fp")
    ttn_site.write_site_db(succ, {
        "works": [shared, delta_new, rogue_new],
        "composers": [composers_row(4, wj_new)],
        "episodes": [episodes_row("RP1")]}, "fp")

    old_c = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True)
    new_c = sqlite3.connect(f"file:{succ}?mode=ro", uri=True)
    old = {t: ttn2_site_parity.load_table(old_c, t)
           for t in ("works", "composers", "episodes")}
    new = {t: ttn2_site_parity.load_table(new_c, t)
           for t in ("works", "composers", "episodes")}
    old_c.close()
    new_c.close()

    work_ix, comp_ix = ttn2_site_parity.build_indexes(old, new)
    report = ttn2_site_parity.classify(
        old, new, {("ck2", "wk2")},
        ttn2_site_parity.make_extractors(work_ix, comp_ix),
        pk_extractors=ttn2_site_parity.make_pk_extractors())
    assert {(e["table"], e["key"]) for e in report["expected"]} == {
        ("works", "w-delta"), ("composers", "c-2"), ("episodes", "ep1")}
    assert [(e["table"], e["key"], e["side"]) for e in report["unexpected"]] \
        == [("works", "w-rogue", "changed")]


def test_site_parity_exception_rps_classify_expected():
    """A diff whose serialized old-or-new row contains an exception token
    (a ratified ledger-link recording pid, or a link episode's pid) is
    EXPECTED; a diff with neither stays UNEXPECTED; the empty default keeps
    the existing behavior unchanged."""
    import ttn2_site_parity

    def ep_row(pid, payload):
        return {"pid": pid, "tracks_json": json.dumps(payload)}

    rp_diff = (ep_row("ep1", [{"pos": 0, "recording_pid": "p0AAAAAA"}]),
               ep_row("ep1", [{"pos": 0, "recording_pid": "p0BBBBBB"}]))
    ep_diff = (ep_row("m001556v", [{"pos": 0, "work_slug": "w"}]),
               ep_row("m001556v", [{"pos": 0, "work_slug": "w2"}]))
    rogue = (ep_row("ep9", [{"a": 1}]), ep_row("ep9", [{"a": 2}]))
    old = [rp_diff[0], ep_diff[0], rogue[0]]
    new = [rp_diff[1], ep_diff[1], rogue[1]]
    extractors = {"episodes": lambda r: []}   # no identity keys -> delta silent
    pks = {"episodes": lambda r: r["pid"]}
    base = ttn2_site_parity.classify(
        {"episodes": old}, {"episodes": new}, set(), extractors,
        pk_extractors=pks)
    assert {e["key"] for e in base["unexpected"]} == \
        {"ep1", "m001556v", "ep9"}
    assert base["expected"] == []
    rep = ttn2_site_parity.classify(
        {"episodes": old}, {"episodes": new}, set(), extractors,
        pk_extractors=pks,
        exception_rps=frozenset({"p0AAAAAA", "m001556v"}))
    assert {(e["key"], e["side"]) for e in rep["expected"]} == \
        {("ep1", "changed"), ("m001556v", "changed")}
    assert {e["key"] for e in rep["unexpected"]} == {"ep9"}


def test_accumulate_t2_strips_arranger_tail_via_composer_line(tmp_path):
    """Ruling 2026-08-29: strip_arranger_tail + normalize_composer are
    canonicalization vocabulary and JOIN the successor identity chain before
    ledger resolution (the legacy site chain, ttn_site.accumulate_entities).
    A compound composer credit whose composer_line ends '(arranger)' (the
    real corpus shape) keys under the pre-comma head; the same row through
    the plain legacy chain (strip + normalize + canonical, no alias)
    agrees; a no-line row keeps the compound key (the guard)."""
    dst = _ledger_db(tmp_path, [])
    comp, ws, wg = L.load_maps(dst)
    compound = "Traditional,Edvard Grieg"
    line = "Traditional,Edvard Grieg (1843-1907), Marius Loken (arranger)"
    rows8 = [
        ("Skalhallning", compound, line, "p", "2005-01-01", "e1", 0, "t"),
        ("Skalhallning", compound, "", "p", "2005-01-02", "e2", 0, "t"),
    ]
    acc, counters = ttn2_site.accumulate_entities_t2(
        rows8, comp, ws, wg, {}, {})
    # the plain legacy chain agrees on the stripped row's key
    stripped = A.strip_arranger_tail(compound, line)
    assert A.canonical_key(A.normalize_composer(stripped)) == "traditional"
    wk = A.work_title_key("Skalhallning", stripped)
    assert ("traditional", wk) in acc["work_airings"]
    # guard: no composer_line -> unchanged behavior, the compound key survives
    wk_raw = A.work_title_key("Skalhallning", compound)
    assert ("traditionaledvard grieg", wk_raw) in acc["work_airings"]
    # counters count normalize_composer(stripped), like build_work_index /
    # build_composer_index -- not the raw compound credit
    assert set(counters["composer_spelling_counter"]["traditional"]) == \
        {"Traditional"}
    assert set(counters["composer_spelling_counter"]
               ["traditionaledvard grieg"]) == {compound}


def test_derive_site_inputs_spine_filters_presentation(tmp_path, monkeypatch):
    """Round 5: the successor presentation map is spine-filtered BEFORE
    accumulate (the legacy path's by-construction invariant,
    ttn_site._run_build). A presentation entry whose recording pid is absent
    from the spine must NOT surface as rp_shown (it would leak into
    build_work_rows' n_recordings/n_text_only counters, which read
    work_airings directly); an entry whose rp IS in the spine must."""
    dst = _ledger_db(tmp_path, [])
    comp, ws, wg = L.load_maps(dst)
    rec_meta = {"RP1": ("Maurice Ravel", "Bolero")}
    pres = {("e1", 0): "RP1",    # spine-present
            ("e2", 0): "RPX"}    # non-spine (the p02ggvkg-class leak)
    monkeypatch.setattr(ttn2_site, "load_identity_maps",
                        lambda src: (comp, ws, wg, rec_meta, {}, pres))
    src = str(tmp_path / "src.sqlite")
    c = sqlite3.connect(src)
    c.executescript("""
      CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT);
      CREATE TABLE tracks (episode_pid TEXT, position INTEGER, title TEXT,
        composer TEXT, composer_line TEXT, performers TEXT, time_str TEXT);
    """)
    c.execute("INSERT INTO episodes VALUES ('e1','2005-01-01')")
    c.execute("INSERT INTO episodes VALUES ('e2','2005-01-02')")
    c.execute("INSERT INTO tracks VALUES ('e1',0,'Bolero','Ravel',"
              "'Maurice Ravel','p','1:01 am')")
    c.execute("INSERT INTO tracks VALUES ('e2',0,'Bolero','Ravel',"
              "'Maurice Ravel','p','1:02 am')")
    c.commit()
    c.close()
    registry = {"works": {}, "composers": {}}

    _we, _ce, _r8, acc, _ct, _trp, pres_out, _pids = \
        ttn2_site.derive_site_inputs(src, registry, spine_rps={"RP1"})
    assert pres_out == {("e1", 0): "RP1"}            # RPX filtered pre-accumulate
    shown = {row[6] for rows in acc["episode_tracks"].values() for row in rows}
    assert "RPX" not in shown and shown == {"RP1", None}   # e2 falls back to None
    assert acc["episode_tracks"]["e2"][0][6] is None
    assert "RPX" not in acc["recording_airings"]
    # spine-present rp still shows
    assert acc["episode_tracks"]["e1"][0][6] == "RP1"
    # no spine_rps -> unchanged behavior (the map passes through unfiltered)
    _we, _ce, _r8, acc2, _ct, _trp2, pres_out2, _pids2 = \
        ttn2_site.derive_site_inputs(src, registry)
    assert pres_out2 == pres
    assert acc2["episode_tracks"]["e2"][0][6] == "RPX"
    # and a spine containing RPX keeps it
    _we, _ce, _r8, acc3, _ct, _trp3, pres_out3, _pids3 = \
        ttn2_site.derive_site_inputs(src, registry, spine_rps={"RP1", "RPX"})
    assert pres_out3 == pres
    assert acc3["episode_tracks"]["e2"][0][6] == "RPX"


def test_parity_presentation_diff_rps_classify_expected():
    """Round 5: both sides' rps of a presentation-map diff at a link episode
    join the exception set, and a diff row carrying such an rp classifies
    EXPECTED; an identical diff away from the link episodes stays
    UNEXPECTED."""
    import ttn2_site_parity as SP
    succ_pres = {("m001556v", 0): "p0NEWRP", ("m001556v", 20): "p0OLD20"}
    legacy_pres = {("m001556v", 0): "p0OLDRP", ("m001556v", 20): "p0OLD20"}
    link_eps = {"m001556v"}
    diffs = SP.presentation_diff_rps(succ_pres, legacy_pres, link_eps)
    assert diffs == {("m001556v", 0): ("p0NEWRP", "p0OLDRP")}
    rps = {rp for pair in diffs.values() for rp in pair if rp}
    assert rps == {"p0NEWRP", "p0OLDRP"}
    # a diff row containing a presentation-diff rp -> EXPECTED
    def ep_row(pid, rp):
        return {"pid": pid,
                "tracks_json": json.dumps([{"pos": 0, "recording_pid": rp}])}
    extractors = {"episodes": lambda r: []}
    pks = {"episodes": lambda r: r["pid"]}
    old = [ep_row("m001556v", "p0OLDRP"), ep_row("ep9", "p0OTHER")]
    new = [ep_row("m001556v", "p0NEWRP"), ep_row("ep9", "p0OTHER2")]
    rep = SP.classify({"episodes": old}, {"episodes": new}, set(),
                      extractors, pk_extractors=pks,
                      exception_rps=frozenset(rps))
    assert [(e["key"], e["side"]) for e in rep["expected"]] == \
        [("m001556v", "changed")]
    assert [e["key"] for e in rep["unexpected"]] == ["ep9"]
