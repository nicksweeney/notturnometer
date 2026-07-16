import json, os, sqlite3
import pytest
import ttn_spine as S
from ttn_analyze import canonical_key

def _mkdb(rows):
    """rows: list of (recording_pid, episode_pid, event_pid, composer_name,
    composer_mbid, duration, track_title, contributions(list of dicts), date).
    Each segment_event gets a position = its 1-indexed order within its episode
    (mirrors the real 1-indexed segment_events.position)."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT)")
    c.execute("""CREATE TABLE segment_events (event_pid TEXT, episode_pid TEXT,
        position INT, recording_pid TEXT, composer_name TEXT, composer_mbid TEXT,
        duration_seconds INT, track_title TEXT, contributions_json TEXT,
        record_label TEXT)""")
    eps = {}
    ep_pos = {}
    for rp, ep, ev, cn, cm, dur, tt, contribs, date in rows:
        eps.setdefault(ep, date)
        ep_pos[ep] = ep_pos.get(ep, 0) + 1
        c.execute("INSERT INTO segment_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (ev, ep, ep_pos[ep], rp, cn, cm, dur, tt, json.dumps(contribs), None))
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

@pytest.fixture(scope="module")
def live_works(live_db, live_recs):
    return S.build_works(live_recs)

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

def test_resolve_identity_ensemble_alias_reaches_mbid():
    # Cross-lingual / variant ensemble whose canonical carries an MBID but the
    # variant name does not: the variant must reach that MBID (the bridge needs
    # both era's spellings to land on one identity). Uses the real Ljubljana alias.
    nm = {S.canon_name("Ljubljanski godalni kvartet"): {"mLJ"}}
    # variant name -> alias canonical -> the canonical's backfilled MBID
    assert S.resolve_identity("Ljubljana String Quartet", None, nm,
                              role="Ensemble") == ("mLJ", "mLJ")
    # but a name with its OWN mbid is preferred (raw lookup first; alias never
    # overrides a present MBID)
    nm2 = dict(nm); nm2[S.canon_name("Ljubljana String Quartet")] = {"mOWN"}
    assert S.resolve_identity("Ljubljana String Quartet", None, nm2,
                              role="Ensemble") == ("mOWN", "mOWN")

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

def test_build_recordings_composer_filter_folds_diacritics():
    # The --composer segment filter ascii-folds, so an ASCII query reaches the
    # stored accented spelling (a raw case-only substring missed every diacritic).
    db = _mkdb([
        ("rD","e1","a","Antonín Dvořák","mD",600,"Symphony No 9",
         [{"name":"Antonín Dvořák","role":"Composer","musicbrainz_gid":"mD"}],"2016-01-01"),
        ("rB","e2","b","Bach","mB",300,"Air",
         [{"name":"Bach","role":"Composer","musicbrainz_gid":"mB"}],"2016-01-02"),
    ])
    assert set(S.build_recordings(db, composer="Dvorak")) == {"rD"}
    assert set(S.build_contributors(db, composer="Dvorak")) == {"rD"}

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

@pytest.mark.live
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

@pytest.mark.live
def test_live_performer_head_is_staier(live_recs, live_con):
    stats = S.rank_contributors(live_recs, live_con, "Performer")
    assert stats[0].display_name == "Andreas Staier"

def test_rank_contributors_role_set_dedupes_identity_within_recording():
    # The combined ensembles view (website): one identity credited on the SAME
    # recording under two ensemble roles (the BBC tags e.g. Finnish RSO both
    # 'Orchestra' and 'Ensemble' across airings) must count once per recording,
    # never double. A different recording still accumulates.
    db = _mkdb([
        ("r1","e1","a","C","mc",10,"t",
         [{"name":"Finnish RSO","role":"Orchestra","musicbrainz_gid":"mF"},
          {"name":"Finnish RSO","role":"Ensemble","musicbrainz_gid":"mF"},
          {"name":"Tapiola Choir","role":"Choir","musicbrainz_gid":"mT"}],
         "2016-01-01"),
        ("r2","e2","b","C","mc",20,"u",
         [{"name":"Finnish RSO","role":"Ensemble","musicbrainz_gid":"mF"}],
         "2016-02-01"),
    ])
    recs = S.build_recordings(db); con = S.build_contributors(db)
    stats = S.rank_contributors(recs, con, {"Orchestra", "Ensemble", "Choir"})
    by_mbid = {s.mbid: s for s in stats}
    assert by_mbid["mF"].airings == 2 and by_mbid["mF"].recordings == 2
    assert by_mbid["mT"].airings == 1 and by_mbid["mT"].recordings == 1
    # single-role string form unchanged
    orch_only = S.rank_contributors(recs, con, "Orchestra")
    assert [s.mbid for s in orch_only] == ["mF"]

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

@pytest.mark.live
def test_les_fastes_is_a_single_recording_fold_candidate(live_cands):
    fastes = [c for c in live_cands if c.recording_pid == "p037d3z3"]
    assert fastes, "Les Fastes (p037d3z3) should surface as a fold candidate"
    assert fastes[0].n_work_keys > 1   # multiple tracks-side keys, one recording
    assert "fastes" in (fastes[0].segment_title or "").lower()

@pytest.mark.live
def test_sibelius_4songs_single_recording(live_cands):
    assert any(c.recording_pid == "p00r8dv2" and c.n_work_keys > 1 for c in live_cands)

@pytest.mark.live
def test_live_works_cluster_and_rank(live_works):
    # the work layer produces fewer works than recordings (clustering happened)
    assert len(live_works) > 1000
    ranked = S.rank_works(live_works)
    top = ranked[0]
    # the most-aired work is a real clustered work: multiple recordings, a span,
    # a human title (not a raw § / token-sort key)
    assert top.airing_count >= top.recording_count >= 1
    assert top.work_display and not top.work_display.startswith("§")
    # the excerpt flag fires somewhere in the corpus (the duration oracle has hits)
    assert any(w.excerpt_flag for w in live_works)

def test_build_position_bridge_maps_episode_position_to_recording():
    db = _mkdb([
        ("rA","e1","a","C","mc",100,"tA",
         [{"name":"C","role":"Composer","musicbrainz_gid":"mc"}],"2016-01-01"),
        ("rB","e1","b","C","mc",200,"tB",
         [{"name":"C","role":"Composer","musicbrainz_gid":"mc"}],"2016-01-01"),
    ])
    seg, per_ep = S._build_position_bridge(db)
    assert all(isinstance(v, tuple) and len(v) == 3 for v in seg.values())
    assert set(rp for (rp, cn, tt) in seg.values()) == {"rA", "rB"}
    assert len(per_ep["e1"]) == 2

def test_assign_recording_work_keys_uses_segment_title():
    # work_key comes from each recording's stable segment title; two recordings
    # sharing a segment title -> one work. No tracks/bridge needed.
    db = _mkdb([
        ("rA","e1","a","Beethoven","mB",1800,"Symphony No 5 in C minor, Op 67",
         [{"name":"Beethoven","role":"Composer","musicbrainz_gid":"mB"}],"2016-01-01"),
        ("rB","e2","b","Beethoven","mB",1790,"Symphony No 5 in C minor, Op 67",
         [{"name":"Beethoven","role":"Composer","musicbrainz_gid":"mB"}],"2016-02-01"),
    ])
    recs = S.build_recordings(db)
    wk = S.assign_recording_work_keys(recs)
    from ttn_analyze import work_title_key, resolve_work_alias
    expected = resolve_work_alias(work_title_key("Symphony No 5 in C minor, Op 67",
                                                 composer=recs["rA"].composer_display))
    assert wk["rA"].work_key == expected
    assert wk["rA"].work_key == wk["rB"].work_key       # same segment title -> one work
    assert wk["rA"].titles["Symphony No 5 in C minor, Op 67"] == 1

def test_assign_work_keys_ignore_long_synopsis_churn():
    # the segment title anchors the key even if a tracks row titles the same
    # recording differently — the within-recording-churn immunity (the flip).
    db = _mkdb([
        ("rX","e1","a","Strauss","mS",600,"The Blue Danube, Op 314",
         [{"name":"Strauss","role":"Composer","musicbrainz_gid":"mS"}],"2016-01-01"),
    ])
    db.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, composer TEXT, title TEXT)")
    db.execute("INSERT INTO tracks VALUES (?,?,?,?)",
               ("e1", 0, "Strauss", "An der schonen blauen Donau - waltz (Op.314) with chorus"))
    db.commit()
    recs = S.build_recordings(db)
    wk = S.assign_recording_work_keys(recs)            # note: no db arg — keys off segment title
    from ttn_analyze import work_title_key, resolve_work_alias
    assert wk["rX"].work_key == resolve_work_alias(
        work_title_key("The Blue Danube, Op 314", composer=recs["rX"].composer_display))

def test_build_works_clusters_by_composer_and_workkey():
    db = _mkdb([
        ("rB1","e1","a","Beethoven","mB",1800,"Symphony No 5 in C minor, Op 67",
         [{"name":"Beethoven","role":"Composer","musicbrainz_gid":"mB"}],"2016-01-01"),
        ("rB1","e2","b","Beethoven","mB",1800,"Symphony No 5 in C minor, Op 67",
         [{"name":"Beethoven","role":"Composer","musicbrainz_gid":"mB"}],"2016-02-01"),
        ("rB2","e3","c","Beethoven","mB",1790,"Symphony No.5 in C minor (Op.67)",
         [{"name":"Beethoven","role":"Composer","musicbrainz_gid":"mB"}],"2016-03-01"),
        ("rG","e4","d","Grieg","mG",900,"Holberg Suite, Op 40",
         [{"name":"Grieg","role":"Composer","musicbrainz_gid":"mG"}],"2016-04-01"),
    ])
    recs = S.build_recordings(db)
    works = S.build_works(recs)
    beeth = [w for w in works if w.composer_display == "Beethoven"]
    assert len(beeth) == 1                            # both pids fold to one work
    w = beeth[0]
    assert w.recording_count == 2 and w.airing_count == 3
    assert set(w.recording_pids) == {"rB1", "rB2"}
    assert w.first_aired == "2016-01-01" and w.last_aired == "2016-03-01"
    assert "symphony" in w.work_display.lower()       # a real title, not the §/token key
    assert {w2.composer_display for w2 in works} == {"Beethoven", "Grieg"}

def test_excerpt_flag_predicate():
    assert S._excerpt_flag("§bwv1009|2,3|", [90, 600]) is True      # short+long under one § key
    assert S._excerpt_flag("§bwv1009|2,3|", [590, 600]) is False    # both whole
    assert S._excerpt_flag("§bwv1009|2,3|", [600]) is False         # single recording
    assert S._excerpt_flag("token sorted key", [90, 600]) is False  # not a catalogue key

def test_build_works_flags_duration_divergence_under_catalogue_key():
    # one catalogue work (RV-bearing) with a short excerpt + a long whole recording
    # work_title_key("Concerto in G, RV 310") -> "§rv310|310|g" (catalogue path)
    db = _mkdb([
        ("rWhole","e1","a","Vivaldi","mV",600,"Concerto in G, RV 310",
         [{"name":"Vivaldi","role":"Composer","musicbrainz_gid":"mV"}],"2016-01-01"),
        ("rExc","e2","b","Vivaldi","mV",120,"Concerto in G, RV 310",
         [{"name":"Vivaldi","role":"Composer","musicbrainz_gid":"mV"}],"2016-02-01"),
    ])
    recs = S.build_recordings(db)
    works = S.build_works(recs)
    assert len(works) == 1                            # same §rv310 key
    assert works[0].excerpt_flag is True
    assert works[0].work_key.startswith("§")

def test_rank_works_by_airings_then_recordings():
    a = S.Work("ca","A","ka","Work A",["r1","r2"],10,2,"2016","2017",False)
    b = S.Work("cb","B","kb","Work B",["r3"],20,1,"2016","2016",False)
    assert [w.work_display for w in S.rank_works([a, b])] == ["Work B", "Work A"]
    # breadth: by distinct recordings
    assert [w.work_display for w in S.rank_works([a, b], sort="recordings")] \
        == ["Work A", "Work B"]

def test_render_works_marks_excerpt_candidates():
    works = [S.Work("c","Bach","§k","Cello Suite No 3",["r1","r2"],8,2,"2016","2018",True)]
    text = S.render_works(works, top=10)
    assert "Bach" in text and "Cello Suite No 3" in text
    assert "8x" in text.replace(" ", "")              # airing count rendered
    assert "excerpt" in text.lower()                  # the split-candidate mark

@pytest.mark.live
def test_live_build_recordings_broadcaster_filter_narrows(tmp_path):
    import os, sqlite3, ttn_spine as S
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    ctx = S.build_context(conn)
    assert hasattr(ctx.seg[0], "record_label")          # SegRow now carries it
    labels = {r.record_label for r in ctx.seg if r.record_label}
    pick = next(iter(labels))
    all_recs = S.build_recordings(conn, ctx=ctx)
    one = S.build_recordings(conn, ctx=ctx, record_labels={pick})
    assert 0 < len(one) <= len(all_recs)
    con = S.build_contributors(conn, ctx=ctx, record_labels={pick})
    assert isinstance(con, dict)

@pytest.mark.live
def test_live_build_recordings_recording_pids_filter(tmp_path):
    import os, sqlite3, ttn_spine as S
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    ctx = S.build_context(conn)
    allr = S.build_recordings(conn, ctx=ctx)
    pick = set(list(allr)[:3])
    sub = S.build_recordings(conn, ctx=ctx, recording_pids=pick)
    assert set(sub) == pick
    con = S.build_contributors(conn, ctx=ctx, recording_pids=pick)
    assert set(con) <= pick


@pytest.mark.live
def test_live_build_recordings_length_band(tmp_path):
    import os, sqlite3, ttn_spine as S
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    ctx = S.build_context(conn)
    longr = S.build_recordings(conn, ctx=ctx, min_seconds=1200)   # >= 20 min
    assert longr
    assert all(r.duration_seconds is not None and r.duration_seconds >= 1200
               for r in longr.values())
    # contributors restricted to the same long-only segment rows
    con = S.build_contributors(conn, ctx=ctx, min_seconds=1200)
    assert set(con) <= set(longr)
