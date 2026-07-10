#!/usr/bin/env python3
"""Reconcile tracks (long_synopsis) with segment_events (MBID-bearing) per
episode, and surface composer alias gaps / same-name ambiguities for triage.
MBID is an audit signal, not the grouping key — the rankings are unchanged.

    uv run ttn_mbid_audit.py ttn.sqlite                 # tiered report
    uv run ttn_mbid_audit.py ttn.sqlite --tier medium   # human-review worklist
    uv run ttn_mbid_audit.py ttn.sqlite --emit          # paste-ready alias tuples
    uv run ttn_mbid_audit.py ttn.sqlite --reconcile-report  # join QC
    uv run ttn_mbid_audit.py ttn.sqlite --reject "A|B"  # park a pair
"""
import argparse
import functools
import json
import os
import re
import sqlite3

from ttn_db import open_db
from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                         resolve_composer_alias, COMPOSER_ALIASES)

_TIME_RE = re.compile(
    r"^\s*(\d{1,2})[.:](\d{2})\s*:?\s*(?:([AP]M))?(?:\s+[A-Z]{2,4})?\s*$",
    re.IGNORECASE)


def parse_clock_offset(time_str):
    """Clock time ("12:31 AM") -> seconds since midnight, or None if malformed.

    The separator may be a dot or a colon and a stray trailing colon / a
    timezone suffix are tolerated. A missing meridiem is read as AM: the
    programme airs overnight (00:30-06:00), so a bare time is unambiguously AM.
    """
    if not time_str:
        return None
    m = _TIME_RE.match(time_str)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "AM").upper()    # overnight show: bare time => AM
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


# Generational suffixes stripped before taking the surname token. Without this,
# a suffixed credit's "surname" was the suffix itself (tracks 'Nicola Matteis
# Sr.' -> 'sr.', segments 'Nicola Matteis, Jr' -> 'jr', 'Johann Strauss Jr' vs
# segment 'Johann Strauss II' -> 'jr' vs 'ii'), so precisely the conflation-
# prone father/son credits could NEVER pass the same-surname gate — locking
# them out of the High tier and hence out of the MBID projection that would
# correct them. It also let two DIFFERENT Jr.-suffixed composers share the
# fake surname 'jr.'. Vocabulary is the observed corpus set (jr/sr, Roman
# numerals I-III); 'Younger'/'Elder' strip only as the 'the X' bigram, because
# bare Elder/Younger can be a REAL surname (the conductor Mark Elder) — jr/sr/
# numerals never are. Same-family credits (Strauss I vs II) then share a real
# surname — the Bach-family situation, which the temporal anchor already
# disambiguates (surname is a scoring nudge, not the key).
_GENERATIONAL_SUFFIXES = {"jr", "sr", "i", "ii", "iii"}
_THE_SUFFIXES = {"younger", "elder"}


# Unbounded caches: the corpus has ~53k distinct titles, so a 4096 cap
# thrashed (49% hit rate over the full reconcile); the full key-sets are
# small and a reconcile is a one-shot batch process.
@functools.lru_cache(maxsize=None)
def surname(name):
    toks = ascii_fold(name or "").lower().split()
    while len(toks) > 1:
        last = toks[-1].strip(".,")
        if last in _GENERATIONAL_SUFFIXES:
            toks.pop()
        elif (last in _THE_SUFFIXES and len(toks) > 2
              and toks[-2].strip(".,") == "the"):
            toks.pop()
            toks.pop()                       # 'the Younger' / 'the Elder'
        else:
            break
    return toks[-1].strip(".,") if toks else ""


@functools.lru_cache(maxsize=None)
def title_tokens(title):
    """Frozen set of ASCII-folded lowercase alphanumeric tokens from the title.
    Cached: same string is typically seen across many episodes."""
    return frozenset(re.findall(r"[a-z0-9]+", ascii_fold(title or "").lower()))


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def _pair_cost_precomputed(t_off, s_off, t_surname, s_surname, t_tokens, s_tokens):
    """Fast inner scorer using already-computed surname/token-set values."""
    same_surname = t_surname == s_surname and t_surname != ""
    title_sim = _jaccard(t_tokens, s_tokens)
    content_good = (1.0 if same_surname else 0.0) * 0.7 + title_sim * 0.3
    content_cost = 1.0 - content_good
    if t_off is None or s_off is None:
        return min(1.0, 0.15 + content_cost)        # mild penalty, content rules
    temporal_cost = 1.0 - _TEMPORAL_TOLERANCE / (_TEMPORAL_TOLERANCE + abs(t_off - s_off))
    return _W_TEMPORAL * temporal_cost + _W_CONTENT * content_cost


def pair_cost(*, t_off, s_off, t_comp, s_comp, t_title, s_title):
    """Cost in [0,1] of matching one track to one segment. Lower = better.
    Combines temporal distance (when both offsets exist) with a composer-surname
    + title-token content score. Content-only when t_off is None."""
    return _pair_cost_precomputed(
        t_off, s_off,
        surname(t_comp), surname(s_comp),
        title_tokens(t_title), title_tokens(s_title),
    )


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
    # Order segments by broadcast position; fall back to version_offset when the
    # position is NULL (8.4% of segments — 424 whole episodes — carry NULL
    # position but a valid version_offset, the seconds-into-programme). Without
    # the fallback those collapse to 0, scrambling both the monotonic alignment
    # and the s_base temporal anchor and demoting correct matches to 'low'.
    segments = sorted(segments, key=lambda s: s["position"]
                      if s.get("position") is not None
                      else (s.get("version_offset") or 0))
    t_off = episode_offsets([t["time_str"] for t in tracks])
    s_off = [s.get("version_offset") for s in segments]
    s_base = next((v for v in s_off if v is not None), 0)
    s_off = [(v - s_base) if v is not None else None for v in s_off]

    n, m = len(tracks), len(segments)
    # Precompute per-track and per-segment surname/token-sets once — O(n+m)
    # folds instead of O(n·m) inside the DP loop.
    t_surnames = [surname(t["composer"]) for t in tracks]
    t_tokens_list = [title_tokens(t["title"]) for t in tracks]
    s_surnames = [surname(s["composer_name"]) for s in segments]
    s_tokens_list = [title_tokens(s["track_title"]) for s in segments]

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
            c = _pair_cost_precomputed(
                t_off[i - 1], s_off[j - 1],
                t_surnames[i - 1], s_surnames[j - 1],
                t_tokens_list[i - 1], s_tokens_list[j - 1],
            )
            best, mv = dp[i - 1][j - 1] + c, ("match", c)
            if dp[i - 1][j] + _GAP_COST < best:
                best, mv = dp[i - 1][j] + _GAP_COST, ("skip_track", None)
            if dp[i][j - 1] + _GAP_COST < best:
                best, mv = dp[i][j - 1] + _GAP_COST, ("skip_seg", None)
            dp[i][j], back[i][j] = best, mv

    # Walk back, recording each track's outcome.
    # Capture both the segment object (for output fields) and its list index
    # (to reuse the precomputed s_surnames without an extra ascii_fold call).
    matched = {}           # track index -> (segment, cost, seg_list_idx)
    i, j = n, m
    while i > 0 or j > 0:
        mv = back[i][j]
        tag = mv[0] if isinstance(mv, tuple) else mv
        if tag == "match":
            matched[i - 1] = (segments[j - 1], mv[1], j - 1)
            i, j = i - 1, j - 1
        elif tag == "skip_track":
            i -= 1
        else:                  # skip_seg
            j -= 1

    out = []
    for idx, t in enumerate(tracks):
        if idx in matched:
            seg, cost, seg_idx = matched[idx]
            # Use precomputed surnames to avoid redundant ascii_fold calls.
            ss = t_surnames[idx] == s_surnames[seg_idx] and t_surnames[idx] != ""
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

_DECISIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "ttn_mbid_audit_decisions.json")

_ANON_TOKENS = {"anon", "anonymous", "trad", "traditional"}


def load_decisions(path):
    """Set of frozenset({ck_a, ck_b}) pairs a human has rejected (keyed by
    canonical key, so spelling variants of a rejected pair are also suppressed).
    Missing file -> empty set."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return set()
    return {frozenset(pair) for pair in data.get("rejected", [])}


def record_rejection(path, name_a, name_b):
    """Append a sorted [ck_a, ck_b] to the decisions file (de-duped by
    canonical key), preserving any existing entries. Creates the file if absent.
    Keyed by canonical key so spelling variants of a rejected pair stay parked."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {"rejected": []}
    ck_a, ck_b = _ck(name_a), _ck(name_b)
    pair_key = frozenset({ck_a, ck_b})
    existing = {frozenset(p) for p in data.get("rejected", [])}
    if pair_key not in existing:
        data.setdefault("rejected", []).append(sorted([ck_a, ck_b]))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")


def _ck(name):
    return resolve_composer_alias(canonical_key(normalize_composer(name or "")))


def _name_tokens(name):
    """Set of ASCII-folded lowercase word tokens from the full name. Tokenizes
    on word characters so trailing punctuation (the comma in 'Mealli, Giovanni')
    doesn't fragment a token and break subset/surname corroboration."""
    return set(re.findall(r"[a-z0-9]+", ascii_fold(name or "").lower()))


def _is_corroborated(variant_display, preferred_display):
    """True iff the two names plausibly denote one person: both Anonymous/
    Traditional family, OR one token-set a subset of the other (name-order swap,
    middle-name expansion, suffix add — 'Strauss' ⊆ 'Johann Strauss II'), OR a
    shared surname (last token; catches spelling/diacritic variants like
    Dieterich/Dietrich Buxtehude). Two distinct people who merely share GIVEN
    names (Giovanni Battista Draghi vs Giovanni Battista Pergolesi) are NOT
    corroborated — the surname differs and neither token-set subsets the other."""
    vt = _name_tokens(variant_display)
    pt = _name_tokens(preferred_display)
    if not vt or not pt:
        return False
    if (vt & _ANON_TOKENS) and (pt & _ANON_TOKENS):
        return True
    if vt == pt:
        return True                      # same tokens reordered — an inversion
    if vt <= pt or pt <= vt:
        # A strict superset is a middle-name / suffix expansion (one person) —
        # UNLESS the longer side joins two names with a comma / & / 'and', i.e.
        # a combined credit ('Brian Eno, Julia Wolfe' -> 'Brian Eno'), which is
        # two people and must NOT fold.
        longer = variant_display if len(vt) > len(pt) else preferred_display
        if re.search(r",|&|\band\b", ascii_fold(longer).lower()):
            return False
        return True
    return surname(variant_display) == surname(preferred_display) != ""


def alias_candidates(matches, rejected=None):
    """One MBID seen under >1 track canonical-key (on trusted matches) => those
    keys are one person => propose (variant -> preferred), preferred = the key
    with more airings.

    Guards applied (in order):
    1. Skip dead aliases (already same key) and any preferred that chains in
       COMPOSER_ALIASES (single-step discipline).
    2. Self-contradiction cross-check (B1a): drop any candidate whose
       variant_ck or preferred_ck also appears in ambiguity_flags — a key
       that's both "fold into X" and "split into multiple people" is a
       misalignment tell (kills the Haydn family case).
    3. Name-corroboration tag (B1b): mark each candidate corroborated=True iff
       the two display names share at least one ASCII-folded token (or both are
       Anon/Trad family). Keeps transliterations; flags cross-surname pairs.
    4. Rejected-pair filter (I1): drop pairs recorded in the decisions ledger
       (keyed by canonical key).

    Returns list of candidate dicts, each with a 'corroborated' bool field.
    """
    if rejected is None:
        rejected = load_decisions(_DECISIONS_PATH)

    by_mbid = defaultdict(Counter)   # mbid -> {ck: airings}
    display = {}                     # ck -> a representative original spelling
    for m in matches:
        if m["tier"] not in _TRUSTED or not m["composer_mbid"]:
            continue
        ck = _ck(m["track_composer"])
        by_mbid[m["composer_mbid"]][ck] += 1
        display.setdefault(ck, m["track_composer"])

    # B1a: compute the set of keys that appear in ambiguity_flags so we can
    # cross-check. A key in both "fold" and "split" is a misalignment signal.
    ambiguous_keys = {f["ck"] for f in ambiguity_flags(matches)}

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
            # B1a: self-contradiction cross-check
            if variant_ck in ambiguous_keys or preferred_ck in ambiguous_keys:
                continue
            # I1: ledger-rejected pair filter
            if frozenset({variant_ck, preferred_ck}) in rejected:
                continue
            # B1b: name-corroboration tag
            corroborated = _is_corroborated(display[variant_ck],
                                            display[preferred_ck])
            out.append({"mbid": mbid, "variant_ck": variant_ck,
                        "preferred_ck": preferred_ck,
                        "variant": display[variant_ck],
                        "preferred": display[preferred_ck], "airings": n,
                        "corroborated": corroborated})
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


def render_report(matches, *, composer=None, rejected=None):
    rows = matches
    if composer:
        cl = composer.lower()
        rows = [m for m in matches if cl in (m["track_composer"] or "").lower()]
    tiers = Counter(m["tier"] for m in rows)
    if rejected is None:
        rejected = load_decisions(_DECISIONS_PATH)
    cands = alias_candidates(rows, rejected=rejected)
    flags = ambiguity_flags(rows)
    corr = [c for c in cands if c["corroborated"]]
    uncorr = [c for c in cands if not c["corroborated"]]
    out = ["MBID composer audit",
           f"  matches: {len(rows):,}   tiers: " +
           ", ".join(f"{k}={tiers.get(k,0):,}" for k in ("high","medium","low","unmatched")),
           f"  alias candidates (1 MBID, >1 name): {len(cands)}"
           f"  ({len(corr)} corroborated, {len(uncorr)} cross-name — verify)",
           f"  ambiguity flags (1 name, >1 person): {len(flags)}"]
    for c in corr[:30]:
        out.append(f"    FOLD  {c['variant']!r} -> {c['preferred']!r}  ({c['airings']} air)")
    for f in flags[:20]:
        out.append(f"    SPLIT?  {f['ck']}  ({f['n_mbids']} people, {f['airings']} air)")
    if uncorr:
        out.append(
            "\n  -- cross-name FOLD? — verify: transliteration or misalignment --")
        for c in uncorr[:20]:
            out.append(f"    FOLD?  {c['variant']!r} -> {c['preferred']!r}"
                       f"  ({c['airings']} air)")
    return "\n".join(out)


def render_emit(cands):
    """Emit paste-ready alias tuples — corroborated candidates only (safe to paste).
    Cross-surname uncorroborated pairs are excluded; they appear in render_report's
    separate section for human review."""
    safe = [c for c in cands if c.get("corroborated", True)]
    out = ["    # MBID-derived composer alias candidates — review before pasting",
           "    # into ttn_aliases._COMPOSER_ALIAS_PAIRS:"]
    for c in safe:
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
    ap.add_argument("--reject", metavar="A|B",
                    help="record a rejected pair to the decisions file and exit")
    args = ap.parse_args(argv)

    if args.reject:
        if "|" not in args.reject:
            ap.error("--reject expects two names separated by '|', "
                     'e.g. --reject "Name A|Name B"')
        a, b = args.reject.split("|", 1)
        record_rejection(_DECISIONS_PATH, a.strip(), b.strip())
        print(f"Recorded rejection: {a.strip()!r} | {b.strip()!r}")
        return

    rejected = load_decisions(_DECISIONS_PATH)

    conn = open_db(args.db, ap)
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
        print(render_emit(alias_candidates(scoped, rejected=rejected)))
    else:
        print(render_report(matches, composer=args.composer, rejected=rejected))
