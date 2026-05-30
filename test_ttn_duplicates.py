from ttn_duplicates import (_fingerprint, Group, build_groups, _jaccard,
                            _composer_rare_tokens, _is_excerpt_key,
                            _set_sibling, _excluded, _verdict)


def test_fingerprint_drops_form_words_keeps_numbers_and_nicknames():
    fp = _fingerprint("Symphony No. 103 in E flat, Hob. I:103 'Drumroll'")
    assert "103" in fp            # work number kept
    assert "drumroll" in fp       # nickname kept
    assert "symphony" not in fp   # form word dropped
    assert "flat" not in fp       # key word dropped
    assert "in" not in fp         # connective dropped


def test_fingerprint_keeps_single_digit_drops_single_letter():
    fp = _fingerprint("Symphony No 5 in C minor")
    assert "5" in fp
    assert "c" not in fp          # bare note letter dropped (len 1, non-digit)


def test_build_groups_groups_by_work_and_applies_composer_alias():
    rows = [
        # "Franz Joseph Haydn" folds to "joseph haydn" via COMPOSER_ALIASES,
        # so these two identical-work rows are ONE group...
        ("Franz Joseph Haydn", "Franz Joseph Haydn (1732-1809)",
         "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),
        ("Joseph Haydn", "Joseph Haydn",
         "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),
        # ...and a different work is a second group.
        ("Joseph Haydn", "Joseph Haydn",
         "Symphony No 92 in G major, Hob I:92 'Oxford'"),
    ]
    groups = build_groups(rows)
    assert len(groups) == 2
    assert all(g.composer == "joseph haydn" for g in groups)
    s103 = next(g for g in groups if "103" in g.display_title)
    assert s103.airings == 2


def test_jaccard():
    assert _jaccard(frozenset("ab"), frozenset("ab")) == 1.0
    assert _jaccard(frozenset("ab"), frozenset("cd")) == 0.0
    assert _jaccard(frozenset("abc"), frozenset("abd")) == 0.5  # 2/4


def _g(wk, disp, airings=2):
    return Group("c", "C", wk, disp, airings, _fingerprint(disp))


def test_composer_rare_tokens():
    groups = [_g("k1", "London Trio No 1"), _g("k2", "London Trio variant"),
              _g("k3", "Symphony No 1"), _g("k4", "Symphony No 2"),
              _g("k5", "Mass No 1")]
    rare = _composer_rare_tokens(groups, rare_max=2)
    assert "london" in rare      # 2 groups -> rare
    assert "1" not in rare        # 3 groups (London Trio/Symphony/Mass No 1) -> not rare


def test_is_excerpt_key():
    assert _is_excerpt_key("§bwv1009|sarabande")   # one pipe
    assert _is_excerpt_key("§k201|4")              # ordinal slug, still one pipe
    assert not _is_excerpt_key("§k516|516|gminor")  # whole, two pipes
    assert not _is_excerpt_key("103 drum roll symphony")  # token-sort


def test_set_sibling_differs_by_keysig_only():
    # same ref, different key sig -> siblings (distinct works)
    assert _set_sibling("§d899|1,899|cminor", "§d899|2,899|eflat")
    # same ref, SAME key sig, only number differs -> phantom straggler, NOT sibling
    assert not _set_sibling("§k516|4,516|gminor", "§k516|516|gminor")
    # different refs -> not handled here
    assert not _set_sibling("§k1|1|c", "§k2|2|c")


def test_excluded():
    assert _excluded("§bwv1009|sarabande", "§bwv1009|1009,3|c")  # excerpt vs whole
    assert _excluded("§d899|1,899|cminor", "§d899|2,899|eflat")  # siblings
    assert not _excluded("§k516|4,516|gminor", "§k516|516|gminor")  # straggler
    assert not _excluded("§hobi103|103|eflat", "103 drum roll h1103 symphony")


def test_verdict_base_and_boost():
    rare = {"london"}
    # high overlap -> base flag
    base_a = _g("k1", "Divertimento London Trio aka No 1")     # {london, aka, 1}
    base_b = _g("k2", "Divertimento London Trio No 1")         # {london, 1}
    flagged, reason = _verdict(base_a, base_b, rare, base=0.5, low=0.2)
    assert flagged and reason.startswith("base")               # J = 2/3
    # low overlap but shared rare token 'london' -> boost flag
    boost_a = _g("k3", "Divertimento aka London Trio No 1 Hob 4")        # {aka,london,1,hob,4}
    boost_b = _g("k4", "Divertimento 2 flutes London trio Hob 41")       # {2,flutes,london,hob,41}
    flagged, reason = _verdict(boost_a, boost_b, rare, base=0.5, low=0.2)
    assert flagged and reason.startswith("boost")              # J = 2/8 = 0.25 >= 0.2, shares london
    # disjoint, no shared rare -> not flagged
    none_a = _g("k5", "Mass C major")
    none_b = _g("k6", "Te Deum D major")
    flagged, _ = _verdict(none_a, none_b, rare, base=0.5, low=0.2)
    assert not flagged
