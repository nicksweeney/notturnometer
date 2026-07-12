"""Tests for ttn_site: composer slug + composer index (website Phase 1).

Run: uv run --with pytest pytest test_ttn_site.py
"""
import json

import pytest

from ttn_site import (composer_slug, build_composer_index, RegistryDriftError,
                       load_registry, dump_registry, sync_registry)


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


# --- registry core: load/dump ----------------------------------------------

def _empty_shell():
    return {"version": 1, "works": {}, "composers": {},
            "redirects": {"works": {}, "composers": {}}}


def test_load_registry_missing_file_returns_empty_shell(tmp_path):
    path = tmp_path / "registry.json"
    assert load_registry(str(path)) == _empty_shell()


def test_load_registry_corrupt_json_hard_errors(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text("{not json")
    with pytest.raises(Exception):
        load_registry(str(path))


def test_load_registry_wrong_shape_hard_errors(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"totally": "not a registry"}))
    with pytest.raises(Exception):
        load_registry(str(path))


def test_dump_registry_deterministic_bytes(tmp_path):
    path = tmp_path / "registry.json"
    registry = {
        "version": 1,
        "works": {"b:sym5": {"composer_key": "b", "work_key": "sym5",
                              "published": "2026-01-01"}},
        "composers": {"b": {"composer_key": "b", "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(registry, str(path))
    raw = path.read_bytes()
    assert raw == json.dumps(registry, indent=2, sort_keys=True).encode() + b"\n"
    # round-trips
    assert load_registry(str(path)) == registry


def test_dump_registry_is_atomic_no_leftover_tmp(tmp_path):
    path = tmp_path / "registry.json"
    dump_registry(_empty_shell(), str(path))
    assert path.exists()
    assert not (tmp_path / "registry.json.tmp").exists()


# --- sync_registry: new identities ------------------------------------------

def _work_entry(ck, wk, slug, airings=1):
    return {"key": (ck, wk), "slug": slug, "composer_display": ck,
            "work_display": wk, "airings": airings, "spellings": [wk]}


def _composer_entry(ck, slug, airings=1):
    return {"composer_key": ck, "slug": slug, "display": ck,
            "airings": airings, "n_works": 1, "spellings": [ck]}


def test_sync_registers_new_identities():
    registry = _empty_shell()
    works = [_work_entry("beethoven", "symphony-5", "beethoven-symphony-5")]
    composers = [_composer_entry("beethoven", "beethoven")]
    new_reg, report = sync_registry(registry, works, composers, today="2026-07-12")

    assert new_reg["works"]["beethoven-symphony-5"] == {
        "composer_key": "beethoven", "work_key": "symphony-5",
        "published": "2026-07-12",
    }
    assert new_reg["composers"]["beethoven"] == {
        "composer_key": "beethoven", "published": "2026-07-12",
    }
    assert report["added_works"] == 1
    assert report["added_composers"] == 1
    assert report["slug_drift"] == []
    assert report["collisions"] == []
    # input untouched (pure)
    assert registry == _empty_shell()


def test_sync_does_not_mutate_input_registry():
    registry = _empty_shell()
    works = [_work_entry("beethoven", "symphony-5", "beethoven-symphony-5")]
    sync_registry(registry, works, [], today="2026-07-12")
    assert registry["works"] == {}


# --- sync_registry: frozen slugs / drift report -----------------------------

def test_sync_frozen_slug_survives_derived_change():
    registry = {
        "version": 1,
        "works": {"beethoven-sym-5": {"composer_key": "beethoven",
                                       "work_key": "symphony-5",
                                       "published": "2026-01-01"}},
        "composers": {},
        "redirects": {"works": {}, "composers": {}},
    }
    # derived slug for the same identity has since changed
    works = [_work_entry("beethoven", "symphony-5", "beethoven-symphony-no-5")]
    new_reg, report = sync_registry(registry, works, [], today="2026-07-12")

    # mapping unchanged -- old slug stays canonical
    assert new_reg["works"] == registry["works"]
    assert report["added_works"] == 0
    assert report["slug_drift"] == [("beethoven-sym-5", "beethoven-symphony-no-5")]


def test_sync_frozen_composer_slug_survives_derived_change():
    registry = {
        "version": 1, "works": {},
        "composers": {"ltvb": {"composer_key": "beethoven",
                                "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }
    composers = [_composer_entry("beethoven", "beethoven")]
    new_reg, report = sync_registry(registry, [], composers, today="2026-07-12")

    assert new_reg["composers"] == registry["composers"]
    assert report["added_composers"] == 0
    assert report["slug_drift"] == [("ltvb", "beethoven")]


# --- sync_registry: collisions ----------------------------------------------

def test_sync_collision_gets_deterministic_suffix():
    # two distinct NEW composer identities derive to the same slug
    registry = _empty_shell()
    composers = [
        _composer_entry("mozart-wolfgang", "mozart"),
        _composer_entry("mozart-leopold", "mozart"),
    ]
    new_reg, report = sync_registry(registry, [], composers, today="2026-07-12")

    slugs = {v["composer_key"]: k for k, v in new_reg["composers"].items()}
    # sorted by identity key: "mozart-leopold" < "mozart-wolfgang" -> leopold
    # keeps the base slug, wolfgang gets the suffix
    assert slugs["mozart-leopold"] == "mozart"
    assert slugs["mozart-wolfgang"] == "mozart-2"
    assert report["added_composers"] == 2
    assert ("mozart-wolfgang", "mozart", "mozart-2") in report["collisions"]


def test_sync_collision_against_existing_registered_slug():
    # a NEW identity's derived slug collides with an ALREADY-registered
    # different identity's frozen slug
    registry = {
        "version": 1, "works": {},
        "composers": {"mozart": {"composer_key": "mozart-wolfgang",
                                  "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }
    composers = [
        _composer_entry("mozart-wolfgang", "mozart"),   # already registered, no-op
        _composer_entry("mozart-leopold", "mozart"),    # new, collides
    ]
    new_reg, report = sync_registry(registry, [], composers, today="2026-07-12")

    assert new_reg["composers"]["mozart"]["composer_key"] == "mozart-wolfgang"
    assert new_reg["composers"]["mozart-2"]["composer_key"] == "mozart-leopold"
    assert report["added_composers"] == 1
    assert ("mozart-leopold", "mozart", "mozart-2") in report["collisions"]


def test_sync_collision_against_redirect_key():
    registry = {
        "version": 1, "works": {}, "composers": {},
        "redirects": {"works": {}, "composers": {"mozart": "mozart-wolfgang"}},
    }
    composers = [_composer_entry("mozart-leopold", "mozart")]
    new_reg, report = sync_registry(registry, [], composers, today="2026-07-12")

    assert new_reg["composers"]["mozart-2"]["composer_key"] == "mozart-leopold"
    assert ("mozart-leopold", "mozart", "mozart-2") in report["collisions"]


def test_sync_collision_three_way_deterministic():
    registry = _empty_shell()
    composers = [
        _composer_entry("c-charlie", "mozart"),
        _composer_entry("a-alpha", "mozart"),
        _composer_entry("b-bravo", "mozart"),
    ]
    new_reg, report = sync_registry(registry, [], composers, today="2026-07-12")
    slugs = {v["composer_key"]: k for k, v in new_reg["composers"].items()}
    # sorted by identity key: a-alpha, b-bravo, c-charlie
    assert slugs["a-alpha"] == "mozart"
    assert slugs["b-bravo"] == "mozart-2"
    assert slugs["c-charlie"] == "mozart-3"


# --- sync_registry: identity drift ------------------------------------------

def test_sync_identity_drift_raises_and_writes_nothing():
    registry = {
        "version": 1,
        "works": {"orphan-work": {"composer_key": "gone", "work_key": "vanished",
                                   "published": "2026-01-01"}},
        "composers": {"orphan-composer": {"composer_key": "also-gone",
                                           "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }
    with pytest.raises(RegistryDriftError):
        sync_registry(registry, [], [], today="2026-07-12")


def test_sync_identity_drift_lists_all_orphans_not_just_first():
    registry = {
        "version": 1,
        "works": {
            "orphan-1": {"composer_key": "gone1", "work_key": "w1",
                         "published": "2026-01-01"},
            "orphan-2": {"composer_key": "gone2", "work_key": "w2",
                         "published": "2026-01-01"},
        },
        "composers": {
            "orphan-c1": {"composer_key": "cgone1", "published": "2026-01-01"},
        },
        "redirects": {"works": {}, "composers": {}},
    }
    with pytest.raises(RegistryDriftError) as excinfo:
        sync_registry(registry, [], [], today="2026-07-12")
    msg = str(excinfo.value)
    assert "orphan-1" in msg and "orphan-2" in msg and "orphan-c1" in msg


# --- sync_registry: idempotence ---------------------------------------------

def test_sync_twice_is_idempotent():
    registry = _empty_shell()
    works = [_work_entry("beethoven", "symphony-5", "beethoven-symphony-5")]
    composers = [_composer_entry("beethoven", "beethoven")]

    first_reg, first_report = sync_registry(registry, works, composers, today="2026-07-12")
    second_reg, second_report = sync_registry(first_reg, works, composers, today="2026-07-13")

    assert second_reg["works"] == first_reg["works"]
    assert second_reg["composers"] == first_reg["composers"]
    assert second_report["added_works"] == 0
    assert second_report["added_composers"] == 0
    assert second_report["collisions"] == []
