"""ttn_work_recordings tests: index/aggregation on synthetic structures."""
import ttn_work_recordings as WR


def _rows():
    # One 2012+ recording aired 3x incl. one pre-2012-bridge-era date; a
    # second work sharing nothing; one unprojected row.
    return [
        ("e1", 0, "2015-01-01", "Trumpet Suite", "Henry Purcell"),
        ("e2", 1, "2016-01-01", "Trumpet Suite (rev)", "Henry Purcell"),
        ("e3", 2, "2021-01-01", "Trumpet Suite", "Henry Purcell"),
        ("e4", 0, "2009-01-01", "Trumpet Suite", "Henry Purcell"),   # text-only era
        ("e5", 0, "2010-01-01", "Duke of Gloucester's trumpet suite", "Henry Purcell"),
    ]


def test_index_groups_by_projected_identity():
    proj = {("e1", 0): "rp1", ("e2", 1): "rp1", ("e3", 2): "rp1"}
    meta = {"rp1": ("Henry Purcell", "Trumpet Suite")}
    g = WR._build_index(_rows(), proj, meta)
    assert len(g) == 2          # Trumpet Suite (3 projected + 1 text) / Gloucester
    main = g[WR.A.resolve_composer_alias(WR.A.canonical_key("Henry Purcell")),
             WR.A.work_title_key("Trumpet Suite", composer="Henry Purcell")]
    assert main["airings"] == 4 and main["text"] == 1
    r1 = main["recs"]["rp1"]
    assert r1 == {"n": 3, "first": "2015-01-01", "last": "2021-01-01"}


def test_search_matches_slug_and_narrows_by_composer():
    proj = {("e1", 0): "rp1"}
    meta = {"rp1": ("Henry Purcell", "Trumpet Suite")}
    groups = WR._build_index(_rows(), proj, meta)
    slugs = {(WR.A.resolve_composer_alias(WR.A.canonical_key("Henry Purcell")),
              WR.A.work_title_key("Trumpet Suite", composer="Henry Purcell")):
             "purcell:trumpet-suite"}
    hits = WR._search(groups, slugs, "trumpet-suite")
    assert hits
    hits_c = WR._search(groups, slugs, "suite", composer="Purcell")
    assert hits_c
    assert not WR._search(groups, slugs, "suite", composer="Bach")


def test_render_panel_lists_recs_and_buckets(capsys):
    proj = {("e1", 0): "rp1", ("e3", 2): "rpX"}     # rpX unknown -> unmatched bucket
    meta = {"rp1": ("Henry Purcell", "Trumpet Suite")}
    groups = WR._build_index([r for r in _rows() if r[0] != "e5"], proj, meta)
    out = WR.render_panel(
        next(iter(groups)), next(iter(groups.values())),
        {"rp1": [300]}, {})
    assert "rp1" in out and "unmatched 1" in out and "text-only 1" in out
    assert "dur[300]" in out


def test_main_end_to_end(tmp_path, capsys):
    import sqlite3
    db = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT)")
    conn.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, title TEXT, composer TEXT)")
    conn.execute("CREATE TABLE segment_events (recording_pid TEXT, duration_seconds INT)")
    conn.executemany("INSERT INTO episodes VALUES (?,?)",
                     [("e1", "2015-01-01T00:30:00Z"), ("e2", "2016-01-01T00:30:00Z")])
    conn.executemany("INSERT INTO tracks VALUES (?,?,?,?)",
                     [("e1", 0, "Trumpet Suite", "Henry Purcell"),
                      ("e2", 0, "Trumpet Suite", "Henry Purcell")])
    conn.executemany("INSERT INTO segment_events VALUES (?,?)", [("rp9", 437)])
    conn.commit()

    real_load = WR.P.load
    WR.P.load = lambda c: ({("e1", 0): "rp9"}, {"rp9": ("Henry Purcell", "Trumpet Suite")}, "ok")
    try:
        rc = WR.main([str(db), "trumpet"])
    finally:
        WR.P.load = real_load
    out = capsys.readouterr().out
    assert rc == 0 and "rp9" in out and "dur[437]" in out


def test_main_no_match_exit_2(tmp_path):
    import sqlite3
    db = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db)
    for ddl in ("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT)",
                "CREATE TABLE tracks (episode_pid TEXT, position INT, title TEXT, composer TEXT)",
                "CREATE TABLE segment_events (recording_pid TEXT, duration_seconds INT)"):
        conn.execute(ddl)
    conn.commit()
    real_load = WR.P.load
    WR.P.load = lambda c: ({}, {}, "ok")
    try:
        rc = WR.main([str(db), "zzzqux"])
    finally:
        WR.P.load = real_load
    assert rc == 2


def test_dispatcher_routes_work_recordings(monkeypatch):
    import ttn_curate as C
    captured = {}
    monkeypatch.setattr(WR, "main", lambda argv, _c=captured: _c.setdefault("argv", argv))
    C.main(["work-recordings", "db.sqlite", "query"])
    assert captured["argv"] == ["db.sqlite", "query"]
