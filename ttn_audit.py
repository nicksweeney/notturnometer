#!/usr/bin/env python3
"""Find re-airing merge candidates in ttn.sqlite — works the BBC aired more
than once under different titles. A report-for-triage tool: it surfaces
candidates and emits paste-ready WORK_ALIASES tuples and tests, but never
writes to the DB or the alias tables. See
docs/superpowers/specs/2026-05-16-ttn-audit-design.md.
"""
import hashlib
import re
from itertools import combinations

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
    # NUL-join is unambiguous here: BBC broadcast titles never contain U+0000.
    joined = "\x00".join(sorted((title_a, title_b)))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]


def components(pairs):
    """Connected components — a list of member sets — over a list of
    (a, b) pairs."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b in pairs:
        # No union-by-rank: path compression alone is ample at this scale.
        parent[find(a)] = find(b)
    groups = {}
    for node in list(parent):
        groups.setdefault(find(node), set()).add(node)
    return list(groups.values())


def _has_internal_conflict(members):
    """True if any two members of a component conflict pairwise."""
    return any(conflict(x, y)
               for x, y in combinations(sorted(members), 2))


def bridge_decomposition(members, pairs):
    """Return None if the component is conflict-free. Otherwise it was
    fused by a cascade bridge: find the smallest set of members whose
    removal makes it conflict-free, and return the decomposition
    {conflicts, bridge, subgroups, orphans}. Components are tiny, so
    brute force is fine.

    `pairs` must be the component's own connecting pairs — the subset of
    candidate pairs with both endpoints in `members`.

    Removing all but one member trivially resolves any conflict, so the
    loop always finds a bridge; the final `bridge: None` return is an
    unreachable defensive guard (it flags for review rather than risk a
    false "clean" None if that invariant is ever broken)."""
    if not _has_internal_conflict(members):
        return None
    members = set(members)
    conflicts = [(x, y) for x, y in combinations(sorted(members), 2)
                 if conflict(x, y)]
    for k in range(1, len(members)):
        for bridge in combinations(sorted(members), k):
            remaining = members - set(bridge)
            subpairs = [p for p in pairs
                        if p[0] in remaining and p[1] in remaining]
            subcomps = components(subpairs)
            if any(_has_internal_conflict(c) for c in subcomps):
                continue
            covered = set().union(*subcomps) if subcomps else set()
            return {"conflicts": conflicts,
                    "bridge": set(bridge),
                    "subgroups": [c for c in subcomps if len(c) > 1],
                    "orphans": set(bridge) | (remaining - covered)}
    # Defensive only — see docstring; never reached for real input.
    return {"conflicts": conflicts, "bridge": None,
            "subgroups": [], "orphans": set(members)}
