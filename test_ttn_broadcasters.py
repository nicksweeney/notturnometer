import sqlite3
from ttn_broadcasters import (BroadcasterStat, rank_broadcasters, load_rows,
                              broadcaster_key, OTHER)
from ttn_ebu_codes import decode
from ttn_segment_meta import INTERSTITIAL_RECORDING_PIDS


def test_airings_count_and_sort_desc_named_record():
    rows = [("GBBBC","r1"), ("PLPR","r2"), ("GBBBC","r1"), ("GBBBC","r3"), ("PLPR","r2")]
    stats = rank_broadcasters(rows)
    assert isinstance(stats[0], BroadcasterStat)
    assert stats[0] == BroadcasterStat("GBBBC", 3, 2)   # r1,r1,r3 -> 3 airings, 2 recs
    assert stats[1] == BroadcasterStat("PLPR", 2, 1)


def test_unattributed_bucket_nulls_and_blanks_sorted_last():
    rows = [("GBBBC","r1"), (None,"r2"), ("","r3"), ("GBBBC","r4"), (None,"r5")]
    stats = rank_broadcasters(rows)
    assert stats[0] == BroadcasterStat("GBBBC", 2, 2)
    assert stats[-1] == BroadcasterStat("UNATTRIBUTED", 3, 3)  # NULL+'' merged, last
    keys = [s.key for s in stats]
    assert keys.count("UNATTRIBUTED") == 1


def test_rank_key_country_swap_aggregates():
    rows = [("DEWDR","r1"), ("CHSRF","r2"), ("CHRSI","r3"), ("DEWDR","r4")]
    stats = rank_broadcasters(rows, rank_key=lambda c: decode(c)[1])
    d = {s.key: s.airings for s in stats}
    assert d == {"DE": 2, "CH": 2}


def test_unattributed_excluded_from_rank_key():
    rows = [("", None), (None, None), ("DEWDR", "r1")]
    stats = rank_broadcasters(rows, rank_key=lambda c: decode(c)[1])
    assert {s.key for s in stats} == {"DE", "UNATTRIBUTED"}


def test_rank_counts_distinct_recordings():
    rows = [("GBBBC","r1"), ("GBBBC","r1"), ("GBBBC","r2"), ("PLPR","r3")]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    d = {s.key: (s.airings, s.recordings) for s in stats}
    assert d["GBBBC"] == (3, 2)
    assert d["PLPR"] == (1, 1)


def test_rank_null_recording_pid_counts_airing_not_recording():
    rows = [("GBBBC", None), ("GBBBC", "r1")]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    g = next(s for s in stats if s.key == "GBBBC")
    assert g.airings == 2 and g.recordings == 1


def _fixture_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript('''
        CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT);
        CREATE TABLE segment_events (
            id INTEGER PRIMARY KEY, episode_pid TEXT, composer_name TEXT,
            record_label TEXT, recording_pid TEXT);
        INSERT INTO episodes VALUES ('e1','2019-03-01T01:00:00Z'),
                                    ('e2','2016-05-01T01:00:00Z');
        INSERT INTO segment_events (episode_pid,composer_name,record_label,recording_pid) VALUES
            ('e1','Frederic Chopin','PLPR','r1'),
            ('e1','Edvard Grieg','NONRK','r2'),
            ('e1','Edvard Grieg',NULL,'r3'),
            ('e1','Darius Milhaud','GBBBC','p03hd05x'),
            ('e2','Antonin Dvorak','CZCR','r4');
    ''')
    return conn


def test_load_rows_all_excludes_interstitials():
    conn = _fixture_db()
    rows = load_rows(conn)
    assert ("GBBBC", "p03hd05x") not in rows       # interstitial dropped by default
    assert ("PLPR", "r1") in rows and ("NONRK", "r2") in rows
    assert (None, "r3") in rows and ("CZCR", "r4") in rows
    assert len(rows) == 4


def test_load_rows_keep_interstitials_override():
    conn = _fixture_db()
    assert ("GBBBC", "p03hd05x") in load_rows(conn, keep_interstitials=True)


def test_load_rows_date_filter():
    conn = _fixture_db()
    rows = load_rows(conn, after="2019-01-01")     # e2 (2016) excluded
    assert ("CZCR", "r4") not in rows
    assert ("PLPR", "r1") in rows


def test_load_rows_composer_filter_diacritic_insensitive():
    conn = _fixture_db()
    assert load_rows(conn, composer="chopin") == [("PLPR", "r1")]


def test_load_rows_year_filter():
    conn = _fixture_db()
    assert load_rows(conn, year="2016") == [("CZCR", "r4")]


def test_load_rows_before_includes_boundary_day():
    conn = _fixture_db()
    rows = load_rows(conn, after="2019-03-01", before="2019-03-01")
    assert ("PLPR", "r1") in rows and ("CZCR", "r4") not in rows


from ttn_broadcasters import render_report


def test_render_has_coverage_line_and_decoded_names():
    stats = rank_broadcasters([("PLPR","r1"), ("PLPR","r2"), ("NONRK","r3"), (None,None)])
    out = render_report(stats, scope_label="all")
    assert "Coverage:" in out
    assert "3 / 4" in out
    assert "UNATTRIBUTED: 1" in out
    assert "Polskie Radio" in out and "PLPR" in out
    assert "Poland" in out
    assert "66.7" in out


def test_render_unattributed_row_dash_pct():
    stats = rank_broadcasters([("PLPR","r1"), (None,None)])
    out = render_report(stats, scope_label="all")
    lines = [l for l in out.splitlines() if "UNATTRIBUTED" in l and "Coverage" not in l]
    assert lines and "—" in lines[0]


def test_render_coverage_and_pct_independent_of_top():
    stats = rank_broadcasters([("A","a1"),("A","a2"),("A","a3"),("B","b1"),("B","b2"),
                               ("C","c1"),(None,None)])  # attr=6, unattr=1
    full = render_report(stats, scope_label="all")
    trimmed = render_report(stats, scope_label="all", top=1)
    cov = lambda o: [l for l in o.splitlines() if l.startswith("Coverage:")][0]
    assert cov(full) == cov(trimmed)
    assert "6 / 7" in cov(trimmed)
    assert "50.0" in trimmed
    assert "UNATTRIBUTED" in trimmed
    body = [l for l in trimmed.splitlines() if l.startswith("   1 ") or l.startswith("   2 ")]
    assert len(body) == 1


from ttn_broadcasters import broadcaster_key, OTHER


def test_broadcaster_key_folds_variant_and_buckets_non_ebu():
    assert broadcaster_key("GBBBC") == "GBBBC"
    assert broadcaster_key("NLNLOS") == "NLNOS"
    assert broadcaster_key("Decca") == OTHER
    assert broadcaster_key("BBC recording") == OTHER


def test_rank_with_broadcaster_key_buckets_other_pinned_before_unattributed():
    rows = [("GBBBC","r1"), ("Decca","r2"), ("EMI","r3"), ("NLNLOS","r4"), ("NLNOS","r4"), (None,None)]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    d = {s.key: s.airings for s in stats}
    assert d["NLNOS"] == 2
    assert d["GBBBC"] == 1
    assert d[OTHER] == 2
    assert d["UNATTRIBUTED"] == 1
    keys = [s.key for s in stats]
    assert keys.index(OTHER) < keys.index("UNATTRIBUTED")
    assert keys.index(OTHER) == len(keys) - 2


def test_render_other_row_shows_pct_not_dash():
    rows = [("GBBBC","r1"), ("Decca","r2"), ("EMI","r3")]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    out = render_report(stats, scope_label="all")
    other_line = [l for l in out.splitlines() if "Other (non-EBU)" in l][0]
    assert "66.7" in other_line


def test_csv_other_row_not_fabricated_broadcaster(tmp_path):
    from ttn_broadcasters import write_csv
    rows = [("GBBBC","r1"), ("Decca","r2"), ("EMI","r3")]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    p = tmp_path / "x.csv"
    write_csv(stats, str(p))
    text = p.read_text()
    assert "OT,OT" not in text and ",OTHER," not in text
    assert "Other (non-EBU)" in text
    other = [l for l in text.splitlines() if "Other (non-EBU)" in l][0]
    assert other.startswith(",,")


def test_render_has_recordings_column():
    rows = [("PLPR","r1"), ("PLPR","r1"), ("PLPR","r2"), ("NONRK","r3")]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    out = render_report(stats, scope_label="all")
    assert "recs" in out                       # column header present
    plpr = [l for l in out.splitlines() if "PLPR" in l][0]
    # PLPR: 3 airings, 2 distinct recordings -> both numbers on the row
    assert "3" in plpr and "2" in plpr


def test_render_rest_of_ebu_row_when_top_truncates():
    # 6 EBU broadcasters; --top 2 hides 4 -> a summary row for the tail so the
    # listing doesn't read as complete (the OTHER/UNATTRIBUTED rows otherwise
    # make it look so).
    rows = ([("GBBBC", "g1")] * 10 + [("PLPR", "p1")] * 8
            + [("DEWDR", "d1")] * 6 + [("NONRK", "n1")] * 4
            + [("SESR", "s1")] * 2 + [("DKDR", "k1")] * 1)
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    out = render_report(stats, scope_label="all", top=2)
    rest = [l for l in out.splitlines() if "more EBU broadcasters" in l]
    assert rest, out
    assert "4 more EBU broadcasters" in rest[0]   # 6 total - 2 shown
    assert "13" in rest[0]                          # tail airings 6+4+2+1
    # no rest row when --top covers all of them
    assert "more EBU broadcasters" not in render_report(stats, scope_label="all", top=0)
    assert "more EBU broadcasters" not in render_report(stats, scope_label="all", top=99)


def test_csv_has_recordings_column(tmp_path):
    from ttn_broadcasters import write_csv
    rows = [("PLPR","r1"), ("PLPR","r1"), ("PLPR","r2")]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    p = tmp_path / "x.csv"
    write_csv(stats, str(p))
    header = p.read_text().splitlines()[0]
    assert "recordings" in header
    assert header.split(",") == ["rank","code","broadcaster","country_code",
                                 "country","airings","recordings","pct"]
    plpr = [l for l in p.read_text().splitlines() if l.startswith("1,")][0]
    assert plpr.split(",")[5] == "3" and plpr.split(",")[6] == "2"  # airings, recordings
