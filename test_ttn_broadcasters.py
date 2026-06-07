import sqlite3
import pytest
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
