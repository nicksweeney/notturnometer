#!/usr/bin/env python3
"""Reconcile tracks (long_synopsis) with segment_events (MBID-bearing) per
episode, and surface composer alias gaps / same-name ambiguities for triage.
MBID is an audit signal, not the grouping key — the rankings are unchanged.

    uv run ttn_mbid_audit.py ttn.sqlite                 # tiered report
    uv run ttn_mbid_audit.py ttn.sqlite --tier medium   # human-review worklist
    uv run ttn_mbid_audit.py ttn.sqlite --emit          # paste-ready alias tuples
    uv run ttn_mbid_audit.py ttn.sqlite --reconcile-report  # join QC
"""
import argparse
import re
import sqlite3

from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                         resolve_composer_alias, COMPOSER_ALIASES)

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*$", re.IGNORECASE)


def parse_clock_offset(time_str):
    """Clock time ("12:31 AM") -> seconds since midnight, or None if it lacks a
    meridiem / is malformed (the dot-time and bare-HH:MM quirk episodes)."""
    if not time_str:
        return None
    m = _TIME_RE.match(time_str)
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    hh %= 12                     # 12 AM -> 0, 12 PM -> 0 then +12 below
    if ap == "PM":
        hh += 12
    return (hh * 60 + mm) * 60


def episode_offsets(time_strs):
    """Per-track seconds-into-programme relative to the first track, with a
    midnight wrap added whenever the raw clock value decreases. Unparseable
    times stay None and don't shift the others."""
    raw = [parse_clock_offset(t) for t in time_strs]
    base = next((r for r in raw if r is not None), None)
    if base is None:
        return raw
    out, wrap, prev = [], 0, None
    for r in raw:
        if r is None:
            out.append(None)
            continue
        if prev is not None and r < prev:
            wrap += 24 * 3600
        out.append(r + wrap - base)
        prev = r
    return out


# Tuning constants — initial values; validated/tuned against the equal-count
# ground truth in Task 6's smoke step.
_TEMPORAL_TOLERANCE = 90.0      # seconds; distance at which temporal score = 0.5
_W_TEMPORAL = 0.6               # weight of the temporal term when a time exists
_W_CONTENT = 0.4               # weight of the composer+title term
_GAP_COST = 0.85               # cost of leaving an item unmatched
_NO_TEMPORAL = object()        # sentinel: temporal term unavailable


def surname(name):
    toks = ascii_fold(name or "").lower().split()
    return toks[-1] if toks else ""


def title_tokens(title):
    return set(re.findall(r"[a-z0-9]+", ascii_fold(title or "").lower()))


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pair_cost(*, t_off, s_off, t_comp, s_comp, t_title, s_title):
    """Cost in [0,1] of matching one track to one segment. Lower = better.
    Combines temporal distance (when both offsets exist) with a composer-surname
    + title-token content score. Content-only when t_off is None."""
    same_surname = surname(t_comp) == surname(s_comp) and surname(t_comp) != ""
    title_sim = _jaccard(title_tokens(t_title), title_tokens(s_title))
    content_good = (1.0 if same_surname else 0.0) * 0.7 + title_sim * 0.3
    content_cost = 1.0 - content_good
    if t_off is None or s_off is None:
        return min(1.0, 0.15 + content_cost)        # mild penalty, content rules
    temporal_cost = 1.0 - _TEMPORAL_TOLERANCE / (_TEMPORAL_TOLERANCE + abs(t_off - s_off))
    return _W_TEMPORAL * temporal_cost + _W_CONTENT * content_cost
