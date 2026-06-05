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
