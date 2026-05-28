"""ttn_audit_composer — composer-deep-dive audit helper.

Surfaces candidate fold-pairs within one composer's catalogue: groups
that share an Op/catalogue ref or a strong title-token overlap and that
are probably the same work split across different BBC phrasings.

Output is a plain-text report. Each candidate shows the groups, their
airing counts, sample titles, and the corpus-wide composer-exclusivity
of each variant key (the gate I keep retyping inline). Pass --emit to
also print paste-ready _WORK_ALIAS_PAIRS tuples and same-group tests.

Decision-making (excerpt-vs-whole, scoring policy, set-catalogue
distinctions) stays manual — the tool surfaces; the human decides.

Usage:
    uv run ttn_audit_composer.py ttn.sqlite --composer Satie
    uv run ttn_audit_composer.py ttn.sqlite --composer Liszt --emit
    uv run ttn_audit_composer.py ttn.sqlite --composer Debussy --min-airings 3
"""

import argparse
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

from ttn_analyze import (canonical_key, resolve_composer_alias,
                         resolve_work_alias, work_title_key)


# --- catalogue and Op extraction -----------------------------------------

# Matches BWV, RV, K, D, Hob, HWV, TWV, WoO, Wq, Sz, BuxWV, MWV, FP, S, L,
# M (Marnat) catalogue refs. Greedy on the numeric suffix to keep e.g.
# "K.299b" together.
_CAT_RE = re.compile(
    r"\b(BWV|RV|K|D|Hob|HWV|TWV|WoO|Wq|Sz|BuxWV|MWV|FP|S|L|M)\W?\s*"
    r"(\d+[\w\.]*)", re.I)

# Matches "Op 35", "Op.35", "Op. 35" — but NOT "Op 35 no 1" tail. Captures
# just the bare opus number for bucket-matching.
_OP_RE = re.compile(r"\bop\b\s*\.?\s*(\d+)", re.I)

# Title tokens that don't disambiguate works. Drop before computing token
# overlap. Includes form names and connectives.
_STOPWORDS = frozenset((
    "the", "a", "an", "and", "of", "in", "from", "for", "to", "by", "with",
    "on", "or", "y", "e", "et", "i", "et", "der", "die", "das", "le", "la",
    "les", "un", "une", "del", "de", "da", "do", "il", "lo", "su", "el",
    "after", "as", "vs", "version", "vers", "arr", "arranged", "no", "nos",
    "op", "opus", "concerto", "sonata", "symphony", "symphonie", "suite",
    "quartet", "quintet", "sextet", "trio", "octet", "septet", "piece",
    "pieces", "movement", "movements", "set", "book", "books", "minor",
    "major", "flat", "sharp", "act", "scene", "excerpt", "excerpts",
    "selection", "first", "second", "third", "fourth", "fifth",
    "string", "strings", "violin", "viola", "cello", "piano", "flute",
    "oboe", "clarinet", "horn", "trumpet", "harp", "guitar", "harpsichord",
    "organ", "orchestra", "voice", "voices", "chorus", "soprano",
    "alto", "tenor", "baritone", "bass", "solo", "duet", "wind",
    "continuo", "bc",
))


def _significant_tokens(title):
    """Lower-case alphanumeric tokens with stopwords removed."""
    tokens = re.findall(r"[a-zA-ZÀ-ſ']+", title.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def _catalogue_refs(title):
    """Set of (ref_letter, number) tuples extracted from a title."""
    refs = set()
    for m in _CAT_RE.finditer(title):
        refs.add((m.group(1).upper(), m.group(2).strip(".").lower()))
    return refs


def _op_number(title):
    """First bare 'Op N' integer in the title, or None."""
    m = _OP_RE.search(title)
    return m.group(1) if m else None


# --- groups: (composer_key, work_key) -> Group -----------------------------

class Group:
    __slots__ = ("titles", "work_key", "title_counts")

    def __init__(self, work_key):
        self.work_key = work_key
        self.titles = []
        self.title_counts = Counter()

    def add(self, title):
        self.titles.append(title)
        self.title_counts[title] += 1

    @property
    def count(self):
        return len(self.titles)

    @property
    def display_title(self):
        return self.title_counts.most_common(1)[0][0]

    def all_refs(self):
        refs = set()
        for t in self.titles:
            refs |= _catalogue_refs(t)
        return refs

    def all_ops(self):
        return {_op_number(t) for t in self.titles} - {None}

    def token_set(self):
        toks = set()
        for t in self.titles:
            toks.update(_significant_tokens(t))
        return toks


def load_groups(conn, composer_substr):
    """Return groups for tracks whose composer matches `composer_substr`,
    keyed by resolved work_key. The composer-key normalization uses the
    same machinery as ttn_analyze, so aliases already in place fold here."""
    groups = defaultdict(Group)
    cur = conn.execute(
        "SELECT composer, title FROM tracks "
        "WHERE composer IS NOT NULL AND title IS NOT NULL "
        "AND LOWER(composer) LIKE ?",
        (f"%{composer_substr.lower()}%",))
    for c, t in cur:
        wk = resolve_work_alias(work_title_key(t))
        g = groups.setdefault(wk, Group(wk))
        g.add(t)
    return groups


# --- candidate detection --------------------------------------------------

class Candidate:
    __slots__ = ("groups", "reason", "shared_key")

    def __init__(self, groups, reason, shared_key=None):
        self.groups = sorted(groups, key=lambda g: -g.count)
        self.reason = reason
        self.shared_key = shared_key

    @property
    def total(self):
        return sum(g.count for g in self.groups)


def find_candidates(groups, min_per_group=2):
    """Return a list of Candidate fold-pairs/clusters.

    Two detection passes:
    1. Op/catalogue-ref bucketing: groups sharing an Op number or a
       catalogue ref (BWV, K, D, RV, …).
    2. Title-token overlap: groups sharing ≥3 significant tokens that
       weren't already paired by pass 1.
    """
    eligible = [g for g in groups.values() if g.count >= min_per_group]

    # Pass 1: bucket by catalogue ref and by Op number
    ref_buckets = defaultdict(list)
    op_buckets = defaultdict(list)
    for g in eligible:
        for ref in g.all_refs():
            ref_buckets[ref].append(g)
        for op in g.all_ops():
            op_buckets[op].append(g)

    candidates = []
    paired = set()  # frozenset({work_key, work_key, ...}) tracking output sets

    for ref, gs in ref_buckets.items():
        if len(gs) >= 2:
            key = frozenset(g.work_key for g in gs)
            if key not in paired:
                paired.add(key)
                candidates.append(
                    Candidate(gs, reason=f"shared catalogue {ref[0]}.{ref[1]}",
                              shared_key=ref))

    for op, gs in op_buckets.items():
        if len(gs) >= 2:
            key = frozenset(g.work_key for g in gs)
            if key not in paired:
                paired.add(key)
                candidates.append(
                    Candidate(gs, reason=f"shared Op {op}", shared_key=op))

    # Pass 2: title-token overlap among groups not yet flagged. Use
    # union-find to coalesce pairs into clusters (e.g., 3 groups that
    # pairwise share tokens become one 3-group candidate, not 3 pairs).
    flagged = set()
    for c in candidates:
        for g in c.groups:
            flagged.add(g.work_key)
    unflagged = [g for g in eligible if g.work_key not in flagged]
    token_sets = {g.work_key: g.token_set() for g in unflagged}

    parent = {g.work_key: g.work_key for g in unflagged}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    shared_tokens_by_pair = {}  # (root) -> sample shared-token set
    for i, ga in enumerate(unflagged):
        ta = token_sets[ga.work_key]
        if len(ta) < 3:
            continue
        for gb in unflagged[i+1:]:
            tb = token_sets[gb.work_key]
            if len(tb) < 3:
                continue
            shared = ta & tb
            if len(shared) >= 3:
                union(ga.work_key, gb.work_key)
                root = find(ga.work_key)
                shared_tokens_by_pair.setdefault(root, shared)

    # Pass 2b: subset detection for short-token groups the 3+ rule missed.
    # E.g., Janáček's bare "Pohadka" (single distinctive token) → same
    # work as "Pohadka (Fairy Tale)" (3 tokens). The 3+ rule skips the
    # bare form; subset detection catches it.
    #
    # Rule: if A's tokens ⊆ B's tokens (or vice versa), AND the shared
    # set contains at least one composer-rare token (appears in ≤ 5
    # groups within this composer), AND the smaller side has ≥ 1 token,
    # union them.
    token_doc_freq = defaultdict(int)
    for ts in token_sets.values():
        for t in ts:
            token_doc_freq[t] += 1
    RARE_THRESHOLD = 5

    for i, ga in enumerate(unflagged):
        ta = token_sets[ga.work_key]
        if not ta:
            continue
        for gb in unflagged[i+1:]:
            tb = token_sets[gb.work_key]
            if not tb:
                continue
            shared = ta & tb
            if not shared:
                continue
            # Subset condition: one side ⊆ the other (or equal). Already
            # handled by pass 2a when both have ≥3 tokens AND shared ≥3,
            # so this only adds new edges for short-token cases.
            if not (ta <= tb or tb <= ta):
                continue
            # At least one shared token must be composer-rare to avoid
            # bridging generic-form tokens like "cantata" across many works.
            if not any(token_doc_freq[t] <= RARE_THRESHOLD for t in shared):
                continue
            union(ga.work_key, gb.work_key)
            root = find(ga.work_key)
            shared_tokens_by_pair.setdefault(root, shared)

    clusters = defaultdict(list)
    for g in unflagged:
        clusters[find(g.work_key)].append(g)

    for root, gs in clusters.items():
        if len(gs) < 2:
            continue
        key = frozenset(g.work_key for g in gs)
        if key in paired:
            continue
        paired.add(key)
        shared = shared_tokens_by_pair.get(root, set())
        candidates.append(Candidate(
            gs,
            reason=f"shared tokens {sorted(shared)[:5]}",
            shared_key=tuple(sorted(shared))[:5]))

    candidates.sort(key=lambda c: -c.total)
    return candidates


# --- corpus-exclusivity check --------------------------------------------

def build_workkey_to_composers(conn):
    """Map work_title_key (raw, not alias-resolved) → set of composer_keys.
    Used to flag variant keys that aren't composer-exclusive."""
    m = defaultdict(set)
    for c, t in conn.execute(
            "SELECT composer, title FROM tracks "
            "WHERE composer IS NOT NULL AND title IS NOT NULL"):
        m[work_title_key(t)].add(resolve_composer_alias(canonical_key(c)))
    return m


def exclusivity_note(work_key, workkey_to_composers, this_composer_key):
    others = workkey_to_composers.get(work_key, set()) - {this_composer_key}
    if not others:
        return "composer-exclusive"
    return f"ALSO shared with: {sorted(others)}"


# --- report rendering ----------------------------------------------------

def render_report(composer, candidates, workkey_to_composers,
                  this_composer_key, min_total=4):
    out = [f"=== {composer}: {len(candidates)} candidate clusters ==="]
    shown = 0
    for c in candidates:
        if c.total < min_total:
            continue
        shown += 1
        out.append("")
        out.append(f"[{c.total} airings, {c.reason}]")
        for g in c.groups:
            ex = exclusivity_note(g.work_key, workkey_to_composers,
                                   this_composer_key)
            out.append(f"  ×{g.count:3}  {g.display_title!r}")
            out.append(f"         work_key: {g.work_key}")
            out.append(f"         {ex}")
            extras = [t for t, _ in g.title_counts.most_common()
                      if t != g.display_title][:2]
            for t in extras:
                out.append(f"         alt: {t!r}")
    if shown == 0:
        out.append(f"\nNo candidates with total ≥ {min_total} airings.")
    return "\n".join(out)


def render_emit(candidates, min_total=4):
    """Paste-ready _WORK_ALIAS_PAIRS tuples and test groups for each
    candidate cluster, picking the most-aired group as target."""
    out = ["", "# --- paste-ready alias tuples (verify each cluster first) ---"]
    test_groups = []
    for c in candidates:
        if c.total < min_total or len(c.groups) < 2:
            continue
        target = c.groups[0].display_title
        out.append(f"\n    # {c.reason}: total {c.total}× across {len(c.groups)} groups")
        for g in c.groups[1:]:
            variant = g.display_title
            out.append(f"    ({variant!r},")
            out.append(f"     {target!r}),")
        test_groups.append([g.display_title for g in c.groups])

    out.append("\n# --- paste-ready test groups ---")
    for tg in test_groups:
        out.append(f"    {tg!r},")
    return "\n".join(out)


# --- CLI -----------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Surface candidate fold-pairs within one composer's catalogue.")
    parser.add_argument("db", help="path to ttn.sqlite")
    parser.add_argument("--composer", required=True,
                        help="composer substring (case-insensitive)")
    parser.add_argument("--min-airings", type=int, default=4,
                        help="hide clusters with total airings below this "
                             "(default: 4)")
    parser.add_argument("--min-per-group", type=int, default=2,
                        help="require each group in a cluster to have at "
                             "least this many airings (default: 2)")
    parser.add_argument("--emit", action="store_true",
                        help="also print paste-ready alias tuples and tests")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.db):
        parser.error(f"database not found: {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        groups = load_groups(conn, args.composer)
        if not groups:
            print(f"No tracks found for composer matching {args.composer!r}.",
                  file=sys.stderr)
            return 1
        candidates = find_candidates(groups, min_per_group=args.min_per_group)
        # Pick the composer key from the highest-airing group (most common
        # canonical spelling for this composer).
        sample = max(groups.values(), key=lambda g: g.count)
        sample_composer = max(sample.title_counts,
                              key=lambda _t: sample.count)  # any title
        # Actually grab the composer key directly from the DB
        cur = conn.execute(
            "SELECT composer, COUNT(*) AS n FROM tracks "
            "WHERE LOWER(composer) LIKE ? GROUP BY composer ORDER BY n DESC "
            "LIMIT 1", (f"%{args.composer.lower()}%",))
        top_composer = cur.fetchone()[0]
        this_composer_key = resolve_composer_alias(canonical_key(top_composer))

        workkey_to_composers = build_workkey_to_composers(conn)
    finally:
        conn.close()

    print(render_report(top_composer, candidates, workkey_to_composers,
                        this_composer_key, min_total=args.min_airings))
    if args.emit:
        print(render_emit(candidates, min_total=args.min_airings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
