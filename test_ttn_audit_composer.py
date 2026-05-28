"""Tests for ttn_audit_composer — composer-deep-dive audit helper.

Tests are mostly unit-level: feed synthetic Group objects in, assert
the candidate detection produces expected clusters."""

import pytest

from ttn_audit_composer import (Candidate, Group, _catalogue_refs,
                                _op_number, _significant_tokens,
                                find_candidates)


def make_group(work_key, *titles):
    """Construct a Group from a list of titles (each appears once)."""
    g = Group(work_key)
    for t in titles:
        g.add(t)
    return g


# --- token / catalogue extraction -----------------------------------------

def test_significant_tokens_drops_form_words():
    # Form names and connectives are stopwords; only distinctive words remain.
    tokens = set(_significant_tokens("Piano Sonata No 12 in F major, K.332"))
    assert "k.332" not in tokens  # we strip catalogue refs elsewhere
    assert "sonata" not in tokens
    assert "piano" not in tokens
    assert "f" not in tokens  # single-char filter


def test_significant_tokens_keeps_named_titles():
    tokens = set(_significant_tokens("La Maja y el Ruisenor - from Goyescas"))
    assert "maja" in tokens
    assert "ruisenor" in tokens
    assert "goyescas" in tokens
    assert "la" not in tokens
    assert "from" not in tokens


def test_catalogue_refs_matches_common_systems():
    assert ("BWV", "1056") in _catalogue_refs("Keyboard Concerto BWV.1056")
    assert ("K", "332") in _catalogue_refs("Piano Sonata in F, K.332")
    assert ("D", "960") in _catalogue_refs("Piano Sonata, D 960")
    assert ("RV", "63") in _catalogue_refs("Trio sonata, RV.63 'La Folia'")
    assert ("HWV", "350") in _catalogue_refs("Water Music HWV.350")


def test_catalogue_refs_handles_alphanumeric_suffix():
    # K.299b (Mozart Les petits riens) keeps the letter suffix.
    assert ("K", "299b") in _catalogue_refs("Les petits riens K.299b")


def test_op_number_extracts_bare_op():
    assert _op_number("Symphony No 3 in F major, Op 90") == "90"
    assert _op_number("Sonata in B minor, Op.5") == "5"
    assert _op_number("Concerto in A minor, op. 16") == "16"
    assert _op_number("Symphony No 1") is None


# --- candidate detection --------------------------------------------------

def test_find_candidates_buckets_shared_op_number():
    # Two groups for the same Op should be flagged.
    g1 = make_group("a key 1", "Sonata in F, Op 99",
                    "Sonata for piano in F, Op 99")
    g2 = make_group("a key 2", "Sonata in F major Op 99 for piano",
                    "Sonata in F, Op 99 (1900)")
    g3 = make_group("a key 3", "Sonata in G, Op 100")  # different Op — alone
    g3.add("Sonata in G, Op 100")  # bump to ≥2 airings so it's eligible
    candidates = find_candidates({g.work_key: g for g in (g1, g2, g3)})
    assert any("Op 99" in c.reason and len(c.groups) == 2 for c in candidates)
    # Op 100 should NOT be a candidate (only one group).
    assert not any("Op 100" in c.reason for c in candidates)


def test_find_candidates_buckets_shared_catalogue_ref():
    g1 = make_group("k a", "Concerto in F minor, BWV.1056",
                    "Keyboard Concerto in F minor BWV.1056")
    g2 = make_group("k b", "Concerto for harpsichord BWV.1056",
                    "Concerto BWV.1056 in F minor")
    candidates = find_candidates({g.work_key: g for g in (g1, g2)})
    assert any("BWV.1056" in c.reason for c in candidates)


def test_find_candidates_clusters_token_overlap_transitively():
    # Four groups where each shares ≥3 tokens with the next form ONE
    # cluster of 4, not multiple pairs. Union-find pulls them together
    # even when not every pair has the threshold of shared tokens, as
    # long as the chain bridges them.
    g1 = make_group("k a", "Sample Track Alpha Bravo Charlie Delta",
                    "Sample Track Alpha Bravo Charlie Delta")
    g2 = make_group("k b", "Sample Track Alpha Bravo Charlie Echo",
                    "Sample Track Alpha Bravo Charlie Echo")
    g3 = make_group("k c", "Sample Track Bravo Charlie Echo Foxtrot",
                    "Sample Track Bravo Charlie Echo Foxtrot")
    g4 = make_group("k d", "Other Track Charlie Echo Foxtrot Golf",
                    "Other Track Charlie Echo Foxtrot Golf")
    candidates = find_candidates({g.work_key: g for g in (g1, g2, g3, g4)})
    token_clusters = [c for c in candidates
                       if c.reason.startswith("shared tokens")]
    # Pairs: (g1,g2)=alpha/bravo/charlie/track shared; (g2,g3)=bravo/charlie/echo/track;
    # (g3,g4)=charlie/echo/foxtrot/track. All bridged → one cluster of 4.
    assert len(token_clusters) == 1
    assert len(token_clusters[0].groups) == 4


def test_find_candidates_does_not_bridge_when_no_intermediate_overlap():
    # Two groups sharing nothing distinctive should NOT merge even via
    # the union-find — token overlap is the bridge.
    g1 = make_group("k a", "Apple Banana Cherry Donut",
                    "Apple Banana Cherry Donut")
    g2 = make_group("k b", "Xylophone Yellow Zebra Wallaby",
                    "Xylophone Yellow Zebra Wallaby")
    candidates = find_candidates({g.work_key: g for g in (g1, g2)})
    assert not any(c.reason.startswith("shared tokens") for c in candidates)


def test_find_candidates_does_not_pair_token_overlap_below_threshold():
    # Two groups sharing only 2 tokens are below the 3-token threshold.
    g1 = make_group("k a", "Piano Sonata in F major",
                    "Sonata for piano in F major")
    g2 = make_group("k b", "Piano Concerto in A major",
                    "Concerto for piano in A major")
    candidates = find_candidates({g.work_key: g for g in (g1, g2)})
    # "piano" and "major" are stopwords; only "f" and "a" remain (single-char
    # filtered out). No tokens shared, no candidate.
    assert not any(c.reason.startswith("shared tokens") for c in candidates)


def test_find_candidates_respects_min_per_group():
    # Group with only 1 airing should not become a candidate (default
    # min_per_group=2).
    g1 = make_group("k a", "Title One, Op 50")  # 1 airing
    g2 = make_group("k b", "Title Two, Op 50", "Title Two, Op 50")  # 2 airings
    candidates = find_candidates({g.work_key: g for g in (g1, g2)})
    # g1 below threshold; no Op 50 candidate even though Op is shared.
    assert not any("Op 50" in c.reason for c in candidates)


def test_find_candidates_skips_set_catalogue_when_op_shared():
    # No special-casing yet for set catalogues — the tool flags Op-shared
    # groups regardless, and the human decides. This documents that
    # behavior: even legitimate sibling pieces under one Op (e.g.,
    # Chopin's 24 Preludes Op 28 + individual preludes) come up as
    # candidates. Human triage is expected.
    g_whole = make_group("k a", "24 Preludes, Op 28")
    g_whole.add("24 Preludes, Op 28")
    g_excerpt = make_group(
        "k b", "Prelude no 15 in D flat, Op 28 'Raindrop'")
    g_excerpt.add("Prelude no 15 in D flat, Op 28 'Raindrop'")
    candidates = find_candidates(
        {g.work_key: g for g in (g_whole, g_excerpt)})
    assert any("Op 28" in c.reason for c in candidates), (
        "Op-sharing surfaces even when one is the whole set and the other "
        "is an excerpt — human triage is the gate, not the tool.")


def test_subset_detection_pairs_short_token_with_longer():
    # Janáček-Pohádka pattern: a bare-form group with only 1 significant
    # token IS the same work as a longer-titled group containing it.
    # The standard 3+-token rule misses this; subset detection catches it.
    g_short = make_group("k a", "Pohadka", "Pohadka")  # tokens: {pohadka}
    g_long = make_group("k b",
                        "Pohadka (Fairy Tale)",
                        "Pohadka (Fairy Tale)")  # tokens: {pohadka, fairy, tale}
    candidates = find_candidates({g.work_key: g for g in (g_short, g_long)})
    token_clusters = [c for c in candidates
                       if c.reason.startswith("shared tokens")]
    assert len(token_clusters) == 1
    assert len(token_clusters[0].groups) == 2


def test_subset_detection_skips_common_form_token():
    # "Cantata" alone in one group should NOT subset-bridge into a longer
    # title that also has "cantata" — the token is too common across the
    # composer's catalogue.
    groups = {}
    # Seed the catalogue with 10 distinct cantatas so "cantata" looks common.
    for i in range(10):
        g = make_group(f"cantata-{i}", f"Cantata No {i+1} Distinct{i}",
                       f"Cantata No {i+1} Distinct{i}")
        groups[g.work_key] = g
    # The lone "Cantata" group and one specific cantata both contain
    # the token "cantata"; subset detection should NOT pair them
    # because "cantata" is too common (appears in >5 groups).
    g_lone = make_group("k lone", "Cantata", "Cantata")
    g_specific = make_group("k spec", "Cantata No 1 Distinct0", "Cantata No 1 Distinct0")
    # Note: g_specific has the same work_key intent as cantata-0, so we
    # use a distinct token sequence to make the subset case clean. Drop
    # the original cantata-0 to avoid duplicate work_key.
    groups.pop("cantata-0")
    groups[g_lone.work_key] = g_lone
    groups[g_specific.work_key] = g_specific
    candidates = find_candidates(groups)
    # No token-cluster candidate should include the lone "Cantata" group.
    for c in candidates:
        if c.reason.startswith("shared tokens"):
            assert g_lone not in c.groups, (
                "Lone 'Cantata' should not bridge into specific cantatas — "
                "the token is too common across the composer's catalogue.")


def test_subset_detection_clusters_with_main_3plus_overlap_pair():
    # Composes pass 2a and 2b: a 3-group cluster where one pair has 3+
    # shared tokens (the main pass) and a third group has only 1 shared
    # token (subset case) should form ONE cluster of 3, not two pairs.
    g_full = make_group("k a", "Pohadka Fairy Tale Excerpt",
                        "Pohadka Fairy Tale Excerpt")
    g_long = make_group("k b", "Pohadka Fairy Tale 'Andante'",
                        "Pohadka Fairy Tale 'Andante'")
    g_short = make_group("k c", "Pohadka", "Pohadka")
    candidates = find_candidates(
        {g.work_key: g for g in (g_full, g_long, g_short)})
    token_clusters = [c for c in candidates
                       if c.reason.startswith("shared tokens")]
    assert len(token_clusters) == 1
    assert len(token_clusters[0].groups) == 3


def test_candidate_total_sums_group_counts():
    g1 = make_group("a", "X, Op 1", "X, Op 1", "X, Op 1")  # 3
    g2 = make_group("b", "Y, Op 1", "Y, Op 1")  # 2
    candidates = find_candidates({g.work_key: g for g in (g1, g2)})
    op_cands = [c for c in candidates if "Op 1" in c.reason]
    assert len(op_cands) == 1
    assert op_cands[0].total == 5
