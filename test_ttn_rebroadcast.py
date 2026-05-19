"""Tests for ttn_rebroadcast pure logic.

Run: uv run --with pytest pytest test_ttn_rebroadcast.py -v
"""
import json

from ttn_audit import candidate_id

from ttn_rebroadcast import (parse_credit, CreditSig, credit_key, Unit,
                             build_units, rebroadcast_clusters, length_band,
                             cluster_length, representative_title, same_work,
                             collapse_multimovement, multiplay_candidates,
                             data_fingerprint, code_fingerprint,
                             write_cache, read_cache, tracks_fingerprint,
                             write_units_cache, read_units_cache,
                             _CODE_FINGERPRINT_FILES)


def test_parse_credit_buckets_by_role():
    # buckets keep the BBC's original spelling — credit_key folds them
    sig = parse_credit(
        "Midori (violin), Bundesjugendorchester, Patrick Lange (conductor)")
    assert sig.conductors == frozenset({"Patrick Lange"})
    assert sig.soloists == frozenset({"Midori"})
    assert sig.ensembles == frozenset({"Bundesjugendorchester"})
    assert sig.degraded is False


def test_parse_credit_bare_string_is_degraded():
    # no parenthetical anywhere -> every name to ensembles, degraded
    sig = parse_credit("Hallé, Mark Elder")
    assert sig.degraded is True
    assert sig.conductors == frozenset()
    assert sig.soloists == frozenset()
    assert sig.ensembles == frozenset({"Hallé", "Mark Elder"})


def test_parse_credit_ensemble_role_word():
    # a parenthetical naming an ensemble role buckets as ensemble
    sig = parse_credit("BBC Singers (choir), Sofi Jeannin (conductor)")
    assert sig.ensembles == frozenset({"BBC Singers"})
    assert sig.conductors == frozenset({"Sofi Jeannin"})
    assert sig.degraded is False


def test_parse_credit_empty_string():
    sig = parse_credit("")
    assert sig == CreditSig(frozenset(), frozenset(), frozenset(), True)


def test_parse_credit_tolerates_trailing_period_after_role():
    # the BBC sometimes ends the performers line with a full stop, leaving
    # a "." after the last "(role)" — the role must still be recognised,
    # not swallowed into a phantom ensemble
    sig = parse_credit("CBC Vancouver Orchestra, Mario Bernardi (conductor).")
    assert sig.conductors == frozenset({"Mario Bernardi"})
    assert sig.ensembles == frozenset({"CBC Vancouver Orchestra"})
    assert sig.degraded is False


def test_credit_key_flattens_all_roles():
    sig = parse_credit(
        "Midori (violin), Bundesjugendorchester, Patrick Lange (conductor)")
    assert credit_key(sig) == frozenset(
        {"midori", "bundesjugendorchester", "patrick lange"})


def test_parse_credit_keeps_casing_but_credit_key_folds():
    # the CreditSig buckets keep the original spelling (case + diacritics)
    # for display; credit_key folds them, so it stays a stable cluster key
    sig = parse_credit("Oslo Philharmonic, Klaus Mäkelä (conductor)")
    assert sig.ensembles == frozenset({"Oslo Philharmonic"})
    assert sig.conductors == frozenset({"Klaus Mäkelä"})
    assert credit_key(sig) == frozenset({"oslo philharmonic", "klaus makela"})


def test_credit_key_equal_across_role_parsing_differences():
    # same forces, one airing role-tagged, one airing bare -> same key
    tagged = parse_credit("Hallé, Mark Elder (conductor)")
    bare = parse_credit("Hallé, Mark Elder")
    assert credit_key(tagged) == credit_key(bare)


def test_build_units_one_per_track():
    rows = [
        ("Symphony No 5 in C minor", "Beethoven", "Hallé, Mark Elder (conductor)",
         "2020-01-01", "01:00 AM", 30),
        ("Egmont Overture, Op 84", "Beethoven", "Hallé, Mark Elder (conductor)",
         "2021-02-02", "02:00 AM", 9),
    ]
    units = build_units(rows)
    assert len(units) == 2
    u = units[0]
    assert u.composer_display == "Beethoven"
    assert u.date == "2020-01-01"
    assert u.length == 30
    assert u.credit_key == frozenset({"halle", "mark elder"})


def test_build_units_drops_tracks_with_no_composer():
    rows = [
        ("Some Work", "", "Hallé", "2020-01-01", "01:00 AM", 10),
        ("Real Work", "Brahms", "Hallé", "2020-01-02", "01:00 AM", 10),
    ]
    units = build_units(rows)
    assert [u.composer_display for u in units] == ["Brahms"]


def test_build_units_truncates_date_to_ten_chars():
    rows = [("W", "Brahms", "Hallé", "2020-01-01T23:30:00+00:00", "x", 5)]
    assert build_units(rows)[0].date == "2020-01-01"


def _unit(title, composer, performers, date, length=10):
    rows = [(title, composer, performers, date, "01:00 AM", length)]
    return build_units(rows)[0]


def test_rebroadcast_clusters_keeps_two_date_groups():
    a = _unit("Egmont Overture, Op 84", "Beethoven",
              "Hallé, Mark Elder (conductor)", "2020-01-01")
    b = _unit("Egmont Overture, Op 84", "Beethoven",
              "Hallé, Mark Elder (conductor)", "2021-06-06")
    clusters = rebroadcast_clusters([a, b])
    assert len(clusters) == 1
    assert {u.date for u in clusters[0]} == {"2020-01-01", "2021-06-06"}


def test_rebroadcast_clusters_drops_single_date():
    a = _unit("Egmont Overture, Op 84", "Beethoven", "Hallé", "2020-01-01")
    assert rebroadcast_clusters([a]) == []


def test_rebroadcast_clusters_splits_on_different_conductor():
    # same orchestra + work, different conductor -> two recordings, neither
    # on its own a rebroadcast (the warhorse false-positive defence)
    a = _unit("Symphony No 5", "Beethoven", "Hallé, Mark Elder (conductor)",
              "2020-01-01")
    b = _unit("Symphony No 5", "Beethoven", "Hallé, Simon Rattle (conductor)",
              "2021-01-01")
    assert rebroadcast_clusters([a, b]) == []


def test_rebroadcast_clusters_ignores_repeat_within_one_date():
    # two airings on the SAME date are not ">=2 distinct dates"
    a = _unit("Egmont Overture, Op 84", "Beethoven", "Hallé", "2020-01-01")
    b = _unit("Egmont Overture, Op 84", "Beethoven", "Hallé", "2020-01-01")
    assert rebroadcast_clusters([a, b]) == []


def test_length_band_thresholds():
    assert length_band(None) == "unknown"
    assert length_band(3) == "short"
    assert length_band(7) == "short"
    assert length_band(8) == "medium"
    assert length_band(20) == "medium"
    assert length_band(21) == "long"
    assert length_band(45) == "long"


def test_cluster_length_is_median_of_airings():
    a = _unit("W", "Brahms", "Hallé", "2020-01-01", length=10)
    b = _unit("W", "Brahms", "Hallé", "2021-01-01", length=14)
    c = _unit("W", "Brahms", "Hallé", "2022-01-01", length=12)
    assert cluster_length([a, b, c]) == 12


def test_cluster_length_none_when_all_missing():
    a = _unit("W", "Brahms", "Hallé", "2020-01-01", length=None)
    b = _unit("W", "Brahms", "Hallé", "2021-01-01", length=None)
    assert cluster_length([a, b]) is None


def test_representative_title_most_common_wins():
    units = [_unit("Egmont Overture", "Beethoven", "Hallé", "2020-01-01"),
             _unit("Egmont Overture", "Beethoven", "Hallé", "2021-01-01"),
             _unit("Overture: Egmont", "Beethoven", "Hallé", "2022-01-01")]
    assert representative_title(units) == "Egmont Overture"


def test_same_work_true_on_shared_catalogue():
    a = _unit("Concerto in A minor, RV 356", "Vivaldi", "Hallé", "2020-01-01")
    b = _unit("Violin Concerto, RV.356", "Vivaldi", "Hallé", "2021-01-01")
    assert same_work(a, b)


def test_same_work_true_on_high_token_overlap():
    a = _unit("Egmont Overture in F minor", "Beethoven", "Hallé", "2020-01-01")
    b = _unit("Overture Egmont in F minor", "Beethoven", "Hallé", "2021-01-01")
    assert same_work(a, b)


def test_same_work_false_on_unrelated_titles():
    a = _unit("Egmont Overture", "Beethoven", "Hallé", "2020-01-01")
    b = _unit("Violin Concerto in D major", "Beethoven", "Hallé", "2021-01-01")
    assert not same_work(a, b)


def test_same_work_false_on_numbered_set_disagreement():
    # Op 10 No 2 vs Op 10 No 3 — two distinct symphonies of one numbered
    # set. Title-token Jaccard is ~0.8 (everything but the digit is shared)
    # so Jaccard alone fuses them; the "No N" disagreement is the only
    # cue, and it must be respected. This is the failure pattern that
    # collapsed Abel's Op.10, Corelli's Op.1 and Durante's concerti into
    # one false-positive cluster each.
    a = _unit("Symphony in E flat major, Op 10 no 2", "Abel", "Hallé",
              "2020-01-01")
    b = _unit("Symphony in E flat major, Op 10 no 3", "Abel", "Hallé",
              "2021-01-01")
    assert not same_work(a, b)


def test_same_work_unaffected_by_asymmetric_no_locator():
    # one airing labels the work with a "No N", the other doesn't — that
    # is incomplete labelling of one work, not a numbered-set disagreement
    a = _unit("Symphony in A major, K.24", "Abel", "Hallé", "2020-01-01")
    b = _unit("Symphony in A major, K 24 (Op 10 No 6)", "Abel", "Hallé",
              "2021-01-01")
    assert same_work(a, b)


def test_same_work_false_on_mismatched_catalogue():
    a = _unit("Concerto, RV 356", "Vivaldi", "Hallé", "2020-01-01")
    b = _unit("Concerto, RV 999", "Vivaldi", "Hallé", "2021-01-01")
    assert not same_work(a, b)


def test_same_work_false_on_two_arias_sharing_opera_catalogue():
    # an opera shares ONE catalogue number across every aria; two
    # different arias must not fuse on the catalogue match alone — the
    # excerpt-locator gate, mirroring work_title_key's own
    a = _unit("Crude furie degli orridi abissi, from Serse HWV 40",
              "Handel", "Hallé", "2020-01-01")
    b = _unit("Se bramate d'amar, from Serse HWV 40", "Handel", "Hallé",
              "2021-01-01")
    assert not same_work(a, b)


def test_collapse_multimovement_merges_movements_of_one_work():
    # two movement-clusters of one symphony, same forces, same two nights
    m1a = _unit("Symphony No 5 in C minor - 1st movement", "Beethoven",
                "Hallé, Mark Elder (conductor)", "2020-01-01", length=15)
    m1b = _unit("Symphony No 5 in C minor - 1st movement", "Beethoven",
                "Hallé, Mark Elder (conductor)", "2021-01-01", length=15)
    m2a = _unit("Symphony No 5 in C minor - 2nd movement", "Beethoven",
                "Hallé, Mark Elder (conductor)", "2020-01-01", length=10)
    m2b = _unit("Symphony No 5 in C minor - 2nd movement", "Beethoven",
                "Hallé, Mark Elder (conductor)", "2021-01-01", length=10)
    clusters = rebroadcast_clusters([m1a, m1b, m2a, m2b])
    assert len(clusters) == 2          # Stage 1 sees two movement-keys
    entries = collapse_multimovement(clusters)
    assert len(entries) == 1           # collapsed into one display entry
    assert entries[0]["airings"] == 2
    assert entries[0]["length"] == 25  # 15 + 10 summed


def test_collapse_multimovement_keeps_distinct_works_separate():
    # two unrelated works by the same forces on the same nights stay apart
    a1 = _unit("Egmont Overture", "Beethoven",
               "Hallé, Mark Elder (conductor)", "2020-01-01", length=9)
    a2 = _unit("Egmont Overture", "Beethoven",
               "Hallé, Mark Elder (conductor)", "2021-01-01", length=9)
    b1 = _unit("Coriolan Overture", "Beethoven",
               "Hallé, Mark Elder (conductor)", "2020-01-01", length=8)
    b2 = _unit("Coriolan Overture", "Beethoven",
               "Hallé, Mark Elder (conductor)", "2021-01-01", length=8)
    clusters = rebroadcast_clusters([a1, a2, b1, b2])
    entries = collapse_multimovement(clusters)
    assert len(entries) == 2


def _raw_unit(work_key, title, catalogue, date_str):
    # a Unit built directly: same forces every time, explicit work_key
    # and catalogue, so Stage 2 grouping is tested without depending on
    # how work_title_key happens to key these particular titles.
    sig = CreditSig(frozenset(), frozenset(),
                    frozenset({"academy of ancient music"}), False)
    return Unit("handel", "Handel", work_key, title, sig,
                credit_key(sig), date_str, 8, catalogue)


def test_multiplay_candidates_finds_variant_titles():
    # one recording (same forces, same catalogue ref) under two work-keys
    a1 = _raw_unit("wk-solit", "Solitudini amate, HWV 202", "hwv202",
                   "2020-01-01")
    a2 = _raw_unit("wk-solit", "Solitudini amate, HWV 202", "hwv202",
                   "2021-01-01")
    b = _raw_unit("wk-solit-alex", "Solitudini amate from Alessandro",
                  "hwv202", "2022-01-01")
    cands = multiplay_candidates([a1, a2, b])
    assert len(cands) == 1
    assert sorted(cands[0]["work_keys"]) == ["wk-solit", "wk-solit-alex"]


def test_multiplay_candidates_skips_single_work_key():
    a = _raw_unit("wk-x", "Egmont Overture", "", "2020-01-01")
    b = _raw_unit("wk-x", "Egmont Overture", "", "2021-01-01")
    assert multiplay_candidates([a, b]) == []


def test_multiplay_candidates_suppresses_decided_pair():
    a = _raw_unit("wk-solit", "Solitudini amate, HWV 202", "hwv202",
                  "2020-01-01")
    b = _raw_unit("wk-alex", "Solitudini amate from Alessandro", "hwv202",
                  "2022-01-01")
    cid = candidate_id(a.title, b.title)
    assert multiplay_candidates([a, b], decided_ids=frozenset({cid})) == []


def test_data_fingerprint_is_deterministic_and_order_independent():
    units = [_unit("Egmont Overture", "Beethoven", "Hallé", "2020-01-01"),
             _unit("Coriolan Overture", "Beethoven", "Hallé", "2021-01-01")]
    assert data_fingerprint(units) == data_fingerprint(list(reversed(units)))


def test_data_fingerprint_ignores_length_and_date():
    # length and date are not multi-play inputs -> must not move the digest
    a = _unit("Egmont Overture", "Beethoven", "Hallé", "2020-01-01", length=9)
    b = _unit("Egmont Overture", "Beethoven", "Hallé", "2099-12-31", length=40)
    assert data_fingerprint([a]) == data_fingerprint([b])


def test_data_fingerprint_changes_on_a_relevant_field():
    a = _unit("Egmont Overture", "Beethoven", "Hallé", "2020-01-01")
    b = _unit("Coriolan Overture", "Beethoven", "Hallé", "2020-01-01")
    assert data_fingerprint([a]) != data_fingerprint([b])


def test_code_fingerprint_is_deterministic(tmp_path):
    for name in _CODE_FINGERPRINT_FILES:
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert code_fingerprint(str(tmp_path)) == code_fingerprint(str(tmp_path))


def test_code_fingerprint_changes_when_a_tracked_file_changes(tmp_path):
    for name in _CODE_FINGERPRINT_FILES:
        (tmp_path / name).write_text("original", encoding="utf-8")
    before = code_fingerprint(str(tmp_path))
    (tmp_path / "ttn_analyze.py").write_text("edited", encoding="utf-8")
    assert code_fingerprint(str(tmp_path)) != before


def test_code_fingerprint_changes_when_decisions_file_appears(tmp_path):
    # decisions file absent, then present -> digest must move
    for name in ("ttn_analyze.py", "ttn_rebroadcast.py", "ttn_audit.py"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    before = code_fingerprint(str(tmp_path))
    (tmp_path / "ttn_rebroadcast_decisions.json").write_text(
        "{}", encoding="utf-8")
    assert code_fingerprint(str(tmp_path)) != before


def test_write_cache_writes_keyed_json(tmp_path):
    path = str(tmp_path / "cache.json")
    cands = [{"work_keys": ["a", "b"], "titles": ["T1", "T2"],
              "pair_ids": ["id1"]}]
    write_cache(path, "DATAHASH", "CODEHASH", cands)
    payload = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert payload["data_hash"] == "DATAHASH"
    assert payload["code_hash"] == "CODEHASH"
    assert payload["candidates"] == cands
    assert "generated_at" in payload


def test_read_cache_returns_candidates_on_full_match(tmp_path):
    path = str(tmp_path / "cache.json")
    cands = [{"work_keys": ["a"], "titles": ["T"], "pair_ids": ["id"]}]
    write_cache(path, "DATAHASH", "CODEHASH", cands)
    assert read_cache(path, "DATAHASH", "CODEHASH") == cands


def test_read_cache_none_on_data_hash_mismatch(tmp_path):
    path = str(tmp_path / "cache.json")
    write_cache(path, "DATAHASH", "CODEHASH", [])
    assert read_cache(path, "STALEDATA", "CODEHASH") is None


def test_read_cache_none_on_code_hash_mismatch(tmp_path):
    path = str(tmp_path / "cache.json")
    write_cache(path, "DATAHASH", "CODEHASH", [])
    assert read_cache(path, "DATAHASH", "STALECODE") is None


def test_read_cache_none_when_file_missing(tmp_path):
    assert read_cache(str(tmp_path / "absent.json"), "D", "C") is None


def test_read_cache_none_on_corrupt_json(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json", encoding="utf-8")
    assert read_cache(str(path), "D", "C") is None


def test_tracks_fingerprint_is_deterministic():
    rows = [("Egmont", "Beethoven", "Hallé", "2020-01-01", "01:00 AM", 9)]
    assert tracks_fingerprint(rows) == tracks_fingerprint(list(rows))


def test_tracks_fingerprint_ignores_time_str():
    # build_units ignores the time_str column -> it must not move the digest
    a = [("Egmont", "Beethoven", "Hallé", "2020-01-01", "01:00 AM", 9)]
    b = [("Egmont", "Beethoven", "Hallé", "2020-01-01", "11:59 PM", 9)]
    assert tracks_fingerprint(a) == tracks_fingerprint(b)


def test_tracks_fingerprint_changes_on_a_consumed_field():
    a = [("Egmont", "Beethoven", "Hallé", "2020-01-01", "01:00 AM", 9)]
    b = [("Coriolan", "Beethoven", "Hallé", "2020-01-01", "01:00 AM", 9)]
    assert tracks_fingerprint(a) != tracks_fingerprint(b)


def test_units_cache_round_trips(tmp_path):
    # a Unit with soloist + ensemble + conductor, and a degraded (bare)
    # one — the round-trip must reconstruct credit and credit_key exactly
    path = str(tmp_path / "units.json")
    units = [_unit("Egmont Overture", "Beethoven",
                   "Midori (violin), Hallé, Mark Elder (conductor)",
                   "2020-01-01", length=9),
             _unit("Symphony No 5", "Beethoven", "Hallé", "2021-01-01")]
    write_units_cache(path, "TRACKS", "CODE", units)
    assert read_units_cache(path, "TRACKS", "CODE") == units


def test_read_units_cache_none_on_tracks_hash_mismatch(tmp_path):
    path = str(tmp_path / "units.json")
    write_units_cache(path, "TRACKS", "CODE", [])
    assert read_units_cache(path, "STALE", "CODE") is None


def test_read_units_cache_none_on_code_hash_mismatch(tmp_path):
    path = str(tmp_path / "units.json")
    write_units_cache(path, "TRACKS", "CODE", [])
    assert read_units_cache(path, "TRACKS", "STALE") is None


def test_read_units_cache_none_when_file_missing(tmp_path):
    assert read_units_cache(str(tmp_path / "absent.json"), "T", "C") is None


def test_read_units_cache_none_on_corrupt_json(tmp_path):
    path = tmp_path / "units.json"
    path.write_text("not json", encoding="utf-8")
    assert read_units_cache(str(path), "T", "C") is None
