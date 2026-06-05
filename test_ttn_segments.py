import sqlite3
from ttn_segments import ensure_segments_schema


def _fresh_db(tmp_path):
    """A DB with just the episodes table, as ttn_scrape.init_db would leave it
    (minus the segments columns this tool adds)."""
    conn = sqlite3.connect(str(tmp_path / "t.sqlite"))
    conn.execute("""CREATE TABLE episodes (
        pid TEXT PRIMARY KEY, title TEXT, subtitle TEXT, broadcast_date TEXT,
        duration_seconds INTEGER, parent_pid TEXT, previous_pid TEXT,
        next_pid TEXT, raw_json TEXT, fetched_at TEXT)""")
    conn.commit()
    return conn


def test_ensure_schema_adds_columns_and_table(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    epcols = {r[1] for r in conn.execute("PRAGMA table_info(episodes)")}
    assert "segments_raw_json" in epcols
    assert "segments_fetched_at" in epcols
    secols = {r[1] for r in conn.execute("PRAGMA table_info(segment_events)")}
    assert {"event_pid", "episode_pid", "position", "composer_mbid",
            "recording_pid", "record_label", "contributions_json"} <= secols


def test_ensure_schema_is_idempotent(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    ensure_segments_schema(conn)   # second call must not raise
    n = conn.execute("SELECT COUNT(*) FROM pragma_table_info('episodes') "
                     "WHERE name='segments_raw_json'").fetchone()[0]
    assert n == 1
