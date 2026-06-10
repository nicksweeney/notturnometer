#!/usr/bin/env python3
"""Parse Through the Night long_synopsis performer credits into role-typed
performance Units — the shared credit/unit primitive (extracted from the retired
ttn_rebroadcast.py). ttn_bridge consumes build_units / cluster_length /
representative_title to cluster text-only airings before signature-matching them
to PID-era spine recordings. Pure logic over tracks rows; no DB, no caches."""
import re
import statistics
from collections import Counter, namedtuple

from ttn_analyze import (canonical_key, catalogue_ref, normalize_composer,
                         normalize_work, resolve_composer_alias,
                         resolve_work_alias, work_title_key)


# --- the credit signature ------------------------------------------------

# conductors / soloists / ensembles: frozensets of credited names in their
# original spelling (credit_key folds them through canonical_key — see there).
# degraded: the performers string carried no (role) parenthetical at all.
CreditSig = namedtuple("CreditSig", "conductors soloists ensembles degraded")

# a name-segment ending in a (role): captures the name and the role text.
_SEG_ROLE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*\.?\s*$")
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
    to ensembles. Names are kept in their original spelling for display;
    the canonical fold happens in credit_key, the actual clustering key."""
    s = performers or ""
    degraded = "(" not in s
    cond, solo, ens = set(), set(), set()
    for seg in re.split(r"[,;|]| and ", s):
        seg = seg.strip()
        if not seg:
            continue
        m = _SEG_ROLE.match(seg)
        name, role = (m.group(1), m.group(2)) if m else (seg, "")
        name = name.strip()
        if not canonical_key(name):       # nothing nameable in this segment
            continue
        if role and _CONDUCTOR_ROLE.search(role):
            cond.add(name)
        elif (not role) or _ENSEMBLE_ROLE.search(role):
            ens.add(name)
        else:
            solo.add(name)
    return CreditSig(frozenset(cond), frozenset(solo), frozenset(ens),
                     degraded)


def credit_key(sig):
    """The flattened, canonical-folded set of every credited name — the
    clustering key. The CreditSig keeps names in their display spelling;
    credit_key folds them through canonical_key, so differently-cased or
    transliterated spellings of one set of forces still cluster. A changed
    conductor changes a name and so splits the cluster — the warhorse
    false-positive defence. Role-blind on purpose: it makes a degraded
    (bare-string) unit cluster naturally with a role-tagged airing of the
    same forces."""
    return frozenset(canonical_key(n)
                     for n in sig.conductors | sig.soloists | sig.ensembles)


# --- performance units ---------------------------------------------------

# composer: canonical, alias-resolved (grouping key). composer_display:
# the original spelling (display). work_key: resolve_work_alias(
# work_title_key(...)). title: normalize_work output. credit: the CreditSig.
# credit_key: flattened name-set. date: 'YYYY-MM-DD'. length: minutes proxy
# or None. catalogue: catalogue_ref(title) or ''.
Unit = namedtuple("Unit", "composer composer_display work_key title "
                          "credit credit_key date length catalogue")


def build_units(rows):
    """rows: (title, composer, performers, broadcast_date, time_str,
    length). One Unit per track; tracks with no composer or no work-key
    are dropped."""
    units = []
    for title, composer, performers, date, _time, length in rows:
        nc = normalize_composer(composer)
        nw = normalize_work(title)
        if not nc or not nw:
            continue
        ckey = resolve_composer_alias(canonical_key(nc))
        wkey = resolve_work_alias(work_title_key(nw, nc))
        if not ckey or not wkey:
            continue
        sig = parse_credit(performers or "")
        units.append(Unit(ckey, nc, wkey, nw, sig, credit_key(sig),
                           (date or "")[:10], length, catalogue_ref(nw)))
    return units


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
