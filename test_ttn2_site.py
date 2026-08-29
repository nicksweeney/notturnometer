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
