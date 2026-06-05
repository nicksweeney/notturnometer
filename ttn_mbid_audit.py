#!/usr/bin/env python3
"""Reconcile tracks (long_synopsis) with segment_events (MBID-bearing) per
episode, and surface composer alias gaps / same-name ambiguities for triage.
MBID is an audit signal, not the grouping key — the rankings are unchanged.

    uv run ttn_mbid_audit.py ttn.sqlite                 # tiered report
    uv run ttn_mbid_audit.py ttn.sqlite --tier medium   # human-review worklist
    uv run ttn_mbid_audit.py ttn.sqlite --emit          # paste-ready alias tuples
    uv run ttn_mbid_audit.py ttn.sqlite --reconcile-report  # join QC
"""
import argparse
import re
import sqlite3

from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                         resolve_composer_alias, COMPOSER_ALIASES)

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*$", re.IGNORECASE)


def parse_clock_offset(time_str):
    """Clock time ("12:31 AM") -> seconds since midnight, or None if it lacks a
    meridiem / is malformed (the dot-time and bare-HH:MM quirk episodes)."""
    if not time_str:
        return None
    m = _TIME_RE.match(time_str)
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    hh %= 12                     # 12 AM -> 0, 12 PM -> 0 then +12 below
    if ap == "PM":
        hh += 12
    return (hh * 60 + mm) * 60


def episode_offsets(time_strs):
    """Per-track seconds-into-programme relative to the first track, with a
    midnight wrap added whenever the raw clock value decreases. Unparseable
    times stay None and don't shift the others."""
    raw = [parse_clock_offset(t) for t in time_strs]
    base = next((r for r in raw if r is not None), None)
    if base is None:
        return raw
    out, wrap, prev = [], 0, None
    for r in raw:
        if r is None:
            out.append(None)
            continue
        if prev is not None and r < prev:
            wrap += 24 * 3600
        out.append(r + wrap - base)
        prev = r
    return out


# Tuning constants — initial values; validated/tuned against the equal-count
# ground truth in Task 6's smoke step.
_TEMPORAL_TOLERANCE = 90.0      # seconds; distance at which temporal score = 0.5
_W_TEMPORAL = 0.6               # weight of the temporal term when a time exists
_W_CONTENT = 0.4               # weight of the composer+title term
_GAP_COST = 0.85               # cost of leaving an item unmatched
_NO_TEMPORAL = object()        # sentinel: temporal term unavailable


def surname(name):
    toks = ascii_fold(name or "").lower().split()
    return toks[-1] if toks else ""


def title_tokens(title):
    return set(re.findall(r"[a-z0-9]+", ascii_fold(title or "").lower()))


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pair_cost(*, t_off, s_off, t_comp, s_comp, t_title, s_title):
    """Cost in [0,1] of matching one track to one segment. Lower = better.
    Combines temporal distance (when both offsets exist) with a composer-surname
    + title-token content score. Content-only when t_off is None."""
    same_surname = surname(t_comp) == surname(s_comp) and surname(t_comp) != ""
    title_sim = _jaccard(title_tokens(t_title), title_tokens(s_title))
    content_good = (1.0 if same_surname else 0.0) * 0.7 + title_sim * 0.3
    content_cost = 1.0 - content_good
    if t_off is None or s_off is None:
        return min(1.0, 0.15 + content_cost)        # mild penalty, content rules
    temporal_cost = 1.0 - _TEMPORAL_TOLERANCE / (_TEMPORAL_TOLERANCE + abs(t_off - s_off))
    return _W_TEMPORAL * temporal_cost + _W_CONTENT * content_cost


def load_episode_data(conn):
    """Return {episode_pid: {"tracks": [...], "segments": [...]}} for every
    episode that has segments. Only episodes with both sides are reconcilable."""
    cur = conn.cursor()
    # Fetch all PIDs into a list first to avoid cursor re-use clobbering the
    # outer iteration (sqlite3 cursors are not re-entrant).
    pids = [r[0] for r in cur.execute("SELECT pid FROM episodes "
                                      "WHERE segments_raw_json IS NOT NULL")]
    data = {}
    for pid in pids:
        tracks = [dict(position=p, time_str=ts, composer=c, title=ti)
                  for p, ts, c, ti in cur.execute(
                      "SELECT position, time_str, composer, title FROM tracks "
                      "WHERE episode_pid=? ORDER BY position", (pid,))]
        segs = [dict(position=p, version_offset=vo, composer_name=cn,
                     track_title=tt, composer_mbid=mb, recording_pid=rp)
                for p, vo, cn, tt, mb, rp in cur.execute(
                    "SELECT position, version_offset, composer_name, track_title, "
                    "composer_mbid, recording_pid FROM segment_events "
                    "WHERE episode_pid=? ORDER BY position", (pid,))]
        if tracks and segs:
            data[pid] = {"tracks": tracks, "segments": segs}
    return data


def reconcile_corpus(conn):
    """Reconcile every reconcilable episode. Returns a flat list of match rows,
    each carrying the originating track composer (for the audit) + episode_pid."""
    out = []
    data = load_episode_data(conn)
    tcomp = {}
    for pid, d in data.items():
        for t in d["tracks"]:
            tcomp[(pid, t["position"])] = t["composer"]
        for m in reconcile_episode(d["tracks"], d["segments"]):
            m = dict(m, episode_pid=pid,
                     track_composer=tcomp[(pid, m["track_position"])])
            out.append(m)
    return out


def _tier(match_cost, *, same_surname, temporal_ok):
    """Confidence tier from the winning pair's cost and signal agreement."""
    if same_surname and match_cost < 0.35:
        return "high"
    if temporal_ok and not same_surname and match_cost < 0.7:
        return "medium"        # same slot, different name -> the triage gold
    if match_cost < 0.6:
        return "high" if same_surname else "medium"
    return "low"


def reconcile_episode(tracks, segments):
    """Monotonic min-cost alignment of one episode's tracks to its segments.
    tracks: dicts with position,time_str,composer,title (position-ordered).
    segments: dicts with position,version_offset,composer_name,track_title,
              composer_mbid,recording_pid.
    Returns one match dict per TRACK: {track_position, composer_mbid,
    recording_pid, segment_composer_name, tier}. Unmatched tracks -> Nones +
    tier 'unmatched'. Pure."""
    tracks = sorted(tracks, key=lambda t: t["position"] or 0)
    segments = sorted(segments, key=lambda s: s["position"] or 0)
    t_off = episode_offsets([t["time_str"] for t in tracks])
    s_off = [s.get("version_offset") for s in segments]
    s_base = next((v for v in s_off if v is not None), 0)
    s_off = [(v - s_base) if v is not None else None for v in s_off]

    n, m = len(tracks), len(segments)
    INF = float("inf")
    # DP over a monotonic alignment: dp[i][j] = min cost aligning first i tracks
    # to first j segments. Moves: match (i-1,j-1), skip segment (i,j-1),
    # leave track unmatched (i-1,j).
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + _GAP_COST
        back[0][j] = "skip_seg"
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + _GAP_COST
        back[i][0] = "skip_track"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            t, s = tracks[i - 1], segments[j - 1]
            c = pair_cost(t_off=t_off[i - 1], s_off=s_off[j - 1],
                          t_comp=t["composer"], s_comp=s["composer_name"],
                          t_title=t["title"], s_title=s["track_title"])
            best, mv = dp[i - 1][j - 1] + c, ("match", c)
            if dp[i - 1][j] + _GAP_COST < best:
                best, mv = dp[i - 1][j] + _GAP_COST, ("skip_track", None)
            if dp[i][j - 1] + _GAP_COST < best:
                best, mv = dp[i][j - 1] + _GAP_COST, ("skip_seg", None)
            dp[i][j], back[i][j] = best, mv

    # Walk back, recording each track's outcome.
    matched = {}           # track index -> (segment, cost)
    i, j = n, m
    while i > 0 or j > 0:
        mv = back[i][j]
        tag = mv[0] if isinstance(mv, tuple) else mv
        if tag == "match":
            matched[i - 1] = (segments[j - 1], mv[1])
            i, j = i - 1, j - 1
        elif tag == "skip_track":
            i -= 1
        else:                  # skip_seg
            j -= 1

    out = []
    for idx, t in enumerate(tracks):
        if idx in matched:
            seg, cost = matched[idx]
            ss = surname(t["composer"]) == surname(seg["composer_name"]) \
                and surname(t["composer"]) != ""
            temporal_ok = t_off[idx] is not None and seg.get("version_offset") is not None \
                and abs(t_off[idx] - (seg["version_offset"] - s_base)) <= 3 * _TEMPORAL_TOLERANCE
            out.append({"track_position": t["position"],
                        "composer_mbid": seg["composer_mbid"],
                        "recording_pid": seg["recording_pid"],
                        "segment_composer_name": seg["composer_name"],
                        "tier": _tier(cost, same_surname=ss, temporal_ok=temporal_ok)})
        else:
            out.append({"track_position": t["position"], "composer_mbid": None,
                        "recording_pid": None, "segment_composer_name": None,
                        "tier": "unmatched"})
    return out


from collections import Counter, defaultdict

_TRUSTED = {"high", "medium"}


def _ck(name):
    return resolve_composer_alias(canonical_key(normalize_composer(name or "")))


def alias_candidates(matches):
    """One MBID seen under >1 track canonical-key (on trusted matches) => those
    keys are one person => propose (variant -> preferred), preferred = the key
    with more airings. Skips dead aliases (already same key) and any preferred
    that already chains in COMPOSER_ALIASES (single-step discipline)."""
    by_mbid = defaultdict(Counter)   # mbid -> {ck: airings}
    display = {}                     # ck -> a representative original spelling
    for m in matches:
        if m["tier"] not in _TRUSTED or not m["composer_mbid"]:
            continue
        ck = _ck(m["track_composer"])
        by_mbid[m["composer_mbid"]][ck] += 1
        display.setdefault(ck, m["track_composer"])
    out = []
    for mbid, cks in by_mbid.items():
        if len(cks) < 2:
            continue
        ranked = cks.most_common()
        preferred_ck = ranked[0][0]
        if preferred_ck in COMPOSER_ALIASES:     # would chain — skip
            continue
        for variant_ck, n in ranked[1:]:
            if variant_ck == preferred_ck:       # dead
                continue
            out.append({"mbid": mbid, "variant_ck": variant_ck,
                        "preferred_ck": preferred_ck,
                        "variant": display[variant_ck],
                        "preferred": display[preferred_ck], "airings": n})
    out.sort(key=lambda c: -c["airings"])
    return out


def ambiguity_flags(matches):
    """One track canonical-key spanning >1 MBID on HIGH matches => same name,
    different people (the bare-Haydn / John-Adams class). Flag, never fold."""
    by_ck = defaultdict(set)
    air = Counter()
    for m in matches:
        if m["tier"] != "high" or not m["composer_mbid"]:
            continue
        ck = _ck(m["track_composer"])
        by_ck[ck].add(m["composer_mbid"])
        air[ck] += 1
    flags = [{"ck": ck, "n_mbids": len(mb), "airings": air[ck]}
             for ck, mb in by_ck.items() if len(mb) > 1]
    flags.sort(key=lambda f: -f["airings"])
    return flags


def render_report(matches, *, composer=None):
    rows = matches
    if composer:
        cl = composer.lower()
        rows = [m for m in matches if cl in (m["track_composer"] or "").lower()]
    tiers = Counter(m["tier"] for m in rows)
    cands = alias_candidates(rows)
    flags = ambiguity_flags(rows)
    out = ["MBID composer audit",
           f"  matches: {len(rows):,}   tiers: " +
           ", ".join(f"{k}={tiers.get(k,0):,}" for k in ("high","medium","low","unmatched")),
           f"  alias candidates (1 MBID, >1 name): {len(cands)}",
           f"  ambiguity flags (1 name, >1 person): {len(flags)}"]
    for c in cands[:30]:
        out.append(f"    FOLD  {c['variant']!r} -> {c['preferred']!r}  ({c['airings']} air)")
    for f in flags[:20]:
        out.append(f"    SPLIT?  {f['ck']}  ({f['n_mbids']} people, {f['airings']} air)")
    return "\n".join(out)


def render_emit(cands):
    out = ["    # MBID-derived composer alias candidates — review before pasting",
           "    # into ttn_aliases._COMPOSER_ALIAS_PAIRS:"]
    for c in cands:
        out.append(f'    ("{c["variant"]}", "{c["preferred"]}"),')
    return "\n".join(out)


def render_reconcile_report(matches):
    tiers = Counter(m["tier"] for m in matches)
    return ("Reconciliation QC\n  " +
            "\n  ".join(f"{k:9} {tiers.get(k,0):,}"
                        for k in ("high","medium","low","unmatched")))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Audit composer identity by reconciling tracks with "
                    "segment_events MBIDs (proposes alias folds / ambiguity flags).")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--tier", choices=("high", "medium", "low", "unmatched"),
                    help="filter the report to one tier")
    ap.add_argument("--composer", help="scope to track composers matching this substring")
    ap.add_argument("--emit", action="store_true",
                    help="print paste-ready _COMPOSER_ALIAS_PAIRS tuples")
    ap.add_argument("--reconcile-report", action="store_true",
                    help="join QC: tier counts only")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    try:
        matches = reconcile_corpus(conn)
    finally:
        conn.close()
    if args.tier:
        matches = [m for m in matches if m["tier"] == args.tier]
    if args.reconcile_report:
        print(render_reconcile_report(matches))
    elif args.emit:
        scoped = matches
        if args.composer:
            cl = args.composer.lower()
            scoped = [m for m in matches if cl in (m["track_composer"] or "").lower()]
        print(render_emit(alias_candidates(scoped)))
    else:
        print(render_report(matches, composer=args.composer))


if __name__ == "__main__":
    main()
