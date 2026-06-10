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
}


def _usage():
    lines = ["usage: ttn_data.py <subcommand> [args...]", "",
             "kitchen data subcommands:"]
    for name in _DESCRIPTIONS:
        lines.append(f"  {name:10}{_DESCRIPTIONS[name]}")
    lines += ["", "Run `ttn_data.py <subcommand> --help` for a tool's own options."]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    sub, rest = argv[0], argv[1:]
    if sub not in SUBCOMMANDS:
        print(f"ttn_data.py: unknown subcommand {sub!r}\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        raise SystemExit(2)
    module = importlib.import_module(SUBCOMMANDS[sub])
    return module.main(rest)


if __name__ == "__main__":
    main()
