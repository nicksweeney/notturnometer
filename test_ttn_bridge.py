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

def _pid(work="§w", cond=(), solo=(), ens=(), dur=600, comp="mC", rp="rP"):
    return B.PidSig(rp, comp, "Comp", work, frozenset(cond), frozenset(solo),
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
