import os
import sqlite3

import ttn_analyze as A
import ttn_warm as Warm


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT);"
        "CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "episode_pid TEXT, composer TEXT, composer_line TEXT, title TEXT);")
    eps = [("e1", "2016-05-01T01:00:00Z"), ("e2", "2017-06-02T01:00:00Z")]
    conn.executemany("INSERT INTO episodes VALUES (?, ?)", eps)
    tracks = [
        ("e1", "Beethoven", "Beethoven", "Symphony no 5 in C minor, Op 67"),
        ("e1", "Mozart", "Mozart", "Symphony no 40 in G minor, K.550"),
        ("e2", "Brahms", "Brahms", "Symphony no 1 in C minor, Op 68"),
    ]
    conn.executemany(
        "INSERT INTO tracks (episode_pid, composer, composer_line, title) "
        "VALUES (?, ?, ?, ?)", tracks)
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
    assert [label for label, _, _ in first] == ["corpus", "2016", "2017", "audit"]
    assert all(status == "computed" for _, status, _ in first)
    assert os.path.exists(str(cache))

    second = Warm.warm_all(str(db), cache_path=str(cache))
    assert all(status == "hit" for _, status, _ in second)


def test_warm_rows_match_main_summary_path(tmp_path):
    # The warmer's row set for the corpus slot must be byte-identical (by
    # fingerprint) to what ttn_analyze.main feeds --summary, or the warmed
    # slot would never be read back.
    db = tmp_path / "t.sqlite"
    _make_db(str(db))
    conn = sqlite3.connect(str(db))
    try:
        warm_rows = Warm.slice_rows(conn, None)
        sql = ("SELECT t.composer, t.composer_line, t.title, t.episode_pid "
               "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")
        main_rows = [
            (A.strip_arranger_tail(c, cl), title, pid)
            for c, cl, title, pid in conn.execute(sql).fetchall()]
    finally:
        conn.close()
    assert (A._summary_data_fingerprint(warm_rows)
            == A._summary_data_fingerprint(main_rows))


def test_warm_all_includes_audit_slot(tmp_path):
    import json
    db = tmp_path / "t.sqlite"
    cache = tmp_path / "cache.json"
    _make_db(str(db))
    Warm.warm_all(str(db), cache_path=str(cache))
    payload = json.load(open(str(cache)))
    kinds = {k.split(":", 1)[0] for k in payload["entries"]}
    assert "summary" in kinds and "audit" in kinds
