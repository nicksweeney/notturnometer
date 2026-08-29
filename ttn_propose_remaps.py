"""Propose tier-1 remap specs for orphaned registry work slugs.

After an alias/gate edit re-keys registered identities, `ttn_data.py site`
fails listing the orphaned slugs and asks for `--remap "SLUG|CK|WK"` specs.
Deriving each successor key by hand (the exact current work_key spelling,
token-sorted or §-formed) is error-prone -- the Lassus Omnia pass wrote one
wrong by guessing a spelling instead of computing it.

For each slug this tool collects successor VOTES from two independent
signals and only proposes when one is an unambiguous >=50% majority:

1. EVIDENCE VOTES -- ttn_evidence.json maps slug -> recording-pid sample;
   each sampled pid's CURRENT airings (via the projection + rec_meta, WORK_
   ALIASES applied) vote for the group they live in now. Same mechanism as
   sync_registry's evidence heal.
2. ALIAS RESOLUTION -- if resolve_work_alias(registered_wk, composer_key)
   moves the registered key under the EDITED tables, that target also votes
   (a small weight, corroborating rather than driving: it cannot see through
   chained identities).

A proposal must land on a group present in the current corpus. Skips are
explicit and reasoned: redirects/retired entries ("nothing to do"), slugs
whose identity still exists ("not an orphan"), evidence ties ("AMBIGUOUS"),
and no-candidate cases ("RETIRE?"). `ttn_data.py site --dry-run --remap-file`
remains the human gate; nothing here writes registry state. Read-only.

--kind composers switches to the composers namespace ("SLUG|CK" specs).

Usage:
    uv run ttn_curate.py propose-remaps ttn.sqlite SLUG [SLUG...] [--out F]
    # paste the site-failure orphan list on stdin:
    ... | uv run ttn_curate.py propose-remaps ttn.sqlite -
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter

import ttn_analyze as A
import ttn_project as P
import ttn_work_recordings as WR

_REGISTRY_PATH = "ttn_site_registry.json"
_EVIDENCE_PATH = "ttn_evidence.json"


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _build(conn):
    """One corpus walk: corpus{(ck,wk): airings} and rp->airings index."""
    rows = WR._fetch_rows(conn)
    projection, rec_meta, _status = P.load(conn)
    groups = WR._build_index(rows, projection, rec_meta)
    cache, air_by_rp = {}, {}
    for ep, pos, _date, _title, _comp, _cl in rows:
        rp = projection.get((ep, pos))
        if not rp or rp not in rec_meta:
            continue
        cm, tt = rec_meta[rp]
        ck = A.resolve_composer_alias(A.canonical_key(cm))
        k2 = (tt, cm)
        wk = cache.get(k2)
        if wk is None:
            wk = A.resolve_work_alias(A.work_title_key(tt, composer=cm), composer=cm)
            cache[k2] = wk
        air_by_rp.setdefault(rp, {}).setdefault((ck, wk), 0)
        air_by_rp[rp][(ck, wk)] += 1
    return {k: g["airings"] for k, g in groups.items()}, air_by_rp


def _propose_one(slug, works_ns, redirects, retired, corpus, air_by_rp, evidence):
    """works-namespace wrapper around propose_slug's mechanics."""
    if slug in redirects:
        return slug, "SKIP", None, "redirected earlier; nothing to do"
    if slug in retired:
        return slug, "SKIP", None, "retired; nothing to do"
    entry = works_ns.get(slug)
    if not entry:
        return slug, "SKIP", None, "unknown to the registry works namespace"
    ck_reg = (entry.get("composer_key") or "").strip().lower()
    wk_reg = (entry.get("work_key") or "").strip()
    if corpus.get((ck_reg, wk_reg)):
        return slug, "SKIP", None, \
            "identity still present in the current corpus - NOT an orphan"
    return _successor_votes(slug, ck_reg, wk_reg, corpus, air_by_rp, evidence)


def _propose_composer(slug, composers_ns, corpus):
    entry = composers_ns.get(slug)
    if not entry:
        return slug, "SKIP", None, "unknown to the registry composers namespace"
    ck = (entry.get("composer_key") or "").strip().lower()
    rk = A.resolve_composer_alias(ck)
    if rk != ck and any(k[0] == rk for k in corpus):
        return slug, "PROPOSE", f"{slug}|{rk}", \
            f"{ck!r} resolves onward to {rk!r} (present in corpus)"
    if any(k[0] == ck for k in corpus):
        return slug, "SKIP", None, "identity still present - NOT an orphan"
    return slug, "RETIRE?", None, f"resolved {rk!r} absent from the corpus"


def _successor_votes(slug, ck_reg, wk_reg, corpus, air_by_rp, evidence):
    cands = Counter()
    ck_res = A.resolve_composer_alias(ck_reg)
    for rp in evidence.get(slug) or []:
        for k, n in air_by_rp.get(rp, {}).items():
            cands[k] += n                       # 1 vote per current airing
    # Tier-1 mechanical: the composer half folded, work key unchanged.
    if corpus.get((ck_res, wk_reg)):
        cands[(ck_res, wk_reg)] += 1
    alias_target = None
    tk = A.resolve_work_alias(wk_reg, ck_res)
    if tk != wk_reg:
        alias_target = (ck_res, tk)
        cands[alias_target] += 1                # corroborating weight only
    if not cands:
        return slug, "RETIRE?", None, (
            "no successor found (no evidence sample, no alias move); "
            "NB if the nightly registry sync ran recently, refresh first: "
            "`git pull && uv run ttn_data.py update` -- slugs minted "
            "johnson-side from broadcasts this DB has not ingested look "
            "exactly like dissolved identities (2026-08-27 Telemann lesson)")
    best, best_n = cands.most_common(1)[0]
    runner = sorted(cands.values(), reverse=True)[1] if len(cands) > 1 else 0
    def fmt(items):
        return "; ".join(f"{k[0]}|{k[1]} ({n})" for k, n in items)
    if best_n == runner:
        return slug, "SKIP", None, "AMBIGUOUS tie among: " + fmt(cands.most_common(4))
    if best_n * 2 < sum(cands.values()):
        return slug, "SKIP", None, "no >=50% majority among: " + fmt(cands.most_common(4))
    if best not in corpus:
        return slug, "SKIP", None, "leading candidate absent from corpus: " + fmt([(best, best_n)])
    via = []
    if best == alias_target:
        via.append("alias")
    if any(air_by_rp.get(rp, {}).get(best) for rp in evidence.get(slug) or []):
        via.append("evidence")
    if best == (ck_res, wk_reg) and ck_res != ck_reg:
        via.append("composer-fold")
    detail = (f"-> {best[0]} | {best[1]}   [{'+'.join(via)}]"
              f" votes={dict((str(k), v) for k, v in cands.most_common(3))}")
    return slug, "PROPOSE", f"{slug}|{best[0]}|{best[1]}", detail

def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(
        prog="ttn_curate.py propose-remaps",
        description="derive --remap specs for orphaned registry slugs "
                    "(mechanical tier only; --dry-run stays the gate)")
    ap.add_argument("db")
    ap.add_argument("slugs", nargs="+",
                    help="orphaned slug(s), or '-' to read them from stdin")
    ap.add_argument("--kind", default="works", choices=["works", "composers"],
                    help="registry namespace (composers takes 'SLUG|CK' specs)")
    ap.add_argument("--out", help="write spec lines to FILE (report still stdout)")
    args = ap.parse_args(argv)

    if args.slugs == ["-"]:
        raw = sys.stdin.read()
        toks = raw.replace(",", "\n").replace("'", "").split()
        slugs = [t.strip("'[]") for t in toks if t.strip("'[]")]
    else:
        slugs = [s.strip("'[], ") for s in args.slugs]
    if not slugs:
        print("no slugs given", file=sys.stderr)
        raise SystemExit(2)

    registry = _load_json(_REGISTRY_PATH)
    if not registry:
        print(f"cannot read {_REGISTRY_PATH}", file=sys.stderr)
        raise SystemExit(2)
    namespace = registry.get(args.kind) or {}
    evidence = (_load_json(_EVIDENCE_PATH).get("works") or {}) \
        if args.kind == "works" else {}

    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        print(f"cannot open DB {args.db!r}: {e}", file=sys.stderr)
        raise SystemExit(2)
    corpus, air_by_rp = _build(conn)
    conn.close()

    if args.kind == "works":
        # NB redirects/retired are NAMESPACED dicts of slug->slug maps.
        red_ns = (registry.get("redirects") or {}).get("works") or {}
        ret_ns = (registry.get("retired") or {})
        retired_slugs = set(ret_ns) if isinstance(ret_ns, dict) else set(ret_ns or [])
        results = [_propose_one(s, namespace, red_ns, retired_slugs,
                                corpus, air_by_rp, evidence) for s in slugs]
    else:
        results = [_propose_composer(s, namespace, corpus) for s in slugs]

    lines, specs = [], []
    counts = Counter()
    for slug, status, spec, detail in results:
        base = status.rstrip("?")
        counts[base] += 1
        prefix = {"PROPOSE": "+", "SKIP": "-", "RETIRE": "?"}[base]
        suffix = "?" if status.endswith("?") else ""
        lines.append(f"{prefix} {slug}\n    {status}{suffix}: {detail}")
        if spec:
            specs.append(spec)

    report = "\n".join(lines)
    summary = (f"\n{counts['PROPOSE']} proposal(s), {counts['SKIP']} skipped, "
               f"{counts['RETIRE']} retire-candidate(s); "
               "gate with `ttn_data.py site --dry-run --remap-file <file>`.")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(specs) + ("\n" if specs else ""))
        print(report)
        print(summary)
        print(f"specs written -> {args.out} ({len(specs)} line(s))")
    else:
        if specs:
            report += "\n\n# --- paste-ready (--dry-run first) ---\n" + "\n".join(specs)
        print(report)
        print(summary)
    return 0


if __name__ == "__main__":
    main()
