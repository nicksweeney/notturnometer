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
    assert parse_clock_offset("00:30") is None        # no meridiem (quirk episode)
    assert parse_clock_offset(None) is None


def test_episode_offsets_relative_with_daywrap():
    # times that cross midnight: 11:58 PM -> 12:02 AM -> 12:31 AM
    secs = episode_offsets(["11:58 PM", "12:02 AM", "12:31 AM"])
    assert secs == [0, 4 * 60, 33 * 60]               # relative to first, wrap handled
    # an unparseable time yields None for that slot but keeps the others aligned
    secs2 = episode_offsets(["12:00 AM", "garbage", "12:10 AM"])
    assert secs2[0] == 0 and secs2[1] is None and secs2[2] == 10 * 60


from ttn_mbid_audit import surname, title_tokens, pair_cost, _NO_TEMPORAL


def test_surname_and_tokens():
    assert surname("Camille Saint-Saens") == "saint-saens"
    assert surname("Antonin Dvorak") == "dvorak"
    assert surname("") == ""
    assert title_tokens("Symphony No.5 in D") == {"symphony", "no", "5", "in", "d"}


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
