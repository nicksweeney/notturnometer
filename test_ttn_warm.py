import json, os, sqlite3

import pytest

import ttn_analyze as A
import ttn_project as P
import ttn_warm as Warm


def _make_db(path):
    # No segment_events table: P.ensure returns ({}, "missing") immediately,
    # so warm_all proceeds with an empty projection (pass-through) without
    # attempting to build the full DP cache against this minimal schema.
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT);"
        "CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "episode_pid TEXT, position INT, composer TEXT, composer_line TEXT, title TEXT);")
    eps = [("e1", "2016-05-01T01:00:00Z"), ("e2", "2017-06-02T01:00:00Z")]
    conn.executemany("INSERT INTO episodes VALUES (?, ?)", eps)
    tracks = [
        ("e1", 0, "Beethoven", "Beethoven", "Symphony no 5 in C minor, Op 67"),
        ("e1", 1, "Mozart", "Mozart", "Symphony no 40 in G minor, K.550"),
        ("e2", 0, "Brahms", "Brahms", "Symphony no 1 in C minor, Op 68"),
    ]
    conn.executemany(
        "INSERT INTO tracks (episode_pid, position, composer, composer_line, title) "
        "VALUES (?, ?, ?, ?, ?)", tracks)
    conn.commit()
    conn.close()


def test_corpus_years_derived_from_db(tmp_path):
    db = tmp_path / "t.sqlite"
    _make_db(str(db))
    conn = sqlite3.connect(str(db))
    try:
        assert Warm.corpus_years(conn) == [2016, 2017]
    finally:
        conn.close()


def test_warm_all_computes_then_hits(tmp_path):
    db = tmp_path / "t.sqlite"
    cache = tmp_path / "cache.json"
    _make_db(str(db))

    first = Warm.warm_all(str(db), cache_path=str(cache))
    # corpus + 2016 + 2017
    assert [label for label, _, _ in first] == ["corpus", "2016", "2017"]
    assert all(status == "computed" for _, status, _ in first)
    assert os.path.exists(str(cache))

    second = Warm.warm_all(str(db), cache_path=str(cache))
    assert all(status == "hit" for _, status, _ in second)


def test_warm_rows_match_main_summary_path(tmp_path):
    # The warmer's row set for the corpus slot must be byte-identical (by
    # fingerprint) to what ttn_analyze.main feeds --summary, or the warmed
    # slot would never be read back. No projection (empty DB) — pass-through only.
    db = tmp_path / "t.sqlite"
    _make_db(str(db))
    conn = sqlite3.connect(str(db))
    try:
        warm_rows = Warm.slice_rows(conn, None, {}, {})
        sql = ("SELECT t.composer, t.composer_line, t.title, t.episode_pid, t.position "
               "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")
        main_rows = [
            (A.strip_arranger_tail(c, cl), t, pid)
            for c, cl, t, pid, _pos in conn.execute(sql).fetchall()]
    finally:
        conn.close()
    assert (A._summary_data_fingerprint(warm_rows)
            == A._summary_data_fingerprint(main_rows))


def test_warm_all_includes_summary_slot(tmp_path):
    import json
    db = tmp_path / "t.sqlite"
    cache = tmp_path / "cache.json"
    _make_db(str(db))
    Warm.warm_all(str(db), cache_path=str(cache))
    payload = json.load(open(str(cache)))
    kinds = {k.split(":", 1)[0] for k in payload["entries"]}
    assert "summary" in kinds


def _seed(db):
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT, "
              "segments_raw_json TEXT)")
    c.execute("""CREATE TABLE tracks (id INTEGER PRIMARY KEY, episode_pid TEXT,
        position INT, time_str TEXT, composer TEXT, composer_line TEXT,
        title TEXT, performers TEXT)""")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        version_offset INT, composer_name TEXT, track_title TEXT,
        composer_mbid TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO episodes VALUES ('e1','2015-01-01T00:30:00Z','{}')")
    c.execute("INSERT INTO episodes VALUES ('e2','2015-02-01T00:30:00Z','{}')")
    c.execute("INSERT INTO tracks (episode_pid,position,composer,composer_line,title,performers) "
              "VALUES ('e1',0,'Johann Strauss II','Johann Strauss II','Blue Danube (Op.314) with chorus','x')")
    c.execute("INSERT INTO tracks (episode_pid,position,composer,composer_line,title,performers) "
              "VALUES ('e2',0,'Johann Strauss II','Johann Strauss II','An der schonen blauen Donau','x')")
    c.execute("INSERT INTO segment_events VALUES ('e1',1,1800,'Johann Strauss II','The Blue Danube, Op 314','mS','rD')")
    c.execute("INSERT INTO segment_events VALUES ('e2',1,1800,'Johann Strauss II','The Blue Danube, Op 314','mS','rD')")
    c.commit(); c.close()


def test_warm_builds_projected_slot_that_summary_hits(tmp_path, monkeypatch):
    db = str(tmp_path / "t.sqlite")
    _seed(db)
    cache = str(tmp_path / "proj.json")
    sumcache = str(tmp_path / "summary_cache.json")
    monkeypatch.setattr(P, "PROJECTION_PATH", cache)
    monkeypatch.setattr(A, "summary_cache_path", lambda: sumcache)
    results = Warm.warm_all(db, cache_path=sumcache)
    labels = {lbl for lbl, _, _ in results}
    assert "corpus" in labels
    # the projected corpus summary collapsed the churn -> Distinct works 1
    conn = sqlite3.connect(db)
    projection, _ = P.load(conn, cache)
    rec_meta = A.build_rec_meta(conn)
    rows = [(A.strip_arranger_tail(c, cl), t, pid) for c, cl, t, pid in
            A._project_summary_rows(conn.execute(
                "SELECT t.composer,t.composer_line,t.title,t.episode_pid,t.position FROM tracks t"),
                projection, rec_meta)]
    stats, was_cached = A.summary_for_rows(rows, sumcache)
    assert was_cached is True                      # warm already populated this slot
    assert stats["n_distinct_works"] == 1


@pytest.mark.live
def test_live_warm_noop_is_stable():
    import os, sqlite3
    if not os.path.exists("ttn.sqlite") or not os.path.exists(P.PROJECTION_PATH):
        pytest.skip("needs live DB + built projection cache")
    conn = sqlite3.connect("ttn.sqlite")
    _, status = P.load(conn, P.PROJECTION_PATH)
    assert status == "ok"                            # already current
    results = Warm.warm_all("ttn.sqlite")
    assert all(st == "hit" for _, st, _ in results)  # no recompute on a warm corpus
