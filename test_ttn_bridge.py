import json, os, sqlite3
import pytest
import ttn_bridge as B

def _mkdb(pid_rows=(), text_rows=()):
    """pid_rows: segment_events tuples (recording_pid, episode_pid, position,
       composer_name, composer_mbid, duration_seconds, track_title,
       contributions(list of dicts), date).
    text_rows: tracks tuples (episode_pid, position, time_str, composer, title,
       performers, date).
    Episodes are created from both sides; a text episode is any episode with
    NO segment_events row (that is exactly what the bridge scopes to)."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT)")
    c.execute("""CREATE TABLE segment_events (event_pid TEXT, episode_pid TEXT,
        position INT, recording_pid TEXT, composer_name TEXT, composer_mbid TEXT,
        duration_seconds INT, track_title TEXT, contributions_json TEXT)""")
    c.execute("""CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT,
        composer TEXT, title TEXT, performers TEXT)""")
    eps = {}
    for i, (rp, ep, pos, cn, cm, dur, tt, contribs, date) in enumerate(pid_rows):
        eps.setdefault(ep, date)
        c.execute("INSERT INTO segment_events VALUES (?,?,?,?,?,?,?,?,?)",
                  (f"ev{i}", ep, pos, rp, cn, cm, dur, tt, json.dumps(contribs)))
    for (ep, pos, ts, comp, title, perf, date) in text_rows:
        eps.setdefault(ep, date)
        c.execute("INSERT INTO tracks VALUES (?,?,?,?,?,?)", (ep, pos, ts, comp, title, perf))
    for ep, date in eps.items():
        c.execute("INSERT INTO episodes VALUES (?,?)", (ep, date))
    c.commit()
    return c

def test_load_text_only_tracks_excludes_segment_episodes():
    db = _mkdb(
        pid_rows=[("rP","ePID",1,"Bach","mB",600,"X",
                   [{"name":"Bach","role":"Composer","musicbrainz_gid":"mB"}],"2015-01-01")],
        text_rows=[("eTXT",0,"12:31 AM","Bach","Goldberg Variations","Glenn Gould (piano)","2011-01-01")],
    )
    rows = B.load_text_only_tracks(db)
    eps = {r[0] for r in rows}                      # row[0] = episode_pid
    assert "eTXT" in eps and "ePID" not in eps      # PID-covered episode excluded

def test_text_recording_key_is_stable_and_composite():
    tr = B.TextRec("mBach","Bach","§bwv988|988|","Goldberg Variations",
                   frozenset(), frozenset({"mGould"}), frozenset(), frozenset(),
                   False, 60, 1, "2011-01-01", "2011-01-01", True,
                   frozenset({"glenn gould"}))
    k = B.text_recording_key(tr)
    assert isinstance(k, str) and "mBach" in k and "§bwv988|988|" in k
    assert k == B.text_recording_key(tr)            # deterministic

def test_pid_signatures_buckets_seven_roles_into_three():
    db = _mkdb(pid_rows=[
        ("rP","e1",1,"Sibelius","mSib",600,"Symphony No 5 in E flat, Op 82",
         [{"name":"Sibelius","role":"Composer","musicbrainz_gid":"mSib"},
          {"name":"Simon Rattle","role":"Conductor","musicbrainz_gid":"mRat"},
          {"name":"CBSO","role":"Orchestra","musicbrainz_gid":"mCbso"},
          {"name":"Janet Baker","role":"Singer","musicbrainz_gid":"mBak"},
          {"name":"Steven Isserlis","role":"Performer","musicbrainz_gid":"mIss"}],
         "2015-01-01")])
    ctx = B.build_context(db)
    sigs = B.pid_signatures(db, ctx)
    s = sigs["rP"]
    assert s.composer_identity == "mSib" and s.duration_seconds == 600
    assert s.conductors == frozenset({"mRat"})
    assert s.ensembles == frozenset({"mCbso"})
    assert s.soloists == frozenset({"mBak", "mIss"})   # Singer + Performer
    assert s.work_key                                  # non-empty (see note)

def _gould(date, ep, perf="Glenn Gould (piano)"):
    return (ep, 0, "12:31 AM", "Bach", "Goldberg Variations, BWV 988", perf, date)

def test_text_recordings_cluster_lifts_identities_and_keeps():
    # Gould plays Goldberg twice (a cluster); 'Glenn Gould' also appears in the
    # PID era with an MBID, so the backfill lifts the text name -> mGould.
    db = _mkdb(
        pid_rows=[("rPID","ePID",1,"Bach","mB",600,"Goldberg Variations, BWV 988",
                   [{"name":"Bach","role":"Composer","musicbrainz_gid":"mB"},
                    {"name":"Glenn Gould","role":"Performer","musicbrainz_gid":"mGould"}],
                   "2015-01-01")],
        text_rows=[_gould("2011-01-01","eT1"), _gould("2011-06-01","eT2")],
    )
    ctx = B.build_context(db)
    trs = B.text_recordings(db, ctx)
    assert len(trs) == 1
    tr = trs[0]
    assert tr.soloists == frozenset({"mGould"})     # lifted to MBID via backfill
    assert tr.airing_count == 2 and tr.is_singleton is False
    assert tr.composer_identity == "mB"

def test_text_recordings_strong_singleton_kept_weak_dropped():
    db = _mkdb(
        pid_rows=[("rPID","ePID",1,"Bach","mB",600,"Goldberg Variations, BWV 988",
                   [{"name":"Bach","role":"Composer","musicbrainz_gid":"mB"},
                    {"name":"Glenn Gould","role":"Performer","musicbrainz_gid":"mGould"}],
                   "2015-01-01")],
        text_rows=[
            _gould("2011-01-01","eStrong"),                                  # soloist -> MBID: KEEP
            ("eWeak",0,"01:00 AM","Bach","Goldberg Variations, BWV 988",
             "Some Unknown Pianist (piano)","2011-02-01"),                   # no MBID: DROP
        ],
    )
    ctx = B.build_context(db)
    trs = B.text_recordings(db, ctx)
    solos = [tr.soloists for tr in trs]
    assert frozenset({"mGould"}) in solos              # strong singleton kept
    assert all(not (tr.is_singleton and not (B._mbids(tr.conductors) or B._mbids(tr.soloists)))
               for tr in trs)                          # no weak singleton survived

def test_text_recordings_chamber_flag_by_name():
    db = _mkdb(text_rows=[
        ("eq1",0,"12:31 AM","Haydn","String Quartet in C, Op 76 No 3",
         "Takacs Quartet","2011-03-01"),
        ("eq2",0,"12:31 AM","Haydn","String Quartet in C, Op 76 No 3",
         "Takacs Quartet","2011-04-01"),
    ])
    ctx = B.build_context(db)
    tr = B.text_recordings(db, ctx)[0]
    # bare ensemble name (no role parens) -> degraded, all names to ensembles
    assert tr.ensembles and tr.chamber_ensembles == tr.ensembles   # 'Quartet' -> chamber

def _pid(work="§w", cond=(), solo=(), ens=(), dur=600, comp="mC", rp="rP", wdisp="Work"):
    return B.PidSig(rp, comp, "Comp", work, wdisp, frozenset(cond), frozenset(solo),
                    frozenset(ens), dur, 5, "2014-01-01", "2018-01-01")

def _txt(work="§w", cond=(), solo=(), ens=(), chamber=(), degraded=False,
         lp=10, comp="mC"):
    return B.TextRec(comp, "Comp", work, "Work", frozenset(cond), frozenset(solo),
                     frozenset(ens), frozenset(chamber), degraded, lp, 1,
                     "2011-01-01", "2011-01-01", True, frozenset({"x"}))

def test_score_trusted_on_matched_soloist_and_duration():
    ms = B.score_match(_txt(solo=["mSolo"], lp=10), _pid(solo=["mSolo"], dur=600))
    assert ms.tier == "trusted"

def test_score_gate_fails_on_work_or_composer():
    assert B.score_match(_txt(work="§a"), _pid(work="§b")).tier == "none"
    assert B.score_match(_txt(comp="mA"), _pid(comp="mB")).tier == "none"

def test_score_conductor_contradiction_vetoes():
    ms = B.score_match(_txt(cond=["mX"], solo=["mSolo"]),
                       _pid(cond=["mY"], solo=["mSolo"]))
    assert ms.tier == "none" and ms.detail == "veto"

def test_score_no_credit_overlap_is_none():
    assert B.score_match(_txt(solo=["mA"]), _pid(solo=["mB"])).tier == "none"

def test_score_orchestra_alone_is_candidate_not_trusted():
    # matched orchestra (ensembles), no conductor/soloist, not chamber -> candidate
    ms = B.score_match(_txt(ens=["mOrch"]), _pid(ens=["mOrch"]))
    assert ms.tier == "candidate"

def test_score_chamber_ensemble_alone_can_be_trusted():
    ms = B.score_match(_txt(ens=["mQ"], chamber=["mQ"], lp=10), _pid(ens=["mQ"], dur=600))
    assert ms.tier == "trusted"

def test_score_duration_contradiction_demotes_to_candidate():
    ms = B.score_match(_txt(solo=["mSolo"], lp=60), _pid(solo=["mSolo"], dur=600))  # 10 vs 60 min
    assert ms.tier == "candidate"

def test_score_degraded_text_never_trusted():
    ms = B.score_match(_txt(solo=["mSolo"], degraded=True, lp=10), _pid(solo=["mSolo"], dur=600))
    assert ms.tier == "candidate"

def test_score_missing_proxy_does_not_block_trusted():
    ms = B.score_match(_txt(solo=["mSolo"], lp=None), _pid(solo=["mSolo"], dur=600))
    assert ms.tier == "trusted"

def test_bridge_unique_trusted_auto_links():
    tr = _txt(solo=["mSolo"], lp=10)
    ps = {"rP": _pid(solo=["mSolo"], dur=600, rp="rP")}
    res = B.bridge([tr], ps, {})
    assert len(res.trusted) == 1 and res.trusted[0].pid_sig.recording_pid == "rP"
    assert not res.candidates and not res.unmatched

def test_bridge_ambiguous_two_trusted_become_candidates():
    tr = _txt(solo=["mSolo"], lp=10)
    ps = {"rP": _pid(solo=["mSolo"], dur=600, rp="rP"),
          "rQ": _pid(solo=["mSolo"], dur=600, rp="rQ")}
    res = B.bridge([tr], ps, {})
    assert not res.trusted and len(res.candidates) == 2     # ambiguous -> all candidates

def test_bridge_reject_removes_link_then_unmatched():
    tr = _txt(solo=["mSolo"], lp=10)
    ps = {"rP": _pid(solo=["mSolo"], dur=600, rp="rP")}
    decisions = {B.text_recording_key(tr): {"rP": "reject"}}
    res = B.bridge([tr], ps, decisions)
    assert not res.trusted and not res.candidates and res.unmatched == [tr]

def test_bridge_accept_promotes_candidate_to_link():
    tr = _txt(ens=["mOrch"], lp=10)                          # orchestra-alone -> candidate tier
    ps = {"rP": _pid(ens=["mOrch"], dur=600, rp="rP")}
    decisions = {B.text_recording_key(tr): {"rP": "accept"}}
    res = B.bridge([tr], ps, decisions)
    assert len(res.trusted) == 1 and res.trusted[0].tier == "accepted"

def test_bridge_unmatched_when_no_bucket():
    tr = _txt(work="§lonely", solo=["mSolo"])
    res = B.bridge([tr], {"rP": _pid(work="§other", solo=["mSolo"])}, {})
    assert res.unmatched == [tr]

def test_decisions_round_trip(tmp_path):
    p = tmp_path / "d.json"
    B.save_decision(str(p), "ck1|§w|gould", "rP", "reject", note="diff perf")
    d = B.load_decisions(str(p))
    assert d["ck1|§w|gould"]["rP"] == "reject"

# ---------------------------------------------------------------------------
# Live tests (require ttn.sqlite; deselected by default via pyproject addopts)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def live_db():
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    return sqlite3.connect("ttn.sqlite")

@pytest.fixture(scope="module")
def live_result(live_db):
    ctx = B.build_context(live_db)
    pid_sigs = B.pid_signatures(live_db, ctx)
    text_recs = B.text_recordings(live_db, ctx)
    return B.bridge(text_recs, pid_sigs, B.load_decisions()), pid_sigs

@pytest.mark.live
def test_live_brahms_osborne_trusted_link(live_result):
    result, _pid = live_result
    # 2010-12-26 Brahms Rhapsody Op.79/1 / Steven Osborne -> recording p00sx1gr
    assert any(lk.pid_sig.recording_pid == "p00sx1gr" for lk in result.trusted), \
        "Brahms/Osborne should trusted-link to p00sx1gr"

@pytest.mark.live
def test_live_bridge_has_trusted_and_tail(live_result):
    result, _pid = live_result
    assert len(result.trusted) > 50            # the bridge links a real population
    assert len(result.unmatched) > 0           # the honest pre-2012-only tail exists
    # trusted links never duplicate a (text_key, recording_pid) pair
    seen = [(B.text_recording_key(lk.text_rec), lk.pid_sig.recording_pid)
            for lk in result.trusted]
    assert len(seen) == len(set(seen))

def test_pid_signatures_carry_segment_title(tmp_path, monkeypatch):
    """PidSig.work_display is the recording's stable segment title (SP-2010-12)."""
    import ttn_bridge as B
    # PidSig must expose work_display between work_key and the credit buckets.
    fields = B.PidSig._fields
    assert "work_display" in fields
    assert fields.index("work_display") == fields.index("work_key") + 1


def test_relaxed_score_matches_across_different_work_key():
    """Same composer+soloist+duration but DIFFERENT work_key -> trusted under
    relaxed (score_match would gate it to 'none')."""
    import ttn_bridge as B
    t = _txt(work="§a", solo=["mSolo"], lp=10)
    p = _pid(work="§b", solo=["mSolo"], dur=600)
    assert B.score_match(t, p).tier == "none"          # strict still gates
    assert B.relaxed_score(t, p).tier == "trusted"      # relaxed does not


def test_relaxed_score_still_gates_composer_veto_overlap_duration():
    import ttn_bridge as B
    # composer still gates
    assert B.relaxed_score(_txt(comp="mA", work="§a"), _pid(comp="mB", work="§b")).tier == "none"
    # contradiction veto still fires
    assert B.relaxed_score(_txt(cond=["mX"], solo=["mS"], work="§a"),
                           _pid(cond=["mY"], solo=["mS"], work="§b")).tier == "none"
    # no performer overlap -> none
    assert B.relaxed_score(_txt(solo=["mA"], work="§a"), _pid(solo=["mB"], work="§b")).tier == "none"
    # duration mismatch demotes trusted->candidate (10 vs 60 min)
    assert B.relaxed_score(_txt(solo=["mS"], lp=60, work="§a"),
                           _pid(solo=["mS"], dur=600, work="§b")).tier == "candidate"


def test_relaxed_links_surfaces_diff_workkey_and_skips_same(monkeypatch):
    import ttn_bridge as B
    pid   = _pid(work="sonata in g", solo=["mSolo"], dur=600, rp="rREC")
    t_var = _txt(work="sonata g major", solo=["mSolo"], lp=10)   # diff key, shares 'sonata'
    t_ok  = _txt(work="sonata in g", solo=["mSolo"], lp=10)      # same key -> already agrees
    links = B.relaxed_links([t_var, t_ok], {"rREC": pid}, {})
    assert len(links) == 1
    lk = links[0]
    assert lk.text_rec is t_var and lk.pid_sig.recording_pid == "rREC"
    assert lk.method == "relaxed-work" and lk.tier == "strong"


def test_relaxed_links_respects_reject_ledger():
    import ttn_bridge as B
    t = _txt(work="sonata g major", solo=["mSolo"], lp=10)
    pid = _pid(work="sonata in g", solo=["mSolo"], dur=600, rp="rREC")
    decisions = {B.text_recording_key(t): {"rREC": "reject"}}
    assert B.relaxed_links([t], {"rREC": pid}, decisions) == []


def test_relaxed_links_requires_work_key_token_overlap():
    """Same composer+soloist+duration, different work_key: kept when the keys
    share a significant token, dropped when they share none (a prolific soloist's
    two unrelated works must not cross-link)."""
    import ttn_bridge as B
    keep_t = _txt(work="violin concerto", solo=["mS"], lp=10)
    keep_p = _pid(work="concerto for violin orchestra", solo=["mS"], dur=600, rp="rKEEP")
    drop_t = _txt(work="etudes grandes paganini s141", solo=["mS"], lp=10)
    drop_p = _pid(work="chapelle guillaume tell s160", solo=["mS"], dur=600, rp="rDROP")
    links = B.relaxed_links([keep_t, drop_t], {"rKEEP": keep_p, "rDROP": drop_p}, {})
    assert {lk.pid_sig.recording_pid for lk in links} == {"rKEEP"}


def test_bridge_alias_candidates_emits_and_skips_dead():
    import ttn_bridge as B
    # injected keyers: work_title_key folds case; resolve is identity (no chains)
    wtk = lambda title, composer=None: title.lower()
    resolve = lambda key: key
    link_fold = B.Link(_txt(work="§a"), _pid(work="§b", wdisp="Fingal's Cave"), "strong", "relaxed-work")
    # text_rec.work_display defaults to "Work"; make a dead pair (same key)
    link_dead = B.Link(_txt(work="§c"), _pid(work="§d", wdisp="work"), "weak", "relaxed-work")
    cands = B.bridge_alias_candidates([link_fold, link_dead],
                                      work_title_key=wtk, resolve_work_alias=resolve)
    assert len(cands) == 1                                   # the dead pair dropped
    c = cands[0]
    assert c.variant == "Work" and c.preferred == "Fingal's Cave"
    assert c.tier == "strong" and c.chained is False


def test_bridge_alias_candidates_flags_chained_preferred():
    import ttn_bridge as B
    wtk = lambda title, composer=None: title.lower()
    resolve = lambda key: "final" if key == "fingal's cave" else key   # preferred redirects
    link = B.Link(_txt(work="§a"), _pid(work="§b", wdisp="Fingal's Cave"), "strong", "relaxed-work")
    c = B.bridge_alias_candidates([link], work_title_key=wtk, resolve_work_alias=resolve)[0]
    assert c.chained is True


def test_main_relaxed_accept_writes_relaxed_method(tmp_path, monkeypatch):
    import ttn_bridge as B
    path = tmp_path / "dec.json"
    monkeypatch.setattr(B, "DECISIONS_PATH", str(path))
    B.main(["x.sqlite", "--relaxed", "--accept", "mBach|§a|x  |  rREC"])
    import json
    data = json.loads(path.read_text())
    v = data["verdicts"][-1]
    assert v["verdict"] == "accept" and v["method"] == "relaxed-work"


@pytest.mark.live
def test_relaxed_finds_a_cross_era_title_variant():
    """Smoke: the relaxed pass produces some cross-era title-variant links on the
    real corpus (the strict bridge's work_key gate misses these)."""
    import sqlite3, ttn_bridge as B
    conn = sqlite3.connect("ttn.sqlite")
    ctx = B.build_context(conn)
    pid_sigs = B.pid_signatures(conn, ctx)
    text_recs = B.text_recordings(conn, ctx, after="2010-01-17", before="2012-03-15")
    result = B.bridge(text_recs, pid_sigs, B.load_decisions())
    links = B.relaxed_links(result.unmatched, pid_sigs, {})
    assert links, "expected at least one relaxed cross-era link in 2010-2012"
    assert all(lk.text_rec.work_key != lk.pid_sig.work_key for lk in links)
    assert all(lk.method == "relaxed-work" for lk in links)
