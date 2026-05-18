"""Tests for ttn_rebroadcast pure logic.

Run: uv run --with pytest pytest test_ttn_rebroadcast.py -v
"""
from ttn_audit import candidate_id

from ttn_rebroadcast import (parse_credit, CreditSig, credit_key, Unit,
                             build_units, rebroadcast_clusters, length_band,
                             cluster_length, representative_title, same_work)


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


def _unit(title, composer, performers, date, length=10):
    rows = [(title, composer, performers, date, "01:00 AM", length)]
    return build_units(rows)[0]


def test_rebroadcast_clusters_keeps_two_date_groups():
    a = _unit("Egmont Overture, Op 84", "Beethoven",
              "Hallé, Mark Elder (conductor)", "2020-01-01")
    b = _unit("Egmont Overture, Op 84", "Beethoven",
              "Hallé, Mark Elder (conductor)", "2021-06-06")
    clusters = rebroadcast_clusters([a, b])
    assert len(clusters) == 1
    assert {u.date for u in clusters[0]} == {"2020-01-01", "2021-06-06"}


def test_rebroadcast_clusters_drops_single_date():
    a = _unit("Egmont Overture, Op 84", "Beethoven", "Hallé", "2020-01-01")
    assert rebroadcast_clusters([a]) == []


def test_rebroadcast_clusters_splits_on_different_conductor():
    # same orchestra + work, different conductor -> two recordings, neither
    # on its own a rebroadcast (the warhorse false-positive defence)
    a = _unit("Symphony No 5", "Beethoven", "Hallé, Mark Elder (conductor)",
              "2020-01-01")
    b = _unit("Symphony No 5", "Beethoven", "Hallé, Simon Rattle (conductor)",
              "2021-01-01")
    assert rebroadcast_clusters([a, b]) == []


def test_rebroadcast_clusters_ignores_repeat_within_one_date():
    # two airings on the SAME date are not ">=2 distinct dates"
    a = _unit("Egmont Overture, Op 84", "Beethoven", "Hallé", "2020-01-01")
    b = _unit("Egmont Overture, Op 84", "Beethoven", "Hallé", "2020-01-01")
    assert rebroadcast_clusters([a, b]) == []


def test_length_band_thresholds():
    assert length_band(None) == "unknown"
    assert length_band(3) == "short"
    assert length_band(7) == "short"
    assert length_band(8) == "medium"
    assert length_band(20) == "medium"
    assert length_band(21) == "long"
    assert length_band(45) == "long"


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


def test_same_work_true_on_shared_catalogue():
    a = _unit("Concerto in A minor, RV 356", "Vivaldi", "Hallé", "2020-01-01")
    b = _unit("Violin Concerto, RV.356", "Vivaldi", "Hallé", "2021-01-01")
    assert same_work(a, b)


def test_same_work_true_on_high_token_overlap():
    a = _unit("Egmont Overture in F minor", "Beethoven", "Hallé", "2020-01-01")
    b = _unit("Overture Egmont in F minor", "Beethoven", "Hallé", "2021-01-01")
    assert same_work(a, b)


def test_same_work_false_on_unrelated_titles():
    a = _unit("Egmont Overture", "Beethoven", "Hallé", "2020-01-01")
    b = _unit("Violin Concerto in D major", "Beethoven", "Hallé", "2021-01-01")
    assert not same_work(a, b)


def test_same_work_false_on_mismatched_catalogue():
    a = _unit("Concerto, RV 356", "Vivaldi", "Hallé", "2020-01-01")
    b = _unit("Concerto, RV 999", "Vivaldi", "Hallé", "2021-01-01")
    assert not same_work(a, b)
