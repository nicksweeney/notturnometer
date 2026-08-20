#!/usr/bin/env python3
"""Auto-remap orphaned registry slugs to their likely successors.

Reads orphan slugs from stdin (one per line), finds successor identities
in the current corpus via token-overlap scoring, and applies remaps to
the registry.  Exit 0 if all orphans resolved; exit 1 if any remain.

Usage (nightly recovery):
    printf '%s\n' 'kacsoh:janos-vitez-excerpts' | uv run ttn_auto_remap.py

Assumes ttn_site_registry.json in cwd.  Writes the registry in place.
"""
import json
import re
import sqlite3
import sys

import ttn_analyze as ana
import ttn_project as proj
from ttn_site import (
    apply_remap, build_composer_index, dump_registry, load_registry,
    registry_path,
)

# --- token-overlap scoring ---------------------------------------------------

_WORK_TOKENS_RE = re.compile(r"[a-z0-9]+")


def _work_tokens(work_key: str) -> set[str]:
    return set(_WORK_TOKENS_RE.findall(work_key))


def _token_overlap(orphan_key: str, candidate_key: str) -> float:
    """Score how well a candidate matches an orphan.

    Uses len(intersection) / min(len(orphan), len(candidate)) so that
    subset relationships in EITHER direction score 1.0.  This catches
    projection drift where tokens are either stripped (e.g. 'c1863' date
    prefix removed) or added (e.g. '[The Hero (Sir) John]' subtitle added).
    """
    ot = _work_tokens(orphan_key)
    ct = _work_tokens(candidate_key)
    if not ot or not ct:
        return 0.0
    return len(ot & ct) / min(len(ot), len(ct))


# --- orphan resolution -------------------------------------------------------

def _resolve_work_orphan(
    slug: str,
    registry: dict,
    derived_by_identity: dict,
    token_threshold: float = 0.6,
) -> tuple[str, str, str] | None:
    """Find the best successor for an orphaned work slug.

    Returns (slug, composer_key, work_key) for the remap, or None.
    """
    stored = registry["works"].get(slug)
    if not stored:
        return None
    ck = stored["composer_key"]
    wk = stored["work_key"]

    # Find candidates: same composer_key in the derived corpus
    candidates = [
        (e["key"][1], e["slug"])
        for e in derived_by_identity.values()
        if e["key"][0] == ck
    ]
    if not candidates:
        return None

    scored = [
        (_token_overlap(wk, cwk), cwk, cslug)
        for cwk, cslug in candidates
    ]
    scored.sort(reverse=True)

    best_score, best_wk, best_slug = scored[0]
    if best_score < token_threshold:
        return None
    # Require a clear winner (no tie at the threshold)
    if len(scored) > 1 and scored[1][0] >= best_score:
        return None

    return (slug, ck, best_wk)


def _resolve_composer_orphan(
    slug: str,
    registry: dict,
    derived_by_identity: dict,
) -> tuple[str, str] | None:
    """Find the best successor for an orphaned composer slug.

    Returns (slug, composer_key) for the remap, or None.
    """
    stored = registry["composers"].get(slug)
    if not stored:
        return None
    ck = stored["composer_key"]

    # The corpus must have this composer under a different key (alias merge)
    # Find any derived entry whose slug is different but whose resolved
    # composer_key is the same alias target
    resolved = ana.resolve_composer_alias(ck)
    if resolved == ck:
        return None  # not an alias merge case

    # Find the resolved identity in the derived composer entries
    for e in derived_by_identity.values():
        if e["composer_key"] == resolved:
            return (slug, resolved)

    return None


# --- main --------------------------------------------------------------------

def main() -> int:
    orphans_raw = sys.stdin.read().strip()
    if not orphans_raw:
        print("ttn_auto_remap: no orphans on stdin", file=sys.stderr)
        return 0

    # Parse orphans from the RegistryDriftError message format:
    #   orphaned work slugs: ['a', 'b']; orphaned composer slugs: []
    work_orphans = []
    composer_orphans = []
    for line in orphans_raw.splitlines():
        m = re.search(r"orphaned work slugs:\s*\[([^\]]*)\]", line)
        if m:
            work_orphans = [
                s.strip().strip("'")
                for s in m.group(1).split(",") if s.strip()
            ]
        m = re.search(r"orphaned composer slugs:\s*\[([^\]]*)\]", line)
        if m:
            composer_orphans = [
                s.strip().strip("'")
                for s in m.group(1).split(",") if s.strip()
            ]

    if not work_orphans and not composer_orphans:
        print("ttn_auto_remap: no orphans found in input", file=sys.stderr)
        return 0

    # Load registry and corpus
    reg = load_registry(registry_path())
    conn = sqlite3.connect("ttn.sqlite")
    try:
        projection, rec_meta, status = proj.ensure(conn)
        if status != "ok":
            print(f"ttn_auto_remap: projection cache status={status!r}", file=sys.stderr)
            return 1
        cursor = conn.execute(
            "SELECT t.title, t.composer, t.composer_line, t.performers, "
            "substr(e.broadcast_date, 1, 10), t.episode_pid, t.position "
            "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid"
        )
        rows5 = list(ana._project_rows(list(cursor), projection, rec_meta))
    finally:
        conn.close()

    entries = ana.build_work_index(rows5)
    composer_entries = build_composer_index(rows5)
    derived_work = {e["key"]: e for e in entries}
    derived_comp = {e["composer_key"]: e for e in composer_entries}

    remapped = 0
    unresolved = []

    # Work orphans
    for slug in work_orphans:
        result = _resolve_work_orphan(slug, reg, derived_work)
        if result is None:
            unresolved.append(slug)
            print(f"  UNRESOLVED: {slug}", file=sys.stderr)
            continue
        s, ck, wk = result
        reg = apply_remap(reg, "works", s, ck, wk)
        remapped += 1
        print(f"  remapped: {s} -> ({ck}, {wk})", file=sys.stderr)

    # Composer orphans
    for slug in composer_orphans:
        result = _resolve_composer_orphan(slug, reg, derived_comp)
        if result is None:
            unresolved.append(slug)
            print(f"  UNRESOLVED: {slug}", file=sys.stderr)
            continue
        s, ck = result
        reg = apply_remap(reg, "composers", s, ck)
        remapped += 1
        print(f"  remapped: {s} -> {ck}", file=sys.stderr)

    dump_registry(reg, registry_path())
    print(f"ttn_auto_remap: {remapped} remapped, {len(unresolved)} unresolved",
          file=sys.stderr)

    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
