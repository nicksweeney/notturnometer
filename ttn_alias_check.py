"""Validate an alias DRAFT FILE before it is pasted into ttn_aliases.py.

`ttn_curate.py check-aliases DRAFT [--db ttn.sqlite] [--kind KIND]` runs the
same verdicts as the ttn_analyze guard tests (dead / chained / trap-A
"scoped target is a global source") at AUTHORING time, plus corpus grounding
the static tests cannot do: an unknown-spelling warning with nearest-key
suggestions and the airing count each fold would pick up.

Exit codes: 0 = all hard checks passed (warnings allowed), 1 = >=1 hard
failure, 2 = usage / file / parse error. Warnings never affect the exit code.

Draft format: one Python string-literal tuple per line, exactly as the
various --emit blocks print them; blank lines skipped, `#`-comment lines
skipped. Trailing junk after the tuple (including an inline comment) is a
parse error -- strip it before checking. --kind selects the reading of
2-field lines (composer vs global work pairs); 3-field lines are always
composer-scoped work triples.

Corpus grounding reads the RAW tables only (tracks + segment_events via the
read-only connection), so it works pre-warm. Known limitation: a variant that
exists only through the projection (rec_meta segment titles) is invisible
here and will false-WARN as unknown.
"""
import argparse
import ast
import difflib
import sqlite3
import sys
from collections import Counter, defaultdict

import ttn_analyze as A


def _parse_draft(path):
    """Return [(lineno, fields)] where fields is a list of 2-3 strings."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise FileNotFoundError(f"cannot read draft file: {e}") from e
    entries = []
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            val = ast.literal_eval(s)
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"line {lineno}: not a string-literal tuple ({e.__class__.__name__})") from e
        if isinstance(val, tuple) and len(val) == 1 and isinstance(val[0], tuple):
            val = val[0]                   # unwrap the trailing-comma 1-tuple
        if not isinstance(val, tuple) or not (2 <= len(val) <= 3) \
                or not all(isinstance(x, str) for x in val):
            raise ValueError(f"line {lineno}: expected a (variant, preferred[, composer]) "
                             f"string-literal tuple")
        entries.append((lineno, list(val)))
    return entries


def _scan_corpus(conn):
    """One pass over both raw tables -> (comp_keys, wk_all, wk_by_ck).

    comp_keys counts airings per RAW canonical composer key (pre-alias);
    wk_all counts work keys over every row; wk_by_ck groups them under the
    RESOLVED composer identity so scoped lookups are exact.
    """
    comp, wk_all, wk_by_ck = Counter(), Counter(), defaultdict(Counter)
    cache = {}
    for tbl, tcol, ccol in (("tracks", "title", "composer"),
                            ("segment_events", "track_title", "composer_name")):
        for c, t, n in conn.execute(
                f"SELECT {ccol}, {tcol}, COUNT(*) FROM {tbl} "
                f"WHERE {tcol} IS NOT NULL GROUP BY {ccol}, {tcol}"):
            c = c or ""
            ckey = A.canonical_key(c)
            comp[ckey] += n
            k = (t, c)
            wk = cache.get(k)
            if wk is None:
                wk = A.work_title_key(t, composer=c)
                cache[k] = wk
            wk_all[wk] += n
            wk_by_ck[A.resolve_composer_alias(ckey)][wk] += n
    return comp, wk_all, dict(wk_by_ck)


def _close(key, pool, n=3):
    return difflib.get_close_matches(key, list(pool), n=n, cutoff=0.6)


def check_entries(entries, kind, corpus):
    """Run every check; return (report_lines, verdict Counter)."""
    comp, wk_all, wk_by_ck = corpus
    out = []
    counts = Counter()
    seen_composer_lhs = {}   # canonical variant key -> (first lineno, preferred)
    draft_variants = set()   # scoped VARIANT keys asserted by earlier lines:
                             # a target may legitimately repeat across lines
                             # (many-to-one folds); only colliding with an
                             # earlier VARIANT would make it resolve onward

    def emit(tag, lineno, kindname, disp, msg=""):
        head = f"line {lineno:>3} {tag:4} {kindname:8} ({disp})"
        out.append(head + (f"\n             {msg}" if msg else ""))

    for lineno, f in entries:
        disp = ", ".join(repr(x) for x in f)

        if len(f) == 3:                                   # --- scoped work triple
            composer, variant, preferred = f
            rk = A.resolve_composer_alias(A.canonical_key(composer))
            vk = A.work_title_key(variant, composer)
            tk = A.work_title_key(preferred, composer)
            if vk == tk:
                emit("FAIL", lineno, "scoped", disp,
                     "dead fold: same work key under this composer")
                counts["fail"] += 1
                continue
            ck = A._scoped_composer_key(composer)
            if tk in draft_variants or (ck, tk) in A._COMPOSER_SCOPED_WORK_ALIASES:
                emit("FAIL", lineno, "scoped", disp,
                     "chained: target is a scoped source elsewhere")
                counts["fail"] += 1
                continue
            if tk in A.WORK_ALIASES:
                emit("FAIL", lineno, "scoped", disp,
                     "trap-A: scoped target is itself a WORK_ALIASES source; it "
                     f"resolves onward to {A.resolve_work_alias(tk, composer)!r} -- "
                     "target that final key's spelling instead")
                counts["fail"] += 1
                continue
            if A.resolve_work_alias(tk, composer) != tk:
                emit("FAIL", lineno, "scoped", disp, "target does not resolve to itself")
                counts["fail"] += 1
                continue
            draft_variants.add(vk)
            n = wk_by_ck.get(rk, {}).get(vk, 0)
            if n:
                emit("OK", lineno, "scoped", disp, f"folds {n} airings -> {tk!r}")
                counts["ok"] += 1
            else:
                near = _close(vk, wk_by_ck.get(rk, {}))
                emit("WARN", lineno, "scoped", disp,
                     "unknown variant under this composer"
                     + (f"; nearest: {[x[:44] for x in near]}" if near else ""))
                counts["warn"] += 1

        elif kind == "composer":                          # --- composer pair
            variant, preferred = f
            vk = A.canonical_key(variant)
            pk = A.canonical_key(preferred)
            if vk == pk:
                emit("FAIL", lineno, "composer", disp,
                     "dead fold: both spellings share one canonical key")
                counts["fail"] += 1
                continue
            if A.resolve_composer_alias(pk) != pk:
                emit("FAIL", lineno, "composer", disp,
                     f"chained: preferred {preferred!r} is itself an alias source; "
                     "use the final canonical spelling")
                counts["fail"] += 1
                continue
            prior = A.COMPOSER_ALIASES.get(vk)
            if prior is not None and prior != pk:
                emit("WARN", lineno, "composer", disp,
                     "COMPOSER_ALIASES already maps this variant to a different target")
                counts["warn"] += 1
            elif vk in seen_composer_lhs and seen_composer_lhs[vk][1] != pk:
                first_ln, first_pref = seen_composer_lhs[vk]
                emit("WARN", lineno, "composer", disp,
                     f"duplicate LHS in batch (line {first_ln} -> {first_pref!r})")
                counts["warn"] += 1
            else:
                seen_composer_lhs.setdefault(vk, (lineno, pk))
            if comp.get(vk, 0):
                emit("OK", lineno, "composer", disp,
                     f"{comp[vk]} airings seen under this spelling-family")
                counts["ok"] += 1
            else:
                near = _close(vk, [k for k, n in comp.items() if n])
                emit("WARN", lineno, "composer", disp,
                     "unknown spelling-family: no raw row shares this canonical key"
                     + (f"; nearest: {near}" if near else ""))
                counts["warn"] += 1

        elif kind == "work":                              # --- global work pair
            variant, preferred = f
            vk = A.work_title_key(variant)
            pk = A.work_title_key(preferred)
            if vk == pk:
                emit("FAIL", lineno, "work", disp,
                     "dead fold: both titles share one work key")
                counts["fail"] += 1
                continue
            if A.resolve_work_alias(pk) != pk:
                emit("FAIL", lineno, "work", disp,
                     f"chained: preferred resolves onward to {A.resolve_work_alias(pk)!r}")
                counts["fail"] += 1
                continue
            if vk in wk_all:
                emit("OK", lineno, "work", disp, f"folds {wk_all[vk]} airings -> {pk!r}")
                counts["ok"] += 1
            else:
                near = _close(vk, [k for k, n in wk_all.items() if n])
                emit("WARN", lineno, "work", disp,
                     "unknown variant key: no raw title shares it"
                     + (f"; nearest: {[x[:44] for x in near]}" if near else ""))
                counts["warn"] += 1

        else:                                             # len(f)==2, kind unresolved
            emit("FAIL", lineno, "ambiguous",
                 disp, "pass --kind composer or --kind work for 2-field lines")
            counts["fail"] += 1

    return out, counts


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(
        prog="ttn_curate.py check-aliases",
        description="validate an alias draft file before editing ttn_aliases.py")
    ap.add_argument("draft")
    ap.add_argument("--db", default="ttn.sqlite")
    ap.add_argument("--kind", default="auto",
                    choices=["auto", "composer", "work", "scoped"])
    ap.add_argument("--quiet", action="store_true",
                    help="print only non-OK lines plus the summary")
    args = ap.parse_args(argv)

    try:
        entries = _parse_draft(args.draft)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2)
    except ValueError as e:
        print(f"parse error: {e}", file=sys.stderr)
        raise SystemExit(2)
    if not entries:
        print(f"no alias tuples found in {args.draft}", file=sys.stderr)
        raise SystemExit(2)

    if args.kind == "auto":
        ambiguous = [ln for ln, f in entries if len(f) == 2]
        if ambiguous:
            print("--kind needed: 2-field lines are ambiguous (composer pair vs "
                  f"global work pair): lines {ambiguous}",
                  file=sys.stderr)
            raise SystemExit(2)
    elif args.kind == "scoped" and any(len(f) != 3 for ln, f in entries):
        print("--kind scoped but the file has non-3-field lines", file=sys.stderr)
        raise SystemExit(2)

    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        corpus = _scan_corpus(conn)
    except sqlite3.Error as e:
        print(f"cannot open/read DB {args.db!r}: {e}", file=sys.stderr)
        raise SystemExit(2)

    out, counts = check_entries(entries, args.kind, corpus)

    if args.quiet:
        kept, prev_ok = [], False
        for l in out:
            is_head = l.startswith("line ")
            if is_head:
                prev_ok = " OK " in l[:14]
            if not prev_ok:
                kept.append(l)
        out = kept
    print("\n".join(out))
    print(f"{counts['ok']} ok, {counts['warn']} warn, {counts['fail']} fail "
          f"({len(entries)} lines)")
    if counts["fail"]:
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    main()
