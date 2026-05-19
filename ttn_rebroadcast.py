#!/usr/bin/env python3
"""Find re-aired recordings in ttn.sqlite — a specific performance (one
work, one set of forces) that Through the Night broadcast on two or more
nights. Prints a banded "top X" rebroadcast report; with --emit, also
emits paste-ready WORK_ALIASES tuples for multi-play merge candidates
(one recording aired under variant titles). A report-for-insight /
report-for-triage tool: it never writes to the DB or the alias tables.
See docs/superpowers/specs/2026-05-18-ttn-rebroadcast-design.md.
"""
import csv
import re
import statistics
from collections import Counter, defaultdict, namedtuple
from datetime import date

from ttn_analyze import (canonical_key, catalogue_ref, normalize_composer,
                         normalize_work, resolve_composer_alias,
                         resolve_work_alias, work_title_key)
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
    ttn_audit's find_pairs() same-work test."""
    if unit_a.catalogue and unit_b.catalogue:
        return unit_a.catalogue == unit_b.catalogue
    ta = set(canonical_key(unit_a.title).split())
    tb = set(canonical_key(unit_b.title).split())
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
