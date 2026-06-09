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
