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
