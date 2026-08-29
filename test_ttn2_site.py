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
    import ttn_project
    import ttn_site
    monkeypatch.chdir(tmp_path)   # successor's relative-path defaults resolve here
    # Keep ttn2_match's bridge re-linker off the real (repo) projection cache:
    # a missing cache degrades to 0 bridge links, which this corpus doesn't need.
    monkeypatch.setattr(ttn_project, "PROJECTION_PATH",
                        str(tmp_path / "no-such-cache.json"))
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
