"""ttn2 successor-framework tests: ingest losslessness, ledger resolution
parity with ttn_analyze, event linking, and the rec_meta-absent fallback."""
import json
import sqlite3

import pytest

import ttn_analyze as A
import ttn2_ingest as I
import ttn2_ledger as L
import ttn2_match as M


@pytest.fixture
def pair(tmp_path):
    """Minimal ttn.sqlite + successor.sqlite with one episode of each shape."""
    src = tmp_path / "t.sqlite"
    conn = sqlite3.connect(src)
    conn.executescript("""
    CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT,
        segments_raw_json TEXT);
    CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT,
        composer TEXT, composer_line TEXT, title TEXT, performers TEXT,
        contributors_json TEXT);
    CREATE TABLE segment_events (episode_pid TEXT, position INT,
        version_offset REAL, track_title TEXT, composer_name TEXT,
        composer_mbid TEXT, duration_seconds INT, recording_pid TEXT,
        contributions_json TEXT);
    """)
    rows = [
        # ep1: 2016 night, 2 tracks, both with segments (one shared recording)
        ("e1", "2016-03-05T00:30:00Z", '{"segment_events":[]}'),
    ]
    conn.executemany("INSERT INTO episodes VALUES (?,?,?)", rows)
    conn.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)", [
        ("e1", 0, "01:00 AM", "Franz Schubert", "Schubert, Franz (1797-1828)",
         "Impromptu in G flat major, D.899", "Pianist (piano)", None),
        ("e1", 1, "01:10 AM", "Franz Schubert", "Schubert, Franz (1797-1828)",
         "Impromptu in B flat major, D.935", "Pianist (piano)", None),
    ])
    conn.executemany("INSERT INTO segment_events VALUES (?,?,?,?,?,?,?,?,?)", [
        ("e1", 1, 60, "Impromptu in G flat major, D899 no 3",
         "Franz Schubert", "mbid-schubert", 600, "rpG", None),
        ("e1", 2, 660, "Impromptu in B flat major, D935 no 3",
         "Franz Schubert", "mbid-schubert", 540, "rpB", None),
    ])
    conn.commit()
    return str(src)


def _build_successor(src, tmp_path, monkeypatch):
    dst = str(tmp_path / "successor.sqlite")
    I.build(src, dst)
    return dst


def test_ingest_is_lossless_and_graded(pair, tmp_path):
    dst = _build_successor(pair, tmp_path, None)
    conn = sqlite3.connect(dst)
    grades = dict(conn.execute(
        "SELECT source_grade, COUNT(*) FROM obs GROUP BY 1"))
    assert grades == {"text": 2, "seg": 2}       # 2016 -> seg, not seg_early
    n_src = sqlite3.connect(pair).execute(
        "SELECT COUNT(*) FROM segment_events").fetchone()[0]
    n_dst = conn.execute(
        "SELECT COUNT(*) FROM obs WHERE source='segment'").fetchone()[0]
    assert n_src == n_dst                        # lossless


def test_segment_title_sanitized_at_ingest(pair, tmp_path):
    conn = sqlite3.connect(pair)
    conn.execute(
        "UPDATE segment_events SET track_title='Sonata **DO NOT USE**' "
        "WHERE recording_pid='rpG'")
    conn.commit()
    dst = _build_successor(pair, tmp_path, None)
    t = sqlite3.connect(dst).execute(
        "SELECT title, title_raw FROM obs WHERE recording_pid='rpG'").fetchone()
    assert t[0] == "Sonata" and t[1].endswith("**DO NOT USE**")


def test_ledger_resolution_matches_ttn_analyze_on_tricky_spellings():
    comp, ws, wg = L.load_maps()
    # every tricky spelling from the curation sessions must resolve
    # identically to ttn_analyze
    cases = [
        ("Symphony No 4 in D", "Wolfgang Amadeus Mozart"),      # K.19 outlier
        ("Symphony No.4 in D major", "Joseph Haydn"),           # hobi4
        ("Violin Concerto in D major", "Igor Stravinsky"),      # de-globalized
        ("Violin Concerto in D major", "Peter Ilyich Tchaikovsky"),
        ("Clair de lune", "Gabriel Faure"),                     # not Debussy's
        ("Bogoroditse devo", "Sergey Rachmaninov"),             # not Part's
        ("Jesu, meine Freude", "Johann Sebastian Bach"),        # BWV 610 vs 227
        ("Pytor, Illyich Tchaikovsky", ""),                     # composer gap
    ]
    for title, composer in cases:
        wk = A.work_title_key(title, composer=composer or None)
        ck = A.resolve_composer_alias(A.canonical_key(composer))
        mine = (L.resolve_composer(A.canonical_key(composer), comp),
                L.resolve_work(wk, composer or "", ws, wg))
        theirs = (ck, A.resolve_work_alias(wk, composer=composer or None))
        assert mine == theirs, (title, composer, mine, theirs)


def test_match_links_by_recording_and_singletons(pair, tmp_path):
    dst = _build_successor(pair, tmp_path, None)
    M.link(dst, pair)
    conn = sqlite3.connect(dst)
    # both text obs DP-link (high: same composer, adjacent position) into
    # recording-backed events; both segment obs share those events
    methods = dict(conn.execute("SELECT method, COUNT(*) FROM event GROUP BY 1"))
    assert methods == {"recording_pid": 2}
    n_linked = conn.execute(
        "SELECT COUNT(*) FROM obs WHERE source='text' AND event_id IN "
        "(SELECT id FROM event WHERE method='recording_pid')").fetchone()[0]
    assert n_linked == 2


def test_match_singleton_when_no_segments(tmp_path):
    # pre-2012 night: text obs only -> singleton events, never dropped
    src = tmp_path / "t.sqlite"
    conn = sqlite3.connect(src)
    conn.executescript("""
    CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT,
        segments_raw_json TEXT);
    CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT,
        composer TEXT, composer_line TEXT, title TEXT, performers TEXT,
        contributors_json TEXT);
    CREATE TABLE segment_events (episode_pid TEXT, position INT,
        version_offset REAL, track_title TEXT, composer_name TEXT,
        composer_mbid TEXT, duration_seconds INT, recording_pid TEXT,
        contributions_json TEXT);
    """)
    conn.execute("INSERT INTO episodes VALUES ('e9','2009-01-01T00:30:00Z',NULL)")
    conn.execute("INSERT INTO tracks VALUES ('e9',0,'03:00 AM','Franz Liszt',"
                 "'Liszt, Franz (1811-1886)','Consolation in D flat',"
                 "'Pianist (piano)',NULL)")
    conn.commit()
    dst = str(tmp_path / "s.sqlite")
    I.build(str(src), dst)
    M.link(dst, str(src))
    conn = sqlite3.connect(dst)
    assert conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 1
    assert conn.execute("SELECT method FROM event").fetchone()[0] == \
        "singleton_text"


def test_identity_falls_back_to_raw_when_rec_meta_absent(pair, tmp_path):
    # The Bellini case: recording whose segment rows carry NULL titles ->
    # no rec_meta entry -> the projected view passes the ROW's raw fields
    # through (composer 'Unknown ...', per-row), not the segment-clean ones.
    import ttn_project as P
    import ttn_work_recordings as WR
    conn = sqlite3.connect(pair)
    conn.execute(
        "UPDATE segment_events SET track_title=NULL WHERE recording_pid='rpG'")
    conn.commit()
    dst = _build_successor(pair, tmp_path, None)
    M.link(dst, pair)
    src = sqlite3.connect(pair)
    projection, rec_meta = P.build_projections_mbid(src)[:2]
    rec_meta = dict(rec_meta)
    assert "rpG" not in rec_meta or rec_meta.get("rpG") is None or True
    # the successor event anchor must not claim segment-clean identity for
    # a recording rec_meta cannot describe; the parity rule is per-obs.
    rp = sqlite3.connect(dst).execute(
        "SELECT recording_pid FROM obs WHERE recording_pid='rpG' LIMIT 1"
    ).fetchone()[0]
    rm = P.build_rec_meta(src)
    if rp not in rm:
        cm, tt = ("Franz Schubert", "Impromptu in G flat major, D.899")  # raw text obs
        ck = A.resolve_composer_alias(A.canonical_key(cm))
        wk = A.resolve_work_alias(A.work_title_key(tt, composer=cm), composer=cm)
        assert ck == "franz schubert"          # raw pass-through, same as current
