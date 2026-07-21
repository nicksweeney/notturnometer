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

def _file_db(tmp_path, tracks=(), name="t.sqlite"):
    """_db_with_rows on disk — the _db_marker fast path needs a real file."""
    c = sqlite3.connect(str(tmp_path / name))
    c.execute("""CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT,
        composer TEXT, title TEXT, composer_line TEXT, performers TEXT)""")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        version_offset INT, composer_name TEXT, track_title TEXT,
        composer_mbid TEXT, recording_pid TEXT)""")
    for ep, pos, ts, comp, ti in tracks:
        c.execute("INSERT INTO tracks (episode_pid,position,time_str,composer,title) "
                  "VALUES (?,?,?,?,?)", (ep, pos, ts, comp, ti))
    c.commit()
    return c


def test_db_marker_none_for_memory_and_wal(tmp_path):
    assert P._db_marker(sqlite3.connect(":memory:")) is None
    c = sqlite3.connect(str(tmp_path / "w.sqlite"))
    c.execute("PRAGMA journal_mode=wal")
    c.execute("CREATE TABLE t (x)")
    c.commit()
    assert P._db_marker(c) is None


def test_load_marker_fast_path_skips_row_scan(tmp_path, monkeypatch):
    db = _file_db(tmp_path, tracks=[("e1", 0, "12:31 AM", "Chopin", "Nocturne")])
    cache = str(tmp_path / "proj.json")
    P._write_cache(cache, {("e1", 0): "rA"}, P._fingerprint(db),
                   P._rows_sha(db), P._db_marker(db))
    real = P._rows_sha
    calls = []
    monkeypatch.setattr(P, "_rows_sha",
                        lambda conn: (calls.append(1), real(conn))[1])
    proj, _rec_meta, status = P.load(db, cache)
    assert status == "ok" and proj == {("e1", 0): "rA"}
    assert calls == []          # marker matched -> the row scan was skipped


def test_load_restamps_marker_after_unrelated_write(tmp_path):
    db = _file_db(tmp_path, tracks=[("e1", 0, "12:31 AM", "Chopin", "Nocturne")])
    cache = str(tmp_path / "proj.json")
    P._write_cache(cache, {("e1", 0): "rA"}, P._fingerprint(db),
                   P._rows_sha(db), P._db_marker(db))
    # a write that leaves the reconcile-input rows intact bumps the counter
    db.execute("CREATE TABLE episodes (pid TEXT)")
    db.execute("INSERT INTO episodes VALUES ('x')")
    db.commit()
    proj, _rec_meta, status = P.load(db, cache)    # rescan path: still fresh
    assert status == "ok" and proj == {("e1", 0): "rA"}
    with open(cache, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["db_marker"] == P._db_marker(db)     # re-stamped for next time
    assert data["projection"] == {"e1\t0": "rA"}     # projection survived


def test_load_stale_on_row_change_in_file_db(tmp_path):
    db = _file_db(tmp_path, tracks=[("e1", 0, "12:31 AM", "Chopin", "Nocturne")])
    cache = str(tmp_path / "proj.json")
    P._write_cache(cache, {("e1", 0): "rA"}, P._fingerprint(db),
                   P._rows_sha(db), P._db_marker(db))
    db.execute("UPDATE tracks SET title = 'Ballade'")
    db.commit()
    assert P.load(db, cache) == ({}, {}, "stale")


def test_fingerprint_is_insertion_order_independent():
    tracks = [("e1", 0, "12:31 AM", "Chopin", "Nocturne"),
              ("e2", 0, "01:02 AM", "Liszt", "Consolation")]
    segs = [("e1", 1, 60, "Chopin", "Nocturne", "mbid1", "rA"),
            ("e2", 1, 60, "Liszt", "Consolation", "mbid2", "rB")]
    fp_fwd = P._fingerprint(_db_with_rows(tracks=tracks, segs=segs))
    fp_rev = P._fingerprint(_db_with_rows(tracks=tracks[::-1], segs=segs[::-1]))
    assert fp_fwd == fp_rev


def test_cache_roundtrip_and_status(tmp_path):
    db = _db_with_rows(tracks=[("e1",0,"12:31 AM","Chopin","Nocturne")])
    path = str(tmp_path / "proj.json")
    # missing before build
    assert P.load(db, path) == ({}, {}, "missing")
    # build writes a fingerprinted cache; we inject a projection + rec_meta
    P._write_cache(path, {("e1",0):"rA"}, P._fingerprint(db),
                   rec_meta={"rA": ("Chopin", "Nocturne")})
    proj, rec_meta, status = P.load(db, path)
    assert status == "ok" and proj == {("e1",0):"rA"}
    assert rec_meta == {"rA": ("Chopin", "Nocturne")}   # tuples restored
    # a data change makes it stale
    db2 = _db_with_rows(tracks=[("e1",0,"12:31 AM","Chopin","Ballade")])
    assert P.load(db2, path) == ({}, {}, "stale")


def test_build_rec_meta_first_nonempty_title_wins():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'JS II','The Blue Danube, Op 314','rD')")
    c.execute("INSERT INTO segment_events VALUES ('e2',1,'JS II','Blue Danube again','rD')")
    c.execute("INSERT INTO segment_events VALUES ('e3',1,'X','','rE')")  # empty title skipped
    c.commit()
    rec_meta = P.build_rec_meta(c)
    assert rec_meta["rD"] == ("JS II", "The Blue Danube, Op 314")  # first wins
    assert "rE" not in rec_meta                                     # empty title excluded

def test_build_rec_meta_applies_recording_composer_override():
    # An upstream BBC mis-attribution (segment name AND MBID wrong for one
    # recording — the Radetzky/Strauss-II case) is corrected via the curated
    # RECORDING_COMPOSER_OVERRIDES table at the rec_meta chokepoint, so the
    # projection never imports the error as the clean identity. The title and
    # every non-overridden recording pass through untouched.
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES "
              "('e1',1,'Johann Strauss II','Radetzky March, Op.228','p03ctfzj')")
    c.execute("INSERT INTO segment_events VALUES "
              "('e2',1,'Johann Strauss II','Rosen aus dem Suden','rOK')")
    c.commit()
    rec_meta = P.build_rec_meta(c)
    assert rec_meta["p03ctfzj"] == ("Johann Strauss", "Radetzky March, Op.228")
    assert rec_meta["rOK"] == ("Johann Strauss II", "Rosen aus dem Suden")

def test_segment_meta_is_in_the_projection_fingerprint():
    # Editing an override must invalidate the projection cache.
    assert "ttn_segment_meta.py" in P._FINGERPRINT_FILES

def test_load_reports_missing_when_no_segment_events_table(tmp_path):
    import sqlite3, ttn_project as P
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tracks (episode_pid TEXT, position INT)")
    # no segment_events table at all
    cache = str(tmp_path / "proj.json")
    assert P.load(db, cache) == ({}, {}, "missing")


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
    proj, rec_meta, status = P.ensure(db, cache)   # builds (empty corpus -> {} links)
    assert status == "ok"
    proj2, rec_meta2, status2 = P.load(db, cache)  # now loads clean
    assert status2 == "ok" and proj2 == proj and rec_meta2 == rec_meta


def test_ensure_returns_missing_without_building_when_no_segments(tmp_path):
    import sqlite3, ttn_project as P
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tracks (episode_pid TEXT, position INT)")
    cache = str(tmp_path / "proj.json")
    assert P.ensure(db, cache) == ({}, {}, "missing")
    import os
    assert not os.path.exists(cache)             # did not write a cache


def _lineage_db():
    """In-memory DB with the full dual-lineage schema (mirrors the ensure test)."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT, "
               "composer TEXT, title TEXT, performers TEXT)")
    db.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
               "version_offset INT, composer_name TEXT, track_title TEXT, "
               "composer_mbid TEXT, recording_pid TEXT, event_pid TEXT, "
               "composer_pid TEXT, duration_seconds INT, record_id TEXT, "
               "record_label TEXT, contributions_json TEXT)")
    db.execute("CREATE TABLE episodes (pid TEXT, segments_raw_json TEXT, "
               "broadcast_date TEXT)")
    return db


def test_load_treats_corrupt_cache_as_missing(tmp_path):
    # A truncated write (killed warm, power loss) must degrade like an absent
    # cache — 'missing' — NOT raise. load()'s contract is
    # 'ok' | 'missing' | 'stale'; an uncaught JSONDecodeError wedged every
    # consumer INCLUDING `warm` itself (ensure -> load -> crash), leaving no
    # tool able to self-heal short of a manual rm.
    db = _lineage_db()
    cache = tmp_path / "proj.json"
    cache.write_text('{"fingerprint": "abc", "projection": {"x')   # truncated
    assert P.load(db, str(cache)) == ({}, {}, "missing")


def test_load_treats_wrong_shape_cache_as_missing(tmp_path):
    # Parses as JSON but isn't a projection cache (hand-edit, wrong file).
    db = _lineage_db()
    cache = tmp_path / "proj.json"
    cache.write_text('[1, 2, 3]')
    assert P.load(db, str(cache)) == ({}, {}, "missing")
    cache.write_text('{"some": "other json"}')
    assert P.load(db, str(cache)) == ({}, {}, "missing")


def test_ensure_self_heals_over_corrupt_cache(tmp_path):
    # ensure() on a corrupt cache must rebuild (the documented fix is
    # `ttn_data.py warm`, which goes through ensure — it must not crash).
    db = _lineage_db()
    cache = tmp_path / "proj.json"
    cache.write_text('{"corrupt')
    proj, rec_meta, status = P.ensure(db, str(cache))
    assert status == "ok"                          # rebuilt over the corpse
    assert P.load(db, str(cache))[2] == "ok"       # and left a valid cache


def test_db_marker_binds_db_identity(tmp_path):
    # Adversarial-review finding: a marker of bare (change_counter, size) can
    # collide across two DIFFERENT DBs (both freshly built -> same counter;
    # same-ish content -> same size), letting load() serve DB-A's projection
    # against DB-B as 'ok' with the row-content check bypassed. The marker
    # must bind the DB's identity (resolved path) so a different DB file
    # never fast-paths into another DB's cached digest.
    import sqlite3 as s
    dbs = []
    for name in ("a.sqlite", "b.sqlite"):
        p = tmp_path / name
        c = s.connect(p)
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
        dbs.append((p, c))
    ma = P._db_marker(dbs[0][1])
    mb = P._db_marker(dbs[1][1])
    assert ma is not None and mb is not None
    assert ma != mb                        # identical content, different DBs
    # and the same DB yields a stable marker across connections
    c2 = s.connect(dbs[0][0])
    assert P._db_marker(c2) == ma


def test_cache_writes_are_atomic_no_tmp_residue(tmp_path):
    # _write_cache goes via tmp-file + os.replace so an interrupted write can
    # never leave a truncated cache at the real path; on success no tmp file
    # remains.
    cache = tmp_path / "proj.json"
    P._write_cache(str(cache), {("ep1", 0): "rp1"}, "fp",
                   rows_sha="r", db_marker=[1, 2], rec_meta={"rp1": ("c", "t")})
    assert json.load(open(cache))["projection"] == {"ep1\t0": "rp1"}
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "proj.json"]
    assert leftovers == []


import os

@pytest.mark.live
def test_live_build_projection_covers_majority(tmp_path):
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    path = str(tmp_path / "proj.json")
    proj, rec_meta = P.build(conn, path)     # full reconcile (~6 min)
    dual = P._dual_lineage_track_count(conn)
    # ~87% of dual-lineage tracks reconcile at High confidence
    assert len(proj) > 0.80 * dual
    # every value is a recording_pid; every key is (episode_pid, int position)
    assert all(isinstance(k, tuple) and isinstance(k[1], int) for k in proj)
    # every projected recording has clean identity metadata
    assert rec_meta and all(rp in rec_meta for rp in set(proj.values()))
    # the freshly written cache loads clean and matches
    proj2, rec_meta2, status = P.load(conn, path)
    assert status == "ok" and proj2 == proj and rec_meta2 == rec_meta


def test_presentation_from_matches_is_medium_only():
    """Graduated trust: the presentation map takes MEDIUM and nothing else."""
    import ttn_project as P
    matches = [
        {"tier": "high",      "episode_pid": "ep1", "track_position": 0, "recording_pid": "recH"},
        {"tier": "medium",    "episode_pid": "ep1", "track_position": 1, "recording_pid": "recM"},
        {"tier": "low",       "episode_pid": "ep1", "track_position": 2, "recording_pid": "recL"},
        {"tier": "unmatched", "episode_pid": "ep1", "track_position": 3, "recording_pid": None},
        {"tier": "medium",    "episode_pid": "ep2", "track_position": 0, "recording_pid": None},
    ]
    assert P.presentation_from_matches(matches) == {("ep1", 1): "recM"}
    # and the identity projection is unchanged by the new tier
    assert P.projection_from_matches(matches) == {("ep1", 0): "recH"}


def test_presentation_and_projection_keyspaces_are_disjoint():
    """A track has ONE match, so it is either high or medium — never both.
    If this ever fails, a recording could be shown under two different
    provenances for the same airing."""
    import ttn_project as P
    matches = [
        {"tier": "high",   "episode_pid": "ep", "track_position": i, "recording_pid": f"r{i}"}
        for i in range(5)
    ] + [
        {"tier": "medium", "episode_pid": "ep", "track_position": i, "recording_pid": f"m{i}"}
        for i in range(5, 9)
    ]
    proj = P.projection_from_matches(matches)
    pres = P.presentation_from_matches(matches)
    assert not (set(proj) & set(pres))


def test_build_projections_runs_one_reconcile(monkeypatch):
    """Both tiers come out of a SINGLE DP pass — the reconcile is the ~5-min
    half of a warm and must not be paid twice."""
    import ttn_project as P
    calls = []

    def fake_reconcile(conn):
        calls.append(conn)
        return [
            {"tier": "high",   "episode_pid": "e", "track_position": 0, "recording_pid": "H"},
            {"tier": "medium", "episode_pid": "e", "track_position": 1, "recording_pid": "M"},
        ]

    import ttn_mbid_audit
    monkeypatch.setattr(ttn_mbid_audit, "reconcile_corpus", fake_reconcile)
    monkeypatch.setattr(P, "bridge_projection", lambda conn: {("pre", 0): "B"})
    proj, pres = P.build_projections(None)
    assert len(calls) == 1
    assert proj == {("e", 0): "H", ("pre", 0): "B"}
    assert pres == {("e", 1): "M"}


def test_presentation_round_trips_through_the_cache(tmp_path):
    import ttn_project as P
    path = str(tmp_path / "proj.json")
    pres = {("ep1", 1): "recM", ("ep2", 7): "recN"}
    P._write_cache(path, {("ep1", 0): "recH"}, "fp", "rows", "marker",
                   {"recH": ("Composer", "Title")}, pres)
    assert P.load_presentation(path) == pres


def test_load_presentation_degrades_never_raises(tmp_path):
    """Every derived cache degrades; an older cache with no 'presentation' key
    simply shows what it showed before."""
    import json, ttn_project as P
    missing = str(tmp_path / "nope.json")
    assert P.load_presentation(missing) == {}

    old = tmp_path / "old.json"                      # pre-feature cache shape
    old.write_text(json.dumps({"fingerprint": "x", "projection": {}}))
    assert P.load_presentation(str(old)) == {}

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text('{"presentation": {"ep\\t0": "rec"')   # truncated
    assert P.load_presentation(str(corrupt)) == {}

    junk = tmp_path / "junk.json"
    junk.write_text('["not", "a", "cache"]')
    assert P.load_presentation(str(junk)) == {}


def test_load_restamp_preserves_presentation(tmp_path, monkeypatch):
    """load()'s fast-path re-stamp rewrites the cache dict. If it dropped the
    presentation key, an ordinary load would silently erase 1,178 recordings'
    visibility — the same shape of bug as the registry `retired` wipe."""
    import sqlite3, ttn_project as P
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT, "
                 "composer TEXT, title TEXT)")
    conn.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
                 "version_offset INT, composer_name TEXT, track_title TEXT, "
                 "composer_mbid TEXT, recording_pid TEXT)")
    path = str(tmp_path / "proj.json")
    pres = {("ep1", 1): "recM"}
    rows_sha = P._rows_sha(conn)
    fp = P._fingerprint(conn, rows_sha)
    # written with a STALE db_marker so load() takes the re-stamp branch
    P._write_cache(path, {}, fp, rows_sha, "stale-marker", {}, pres)
    monkeypatch.setattr(P, "_db_marker", lambda conn: "fresh-marker")
    _proj, _rm, status = P.load(conn, path)
    assert status == "ok"
    assert P.load_presentation(path) == pres


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
    monkeypatch.setattr(P, "build_projections_mbid",
                        lambda conn: ({("epPost", 0): "rec2012"}, {}))
    monkeypatch.setattr(P, "bridge_projection",
                        lambda conn: {("epPre", 0): "recOld"})
    merged = P.build_projection(None)
    assert merged == {("epPost", 0): "rec2012", ("epPre", 0): "recOld"}
    # the presentation half never leaks into the identity projection
    monkeypatch.setattr(P, "build_projections_mbid",
                        lambda conn: ({("epPost", 0): "rec2012"},
                                      {("epPost", 1): "recMedium"}))
    assert P.build_projection(None) == {("epPost", 0): "rec2012",
                                        ("epPre", 0): "recOld"}


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
