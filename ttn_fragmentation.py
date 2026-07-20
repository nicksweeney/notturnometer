"""Fragmentation scan: rank composers by FOLDABLE AIRINGS -- which curation
pass moves the most airings. Graduated from scratch/fragmentation_scan.py
(2026-07-19) after proving out over the Milhaud/Hildegard/Durufle/Handel/
Debussy/Brahms passes and finding the number-leak gate.

Score per composer = airings that would MOVE if the fragmentation were folded:
  1. Recording-proven (strong): minority-key airings of recordings spanning
     >1 work key (ttn_spine.work_alias_candidates), with keys RESOLVED
     through WORK_ALIASES before judging (pre-alias counting falsely
     inflates already-consolidated composers -- the Brahms lesson) and a
     generic-token noise guard against the pos+1 bridge-noise class.
  2. Candidate-grade (weak, x0.5): ttn_duplicates pair minorities.

Validation property: swept composers score near zero; a swept composer
scoring high again = NEW fragmentation. ~4 min on the Pi (spine build).
Reached via `uv run ttn_curate.py fragmentation [db] [--top N]`.
"""
import argparse
import sqlite3
from collections import defaultdict

from ttn_analyze import canonical_key, resolve_composer_alias, resolve_work_alias
from ttn_duplicates import build_groups, find_duplicates
from ttn_spine import work_alias_candidates

STOP = {"a", "and", "de", "des", "for", "from", "in", "la", "le", "no",
        "o", "of", "op", "sur", "the"}

# Generic musical vocabulary: shared tokens from this set are NOT evidence
# that two keys name the same work (the pos+1 bridge-noise guard let a
# Prokofiev symphony through under Milhaud on the word 'symphony' alone).
GENERIC = {"symphony", "concerto", "sonata", "quartet", "quintet", "trio",
           "suite", "overture", "major", "minor", "sharp", "flat", "piano",
           "violin", "cello", "viola", "flute", "oboe", "clarinet", "horn",
           "orchestra", "strings", "chorus", "voice", "organ", "harpsichord",
           "movement", "mvt", "excerpt", "arr", "arranged", "song", "songs",
           "dance", "dances", "waltz", "prelude", "fugue", "variations",
           "theme", "adagio", "allegro", "andante", "rondo", "scherzo"}


def sig_tokens(key):
    return {t for t in key.split() if len(t) > 1 and t not in STOP
            and not t.isdigit()}


def same_work_evidence(toks_a, toks_b):
    """Shared-token test that generic vocabulary can't satisfy alone:
    >=1 shared SPECIFIC token, or >=3 shared generic ones."""
    shared = toks_a & toks_b
    specific = shared - GENERIC
    return bool(specific) or len(shared) >= 3


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="ttn_curate.py fragmentation",
        description="Rank composers by FOLDABLE AIRINGS -- the curation "
                    "worklist heuristic (rec-proven minority airings + "
                    "half-weight duplicate pairs).")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args(argv)
    top = args.top
    conn = sqlite3.connect(args.db)

    rec_score = defaultdict(int)     # composer canonical key -> minority airings
    rec_items = defaultdict(list)
    for c in work_alias_candidates(conn):
        # The oracle counts PRE-alias keys, so already-consolidated composers
        # score falsely high (the Brahms lesson, 2026-07-19): resolve each
        # key and re-merge before judging. A candidate whose keys all resolve
        # to one final key is already folded -- skip it.
        resolved = defaultdict(int)
        for k, n in c.work_keys.items():
            resolved[resolve_work_alias(k)] += n
        if len(resolved) < 2:
            continue
        keys = sorted(resolved.items(), key=lambda kv: -kv[1])
        dom_key, _dom_n = keys[0]
        dom_toks = sig_tokens(dom_key)
        ck = resolve_composer_alias(canonical_key(c.composer_display or ""))
        for k, n in keys[1:]:
            if not same_work_evidence(sig_tokens(k), dom_toks):
                continue             # bridge-noise guard
            rec_score[ck] += n
            rec_items[ck].append((c.recording_pid, n, k, dom_key))

    dup_score = defaultdict(float)
    dup_items = defaultdict(list)
    rows = conn.execute("SELECT composer, title, episode_pid FROM tracks")
    groups = build_groups(rows)
    for pair in find_duplicates(groups):
        a, b = pair.a, pair.b
        minority = min(a.airings, b.airings)
        ck = resolve_composer_alias(canonical_key(a.composer))
        dup_score[ck] += minority * 0.5
        dup_items[ck].append((minority, a.display_title, b.display_title))

    display = {}
    for (comp, n) in conn.execute(
            "SELECT composer, COUNT(*) FROM tracks GROUP BY composer"):
        ck = resolve_composer_alias(canonical_key(comp or ""))
        if ck not in display or n > display[ck][1]:
            display[ck] = (comp, n)

    total = {ck: rec_score.get(ck, 0) + dup_score.get(ck, 0.0)
             for ck in set(rec_score) | set(dup_score)}
    ranked = sorted(total.items(), key=lambda kv: -kv[1])

    print(f"=== fragmentation worklist: top {top} by foldable airings ===")
    print(f"{'score':>7}  {'rec-proven':>10}  {'dup-cand':>8}  composer")
    for ck, sc in ranked[:top]:
        name = display.get(ck, (ck, 0))[0]
        print(f"{sc:>7.1f}  {rec_score.get(ck, 0):>10}  "
              f"{dup_score.get(ck, 0.0):>8.1f}  {name}")
        for rp, n, k, dom in rec_items.get(ck, [])[:2]:
            print(f"         rec {rp}: {n}x {k[:70]!r} vs dom {dom[:70]!r}")

    print("\n=== validation: the swept composers ===")
    for probe in ("darius milhaud", "hildegard of bingen", "maurice durufle"):
        ck = resolve_composer_alias(probe)
        print(f"  {probe}: score={total.get(ck, 0.0):.1f}")


if __name__ == "__main__":
    main()
