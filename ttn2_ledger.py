"""ttn2_ledger — layer 2: identity decisions as data + resolution.

Imports the three alias tables from ttn_aliases into the successor's
`ledger` table, tagging each row with method + confidence + audit flags
(computed by the same cross-examination as scratch/alias_audit.py), then
provides resolution over the ledger that must reproduce ttn_analyze's
behavior exactly (verified by `check`).

Boundary: tokenization (canonical_key / work_title_key) is IMPORTED from
ttn_analyze — it is shared vocabulary, not an identity decision. Identity
DECISIONS (the alias maps) come from the ledger.

CLI:
  uv run ttn2_ledger.py import          # rebuild ledger from ttn_aliases
  uv run ttn2_ledger.py check           # full-corpus resolution parity vs ttn_analyze
"""
import collections
import json
import sqlite3
import sys

import ttn_analyze as A
import ttn_aliases as T

DB = "successor.sqlite"


def _paren_balance(s):
    for a, b in (("(", ")"), ("[", "]")):
        if s.count(a) != s.count(b):
            return False
    return s.count('"') % 2 == 0


def _flags(src, dst, raw_key_composers, scoped_keys):
    sk = A.work_title_key(src)
    xcomp = {c: n for c, n in raw_key_composers.get(sk, {}).items()}
    flags = {}
    if not _paren_balance(src) or not _paren_balance(dst):
        flags["malformed"] = True
    if len([1 for n in xcomp.values() if n]) >= 2:
        flags["xcomposer"] = xcomp
    if sk in scoped_keys:
        flags["scoped_shadow"] = True
    return flags


def _raw_key_composers(conn):
    """raw wk -> {resolved ck: airings} over both source tables."""
    out = collections.defaultdict(lambda: collections.Counter())
    for tbl, tcol, ccol in (("tracks", "title", "composer"),
                            ("segment_events", "track_title", "composer_name")):
        for c, t, n in conn.execute(
                f"SELECT {ccol}, {tcol}, COUNT(*) FROM {tbl} "
                f"WHERE {tcol} IS NOT NULL GROUP BY {ccol}, {tcol}"):
            ck = A.resolve_composer_alias(A.canonical_key(c or ""))
            out[A.work_title_key(t, composer=c or "")][ck] += n
    return out


def import_aliases(src="ttn.sqlite", dst=DB):
    t2 = sqlite3.connect(dst)
    t2.execute("DELETE FROM ledger")
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    rkc = _raw_key_composers(src_conn)
    src_conn.close()
    scoped_keys = {A.work_title_key(v, composer=c)
                   for c, v, _ in T._COMPOSER_SCOPED_WORK_ALIAS_PAIRS}
    rows = []
    for src_t, dst_t in T._WORK_ALIAS_PAIRS:
        sk = A.work_title_key(src_t)
        dk = A.work_title_key(dst_t)
        flags = _flags(src_t, dst_t, rkc, scoped_keys)
        conf = "review" if ("xcomposer" in flags or "malformed" in flags) else "legacy"
        rows.append(("work_alias", "global", sk, dst_t, dk,
                     "legacy-global", conf, json.dumps(flags) if flags else None))
    for comp, v, p in T._COMPOSER_SCOPED_WORK_ALIAS_PAIRS:
        ck = A._scoped_composer_key(comp)
        rows.append(("work_alias", ck, A.work_title_key(v, composer=comp),
                     p, A.work_title_key(p, composer=comp),
                     "legacy-scoped", "medium", None))
    for src_c, dst_c in T._COMPOSER_ALIAS_PAIRS:
        rows.append(("composer_alias", "global", A.canonical_key(src_c),
                     dst_c, A.canonical_key(dst_c),
                     "legacy-composer", "legacy", None))
    t2.executemany(
        "INSERT INTO ledger (kind, scope, variant_key, target, target_key, "
        "method, confidence, flags_json) VALUES (?,?,?,?,?,?,?,?)", rows)
    t2.commit()
    n_flag = sum(1 for r in rows if r[7])
    print(f"ttn2_ledger: {len(rows)} decisions "
          f"(work {sum(1 for r in rows if r[0]=='work_alias')}, "
          f"composer {sum(1 for r in rows if r[0]=='composer_alias')}); "
          f"{n_flag} flagged for review")


def load_maps(dst=DB):
    t2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    work_global, work_scoped, comp = {}, {}, {}
    for kind, scope, vk, tgt, tk in t2.execute(
            "SELECT kind, scope, variant_key, target, target_key FROM ledger"):
        if kind == "work_alias":
            if scope == "global":
                work_global[vk] = tk
            else:
                work_scoped[(scope, vk)] = tk
        else:
            comp[vk] = tk
    t2.close()
    return comp, work_scoped, work_global


def resolve_composer(ck, comp):
    return comp.get(ck, ck)


def resolve_work(wk, composer_str, work_scoped, work_global):
    # mirrors ttn_analyze.resolve_work_alias exactly: the scoped lookup is
    # keyed by _scoped_composer_key(RAW composer string) — which runs
    # normalize_composer — NOT by the pre-resolved composer key. Segment-side
    # compound credits ('X and Y', 'Pytor, Illyich ...') expose the
    # difference. Single step, no chaining.
    ck_scope = A._scoped_composer_key(composer_str)
    scoped = work_scoped.get((ck_scope, wk))
    if scoped is not None:
        return scoped
    return work_global.get(wk, wk)


def check(src="ttn.sqlite", dst=DB, sample=None):
    """Full-corpus parity: ledger resolution must equal ttn_analyze's."""
    comp, ws, wg = load_maps(dst)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    diffs = 0
    checked = 0
    q = ("SELECT composer, title FROM tracks WHERE title IS NOT NULL"
         + (f" LIMIT {int(sample)}" if sample else ""))
    for c, t in src_conn.execute(q):
        ck = A.resolve_composer_alias(A.canonical_key(c))
        wk = A.work_title_key(t, composer=c)
        mine_c = resolve_composer(A.canonical_key(c), comp)
        mine_w = resolve_work(wk, c, ws, wg)
        if (mine_c, mine_w) != (ck, A.resolve_work_alias(wk, composer=c)):
            diffs += 1
            if diffs <= 5:
                print("DIFF:", repr(c), repr(t), (ck, A.resolve_work_alias(wk, composer=c)),
                      "->", (mine_c, mine_w))
        checked += 1
    src_conn.close()
    print(f"ttn2_ledger check: {checked} rows, {diffs} resolution diffs")
    return diffs


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "import"
    if cmd == "import":
        import_aliases()
    elif cmd == "check":
        sys.exit(1 if check(sample=sys.argv[2] if len(sys.argv) > 2 else None) else 0)
    else:
        print("usage: ttn2_ledger.py import|check [sample]", file=sys.stderr)
        sys.exit(2)
