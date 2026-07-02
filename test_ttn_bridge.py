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
        duration_seconds INT, track_title TEXT, contributions_json TEXT,
        record_label TEXT)""")
    c.execute("""CREATE TABLE tracks (episode_pid TEXT, position INT, time_str TEXT,
        composer TEXT, title TEXT, performers TEXT)""")
    eps = {}
    for i, (rp, ep, pos, cn, cm, dur, tt, contribs, date) in enumerate(pid_rows):
        eps.setdefault(ep, date)
        c.execute("INSERT INTO segment_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (f"ev{i}", ep, pos, rp, cn, cm, dur, tt, json.dumps(contribs), None))
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

def test_score_degraded_non_chamber_stays_candidate():
    # a degraded credit discriminated only by a soloist (not a chamber ensemble)
    # still caps at candidate
    ms = B.score_match(_txt(solo=["mSolo"], degraded=True, lp=10), _pid(solo=["mSolo"], dur=600))
    assert ms.tier == "candidate"

def test_score_degraded_chamber_match_can_be_trusted():
    # a bare-ensemble (degraded) credit whose CHAMBER-ensemble MBID matches the
    # recording's ensemble is still trusted: for a string quartet / piano trio the
    # bare ensemble name IS the complete credit and the clean MBID match is strong.
    # This is the cross-lingual-stranded-recording recovery (Wolf / Ljubljana).
    ms = B.score_match(_txt(ens=["mQ"], chamber=["mQ"], degraded=True, lp=10),
                       _pid(ens=["mQ"], dur=600))
    assert ms.tier == "trusted"

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


def test_render_relaxed_candidates_sorts_strong_first_then_airings():
    """The worklist surfaces [strong] before [weak], and high-airing folds first,
    so the top-N slice is the highest-value (a 3k-item list)."""
    import ttn_bridge as B
    strong_hi = B.Link(_txt(work="a sonata"), _pid(work="sonata b", rp="rSHI"), "strong", "relaxed-work")
    strong_lo = B.Link(_txt(work="a sonata"), _pid(work="sonata c", rp="rSLO"), "strong", "relaxed-work")
    weak_hi   = B.Link(_txt(work="a sonata"), _pid(work="sonata d", rp="rWHI"), "weak", "relaxed-work")
    # strong_hi has the most airings, strong_lo fewer; weak_hi has many but is weak
    strong_hi = strong_hi._replace(text_rec=strong_hi.text_rec._replace(airing_count=9))
    strong_lo = strong_lo._replace(text_rec=strong_lo.text_rec._replace(airing_count=2))
    weak_hi   = weak_hi._replace(text_rec=weak_hi.text_rec._replace(airing_count=50))
    out = B.render_relaxed_candidates([weak_hi, strong_lo, strong_hi])
    i_shi, i_slo, i_whi = out.index("rSHI"), out.index("rSLO"), out.index("rWHI")
    assert i_shi < i_slo < i_whi          # strong-by-airings first, weak last


def test_bridge_alias_candidates_skips_already_grouped_via_existing_alias():
    """A fold whose two titles already resolve to the same canonical (an existing
    alias handles it) is dropped — not just literal same-key dead pairs. This is
    the gap that let the Falla/Bach/Vivaldi/Weber redundant folds through."""
    import ttn_bridge as B
    wtk = lambda title, composer=None: title.lower()
    resolve = lambda key: "canon" if key in ("a", "b") else key  # a,b -> same canonical
    link = B.Link(_txt(work="x"), _pid(work="y", wdisp="b"), "strong", "relaxed-work")
    link = link._replace(text_rec=link.text_rec._replace(work_display="a"))
    cands = B.bridge_alias_candidates([link], work_title_key=wtk, resolve_work_alias=resolve)
    assert cands == []


def test_bridge_alias_candidates_skips_variant_that_is_existing_canonical():
    """A fold whose VARIANT is an existing alias target (a canonical others fold
    to) is skipped — redirecting it would chain those existing aliases (the
    Falla/Bach/Vivaldi/Weber/Poulenc trap)."""
    import ttn_bridge as B
    wtk = lambda title, composer=None: title.lower()
    resolve = lambda key: key
    link = B.Link(_txt(work="x"), _pid(work="y", wdisp="seg"), "strong", "relaxed-work")
    link = link._replace(text_rec=link.text_rec._replace(work_display="canon"))  # vk='canon'
    # canon is an existing alias target -> must be skipped
    assert B.bridge_alias_candidates([link], work_title_key=wtk, resolve_work_alias=resolve,
                                     alias_targets=frozenset({"canon"})) == []
    # not a target -> emitted as before
    assert len(B.bridge_alias_candidates([link], work_title_key=wtk, resolve_work_alias=resolve,
                                         alias_targets=frozenset())) == 1


def test_auto_markers_and_extractors():
    import ttn_bridge as B
    assert B._ANNOTATION_RE.search("symphony do not use again")
    assert B._ANNOTATION_RE.search("concerto [doubtful]")
    assert B._ALTSCORING_RE.search("danish suite vers. orchestral")
    assert B._ALTSCORING_RE.search("widmung transc. for piano")
    assert B._EXCERPT_RE.search("piano sonata no 1 - ivb movement")
    assert not B._EXCERPT_RE.search("symphony no 3 in a minor")   # bare 'no N' is not an excerpt
    assert B._MOVEMENT_KEY_RE.match("§bwv1068|air")               # catalogue movement-slug
    assert not B._MOVEMENT_KEY_RE.match("§bwv988|988|")           # whole-work catalogue
    assert B._key_sig("Violin sonata in C minor, Op 24") == ("c", "minor")
    assert B._key_sig("Sonata in B flat major") == ("b flat", "major")
    assert B._key_sig("Tarantella for guitar") is None
    assert B._work_num("Symphony No.3 in A minor") == "3"
    assert B._work_num("Sonata for piano no. 5") == "5"
    assert B._work_num("Tarantella for guitar") is None


def _autolink(text_title, seg_title, *, tier="strong", vkey=None, pkey=None):
    """A Link with controlled display titles (vkey/pkey override the keys the
    injected work_title_key would produce; default = lowercased title)."""
    import ttn_bridge as B
    tr = _txt(work=(vkey if vkey is not None else text_title.lower()))._replace(work_display=text_title)
    ps = _pid(work=(pkey if pkey is not None else seg_title.lower()), wdisp=seg_title)
    return B.Link(tr, ps, tier, "relaxed-work")

_WTK = lambda title, composer=None: title.lower()
_RESOLVE = lambda key: key

def _reason(link, cluster_size=1, *, alias_targets=frozenset()):
    import ttn_bridge as B
    return B._auto_fold_reason(link, cluster_size, work_title_key=_WTK,
                               resolve_work_alias=_RESOLVE, alias_targets=alias_targets)

def test_auto_fold_reason_accepts_clean_single_rephrasing():
    lk = _autolink("Violin Concerto", "Violin Concerto in B minor",
                   vkey="violin concerto", pkey="violin concerto b minor")
    assert _reason(lk) == ""                       # accept

def test_auto_fold_reason_defers_cluster_weak_guarded():
    lk = _autolink("Violin Concerto", "Violin Concerto in B minor",
                   vkey="violin concerto", pkey="violin concerto b minor")
    assert _reason(lk, cluster_size=2) == "cluster"
    assert _reason(lk._replace(tier="weak")) == "weak"
    assert _reason(lk, alias_targets=frozenset({"violin concerto"})) == "guarded"

def test_auto_fold_reason_defers_trap_markers():
    assert _reason(_autolink("Concerto in A minor", "Concerto in A minor DO NOT USE",
                             vkey="concerto a minor", pkey="concerto a minor")) == "annotation"
    assert _reason(_autolink("Danish Suite", "Danish suite vers. orchestral",
                             vkey="danish suite", pkey="danish suite vers orchestral")) == "alt-scoring"
    assert _reason(_autolink("Piano Sonata", "Piano Sonata - IVb movement",
                             vkey="piano sonata", pkey="piano sonata ivb movement")) == "excerpt"
    assert _reason(_autolink("Air from Suite (BWV.1068)", "Air, Overture, BWV1068",
                             vkey="§bwv1068|air", pkey="§bwv1068|1068,3|d")) == "catalogue-excerpt"

def test_auto_fold_reason_defers_key_and_number_conflicts():
    assert _reason(_autolink("Sonata in C minor", "Sonata in D minor",
                             vkey="sonata c minor", pkey="sonata d minor")) == "key-conflict"
    assert _reason(_autolink("Symphony No 1", "Symphony No 4, H.305",
                             vkey="symphony 1", pkey="symphony 4 h305")) == "number-conflict"

def test_auto_fold_reason_defers_low_overlap():
    assert _reason(_autolink("Etudes Paganini S141", "Chapelle Guillaume Tell S160",
                             vkey="etudes grandes paganini s141",
                             pkey="chapelle guillaume tell s160")) == "low-overlap"

def test_auto_fold_ok_is_reason_empty():
    import ttn_bridge as B
    lk = _autolink("Violin Concerto", "Violin Concerto in B minor",
                   vkey="violin concerto", pkey="violin concerto b minor")
    assert B.auto_fold_ok(lk, 1, work_title_key=_WTK, resolve_work_alias=_RESOLVE,
                          alias_targets=frozenset()) is True

def test_auto_fold_candidates_groups_and_tallies():
    import ttn_bridge as B
    # two links share ONE text-recording (a cluster) -> both defer 'cluster';
    # a third is a clean single-candidate -> accepted.
    cl_a = _autolink("Symphony Op 10", "Symphony in C, Op 10 no 4",
                     vkey="symphony op 10", pkey="symphony c op 10 no 4")
    cl_b = _autolink("Symphony Op 10", "Symphony in D, Op 10 no 5",
                     vkey="symphony op 10", pkey="symphony d op 10 no 5")
    shared = cl_a.text_rec
    cl_b = cl_b._replace(text_rec=shared)
    cl_a = cl_a._replace(text_rec=shared)
    solo = _autolink("Violin Concerto", "Violin Concerto in B minor",
                     vkey="violin concerto", pkey="violin concerto b minor")
    accepted, reasons = B.auto_fold_candidates(
        [cl_a, cl_b, solo], {}, work_title_key=_WTK, resolve_work_alias=_RESOLVE,
        alias_targets=frozenset())
    assert [lk.pid_sig.recording_pid for lk in accepted] == [solo.pid_sig.recording_pid]
    assert reasons["cluster"] == 2

def test_auto_fold_candidates_skips_already_decided():
    import ttn_bridge as B
    solo = _autolink("Violin Concerto", "Violin Concerto in B minor",
                     vkey="violin concerto", pkey="violin concerto b minor")
    decisions = {B.text_recording_key(solo.text_rec): {solo.pid_sig.recording_pid: "reject"}}
    accepted, reasons = B.auto_fold_candidates(
        [solo], decisions, work_title_key=_WTK, resolve_work_alias=_RESOLVE,
        alias_targets=frozenset())
    assert accepted == []


def test_main_relaxed_auto_dry_run_writes_nothing(tmp_path, monkeypatch):
    """--relaxed --auto --dry-run must not touch the ledger."""
    import ttn_bridge as B
    path = tmp_path / "dec.json"
    monkeypatch.setattr(B, "DECISIONS_PATH", str(path))
    solo = _autolink("Violin Concerto", "Violin Concerto in B minor",
                     vkey="violin concerto", pkey="violin concerto b minor")
    monkeypatch.setattr(B, "build_context", lambda conn: object())
    monkeypatch.setattr(B, "pid_signatures", lambda conn, ctx: {})
    monkeypatch.setattr(B, "text_recordings", lambda conn, ctx, **k: [])
    monkeypatch.setattr(B, "bridge", lambda *a, **k: B.BridgeResult([], [], []))
    monkeypatch.setattr(B, "relaxed_links", lambda *a, **k: [solo])
    monkeypatch.setattr(B, "open_db", lambda db, ap: object())
    B.main(["x.sqlite", "--relaxed", "--auto", "--dry-run"])
    assert not path.exists()                               # nothing written


@pytest.mark.live
def test_auto_fold_dry_run_on_real_corpus():
    """The auto pass produces a plausible non-zero accepted set on ttn.sqlite, and
    every accepted link is single-candidate + strong + free of trap markers."""
    import sqlite3, ttn_bridge as B
    from ttn_analyze import work_title_key, resolve_work_alias, WORK_ALIASES
    conn = sqlite3.connect("ttn.sqlite")
    ctx = B.build_context(conn)
    pid_sigs = B.pid_signatures(conn, ctx)
    text_recs = B.text_recordings(conn, ctx, after="2010-01-17", before="2012-03-15")
    links = B.relaxed_links(B.bridge(text_recs, pid_sigs, B.load_decisions()).unmatched,
                            pid_sigs, B.load_decisions())
    targets = frozenset(WORK_ALIASES.values())
    # Empty decisions: test the PREDICATE on fresh candidates, independent of
    # what the operational --auto run has already ratified into the ledger.
    # With a populated ledger every auto-acceptable link is already decided and
    # skipped, so accepted would be empty — that's consumed state, not a broken
    # predicate.
    accepted, reasons = B.auto_fold_candidates(
        links, {}, work_title_key=work_title_key,
        resolve_work_alias=resolve_work_alias, alias_targets=targets)
    assert accepted, "expected some auto-acceptable folds"
    assert reasons["cluster"] > 0
    for lk in accepted:
        for s in (lk.text_rec.work_display, lk.pid_sig.work_display):
            assert not B._ANNOTATION_RE.search(s) and not B._ALTSCORING_RE.search(s)


def test_auto_fold_reason_hardening_new_defers():
    # excerpt-plural bug: 'Excerpts' on seg only
    assert _reason(_autolink("Romeo and Juliet Op 64", "Romeo and Juliet Op 64 (Excerpts)",
                             vkey="romeo juliet op 64", pkey="romeo juliet op 64 excerpts")) == "excerpt"
    # 'orig.' alt-scoring
    assert _reason(_autolink("Suru Op 22 no 2", "Suru, Op 22 no 2 (orig. cello and orchestra)",
                             vkey="suru op 22 no 2", pkey="suru op 22 no 2 orig cello orchestra")) == "alt-scoring"
    # opus conflict
    assert _reason(_autolink("4 Songs Op 142", "6 Songs Op 107",
                             vkey="songs op 142", pkey="songs op 107")) == "opus-conflict"
    # leading-count conflict (no opus, so opus check passes through)
    assert _reason(_autolink("4 Bagatelles", "6 Bagatelles",
                             vkey="bagatelles four", pkey="bagatelles six")) == "count-conflict"
    # selection list on seg only
    assert _reason(_autolink("20 Mazurkas Op 50", "20 Mazurkas Op 50 nos 1, 2 & 13",
                             vkey="mazurkas op 50 twenty", pkey="mazurkas op 50 nos twenty")) == "selection"
    # whole-set (leading count) vs single member
    assert _reason(_autolink("12 Fantasies for flute", "Fantasy no 4 for flute",
                             vkey="fantasies flute twelve", pkey="fantasy flute four")) == "set-vs-member"
    # generic single-token variant
    assert _reason(_autolink("Adagio", "Adagio for viola and piano in C",
                             vkey="adagio", pkey="adagio viola piano")) == "generic"
    # protected work (VW Wasps)
    assert _reason(_autolink("Overture from The Wasps", "Overture to The Wasps - Aristophanic suite",
                             vkey="overture wasps", pkey="overture wasps aristophanic suite")) == "protected"


def test_auto_fold_reason_still_accepts_clean():
    # regression: a clean two-token rephrasing still accepts
    assert _reason(_autolink("Violin Concerto", "Violin Concerto in B minor",
                             vkey="violin concerto", pkey="violin concerto b minor")) == ""


def test_airings_by_text_key_groups_by_text_recording_key(monkeypatch):
    import ttn_bridge as B
    # Two airings of the same (composer, work, credit) + one different work.
    raw = [
        ("epA", 0, "1:00 AM", "Symphony No 5", "Beethoven", "Berlin PO", "2011-01-01"),
        ("epB", 3, "2:00 AM", "Symphony no.5", "Beethoven", "Berlin PO", "2011-02-01"),
        ("epA", 1, "1:30 AM", "Symphony No 7", "Beethoven", "Berlin PO", "2011-01-01"),
    ]
    monkeypatch.setattr(B, "load_text_only_tracks", lambda conn: raw)

    class Ctx:                       # name_mbid backfill not needed for name identities
        name_mbid = {}
    out = B.airings_by_text_key(None, Ctx())
    # the two No.5 airings share a key; No.7 is its own key
    groups = sorted(sorted(v) for v in out.values())
    assert [("epA", 0), ("epB", 3)] in groups
    assert [("epA", 1)] in groups
    assert len(out) == 2


def test_precomputed_units_match_internal_pass(monkeypatch):
    import ttn_bridge as B
    raw = [
        ("epA", 0, "1:00 AM", "Symphony No 5", "Beethoven", "Berlin PO", "2011-01-01"),
        ("epB", 3, "2:00 AM", "Symphony no.5", "Beethoven", "Berlin PO", "2011-02-01"),
        ("epA", 1, "1:30 AM", "Symphony No 7", "Beethoven", "Berlin PO", "2011-01-01"),
    ]
    monkeypatch.setattr(B, "load_text_only_tracks", lambda conn: raw)

    class Ctx:
        name_mbid = {}
    units = B.load_text_units(None)
    # passing the shared units must reproduce each function's own pass exactly
    assert B.text_recordings(None, Ctx(), units=units) == B.text_recordings(None, Ctx())
    assert (B.airings_by_text_key(None, Ctx(), units=units)
            == B.airings_by_text_key(None, Ctx()))


@pytest.mark.live
def test_live_airings_cover_every_text_recording(monkeypatch):
    import os, sqlite3, ttn_bridge as B
    if not os.path.exists("ttn.sqlite"):
        pytest.skip("needs live DB")
    conn = sqlite3.connect("ttn.sqlite")
    ctx = B.build_context(conn)
    airings = B.airings_by_text_key(conn, ctx)
    text_recs = B.text_recordings(conn, ctx)
    # Every bridged text-recording must be expandable back to its airings.
    missing = [B.text_recording_key(tr) for tr in text_recs
               if B.text_recording_key(tr) not in airings]
    assert not missing, f"{len(missing)} text-recs have no airing membership"
