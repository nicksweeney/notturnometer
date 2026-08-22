"""Tests for ttn_evidence: cache I/O conventions + the match rule.

Run: uv run --with pytest pytest test_ttn_evidence.py
"""
import json

import ttn_evidence as ev


def _pids(*names):
    return set(names)


# --- write_evidence / load_evidence ------------------------------------------

def test_write_then_load_round_trips(tmp_path):
    path = str(tmp_path / "ev.json")
    ev.write_evidence(
        {"a:x": {"rp1", "rp2", "rp3"}, "b:y": {"rp4"}},
        rows_sha="abc123", path=path, today="2026-08-22")
    data = ev.load_evidence(path)
    assert data["works"]["a:x"] == frozenset({"rp1", "rp2", "rp3"})
    assert data["works"]["b:y"] == frozenset({"rp4"})

    raw = json.load(open(path))
    assert raw["rows_sha"] == "abc123"
    assert raw["written"] == "2026-08-22"


def test_empty_pid_sets_are_dropped(tmp_path):
    path = str(tmp_path / "ev.json")
    ev.write_evidence({"a:x": set(), "b:y": {"rp1"}}, path=path)
    data = ev.load_evidence(path)
    assert "a:x" not in data["works"]
    assert "b:y" in data["works"]


def test_sample_is_sorted_and_capped(tmp_path):
    path = str(tmp_path / "ev.json")
    pids = {f"rp{i:03d}" for i in range(50)}
    ev.write_evidence({"a:x": pids}, path=path)
    raw = json.load(open(path))
    stored = raw["works"]["a:x"]
    assert len(stored) == ev.CAP
    assert stored == sorted(stored)          # deterministic bytes
    # sorted order keeps the lexicographically first CAP pids
    assert set(stored) <= pids


def test_missing_file_degrades_to_empty(tmp_path):
    data = ev.load_evidence(str(tmp_path / "nope.json"))
    assert data == {"works": {}}


def test_corrupt_file_degrades_to_empty(tmp_path):
    path = tmp_path / "ev.json"
    path.write_text("{not json")
    assert ev.load_evidence(str(path)) == {"works": {}}


def test_wrong_shape_degrades_to_empty(tmp_path):
    path = tmp_path / "ev.json"
    path.write_text(json.dumps({"works": "not-a-dict"}))
    assert ev.load_evidence(str(path)) == {"works": {}}
    path.write_text(json.dumps(["not", "a", "dict"]))
    assert ev.load_evidence(str(path)) == {"works": {}}


def test_non_string_pids_filtered_on_load(tmp_path):
    path = tmp_path / "ev.json"
    path.write_text(json.dumps({"works": {"a:x": ["ok", 42, None]}}))
    data = ev.load_evidence(str(path))
    assert data["works"] == {}


def test_atomic_write_leaves_no_tmp_files(tmp_path):
    import os
    path = str(tmp_path / "ev.json")
    ev.write_evidence({"a:x": {"rp1"}}, path=path)
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert leftovers == []


# --- match_unique --------------------------------------------------------------

def test_match_unique_clear_winner():
    # The orphaned identity itself never appears among candidates: it is
    # absent from current derivation by definition of being an orphan.
    pbi = {
        ("composer a", "new key"): _pids("rp1", "rp2", "rp3"),
        ("composer b", "unrelated"): _pids("rp9"),
    }
    assert ev.match_unique(_pids("rp1", "rp2"), pbi) == \
        ("composer a", "new key")


def test_match_unique_ambiguous_two_candidates_returns_none():
    pbi = {
        ("c", "work one"): _pids("rp1", "rp2"),
        ("c", "work two"): _pids("rp1", "rp3"),
    }
    assert ev.match_unique(_pids("rp1", "rp2"), pbi) is None


def test_match_unique_threshold_requires_half():
    pbi = {("c", "w"): _pids("rp1")}
    # |E|=4 -> threshold 3; overlap of 1 is not enough
    assert ev.match_unique(_pids("rp1", "rx", "ry", "rz"), pbi) is None
    # threshold 1 met
    assert ev.match_unique(_pids("rp1"), pbi) == ("c", "w")


def test_match_unique_single_pid_evidence_is_acceptable():
    pbi = {("c", "w"): _pids("rp1", "rp9")}
    assert ev.match_unique(_pids("rp1"), pbi) == ("c", "w")


def test_match_unique_no_overlap_returns_none():
    pbi = {("c", "w"): _pids("rp7", "rp8")}
    assert ev.match_unique(_pids("rp1", "rp2"), pbi) is None


def test_match_unique_empty_evidence_returns_none():
    assert ev.match_unique(set(), {("c", "w"): _pids("rp1")}) is None


def test_match_unique_uniqueness_is_global_not_per_composer():
    pbi = {
        ("composer one", "same title"): _pids("rp1"),
        ("composer two", "same title"): _pids("rp1"),
    }
    assert ev.match_unique(_pids("rp1"), pbi) is None


# --- current_pids_by_identity ---------------------------------------------------

def test_current_pids_by_identity_groups_projected_rows(monkeypatch):
    # Two rows, same projected identity, distinct recording pids.
    rows8 = [
        ("T", "C", "C", "", "", "ep1", 0, ""),
        ("T", "C", "C", "", "", "ep2", 0, ""),
        ("T", "C", "C", "", "", "ep3", 1, ""),   # no projection entry
    ]
    projection = {("ep1", 0): "rpA", ("ep2", 0): "rpB"}
    rec_meta = {"rpA": ("Comp One", "Real Title"),
                "rpB": ("Comp One", "Real Title")}

    import ttn_analyze as ana

    def fake_identity(ep, pos, composer, cl, title, proj, meta):
        rp = proj.get((ep, pos))
        if rp is not None and rp in rec_meta:
            name, ttl = rec_meta[rp]
            return name, name, ttl
        return composer, cl, title

    monkeypatch.setattr(ana, "_project_identity", fake_identity)
    out = ev.current_pids_by_identity(rows8, projection, rec_meta)
    ck = ana.resolve_composer_alias(ana.canonical_key(ana.normalize_composer("Comp One")))
    wk = ana.resolve_work_alias(ana.work_title_key("Real Title", "Comp One"), "Comp One")
    assert out[(ck, wk)] == {"rpA", "rpB"}
