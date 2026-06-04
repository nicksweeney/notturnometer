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
