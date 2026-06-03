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


# Comparable field-tuple: the stored tracks columns minus id/episode_pid/
# position. Both DB rows and freshly-parsed dicts are projected to this shape.
_OLD_COLS = ("time_str, composer, composer_line, contributors_json, "
             "title, performers")


def _track_tuple(t):
    """Project a parse_tracks() dict into the comparable field-tuple, matching
    exactly how rebuild_tracks serializes contributors_json."""
    return (t["time"], t["composer"], t["composer_line"],
            json.dumps(t["contributors"], ensure_ascii=False),
            t["title"], t["performers"])


def reparse(conn, *, pids=None, dry_run=False):
    """Re-derive tracks for every episode (or just `pids`) from raw_json.
    Returns a result dict. Writes (and commits once) unless dry_run."""
    cur = conn.cursor()
    if pids is not None:
        rows, found = [], set()
        for pid in pids:
            row = cur.execute(
                "SELECT pid, raw_json, broadcast_date FROM episodes "
                "WHERE pid = ?", (pid,)).fetchone()
            if row:
                rows.append(row)
                found.add(pid)
        pids_not_found = [p for p in pids if p not in found]
    else:
        rows = cur.execute(
            "SELECT pid, raw_json, broadcast_date FROM episodes").fetchall()
        pids_not_found = []

    result = {
        "dry_run": dry_run,
        "episodes_processed": 0,
        "pids_not_found": pids_not_found,
        "skipped": [],
        "tracks_before": 0,
        "tracks_after": 0,
        "content_changed": 0,
        "count_changes": [],
    }

    for pid, raw_json, bdate in rows:
        try:
            parsed = json.loads(raw_json) if raw_json else None
            prog = (parsed or {}).get("programme") or {}
        except (TypeError, json.JSONDecodeError):
            result["skipped"].append((pid, "malformed raw_json"))
            continue
        long_synopsis = prog.get("long_synopsis", "")

        old = cur.execute(
            f"SELECT {_OLD_COLS} FROM tracks WHERE episode_pid = ? "
            "ORDER BY position", (pid,)).fetchall()
        new = [_track_tuple(t) for t in parse_tracks(long_synopsis)]

        count_delta, n_content = diff_tracks(old, new)
        result["tracks_before"] += len(old)
        result["tracks_after"] += len(new)
        result["content_changed"] += n_content
        if count_delta != 0:
            result["count_changes"].append(
                (pid, (bdate or "")[:10], len(old), len(new)))
        if not dry_run:
            rebuild_tracks(conn, pid, long_synopsis)
        result["episodes_processed"] += 1

    if not dry_run:
        conn.commit()
    result["count_changes"].sort(key=lambda c: c[1])   # by broadcast date
    return result
