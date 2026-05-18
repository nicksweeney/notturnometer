"""Tests for ttn_rebroadcast pure logic.

Run: uv run --with pytest pytest test_ttn_rebroadcast.py -v
"""
from ttn_audit import candidate_id

from ttn_rebroadcast import parse_credit, CreditSig


def test_parse_credit_buckets_by_role():
    sig = parse_credit(
        "Midori (violin), Bundesjugendorchester, Patrick Lange (conductor)")
    assert sig.conductors == frozenset({"patrick lange"})
    assert sig.soloists == frozenset({"midori"})
    assert sig.ensembles == frozenset({"bundesjugendorchester"})
    assert sig.degraded is False


def test_parse_credit_bare_string_is_degraded():
    # no parenthetical anywhere -> every name to ensembles, degraded
    sig = parse_credit("Hallé, Mark Elder")
    assert sig.degraded is True
    assert sig.conductors == frozenset()
    assert sig.soloists == frozenset()
    assert sig.ensembles == frozenset({"halle", "mark elder"})


def test_parse_credit_ensemble_role_word():
    # a parenthetical naming an ensemble role buckets as ensemble
    sig = parse_credit("BBC Singers (choir), Sofi Jeannin (conductor)")
    assert sig.ensembles == frozenset({"bbc singers"})
    assert sig.conductors == frozenset({"sofi jeannin"})
    assert sig.degraded is False


def test_parse_credit_empty_string():
    sig = parse_credit("")
    assert sig == CreditSig(frozenset(), frozenset(), frozenset(), True)
