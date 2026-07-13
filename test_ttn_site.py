"""Tests for ttn_site: composer slug + composer index (website Phase 1).

Run: uv run --with pytest pytest test_ttn_site.py
"""
import json
import os
import sqlite3

import pytest

import ttn_site
from ttn_site import (composer_slug, build_composer_index, RegistryDriftError,
                       load_registry, dump_registry, sync_registry,
                       apply_rename, apply_remap, RegistryActionError,
                       site_db_path, site_fingerprint, write_site_db,
                       site_status, accumulate_entities, build_work_rows,
                       build_recording_rows, check_closure)
from ttn_analyze import (canonical_key, normalize_composer, strip_arranger_tail,
                          resolve_composer_alias, work_title_key, resolve_work_alias)
from ttn_spine import Recording, Contributor


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
                 "title TEXT, segments_raw_json TEXT)")
    conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "episode_pid TEXT, position INT, time_str TEXT, composer TEXT, "
                 "composer_line TEXT, contributors_json TEXT, title TEXT, performers TEXT)")
    conn.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
                 "version_offset INT, composer_name TEXT, track_title TEXT, "
                 "composer_mbid TEXT, recording_pid TEXT, event_pid TEXT, "
                 "composer_pid TEXT, duration_seconds INT, record_id TEXT, "
                 "record_label TEXT, contributions_json TEXT)")
    conn.execute("INSERT INTO episodes VALUES ('ep1', '2020-01-01T01:00:00Z', "
                 "'Through the Night', NULL)")
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


def test_main_drift_error_prints_orphans_and_remap_hint(tmp_path, monkeypatch, capsys):
    # The drift-recovery path is the registry's whole point at the SECOND
    # build after a canonicalization edit: a registered identity no longer
    # derivable from the corpus must fail the build with the orphaned slug
    # and the --remap fix hint, writing nothing (final-review finding).
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    orphaned = {
        "version": 1,
        "works": {"ghost:work": {"composer_key": "zzz nobody",
                                  "work_key": "zzz nothing",
                                  "published": "2026-01-01"}},
        "composers": {},
        "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(orphaned, str(registry_path))
    before = registry_path.read_bytes()

    monkeypatch.setattr(ttn_site.ttn_project, "load",
                         lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--db", str(db_path), "--registry", str(registry_path)])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "ghost:work" in err          # the orphaned slug is named
    assert "--remap" in err             # the operator's fix hint
    assert registry_path.read_bytes() == before   # nothing written


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


# --- site.sqlite: fingerprint -------------------------------------------------
# site_fingerprint hashes, in order: ttn_site.py, ttn_analyze.py, ttn_aliases.py
# (all beside the module), the projection cache file, and the registry file --
# all via monkeypatched path constants so the real tracked files are never
# touched by a test.

def _fingerprint_env(tmp_path, monkeypatch):
    """Point every byte-source ttn_site.site_fingerprint reads at tmp files,
    each pre-seeded with distinct content. Returns a dict of the tmp paths
    keyed by the same names used in site_fingerprint's docstring."""
    site_py = tmp_path / "ttn_site.py"
    analyze_py = tmp_path / "ttn_analyze.py"
    aliases_py = tmp_path / "ttn_aliases.py"
    projection = tmp_path / "ttn_projection_cache.json"
    registry = tmp_path / "ttn_site_registry.json"

    site_py.write_bytes(b"site-v1")
    analyze_py.write_bytes(b"analyze-v1")
    aliases_py.write_bytes(b"aliases-v1")
    projection.write_bytes(b"projection-v1")
    registry.write_bytes(b"registry-v1")

    monkeypatch.setattr(ttn_site, "__file__", str(site_py))
    monkeypatch.setattr(ttn_site, "_ANALYZE_MODULE_PATH", str(analyze_py))
    monkeypatch.setattr(ttn_site, "_ALIASES_MODULE_PATH", str(aliases_py))
    monkeypatch.setattr(ttn_site.ttn_project, "PROJECTION_PATH", str(projection))

    return {
        "site_py": site_py, "analyze_py": analyze_py, "aliases_py": aliases_py,
        "projection": projection, "registry": registry,
    }


def test_site_fingerprint_changes_when_site_py_bytes_change(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    before = ttn_site.site_fingerprint(str(paths["registry"]))
    paths["site_py"].write_bytes(b"site-v2")
    after = ttn_site.site_fingerprint(str(paths["registry"]))
    assert before != after


def test_site_fingerprint_changes_when_analyze_py_bytes_change(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    before = ttn_site.site_fingerprint(str(paths["registry"]))
    paths["analyze_py"].write_bytes(b"analyze-v2")
    after = ttn_site.site_fingerprint(str(paths["registry"]))
    assert before != after


def test_site_fingerprint_changes_when_aliases_py_bytes_change(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    before = ttn_site.site_fingerprint(str(paths["registry"]))
    paths["aliases_py"].write_bytes(b"aliases-v2")
    after = ttn_site.site_fingerprint(str(paths["registry"]))
    assert before != after


def test_site_fingerprint_changes_when_projection_cache_bytes_change(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    before = ttn_site.site_fingerprint(str(paths["registry"]))
    paths["projection"].write_bytes(b"projection-v2")
    after = ttn_site.site_fingerprint(str(paths["registry"]))
    assert before != after


def test_site_fingerprint_changes_when_registry_bytes_change(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    before = ttn_site.site_fingerprint(str(paths["registry"]))
    paths["registry"].write_bytes(b"registry-v2")
    after = ttn_site.site_fingerprint(str(paths["registry"]))
    assert before != after


def test_site_fingerprint_tolerates_missing_registry_file(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    missing = tmp_path / "nonexistent-registry.json"
    # missing file hashes as the empty string for that slot -- no exception
    fp = ttn_site.site_fingerprint(str(missing))
    assert isinstance(fp, str) and fp


def test_site_fingerprint_tolerates_missing_projection_cache(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    paths["projection"].unlink()
    fp = ttn_site.site_fingerprint(str(paths["registry"]))
    assert isinstance(fp, str) and fp


# --- site.sqlite: db path helper ----------------------------------------------

def test_site_db_path_defaults_beside_module():
    path = site_db_path()
    assert os.path.basename(path) == "site.sqlite"
    assert os.path.dirname(path) == os.path.dirname(os.path.abspath(ttn_site.__file__))


# --- site.sqlite: write_site_db + site_status ---------------------------------

def test_write_site_db_creates_file_with_meta(tmp_path):
    path = tmp_path / "site.sqlite"
    write_site_db(str(path), {}, "fp-abc123")
    assert path.exists()
    assert not (tmp_path / "site.sqlite.tmp").exists()

    conn = sqlite3.connect(str(path))
    row = conn.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
    assert row == ("fp-abc123",)
    built_at = conn.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    assert built_at is not None and built_at[0]
    conn.close()


def test_write_site_db_creates_all_tables_empty(tmp_path):
    path = tmp_path / "site.sqlite"
    write_site_db(str(path), {}, "fp-1")
    conn = sqlite3.connect(str(path))
    for table in ("meta", "works", "composers", "episodes", "recordings", "browse"):
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
        if table == "meta":
            assert n == 2   # fingerprint + built_at
        else:
            assert n == 0
    conn.close()


def test_write_site_db_inserts_provided_rows(tmp_path):
    path = tmp_path / "site.sqlite"
    tables = {
        "composers": [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]")],
    }
    write_site_db(str(path), tables, "fp-2")
    conn = sqlite3.connect(str(path))
    row = conn.execute("SELECT slug, display FROM composers").fetchone()
    assert row == ("beethoven", "Ludwig van Beethoven")
    conn.close()


def test_write_site_db_round_trips_one_row_in_every_table(tmp_path):
    # The arity-drift regression test: a well-formed row for EVERY table (works
    # has 13 columns -- a hand-maintained count map once said 12) must insert
    # and read back verbatim.
    path = tmp_path / "site.sqlite"
    tables = {
        "works": [("beethoven-symphony-5", "beethoven", "beethoven", "symphony-5",
                   "Symphony No 5", "Ludwig van Beethoven", "Op.67", 100,
                   4, 10, "2010-01-17", "2026-06-01", "{}")],
        "composers": [("beethoven", "beethoven", "Ludwig van Beethoven",
                        100, 9, "[]")],
        "episodes": [("b0000001", "2020-01-01", "Through the Night",
                       "https://www.bbc.co.uk/programmes/b0000001", "[]")],
        "recordings": [("p0000001", "beethoven-symphony-5", "beethoven", 1800,
                         "GBBBC", 4, "2012-04-01", "2026-01-01", "[]", "[]")],
        "browse": [("top-works", "{}")],
    }
    write_site_db(str(path), tables, "fp-rt")
    conn = sqlite3.connect(str(path))
    for table, rows in tables.items():
        got = conn.execute(f"SELECT * FROM {table}").fetchall()
        assert got == rows, table
    conn.close()


def test_write_site_db_unknown_table_key_raises_value_error(tmp_path):
    path = tmp_path / "site.sqlite"
    with pytest.raises(ValueError):
        write_site_db(str(path), {"not_a_table": [("x",)]}, "fp-bad-key")
    assert not path.exists()
    assert not (tmp_path / "site.sqlite.tmp").exists()


def test_write_site_db_is_atomic_no_leftover_tmp(tmp_path):
    path = tmp_path / "site.sqlite"
    write_site_db(str(path), {}, "fp-3")
    assert path.exists()
    assert not (tmp_path / "site.sqlite.tmp").exists()


def test_write_site_db_removes_stale_tmp_before_building(tmp_path):
    path = tmp_path / "site.sqlite"
    tmp = tmp_path / "site.sqlite.tmp"
    tmp.write_bytes(b"leftover garbage from a killed prior run")
    write_site_db(str(path), {}, "fp-4")
    assert path.exists()
    assert not tmp.exists()
    # the leftover garbage did not corrupt the real file
    conn = sqlite3.connect(str(path))
    assert conn.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone() == ("fp-4",)
    conn.close()


def test_write_site_db_poisoned_row_leaves_no_residue(tmp_path):
    path = tmp_path / "site.sqlite"
    # composers table has 6 columns; this row has the wrong arity -> executemany fails
    tables = {"composers": [("only", "two")]}
    with pytest.raises(Exception):
        write_site_db(str(path), tables, "fp-5")
    assert not path.exists()
    assert not (tmp_path / "site.sqlite.tmp").exists()


def test_write_site_db_poisoned_row_does_not_clobber_existing_fresh_file(tmp_path):
    path = tmp_path / "site.sqlite"
    write_site_db(str(path), {}, "fp-good")
    good_bytes = path.read_bytes()

    tables = {"composers": [("only", "two")]}
    with pytest.raises(Exception):
        write_site_db(str(path), tables, "fp-bad")

    # the previously-good file at `path` must survive a failed rebuild attempt
    assert path.read_bytes() == good_bytes
    assert not (tmp_path / "site.sqlite.tmp").exists()


# --- site.sqlite: site_status ------------------------------------------------

def test_site_status_missing_file():
    assert site_status("/nonexistent/path/site.sqlite", "fp-1") == "missing"


def test_site_status_fresh_after_write(tmp_path):
    path = tmp_path / "site.sqlite"
    write_site_db(str(path), {}, "fp-match")
    assert site_status(str(path), "fp-match") == "fresh"


def test_site_status_stale_on_fingerprint_mismatch(tmp_path):
    path = tmp_path / "site.sqlite"
    write_site_db(str(path), {}, "fp-old")
    assert site_status(str(path), "fp-new") == "stale"


def test_site_status_corrupt_file_is_missing_not_exception(tmp_path):
    path = tmp_path / "site.sqlite"
    path.write_bytes(b"not a sqlite file at all, just garbage bytes")
    assert site_status(str(path), "fp-1") == "missing"


def test_site_status_valid_sqlite_no_meta_table_is_missing(tmp_path):
    path = tmp_path / "site.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()
    assert site_status(str(path), "fp-1") == "missing"


def test_site_status_meta_table_no_fingerprint_row_is_missing(tmp_path):
    path = tmp_path / "site.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('built_at', '2026-01-01T00:00:00')")
    conn.commit()
    conn.close()
    assert site_status(str(path), "fp-1") == "missing"


# --- build wiring: _run_build calls site machinery ----------------------------

def test_main_build_writes_site_db_after_registry_sync(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db)])
    assert rc in (0, None)
    assert site_db.exists()

    conn = sqlite3.connect(str(site_db))
    fp_row = conn.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
    assert fp_row is not None and fp_row[0]
    conn.close()


def test_main_build_end_to_end_populates_all_five_tables_and_settles_fresh(
        tmp_path, monkeypatch):
    # Task 7: the FULL build wiring -- work/composer/episode/recording/browse,
    # driven off the fixture DB's two text-only tracks (no segment_events rows,
    # so recs/cons/broadcasters are legitimately empty -- but every table must
    # still get a row for the two tracked works/composers/one episode).
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db)])
    assert rc in (0, None)

    conn = sqlite3.connect(str(site_db))
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("works", "composers", "episodes", "recordings", "browse")}
    conn.close()

    assert counts["works"] == 2                 # Symphony No 5 + Requiem
    assert counts["composers"] == 2              # Beethoven + Mozart
    assert counts["episodes"] == 1                # ep1
    assert counts["recordings"] == 0              # no segment_events rows in the fixture
    assert counts["browse"] == 4                  # top_works/years/broadcasters/house_recordings

    fp = ttn_site.site_fingerprint(str(registry_path))
    assert ttn_site.site_status(str(site_db), fp) == "fresh"


def test_main_build_composer_slug_collision_is_registry_authoritative(
        tmp_path, monkeypatch):
    # Task-7 review fix: two DISTINCT composer identities whose display names
    # kebab to the SAME slug. canonical_key keeps apostrophes on the composer
    # side ("anna o'test" != "anna o test") but composer_slug's kebab folds
    # both to 'anna-o-test'. Without the registry overlay on composer_entries
    # the composers table emits two IDENTICAL PKs (UNIQUE-constraint abort);
    # with it, one gets the '-2' registry suffix and every cross-reference
    # agrees with the registry.
    db_path = tmp_path / "fixture.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT, "
                 "title TEXT, segments_raw_json TEXT)")
    conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "episode_pid TEXT, position INT, time_str TEXT, composer TEXT, "
                 "composer_line TEXT, contributors_json TEXT, title TEXT, performers TEXT)")
    conn.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
                 "version_offset INT, composer_name TEXT, track_title TEXT, "
                 "composer_mbid TEXT, recording_pid TEXT, event_pid TEXT, "
                 "composer_pid TEXT, duration_seconds INT, record_id TEXT, "
                 "record_label TEXT, contributions_json TEXT)")
    conn.execute("INSERT INTO episodes VALUES ('ep1', '2020-01-01T01:00:00Z', "
                 "'Through the Night', NULL)")
    conn.execute("INSERT INTO tracks (episode_pid, position, time_str, composer, "
                 "composer_line, title, performers) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 ("ep1", 0, "01:00 AM", "Anna O'Test", "Anna O'Test",
                  "First Fancy", "P1"))
    conn.execute("INSERT INTO tracks (episode_pid, position, time_str, composer, "
                 "composer_line, title, performers) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 ("ep1", 1, "02:00 AM", "Anna O Test", "Anna O Test",
                  "Second Fancy", "P2"))
    conn.commit()
    conn.close()

    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db)])
    assert rc in (0, None)

    reg = load_registry(str(registry_path))
    composer_slug_of = {v["composer_key"]: slug
                        for slug, v in reg["composers"].items()}
    # sanity: the fixture really produced 2 identities colliding on one base
    assert set(composer_slug_of.values()) == {"anna-o-test", "anna-o-test-2"}

    conn = sqlite3.connect(str(site_db))
    composer_rows = conn.execute(
        "SELECT slug, composer_key FROM composers").fetchall()
    work_rows = conn.execute(
        "SELECT composer_key, composer_slug FROM works").fetchall()
    conn.close()

    # BOTH composers landed (no UNIQUE-constraint abort), keyed at the
    # registry's slugs -- the suffixed one included.
    assert {slug for slug, _ck in composer_rows} == {"anna-o-test", "anna-o-test-2"}
    for slug, ck in composer_rows:
        assert slug == composer_slug_of[ck]

    # every works row's composer_slug agrees with the registry mapping
    assert len(work_rows) == 2
    for ck, cslug in work_rows:
        assert cslug == composer_slug_of[ck]


def test_main_build_second_run_is_a_noop_skip(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                   "--site-db", str(site_db)])
    capsys.readouterr()
    mtime_before = site_db.stat().st_mtime_ns

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db)])
    assert rc in (0, None)
    out = capsys.readouterr().out
    assert "fresh" in out.lower() and "skip" in out.lower()
    assert site_db.stat().st_mtime_ns == mtime_before


def test_main_build_force_rebuilds_even_when_fresh(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                   "--site-db", str(site_db)])
    mtime_before = site_db.stat().st_mtime_ns

    import time
    time.sleep(0.01)

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--force"])
    assert rc in (0, None)
    assert site_db.stat().st_mtime_ns != mtime_before


def test_main_build_site_db_default_path_uses_site_db_path(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"

    fake_site_db = tmp_path / "default-site.sqlite"
    monkeypatch.setattr(ttn_site, "site_db_path", lambda: str(fake_site_db))
    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path)])
    assert rc in (0, None)
    assert fake_site_db.exists()


# --- accumulate_entities: the corpus-pass entity accumulators (task 5) -------
# rows8: (title, composer, composer_line, performers, bdate, episode_pid,
#         position, time_str) -- the profile-card 7-tuple + time_str.

def _key_for(title, composer, composer_line):
    """Compute the expected (ck, wk) via the real chain -- never hand-guessed."""
    stripped = strip_arranger_tail(composer, composer_line)
    ck = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
    wk = resolve_work_alias(work_title_key(title, stripped))
    return ck, wk


def test_accumulate_projected_row_inherits_clean_identity():
    # text-only row says "Beethoven, Symphony 5 (live)"; the recording's clean
    # segment metadata is "Ludwig van Beethoven" / "Symphony No. 5".
    rows = [("Symphony 5 (live)", "Beethoven", "Beethoven", "Berlin Phil",
             "2020-01-01", "ep1", 0, "01:00 AM")]
    projection = {("ep1", 0): "rec1"}
    rec_meta = {"rec1": ("Ludwig van Beethoven", "Symphony No. 5")}

    result = accumulate_entities(rows, projection, rec_meta)

    expected_key = _key_for("Symphony No. 5", "Ludwig van Beethoven", "Ludwig van Beethoven")
    assert expected_key in result["work_airings"]
    assert result["work_airings"][expected_key] == [
        ("2020-01-01", "rec1", "Berlin Phil", "ep1", 0)]

    tracks = result["episode_tracks"]["ep1"]
    assert len(tracks) == 1
    pos, time_str, key, composer_display, title_display, performers, rp = tracks[0]
    assert pos == 0
    assert time_str == "01:00 AM"
    assert key == expected_key
    assert composer_display == "Ludwig van Beethoven"
    assert title_display == "Symphony No. 5"
    assert performers == "Berlin Phil"
    assert rp == "rec1"


def test_accumulate_text_only_row_keeps_rp_none_and_raw_display():
    rows = [("Nocturne in E flat", "Chopin", "Chopin", "Zimerman",
             "2019-05-01", "ep2", 0, "02:00 AM")]
    projection = {}
    rec_meta = {}

    result = accumulate_entities(rows, projection, rec_meta)

    expected_key = _key_for("Nocturne in E flat", "Chopin", "Chopin")
    assert result["work_airings"][expected_key] == [
        ("2019-05-01", None, "Zimerman", "ep2", 0)]

    pos, time_str, key, composer_display, title_display, performers, rp = \
        result["episode_tracks"]["ep2"][0]
    assert key == expected_key
    assert composer_display == "Chopin"
    assert title_display == "Nocturne in E flat"
    assert rp is None
    assert "ep2" not in result["recording_airings"].get("rec1", [])
    assert not any("ep2" in v for v in result["recording_airings"].values())


def test_accumulate_junk_row_lands_in_episode_tracks_with_none_key_and_no_work_airing():
    rows = [("", "", "", "", "2019-05-01", "ep3", 0, "03:00 AM")]
    projection = {}
    rec_meta = {}

    result = accumulate_entities(rows, projection, rec_meta)

    # confirm this really is the empty-ck-and-wk case per build_work_index's gate
    ck, wk = _key_for("", "", "")
    assert not ck and not wk

    pos, time_str, key, composer_display, title_display, performers, rp = \
        result["episode_tracks"]["ep3"][0]
    assert key is None
    assert (ck, wk) not in result["work_airings"]
    assert result["work_airings"] == {}


def test_accumulate_position_order_preserved_even_when_rows_arrive_out_of_order():
    rows = [
        ("Piece B", "Composer X", "Composer X", "Perf B", "2020-01-01", "ep4", 2, "03:00 AM"),
        ("Piece A", "Composer X", "Composer X", "Perf A", "2020-01-01", "ep4", 0, "01:00 AM"),
        ("Piece C", "Composer X", "Composer X", "Perf C", "2020-01-01", "ep4", 1, "02:00 AM"),
    ]
    result = accumulate_entities(rows, {}, {})

    positions = [row[0] for row in result["episode_tracks"]["ep4"]]
    assert positions == [0, 1, 2]
    titles = [row[4] for row in result["episode_tracks"]["ep4"]]
    assert titles == ["Piece A", "Piece C", "Piece B"]


def test_accumulate_two_airings_of_same_work_different_episodes_accumulate_in_order():
    rows = [
        ("Requiem", "Mozart", "Mozart", "LSO", "2019-01-01", "ep5", 0, "01:00 AM"),
        ("Requiem", "Mozart", "Mozart", "BBC SO", "2021-06-01", "ep6", 3, "04:00 AM"),
    ]
    result = accumulate_entities(rows, {}, {})

    expected_key = _key_for("Requiem", "Mozart", "Mozart")
    assert result["work_airings"][expected_key] == [
        ("2019-01-01", None, "LSO", "ep5", 0),
        ("2021-06-01", None, "BBC SO", "ep6", 3),
    ]


def test_accumulate_projected_row_lands_in_recording_airings():
    rows = [
        ("Symphony 5", "Beethoven", "Beethoven", "Berlin Phil",
         "2020-01-01", "ep1", 0, "01:00 AM"),
        ("Nocturne", "Chopin", "Chopin", "Zimerman",
         "2019-05-01", "ep2", 0, "02:00 AM"),
    ]
    projection = {("ep1", 0): "rec1"}
    rec_meta = {"rec1": ("Ludwig van Beethoven", "Symphony No. 5")}

    result = accumulate_entities(rows, projection, rec_meta)

    assert result["recording_airings"] == {"rec1": [("2020-01-01", "ep1")]}


def test_accumulate_every_row_lands_in_episode_tracks_including_junk():
    rows = [
        ("Requiem", "Mozart", "Mozart", "LSO", "2019-01-01", "ep7", 0, "01:00 AM"),
        ("", "", "", "", "2019-01-01", "ep7", 1, "02:00 AM"),
    ]
    result = accumulate_entities(rows, {}, {})

    assert len(result["episode_tracks"]["ep7"]) == 2
    assert len(result["work_airings"]) == 1


# --- build_work_rows / build_recording_rows: batched aggregates (task 6) ----
# entries: build_work_index-shaped dicts (key, slug, composer_display,
#          work_display, airings, spellings) WITH canonical slugs overlaid.
# recs/cons: whole-corpus ttn_spine.build_recordings/build_contributors output
#            -- built directly from the real namedtuples, not a DB.

def _rec(rp, composer_identity="name:beethoven", composer_display="Beethoven",
          composer_mbid=None, duration=1800, segment_title="Symphony No. 5",
          airing_count=1, first="2020-01-01", last="2020-01-01"):
    return Recording(rp, composer_identity, composer_display, composer_mbid,
                      duration, segment_title, airing_count, first, last)


def _con(role, identity_key, display_name, mbid=None):
    return Contributor(role, identity_key, display_name, mbid)


WORK_KEY = ("beethoven", "§op67|5")


def test_build_work_rows_two_recordings_plus_text_only():
    entries = [{
        "key": WORK_KEY, "slug": "beethoven-symphony-5",
        "composer_display": "Ludwig van Beethoven",
        "work_display": "Symphony No. 5",
        "airings": 3, "spellings": ["Symphony No. 5", "Symphony 5"],
    }]
    work_airings = {
        WORK_KEY: [
            ("2020-01-01", "rec1", "Berlin Phil / Karajan", "ep1", 0),
            ("2019-06-01", "rec2", "Vienna Phil / Bernstein", "ep2", 1),
            ("2018-03-01", None, "LSO / Davis", "ep3", 0),   # text-only
        ],
    }
    composer_slug_of = {"beethoven": "beethoven"}
    recs = {
        "rec1": _rec("rec1", airing_count=2, first="2020-01-01", last="2021-01-01"),
        "rec2": _rec("rec2", airing_count=1, first="2019-06-01", last="2019-06-01"),
    }
    cons = {
        "rec1": [
            _con("Conductor", "name:karajan", "Herbert von Karajan"),
            _con("Orchestra", "name:berlinphil", "Berlin Philharmonic"),
        ],
        "rec2": [
            _con("Conductor", "name:bernstein", "Leonard Bernstein"),
            _con("Performer", "name:soloist", "A Soloist"),
        ],
    }
    brc_rows_by_rp = {
        "rec1": ["GBBBC", "GBBBC"],
        "rec2": ["PLPR"],
    }

    rows = build_work_rows(entries, work_airings, composer_slug_of, recs, cons,
                            brc_rows_by_rp)

    assert len(rows) == 1
    (slug, cslug, ck, wk, work_display, composer_display, catalogue, airings,
     n_recordings, n_text_only, first_aired, last_aired, facets_json) = rows[0]

    assert slug == "beethoven-symphony-5"
    assert cslug == "beethoven"
    assert ck == "beethoven"
    assert wk == WORK_KEY[1]
    assert work_display == "Symphony No. 5"
    assert composer_display == "Ludwig van Beethoven"
    assert catalogue == "op67"          # text between § and first |
    assert airings == 3
    assert n_recordings == 2
    assert n_text_only == 1
    assert first_aired == "2018-03-01"
    assert last_aired == "2020-01-01"

    facets = json.loads(facets_json)
    assert set(facets) == {"recordings", "top_performers", "top_conductors",
                            "top_ensembles", "by_year", "broadcasters"}

    # recordings list: sorted by (-airing_count, recording_pid) -- rec1 (2) before rec2 (1)
    rec_pids = [r["recording_pid"] for r in facets["recordings"]]
    assert rec_pids == ["rec1", "rec2"]

    # top-contributor ranking: both conductors present, ranked deterministically
    conductor_names = {c["display_name"] for c in facets["top_conductors"]}
    assert conductor_names == {"Herbert von Karajan", "Leonard Bernstein"}

    ensemble_names = {e["display_name"] for e in facets["top_ensembles"]}
    assert ensemble_names == {"Berlin Philharmonic"}

    # by_year: 3 distinct years
    years = {y["year"] for y in facets["by_year"]}
    assert years == {"2018", "2019", "2020"}
    total_by_year = sum(y["airings"] for y in facets["by_year"])
    assert total_by_year == 3

    # broadcasters: majority decode from brc_rows_by_rp for the work's rps
    broadcaster_keys = {b["key"] for b in facets["broadcasters"]}
    assert "GBBBC" in broadcaster_keys or "PLPR" in broadcaster_keys


def test_build_work_rows_fully_text_only_empty_facets():
    key = ("chopin", "nocturne in e flat")
    entries = [{
        "key": key, "slug": "chopin-nocturne-in-e-flat",
        "composer_display": "Chopin", "work_display": "Nocturne in E flat",
        "airings": 1, "spellings": ["Nocturne in E flat"],
    }]
    work_airings = {
        key: [("2015-01-01", None, "Zimerman", "ep9", 0)],
    }
    composer_slug_of = {"chopin": "chopin"}

    rows = build_work_rows(entries, work_airings, composer_slug_of, {}, {}, {})

    assert len(rows) == 1
    row = rows[0]
    assert row[7] == 1          # airings
    assert row[8] == 0          # n_recordings
    assert row[9] == 1          # n_text_only
    assert row[6] is None       # catalogue -- no § prefix

    facets = json.loads(row[-1])
    assert facets["recordings"] == []
    assert facets["top_performers"] == []
    assert facets["top_conductors"] == []
    assert facets["top_ensembles"] == []
    assert facets["broadcasters"] == []
    assert len(facets["by_year"]) == 1


def test_build_work_rows_catalogue_none_when_no_section_marker():
    key = ("brahms", "hungarian dance no 5")
    entries = [{
        "key": key, "slug": "brahms-hungarian-dance-no-5",
        "composer_display": "Brahms", "work_display": "Hungarian Dance No. 5",
        "airings": 1, "spellings": ["Hungarian Dance No. 5"],
    }]
    work_airings = {key: [("2015-01-01", None, "LSO", "ep1", 0)]}
    rows = build_work_rows(entries, work_airings, {"brahms": "brahms"}, {}, {}, {})
    assert rows[0][6] is None


# --- build_recording_rows ----------------------------------------------------

def test_build_recording_rows_basic_columns_and_order():
    work_key = ("beethoven", "§op67|5")
    work_airings = {
        work_key: [
            ("2020-01-01", "rec1", "Berlin Phil", "ep1", 0),
            ("2021-05-01", "rec1", "Berlin Phil 2", "ep2", 0),
        ],
    }
    recording_airings = {
        "rec1": [("2020-01-01", "ep1"), ("2021-05-01", "ep2")],
    }
    work_slug_of = {work_key: "beethoven-symphony-5"}
    composer_slug_of = {"beethoven": "beethoven"}
    recs = {"rec1": _rec("rec1", duration=1900, airing_count=2,
                          first="2020-01-01", last="2021-05-01")}
    cons = {"rec1": [_con("Conductor", "name:karajan", "Herbert von Karajan")]}
    brc_rows_by_rp = {"rec1": ["GBBBC", "GBBBC", "PLPR"]}

    rows, n_multi_work, n_skipped = build_recording_rows(
        work_airings, recording_airings, work_slug_of, composer_slug_of,
        recs, cons, brc_rows_by_rp)

    assert n_multi_work == 0
    assert n_skipped == 0
    assert len(rows) == 1
    (rp, work_slug, composer_slug_, duration, broadcaster, airings,
     first_aired, last_aired, contributors_json, airing_dates_json) = rows[0]

    assert rp == "rec1"
    assert work_slug == "beethoven-symphony-5"
    assert composer_slug_ == "beethoven"
    assert duration == 1900
    assert broadcaster == "BBC"          # majority label GBBBC decoded
    assert airings == 2
    assert first_aired == "2020-01-01"
    assert last_aired == "2021-05-01"

    contributors = json.loads(contributors_json)
    assert contributors == [{"role": "Conductor", "name": "Herbert von Karajan"}]

    dates = json.loads(airing_dates_json)
    assert dates == [["2020-01-01", "ep1"], ["2021-05-01", "ep2"]]


def test_build_recording_rows_multi_work_assigns_majority_and_counts():
    work_a = ("x", "work a")
    work_b = ("x", "work b")
    work_airings = {
        work_a: [("2020-01-01", "rec9", "P1", "ep1", 0),
                 ("2020-02-01", "rec9", "P2", "ep2", 0)],
        work_b: [("2020-03-01", "rec9", "P3", "ep3", 0)],
    }
    recording_airings = {
        "rec9": [("2020-01-01", "ep1"), ("2020-02-01", "ep2"), ("2020-03-01", "ep3")],
    }
    work_slug_of = {work_a: "x-work-a", work_b: "x-work-b"}
    composer_slug_of = {"x": "x"}
    recs = {"rec9": _rec("rec9", duration=100, airing_count=3)}
    cons = {}
    brc_rows_by_rp = {}

    rows, n_multi_work, n_skipped = build_recording_rows(
        work_airings, recording_airings, work_slug_of, composer_slug_of,
        recs, cons, brc_rows_by_rp)

    assert n_multi_work == 1
    assert len(rows) == 1
    assert rows[0][0] == "rec9"
    assert rows[0][1] == "x-work-a"     # majority: 2 airings vs 1
    assert rows[0][4] is None            # no broadcaster rows -> None


def test_build_recording_rows_multi_work_tie_breaks_lexicographically():
    work_a = ("x", "work b")   # slug 'x-work-b' -- deliberately the "later" work key
    work_b = ("x", "work a")   # slug 'x-work-a' -- lexicographically smaller slug
    work_airings = {
        work_a: [("2020-01-01", "rec8", "P1", "ep1", 0)],
        work_b: [("2020-01-02", "rec8", "P2", "ep2", 0)],
    }
    recording_airings = {"rec8": [("2020-01-01", "ep1"), ("2020-01-02", "ep2")]}
    work_slug_of = {work_a: "x-work-b", work_b: "x-work-a"}
    composer_slug_of = {"x": "x"}
    recs = {"rec8": _rec("rec8", airing_count=2)}

    rows, n_multi_work, n_skipped = build_recording_rows(
        work_airings, recording_airings, work_slug_of, composer_slug_of,
        recs, {}, {})

    assert n_multi_work == 1
    assert rows[0][1] == "x-work-a"      # tie -> lexicographically smallest slug


def test_build_recording_rows_skips_recording_absent_from_spine():
    work_key = ("x", "work a")
    work_airings = {work_key: [("2020-01-01", "rec-missing", "P1", "ep1", 0)]}
    recording_airings = {"rec-missing": [("2020-01-01", "ep1")]}
    work_slug_of = {work_key: "x-work-a"}
    composer_slug_of = {"x": "x"}

    rows, n_multi_work, n_skipped = build_recording_rows(
        work_airings, recording_airings, work_slug_of, composer_slug_of,
        {}, {}, {})     # recs empty -- rec-missing not present

    assert rows == []
    assert n_skipped == 1
    assert n_multi_work == 0


def test_build_recording_rows_no_broadcaster_labels_is_none():
    work_key = ("x", "work a")
    work_airings = {work_key: [("2020-01-01", "rec1", "P1", "ep1", 0)]}
    recording_airings = {"rec1": [("2020-01-01", "ep1")]}
    rows, _, _ = build_recording_rows(
        work_airings, recording_airings, {work_key: "x-work-a"}, {"x": "x"},
        {"rec1": _rec("rec1")}, {}, {"rec1": []})
    assert rows[0][4] is None


def test_build_recording_rows_non_ebu_label_uses_raw_code():
    work_key = ("x", "work a")
    work_airings = {work_key: [("2020-01-01", "rec1", "P1", "ep1", 0)]}
    recording_airings = {"rec1": [("2020-01-01", "ep1")]}
    rows, _, _ = build_recording_rows(
        work_airings, recording_airings, {work_key: "x-work-a"}, {"x": "x"},
        {"rec1": _rec("rec1")}, {}, {"rec1": ["SomeCommercialLabel"]})
    assert rows[0][4] == "SomeCommercialLabel"


def test_build_recording_rows_empty_string_majority_label_is_none():
    # task-6 review fix: a majority label that decodes to '' (an empty-string
    # record_label counted as a "majority") must yield broadcaster=None, not
    # the empty string -- 'no attribution' should look the same everywhere.
    work_key = ("x", "work a")
    work_airings = {work_key: [("2020-01-01", "rec1", "P1", "ep1", 0)]}
    recording_airings = {"rec1": [("2020-01-01", "ep1")]}
    rows, _, _ = build_recording_rows(
        work_airings, recording_airings, {work_key: "x-work-a"}, {"x": "x"},
        {"rec1": _rec("rec1")}, {}, {"rec1": ["", ""]})
    assert rows[0][4] is None


def test_build_work_rows_and_recording_rows_json_round_trip_serializable():
    key = ("beethoven", "§op67|5")
    entries = [{
        "key": key, "slug": "beethoven-symphony-5",
        "composer_display": "Beethoven", "work_display": "Symphony No. 5",
        "airings": 1, "spellings": ["Symphony No. 5"],
    }]
    work_airings = {key: [("2020-01-01", "rec1", "Berlin Phil", "ep1", 0)]}
    recs = {"rec1": _rec("rec1")}
    cons = {"rec1": [_con("Singer", "name:x", "A Singer", mbid="mbid-123")]}
    brc_rows_by_rp = {"rec1": ["GBBBC"]}

    work_rows = build_work_rows(entries, work_airings, {"beethoven": "beethoven"},
                                 recs, cons, brc_rows_by_rp)
    # every value must already be JSON/SQLite-native
    json.dumps(work_rows[0])

    recording_airings = {"rec1": [("2020-01-01", "ep1")]}
    rec_rows, _, _ = build_recording_rows(
        work_airings, recording_airings, {key: "beethoven-symphony-5"},
        {"beethoven": "beethoven"}, recs, cons, brc_rows_by_rp)
    json.dumps(rec_rows[0])


# --- build_composer_rows / build_episode_rows / build_browse_payloads (task 7) -

from ttn_site import build_composer_rows, build_episode_rows, build_browse_payloads  # noqa: E402


def test_build_composer_rows_works_json_ranked_and_deterministic():
    composer_entries = [{
        "composer_key": "beethoven", "slug": "beethoven",
        "display": "Ludwig van Beethoven", "airings": 5, "n_works": 2,
        "spellings": ["Ludwig van Beethoven"],
    }]
    work_entries = [
        {"key": ("beethoven", "§op67|5"), "slug": "beethoven-symphony-5",
         "composer_display": "Ludwig van Beethoven", "work_display": "Symphony No. 5"},
        {"key": ("beethoven", "§op125|9"), "slug": "beethoven-symphony-9",
         "composer_display": "Ludwig van Beethoven", "work_display": "Symphony No. 9"},
    ]
    work_airings = {
        ("beethoven", "§op67|5"): [("2020-01-01", None, "P", "ep1", 0)] * 3,
        ("beethoven", "§op125|9"): [("2020-01-01", None, "P", "ep2", 0)] * 2,
    }
    composer_slug_of = {"beethoven": "beethoven"}
    work_slug_of = {("beethoven", "§op67|5"): "beethoven-symphony-5",
                     ("beethoven", "§op125|9"): "beethoven-symphony-9"}

    rows = build_composer_rows(composer_entries, work_entries, work_airings,
                                composer_slug_of, work_slug_of)

    assert len(rows) == 1
    slug, ck, display, airings, n_works, works_json = rows[0]
    assert slug == "beethoven"
    assert ck == "beethoven"
    assert display == "Ludwig van Beethoven"
    assert airings == 5
    assert n_works == 2

    works = json.loads(works_json)
    assert [w["slug"] for w in works] == ["beethoven-symphony-5", "beethoven-symphony-9"]
    assert works[0]["airings"] == 3 and works[1]["airings"] == 2
    assert works[0]["display"] == "Symphony No. 5"


def test_build_composer_rows_works_json_tie_break_by_slug():
    composer_entries = [{
        "composer_key": "x", "slug": "x", "display": "X", "airings": 2, "n_works": 2,
        "spellings": ["X"],
    }]
    work_entries = [
        {"key": ("x", "b"), "slug": "x-b", "composer_display": "X", "work_display": "B"},
        {"key": ("x", "a"), "slug": "x-a", "composer_display": "X", "work_display": "A"},
    ]
    work_airings = {
        ("x", "b"): [("2020-01-01", None, "P", "ep1", 0)],
        ("x", "a"): [("2020-01-01", None, "P", "ep2", 0)],
    }
    rows = build_composer_rows(composer_entries, work_entries, work_airings,
                                {"x": "x"}, {("x", "b"): "x-b", ("x", "a"): "x-a"})
    works = json.loads(rows[0][5])
    # equal airings -> tie-break by slug ascending
    assert [w["slug"] for w in works] == ["x-a", "x-b"]


def test_build_composer_rows_skips_composer_with_no_works():
    composer_entries = [{
        "composer_key": "nobody", "slug": "nobody", "display": "Nobody",
        "airings": 0, "n_works": 0, "spellings": [],
    }]
    rows = build_composer_rows(composer_entries, [], {}, {"nobody": "nobody"}, {})
    assert len(rows) == 1
    works = json.loads(rows[0][5])
    assert works == []


def test_build_composer_rows_slug_column_comes_from_overlaid_entry():
    # The row PK must be whatever slug the entry carries AFTER the caller's
    # registry overlay -- a collision-suffixed registry slug ('x-2') must key
    # the row, not the raw derived slug (task-7 review fix: the overlay in
    # _run_build must reach composer_entries too, and this builder must
    # faithfully emit the overlaid value).
    composer_entries = [{
        "composer_key": "x", "slug": "x-2", "display": "X", "airings": 1,
        "n_works": 1, "spellings": ["X"],
    }]
    rows = build_composer_rows(composer_entries, [], {}, {"x": "x-2"}, {})
    assert rows[0][0] == "x-2"


# --- build_episode_rows -------------------------------------------------------

def test_build_episode_rows_basic_shape_and_bbc_url():
    episode_meta = [("ep1", "2020-01-01", "Through the Night")]
    episode_tracks = {
        "ep1": [(0, "01:00 AM", ("beethoven", "sym5"), "Ludwig van Beethoven",
                 "Symphony No. 5", "Berlin Phil", "rec1")],
    }
    work_slug_of = {("beethoven", "sym5"): "beethoven-symphony-5"}
    composer_slug_of = {"beethoven": "beethoven"}

    rows = build_episode_rows(episode_meta, episode_tracks, work_slug_of,
                              composer_slug_of, {"rec1"})

    assert len(rows) == 1
    pid, date, title, bbc_url, tracks_json = rows[0]
    assert pid == "ep1"
    assert date == "2020-01-01"
    assert title == "Through the Night"
    assert bbc_url == "https://www.bbc.co.uk/programmes/ep1"

    tracks = json.loads(tracks_json)
    assert len(tracks) == 1
    t = tracks[0]
    assert t == {
        "pos": 0, "time": "01:00 AM",
        "work_slug": "beethoven-symphony-5", "composer_slug": "beethoven",
        "composer": "Ludwig van Beethoven", "title": "Symphony No. 5",
        "performers": "Berlin Phil", "recording_pid": "rec1",
    }


def test_build_episode_rows_junk_row_has_null_slugs():
    episode_meta = [("ep1", "2020-01-01", "TTN")]
    episode_tracks = {
        "ep1": [(0, "01:00 AM", None, "", "", "", None)],
    }
    rows = build_episode_rows(episode_meta, episode_tracks, {}, {}, set())
    tracks = json.loads(rows[0][4])
    assert tracks[0]["work_slug"] is None
    assert tracks[0]["composer_slug"] is None


def test_build_episode_rows_zero_track_episode_gets_empty_list():
    episode_meta = [("anchor1", "2008-08-01", "TTN")]
    episode_tracks = {}   # no rows for this episode at all
    rows = build_episode_rows(episode_meta, episode_tracks, {}, {}, set())
    assert len(rows) == 1
    pid, date, title, bbc_url, tracks_json = rows[0]
    assert pid == "anchor1"
    assert json.loads(tracks_json) == []


def test_build_episode_rows_multi_episode_date_one_row_per_pid():
    episode_meta = [
        ("m00113tp", "2021-10-31", "TTN"),
        ("m00113tv", "2021-10-31", "TTN"),
        ("m00113tz", "2021-10-31", "TTN"),
    ]
    rows = build_episode_rows(episode_meta, {}, {}, {}, set())
    assert len(rows) == 3
    assert {r[0] for r in rows} == {"m00113tp", "m00113tv", "m00113tz"}
    assert all(r[1] == "2021-10-31" for r in rows)


def test_build_episode_rows_tracks_in_broadcast_order():
    episode_meta = [("ep1", "2020-01-01", "TTN")]
    episode_tracks = {
        "ep1": [
            (1, "02:00 AM", None, "B", "Y", "P2", None),
            (0, "01:00 AM", None, "A", "X", "P1", None),
        ],
    }
    rows = build_episode_rows(episode_meta, episode_tracks, {}, {}, set())
    tracks = json.loads(rows[0][4])
    assert [t["pos"] for t in tracks] == [0, 1]


def test_build_work_rows_empty_composer_key_yields_null_composer_slug(tmp_path):
    # build_work_index admits ("", wk) keys (only both-empty is excluded);
    # such a work has no composer page, so composer_slug is None and the
    # schema must accept it -- a NOT NULL would abort the whole build with
    # an opaque IntegrityError on the first future blank-composer projection
    # target (final-review finding). Round-trip through write_site_db +
    # check_closure to pin both the nullable column and the closure pass.
    entry = {"key": ("", "orphan title"), "slug": "w12345678",
             "composer_display": "", "work_display": "Orphan Title",
             "airings": 1, "spellings": ["Orphan Title"]}
    work_airings = {("", "orphan title"): [("2020-01-01", None, "P", "ep1", 0)]}
    rows = build_work_rows([entry], work_airings, {}, {}, {}, {})
    assert rows[0][1] is None            # composer_slug column

    db = tmp_path / "site.sqlite"
    write_site_db(str(db), {"works": rows}, "fp", validate=check_closure)
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT composer_slug FROM works").fetchone() == (None,)
    conn.close()


def test_build_episode_rows_unknown_recording_link_nulled():
    # A projected rp with no recordings-table row (spine-excluded interstitial
    # -- b0833vgj's segment-backfilled Milhaud filler is the live case -- or a
    # build_recording_rows skip) must NOT dangle: the link is nulled, the
    # track still renders as text. Caught by check_closure on the real corpus.
    episode_meta = [("ep1", "2020-01-01", "TTN")]
    episode_tracks = {
        "ep1": [
            (0, "01:00 AM", ("milhaud", "cheminee"), "Darius Milhaud",
             "La Cheminée du Roi René", "", "p_interstitial"),
            (1, "01:01 AM", ("beethoven", "sym5"), "Ludwig van Beethoven",
             "Symphony No. 5", "Berlin Phil", "p_real"),
        ],
    }
    rows = build_episode_rows(episode_meta, episode_tracks, {}, {}, {"p_real"})
    tracks = json.loads(rows[0][4])
    assert tracks[0]["recording_pid"] is None      # excluded rp: link nulled
    assert tracks[0]["title"] == "La Cheminée du Roi René"  # text kept
    assert tracks[1]["recording_pid"] == "p_real"  # emitted rp: link kept


# --- build_browse_payloads ----------------------------------------------------

def test_build_browse_payloads_top_works_capped_at_100_and_shaped():
    work_entries = [
        {"key": ("c", f"w{i}"), "slug": f"w{i}", "composer_display": "C",
         "work_display": f"Work {i}"}
        for i in range(120)
    ]
    work_airings = {
        ("c", f"w{i}"): [("2020-01-01", None, "P", f"ep{i}", 0)] * (120 - i)
        for i in range(120)
    }
    payloads = build_browse_payloads(
        work_entries, work_airings, [], [], {("c", f"w{i}"): f"w{i}" for i in range(120)},
        {"c": "c"}, {}, {})
    names = dict(payloads)
    top_works = json.loads(names["top_works"])
    assert len(top_works) == 100
    assert top_works[0]["slug"] == "w0"          # highest airings (120)
    assert top_works[0]["airings"] == 120
    assert set(top_works[0]) == {"slug", "display", "composer_display",
                                  "composer_slug", "airings"}


def test_build_browse_payloads_years_and_broadcasters_serialized():
    all_rows5 = [("Sym 5", "Beethoven", "Beethoven", "P", "2020-01-01")]
    all_brc_rows = [("GBBBC", "rec1"), ("PLPR", "rec1")]
    payloads = build_browse_payloads([], {}, all_rows5, all_brc_rows, {}, {}, {}, {})
    names = dict(payloads)

    years = json.loads(names["years"])
    assert years[0]["year"] == "2020"
    assert years[0]["airings"] == 1

    broadcasters = json.loads(names["broadcasters"])
    assert {b["key"] for b in broadcasters} == {"GBBBC", "PLPR"}


def test_build_browse_payloads_house_recordings_dominant_and_share():
    key = ("c", "w")
    work_entries = [{"key": key, "slug": "c-w", "composer_display": "C",
                      "work_display": "W"}]
    # 3 airings on rec1 (2016+), 1 on rec2 (2016+), 1 pre-2016 (excluded),
    # 1 text-only (rp None, excluded)
    work_airings = {
        key: [
            ("2016-01-01", "rec1", "P", "ep1", 0),
            ("2017-01-01", "rec1", "P", "ep2", 0),
            ("2018-01-01", "rec1", "P", "ep3", 0),
            ("2019-01-01", "rec2", "P", "ep4", 0),
            ("2010-01-01", "rec1", "P", "ep5", 0),   # pre-2016, excluded
            ("2020-01-01", None, "P", "ep6", 0),      # text-only, excluded
        ],
    }
    composer_slug_of = {"c": "c"}
    work_slug_of = {key: "c-w"}
    recs = {"rec1": _rec("rec1"), "rec2": _rec("rec2")}
    cons = {"rec1": [_con("Conductor", "name:k", "K"), _con("Orchestra", "name:o", "O")],
            "rec2": [_con("Performer", "name:p", "P")]}

    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      composer_slug_of, work_slug_of, recs, cons)
    names = dict(payloads)
    house = json.loads(names["house_recordings"])
    assert len(house) == 1
    h = house[0]
    assert h["work_slug"] == "c-w"
    assert h["recording_pid"] == "rec1"
    assert h["rec_airings"] == 3
    assert h["total_2016"] == 4          # rec1(3) + rec2(1), 2016+ only
    assert h["share_pct"] == 75          # round(3/4 * 100)
    assert h["conductors"] == ["K"]
    assert h["ensembles"] == ["O"]
    assert h["soloists"] == []


def test_build_browse_payloads_house_recordings_skips_work_with_no_2016_recording():
    key = ("c", "w")
    work_entries = [{"key": key, "slug": "c-w", "composer_display": "C",
                      "work_display": "W"}]
    work_airings = {
        key: [("2010-01-01", "rec1", "P", "ep1", 0)],   # pre-2016 only
    }
    recs = {"rec1": _rec("rec1")}
    cons = {}
    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      {"c": "c"}, {key: "c-w"}, recs, cons)
    names = dict(payloads)
    house = json.loads(names["house_recordings"])
    assert house == []


def test_build_browse_payloads_house_recordings_spine_excluded_rp_cannot_dominate():
    # A projected rp with no spine recording (interstitial / skip class) has
    # no recordings-table page: it must neither be picked as the house
    # recording nor count in the share denominator, even when it has the
    # most 2016+ airings. Structural mirror of the episode-link nulling.
    key = ("c", "w")
    work_entries = [{"key": key, "slug": "c-w", "composer_display": "C",
                      "work_display": "W"}]
    work_airings = {
        key: [
            ("2016-01-01", "ghost", "P", "ep1", 0),   # excluded rp, majority
            ("2017-01-01", "ghost", "P", "ep2", 0),
            ("2018-01-01", "ghost", "P", "ep3", 0),
            ("2019-01-01", "rec1", "P", "ep4", 0),    # the only paged rp
        ],
    }
    recs = {"rec1": _rec("rec1")}                      # 'ghost' absent
    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      {"c": "c"}, {key: "c-w"}, recs, {})
    house = json.loads(dict(payloads)["house_recordings"])
    assert len(house) == 1
    assert house[0]["recording_pid"] == "rec1"
    assert house[0]["rec_airings"] == 1
    assert house[0]["total_2016"] == 1     # ghost airings out of the denominator
    assert house[0]["share_pct"] == 100

    # ...and a work whose ONLY 2016+ rps are excluded is skipped entirely.
    work_airings[key] = work_airings[key][:3]          # ghost rows only
    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      {"c": "c"}, {key: "c-w"}, recs, {})
    assert json.loads(dict(payloads)["house_recordings"]) == []


def test_build_browse_payloads_house_recordings_tie_breaks_lexicographically():
    key = ("c", "w")
    work_entries = [{"key": key, "slug": "c-w", "composer_display": "C",
                      "work_display": "W"}]
    work_airings = {
        key: [
            ("2020-01-01", "recB", "P", "ep1", 0),
            ("2020-01-02", "recA", "P", "ep2", 0),
        ],
    }
    recs = {"recA": _rec("recA"), "recB": _rec("recB")}
    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      {"c": "c"}, {key: "c-w"}, recs, {})
    house = json.loads(dict(payloads)["house_recordings"])
    assert house[0]["recording_pid"] == "recA"   # tie 1-vs-1 -> lexicographic


def test_build_browse_payloads_house_recordings_only_top_50_works_considered():
    # 60 works, all with a 2016+ recording; only the top 50 by total airings
    # should be candidates for house_recordings.
    work_entries = [
        {"key": ("c", f"w{i}"), "slug": f"w{i}", "composer_display": "C",
         "work_display": f"Work {i}"}
        for i in range(60)
    ]
    work_airings = {}
    recs = {}
    for i in range(60):
        rp = f"rec{i}"
        n = 60 - i   # w0 has the most airings, w59 the fewest
        work_airings[("c", f"w{i}")] = [
            ("2020-01-01", rp, "P", f"ep{i}", j) for j in range(n)]
        recs[rp] = _rec(rp)
    work_slug_of = {("c", f"w{i}"): f"w{i}" for i in range(60)}
    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      {"c": "c"}, work_slug_of, recs, {})
    house = json.loads(dict(payloads)["house_recordings"])
    slugs = {h["work_slug"] for h in house}
    assert "w49" in slugs      # 50th-highest airings, just inside top 50
    assert "w50" not in slugs  # 51st-highest, excluded


# --- check_closure (Task 8) --------------------------------------------------
# check_closure(conn) walks a BUILT site.sqlite and returns a list of
# violation strings (empty = pass) for every non-NULL cross-table reference:
# works.composer_slug, recordings.work_slug/composer_slug, every
# episodes.tracks_json entry's work_slug/composer_slug/recording_pid, every
# composers.works_json entry's slug, every works.facets_json
# recordings[].recording_pid, and browse's top_works/house_recordings slugs.
# A JSON null (None) link is the deliberate junk-row case and never a
# violation -- only a non-null dangling reference is.

def _work_row(slug="beet:sym5", composer_slug_val="beethoven", facets=None):
    return (slug, composer_slug_val, "beethoven", "sym5", "Symphony No 5",
            "Beethoven", None, 10, 1, 0, "2020-01-01", "2020-06-01",
            json.dumps(facets if facets is not None else {"recordings": []}))


def _composer_row(slug="beethoven", works_json=None):
    return (slug, "beethoven", "Beethoven", 10, 1,
            json.dumps(works_json if works_json is not None else
                       [{"slug": "beet:sym5", "display": "Symphony No 5", "airings": 10}]))


def _episode_row(pid="ep1", tracks=None):
    return (pid, "2013-01-01", "Through the Night",
            f"https://www.bbc.co.uk/programmes/{pid}",
            json.dumps(tracks if tracks is not None else [
                {"pos": 0, "time": "01:00 AM", "work_slug": "beet:sym5",
                 "composer_slug": "beethoven", "composer": "Beethoven",
                 "title": "Symphony No 5", "performers": "Berlin Phil",
                 "recording_pid": "rec1"},
            ]))


def _recording_row(rp="rec1", work_slug="beet:sym5", composer_slug_val="beethoven"):
    return (rp, work_slug, composer_slug_val, 1800, "GBBBC", 5,
            "2020-01-01", "2020-06-01", json.dumps([]), json.dumps([]))


def _happy_closure_tables():
    """A minimal, internally-consistent set of rows -- every non-null
    reference resolves. The base fixture for both the pass test and each
    violation-injection test (which mutates one reference to dangle)."""
    return {
        "works": [_work_row(facets={
            "recordings": [{"recording_pid": "rec1"}],
        })],
        "composers": [_composer_row()],
        "episodes": [_episode_row()],
        "recordings": [_recording_row()],
        "browse": [
            ("top_works", json.dumps([
                {"slug": "beet:sym5", "composer_slug": "beethoven"},
            ])),
            ("house_recordings", json.dumps([
                {"work_slug": "beet:sym5", "composer_slug": "beethoven",
                 "recording_pid": "rec1"},
            ])),
        ],
    }


def _closure_conn(tmp_path, tables, name="closure.sqlite"):
    path = tmp_path / name
    write_site_db(str(path), tables, "fp-closure")
    conn = sqlite3.connect(str(path))
    return conn


def test_check_closure_passes_on_happy_fixture(tmp_path):
    conn = _closure_conn(tmp_path, _happy_closure_tables())
    violations = check_closure(conn)
    conn.close()
    assert violations == []


def test_check_closure_null_links_are_not_violations(tmp_path):
    tables = _happy_closure_tables()
    # a junk episode-track row: every slug/rp is None
    tables["episodes"] = [_episode_row(tracks=[
        {"pos": 0, "time": "01:00 AM", "work_slug": None,
         "composer_slug": None, "composer": "??", "title": "??",
         "performers": "", "recording_pid": None},
    ])]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert violations == []


def test_check_closure_detects_dangling_works_composer_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["works"] = [_work_row(composer_slug_val="ghost-composer")]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert len(violations) >= 1
    assert any("works" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_recording_work_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["recordings"] = [_recording_row(work_slug="ghost:work")]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("recordings" in v and "ghost:work" in v for v in violations)


def test_check_closure_detects_dangling_recording_composer_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["recordings"] = [_recording_row(composer_slug_val="ghost-composer")]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("recordings" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_episode_track_work_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["episodes"] = [_episode_row(tracks=[
        {"pos": 0, "time": "01:00 AM", "work_slug": "ghost:work",
         "composer_slug": "beethoven", "composer": "Beethoven",
         "title": "Symphony No 5", "performers": "Berlin Phil",
         "recording_pid": "rec1"},
    ])]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("episodes" in v and "ep1" in v and "ghost:work" in v
                for v in violations)


def test_check_closure_detects_dangling_episode_track_composer_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["episodes"] = [_episode_row(tracks=[
        {"pos": 0, "time": "01:00 AM", "work_slug": "beet:sym5",
         "composer_slug": "ghost-composer", "composer": "Beethoven",
         "title": "Symphony No 5", "performers": "Berlin Phil",
         "recording_pid": "rec1"},
    ])]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("episodes" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_episode_track_recording_pid(tmp_path):
    tables = _happy_closure_tables()
    tables["episodes"] = [_episode_row(tracks=[
        {"pos": 0, "time": "01:00 AM", "work_slug": "beet:sym5",
         "composer_slug": "beethoven", "composer": "Beethoven",
         "title": "Symphony No 5", "performers": "Berlin Phil",
         "recording_pid": "ghost-rec"},
    ])]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("episodes" in v and "ghost-rec" in v for v in violations)


def test_check_closure_detects_dangling_composer_works_json_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["composers"] = [_composer_row(works_json=[
        {"slug": "ghost:work", "display": "Ghost Work", "airings": 3},
    ])]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("composers" in v and "ghost:work" in v for v in violations)


def test_check_closure_detects_dangling_facets_recording_pid(tmp_path):
    tables = _happy_closure_tables()
    tables["works"] = [_work_row(facets={
        "recordings": [{"recording_pid": "ghost-rec"}],
    })]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("works" in v and "ghost-rec" in v for v in violations)


def test_check_closure_detects_dangling_browse_top_works(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_works", json.dumps([
            {"slug": "ghost:work", "composer_slug": "beethoven"},
        ])),
        ("house_recordings", json.dumps([])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("browse" in v and "ghost:work" in v for v in violations)


def test_check_closure_detects_dangling_browse_top_works_composer_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_works", json.dumps([
            {"slug": "beet:sym5", "composer_slug": "ghost-composer"},
        ])),
        ("house_recordings", json.dumps([])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("browse" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_browse_house_recordings(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_works", json.dumps([])),
        ("house_recordings", json.dumps([
            {"work_slug": "ghost:work", "composer_slug": "beethoven",
             "recording_pid": "rec1"},
        ])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("browse" in v and "ghost:work" in v for v in violations)


def test_check_closure_detects_dangling_browse_house_recordings_recording_pid(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_works", json.dumps([])),
        ("house_recordings", json.dumps([
            {"work_slug": "beet:sym5", "composer_slug": "beethoven",
             "recording_pid": "ghost-rec"},
        ])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("browse" in v and "ghost-rec" in v for v in violations)


def test_check_closure_message_names_table_key_reference(tmp_path):
    tables = _happy_closure_tables()
    tables["works"] = [_work_row(composer_slug_val="ghost-composer")]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert len(violations) == 1
    v = violations[0]
    # table name, row key, and offending reference all present
    assert "works" in v
    assert "beet:sym5" in v          # the row key
    assert "composer_slug" in v
    assert "ghost-composer" in v     # the offending reference


def test_check_closure_empty_db_no_violations(tmp_path):
    conn = _closure_conn(tmp_path, {})
    violations = check_closure(conn)
    conn.close()
    assert violations == []


def test_write_site_db_validate_hook_raises_and_leaves_no_tmp(tmp_path):
    path = tmp_path / "publish.sqlite"

    def _always_fails(conn):
        return ["fake violation #1", "fake violation #2"]

    tables = _happy_closure_tables()
    with pytest.raises(ValueError) as ei:
        write_site_db(str(path), tables, "fp-x", validate=_always_fails)
    assert "fake violation #1" in str(ei.value)
    assert not path.exists()
    assert not os.path.exists(str(path) + ".tmp")


def test_write_site_db_validate_hook_passes_through_on_no_violations(tmp_path):
    path = tmp_path / "publish.sqlite"
    tables = _happy_closure_tables()

    write_site_db(str(path), tables, "fp-y", validate=check_closure)
    assert path.exists()


def test_write_site_db_validate_failure_does_not_clobber_existing_good_file(tmp_path):
    path = tmp_path / "publish.sqlite"
    good_tables = _happy_closure_tables()
    write_site_db(str(path), good_tables, "fp-good", validate=check_closure)
    good_bytes = path.read_bytes()

    bad_tables = _happy_closure_tables()
    bad_tables["works"] = [_work_row(composer_slug_val="ghost-composer")]

    with pytest.raises(ValueError):
        write_site_db(str(path), bad_tables, "fp-bad", validate=check_closure)

    assert path.read_bytes() == good_bytes


def test_write_site_db_validate_message_reports_total_count_when_truncated(tmp_path):
    path = tmp_path / "publish.sqlite"
    tables = _happy_closure_tables()

    def _many_violations(conn):
        return [f"violation {i}" for i in range(30)]

    with pytest.raises(ValueError) as ei:
        write_site_db(str(path), tables, "fp-many", validate=_many_violations)
    msg = str(ei.value)
    assert "30" in msg   # total count surfaced even if listing is truncated


# --- main(): build THEN render + --build-only / --render-only (task 5) -------
# render_site itself is exercised in test_ttn_site_render.py; these tests only
# check ttn_site.main's WIRING -- that it calls render_site at the right time,
# with the right args, and enforces the render-only-needs-fresh hard error.
# render_site is monkeypatched throughout so these stay fast/offline and don't
# duplicate the render-driver's own coverage.

def test_dist_path_default_beside_module():
    from ttn_site import dist_path_default
    path = dist_path_default()
    assert os.path.basename(path) == "dist"
    assert os.path.dirname(path) == os.path.dirname(os.path.abspath(ttn_site.__file__))


def test_main_default_calls_build_then_render(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    calls = []
    def _fake_render_site(site_db_arg, registry_arg, dist_arg, base_url=None, pagefind=None):
        calls.append((site_db_arg, registry_arg, dist_arg))
        return {"pages": 3, "written": 3, "skipped": 0, "pruned": 0, "crawl_ok": True,
                "pagefind": pagefind}
    monkeypatch.setattr(ttn_site, "render_site", _fake_render_site)

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist)])
    assert rc in (0, None)
    assert len(calls) == 1
    assert calls[0] == (str(site_db), str(registry_path), str(dist))


def test_main_build_only_skips_render(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    calls = []
    monkeypatch.setattr(ttn_site, "render_site",
                         lambda *a, **k: calls.append(a) or {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist),
                         "--build-only"])
    assert rc in (0, None)
    assert calls == []
    assert site_db.exists()


def test_main_render_only_requires_fresh_site_db(tmp_path, monkeypatch, capsys):
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"   # never built -- status is 'missing'
    dist = tmp_path / "dist"

    calls = []
    monkeypatch.setattr(ttn_site, "render_site",
                         lambda *a, **k: calls.append(a) or {})

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--registry", str(registry_path), "--site-db", str(site_db),
                        "--dist", str(dist), "--render-only"])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "ttn_data.py site" in err
    assert calls == []


def test_main_render_only_renders_when_fresh(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    # Build first (populates + settles site_db fresh against the registry).
    ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                   "--site-db", str(site_db), "--build-only"])

    calls = []
    def _fake_render_site(site_db_arg, registry_arg, dist_arg, base_url=None, pagefind=None):
        calls.append((site_db_arg, registry_arg, dist_arg))
        return {"pages": 5, "written": 5, "skipped": 0, "pruned": 0, "crawl_ok": True,
                "pagefind": pagefind}
    monkeypatch.setattr(ttn_site, "render_site", _fake_render_site)

    rc = ttn_site.main(["--registry", str(registry_path), "--site-db", str(site_db),
                         "--dist", str(dist), "--render-only"])
    assert rc in (0, None)
    assert len(calls) == 1


def test_main_dist_default_uses_dist_path_default(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    fake_dist = tmp_path / "default-dist"
    monkeypatch.setattr(ttn_site, "dist_path_default", lambda: str(fake_dist))

    calls = []
    monkeypatch.setattr(ttn_site, "render_site",
                         lambda *a, **k: calls.append(a) or {"pages": 0, "written": 0,
                                                              "skipped": 0, "pruned": 0,
                                                              "crawl_ok": True})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db)])
    assert rc in (0, None)
    assert calls[0][2] == str(fake_dist)


def test_main_prints_render_summary_line(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})
    monkeypatch.setattr(ttn_site, "render_site",
                         lambda *a, **k: {"pages": 42, "written": 10, "skipped": 32,
                                          "pruned": 2, "crawl_ok": True})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist)])
    assert rc in (0, None)
    out = capsys.readouterr().out
    assert "42" in out and "10" in out and "32" in out and "2" in out
    assert "crawl ok" in out.lower() or "crawl_ok" in out.lower()


def test_main_default_runs_pagefind_true(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    calls = []
    def _fake_render_site(site_db_arg, registry_arg, dist_arg, base_url=None, pagefind=None):
        calls.append(pagefind)
        return {"pages": 3, "written": 3, "skipped": 0, "pruned": 0,
                "crawl_ok": True, "pagefind": pagefind}
    monkeypatch.setattr(ttn_site, "render_site", _fake_render_site)

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist)])
    assert rc in (0, None)
    assert calls == [True]


def test_main_no_pagefind_flag_disables_it(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    calls = []
    def _fake_render_site(site_db_arg, registry_arg, dist_arg, base_url=None, pagefind=None):
        calls.append(pagefind)
        return {"pages": 3, "written": 3, "skipped": 0, "pruned": 0,
                "crawl_ok": True, "pagefind": pagefind}
    monkeypatch.setattr(ttn_site, "render_site", _fake_render_site)

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist),
                         "--no-pagefind"])
    assert rc in (0, None)
    assert calls == [False]


def test_main_render_only_respects_no_pagefind(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                   "--site-db", str(site_db), "--build-only"])

    calls = []
    def _fake_render_site(site_db_arg, registry_arg, dist_arg, base_url=None, pagefind=None):
        calls.append(pagefind)
        return {"pages": 5, "written": 5, "skipped": 0, "pruned": 0,
                "crawl_ok": True, "pagefind": pagefind}
    monkeypatch.setattr(ttn_site, "render_site", _fake_render_site)

    rc = ttn_site.main(["--registry", str(registry_path), "--site-db", str(site_db),
                         "--dist", str(dist), "--render-only", "--no-pagefind"])
    assert rc in (0, None)
    assert calls == [False]


def test_main_prints_search_status_in_summary(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})
    monkeypatch.setattr(ttn_site, "render_site",
                         lambda *a, **k: {"pages": 42, "written": 10, "skipped": 32,
                                          "pruned": 2, "crawl_ok": True, "pagefind": True})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist)])
    assert rc in (0, None)
    out = capsys.readouterr().out
    assert "search" in out.lower()


def test_main_build_only_never_touches_pagefind_flag(tmp_path, monkeypatch):
    # --build-only skips render entirely, so the --no-pagefind/pagefind
    # plumbing must never be consulted -- render_site isn't even called.
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    calls = []
    monkeypatch.setattr(ttn_site, "render_site",
                         lambda *a, **k: calls.append(a) or {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist),
                         "--build-only", "--no-pagefind"])
    assert rc in (0, None)
    assert calls == []


def test_main_admin_actions_skip_render(tmp_path, monkeypatch):
    # --rename/--remap must never trigger a render.
    registry_path = tmp_path / "registry.json"
    from ttn_site import dump_registry, _empty_registry
    reg = _empty_registry()
    reg["works"]["old-slug"] = {"composer_key": "c1", "work_key": "w1", "published": "2020-01-01"}
    dump_registry(reg, str(registry_path))

    calls = []
    monkeypatch.setattr(ttn_site, "render_site",
                         lambda *a, **k: calls.append(a) or {})

    rc = ttn_site.main(["--registry", str(registry_path), "--rename", "old-slug", "new-slug"])
    assert rc in (0, None)
    assert calls == []
