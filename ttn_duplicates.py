#!/usr/bin/env python3
"""Post-alias duplicate-work detector — an independent cross-check that
flags same-composer work-groups likely to be one work keyed apart (the
straggler-scan that was being done by eye over `ttn_analyze --by work`).

Design: docs/superpowers/specs/2026-05-30-duplicate-detector-design.md
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

from ttn_analyze import (canonical_key, strip_arranger_tail,
                         resolve_composer_alias, work_title_key,
                         resolve_work_alias)

# Own stopword set (deliberately separate from ttn_audit_composer's, for
# independence). Form words, connectives, key words, scoring, ordinals —
# everything that does NOT carry work identity. Numbers and nickname words
# are kept by _fingerprint.
_STOPWORDS = frozenset((
    "the", "a", "an", "and", "of", "in", "from", "for", "to", "by", "with",
    "on", "or", "no", "nos", "op", "opus", "arr", "arranged", "version",
    "major", "minor", "flat", "sharp",
    "concerto", "concertino", "sonata", "sonatina", "sinfonia",
    "sinfonietta", "symphony", "symphonie", "suite", "partita",
    "divertimento", "serenade", "quartet", "quintet", "sextet", "septet",
    "octet", "nonet", "trio", "overture", "prelude", "fugue", "rondo",
    "fantasia", "fantasy", "variations", "movement", "movements",
    "piano", "violin", "viola", "cello", "flute", "oboe", "clarinet",
    "horn", "trumpet", "harp", "guitar", "harpsichord", "organ",
    "orchestra", "strings", "string", "voice", "voices", "chorus",
    "solo", "continuo",
))


def _fingerprint(title):
    """Identity tokens of a title: canonical-key'd, stopwords removed,
    numbers and nickname words kept (single letters dropped, digits kept)."""
    return frozenset(
        t for t in canonical_key(title).split()
        if t not in _STOPWORDS and (t.isdigit() or len(t) > 1))


@dataclass
class Group:
    composer: str          # canonical composer key (grouping)
    composer_display: str  # most-common original spelling
    work_key: str
    display_title: str     # most-common original title
    airings: int
    fingerprint: frozenset


def build_groups(rows):
    """rows: iterable of (composer, composer_line, title). Returns a list of
    Group, one per (composer_key, work_key) — the same grouping --by work
    produces (arranger tails stripped, composer + work aliases applied)."""
    acc = {}  # (ck, wk) -> [airings, title_counter, composer_counter]
    for composer, composer_line, title in rows:
        if not composer or not title:
            continue
        ck = resolve_composer_alias(
            canonical_key(strip_arranger_tail(composer, composer_line)))
        wk = resolve_work_alias(work_title_key(title))
        rec = acc.setdefault((ck, wk), [0, Counter(), Counter()])
        rec[0] += 1
        rec[1][title] += 1
        rec[2][composer] += 1
    groups = []
    for (ck, wk), (n, titles, comps) in acc.items():
        disp = titles.most_common(1)[0][0]
        groups.append(Group(ck, comps.most_common(1)[0][0], wk, disp, n,
                            _fingerprint(disp)))
    return groups


def _jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _composer_rare_tokens(groups, rare_max):
    """Tokens appearing in <= rare_max of these groups' fingerprints —
    composer-distinctive (nicknames, work numbers like '103')."""
    counts = Counter()
    for g in groups:
        counts.update(g.fingerprint)
    return {t for t, c in counts.items() if c <= rare_max}


def _ref(key):
    """Catalogue ref of a §-key ('§k516|516|gminor' -> 'k516'), else ''."""
    return key[1:].split("|", 1)[0] if key.startswith("§") else ""


def _is_excerpt_key(key):
    """A §-key with exactly one '|' is a movement-excerpt slug (§ref|slug);
    a whole catalogue key has two ('§ref|nums|keys')."""
    return key.startswith("§") and key.count("|") == 1


def _set_sibling(ka, kb):
    """Two WHOLE catalogue keys (two pipes) with the same ref but different
    key signatures — distinct set-catalogue siblings (D.899 impromptus…).
    Same ref + same/absent keysig + only number differing is NOT a sibling
    (that is a phantom-ordering straggler we WANT to flag)."""
    if not (ka.startswith("§") and kb.startswith("§")):
        return False
    if ka.count("|") != 2 or kb.count("|") != 2:
        return False
    if _ref(ka) != _ref(kb):
        return False
    return ka.split("|")[2] != kb.split("|")[2]


def _excluded(ka, kb):
    """Pairs that are legitimately distinct by their keys — never duplicates."""
    return _is_excerpt_key(ka) or _is_excerpt_key(kb) or _set_sibling(ka, kb)


def _verdict(a, b, rare, base, low):
    """(flagged, reason) for a candidate pair. Base: high Jaccard. Boost:
    moderate Jaccard AND a shared composer-rare token (nickname/number)."""
    j = _jaccard(a.fingerprint, b.fingerprint)
    if j >= base:
        return True, f"base J={j:.2f}"
    shared_rare = a.fingerprint & b.fingerprint & rare
    if j >= low and shared_rare:
        return True, f"boost J={j:.2f} +{','.join(sorted(shared_rare))}"
    return False, None


@dataclass
class Pair:
    composer: str
    a: Group
    b: Group
    reason: str

    @property
    def airings(self):
        return self.a.airings + self.b.airings


def find_duplicates(groups, base=0.5, low=0.2, rare_max=3):
    """Flagged straggler pairs, ranked by combined airings (desc)."""
    by_composer = defaultdict(list)
    for g in groups:
        by_composer[g.composer].append(g)
    pairs = []
    for comp, gs in by_composer.items():
        rare = _composer_rare_tokens(gs, rare_max)
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                a, b = gs[i], gs[j]
                if _excluded(a.work_key, b.work_key):
                    continue
                flagged, reason = _verdict(a, b, rare, base, low)
                if flagged:
                    hi, lo = (a, b) if a.airings >= b.airings else (b, a)
                    pairs.append(Pair(comp, hi, lo, reason))
    pairs.sort(key=lambda p: -p.airings)
    return pairs


def render(pairs, emit=False):
    out = [f"=== {len(pairs)} likely-duplicate work pair(s) ==="]
    for p in pairs:
        out.append(f"\n[{p.airings} airings] {p.a.composer_display}  ({p.reason})")
        out.append(f"  × {p.a.airings:>3}  {p.a.display_title}")
        out.append(f"          {p.a.work_key}")
        out.append(f"  × {p.b.airings:>3}  {p.b.display_title}")
        out.append(f"          {p.b.work_key}")
    if emit:
        out.append("\n# --- paste-ready WORK_ALIASES (VERIFY before pasting) ---")
        for p in pairs:
            out.append(f"    ({p.b.display_title!r},")
            out.append(f"     {p.a.display_title!r}),")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Flag same-composer work-groups likely to be one work "
                    "keyed apart (post-alias straggler scan).")
    parser.add_argument("db", nargs="?", default="ttn.sqlite",
                        help="path to ttn.sqlite")
    parser.add_argument("--composer", help="restrict to one composer (substring)")
    parser.add_argument("--top", type=int, default=0, help="cap the report (0 = all)")
    parser.add_argument("--emit", action="store_true",
                        help="append paste-ready WORK_ALIASES tuples")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT composer, composer_line, title FROM tracks").fetchall()
    conn.close()

    pairs = find_duplicates(build_groups(rows))
    if args.composer:
        needle = canonical_key(args.composer)
        pairs = [p for p in pairs if needle in p.composer]
    if args.top:
        pairs = pairs[:args.top]
    print(render(pairs, emit=args.emit))


if __name__ == "__main__":
    main()
