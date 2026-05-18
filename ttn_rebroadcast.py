#!/usr/bin/env python3
"""Find re-aired recordings in ttn.sqlite — a specific performance (one
work, one set of forces) that Through the Night broadcast on two or more
nights. Prints a banded "top X" rebroadcast report; with --emit, also
emits paste-ready WORK_ALIASES tuples for multi-play merge candidates
(one recording aired under variant titles). A report-for-insight /
report-for-triage tool: it never writes to the DB or the alias tables.
See docs/superpowers/specs/2026-05-18-ttn-rebroadcast-design.md.
"""
import csv
import re
import statistics
from collections import Counter, defaultdict, namedtuple
from datetime import date

from ttn_analyze import (canonical_key, catalogue_ref, normalize_composer,
                         normalize_work, resolve_composer_alias,
                         resolve_work_alias, work_title_key)
from ttn_audit import (candidate_id, components, load_decisions,
                       load_tracks, with_track_lengths)
