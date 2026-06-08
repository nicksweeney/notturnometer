import json, os, sqlite3
import pytest
import ttn_spine as S
from ttn_analyze import canonical_key

def _mkdb(rows):
    """rows: list of (recording_pid, episode_pid, event_pid, composer_name,
    composer_mbid, duration, track_title, contributions(list of dicts), date)."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT)")
    c.execute("""CREATE TABLE segment_events (event_pid TEXT, episode_pid TEXT,
        recording_pid TEXT, composer_name TEXT, composer_mbid TEXT,
        duration_seconds INT, track_title TEXT, contributions_json TEXT)""")
    eps = {}
    for rp, ep, ev, cn, cm, dur, tt, contribs, date in rows:
        eps.setdefault(ep, date)
        c.execute("INSERT INTO segment_events VALUES (?,?,?,?,?,?,?,?)",
                  (ev, ep, rp, cn, cm, dur, tt, json.dumps(contribs)))
    for ep, date in eps.items():
        c.execute("INSERT INTO episodes VALUES (?,?)", (ep, date))
    c.commit()
    return c

# --- Live-DB fixtures (module-scoped): the heavy full-corpus passes
# (build_recordings / build_contributors / work_alias_candidates each rebuild
# the 125k-row maps or scan tracks+segments) run ONCE and are shared across the
# live tests, instead of per-test. The live_db fixture also handles the skip. ---

@pytest.fixture(scope="module")
def live_db():
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    return sqlite3.connect("ttn.sqlite")

@pytest.fixture(scope="module")
def live_ctx(live_db):
    return S.build_context(live_db)            # the 86s load+maps prefix, ONCE

@pytest.fixture(scope="module")
def live_recs(live_db, live_ctx):
    return S.build_recordings(live_db, ctx=live_ctx)

@pytest.fixture(scope="module")
def live_con(live_db, live_ctx):
    return S.build_contributors(live_db, ctx=live_ctx)

@pytest.fixture(scope="module")
def live_cands(live_db):
    return S.work_alias_candidates(live_db)   # full corpus (composer=None)

def test_canon_name_folds_diacritics_and_case():
    assert S.canon_name("Łukasz Borowicz") == S.canon_name("Lukasz Borowicz")
    assert S.canon_name("Heinrich Schütz") == S.canon_name("Heinrich Schutz")

def test_load_seg_rows_flattens_contributions():
    db = _mkdb([
        ("r1","e1","ev1","Sibelius","mbS",567,"4 Songs",
         [{"name":"Sibelius","role":"Composer","pid":"pC","musicbrainz_gid":"mbS"},
          {"name":"Andreas Staier","role":"Performer","pid":"pP","musicbrainz_gid":"mbP"}],
         "2015-01-20T00:30:00Z"),
    ])
    rows = S.load_seg_rows(db)
    roles = {(r.role, r.name, r.mbid) for r in rows}
    assert ("Composer","Sibelius","mbS") in roles
    assert ("Performer","Andreas Staier","mbP") in roles
    assert all(r.recording_pid == "r1" and r.date == "2015-01-20" for r in rows)

def test_resolve_identity_four_branches():
    nm = {S.canon_name("Polish RSO"): {"mP"},
          S.canon_name("Johann Bach"): {"b1","b2"}}      # ambiguous
    # (a) mbid present -> trust it
    assert S.resolve_identity("Anything","mX", nm, role="Composer") == ("mX","mX")
    # (b) backfillable: no mbid, name maps to exactly one
    assert S.resolve_identity("Polish RSO", None, nm, role="Orchestra") == ("mP","mP")
    # (c) ambiguous: name maps to >1 mbid -> stay name-keyed, no backfill
    k,m = S.resolve_identity("Johann Bach", None, nm, role="Composer")
    assert m is None and k.startswith("name:")
    # (d) never-resolved + alias override (composer)
    k2,m2 = S.resolve_identity("Lukasz Borowicz", None, nm, role="Conductor")
    assert m2 is None and k2 == "name:" + canonical_key("Lukasz Borowicz")

def test_build_name_mbid_map_records_ambiguity():
    db = _mkdb([
        ("r1","e1","ev1","Bach","b1",100,"X",
         [{"name":"Johann Bach","role":"Composer","pid":"p","musicbrainz_gid":"b1"}],"2014-01-01"),
        ("r2","e2","ev2","Bach","b2",100,"Y",
         [{"name":"Johann Bach","role":"Composer","pid":"p","musicbrainz_gid":"b2"}],"2014-01-02"),
    ])
    nm, disp = S.build_name_mbid_maps(S.load_seg_rows(db))
    assert nm[S.canon_name("Johann Bach")] == {"b1","b2"}
    assert disp["b1"] == "Johann Bach"

def test_build_recordings_groups_and_resolves():
    db = _mkdb([
        ("rOv","e1","a","Erkel Ferenc","mE",262,"Overture to Nevtelen hosok",
         [{"name":"Erkel Ferenc","role":"Composer","pid":"p","musicbrainz_gid":"mE"}],"2016-01-01"),
        ("rOv","e2","b","Erkel Ferenc","mE",262,"Overture to Nevtelen hosok",
         [{"name":"Erkel Ferenc","role":"Composer","pid":"p","musicbrainz_gid":"mE"}],"2017-01-01"),
        ("rDuo","e3","c","Erkel Ferenc","mE",1002,"Duo brillant",
         [{"name":"Erkel Ferenc","role":"Composer","pid":"p","musicbrainz_gid":"mE"}],"2018-01-01"),
    ])
    recs = S.build_recordings(db)
    assert set(recs) == {"rOv","rDuo"}
    assert recs["rOv"].airing_count == 2
    assert recs["rOv"].first_aired == "2016-01-01" and recs["rOv"].last_aired == "2017-01-01"
    assert recs["rOv"].duration_seconds == 262 and recs["rDuo"].duration_seconds == 1002
    assert recs["rOv"].composer_mbid == "mE"

def test_build_recordings_date_filter_is_boundary_safe():
    db = _mkdb([
        ("r","e1","a","X","m",10,"t",[{"name":"X","role":"Composer","musicbrainz_gid":"m"}],"2019-12-31T23:30:00Z"),
    ])
    assert "r" in S.build_recordings(db, before="2019-12-31")   # boundary day kept
    assert "r" not in S.build_recordings(db, after="2020-01-01")

def test_interstitials_excluded_by_default():
    from ttn_segment_meta import INTERSTITIAL_RECORDING_PIDS
    inter = next(iter(INTERSTITIAL_RECORDING_PIDS))
    db = _mkdb([
        (inter,"e1","a","Milhaud","mM",32,"Cheminee",
         [{"name":"Milhaud","role":"Composer","musicbrainz_gid":"mM"}],"2016-01-01"),
        ("rOk","e2","b","Bach","mB",600,"Real piece",
         [{"name":"Bach","role":"Composer","musicbrainz_gid":"mB"}],"2016-01-02"),
    ])
    assert set(S.build_recordings(db)) == {"rOk"}                       # filler dropped
    assert set(S.build_recordings(db, keep_interstitials=True)) == {inter, "rOk"}
    assert inter not in S.build_contributors(db)
    assert inter in S.build_contributors(db, keep_interstitials=True)

def test_build_contributors_resolves_roles_and_dedupes():
    db = _mkdb([
        ("r","e1","a","Bach","mC",100,"t",
         [{"name":"Bach","role":"Composer","pid":"pc","musicbrainz_gid":"mC"},
          {"name":"German RPO","role":"Orchestra","pid":"po1","musicbrainz_gid":None},
          {"name":"German RPO","role":"Orchestra","pid":"po2","musicbrainz_gid":None}],"2016-01-01"),
    ])
    con = S.build_contributors(db)
    orchs = [c for c in con["r"] if c.role == "Orchestra"]
    assert len(orchs) == 1                         # two throwaway pids -> one identity
    assert orchs[0].mbid is None and orchs[0].identity_key.startswith("name:")
    assert any(c.role == "Composer" and c.mbid == "mC" for c in con["r"])

def test_ctx_passing_matches_internal_build():
    db = _mkdb([
        ("r1","e1","a","Bach","mC",100,"t",
         [{"name":"Bach","role":"Composer","pid":"pc","musicbrainz_gid":"mC"},
          {"name":"Staier","role":"Performer","pid":"pp","musicbrainz_gid":"mS"}],"2016-01-01"),
        ("r2","e2","b","Bach","mC",200,"u",
         [{"name":"Bach","role":"Composer","pid":"pc","musicbrainz_gid":"mC"}],"2017-01-01"),
    ])
    ctx = S.build_context(db)
    assert S.build_recordings(db, ctx=ctx) == S.build_recordings(db)
    assert S.build_contributors(db, ctx=ctx) == S.build_contributors(db)

def test_live_saarbrucken_and_borowicz(live_con):
    ids = {}   # identity_key -> set of display names seen
    for rp, clist in live_con.items():
        for c in clist:
            ids.setdefault(c.identity_key, set()).add(c.display_name)
    # Borowicz: the BBC links only the diacritic spelling 'Łukasz Borowicz'
    # (MBID a4847673); canon_name folds 'Łukasz'->'Lukasz', so the name->MBID
    # backfill recovers that MBID for all the ASCII 'Lukasz Borowicz' airings
    # too -> ONE MBID identity for all ~629 airings (not 31 throwaway-pid
    # fragments, not a name key), displayed with the correct diacritic.
    bor = [k for k, names in ids.items()
           if any("borowicz" in (n or "").lower() for n in names)]
    assert bor == ["a4847673-3b3d-4cfb-ba3c-bc7498710eae"]
    assert ids[bor[0]] == {"Łukasz Borowicz"}
    # Saarbrücken successor vs predecessor are distinct MBIDs (distinct identities)
    assert "afe4c2d5-12f5-441a-b236-efd382814683" in ids   # successor
    assert "24dfa7fe-f6c3-4751-84eb-b847a5f9db33" in ids   # predecessor

def test_rank_contributors_airings_and_breadth():
    db = _mkdb([
        ("r1","e1","a","C","mc",10,"t",
         [{"name":"Staier","role":"Performer","pid":"p","musicbrainz_gid":"mS"}],"2016-01-01"),
        ("r1","e2","b","C","mc",10,"t",
         [{"name":"Staier","role":"Performer","pid":"p","musicbrainz_gid":"mS"}],"2016-02-01"),
        ("r2","e3","c","C","mc",20,"u",
         [{"name":"Staier","role":"Performer","pid":"p","musicbrainz_gid":"mS"}],"2016-03-01"),
    ])
    recs = S.build_recordings(db); con = S.build_contributors(db)
    stats = S.rank_contributors(recs, con, "Performer")
    top = stats[0]
    assert top.mbid == "mS" and top.airings == 3 and top.recordings == 2

def test_live_performer_head_is_staier(live_recs, live_con):
    stats = S.rank_contributors(live_recs, live_con, "Performer")
    assert stats[0].display_name == "Andreas Staier"

def test_coverage_split_counts_name_keyed():
    db = _mkdb([
        ("r1","e1","a","C","m1",10,"t",[{"name":"A","role":"Conductor","musicbrainz_gid":"m1"}],"2016-01-01"),
        ("r2","e2","b","C","m2",10,"t",[{"name":"B","role":"Conductor","musicbrainz_gid":None}],"2016-01-02"),
    ])
    recs = S.build_recordings(db); con = S.build_contributors(db)
    stats = S.rank_contributors(recs, con, "Conductor")
    resolved, named = S.coverage_split(stats)
    assert resolved == 1 and named == 1

def test_render_ranking_marks_name_keyed():
    st = [S.ContribStat("name:x","B",None,5,3), S.ContribStat("m","A","m",9,4)]
    text = S.render_ranking(st, by="conductor", top=10)
    assert "·name" in text and "A" in text and "B" in text

def test_les_fastes_is_a_single_recording_fold_candidate(live_cands):
    fastes = [c for c in live_cands if c.recording_pid == "p037d3z3"]
    assert fastes, "Les Fastes (p037d3z3) should surface as a fold candidate"
    assert fastes[0].n_work_keys > 1   # multiple tracks-side keys, one recording
    assert "fastes" in (fastes[0].segment_title or "").lower()

def test_sibelius_4songs_single_recording(live_cands):
    assert any(c.recording_pid == "p00r8dv2" and c.n_work_keys > 1 for c in live_cands)
