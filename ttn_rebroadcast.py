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
