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
                       apply_rename, apply_remap, apply_retire, RegistryActionError,
                       site_db_path, site_fingerprint, write_site_db,
                       site_status, accumulate_entities, build_work_rows,
                       build_recording_rows, check_closure)
from ttn_analyze import (canonical_key, normalize_composer, strip_arranger_tail,
                          resolve_composer_alias, work_title_key, resolve_work_alias)
from ttn_spine import Recording, Contributor

# Captured BEFORE the autouse guard below patches it, for the one test that
# asserts the real function's behaviour.
_REAL_DIST_PATH_DEFAULT = ttn_site.dist_path_default


@pytest.fixture(autouse=True)
def _dist_never_the_repo(tmp_path_factory, monkeypatch):
    """Isolation guard: a main() invocation that reaches the render stage
    without an explicit --dist would otherwise render INTO THE REPO'S REAL
    dist/ (prune included) -- which is exactly what happened when the render
    half was folded into main() and the Phase-1 substrate tests predated
    --dist. Redirect the default to a throwaway tmp dir for every test."""
    monkeypatch.setattr(ttn_site, "dist_path_default",
                        lambda: str(tmp_path_factory.mktemp("dist-guard")))


@pytest.fixture(autouse=True)
def _artist_registry_never_the_repo(tmp_path_factory, monkeypatch):
    """Isolation guard, artist edition: _run_build SYNCS AND DUMPS the artist
    registry (a git-tracked decisions file beside the module), so any build
    test without an explicit --artist-registry would write the repo's real
    ttn_site_artist_registry.json. Redirect the default per test."""
    p = tmp_path_factory.mktemp("artist-reg-guard") / "artist_registry.json"
    monkeypatch.setattr(ttn_site, "artist_registry_path", lambda: str(p))


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
            "redirects": {"works": {}, "composers": {}},
            "retired": {"works": {}, "composers": {}}}


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


def test_load_registry_missing_retired_key_normalises_to_empty(tmp_path):
    # the live ttn_site_registry.json predates the 'retired' key -- a hard
    # error here would block every build, so 'retired' is NOT in `required`;
    # a registry file without it loads with 'retired' normalised to empty maps.
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "version": 1, "works": {}, "composers": {},
        "redirects": {"works": {}, "composers": {}},
    }))
    reg = load_registry(str(path))
    assert reg["retired"] == {"works": {}, "composers": {}}


def test_load_registry_malformed_retired_hard_errors(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "version": 1, "works": {}, "composers": {},
        "redirects": {"works": {}, "composers": {}},
        "retired": {"works": "not a dict", "composers": {}},
    }))
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
        "retired": {"works": {}, "composers": {}},
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


# --- sync_registry: retired slugs --------------------------------------------

def test_sync_retired_slug_is_not_reported_as_orphan():
    # a retired identity has already been moved OUT of `registered` by
    # apply_retire -- sync_registry must not raise RegistryDriftError over
    # it just because its identity is (of course) absent from the corpus.
    registry = {
        "version": 1, "works": {}, "composers": {},
        "redirects": {"works": {}, "composers": {}},
        "retired": {
            "works": {"anonymous:4-works": {
                "composer_key": "anonymous", "work_key": "4 works",
                "published": "2026-07-12", "retired": "2026-07-20",
                "reason": "airings reattributed to named composers"}},
            "composers": {},
        },
    }
    # doesn't raise
    new_reg, report = sync_registry(registry, [], [], today="2026-07-20")
    assert new_reg["retired"]["works"]["anonymous:4-works"]["composer_key"] == "anonymous"


def test_sync_never_re_mints_a_retired_slug():
    # a NEW identity whose derived slug collides with a RETIRED one must get
    # the '-2' suffix, exactly as if that slug were still live -- a URL that
    # once meant one work must never come to mean a different one.
    registry = {
        "version": 1, "works": {}, "composers": {},
        "redirects": {"works": {}, "composers": {}},
        "retired": {
            "works": {},
            "composers": {"mozart": {"composer_key": "mozart-wolfgang",
                                      "published": "2026-01-01",
                                      "retired": "2026-07-20"}},
        },
    }
    composers = [_composer_entry("mozart-leopold", "mozart")]
    new_reg, report = sync_registry(registry, [], composers, today="2026-07-20")

    assert "mozart" not in new_reg["composers"]      # never re-minted
    assert new_reg["composers"]["mozart-2"]["composer_key"] == "mozart-leopold"
    assert ("mozart-leopold", "mozart", "mozart-2") in report["collisions"]
    # the retired entry itself is untouched
    assert new_reg["retired"]["composers"]["mozart"]["composer_key"] == "mozart-wolfgang"


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


# --- admin actions: --retire -------------------------------------------------
# The dissolved-identity counterpart to --remap: some identities don't MOVE
# (a successor to point at), they vanish outright -- an 'anonymous: 4 works'
# entry whose airings turned out to be four different named composers, or a
# pre-2012 text-only work with no traceable heir. --remap can't help there
# (there's nothing to remap TO); --retire moves the slug out of the live
# registry into a permanent record instead.

def test_apply_retire_moves_entry_and_stamps_date_and_reason():
    registry = {
        "version": 1,
        "works": {"anonymous:4-works": {"composer_key": "anonymous",
                                         "work_key": "4 works",
                                         "published": "2026-07-12"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
        "retired": {"works": {}, "composers": {}},
    }
    new_reg = apply_retire(registry, "works", "anonymous:4-works",
                            reason="airings reattributed to named composers",
                            today="2026-07-20")

    assert "anonymous:4-works" not in new_reg["works"]
    retired = new_reg["retired"]["works"]["anonymous:4-works"]
    # original stored fields preserved verbatim
    assert retired["composer_key"] == "anonymous"
    assert retired["work_key"] == "4 works"
    assert retired["published"] == "2026-07-12"
    # plus the new stamps
    assert retired["retired"] == "2026-07-20"
    assert retired["reason"] == "airings reattributed to named composers"


def test_apply_retire_reason_is_optional():
    registry = {
        "version": 1, "works": {},
        "composers": {"ghost": {"composer_key": "ghost-ck", "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
        "retired": {"works": {}, "composers": {}},
    }
    new_reg = apply_retire(registry, "composers", "ghost", today="2026-07-20")
    retired = new_reg["retired"]["composers"]["ghost"]
    assert retired["retired"] == "2026-07-20"
    assert "reason" not in retired


def test_apply_retire_tolerates_missing_retired_key_on_input():
    # a raw registry dict (as many tests, and pre-migration files, construct)
    # may not carry a 'retired' key at all yet -- apply_retire must not KeyError.
    registry = {
        "version": 1,
        "works": {"orphan": {"composer_key": "ck", "work_key": "wk",
                              "published": "2026-01-01"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    new_reg = apply_retire(registry, "works", "orphan", today="2026-07-20")
    assert new_reg["retired"]["works"]["orphan"]["composer_key"] == "ck"


def test_apply_retire_does_not_mutate_input():
    registry = {
        "version": 1,
        "works": {"orphan": {"composer_key": "ck", "work_key": "wk",
                              "published": "2026-01-01"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
        "retired": {"works": {}, "composers": {}},
    }
    apply_retire(registry, "works", "orphan", today="2026-07-20")
    assert "orphan" in registry["works"]
    assert registry["retired"]["works"] == {}


def test_apply_retire_refuses_when_slug_not_registered():
    registry = _empty_shell()
    with pytest.raises(RegistryActionError):
        apply_retire(registry, "works", "missing-slug", today="2026-07-20")


def test_apply_retire_refuses_when_slug_is_a_redirect_target():
    registry = {
        "version": 1,
        "works": {
            "canonical-slug": {"composer_key": "ck", "work_key": "wk",
                                "published": "2026-01-01"},
        },
        "composers": {},
        "redirects": {"works": {"old-slug": "canonical-slug"}, "composers": {}},
        "retired": {"works": {}, "composers": {}},
    }
    with pytest.raises(RegistryActionError):
        apply_retire(registry, "works", "canonical-slug", today="2026-07-20")
    # unchanged on refusal
    assert "canonical-slug" in registry["works"]


# --- main(): build action -----------------------------------------------------

def _make_fixture_db(path):
    """A tiny synthetic DB: episodes/tracks/segment_events, mirroring
    test_ttn_project.py::_lineage_db's dual-lineage schema but with real rows
    so the whole-corpus 7-tuple cursor + build_work_index/build_composer_index
    have something to chew on."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT, "
                 "title TEXT, subtitle TEXT, segments_raw_json TEXT)")
    conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "episode_pid TEXT, position INT, time_str TEXT, composer TEXT, "
                 "composer_line TEXT, contributors_json TEXT, title TEXT, performers TEXT)")
    conn.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
                 "version_offset INT, composer_name TEXT, track_title TEXT, "
                 "composer_mbid TEXT, recording_pid TEXT, event_pid TEXT, "
                 "composer_pid TEXT, duration_seconds INT, record_id TEXT, "
                 "record_label TEXT, contributions_json TEXT)")
    conn.execute("INSERT INTO episodes VALUES ('ep1', '2020-01-01T01:00:00Z', "
                 "'Through the Night', 'Beethoven and Mozart from Berlin', NULL)")
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

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--build-only"])
    assert rc in (0, None)

    reg = load_registry(str(registry_path))
    work_cks = {v["composer_key"] for v in reg["works"].values()}
    assert "beethoven" in " ".join(work_cks) or any("beethoven" in ck for ck in work_cks)
    composer_slugs = set(reg["composers"].keys())
    assert any("beethoven" in s for s in composer_slugs)
    assert any("mozart" in s for s in composer_slugs)


def test_episode_title_is_the_subtitle(tmp_path, monkeypatch):
    # episodes.title is uniformly "Through the Night"; the site's episode
    # heading must be the per-night SUBTITLE (_EPISODE_META_SQL COALESCEs
    # subtitle over title).
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"

    monkeypatch.setattr(ttn_site.ttn_project, "load",
                         lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--build-only"])
    assert rc in (0, None)

    conn = sqlite3.connect(str(site_db))
    (title,) = conn.execute(
        "SELECT title FROM episodes WHERE pid = 'ep1'").fetchone()
    conn.close()
    assert title == "Beethoven and Mozart from Berlin"


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
    # load_registry normalises the missing 'retired' key onto whatever it
    # reads, so compare against that normalised shape, not the bare `original`.
    assert load_registry(str(registry_path)) == {
        **original, "retired": {"works": {}, "composers": {}}}


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


# --- --remap batching (repeatable --remap / --remap-file / --dry-run) -------
# A drift-repair pass is inherently a batch (35 orphaned slugs in one
# curation round), so --remap is repeatable and --remap-file reads specs
# from a file; the two combine. Every spec is parsed+applied in memory
# before ONE dump_registry -- a bad spec anywhere in the batch, or
# --dry-run, must leave the registry file byte-for-byte untouched.

def test_main_remap_multiple_flags_apply_all(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "old-ck1", "work_key": "old-wk1",
                        "published": "2026-01-01"},
            "orphan2": {"composer_key": "old-ck2", "work_key": "old-wk2",
                        "published": "2026-01-02"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--remap", "orphan1|new-ck1|new-wk1",
                         "--remap", "orphan2|new-ck2|new-wk2"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert reg["works"]["orphan1"]["composer_key"] == "new-ck1"
    assert reg["works"]["orphan1"]["work_key"] == "new-wk1"
    assert reg["works"]["orphan2"]["composer_key"] == "new-ck2"
    assert reg["works"]["orphan2"]["work_key"] == "new-wk2"


def test_main_remap_file_applies_all_skipping_blank_and_comments(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "old-ck1", "work_key": "old-wk1",
                        "published": "2026-01-01"},
            "orphan2": {"composer_key": "old-ck2", "work_key": "old-wk2",
                        "published": "2026-01-02"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))
    specs_file = tmp_path / "remaps.txt"
    specs_file.write_text(
        "# a leading comment\n"
        "\n"
        "orphan1|new-ck1|new-wk1\n"
        "   \n"
        "# another comment\n"
        "orphan2|new-ck2|new-wk2\n"
    )

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--remap-file", str(specs_file)])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert reg["works"]["orphan1"]["composer_key"] == "new-ck1"
    assert reg["works"]["orphan2"]["composer_key"] == "new-ck2"


def test_main_remap_file_and_flags_combine(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "old-ck1", "work_key": "old-wk1",
                        "published": "2026-01-01"},
            "orphan2": {"composer_key": "old-ck2", "work_key": "old-wk2",
                        "published": "2026-01-02"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))
    specs_file = tmp_path / "remaps.txt"
    specs_file.write_text("orphan1|new-ck1|new-wk1\n")

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--remap-file", str(specs_file),
                         "--remap", "orphan2|new-ck2|new-wk2"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert reg["works"]["orphan1"]["composer_key"] == "new-ck1"
    assert reg["works"]["orphan2"]["composer_key"] == "new-ck2"


def test_main_remap_batch_parse_error_writes_nothing(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    original = {
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "old-ck1", "work_key": "old-wk1",
                        "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(original, str(registry_path))
    before = registry_path.read_bytes()

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--registry", str(registry_path),
                        "--remap", "orphan1|new-ck1|new-wk1",
                        "--remap", "this-is-not-a-valid-spec"])
    assert ei.value.code == 1
    assert registry_path.read_bytes() == before
    assert "this-is-not-a-valid-spec" in capsys.readouterr().err


def test_main_remap_batch_action_error_writes_nothing(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    original = {
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "old-ck1", "work_key": "old-wk1",
                        "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(original, str(registry_path))
    before = registry_path.read_bytes()

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--registry", str(registry_path),
                        "--remap", "orphan1|new-ck1|new-wk1",
                        "--remap", "unregistered-slug|new-ck2|new-wk2"])
    assert ei.value.code == 1
    assert registry_path.read_bytes() == before
    assert "unregistered-slug" in capsys.readouterr().err


def test_main_remap_dry_run_writes_nothing(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    original = {
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "old-ck1", "work_key": "old-wk1",
                        "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(original, str(registry_path))
    before = registry_path.read_bytes()

    rc = ttn_site.main(["--registry", str(registry_path),
                        "--remap", "orphan1|new-ck1|new-wk1",
                        "--dry-run"])
    assert rc in (0, None)
    assert registry_path.read_bytes() == before
    out = capsys.readouterr().out
    assert "orphan1" in out
    assert "1" in out   # totals summary


def test_main_remap_sequential_folding_sees_earlier_effect(tmp_path):
    # slug-b's spec targets the SAME successor identity slug-a's spec just
    # claimed -- if the batch applied against the ORIGINAL registry instead
    # of folding, slug-b would land as a SECOND canonical registration for
    # that identity instead of a redirect to slug-a.
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "slug-a": {"composer_key": "old-ck-a", "work_key": "old-wk-a",
                       "published": "2026-01-01"},
            "slug-b": {"composer_key": "old-ck-b", "work_key": "old-wk-b",
                       "published": "2026-01-02"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--remap", "slug-a|shared-ck|shared-wk",
                         "--remap", "slug-b|shared-ck|shared-wk"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert reg["works"]["slug-a"]["composer_key"] == "shared-ck"
    assert reg["works"]["slug-a"]["work_key"] == "shared-wk"
    assert "slug-b" not in reg["works"]
    assert reg["redirects"]["works"]["slug-b"] == "slug-a"


# --- --retire batching (repeatable --retire / --retire-file / --dry-run) ----
# Mirrors the --remap batch machinery above: all-or-nothing, one dump_registry,
# --dry-run reports without writing.

def test_main_retire_single(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {"anonymous:4-works": {"composer_key": "anonymous",
                                         "work_key": "4 works",
                                         "published": "2026-07-12"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--retire", "anonymous:4-works",
                         "--reason", "airings reattributed to named composers"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "anonymous:4-works" not in reg["works"]
    retired = reg["retired"]["works"]["anonymous:4-works"]
    assert retired["composer_key"] == "anonymous"
    assert retired["reason"] == "airings reattributed to named composers"
    assert "retired" in retired


def test_main_retire_composer_namespace(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1, "works": {},
        "composers": {"ghost": {"composer_key": "ghost-ck", "published": "2026-01-01"}},
        "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path), "--composer",
                         "--retire", "ghost"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "ghost" not in reg["composers"]
    assert reg["retired"]["composers"]["ghost"]["composer_key"] == "ghost-ck"


def test_main_retire_repeated_flag_applies_all(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "ck1", "work_key": "wk1", "published": "2026-01-01"},
            "orphan2": {"composer_key": "ck2", "work_key": "wk2", "published": "2026-01-02"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--retire", "orphan1", "--retire", "orphan2"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "orphan1" not in reg["works"] and "orphan2" not in reg["works"]
    assert "orphan1" in reg["retired"]["works"] and "orphan2" in reg["retired"]["works"]


def test_main_retire_file(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "ck1", "work_key": "wk1", "published": "2026-01-01"},
            "orphan2": {"composer_key": "ck2", "work_key": "wk2", "published": "2026-01-02"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))
    slugs_file = tmp_path / "retire.txt"
    slugs_file.write_text(
        "# a leading comment\n"
        "\n"
        "orphan1\n"
        "   \n"
        "# another comment\n"
        "orphan2\n"
    )

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--retire-file", str(slugs_file)])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "orphan1" in reg["retired"]["works"] and "orphan2" in reg["retired"]["works"]


def test_main_retire_file_and_flags_combine(tmp_path):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "ck1", "work_key": "wk1", "published": "2026-01-01"},
            "orphan2": {"composer_key": "ck2", "work_key": "wk2", "published": "2026-01-02"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))
    slugs_file = tmp_path / "retire.txt"
    slugs_file.write_text("orphan1\n")

    rc = ttn_site.main(["--registry", str(registry_path),
                         "--retire-file", str(slugs_file),
                         "--retire", "orphan2"])
    assert rc in (0, None)
    reg = load_registry(str(registry_path))
    assert "orphan1" in reg["retired"]["works"] and "orphan2" in reg["retired"]["works"]


def test_main_retire_batch_atomicity_bad_slug_writes_nothing(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    original = {
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "ck1", "work_key": "wk1", "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(original, str(registry_path))
    before = registry_path.read_bytes()

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--registry", str(registry_path),
                        "--retire", "orphan1",
                        "--retire", "unregistered-slug"])
    assert ei.value.code == 1
    assert registry_path.read_bytes() == before
    assert "unregistered-slug" in capsys.readouterr().err


def test_main_retire_dry_run_writes_nothing(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    original = {
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "ck1", "work_key": "wk1", "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }
    dump_registry(original, str(registry_path))
    before = registry_path.read_bytes()

    rc = ttn_site.main(["--registry", str(registry_path),
                        "--retire", "orphan1", "--dry-run"])
    assert rc in (0, None)
    assert registry_path.read_bytes() == before
    out = capsys.readouterr().out
    assert "orphan1" in out


def test_main_retire_and_remap_together_is_a_clean_error(tmp_path, capsys):
    registry_path = tmp_path / "registry.json"
    dump_registry({
        "version": 1,
        "works": {
            "orphan1": {"composer_key": "ck1", "work_key": "wk1", "published": "2026-01-01"},
        },
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }, str(registry_path))
    before = registry_path.read_bytes()

    with pytest.raises(SystemExit) as ei:
        ttn_site.main(["--registry", str(registry_path),
                        "--retire", "orphan1",
                        "--remap", "orphan1|new-ck|new-wk"])
    assert ei.value.code != 0
    assert registry_path.read_bytes() == before


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
    ebu_py = tmp_path / "ttn_ebu_codes.py"
    broadcasters_py = tmp_path / "ttn_broadcasters.py"
    projection = tmp_path / "ttn_projection_cache.json"
    registry = tmp_path / "ttn_site_registry.json"

    site_py.write_bytes(b"site-v1")
    analyze_py.write_bytes(b"analyze-v1")
    aliases_py.write_bytes(b"aliases-v1")
    ebu_py.write_bytes(b"ebu-v1")
    broadcasters_py.write_bytes(b"broadcasters-v1")
    projection.write_bytes(b"projection-v1")
    registry.write_bytes(b"registry-v1")

    monkeypatch.setattr(ttn_site, "__file__", str(site_py))
    monkeypatch.setattr(ttn_site, "_ANALYZE_MODULE_PATH", str(analyze_py))
    monkeypatch.setattr(ttn_site, "_ALIASES_MODULE_PATH", str(aliases_py))
    monkeypatch.setattr(ttn_site, "_EBU_CODES_MODULE_PATH", str(ebu_py))
    monkeypatch.setattr(ttn_site, "_BROADCASTERS_MODULE_PATH", str(broadcasters_py))
    monkeypatch.setattr(ttn_site.ttn_project, "PROJECTION_PATH", str(projection))

    return {
        "site_py": site_py, "analyze_py": analyze_py, "aliases_py": aliases_py,
        "ebu_py": ebu_py, "broadcasters_py": broadcasters_py,
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


def test_site_fingerprint_changes_when_ebu_codes_py_bytes_change(tmp_path, monkeypatch):
    # The gap fix: a broadcaster-table-shaping module (ttn_ebu_codes) must
    # invalidate a 'fresh' site.sqlite (it's in NEITHER the projection cache
    # fingerprint nor, previously, this one -- so a country-code fix once
    # rendered against a stale substrate).
    paths = _fingerprint_env(tmp_path, monkeypatch)
    before = ttn_site.site_fingerprint(str(paths["registry"]))
    paths["ebu_py"].write_bytes(b"ebu-v2")
    after = ttn_site.site_fingerprint(str(paths["registry"]))
    assert before != after


def test_site_fingerprint_changes_when_broadcasters_py_bytes_change(tmp_path, monkeypatch):
    paths = _fingerprint_env(tmp_path, monkeypatch)
    before = ttn_site.site_fingerprint(str(paths["registry"]))
    paths["broadcasters_py"].write_bytes(b"broadcasters-v2")
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
        "composers": [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]", "{}")],
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
                        100, 9, "[]", "{}")],
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
                         "--site-db", str(site_db), "--build-only"])
    assert rc in (0, None)
    assert site_db.exists()

    conn = sqlite3.connect(str(site_db))
    fp_row = conn.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
    assert fp_row is not None and fp_row[0]
    conn.close()


def test_main_build_end_to_end_populates_all_tables_and_settles_fresh(
        tmp_path, monkeypatch):
    # Task 7: the FULL build wiring -- work/composer/episode/recording/browse/
    # years, driven off the fixture DB's two text-only tracks (no segment_events
    # rows, so recs/cons/broadcasters are legitimately empty -- but every table
    # must still get a row for the two tracked works/composers/one episode).
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--build-only"])
    assert rc in (0, None)

    conn = sqlite3.connect(str(site_db))
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("works", "composers", "episodes", "recordings", "browse",
                        "years", "forms", "artists", "countries")}
    conn.close()

    assert counts["works"] == 2                 # Symphony No 5 + Requiem
    assert counts["composers"] == 2              # Beethoven + Mozart
    assert counts["episodes"] == 1                # ep1
    assert counts["recordings"] == 0              # no segment_events rows in the fixture
    assert counts["browse"] == 14                 # + countries (2026-07-17)
    assert counts["countries"] == 0               # no segment_events in the fixture
    assert counts["years"] == 1                   # both tracks aired 2020 -> one year page
    assert counts["forms"] == 1                   # 'Symphony No 5' classifies under symphony
    assert counts["artists"] == 0                 # no segment_events in the fixture

    # the artist registry was synced (empty shell dumped to the guarded path)
    art_reg = ttn_site.load_artist_registry(ttn_site.artist_registry_path())
    assert art_reg["artists"] == {}

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
                 "title TEXT, subtitle TEXT, segments_raw_json TEXT)")
    conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "episode_pid TEXT, position INT, time_str TEXT, composer TEXT, "
                 "composer_line TEXT, contributors_json TEXT, title TEXT, performers TEXT)")
    conn.execute("CREATE TABLE segment_events (episode_pid TEXT, position INT, "
                 "version_offset INT, composer_name TEXT, track_title TEXT, "
                 "composer_mbid TEXT, recording_pid TEXT, event_pid TEXT, "
                 "composer_pid TEXT, duration_seconds INT, record_id TEXT, "
                 "record_label TEXT, contributions_json TEXT)")
    conn.execute("INSERT INTO episodes VALUES ('ep1', '2020-01-01T01:00:00Z', "
                 "'Through the Night', 'Two Fancies', NULL)")
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
                         "--site-db", str(site_db), "--build-only"])
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
                   "--site-db", str(site_db), "--build-only"])
    capsys.readouterr()
    mtime_before = site_db.stat().st_mtime_ns

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--build-only"])
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
                   "--site-db", str(site_db), "--build-only"])
    mtime_before = site_db.stat().st_mtime_ns

    import time
    time.sleep(0.01)

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--force", "--build-only"])
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

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--build-only"])
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

    rows = build_work_rows(entries, work_airings, composer_slug_of, {},
                           recs, cons, brc_rows_by_rp)

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

    # per-recording broadcaster: the majority label decoded, plus the
    # drill-in page slug for recognized EBU codes
    assert facets["recordings"][0]["broadcaster"] == "BBC"
    assert facets["recordings"][0]["broadcaster_slug"] == "bbc"
    assert facets["recordings"][1]["broadcaster"] == "Polskie Radio"
    assert facets["recordings"][1]["broadcaster_slug"] == "polskie-radio"

    # top-contributor ranking: both conductors present, ranked deterministically
    conductor_names = {c["display_name"] for c in facets["top_conductors"]}
    assert conductor_names == {"Herbert von Karajan", "Leonard Bernstein"}

    ensemble_names = {e["display_name"] for e in facets["top_ensembles"]}
    assert ensemble_names == {"Berlin Philharmonic"}

    # by_year: 3 distinct years, rendered newest-first
    assert [y["year"] for y in facets["by_year"]] == ["2020", "2019", "2018"]
    total_by_year = sum(y["airings"] for y in facets["by_year"])
    assert total_by_year == 3

    # broadcasters: majority decode from brc_rows_by_rp for the work's rps
    broadcaster_keys = {b["key"] for b in facets["broadcasters"]}
    assert "GBBBC" in broadcaster_keys or "PLPR" in broadcaster_keys


def test_build_work_rows_composer_display_ssot_overrides_per_work_spelling():
    # The corpus-wide composer_display_of map wins over the entry's own
    # per-work best-spelling, so the byline matches the composer page.
    entries = [{
        "key": WORK_KEY, "slug": "beethoven-symphony-5",
        "composer_display": "L. van Beethoven",     # per-work minority spelling
        "work_display": "Symphony No. 5",
        "airings": 1, "spellings": [],
    }]
    work_airings = {WORK_KEY: [("2020-01-01", None, "LSO", "ep1", 0)]}
    composer_display_of = {"beethoven": "Ludwig van Beethoven"}   # corpus SSOT

    rows = build_work_rows(entries, work_airings, {"beethoven": "beethoven"},
                           composer_display_of, {}, {}, {})
    composer_display = rows[0][5]
    assert composer_display == "Ludwig van Beethoven"

    # empty-composer / unmapped ck falls back to the entry's own spelling
    entries[0]["key"] = ("", "§op67|5")
    rows = build_work_rows(entries, {("", "§op67|5"): []}, {}, composer_display_of,
                           {}, {}, {})
    assert rows[0][5] == "L. van Beethoven"


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

    rows = build_work_rows(entries, work_airings, composer_slug_of, {}, {}, {}, {})

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
    rows = build_work_rows(entries, work_airings, {"brahms": "brahms"}, {}, {}, {}, {})
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
    assert contributors == [{"role": "Conductor", "name": "Herbert von Karajan",
                              "mbid": None}]

    dates = json.loads(airing_dates_json)
    # newest-first (reverse-chronological)
    assert dates == [["2021-05-01", "ep2"], ["2020-01-01", "ep1"]]


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
                                {}, recs, cons, brc_rows_by_rp)
    # every value must already be JSON/SQLite-native
    json.dumps(work_rows[0])

    recording_airings = {"rec1": [("2020-01-01", "ep1")]}
    rec_rows, _, _ = build_recording_rows(
        work_airings, recording_airings, {key: "beethoven-symphony-5"},
        {"beethoven": "beethoven"}, recs, cons, brc_rows_by_rp)
    json.dumps(rec_rows[0])


# --- build_composer_rows / build_episode_rows / build_browse_payloads (task 7) -

from ttn_site import build_composer_rows, build_episode_rows, build_browse_payloads, build_year_rows  # noqa: E402


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
                                composer_slug_of, work_slug_of, {}, {}, {})

    assert len(rows) == 1
    slug, ck, display, airings, n_works, works_json, facets_json = rows[0]
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
                                {"x": "x"}, {("x", "b"): "x-b", ("x", "a"): "x-a"},
                                {}, {}, {})
    works = json.loads(rows[0][5])
    # equal airings -> tie-break by slug ascending
    assert [w["slug"] for w in works] == ["x-a", "x-b"]


def test_build_composer_rows_skips_composer_with_no_works():
    composer_entries = [{
        "composer_key": "nobody", "slug": "nobody", "display": "Nobody",
        "airings": 0, "n_works": 0, "spellings": [],
    }]
    rows = build_composer_rows(composer_entries, [], {}, {"nobody": "nobody"}, {},
                                {}, {}, {})
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
    rows = build_composer_rows(composer_entries, [], {}, {"x": "x-2"}, {},
                                {}, {}, {})
    assert rows[0][0] == "x-2"


def test_contributor_facets_ensemble_credited_two_roles_appears_once():
    # Regression (Toivo Kuula page): the Finnish RSO credited "Orchestra" on
    # one recording and "Ensemble" on another must be ONE row (same MBID),
    # with the union airing count -- not two rows sharing a link.
    recs = {"r1": _rec("r1", airing_count=8), "r2": _rec("r2", airing_count=3)}
    cons = {
        "r1": [_con("Orchestra", "m-frso", "Finnish RSO", "m-frso")],
        "r2": [_con("Ensemble", "m-frso", "Finnish RSO", "m-frso")],
    }
    facets = ttn_site._contributor_facets({"r1", "r2"}, recs, cons, {})
    ens = facets["top_ensembles"]
    assert len(ens) == 1
    assert ens[0]["display_name"] == "Finnish RSO"
    assert ens[0]["mbid"] == "m-frso"
    assert ens[0]["airings"] == 11 and ens[0]["recordings"] == 2

    # and dual-tagged on the SAME recording counts once for that recording
    cons2 = {"r1": [_con("Orchestra", "m-frso", "Finnish RSO", "m-frso"),
                     _con("Ensemble", "m-frso", "Finnish RSO", "m-frso")]}
    facets2 = ttn_site._contributor_facets({"r1"}, {"r1": _rec("r1", airing_count=8)},
                                            cons2, {})
    assert len(facets2["top_ensembles"]) == 1
    assert facets2["top_ensembles"][0]["airings"] == 8


def test_build_composer_rows_facets_by_year_and_contributors():
    composer_entries = [{
        "composer_key": "c", "slug": "c", "display": "C", "airings": 5,
        "n_works": 2, "spellings": ["C"],
    }]
    work_entries = [
        {"key": ("c", "w1"), "slug": "c:w1", "composer_display": "C",
         "work_display": "W1"},
        {"key": ("c", "w2"), "slug": "c:w2", "composer_display": "C",
         "work_display": "W2"},
    ]
    work_airings = {
        ("c", "w1"): [("2020-01-01", "r1", "P", "e1", 0),
                       ("2020-06-01", "r1", "P", "e2", 0),
                       ("2021-01-01", None, "P", "e3", 0)],
        ("c", "w2"): [("2020-02-01", "r2", "P", "e4", 0),
                       ("2019-01-01", None, "P", "e5", 0)],
    }
    recs = {"r1": _rec("r1", airing_count=2), "r2": _rec("r2")}
    cons = {"r1": [_con("Conductor", "mC", "Maestro", "mC")],
            "r2": [_con("Conductor", "mC", "Maestro", "mC"),
                    _con("Orchestra", "mO", "Band", "mO")]}
    brc_rows_by_rp = {"r1": ["PLPR"], "r2": ["GBBBC"]}

    rows = build_composer_rows(composer_entries, work_entries, work_airings,
                                {"c": "c"}, {}, recs, cons, brc_rows_by_rp)
    facets = json.loads(rows[0][6])

    # by_year: newest-first, whole-corpus (text-only airings count), works =
    # distinct work keys that year
    assert facets["by_year"] == [
        {"year": "2021", "airings": 1, "works": 1},
        {"year": "2020", "airings": 3, "works": 2},
        {"year": "2019", "airings": 1, "works": 1},
    ]
    # contributor rankings over the union of the composer's recording set
    assert facets["top_conductors"][0]["display_name"] == "Maestro"
    assert facets["top_ensembles"][0]["display_name"] == "Band"
    # a composer facets dict has NO per-recording list (that's the work page's)
    assert "recordings" not in facets
    keys = {b["key"] for b in facets["broadcasters"]}
    assert {"PLPR", "GBBBC"} <= keys


def test_build_composer_rows_text_only_composer_has_empty_contributor_facets():
    composer_entries = [{
        "composer_key": "c", "slug": "c", "display": "C", "airings": 1,
        "n_works": 1, "spellings": ["C"],
    }]
    work_entries = [{"key": ("c", "w"), "slug": "c:w",
                      "composer_display": "C", "work_display": "W"}]
    work_airings = {("c", "w"): [("2009-05-01", None, "P", "e1", 0)]}
    rows = build_composer_rows(composer_entries, work_entries, work_airings,
                                {"c": "c"}, {}, {}, {}, {})
    facets = json.loads(rows[0][6])
    assert facets["top_performers"] == [] and facets["broadcasters"] == []
    assert facets["by_year"] == [{"year": "2009", "airings": 1, "works": 1}]


# --- artist registry-lite -----------------------------------------------------

def test_load_artist_registry_missing_file_returns_empty_shell(tmp_path):
    reg = ttn_site.load_artist_registry(str(tmp_path / "nope.json"))
    assert reg == {"version": 1, "artists": {}, "redirects": {}}


def test_load_artist_registry_corrupt_json_hard_errors(tmp_path):
    p = tmp_path / "artist.json"
    p.write_text("{ not json")
    with pytest.raises(json.JSONDecodeError):
        ttn_site.load_artist_registry(str(p))


def test_load_artist_registry_wrong_shape_hard_errors(tmp_path):
    p = tmp_path / "artist.json"
    p.write_text(json.dumps({"version": 1, "artists": []}))
    with pytest.raises(ValueError):
        ttn_site.load_artist_registry(str(p))


def test_dump_artist_registry_deterministic_and_atomic(tmp_path):
    p = tmp_path / "artist.json"
    reg = {"version": 1,
           "artists": {"b": {"mbid": "m2", "minted": "2026-07-17",
                              "display_at_mint": "B"},
                        "a": {"mbid": "m1", "minted": "2026-07-17",
                              "display_at_mint": "A"}},
           "redirects": {}}
    ttn_site.dump_artist_registry(reg, str(p))
    first = p.read_bytes()
    ttn_site.dump_artist_registry(reg, str(p))
    assert p.read_bytes() == first                 # deterministic bytes
    assert not (tmp_path / "artist.json.tmp").exists()
    assert ttn_site.load_artist_registry(str(p)) == reg   # round-trips


def test_sync_artist_registry_mints_new_and_keeps_existing_verbatim():
    reg = {"version": 1,
           "artists": {"hannu-lintu": {"mbid": "m-lintu", "minted": "2026-01-01",
                                        "display_at_mint": "Hannu Lintu"}},
           "redirects": {}}
    new, report = ttn_site.sync_artist_registry(
        reg, [("m-lintu", "Hannu LINTU (respelled)"),
              ("m-osborne", "Steven Osborne")], "2026-07-17")
    assert report == {"added": 1}
    # existing entry kept verbatim -- slug AND mint-time record untouched
    assert new["artists"]["hannu-lintu"] == reg["artists"]["hannu-lintu"]
    assert new["artists"]["steven-osborne"] == {
        "mbid": "m-osborne", "minted": "2026-07-17",
        "display_at_mint": "Steven Osborne"}
    # input registry not mutated
    assert "steven-osborne" not in reg["artists"]


def test_sync_artist_registry_collision_suffixes_deterministically():
    new, _r = ttn_site.sync_artist_registry(
        _empty_artist_reg(),
        [("m1", "John Smith"), ("m2", "John Smith")], "2026-07-17")
    assert new["artists"]["john-smith"]["mbid"] == "m1"     # caller order wins
    assert new["artists"]["john-smith-2"]["mbid"] == "m2"


def test_sync_artist_registry_collision_against_redirect_source():
    reg = {"version": 1, "artists": {}, "redirects": {"john-smith": "somewhere"}}
    new, _r = ttn_site.sync_artist_registry(
        reg, [("m1", "John Smith")], "2026-07-17")
    assert "john-smith" not in new["artists"]
    assert new["artists"]["john-smith-2"]["mbid"] == "m1"


def test_sync_artist_registry_never_removes_and_is_idempotent():
    reg = {"version": 1,
           "artists": {"gone-below-cut": {"mbid": "m-old", "minted": "2025-01-01",
                                           "display_at_mint": "Old Name"}},
           "redirects": {}}
    # m-old absent from the qualifiers (dropped below the cut) -> kept anyway
    new1, r1 = ttn_site.sync_artist_registry(
        reg, [("m-new", "New Artist")], "2026-07-17")
    assert "gone-below-cut" in new1["artists"] and r1 == {"added": 1}
    new2, r2 = ttn_site.sync_artist_registry(
        new1, [("m-new", "New Artist")], "2026-07-18")
    assert new2 == new1 and r2 == {"added": 0}     # sync twice == once


def _empty_artist_reg():
    return {"version": 1, "artists": {}, "redirects": {}}


def _artist_fixture():
    """A tiny spine: 2 recordings. r1 (5 airings): conductor LINTU + soloist
    OSBORNE + orchestra FRSO. r2 (60 airings): LINTU conducts FRSO, plus a
    name-keyed (MBID-less) soloist. LINTU also SOLOS on r1 (the soloist-
    director case). Registry-lite tests drive qualification/rows off it."""
    recs = {
        "r1": _rec("r1", airing_count=5, duration=900,
                    first="2015-01-01", last="2020-01-01"),
        "r2": _rec("r2", airing_count=60, duration=1800,
                    first="2013-01-01", last="2026-01-01"),
    }
    cons = {
        "r1": [_con("Conductor", "m-lintu", "Hannu Lintu", "m-lintu"),
                _con("Performer", "m-lintu", "Hannu Lintu", "m-lintu"),
                _con("Performer", "m-osborne", "Steven Osborne", "m-osborne"),
                _con("Orchestra", "m-frso", "Finnish RSO", "m-frso")],
        "r2": [_con("Conductor", "m-lintu", "Hannu Lintu", "m-lintu"),
                _con("Orchestra", "m-frso", "Finnish RSO", "m-frso"),
                _con("Performer", "name:big star", "Big Star", None)],
    }
    rec_rows = [
        ("r1", "sibelius:sym5", "sibelius", 900, "FIYLE", 5, "2015-01-01",
         "2020-01-01", "[]", json.dumps([["2015-01-01", "e1"]] * 2
                                          + [["2020-01-01", "e2"]] * 3)),
        ("r2", "sibelius:sym2", "sibelius", 1800, "FIYLE", 60, "2013-01-01",
         "2026-01-01", "[]", json.dumps([["2013-01-01", "e3"]] * 60)),
    ]
    work_entries = [
        {"key": ("sibelius", "w5"), "slug": "sibelius:sym5",
         "work_display": "Symphony No 5", "composer_display": "per-work"},
        {"key": ("sibelius", "w2"), "slug": "sibelius:sym2",
         "work_display": "Symphony No 2", "composer_display": "per-work"},
    ]
    composer_display_of = {"sibelius": "Jean Sibelius"}
    brc_rows_by_rp = {"r1": ["FIYLE"], "r2": ["FIYLE"]}
    return recs, cons, rec_rows, work_entries, composer_display_of, brc_rows_by_rp


def test_artist_qualifiers_mbid_gate_cut_and_person_wins():
    recs, cons, *_rest = _artist_fixture()
    quals = ttn_site.artist_qualifiers(recs, cons)
    # LINTU: 65 combined people-airings; FRSO: 65 group-airings; OSBORNE only
    # 5 (below cut); the name-keyed Big Star (60 airings) is GATED OUT.
    assert quals == [("m-frso", "Finnish RSO"), ("m-lintu", "Hannu Lintu")] or \
           quals == [("m-lintu", "Hannu Lintu"), ("m-frso", "Finnish RSO")]
    # deterministic: equal airings (65 each) -> mbid ascending
    assert quals[0][0] == "m-frso"


def test_artist_page_cut_below_listing_cut_admits_recurring_contributors():
    # The decoupled cuts: a 30-airing MBID mints an /artist/ PAGE (page cut 20)
    # even though it is below the LISTING cut (50), so recurring contributors
    # become links without lengthening the "who appears most" rankings.
    assert ttn_site._ARTIST_PAGE_CUT < ttn_site._ARTIST_LISTING_CUT
    recs = {f"r{i}": _rec(f"r{i}", airing_count=1) for i in range(30)}
    cons = {f"r{i}": [_con("Conductor", "m-mid", "Middling Maestro", "m-mid")]
            for i in range(30)}
    quals = ttn_site.artist_qualifiers(recs, cons)
    assert ("m-mid", "Middling Maestro") in quals   # 30 airings >= page cut 20


def test_build_artist_rows_person_merges_roles_and_facets():
    recs, cons, rec_rows, work_entries, cdisp, brc = _artist_fixture()
    quals = ttn_site.artist_qualifiers(recs, cons)
    reg, _r = ttn_site.sync_artist_registry(_empty_artist_reg(), quals, "2026-07-17")
    rows = ttn_site.build_artist_rows(reg, recs, cons, brc, rec_rows,
                                       work_entries, cdisp)
    by_slug = {r[0]: r for r in rows}
    assert set(by_slug) == {"hannu-lintu", "finnish-rso"}

    lintu = by_slug["hannu-lintu"]
    (slug, mbid, display, kind, roles_json, airings, n_rec,
     first, last, facets_json) = lintu
    assert (mbid, display, kind) == ("m-lintu", "Hannu Lintu", "person")
    assert json.loads(roles_json) == ["Conductor", "Performer"]  # merged roles
    assert airings == 65 and n_rec == 2          # deduped per rp across roles
    assert (first, last) == ("2013-01-01", "2026-01-01")

    facets = json.loads(facets_json)
    # NO top_works: on an artist page a work row IS a performance row 98.7% of
    # the time (one artist, one tape per work), so the block was the
    # performances table with the PID, duration and dates removed. Performances
    # lead instead.
    assert "top_works" not in facets
    assert facets["top_composers"] == [
        {"slug": "sibelius", "display": "Jean Sibelius", "airings": 65}]
    # collaborators: self excluded; FRSO linked (registered), Osborne and the
    # name-keyed Big Star unlinked (below cut / no MBID)
    collab = facets["collaborators"]
    assert collab["ensembles"][0]["display"] == "Finnish RSO"
    assert collab["ensembles"][0]["slug"] == "finnish-rso"
    soloist_names = {s["display"]: s["slug"] for s in collab["soloists"]}
    assert soloist_names == {"Steven Osborne": None, "Big Star": None}
    assert not any(c["display"] == "Hannu Lintu"
                   for b in collab.values() for c in b)
    # by_year from rec_rows airing dates, newest-first
    assert facets["by_year"][0] == {"year": "2020", "airings": 3}
    assert facets["by_year"][-1] == {"year": "2013", "airings": 60}
    # performances ranked by airings, closure-safe fields
    assert facets["performances"][0]["recording_pid"] == "r2"
    assert facets["performances"][0]["work_slug"] == "sibelius:sym2"
    assert facets["broadcasters"][0]["key"] == "FIYLE"

    frso = by_slug["finnish-rso"]
    assert frso[3] == "ensemble"
    assert json.loads(frso[4]) == ["Orchestra"]


def test_artist_performances_cut_is_twenty():
    # The lead block on an artist page. 96% of artists have <=20 recordings,
    # so for almost every page this is the complete list, not a top-N.
    assert ttn_site._ARTIST_PERFORMANCES_TOP_N == 20


def test_build_artist_rows_registry_is_the_page_authority():
    recs, cons, rec_rows, work_entries, cdisp, brc = _artist_fixture()
    reg = {"version": 1,
           "artists": {
               # below-cut but REGISTERED (dropped since mint) -> still a row
               "steven-osborne": {"mbid": "m-osborne", "minted": "2025-01-01",
                                    "display_at_mint": "Steven Osborne"},
               # registered but VANISHED from the corpus -> no row
               "ghost-artist": {"mbid": "m-ghost", "minted": "2025-01-01",
                                 "display_at_mint": "Ghost"},
           },
           "redirects": {}}
    rows = ttn_site.build_artist_rows(reg, recs, cons, brc, rec_rows,
                                       work_entries, cdisp)
    assert [r[0] for r in rows] == ["steven-osborne"]
    assert rows[0][5] == 5                       # its real current airings


def test_build_artist_rows_ensemble_mistag_does_not_hijack_headline():
    # An orchestra whose MBID carries a stray upstream "Performer" credit on
    # ONE airing lands in both the people and group role-sets. The headline
    # count/name/kind must come from the role-set it predominates in (Orchestra,
    # 100 airings), NOT the 1-airing mis-tag bucket -- the ensemble artist-page
    # "Airings 1" deploy-blocker (Reviewer #2, round 3).
    recs = {
        "big": _rec("big", airing_count=100, first="2013-01-01", last="2026-01-01"),
        "tiny": _rec("tiny", airing_count=1, first="2019-01-01", last="2019-01-01"),
    }
    cons = {
        "big": [_con("Orchestra", "m-orch", "Mega Orchestra", "m-orch")],
        "tiny": [_con("Performer", "m-orch", "Mega Orchestra", "m-orch")],
    }
    reg = {"version": 1,
           "artists": {"mega-orchestra": {"mbid": "m-orch", "minted": "2025-01-01",
                                           "display_at_mint": "Mega Orchestra"}},
           "redirects": {}}
    rows = ttn_site.build_artist_rows(reg, recs, cons, {}, [], [], {})
    (slug, mbid, display, kind, roles_json, airings, n_rec,
     first, last, _facets) = rows[0]
    assert (display, kind) == ("Mega Orchestra", "ensemble")
    assert airings == 100 and n_rec == 1     # the Orchestra bulk, not the mis-tag
    assert json.loads(roles_json) == ["Orchestra", "Performer"]  # both still shown


def test_sane_duration_floors_sub_10s_to_none():
    assert ttn_site._sane_duration(2) is None       # a 2s "quartet movement"
    assert ttn_site._sane_duration(9) is None
    assert ttn_site._sane_duration(10) == 10        # floor is inclusive-keep
    assert ttn_site._sane_duration(32) == 32        # the Milhaud interstitial
    assert ttn_site._sane_duration(None) is None
    assert ttn_site._sane_duration(1800) == 1800


def test_build_recording_rows_sub_floor_duration_nulled():
    wk = ("beethoven", "§op67|5")
    work_airings = {wk: [("2020-01-01", "r1", "P", "e1", 0)]}
    recording_airings = {"r1": [("2020-01-01", "e1")]}
    work_slug_of = {wk: "beethoven-symphony-5"}
    composer_slug_of = {"beethoven": "beethoven"}
    recs = {"r1": _rec("r1", duration=2)}           # a 2-second feed artifact
    rows, _n_multi, _n_skip = build_recording_rows(
        work_airings, recording_airings, work_slug_of, composer_slug_of,
        recs, {"r1": []}, {})
    assert rows[0][3] is None                        # duration column nulled


def test_build_country_rows_rolls_up_broadcasters_and_national_profile():
    work_entries = [{"key": ("c", "w"), "slug": "c:w", "work_display": "Work W",
                      "composer_display": "fallback"}]
    composer_display_of = {"c": "Composer C"}
    rec_rows = [
        ("r1", "c:w", "c", 900, "DEWDR", 9, "2016", "2020", "[]", "[]"),
        ("r2", "c:w", "c", 900, "DENDR", 9, "2016", "2020", "[]", "[]"),
    ]
    cons = {"r1": [Contributor("Orchestra", "mW", "WDR SO", "mW")],
            "r2": [Contributor("Orchestra", "mN", "NDR Elbphil", "mN")]}
    # WDR: 5 airings of r1; NDR: 3 of r2; plus a non-EBU + empty label skipped.
    brc_rows = ([("DEWDR", "r1")] * 5 + [("DENDR", "r2")] * 3
                + [("Decca", "r1"), (None, "r1")])
    rows = ttn_site.build_country_rows(
        brc_rows, rec_rows, work_entries, composer_display_of, cons)
    assert len(rows) == 1                        # both German codes -> ONE country
    (slug, country, airings, n_rec, n_brc,
     brc_json, tw_json, tp_json, te_json) = rows[0]
    assert slug == "germany" and country == "Germany"
    assert airings == 8 and n_rec == 2 and n_brc == 2   # rolled up

    # hub: the country's broadcasters, each with its /broadcaster/ page slug,
    # airings-DESC (WDR 5 before NDR 3)
    hub = json.loads(brc_json)
    assert [b["slug"] for b in hub] == ["wdr-westdeutscher-rundfunk",
                                         "ndr-norddeutscher-rundfunk"]
    assert hub[0]["airings"] == 5 and hub[1]["airings"] == 3

    # national profile: work aggregated across BOTH broadcasters (8 airings),
    # listing both tapes that carried it, airings-DESC (r1 5, r2 3)
    tw = json.loads(tw_json)
    assert tw == [{"slug": "c:w", "display": "Work W",
                   "composer_display": "Composer C", "airings": 8,
                   "recording_pids": ["r1", "r2"]}]
    # ensembles union across the country's recordings
    te = {e["display"] for e in json.loads(te_json)}
    assert te == {"WDR SO", "NDR Elbphil"}
    # performances link both recordings
    assert {p["recording_pid"] for p in json.loads(tp_json)} == {"r1", "r2"}


def test_build_browse_payloads_countries_ranks_with_accounting_rows():
    country_rows = [
        ("germany", "Germany", 8, 2, 2, "[]", "[]", "[]", "[]"),
        ("poland", "Poland", 5, 1, 1, "[]", "[]", "[]", "[]"),
    ]
    # a real EBU label (Poland), a non-EBU (OTHER), and an empty (UNATTRIBUTED)
    brc_rows = ([("DEWDR", "r1")] * 5 + [("DENDR", "r2")] * 3
                + [("PLPR", "r3")] * 5 + [("Decca", "r4")] * 2 + [(None, "r5")])
    payloads = dict(build_browse_payloads(
        [], {}, [], brc_rows, {}, {}, {}, {}, {}, country_rows=country_rows))
    countries = json.loads(payloads["countries"])
    by_name = {c["display"]: c for c in countries}
    assert by_name["Germany"]["slug"] == "germany"
    assert by_name["Germany"]["n_broadcasters"] == 2
    assert by_name["Germany"]["airings"] == 8
    # accounting buckets present, link-less (no page)
    assert by_name["OTHER"]["slug"] is None
    assert by_name["UNATTRIBUTED"]["slug"] is None
    # ordered by airings, OTHER/UNATTRIBUTED pinned last
    names = [c["display"] for c in countries]
    assert names[-1] == "UNATTRIBUTED" and names[-2] == "OTHER"


def test_check_closure_detects_dangling_country_links(tmp_path):
    tables = _happy_closure_tables()
    tables["countries"] = [
        ("germany", "Germany", 8, 2, 2,
         json.dumps([{"slug": "ghost-brc", "display": "G", "airings": 1}]),
         json.dumps([{"slug": "ghost:work", "composer_slug": "ghost-composer"}]),
         json.dumps([{"recording_pid": "ghost-rp", "work_slug": "ghost:work2",
                       "composer_slug": "ghost-c"}]),
         json.dumps([])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("countries[germany]" in v and "ghost-brc" in v for v in violations)
    assert any("ghost:work'" in v for v in violations)
    assert any("ghost-rp" in v for v in violations)


def test_check_closure_detects_dangling_browse_country_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("countries", json.dumps([
            {"display": "Germany", "slug": "ghost-country", "airings": 8},
            {"display": "OTHER", "slug": None, "airings": 1},
        ])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("ghost-country" in v for v in violations)
    assert not any("OTHER" in v for v in violations)   # null slug = fine


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
    rows = build_work_rows([entry], work_airings, {}, {}, {}, {}, {})
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

def test_build_browse_payloads_composers_ranked_capped_and_shaped():
    composer_entries = [
        {"composer_key": f"c{i}", "slug": f"c{i}", "display": f"Composer {i}",
         "airings": 200 - i, "n_works": i + 1}
        for i in range(120)
    ]
    payloads = dict(build_browse_payloads(
        [], {}, [], [], {}, {}, {}, {}, {}, composer_entries=composer_entries))
    composers = json.loads(payloads["composers"])
    assert len(composers) == 100                       # capped at 100
    assert composers[0]["slug"] == "c0"                # highest airings (200)
    assert composers[0]["airings"] == 200
    assert set(composers[0]) == {"slug", "display", "airings", "n_works"}


def test_build_browse_payloads_composers_empty_without_entries():
    payloads = dict(build_browse_payloads([], {}, [], [], {}, {}, {}, {}, {}))
    assert json.loads(payloads["composers"]) == []


def test_build_browse_payloads_ensembles_combined_cut_and_total():
    # Combined Orchestra/Ensemble/Choir ranking: one identity under two roles
    # on one recording counts once; sub-cut identities are in `total` but not
    # `rows`; non-ensemble roles are excluded.
    recs = {
        "r1": Recording("r1", "mc", "C", "mc", 100, "t", 60,
                         "2016-01-01", "2020-01-01"),
        "r2": Recording("r2", "mc", "C", "mc", 100, "u", 1,
                         "2016-01-01", "2016-01-01"),
    }
    cons = {
        "r1": [Contributor("Orchestra", "mF", "Finnish RSO", "mF"),
               Contributor("Ensemble", "mF", "Finnish RSO", "mF"),
               Contributor("Conductor", "mX", "Somebody", "mX")],
        "r2": [Contributor("Choir", "mT", "Tiny Choir", "mT")],
    }
    payloads = dict(build_browse_payloads([], {}, [], [], {}, {}, {}, recs, cons))
    ens = json.loads(payloads["ensembles"])
    assert ens["cut"] == ttn_site._ENSEMBLES_AIRINGS_CUT
    assert ens["total"] == 2
    assert ens["rows"] == [
        {"display": "Finnish RSO", "airings": 60, "performances": 1,
         "slug": None}]                       # no artist_slug_of -> link-less


def test_build_browse_payloads_contributor_listings_and_artist_links():
    recs, cons, *_rest = _artist_fixture()
    quals = ttn_site.artist_qualifiers(recs, cons)
    reg, _r = ttn_site.sync_artist_registry(_empty_artist_reg(), quals, "2026-07-17")
    artist_slug_of = {v["mbid"]: slug for slug, v in reg["artists"].items()}

    payloads = dict(build_browse_payloads(
        [], {}, [], [], {}, {}, {}, recs, cons, artist_slug_of=artist_slug_of))

    con = json.loads(payloads["conductors"])
    assert con["cut"] == ttn_site._ARTIST_LISTING_CUT
    assert con["rows"] == [{"display": "Hannu Lintu", "airings": 65,
                             "performances": 2, "slug": "hannu-lintu"}]

    ens = json.loads(payloads["ensembles"])
    assert ens["rows"][0]["slug"] == "finnish-rso"   # registered ensemble links

    per = json.loads(payloads["performers"])
    # Big Star (60 perf. airings, name-keyed) is listed but LINK-LESS;
    # Lintu's 5 performer airings are below the per-role cut -> not listed
    assert per["rows"] == [{"display": "Big Star", "airings": 60,
                             "performances": 1, "slug": None}]

    sing = json.loads(payloads["singers"])
    assert sing["rows"] == [] and sing["total"] == 0


def test_broadcaster_slug_strips_trailing_parenthetical():
    assert ttn_site.broadcaster_slug("MTVA (current)") == "mtva"
    assert ttn_site.broadcaster_slug("Magyar Rádió (legacy)") == "magyar-radio"
    assert ttn_site.broadcaster_slug("Slovak Radio (legacy; now RTVS)") == "slovak-radio"
    assert ttn_site.broadcaster_slug("Catalunya Música (Catalan classical)") == "catalunya-musica"
    assert ttn_site.broadcaster_slug("Polskie Radio") == "polskie-radio"


def test_mint_broadcaster_slugs_unique_and_collision_qualified():
    minted = ttn_site.mint_broadcaster_slugs()
    slugs = [s for s, _n, _c in minted.values()]
    assert len(slugs) == len(set(slugs))          # the hard invariant
    # the Swiss/Serbian RTS acronym clash: BOTH sides country-qualified
    assert minted["CHRTS"][0] == "rts-switzerland"
    assert minted["CSRTS"][0] == "rts-serbia"
    # an unambiguous name keeps its clean slug
    assert minted["PLPR"][0] == "polskie-radio"


def test_build_broadcaster_rows_sections_and_accounting():
    work_entries = [{"key": ("c", "w"), "slug": "c:w", "work_display": "Work W",
                      "composer_display": "fallback"}]
    composer_display_of = {"c": "Composer C"}
    rec_rows = [
        ("r1", "c:w", "c", 900, "X", 9, "2016", "2020", "[]", "[]"),
        ("r2", "c:w", "c", 900, "X", 9, "2016", "2020", "[]", "[]"),
    ]
    cons = {"r1": [Contributor("Orchestra", "mF", "Finnish RSO", "mF")],
            "r2": [Contributor("Orchestra", "mF", "Finnish RSO", "mF"),
                    Contributor("Choir", "mT", "Tapiola Choir", "mT")]}
    # 3 PLPR airings of r1, 1 of r2; 1 non-EBU label + 1 empty label skipped.
    brc_rows = [("PLPR", "r1")] * 3 + [("PLPR", "r2"), ("Decca", "r1"), (None, "r1")]
    rows = ttn_site.build_broadcaster_rows(
        brc_rows, rec_rows, work_entries, composer_display_of, cons)
    assert len(rows) == 1
    slug, key, display, country, airings, n_rec, tw, tp, te = rows[0]
    assert (slug, key, country) == ("polskie-radio", "PLPR", "Poland")
    assert airings == 4 and n_rec == 2
    tw, tp, te = json.loads(tw), json.loads(tp), json.loads(te)
    assert tw == [{"slug": "c:w", "display": "Work W",
                   "composer_display": "Composer C", "airings": 4,
                   "recording_pids": ["r1", "r2"]}]
    assert [p["recording_pid"] for p in tp] == ["r1", "r2"]
    assert tp[0]["airings"] == 3                    # THIS broadcaster's count
    # ensemble rows carry the identity's mbid for /artist/ linking
    assert te[0] == {"display": "Finnish RSO", "mbid": "mF", "airings": 4}
    assert te[1] == {"display": "Tapiola Choir", "mbid": "mT", "airings": 1}


def test_source_ranking_facets_orders_work_pids_by_airings():
    # Three tapes of one work under one source: the PID list is airings-DESC
    # (tie -> pid), the same convention as top_performances, so the busiest
    # tape reads first in the cell.
    per_rp = {"rB": 1, "rA": 1, "rC": 7}
    rec_meta = {"rA": ("c:w", "c"), "rB": ("c:w", "c"), "rC": ("c:w", "c")}
    disp_of = {"c:w": ("Work W", "Composer C")}
    top_works, _tp, _te = ttn_site._source_ranking_facets(
        per_rp, rec_meta, disp_of, {}, 10)
    assert top_works[0]["recording_pids"] == ["rC", "rA", "rB"]
    assert top_works[0]["airings"] == 9


def test_source_ranking_facets_omits_pids_with_no_recordings_row():
    # rec_meta comes from the BUILT recordings tuples, so an rp absent from it
    # has no recordings row -- it must not reach the PID list (closure).
    per_rp = {"rA": 3, "ghost": 5}
    rec_meta = {"rA": ("c:w", "c")}
    disp_of = {"c:w": ("Work W", "Composer C")}
    top_works, _tp, _te = ttn_site._source_ranking_facets(
        per_rp, rec_meta, disp_of, {}, 10)
    assert top_works[0]["recording_pids"] == ["rA"]
    assert top_works[0]["airings"] == 3


def test_check_closure_detects_dangling_broadcaster_page_links(tmp_path):
    tables = _happy_closure_tables()
    tables["broadcasters"] = [
        ("polskie-radio", "PLPR", "Polskie Radio", "Poland", 4, 2,
         json.dumps([{"slug": "ghost:work", "display": "G",
                      "composer_display": "G", "airings": 1,
                      "recording_pids": ["ghost-work-rp"]}]),
         json.dumps([{"recording_pid": "ghost-rp", "work_slug": "ghost:work2",
                      "composer_slug": "ghost-composer", "airings": 1}]),
         json.dumps([])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("broadcasters[polskie-radio]" in v and "ghost:work'" in v
               for v in violations)
    assert any("ghost-rp" in v for v in violations)
    assert any("ghost-composer" in v for v in violations)
    assert any("top_works[0].recording_pids[0]" in v and "ghost-work-rp" in v
               for v in violations)


def test_check_closure_detects_dangling_browse_broadcaster_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("broadcasters", json.dumps([
            {"key": "PLPR", "airings": 4, "recordings": 2, "slug": "ghost-brc"},
            {"key": "OTHER", "airings": 1, "recordings": 1, "slug": None},
        ])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("ghost-brc" in v for v in violations)
    assert not any("OTHER" in v for v in violations)   # null slug = no violation


def test_build_browse_payloads_top_performances_ranked_joined_and_skips_unknown():
    work_entries = [{"key": ("c", "w"), "slug": "c:w", "work_display": "Work W",
                      "composer_display": "per-work spelling"}]
    composer_display_of = {"c": "Composer C"}   # the SSOT display wins
    # 10-tuples in recordings-schema order; r2 outranks r1 by airings; r3's
    # work_slug is unknown to work_entries -> skipped.
    recording_rows = [
        ("r1", "c:w", "c", 900, "BBC", 5, "2016-01-01", "2020-01-01", "[]", "[]"),
        ("r2", "c:w", "c", 900, "BBC", 9, "2016-01-01", "2020-01-01", "[]", "[]"),
        ("r3", "ghost:slug", "c", 900, "BBC", 99, "2016-01-01", "2020-01-01", "[]", "[]"),
    ]
    cons = {"r2": [Contributor("Conductor", "mC", "Maestro", "mC"),
                    Contributor("Orchestra", "mO", "Band", "mO"),
                    Contributor("Performer", "mP", "Soloist", "mP")]}
    payloads = dict(build_browse_payloads(
        work_entries, {}, [], [], {}, composer_display_of, {}, {}, cons,
        recording_rows=recording_rows))
    tp = json.loads(payloads["top_performances"])
    assert [p["recording_pid"] for p in tp] == ["r2", "r1"]   # ranked, r3 skipped
    assert tp[0]["work_display"] == "Work W"
    assert tp[0]["composer_display"] == "Composer C"
    assert tp[0]["airings"] == 9
    assert tp[0]["conductors"] == ["Maestro"]
    assert tp[0]["ensembles"] == ["Band"]
    assert tp[0]["soloists"] == ["Soloist"]


def test_build_browse_payloads_top_performances_empty_without_rows():
    payloads = dict(build_browse_payloads([], {}, [], [], {}, {}, {}, {}, {}))
    assert json.loads(payloads["top_performances"]) == []


def test_weighted_median_reaches_half_total_weight():
    assert ttn_site._weighted_median([(100, 1)]) == 100
    # the 1-airing outlier can't drag the median off the 9-airing recording
    assert ttn_site._weighted_median([(500, 9), (2000, 1)]) == 500
    assert ttn_site._weighted_median([(500, 1), (2000, 9)]) == 2000
    assert ttn_site._weighted_median([(100, 1), (200, 1)]) == 100  # ties -> lower


def test_build_browse_payloads_lengths_classifies_by_work_median():
    entries = [
        {"key": ("c", "w1"), "slug": "c:short", "work_display": "Short Piece",
         "composer_display": "C"},
        {"key": ("c", "w2"), "slug": "c:straddle", "work_display": "Straddler",
         "composer_display": "C"},
        {"key": ("c", "w3"), "slug": "c:long", "work_display": "Long Piece",
         "composer_display": "C"},
        {"key": ("c", "w4"), "slug": "c:unmeasured", "work_display": "Text Only",
         "composer_display": "C"},
    ]
    work_airings = {("c", "w1"): [("2020", None, "P", "e", 0)] * 5,
                    ("c", "w2"): [("2020", None, "P", "e", 0)] * 9,
                    ("c", "w3"): [("2020", None, "P", "e", 0)] * 2,
                    ("c", "w4"): [("2015", None, "P", "e", 0)] * 7}
    # the straddler has recordings either side of 10m; the airing-weighted
    # median (8 airings at 620s vs 1 at 580s) lands it in MEDIUM, once.
    recording_rows = [
        ("r1", "c:short", "c", 300, "X", 5, "a", "b", "[]", "[]"),
        ("r2", "c:straddle", "c", 620, "X", 8, "a", "b", "[]", "[]"),
        ("r3", "c:straddle", "c", 580, "X", 1, "a", "b", "[]", "[]"),
        ("r4", "c:long", "c", 2400, "X", 2, "a", "b", "[]", "[]"),
    ]
    payloads = dict(build_browse_payloads(
        entries, work_airings, [], [], {"c": "c"}, {"c": "Composer C"}, {},
        {}, {}, recording_rows=recording_rows))
    lengths = json.loads(payloads["lengths"])
    assert lengths["short_max"] == 600 and lengths["long_min"] == 1800
    assert [w["slug"] for w in lengths["short"]] == ["c:short"]
    assert [w["slug"] for w in lengths["medium"]] == ["c:straddle"]
    assert [w["slug"] for w in lengths["long"]] == ["c:long"]
    med = lengths["medium"][0]
    assert med["median_seconds"] == 620
    assert med["airings"] == 9                      # total airings, not 2012+
    assert med["composer_display"] == "Composer C"  # the SSOT display
    # the unmeasured work appears in NO section
    all_slugs = {w["slug"] for s in ("short", "medium", "long")
                 for w in lengths[s]}
    assert "c:unmeasured" not in all_slugs


def test_check_closure_detects_dangling_lengths_links(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("lengths", json.dumps({
            "short_max": 600, "long_min": 1800,
            "short": [{"slug": "ghost:work", "composer_slug": "ghost-composer"}],
            "medium": [], "long": [],
        })),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("lengths.short" in v and "ghost:work" in v for v in violations)
    assert any("lengths.short" in v and "ghost-composer" in v for v in violations)


def test_build_form_rows_classifies_ranks_and_multi_counts():
    entries = [
        {"key": ("c", "w1"), "slug": "c:piano-concerto",
         "work_display": "Piano Concerto No 1", "composer_display": "C"},
        {"key": ("c", "w2"), "slug": "c:concertino",
         "work_display": "Concertino for flute", "composer_display": "C"},
        {"key": ("c", "w3"), "slug": "c:prelude",
         "work_display": "Prélude à l'après-midi", "composer_display": "C"},
        {"key": ("c", "w4"), "slug": "c:waltz-dance",
         "work_display": "Waltz from Dance Suite", "composer_display": "C"},
        {"key": ("c", "w5"), "slug": "c:bare-title",
         "work_display": "Finlandia", "composer_display": "C"},
    ]
    work_airings = {("c", "w1"): [("2020", None, "P", "e", 0)] * 5,
                    ("c", "w2"): [("2020", None, "P", "e", 0)] * 3,
                    ("c", "w3"): [("2020", None, "P", "e", 0)] * 2,
                    ("c", "w4"): [("2020", None, "P", "e", 0)] * 1,
                    ("c", "w5"): [("2020", None, "P", "e", 0)] * 9}
    rows = ttn_site.build_form_rows(
        entries, work_airings, {"c": "c"}, {"c": "Composer C"})
    by_slug = {r[0]: r for r in rows}

    # word-boundary: the concertino does NOT land under concerto (and vice versa)
    assert [w["slug"] for w in json.loads(by_slug["concerto"][4])] == ["c:piano-concerto"]
    assert [w["slug"] for w in json.loads(by_slug["concertino"][4])] == ["c:concertino"]
    # diacritic fold: 'Prélude' classifies under prelude
    assert [w["slug"] for w in json.loads(by_slug["prelude"][4])] == ["c:prelude"]
    # multi-form: one title counts under waltz AND dance AND suite
    for form in ("waltz", "dance", "suite"):
        assert [w["slug"] for w in json.loads(by_slug[form][4])] == ["c:waltz-dance"]
    # a name-titled work appears under NO form; zero-match forms get no row
    assert not any("c:bare-title" in r[4] for r in rows)
    assert "symphony" not in by_slug
    # accounting + shape: airings/n_works, terms as written, SSOT display
    assert by_slug["concerto"][1] == 5 and by_slug["concerto"][2] == 1
    assert json.loads(by_slug["prelude"][3]) == ["prelude", "prélude", "preludes"]
    top = json.loads(by_slug["concerto"][4])[0]
    assert top["composer_display"] == "Composer C"
    assert top["composer_slug"] == "c"
    assert top["airings"] == 5
    # airings-DESC row order (concerto 5 ahead of concertino 3)
    slugs_in_order = [r[0] for r in rows]
    assert slugs_in_order.index("concerto") < slugs_in_order.index("concertino")


def test_build_form_rows_top_works_capped():
    entries = [
        {"key": ("c", f"w{i}"), "slug": f"c:sonata-{i}",
         "work_display": f"Sonata No {i}", "composer_display": "C"}
        for i in range(60)
    ]
    work_airings = {("c", f"w{i}"): [("2020", None, "P", "e", 0)] * (60 - i)
                    for i in range(60)}
    rows = ttn_site.build_form_rows(entries, work_airings, {}, {})
    (slug, airings, n_works, _terms, tw_json) = rows[0]
    assert slug == "sonata"
    assert n_works == 60                          # the count is uncapped
    assert airings == sum(range(1, 61))
    assert len(json.loads(tw_json)) == ttn_site._FORM_PAGE_TOP_N


def test_build_browse_payloads_forms_derived_from_form_rows():
    form_rows = [
        ("concerto", 500, 40, json.dumps(["concerto"]), "[]"),
        ("nocturne", 90, 12, json.dumps(["nocturne", "notturno"]), "[]"),
    ]
    payloads = dict(build_browse_payloads(
        [], {}, [], [], {}, {}, {}, {}, {}, form_rows=form_rows))
    forms = json.loads(payloads["forms"])
    assert forms == [
        {"slug": "concerto", "display": "Concerto", "airings": 500, "n_works": 40},
        {"slug": "nocturne", "display": "Nocturne", "airings": 90, "n_works": 12},
    ]
    # and empty without the kwarg
    payloads = dict(build_browse_payloads([], {}, [], [], {}, {}, {}, {}, {}))
    assert json.loads(payloads["forms"]) == []


def test_build_browse_payloads_christmas_window_ranking_and_nights():
    entries = [
        {"key": ("c", "w1"), "slug": "c:carol", "work_display": "A Carol",
         "composer_display": "C"},
        {"key": ("c", "w2"), "slug": "c:summer", "work_display": "Summer Piece",
         "composer_display": "C"},
    ]
    work_airings = {
        # 3 airings inside the window (12-24 Christmas Eve + 12-25 Christmas
        # Day broadcasts); the 12-26 night is deliberately OUTSIDE it
        # (measured 2026-07-17: 7.4% festive-titled vs the 25th's 29.7% and
        # the 24th's 23.4%), as is the March airing
        ("c", "w1"): [("2024-12-25", None, "P", "e1", 0),
                       ("2023-12-25", None, "P", "e2", 0),
                       ("2022-12-24", None, "P", "e3", 0),
                       ("2023-12-26", None, "P", "e4", 0),
                       ("2024-03-01", None, "P", "e5", 0)],
        ("c", "w2"): [("2024-07-01", None, "P", "e6", 0)],
    }
    payloads = dict(build_browse_payloads(
        entries, work_airings, [], [], {"c": "c"}, {"c": "Composer C"},
        {}, {}, {}))
    xmas = json.loads(payloads["christmas"])
    assert xmas["window"] == ["12-24", "12-25"]
    assert [w["slug"] for w in xmas["top_works"]] == ["c:carol"]
    assert xmas["top_works"][0]["airings"] == 3          # in-window only
    assert xmas["top_works"][0]["composer_display"] == "Composer C"
    assert xmas["nights"] == ["2024-12-25", "2023-12-25", "2022-12-24"]  # newest first
    # a corpus with no Christmas airings -> empty shape, page still renderable
    payloads = dict(build_browse_payloads([], {}, [], [], {}, {}, {}, {}, {}))
    xmas = json.loads(payloads["christmas"])
    assert xmas["top_works"] == [] and xmas["nights"] == []


def test_check_closure_detects_dangling_browse_christmas_links(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("christmas", json.dumps({
            "window": ["12-24", "12-25"],
            "top_works": [{"slug": "ghost:work", "composer_slug": "ghost-composer"}],
            "nights": ["2024-12-25"],
        })),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("christmas.top_works" in v and "ghost:work" in v for v in violations)
    assert any("christmas.top_works" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_contributor_listing_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("conductors", json.dumps({"cut": 50, "total": 2, "rows": [
            {"display": "G", "airings": 60, "performances": 2,
             "slug": "ghost-artist"},
            {"display": "N", "airings": 55, "performances": 1, "slug": None},
        ]})),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("conductors.rows[0].slug" in v and "ghost-artist" in v
               for v in violations)
    assert not any("rows[1]" in v for v in violations)   # null = link-less, fine


def test_check_closure_detects_dangling_artist_facet_links(tmp_path):
    tables = _happy_closure_tables()
    tables["artists"] = [
        ("hannu-lintu", "m-lintu", "Hannu Lintu", "person",
         json.dumps(["Conductor"]), 65, 2, "2013-01-01", "2026-01-01",
         json.dumps({
             "top_composers": [{"slug": "ghost-composer"}],
             "performances": [{"recording_pid": "ghost-rp",
                                "work_slug": "ghost:work2"}],
             "collaborators": {"ensembles": [{"display": "X", "airings": 1,
                                                "slug": "ghost-artist"}],
                                "soloists": [{"display": "Y", "airings": 1,
                                               "slug": None}]},
         })),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("ghost-composer" in v for v in violations)
    assert any("ghost-rp" in v for v in violations)
    assert any("ghost:work2" in v for v in violations)
    assert any("ghost-artist" in v for v in violations)
    # the null collaborator slug is NOT a violation
    assert not any("soloists[0]" in v for v in violations)


def test_check_closure_detects_dangling_form_page_links(tmp_path):
    tables = _happy_closure_tables()
    tables["forms"] = [
        ("symphony", 100, 5, "[]",
         json.dumps([{"slug": "ghost:work", "composer_slug": "ghost-composer",
                      "display": "G", "composer_display": "G", "airings": 1}])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("forms[symphony]" in v and "ghost:work" in v for v in violations)
    assert any("forms[symphony]" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_browse_form_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("forms", json.dumps([
            {"slug": "ghost-form", "display": "Ghost", "airings": 1, "n_works": 1},
        ])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("ghost-form" in v for v in violations)


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
        {}, {"c": "c"}, {}, {})
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
    payloads = build_browse_payloads([], {}, all_rows5, all_brc_rows, {}, {}, {}, {}, {})
    names = dict(payloads)

    years = json.loads(names["years"])
    assert years[0]["year"] == "2020"
    assert years[0]["airings"] == 1

    broadcasters = json.loads(names["broadcasters"])
    assert {b["key"] for b in broadcasters} == {"GBBBC", "PLPR"}


def test_build_browse_payloads_years_newest_first():
    all_rows5 = [
        ("Sym 5", "Beethoven", "Beethoven", "P", "2018-01-01"),
        ("Sym 5", "Beethoven", "Beethoven", "P", "2020-01-01"),
        ("Sym 5", "Beethoven", "Beethoven", "P", "2024-01-01"),
    ]
    payloads = build_browse_payloads([], {}, all_rows5, [], {}, {}, {}, {}, {})
    years = json.loads(dict(payloads)["years"])
    assert [y["year"] for y in years] == ["2024", "2020", "2018"]


def test_build_browse_payloads_house_performances_dominant_and_broadcaster():
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

    # rec1's EBU labels -> its majority broadcaster (BBC) + drill-in slug.
    all_brc_rows = [("GBBBC", "rec1"), ("GBBBC", "rec1"), ("NLNOS", "rec2")]
    payloads = build_browse_payloads(work_entries, work_airings, [], all_brc_rows,
                                      composer_slug_of, {}, work_slug_of, recs, cons)
    names = dict(payloads)
    house = json.loads(names["house_performances"])
    assert len(house) == 1
    h = house[0]
    assert h["work_slug"] == "c-w"
    assert h["recording_pid"] == "rec1"
    assert h["rec_airings"] == 3
    assert h["total_2016"] == 4          # rec1(3) + rec2(1), 2016+ only
    assert "share_pct" not in h          # the Share column was retired
    assert h["broadcaster"] == "BBC"     # rec1's majority EBU label, decoded
    assert h["broadcaster_slug"] == "bbc"
    assert h["conductors"] == ["K"]
    assert h["ensembles"] == ["O"]
    assert h["soloists"] == []


def test_build_browse_payloads_house_performances_skips_work_with_no_2016_recording():
    key = ("c", "w")
    work_entries = [{"key": key, "slug": "c-w", "composer_display": "C",
                      "work_display": "W"}]
    work_airings = {
        key: [("2010-01-01", "rec1", "P", "ep1", 0)],   # pre-2016 only
    }
    recs = {"rec1": _rec("rec1")}
    cons = {}
    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      {"c": "c"}, {}, {key: "c-w"}, recs, cons)
    names = dict(payloads)
    house = json.loads(names["house_performances"])
    assert house == []


def test_build_browse_payloads_house_performances_spine_excluded_rp_cannot_dominate():
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
                                      {"c": "c"}, {}, {key: "c-w"}, recs, {})
    house = json.loads(dict(payloads)["house_performances"])
    assert len(house) == 1
    assert house[0]["recording_pid"] == "rec1"
    assert house[0]["rec_airings"] == 1
    assert house[0]["total_2016"] == 1     # ghost airings out of the denominator
    assert house[0]["broadcaster"] is None  # no EBU labels supplied

    # ...and a work whose ONLY 2016+ rps are excluded is skipped entirely.
    work_airings[key] = work_airings[key][:3]          # ghost rows only
    payloads = build_browse_payloads(work_entries, work_airings, [], [],
                                      {"c": "c"}, {}, {key: "c-w"}, recs, {})
    assert json.loads(dict(payloads)["house_performances"]) == []


def test_build_browse_payloads_house_performances_tie_breaks_lexicographically():
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
                                      {"c": "c"}, {}, {key: "c-w"}, recs, {})
    house = json.loads(dict(payloads)["house_performances"])
    assert house[0]["recording_pid"] == "recA"   # tie 1-vs-1 -> lexicographic


def test_build_browse_payloads_house_performances_only_top_50_works_considered():
    # 60 works, all with a 2016+ recording; only the top 50 by total airings
    # should be candidates for house_performances.
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
                                      {"c": "c"}, {}, work_slug_of, recs, {})
    house = json.loads(dict(payloads)["house_performances"])
    slugs = {h["work_slug"] for h in house}
    assert "w49" in slugs      # 50th-highest airings, just inside top 50
    assert "w50" not in slugs  # 51st-highest, excluded


# --- build_year_rows ----------------------------------------------------------

def test_build_year_rows_buckets_by_year_and_ranks():
    work_entries = [
        {"key": ("beethoven", "sym5"), "slug": "beethoven:sym5",
         "work_display": "Symphony No 5", "composer_display": "Ludwig van Beethoven"},
        {"key": ("mozart", "req"), "slug": "mozart:requiem",
         "work_display": "Requiem", "composer_display": "W A Mozart"},
    ]
    work_airings = {
        ("beethoven", "sym5"): [
            ("2020-01-01", "r1", "P", "e1", 0),
            ("2020-06-01", "r1", "P", "e2", 0),
            ("2021-02-01", "r1", "P", "e3", 0),
        ],
        ("mozart", "req"): [
            ("2020-03-01", "r2", "P", "e4", 0),
        ],
    }
    composer_slug_of = {"beethoven": "beethoven", "mozart": "mozart"}
    composer_display_of = {"beethoven": "Ludwig van Beethoven", "mozart": "Wolfgang Amadeus Mozart"}
    work_slug_of = {("beethoven", "sym5"): "beethoven:sym5", ("mozart", "req"): "mozart:requiem"}

    rows = build_year_rows(work_entries, work_airings, composer_slug_of,
                           composer_display_of, work_slug_of)
    by_year = {r[0]: r for r in rows}
    assert set(by_year) == {"2020", "2021"}

    y2020 = by_year["2020"]
    assert y2020[1] == 3               # airings: beethoven x2 + mozart x1
    assert y2020[2] == 2               # distinct works
    assert y2020[3] == 2               # distinct composers
    top_works = json.loads(y2020[4])
    assert top_works[0]["slug"] == "beethoven:sym5"     # 2 airings, ranked first
    assert top_works[0]["airings"] == 2
    # SSOT composer display used, not the work entry's per-work spelling
    assert top_works[1]["composer_display"] == "Wolfgang Amadeus Mozart"
    top_composers = json.loads(y2020[5])
    assert top_composers[0]["slug"] == "beethoven"
    assert top_composers[0]["airings"] == 2

    y2021 = by_year["2021"]
    assert y2021[1] == 1


def test_build_year_rows_skips_undated_airings_and_unslugged_works():
    work_entries = [
        {"key": ("", "orphan"), "slug": None, "work_display": "Orphan",
         "composer_display": ""},
        {"key": ("beethoven", "sym5"), "slug": "beethoven:sym5",
         "work_display": "Symphony No 5", "composer_display": "Beethoven"},
    ]
    work_airings = {
        ("", "orphan"): [("2020-01-01", None, "P", "e0", 0)],       # unslugged
        ("beethoven", "sym5"): [
            (None, "r1", "P", "e1", 0),                             # undated: skipped
            ("2020-01-01", "r1", "P", "e2", 0),
        ],
    }
    rows = build_year_rows(work_entries, work_airings, {"beethoven": "beethoven"},
                           {"beethoven": "Ludwig van Beethoven"},
                           {("beethoven", "sym5"): "beethoven:sym5"})
    y2020 = {r[0]: r for r in rows}["2020"]
    # 2 airings counted (orphan + the one dated beethoven); undated skipped
    assert y2020[1] == 2
    top_works = json.loads(y2020[4])
    # the unslugged work is excluded from the ranked list (no page to link)
    assert [w["slug"] for w in top_works] == ["beethoven:sym5"]


# --- check_closure (Task 8) --------------------------------------------------
# check_closure(conn) walks a BUILT site.sqlite and returns a list of
# violation strings (empty = pass) for every non-NULL cross-table reference:
# works.composer_slug, recordings.work_slug/composer_slug, every
# episodes.tracks_json entry's work_slug/composer_slug/recording_pid, every
# composers.works_json entry's slug, every works.facets_json
# recordings[].recording_pid, and browse's top_works/house_performances slugs.
# A JSON null (None) link is the deliberate junk-row case and never a
# violation -- only a non-null dangling reference is.

def _work_row(slug="beet:sym5", composer_slug_val="beethoven", facets=None):
    return (slug, composer_slug_val, "beethoven", "sym5", "Symphony No 5",
            "Beethoven", None, 10, 1, 0, "2020-01-01", "2020-06-01",
            json.dumps(facets if facets is not None else {"recordings": []}))


def _composer_row(slug="beethoven", works_json=None):
    return (slug, "beethoven", "Beethoven", 10, 1,
            json.dumps(works_json if works_json is not None else
                       [{"slug": "beet:sym5", "display": "Symphony No 5", "airings": 10}]),
            "{}")


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
            ("house_performances", json.dumps([
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


def test_check_closure_detects_dangling_facets_broadcaster_slug(tmp_path):
    tables = _happy_closure_tables()
    tables["works"] = [_work_row(facets={
        "recordings": [{"recording_pid": None, "broadcaster_slug": "ghost-brc"}],
    })]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("broadcaster_slug" in v and "ghost-brc" in v for v in violations)


def test_check_closure_detects_dangling_browse_top_works(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_works", json.dumps([
            {"slug": "ghost:work", "composer_slug": "beethoven"},
        ])),
        ("house_performances", json.dumps([])),
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
        ("house_performances", json.dumps([])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("browse" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_browse_top_performances(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_performances", json.dumps([
            {"work_slug": "ghost:work", "composer_slug": "ghost-composer",
             "recording_pid": "ghost-rp"},
        ])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("top_performances" in v and "ghost:work" in v for v in violations)
    assert any("top_performances" in v and "ghost-composer" in v for v in violations)
    assert any("top_performances" in v and "ghost-rp" in v for v in violations)


def test_check_closure_detects_dangling_browse_composers(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("composers", json.dumps([{"slug": "ghost-composer"}])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("browse" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_year_top_works(tmp_path):
    tables = _happy_closure_tables()
    tables["years"] = [
        ("2020", 1, 1, 1,
         json.dumps([{"slug": "ghost:work", "composer_slug": "beethoven"}]),
         json.dumps([])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("years" in v and "ghost:work" in v for v in violations)


def test_check_closure_detects_dangling_year_top_composers(tmp_path):
    tables = _happy_closure_tables()
    tables["years"] = [
        ("2020", 1, 1, 1,
         json.dumps([]),
         json.dumps([{"slug": "ghost-composer"}])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("years" in v and "ghost-composer" in v for v in violations)


def test_check_closure_detects_dangling_browse_house_performances(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_works", json.dumps([])),
        ("house_performances", json.dumps([
            {"work_slug": "ghost:work", "composer_slug": "beethoven",
             "recording_pid": "rec1"},
        ])),
    ]
    conn = _closure_conn(tmp_path, tables)
    violations = check_closure(conn)
    conn.close()
    assert any("browse" in v and "ghost:work" in v for v in violations)


def test_check_closure_detects_dangling_browse_house_performances_recording_pid(tmp_path):
    tables = _happy_closure_tables()
    tables["browse"] = [
        ("top_works", json.dumps([])),
        ("house_performances", json.dumps([
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
    # the autouse guard patches ttn_site.dist_path_default; test the REAL one
    path = _REAL_DIST_PATH_DEFAULT()
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


def test_main_default_base_url_is_production_domain(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    calls = []
    def _fake_render_site(site_db_arg, registry_arg, dist_arg, base_url=None, pagefind=None):
        calls.append(base_url)
        return {"pages": 3, "written": 3, "skipped": 0, "pruned": 0,
                "crawl_ok": True, "pagefind": pagefind}
    monkeypatch.setattr(ttn_site, "render_site", _fake_render_site)

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist)])
    assert rc in (0, None)
    assert calls == [ttn_site.BASE_URL]


def test_main_base_url_flag_overrides(tmp_path, monkeypatch):
    db_path = tmp_path / "fixture.sqlite"
    _make_fixture_db(db_path)
    registry_path = tmp_path / "registry.json"
    site_db = tmp_path / "site.sqlite"
    dist = tmp_path / "dist"

    monkeypatch.setattr(ttn_site.ttn_project, "load", lambda conn: ({}, {}, "ok"))
    monkeypatch.setattr(ttn_site, "load_slug_map", lambda path: {})

    calls = []
    def _fake_render_site(site_db_arg, registry_arg, dist_arg, base_url=None, pagefind=None):
        calls.append(base_url)
        return {"pages": 3, "written": 3, "skipped": 0, "pruned": 0,
                "crawl_ok": True, "pagefind": pagefind}
    monkeypatch.setattr(ttn_site, "render_site", _fake_render_site)

    rc = ttn_site.main(["--db", str(db_path), "--registry", str(registry_path),
                         "--site-db", str(site_db), "--dist", str(dist),
                         "--base-url", "https://staging.example"])
    assert rc in (0, None)
    assert calls == ["https://staging.example"]


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


def test_run_remap_spec_parses_pipe_bearing_catalogue_work_key(tmp_path):
    # Catalogue-path work keys legitimately CONTAIN pipes ('§hwv232|232|');
    # the CLI spec is pipe-delimited, so _run_remap must maxsplit -- a plain
    # split rejected every §-keyed remap (first hit: the Handel batch).
    import json
    reg_path = tmp_path / "reg.json"
    reg_path.write_text(json.dumps({
        "version": 1,
        "works": {"handel:hwv232": {"composer_key": "george frideric handel",
                                     "work_key": "§hwv232|109,232|",
                                     "published": "2026-01-01"}},
        "composers": {}, "redirects": {"works": {}, "composers": {}},
    }))
    rc = ttn_site._run_remap(str(reg_path), "works",
                             [("test", "handel:hwv232|george frideric handel|§hwv232|232|")])
    assert rc == 0
    reg = json.loads(reg_path.read_text())
    assert reg["works"]["handel:hwv232"]["work_key"] == "§hwv232|232|"


# --- composer_search_weight ------------------------------------------------

import math
from ttn_site_render import composer_search_weight


def test_composer_search_weight_anchors():
    # Validated spike anchors (k=2.5, banker's round, clamp 1..10).
    assert composer_search_weight(7032) == 10   # Wolfgang Amadeus Mozart
    assert composer_search_weight(53) == 4       # Attributed Mozart
    assert composer_search_weight(9) == 2        # bare Mozart
    assert composer_search_weight(1) == 1        # one-off
    assert composer_search_weight(0) == 1        # defensive floor


def test_composer_search_weight_in_range():
    for a in [0, 1, 4, 9, 60, 755, 7032, 100000]:
        w = composer_search_weight(a)
        assert 1 <= w <= 10


def test_composer_search_weight_monotonic_nondecreasing():
    prev = 0
    for a in range(0, 20001):
        w = composer_search_weight(a)
        assert w >= prev
        prev = w


def test_composer_search_weight_handles_none():
    assert composer_search_weight(None) == 1
