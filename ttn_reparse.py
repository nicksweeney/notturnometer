#!/usr/bin/env python3
"""Re-derive the tracks table from episodes.raw_json using the current parser.

The counterpart to ttn_warm.py: analysis-time edits (aliases, canonical_key,
normalize_work) need only a cache re-warm; parser-time edits (parse_tracks)
need the tracks table re-derived from the immutable raw_json. This script does
that offline, reports what moved, and offers a no-write --dry-run preview.

    uv run ttn_reparse.py --dry-run            # preview over the whole DB
    uv run ttn_reparse.py                       # apply over the whole DB
    uv run ttn_reparse.py --pids m000ql1y       # one episode (after a quirk fix)
"""
import argparse
import json
import sqlite3

from ttn_scrape import parse_tracks, rebuild_tracks


def diff_tracks(old, new):
    """old, new: position-ordered lists of comparable field-tuples. Returns
    (count_delta, n_content_changed): count_delta = len(new) - len(old);
    n_content_changed = positions present in BOTH that differ. Pure."""
    count_delta = len(new) - len(old)
    n_content_changed = sum(1 for o, m in zip(old, new) if o != m)
    return count_delta, n_content_changed
