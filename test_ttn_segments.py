import json
import sqlite3
from ttn_segments import ensure_segments_schema, derive_segment_events


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


# A fixture blob shaped exactly like the real endpoint (survey-confirmed keys).
SEG_FIXTURE = {
    "segment_events": [
        {"pid": "evt1", "position": 1, "version_offset": 72,
         "is_chapter": False, "has_snippet": False, "title": None,
         "segment": {
             "type": "music", "pid": "rec1", "track_title": "Fantasie no 2",
             "title": "Fantasie no 2", "artist": "Nicola Matteis, Jr",
             "duration": 228, "record_id": "n9958b", "record_label": "GBBBC",
             "track_number": None, "catalogue_number": None, "release_title": None,
             "primary_contributor": {"pid": "p_mat", "name": "Nicola Matteis, Jr",
                                     "musicbrainz_gid": "52f19bc1"},
             "contributions": [
                 {"pid": "p_mat", "name": "Nicola Matteis, Jr", "role": "Composer",
                  "musicbrainz_gid": "52f19bc1"},
                 {"pid": "p_eb", "name": "Veronika Eberle", "role": "Performer",
                  "musicbrainz_gid": None}]}},
        # a non-music event that MUST be filtered out
        {"pid": "evt2", "position": 2, "version_offset": 300,
         "segment": {"type": "speech", "pid": "sp1", "track_title": "chat"}},
        # missing record_label -> None; multi-composer (primary authoritative)
        {"pid": "evt3", "position": 3, "version_offset": 600,
         "segment": {
             "type": "music", "pid": "rec3", "track_title": "Duet",
             "artist": "Heinrich Schutz", "duration": 100, "record_id": "n9",
             "record_label": None,
             "primary_contributor": {"pid": "p_sch", "name": "Heinrich Schutz",
                                     "musicbrainz_gid": "abc"},
             "contributions": [
                 {"pid": "p_sch", "name": "Heinrich Schutz", "role": "Composer",
                  "musicbrainz_gid": "abc"},
                 {"pid": "p_anon", "name": "Anonymous", "role": "Composer",
                  "musicbrainz_gid": None}]}},
    ]
}


def test_derive_maps_fields_and_filters_nonmusic():
    rows = derive_segment_events(SEG_FIXTURE)
    assert len(rows) == 2                       # speech event dropped
    r0 = rows[0]
    assert r0["event_pid"] == "evt1"
    assert r0["position"] == 1
    assert r0["version_offset"] == 72
    assert r0["track_title"] == "Fantasie no 2"
    assert r0["composer_name"] == "Nicola Matteis, Jr"
    assert r0["composer_pid"] == "p_mat"
    assert r0["composer_mbid"] == "52f19bc1"
    assert r0["duration_seconds"] == 228
    assert r0["recording_pid"] == "rec1"
    assert r0["record_id"] == "n9958b"
    assert r0["record_label"] == "GBBBC"


def test_derive_record_label_none_and_contributions_roundtrip():
    rows = derive_segment_events(SEG_FIXTURE)
    r1 = rows[1]
    assert r1["record_label"] is None
    assert r1["composer_name"] == "Heinrich Schutz"   # primary authoritative
    contribs = json.loads(r1["contributions_json"])   # multi-composer preserved
    assert [c["role"] for c in contribs] == ["Composer", "Composer"]
    assert contribs[1]["name"] == "Anonymous"


def test_derive_handles_empty_and_malformed():
    assert derive_segment_events(None) == []
    assert derive_segment_events("") == []
    assert derive_segment_events("not json") == []
    assert derive_segment_events({"segment_events": []}) == []


def test_derive_accepts_json_string():
    rows = derive_segment_events(json.dumps(SEG_FIXTURE))
    assert len(rows) == 2 and rows[0]["event_pid"] == "evt1"
