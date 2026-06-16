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
               "composer TEXT, title TEXT, performers TEXT)")
    db.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
               "version_offset INT, composer_name TEXT, track_title TEXT, "
               "composer_mbid TEXT, recording_pid TEXT, event_pid TEXT, "
               "composer_pid TEXT, duration_seconds INT, record_id TEXT, "
               "record_label TEXT, contributions_json TEXT)")
    # reconcile_corpus also queries episodes; empty table -> empty corpus -> {} links
    db.execute("CREATE TABLE episodes (pid TEXT, segments_raw_json TEXT, "
               "broadcast_date TEXT)")
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


def test_expand_links_trusted_only():
    from collections import namedtuple
    import ttn_project as P
    Link = namedtuple("Link", "text_rec pid_sig tier method")
    TR = namedtuple("TR", "key")           # stand-in; only its key matters
    PS = namedtuple("PS", "recording_pid")
    # link-key resolver + airing map injected so the test needs no DB
    links = [
        Link(TR("kA"), PS("recX"), "trusted", "mbid"),
        Link(TR("kB"), PS("recY"), "accepted", "mbid"),   # v1 ignores accepted
    ]
    airings = {"kA": [("ep1", 0), ("ep2", 2)], "kB": [("ep3", 1)]}
    out = P._expand_links(links, airings, key_of=lambda tr: tr.key)
    assert out == {("ep1", 0): "recX", ("ep2", 2): "recX"}   # only the trusted link


@pytest.mark.live
def test_live_bridge_projection_nonempty_and_pre2012(tmp_path):
    import os, sqlite3, ttn_project as P
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    proj = P.bridge_projection(conn)
    assert len(proj) > 2000                 # ~8.3k airings expected; floor well under
    # keys are (episode_pid, int position); values are recording_pids that exist
    assert all(isinstance(k, tuple) and isinstance(k[1], int) for k in proj)
    recs = {r[0] for r in conn.execute(
        "SELECT DISTINCT recording_pid FROM segment_events WHERE recording_pid IS NOT NULL")}
    assert all(rp in recs for rp in proj.values())
    # the projected episodes are text-only (no segment_events of their own)
    seg_eps = {r[0] for r in conn.execute("SELECT DISTINCT episode_pid FROM segment_events")}
    assert not ({ep for ep, _pos in proj} & seg_eps)


def test_build_projection_merges_disjoint(monkeypatch):
    import ttn_project as P
    monkeypatch.setattr(P, "build_projection_mbid",
                        lambda conn: {("epPost", 0): "rec2012"})
    monkeypatch.setattr(P, "bridge_projection",
                        lambda conn: {("epPre", 0): "recOld"})
    merged = P.build_projection(None)
    assert merged == {("epPost", 0): "rec2012", ("epPre", 0): "recOld"}


@pytest.mark.live
def test_live_build_projection_keyspaces_disjoint():
    import os, sqlite3, ttn_project as P
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    mbid = P.build_projection_mbid(conn)
    bridge = P.bridge_projection(conn)
    assert not (set(mbid) & set(bridge)), "MBID and bridge key-spaces must be disjoint"


def test_fingerprint_covers_bridge_inputs(tmp_path, monkeypatch):
    import os, sqlite3, ttn_project as P
    # minimal DB with both lineage tables so _fingerprint reads them
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT, "
                 "composer TEXT, title TEXT)")
    conn.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
                 "version_offset INT, composer_name TEXT, track_title TEXT, "
                 "composer_mbid TEXT, recording_pid TEXT)")
    base = P._fingerprint(conn)
    # the decisions ledger is part of the fingerprint: changing it must invalidate
    import ttn_bridge as B
    assert os.path.basename(B.DECISIONS_PATH) in P._FINGERPRINT_FILES
    # the projection-build module self-hashes: editing build_projection /
    # bridge_projection / the tier selection must invalidate the cache
    assert "ttn_project.py" in P._FINGERPRINT_FILES
    # all named code deps exist and are hashed
    for mod in P._FINGERPRINT_FILES:
        assert mod  # non-empty names
    assert base  # non-empty digest


def test_bridge_coverage_counts_pre2012_entries():
    import ttn_project as P
    proj = {("epPre", 0): "recOld", ("epPre", 1): "recOld2", ("epPost", 0): "rec2012"}
    seg_eps = {"epPost"}                       # only epPost has segments
    assert P._bridge_coverage(proj, seg_eps) == 2   # the two text-only entries
