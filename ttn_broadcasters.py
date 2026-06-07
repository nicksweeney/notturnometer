#!/usr/bin/env python3
"""Rank the EBU source broadcasters supplying BBC R3 'Through the Night',
from segment_events.record_label. Standalone; reads segment_events only.

MBID/EBU provenance lives on the segments side of the tracks<->segment_events
seam; this tool stays wholly on that side (see the design spec). --composer is a
raw ascii-fold filter, NOT a canonical grouping, by design.
"""

import argparse
import sqlite3
from collections import Counter, namedtuple

from ttn_analyze import ascii_fold
from ttn_ebu_codes import decode

UNATTRIBUTED = "UNATTRIBUTED"

BroadcasterStat = namedtuple("BroadcasterStat", "key airings")


def rank_broadcasters(rows, rank_key=lambda code: code):
    """rows: iterable of record_label values (one per segment). Group by
    rank_key(label); empty/NULL label -> the UNATTRIBUTED bucket (never
    inferred). Returns [BroadcasterStat(key, airings)] sorted by airings desc,
    then key asc, with UNATTRIBUTED forced last."""
    counts = Counter()
    for label in rows:
        counts[rank_key(label) if label else UNATTRIBUTED] += 1
    def sort_key(item):
        key, n = item
        return (key == UNATTRIBUTED, -n, key)   # UNATTRIBUTED last
    return [BroadcasterStat(k, n) for k, n in sorted(counts.items(), key=sort_key)]


def load_rows(conn, *, after=None, before=None, year=None, composer=None):
    """Return record_label for every in-scope segment (NULL/'' kept, so coverage
    is computable). Filters: date range / single year (on episodes.broadcast_date)
    and composer (diacritic-insensitive substring on segment_events.composer_name)."""
    conn.create_function(
        "ascii_fold", 1, lambda s: ascii_fold(s) if s is not None else None)
    clauses, params = [], []
    if after:
        clauses.append("e.broadcast_date >= ?"); params.append(after)
    if before:
        clauses.append("e.broadcast_date <= ?"); params.append(before)
    if year:
        clauses.append("substr(e.broadcast_date,1,4) = ?"); params.append(str(year))
    if composer:
        clauses.append("LOWER(ascii_fold(s.composer_name)) LIKE ?")
        params.append(f"%{ascii_fold(composer).lower()}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = ("SELECT s.record_label FROM segment_events s "
           "JOIN episodes e ON s.episode_pid = e.pid" + where)
    return [r[0] for r in conn.execute(sql, params)]
