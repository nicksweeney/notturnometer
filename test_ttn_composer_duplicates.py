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


def test_parse_span_circa():
    # A circa-qualified year must be matched, not skipped — otherwise on a
    # multi-composer line parse_span grabs a LATER composer's clean date.
    assert parse_span("Fernandes, Gasper (c.1570-1629) / Franco (1532-1585)") \
        == ("1570", "1629")
    assert parse_span("Someone (ca. 1605-c.1670)") == ("1605", "1670")
    assert parse_span("Composer (c.1700)") == ("1700", "")


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
    # Two spellings that fold to one key via canonical_key itself (diacritics),
    # so this is immune to the alias table and tests display selection within a
    # single merged group: the most common original spelling wins.
    rows = ([("Béla Bartók", "Béla Bartók (1881-1945)")] * 3
            + [("Bela Bartok", "Bela Bartok (1881-1945)")] * 1)
    groups = {g.key: g for g in build_groups(rows)}
    assert len(groups) == 1
    assert groups[canonical_key("Béla Bartók")].display == "Béla Bartók"


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


from ttn_composer_duplicates import find_duplicates


def _g(name, n, span):
    return ComposerGroup(canonical_key(name), name, n, span)


def test_find_primary_date_corroborated():
    groups = [_g("Aurelio Vibratto", 8, ("1729", "1774")),
              _g("Aurelio Vibrato", 6, ("1729", "1774"))]
    pairs = find_duplicates(groups)
    assert len(pairs) == 1
    assert pairs[0].tier == "primary"
    assert pairs[0].big.display == "Aurelio Vibratto"   # more airings
    assert pairs[0].small.display == "Aurelio Vibrato"
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


def test_find_ranks_primary_first_then_min_airings():
    groups = [
        _g("Georg Druschetzky", 7, ("1745", "1819")),
        _g("Georg Druschetsky", 6, ("1745", "1819")),     # primary, min 6
        _g("Filip Kutev", 30, ("1903", "1982")),
        _g("Filip Koutev", 4, ("1903", "1982")),          # primary, min 4
        # secondary pair with a HIGHER min_airings than either primary:
        _g("Anthony Holborne", 11, ("1560", "1602")),
        _g("Antony Holborne", 20, None),                  # secondary, min 11
    ]
    pairs = find_duplicates(groups)
    # primary-first beats raw min_airings (the secondary's 11 sorts last)...
    assert [p.tier for p in pairs] == ["primary", "primary", "secondary"]
    # ...and within the primary tier, min_airings desc (6 before 4).
    assert [p.min_airings for p in pairs] == [6, 4, 11]


def test_find_high_confidence_sorts_before_low_within_primary():
    # min_airings must NOT pull a sub-0.82 pair above a >=0.82 pair: the
    # confidence partition keeps the divider clean (code-review fix).
    groups = [
        _g("Johann Christoph Bach", 47, ("1642", "1703")),  # r~0.78, min 20
        _g("Georg Christoph Bach", 20, ("1642", "1703")),
        _g("Aurelio Vibratto", 8, ("1729", "1774")),  # r~0.98, min 6
        _g("Aurelio Vibrato", 6, ("1729", "1774")),
    ]
    pairs = find_duplicates(groups)
    # the high-confidence Vibratto pair (r~0.98) precedes the low Bach pair
    # (r~0.78) despite the Bach pair's larger min_airings.
    assert pairs[0].big.display == "Aurelio Vibratto"
    assert pairs[1].big.display == "Johann Christoph Bach"


import json
from ttn_composer_duplicates import load_decisions, reject_pair


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


from ttn_composer_duplicates import render, _majority_maybe_error


def test_majority_maybe_error_shorter_majority():
    big = ComposerGroup(canonical_key("Gedimas Gelgotas"),
                        "Gedimas Gelgotas", 8, ("1986", ""))
    small = ComposerGroup(canonical_key("Gediminas Gelgotas"),
                          "Gediminas Gelgotas", 1, ("1986", ""))
    assert _majority_maybe_error(big, small) is True


def test_majority_maybe_error_fewer_diacritics():
    big = ComposerGroup(canonical_key("Sebastian Yradier"),
                        "Sebastian Yradier", 5, ("1809", "1865"))
    small = ComposerGroup(canonical_key("Sebastián Iradier"),
                          "Sebastián Iradier", 2, ("1809", "1865"))
    assert _majority_maybe_error(big, small) is True


def test_render_has_tiers_and_divider():
    groups = [_g("Aurelio Vibratto", 8, ("1729", "1774")),   # r~0.98
              _g("Aurelio Vibrato", 6, ("1729", "1774")),
              # a sub-0.82 primary pair (r~0.78) to exercise the divider:
              _g("Johann Christoph Bach", 47, ("1642", "1703")),
              _g("Georg Christoph Bach", 7, ("1642", "1703")),
              _g("Anthony Holborne", 11, ("1560", "1602")),
              _g("Antony Holborne", 1, None)]
    out = render(find_duplicates(groups))
    assert "date-corroborated" in out
    assert "no date corroboration" in out
    assert "below high-confidence (0.82)" in out          # divider fired
    assert "Vibratto" in out and "Holborne" in out


def test_emit_live_chainfree_only_and_flag():
    # Vibrato -> Vibratto is live + chain-free; emit the tuple.
    groups = [_g("Aurelio Vibratto", 8, ("1729", "1774")),
              _g("Aurelio Vibrato", 6, ("1729", "1774"))]
    out = render(find_duplicates(groups), emit=True)
    assert "_COMPOSER_ALIAS_PAIRS" in out
    assert "('Aurelio Vibrato', 'Aurelio Vibratto')" in out


from ttn_composer_duplicates import main


def _seed_db(path):
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tracks (composer TEXT, composer_line TEXT)")
    conn.executemany(
        "INSERT INTO tracks (composer, composer_line) VALUES (?, ?)",
        [("Aurelio Vibratto", "Aurelio Vibratto (1729-1774)")] * 8
        + [("Aurelio Vibrato", "Aurelio Vibrato (1729-1774)")] * 6)
    conn.commit()
    conn.close()


def _patch_decisions(monkeypatch, tmp_path):
    """Point _DECISIONS_PATH at a fresh tmp file so tests never touch the
    repo's real ledger."""
    import ttn_composer_duplicates as mod
    monkeypatch.setattr(mod, "_DECISIONS_PATH", str(tmp_path / "dec.json"))


def test_main_reports(tmp_path, capsys, monkeypatch):
    db = str(tmp_path / "t.sqlite")
    _seed_db(db)
    _patch_decisions(monkeypatch, tmp_path)
    main([db])
    out = capsys.readouterr().out
    assert "candidate same-person split" in out
    assert "Vibratto" in out


def test_main_reject_writes_and_exits(tmp_path, capsys, monkeypatch):
    db = str(tmp_path / "t.sqlite")
    _seed_db(db)
    _patch_decisions(monkeypatch, tmp_path)
    main([db, "--reject", "Aurelio Vibrato|Aurelio Vibratto"])
    assert "Recorded rejection" in capsys.readouterr().out
    main([db])                                   # pair now suppressed
    assert "Vibratto" not in capsys.readouterr().out


def test_main_csv(tmp_path, monkeypatch):
    import csv
    db = str(tmp_path / "t.sqlite")
    _seed_db(db)
    _patch_decisions(monkeypatch, tmp_path)
    out_csv = str(tmp_path / "dups.csv")
    main([db, "--csv", out_csv])
    rows = list(csv.DictReader(open(out_csv, encoding="utf-8")))
    assert rows and rows[0]["name_a"] == "Aurelio Vibratto"
