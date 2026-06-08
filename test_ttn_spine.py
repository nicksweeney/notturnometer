import json, os, sqlite3
import pytest
import ttn_spine as S

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
