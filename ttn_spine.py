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

Recording = namedtuple("Recording",
    "recording_pid composer_identity composer_display composer_mbid "
    "duration_seconds segment_title airing_count first_aired last_aired")

def _passes(date, after, before):
    return (after is None or date >= after) and (before is None or date <= before)

def build_recordings(conn, *, after=None, before=None, composer=None):
    seg = load_seg_rows(conn)
    name_mbid, mbid_display = build_name_mbid_maps(seg)
    agg = {}  # rp -> dict
    q = """SELECT s.recording_pid, substr(e.broadcast_date,1,10) AS date,
                  s.composer_name, s.composer_mbid, s.duration_seconds, s.track_title
           FROM segment_events s JOIN episodes e ON e.pid = s.episode_pid"""
    for rp, date, cn, cm, dur, tt in conn.execute(q):
        if not _passes(date, after, before):
            continue
        if composer and composer.lower() not in (cn or "").lower():
            continue
        a = agg.setdefault(rp, {"n":0, "cn":cn, "cm":cm, "dur":dur, "tt":tt,
                                "first":date, "last":date, "names":Counter()})
        a["n"] += 1
        a["first"] = min(a["first"], date); a["last"] = max(a["last"], date)
        a["names"][cn] += 1
    out = {}
    for rp, a in agg.items():
        ident, mbid = resolve_identity(a["cn"], a["cm"], name_mbid, role="Composer")
        disp = _display_name(ident, mbid, a["names"], mbid_display, is_composer=True)
        out[rp] = Recording(rp, ident, disp, mbid, a["dur"], a["tt"], a["n"],
                            a["first"], a["last"])
    return out

def _display_name(ident, mbid, name_counter, mbid_display, *, is_composer):
    if mbid:
        return mbid_display.get(mbid) or name_counter.most_common(1)[0][0]
    best = name_counter.most_common(1)[0][0]
    if is_composer:
        rk = ident[len("name:"):]               # resolved canonical key
        return override_composer_display(rk, "composer", best)
    return best

Contributor = namedtuple("Contributor", "role identity_key display_name mbid")

def build_contributors(conn, *, after=None, before=None, composer=None):
    seg = load_seg_rows(conn)
    name_mbid, mbid_display = build_name_mbid_maps(seg)
    # rp -> role -> identity_key -> {mbid, names Counter}
    acc = defaultdict(lambda: defaultdict(dict))
    for r in seg:
        if not _passes(r.date, after, before):
            continue
        if composer and composer.lower() not in (r.composer_name or "").lower():
            continue
        if not r.role or not r.name:
            continue
        ident, mbid = resolve_identity(r.name, r.mbid, name_mbid, role=r.role)
        slot = acc[r.recording_pid][r.role].setdefault(ident,
                    {"mbid": mbid, "names": Counter()})
        slot["names"][r.name] += 1
    out = {}
    for rp, by_role in acc.items():
        clist = []
        for role, idents in by_role.items():
            for ident, info in idents.items():
                disp = _display_name(ident, info["mbid"], info["names"],
                                     mbid_display, is_composer=(role == "Composer"))
                clist.append(Contributor(role, ident, disp, info["mbid"]))
        out[rp] = clist
    return out
