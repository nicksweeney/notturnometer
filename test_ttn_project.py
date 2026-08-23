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


def test_db_marker_binds_identity_by_hash_not_raw_path(tmp_path):
    # The marker binds DB identity via a path HASH (raw absolute paths in the
    # cache made load() re-stamp pulled caches with host-local noise --
    # 2026-08-22 cross-host lesson). Properties pinned here:
    #   - marker form: [counter, size, path-hash] -- no raw path anywhere
    #   - stable for the same file across repeated calls
    #   - differs when the DB content changes (counter bump)
    import json
    db_path = tmp_path / "ttn.sqlite"
    db = sqlite3.connect(str(db_path))
    db.execute("CREATE TABLE t (x)")
    db.commit()
    m1 = P._db_marker(db)
    assert m1 is not None
    assert isinstance(m1, list) and len(m1) == 3
    assert isinstance(m1[2], str) and len(m1[2]) == 16   # hex prefix, not a path
    assert "/" not in m1[2]
    assert P._db_marker(db) == m1                        # stable within a process
    raw = json.dumps(m1)
    assert "/private" not in raw and "/home" not in raw and str(tmp_path) not in raw
    db.execute("INSERT INTO t VALUES (1)")               # counter bump
    db.commit()
    assert P._db_marker(db) != m1


def test_load_never_restamps_across_foreign_identity(tmp_path, monkeypatch):
    # A cache written by another host (its db_marker names a different path,
    # in EITHER legacy raw-path or hash form) must be read WITHOUT being
    # rewritten: the re-stamp would dirty bytes that other caches fingerprint
    # over. Same-host markers still re-stamp normally.
    import json as _json

    db = _file_db(tmp_path, tracks=[("e1", 0, "12:31 AM", "Chopin", "Nocturne")])
    real_marker = P._db_marker(db)

    def _cache_with(stored_marker):
        payload = {
            "fingerprint": P._fingerprint(db),
            "rows_sha": P._rows_sha(db),
            "db_marker": stored_marker,
            "projection": {"e1\t0": "rA"},
        }
        p = tmp_path / f"proj-{abs(hash(_json.dumps(stored_marker, default=str)))}.json"
        p.write_text(_json.dumps(payload))
        return str(p)

    # foreign HASH-form identity -> fresh read, bytes untouched
    foreign_hash = list(real_marker)
    foreign_hash[2] = "0" * 16
    foreign = _cache_with(foreign_hash)
    proj, _rm, status = P.load(db, foreign)
    assert status == "ok" and proj == {("e1", 0): "rA"}
    assert _json.load(open(foreign))["db_marker"] == foreign_hash   # NOT re-stamped

    # legacy RAW-path marker naming THIS host -> re-stamps to hash form
    legacy = _cache_with(_db_path_of(db))
    proj, _rm, status = P.load(db, legacy)
    assert status == "ok"
    data_legacy = _json.load(open(legacy))
    assert data_legacy["db_marker"] == real_marker   # upgraded to hash form

    # legacy RAW-path marker naming ANOTHER host -> never rewritten
    alien = _cache_with("/home/pi/notturnometer/ttn.sqlite")
    proj, _rm, status = P.load(db, alien)
    assert status == "ok"
    assert _json.load(open(alien))["db_marker"] == \
        "/home/pi/notturnometer/ttn.sqlite"


def _db_path_of(conn):
    return conn.execute("PRAGMA database_list").fetchone()[2]


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


def test_build_rec_meta_deterministic_title_selection():
    # When several raw segment rows share one canonical recording_pid with
    # differing metadata, rec_meta must pick ONE deterministically (not by
    # undefined scan/insertion order). The tie-breaker is
    # ORDER BY recording_pid, composer_name, track_title, so the alphabetically
    # first (composer, title) wins — stable across DBs and insertion orders.
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'JS II','The Blue Danube, Op 314','rD')")
    c.execute("INSERT INTO segment_events VALUES ('e2',1,'JS II','Blue Danube again','rD')")
    c.execute("INSERT INTO segment_events VALUES ('e3',1,'X','','rE')")  # empty title skipped
    c.commit()
    rec_meta = P.build_rec_meta(c)
    # deterministic: alphabetically-first (composer, title) among rD's rows
    assert rec_meta["rD"] == ("JS II", "Blue Danube again")
    assert "rE" not in rec_meta                                     # empty title excluded


def test_build_rec_meta_deterministic_across_insertion_orders():
    # Regression: the same conflicting rows inserted in two different orders must
    # yield the identical rec_meta entry. The selection is content-deterministic
    # (ORDER BY recording_pid, composer_name, track_title), not scan-order-
    # dependent, so a rebuilt DB or a differently-loaded one can't flip the
    # chosen canonical metadata for a recording_pid.
    def db(rows):
        c = sqlite3.connect(":memory:")
        c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
            composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
        for r in rows:
            c.execute("INSERT INTO segment_events VALUES (?,?,?,?,?)", r)
        c.commit()
        return c
    rows = [('e1',1,'JS II','The Blue Danube, Op 314','rD'),
            ('e2',1,'JS II','Blue Danube again','rD')]
    a = P.build_rec_meta(db(rows))
    b = P.build_rec_meta(db(rows[::-1]))
    assert a == b
    assert a["rD"] == ("JS II", "Blue Danube again")

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

def test_build_rec_meta_applies_recording_title_override():
    # The title analogue of the composer override: a recording whose segment
    # TITLE itself is opus-less (Brahms Symphony No.2, p00r4gc3 = 'Symphony No 2
    # in D') is corrected to the canonical title at the rec_meta chokepoint, so
    # the projection anchors the airings onto the clean work group. The composer
    # and every non-overridden recording pass through untouched.
    import ttn_analyze as A
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES "
              "('e1',1,'Johannes Brahms','Symphony No 2 in D','p00r4gc3')")
    c.execute("INSERT INTO segment_events VALUES "
              "('e2',1,'Johannes Brahms','Symphony no 3 in F major, Op 90','rOK')")
    c.commit()
    rec_meta = P.build_rec_meta(c)
    assert rec_meta["p00r4gc3"] == ("Johannes Brahms", "Symphony no 2 in D major, Op 73")
    assert rec_meta["rOK"] == ("Johannes Brahms", "Symphony no 3 in F major, Op 90")
    # the override title keys to the canonical Op.73 group, not the bare fragment
    assert A.work_title_key(rec_meta["p00r4gc3"][1], "Johannes Brahms") == \
        A.work_title_key("Symphony no.2 in D major (Op.73)", "Johannes Brahms")

def test_sanitize_segment_title_strips_clean_affix_qc_markers():
    # Every clean-affix QC marker observed in the corpus -- EXPIRED (11 recs),
    # AVOID, DO NOT USE, DON'T USE -- leading or trailing, any case/decoration.
    from ttn_segment_meta import sanitize_segment_title as s
    cases = {
        "Concerto for piano and orchestra no. 3 (Op.37) in C minor **EXPIRED**":
            "Concerto for piano and orchestra no. 3 (Op.37) in C minor",
        "EXPIRED Gavotte in A minor": "Gavotte in A minor",
        "EXPIRED Piano Concerto No. 27 in B flat major K.595":
            "Piano Concerto No. 27 in B flat major K.595",
        "Passacaille    EXPIRED": "Passacaille",
        "Prelude (Introduction) [string sextet] from Capriccio - EXPIRED":
            "Prelude (Introduction) [string sextet] from Capriccio",
        'Symphony No.6 (H.343) [1953] "Fantasies symphoniques" EXPIRED':
            'Symphony No.6 (H.343) [1953] "Fantasies symphoniques"',
        "Toccata in C minor BWV.911 for keyboard **expired**":
            "Toccata in C minor BWV.911 for keyboard",
        "Where the Willows Meet  **EXPIRED(**": "Where the Willows Meet",
        "EXPIRED Concert No 8 ('Dans le goût théâtral'), from 'Les gouts réunis'":
            "Concert No 8 ('Dans le goût théâtral'), from 'Les gouts réunis'",
        "Notturno in F sharp minor **AVOID**": "Notturno in F sharp minor",
        "Kyrie and Gloria from 'Missa Sao Sebastiao' **DO NOT USE**":
            "Kyrie and Gloria from 'Missa Sao Sebastiao'",
        "**DON'T USE** A Song at Sunset, Op 138b": "A Song at Sunset, Op 138b",
        "5 Flower Songs for chorus (Op.47) DON'T USE!":
            "5 Flower Songs for chorus (Op.47)",   # keeps the ')'
    }
    for raw, want in cases.items():
        assert s(raw) == want, raw


def test_sanitize_segment_title_leaves_embedded_and_clean_titles_untouched():
    # The anchoring is load-bearing: DO NOT USE also carries free-text QC notes,
    # where the directive is NOT a clean affix (real text sits between it and the
    # end). Those must be returned BYTE-IDENTICAL, not stripped-then-dangling and
    # not whitespace-normalised. A marker-free title is likewise a strict no-op.
    from ttn_segment_meta import sanitize_segment_title as s
    for raw in [
        "Adagio and Allegro (Op.70) **DO NOT USE Pianist awol c,8.13**",
        "Cello Concerto in A minor (Op.129) DO NOT USE - AMADEUS ORCHESTRA",
        "Kaukasian Suite DO NOT USE UNLESS ALREADY IN A MODULE",
        "Suite for clarinet, violin and piano (Op.157b) Do not use without adding 1st mov",
        "Symphony No.16 in C major (K.128)  Please DO NOT USE again  2015 bn",
        "Nocturne for piano in E major, Op.62 No.2",  # marker-free: strict no-op
    ]:
        assert s(raw) == raw, raw
    # idempotent; None/empty pass through
    assert s(s("Passacaille    EXPIRED")) == "Passacaille"
    assert s("") == "" and s(None) is None


def test_build_rec_meta_strips_leaked_expired_marker():
    # b046crcq shape: the segment title for the Beethoven PC3 recording carries a
    # leaked '**EXPIRED**' QC marker; build_rec_meta cleans it so the projection
    # anchors airings onto the clean title (display + work grouping).
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'Ludwig van Beethoven',"
              "'Concerto for piano and orchestra no. 3 (Op.37) in C minor **EXPIRED**','p01p4ll7')")
    c.commit()
    rec_meta = P.build_rec_meta(c)
    assert rec_meta["p01p4ll7"] == (
        "Ludwig van Beethoven",
        "Concerto for piano and orchestra no. 3 (Op.37) in C minor")


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


def test_ensure_builds_when_missing_then_loads_ok(tmp_path, monkeypatch):
    import sqlite3, ttn_project as P
    # neutralize the real recording ledger: this test exercises cache
    # build/load mechanics with a synthetic DB, not alias validation.
    monkeypatch.setattr(P, "load_recording_decisions", lambda *a, **k: {})
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


def test_ensure_self_heals_over_corrupt_cache(tmp_path, monkeypatch):
    # ensure() on a corrupt cache must rebuild (the documented fix is
    # `ttn_data.py warm`, which goes through ensure — it must not crash).
    # neutralize the real recording ledger (synthetic DB, not alias validation).
    monkeypatch.setattr(P, "load_recording_decisions", lambda *a, **k: {})
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
    monkeypatch.setattr(P, "bridge_projection", lambda conn, aliases=None: {("pre", 0): "B"})
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
                        lambda conn, aliases=None: ({("epPost", 0): "rec2012"}, {}))
    monkeypatch.setattr(P, "bridge_projection",
                        lambda conn, aliases=None: {("epPre", 0): "recOld"})
    merged = P.build_projection(None)
    assert merged == {("epPost", 0): "rec2012", ("epPre", 0): "recOld"}
    # the presentation half never leaks into the identity projection
    monkeypatch.setattr(P, "build_projections_mbid",
                        lambda conn, aliases=None: ({("epPost", 0): "rec2012"},
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


# --- Recording-PID equivalence ledger (2026-08-19) ---

def test_load_recording_decisions_reads_seeded_ledger():
    import ttn_project as P
    aliases = P.load_recording_decisions()
    assert aliases == {"p0gg1wdd": "p01yzj4c", "p0gb7ppw": "p0f2rbym"}

def test_resolve_recording_pid_terminal_identity():
    import ttn_project as P
    assert P.resolve_recording_pid("rX", None) == "rX"          # no ledger
    assert P.resolve_recording_pid("rX", {}) == "rX"            # empty ledger
    assert P.resolve_recording_pid("rX", {"a": "b"}) == "rX"    # absent -> self

def test_resolve_recording_pid_seeded_mappings():
    import ttn_project as P
    aliases = P.load_recording_decisions()
    assert P.resolve_recording_pid("p0gg1wdd", aliases) == "p01yzj4c"
    assert P.resolve_recording_pid("p0gb7ppw", aliases) == "p0f2rbym"

def test_resolve_recording_pid_multihop():
    import ttn_project as P
    aliases = {"a": "b", "b": "c", "c": "d"}
    assert P.resolve_recording_pid("a", aliases) == "d"
    assert P.resolve_recording_pid("b", aliases) == "d"
    assert P.resolve_recording_pid("d", aliases) == "d"         # terminal stays

def test_load_recording_decisions_rejects_self_link(tmp_path):
    import json, ttn_project as P
    ledger = tmp_path / "ttn_recording_decisions.json"
    ledger.write_text(json.dumps({"aliases": {"x": "x"}}))
    with pytest.raises(ValueError):
        P.load_recording_decisions(str(ledger))

def test_load_recording_decisions_rejects_cycle(tmp_path):
    import json, ttn_project as P
    ledger = tmp_path / "ttn_recording_decisions.json"
    ledger.write_text(json.dumps({"aliases": {"a": "b", "b": "a"}}))
    with pytest.raises(ValueError):
        P.load_recording_decisions(str(ledger))

def test_load_recording_decisions_rejects_bad_shape(tmp_path):
    import json, ttn_project as P
    ledger = tmp_path / "ttn_recording_decisions.json"
    ledger.write_text(json.dumps({"not_aliases": {}}))          # missing key
    with pytest.raises(ValueError):
        P.load_recording_decisions(str(ledger))
    ledger.write_text(json.dumps({"aliases": {"k": 1}}))        # non-string value
    with pytest.raises(ValueError):
        P.load_recording_decisions(str(ledger))

def test_load_recording_decisions_missing_is_empty(tmp_path):
    import ttn_project as P
    assert P.load_recording_decisions(str(tmp_path / "nope.json")) == {}

def test_projection_from_matches_normalizes_pid():
    import ttn_project as P
    aliases = {"rOld": "rNew"}
    matches = [
        {"episode_pid": "e1", "track_position": 0, "recording_pid": "rOld", "tier": "high"},
        {"episode_pid": "e1", "track_position": 1, "recording_pid": "rKeep", "tier": "high"},
    ]
    assert P.projection_from_matches(matches, aliases) == {
        ("e1", 0): "rNew", ("e1", 1): "rKeep"}
    # without the ledger the raw PID is preserved
    assert P.projection_from_matches(matches) == {
        ("e1", 0): "rOld", ("e1", 1): "rKeep"}

def test_presentation_from_matches_normalizes_pid():
    import ttn_project as P
    aliases = {"rOld": "rNew"}
    matches = [
        {"episode_pid": "e1", "track_position": 1, "recording_pid": "rOld", "tier": "medium"},
    ]
    assert P.presentation_from_matches(matches, aliases) == {("e1", 1): "rNew"}

def test_build_rec_meta_normalizes_key():
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    # both raw PIDs resolve to the same canonical recording -> one rec_meta entry
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'Elgar','Enigma Variations','p0gg1wdd')")
    c.execute("INSERT INTO segment_events VALUES ('e2',1,'Elgar','Enigma Variations','p01yzj4c')")
    c.commit()
    aliases = P.load_recording_decisions()
    rec_meta = P.build_rec_meta(c, aliases)
    assert "p01yzj4c" in rec_meta
    assert "p0gg1wdd" not in rec_meta          # folded into the canonical key
    assert rec_meta["p01yzj4c"] == ("Elgar", "Enigma Variations")

def test_build_rec_meta_leaves_raw_db_untouched():
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'Elgar','Enigma','p0gg1wdd')")
    c.commit()
    P.build_rec_meta(c, P.load_recording_decisions())
    # the source row still carries the raw, non-canonical PID
    raw = c.execute("SELECT recording_pid FROM segment_events").fetchone()[0]
    assert raw == "p0gg1wdd"

def test_fingerprint_includes_recording_decisions_ledger(tmp_path, monkeypatch):
    import json, ttn_project as P
    assert "ttn_recording_decisions.json" in P._FINGERPRINT_FILES
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"aliases": {"p0gg1wdd": "p01yzj4c"}}))
    monkeypatch.setattr(P, "RECORDING_DECISIONS_PATH", str(ledger))
    conn = _db_with_rows(tracks=[("e1", 0, "12:31 AM", "Chopin", "Nocturne")])
    fp1 = P._fingerprint(conn)
    ledger.write_text(json.dumps({"aliases": {"p0gg1wdd": "p0XXXXXX"}}))
    fp2 = P._fingerprint(conn)
    assert fp1 != fp2                          # a ledger edit invalidates the cache

def test_unrelated_recording_identity_unchanged():
    import ttn_project as P
    aliases = P.load_recording_decisions()
    # a recording not in the ledger resolves to itself everywhere
    assert P.resolve_recording_pid("pZZZZZZZ", aliases) == "pZZZZZZZ"
    matches = [{"episode_pid": "e", "track_position": 0,
                "recording_pid": "pZZZZZZZ", "tier": "high"}]
    assert P.projection_from_matches(matches, aliases) == {("e", 0): "pZZZZZZZ"}


def test_bridge_projection_passes_aliases_to_expand_links(monkeypatch):
    """Regression: bridge_projection must forward `aliases` to _expand_links so
    pre-2012 bridge projection PIDs are canonicalized via the recording ledger
    (the same normalization the 2012+ MBID path already gets). The whole bridge
    chain is stubbed so the test needs no real DB or slow in-memory build."""
    import ttn_project as P
    import ttn_bridge as B
    from collections import namedtuple

    Link = namedtuple("Link", "text_rec pid_sig tier method")
    TR = namedtuple("TR", "key")
    PS = namedtuple("PS", "recording_pid")
    link = Link(TR("kA"), PS("recOld"), "trusted", "bridge")

    class _Result:
        trusted = [link]

    aliases = {"recOld": "recNew"}
    airings = {"kA": [("epPre", 0)]}

    monkeypatch.setattr(B, "build_context", lambda conn: None)
    monkeypatch.setattr(B, "pid_signatures", lambda conn, ctx: None)
    monkeypatch.setattr(B, "load_text_units", lambda conn: None)
    monkeypatch.setattr(B, "text_recordings", lambda conn, ctx, units=None: None)
    monkeypatch.setattr(B, "load_decisions", lambda: None)
    monkeypatch.setattr(B, "bridge",
                        lambda text_recs, pid_sigs, decisions: _Result())
    monkeypatch.setattr(B, "airings_by_text_key",
                        lambda conn, ctx, units=None: airings)
    monkeypatch.setattr(B, "text_recording_key", lambda tr: tr.key)

    proj = P.bridge_projection(None, aliases)
    assert proj == {("epPre", 0): "recNew"}      # canonicalized via aliases

    # without the ledger the raw PID is preserved — proves aliases (not a
    # coincidence) is what drives the normalization
    assert P.bridge_projection(None) == {("epPre", 0): "recOld"}


def test_build_rec_meta_prefers_canonical_pid_metadata():
    """Regression (final-review finding 1): when aliases collapse several raw
    PIDs onto one terminal PID, rec_meta must prefer the metadata carried by
    the row whose raw recording_pid IS the canonical terminal, not whichever
    row the scan happened to reach first. Here the non-canonical row carries a
    stale/aliased title; the canonical terminal row carries the reviewed one."""
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    # non-canonical row (aliased away) carries a different, stale title
    c.execute("INSERT INTO segment_events VALUES "
              "('e1',1,'Elgar','Enigma Variations (early take)','p0gg1wdd')")
    # canonical terminal row carries the reviewed clean title
    c.execute("INSERT INTO segment_events VALUES "
              "('e2',1,'Elgar','Enigma Variations','p01yzj4c')")
    c.commit()
    aliases = P.load_recording_decisions()
    rec_meta = P.build_rec_meta(c, aliases)
    # the canonical PID's own metadata wins, deterministically
    assert rec_meta["p01yzj4c"] == ("Elgar", "Enigma Variations")
    assert "p0gg1wdd" not in rec_meta          # folded into the canonical key


def test_build_rec_meta_canonical_preference_is_deterministic():
    """The canonical-source preference must hold regardless of scan order, so
    reverse the insertion order (non-canonical first) and re-assert."""
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES "
              "('e2',1,'Elgar','Enigma Variations','p01yzj4c')")
    c.execute("INSERT INTO segment_events VALUES "
              "('e1',1,'Elgar','Enigma Variations (early take)','p0gg1wdd')")
    c.commit()
    aliases = P.load_recording_decisions()
    rec_meta = P.build_rec_meta(c, aliases)
    assert rec_meta["p01yzj4c"] == ("Elgar", "Enigma Variations")


def test_load_recording_rationale_reads_seeded_ledger():
    """Final-review finding 2: the ledger carries concise reviewed rationale
    for each approved alias, in a clear general format that leaves the
    `aliases` map (the loader contract) untouched."""
    import ttn_project as P
    rationale = P.load_recording_rationale()
    assert set(rationale) == {"p0gg1wdd", "p0gb7ppw"}
    assert "p01yzj4c" in rationale["p0gg1wdd"]   # references the canonical target
    assert "p0f2rbym" in rationale["p0gb7ppw"]
    # the aliases map itself is unchanged by adding rationale
    assert P.load_recording_decisions() == {
        "p0gg1wdd": "p01yzj4c", "p0gb7ppw": "p0f2rbym"}


def test_load_recording_rationale_missing_is_empty(tmp_path):
    import ttn_project as P
    assert P.load_recording_rationale(str(tmp_path / "nope.json")) == {}


def test_validate_recording_aliases_accepts_known_target(tmp_path):
    """Final-review finding 3: a real projection build validates alias targets
    against the recording PIDs actually present in segment_events. A target
    that exists (and whose SOURCE is also present) is accepted."""
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    # both source and target present -> accepted (no raise)
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'Elgar','Enigma','p0gg1wdd')")
    c.execute("INSERT INTO segment_events VALUES ('e2',1,'Elgar','Enigma','p01yzj4c')")
    c.commit()
    assert P.validate_recording_aliases({"p0gg1wdd": "p01yzj4c"}, c) is True


def test_validate_recording_aliases_rejects_typo_target(tmp_path):
    """A typo'd target (not a real recording PID) must be rejected before the
    projection is published, so airings are never canonicalized onto a phantom
    recording — but only when the alias's SOURCE PID is present in this DB."""
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    # source p0gg1wdd IS present, so its typo target must be rejected
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'Elgar','Enigma','p0gg1wdd')")
    c.commit()
    with pytest.raises(ValueError):
        P.validate_recording_aliases({"p0gg1wdd": "p0TYPO99"}, c)


def test_validate_recording_aliases_rejects_typo_terminal_in_multihop(tmp_path):
    """A multi-hop alias whose resolved terminal is a typo is also rejected —
    again only when the alias's SOURCE PID is present in this DB."""
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    # sources a and b present; the multi-hop terminal pTYPO99 is not -> rejected
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'X','T','a')")
    c.execute("INSERT INTO segment_events VALUES ('e2',1,'X','T','b')")
    c.commit()
    with pytest.raises(ValueError):
        P.validate_recording_aliases({"a": "b", "b": "pTYPO99"}, c)


def test_validate_recording_aliases_skips_absent_source(tmp_path):
    """An alias whose SOURCE PID is not in this DB is irrelevant to it — a
    synthetic test DB or partial corpus must not be rejected for a ledger entry
    that doesn't apply here. Even a typo target is tolerated when the source was
    never ingested (the target is simply never checked)."""
    import sqlite3, ttn_project as P
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE segment_events (episode_pid TEXT, position INT,
        composer_name TEXT, track_title TEXT, recording_pid TEXT)""")
    c.execute("INSERT INTO segment_events VALUES ('e1',1,'Elgar','Enigma','p01yzj4c')")
    c.commit()
    # source p0gg1wdd absent -> skipped, no raise (target p0TYPO99 never checked)
    assert P.validate_recording_aliases({"p0gg1wdd": "p0TYPO99"}, c) is True
