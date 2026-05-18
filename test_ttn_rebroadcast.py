"""Tests for ttn_rebroadcast pure logic.

Run: uv run --with pytest pytest test_ttn_rebroadcast.py -v
"""
from ttn_audit import candidate_id

from ttn_rebroadcast import parse_credit, CreditSig, credit_key, Unit, build_units


def test_parse_credit_buckets_by_role():
    sig = parse_credit(
        "Midori (violin), Bundesjugendorchester, Patrick Lange (conductor)")
    assert sig.conductors == frozenset({"patrick lange"})
    assert sig.soloists == frozenset({"midori"})
    assert sig.ensembles == frozenset({"bundesjugendorchester"})
    assert sig.degraded is False


def test_parse_credit_bare_string_is_degraded():
    # no parenthetical anywhere -> every name to ensembles, degraded
    sig = parse_credit("Hallé, Mark Elder")
    assert sig.degraded is True
    assert sig.conductors == frozenset()
    assert sig.soloists == frozenset()
    assert sig.ensembles == frozenset({"halle", "mark elder"})


def test_parse_credit_ensemble_role_word():
    # a parenthetical naming an ensemble role buckets as ensemble
    sig = parse_credit("BBC Singers (choir), Sofi Jeannin (conductor)")
    assert sig.ensembles == frozenset({"bbc singers"})
    assert sig.conductors == frozenset({"sofi jeannin"})
    assert sig.degraded is False


def test_parse_credit_empty_string():
    sig = parse_credit("")
    assert sig == CreditSig(frozenset(), frozenset(), frozenset(), True)


def test_credit_key_flattens_all_roles():
    sig = parse_credit(
        "Midori (violin), Bundesjugendorchester, Patrick Lange (conductor)")
    assert credit_key(sig) == frozenset(
        {"midori", "bundesjugendorchester", "patrick lange"})


def test_credit_key_equal_across_role_parsing_differences():
    # same forces, one airing role-tagged, one airing bare -> same key
    tagged = parse_credit("Hallé, Mark Elder (conductor)")
    bare = parse_credit("Hallé, Mark Elder")
    assert credit_key(tagged) == credit_key(bare)


def test_build_units_one_per_track():
    rows = [
        ("Symphony No 5 in C minor", "Beethoven", "Hallé, Mark Elder (conductor)",
         "2020-01-01", "01:00 AM", 30),
        ("Egmont Overture, Op 84", "Beethoven", "Hallé, Mark Elder (conductor)",
         "2021-02-02", "02:00 AM", 9),
    ]
    units = build_units(rows)
    assert len(units) == 2
    u = units[0]
    assert u.composer_display == "Beethoven"
    assert u.date == "2020-01-01"
    assert u.length == 30
    assert u.credit_key == frozenset({"halle", "mark elder"})


def test_build_units_drops_tracks_with_no_composer():
    rows = [
        ("Some Work", "", "Hallé", "2020-01-01", "01:00 AM", 10),
        ("Real Work", "Brahms", "Hallé", "2020-01-02", "01:00 AM", 10),
    ]
    units = build_units(rows)
    assert [u.composer_display for u in units] == ["Brahms"]


def test_build_units_truncates_date_to_ten_chars():
    rows = [("W", "Brahms", "Hallé", "2020-01-01T23:30:00+00:00", "x", 5)]
    assert build_units(rows)[0].date == "2020-01-01"
