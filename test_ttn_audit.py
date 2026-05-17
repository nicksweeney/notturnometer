"""Tests for ttn_audit pure logic.

Run: uv run --with pytest pytest test_ttn_audit.py -v
"""
from ttn_audit import conflict, candidate_id, components, bridge_decomposition, OneOff, _performer_names, find_pairs


def test_conflict_on_different_part():
    assert conflict("Messiah, HWV 56 - Part 2", "Messiah, HWV 56 - Part 3")


def test_conflict_on_different_number():
    assert conflict("Hungarian Dance no 1 in G minor",
                    "Hungarian Dance no 5 in G minor")


def test_conflict_on_different_mode():
    assert conflict("Sonata in A minor, Op 23", "Sonata in A major, Op 23")


def test_no_conflict_on_pure_rephrasing():
    assert not conflict("Symphony No 8 in G major, Op 88, B.163",
                        "Symphony No. 8 in G major, Op. 88, B. 163")


def test_no_conflict_when_one_side_merely_omits_a_number():
    # one title is a subset of the other's numbers — not a conflict
    assert not conflict("Symphony No.1 in G minor",
                        "Symphony No.1 in G minor (Op.13)")


def test_conflict_on_different_volume():
    # "volume" must be read whole — not as "vol" with a captured "ume"
    assert conflict("Folksong Arrangements Volume 1",
                    "Folksong Arrangements Volume 2")


def test_candidate_id_is_8_hex_chars():
    cid = candidate_id("Title A", "Title B")
    assert len(cid) == 8
    assert all(c in "0123456789abcdef" for c in cid)


def test_candidate_id_order_independent():
    assert candidate_id("Title A", "Title B") == candidate_id("Title B",
                                                              "Title A")


def test_candidate_id_distinct_for_distinct_pairs():
    assert candidate_id("A", "B") != candidate_id("A", "C")


def test_candidate_id_value_is_pinned():
    # Pin the scheme: ids anchor a future decisions file, so a change to the
    # hashing must be a deliberate, test-breaking choice.
    assert candidate_id("Title A", "Title B") == "d75d4bfc"


def test_components_single_chain():
    assert components([("a", "b"), ("b", "c")]) == [{"a", "b", "c"}]


def test_components_two_separate():
    comps = sorted(components([("a", "b"), ("c", "d")]), key=min)
    assert comps == [{"a", "b"}, {"c", "d"}]


def test_components_empty():
    assert components([]) == []


def test_components_handles_repeated_pairs():
    # callers building pairs from DB queries can emit duplicates
    assert components([("a", "b"), ("a", "b")]) == [{"a", "b"}]


def test_clean_component_returns_none():
    members = {"Cantata BWV.43, Gott fahret auf mit Jauchzen",
               "Cantata - Gott fahret auf mit Jauchzen, BWV 43"}
    pairs = [tuple(sorted(members))]
    assert bridge_decomposition(members, pairs) is None


def test_cascade_bridge_is_detected_and_decomposed():
    # Two Part-I airings, two Part-II airings, and a bare no-part airing
    # that bridges them. The no-part title is the bridge; removing it
    # leaves a clean Part-I group and a clean Part-II group.
    a1 = "Elias, Op.70 - oratorio: Part I"
    a2 = "Elias, Op.70 - oratorio (Carus version): Part I"
    b1 = "Elias, Op.70 - oratorio: Part II"
    b2 = "Elias, Op.70 - oratorio (Carus version): Part II"
    z = "Elias, Op.70 - oratorio (Carus edition)"
    members = {a1, a2, b1, b2, z}
    pairs = [(a1, a2), (b1, b2), (a1, z), (a2, z), (b1, z), (b2, z)]
    decomp = bridge_decomposition(members, pairs)
    assert decomp is not None
    assert decomp["bridge"] == {z}
    assert {a1, a2} in decomp["subgroups"]
    assert {b1, b2} in decomp["subgroups"]
    assert decomp["orphans"] == {z}
    # the four Part I x Part II cross-pairs
    assert len(decomp["conflicts"]) == 4


def _oneoff(title, performers):
    return OneOff(title, performers, _performer_names(performers), "", "")


def test_performer_names_strips_roles_and_splits():
    names = _performer_names("Imogen Cooper (piano), Hallé, Mark Elder (conductor)")
    assert names == {"imogen cooper", "halle", "mark elder"}


def test_find_pairs_matches_same_work_same_performers():
    a = _oneoff("Nocturne in C sharp minor, Op 19 no 4",
                "Yuja Wang (piano)")
    b = _oneoff("Nocturne in C sharp minor, Op 19 no 4 (encore)",
                "Yuja Wang (piano)")
    assert find_pairs([a, b]) == [(a, b)]


def test_find_pairs_skips_different_performers():
    a = _oneoff("Nocturne in C sharp minor, Op 19 no 4",
                "Yuja Wang (piano)")
    b = _oneoff("Nocturne in C sharp minor, Op 19 no 4 (encore)",
                "Lang Lang (piano)")
    assert find_pairs([a, b]) == []


def test_find_pairs_skips_unrelated_works():
    a = _oneoff("Piano Sonata No 14 in C sharp minor", "Yuja Wang (piano)")
    b = _oneoff("Violin Concerto in D major", "Yuja Wang (piano)")
    assert find_pairs([a, b]) == []


def test_find_pairs_matches_by_catalogue_ref():
    # a shared catalogue ref collapses works regardless of title wording
    a = OneOff("Concerto in A minor", "Yuja Wang (piano)",
               frozenset({"yuja wang"}), "", "rv356")
    b = OneOff("Violin Concerto, RV 356", "Yuja Wang (piano)",
               frozenset({"yuja wang"}), "", "rv356")
    assert find_pairs([a, b]) == [(a, b)]


def test_performer_names_strips_unclosed_paren():
    # an unbalanced "(role" must not leak into the name token
    assert _performer_names("Patrick Demenga (cello") == {"patrick demenga"}


from ttn_audit import oneoffs_by_composer


def test_oneoffs_by_composer_keeps_only_single_play_works():
    # "Symphony No 5" is played twice (not a one-off); "Egmont Overture"
    # once (a one-off). Rows: (title, composer, performers, date).
    rows = [
        ("Symphony No 5 in C minor", "Beethoven", "Hallé", "2020-01-01"),
        ("Symphony No. 5 in C minor", "Beethoven", "Hallé", "2021-01-01"),
        ("Egmont Overture, Op 84", "Beethoven", "Hallé", "2022-01-01"),
    ]
    result = oneoffs_by_composer(rows)
    titles = {o.title for offs in result.values() for o in offs}
    assert "Egmont Overture, Op 84" in titles
    assert not any("Symphony" in t for t in titles)
