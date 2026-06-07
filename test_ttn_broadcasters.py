from ttn_broadcasters import BroadcasterStat, rank_broadcasters
from ttn_ebu_codes import decode


def test_airings_count_and_sort_desc_named_record():
    rows = ["GBBBC", "PLPR", "GBBBC", "GBBBC", "PLPR"]
    stats = rank_broadcasters(rows)
    assert isinstance(stats[0], BroadcasterStat)
    assert stats[0] == BroadcasterStat("GBBBC", 3)
    assert stats[1] == BroadcasterStat("PLPR", 2)


def test_unattributed_bucket_nulls_and_blanks_sorted_last():
    rows = ["GBBBC", None, "", "GBBBC", None]
    stats = rank_broadcasters(rows)
    assert stats[0] == BroadcasterStat("GBBBC", 2)
    assert stats[-1] == BroadcasterStat("UNATTRIBUTED", 3)  # NULL+'' merged, last
    keys = [s.key for s in stats]
    assert keys.count("UNATTRIBUTED") == 1


def test_rank_key_country_swap_aggregates():
    rows = ["DEWDR", "CHSRF", "CHRSI", "DEWDR"]   # 2x DE, 2x CH
    stats = rank_broadcasters(rows, rank_key=lambda c: decode(c)[1])
    d = {s.key: s.airings for s in stats}
    assert d == {"DE": 2, "CH": 2}


def test_unattributed_excluded_from_rank_key():
    # empty labels must not be passed to rank_key (would KeyError/garbage)
    rows = ["", None, "DEWDR"]
    stats = rank_broadcasters(rows, rank_key=lambda c: decode(c)[1])
    assert {s.key for s in stats} == {"DE", "UNATTRIBUTED"}
