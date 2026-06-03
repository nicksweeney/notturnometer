import json
import pytest
from ttn_scrape import init_db, rebuild_tracks
from ttn_reparse import diff_tracks, reparse


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
