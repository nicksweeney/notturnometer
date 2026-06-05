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


from ttn_mbid_audit import surname, title_tokens, pair_cost, _NO_TEMPORAL


def test_surname_and_tokens():
    assert surname("Camille Saint-Saens") == "saint-saens"
    assert surname("Antonin Dvorak") == "dvorak"
    assert surname("") == ""
    assert title_tokens("Symphony No.5 in D") == {"symphony", "no", "5", "in", "d"}


def test_pair_cost_same_slot_same_composer_is_low():
    c = pair_cost(t_off=120, s_off=120, t_comp="Antonin Dvorak",
                  s_comp="Antonin Dvorak", t_title="Slavonic Dance",
                  s_title="Slavonic Dance")
    assert c < 0.2


def test_pair_cost_same_slot_different_composer_is_mid():
    # temporal agrees, names disagree -> a Medium candidate (cost in a middle band)
    c = pair_cost(t_off=120, s_off=120, t_comp="Anonymous", s_comp="Anon",
                  t_title="Carol", s_title="Carol")
    assert 0.2 <= c < 0.7


def test_pair_cost_far_apart_is_high():
    c = pair_cost(t_off=0, s_off=3600, t_comp="A B", s_comp="X Y",
                  t_title="foo", s_title="bar")
    assert c > 0.7


def test_pair_cost_without_temporal_uses_content_only():
    c = pair_cost(t_off=None, s_off=120, t_comp="J S Bach", s_comp="J S Bach",
                  t_title="Fugue", s_title="Fugue")
    assert c < 0.4          # content-only still matches a clear pair
