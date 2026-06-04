#!/usr/bin/env python3
"""Post-alias composer-duplicate detector — an independent cross-check that
flags distinct composer groups likely to be one person keyed apart by a
spelling / transliteration / name-order / typo difference that escapes both
canonical_key's diacritic-fold and the same-surname --mode audit gate (the
Ion Dimitrescu vs Ion Dumitrescu class). Reports candidates for human triage;
optionally emits paste-ready _COMPOSER_ALIAS_PAIRS tuples. Never folds.

Two tiers: date-corroborated (groups sharing a birth-death span, names
compared down to a 0.74 ratio floor with a 0.82 high-confidence divider) and
no-date-corroboration (surname-blocked, 0.88 floor). Dates are a detection
signal only — never folded into the grouping key.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from ttn_analyze import canonical_key, resolve_composer_alias, COMPOSER_ALIASES

PRIMARY_FLOOR = 0.74      # report date-corroborated pairs at/above this ratio
PRIMARY_HIGH = 0.82       # high-confidence divider within the primary tier
SECONDARY_FLOOR = 0.88    # stricter floor for no-date, surname-blocked pairs

_DATE = re.compile(r'[(\[]\s*(?:b\.?\s*)?(\d{3,4})\s*(?:[-–—]\s*(\d{3,4})?)?')


def parse_span(composer_line):
    """The (birth, death) year tuple from a composer_line, or None. death is
    '' for open / birth-only spans (e.g. '(b.1948)', '(1660-)'). The dash and
    death year are optional so birth-only forms still yield a span. Detection
    signal only — never a key."""
    m = _DATE.search(composer_line or "")
    return (m.group(1), m.group(2) or "") if m else None


@dataclass
class ComposerGroup:
    key: str             # resolved canonical key — the group identity
    display: str         # most-common original spelling
    airings: int
    span: tuple | None   # (birth, death|'') most-common span, or None


_EXCLUDE_PREFIX = ("Traditional", "Anon", "Unknown")


_ARR = re.compile(r"\barr\b|arr\.")


def _excluded_name(composer):
    """True for rows that carry no clean single-composer identity: two-composer
    or surname-first malformed lines (comma), arranger credits (the *token*
    'arr'/'arr.', NOT the substring — a substring match would wrongly drop
    Parry, Tarrega, Larrocha, Barriere, Birtwistle, …), and the
    Traditional/Anon/Unknown source-attribution forms."""
    return bool("," in composer or _ARR.search(composer.lower())
                or composer.startswith(_EXCLUDE_PREFIX))


def build_groups(rows):
    """rows: iterable of (composer, composer_line). Returns list[ComposerGroup],
    one per resolved canonical key, with airings, the most-common spelling as
    display, and the most-common parsed date-span."""
    acc = defaultdict(lambda: {"airings": 0, "names": Counter(),
                               "spans": Counter()})
    for composer, line in rows:
        if not composer or _excluded_name(composer):
            continue
        key = resolve_composer_alias(canonical_key(composer))
        rec = acc[key]
        rec["airings"] += 1
        rec["names"][composer] += 1
        sp = parse_span(line)
        if sp:
            rec["spans"][sp] += 1
    groups = []
    for key, rec in acc.items():
        span = rec["spans"].most_common(1)[0][0] if rec["spans"] else None
        groups.append(ComposerGroup(key, rec["names"].most_common(1)[0][0],
                                    rec["airings"], span))
    return groups
