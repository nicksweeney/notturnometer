#!/usr/bin/env python3
"""Find re-aired recordings in ttn.sqlite — a specific performance (one
work, one set of forces) that Through the Night broadcast on two or more
nights. Prints a banded "top X" rebroadcast report; with --multiplay also
shows multi-play merge candidates (one recording aired under variant
titles), and with --emit appends paste-ready WORK_ALIASES tuples for them.
The multi-play scan is cached to ttn_rebroadcast_cache.json. A
report-for-insight / report-for-triage tool: it never writes to the DB or
the alias tables.
See docs/superpowers/specs/2026-05-18-ttn-rebroadcast-design.md and
2026-05-19-ttn-rebroadcast-caching-design.md.
"""
import csv
import hashlib
import json
import os
import re
import statistics
from collections import Counter, defaultdict, namedtuple
from datetime import date, datetime

from ttn_analyze import (_EXCERPT_LOCATOR_RE, canonical_key, catalogue_ref,
                         normalize_composer, normalize_work,
                         resolve_composer_alias, resolve_work_alias,
                         work_title_key)
from ttn_audit import (candidate_id, components, load_decisions,
                       load_tracks, with_track_lengths)


# --- pure logic: the credit signature ------------------------------------

# conductors / soloists / ensembles: frozensets of canonical_key'd names.
# degraded: the performers string carried no (role) parenthetical at all,
# so role buckets could not be assigned (~10.6% of tracks).
CreditSig = namedtuple("CreditSig", "conductors soloists ensembles degraded")

# a name-segment ending in a (role): captures the name and the role text.
_SEG_ROLE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")
_CONDUCTOR_ROLE = re.compile(r"conduct|direct|dirigent", re.I)
_ENSEMBLE_ROLE = re.compile(
    r"orchestra|choir|chorus|ensemble|consort|quartet|quintet|sextet|"
    r"octet|trio|band|singers|players|philharmon|sinfoni|collegium|"
    r"capella|cappella|camerata", re.I)


def parse_credit(performers):
    """Parse a performers string into a CreditSig. Segments are split on
    , ; | and ' and '; each is bucketed by its trailing (role): a
    conductor/director role to conductors, an ensemble-type role (or no
    role) to ensembles, anything else (instruments, voices) to soloists.
    A string with no parenthetical anywhere is degraded — every name goes
    to ensembles. Names are folded through canonical_key."""
    s = performers or ""
    degraded = "(" not in s
    cond, solo, ens = set(), set(), set()
    for seg in re.split(r"[,;|]| and ", s):
        seg = seg.strip()
        if not seg:
            continue
        m = _SEG_ROLE.match(seg)
        name, role = (m.group(1), m.group(2)) if m else (seg, "")
        nk = canonical_key(name).strip()
        if not nk:
            continue
        if role and _CONDUCTOR_ROLE.search(role):
            cond.add(nk)
        elif (not role) or _ENSEMBLE_ROLE.search(role):
            ens.add(nk)
        else:
            solo.add(nk)
    return CreditSig(frozenset(cond), frozenset(solo), frozenset(ens),
                     degraded)


def credit_key(sig):
    """The flattened set of every credited name — the clustering key. A
    changed conductor changes a name and so splits the cluster; this is
    the warhorse-false-positive defence. Role-blind on purpose: it makes
    a degraded (bare-string) unit cluster naturally with a role-tagged
    airing of the same forces."""
    return sig.conductors | sig.soloists | sig.ensembles


# --- pure logic: performance units ---------------------------------------

# composer: canonical, alias-resolved (grouping key). composer_display:
# the original spelling (display). work_key: resolve_work_alias(
# work_title_key(...)). title: normalize_work output (representative-title
# display). credit: the CreditSig. credit_key: flattened name-set.
# date: 'YYYY-MM-DD'. length: minutes proxy or None. catalogue:
# catalogue_ref(title) or ''.
Unit = namedtuple("Unit", "composer composer_display work_key title "
                          "credit credit_key date length catalogue")


def build_units(rows):
    """rows: (title, composer, performers, broadcast_date, time_str,
    length) — the shape with_track_lengths() returns. One Unit per track;
    tracks with no composer or no work-key are dropped."""
    units = []
    for title, composer, performers, date, _time, length in rows:
        nc = normalize_composer(composer)
        nw = normalize_work(title)
        if not nc or not nw:
            continue
        ckey = resolve_composer_alias(canonical_key(nc))
        wkey = resolve_work_alias(work_title_key(nw))
        if not ckey or not wkey:
            continue
        sig = parse_credit(performers or "")
        units.append(Unit(ckey, nc, wkey, nw, sig, credit_key(sig),
                           (date or "")[:10], length, catalogue_ref(nw)))
    return units


# --- pure logic: Stage 1, rebroadcast clustering -------------------------

def rebroadcast_clusters(units):
    """Group units by (composer, work_key, credit_key). Return the groups
    — each a list of units — aired on two or more distinct dates. A group
    on one date only (or many units of one date) is not a rebroadcast."""
    groups = defaultdict(list)
    for u in units:
        groups[(u.composer, u.work_key, u.credit_key)].append(u)
    out = []
    for members in groups.values():
        if len({u.date for u in members if u.date}) >= 2:
            out.append(members)
    return out


# --- pure logic: length bands and group display -------------------------

# Fixed thresholds (minutes), not flags — the ttn_audit YAGNI precedent.
SHORT_MAX_MIN = 8     # under this -> "short"; a gap-filler piece
LONG_MIN_MIN = 20     # over this  -> "long"; a substantial work


def length_band(minutes):
    """The length band of a recording: 'short' (< 8 min), 'medium',
    'long' (> 20 min), or 'unknown' when the length proxy is missing."""
    if minutes is None:
        return "unknown"
    if minutes < SHORT_MAX_MIN:
        return "short"
    if minutes > LONG_MIN_MIN:
        return "long"
    return "medium"


def cluster_length(cluster):
    """A recording's representative length — the median of its airings'
    length proxies — or None when every airing's proxy is missing."""
    lengths = [u.length for u in cluster if u.length is not None]
    return statistics.median(lengths) if lengths else None


def representative_title(units):
    """The display title for a group of units: the most common title,
    tie-broken on the title text so the pick is deterministic."""
    counts = Counter(u.title for u in units)
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


# --- pure logic: the same-work signal ------------------------------------

_JACCARD_MIN = 0.55   # ttn_audit's proven token-overlap threshold


def same_work(unit_a, unit_b):
    """True if two units' titles denote the same work — a shared
    catalogue ref, or (failing that) title-token Jaccard >= 0.55. Mirrors
    ttn_audit's find_pairs() same-work test.

    The catalogue short-circuit is gated by an excerpt check: an opera /
    oratorio / cantata shares ONE catalogue number across every aria, so
    when *both* titles carry an excerpt locator (from, aria, Act…) a
    catalogue match is not decisive — it falls through to the token test,
    which keeps two distinct arias apart. Mirrors work_title_key's own
    _EXCERPT_LOCATOR_RE gate."""
    ca = canonical_key(unit_a.title)
    cb = canonical_key(unit_b.title)
    both_excerpts = bool(_EXCERPT_LOCATOR_RE.search(ca)
                         and _EXCERPT_LOCATOR_RE.search(cb))
    if unit_a.catalogue and unit_b.catalogue and not both_excerpts:
        return unit_a.catalogue == unit_b.catalogue
    ta = set(ca.split())
    tb = set(cb.split())
    union = ta | tb
    return bool(union) and len(ta & tb) / len(union) >= _JACCARD_MIN


# --- pure logic: multi-movement display-collapse -------------------------

def _cluster_entry(clusters):
    """Build one display entry from one or more rebroadcast clusters that
    have been judged the same work. airings = distinct dates across them;
    length = the clusters' representative lengths summed (None-safe);
    length_spread = the widest within-cluster airing-length gap, the
    visible tell for the irreducible same-forces false positive."""
    members = [u for c in clusters for u in c]
    dates = {u.date for u in members if u.date}
    lengths = [cluster_length(c) for c in clusters]
    total = sum(x for x in lengths if x is not None) or None
    spread = 0
    for c in clusters:
        ls = [u.length for u in c if u.length is not None]
        if len(ls) >= 2:
            spread = max(spread, max(ls) - min(ls))
    return {"clusters": clusters,
            "title": representative_title(members),
            "composer": members[0].composer,
            "credit": next((u.credit for u in members
                            if not u.credit.degraded), members[0].credit),
            "degraded": any(u.credit.degraded for u in members),
            "airings": len(dates),
            "dates": sorted(dates),
            "length": total,
            "length_spread": spread,
            "catalogue": members[0].catalogue}


def collapse_multimovement(clusters):
    """Collapse rebroadcast clusters that are movements of one work into
    single display entries. Clusters sharing (composer, credit_key,
    date-set) are candidates; within such a group, clusters whose
    representative units pass same_work() are union-found together and
    summed. Purely cosmetic — it never affects matching."""
    buckets = defaultdict(list)
    for c in clusters:
        rep = c[0]
        date_set = frozenset(u.date for u in c if u.date)
        buckets[(rep.composer, rep.credit_key, date_set)].append(c)
    entries = []
    for group in buckets.values():
        if len(group) == 1:
            entries.append(_cluster_entry(group))
            continue
        # union-find the clusters in this bucket by the same-work signal
        reps = {id(c): c[0] for c in group}
        pairs = [(id(a), id(b))
                 for a, b in _index_pairs(group)
                 if same_work(reps[id(a)], reps[id(b)])]
        by_id = {id(c): c for c in group}
        seen = set()
        for comp in components(pairs):
            seen |= comp
            entries.append(_cluster_entry([by_id[i] for i in comp]))
        for c in group:               # clusters in no pair stand alone
            if id(c) not in seen:
                entries.append(_cluster_entry([c]))
    return entries


def _index_pairs(items):
    """All unordered pairs of a list — like itertools.combinations(_, 2),
    spelled out so the module needs no extra import."""
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield items[i], items[j]


# --- pure logic: Stage 2, multi-play detection ---------------------------

def multiplay_candidates(units, decided_ids=frozenset()):
    """Stage 2. Regroup units by (composer, credit_key) — work-key
    dropped. Within a credit group with two or more work-keys, work-keys
    whose representative units pass same_work() are one recording aired
    under variant titles. Returns a list of candidate dicts
    {work_keys, titles, pair_ids} — work-keys union-found into merge
    groups. A pair whose candidate_id is in decided_ids is dropped before
    grouping, so a rejected pair cannot bridge a group either."""
    by_credit = defaultdict(list)
    for u in units:
        by_credit[(u.composer, u.credit_key)].append(u)
    out = []
    for members in by_credit.values():
        by_wk = defaultdict(list)
        for u in members:
            by_wk[u.work_key].append(u)
        if len(by_wk) < 2:
            continue
        reps = {wk: representative_title(us) for wk, us in by_wk.items()}
        rep_unit = {wk: us[0] for wk, us in by_wk.items()}
        pairs = []
        for wk_a, wk_b in _index_pairs(sorted(by_wk)):
            if not same_work(rep_unit[wk_a], rep_unit[wk_b]):
                continue
            if candidate_id(reps[wk_a], reps[wk_b]) in decided_ids:
                continue
            pairs.append((wk_a, wk_b))
        for comp in components(pairs):
            keys = sorted(comp)
            titles = sorted(reps[wk] for wk in keys)
            ids = sorted(candidate_id(a, b) for a, b in _index_pairs(titles))
            out.append({"work_keys": keys, "titles": titles,
                        "pair_ids": ids})
    out.sort(key=lambda c: c["titles"])
    return out


# --- I/O: report rendering -----------------------------------------------

_BANDS = [("short", "SHORT FILLERS (< 8 min)"),
          ("medium", "MEDIUM (8-20 min)"),
          ("long", "LONG WORKS (> 20 min)"),
          ("unknown", "LENGTH UNKNOWN")]

# a within-cluster airing-length gap at or above this (minutes) is flagged
# in the report — the tell that "one tape re-aired" may instead be two
# performances by the same forces (the irreducible false positive).
_LENGTH_SPREAD_WARN_MIN = 5


def _fmt_credit(sig):
    """A one-line forces string from a CreditSig, for display."""
    bits = []
    if sig.soloists:
        bits.append(", ".join(sorted(sig.soloists)))
    if sig.ensembles:
        bits.append(", ".join(sorted(sig.ensembles)))
    if sig.conductors:
        bits.append(", ".join(sorted(sig.conductors)) + " (cond.)")
    return " / ".join(bits) if bits else "(forces unknown)"


def _entry_sort_key(entry):
    """Rank: airing count desc, then span (last - first airing) in days
    desc, then title. Every rebroadcast entry has >=2 ISO dates."""
    first, last = entry["dates"][0], entry["dates"][-1]
    span = (date.fromisoformat(last) - date.fromisoformat(first)).days
    return (-entry["airings"], -span, entry["title"])


def render_report(entries, composer_display, top):
    """The banded rebroadcast report. entries: collapse_multimovement()
    output. composer_display: {composer_key: display name}. top: rows per
    band."""
    by_band = defaultdict(list)
    for e in entries:
        by_band[length_band(e["length"])].append(e)
    out = [f"\n{'=' * 72}\nRE-AIRED RECORDINGS\n{'=' * 72}"]
    for band_key, heading in _BANDS:
        rows = sorted(by_band.get(band_key, []), key=_entry_sort_key)[:top]
        out.append(f"\n{heading}: {len(rows)}")
        for rank, e in enumerate(rows, 1):
            conf = "Degraded" if e["degraded"] else "Confirmed"
            length = f"~{int(e['length'])}m" if e["length"] else "?"
            cats = {c[0].catalogue for c in e["clusters"]}
            cat = "cat=" + (next(iter(cats)) or "-") if len(cats) == 1 \
                else "cat≠"
            warn = (" ⚠length-spread"
                    if e["length_spread"] >= _LENGTH_SPREAD_WARN_MIN else "")
            out.append(
                f"  {rank:2d}. {e['airings']}x  ({length})  [{conf}] "
                f"[{cat}]{warn}")
            out.append(f"      {composer_display.get(e['composer'], e['composer'])}"
                       f" — {e['title']}")
            out.append(f"      {_fmt_credit(e['credit'])}")
            out.append(f"      aired: {', '.join(e['dates'])}")
    return "\n".join(out)


# --- I/O: multi-play merge-candidate rendering ---------------------------

def render_multiplay(candidates, emit):
    """The multi-play merge-candidate section. Always lists the
    candidates; with emit=True also prints paste-ready WORK_ALIASES
    tuples and a _REAIRING_GROUPS test list."""
    out = [f"\n{'=' * 72}\nMULTI-PLAY MERGE CANDIDATES: {len(candidates)}"
           f"\n{'=' * 72}"]
    for c in candidates:
        ids = " ".join(f"[{i}]" for i in c["pair_ids"])
        out.append(f"\n   {ids}")
        for title in c["titles"]:
            out.append(f"      {title}")
    if emit and candidates:
        out.append("\n# --- WORK_ALIASES tuples (paste into _WORK_ALIAS_PAIRS) ---")
        for c in candidates:
            target = c["titles"][0]
            for variant in c["titles"][1:]:
                out.append(f"    ({variant!r},")
                out.append(f"     {target!r}),")
        out.append("\n# --- test groups (paste into a _REAIRING_GROUPS list) ---")
        for c in candidates:
            out.append(f"    {c['titles']!r},")
    return "\n".join(out)


# --- I/O: CSV export -----------------------------------------------------

def write_csv(path, entries, composer_display):
    """One row per re-aired recording: composer, work, airings, length,
    band, confidence, forces, dates."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["composer", "work", "airings", "length_min", "band",
                    "length_spread_min", "confidence", "forces", "dates"])
        for e in sorted(entries, key=_entry_sort_key):
            w.writerow([
                composer_display.get(e["composer"], e["composer"]),
                e["title"], e["airings"],
                "" if e["length"] is None else int(e["length"]),
                length_band(e["length"]), e["length_spread"],
                "degraded" if e["degraded"] else "confirmed",
                _fmt_credit(e["credit"]), "; ".join(e["dates"])])


# --- I/O: the multi-play cache -------------------------------------------

# files whose contents determine a multi-play scan result — hashed into the
# cache's code fingerprint so an alias-table edit (ttn_analyze.py) or a new
# decisions verdict invalidates the cache. See the caching design spec.
_CODE_FINGERPRINT_FILES = ("ttn_analyze.py", "ttn_rebroadcast.py",
                           "ttn_audit.py", "ttn_rebroadcast_decisions.json")


def code_fingerprint(directory):
    """A sha1 hex digest over the bytes of the files that determine a
    multi-play scan — the analyzer, this module, ttn_audit, and the
    decisions file, each resolved under `directory`. Each file's bytes are
    prefixed with their 8-byte length so file boundaries are unambiguous;
    a missing file contributes an all-0xff sentinel length (one no real
    file reaches), so its later appearance still moves the digest."""
    h = hashlib.sha1()
    for name in _CODE_FINGERPRINT_FILES:
        h.update(name.encode("utf-8"))
        try:
            with open(os.path.join(directory, name), "rb") as fh:
                content = fh.read()
        except FileNotFoundError:
            h.update(b"\xff" * 8)
            continue
        h.update(len(content).to_bytes(8, "big"))
        h.update(content)
    return h.hexdigest()


def data_fingerprint(units):
    """A sha1 hex digest over the multi-play-relevant fields of every unit
    — composer, credit_key, work_key, title, catalogue. Stage 2 reads only
    these, so the digest changes exactly when the multi-play result could,
    and stays blind to length / date churn. Order-independent: the rows are
    sorted before hashing."""
    rows = sorted((u.composer, tuple(sorted(u.credit_key)), u.work_key,
                   u.title, u.catalogue) for u in units)
    h = hashlib.sha1()
    for row in rows:
        h.update(repr(row).encode("utf-8"))
    return h.hexdigest()


def tracks_fingerprint(rows):
    """A sha1 hex digest over the raw track fields build_units consumes —
    title, composer, performers, broadcast_date, length. Computed straight
    from load_tracks + with_track_lengths output, so it costs no
    canonicalization and is available *before* the ~80s build_units pass;
    that is what lets the units cache be checked cheaply. The time_str
    column is excluded — build_units ignores it."""
    h = hashlib.sha1()
    for title, composer, performers, date, _time, length in rows:
        h.update(repr((title, composer, performers, date, length))
                 .encode("utf-8"))
    return h.hexdigest()


def write_cache(path, data_fp, code_fp, candidates):
    """Write the whole-DB multi-play scan to a self-keyed JSON cache file.
    Pretty-printed with sorted keys so it reads cleanly when opened for
    triage; the `candidates` list keeps multiplay_candidates' own sorted
    order (json.dump sorts dict keys, not list elements)."""
    payload = {"data_hash": data_fp, "code_hash": code_fp,
               "generated_at": datetime.now().isoformat(timespec="seconds"),
               "candidates": candidates}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def read_cache(path, data_fp, code_fp):
    """The cached candidate list when the cache file at `path` exists and
    both its stored fingerprints match the supplied pair — otherwise None
    (file missing, unreadable, or stale). This is the cache hit/miss
    decision."""
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if (payload.get("data_hash") == data_fp
            and payload.get("code_hash") == code_fp):
        return payload.get("candidates")
    return None


def _unit_to_dict(u):
    """A Unit as a JSON-native dict. credit_key is not stored — it is
    recomputed from credit on load."""
    return {"composer": u.composer, "composer_display": u.composer_display,
            "work_key": u.work_key, "title": u.title, "date": u.date,
            "length": u.length, "catalogue": u.catalogue,
            "conductors": sorted(u.credit.conductors),
            "soloists": sorted(u.credit.soloists),
            "ensembles": sorted(u.credit.ensembles),
            "degraded": u.credit.degraded}


def _unit_from_dict(d):
    """Rebuild a Unit from _unit_to_dict's output; credit_key is recomputed
    from the reconstructed CreditSig."""
    sig = CreditSig(frozenset(d["conductors"]), frozenset(d["soloists"]),
                    frozenset(d["ensembles"]), d["degraded"])
    return Unit(d["composer"], d["composer_display"], d["work_key"],
                d["title"], sig, credit_key(sig), d["date"], d["length"],
                d["catalogue"])


def write_units_cache(path, tracks_fp, code_fp, units):
    """Write build_units' whole-DB output to a self-keyed JSON cache file,
    so a later run on an unchanged DB skips the ~80s canonicalization pass.
    Not pretty-printed — this is bulk derived data (one record per track),
    not a file read for triage."""
    payload = {"tracks_hash": tracks_fp, "code_hash": code_fp,
               "generated_at": datetime.now().isoformat(timespec="seconds"),
               "units": [_unit_to_dict(u) for u in units]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def read_units_cache(path, tracks_fp, code_fp):
    """build_units' cached whole-DB output as a list of Units, when the
    cache file at `path` exists and both stored fingerprints match the
    supplied pair — otherwise None (file missing, unreadable, or stale)."""
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    units = payload.get("units")
    if (payload.get("tracks_hash") == tracks_fp
            and payload.get("code_hash") == code_fp
            and units is not None):
        return [_unit_from_dict(d) for d in units]
    return None


# --- CLI -----------------------------------------------------------------

def _composer_display(units):
    """{composer_key: most common original spelling} across all units."""
    seen = defaultdict(Counter)
    for u in units:
        seen[u.composer][u.composer_display] += 1
    return {k: max(c.items(), key=lambda kv: (kv[1], kv[0]))[0]
            for k, c in seen.items()}


def main(argv=None):
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(
        description="Find re-aired recordings in ttn.sqlite.")
    parser.add_argument("db", help="path to the SQLite database")
    parser.add_argument("--top", type=int, default=20,
                        help="rows per length band (default 20)")
    parser.add_argument("--composer", help="restrict to composers matching "
                        "this case-insensitive substring")
    parser.add_argument("--csv", help="also write the report flat to this "
                        "CSV path")
    parser.add_argument("--multiplay", action="store_true",
                        help="also show the multi-play merge-candidate "
                        "section (cached to ttn_rebroadcast_cache.json)")
    parser.add_argument("--emit", action="store_true",
                        help="in the multi-play section, append paste-ready "
                        "WORK_ALIASES tuples and test groups (implies "
                        "--multiplay)")
    args = parser.parse_args(argv)

    # sqlite3.connect() would silently CREATE a missing file — guard so a
    # wrong path is a clean error, not a confusing "no such table" later.
    if not os.path.isfile(args.db):
        parser.error(f"database not found: {args.db}")

    here = os.path.dirname(os.path.abspath(__file__))
    code_fp = code_fingerprint(here)
    show_multiplay = args.multiplay or args.emit

    conn = sqlite3.connect(args.db)
    try:
        rows = with_track_lengths(load_tracks(conn))
    finally:
        conn.close()

    units_cache_path = os.path.join(here, "ttn_rebroadcast_units_cache.json")
    tracks_fp = tracks_fingerprint(rows)
    units = read_units_cache(units_cache_path, tracks_fp, code_fp)
    if units is None:
        units = build_units(rows)
        write_units_cache(units_cache_path, tracks_fp, code_fp, units)

    if args.composer:
        sub = args.composer.lower()
        display = _composer_display(units)
        units = [u for u in units if sub in display[u.composer].lower()]

    composer_display = _composer_display(units)
    clusters = rebroadcast_clusters(units)
    entries = collapse_multimovement(clusters)
    print(render_report(entries, composer_display, args.top))

    if show_multiplay:
        decided = load_decisions(
            os.path.join(here, "ttn_rebroadcast_decisions.json"))
        if args.composer:
            # a per-composer subset is already fast — compute it fresh; the
            # cache holds only the whole-DB scan (a candidate carries no
            # composer field, so a cached result cannot be filtered down).
            candidates = multiplay_candidates(units, decided)
        else:
            cache_path = os.path.join(here, "ttn_rebroadcast_cache.json")
            data_fp = data_fingerprint(units)
            candidates = read_cache(cache_path, data_fp, code_fp)
            if candidates is None:
                candidates = multiplay_candidates(units, decided)
                write_cache(cache_path, data_fp, code_fp, candidates)
        print(render_multiplay(candidates, args.emit))

    if args.csv:
        write_csv(args.csv, entries, composer_display)
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
