"""ttn_qc_audit tests: classifier + scan buckets on synthetic titles."""
import pytest

import ttn_qc_audit as QA


def test_classify_kinds():
    assert QA._classify("CHECK BEFORE USING Concerto Grosso")[0] == "lead"
    assert QA._classify("Waltz in A minor **EXPIRED**")[0] == "trail"
    # free-text note between directive and edge = embedded (parked by design)
    assert QA._classify("Adagio DO NOT USE Pianist awol c,8.13")[0] == "embedded"
    assert QA._classify("Symphony in D major") == (None, None)


def test_classify_phrase_normalisation():
    kind, phrase = QA._classify("Don't use! Gavotte")
    assert kind == "lead" and phrase == "DON'T USE"


def test_scan_buckets_and_dedup():
    rows = [
        ("rp1", "CHECK BEFORE USING Concerto"),
        ("rp1", "Concerto"),                    # same rp: survivor counted once more? no:
                                                # rp appears twice but only one title hits
        ("rp2", "Quartet in C minor, Op 51 No 1"),
        ("rp3", "LATIN KYRIE GLORIA setting"),
    ]
    scan = QA.scan_titles(rows)
    # lead survivor
    assert scan["dirs"][("lead", "CHECK BEFORE USING")] == 1
    # caps run discovered on the Latin-ish title (one per recording per phrase)
    assert sum(scan["caps"].values()) >= 1
    assert any("KYRIE GLORIA" in k for k in scan["caps"])
    # clean title contributes nothing
    assert all(n == 0 for (kd, _), n in scan["dirs"].items() if kd != "lead")


def test_directive_phrases_do_not_double_as_caps_hits():
    # An all-caps directive title must land ONLY in the survivor bucket,
    # not again as a caps-run discovery.
    scan = QA.scan_titles([("rpX", "FAN TASY **EXPIRED**")])
    assert scan["dirs"][("trail", "EXPIRED")] == 1
    assert "EXPIRED FAN" not in " ".join(scan["caps"])
    assert "FAN TASY" in scan["caps"]          # the legit-caps word still surfaces


def test_render_clean_case():
    scan = QA.scan_titles([("rp", "Sonata in G")])
    out = QA.render(scan, 1, {"rp": 3})
    assert "clean:" in out


def test_main_raw_mode_end_to_end(tmp_path, capsys):
    import sqlite3
    db = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, title TEXT)")
    conn.execute("CREATE TABLE segment_events (recording_pid TEXT, track_title TEXT)")
    conn.executemany("INSERT INTO tracks VALUES (?,?,?)",
                     [("e1", 0, "x"), ("e2", 0, "y")])
    conn.executemany("INSERT INTO segment_events VALUES (?,?)",
                     [("rpa", "CHECK BEFORE USING Concerto Grosso in F major, Op 6, No 9"),
                      ("rpb", "Symphony No 5")])
    conn.commit()
    rc = QA.main([str(db), "--raw"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "leading survivors" in out and "CHECK BEFORE USING" in out


def test_main_recmeta_mode_with_stubbed_projection(tmp_path, capsys):
    import sqlite3
    import ttn_project as P
    db = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, title TEXT)")
    conn.executemany("INSERT INTO tracks VALUES (?,?,?)",
                     [("e1", 0, "x"), ("e1", 1, "y")])
    conn.commit()
    orig = P.load
    P.load = lambda c: ({("e1", 0): "rpA", ("e1", 1): "rpA"},
                        {"rpA": ("A. Composer", "**AVOID** Something")}, "ok")
    try:
        rc = QA.main([str(db)])
    finally:
        P.load = orig
    out = capsys.readouterr().out
    assert rc == 0
    assert "leading survivors" in out and "2×" in out   # two airings on rpA


def test_dispatcher_routes_qc_audit(monkeypatch):
    import ttn_curate as C
    captured = {}
    monkeypatch.setattr(QA, "main",
                        lambda argv, _c=captured: _c.setdefault("argv", argv))
    C.main(["qc-audit", "db.sqlite"])
    assert captured["argv"] == ["db.sqlite"]
