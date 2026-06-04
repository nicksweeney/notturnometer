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
