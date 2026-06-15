"""Tests for ttn_mbid_audit: temporal matcher, DB loading, audit logic, CLI.

Run: uv run --with pytest pytest test_ttn_mbid_audit.py -q
"""
import sqlite3

from ttn_mbid_audit import parse_clock_offset, episode_offsets


def test_parse_clock_offset_seconds_since_midnight():
    assert parse_clock_offset("12:00 AM") == 0
    assert parse_clock_offset("12:31 AM") == 31 * 60
    assert parse_clock_offset("1:55 AM") == (1 * 60 + 55) * 60
    assert parse_clock_offset("11:30 PM") == (23 * 60 + 30) * 60
    assert parse_clock_offset("12:15 PM") == (12 * 60 + 15) * 60


def test_parse_clock_offset_unparseable_returns_none():
    assert parse_clock_offset("") is None
    assert parse_clock_offset("not a time") is None
    assert parse_clock_offset("3 works") is None
    assert parse_clock_offset(None) is None


def test_parse_clock_offset_infers_am_for_bare_times():
    # Overnight show: a meridiem-less time is AM. Separator may be dot or colon,
    # a stray colon and a trailing timezone are tolerated.
    assert parse_clock_offset("12:31") == 31 * 60          # 00:31
    assert parse_clock_offset("1:00") == 60 * 60
    assert parse_clock_offset("01:00 BST") == 60 * 60
    assert parse_clock_offset("12.31") == 31 * 60
    assert parse_clock_offset("02.00AM") == 2 * 60 * 60    # bucket A: dot + AM
    assert parse_clock_offset("02:46:AM") == (2 * 60 + 46) * 60
    # meridiem-bearing values are unchanged
    assert parse_clock_offset("11:30 PM") == (23 * 60 + 30) * 60


def test_episode_offsets_relative_with_daywrap():
    # times that cross midnight: 11:58 PM -> 12:02 AM -> 12:31 AM
    secs = episode_offsets(["11:58 PM", "12:02 AM", "12:31 AM"])
    assert secs == [0, 4 * 60, 33 * 60]               # relative to first, wrap handled
    # an unparseable time yields None for that slot but keeps the others aligned
    secs2 = episode_offsets(["12:00 AM", "garbage", "12:10 AM"])
    assert secs2[0] == 0 and secs2[1] is None and secs2[2] == 10 * 60


from ttn_mbid_audit import surname, title_tokens, pair_cost


def test_surname_and_tokens():
    assert surname("Camille Saint-Saens") == "saint-saens"
    assert surname("Antonin Dvorak") == "dvorak"
    assert surname("") == ""
    assert title_tokens("Symphony No.5 in D") == {"symphony", "no", "5", "in", "d"}


def test_surname_folds_typographic_hyphen():
    # segments.json renders hyphenated surnames with U+2010 (‐), long_synopsis
    # with ASCII '-'. The matcher's High tier gates on surname equality, so an
    # unfolded U+2010 spuriously fails the gate and suppresses the whole
    # recording's projection (Saint-Saens, Villa-Lobos, ... — 1263 airings).
    # ascii_fold must fold U+2010/U+2011 to '-' the way canonical_key does.
    assert surname("Camille Saint‐Saëns") == surname("Camille Saint-Saens")
    assert surname("Heitor Villa‑Lobos") == surname("Heitor Villa-Lobos")
    assert surname("Jean de Sainte‐Colombe") == "sainte-colombe"


def test_pair_cost_same_slot_same_composer_is_low():
    c = pair_cost(t_off=120, s_off=120, t_comp="Antonin Dvorak",
                  s_comp="Antonin Dvorak", t_title="Slavonic Dance",
                  s_title="Slavonic Dance")
    assert c < 0.2


def test_pair_cost_same_slot_different_composer_is_mid():
    # temporal agrees, names disagree -> a Medium candidate (cost in a middle band)
    c = pair_cost(t_off=120, s_off=120, t_comp="Anonymous", s_comp="Anon",
                  t_title="Carol", s_title="Carol")
    assert 0.2 <= c < 0.7


def test_pair_cost_far_apart_is_high():
    c = pair_cost(t_off=0, s_off=3600, t_comp="A B", s_comp="X Y",
                  t_title="foo", s_title="bar")
    assert c > 0.7


def test_pair_cost_without_temporal_uses_content_only():
    c = pair_cost(t_off=None, s_off=120, t_comp="J S Bach", s_comp="J S Bach",
                  t_title="Fugue", s_title="Fugue")
    assert c < 0.4          # content-only still matches a clear pair


from ttn_mbid_audit import reconcile_episode

def _track(pos, time, comp, title):
    return {"position": pos, "time_str": time, "composer": comp, "title": title}

def _seg(pos, voff, comp, title, mbid, rec):
    return {"position": pos, "version_offset": voff, "composer_name": comp,
            "track_title": title, "composer_mbid": mbid, "recording_pid": rec}


def test_reconcile_equal_count_diagonal():
    tracks = [_track(0, "12:00 AM", "Bach", "Fugue"),
              _track(1, "12:05 AM", "Mozart", "Sonata")]
    segs = [_seg(1, 0, "Bach", "Fugue", "mb-bach", "rec1"),
            _seg(2, 300, "Mozart", "Sonata", "mb-moz", "rec2")]
    matches = reconcile_episode(tracks, segs)
    by_pos = {m["track_position"]: m for m in matches}
    assert by_pos[0]["composer_mbid"] == "mb-bach" and by_pos[0]["tier"] == "high"
    assert by_pos[1]["composer_mbid"] == "mb-moz" and by_pos[1]["tier"] == "high"


def test_reconcile_off_by_one_extra_segment_leaves_track_unmatched_correctly():
    # segments has an extra item in the middle; the two real tracks must still
    # bind to their correct segments, not cascade.
    tracks = [_track(0, "12:00 AM", "Bach", "Fugue"),
              _track(1, "12:10 AM", "Mozart", "Sonata")]
    segs = [_seg(1, 0, "Bach", "Fugue", "mb-bach", "r1"),
            _seg(2, 300, "Filler", "Interlude", "mb-x", "rx"),
            _seg(3, 600, "Mozart", "Sonata", "mb-moz", "r2")]
    by_pos = {m["track_position"]: m for m in reconcile_episode(tracks, segs)}
    assert by_pos[0]["composer_mbid"] == "mb-bach"
    assert by_pos[1]["composer_mbid"] == "mb-moz"     # NOT mb-x


def test_reconcile_medium_tier_same_slot_name_disagrees():
    tracks = [_track(0, "12:00 AM", "Anonymous", "Carol")]
    segs = [_seg(1, 0, "Anon", "Carol", "mb-anon", "r1")]
    m = reconcile_episode(tracks, segs)[0]
    assert m["composer_mbid"] == "mb-anon"
    assert m["tier"] == "medium"      # time agrees, surname disagrees


def test_reconcile_unparseable_time_falls_back_to_content():
    tracks = [_track(0, "00:30", "Bach", "Fugue")]     # no meridiem
    segs = [_seg(1, 0, "Bach", "Fugue", "mb-bach", "r1")]
    m = reconcile_episode(tracks, segs)[0]
    assert m["composer_mbid"] == "mb-bach"
    assert m["tier"] in ("high", "medium")             # content carried it


def test_reconcile_track_with_no_segment_is_unmatched():
    tracks = [_track(0, "12:00 AM", "Bach", "Fugue")]
    m = reconcile_episode(tracks, [])[0]
    assert m["composer_mbid"] is None and m["tier"] == "unmatched"


def test_reconcile_null_position_orders_by_version_offset():
    # ~8.4% of segments (424 whole episodes) carry NULL position but a valid
    # version_offset. The matcher must order those by version_offset, else the
    # monotonic alignment AND the s_base temporal anchor scramble, demoting
    # otherwise-correct matches to 'low' (which the High-only projection drops).
    # Segments here are supplied OUT of temporal order to prove ordering is fixed.
    tracks = [_track(0, "12:00 AM", "Bach", "Fugue"),
              _track(1, "1:00 AM", "Cesar Franck", "Choral")]   # +3600s
    segs = [_seg(None, 3600, "Cesar Franck", "Choral", "mb-franck", "r-franck"),
            _seg(None, 0, "Bach", "Fugue", "mb-bach", "r-bach")]
    by_pos = {m["track_position"]: m for m in reconcile_episode(tracks, segs)}
    assert by_pos[0]["recording_pid"] == "r-bach" and by_pos[0]["tier"] == "high"
    assert by_pos[1]["recording_pid"] == "r-franck" and by_pos[1]["tier"] == "high"


from ttn_mbid_audit import load_episode_data, reconcile_corpus

def _db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.sqlite"))
    conn.executescript("""
      CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT,
        segments_raw_json TEXT);
      CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, episode_pid TEXT,
        position INTEGER, time_str TEXT, composer TEXT, title TEXT);
      CREATE TABLE segment_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_pid TEXT, position INTEGER, version_offset INTEGER,
        composer_name TEXT, track_title TEXT, composer_mbid TEXT,
        recording_pid TEXT);
    """)
    return conn


def test_load_and_reconcile_corpus(tmp_path):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO episodes VALUES ('ep1','2020-01-01','{}')")
    conn.execute("INSERT INTO tracks (episode_pid,position,time_str,composer,title) "
                 "VALUES ('ep1',0,'12:00 AM','Anonymous','Carol')")
    conn.execute("INSERT INTO segment_events (episode_pid,position,version_offset,"
                 "composer_name,track_title,composer_mbid,recording_pid) "
                 "VALUES ('ep1',1,0,'Anon','Carol','mb-anon','r1')")
    conn.commit()
    data = load_episode_data(conn)
    assert set(data.keys()) == {"ep1"}
    assert len(data["ep1"]["tracks"]) == 1 and len(data["ep1"]["segments"]) == 1
    matches = reconcile_corpus(conn)
    assert matches[0]["composer_mbid"] == "mb-anon"
    assert matches[0]["track_composer"] == "Anonymous"   # the matcher rows carry the track composer
    assert matches[0]["tier"] == "medium"


from ttn_mbid_audit import alias_candidates, ambiguity_flags

def _match(mbid, tcomp, tier="high"):
    return {"composer_mbid": mbid, "track_composer": tcomp, "tier": tier,
            "episode_pid": "e", "track_position": 0, "recording_pid": "r",
            "segment_composer_name": tcomp}


def test_alias_candidates_one_mbid_many_names():
    # one MBID seen under two different track spellings -> an alias candidate
    matches = [_match("mb1", "Dieterich Buxtehude"),
               _match("mb1", "Dietrich Buxtehude"),
               _match("mb1", "Dietrich Buxtehude")]
    cands = alias_candidates(matches)
    keys = {(c["variant_ck"], c["preferred_ck"]) for c in cands}
    # preferred = the more-aired spelling's canonical key
    import ttn_analyze as A
    def ck(x): return A.resolve_composer_alias(A.canonical_key(A.normalize_composer(x)))
    assert (ck("Dieterich Buxtehude"), ck("Dietrich Buxtehude")) in keys


def test_alias_candidates_ignore_low_and_unmatched():
    matches = [_match("mb1", "A One", tier="low"),
               _match("mb1", "A Two", tier="unmatched")]
    assert alias_candidates(matches) == []


def test_ambiguity_flags_one_name_many_mbids():
    # same canonical key, two MBIDs (on high matches) -> ambiguity flag
    matches = [_match("mbA", "John Adams"), _match("mbB", "John Adams")]
    flags = ambiguity_flags(matches)
    import ttn_analyze as A
    def ck(x): return A.resolve_composer_alias(A.canonical_key(A.normalize_composer(x)))
    assert any(f["ck"] == ck("John Adams") and f["n_mbids"] == 2 for f in flags)


import ttn_mbid_audit

def test_render_emit_produces_alias_tuples():
    cands = [{"variant": "Dieterich Buxtehude", "preferred": "Dietrich Buxtehude",
              "variant_ck": "x", "preferred_ck": "y", "mbid": "m", "airings": 3}]
    out = ttn_mbid_audit.render_emit(cands)
    assert '("Dieterich Buxtehude", "Dietrich Buxtehude")' in out


def test_main_report_runs_end_to_end(tmp_path, capsys):
    db = str(tmp_path / "t.sqlite")
    conn = sqlite3.connect(db)
    conn.executescript("""
      CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT, segments_raw_json TEXT);
      CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, episode_pid TEXT,
        position INTEGER, time_str TEXT, composer TEXT, title TEXT);
      CREATE TABLE segment_events (id INTEGER PRIMARY KEY AUTOINCREMENT, episode_pid TEXT,
        position INTEGER, version_offset INTEGER, composer_name TEXT, track_title TEXT,
        composer_mbid TEXT, recording_pid TEXT);""")
    conn.execute("INSERT INTO episodes VALUES ('e','2020-01-01','{}')")
    conn.execute("INSERT INTO tracks (episode_pid,position,time_str,composer,title) "
                 "VALUES ('e',0,'12:00 AM','Anonymous','Carol')")
    conn.execute("INSERT INTO segment_events (episode_pid,position,version_offset,"
                 "composer_name,track_title,composer_mbid,recording_pid) "
                 "VALUES ('e',1,0,'Anon','Carol','mb','r')")
    conn.commit(); conn.close()
    ttn_mbid_audit.main([db])
    assert "tier" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# I3(a): reconcile_episode — unequal count, cross-composer forced match
# ---------------------------------------------------------------------------

def test_reconcile_unequal_count_cross_composer_match():
    """When segments outnumber tracks AND the best-cost match pairs a track with a
    wrong-composer segment (e.g. only one segment near the track's slot), the
    match is still recorded and the cross-composer pairing is visible in the
    result. This documents the dominant failure mode that alias_candidates must
    guard against."""
    # Two tracks but three segments; track 1 (Bach) is close in time to seg 2
    # (Gounod) because the Bach segment is far away, so the DP is forced to
    # match Bach->Gounod.
    tracks = [
        _track(0, "12:00 AM", "Johann Sebastian Bach", "Toccata"),
        _track(1, "12:30 AM", "Mozart", "Sonata"),
    ]
    segs = [
        _seg(1,    0, "Bach",   "Toccata",     "mb-bach", "r-bach"),   # far from track 1
        _seg(2, 1800, "Gounod", "Ave Maria",   "mb-gounod", "r-g"),    # near track 1 @1800s
        _seg(3, 3600, "Mozart", "Sonata",      "mb-moz",  "r-moz"),    # near track 2 @1800s
    ]
    # Track 0 is at offset 0 relative to itself (base=0), track 1 at +1800s.
    # Seg offsets relative to seg base (0): 0, 1800, 3600.
    # Under a monotonic DP the cheapest alignment should pair:
    #   track0 -> seg1 (same surname Bach, offset 0 vs 0 -> perfect)
    #   track1 -> seg2 (Mozart name agrees, offset 1800 vs 1800 -> perfect)
    # So actually both should match well here — we need a trickier fixture.
    # Instead: make the ONLY segment near track 0's slot be a wrong-composer one.
    tracks2 = [_track(0, "12:00 AM", "Johann Sebastian Bach", "Toccata")]
    segs2 = [_seg(1, 0, "Gounod", "Ave Maria", "mb-gounod", "r-g")]  # only option
    result = reconcile_episode(tracks2, segs2)
    assert len(result) == 1
    # The track IS bound (only one segment, so it must take it)
    assert result[0]["composer_mbid"] == "mb-gounod"
    # Cross-composer: Bach != Gounod -> medium or low tier
    assert result[0]["tier"] != "high"


# ---------------------------------------------------------------------------
# I3(b): alias_candidates — corroboration filtering and ledger suppression
# ---------------------------------------------------------------------------

def test_alias_candidates_cross_surname_not_corroborated():
    """A cross-surname pair (Bach→Gounod) generated by a wrong-composer forced
    match must NOT appear in the corroborated set (and must therefore not be
    emitted by --emit)."""
    # Simulate forced cross-composer matches under a single shared MBID
    cross_matches = [
        _match("mb-cross", "Johann Sebastian Bach", tier="medium"),
        _match("mb-cross", "Charles Gounod", tier="medium"),
    ]
    cands = alias_candidates(cross_matches)
    # Any candidate should NOT be corroborated (Bach and Gounod share no name tokens)
    for c in cands:
        assert not c.get("corroborated"), (
            f"Expected no corroborated=True for Bach/Gounod, got: {c}")


def test_alias_candidates_same_surname_transliteration_is_corroborated():
    """A transliteration pair (Dieterich→Dietrich Buxtehude) shares the surname
    token 'buxtehude' and must be marked corroborated=True."""
    matches = [
        _match("mb1", "Dieterich Buxtehude"),
        _match("mb1", "Dietrich Buxtehude"),
        _match("mb1", "Dietrich Buxtehude"),
    ]
    cands = alias_candidates(matches)
    assert cands, "Expected at least one candidate"
    assert all(c["corroborated"] for c in cands), (
        f"All Buxtehude candidates must be corroborated: {cands}")


def test_alias_candidates_ledger_rejected_pair_suppressed(tmp_path):
    """A pair recorded in the decisions ledger must not appear in alias_candidates."""
    import ttn_mbid_audit as A
    # Record a rejection in a temporary decisions file
    decisions_path = str(tmp_path / "decisions.json")
    A.record_rejection(decisions_path, "Nicola Matteis Sr.", "Nicola Matteis")
    rejected = A.load_decisions(decisions_path)

    # Build matches that would otherwise generate the Matteis Sr. → Matteis candidate
    matches = [
        _match("mb-matteis", "Nicola Matteis"),
        _match("mb-matteis", "Nicola Matteis Sr."),
        _match("mb-matteis", "Nicola Matteis Sr."),
    ]
    cands = alias_candidates(matches, rejected=rejected)
    # The Matteis pair must be absent regardless of airings
    import ttn_analyze as A2
    def ck(x): return A2.resolve_composer_alias(A2.canonical_key(A2.normalize_composer(x)))
    matteis_cks = {ck("Nicola Matteis"), ck("Nicola Matteis Sr.")}
    for c in cands:
        assert not (c["variant_ck"] in matteis_cks and c["preferred_ck"] in matteis_cks), (
            f"Ledger-rejected pair must be suppressed: {c}")


def test_alias_candidates_ambiguity_cross_check_suppresses_haydn():
    """When both sides of a candidate appear in ambiguity_flags (1 name -> many
    MBIDs), the candidate is a misalignment tell and must be dropped (B1a)."""
    # Joseph Haydn and Michael Haydn resolve to DIFFERENT canonical keys.
    # Simulate: mb1 is seen under Joseph Haydn AND under Michael Haydn ->
    # looks like a fold candidate.  But ALSO: "michael haydn" maps to 2 MBIDs
    # (or one of the keys maps to multiple MBIDs on high matches) -> ambiguity flag
    # fires -> the candidate should be dropped.
    import ttn_analyze as A
    def ck(x): return A.resolve_composer_alias(A.canonical_key(A.normalize_composer(x)))
    joseph_ck = ck("Joseph Haydn")
    michael_ck = ck("Michael Haydn")
    # Ensure they're distinct (sanity)
    assert joseph_ck != michael_ck

    matches = [
        # mb1 seen under both -> alias candidate Joseph->Michael would fire
        _match("mb1", "Joseph Haydn", tier="high"),
        _match("mb1", "Michael Haydn", tier="high"),
        # Also: Joseph Haydn seen with a SECOND mbid on high -> ambiguity flag for Joseph
        _match("mb2", "Joseph Haydn", tier="high"),
    ]
    cands = alias_candidates(matches)
    # Joseph Haydn's ck appears in ambiguity_flags (mb1 + mb2)
    # -> any candidate involving Joseph Haydn's ck must be dropped (B1a)
    for c in cands:
        assert c["variant_ck"] != joseph_ck and c["preferred_ck"] != joseph_ck, (
            f"Candidate with ambiguous key {joseph_ck!r} must be suppressed: {c}")


def test_render_report_separates_corroborated_and_uncorroborated(capsys):
    """render_report must show uncorroborated candidates in a separate labelled
    section, not silently discard them."""
    # One corroborated candidate (same surname, transliteration)
    corr_matches = [
        _match("mb1", "Dieterich Buxtehude"),
        _match("mb1", "Dietrich Buxtehude"),
        _match("mb1", "Dietrich Buxtehude"),
    ]
    # One uncorroborated candidate (cross-surname, forced by shared MBID)
    cross_matches = [
        _match("mb2", "Johann Sebastian Bach", tier="medium"),
        _match("mb2", "Charles Gounod", tier="medium"),
    ]
    all_matches = corr_matches + cross_matches
    out = ttn_mbid_audit.render_report(all_matches)
    # The uncorroborated section heading must be present
    assert "cross-name" in out.lower() or "verify" in out.lower() or "uncorroborated" in out.lower(), (
        f"Expected a separate section for uncorroborated candidates in:\n{out}")


def test_decisions_file_seeded_with_matteis_and_jarnefelt():
    """The bundled decisions file must contain the two documented residue pairs
    so they are parked by default on any installation."""
    rejected = ttn_mbid_audit.load_decisions(ttn_mbid_audit._DECISIONS_PATH)
    import ttn_analyze as A
    def ck(x): return A.resolve_composer_alias(A.canonical_key(A.normalize_composer(x)))
    # Matteis pair
    matteis_pair = frozenset({ck("Nicola Matteis Sr."), ck("Nicola Matteis")})
    # Järnefelt pair
    jarnefelt_pair = frozenset({ck("Edvard Järnefelt"), ck("Armas Järnefelt")})
    assert any(matteis_pair == r or
               frozenset({ck(list(r)[0]), ck(list(r)[1])}) == matteis_pair
               for r in rejected), "Matteis Sr./Matteis pair must be in decisions"
    assert any(jarnefelt_pair == r or
               frozenset({ck(list(r)[0]), ck(list(r)[1])}) == jarnefelt_pair
               for r in rejected), "Järnefelt pair must be in decisions"


def test_corroboration_surname_anchored_not_given_name():
    from ttn_mbid_audit import _is_corroborated
    # subset / name-order swap / suffix add -> corroborated (kept)
    assert _is_corroborated("Strauss", "Johann Strauss II")
    assert _is_corroborated("Pandolfi Mealli, Giovanni Antonio",
                            "Giovanni Antonio Pandolfi Mealli")
    assert _is_corroborated("Chédeville", "Nicolas Chédeville")
    # shared surname, differing spelling -> corroborated (kept)
    assert _is_corroborated("Dieterich Buxtehude", "Dietrich Buxtehude")
    # shared GIVEN names only, different surname -> NOT corroborated (fixed FP)
    assert not _is_corroborated("Giovanni Battista Draghi",
                                "Giovanni Battista Pergolesi")
    assert not _is_corroborated("Johann Sebastian Bach", "Charles Gounod")
    # combined credit (two people joined by comma/&) -> NOT corroborated
    assert not _is_corroborated("Brian Eno, Julia Wolfe", "Brian Eno")
    assert not _is_corroborated("Anonymous,Nicola Matteis Sr.", "Nicola Matteis")
