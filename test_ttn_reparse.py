import json
import pytest
from ttn_scrape import init_db, rebuild_tracks
from ttn_reparse import diff_tracks, reparse, render_report, main


def test_diff_identical():
    a = [("t", "c", "cl", "[]", "ti", "p")]
    assert diff_tracks(a, a) == (0, 0)


def test_diff_count_gain():
    old = [("t", "c", "cl", "[]", "ti", "p")]
    new = old + [("t2", "c2", "cl2", "[]", "ti2", "p2")]
    assert diff_tracks(old, new) == (1, 0)


def test_diff_count_loss():
    old = [("a",), ("b",)]
    new = [("a",)]
    assert diff_tracks(old, new) == (-1, 0)


def test_diff_content_change_same_count():
    old = [("t", "OldComposer", "cl", "[]", "ti", "p")]
    new = [("t", "NewComposer", "cl", "[]", "ti", "p")]
    assert diff_tracks(old, new) == (0, 1)


def test_diff_empty_old():
    new = [("t", "c", "cl", "[]", "ti", "p")]
    assert diff_tracks([], new) == (1, 0)


def test_diff_empty_new():
    old = [("t", "c", "cl", "[]", "ti", "p")]
    assert diff_tracks(old, []) == (-1, 0)


def test_diff_count_and_content_together():
    # position 0 content-changed, position 1 added
    old = [("t", "Old", "cl", "[]", "ti", "p")]
    new = [("t", "New", "cl", "[]", "ti", "p"),
           ("t2", "c2", "cl2", "[]", "ti2", "p2")]
    assert diff_tracks(old, new) == (1, 1)


_SYN1 = (
    "12:31 AM\n"
    "Wolfgang Amadeus Mozart (1756-1791)\n"
    "Symphony No 40 in G minor, K.550\n"
    "Some Orchestra, Some Conductor (conductor)\n"
    "01:02 AM\n"
    "Ludwig van Beethoven (1770-1827)\n"
    "Coriolan Overture, Op 62\n"
    "Another Orchestra\n"
)
_SYN2 = (
    "11:05 PM\n"
    "Claude Debussy (1862-1918)\n"
    "Clair de lune\n"
    "A Pianist (piano)\n"
)


def _add_episode(conn, pid, synopsis, date, in_sync=True):
    """Insert an episode whose raw_json carries `synopsis`; optionally populate
    its tracks in sync with the parser."""
    raw = json.dumps({"programme": {"pid": pid, "long_synopsis": synopsis}})
    conn.execute(
        "INSERT INTO episodes (pid, broadcast_date, raw_json) VALUES (?, ?, ?)",
        (pid, date, raw))
    if in_sync:
        rebuild_tracks(conn, pid, synopsis)
    conn.commit()


@pytest.fixture
def db():
    c = init_db(":memory:")
    yield c
    c.close()


def test_reparse_in_sync_reports_no_changes(db):
    _add_episode(db, "ep1", _SYN1, "2020-01-01")
    r = reparse(db, dry_run=True)
    assert r["episodes_processed"] == 1
    assert r["tracks_before"] == 2 and r["tracks_after"] == 2
    assert r["content_changed"] == 0
    assert r["count_changes"] == []


def test_reparse_dry_run_does_not_write(db):
    _add_episode(db, "ep1", _SYN1, "2020-01-01")
    db.execute("DELETE FROM tracks WHERE episode_pid='ep1' AND position=1")
    db.commit()                                   # DB now has 1 track, parser wants 2
    r = reparse(db, dry_run=True)
    assert r["count_changes"] == [("ep1", "2020-01-01", 1, 2)]
    assert r["tracks_before"] == 1 and r["tracks_after"] == 2
    assert db.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep1'").fetchone()[0] == 1


def test_reparse_real_run_rebuilds(db):
    _add_episode(db, "ep1", _SYN1, "2020-01-01")
    db.execute("DELETE FROM tracks WHERE episode_pid='ep1' AND position=1")
    db.commit()
    r = reparse(db, dry_run=False)
    assert r["count_changes"] == [("ep1", "2020-01-01", 1, 2)]
    assert db.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep1'").fetchone()[0] == 2


def test_reparse_previews_and_applies_segment_backfill():
    # An allowlisted episode whose long_synopsis can't be parsed: reparse must
    # derive via derive_tracks (segment fallback), so the dry-run PREVIEWS the
    # gain (0 -> 1) and apply writes it. Guards the dry-run/apply parity bug.
    from ttn_segments import ensure_segments_schema
    c = init_db(":memory:")
    ensure_segments_schema(c)
    raw = json.dumps({"programme": {"pid": "b0833vgj",
                                    "long_synopsis": "12.31 Reger: Title"}})
    c.execute("INSERT INTO episodes (pid, broadcast_date, raw_json) "
              "VALUES (?, ?, ?)", ("b0833vgj", "2016-11-21T00:30:00Z", raw))
    c.execute("INSERT INTO segment_events (episode_pid, version_offset, "
              "track_title, composer_name, contributions_json) "
              "VALUES (?, ?, ?, ?, ?)",
              ("b0833vgj", 0, "La Cheminee", "Darius Milhaud",
               json.dumps([{"name": "Darius Milhaud", "role": "Composer"}])))
    c.commit()
    r = reparse(c, dry_run=True)
    assert r["count_changes"] == [("b0833vgj", "2016-11-21", 0, 1)]
    assert c.execute("SELECT COUNT(*) FROM tracks WHERE "
                     "episode_pid='b0833vgj'").fetchone()[0] == 0   # nothing written
    reparse(c, dry_run=False)
    assert c.execute("SELECT composer FROM tracks WHERE "
                     "episode_pid='b0833vgj'").fetchone()[0] == "Darius Milhaud"
    c.close()


def test_reparse_detects_content_change_same_count(db):
    _add_episode(db, "ep1", _SYN1, "2020-01-01")
    db.execute("UPDATE tracks SET composer='WRONG' "
               "WHERE episode_pid='ep1' AND position=0")
    db.commit()
    r = reparse(db, dry_run=True)
    assert r["content_changed"] == 1
    assert r["count_changes"] == []               # count unchanged


def test_reparse_pids_subset_touches_only_named(db):
    _add_episode(db, "ep1", _SYN1, "2020-01-01")
    _add_episode(db, "ep2", _SYN2, "2021-02-02")
    db.execute("DELETE FROM tracks WHERE episode_pid='ep1'")  # ep1 out of sync
    db.execute("DELETE FROM tracks WHERE episode_pid='ep2'")  # ep2 out of sync
    db.commit()
    r = reparse(db, pids=["ep1"], dry_run=False)
    assert r["episodes_processed"] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep1'").fetchone()[0] == 2
    assert db.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep2'").fetchone()[0] == 0


def test_reparse_pids_not_found(db):
    _add_episode(db, "ep1", _SYN1, "2020-01-01")
    r = reparse(db, pids=["nope"], dry_run=True)
    assert r["pids_not_found"] == ["nope"]
    assert r["episodes_processed"] == 0


def test_reparse_empty_pids_processes_nothing(db):
    # An explicit empty filter means "process zero episodes" — distinct from
    # pids=None (the default), which means "all episodes".
    _add_episode(db, "ep1", _SYN1, "2020-01-01")
    r = reparse(db, pids=[], dry_run=True)
    assert r["episodes_processed"] == 0
    assert r["pids_not_found"] == []


def test_reparse_skips_malformed_raw_json(db):
    db.execute("INSERT INTO episodes (pid, broadcast_date, raw_json) "
               "VALUES ('bad', '2020-01-01', 'not json')")
    db.commit()
    r = reparse(db, dry_run=True)
    assert r["skipped"] == [("bad", "malformed raw_json")]
    assert r["episodes_processed"] == 0


def test_render_report_no_changes():
    result = {
        "dry_run": True, "episodes_processed": 3, "pids_not_found": [],
        "skipped": [], "tracks_before": 70, "tracks_after": 70,
        "content_changed": 0, "count_changes": [],
    }
    out = render_report(result, "ttn.sqlite")
    assert "[DRY RUN]" in out
    assert "No changes" in out


def test_render_report_with_changes_and_cache_reminder():
    result = {
        "dry_run": False, "episodes_processed": 2, "pids_not_found": [],
        "skipped": [], "tracks_before": 24, "tracks_after": 63,
        "content_changed": 5,
        "count_changes": [("m000ql1y", "2020-12-25", 1, 40)],
    }
    out = render_report(result, "ttn.sqlite")
    assert "[DRY RUN]" not in out
    assert "24 → 63" in out and "+39" in out
    assert "5 track" in out
    assert "m000ql1y" in out and "1 → 40" in out
    assert "ttn_data.py warm" in out               # cache reminder on real run


def test_render_report_dry_run_with_changes_prompts_apply():
    result = {
        "dry_run": True, "episodes_processed": 1, "pids_not_found": [],
        "skipped": [], "tracks_before": 1, "tracks_after": 40,
        "content_changed": 0,
        "count_changes": [("m000ql1y", "2020-12-25", 1, 40)],
    }
    out = render_report(result, "ttn.sqlite")
    assert "re-run without --dry-run to apply" in out
    assert "ttn_data.py warm" not in out            # no write happened, no reminder
    assert "No changes" not in out                  # there ARE changes


def test_render_report_not_found_and_skipped():
    result = {
        "dry_run": True, "episodes_processed": 1, "pids_not_found": ["nope"],
        "skipped": [("bad", "malformed raw_json")], "tracks_before": 2,
        "tracks_after": 2, "content_changed": 0, "count_changes": [],
    }
    out = render_report(result, "ttn.sqlite")
    assert "1 not found" in out
    assert "1 skipped" in out


def test_main_dry_run_smoke(capsys, tmp_path):
    # main() opens its own connection from a path, so write a file DB.
    path = str(tmp_path / "t.sqlite")
    c = init_db(path)
    raw = json.dumps({"programme": {"pid": "ep1",
        "long_synopsis": _SYN1}})
    c.execute("INSERT INTO episodes (pid, broadcast_date, raw_json) "
              "VALUES ('ep1', '2020-01-01', ?)", (raw,))
    rebuild_tracks(c, "ep1", _SYN1)
    c.commit(); c.close()
    main([path, "--dry-run"])
    out = capsys.readouterr().out
    assert "[DRY RUN]" in out and "No changes" in out
