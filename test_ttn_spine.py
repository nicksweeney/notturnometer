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
