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
