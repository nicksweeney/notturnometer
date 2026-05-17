#!/usr/bin/env python3
"""Find re-airing merge candidates in ttn.sqlite — works the BBC aired more
than once under different titles. A report-for-triage tool: it surfaces
candidates and emits paste-ready WORK_ALIASES tuples and tests, but never
writes to the DB or the alias tables. See
docs/superpowers/specs/2026-05-16-ttn-audit-design.md.
"""
import hashlib
import re

from ttn_analyze import canonical_key

# --- pure logic: conflict detection --------------------------------------

_KEY_FULL = re.compile(r"\b([a-g])(?:\s+(flat|sharp))?\s+(major|minor)\b")
# "volume" before "vol" — longest alternative first, so "Volume II" is not
# matched as "vol" + a captured "ume".
_PART_RE = re.compile(r"\b(?:part|act|book|volume|vol)\s*\.?\s*(\w+)\b")


def _identity(title):
    """(numbers, modes-by-note, parts) of a title — the tokens that, when
    they disagree between two titles, mark them as distinct works."""
    s = canonical_key(title)
    numbers = frozenset(re.findall(r"\d+", s))
    modes = {(note, acc or ""): mode
             for note, acc, mode in _KEY_FULL.findall(s)}
    parts = frozenset(_PART_RE.findall(s))
    return numbers, modes, parts


def conflict(title_a, title_b):
    """True if two titles disagree on a number, key/mode or part — i.e.
    they are distinct works, not two rephrasings of one."""
    na, ma, pa = _identity(title_a)
    nb, mb, pb = _identity(title_b)
    if any(ma[k] != mb[k] for k in ma.keys() & mb.keys()):
        return True
    if pa and pb and pa != pb:
        return True
    return na != nb and not (na <= nb or nb <= na)


def candidate_id(title_a, title_b):
    """Stable 8-hex id for a candidate pair. Hashes the (sorted) broadcast
    titles themselves — not work_title_key output — so the id survives
    changes to the canonicalization rules. This is the seam a future
    decisions file would key against."""
    joined = "\x00".join(sorted((title_a, title_b)))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]
