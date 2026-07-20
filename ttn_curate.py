"""Staff/back-of-house curation dispatcher: one door to the triage tools.

Thin pass-through: `uv run ttn_curate.py <subcommand> [args...]` calls the
matching tool's main(args...) verbatim. Single-path since SP4d-3b: the
tools' standalone CLIs are retired, so this dispatcher (with ttn_data for
the kitchen stages) is the only door to them.
"""
import importlib
import sys

# subcommand -> module exposing main(argv)
SUBCOMMANDS = {
    "duplicates":          "ttn_duplicates",
    "composer-duplicates": "ttn_composer_duplicates",
    "audit":               "ttn_audit",
    "audit-composer":      "ttn_audit_composer",
    "mbid-audit":          "ttn_mbid_audit",
    "bridge":              "ttn_bridge",
    "work-alias-candidates": "ttn_spine",
    "fragmentation":       "ttn_fragmentation",
}

_DESCRIPTIONS = {
    "duplicates":          "post-alias duplicate-work straggler scan",
    "composer-duplicates": "same-person composer-split detector",
    "audit":               "--once re-airing merge-candidate finder",
    "audit-composer":      "composer-deep-dive fold-candidate audit",
    "mbid-audit":          "reconcile tracks <-> segment_events (MBID audit)",
    "bridge":              "cross-era link ledger (candidates / accept / reject)",
    "work-alias-candidates": "recording-co-occurrence work-alias oracle (spine)",
    "fragmentation":       "rank composers by foldable airings (curation worklist)",
}


def _usage():
    lines = ["usage: ttn_curate.py <subcommand> [args...]", "",
             "staff curation subcommands:"]
    for name in SUBCOMMANDS:
        lines.append(f"  {name:22}{_DESCRIPTIONS[name]}")
    lines += ["", "Run `ttn_curate.py <subcommand> --help` for a tool's own options."]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    sub, rest = argv[0], argv[1:]
    if sub not in SUBCOMMANDS:
        print(f"ttn_curate.py: unknown subcommand {sub!r}\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        raise SystemExit(2)
    module = importlib.import_module(SUBCOMMANDS[sub])
    return module.main(rest)


if __name__ == "__main__":
    main()
