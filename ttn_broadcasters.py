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
