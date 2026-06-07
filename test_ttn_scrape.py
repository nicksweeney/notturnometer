"""Tests for ttn_scrape seed discovery (pure selection logic; no network)."""
import datetime as dt

import pytest

from ttn_scrape import (
    _choose_seed_pid,
    _resolve_seed_date,
    init_db,
    parse_tracks,
    rebuild_tracks,
)

UTC = dt.timezone.utc


def _b(pid, start):
    return {"start": start, "programme": {"pid": pid}}


def test_choose_seed_prefers_most_recent_aired():
    # now is midday 2026-06-02 UTC; the two 00:30 broadcasts have aired,
    # the 06-03/06-04 ones have not.
    now = dt.datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bs = [
        _b("aired_old", "2026-06-01T00:30:00+01:00"),
        _b("aired_new", "2026-06-02T00:30:00+01:00"),   # most recent aired
        _b("future1",   "2026-06-03T00:30:00+01:00"),
        _b("future2",   "2026-06-04T00:30:00+01:00"),
    ]
    assert _choose_seed_pid(bs, now) == "aired_new"


def test_choose_seed_falls_back_to_soonest_upcoming_when_none_aired():
    # now is before any listed broadcast → none have aired; take the soonest.
    now = dt.datetime(2026, 6, 1, 23, 0, tzinfo=UTC)
    bs = [
        _b("future_late", "2026-06-04T00:30:00+01:00"),
        _b("future_soon", "2026-06-02T00:30:00+01:00"),
    ]
    assert _choose_seed_pid(bs, now) == "future_soon"


def test_choose_seed_empty_returns_none():
    now = dt.datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    assert _choose_seed_pid([], now) is None


def test_choose_seed_ignores_entry_without_pid():
    now = dt.datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bs = [{"start": "2026-06-02T00:30:00+01:00", "programme": {}}]
    assert _choose_seed_pid(bs, now) is None


# ---------- seed-date anchoring (--days) ------------------------------------


def test_resolve_seed_date_reads_cached_seed_without_network():
    # A cached seed: --days must anchor on the seed's broadcast date, so the
    # resolver returns it straight from the DB and never touches `session`.
    c = init_db(":memory:")
    c.execute(
        "INSERT INTO episodes (pid, broadcast_date) VALUES (?, ?)",
        ("b07b27lk", "2016-05-16T00:30:00+01:00"))
    c.commit()
    # session=None proves the cached path makes no request.
    got = _resolve_seed_date(None, c, "b07b27lk")
    assert got == dt.datetime(2016, 5, 16, 0, 30,
                              tzinfo=dt.timezone(dt.timedelta(hours=1)))
    c.close()


def test_resolve_seed_date_anchors_cutoff_to_seed_not_today():
    # Regression for the --days-from-today bug: with a 2016 seed, the cutoff is
    # `seed_date - days`, so 1523 days reaches 2012-03-15 regardless of `now`.
    c = init_db(":memory:")
    c.execute(
        "INSERT INTO episodes (pid, broadcast_date) VALUES (?, ?)",
        ("b07b27lk", "2016-05-16T00:30:00+01:00"))
    c.commit()
    anchor = _resolve_seed_date(None, c, "b07b27lk")
    cutoff = anchor - dt.timedelta(days=1523)
    assert cutoff.date() == dt.date(2012, 3, 15)
    c.close()


def test_resolve_seed_date_returns_none_for_unknown_uncached_seed():
    # Uncached seed with no usable fetch result → None (main() then falls back
    # to `now`). A stub session that yields nothing stands in for a 404.
    class _NoData:
        def get(self, *a, **k):
            raise AssertionError("should not be reached in this test")
    c = init_db(":memory:")
    c.commit()
    # broadcast_date NULL row is treated as uncached and falls through to fetch.
    c.execute("INSERT INTO episodes (pid) VALUES ('ghost')")
    c.commit()
    import ttn_scrape
    orig = ttn_scrape.fetch_one
    ttn_scrape.fetch_one = lambda session, pid: None
    try:
        assert _resolve_seed_date(_NoData(), c, "ghost") is None
    finally:
        ttn_scrape.fetch_one = orig
    c.close()


# ---------- rebuild_tracks tests -------------------------------------------

_SYNOPSIS = (
    "12:31 AM\n"
    "Wolfgang Amadeus Mozart (1756-1791)\n"
    "Symphony No 40 in G minor, K.550\n"
    "Some Orchestra, Some Conductor (conductor)\n"
    "01:02 AM\n"
    "Ludwig van Beethoven (1770-1827)\n"
    "Coriolan Overture, Op 62\n"
    "Another Orchestra\n"
)


@pytest.fixture
def conn():
    c = init_db(":memory:")
    c.execute("INSERT INTO episodes (pid) VALUES ('ep1')")
    c.execute("INSERT INTO episodes (pid) VALUES ('ep2')")
    c.commit()                 # clean baseline so in_transaction test is meaningful
    yield c
    c.close()


def test_rebuild_tracks_matches_parser(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    rows = conn.execute(
        "SELECT position, composer, title FROM tracks "
        "WHERE episode_pid='ep1' ORDER BY position").fetchall()
    assert rows == [
        (0, "Wolfgang Amadeus Mozart", "Symphony No 40 in G minor, K.550"),
        (1, "Ludwig van Beethoven", "Coriolan Overture, Op 62"),
    ]


def test_rebuild_tracks_is_idempotent(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    n = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep1'").fetchone()[0]
    assert n == 2


def test_rebuild_tracks_touches_only_its_pid(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    rebuild_tracks(conn, "ep2", _SYNOPSIS)
    rebuild_tracks(conn, "ep1", "")          # ep1 now parses to 0 tracks
    assert conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep1'").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep2'").fetchone()[0] == 2


def test_rebuild_tracks_returns_parsed_dicts(conn):
    parsed = rebuild_tracks(conn, "ep1", _SYNOPSIS)
    assert parsed == parse_tracks(_SYNOPSIS)


def test_rebuild_tracks_does_not_commit(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    # baseline was committed, so a pending (uncommitted) transaction here means
    # rebuild_tracks did not commit.
    assert conn.in_transaction
