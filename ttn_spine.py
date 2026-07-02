"""Recording-keyed identity spine over segment_events (2012+). Offline,
in-memory, no caches. Segment-side only — additive to tracks/aliases.
See docs/superpowers/specs/2026-06-08-recording-spine-design.md."""
import argparse, json, sqlite3
from collections import Counter, defaultdict, namedtuple

from ttn_analyze import (canonical_key, work_title_key, resolve_work_alias,
                         resolve_composer_alias, resolve_ensemble_alias,
                         override_composer_display, ascii_fold)
from ttn_db import open_db
from ttn_segment_meta import INTERSTITIAL_RECORDING_PIDS

SegRow = namedtuple("SegRow",
    "recording_pid episode_pid event_pid date role name pid mbid "
    "composer_name composer_mbid duration_seconds track_title record_label")

_ENSEMBLE_ROLES = {"Orchestra", "Ensemble", "Choir"}

def canon_name(name):
    return canonical_key(name or "")

def load_seg_rows(conn):
    q = """SELECT s.recording_pid, s.episode_pid, s.event_pid,
                  substr(e.broadcast_date,1,10) AS date,
                  s.composer_name, s.composer_mbid, s.duration_seconds,
                  s.track_title, s.contributions_json, s.record_label
           FROM segment_events s JOIN episodes e ON e.pid = s.episode_pid"""
    out = []
    for (rp, ep, ev, date, cn, cm, dur, tt, cj, lab) in conn.execute(q):
        for c in json.loads(cj or "[]"):
            out.append(SegRow(rp, ep, ev, date, c.get("role"), c.get("name"),
                              c.get("pid"), c.get("musicbrainz_gid"),
                              cn, cm, dur, tt, lab))
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
    if not (seen and len(seen) == 1) and role in _ENSEMBLE_ROLES:
        # An ensemble alias to an MBID-bearing canonical should reach that MBID:
        # cross-lingual / city-suffix variants (Ljubljana String Quartet ->
        # Ljubljanski godalni kvartet, Rundfunk-Sinfonieorchester Saarbrücken ->
        # the English name) carry no MBID of their own, so normalize the name to
        # its alias canonical and retry the backfill. The RAW lookup ran first, so
        # a name with its own MBID is never overridden by an alias. ENSEMBLE ONLY —
        # composer aliases are NOT alias-normalized pre-backfill (that would shift
        # ~233 composer identities; out of scope here).
        aliased = resolve_ensemble_alias(ck)
        if aliased != ck:
            ck = aliased
            seen = name_mbid_map.get(ck)
    if seen and len(seen) == 1:          # backfill-able (unambiguous)
        m = next(iter(seen))
        return (m, m)
    if role == "Composer":
        rk = resolve_composer_alias(ck)
    elif role in _ENSEMBLE_ROLES:
        rk = ck                          # already alias-resolved above
    else:                                # people w/o a table (conductor/performer/singer)
        rk = ck
    return ("name:" + rk, None)

Recording = namedtuple("Recording",
    "recording_pid composer_identity composer_display composer_mbid "
    "duration_seconds segment_title airing_count first_aired last_aired")

def _passes(date, after, before):
    return (after is None or date >= after) and (before is None or date <= before)

SpineContext = namedtuple("SpineContext", "seg name_mbid mbid_display")

def build_context(conn):
    """The shared expensive prefix (load_seg_rows + build_name_mbid_maps).
    Build once and pass via ctx= to build_recordings/build_contributors to
    avoid re-parsing the corpus per pass."""
    seg = load_seg_rows(conn)
    name_mbid, mbid_display = build_name_mbid_maps(seg)
    return SpineContext(seg, name_mbid, mbid_display)

def build_recordings(conn, *, after=None, before=None, composer=None,
                     keep_interstitials=False, ctx=None, record_labels=None,
                     recording_pids=None, min_seconds=None, max_seconds=None):
    if ctx is None:
        ctx = build_context(conn)
    name_mbid, mbid_display = ctx.name_mbid, ctx.mbid_display
    # ascii-fold the composer query so 'Dvorak' matches the stored 'Dvořák',
    # consistent with the tracks-side --composer filter and ttn_broadcasters
    # (a raw case-only substring silently dropped every diacritic spelling).
    cfold = ascii_fold(composer).lower() if composer else None
    agg = {}  # rp -> dict
    q = """SELECT s.recording_pid, substr(e.broadcast_date,1,10) AS date,
                  s.composer_name, s.composer_mbid, s.duration_seconds, s.track_title,
                  s.record_label
           FROM segment_events s JOIN episodes e ON e.pid = s.episode_pid"""
    for rp, date, cn, cm, dur, tt, lab in conn.execute(q):
        if not keep_interstitials and rp in INTERSTITIAL_RECORDING_PIDS:
            continue
        if not _passes(date, after, before):
            continue
        if cfold and cfold not in ascii_fold(cn or "").lower():
            continue
        if record_labels is not None and lab not in record_labels:
            continue
        if recording_pids is not None and rp not in recording_pids:
            continue
        # Length band (segment-side; NULL duration can't satisfy a bound -> skip).
        if min_seconds is not None and (dur is None or dur < min_seconds):
            continue
        if max_seconds is not None and (dur is None or dur > max_seconds):
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

ContribStat = namedtuple("ContribStat", "identity display_name mbid airings recordings")

def rank_recordings(recordings):
    return sorted(recordings.values(),
                  key=lambda r: (-r.airing_count, r.recording_pid))

def rank_contributors(recordings, contributors, role):
    # identity -> [airings, recordings, display, mbid]
    agg = {}
    for rp, clist in contributors.items():
        air = recordings[rp].airing_count if rp in recordings else 0
        for c in clist:
            if c.role != role:
                continue
            a = agg.setdefault(c.identity_key, [0, 0, c.display_name, c.mbid])
            a[0] += air
            a[1] += 1
    stats = [ContribStat(k, v[2], v[3], v[0], v[1]) for k, v in agg.items()]
    stats.sort(key=lambda s: (-s.airings, -s.recordings, s.display_name))
    return stats

def build_contributors(conn, *, after=None, before=None, composer=None,
                       keep_interstitials=False, ctx=None, record_labels=None,
                       recording_pids=None, min_seconds=None, max_seconds=None):
    if ctx is None:
        ctx = build_context(conn)
    name_mbid, mbid_display = ctx.name_mbid, ctx.mbid_display
    cfold = ascii_fold(composer).lower() if composer else None  # see build_recordings
    # rp -> role -> identity_key -> {mbid, names Counter}
    acc = defaultdict(lambda: defaultdict(dict))
    for r in ctx.seg:
        if not keep_interstitials and r.recording_pid in INTERSTITIAL_RECORDING_PIDS:
            continue
        if not _passes(r.date, after, before):
            continue
        if cfold and cfold not in ascii_fold(r.composer_name or "").lower():
            continue
        if record_labels is not None and r.record_label not in record_labels:
            continue
        if recording_pids is not None and r.recording_pid not in recording_pids:
            continue
        if min_seconds is not None and (r.duration_seconds is None
                                        or r.duration_seconds < min_seconds):
            continue
        if max_seconds is not None and (r.duration_seconds is None
                                        or r.duration_seconds > max_seconds):
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

_ROLE_BY = {"composer":"Composer","conductor":"Conductor","orchestra":"Orchestra",
            "ensemble":"Ensemble","performer":"Performer","singer":"Singer","choir":"Choir"}

def coverage_split(stats):
    resolved = sum(1 for s in stats if s.mbid)
    named = sum(1 for s in stats if not s.mbid)
    return resolved, named

def render_ranking(stats, *, by, top=None):
    rows = stats[: top] if top else stats
    resolved, named = coverage_split(stats)
    lines = [f"top {by} by airings  (identities: {resolved} MBID-resolved, "
             f"{named} name-keyed)", ""]
    for i, s in enumerate(rows, 1):
        mark = "" if s.mbid else "  ·name"
        lines.append(f"{i:3d}.  {s.airings:5d}x  {s.recordings:4d} rec   "
                     f"{s.display_name}{mark}")
    return "\n".join(lines)

def render_recordings(recordings, *, top=None):
    ranked = rank_recordings(recordings)
    rows = ranked[: top] if top else ranked
    lines = ["top recordings by airings (most-repeated performances)", ""]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i:3d}.  {r.airing_count:5d}x  {r.duration_seconds:5d}s   "
                     f"{r.composer_display} — {r.segment_title}")
    return "\n".join(lines)

def rank_works(works, *, sort="airings"):
    if sort == "recordings":                          # breadth: distinct recordings
        key = lambda w: (-w.recording_count, -w.airing_count, w.work_display)
    else:                                             # default: repetition (airings)
        key = lambda w: (-w.airing_count, -w.recording_count, w.work_display)
    return sorted(works, key=key)

def render_works(works, *, top=None, sort="airings"):
    ranked = rank_works(works, sort=sort)
    rows = ranked[: top] if top else ranked
    head = ("airings" if sort != "recordings" else "distinct recordings")
    lines = [f"top works by {head} "
             "(recordings grouped by composer-scoped work_title_key)", ""]
    for i, w in enumerate(rows, 1):
        mark = "  ·excerpt?" if w.excerpt_flag else ""
        lines.append(f"{i:3d}.  {w.airing_count:5d}x  {w.recording_count:4d} rec   "
                     f"{w.composer_display} — {w.work_display}{mark}")
    return "\n".join(lines)

def write_csv(stats, path):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["display_name","mbid","airings","recordings"])
        for s in stats:
            w.writerow([s.display_name, s.mbid or "", s.airings, s.recordings])

def main(argv=None):
    # Staff-only surface (SP4d-3b): the recording/work/contributor RANKINGS
    # moved to ttn_analyze (which imports the build_*/rank_*/render_* library
    # functions, not this main). What's left here is the work-alias-candidates
    # oracle (always on), reached via `ttn_curate.py work-alias-candidates`.
    ap = argparse.ArgumentParser(
        description="Recording spine — work-alias-candidates oracle (staff).")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--composer")
    a = ap.parse_args(argv)
    conn = open_db(a.db, ap)
    print(render_candidates(work_alias_candidates(conn, composer=a.composer)))

Candidate = namedtuple("Candidate",
    "recording_pid composer_display segment_title n_work_keys work_keys airings")

def _build_position_bridge(conn):
    """(episode_pid, position) -> (recording_pid, composer_name, track_title),
    plus per_ep[episode_pid] -> [(position, recording_pid, composer_name,
    track_title)]. The shared segment-side bridge used to soft-link a tracks row
    to its recording. segment_events.position is 1-indexed (tracks.position is
    0-indexed), so callers bridge a tracks row at (ep, pos) to seg (ep, pos+1)."""
    seg = {}
    per_ep = defaultdict(list)
    sq = """SELECT episode_pid, position, recording_pid, composer_name, track_title
            FROM segment_events"""
    for ep, pos, rp, cn, tt in conn.execute(sq):
        seg[(ep, pos)] = (rp, cn, tt)
        per_ep[ep].append((pos, rp, cn, tt))
    return seg, per_ep

WorkKeyInfo = namedtuple("WorkKeyInfo", "work_key titles all_keys")

def assign_recording_work_keys(recordings):
    """For each recording, derive one canonical work_key from its SEGMENT title.

    The segment track_title is recording-stable — one title per recording_pid
    (verified: 1 of 20,390 recordings carries >1 distinct segment title) — so
    keying off it eliminates the long_synopsis within-recording title churn the
    old tracks-bridge introduced (and the position-bridge misalignment that came
    with it). No DB access: every recording already carries its segment_title.
    Composer-scoped by the recording's resolved composer_display (Debussy/
    Scarlatti L-catalogue scoping); WORK_ALIASES via resolve_work_alias.
    Returns recording_pid -> WorkKeyInfo(work_key, title Counter, key->airings)."""
    out = {}
    for rp, rec in recordings.items():
        wk = resolve_work_alias(work_title_key(rec.segment_title or "",
                                               composer=rec.composer_display))
        titles = Counter()
        if rec.segment_title:
            titles[rec.segment_title] += rec.airing_count
        out[rp] = WorkKeyInfo(wk, titles, {wk: rec.airing_count})
    return out

_EXCERPT_DURATION_RATIO = 2.0   # max/min duration above this, under one catalogue
                                # key, flags a whole-vs-excerpt split candidate

def _excerpt_flag(work_key, durations):
    """A catalogue-keyed (§) work whose recordings' durations diverge sharply is
    a whole-vs-excerpt split candidate (the recording_pid+duration oracle):
    every recording here already shares the SAME §ref|nums|keys key, so a large
    duration spread means one is mistitled-as-whole. Surfaced, never auto-split.
    Token-sort-path works (no § prefix) are not flagged — they carry no
    catalogue anchor to corroborate against."""
    if not work_key.startswith("§"):
        return False
    durs = [d for d in durations if d]
    if len(durs) < 2:
        return False
    return max(durs) >= _EXCERPT_DURATION_RATIO * min(durs)

Work = namedtuple("Work",
    "composer_identity composer_display work_key work_display "
    "recording_pids airing_count recording_count first_aired last_aired excerpt_flag")

def build_works(recordings):
    """Cluster `recordings` (from build_recordings) into works keyed by
    (composer_identity, work_key). Returns a list of Work. Segment-side, PID-era
    only — no cross-era membership (SP2/SP3). work_key is the group key (never
    displayed); work_display is the recording-stable segment title."""
    wkinfo = assign_recording_work_keys(recordings)
    groups = defaultdict(list)            # (composer_identity, work_key) -> [rp]
    for rp, rec in recordings.items():
        groups[(rec.composer_identity, wkinfo[rp].work_key)].append(rp)
    out = []
    for (cid, wk), rps in groups.items():
        airings = sum(recordings[rp].airing_count for rp in rps)
        durs = [recordings[rp].duration_seconds for rp in rps]
        # representative composer display + title: weight by airings for stability
        dominant = max(rps, key=lambda rp: recordings[rp].airing_count)
        cdisp = recordings[dominant].composer_display
        title_counter = Counter()
        for rp in rps:
            for t, n in wkinfo[rp].titles.items():
                title_counter[t] += n
        wdisp = (title_counter.most_common(1)[0][0] if title_counter
                 else recordings[dominant].segment_title or "(untitled)")
        out.append(Work(
            cid, cdisp, wk, wdisp, rps, airings, len(rps),
            min(recordings[rp].first_aired for rp in rps),
            max(recordings[rp].last_aired for rp in rps),
            _excerpt_flag(wk, durs)))
    return out

def work_alias_candidates(conn, *, composer=None):
    # segment side: (episode, position) -> recording_pid + meta
    seg, per_ep = _build_position_bridge(conn)
    # tracks side -> bridge to recording, collect work_title_keys per recording
    by_rec = defaultdict(lambda: {"keys": Counter(), "cn": None, "tt": None})
    tq = "SELECT episode_pid, position, composer, title FROM tracks"
    for ep, pos, comp, title in conn.execute(tq):
        if composer and composer.lower() not in (comp or "").lower():
            continue
        hit = seg.get((ep, pos + 1))                 # seg position is 1-indexed
        if hit is None:
            cands = per_ep.get(ep, [])
            hit = (cands[0][1], cands[0][2], cands[0][3]) if len(cands) == 1 else None
        if hit is None:
            continue
        rp, cn, tt = hit
        slot = by_rec[rp]
        slot["keys"][work_title_key(title, composer=comp)] += 1
        slot["cn"] = cn; slot["tt"] = tt
    out = []
    for rp, s in by_rec.items():
        if len(s["keys"]) > 1:                       # one recording, many title-keys
            out.append(Candidate(rp, s["cn"], s["tt"], len(s["keys"]),
                                 dict(s["keys"]), sum(s["keys"].values())))
    out.sort(key=lambda c: (-c.n_work_keys, -c.airings))
    return out

def render_candidates(cands):
    lines = [f"{len(cands)} fold candidate(s): one recording spanning >1 work-key",
             ""]
    for c in cands:
        lines.append(f"  rec {c.recording_pid}  {c.airings}x  "
                     f"{c.n_work_keys} keys  {c.composer_display} — {c.segment_title}")
        for k, n in sorted(c.work_keys.items(), key=lambda kv: -kv[1]):
            lines.append(f"        {n:3d}x  {k}")
    return "\n".join(lines)
