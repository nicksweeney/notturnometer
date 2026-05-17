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


# clean_groups: [set of titles]. review_groups: [(members, decomp)].
# rejected_count: int. by_title: {title: OneOff}.
AuditResult = namedtuple(
    "AuditResult", "clean_groups review_groups rejected_count by_title")


def audit_composer(oneoffs):
    """Run the full pipeline for one composer's one-off works and return an
    AuditResult: candidate pairs from find_pairs() are split into directly
    conflicting (counted as rejected) and clean; clean pairs are grouped by
    union-find, and each component is routed to clean_groups (conflict-free)
    or review_groups (cascade-bridged). `oneoffs` should have unique titles
    — by_title is a {title: OneOff} dict that would silently drop a clash."""
    by_title = {o.title: o for o in oneoffs}
    title_pairs = [(a.title, b.title) for a, b in find_pairs(oneoffs)]
    clean = [p for p in title_pairs if not conflict(*p)]
    rejected = [p for p in title_pairs if conflict(*p)]
    clean_groups, review_groups = [], []
    for members in components(clean):
        comp_pairs = [p for p in clean
                      if p[0] in members and p[1] in members]
        decomp = bridge_decomposition(members, comp_pairs)
        if decomp is None:
            clean_groups.append(members)
        else:
            review_groups.append((members, decomp))
    # sort both lists so report output is stable regardless of input order.
    clean_groups.sort(key=lambda m: sorted(m))
    review_groups.sort(key=lambda mr: sorted(mr[0]))
    return AuditResult(clean_groups, review_groups, len(rejected), by_title)


# --- I/O: database read --------------------------------------------------

def load_tracks(conn):
    """All (title, composer, performers, broadcast_date) track rows."""
    return conn.execute(
        "SELECT t.title, t.composer, t.performers, e.broadcast_date "
        "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid "
        "WHERE t.title IS NOT NULL AND t.title != ''").fetchall()


def _fmt_group(members, by_title):
    """One indented block per merge group: each member's date, title,
    performers, and the pair id linking the first two members."""
    members = sorted(members)
    lines = []
    for title in members:
        o = by_title[title]
        lines.append(f"      {o.date}  {title}")
        lines.append(f"                  {o.performers}")
    cid = candidate_id(members[0], members[1]) if len(members) > 1 else ""
    return f"   [{cid}]\n" + "\n".join(lines)


def render_report(composer, result):
    """Human-readable audit report for one composer."""
    out = [f"\n{'=' * 72}\n{composer}\n{'=' * 72}"]

    out.append(f"\nCLEAN MERGE CANDIDATES: {len(result.clean_groups)}")
    for members in sorted(result.clean_groups, key=lambda m: sorted(m)[0]):
        out.append(_fmt_group(members, result.by_title))

    out.append(f"\n⚠ NEEDS REVIEW: {len(result.review_groups)}")
    for members, decomp in result.review_groups:
        out.append(f"   component of {len(members)}, "
                   f"internal conflict(s): {len(decomp['conflicts'])}")
        for x, y in decomp["conflicts"]:
            out.append(f"      conflict:  {x}")
            out.append(f"                 {y}")
        if decomp["bridge"]:
            out.append(f"   without bridge {sorted(decomp['bridge'])}:")
            for sub in decomp["subgroups"]:
                out.append(f"      merge group: {sorted(sub)}")
            out.append(f"      orphans: {sorted(decomp['orphans'])}")
        else:
            out.append("   no single bridge resolves it — inspect by hand")

    out.append(f"\nrejected pairs (directly conflicting): "
               f"{result.rejected_count}")
    return "\n".join(out)


def render_emit(composer, result):
    """Paste-ready WORK_ALIASES tuples and test groups for the CLEAN merge
    candidates only. Needs-review components are deliberately excluded."""
    groups = [sorted(m) for m in result.clean_groups]
    groups.sort()
    out = [f"\n# === {composer}: {len(groups)} merge groups ===",
           "\n# --- WORK_ALIASES tuples (paste into _WORK_ALIAS_PAIRS) ---"]
    for g in groups:
        target = g[0]
        for variant in g[1:]:
            out.append(f"    ({variant!r},")
            out.append(f"     {target!r}),")
    out.append("\n# --- test groups (paste into a _REAIRING_GROUPS list) ---")
    for g in groups:
        out.append(f"    {g!r},")
    return "\n".join(out)


# --- CLI -----------------------------------------------------------------

def main(argv=None):
    import argparse
    import os
    import sqlite3

    parser = argparse.ArgumentParser(
        description="Find --once re-airing merge candidates in ttn.sqlite.")
    parser.add_argument("db", help="path to the SQLite database")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--composer", help="audit composers matching this "
                       "substring (case-insensitive)")
    group.add_argument("--all", action="store_true",
                       help="audit every composer")
    parser.add_argument("--emit", action="store_true",
                        help="append paste-ready alias tuples and tests")
    args = parser.parse_args(argv)

    # sqlite3.connect() would silently CREATE a missing file — guard so a
    # wrong path is a clean error, not a confusing "no such table" later.
    if not os.path.isfile(args.db):
        parser.error(f"database not found: {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        by_composer = oneoffs_by_composer(load_tracks(conn))
    finally:
        conn.close()

    if args.composer:
        sub = args.composer.lower()
        names = sorted(c for c in by_composer if sub in c.lower())
    else:
        names = sorted(by_composer)

    for composer in names:
        result = audit_composer(by_composer[composer])
        if not result.clean_groups and not result.review_groups:
            continue
        print(render_report(composer, result))
        if args.emit and result.clean_groups:
            print(render_emit(composer, result))


if __name__ == "__main__":
    main()
