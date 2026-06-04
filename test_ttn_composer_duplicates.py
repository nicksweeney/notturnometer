from ttn_analyze import canonical_key
from ttn_composer_duplicates import parse_span


def test_parse_span_paren():
    assert parse_span("Ion Dumitrescu (1913-1996)") == ("1913", "1996")


def test_parse_span_bracket():
    assert parse_span("Composer [1685-1750]") == ("1685", "1750")


def test_parse_span_birth_only():
    assert parse_span("Frano Parac (b.1948)") == ("1948", "")
    assert parse_span("Someone (b. 1966)") == ("1966", "")


def test_parse_span_open_death():
    assert parse_span("Johann Schenck (1660-)") == ("1660", "")


def test_parse_span_none():
    assert parse_span("No dates here") is None
    assert parse_span("") is None
    assert parse_span(None) is None


from ttn_composer_duplicates import build_groups, ComposerGroup


def test_build_groups_accumulates():
    rows = [
        ("Ion Dumitrescu", "Ion Dumitrescu (1913-1996)"),
        ("Ion Dumitrescu", "Ion Dumitrescu (1913-1996)"),
        ("Claude Debussy", "Claude Debussy (1862-1918)"),
    ]
    groups = {g.key: g for g in build_groups(rows)}
    d = groups[canonical_key("Ion Dumitrescu")]
    assert d.airings == 2
    assert d.display == "Ion Dumitrescu"
    assert d.span == ("1913", "1996")


def test_build_groups_display_is_most_common_spelling():
    rows = ([("Georg Druschetzky", "Georg Druschetzky (1745-1819)")] * 3
            + [("Georg Druschetsky", "Georg Druschetsky (1745-1819)")] * 1)
    # both resolve to distinct keys (neither is aliased to the other)
    groups = {g.key: g for g in build_groups(rows)}
    assert groups[canonical_key("Georg Druschetzky")].display == "Georg Druschetzky"


def test_build_groups_excludes_noise():
    rows = [
        ("Traditional Hungarian", "Traditional Hungarian"),
        ("Anon.", "Anon."),
        ("Unknown Sergey Rachmaninov", "Unknown Sergey Rachmaninov"),
        ("Trad. arr. Smith", "Trad. arr. Smith"),
        ("Strauss, Johann", "Strauss, Johann (1825-1899)"),  # comma line
        ("Real Composer", "Real Composer (1900-1980)"),
        # MUST survive: 'arr' is an inner substring, not the arranger token
        ("Louise Farrenc", "Louise Farrenc (1804-1875)"),
        ("Hubert Parry", "Hubert Parry (1848-1918)"),
    ]
    keys = {g.display for g in build_groups(rows)}
    assert keys == {"Real Composer", "Louise Farrenc", "Hubert Parry"}


from ttn_composer_duplicates import find_duplicates, DupPair, ComposerGroup


def _g(name, n, span):
    return ComposerGroup(canonical_key(name), name, n, span)


def test_find_primary_date_corroborated():
    groups = [_g("Florian Leopold Gassmann", 8, ("1729", "1774")),
              _g("Florian Leopold Gassman", 6, ("1729", "1774"))]
    pairs = find_duplicates(groups)
    assert len(pairs) == 1
    assert pairs[0].tier == "primary"
    assert pairs[0].big.display == "Florian Leopold Gassmann"   # more airings
    assert pairs[0].small.display == "Florian Leopold Gassman"
    assert pairs[0].min_airings == 6


def test_find_secondary_no_shared_span():
    # same surname, no shared span (one spanless) -> secondary tier
    groups = [_g("Anthony Holborne", 11, ("1560", "1602")),
              _g("Antony Holborne", 1, None)]
    pairs = find_duplicates(groups)
    assert len(pairs) == 1
    assert pairs[0].tier == "secondary"


def test_find_excludes_below_floor_and_already_merged():
    # genuinely dissimilar names, same span, ratio < 0.74 -> not flagged.
    # (Note: a 0.74-0.82 distinct-relative pair like the two Christoph Bachs
    # DOES surface by design — it is parked via the decisions ledger, not the
    # floor — so it is not used here.)
    groups = [_g("Aaron Copland", 5, ("1900", "1990")),
              _g("Benjamin Britten", 5, ("1900", "1990"))]
    assert find_duplicates(groups) == []
    # identical key -> never a self-pair
    dup = [_g("Same Name", 3, ("1900", "1950")),
           _g("Same Name", 4, ("1900", "1950"))]
    assert find_duplicates(dup) == []


def test_find_ranks_by_min_airings_then_primary_first():
    groups = [
        _g("Georg Druschetzky", 7, ("1745", "1819")),
        _g("Georg Druschetsky", 6, ("1745", "1819")),     # primary, min 6
        _g("Filip Kutev", 30, ("1903", "1982")),
        _g("Filip Koutev", 4, ("1903", "1982")),          # primary, min 4
    ]
    pairs = find_duplicates(groups)
    assert [p.min_airings for p in pairs] == [6, 4]        # 6 before 4


import json
from ttn_composer_duplicates import load_decisions, reject_pair, find_duplicates


def test_load_decisions_missing_file(tmp_path):
    assert load_decisions(str(tmp_path / "nope.json")) == set()


def test_reject_pair_writes_sorted_and_dedupes(tmp_path):
    p = str(tmp_path / "dec.json")
    reject_pair(p, "Zeb Composer", "Aaron Composer")
    reject_pair(p, "Aaron Composer", "Zeb Composer")     # same pair, reversed
    data = json.load(open(p, encoding="utf-8"))
    assert data["rejected"] == [["Aaron Composer", "Zeb Composer"]]
    assert load_decisions(p) == {frozenset({"Aaron Composer", "Zeb Composer"})}


def test_find_duplicates_filters_rejected():
    groups = [_g("Georg Druschetzky", 7, ("1745", "1819")),
              _g("Georg Druschetsky", 6, ("1745", "1819"))]
    rejected = {frozenset({"Georg Druschetzky", "Georg Druschetsky"})}
    assert find_duplicates(groups, rejected=rejected) == []
