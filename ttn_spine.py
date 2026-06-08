"""Recording-keyed identity spine over segment_events (2012+). Offline,
in-memory, no caches. Segment-side only — additive to tracks/aliases.
See docs/superpowers/specs/2026-06-08-recording-spine-design.md."""
import argparse, json, sqlite3
from collections import Counter, defaultdict, namedtuple

from ttn_analyze import (canonical_key, work_title_key, resolve_composer_alias,
                         resolve_ensemble_alias, override_composer_display)

SegRow = namedtuple("SegRow",
    "recording_pid episode_pid event_pid date role name pid mbid "
    "composer_name composer_mbid duration_seconds track_title")

_ENSEMBLE_ROLES = {"Orchestra", "Ensemble", "Choir"}

def canon_name(name):
    return canonical_key(name or "")

def load_seg_rows(conn):
    q = """SELECT s.recording_pid, s.episode_pid, s.event_pid,
                  substr(e.broadcast_date,1,10) AS date,
                  s.composer_name, s.composer_mbid, s.duration_seconds,
                  s.track_title, s.contributions_json
           FROM segment_events s JOIN episodes e ON e.pid = s.episode_pid"""
    out = []
    for (rp, ep, ev, date, cn, cm, dur, tt, cj) in conn.execute(q):
        for c in json.loads(cj or "[]"):
            out.append(SegRow(rp, ep, ev, date, c.get("role"), c.get("name"),
                              c.get("pid"), c.get("musicbrainz_gid"),
                              cn, cm, dur, tt))
    return out

def build_name_mbid_maps(seg_rows):
    name_mbid = defaultdict(set)
    mbid_display = {}
    for r in seg_rows:
        if r.mbid:
            name_mbid[canon_name(r.name)].add(r.mbid)
            mbid_display.setdefault(r.mbid, r.name)
    return name_mbid, mbid_display

def resolve_identity(name, mbid, name_mbid_map, *, role):
    if mbid:
        return (mbid, mbid)
    ck = canon_name(name)
    seen = name_mbid_map.get(ck)
    if seen and len(seen) == 1:          # backfill-able (unambiguous)
        m = next(iter(seen))
        return (m, m)
    if role == "Composer":
        rk = resolve_composer_alias(ck)
    elif role in _ENSEMBLE_ROLES:
        rk = resolve_ensemble_alias(ck)
    else:                                # people w/o a table (conductor/performer/singer)
        rk = ck
    return ("name:" + rk, None)
