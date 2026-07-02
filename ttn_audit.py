#!/usr/bin/env python3
"""Find re-airing merge candidates in ttn.sqlite — works the BBC aired more
than once under different titles. A report-for-triage tool: it surfaces
candidates and emits paste-ready WORK_ALIASES tuples and tests, but never
writes to the DB or the alias tables.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict, namedtuple
from itertools import combinations

from ttn_analyze import (canonical_key, catalogue_ref, normalize_composer,
                         normalize_work, resolve_composer_alias,
                         resolve_work_alias, work_title_key)
from ttn_db import open_db

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


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _same_night(when_a, when_b):
    """True if two airings share a broadcast date — a sibling of conflict()
    that disqualifies a pair on dates rather than titles. Through the Night
    does not play a piece twice in one night, so a same-date pair is two
    tracks of one recital, not a re-airing. `when` is the OneOff display
    string 'YYYY-MM-DD HH:MM AM'; a missing/unparseable date yields False
    (the check abstains). The clock-change nights with three broadcasts
    are the one place this could in principle reject a real re-airing —
    accepted, since a within-night repeat is otherwise unheard of."""
    ma = _DATE_RE.match(when_a or "")
    mb = _DATE_RE.match(when_b or "")
    return ma is not None and mb is not None and ma.group() == mb.group()


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
# when: broadcast date + time, for display. cat: catalogue_ref(title) or "".
# length: minutes to the next track (a broadcast-length proxy) or None.
OneOff = namedtuple("OneOff", "title performers names when cat length")


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
    # per-title token sets, hoisted out of the O(k^2) pair loop
    tokens = [frozenset(canonical_key(o.title).split()) for o in oneoffs]
    for (i, a), (j, b) in combinations(enumerate(oneoffs), 2):
        if a.cat and b.cat:
            same_work = a.cat == b.cat
        else:
            ta, tb = tokens[i], tokens[j]
            inter = len(ta & tb)
            union = len(ta) + len(tb) - inter
            same_work = union > 0 and inter / union >= 0.55
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


_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AP]M)\b", re.I)
_MAX_PLAUSIBLE_GAP = 90   # minutes; a longer gap means a track went missing


def _parse_minutes(time_str):
    """Minutes since midnight for a 'HH:MM AM' track time, or None when the
    string can't be parsed. A trailing timezone (BST/GMT) is tolerated."""
    m = _TIME_RE.search(time_str or "")
    if not m:
        return None
    hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
    hour %= 12                       # 12 AM -> 0; 12 PM -> 0, then +12 below
    if meridiem.upper() == "PM":
        hour += 12
    return hour * 60 + minute


def with_track_lengths(rows):
    """rows: (episode_pid, position, time_str, title, composer, performers,
    broadcast_date) — every track of every episode. Returns the trimmed
    (title, composer, performers, broadcast_date, time_str, length) rows,
    where length is the minutes to the next track in the same episode — a
    broadcast-length proxy. length is None for the last track of an
    episode, for an unparseable time on either side, and for an
    implausible gap: a long one (a track between the two went missing) or
    a negative one that is not a midnight crossing (tracks out of order)."""
    minutes = {(ep, pos): _parse_minutes(ts) for ep, pos, ts, *_ in rows}
    out = []
    for ep, pos, ts, title, composer, performers, bd in rows:
        cur, nxt = minutes[(ep, pos)], minutes.get((ep, pos + 1))
        length = None
        if cur is not None and nxt is not None:
            gap = nxt - cur
            if gap < 0:
                gap += 24 * 60            # the episode crossed midnight
            if 0 < gap <= _MAX_PLAUSIBLE_GAP:
                length = gap
        out.append((title, composer, performers, bd, ts, length))
    return out


def oneoffs_by_composer(rows):
    """rows: iterable of (title, composer, performers, broadcast_date,
    time_str, length). Returns {composer_display: [OneOff, ...]} — one
    OneOff per work a composer played exactly once. Tracks are grouped
    into (composer, work) pairs by the same keys the --by work rollup
    uses."""
    groups = defaultdict(list)
    names = defaultdict(Counter)
    for title, composer, performers, date, time, length in rows:
        nc = normalize_composer(composer)
        nw = normalize_work(title)
        if not nc or not nw:
            continue
        ckey = resolve_composer_alias(canonical_key(nc))
        wkey = resolve_work_alias(work_title_key(nw, nc))
        when = f"{(date or '')[:10]} {time or ''}".strip()
        groups[(ckey, wkey)].append((nw, performers or "", when, length))
        # tally spellings across ALL of a composer's plays, not just the
        # one-offs — the display name should reflect their whole presence.
        names[ckey][nc] += 1
    out = defaultdict(list)
    for (ckey, wkey), tracks in groups.items():
        if len(tracks) != 1:
            continue
        nw, performers, when, length = tracks[0]
        # most common spelling wins; tie broken on the spelling itself so
        # the display pick is deterministic regardless of row order.
        display = max(names[ckey].items(), key=lambda kv: (kv[1], kv[0]))[0]
        out[display].append(
            OneOff(nw, performers, _performer_names(performers),
                   when, catalogue_ref(nw), length))
    return dict(out)


# clean_groups: [(members, pairs)] — members is a set of titles, pairs the
# surviving candidate pairs that connect them. review_groups: [(members,
# decomp)]. rejected_count: structural conflicts + same-night pairs.
# decided_count: pairs dropped by the decisions file. by_title: {title:
# OneOff}.
AuditResult = namedtuple(
    "AuditResult",
    "clean_groups review_groups rejected_count decided_count by_title")


def audit_composer(oneoffs, decided_ids=frozenset()):
    """Run the full pipeline for one composer's one-off works and return an
    AuditResult: candidate pairs from find_pairs() are split three ways —
    decided (candidate id in `decided_ids`, a human-rejected semantic false
    positive from the decisions file), rejected (a structural title
    conflict, or a same-night airing), and clean; clean pairs are grouped by
    union-find, and each component is routed to clean_groups (conflict-free)
    or review_groups (cascade-bridged). Decided and rejected pairs are both
    dropped before grouping, so neither can bridge a component.
    `oneoffs` should have unique titles — by_title is a {title: OneOff}
    dict that would silently drop a clash."""
    by_title = {o.title: o for o in oneoffs}
    # work in titles from here on: they are the stable identity and the
    # union-find keys; the OneOff objects are re-fetched via by_title.
    title_pairs = [(a.title, b.title) for a, b in find_pairs(oneoffs)]
    clean, rejected, decided = [], [], []
    for ta, tb in title_pairs:
        # a human verdict is the most specific signal — checked first, so a
        # decided pair is tallied as decided even if it also conflicts.
        if candidate_id(ta, tb) in decided_ids:
            decided.append((ta, tb))
        # not a merge if the titles structurally conflict, or if the two
        # aired the same night (two tracks of one recital).
        elif conflict(ta, tb) or _same_night(by_title[ta].when,
                                             by_title[tb].when):
            rejected.append((ta, tb))
        else:
            clean.append((ta, tb))
    clean_groups, review_groups = [], []
    for members in components(clean):
        comp_pairs = [p for p in clean
                      if p[0] in members and p[1] in members]
        decomp = bridge_decomposition(members, comp_pairs)
        if decomp is None:
            clean_groups.append((members, comp_pairs))
        else:
            review_groups.append((members, decomp))
    # sort both lists so report output is stable regardless of input order.
    clean_groups.sort(key=lambda mp: sorted(mp[0]))
    review_groups.sort(key=lambda mr: sorted(mr[0]))
    return AuditResult(clean_groups, review_groups, len(rejected),
                       len(decided), by_title)


# --- I/O: database read --------------------------------------------------

def load_tracks(conn):
    """Every track as (episode_pid, position, time_str, title, composer,
    performers, broadcast_date) — the shape with_track_lengths() expects."""
    return conn.execute(
        "SELECT t.episode_pid, t.position, t.time_str, t.title, t.composer, "
        "t.performers, e.broadcast_date "
        "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid "
        "WHERE t.title IS NOT NULL AND t.title != ''").fetchall()


def load_decisions(path):
    """The set of candidate ids a human has triaged and rejected — read from
    a ttn_audit_decisions.json file: every `candidate_ids` entry under its
    `rejected` list, pooled. Pairs whose id is in this set are dropped
    before grouping (see audit_composer), so a known semantic false
    positive — one the tool has no structural signal for — stops
    resurfacing on every run. A missing file yields an empty set: the audit
    still runs, just statelessly."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return frozenset()
    ids = set()
    for entry in data.get("rejected", []):
        ids.update(entry.get("candidate_ids", []))
    return frozenset(ids)


def _fmt_group(members, pairs, by_title):
    """One indented block per merge group: each member's broadcast date and
    time, approximate broadcast length, title and performers, headed by the
    candidate id of every contributing pair."""
    lines = []
    for title in sorted(members):
        o = by_title[title]
        # width 6 fits "(~NNm)" — a 2-digit length, capped by
        # _MAX_PLAUSIBLE_GAP (90); widen this if that cap ever rises.
        length = f"(~{o.length}m)" if o.length is not None else "( ? )"
        head = f"      {o.when:<19}  {length:>6}  "
        lines.append(head + title)
        lines.append(" " * len(head) + o.performers)
    ids = " ".join(f"[{cid}]"
                   for cid in sorted(candidate_id(a, b) for a, b in pairs))
    return f"   {ids}\n" + "\n".join(lines)


def render_report(composer, result):
    """Human-readable audit report for one composer."""
    out = [f"\n{'=' * 72}\n{composer}\n{'=' * 72}"]

    out.append(f"\nCLEAN MERGE CANDIDATES: {len(result.clean_groups)}")
    for members, pairs in result.clean_groups:
        out.append(_fmt_group(members, pairs, result.by_title))

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
    if result.decided_count:
        out.append(f"suppressed by decisions file: "
                   f"{result.decided_count}")
    return "\n".join(out)


def render_emit(composer, result):
    """Paste-ready WORK_ALIASES tuples and test groups for the CLEAN merge
    candidates only. Needs-review components are deliberately excluded."""
    groups = [sorted(m) for m, _pairs in result.clean_groups]
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
# (open_db moved to ttn_db so every tool CLI shares the missing-file guard.)


def main(argv=None):
    import argparse
    import os

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

    conn = open_db(args.db, parser)
    try:
        by_composer = oneoffs_by_composer(
            with_track_lengths(load_tracks(conn)))
    finally:
        conn.close()

    # decisions file sits beside this script, not beside the DB — load it
    # cwd-independently so `uv run ttn_audit.py` works from anywhere.
    decided = load_decisions(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "ttn_audit_decisions.json"))

    if args.composer:
        sub = args.composer.lower()
        names = sorted(c for c in by_composer if sub in c.lower())
    else:
        names = sorted(by_composer)

    for composer in names:
        result = audit_composer(by_composer[composer], decided)
        if not result.clean_groups and not result.review_groups:
            continue
        print(render_report(composer, result))
        if args.emit and result.clean_groups:
            print(render_emit(composer, result))
