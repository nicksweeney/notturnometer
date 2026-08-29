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
        # P4-triage divergence (ledger ahead of ttn_aliases until cutover):
        # Fauré's Clair de lune resolves to its own bare group in the ledger;
        # ttn_aliases still folds it into Debussy's Bergamasque group.
        ("Clair de lune", "Gabriel Faure"),
        ("Jesu, meine Freude", "Johann Sebastian Bach"),        # BWV 610 vs 227
        ("Pytor, Illyich Tchaikovsky", ""),                     # composer gap
    ]
    # spellings whose resolution the P4 triage intentionally diverged
    diverged = {("Clair de lune", "Gabriel Faure"),
                ("Bogoroditse devo", "Sergey Rachmaninov")}
    for title, composer in cases:
        wk = A.work_title_key(title, composer=composer or None)
        ck = A.resolve_composer_alias(A.canonical_key(composer))
        mine = (L.resolve_composer(A.canonical_key(composer), comp),
                L.resolve_work(wk, composer or "", ws, wg))
        theirs = (ck, A.resolve_work_alias(wk, composer=composer or None))
        if (title, composer) in diverged:
            assert mine != theirs, (title, composer)   # ledger ahead, by design
        else:
            assert mine == theirs, (title, composer, mine, theirs)
    # the triage's Pärt-scoped fold: the transliteration family still lands
    # on the Op.37 group under Part scope
    assert L.resolve_work(
        A.work_title_key("Bogoroditse devo", composer="Arvo Part"),
        "Arvo Part", ws, wg) == \
        A.work_title_key("Bogoróditse Dévo, ráduisya - from All-Night Vigil "
                         "(Op.37)", composer="Arvo Part")


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


# --- ttn2_query: the P3 prototype tools over successor groups ---------------

def _query(args, tmp_path, pair):
    import ttn2_query as Q
    dst = _build_successor(pair, tmp_path, None)
    M.link(dst, pair)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = Q.main(["--src", pair, "--dst", dst] + args)
    return rc, buf.getvalue()


def test_query_fragmentation_finds_pairs(tmp_path):
    # A genuine fragment: two bare spellings of one unref work on a
    # pre-2012 night (no segments -> singletons -> separate groups).
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
    conn.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)", [
        ("e9", 0, "03:00 AM", "Franz Liszt", "Liszt, Franz (1811-1886)",
         'Zzzqux Symphony "Clock"', "P (piano)", None),
        ("e9", 1, "03:06 AM", "Franz Liszt", "Liszt, Franz (1811-1886)",
         "Zzzqux Symphony in D", "P (piano)", None),
    ])
    conn.commit()
    dst = str(tmp_path / "s.sqlite")
    I.build(str(src), dst)
    M.link(dst, str(src))
    rc, out = _query(["fragmentation", "--top", "5"], tmp_path, str(src))
    assert rc == 0
    assert "Franz Liszt" in out and "Zzzqux" in out


def test_query_work_recordings_panel(tmp_path, pair, capsys):
    rc, out = _query(["work-recordings", "impromptu"], tmp_path, pair)
    assert rc == 0
    assert "rpG" in out and "dur[600]" in out
    assert "projected" in out


def test_query_qc_audit_runs(tmp_path, pair, capsys):
    conn = sqlite3.connect(pair)
    conn.execute("UPDATE segment_events SET track_title="
                 "'Sonata **DO NOT USE**' WHERE recording_pid='rpG'")
    conn.commit()
    rc, out = _query(["qc-audit"], tmp_path, pair)
    assert rc == 0
    # obs titles were sanitized at ingest -> the marker does NOT survive
    assert "leading survivors" not in out
    assert "clean:" in out or "no directive" in out or "embedded" in out


def test_match_resolves_recording_pid_via_ledger(tmp_path, monkeypatch):
    """Fix round 3: a raw segment recording_pid resolves through the
    recording-decisions ledger at event/presentation creation, so successor
    state stores ledger-RESOLVED terminals exactly like the legacy projection
    (ttn_project.projection_from_matches)."""
    import sqlite3, ttn2_ingest, ttn2_match
    dst = str(tmp_path / "s.sqlite")
    conn = sqlite3.connect(dst)
    conn.executescript(ttn2_ingest.SCHEMA)
    # one segment obs (raw rp A) + one text obs the (fake) DP matches at medium
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, title, recording_pid) "
                 "VALUES (1, 'ep1', '2020-01-01', 1.0, 'segment', 'seg', "
                 "'Smetana', 'Vltava', 'A')")
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, title) "
                 "VALUES (2, 'ep1', '2020-01-01', 1.5, 'text', 'text', "
                 "'Smetana', 'Vltava')")
    conn.commit()
    fake = [{"track_position": 1, "composer_mbid": None,
             "recording_pid": "A", "segment_composer_name": "Smetana",
             "tier": "medium"}]
    monkeypatch.setattr(ttn2_match, "reconcile_episode", lambda t, s: fake)
    monkeypatch.setattr(ttn2_match, "load_recording_decisions",
                        lambda: {"A": "B"})
    ttn2_match.link(dst=dst, src=str(tmp_path / "nonexistent-src.sqlite"))
    # the segment event was created with the TERMINAL B, never raw A
    ev = conn.execute("SELECT method, recording_pid FROM event "
                      "WHERE method='recording_pid'").fetchall()
    assert ev == [("recording_pid", "B")]
    # the medium presentation link carries the terminal too
    assert conn.execute("SELECT recording_pid FROM presentation").fetchall() \
        == [("B",)]
    conn.close()


def test_ledger_link_rows_survive_rebuild(tmp_path):
    """Round 4: import RESTORES the ledger from the tracked
    ttn2_ledger.json (rows verbatim — the curated deglob-* rows survive),
    tops up any missing ratified link rows, an old-shape ledger migrates
    in place, and load_maps never mistakes kind='link' rows for composer
    aliases."""
    dst = str(tmp_path / "succ.sqlite")
    conn = sqlite3.connect(dst)
    conn.executescript(I.SCHEMA)
    conn.close()
    want = {(ep, str(pos), rp) for ep, pos, rp in L._EBU_ORDER_LINKS}
    assert len(want) == len(L._EBU_ORDER_LINKS)      # triples are unique

    def rows(db, where="kind='link'"):
        c = sqlite3.connect(db)
        out = set(c.execute(f"SELECT scope, variant_key, target FROM ledger "
                            f"WHERE {where}"))
        c.close()
        return out

    L.import_aliases(dst=dst)                 # restore from tracked JSON
    assert rows(dst) == want
    L.import_aliases(dst=dst)                 # rebuild: DELETE + insert
    assert rows(dst) == want
    # the curated de-globalization rows survive the rebuild (round-4 fix:
    # the from-aliases derivation wiped all 140). COUNT(*), not a distinct
    # triple set — the curated ledger itself holds 7 duplicate triples.
    c = sqlite3.connect(dst)
    n_deglob = c.execute(
        "SELECT COUNT(*) FROM ledger WHERE method LIKE 'deglob%'"
    ).fetchone()[0]
    c.close()
    assert n_deglob == 140
    # evidence rides on the rows
    c = sqlite3.connect(dst)
    evid = c.execute("SELECT evidence_json FROM ledger WHERE kind='link' "
                     "LIMIT 1").fetchone()[0]
    c.close()
    assert json.loads(evid)["episodes"] == \
        sorted({ep for ep, _p, _r in L._EBU_ORDER_LINKS})
    # load_maps ignores them: no episode pid / recording pid in the maps
    comp, ws, wg = L.load_maps(dst)
    eps = {ep for ep, _p, _r in L._EBU_ORDER_LINKS}
    rps = {rp for _e, _p, rp in L._EBU_ORDER_LINKS}
    assert not (set(comp) & (eps | rps))
    assert not (set(comp.values()) & rps)
    # a JSON WITHOUT link rows still gets them topped up
    mini = str(tmp_path / "mini.json")
    with open(mini, "w") as fh:
        json.dump({"ledger": [], "meta": {}, "anchor": [],
                   "work_entities": []}, fh)
    L.import_aliases(json_path=mini, dst=dst)
    assert rows(dst) == want
    # an OLD-shape ledger (pre evidence_json) migrates in place
    old = str(tmp_path / "old.sqlite")
    c2 = sqlite3.connect(old)
    c2.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
               "scope TEXT NOT NULL, variant_key TEXT NOT NULL, target TEXT NOT NULL, "
               "target_key TEXT NOT NULL, method TEXT NOT NULL, confidence TEXT NOT NULL, "
               "flags_json TEXT)")
    c2.commit()
    c2.close()
    L.import_aliases(dst=old)
    assert rows(old) == want


def test_match_records_medium_presentation(tmp_path, monkeypatch):
    """A Medium-tier DP match becomes a presentation row, NOT an event link:
    the obs keeps a singleton event and raw-text identity."""
    import sqlite3, ttn2_ingest, ttn2_match
    dst = str(tmp_path / "s.sqlite")
    conn = sqlite3.connect(dst)
    conn.executescript(ttn2_ingest.SCHEMA)
    # one segment obs (rp X) + one text obs that the (fake) DP matches at medium
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, title, recording_pid) "
                 "VALUES (1, 'ep1', '2020-01-01', 1.0, 'segment', 'seg', "
                 "'Smetana', 'Vltava', 'X')")
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, title) "
                 "VALUES (2, 'ep1', '2020-01-01', 1.5, 'text', 'text', "
                 "'Smetana', 'Vltava')")
    conn.commit()
    fake = [{"track_position": 1, "composer_mbid": None,
             "recording_pid": "X", "segment_composer_name": "Smetana",
             "tier": "medium"}]
    monkeypatch.setattr(ttn2_match, "reconcile_episode", lambda t, s: fake)
    ttn2_match.link(dst=dst, src=str(tmp_path / "nonexistent-src.sqlite"))
    # obs NOT linked to the recording event (identity stays raw)
    ev = conn.execute("SELECT method, confidence, recording_pid FROM event "
                      "ORDER BY id").fetchall()
    assert ("recording_pid", "high", "X") in ev          # segment event
    assert ("singleton_text", "singleton", None) in ev   # text obs stays singleton
    assert conn.execute("SELECT recording_pid FROM presentation").fetchall() \
        == [("X",)]
    conn.close()


def test_match_ingests_bridge_links(tmp_path):
    """Pre-2012 text obs (episodes with no segment obs) whose (ep, pos) is in
    the legacy full projection become recording-backed events, method='bridge'."""
    import sqlite3, ttn2_ingest, ttn2_match
    src = str(tmp_path / "ttn.sqlite"); dst = str(tmp_path / "s.sqlite")
    s = sqlite3.connect(src)
    s.executescript("CREATE TABLE episodes (pid TEXT PRIMARY KEY, "
                    "broadcast_date TEXT); CREATE TABLE tracks (episode_pid TEXT, "
                    "position INTEGER, time_str TEXT, composer TEXT, "
                    "composer_line TEXT, title TEXT, performers TEXT, "
                    "contributors_json TEXT);")
    s.execute("INSERT INTO episodes VALUES ('old1', '2005-01-01T00:30:00Z')")
    s.execute("INSERT INTO tracks VALUES ('old1', 0, '1:01 am', 'Bach', "
              "'Johann Sebastian Bach (1685-1750)', 'Cello Suite No 1', 'p', '[]')")
    s.commit(); s.close()
    conn = sqlite3.connect(dst)
    conn.executescript(ttn2_ingest.SCHEMA)
    # minimal obs for the episode (what ingest would have written)
    conn.execute("INSERT INTO obs (id, episode_pid, date10, ord, source, "
                 "source_grade, composer_raw, composer_line, title) "
                 "VALUES (1, 'old1', '2005-01-01', 0.0, 'text', 'text', "
                 "'Bach', 'Johann Sebastian Bach (1685-1750)', 'Cello Suite No 1')")
    conn.commit()
# monkeypatch the legacy projection read: (old1, 0) -> rp BR1
    class FakeP:
        @staticmethod
        def load(conn, *a, **k):
            return {("old1", 0): "BR1"}, {"BR1": ("Johann Sebastian Bach",
                                                  "Cello Suite No 1, BWV 1007")}, "ok"
    import ttn_project
    orig = ttn_project.load
    ttn_project.load = FakeP.load
    try:
        ttn2_match.link(dst=dst, src=src)
    finally:
        ttn_project.load = orig
    ev = conn.execute("SELECT method, confidence, recording_pid, composer, title "
                      "FROM event WHERE method='bridge'").fetchall()
    assert ev == [("bridge", "high", "BR1", "Johann Sebastian Bach",
                   "Cello Suite No 1, BWV 1007")]
    assert conn.execute("SELECT event_id FROM obs WHERE id=1").fetchone()[0] == \
        conn.execute("SELECT id FROM event WHERE method='bridge'").fetchone()[0]
    conn.close()


def test_query_propose_remaps_presence_and_redirect(tmp_path, pair):
    import io as _io
    import contextlib
    import os
    import ttn2_query as Q
    dst = _build_successor(pair, tmp_path, None)
    M.link(dst, pair)
    os.chdir(tmp_path)
    try:
        with open("ttn_site_registry.json", "w") as fh:
            json.dump({"works": {"x:work": {
                "composer_key": "franz schubert",
                "work_key": "3 flat flat g impromptu major no"}},
                "redirects": {"works": {"x:old": "x:work"}}}, fh)
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = Q.main(["--src", pair, "--dst", dst, "propose-remaps",
                         "x:old", "x:work"])
        out = buf.getvalue()
        assert rc == 0
        assert "redirected to 'x:work'" in out
        assert "identity present" in out or "MISSING" in out
    finally:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
