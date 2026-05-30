from ttn_duplicates import _fingerprint, Group, build_groups


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
