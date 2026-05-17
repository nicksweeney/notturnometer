"""Tests for ttn_audit pure logic.

Run: uv run --with pytest pytest test_ttn_audit.py -v
"""
from ttn_audit import conflict, candidate_id


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
