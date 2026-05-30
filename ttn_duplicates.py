#!/usr/bin/env python3
"""Post-alias duplicate-work detector — an independent cross-check that
flags same-composer work-groups likely to be one work keyed apart (the
straggler-scan that was being done by eye over `ttn_analyze --by work`).

Design: docs/superpowers/specs/2026-05-30-duplicate-detector-design.md
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

from ttn_analyze import (canonical_key, strip_arranger_tail,
                         resolve_composer_alias, work_title_key,
                         resolve_work_alias)

# Own stopword set (deliberately separate from ttn_audit_composer's, for
# independence). Form words, connectives, key words, scoring, ordinals —
# everything that does NOT carry work identity. Numbers and nickname words
# are kept by _fingerprint.
_STOPWORDS = frozenset((
    "the", "a", "an", "and", "of", "in", "from", "for", "to", "by", "with",
    "on", "or", "no", "nos", "op", "opus", "arr", "arranged", "version",
    "major", "minor", "flat", "sharp",
    "concerto", "concertino", "sonata", "sonatina", "sinfonia",
    "sinfonietta", "symphony", "symphonie", "suite", "partita",
    "divertimento", "serenade", "quartet", "quintet", "sextet", "septet",
    "octet", "nonet", "trio", "overture", "prelude", "fugue", "rondo",
    "fantasia", "fantasy", "variations", "movement", "movements",
    "piano", "violin", "viola", "cello", "flute", "oboe", "clarinet",
    "horn", "trumpet", "harp", "guitar", "harpsichord", "organ",
    "orchestra", "strings", "string", "voice", "voices", "chorus",
    "solo", "continuo",
))


def _fingerprint(title):
    """Identity tokens of a title: canonical-key'd, stopwords removed,
    numbers and nickname words kept (single letters dropped, digits kept)."""
    return frozenset(
        t for t in canonical_key(title).split()
        if t not in _STOPWORDS and (t.isdigit() or len(t) > 1))


@dataclass
class Group:
    composer: str          # canonical composer key (grouping)
    composer_display: str  # most-common original spelling
    work_key: str
    display_title: str     # most-common original title
    airings: int
    fingerprint: frozenset


def build_groups(rows):
    """rows: iterable of (composer, composer_line, title). Returns a list of
    Group, one per (composer_key, work_key) — the same grouping --by work
    produces (arranger tails stripped, composer + work aliases applied)."""
    acc = {}  # (ck, wk) -> [airings, title_counter, composer_counter]
    for composer, composer_line, title in rows:
        if not composer or not title:
            continue
        ck = resolve_composer_alias(
            canonical_key(strip_arranger_tail(composer, composer_line)))
        wk = resolve_work_alias(work_title_key(title))
        rec = acc.setdefault((ck, wk), [0, Counter(), Counter()])
        rec[0] += 1
        rec[1][title] += 1
        rec[2][composer] += 1
    groups = []
    for (ck, wk), (n, titles, comps) in acc.items():
        disp = titles.most_common(1)[0][0]
        groups.append(Group(ck, comps.most_common(1)[0][0], wk, disp, n,
                            _fingerprint(disp)))
    return groups
