"""Tests for ttn_mbid_audit: temporal matcher, DB loading, audit logic, CLI.

Run: uv run --with pytest pytest test_ttn_mbid_audit.py -q
"""
import sqlite3

from ttn_mbid_audit import parse_clock_offset, episode_offsets


def test_parse_clock_offset_seconds_since_midnight():
    assert parse_clock_offset("12:00 AM") == 0
    assert parse_clock_offset("12:31 AM") == 31 * 60
    assert parse_clock_offset("1:55 AM") == (1 * 60 + 55) * 60
    assert parse_clock_offset("11:30 PM") == (23 * 60 + 30) * 60
    assert parse_clock_offset("12:15 PM") == (12 * 60 + 15) * 60


def test_parse_clock_offset_unparseable_returns_none():
    assert parse_clock_offset("") is None
    assert parse_clock_offset("00:30") is None        # no meridiem (quirk episode)
    assert parse_clock_offset(None) is None


def test_episode_offsets_relative_with_daywrap():
    # times that cross midnight: 11:58 PM -> 12:02 AM -> 12:31 AM
    secs = episode_offsets(["11:58 PM", "12:02 AM", "12:31 AM"])
    assert secs == [0, 4 * 60, 33 * 60]               # relative to first, wrap handled
    # an unparseable time yields None for that slot but keeps the others aligned
    secs2 = episode_offsets(["12:00 AM", "garbage", "12:10 AM"])
    assert secs2[0] == 0 and secs2[1] is None and secs2[2] == 10 * 60
