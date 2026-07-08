"""Kitchen/back-of-house data dispatcher: one door to the ingestion + cache tools.

Thin pass-through: `uv run ttn_data.py <subcommand> [args...]` calls the matching
tool's main(args...) verbatim. Plus three metatasks: `update` (= scrape -> segments
-> warm), the DATA-REFRESH recipe so the segments-backfill and re-warm can't be
forgotten; `rebuild` (= reparse -> warm, or `--segments`: segments --reparse
-> warm), the CODE-CHANGE reconciliation recipe so the post-reparse re-warm can't
be forgotten; and `bootstrap` (= scrape --full -> segments -> warm), the COLD-START
recipe that builds the whole corpus from scratch (estimate-by-default, --yes to run).
Single-path (SP4d-4): the stage tools have no standalone CLI; this dispatcher (with
ttn_analyze and ttn_curate) is one of the three doors.
"""
import argparse
import importlib
import sys

# subcommand -> module exposing main(argv). (update is a metatask, handled below.)
SUBCOMMANDS = {
    "scrape":   "ttn_scrape",
    "segments": "ttn_segments",
    "reparse":  "ttn_reparse",
    "project":  "ttn_project",
    "warm":     "ttn_warm",
}

_DESCRIPTIONS = {
    "scrape":   "walk peers.previous from a seed into episodes/tracks (network)",
    "segments": "fetch /segments.json into segment_events (gap-driven, network)",
    "reparse":  "re-derive tracks from raw_json after a parser change (offline)",
    "project":  "build / --status the recording-anchored projection cache",
    "warm":     "make-current: projection (if stale) + the --summary caches",
    "update":   "data-refresh recipe: scrape -> segments -> warm (idempotent)",
    "rebuild":  "code-change recipe: reparse -> warm (--segments: segments --reparse -> warm)",
    "bootstrap": "cold-start recipe: full scrape -> segments -> warm (from scratch; --yes to run)",
}


def _usage():
    lines = ["usage: ttn_data.py <subcommand> [args...]", "",
             "kitchen data subcommands:"]
    for name in _DESCRIPTIONS:
        lines.append(f"  {name:10}{_DESCRIPTIONS[name]}")
    lines += ["", "Run `ttn_data.py <subcommand> --help` for a tool's own options."]
    return "\n".join(lines)


def _run_stages(metatask, stages):
    """Run an ordered [(name, module, argv), …] pipeline, abort-on-failure.

    Honors all three stage exit conventions: SystemExit (a clean exit(0)/None is
    success, a non-zero code stops), an int return code, and a raised exception.
    Shared by the `update` and `rebuild` metatasks — pure sequencing, no new
    derivation logic of its own.
    """
    n = len(stages)
    for i, (name, module, sargv) in enumerate(stages, 1):
        print(f"[{i}/{n}] {name} …", flush=True)
        try:
            rc = module.main(sargv)
        except SystemExit as e:
            if e.code:
                print(f"{metatask}: {name} failed (exit {e.code}), stopping", file=sys.stderr)
                raise SystemExit(e.code)
            rc = 0  # a clean sys.exit(0)/None from the stage is success
        except Exception as e:                     # noqa: BLE001 - surface any stage error, then stop
            print(f"{metatask}: {name} failed ({e}), stopping", file=sys.stderr)
            raise SystemExit(1)
        if isinstance(rc, int) and rc != 0:        # stages that signal via return code
            print(f"{metatask}: {name} failed (exit {rc}), stopping", file=sys.stderr)
            raise SystemExit(rc)
    return 0


def _run_update(rest):
    """Data-refresh recipe: scrape -> segments -> warm, in order, abort-on-fail.

    Idempotent by construction (each stage is): no new episodes -> segments
    no-ops -> warm is all cache-hits. Pure sequencing, no new derivation logic.
    """
    ap = argparse.ArgumentParser(
        prog="ttn_data.py update",
        description="Pull new broadcasts and make the caches current.")
    ap.add_argument("--db", default="ttn.sqlite", help="SQLite path (default: ttn.sqlite)")
    ap.add_argument("--days", type=int, default=None,
                    help="Forwarded to scrape's back-walk (default: scrape's own 365)")
    a = ap.parse_args(rest)

    import ttn_scrape, ttn_segments, ttn_warm
    scrape_argv = ["--db", a.db] + (["--days", str(a.days)] if a.days is not None else [])
    stages = [
        ("scrape",   ttn_scrape,   scrape_argv),   # scrape: --db / --days flags
        ("segments", ttn_segments, [a.db]),        # segments: positional db
        ("warm",     ttn_warm,     [a.db]),        # warm: positional db
    ]
    return _run_stages("update", stages)


def _run_rebuild(rest):
    """Code-change reconciliation recipe: re-derive, then make the caches current.

    Default = reparse -> warm (after a tracks parser / `parse_tracks` change).
    `--segments` = segments --reparse -> warm (after a `derive_segment_events`
    mapping change) INSTEAD of reparse: the two derivations are independent
    (tracks vs segment_events), so you rebuild only the table whose code you
    changed. Both paths end in warm, which rebuilds the projection + summary
    caches — the re-warm a bare `reparse`/`segments --reparse` is easy to forget.
    Same thin-sequencing + abort-on-failure discipline as `update`.
    """
    ap = argparse.ArgumentParser(
        prog="ttn_data.py rebuild",
        description="Re-derive after a parser/derivation code change, then make caches current.")
    ap.add_argument("--db", default="ttn.sqlite", help="SQLite path (default: ttn.sqlite)")
    ap.add_argument("--segments", action="store_true",
                    help="Re-derive segment_events (segments --reparse) instead of tracks (reparse)")
    a = ap.parse_args(rest)

    import ttn_reparse, ttn_segments, ttn_warm
    if a.segments:
        first = ("segments --reparse", ttn_segments, ["--reparse", a.db])  # segments: positional db + flag
    else:
        first = ("reparse", ttn_reparse, [a.db])                            # reparse: positional db
    stages = [first, ("warm", ttn_warm, [a.db])]                            # warm: positional db
    return _run_stages("rebuild", stages)


def _render_bootstrap_plan(db, delay, today=None):
    """The pre-run plan/estimate a bare `bootstrap` prints, then exits (the same
    cancel-before-begin gate as `scrape --full`, scaled to the whole pipeline).

    Network-free: the per-stage figures are date-derived upper bounds (nights
    from each stage's floor to today at the request rate) plus a fixed offline
    warm — the exact work isn't knowable until the run starts (that's the point
    of a cold start), and on a populated DB the real time is less (cached
    episodes skip). `today` is injectable for testing.
    """
    import datetime as _dt
    import ttn_scrape
    import ttn_segments
    if today is None:
        today = _dt.date.today()

    def _hm(mins):
        h, m = divmod(round(mins), 60)
        return f"~{h}h{m:02d}m" if h else f"~{m}m"

    scrape_eps = (today - _dt.date.fromisoformat(ttn_scrape.CORPUS_FLOOR_DATE)).days
    seg_eps = (today - _dt.date.fromisoformat(ttn_segments.SEGMENTS_FLOOR_DATE)).days
    warm_min = 7
    scrape_min, seg_min = scrape_eps * delay / 60, seg_eps * delay / 60
    total = _hm(scrape_min + seg_min + warm_min)
    db_flag = "" if db == "ttn.sqlite" else f" --db {db}"
    return "\n".join([
        "Bootstrap: build the whole corpus from scratch, then make it analyzable.",
        "Three stages, abort-on-failure:",
        "",
        f"  1 scrape --full : peers.previous back to {ttn_scrape.CORPUS_FLOOR_DATE}"
        f"   ({_hm(scrape_min)}, up to ~{scrape_eps:,} eps)",
        f"  2 segments      : /segments.json for 2012+ episodes"
        f"          ({_hm(seg_min)}, up to ~{seg_eps:,} eps)",
        f"  3 warm          : projection + summary/slug caches"
        f"           (~{warm_min}m, offline)",
        "",
        f"  total: {total} at {delay}s/request   writes: {db}",
        "",
        "Idempotent (skips cached) but long — run it detached so it survives a "
        "dropped shell:",
        "",
        f"  nohup uv run ttn_data.py bootstrap --yes{db_flag} "
        f">bootstrap.log 2>&1 &",
        "",
        "Re-run with --yes to start now. Nothing was fetched.",
    ])


def _run_bootstrap(rest):
    """Cold-start recipe: full scrape -> segments -> warm, abort-on-failure.

    The from-scratch counterpart to `update` (which tops up an existing corpus):
    a full back-walk to the corpus floor, then the segments backfill, then the
    caches — one command for a complete, current, analyzable corpus. Same thin
    sequencing + `_run_stages` discipline. Guarded by the same estimate-by-
    default / --yes gate as `scrape --full`, at the whole-pipeline scale; --yes
    propagates into the scrape stage so its own inner gate doesn't re-block.
    """
    ap = argparse.ArgumentParser(
        prog="ttn_data.py bootstrap",
        description="Build the whole corpus from scratch: full scrape -> segments -> warm.")
    ap.add_argument("--db", default="ttn.sqlite", help="SQLite path (default: ttn.sqlite)")
    ap.add_argument("--delay", type=float, default=0.8,
                    help="Seconds between requests, forwarded to scrape+segments (default: 0.8)")
    ap.add_argument("--yes", action="store_true",
                    help="Confirm and actually run (without it, prints the plan/estimate and exits)")
    a = ap.parse_args(rest)

    if not a.yes:
        print(_render_bootstrap_plan(a.db, a.delay))
        return 0

    import ttn_scrape, ttn_segments, ttn_warm
    d = str(a.delay)
    stages = [
        ("scrape --full", ttn_scrape,   ["--db", a.db, "--full", "--yes", "--delay", d]),
        ("segments",      ttn_segments, [a.db, "--delay", d]),   # segments: positional db
        ("warm",          ttn_warm,     [a.db]),                 # warm: positional db
    ]
    return _run_stages("bootstrap", stages)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "update":
        return _run_update(rest)
    if sub == "rebuild":
        return _run_rebuild(rest)
    if sub == "bootstrap":
        return _run_bootstrap(rest)
    if sub not in SUBCOMMANDS:
        print(f"ttn_data.py: unknown subcommand {sub!r}\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        raise SystemExit(2)
    module = importlib.import_module(SUBCOMMANDS[sub])
    return module.main(rest)


if __name__ == "__main__":
    main()
