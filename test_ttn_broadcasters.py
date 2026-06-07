import sqlite3
from ttn_broadcasters import BroadcasterStat, rank_broadcasters, load_rows
from ttn_ebu_codes import decode


def test_airings_count_and_sort_desc_named_record():
    rows = ["GBBBC", "PLPR", "GBBBC", "GBBBC", "PLPR"]
    stats = rank_broadcasters(rows)
    assert isinstance(stats[0], BroadcasterStat)
    assert stats[0] == BroadcasterStat("GBBBC", 3)
    assert stats[1] == BroadcasterStat("PLPR", 2)


def test_unattributed_bucket_nulls_and_blanks_sorted_last():
    rows = ["GBBBC", None, "", "GBBBC", None]
    stats = rank_broadcasters(rows)
    assert stats[0] == BroadcasterStat("GBBBC", 2)
    assert stats[-1] == BroadcasterStat("UNATTRIBUTED", 3)  # NULL+'' merged, last
    keys = [s.key for s in stats]
    assert keys.count("UNATTRIBUTED") == 1


def test_rank_key_country_swap_aggregates():
    rows = ["DEWDR", "CHSRF", "CHRSI", "DEWDR"]   # 2x DE, 2x CH
    stats = rank_broadcasters(rows, rank_key=lambda c: decode(c)[1])
    d = {s.key: s.airings for s in stats}
    assert d == {"DE": 2, "CH": 2}


def test_unattributed_excluded_from_rank_key():
    # empty labels must not be passed to rank_key (would KeyError/garbage)
    rows = ["", None, "DEWDR"]
    stats = rank_broadcasters(rows, rank_key=lambda c: decode(c)[1])
    assert {s.key for s in stats} == {"DE", "UNATTRIBUTED"}


def _fixture_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript('''
        CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT);
        CREATE TABLE segment_events (
            id INTEGER PRIMARY KEY, episode_pid TEXT, composer_name TEXT,
            record_label TEXT);
        INSERT INTO episodes VALUES ('e1','2019-03-01T01:00:00Z'),
                                    ('e2','2016-05-01T01:00:00Z');
        INSERT INTO segment_events (episode_pid,composer_name,record_label) VALUES
            ('e1','Frederic Chopin','PLPR'),
            ('e1','Edvard Grieg','NONRK'),
            ('e1','Edvard Grieg',NULL),
            ('e2','Antonin Dvorak','CZCR');
    ''')
    return conn


def test_load_rows_all():
    conn = _fixture_db()
    assert sorted(r or '' for r in load_rows(conn)) == ['', 'CZCR', 'NONRK', 'PLPR']


def test_load_rows_date_filter():
    conn = _fixture_db()
    rows = load_rows(conn, after="2019-01-01")
    assert sorted(r or '' for r in rows) == ['', 'NONRK', 'PLPR']  # e2 excluded


def test_load_rows_composer_filter_diacritic_insensitive():
    conn = _fixture_db()
    # 'Frederic' must match 'Frédéric' too via ascii_fold; here input is ascii.
    assert load_rows(conn, composer="chopin") == ['PLPR']


def test_load_rows_year_filter():
    conn = _fixture_db()
    assert sorted(load_rows(conn, year="2016")) == ['CZCR']


def test_load_rows_before_includes_boundary_day():
    # broadcast_date carries a time suffix ('2019-03-01T01:00:00Z'); --before
    # must compare on the date part, so a same-day --before keeps that day
    # (regression for the full-timestamp-vs-bare-date boundary bug).
    conn = _fixture_db()
    rows = load_rows(conn, after="2019-03-01", before="2019-03-01")
    assert sorted(r or '' for r in rows) == ['', 'NONRK', 'PLPR']  # all of e1, e2 excluded


from ttn_broadcasters import render_report


def test_render_has_coverage_line_and_decoded_names():
    stats = rank_broadcasters(["PLPR", "PLPR", "NONRK", None])
    out = render_report(stats, scope_label="all")
    assert "Coverage:" in out
    assert "3 / 4" in out            # attributed / total
    assert "UNATTRIBUTED: 1" in out
    assert "Polskie Radio" in out and "PLPR" in out
    assert "Poland" in out
    # pct of attributed: PLPR 2/3 = 66.7
    assert "66.7" in out


def test_render_unattributed_row_dash_pct():
    stats = rank_broadcasters(["PLPR", None])
    out = render_report(stats, scope_label="all")
    lines = [l for l in out.splitlines() if "UNATTRIBUTED" in l and "Coverage" not in l]
    assert lines and "—" in lines[0]


def test_render_coverage_and_pct_independent_of_top():
    # --top must trim displayed rows only, never the coverage totals or the %
    # denominator (regression: previously % was computed over the shown subset).
    stats = rank_broadcasters(["A", "A", "A", "B", "B", "C", None])  # attr=6, unattr=1
    full = render_report(stats, scope_label="all")
    trimmed = render_report(stats, scope_label="all", top=1)
    cov = lambda o: [l for l in o.splitlines() if l.startswith("Coverage:")][0]
    assert cov(full) == cov(trimmed)            # totals identical
    assert "6 / 7" in cov(trimmed)              # attributed=6, total=7 (not 3/4)
    assert "50.0" in trimmed                    # A: 3/6, denominator is full attributed
    assert "UNATTRIBUTED" in trimmed            # kept under --top
    # only one broadcaster row shown under top=1 (rank '1', no rank '2')
    body = [l for l in trimmed.splitlines() if l.startswith("   1 ") or l.startswith("   2 ")]
    assert len(body) == 1


from ttn_broadcasters import broadcaster_key, OTHER


def test_broadcaster_key_folds_variant_and_buckets_non_ebu():
    assert broadcaster_key("GBBBC") == "GBBBC"
    assert broadcaster_key("NLNLOS") == "NLNOS"     # variant fold
    assert broadcaster_key("Decca") == OTHER        # commercial label
    assert broadcaster_key("BBC recording") == OTHER


def test_rank_with_broadcaster_key_buckets_other_pinned_before_unattributed():
    rows = ["GBBBC", "Decca", "EMI", "NLNLOS", "NLNOS", None]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    d = {s.key: s.airings for s in stats}
    assert d["NLNOS"] == 2          # NLNLOS folded into NLNOS
    assert d["GBBBC"] == 1
    assert d[OTHER] == 2            # Decca + EMI
    assert d["UNATTRIBUTED"] == 1
    keys = [s.key for s in stats]
    assert keys.index(OTHER) < keys.index("UNATTRIBUTED")   # OTHER before UNATTRIBUTED
    assert keys.index(OTHER) == len(keys) - 2               # second-last


def test_render_other_row_shows_pct_not_dash():
    rows = ["GBBBC", "Decca", "EMI"]   # attributed=3, OTHER=2
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    out = render_report(stats, scope_label="all")
    other_line = [l for l in out.splitlines() if "Other (non-EBU)" in l][0]
    assert "66.7" in other_line   # 2/3 of attributed, a real % (not —)


def test_csv_other_row_not_fabricated_broadcaster(tmp_path):
    from ttn_broadcasters import write_csv
    rows = ["GBBBC", "Decca", "EMI"]
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)
    p = tmp_path / "x.csv"
    write_csv(stats, str(p))
    text = p.read_text()
    # OTHER must NOT be emitted as a fabricated code/country ("OT") or ranked.
    assert "OT,OT" not in text and ",OTHER," not in text
    assert "Other (non-EBU)" in text          # labelled, blank code/country
    other = [l for l in text.splitlines() if "Other (non-EBU)" in l][0]
    assert other.startswith(",,")             # no rank, no code
