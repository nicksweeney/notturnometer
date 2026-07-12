"""Tests for ttn_site: composer slug + composer index (website Phase 1).

Run: uv run --with pytest pytest test_ttn_site.py
"""
from ttn_site import composer_slug, build_composer_index


def test_composer_slug_kebab():
    assert composer_slug("Ralph Vaughan Williams") == "ralph-vaughan-williams"


def test_composer_slug_diacritics_fold():
    assert composer_slug("Antonín Dvořák") == "antonin-dvorak"


def test_composer_slug_punctuation():
    assert composer_slug("Camille Saint-Saëns") == "camille-saint-saens"
    assert composer_slug("Turlough O'Carolan") == "turlough-o-carolan"


def test_composer_slug_empty_falls_back_to_hash():
    s = composer_slug("···")
    assert s.startswith("c") and len(s) == 9   # "c" + sha1[:8]


def test_build_composer_index_groups_and_displays():
    rows = [
        ("Sym 5", "Pyotr Tchaikovsky", "Pyotr Tchaikovsky", "", "2020-01-01"),
        ("Sym 5", "Peter Tchaikovsky", "Peter Tchaikovsky", "", "2020-01-02"),
        ("Sym 5", "Peter Tchaikovsky", "Peter Tchaikovsky", "", "2020-01-03"),
    ]
    idx = build_composer_index(rows)
    assert len(idx) == 1
    e = idx[0]
    assert e["display"] == "Peter Tchaikovsky"      # majority spelling
    assert e["airings"] == 3 and e["n_works"] == 1
    assert e["slug"] == "peter-tchaikovsky"


def test_build_composer_index_distinct_composers_split():
    rows = [
        ("Sym 5", "Beethoven", "Beethoven", "", "2020-01-01"),
        ("Requiem", "Mozart", "Mozart", "", "2020-01-02"),
    ]
    idx = build_composer_index(rows)
    assert len(idx) == 2
    displays = {e["display"] for e in idx}
    assert displays == {"Beethoven", "Mozart"}
    for e in idx:
        assert e["airings"] == 1 and e["n_works"] == 1


def test_build_composer_index_n_works_counts_distinct_work_keys():
    rows = [
        ("Symphony No 5", "Beethoven", "Beethoven", "", "2020-01-01"),
        ("Symphony No 6", "Beethoven", "Beethoven", "", "2020-01-02"),
        ("Symphony No 5", "Beethoven", "Beethoven", "", "2020-01-03"),
    ]
    idx = build_composer_index(rows)
    assert len(idx) == 1
    assert idx[0]["airings"] == 3
    assert idx[0]["n_works"] == 2


def test_build_composer_index_skips_empty_composer_key():
    rows = [
        ("Untitled fragment", "", "", "", "2020-01-01"),
    ]
    idx = build_composer_index(rows)
    assert idx == []
