#!/usr/bin/env python3
"""Recording-pid evidence for identity-aware registry sync (option b).

The evidence cache answers one question during sync_registry's orphan pass:
WHICH recordings backed a slug historically? Keyed by SLUG -- an orphan is a
slug whose stored identity vanished from derivation; what must persist across
that breakage is the set of recording pids that aired under the slug, not any
derived key. Losing the cache degrades to pre-evidence behavior (orphans
raise, auto-remap engages); nothing gates on its freshness -- each successful
build refreshes it from data already in hand.

File shape (gitignored; derived-cache family conventions apply):
    {
      "rows_sha": "<corpus digest at write time>",   # informational only
      "written": "YYYY-MM-DD",
      "works": {"<slug>": ["<recording_pid>", ...]}  # sorted, capped at CAP
    }

rows_sha is informational (a debugging aid when inspecting a cache); nothing
gates on its freshness -- each successful build refreshes the whole file.

The matching rule is deliberately conservative: >= half the sample must
overlap a candidate identity's current pid set, and the candidate must be
GLOBALLY unique (one work anywhere in the corpus), not merely unique within
the orphan's composer.
"""
import json
import math
import os

import ttn_analyze as ana

EVIDENCE_PATH = "ttn_evidence.json"

# Bounded per-slug sample: enough proof for overlap scoring, small enough
# that the file stays modest (~20k slugs x <=32 short pids) and diffs stable.
CAP = 32


def current_pids_by_identity(raw8, projection, rec_meta):
    """{identity_tuple: set(recording_pid)} for the CURRENT corpus.

    raw8: whole-corpus 8-tuple rows (title, composer, composer_line,
          performers, bdate, episode_pid, position, time_str).
    Uses the same identity derivation as the build path, applied to the
    projection only (never presentation -- a medium link is not identity
    proof).
    """
    out = {}
    for row in raw8:
        title, composer, composer_line, _performers, _bdate, ep, pos, _time = row
        c, _cl, t = ana._project_identity(
            ep, pos, composer, composer_line, title, projection, {})
        stripped = ana.strip_arranger_tail(c, _cl)
        ck = ana.resolve_composer_alias(ana.canonical_key(ana.normalize_composer(stripped)))
        wk = ana.resolve_work_alias(ana.work_title_key(t, stripped), stripped)
        if not ck and not wk:
            continue
        rp = projection.get((ep, pos))
        if rp is None:
            continue
        out.setdefault((ck, wk), set()).add(rp)
    return out


def load_evidence(path=EVIDENCE_PATH):
    """Load the evidence cache. Missing/corrupt/wrong-shape -> {'works': {}}
    -- degrade exactly like every other derived cache; the caller's orphan
    pass then finds no evidence and behaves as before."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"works": {}}
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {"works": {}}
    if not isinstance(data, dict) or not isinstance(data.get("works"), dict):
        return {"works": {}}
    works = {}
    for slug, pids in data["works"].items():
        if isinstance(pids, list) and all(isinstance(p, str) for p in pids):
            works[slug] = frozenset(pids)
    return {"works": works}


def write_evidence(pids_by_slug, rows_sha=None, path=EVIDENCE_PATH,
                   today=None):
    """Atomically write the cache: pid sets sorted + capped for stable bytes.

    today: 'YYYY-MM-DD' stamp (caller-supplied for determinism, matching
    sync_registry's style); defaults to omitting the field when None.
    """
    import time

    works = {slug: sorted(pids)[:CAP]
             for slug, pids in sorted(pids_by_slug.items()) if pids}
    data = {"rows_sha": rows_sha,
            "written": today or time.strftime("%Y-%m-%d"),
            "works": works}
    tmp = f"{path}.{os.getpid()}.tmp"       # pid-unique: the 2026-07-19 lesson
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def match_unique(evidence_pids, pids_by_identity):
    """The unique-overlap rule: candidates are identities whose current pid
    set shares >= ceil(0.5 * |E|) of the evidence sample E; heal only when
    EXACTLY ONE candidate matches corpus-wide. Returns the winning identity
    tuple, or None (no match / ambiguous)."""
    evidence_pids = set(evidence_pids)
    n = len(evidence_pids)
    if n == 0:
        return None
    threshold = max(1, math.ceil(0.5 * n))
    winners = []
    for ident, rps in pids_by_identity.items():
        if len(evidence_pids & rps) >= threshold:
            winners.append(ident)
            if len(winners) > 1:
                return None
    return winners[0] if winners else None
