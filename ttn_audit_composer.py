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

# Matches "Op X" with an optional "No Y" tail — captures (op, sub_no) for
# the Pass 1b cross-path bridge. sub_no is None when not present.
_OP_NO_RE = re.compile(
    r"\bop\b\s*\.?\s*(\d+)(?:\s*[\.,`/]?\s*no\.?\s*(\d+))?", re.I)

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


def _op_subno_pairs(title):
    """Set of (op, sub_no) tuples in a title. sub_no is the integer
    string if the title carries "Op X No Y", else None. Used by the
    Pass 1b cross-path bridge to distinguish e.g. Op 1 No 4 (= HWV.362)
    from Op 1 No 5 (= HWV.363a), even though both share Op 1."""
    pairs = set()
    for m in _OP_NO_RE.finditer(title):
        pairs.add((m.group(1), m.group(2)))
    return pairs


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

    def all_op_pairs(self):
        """Union of (op, sub_no) pairs across all titles in the group."""
        pairs = set()
        for t in self.titles:
            pairs |= _op_subno_pairs(t)
        return pairs

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

def _likely_set_catalogue(groups):
    """Heuristic flag for set-catalogue siblings (one catalogue ref or
    Op number identifies multiple distinct works distinguished by
    sub-no + key signature, e.g. Schubert D.899 / D.935 Impromptus,
    D.780 individual movements, Op 79 Brahms Rhapsodies).

    True when the cluster has ≥3 groups whose catalogue-path work_keys
    (`§ref|nums|keysig`) carry ≥3 distinct non-empty key signatures —
    the signature that distinct sibling works leave in their grouping
    key. Folding such clusters would merge what are actually different
    pieces. The flag is advisory; the human still triages."""
    if len(groups) < 3:
        return False
    keysigs = []
    for g in groups:
        if not g.work_key.startswith("§"):
            continue
        parts = g.work_key.split("|")
        if len(parts) >= 3 and parts[2]:
            keysigs.append(parts[2])
    return len(set(keysigs)) >= 3


# Composer-distinctive song-cycle and collection names. When a cluster's
# shared tokens include one of these, the cluster almost certainly groups
# individual songs/movements of the named cycle (which are distinct works
# and legitimately stay split) rather than multi-phrasings of one work.
# The list is composer-specific — generic tokens like "lieder" / "songs"
# are excluded to avoid catching multi-phrasing clusters that happen to
# share those words.
_CYCLE_COLLECTION_TOKENS = frozenset((
    # Schubert
    "winterreise", "schwanengesang", "müllerin", "mullerin",
    # Schumann
    "dichterliebe", "frauenliebe", "myrthen", "myrten", "liederkreis",
    # Mahler
    "kindertotenlieder", "wunderhorn", "rückert", "ruckert", "gesellen",
    # Mendelssohn — Lieder ohne Worte / Songs Without Words
    "worte",
    # Strauss — Vier letzte Lieder
    "letzte",
    # Brahms — Vier ernste Gesänge
    "ernste",
    # Wolf — Italian / Spanish / Mörike / Goethe / Eichendorff Liederbücher
    "liederbuch", "mörike", "morike", "eichendorff",
    # Berlioz — Les nuits d'été
    "nuits",
    # Britten
    "illuminations",
    # Ravel
    "shéhérazade", "scheherazade", "madécasses", "histoires",
    # Debussy
    "bilitis",
))


def _normalise_token(t):
    """Strip leading/trailing apostrophes that `_significant_tokens`
    leaves attached when tokenising titles like "'Des Knaben Wunderhorn'"."""
    return t.strip("'")


def _title_contains_cycle_token(title):
    tokens = re.findall(r"[a-zA-ZÀ-ſ']+", title.lower())
    return any(_normalise_token(t) in _CYCLE_COLLECTION_TOKENS for t in tokens)


def _likely_cycle_collection(groups):
    """True if a majority of the cluster's groups have at least one
    title containing a composer-distinctive cycle/collection name.

    Scanning group titles (rather than only union-find's shared_tokens)
    catches transitive clusters where the cycle name isn't in every
    pair's shared set — e.g. Mahler's Rückert-Lieder cluster pivots on
    generic tokens like "ich" / "lieder" but most groups carry
    "rückert" in their titles. Flag is advisory; multi-phrasing folds
    within ONE cycle song are still possible — the human triages."""
    if not groups:
        return False
    n_cycle = sum(
        1 for g in groups
        if any(_title_contains_cycle_token(t) for t in g.titles))
    return n_cycle >= max(2, len(groups) // 2 + 1)


class Candidate:
    __slots__ = ("groups", "reason", "shared_key",
                 "likely_set_catalogue", "likely_cycle_collection")

    def __init__(self, groups, reason, shared_key=None):
        self.groups = sorted(groups, key=lambda g: -g.count)
        self.reason = reason
        self.shared_key = shared_key
        self.likely_set_catalogue = _likely_set_catalogue(self.groups)
        self.likely_cycle_collection = _likely_cycle_collection(self.groups)

    @property
    def total(self):
        return sum(g.count for g in self.groups)

    @property
    def advisory_skip(self):
        """Combined warning flag — either heuristic firing means the
        cluster is likely a set of distinct works that should NOT be
        bulk-folded."""
        return self.likely_set_catalogue or self.likely_cycle_collection


def find_candidates(groups, min_per_group=2):
    """Return a list of Candidate fold-pairs/clusters.

    Detection passes:
    1.  Op/catalogue-ref bucketing: groups sharing an Op number or a
        catalogue ref (BWV, K, D, RV, …).
    1b. Cross-path bridge: when a "bridge group" has BOTH an Op N No M
        and a catalogue ref, surface op-only and ref-only sibling groups
        as a candidate cluster. Catches splits like Handel HWV.362 where
        "Oboe Sonata Op 1 No 4" (token-sort) and "Sonata in A minor
        HWV 362" (catalogue) don't share enough tokens for Pass 2 but
        the canonical "Violin Sonata in A minor (Op.1 No.4) (HWV.362)"
        carries both references.
    2.  Title-token overlap: groups sharing ≥3 significant tokens that
        weren't already paired by passes 1 / 1b.
    2b. Subset detection for short-token groups.
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

    # Pass 1b: cross-path bridge — Op N No M ↔ catalogue ref pairs that
    # co-occur in at least one "bridge group" pull op-only and ref-only
    # sibling groups together. The bridge group itself has both
    # references; the siblings have only one each.
    op_pair_to_groups = defaultdict(list)
    for g in eligible:
        for pair in g.all_op_pairs():
            op_pair_to_groups[pair].append(g)

    bridges = defaultdict(set)  # (op_pair, ref) -> set of bridge work_keys
    for g in eligible:
        op_pairs = g.all_op_pairs()
        refs = g.all_refs()
        if not op_pairs or not refs:
            continue
        for op_pair in op_pairs:
            for ref in refs:
                bridges[(op_pair, ref)].add(g.work_key)

    for (op_pair, ref), bridge_keys in bridges.items():
        # Only bridge when the op_pair has a concrete sub-no. Bare
        # (op, None) over-merges collection works — a bridge of
        # (6, None) ↔ HWV.323 would drag in every bare-Op-6 group
        # regardless of which sub-numbered concerto grosso it is.
        if op_pair[1] is None:
            continue
        op_side = op_pair_to_groups.get(op_pair, [])
        ref_side = ref_buckets.get(ref, [])
        cluster_keys = {g.work_key for g in op_side} | {g.work_key for g in ref_side}
        if len(cluster_keys) < 2:
            continue
        key = frozenset(cluster_keys)
        if key in paired:
            continue
        paired.add(key)
        cluster_groups = [g for g in eligible if g.work_key in cluster_keys]
        candidates.append(Candidate(
            cluster_groups,
            reason=f"cross-path: Op {op_pair[0]} No {op_pair[1]} ↔ {ref[0]}.{ref[1]}",
            shared_key=(op_pair, ref)))

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
        tag_parts = []
        if c.likely_set_catalogue:
            tag_parts.append("likely set-catalogue siblings")
        if c.likely_cycle_collection:
            tag_parts.append("likely cycle/collection internal")
        tag = (" — " + ", ".join(tag_parts) + ", verify") if tag_parts else ""
        out.append(f"[{c.total} airings, {c.reason}{tag}]")
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
        if c.likely_set_catalogue:
            out.append(
                "    # WARNING: likely set-catalogue siblings — each "
                "(sub-no + key sig) pair below is probably a DISTINCT work.")
            out.append("    # Verify before pasting; the aliases are commented out.")
        if c.likely_cycle_collection:
            out.append(
                "    # WARNING: likely cycle/collection internal — the "
                "groups below are probably individual songs/movements")
            out.append(
                "    # of the named cycle (which are distinct works). "
                "Verify before pasting; the aliases are commented out.")
        for g in c.groups[1:]:
            variant = g.display_title
            prefix = "    # " if c.advisory_skip else "    "
            out.append(f"{prefix}({variant!r},")
            out.append(f"{prefix} {target!r}),")
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
