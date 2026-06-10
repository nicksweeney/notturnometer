"""Kitchen/back-of-house data dispatcher: one door to the ingestion + cache tools.

Thin pass-through: `uv run ttn_data.py <subcommand> [args...]` calls the matching
tool's main(args...) verbatim. Plus one metatask, `update` (= scrape -> segments
-> warm), encoding the data-refresh recipe so the segments-backfill and re-warm
can't be forgotten. Single-path (SP4d-4): the stage tools have no standalone CLI;
this dispatcher (with ttn_analyze and ttn_curate) is one of the three doors.
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
}


def _usage():
    lines = ["usage: ttn_data.py <subcommand> [args...]", "",
             "kitchen data subcommands:"]
    for name in _DESCRIPTIONS:
        lines.append(f"  {name:10}{_DESCRIPTIONS[name]}")
    lines += ["", "Run `ttn_data.py <subcommand> --help` for a tool's own options."]
    return "\n".join(lines)


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
    n = len(stages)
    for i, (name, module, sargv) in enumerate(stages, 1):
        print(f"[{i}/{n}] {name} …", flush=True)
        try:
            rc = module.main(sargv)
        except SystemExit as e:
            if e.code:
                print(f"update: {name} failed (exit {e.code}), stopping", file=sys.stderr)
                raise SystemExit(e.code)
            rc = 0  # a clean sys.exit(0)/None from the stage is success
        except Exception as e:                     # noqa: BLE001 - surface any stage error, then stop
            print(f"update: {name} failed ({e}), stopping", file=sys.stderr)
            raise SystemExit(1)
        if isinstance(rc, int) and rc != 0:        # stages that signal via return code
            print(f"update: {name} failed (exit {rc}), stopping", file=sys.stderr)
            raise SystemExit(rc)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "update":
        return _run_update(rest)
    if sub not in SUBCOMMANDS:
        print(f"ttn_data.py: unknown subcommand {sub!r}\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        raise SystemExit(2)
    module = importlib.import_module(SUBCOMMANDS[sub])
    return module.main(rest)


if __name__ == "__main__":
    main()
