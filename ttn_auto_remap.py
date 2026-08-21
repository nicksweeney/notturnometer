#!/usr/bin/env python3
"""Auto-remap orphaned registry slugs to their likely successors.

Reads orphan slugs from stdin (the RegistryDriftError message format), finds
successor identities in the current corpus, and applies remaps to the
registry.  Exit 0 if every orphan resolved; exit 1 if any remain.

Resolution tiers, strongest proof first:

  A. composer-folded exact key  -- resolve the stored composer key through the
     current alias table, then look for a derived work whose key is
     (resolved_ck, stored_work_key). Byte-identical proof: an alias/gate edit
     moved the composer half, the work half didn't change.

  B. recording-pid overlap      -- the orphan's old recording_pid set (from the
     STALE site.sqlite, which is still intact because the drift check aborts
     before write_site_db) overlaps UNIQUELY with one current work. Airing-
     overlap proof, the keydump method, already persisted.

  C. token overlap (review only) -- same resolved composer, strong title-token
     overlap. NOT auto-applied; emitted as a --remap-file candidate for a
     human to review. A movement-vs-whole-work guard refuses a pure-subset
     match unless the shared tokens include a non-generic content token.

  D. dissolve (retire candidate) -- no recording_pid oracle and no strong
     match; emitted as a --retire-file candidate, never auto-applied.

--dry-run reports the tiers and writes nothing; otherwise tier A/B remaps are
applied and tiers C/D are emitted to stdout for review.

Usage (nightly recovery):
    printf '%s\n' 'kacsoh:janos-vitez-excerpts' | uv run ttn_auto_remap.py

Assumes ttn_site_registry.json and ttn.sqlite in cwd.
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

# Generic movement/formal terms that do NOT prove a work is the same thing.
# A pure-subset match consisting only of these (or these + numbers/key) is a
# movement-vs-whole-work risk, not a remap proof. Catalogue-path keys (the
# §ref|nums|keys form) are excluded from this guard because they encode the
# catalogue identity, not the descriptive title.
_MOVEMENT_TERMS = frozenset({
    "adagio", "allegro", "andante", "largo", "lento", "presto", "vivace",
    "aria", "recitative", "recit", "chorus", "duet", "trio", "quartet",
    "quintet", "overture", "intermezzo", "scherzo", "sarabande", "bourree",
    "gavotte", "gigue", "minuet", "menuet", "allemande", "courante",
    "passepied", "rigaudon", "siciliano", "badinerie",
})


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


def _has_content_evidence(orphan_key: str, candidate_key: str) -> bool:
    """True when the shared tokens include at least one non-generic token --
    the movement-vs-whole-work guard for the token-overlap tier."""
    shared = _work_tokens(orphan_key) & _work_tokens(candidate_key)
    return any(tok not in _MOVEMENT_TERMS for tok in shared)


# --- stale-site.sqlite oracle ------------------------------------------------

def load_stale_work_recording_pids(site_db_path="site.sqlite"):
    """Read the PREVIOUS build's works table and return
    {slug: set(recording_pid)}. A missing/corrupt/stale file degrades to {}
    (the oracle is an enhancement, not a gate -- the same degrade-don't-abort
    convention as every derived cache)."""
    try:
        conn = sqlite3.connect(site_db_path)
        try:
            rows = conn.execute("SELECT slug, facets_json FROM works").fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return {}

    out = {}
    for slug, facets_json in rows:
        if not facets_json:
            continue
        try:
            facets = json.loads(facets_json)
        except ValueError:
            continue
        rps = {r.get("recording_pid") for r in facets.get("recordings", [])}
        rps.discard(None)
        if rps:
            out[slug] = rps
    return out


def build_current_work_recording_pids(raw8, projection):
    """Return {work_key_tuple: set(recording_pid)} for the CURRENT corpus.

    raw8: the whole-corpus 8-tuple cursor (title, composer, composer_line,
          performers, bdate, episode_pid, position, time_str).
    projection: {(episode_pid, position): recording_pid}.
    Uses the same identity derivation as accumulate_entities, applied to the
    projection only (never presentation -- a medium link is not identity
    proof)."""
    out = {}
    for row in raw8:
        title, composer, composer_line, performers, bdate, ep, pos, _time = row
        c, cl, t = ana._project_identity(
            ep, pos, composer, composer_line, title, projection, {})
        stripped = ana.strip_arranger_tail(c, cl)
        ck = ana.resolve_composer_alias(ana.canonical_key(ana.normalize_composer(stripped)))
        wk = ana.resolve_work_alias(ana.work_title_key(t, stripped), stripped)
        if not ck and not wk:
            continue
        rp = projection.get((ep, pos))
        if rp is None:
            continue
        out.setdefault((ck, wk), set()).add(rp)
    return out


# --- orphan resolution -------------------------------------------------------

def resolve_work_orphan(
    slug,
    registry,
    derived_by_identity,
    stale_rps_by_slug,
    current_rps_by_key,
    token_threshold=0.6,
):
    """Classify one orphaned work slug.

    Returns a dict:
      {tier: 'A'|'B'|'C'|'D', slug, composer_key, work_key, candidates?}
    where composer_key/work_key are the successor identity for tiers A/B/C,
    and candidates carries the review list for C/D.
    """
    stored = registry["works"].get(slug)
    if not stored:
        return {"tier": "D", "slug": slug}

    stored_ck = stored["composer_key"]
    stored_wk = stored["work_key"]

    # Tier A: composer-folded exact key. Resolve the STORED composer through
    # the current alias table; the work key must be byte-identical under it.
    resolved_ck = ana.resolve_composer_alias(stored_ck)
    a_key = (resolved_ck, stored_wk)
    if a_key in derived_by_identity:
        return {"tier": "A", "slug": slug, "composer_key": resolved_ck,
                "work_key": stored_wk}

    # Tier B: recording-pid overlap, unique.
    stale_rps = stale_rps_by_slug.get(slug, set())
    if stale_rps:
        overlapping = {}
        for key, rps in current_rps_by_key.items():
            ck, _wk = key
            if ck != resolved_ck:
                continue
            overlap = stale_rps & rps
            if overlap:
                overlapping[key] = overlap
        if len(overlapping) == 1:
            (ck, wk), _overlap = next(iter(overlapping.items()))
            return {"tier": "B", "slug": slug, "composer_key": ck, "work_key": wk}

    # Tier C: token overlap, review only. Same resolved composer, strong
    # overlap, with the movement guard.
    candidates = [
        e for e in derived_by_identity.values()
        if e["key"][0] == resolved_ck
    ]
    scored = sorted(
        (
            _token_overlap(stored_wk, e["key"][1]),
            e["key"][1],
            e["slug"],
        )
        for e in candidates
        if _has_content_evidence(stored_wk, e["key"][1])
    )
    if scored:
        best = scored[-1]
        if best[0] >= token_threshold:
            return {"tier": "C", "slug": slug, "composer_key": resolved_ck,
                    "work_key": best[1], "candidates": scored}

    return {"tier": "D", "slug": slug}


def resolve_composer_orphan(slug, registry, derived_by_identity):
    """Classify an orphaned composer slug. Returns {'tier': 'A'|'D', ...}.

    Only the alias-fold case is provable: the stored key resolves through the
    current alias table to a key that IS in the current composer entries.
    Everything else is a dissolve/retire candidate."""
    stored = registry["composers"].get(slug)
    if not stored:
        return {"tier": "D", "slug": slug}
    stored_ck = stored["composer_key"]
    resolved = ana.resolve_composer_alias(stored_ck)
    if resolved != stored_ck and resolved in derived_by_identity:
        return {"tier": "A", "slug": slug, "composer_key": resolved}
    return {"tier": "D", "slug": slug}


# --- main --------------------------------------------------------------------

def _parse_orphans(raw):
    work_orphans = []
    composer_orphans = []
    for line in raw.splitlines():
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
    return work_orphans, composer_orphans


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    orphans_raw = sys.stdin.read().strip()
    if not orphans_raw:
        print("ttn_auto_remap: no orphans on stdin", file=sys.stderr)
        return 0

    work_orphans, composer_orphans = _parse_orphans(orphans_raw)
    if not work_orphans and not composer_orphans:
        print("ttn_auto_remap: no orphans found in input", file=sys.stderr)
        return 0

    reg = load_registry(registry_path())

    # Current corpus: reuse ttn_site's exact build path (load, not ensure --
    # a stale projection is an operator problem, same as the build).
    try:
        conn = sqlite3.connect("ttn.sqlite")
        try:
            projection, rec_meta, status = proj.load(conn)
            if status != "ok":
                print(f"ttn_auto_remap: projection cache status={status!r} -- "
                      "run `uv run ttn_data.py warm` first", file=sys.stderr)
                return 1
            cursor = conn.execute(
                "SELECT t.title, t.composer, t.composer_line, t.performers, "
                "substr(e.broadcast_date, 1, 10), t.episode_pid, t.position, "
                "t.time_str FROM tracks t JOIN episodes e ON t.episode_pid = e.pid"
            )
            raw8 = list(cursor)
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"ttn_auto_remap: {e}", file=sys.stderr)
        return 1

    rows5 = list(ana._project_rows((r[:7] for r in raw8), projection, rec_meta))
    work_entries = ana.build_work_index(rows5)
    composer_entries = build_composer_index(rows5)
    derived_work = {e["key"]: e for e in work_entries}
    derived_comp = {e["composer_key"]: e for e in composer_entries}

    stale_rps_by_slug = load_stale_work_recording_pids()
    current_rps_by_key = build_current_work_recording_pids(raw8, projection)

    remapped = 0
    review_remap = []
    review_retire = []

    for slug in work_orphans:
        result = resolve_work_orphan(
            slug, reg, derived_work, stale_rps_by_slug, current_rps_by_key)
        tier = result["tier"]
        if tier in ("A", "B"):
            s = result["slug"]
            ck = result["composer_key"]
            wk = result["work_key"]
            if not dry_run:
                reg = apply_remap(reg, "works", s, ck, wk)
            remapped += 1
            print(f"  TIER {tier} remap: {s} -> ({ck}, {wk})", file=sys.stderr)
        elif tier == "C":
            review_remap.append(result)
            print(f"  TIER C review: {result['slug']} -> "
                  f"({result['composer_key']}, {result['work_key']})", file=sys.stderr)
        else:
            review_retire.append(result)
            print(f"  TIER D retire: {result['slug']}", file=sys.stderr)

    for slug in composer_orphans:
        result = resolve_composer_orphan(slug, reg, derived_comp)
        if result["tier"] == "A":
            s = result["slug"]
            ck = result["composer_key"]
            if not dry_run:
                reg = apply_remap(reg, "composers", s, ck)
            remapped += 1
            print(f"  TIER A composer remap: {s} -> {ck}", file=sys.stderr)
        else:
            review_retire.append(result)
            print(f"  TIER D composer retire: {result['slug']}", file=sys.stderr)

    if not dry_run:
        dump_registry(reg, registry_path())

    if review_remap:
        print("# review --remap-file candidates:", file=sys.stderr)
        for r in review_remap:
            print(f"{r['slug']}|{r['composer_key']}|{r['work_key']}", file=sys.stderr)
    if review_retire:
        print("# review --retire-file candidates:", file=sys.stderr)
        for r in review_retire:
            print(r["slug"], file=sys.stderr)

    unresolved_count = len(review_remap) + len(review_retire)
    print(f"ttn_auto_remap: {remapped} auto-remapped, "
          f"{unresolved_count} need review", file=sys.stderr)

    return 1 if unresolved_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
