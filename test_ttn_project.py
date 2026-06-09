import json, sqlite3
import pytest
import ttn_project as P

def _db_with_rows(tracks=(), segs=()):
    """tracks: (episode_pid, position, time_str, composer, title).
    segs: (episode_pid, position, version_offset, composer_name, track_title,
           composer_mbid, recording_pid)."""
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT,
        composer TEXT, title TEXT, composer_line TEXT, performers TEXT)""")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        version_offset INT, composer_name TEXT, track_title TEXT,
        composer_mbid TEXT, recording_pid TEXT)""")
    for ep, pos, ts, comp, ti in tracks:
        c.execute("INSERT INTO tracks (episode_pid,position,time_str,composer,title) "
                  "VALUES (?,?,?,?,?)", (ep, pos, ts, comp, ti))
    for row in segs:
        c.execute("INSERT INTO segment_events (episode_pid,position,version_offset,"
                  "composer_name,track_title,composer_mbid,recording_pid) "
                  "VALUES (?,?,?,?,?,?,?)", row)
    c.commit()
    return c

def test_projection_from_matches_keeps_high_only():
    matches = [
        {"episode_pid":"e1","track_position":0,"recording_pid":"rA","tier":"high"},
        {"episode_pid":"e1","track_position":1,"recording_pid":"rB","tier":"medium"},
        {"episode_pid":"e2","track_position":0,"recording_pid":"rC","tier":"high"},
        {"episode_pid":"e2","track_position":1,"recording_pid":None,"tier":"unmatched"},
    ]
    proj = P.projection_from_matches(matches)
    assert proj == {("e1",0):"rA", ("e2",0):"rC"}

def test_fingerprint_changes_when_a_track_changes_else_stable():
    db1 = _db_with_rows(tracks=[("e1",0,"12:31 AM","Chopin","Nocturne")])
    fp_a = P._fingerprint(db1)
    fp_a2 = P._fingerprint(db1)
    db2 = _db_with_rows(tracks=[("e1",0,"12:31 AM","Chopin","Ballade")])  # title changed
    fp_b = P._fingerprint(db2)
    assert fp_a == fp_a2          # stable on identical data
    assert fp_a != fp_b          # sensitive to a track edit

def test_cache_roundtrip_and_status(tmp_path):
    db = _db_with_rows(tracks=[("e1",0,"12:31 AM","Chopin","Nocturne")])
    path = str(tmp_path / "proj.json")
    # missing before build
    assert P.load(db, path) == ({}, "missing")
    # build writes a fingerprinted cache; we inject a projection to persist
    P._write_cache(path, {("e1",0):"rA"}, P._fingerprint(db))
    proj, status = P.load(db, path)
    assert status == "ok" and proj == {("e1",0):"rA"}
    # a data change makes it stale
    db2 = _db_with_rows(tracks=[("e1",0,"12:31 AM","Chopin","Ballade")])
    assert P.load(db2, path) == ({}, "stale")

def test_load_reports_missing_when_no_segment_events_table(tmp_path):
    import sqlite3, ttn_project as P
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tracks (episode_pid TEXT, position INT)")
    # no segment_events table at all
    cache = str(tmp_path / "proj.json")
    proj, status = P.load(db, cache)
    assert (proj, status) == ({}, "missing")


def test_ensure_builds_when_missing_then_loads_ok(tmp_path):
    import sqlite3, ttn_project as P
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT, "
               "composer TEXT, title TEXT)")
    db.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
               "version_offset INT, composer_name TEXT, track_title TEXT, "
               "composer_mbid TEXT, recording_pid TEXT)")
    # reconcile_corpus also queries episodes; empty table -> empty corpus -> {} links
    db.execute("CREATE TABLE episodes (pid TEXT, segments_raw_json TEXT)")
    cache = str(tmp_path / "proj.json")
    proj, status = P.ensure(db, cache)           # builds (empty corpus -> {} links)
    assert status == "ok"
    proj2, status2 = P.load(db, cache)           # now loads clean
    assert status2 == "ok" and proj2 == proj


def test_ensure_returns_missing_without_building_when_no_segments(tmp_path):
    import sqlite3, ttn_project as P
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tracks (episode_pid TEXT, position INT)")
    cache = str(tmp_path / "proj.json")
    proj, status = P.ensure(db, cache)
    assert (proj, status) == ({}, "missing")
    import os
    assert not os.path.exists(cache)             # did not write a cache


import os

@pytest.mark.live
def test_live_build_projection_covers_majority(tmp_path):
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    path = str(tmp_path / "proj.json")
    proj = P.build(conn, path)               # full reconcile (~6 min)
    dual = P._dual_lineage_track_count(conn)
    # ~87% of dual-lineage tracks reconcile at High confidence
    assert len(proj) > 0.80 * dual
    # every value is a recording_pid; every key is (episode_pid, int position)
    assert all(isinstance(k, tuple) and isinstance(k[1], int) for k in proj)
    # the freshly written cache loads clean and matches
    proj2, status = P.load(conn, path)
    assert status == "ok" and proj2 == proj
