#!/usr/bin/env python3
"""Find re-airing merge candidates in ttn.sqlite — works the BBC aired more
than once under different titles. A report-for-triage tool: it surfaces
candidates and emits paste-ready WORK_ALIASES tuples and tests, but never
writes to the DB or the alias tables. See
docs/superpowers/specs/2026-05-16-ttn-audit-design.md.
"""
import hashlib
import re
from collections import Counter, defaultdict, namedtuple
from itertools import combinations

from ttn_analyze import (canonical_key, catalogue_ref, normalize_composer,
                         normalize_work, resolve_composer_alias,
                         resolve_work_alias, work_title_key)

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


# --- pure logic: one-off works and pairing -------------------------------

# title: normalize_work() output. performers: raw string (for display).
# names: frozenset of canonical performer-name tokens (for matching).
# date: broadcast date (YYYY-MM-DD). cat: catalogue_ref(title) or "".
OneOff = namedtuple("OneOff", "title performers names date cat")


def _performer_names(performers):
    """Canonical performer/ensemble name tokens from a performers string,
    with parenthesised roles and instruments stripped — including an
    unclosed trailing role like "(cello" with no closing paren. " and "
    is a split point, so an ensemble name containing "and" gets split —
    harmless, since both sides of a comparison are split identically."""
    bare = re.sub(r"\([^)]*\)", "", performers)   # balanced () pairs
    bare = re.sub(r"\([^)]*$", "", bare)          # an unclosed trailing (
    out = set()
    for part in re.split(r"[,;|]| and ", bare):
        key = canonical_key(part).strip()
        if key:
            out.add(key)
    return frozenset(out)


def find_pairs(oneoffs):
    """Candidate re-airing pairs among one composer's one-off works: a
    same-work signal (shared catalogue ref, or title-token Jaccard
    >= 0.55) AND matching performers (name-set overlap >= 50% of the
    smaller set). Returns a list of (OneOff, OneOff)."""
    pairs = []
    for a, b in combinations(oneoffs, 2):
        if a.cat and b.cat:
            same_work = a.cat == b.cat
        else:
            ta = set(canonical_key(a.title).split())
            tb = set(canonical_key(b.title).split())
            union = ta | tb
            same_work = bool(union) and len(ta & tb) / len(union) >= 0.55
        if not same_work:
            continue
        if not a.names or not b.names:
            continue
        overlap = a.names & b.names
        if not overlap:
            continue
        if len(overlap) / min(len(a.names), len(b.names)) < 0.5:
            continue
        pairs.append((a, b))
    return pairs


def oneoffs_by_composer(rows):
    """rows: iterable of (title, composer, performers, broadcast_date).
    Returns {composer_display: [OneOff, ...]} — one OneOff per work a
    composer played exactly once. Tracks are grouped into (composer, work)
    pairs by the same keys the --by work rollup uses."""
    groups = defaultdict(list)
    names = defaultdict(Counter)
    for title, composer, performers, date in rows:
        nc = normalize_composer(composer)
        nw = normalize_work(title)
        if not nc or not nw:
            continue
        ckey = resolve_composer_alias(canonical_key(nc))
        wkey = resolve_work_alias(work_title_key(nw))
        groups[(ckey, wkey)].append((nw, performers or "", (date or "")[:10]))
        # tally spellings across ALL of a composer's plays, not just the
        # one-offs — the display name should reflect their whole presence.
        names[ckey][nc] += 1
    out = defaultdict(list)
    for (ckey, wkey), tracks in groups.items():
        if len(tracks) != 1:
            continue
        nw, performers, date = tracks[0]
        # most common spelling wins; tie broken on the spelling itself so
        # the display pick is deterministic regardless of row order.
        display = max(names[ckey].items(), key=lambda kv: (kv[1], kv[0]))[0]
        out[display].append(
            OneOff(nw, performers, _performer_names(performers),
                   date, catalogue_ref(nw)))
    return dict(out)


# --- I/O: database read --------------------------------------------------

def load_tracks(conn):
    """All (title, composer, performers, broadcast_date) track rows."""
    return conn.execute(
        "SELECT t.title, t.composer, t.performers, e.broadcast_date "
        "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid "
        "WHERE t.title IS NOT NULL AND t.title != ''").fetchall()
