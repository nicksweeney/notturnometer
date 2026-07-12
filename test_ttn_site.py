"""Tests for ttn_site: composer slug + composer index (website Phase 1).

Run: uv run --with pytest pytest test_ttn_site.py
"""
import json
import sqlite3

import pytest

import ttn_site
from ttn_site import (composer_slug, build_composer_index, RegistryDriftError,
                       load_registry, dump_registry, sync_registry,
                       apply_rename, apply_remap, RegistryActionError)


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
    with pytest.raises(ValueError):
        load_registry(str(path))


def test_load_registry_wrong_shape_hard_errors(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"totally": "not a registry"}))
    with pytest.raises(ValueError):
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


# --- admin actions: --rename -------------------------------------------------

def test_apply_rename_works_namespace_moves_registration_and_adds_redirect():
    registry = {
        "version": 1,
        "works": {"old-slug": {"composer_key": "beethoven", "work_key": "symphony-5",
                                "published": "2026-01-01"}},
        "composers": {},
        "redirects": {"works": {}, "composers": {}},
    }
    new_reg = apply_rename(registry, "works", "old-slug", "new-slug")
    assert "old-slug" not in new_reg["works"]
    assert new_reg["works"]["new-slug"] == {"composer_key": "beethoven",
                                             "work_key": "symphony-5",
                                             "published": "2026-01-01"}
    assert new_reg["redirects"]["works"]["old-slug"] == "new-slug"
    # input untouched (pure)
    assert "old-slug" in registry["works"]


def test_apply_rename_composers_namespace():
    registry = {
        "version": 1, "works": {},
        "composers": {"old": {"composer_key": "beethoven", "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }
    new_reg = apply_rename(registry, "composers", "old", "new")
    assert new_reg["composers"]["new"]["composer_key"] == "beethoven"
    assert new_reg["redirects"]["composers"]["old"] == "new"


def test_apply_rename_refuses_when_new_slug_registered():
    registry = {
        "version": 1,
        "works": {
            "old-slug": {"composer_key": "a", "work_key": "w1", "published": "2026-01-01"},
            "taken": {"composer_key": "b", "work_key": "w2", "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    with pytest.raises(RegistryActionError):
        apply_rename(registry, "works", "old-slug", "taken")


def test_apply_rename_refuses_when_new_slug_is_a_redirect():
    registry = {
        "version": 1,
        "works": {"old-slug": {"composer_key": "a", "work_key": "w1", "published": "2026-01-01"}},
        "composers": {},
        "redirects": {"works": {"taken": "somewhere-else"}, "composers": {}},
    }
    with pytest.raises(RegistryActionError):
        apply_rename(registry, "works", "old-slug", "taken")


def test_apply_rename_refuses_when_old_slug_not_registered():
    registry = _empty_shell()
    with pytest.raises(RegistryActionError):
        apply_rename(registry, "works", "missing-slug", "new-slug")


# --- admin actions: --remap --------------------------------------------------

def test_apply_remap_works_repoints_orphan_to_unregistered_successor():
    registry = {
        "version": 1,
        "works": {"orphan": {"composer_key": "old-ck", "work_key": "old-wk",
                              "published": "2026-01-01"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    new_reg = apply_remap(registry, "works", "orphan", "new-ck", "new-wk")
    assert new_reg["works"]["orphan"] == {"composer_key": "new-ck", "work_key": "new-wk",
                                           "published": "2026-01-01"}
    assert "orphan" not in new_reg["redirects"]["works"]


def test_apply_remap_composers_repoints_orphan():
    registry = {
        "version": 1, "works": {},
        "composers": {"orphan": {"composer_key": "old-ck", "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }
    new_reg = apply_remap(registry, "composers", "orphan", "new-ck")
    assert new_reg["composers"]["orphan"] == {"composer_key": "new-ck",
                                               "published": "2026-01-01"}


def test_apply_remap_becomes_redirect_when_successor_already_registered():
    registry = {
        "version": 1,
        "works": {
            "orphan": {"composer_key": "old-ck", "work_key": "old-wk",
                       "published": "2026-01-01"},
            "canonical-slug": {"composer_key": "new-ck", "work_key": "new-wk",
                                "published": "2026-02-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    new_reg = apply_remap(registry, "works", "orphan", "new-ck", "new-wk")
    assert "orphan" not in new_reg["works"]
    assert new_reg["works"]["canonical-slug"] == registry["works"]["canonical-slug"]
    assert new_reg["redirects"]["works"]["orphan"] == "canonical-slug"


def test_apply_remap_composers_becomes_redirect_when_successor_registered():
    registry = {
        "version": 1, "works": {},
        "composers": {
            "orphan": {"composer_key": "old-ck", "published": "2026-01-01"},
            "canonical": {"composer_key": "new-ck", "published": "2026-02-01"},
        },
        "redirects": {"works": {}, "composers": {}},
    }
    new_reg = apply_remap(registry, "composers", "orphan", "new-ck")
    assert "orphan" not in new_reg["composers"]
    assert new_reg["redirects"]["composers"]["orphan"] == "canonical"


def test_apply_remap_refuses_when_slug_not_registered():
    registry = _empty_shell()
    with pytest.raises(RegistryActionError):
        apply_remap(registry, "works", "missing-slug", "new-ck", "new-wk")


def test_apply_remap_does_not_mutate_input():
    registry = {
        "version": 1,
        "works": {"orphan": {"composer_key": "old-ck", "work_key": "old-wk",
                              "published": "2026-01-01"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    apply_remap(registry, "works", "orphan", "new-ck", "new-wk")
    assert registry["works"]["orphan"]["composer_key"] == "old-ck"


# --- main(): build action -----------------------------------------------------

def _make_fixture_db(path):
    """A tiny synthetic DB: episodes/tracks/segment_events, mirroring
    test_ttn_project.py::_lineage_db's dual-lineage schema but with real rows
    so the whole-corpus 7-tuple cursor + build_work_index/build_composer_index
    have something to chew on."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT, "
                 "segments_raw_json TEXT)")
    conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "episode_pid TEXT, position INT, time_str TEXT, composer TEXT, "
                 "composer_line TEXT, contributors_json TEXT, title TEXT, performers TEXT)")
    conn.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
                 "version_offset INT, composer_name TEXT, track_title TEXT, "
                 "composer_mbid TEXT, recording_pid TEXT, event_pid TEXT, "
                 "composer_pid TEXT, duration_seconds INT, record_id TEXT, "
                 "record_label TEXT, contributions_json TEXT)")
    conn.execute("INSERT INTO episodes VALUES ('ep1', '2020-01-01T01:00:00Z', NULL)")
    conn.execute("INSERT INTO tracks (episode_pid, position, time_str, composer, "
                 "composer_line, title, performers) VALUES "
                 "('ep1', 0, '01:00 AM', 'Ludwig van Beethoven', 'Ludwig van Beethoven', "
                 "'Symphony No 5', 'Berlin Phil')")
    conn.execute("INSERT INTO tracks (episode_pid, position, time_str, composer, "
                 "composer_line, title, performers) VALUES "
                 "('ep1', 1, '02:00 AM', 'Wolfgang Amadeus Mozart', 'Wolfgang Amadeus Mozart', "
                 "'Requiem', 'LSO')")
    conn.commit()
    conn.close()


def test_main_build_creates_registry_with_expected_slugs(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"

    monkeypatch.setattr(ttn_site.ttn_project, "load",
                         lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path)])
    assert rc in (0, None)

    reg = load_registry(str(registry_path))
    work_cks = {v["composer_key"] for v in reg["works"].values()}
    assert "beethoven" in " ".join(work_cks) or any("beethoven" in ck for ck in work_cks)
    composer_slugs = set(reg["composers"].keys())
    assert any("beethoven" in s for s in composer_slugs)
    assert any("mozart" in s for s in composer_slugs)


def test_main_hard_errors_when_projection_not_ok(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"

    monkeypatch.setattr(ttn_site.ttn_project, "load",
                         lambda conn: ({}, {}, "stale"))

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--db", str(db_path), "--registry", str(registry_path)])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "ttn_data.py warm" in err
    assert not registry_path.exists()


def test_main_hard_errors_when_slug_map_missing(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"

    monkeypatch.setattr(ttn_site.ttn_project, "load",
                         lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: None)

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--db", str(db_path), "--registry", str(registry_path)])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "ttn_data.py warm" in err
    assert not registry_path.exists()


# --- main(): admin actions ----------------------------------------------------

def test_main_rename_happy_path(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {"old-slug": {"composer_key": "beethoven", "work_key": "symphony-5",
                                "published": "2026-01-01"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--rename", "old-slug", "new-slug"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "new-slug" in reg["works"]
    assert reg["redirects"]["works"]["old-slug"] == "new-slug"


def test_main_rename_composer_namespace(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1, "works": {},
        "composers": {"old": {"composer_key": "beethoven", "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path), "--composer",
                         "--rename", "old", "new"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "new" in reg["composers"]
    assert reg["redirects"]["composers"]["old"] == "new"


def test_main_rename_refusal_prints_error_and_writes_nothing(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    original = {
        "version": 1,
        "works": {
            "old-slug": {"composer_key": "a", "work_key": "w1", "published": "2026-01-01"},
            "taken": {"composer_key": "b", "work_key": "w2", "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(original, str(registry_path))

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--registry", str(registry_path),
                        "--rename", "old-slug", "taken"])
    assert ei.value.code == 1
    assert "taken" in capsys.readouterr().err
    assert load_registry(str(registry_path)) == original


def test_main_remap_happy_path(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {"orphan": {"composer_key": "old-ck", "work_key": "old-wk",
                              "published": "2026-01-01"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--remap", "orphan|new-ck|new-wk"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert reg["works"]["orphan"]["composer_key"] == "new-ck"
    assert reg["works"]["orphan"]["work_key"] == "new-wk"


def test_main_remap_composer_namespace(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1, "works": {},
        "composers": {"orphan": {"composer_key": "old-ck", "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path), "--composer",
                         "--remap", "orphan|new-ck"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert reg["composers"]["orphan"]["composer_key"] == "new-ck"


def test_main_remap_redirect_when_successor_registered(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan": {"composer_key": "old-ck", "work_key": "old-wk",
                       "published": "2026-01-01"},
            "canonical-slug": {"composer_key": "new-ck", "work_key": "new-wk",
                                "published": "2026-02-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--remap", "orphan|new-ck|new-wk"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "orphan" not in reg["works"]
    assert reg["redirects"]["works"]["orphan"] == "canonical-slug"


def test_main_remap_refusal_on_unregistered_slug(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    dump_registry(_empty_shell(), str(registry_path))

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--registry", str(registry_path),
                        "--remap", "missing-slug|new-ck|new-wk"])
    assert ei.value.code == 1
    assert "missing-slug" in capsys.readouterr().err
    assert load_registry(str(registry_path)) == _empty_shell()
