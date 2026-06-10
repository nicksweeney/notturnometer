import json
import sqlite3

import pytest

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


import ttn_segments
from ttn_segments import (rebuild_segment_events, select_episodes, ingest,
                          reparse_segments, render_ingest, _pid_tail, _coverage)


def _seed_episode(conn, pid="ep1", date="2020-01-01"):
    conn.execute("INSERT INTO episodes (pid, broadcast_date) VALUES (?, ?)",
                 (pid, date))
    conn.commit()


def test_rebuild_inserts_rows(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed_episode(conn)
    rows = rebuild_segment_events(conn, "ep1", SEG_FIXTURE)
    conn.commit()
    assert len(rows) == 2
    n = conn.execute("SELECT COUNT(*) FROM segment_events WHERE episode_pid='ep1'"
                     ).fetchone()[0]
    assert n == 2
    got = conn.execute("SELECT event_pid, composer_mbid FROM segment_events "
                       "WHERE episode_pid='ep1' ORDER BY position").fetchall()
    assert got[0] == ("evt1", "52f19bc1")


def test_rebuild_replaces_not_duplicates(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed_episode(conn)
    rebuild_segment_events(conn, "ep1", SEG_FIXTURE)
    rebuild_segment_events(conn, "ep1", SEG_FIXTURE)   # again
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM segment_events WHERE episode_pid='ep1'"
                     ).fetchone()[0]
    assert n == 2          # replaced, not 4


def _seed(conn, pid, date, fetched_at=None, blob=None):
    conn.execute("INSERT INTO episodes (pid, broadcast_date, segments_fetched_at, "
                 "segments_raw_json) VALUES (?, ?, ?, ?)",
                 (pid, date, fetched_at, blob))


def test_select_gap_picks_never_attempted(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "never", "2020-01-01")                       # never attempted
    _seed(conn, "present", "2020-01-02", "ts", '{"x":1}')    # has blob
    _seed(conn, "absent", "2020-01-03", "ts", None)          # attempted, absent
    conn.commit()
    assert select_episodes(conn) == ["never"]


def test_select_retry_absent_picks_absent_only(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "never", "2020-01-01")
    _seed(conn, "present", "2020-01-02", "ts", '{"x":1}')
    _seed(conn, "absent", "2020-01-03", "ts", None)
    conn.commit()
    assert select_episodes(conn, retry_absent=True) == ["absent"]


def test_select_pids_overrides_and_keeps_existing_only(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "present", "2020-01-02", "ts", '{"x":1}')
    conn.commit()
    # 'present' exists (even though it has a blob); 'ghost' does not
    assert select_episodes(conn, pids=["present", "ghost"]) == ["present"]


def test_select_gap_excludes_pre_2012_segments_floor(tmp_path):
    """The gap never reaches the text-only era: /segments.json has nothing
    before 2012-03-15 (b01d0zy2 is the first episode carrying segments;
    2012-03-14 is confirmed absent), so never-attempted episodes below the
    floor are NOT work — attempting them only wastes BBC round-trips."""
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "pre",      "2010-05-25")   # never attempted, pre-segments era
    _seed(conn, "edge_out", "2012-03-14")   # day before first-ever segments
    _seed(conn, "edge_in",  "2012-03-15")   # first episode that carries segments
    _seed(conn, "new",      "2026-06-10")   # a fresh top-up episode
    conn.commit()
    assert select_episodes(conn) == ["edge_in", "new"]


def test_select_pids_bypasses_the_floor(tmp_path):
    """An explicit PID is always honored, even below the floor (a deliberate
    pre-2012 spot-check must still reach the BBC)."""
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "pre", "2010-05-25")
    conn.commit()
    assert select_episodes(conn, pids=["pre"]) == ["pre"]


def test_select_retry_absent_respects_the_floor(tmp_path):
    """retry-absent is lag catch-up; the pre-2012 era never gains segments,
    so flooring it too keeps re-attempts off the text-only block."""
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "pre_absent",  "2010-05-25", "ts", None)   # attempted-absent, pre-floor
    _seed(conn, "post_absent", "2013-01-01", "ts", None)   # attempted-absent, in-era
    conn.commit()
    assert select_episodes(conn, retry_absent=True) == ["post_absent"]


def _fake_fetch(mapping):
    """mapping: pid -> raw dict | None (absent) | Exception instance (network)."""
    def fetch(pid):
        v = mapping.get(pid)
        if isinstance(v, Exception):
            raise v
        return v
    return fetch


def test_ingest_present_stores_blob_and_rows(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "ep1", "2020-01-01"); conn.commit()
    res = ingest(conn, ["ep1"], _fake_fetch({"ep1": SEG_FIXTURE}), delay=0)
    assert res["present"] == 1 and res["segments"] == 2
    row = conn.execute("SELECT segments_raw_json, segments_fetched_at "
                       "FROM episodes WHERE pid='ep1'").fetchone()
    assert row[0] is not None and row[1] is not None
    assert conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0] == 2


def test_ingest_absent_marks_fetched_null_blob(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "old", "2010-01-01"); conn.commit()
    res = ingest(conn, ["old"], _fake_fetch({"old": None}), delay=0)   # 404
    assert res["absent"] == 1
    row = conn.execute("SELECT segments_raw_json, segments_fetched_at "
                       "FROM episodes WHERE pid='old'").fetchone()
    assert row[0] is None and row[1] is not None
    # and a subsequent bare run does NOT re-select it
    assert select_episodes(conn) == []


def test_ingest_network_failure_leaves_unfetched(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "ep1", "2020-01-01"); conn.commit()
    res = ingest(conn, ["ep1"], _fake_fetch({"ep1": RuntimeError("boom")}), delay=0)
    assert res["failed"] == 1
    row = conn.execute("SELECT segments_fetched_at FROM episodes WHERE pid='ep1'"
                       ).fetchone()
    assert row[0] is None            # still in the gap, retried next run


def test_ingest_calls_progress_per_episode(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "ep1", "2020-01-01")
    _seed(conn, "old", "2010-01-01"); conn.commit()
    seen = []
    ingest(conn, ["ep1", "old"],
           _fake_fetch({"ep1": SEG_FIXTURE, "old": None}),
           delay=0, progress=lambda n, pid, status, nsegs: seen.append(
               (n, pid, status, nsegs)))
    assert seen == [(1, "ep1", "present", 2), (2, "old", "absent", 0)]


def test_ingest_collects_absent_and_coverage(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "ep1", "2020-01-01")
    _seed(conn, "old", "2010-01-01"); conn.commit()
    res = ingest(conn, ["ep1", "old"],
                 _fake_fetch({"ep1": SEG_FIXTURE, "old": None}), delay=0)
    assert res["absent_pids"] == ["old"] and res["failed_pids"] == []
    # ep1 stored a blob; coverage is 1 of the 2 episodes in the DB.
    assert res["coverage_with"] == 1 and res["coverage_total"] == 2


def test_pid_tail_lists_small_sets_and_drops_large():
    assert _pid_tail([]) == ""
    assert _pid_tail(["a", "b"]) == "   [a, b]"
    assert _pid_tail([f"p{i}" for i in range(21)]) == ""   # over the limit


def test_render_ingest_shows_coverage_and_absent_pids():
    result = {"dry_run": False, "attempted": 3, "present": 2, "absent": 1,
              "failed": 0, "segments": 47, "absent_pids": ["b06cb8q0"],
              "failed_pids": [], "coverage_with": 5138, "coverage_total": 5140}
    out = render_ingest(result, "ttn.sqlite")
    assert "coverage:  5,138 / 5,140 episodes have segments (100.0%)" in out
    assert "[b06cb8q0]" in out


def test_coverage_counts_blob_bearing_episodes(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "a", "2020-01-01", blob='{"x":1}')
    _seed(conn, "b", "2020-01-02")            # no blob
    conn.commit()
    assert _coverage(conn) == (1, 2)


def test_ingest_dry_run_writes_nothing(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "ep1", "2020-01-01"); conn.commit()
    ingest(conn, ["ep1"], _fake_fetch({"ep1": SEG_FIXTURE}), delay=0, dry_run=True)
    row = conn.execute("SELECT segments_raw_json, segments_fetched_at "
                       "FROM episodes WHERE pid='ep1'").fetchone()
    assert row == (None, None)
    assert conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0] == 0


def test_ingest_dry_run_makes_no_fetch_calls(tmp_path):
    # A dry-run is a gap PREVIEW: it must not touch the network at all, only
    # report how many episodes WOULD be attempted.
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "ep1", "2020-01-01")
    _seed(conn, "ep2", "2020-01-02")
    conn.commit()
    calls = []

    def spy(pid):
        calls.append(pid)
        return SEG_FIXTURE

    res = ingest(conn, ["ep1", "ep2"], spy, delay=0, dry_run=True)
    assert calls == []                 # zero network fetches
    assert res["attempted"] == 2       # reports the gap size
    assert conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0] == 0


def test_reparse_rederives_from_blob_no_network(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    # store a blob but NO derived rows yet (simulates a derivation-logic change)
    conn.execute("INSERT INTO episodes (pid, broadcast_date, segments_fetched_at, "
                 "segments_raw_json) VALUES (?,?,?,?)",
                 ("ep1", "2020-01-01", "ts", json.dumps(SEG_FIXTURE)))
    conn.commit()
    res = reparse_segments(conn)
    assert res["episodes"] == 1 and res["segments_after"] == 2
    assert conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0] == 2


def test_reparse_skips_null_blob_episodes(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "absent", "2010-01-01", "ts", None)   # attempted, no blob
    conn.commit()
    res = reparse_segments(conn)
    assert res["episodes"] == 0


def test_reparse_dry_run_writes_nothing(tmp_path):
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    conn.execute("INSERT INTO episodes (pid, broadcast_date, segments_fetched_at, "
                 "segments_raw_json) VALUES (?,?,?,?)",
                 ("ep1", "2020-01-01", "ts", json.dumps(SEG_FIXTURE)))
    conn.commit()
    reparse_segments(conn, dry_run=True)
    assert conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0] == 0


def test_render_ingest_summarizes():
    out = ttn_segments.render_ingest(
        {"dry_run": False, "attempted": 3, "present": 2, "absent": 1,
         "failed": 0, "segments": 47, "absent_pids": [], "failed_pids": [],
         "coverage_with": 2, "coverage_total": 3}, "ttn.sqlite")
    assert "present" in out and "47" in out


def test_render_ingest_dry_run_reports_gap_size():
    out = ttn_segments.render_ingest(
        {"dry_run": True, "attempted": 3661, "present": 0, "absent": 0,
         "failed": 0, "segments": 0}, "ttn.sqlite")
    assert "DRY RUN" in out and "3,661" in out
    assert "would attempt" in out.lower()


def test_main_ingest_end_to_end(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "t.sqlite")
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE episodes (pid TEXT PRIMARY KEY, title TEXT,
        subtitle TEXT, broadcast_date TEXT, duration_seconds INTEGER,
        parent_pid TEXT, previous_pid TEXT, next_pid TEXT, raw_json TEXT,
        fetched_at TEXT)""")
    conn.execute("INSERT INTO episodes (pid, broadcast_date) VALUES (?,?)",
                 ("ep1", "2020-01-01"))
    conn.commit(); conn.close()
    monkeypatch.setattr(ttn_segments, "_make_fetch",
                        lambda session: (lambda pid: SEG_FIXTURE))
    # The CLI floors --delay at 0.5s, so no-op the sleep to keep the test fast
    # rather than passing a sub-floor delay (which argparse now rejects).
    monkeypatch.setattr(ttn_segments.time, "sleep", lambda *a, **k: None)
    ttn_segments.main([db, "--delay", "0.5"])
    out = capsys.readouterr().out
    assert "present" in out
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0] == 2


def test_main_reparse_no_network(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "t.sqlite")
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE episodes (pid TEXT PRIMARY KEY, title TEXT,
        subtitle TEXT, broadcast_date TEXT, duration_seconds INTEGER,
        parent_pid TEXT, previous_pid TEXT, next_pid TEXT, raw_json TEXT,
        fetched_at TEXT)""")
    conn.close()
    # ensure schema, then store a blob
    conn = sqlite3.connect(db)
    ttn_segments.ensure_segments_schema(conn)
    conn.execute("INSERT INTO episodes (pid, broadcast_date, segments_fetched_at, "
                 "segments_raw_json) VALUES (?,?,?,?)",
                 ("ep1", "2020-01-01", "ts", json.dumps(SEG_FIXTURE)))
    conn.commit(); conn.close()
    # make any accidental network use explode
    def _boom(session):
        def f(pid):
            raise AssertionError("reparse must not fetch")
        return f
    monkeypatch.setattr(ttn_segments, "_make_fetch", _boom)
    ttn_segments.main([db, "--reparse"])
    assert "re-derive" in capsys.readouterr().out.lower()   # Fix 3: was `or True`
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# Fix 1 — duplicate event_pid must not abort the backfill
# ---------------------------------------------------------------------------

# Two music events sharing the same event_pid in one feed.
SEG_DUP_EVENTPID = {
    "segment_events": [
        {"pid": "dup_evt", "position": 1, "version_offset": 0,
         "segment": {
             "type": "music", "pid": "rec_a", "track_title": "Work A",
             "artist": "Composer A", "duration": 100, "record_id": "r1",
             "record_label": "LBL",
             "primary_contributor": {"pid": "pc_a", "name": "Composer A",
                                     "musicbrainz_gid": "mbid_a"},
             "contributions": []}},
        # Same event_pid — duplicate that must silently collapse
        {"pid": "dup_evt", "position": 2, "version_offset": 60,
         "segment": {
             "type": "music", "pid": "rec_b", "track_title": "Work B",
             "artist": "Composer B", "duration": 200, "record_id": "r2",
             "record_label": "LBL",
             "primary_contributor": {"pid": "pc_b", "name": "Composer B",
                                     "musicbrainz_gid": "mbid_b"},
             "contributions": []}},
    ]
}


def test_ingest_dup_event_pid_completes_without_raising(tmp_path):
    """Two events sharing an event_pid in one feed: ingest completes, episode
    is marked present, and segment_events has exactly ONE row for that pid
    (the dup collapses via INSERT OR IGNORE)."""
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed(conn, "ep_dup", "2022-01-01"); conn.commit()
    res = ingest(conn, ["ep_dup"],
                 _fake_fetch({"ep_dup": SEG_DUP_EVENTPID}), delay=0)
    # The episode must be counted present (not failed)
    assert res["present"] == 1
    assert res["failed"] == 0
    # Exactly ONE row for the shared event_pid (INSERT OR IGNORE dedup)
    n = conn.execute(
        "SELECT COUNT(*) FROM segment_events WHERE event_pid='dup_evt'"
    ).fetchone()[0]
    assert n == 1


# ---------------------------------------------------------------------------
# Fix 4a — composer_name fallback when primary_contributor key is absent
# ---------------------------------------------------------------------------

SEG_NO_PRIMARY_CONTRIBUTOR = {
    "segment_events": [
        {"pid": "evt_npc", "position": 1, "version_offset": 0,
         "segment": {
             "type": "music", "pid": "rec_npc", "track_title": "Folk Tune",
             "artist": "Traditional", "duration": 90, "record_id": "r3",
             "record_label": None,
             # NO primary_contributor key at all
             "contributions": []}},
    ]
}


def test_derive_no_primary_contributor_falls_back_to_artist():
    """derive_segment_events falls back to seg['artist'] when
    primary_contributor is absent."""
    rows = derive_segment_events(SEG_NO_PRIMARY_CONTRIBUTOR)
    assert len(rows) == 1
    r = rows[0]
    assert r["composer_name"] == "Traditional"
    assert r["composer_pid"] is None
    assert r["composer_mbid"] is None


# ---------------------------------------------------------------------------
# Fix 4b — --retry-absent end-to-end through main
# ---------------------------------------------------------------------------

def test_main_retry_absent_flips_episode_to_present(tmp_path, monkeypatch, capsys):
    """An episode previously marked absent (fetched_at set, blob NULL) is
    re-fetched and flipped to present when --retry-absent is used."""
    db = str(tmp_path / "t.sqlite")
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE episodes (pid TEXT PRIMARY KEY, title TEXT,
        subtitle TEXT, broadcast_date TEXT, duration_seconds INTEGER,
        parent_pid TEXT, previous_pid TEXT, next_pid TEXT, raw_json TEXT,
        fetched_at TEXT)""")
    conn.execute("INSERT INTO episodes (pid, broadcast_date) VALUES (?,?)",
                 ("ep_absent", "2022-06-01"))
    conn.commit(); conn.close()
    # Initialise schema and mark the episode absent
    conn = sqlite3.connect(db)
    ttn_segments.ensure_segments_schema(conn)
    conn.execute("UPDATE episodes SET segments_fetched_at=? WHERE pid=?",
                 ("2022-06-02T00:00:00+00:00", "ep_absent"))
    conn.commit(); conn.close()
    # Monkeypatch the fetch to return a real fixture
    monkeypatch.setattr(ttn_segments, "_make_fetch",
                        lambda session: (lambda pid: SEG_FIXTURE))
    # CLI floors --delay at 0.5s; no-op the sleep to keep the test fast.
    monkeypatch.setattr(ttn_segments.time, "sleep", lambda *a, **k: None)
    ttn_segments.main([db, "--retry-absent", "--delay", "0.5"])
    out = capsys.readouterr().out
    assert "present" in out
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT segments_raw_json FROM episodes WHERE pid='ep_absent'"
    ).fetchone()
    assert row[0] is not None        # blob written — no longer absent
    n = conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0]
    assert n == 2                    # segment_events rows derived


# ---------------------------------------------------------------------------
# Fix 4c — render_reparse direct test
# ---------------------------------------------------------------------------

def test_render_reparse_summarizes():
    """render_reparse includes episode count and the before→after segment
    delta in its output."""
    out = ttn_segments.render_reparse(
        {"dry_run": False, "episodes": 5,
         "segments_before": 40, "segments_after": 45},
        "ttn.sqlite")
    assert "5" in out
    assert "40" in out and "45" in out
    assert "re-derive" in out.lower()


# ---------------------------------------------------------------------------
# Fix 4d — rebuild_segment_events delete-then-insert contract (fewer rows)
# ---------------------------------------------------------------------------

def test_rebuild_clears_stale_rows_when_new_derive_is_empty(tmp_path):
    """rebuild_segment_events unconditionally DELETEs old rows before
    inserting the new derive. If the new derive yields zero rows (e.g. all
    non-music), the prior rows must be gone."""
    conn = _fresh_db(tmp_path)
    ensure_segments_schema(conn)
    _seed_episode(conn)
    # Seed rows from the multi-event fixture
    rebuild_segment_events(conn, "ep1", SEG_FIXTURE)
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM segment_events WHERE episode_pid='ep1'"
    ).fetchone()[0] == 2             # baseline: 2 rows present

    # Rebuild from an all-non-music blob
    empty_blob = {"segment_events": [
        {"pid": "sp1", "position": 1, "version_offset": 0,
         "segment": {"type": "speech", "pid": "s1",
                     "track_title": "spoken word"}}
    ]}
    rebuild_segment_events(conn, "ep1", empty_blob)
    conn.commit()
    n = conn.execute(
        "SELECT COUNT(*) FROM segment_events WHERE episode_pid='ep1'"
    ).fetchone()[0]
    assert n == 0                    # stale rows cleared


def test_main_rejects_delay_below_floor():
    # The 0.5s politeness floor is enforced at the CLI: argparse exits before
    # anything opens the DB or touches the network. Lowering it requires a
    # code edit, not a flag.
    with pytest.raises(SystemExit):
        ttn_segments.main(["unused.sqlite", "--delay", "0.3"])


def test_cli_delay_accepts_floor_and_above():
    assert ttn_segments._cli_delay("0.5") == 0.5
    assert ttn_segments._cli_delay("0.8") == 0.8
