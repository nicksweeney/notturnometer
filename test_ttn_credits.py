"""Tests for ttn_credits — the credit/unit primitive (extracted from the
retired ttn_rebroadcast). Run: uv run --with pytest pytest test_ttn_credits.py -v"""
from ttn_credits import (parse_credit, CreditSig, credit_key, Unit,
                         build_units, cluster_length, representative_title)


def test_parse_credit_buckets_by_role():
    # buckets keep the BBC's original spelling — credit_key folds them
    sig = parse_credit(
        "Midori (violin), Bundesjugendorchester, Patrick Lange (conductor)")
    assert sig.conductors == frozenset({"Patrick Lange"})
    assert sig.soloists == frozenset({"Midori"})
    assert sig.ensembles == frozenset({"Bundesjugendorchester"})
    assert sig.degraded is False


def test_parse_credit_bare_string_is_degraded():
    # no parenthetical anywhere -> every name to ensembles, degraded
    sig = parse_credit("Hallé, Mark Elder")
    assert sig.degraded is True
    assert sig.conductors == frozenset()
    assert sig.soloists == frozenset()
    assert sig.ensembles == frozenset({"Hallé", "Mark Elder"})


def test_parse_credit_ensemble_role_word():
    # a parenthetical naming an ensemble role buckets as ensemble
    sig = parse_credit("BBC Singers (choir), Sofi Jeannin (conductor)")
    assert sig.ensembles == frozenset({"BBC Singers"})
    assert sig.conductors == frozenset({"Sofi Jeannin"})
    assert sig.degraded is False


def test_parse_credit_empty_string():
    sig = parse_credit("")
    assert sig == CreditSig(frozenset(), frozenset(), frozenset(), True)


def test_parse_credit_tolerates_trailing_period_after_role():
    # the BBC sometimes ends the performers line with a full stop, leaving
    # a "." after the last "(role)" — the role must still be recognised,
    # not swallowed into a phantom ensemble
    sig = parse_credit("CBC Vancouver Orchestra, Mario Bernardi (conductor).")
    assert sig.conductors == frozenset({"Mario Bernardi"})
    assert sig.ensembles == frozenset({"CBC Vancouver Orchestra"})
    assert sig.degraded is False


def test_credit_key_flattens_all_roles():
    sig = parse_credit(
        "Midori (violin), Bundesjugendorchester, Patrick Lange (conductor)")
    assert credit_key(sig) == frozenset(
        {"midori", "bundesjugendorchester", "patrick lange"})


def test_parse_credit_keeps_casing_but_credit_key_folds():
    # the CreditSig buckets keep the original spelling (case + diacritics)
    # for display; credit_key folds them, so it stays a stable cluster key
    sig = parse_credit("Oslo Philharmonic, Klaus Mäkelä (conductor)")
    assert sig.ensembles == frozenset({"Oslo Philharmonic"})
    assert sig.conductors == frozenset({"Klaus Mäkelä"})
    assert credit_key(sig) == frozenset({"oslo philharmonic", "klaus makela"})


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


def _unit(title, composer, performers, date, length=10):
    rows = [(title, composer, performers, date, "01:00 AM", length)]
    return build_units(rows)[0]


def test_cluster_length_is_median_of_airings():
    a = _unit("W", "Brahms", "Hallé", "2020-01-01", length=10)
    b = _unit("W", "Brahms", "Hallé", "2021-01-01", length=14)
    c = _unit("W", "Brahms", "Hallé", "2022-01-01", length=12)
    assert cluster_length([a, b, c]) == 12


def test_cluster_length_none_when_all_missing():
    a = _unit("W", "Brahms", "Hallé", "2020-01-01", length=None)
    b = _unit("W", "Brahms", "Hallé", "2021-01-01", length=None)
    assert cluster_length([a, b]) is None


def test_representative_title_most_common_wins():
    units = [_unit("Egmont Overture", "Beethoven", "Hallé", "2020-01-01"),
             _unit("Egmont Overture", "Beethoven", "Hallé", "2021-01-01"),
             _unit("Overture: Egmont", "Beethoven", "Hallé", "2022-01-01")]
    assert representative_title(units) == "Egmont Overture"
