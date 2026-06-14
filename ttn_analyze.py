#!/usr/bin/env python3
"""
Analyze the SQLite database produced by ttn_scrape.py to find the recurring
pieces, works, and composers on BBC Radio 3 'Through the Night'.

Five rollup modes:

  --by piece     : exact title — movement-level and arrangement/scoring
                   distinctions kept (the lens for seeing individual
                   arrangements; --by work folds them)
  --by work      : title with movement/section markers stripped, so e.g.
                   "Symphony No. 5 ... I. Allegro con brio" and
                   "Symphony No. 5 ... II. Andante con moto" both fold into
                   "Symphony No. 5". (Default.)
  --by composer  : composer only
  --by ensemble  : performing ensemble (orchestra, choir, quartet, …);
                   tracks with multiple ensembles credit each one
  --by conductor : conductor or director; many tracks (chamber music)
                   have none — those don't contribute

Date range filtering (both bounds inclusive):

  --after  YYYY-MM-DD    only broadcasts on or after this date
  --before YYYY-MM-DD    only broadcasts on or before this date
  --year   YYYY          shortcut for --after YYYY-01-01 --before YYYY-12-31

So `--after 2024-01-01 --before 2024-12-31` and `--year 2024` are equivalent.

Other options:

  --christmas            restrict to Dec 25 broadcasts of any year (TTN's
                         early-Christmas-morning programmes — these are
                         heavily festive, unlike Dec 26)
  --dates                also list the individual broadcast dates for each
                         entry (inline in stdout, extra column in CSV)
  --once                 restrict to one-off entries (count == 1). Under
                         --by piece/work, also shows the performer inline
                         since there's exactly one — useful for browsing
                         repertoire that someone made a deliberate choice
                         to play just once
  --raw                  disable canonicalization (no diacritic folding,
                         no alias lookup)
  -v, --verbose          show audit info: per-row spelling-variant counts
                         and the count of composer aliases resolved

Filters (combinable with each other and with date filters):

  --composer S           tracks whose composer contains S (case-insensitive
                         substring)
  --title    S           tracks whose title contains S as a whole word
                         (case-insensitive, word-boundary — '--title
                         concerto' does NOT match 'concertino')
  --form     NAME        tracks naming a compositional form, including
                         cross-language synonyms (--form symphony matches
                         Symphony and Symphonie). See --help for the full
                         vocabulary; siblings stay separate ('--form
                         concerto' does NOT match Concertino).

Usage:
    uv run ttn_analyze.py ttn.sqlite
    uv run ttn_analyze.py ttn.sqlite --by composer --top 50
    uv run ttn_analyze.py ttn.sqlite --after 2023-01-01 --before 2023-12-31
    uv run ttn_analyze.py ttn.sqlite --composer Sibelius --dates
    uv run ttn_analyze.py ttn.sqlite --title symphony --top 10
    uv run ttn_analyze.py ttn.sqlite --by composer --title concerto --top 10
    uv run ttn_analyze.py ttn.sqlite --form prelude --top 10
    uv run ttn_analyze.py ttn.sqlite --composer Berlioz --form symphony
    uv run ttn_analyze.py ttn.sqlite --by work --csv top_works.csv --dates
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from ttn_aliases import (_COMPOSER_ALIAS_PAIRS, _COMPOSER_DISPLAY_PREFERENCES,
                         _ENSEMBLE_ALIAS_PAIRS, _WORK_ALIAS_PAIRS)

# ---------------------------------------------------------------------------
# Normalization
#
# Heuristics only. Classical-music titling is wildly inconsistent: the same
# piece can appear as
#   "Symphony No. 5 in C minor, Op. 67"
#   "Symphony no 5 in C minor, Op. 67: I. Allegro con brio"
#   "Symphony No. 5 in C minor, Op. 67 (1st mvt)"
# We try to fold these together for the 'work' rollup but won't catch every
# variant. Inspect the output and tweak the regex if needed.
# ---------------------------------------------------------------------------

TEMPO_TERMS = (
    r"Allegro|Allegretto|Andante|Andantino|Adagio|Adagietto|Largo|Larghetto|"
    r"Lento|Presto|Prestissimo|Vivace|Vivacissimo|Moderato|Maestoso|"
    r"Grave|Sostenuto|Cantabile|Espressivo|Tranquillo"
)
FORM_TERMS = (
    r"Scherzo|Minuet|Menuett|Menuetto|Trio|Rondo|Rondeau|Finale|Prelude|"
    r"Pr[eé]lude|Aria|Recitativ[eo]?|Chorale|Choral|Fugue|Fuga|Toccata|"
    r"Variation[s]?|Theme|Cadenza|Intermezzo|Interlude|Sinfonia|"
    r"Introduction|Cavatina|Romanza|Romance|Nocturne|Notturno|Berceuse"
)
# "Overture" deliberately NOT in FORM_TERMS: a standalone overture (opera/play
# concert overture) is the work itself, not a movement excerpt, so stripping a
# trailing "- Overture" mis-displayed ~131 works as their bare opera name. The
# strip is display-only (work_title_key never calls normalize_work), so this
# changes nothing about grouping.

# Movement/tempo/form-excerpt strippers — clean a movement designation off a
# displayed title ("Symphony No 5: I. Allegro" -> "Symphony No 5").
_movement_strip_patterns = [
    re.compile(r"\s*[:;,\-]\s*(I{1,3}V?|IV|VI{0,3}|IX|X{1,3}V?|XI{1,3}|"
               r"XIV|XV|XVI{0,3}|XIX|XX)\.?\b.*$"),
    re.compile(r"\s*[:;,\-]\s*\d{1,2}\.\s+\S.*$"),
    re.compile(r"\s*\([^)]*\b(?:mvt|movement|movt)\b[^)]*\)\s*$",
               re.IGNORECASE),
    re.compile(rf"\s*[:;,\-]\s*(?:{TEMPO_TERMS})\b.*$", re.IGNORECASE),
    re.compile(rf"\s*[:;,\-]\s*(?:{FORM_TERMS})\b.*$", re.IGNORECASE),
]

# Trailing parenthetical labels. work_title_key keeps these as tokens on the
# token-sort path (so "X (excerpts)" is a DISTINCT group from "X"), but folds
# them on the catalogue path. Stripping them for display therefore makes two
# genuinely-distinct groups render identically — see keep_parentheticals below.
_parenthetical_strip_pattern = re.compile(
    r"\s*\((?:excerpts?|arr\.?[^)]*|transcr\.?[^)]*|orch\.?[^)]*)\)\s*$",
    re.IGNORECASE)

# Default order preserves prior behaviour exactly (parenthetical strip last).
_movement_patterns = _movement_strip_patterns + [_parenthetical_strip_pattern]


def normalize_work(title: str, *, keep_parentheticals: bool = False) -> str:
    """Display-clean a work title by stripping a trailing movement designation.

    keep_parentheticals=True suppresses ONLY the trailing
    (excerpts)/(arr.)/(transcr.)/(orch.) strip, so a work aired both whole and
    as "(excerpts)" — distinct work_title_keys — renders as two distinct rows.
    The DEFAULT keeps stripping them: ttn_audit/ttn_credits route their grouping
    key through normalize_work, and the cross-era bridge ledger depends on that
    key staying stable, so only the --by work display opts in."""
    if not title:
        return ""
    pats = _movement_strip_patterns if keep_parentheticals else _movement_patterns
    t = title.strip()
    changed = True
    while changed:
        changed = False
        for pat in pats:
            new = pat.sub("", t).strip()
            if new and new != t:
                t = new
                changed = True
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(" :;,-")
    return t


# Bare form/tempo words (ascii-folded, lowercase, singular) used by the display
# guard below to detect a movement-strip that ate a compound work-name down to
# nothing. Mirrors FORM_TERMS + TEMPO_TERMS; the detector folds plurals, so only
# singular forms are listed. A drift test asserts each stays detected.
_BARE_FORMTEMPO_WORDS = frozenset({
    # TEMPO_TERMS
    "allegro", "allegretto", "andante", "andantino", "adagio", "adagietto",
    "largo", "larghetto", "lento", "presto", "prestissimo", "vivace",
    "vivacissimo", "moderato", "maestoso", "grave", "sostenuto", "cantabile",
    "espressivo", "tranquillo",
    # FORM_TERMS
    "scherzo", "minuet", "menuett", "menuetto", "trio", "rondo", "rondeau",
    "finale", "prelude", "aria", "recitative", "recitativo", "recitativ",
    "chorale", "choral", "fugue", "fuga", "toccata", "variation", "theme",
    "cadenza", "intermezzo", "interlude", "sinfonia", "introduction",
    "cavatina", "romanza", "romance", "nocturne", "notturno", "berceuse",
})
_BARE_FORMTEMPO_LEAD = re.compile(
    r"^(?:the|a|an|le|la|les|der|die|das|l'|no\.?\s*\d+|\d+)\s+", re.IGNORECASE)


def _is_bare_form_word(s: str) -> bool:
    """True when `s` is nothing but a single form/tempo word (after dropping a
    leading article or 'No N' / number), e.g. 'Prelude', 'Prélude', 'Aria',
    'Allegro'. Used to detect a movement-strip false positive."""
    x = ascii_fold(s).lower().strip()
    prev = None
    while x != prev:
        prev, x = x, _BARE_FORMTEMPO_LEAD.sub("", x).strip()
    return x in _BARE_FORMTEMPO_WORDS or x.rstrip("s") in _BARE_FORMTEMPO_WORDS


def display_work_title(title: str) -> str:
    """Display-faithful work title for the --by work ranking. Keeps the trailing
    parenthetical (so whole vs '(excerpts)' stay visually distinct) AND reverts a
    movement-strip that collapsed a COMPOUND work-name to a bare form/tempo word:
    'Prelude, Fugue and Variation' would otherwise show as 'Prelude'. When the
    strip leaves only a bare form word, the full (trimmed) title is shown instead
    — strictly more informative than a bare tempo marker. The strip still applies
    to genuine movement excerpts whose stem is substantive ('Symphony No 5: I.
    Allegro' -> 'Symphony No 5')."""
    cleaned = normalize_work(title, keep_parentheticals=True)
    if _is_bare_form_word(cleaned):
        trimmed = re.sub(r"\s+", " ", title.strip()).rstrip(" :;,-")
        if not _is_bare_form_word(trimmed):
            return trimmed
    return cleaned


def normalize_composer(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # BBC sometimes wraps group-composer names in single quotes for styling
    # (e.g. "'Les Six'"). Strip the wrapping pair; leaves "O'Connor" alone
    # because that's quote-then-letter, not a wrapping pair.
    if len(name) > 2 and name.startswith("'") and name.endswith("'"):
        name = name[1:-1].strip()
    return name


# When the BBC source line ends with "(arranger)" and the composer string
# carries a comma, both halves got mashed into the composer field — e.g.
# "Johann Sebastian Bach, Ottorino Respighi" with source line
# "Johann Sebastian Bach, Ottorino Respighi (arranger)". The intent is
# "Bach composed, Respighi arranged". Strip the tail so the work is
# attributed to the actual composer. Affects ~30 distinct strings in
# the 10-year DB. Arranger info is still preserved verbatim in
# contributors_json and composer_line.
_ARRANGER_LINE_RE = re.compile(r"\(arranger\)\s*$", re.IGNORECASE)


def strip_arranger_tail(composer: str, composer_line: str) -> str:
    if not composer or not composer_line or "," not in composer:
        return composer
    if not _ARRANGER_LINE_RE.search(composer_line):
        return composer
    return composer.split(",", 1)[0].strip() or composer


def composer_surname(name: str) -> str:
    if not name:
        return ""
    name = normalize_composer(name)
    if "," in name:
        return name.split(",", 1)[0].strip()
    return name.split()[-1] if name.split() else name


# ---------------------------------------------------------------------------
# Canonicalization — used as a grouping key only. The original spellings are
# preserved for display; the canonical key folds diacritics and normalizes
# punctuation/whitespace/opus markers so that variants of the same item are
# counted together.
#
# Real examples this catches:
#   "Antonín Dvořák"   ↔ "Antonin Dvorak"
#   "Sergey Prokofiev" ↔ "Sergei Prokofiev"  (no, distinct keys -- caught separately)
#   "Op 26" ↔ "Op. 26" ↔ "op. 26"
#   "Prélude à l'après-midi d'un faune" ↔ "Prelude a l'apres-midi d'un faune"
# ---------------------------------------------------------------------------

# Characters that NFKD won't decompose to ASCII -- handle them explicitly.
# Found in this dataset: ł (62 occurrences in composer names), ø (13), đ (1).
# Including the others preemptively for older data.
_EXTRA_FOLD = str.maketrans({
    "ł": "l", "Ł": "L",
    "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th",
    "ß": "ss",
    "æ": "ae", "Æ": "Ae",
    "œ": "oe", "Œ": "Oe",
    "ı": "i", "İ": "I",
    "‐": "-", "‑": "-",   # U+2010 / U+2011 typographic hyphens (segments.json)
})


def ascii_fold(s: str) -> str:
    if not s:
        return ""
    s = s.translate(_EXTRA_FOLD)
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _demojibake(s: str) -> str:
    """Repair double-encoded UTF-8 (mojibake) — text whose UTF-8 bytes were
    decoded as Latin-1/CP1252 at the source, e.g. 'FrÃ©dÃ©ric' for 'Frédéric',
    'MartinÅ¯' for 'Martinů', 'MikoÅ‚aj' (cp1252) for 'Mikołaj'. Returns the
    repaired string only when a round-trip cleanly succeeds and improves it;
    otherwise returns s unchanged.

    Strict no-op on clean text and on real accented / Nordic names (José, Åke,
    Dvořák): their bytes don't form valid UTF-8 on the round-trip, so the
    decode raises and the original is returned. This makes the repair safe —
    it can only ever fix corruption, never introduce it."""
    for codec in ("latin-1", "cp1252"):
        try:
            fixed = s.encode(codec).decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        if fixed != s and fixed.isprintable() and "�" not in fixed:
            return fixed
    return s


def _best_spelling(counter) -> str:
    """Pick the display spelling from a Counter of original spellings: the most
    common one, except a detected mojibake (one that _demojibake would repair)
    never wins when a clean alternative exists in the group. Identical to
    counter.most_common(1)[0][0] when nothing in the group is mojibake.

    Counter keys may be plain strings (single-value axes) or (composer, title)
    tuples (multi-value axes); a tuple is clean only when every element is."""
    if not counter:
        return ""

    def _clean(s):
        if isinstance(s, tuple):
            return all(_demojibake(x) == x for x in s)
        return _demojibake(s) == s

    # (is-clean, count): a clean spelling outranks any mojibake one regardless
    # of count; ties fall back to count, then first-seen (insertion) order.
    return max(counter, key=lambda s: (_clean(s), counter[s]))


def canonical_key(s: str) -> str:
    """Diacritic-folded, lowercase, whitespace/punctuation-normalized key
    suitable for grouping spelling variants. Not for display."""
    if not s:
        return ""
    # Repair mojibake first, BEFORE the ASCII fold — the corrupt bytes must
    # become real accented chars ('FrÃ©dÃ©ric' -> 'Frédéric') so the fold then
    # yields the same key as the clean spelling ('frederic'). Folding first
    # would turn the mojibake into garbage and never match.
    s = _demojibake(s)
    # Fold Unicode hyphens (U+2010 ‐, U+2011 non-breaking) to ASCII '-' so a
    # name written with the typographic hyphen keys the same as the plain one
    # (segments.json uses U+2010; long_synopsis uses '-'). Done before the
    # ascii_fold so the intra-word-hyphen rules below see one consistent dash.
    s = re.sub(r"[‐‑]", "-", s)
    s = ascii_fold(s).lower().strip()
    # Various apostrophes and quotes → straight
    s = re.sub(r"[\u2018\u2019\u201A\u201B'`´]", "'", s)
    s = re.sub(r"[\u201C\u201D\u201E\u201F]", '"', s)
    # Drop a parenthesized or square-bracketed composition/publication year —
    # "(1902)", "(1905-6)", "[1581]", "[1583-1643]". The BBC appends these
    # inconsistently; they're annotation, not work identity. The bracket form
    # is the same noise as the paren form (the line below strips bare '['/']'
    # but leaves the digits, which then fragment the work — e.g. Palestrina's
    # 'Fundamenta ejus … [1581]' split from its year-less twin). Year-only:
    # the bracket must contain nothing but the year/range, so '[15] Improvisations'
    # and '[Hamburg, 1732-3]' are left intact.
    s = re.sub(r"[(\[]\s*\d{4}(?:\s*[-–/]\s*\d{1,4})?\s*[)\]]", " ", s)
    # Drop a parenthesized/bracketed PERFORMANCE marker — "(encore)", "(appl)",
    # "(applause)". These annotate the airing, not the work, and are never part
    # of a real title (merges Clair de lune, Liebestod, … with their unmarked
    # twins). NB: "(excerpt)" is deliberately NOT here — an excerpt IS a distinct
    # musical unit (the catalogue path keys on excerpt locators).
    s = re.sub(r"[(\[]\s*(?:appl(?:ause)?|encore)\s*[)\]]", " ", s)
    # "&" and "and" are interchangeable in BBC titles ("Romeo & Juliet").
    s = s.replace("&", " and ")
    # A space-flanked dash is a separator ("X - Suite No 2" vs "X, Suite
    # No 2") — collapse it. An intra-word hyphen (Rimsky-Korsakov) has no
    # flanking spaces and is left alone. A space-flanked '?' is a BBC
    # transcoding artifact for that separator dash/colon (never a genuine
    # question mark, which attaches: "Quo Vadis?"), so it collapses too.
    s = re.sub(r"\s[-–—?]+\s", " ", s)
    # Drop quote marks setting off a nickname ("'Jupiter'", '"Jupiter"').
    # A double quote is always noise here; an apostrophe is dropped only at
    # a word boundary — inside a word it's part of the name (l'apres-midi,
    # O'Connor, d'Indy).
    s = s.replace('"', "")
    s = re.sub(r"(?<![a-z0-9])'|'(?![a-z0-9])", "", s)
    # Normalize opus and number markers: "Op.5" / "Op 5" / "op.5" → "op 5".
    # "nos" before "no" in the alternation — longest match wins, so "Nos."
    # is not chopped to "no" with an orphaned "s". The (?=\d) guard means
    # the rule fires only when a number actually follows, so ordinary words
    # that merely begin with these letters ("Norwegian", "Opera",
    # "Nocturne") are left intact.
    s = re.sub(r"\b(op|nos|no)\.?\s*(?=\d)", r"\1 ", s)
    # Collapse whitespace and drop minor punctuation noise — parentheses
    # included, so a work written "... (Op.49)" and "..., Op.49" matches.
    s = re.sub(r"[.,;:()\[\]]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Performer parsing
#
# The `performers` column is a comma-separated string written by the BBC:
#   "Vladimir Jurowsky (conductor), Oslo Philharmonic Orchestra, Annie Fischer (piano)"
# Items without parentheses are ensembles (orchestras, choirs, quartets…).
# Items with a parenthesised role of "conductor" or "director" are conductors;
# anything else with a parenthesised role is a soloist's instrument/voice.
#
# Wart: BBC sometimes writes an ensemble with a trailing city — e.g.
# "WDR Symphony Orchestra, Cologne, Conductor (conductor)" — which a naive
# comma-split would turn into a phantom "Cologne" ensemble. We merge bare
# city tokens that match a known suffix list back into the previous bare
# part. Variants where the city is sometimes omitted (e.g. "Akademie für
# Alte Musik" usually bare but occasionally ", Berlin") are not unified
# here — that would want an ensemble alias table, parallel to COMPOSER_ALIASES.
# ---------------------------------------------------------------------------

# A trailing "." after the (role) is tolerated — the BBC sometimes writes
# "... (conductor)." mid-string, which would otherwise leave the role
# unrecognised. (A line-final "." is already handled by parse_performers'
# rstrip; this also covers the mid-string case.)
_PERFORMER_PAREN_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*\.?\s*$")

_ENSEMBLE_CITY_SUFFIXES = {canonical_key(c) for c in (
    "Cologne", "Köln",
    "Berlin", "Dresden", "Munich", "München", "Hamburg",
    "Frankfurt", "Stuttgart", "Leipzig",
    "Vienna", "Wien", "Salzburg",
    "Katowice", "Warsaw", "Krakow", "Kraków",
    "Budapest",
    "Prague", "Bratislava", "Ljubljana", "Zagreb",
    "Paris", "Madrid", "Rome", "Milan",
    "Helsinki", "Stockholm", "Oslo", "Copenhagen", "Bergen",
    "London", "Manchester",
    "Toronto", "Vancouver", "Montreal",
    # Two-word tail: the Deutsche Radio Philharmonie is credited
    # "<name>, Saarbrücken Kaiserslautern" — keep that pair together.
    "Saarbrücken Kaiserslautern",
)}


def parse_performers(s: str):
    """Return (ensembles, conductors) extracted from a performers string."""
    if not s:
        return [], []
    s = s.rstrip(". ").strip()
    raw_parts = [p.strip() for p in s.split(",") if p.strip()]

    # Merge "<ensemble>, <city>" pairs back together so the city doesn't
    # become a phantom ensemble.
    merged = []
    for part in raw_parts:
        if (merged
                and "(" not in part
                and "(" not in merged[-1]
                and canonical_key(part) in _ENSEMBLE_CITY_SUFFIXES):
            merged[-1] = f"{merged[-1]}, {part}"
        else:
            merged.append(part)

    ensembles, conductors = [], []
    for part in merged:
        m = _PERFORMER_PAREN_RE.match(part)
        if m:
            name, role = m.group(1).strip(), m.group(2).strip().lower()
            if "conductor" in role or "director" in role:
                if name:
                    conductors.append(name)
        else:
            ensembles.append(part)
    return ensembles, conductors


# COMPOSER_ALIASES is built from _COMPOSER_ALIAS_PAIRS (now in ttn_aliases.py),
# keyed on canonical_key(name) so capitalisation, diacritics and punctuation
# in the table don't matter.
def _build_alias_table():
    table = {}
    for variant, preferred in _COMPOSER_ALIAS_PAIRS:
        table[canonical_key(variant)] = canonical_key(preferred)
    return table


COMPOSER_ALIASES = _build_alias_table()


def resolve_composer_alias(canon_key: str) -> str:
    """Apply the alias table once. Returns the canonical key after resolution."""
    return COMPOSER_ALIASES.get(canon_key, canon_key)


# Curated display preferences, keyed by a group's resolved canonical key. When
# present, this label is shown instead of the most-common-original default.
# Each _COMPOSER_DISPLAY_PREFERENCES entry is either a plain string (the label
# IS a real spelling of the group, so it anchors and displays itself — the
# majority-is-the-error case) or an (anchor, label) tuple (the label is a
# synthetic display string that does NOT canonicalize to the group key, e.g.
# "Pau (Pablo) Casals"; the anchor is a real spelling used to locate the group).
# See the table and its rationale in ttn_aliases.py.
def _build_composer_display_override():
    table = {}
    for entry in _COMPOSER_DISPLAY_PREFERENCES:
        anchor, label = entry if isinstance(entry, tuple) else (entry, entry)
        table[canonical_key(anchor)] = label
    return table


COMPOSER_DISPLAY_OVERRIDE = _build_composer_display_override()


def override_composer_display(key, by, default):
    """Return the curated display spelling for a group if one exists, else
    `default` (the most-common-original pick). On the work/piece axes the
    override replaces only the composer component of the (composer, title)
    display tuple; the title is left untouched."""
    if by == "composer":
        return COMPOSER_DISPLAY_OVERRIDE.get(key, default)
    if (by in ("work", "piece") and isinstance(key, tuple)
            and isinstance(default, tuple)):
        pref = COMPOSER_DISPLAY_OVERRIDE.get(key[0])
        if pref is not None:
            return (pref,) + default[1:]
    return default


# ENSEMBLE_ALIASES is built from _ENSEMBLE_ALIAS_PAIRS (now in ttn_aliases.py);
# it handles the bare-vs-city-suffixed case (e.g. "WDR Symphony Orchestra" vs
# "… Orchestra, Cologne") that parse_performers' merger can't fix alone.
def _build_ensemble_alias_table():
    table = {}
    for variant, preferred in _ENSEMBLE_ALIAS_PAIRS:
        table[canonical_key(variant)] = canonical_key(preferred)
    return table


ENSEMBLE_ALIASES = _build_ensemble_alias_table()


def resolve_ensemble_alias(canon_key: str) -> str:
    return ENSEMBLE_ALIASES.get(canon_key, canon_key)


# ---------------------------------------------------------------------------
# Work-title key + work aliases.
#
# canonical_key folds punctuation, opus markers, quotes and "(year)" noise.
# work_title_key goes one step further and SORTS the title's tokens, which
# collapses the BBC's pervasive word-order churn for free: it freely moves
# key, opus and catalogue number around —
#   "Egmont Overture, Op 84"      ~  "Overture (Egmont, Op 84)"
#   "Concerto in F major, RV.442" ~  "Concerto in F major (RV.442)"
# all become the same sorted-token key. (Order-insensitivity can in
# principle merge two different works with the same word multiset; an
# audit of the 10-year DB found no such collision — real titles differ by
# number/key/movement words, which survive the sort.)
#
# WORK_ALIASES is the hand-curated remainder, parallel to COMPOSER_ALIASES:
# rephrasings that change the *words*, which a token sort can't reach —
# an added/dropped "Overture"/"to"/"from"/article, a cross-language "and"
# (et / i / und), a translated or alternate title. Each pair is
# (alternate_form, preferred_form), matched on work_title_key, so
# punctuation/case/word-order within this table don't matter.
# ---------------------------------------------------------------------------

# Composer-specific thematic-catalogue prefixes. A catalogue number (RV.444,
# BWV 1012, K.515, D.958…) pins down a work far more reliably than its
# descriptive title, which the BBC rewords endlessly. Op is deliberately
# absent — opus word-order churn is already handled by the token sort, and an
# opus can cover a multi-piece set. Single-letter K (Mozart/Köchel) and D
# (Schubert/Deutsch) require digits right after, so "in D major" is safe.
# The designator may carry a compound "group:key+number" tail (Telemann
# TWV 55:D1, Hoboken Hob XVI:37). Single-letter K/D must not match after a
# colon, or "TWV 55:D1" would yield a phantom Deutsch "D1".
_CATALOGUE_RE = re.compile(
    r"\b((?:bwv|hwv|buxwv|twv|woo|rv|kv|hob|wq|mwv|sz)|(?<!:)[kd])"
    r"\.?\s*:?\s*([ivxlc]*\.?\s*:?\s*\d+[a-z]?(?:\s*:\s*[a-z]{0,3}\d+)?)",
    re.IGNORECASE)


def _catalogue_refs(title: str) -> set:
    """All thematic-catalogue references in a title, normalized (e.g.
    {'rv444'}). 'KV' folds to 'K'; leading zeros are dropped."""
    out = set()
    for m in _CATALOGUE_RE.finditer(title):
        prefix = m.group(1).lower()
        if prefix == "kv":
            prefix = "k"
        designator = re.sub(r"[^a-z0-9]", "", m.group(2).lower())
        designator = re.sub(r"^0+(\d)", r"\1", designator)
        out.add(prefix + designator)
    return out


def catalogue_ref(title: str) -> str:
    """The primary thematic-catalogue reference in a title (e.g. 'rv444',
    'bwv1012', 'd899'), or '' if none. Deterministic when several appear."""
    refs = _catalogue_refs(title)
    return min(refs) if refs else ""


_PARENT_WORK_PAREN_RE = re.compile(r"\(([^()]+)\)")
_ORDERING_MARKER_RE = re.compile(r"\b(?:no|op|nos)\.?\s*\d+\b", re.IGNORECASE)
# Words a parent-work parenthetical's residue may contain WITHOUT signalling
# a parent reference. "and"/"or" appear in multi-catalogue-ref listings
# ("(BWV.478, 484, 492 and 502)"); articles/preps slip past the residue
# strip but don't name a parent.
_PAREN_RESIDUE_STOPWORDS = frozenset((
    "and", "or", "the", "a", "an", "of", "for", "in",
))


def _has_parent_work_reference(title: str) -> bool:
    """True if the title carries a parenthetical naming a parent work via
    its catalogue ref — e.g. "Piangerò la sorte mia (Giulio Cesare,
    HWV 17)", "Chaconne (Almira, HWV 1)", "Jesu, joy of man's desiring
    (Cantata BWV 147)". Pattern: a parenthetical containing both a
    thematic-catalogue ref AND a name-like word (multi-letter alphabetic
    remnant after stripping the ref, any "No N" / "Op N" ordering, bare
    digit listings, and common stopwords).

    Signals that the title is an excerpt of the parent work named in the
    parens — so it must NOT take the catalogue path's whole-vocal-work
    branch, which would key it identically to the parent. Catalogue-path
    cases that fire via the form-word gate (Concerto, Suite, Sonata, …)
    aren't consulted: the form-word gate covers them independently.

    The stopword filter keeps multi-catalogue-ref listings off the
    parent-ref classification: "(BWV.478, 484, 492 and 502)" reduces to
    just "and" once bare digits and the first matched ref are stripped.
    Annotation-style parentheticals where the parent IS the title (e.g.
    "Christ lag in Todesbanden (Cantata BWV 4)", where Christ lag IS
    BWV 4) remain a known false positive — semantically ambiguous from
    the title alone."""
    for paren_content in _PARENT_WORK_PAREN_RE.findall(title):
        if not _CATALOGUE_RE.search(paren_content):
            continue
        residue = _CATALOGUE_RE.sub("", paren_content)
        residue = _ORDERING_MARKER_RE.sub("", residue)
        residue = re.sub(r"\d+", "", residue)
        words = re.findall(r"[A-Za-z]{2,}", residue)
        if any(w.lower() not in _PAREN_RESIDUE_STOPWORDS for w in words):
            return True
    return False


def _key_signatures(canon: str) -> set:
    """Key signatures named in a canonical_key string, e.g. {'gflat'}.
    'major' is dropped — a bare note is major by convention, so "in G" and
    "in G major" agree — while 'minor' is kept. Used to keep set-catalogue
    siblings (the four D.899 impromptus, in different keys but one Deutsch
    number) from collapsing together."""
    out = set()
    for m in re.finditer(
            r"\bin ([a-g])(?: (flat|sharp))?(?: (major|minor))?\b", canon):
        mode = "minor" if m.group(3) == "minor" else ""
        out.add(m.group(1) + (m.group(2) or "") + mode)
    for m in re.finditer(
            r"\b([a-g])(?: (flat|sharp))? (major|minor)\b", canon):
        mode = "minor" if m.group(3) == "minor" else ""
        out.add(m.group(1) + (m.group(2) or "") + mode)
    return out


# Instrumental / standalone work-type words. The catalogue rule (which drops
# descriptive wording) only fires when one is present — because a catalogue
# number identifies a single work for these forms, whereas for an opera,
# oratorio, cantata or song cycle ONE catalogue number spans every aria and
# song. Gating on these terms keeps "Overture to Figaro, K.492" mergeable
# while leaving "'Dove sono', aria from Figaro, K.492" on the token sort.
_STANDALONE_WORK_TERMS = frozenset((
    "concerto", "concertino", "sinfonia", "sinfonietta", "symphony",
    "symphonie", "sonata", "sonatina", "quartet", "quintet", "sextet",
    "septet", "octet", "nonet", "trio", "partita", "suite", "divertimento",
    "serenade", "cassation", "fantasia", "fantasie", "fantasy", "variations",
    "rondo", "rondeau", "capriccio", "scherzo", "ballade", "impromptu",
    "prelude", "preludes", "fugue", "toccata", "nocturne", "notturno",
    "intermezzo", "rhapsody", "overture", "march", "waltz", "polonaise",
    "mazurka", "dance", "dances", "etude", "study",
))


# Form-family synonyms for the --form filter. Each entry maps a canonical
# form name (used as the CLI argument) to a tuple of word-boundary terms
# that all denote the same compositional form across languages or
# orthographic variants (cross-language same-form folding).
#
# Sibling diminutives (sonatina, concertino, sinfonietta) and sibling
# parents (sinfonia ≢ symphony) are intentionally NOT folded — they are
# distinct compositional forms. Each gets its own one-entry mapping so
# `--form` is a discoverable alternative to `--title` for the whole
# standalone-form vocabulary.
_FORM_SYNONYMS = {
    # Cross-language / orthographic folds
    "symphony":     ("symphony", "symphonie"),
    "overture":     ("overture", "ouverture"),
    "prelude":      ("prelude", "prélude", "preludes"),
    "fantasia":     ("fantasia", "fantasie", "fantasy"),
    "nocturne":     ("nocturne", "notturno"),
    "rondo":        ("rondo", "rondeau"),
    "waltz":        ("waltz", "valse"),
    "march":        ("march", "marche"),
    "etude":        ("etude", "étude", "etudes", "études", "study", "studies"),
    "dance":        ("dance", "dances"),
    # Single-entry forms (no cross-language equivalent in the corpus)
    "concerto":     ("concerto",),
    "concertino":   ("concertino",),
    "sonata":       ("sonata",),
    "sonatina":     ("sonatina",),
    "sinfonia":     ("sinfonia",),
    "sinfonietta":  ("sinfonietta",),
    "partita":      ("partita",),
    "suite":        ("suite",),
    "quartet":      ("quartet",),
    "quintet":      ("quintet",),
    "sextet":       ("sextet",),
    "septet":       ("septet",),
    "octet":        ("octet",),
    "nonet":        ("nonet",),
    "trio":         ("trio",),
    "scherzo":      ("scherzo",),
    "capriccio":    ("capriccio",),
    "ballade":      ("ballade",),
    "impromptu":    ("impromptu",),
    "fugue":        ("fugue",),
    "toccata":      ("toccata",),
    "intermezzo":   ("intermezzo",),
    "rhapsody":     ("rhapsody",),
    "polonaise":    ("polonaise",),
    "mazurka":      ("mazurka",),
    "divertimento": ("divertimento",),
    "serenade":     ("serenade",),
    "variations":   ("variations",),
    "cassation":    ("cassation",),
}


# Catalogue numbers that are CONTAINERS for many independently-titled works
# — song cycles and song sets. Each song has its own identity (and usually a
# sub-indexed number), but the BBC sometimes lists one by bare title plus the
# cycle's number. The vocal catalogue rule must stay off these, or e.g.
# "Ständchen, D.957" would fuse into "Schwanengesang, D.957".
_CYCLE_CATALOGUE_REFS = frozenset((
    "d957",   # Schubert — Schwanengesang
    "d911",   # Schubert — Winterreise
    "d795",   # Schubert — Die schöne Müllerin
    "d877",   # Schubert — 4 Gesänge aus Wilhelm Meister
))

# Words marking a title as an EXCERPT of a larger catalogued vocal work (an
# aria, recitative, act, scene…). When present, the catalogue rule stays off
# so the excerpt is not fused with its parent or its siblings. Deliberately
# broad: a false positive merely costs a missed merge, whereas a miss would
# fuse distinct excerpts that share a container catalogue number.
#
# 'duet' is NOT a member: in practice it is overwhelmingly used as a SCORING
# word ("for piano duet", "Duet for viola and cello") rather than an opera
# excerpt locator. Genuine operatic duet excerpts ("Duet from Don Giovanni")
# are caught by 'from'; Italian operatic forms (duetto/duettino) are still
# caught by `duett\w*`.
_EXCERPT_LOCATOR_RE = re.compile(
    r"\b(from|aria|arias|arioso|recit|recitativ\w*|cavatina|duett\w*|"
    r"chorus|act|scene|part|excerpt\w*|interlude|prologue|movement\w*)\b")

# Explicit arrangement markers. A title that declares itself an arrangement
# ("arr. for X", "transcribed for X", "orchestrated by X", "orig. for X")
# folds into the original work on work_title_key's token-sort path, mirroring
# how the catalogue path already drops arrangement wording. Bare
# "for <scoring>" is NOT a marker (it can be a work's original scoring, e.g.
# "Concerto for Orchestra"). Word boundaries keep "orig" off "Original Rags"
# and "orchestrated" off "orchestra".
_ARR_TAIL_RE = re.compile(
    r"[\s,(]*\b(?:arrangement|arranged|arr|transcription|transcribed|transcr?|"
    r"orchestrated|orchestration|originally|orig)\b[^:;]*", re.IGNORECASE)


def _strip_arrangement_tail(title: str) -> str:
    """Remove an explicit-arrangement clause from a title, up to the next
    movement boundary (':' / ';') or end. Returns the title unchanged if
    stripping would empty it (a title that is only an arrangement clause,
    e.g. one beginning 'Arrangement of …')."""
    stripped = _ARR_TAIL_RE.sub("", title).strip(" ,(-")
    return stripped or title


def _squash_separators(canon: str) -> str:
    """Fold hyphen-vs-space and apostrophe placement — variation carrying no
    work-distinguishing information ("l'apres-midi" == "l'apres midi"). Runs
    on canonical_key output, which has straightened apostrophes and dropped
    boundary ones; this strips the remaining (word-internal) apostrophes and
    turns hyphens into spaces — so "Soldier's" (internal ') folds with
    "Soldiers'" (trailing ', already dropped upstream). Touches only "-" and
    "'", never digits/note-letters/major-minor, so it can never merge works
    differing by number or key."""
    return canon.replace("-", " ").replace("'", "")


_IMPLICIT_MAJOR_RE = re.compile(r"\b(in [a-g](?: (?:flat|sharp))?) major\b")


def _drop_implicit_major(canon: str) -> str:
    """Drop ' major' immediately after a key-signature pattern ('in <note>'
    or 'in <note> flat/sharp'). A bare note is major by convention, so
    "Symphony in F" and "Symphony in F major" name the same key — the BBC
    alternates between the two phrasings for the same work. Mirror of the
    catalogue path's `_key_signatures`, which already drops 'major'; this
    extends the same convention to the token-sort path. 'Minor' is never
    dropped (no implicit-minor convention exists)."""
    return _IMPLICIT_MAJOR_RE.sub(r"\1", canon)


# Movement / tempo / dance names. A title LEADING with one of these and
# naming a parent work ("… from <Work>"), or carrying an explicit "Nth
# movement"/"mvt"/"excerpt" marker, is an instrumental movement excerpt —
# keyed §ref|slug so it stays distinct from the whole work while its
# phrasings collapse.
_MOVEMENT_NAMES = (
    "adagio|adagietto|allegro|allegra|allegretto|andante|andantino|largo|"
    "larghetto|lento|presto|prestissimo|vivace|moderato|grave|"
    "menuett?o?|minuet|scherzo|finale|gavotte|sarabande|sarabanda|gigue|courante|"
    "allemande|bourrees?|sicilian[oa]|romanze|romance|air|rondeau|rondo|loure|"
    "passepied|musette|prelude|preludio|fugue|aria|chaconne|giga|capriccio|"
    "intermezzo|nocturne|badinerie|fantasi[ae]")

_MOVEMENT_LEAD_RE = re.compile(
    r"^\W*(" + _MOVEMENT_NAMES + r")\b[^,]*,?[\s(]+from\b", re.I)
_MOVEMENT_NAME_RE = re.compile(r"\b(" + _MOVEMENT_NAMES + r")\b", re.I)
_MOVEMENT_ORD_RE = re.compile(
    r"\b(\d+)\s*(?:st|nd|rd|th)\s+(?:movement|mvt)\b|\bmovement\s*(\d+)\b",
    re.I)
_MOVEMENT_MARK_RE = re.compile(
    r"\b\d+\s*(?:st|nd|rd|th)\s+(?:movement|mvt)\b|\bmvt\b"
    r"|\bexcerpt\w*|\bextract\w*|^\W*finale\b\s*[-–.:]", re.I)

# Movement-name spelling / synonym folds for the slug.
_SLUG_NORM = {"siciliano": "siciliana", "aria": "air",
              "menuet": "menuetto", "menuett": "menuetto", "giga": "gigue",
              "sarabanda": "sarabande", "preludio": "prelude",
              "allegra": "allegro", "fantasie": "fantasia",
              "bourrees": "bourree"}


def _movement_slug(title):
    """A normalized movement marker for an instrumental movement excerpt, or
    None if the title is not an excerpt. The slug is the sorted set of
    movement-name tokens; failing that a movement ordinal; failing that
    'excerpt' for a bare '(excerpt)'/'(extract)' title. Detection requires a
    leading movement name + 'from', or an explicit mvt/excerpt marker — so a
    whole work named after a tempo (Adagio and Fugue, K.546) returns None."""
    # Match on the ascii-folded title so accented movement names (Prélude,
    # Bourrées) are recognized; fold once and use `t` throughout so the
    # catalogue-ref-before-from guard's positions stay internally consistent.
    t = ascii_fold(title)
    if not (_MOVEMENT_LEAD_RE.search(t) or _MOVEMENT_MARK_RE.search(t)):
        return None
    # A catalogue ref BEFORE the first "from" means the title carries its own
    # work number — it is a whole work (e.g. "Prelude and fugue No.5 in D
    # major (BWV.874) from Das Wohltemperierte Klavier", where "from" names
    # the collection, not a parent), not a movement excerpt.
    fm = re.search(r"\bfrom\b", t, re.I)
    if fm and _catalogue_refs(t[:fm.start()]):
        return None
    # Slug from the excerpt designation (before "from"), not the parent work
    # name after it — else a parent named after movements ("Fantasia & Fugue")
    # would leak its words into the excerpt's slug.
    scope = t[:fm.start()] if fm else t
    names = sorted({_SLUG_NORM.get(m, m)
                    for m in (g.lower()
                              for g in _MOVEMENT_NAME_RE.findall(scope))})
    if names:
        return ",".join(names)
    o = _MOVEMENT_ORD_RE.search(t)
    if o:
        return o.group(1) or o.group(2)
    return "excerpt"


# --- scoring-phrase normalization (token-sort path) -----------------------
# The BBC writes one work two ways: "<Instrument> Sonata" and "Sonata for
# <instrument> and piano" (likewise Concerto / "and orchestra"). On the
# token-sort path these don't fold (the extra for/and/piano tokens differ).
# _normalize_scoring rewrites a recognized "for <solo> [and <accompaniment>]"
# phrase down to just <solo>, so the two phrasings produce identical token
# sets. It fires ONLY on a fully-recognized solo[+accompaniment] shape — any
# unknown scoring is left untouched, so it can never cause a false merge. The
# Op/number/key tokens it never touches keep distinct works apart. The
# catalogue path does not use this (it already drops all scoring wording).
_SCORING_SOLO = frozenset({
    "violin", "cello", "viola", "viola da gamba", "flute", "oboe", "clarinet",
    "bassoon", "horn", "trumpet", "harp", "mandolin", "organ", "guitar",
    "recorder", "double bass", "arpeggione", "piano", "harpsichord",
    "fortepiano", "keyboard",
})
_SONATA_ACCOMP = frozenset({
    "piano", "fortepiano", "harpsichord", "keyboard", "continuo",
    "basso continuo", "bc",
})
_CONCERTO_ACCOMP = frozenset({
    "orchestra", "strings", "string orchestra", "chamber orchestra",
})
# Chamber forms (Quintet/Quartet/Trio/…) phrased "for <solo> and strings" fold
# to "<solo> <Form>" the same way. The accompaniment is restricted to a STRING
# ENSEMBLE: excluding piano/keyboard is what keeps a keyboard reduction
# ("Quintet for clarinet and piano") split from the strings version for free,
# honouring the alt-scoring policy.
_CHAMBER_FORMS = frozenset({
    "quintet", "quartet", "trio", "sextet", "septet", "octet", "nonet",
})
_CHAMBER_ACCOMP = frozenset({
    "strings", "string quartet", "string trio",
})
# The ensemble-only chamber shape "<Form> for strings" -> "String <Form>" (and
# Wind/…). The for-phrase carries the plural ensemble NOUN; the bare target the
# singular ADJECTIVE, so this is a singularization MAP, not a passthrough set.
# Chamber forms ONLY (see the `chamber` gate below): "Concerto for strings" is
# itself canonical — there is no "String Concerto". A name-led work
# ("Three Shanties for wind quintet") is left untouched because its captured
# phrase is "wind quintet", not a bare ensemble key here.
_ENSEMBLE_SCORING = {
    "strings": "string", "string": "string",
    "wind": "wind", "winds": "wind", "wind instruments": "wind",
}
# every single word that may appear inside a scoring phrase (multi-word
# instruments split into their words), for the maximal-run capture below.
_SCORING_WORDS = {w for phrase in (_SCORING_SOLO | _SONATA_ACCOMP
                                   | _CONCERTO_ACCOMP | _CHAMBER_ACCOMP
                                   | _ENSEMBLE_SCORING.keys())
                  for w in phrase.split()} | {"and"}
_SCORING_WORD_ALT = "|".join(sorted(_SCORING_WORDS, key=len, reverse=True))
_SCORING_FOR_RE = re.compile(
    r"\bfor ((?:" + _SCORING_WORD_ALT + r")(?: (?:" + _SCORING_WORD_ALT
    + r"))*)\b")


def _normalize_scoring(canon: str) -> str:
    """On the token-sort path, fold a recognized scoring phrase so the BBC's two
    phrasings of one work key alike: 'Sonata for violin and piano' -> 'Violin
    Sonata', 'Quintet for clarinet and strings' -> 'Clarinet Quintet', and
    'Quartet for strings' -> 'String Quartet'. Operates on canonical_key output;
    returns it unchanged when no recognized scoring phrase is present."""
    tokens = canon.split()
    chamber = False
    if "sonata" in tokens:
        accomp = _SONATA_ACCOMP
    elif "concerto" in tokens:
        accomp = _CONCERTO_ACCOMP
    elif not _CHAMBER_FORMS.isdisjoint(tokens):
        accomp = _CHAMBER_ACCOMP
        chamber = True
    else:
        return canon
    m = _SCORING_FOR_RE.search(canon)
    if not m:
        return canon
    tail = canon[m.end():].split()
    if tail and tail[0] in _CHAMBER_FORMS:
        return canon            # name-led: the form word sits INSIDE the scoring
                                # ("Three Shanties for wind quintet"), not leading
    phrase = m.group(1)
    if phrase in _SCORING_SOLO:
        repl = phrase                       # solo form: "for piano", "for flute"
    elif " and " in phrase:
        left, _, right = phrase.partition(" and ")
        repl = left if (left in _SCORING_SOLO and right in accomp) else None
    elif chamber and phrase in _ENSEMBLE_SCORING:
        repl = _ENSEMBLE_SCORING[phrase]    # ensemble form: "for strings"
    else:
        repl = None
    if repl is None:
        return canon                        # unrecognized shape — leave as-is
    out = canon[:m.start()] + repl + canon[m.end():]
    return re.sub(r"\s+", " ", out).strip()


# L = Lesure (Debussy's thematic catalogue) here, NOT Longo (Scarlatti, 50
# tracks). The two catalogues share the identical "L.NNN" string form, so this
# MUST stay scoped to Debussy — a global strip would corrupt Scarlatti's
# Longo-distinguished sonatas. Stripping (rather than keying on) the ref is
# correct here because the bare descriptive title is the dominant, stable form
# and the L-number is the rare fragmenting add-on; dropping it also dissolves
# Lesure's dual numbering (the cello sonata is both L.135 (1977) and L.144
# (1985)) for free.
_LESURE_COMPOSERS = frozenset({"claude debussy"})

# A trailing/parenthetical Lesure number: optional leading comma/paren, "L",
# optional dot, optional single space, digits, optional close paren. "L'..."
# (apostrophe) and "La ..." never match because a digit must follow L.
# Case-sensitive: the catalogue is always capital L.
_LESURE_REF_RE = re.compile(r"\s*[\(,]?\s*\bL\.?\s?\d+\b\s*\)?")


def _strip_lesure_ref(title: str) -> str:
    """Drop a Lesure catalogue number and tidy the punctuation it leaves."""
    out = _LESURE_REF_RE.sub(" ", title)
    out = re.sub(r"\(\s*[,;]?\s*\)", "", out)   # empty parens left behind
    out = re.sub(r"\s*,\s*,", ",", out)         # doubled commas
    out = re.sub(r"\s+", " ", out).strip().strip(",").strip()
    return out


def work_title_key(title: str, composer: str | None = None) -> str:
    """Order-independent canonical key for a work title. Grouping key for
    the --by work rollup; never displayed.

    When a title carries a thematic-catalogue reference, the key is built
    from (catalogue ref, numbers, key signatures) alone — descriptive
    wording is dropped, so the BBC's endless rephrasings of one catalogued
    work all collapse. This fires when:

      - the title names a standalone instrumental form (Concerto, Sonata…),
        for which a catalogue number identifies a single work; or
      - the title names a whole vocal work — no excerpt locator (aria,
        recitative, 'from'…), no parenthetical naming a parent work via
        its own catalogue ref (see `_has_parent_work_reference`), and
        its number is not a song-cycle container.

    Otherwise the title's tokens are simply sorted, collapsing word-order
    churn for free without risking the fusion of distinct excerpts that
    share a container catalogue number."""
    # Repair mojibake FIRST, before any byte-level title manipulation below.
    # In 'PrÃ©lude Ã\xa0 ...' the \xa0 is the 2nd UTF-8 byte of 'à', not a real
    # NBSP — a strip that collapses it (e.g. _strip_lesure_ref) leaves '0xC3
    # 0x20', defeating canonical_key's own _demojibake and fragmenting the work.
    title = _demojibake(title)
    if composer is not None and \
            resolve_composer_alias(canonical_key(composer)) in _LESURE_COMPOSERS:
        title = _strip_lesure_ref(title)
    canon = canonical_key(title)
    tokens = canon.split()
    refs = _catalogue_refs(title)
    if refs:
        has_form_word = not _STANDALONE_WORK_TERMS.isdisjoint(tokens)
        slug = _movement_slug(title) if has_form_word else None
        if slug is not None:
            return f"§{min(refs)}|{slug}"
        vocal_whole = (not has_form_word
                       and not _EXCERPT_LOCATOR_RE.search(canon)
                       and not _has_parent_work_reference(title)
                       and refs.isdisjoint(_CYCLE_CATALOGUE_REFS))
        if has_form_word or vocal_whole:
            nums = ",".join(sorted(set(re.findall(r"\d+", canon))))
            keys = ",".join(sorted(_key_signatures(canon)))
            return f"§{min(refs)}|{nums}|{keys}"
    # token-sort path: fold a declared arrangement of an uncatalogued work
    # into its original (the catalogue path above already folds arrangements).
    canon = canonical_key(_strip_arrangement_tail(title))
    canon = _normalize_scoring(canon)
    canon = _squash_separators(canon)
    canon = _drop_implicit_major(canon)
    return " ".join(sorted(canon.split()))




def _build_work_alias_table():
    table = {}
    for variant, preferred in _WORK_ALIAS_PAIRS:
        table[work_title_key(variant)] = work_title_key(preferred)
    return table


WORK_ALIASES = _build_work_alias_table()


def resolve_work_alias(work_key: str) -> str:
    return WORK_ALIASES.get(work_key, work_key)


def _alias_health(pairs, key_fn, resolve_fn):
    """Health metrics for one alias table: pair count, distinct preferred
    targets, and the chain-free / no-dead invariant counts (expected 0/0)."""
    keys = [(key_fn(a), key_fn(b)) for a, b in pairs]
    return {
        "n": len(pairs),
        "targets": len({resolve_fn(kb) for _, kb in keys}),
        "chained": sum(1 for ka, kb in keys if resolve_fn(ka) != resolve_fn(kb)),
        "dead": sum(1 for ka, kb in keys if ka == kb),
    }


def _project_identity(ep, pos, composer, composer_line, title, projection, rec_meta):
    """The single substitution point shared by the ranking and summary
    projections. Returns (composer, composer_line, title): when (ep, pos) is a
    High-confidence projected track whose recording carries clean segment
    metadata, substitute the recording's (segment_name, segment_name,
    segment_title) — composer_line set to the clean name so strip_arranger_tail
    is a no-op on projected rows. Otherwise pass through unchanged."""
    rp = projection.get((ep, pos))
    if rp is not None and rp in rec_meta:
        seg_name, seg_title = rec_meta[rp]
        return seg_name, seg_name, seg_title
    return composer, composer_line, title


def _project_rows(cursor, projection, rec_meta):
    """Adapt the 7-tuple ranking cursor (title, composer, composer_line,
    performers, bdate, episode_pid, position) to the 5-tuple compute_ranking
    expects, substituting projected rows via _project_identity. Rows not in the
    projection (Medium/Low/unmatched, pre-2012) pass through."""
    for title, composer, composer_line, performers, bdate, ep, pos in cursor:
        composer, composer_line, title = _project_identity(
            ep, pos, composer, composer_line, title, projection, rec_meta)
        yield (title, composer, composer_line, performers, bdate)


def build_rec_meta(conn):
    """recording_pid -> (segment_composer_name, segment_track_title), first
    non-empty title per recording. The clean identity source the projection
    substitutes in; shared by the ranking and summary projection paths."""
    rec_meta = {}
    for rp, cn, tt in conn.execute(
            "SELECT recording_pid, composer_name, track_title FROM segment_events "
            "WHERE recording_pid IS NOT NULL AND track_title IS NOT NULL "
            "AND track_title != ''"):
        rec_meta.setdefault(rp, (cn, tt))
    return rec_meta


def _project_summary_rows(cursor, projection, rec_meta):
    """Adapt a (composer, composer_line, title, episode_pid, position) cursor to
    the (composer, composer_line, title, episode_pid) shape the summary builds
    from, substituting projected rows via _project_identity. The caller strips
    arranger tails afterwards, exactly as the un-projected summary does."""
    for composer, composer_line, title, ep, pos in cursor:
        composer, composer_line, title = _project_identity(
            ep, pos, composer, composer_line, title, projection, rec_meta)
        yield (composer, composer_line, title, ep)


def compute_ranking(rows, *, by, raw=False, sort="airings",
                    min_airings=None, max_airings=None):
    """rows: iterable of (title, composer, composer_line, performers, bdate),
    arranger tails NOT yet stripped (this strips them). Returns
    (ranked, aliases_applied):
      ranked          -- list of group dicts ordered by the active metric (airings, or distinct works under sort="works") descending
      aliases_applied -- int, for the --verbose line
    Each group: {"key": grouping key, "n": int, "display": Counter,
    "dates": list, "performers": list, "n_works": int|None}. "key" is carried
    so callers can apply override_composer_display. n_works is the distinct-work
    count when by == "composer", else None. Pure: no SQL, no printing.
    min_airings/max_airings -- optional closed-interval filter on airing count, applied before the sort."""
    groups = defaultdict(lambda: {"n": 0, "display": Counter(), "dates": [],
                                  "performers": [], "_works": set()})
    aliases_applied = 0
    for title, composer, composer_line, performers, bdate in rows:
        composer = strip_arranger_tail(composer, composer_line)
        entries = []           # (key, display) to record
        work_key = None        # for the composer work-tally
        if by == "composer":
            disp_composer = normalize_composer(composer)
            display = disp_composer
            if raw:
                key = display
                work_key = title.strip()
            else:
                ck = canonical_key(disp_composer)
                resolved = resolve_composer_alias(ck)
                if resolved != ck:
                    aliases_applied += 1
                key = resolved
                work_key = resolve_work_alias(work_title_key(title, composer))
            entries.append((key, display))
        elif by == "piece":
            display = (normalize_composer(composer), title.strip())
            if raw:
                key = display
            else:
                ck_c = canonical_key(display[0])
                resolved_c = resolve_composer_alias(ck_c)
                if resolved_c != ck_c:
                    aliases_applied += 1
                key = (resolved_c, canonical_key(display[1]))
            entries.append((key, display))
        elif by in ("ensemble", "conductor"):
            ensembles, conductors = parse_performers(performers)
            names = ensembles if by == "ensemble" else conductors
            for name in names:
                if raw:
                    key = name
                else:
                    ck = canonical_key(name)
                    if by == "ensemble":
                        resolved = resolve_ensemble_alias(ck)
                        if resolved != ck:
                            aliases_applied += 1
                        ck = resolved
                    key = ck
                if key:
                    entries.append((key, name))
        else:  # work
            display = (normalize_composer(composer), display_work_title(title))
            if raw:
                key = display
            else:
                ck_c = canonical_key(display[0])
                resolved_c = resolve_composer_alias(ck_c)
                if resolved_c != ck_c:
                    aliases_applied += 1
                # Key off the RAW title, not display[1]=normalize_work(title):
                # normalize_work collapses a NBSP that _demojibake needs to
                # repair the 'Ã'+U+00A0 mojibake of 'à' (matches the composer
                # path at ~line 1012 and the summary path).
                wk = work_title_key(title, composer)
                resolved_w = resolve_work_alias(wk)
                if resolved_w != wk:
                    aliases_applied += 1
                key = (resolved_c, resolved_w)
            entries.append((key, display))

        for key, display in entries:
            if not key or (isinstance(key, tuple) and not any(key)):
                continue
            g = groups[key]
            g["key"] = key
            g["n"] += 1
            g["display"][display] += 1
            if bdate:
                g["dates"].append(bdate)
            g["performers"].append(performers or "")
            if by == "composer" and work_key:
                g["_works"].add(work_key)

    for g in groups.values():
        g["n_works"] = len(g["_works"]) if by == "composer" else None
        del g["_works"]
    survivors = [g for g in groups.values()
                 if (min_airings is None or g["n"] >= min_airings)
                 and (max_airings is None or g["n"] <= max_airings)]

    def _disp(g):
        return override_composer_display(
            g["key"], by, _best_spelling(g["display"]))

    def _alpha(g):
        d = _disp(g)
        return tuple(s.lower() for s in d) if isinstance(d, tuple) else (d.lower(),)

    if sort == "works":
        survivors.sort(key=lambda g: (-(g["n_works"] or 0), -g["n"],
                                      _disp(g).lower()))
    elif max_airings is not None:
        # Bounded-above band: count-desc primary, alpha secondary for a
        # deterministic, readable order (also reproduces --once: all n==1,
        # so count is constant and alpha is the only effective key).
        survivors.sort(key=lambda g: (-g["n"], _alpha(g)))
    else:
        survivors.sort(key=lambda g: -g["n"])
    return survivors, aliases_applied


def compute_summary(rows):
    """Compute corpus-wide statistics from a sequence of (composer, title,
    episode_pid) tuples. Returns a dict of named stats. Pure logic — no
    SQL or printing, so it's easily testable."""
    composer_keys = defaultdict(int)        # composer_key -> airing count
    work_keys = defaultdict(int)            # (composer_key, work_key) -> count
    tracks_per_episode = defaultdict(int)   # episode_pid -> track count
    composer_display = {}                   # composer_key -> most-common original
    composer_display_counts = defaultdict(Counter)
    work_display = {}                       # (ck, wk) -> most-common title
    work_display_counts = defaultdict(Counter)

    for composer, title, episode_pid in rows:
        if not composer or not title:
            continue
        ck = resolve_composer_alias(canonical_key(composer))
        wk = resolve_work_alias(work_title_key(title, composer))
        composer_keys[ck] += 1
        work_keys[(ck, wk)] += 1
        tracks_per_episode[episode_pid] += 1
        composer_display_counts[ck][composer] += 1
        work_display_counts[(ck, wk)][title] += 1

    for ck, counter in composer_display_counts.items():
        composer_display[ck] = override_composer_display(
            ck, "composer", _best_spelling(counter))
    for key, counter in work_display_counts.items():
        work_display[key] = _best_spelling(counter)

    # Distribution buckets for composers and works
    def bucket(counts):
        b = {"1": 0, "2-5": 0, "6-10": 0, "11-50": 0, "51-100": 0, "100+": 0}
        for n in counts.values():
            if n == 1:        b["1"] += 1
            elif n <= 5:      b["2-5"] += 1
            elif n <= 10:     b["6-10"] += 1
            elif n <= 50:     b["11-50"] += 1
            elif n <= 100:    b["51-100"] += 1
            else:             b["100+"] += 1
        return b

    track_counts = sorted(tracks_per_episode.values())
    n_eps = len(track_counts)
    median_tpe = track_counts[n_eps // 2] if n_eps else 0
    mean_tpe = sum(track_counts) / n_eps if n_eps else 0

    top_composers = sorted(composer_keys.items(), key=lambda kv: -kv[1])[:10]
    top_works = sorted(work_keys.items(), key=lambda kv: -kv[1])[:10]

    # Composers ranked by distinct works (breadth of repertoire) rather
    # than total airings. Derived from work_keys' (ck, wk) tuples.
    composer_n_works = defaultdict(int)
    for (ck, _wk) in work_keys:
        composer_n_works[ck] += 1
    top_composers_by_works = sorted(
        composer_n_works.items(), key=lambda kv: -kv[1])[:10]

    return {
        "n_distinct_composers": len(composer_keys),
        "n_distinct_works": len(work_keys),
        "tracks_per_episode_median": median_tpe,
        "tracks_per_episode_mean": mean_tpe,
        "composer_buckets": bucket(composer_keys),
        "work_buckets": bucket(work_keys),
        "top_composers": [(composer_display[ck], n) for ck, n in top_composers],
        "top_composers_by_works": [(composer_display[ck], n)
                                    for ck, n in top_composers_by_works],
        "top_works": [(composer_display[ck], work_display[(ck, wk)], n)
                      for (ck, wk), n in top_works],
    }


_SUMMARY_CACHE_FILENAME = "ttn_summary_cache.json"


def _summary_data_fingerprint(rows):
    """sha1 over the (composer, title, episode_pid) rows compute_summary
    consumes. Cheap to compute — runs on the raw SQL output before the
    ~50s canonicalization pass. Order-independent: rows are sorted first."""
    h = hashlib.sha1()
    for row in sorted(rows):
        h.update(repr(row).encode("utf-8"))
    return h.hexdigest()


def _summary_code_fingerprint():
    """sha1 over the bytes of this module AND ttn_aliases.py (the alias tables
    live there now). Editing canonical_key, compute_summary, or any alias table
    invalidates the cache."""
    h = hashlib.sha1()
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        for name in ("ttn_analyze.py", "ttn_aliases.py"):
            with open(os.path.join(here, name), "rb") as fh:
                h.update(fh.read())
    except OSError:
        return ""
    return h.hexdigest()


def _load_summary_cache_file(path):
    """Return the parsed cache payload, or an empty payload on missing /
    unreadable / malformed file. Payload shape:
    {"code_hash": str, "entries": {data_hash: {"generated_at", "stats"}}}."""
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"code_hash": None, "entries": {}}
    if not isinstance(payload, dict) or "entries" not in payload:
        return {"code_hash": None, "entries": {}}
    return payload


def _read_summary_cache(path, data_fp, code_fp):
    """Return the cached stats dict when the code fingerprint matches and
    an entry for this data fingerprint exists; otherwise None. A
    code-fingerprint mismatch implicitly invalidates every slot."""
    payload = _load_summary_cache_file(path)
    if payload.get("code_hash") != code_fp:
        return None
    entry = payload.get("entries", {}).get(data_fp)
    if entry is None:
        return None
    return entry.get("stats")


def _write_summary_cache(path, data_fp, code_fp, stats):
    """Write a new entry for `data_fp` into the multi-slot cache. If the
    file's code_hash mismatches the supplied one, the prior entries are
    dropped (they're stale by construction)."""
    payload = _load_summary_cache_file(path)
    if payload.get("code_hash") != code_fp:
        payload = {"code_hash": code_fp, "entries": {}}
    payload["entries"][data_fp] = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "stats": stats,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def summary_cache_path():
    """Absolute path to the summary cache, beside this module."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        _SUMMARY_CACHE_FILENAME)


def cached(rows, kind, compute_fn, cache_path=None):
    """Self-keyed multi-slot cache shared by every corpus computation. The
    slot key is f"{kind}:{data_fp}", so the summary and audit reports coexist
    in one file. Returns (stats, was_cached). The whole-file code fingerprint
    still invalidates every slot on any edit."""
    if cache_path is None:
        cache_path = summary_cache_path()
    slot = f"{kind}:{_summary_data_fingerprint(rows)}"
    code_fp = _summary_code_fingerprint()
    stats = _read_summary_cache(cache_path, slot, code_fp)
    if stats is not None:
        return stats, True
    stats = compute_fn(rows)
    _write_summary_cache(cache_path, slot, code_fp, stats)
    return stats, False


def summary_for_rows(rows, cache_path=None):
    """Cached compute_summary for an already-prepared row set (arranger tails
    stripped). Returns (stats, was_cached)."""
    return cached(rows, "summary", compute_summary, cache_path)


_BUCKET_ORDER = ("1", "2-5", "6-10", "11-50", "51-100", "100+")


def render_summary(stats, *, projected=False):
    out = []
    out.append(f"Tracks per episode:   {stats['tracks_per_episode_mean']:.1f} mean, "
               f"{stats['tracks_per_episode_median']} median")
    out.append("")
    out.append(f"Distinct composers:   {stats['n_distinct_composers']:,}")
    out.append(f"Distinct works:       {stats['n_distinct_works']:,}  "
               f"(composer × work groups, post-alias)")
    if projected:
        out.append("                      (recording-anchored 2012+; "
                   "text-anchored before)")
    out.append("")
    out.append("Composer airing distribution:")
    for label in _BUCKET_ORDER:
        out.append(f"  {label:>8}× plays: {stats['composer_buckets'][label]:,}")
    out.append("")
    out.append("Work airing distribution:")
    for label in _BUCKET_ORDER:
        out.append(f"  {label:>8}× plays: {stats['work_buckets'][label]:,}")
    out.append("")
    out.append("Top composers by airings:")
    for name, n in stats["top_composers"]:
        out.append(f"  {n:>5,}×  {name}")
    out.append("")
    out.append("Top composers by works:")
    for name, n in stats["top_composers_by_works"]:
        out.append(f"  {n:>5,}   {name}")
    out.append("")
    out.append("Top works by airings:")
    for composer, title, n in stats["top_works"]:
        out.append(f"  {n:>5}×  {composer} — {title}")
    return "\n".join(out)


def _date_arg(s):
    """argparse type for YYYY-MM-DD; returns the canonical ISO string."""
    try:
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date {s!r}; expected YYYY-MM-DD")


def _title_filter_pattern(user_input: str) -> str:
    """Word-boundary regex for the --title filter. The user's substring is
    ASCII-folded (so 'espanola' matches 'española' — diacritic-insensitive,
    mirroring how the column is folded at query time), escaped (so '.' /
    parens / numbers stay literal) and wrapped in \\b…\\b so e.g. 'concerto'
    does not match 'concertino'."""
    return r"\b" + re.escape(ascii_fold(user_input)) + r"\b"


def _form_filter_clauses(form_name):
    """Build a (sql_clause, params) pair for the --form filter. The clause
    is an OR of word-boundary REGEXP predicates over t.title, one per
    synonym. Combinable with --title (caller AND-joins them)."""
    synonyms = _FORM_SYNONYMS[form_name]
    patterns = [_title_filter_pattern(s) for s in synonyms]
    clause = "(" + " OR ".join("ascii_fold(t.title) REGEXP ?" for _ in patterns) + ")"
    return clause, patterns


def _normalize_title_filter(value):
    """Normalize the raw --title argument. Strips surrounding whitespace and
    treats empty/whitespace-only input as None (no filter), since `\\b\\b`
    would match everywhere and a trailing space would match nowhere — both
    surprising. Returns None or a non-empty stripped string."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# ---------------------------------------------------------------------------

def _resolve_mode(args, argv):
    """Return (mode, conflict_message). conflict_message is None unless
    --mode and --summary disagree. Preserves the historical contract: with no
    --mode/--summary, bare invocation (no dash-flags) is summary, else rank."""
    if args.mode and args.summary and args.mode != "summary":
        return None, f"--summary conflicts with --mode {args.mode}"
    mode = args.mode or ("summary" if args.summary else None)
    if mode is None:
        mode = "summary" if not any(a.startswith("-") for a in argv) else "rank"
    return mode, None


def _invalid_modifiers(args, mode, argv):
    """Flag names that `mode` ignores — caller turns a non-empty list into an
    error. Flags whose default value is itself meaningful (--by, --top) are
    detected by literal presence in argv; the rest by non-default value.
    Must be called BEFORE --year expansion and --title normalization."""
    if mode == "rank":
        return []

    def passed(*names):
        return any(n in argv for n in names)

    bad = {
        "--by": passed("--by"),
        "--top": passed("--top"),
        "--composer": args.composer is not None,
        "--title": args.title is not None,
        "--form": args.form is not None,
        "--once": args.once,
        "--dates": args.dates,
        "--csv": args.csv is not None,
        "--raw": args.raw,
        "--sort": passed("--sort"),
        "--min-airings": args.min_airings is not None,
        "--max-airings": args.max_airings is not None,
    }
    return sorted(f for f, on in bad.items() if on)


SPINE_ONLY = {"recording", "performer", "orchestra", "singer", "choir"}
BROADCASTER_AXES = {"broadcaster", "country"}
SEGMENT_CAPABLE = (SPINE_ONLY | BROADCASTER_AXES
                   | {"composer", "work", "conductor", "ensemble"})
# Filters/flags that read the tracks lineage only; rejected on a segment source.
_TRACKS_ONLY_FLAGS = (
    ("title", "--title"), ("form", "--form"), ("dates", "--dates"),
    ("christmas", "--christmas"), ("min_airings", "--min-airings"),
    ("max_airings", "--max-airings"), ("once", "--once"),
)


def _has_segment_rows(conn):
    """True iff the segment_events table exists and holds at least one row."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='segment_events'")
    if cur.fetchone() is None:
        return False
    cur.execute("SELECT 1 FROM segment_events LIMIT 1")
    return cur.fetchone() is not None


def _reject_tracks_only_flags(args, ap):
    """ap.error if a tracks-only filter/flag is combined with a segment source."""
    offenders = [flag for attr, flag in _TRACKS_ONLY_FLAGS if getattr(args, attr, None)]
    if offenders:
        ap.error(f"{', '.join(offenders)} read the tracks lineage only and can't be "
                 f"combined with a segment source (--by {args.by} / --source segments).")


def _resolve_engine(args, conn, ap):
    """Pick 'tracks' | 'spine' | 'broadcasters' | 'bridge' for this (--by, --source);
    enforce the segment-side guards. (Bridge/cross-era added in SP4d-2b Task 2.)"""
    by, source = args.by, args.source
    if args.cross_era:
        if args.by != "recording":
            ap.error("--cross-era is only valid with --by recording")
        engine = "bridge"
        if args.source == "tracks":
            ap.error("--cross-era has no tracks engine; drop --source tracks")
        if not _has_segment_rows(conn):
            ap.error("segment data required for --cross-era, but segment_events is empty. "
                     "Backfill with: uv run ttn_data.py segments")
        _reject_tracks_only_flags(args, ap)
        return engine
    if by in BROADCASTER_AXES:
        engine = "broadcasters"
    elif by in SPINE_ONLY:
        engine = "spine"
    elif by in SEGMENT_CAPABLE and source == "segments":
        engine = "spine"
    elif source == "segments":
        ap.error(f"--by {by} has no segment engine; --source segments is invalid here")
    else:
        return "tracks"
    if source == "tracks":
        ap.error(f"--by {by} has no tracks engine; use --source auto or --source segments")
    if not _has_segment_rows(conn):
        ap.error("segment data required for this --by/--source, but segment_events is "
                 "empty. Backfill with: uv run ttn_data.py segments")
    _reject_tracks_only_flags(args, ap)
    return engine


def _run_segments_ranking(args, conn):
    """Route a segment-native ranking to the spine engine (lazy import avoids the
    ttn_spine -> ttn_analyze circular import). Mirrors ttn_spine.main's dispatch."""
    import ttn_spine as S
    after, before = args.after, args.before
    if args.year:
        after, before = f"{args.year}-01-01", f"{args.year}-12-31"
    ctx = S.build_context(conn)
    recs = S.build_recordings(conn, ctx=ctx, after=after, before=before,
                              composer=args.composer,
                              keep_interstitials=args.keep_interstitials)
    if args.by == "recording":
        print(S.render_recordings(recs, top=args.top)); return
    if args.by == "work":
        works = S.build_works(recs)
        print(S.render_works(works, top=args.top, sort=args.sort)); return
    con = S.build_contributors(conn, ctx=ctx, after=after, before=before,
                               composer=args.composer,
                               keep_interstitials=args.keep_interstitials)
    stats = S.rank_contributors(recs, con, S._ROLE_BY[args.by])
    if args.csv:
        S.write_csv(stats, args.csv); print(f"wrote {len(stats)} rows to {args.csv}"); return
    print(S.render_ranking(stats, by=args.by, top=args.top))


def _run_broadcasters_ranking(args, conn):
    """Route a broadcaster/country ranking to ttn_broadcasters (lazy import:
    ttn_broadcasters imports ttn_analyze). The --by axis carries the level."""
    import ttn_broadcasters as B
    rows = B.load_rows(conn, after=args.after, before=args.before, year=args.year,
                       composer=args.composer, keep_interstitials=args.keep_interstitials)
    level = "country" if args.by == "country" else "broadcaster"
    key = B.country_key if level == "country" else B.broadcaster_key
    stats = B.rank_broadcasters(rows, rank_key=key)
    if args.csv:
        B.write_csv(stats, args.csv, level=level); print(f"Wrote {args.csv}"); return
    bits = [b for b in (args.after and f"{args.after}→", args.before, args.year) if b]
    scope = "".join(str(b) for b in bits) or "all years"
    print(B.render_report(stats, scope_label=scope, top=args.top,
                          composer=args.composer, level=level))
    if not args.keep_interstitials:
        print(f"\n({len(B.INTERSTITIAL_RECORDING_PIDS)} interstitial schedule-fillers "
              f"excluded; --keep-interstitials to include)")


def _run_cross_era_ranking(args, conn):
    """Route --by recording --cross-era to ttn_bridge's by-recording view
    (lazy import). Reads ttn_bridge_decisions.json read-only (writes are staff)."""
    import ttn_bridge as B
    ctx = B.build_context(conn)
    pid_sigs = B.pid_signatures(conn, ctx)
    text_recs = B.text_recordings(conn, ctx)
    result = B.bridge(text_recs, pid_sigs, B.load_decisions())
    print(B.render_by_recording(result, pid_sigs, top=args.top))


def _resolve_source(args, mode, conn):
    """Resolve the effective grouping source for this run, loading the
    projection when 'auto' is in effect. Returns (effective_source,
    projection, rec_meta, warnings).
      * --raw forces 'tracks' (source is inert there).
      * --source tracks groups on the raw long_synopsis, no projection.
      * --source auto (default) recording-anchors composer/work/piece/summary
        via the projection cache; on a missing/stale cache it degrades to
        'tracks' and accrues an end-of-run footer warning. (The SP4a explicit-
        request hard-error is dormant until --source segments lands in SP4d-2.)"""
    if args.raw or args.source == "tracks":
        return "tracks", {}, {}, []
    import ttn_project
    projection, pstatus = ttn_project.load(conn, ttn_project.PROJECTION_PATH)
    if pstatus != "ok":
        return "tracks", {}, {}, [
            f"projection cache {pstatus}: grouped with tracks source, so 2012+ "
            f"recording-anchoring is OFF. Rebuild with `uv run ttn_data.py warm`."]
    return "auto", projection, build_rec_meta(conn), []


def _emit_source_footer(warnings):
    """Print accrued source warnings as an end-of-run footer on stderr, after
    the output so a long ranking can't bury them (mirrors ttn_scrape's
    'Walk summary:' block)."""
    if not warnings:
        return
    print("\n─ Notes ─", file=sys.stderr)
    for w in warnings:
        print(f"  ⚠ {w}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", nargs="?", default="ttn.sqlite",
                    help="Path to the SQLite DB (default: ttn.sqlite)")
    ap.add_argument("--top", type=int, default=30,
                    help="How many rows to show on stdout (default: 30)")
    ap.add_argument("--by",
                    choices=["piece", "work", "composer", "ensemble", "conductor",
                             "recording", "performer", "orchestra", "singer", "choir",
                             "broadcaster", "country"],
                    default="work",
                    help="Rollup level (default: work). recording/performer/orchestra/"
                         "singer/choir are segment-native (2012+, --source segments). "
                         "broadcaster/country rank EBU source broadcasters "
                         "(segment-native).")
    ap.add_argument("--composer", default=None,
                    help="Restrict to tracks whose composer contains this "
                         "string (case-insensitive)")
    ap.add_argument("--title", default=None,
                    help="Restrict to tracks whose title contains this "
                         "string as a whole word (case-insensitive, "
                         "word-boundary match — '--title concerto' does "
                         "NOT match 'concertino'). Combinable with --composer.")
    ap.add_argument("--form", default=None, choices=sorted(_FORM_SYNONYMS),
                    help="Restrict to tracks whose title names this "
                         "compositional form, including cross-language "
                         "synonyms (e.g. '--form symphony' matches "
                         "Symphony and Symphonie; '--form prelude' also "
                         "matches Prélude and Preludes). Sibling "
                         "diminutives stay separate ('--form concerto' "
                         "does NOT match Concertino). Combinable with "
                         "--composer and --title.")
    ap.add_argument("--csv", default=None,
                    help="Write the full ranking to this CSV file")
    ap.add_argument("--raw", action="store_true",
                    help="Disable canonicalization (group by exact strings, "
                         "so 'Antonin Dvorak' and 'Antonín Dvořák' count "
                         "separately). Default: canonicalized.")
    ap.add_argument("--after", type=_date_arg, default=None, metavar="YYYY-MM-DD",
                    help="Only count broadcasts on or after this date (inclusive)")
    ap.add_argument("--before", type=_date_arg, default=None, metavar="YYYY-MM-DD",
                    help="Only count broadcasts on or before this date (inclusive)")
    ap.add_argument("--year", type=int, default=None, metavar="YYYY",
                    help="Shortcut for --after YYYY-01-01 --before YYYY-12-31")
    ap.add_argument("--christmas", action="store_true",
                    help="Restrict to Dec 25 broadcasts of any year "
                         "(TTN's Christmas-morning programmes)")
    ap.add_argument("--dates", action="store_true",
                    help="Show the individual broadcast dates of each work "
                         "(inline in stdout, extra 'dates' column in CSV)")
    ap.add_argument("--once", action="store_true",
                    help="Restrict to one-off entries (count == 1). Under "
                         "--by piece/work, the performer line is shown inline "
                         "since there's exactly one. Results are sorted "
                         "alphabetically since all counts are equal.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Show audit info: per-row spelling-variant counts "
                         "and the count of composer aliases resolved")
    ap.add_argument("--mode", choices=["rank", "summary"], default=None,
                    help="Output mode: rank (the ranking table) or summary "
                         "(corpus stats). Default: summary when no other flags "
                         "are given, else rank. --summary is an alias for "
                         "--mode summary.")
    ap.add_argument("--sort", choices=["airings", "works", "recordings"],
                    default="airings",
                    help="Ranking metric: airings (default); works (distinct works, "
                         "--by composer); recordings (distinct recordings, segment "
                         "work/role axes).")
    ap.add_argument("--source", choices=["tracks", "segments", "auto"], default="auto",
                    help="grouping source. 'auto' (default): recording-anchored "
                         "projection for composer/work/piece, tracks for "
                         "conductor/ensemble, segments for the spine-only axes. "
                         "'tracks': raw long_synopsis. 'segments': segment-native "
                         "spine engine (2012+). --raw is always tracks.")
    ap.add_argument("--keep-interstitials", action="store_true",
                    help="(segment sources) include the 2 Milhaud schedule-filler "
                         "recordings, excluded by default.")
    ap.add_argument("--cross-era", action="store_true",
                    help="(with --by recording) cross-era extended histories via the "
                         "bridge: text-only pre-2012 airings soft-linked to PID recordings.")
    ap.add_argument("--min-airings", type=int, default=None, metavar="N",
                    help="Only show ranking rows aired at least N times.")
    ap.add_argument("--max-airings", type=int, default=None, metavar="N",
                    help="Only show ranking rows aired at most N times "
                         "(--once is shorthand for --max-airings 1).")
    ap.add_argument("--summary", action="store_true",
                    help="Print corpus-wide summary statistics (episodes, "
                         "tracks, distinct composers/works, repertoire "
                         "distribution) and exit. Respects date filters "
                         "(--after/--before/--year/--christmas); ignores "
                         "--composer/--title/--form/--by/--top/--csv.")
    if argv is None:
        argv = sys.argv[1:]
    args = ap.parse_args(argv)

    mode, conflict = _resolve_mode(args, argv)
    if conflict:
        ap.error(conflict)
    bad = _invalid_modifiers(args, mode, argv)
    if bad:
        ap.error(f"--mode {mode} ignores {', '.join(bad)}; "
                 f"remove them or use --mode rank")
    args.mode = mode
    args.summary = (mode == "summary")

    if args.mode == "rank":
        if args.sort == "works" and args.by != "composer":
            ap.error("--sort works requires --by composer")
        if args.sort == "works" and args.dates:
            ap.error("--dates is not supported with --sort works")
        if args.once and (args.min_airings is not None
                          or args.max_airings is not None):
            ap.error("--once cannot be combined with --min-airings/--max-airings")
        for name, val in (("--min-airings", args.min_airings),
                          ("--max-airings", args.max_airings)):
            if val is not None and val < 1:
                ap.error(f"{name} must be >= 1")
        if (args.min_airings is not None and args.max_airings is not None
                and args.min_airings > args.max_airings):
            ap.error("--min-airings must be <= --max-airings")

    if args.year is not None:
        if args.after or args.before:
            ap.error("--year cannot be combined with --after or --before")
        args.after = f"{args.year:04d}-01-01"
        args.before = f"{args.year:04d}-12-31"

    args.title = _normalize_title_filter(args.title)

    conn = sqlite3.connect(args.db)
    conn.create_function(
        "regexp", 2,
        lambda pat, val: 1 if val and re.search(pat, val, re.IGNORECASE) else 0,
    )
    # Diacritic-insensitive text filters: fold the column to ASCII so a query
    # typed in ASCII ('Dvorak', 'espanola') matches the stored accented form
    # ('Dvořák', 'española'), consistent with how grouping already folds.
    conn.create_function(
        "ascii_fold", 1, lambda s: ascii_fold(s) if s is not None else None)
    cur = conn.cursor()

    # Build the date predicate once -- used for both header counts and the
    # main aggregation query.
    date_clauses = []
    date_params = []
    if args.after:
        date_clauses.append("substr(broadcast_date, 1, 10) >= ?")
        date_params.append(args.after)
    if args.before:
        date_clauses.append("substr(broadcast_date, 1, 10) <= ?")
        date_params.append(args.before)
    if args.christmas:
        date_clauses.append("substr(broadcast_date, 6, 5) = '12-25'")
    eps_where = (" WHERE " + " AND ".join(date_clauses)) if date_clauses else ""

    # ---- engine dispatch: segment-native axes route to their engine ----
    # Broadcaster/spine axes bypass the tracks-oriented header block entirely
    # (Episodes/Tracks/Range/Mode is irrelevant for segment-side renders).
    if mode == "rank":
        engine = _resolve_engine(args, conn, ap)
        if engine == "spine":        _run_segments_ranking(args, conn);     return
        if engine == "broadcasters": _run_broadcasters_ranking(args, conn); return
        if engine == "bridge":       _run_cross_era_ranking(args, conn);    return
    # ---- tracks engine: the existing long_synopsis ranking path below ----

    total_eps = cur.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    total_tracks = cur.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    filt_eps = cur.execute(
        f"SELECT COUNT(*) FROM episodes{eps_where}", date_params
    ).fetchone()[0]
    date_min, date_max = cur.execute(
        f"SELECT MIN(broadcast_date), MAX(broadcast_date) FROM episodes{eps_where}",
        date_params
    ).fetchone()

    print(f"Database:  {args.db}")
    if args.after or args.before or args.christmas:
        print(f"Episodes:  {filt_eps:,} (of {total_eps:,} total)")
        if args.christmas:
            print(f"Filter:    Dec 25 broadcasts (any year)")
        if args.year is not None:
            print(f"Filter:    Year {args.year}")
        elif args.after or args.before:
            print(f"Filter:    {args.after or 'beginning'}  →  {args.before or 'present'}")
    else:
        print(f"Episodes:  {total_eps:,}")
        print(f"Tracks:    {total_tracks:,}")
    print(f"Range:     {(date_min or '?')[:10]}  →  {(date_max or '?')[:10]}")
    print(f"Mode:      {'raw (no canonicalization)' if args.raw else 'canonicalized'}")
    print()

    effective_source, projection, rec_meta, source_warnings = _resolve_source(
        args, mode, conn)

    if args.summary:
        if effective_source == "auto":
            sql = ("SELECT t.composer, t.composer_line, t.title, t.episode_pid, "
                   "t.position FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")
        else:
            sql = ("SELECT t.composer, t.composer_line, t.title, t.episode_pid "
                   "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")
        if date_clauses:
            # date_clauses target the episodes table column directly; qualify
            # for the join.
            qualified = [c.replace("broadcast_date", "e.broadcast_date")
                         for c in date_clauses]
            sql += " WHERE " + " AND ".join(qualified)
        # Strip arranger-tail co-credits before keying, exactly as the
        # --by composer ranking does, so an "X, Y (Arranger)" track is
        # attributed to its principal composer X rather than spawning a phantom
        # "X, Y" composer (which would also inflate the distinct-composer count).
        if effective_source == "auto":
            projected = _project_summary_rows(
                cur.execute(sql, date_params), projection, rec_meta)
            rows = [(strip_arranger_tail(c, cl), t, pid)
                    for c, cl, t, pid in projected]
        else:
            rows = [(strip_arranger_tail(composer, composer_line), title, episode_pid)
                    for composer, composer_line, title, episode_pid
                    in cur.execute(sql, date_params).fetchall()]
        stats, _ = summary_for_rows(rows)
        print(render_summary(stats, projected=(effective_source == "auto")))
        _emit_source_footer(source_warnings)
        return

    # ---- tracks engine: the existing long_synopsis ranking path below ----
    # (segment-native paths were dispatched before the header above)

    # Main aggregation query -- joins to episodes so we can pull the date.
    track_clauses = ["t.title IS NOT NULL", "t.title != ''"]
    track_params = []
    if args.composer:
        track_clauses.append("LOWER(ascii_fold(t.composer)) LIKE ?")
        track_params.append(f"%{ascii_fold(args.composer).lower()}%")
    if args.title:
        track_clauses.append("ascii_fold(t.title) REGEXP ?")
        track_params.append(_title_filter_pattern(args.title))
    if args.form:
        form_clause, form_params = _form_filter_clauses(args.form)
        track_clauses.append(form_clause)
        track_params.extend(form_params)
    if args.after:
        track_clauses.append("substr(e.broadcast_date, 1, 10) >= ?")
        track_params.append(args.after)
    if args.before:
        track_clauses.append("substr(e.broadcast_date, 1, 10) <= ?")
        track_params.append(args.before)
    if args.christmas:
        track_clauses.append("substr(e.broadcast_date, 6, 5) = '12-25'")

    base_from = ("FROM tracks t JOIN episodes e ON t.episode_pid = e.pid "
                 "WHERE " + " AND ".join(track_clauses))
    once_display = args.once
    max_airings = 1 if args.once else args.max_airings

    if effective_source == "auto":
        sql_r = ("SELECT t.title, t.composer, t.composer_line, t.performers, "
                 "substr(e.broadcast_date, 1, 10), t.episode_pid, t.position " + base_from)
        row_iter = _project_rows(cur.execute(sql_r, track_params), projection, rec_meta)
    else:
        sql = ("SELECT t.title, t.composer, t.composer_line, t.performers, "
               "substr(e.broadcast_date, 1, 10) " + base_from)
        row_iter = cur.execute(sql, track_params)

    ranked, aliases_applied = compute_ranking(
        row_iter, by=args.by, raw=args.raw,
        sort=args.sort, min_airings=args.min_airings, max_airings=max_airings)

    label = f"top {args.top} by {args.by}"
    if args.sort == "works":
        label += " (distinct works)"
    if once_display:
        label += " (one-offs only)"
    elif args.min_airings is not None and max_airings is not None:
        label += f" (airings {args.min_airings}–{max_airings})"
    elif args.min_airings is not None:
        label += f" (airings ≥{args.min_airings})"
    elif max_airings is not None:
        label += f" (airings ≤{max_airings})"
    if args.composer:
        label += f" (composer~='{args.composer}')"
    if args.title:
        label += f" (title~='{args.title}')"
    # For a composer-scoped work ranking, show the composer's full catalogue
    # size above the (possibly --top-truncated) list. Suppressed when an
    # airing-count filter is active (--once/--min/--max-airings), since then
    # len(ranked) is the filtered subset, not the total broadcast — and the
    # --once branch below already reports its own count.
    airing_filtered = args.min_airings is not None or max_airings is not None
    if args.by == "work" and args.composer and not airing_filtered:
        print(f"Total number of works broadcast: {len(ranked):,}")
    print(label + ":")
    if once_display:
        print(f"  ({len(ranked):,} entries appear exactly once)")
        if effective_source == "auto":
            # The one-off list blends two grouping regimes: 2012+ is recording-
            # anchored (re-airings + BBC rephrasings collapse, so these are true
            # one-offs), but the pre-2012 tail falls back to long_synopsis keys
            # and still carries spelling churn — so a pre-2012 one-off is softer
            # evidence than a post-2012 one. Mirrors the --summary disclosure.
            print("  (recording-anchored 2012+; text-anchored before — the "
                  "pre-2012 tail still carries long_synopsis spelling churn, "
                  "so its one-offs are softer)")
    if args.verbose and not args.raw and aliases_applied:
        alias_kind = {"ensemble": "ensemble",
                      "work": "composer/work"}.get(args.by, "composer")
        print(f"  ({aliases_applied:,} {alias_kind} aliases resolved via lookup table)")
    print()
    metric = (lambda g: g["n_works"]) if args.sort == "works" else (lambda g: g["n"])
    unit = " works" if args.sort == "works" else "×"
    width = len(str(metric(ranked[0]))) if ranked else 1
    show_performer = once_display and args.by in ("piece", "work")
    for i, g in enumerate(ranked[: args.top], 1):
        display = override_composer_display(
            g["key"], args.by, _best_spelling(g["display"]))
        text = " — ".join(p for p in display if p) if isinstance(display, tuple) else display
        # If the group has variants, mark it (verbose only)
        n_variants = len(g["display"])
        marker = (f" ({n_variants} spelling variants)"
                  if args.verbose and n_variants > 1 else "")
        print(f"{i:>3}.  {metric(g):>{width}}{unit}   {text}{marker}")
        if show_performer:
            perf = g["performers"][0] if g["performers"] else ""
            date = g["dates"][0] if g["dates"] else "?"
            if perf:
                print(f"        {date}  ·  {perf}")
            else:
                print(f"        {date}")
        elif args.dates:
            sorted_dates = sorted(g["dates"])
            print(f"        {', '.join(sorted_dates)}")

    if args.csv:
        single_value_by = args.by in ("composer", "ensemble", "conductor")
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if single_value_by:
                header = ["count", args.by, "n_variants"]
            else:
                header = ["count", "composer", "title", "n_variants"]
            if args.dates:
                header.append("dates")
            if show_performer:
                header.append("performers")
            w.writerow(header)
            for g in ranked:
                display = override_composer_display(
                    g["key"], args.by, _best_spelling(g["display"]))
                if single_value_by:
                    row = [metric(g), display, len(g["display"])]
                else:
                    row = [metric(g), *display, len(g["display"])]
                if args.dates:
                    row.append("|".join(sorted(g["dates"])))
                if show_performer:
                    row.append(g["performers"][0] if g["performers"] else "")
                w.writerow(row)
        print(f"\nFull ranking ({len(ranked)} rows) written to {args.csv}",
              file=sys.stderr)

    _emit_source_footer(source_warnings)
    conn.close()


if __name__ == "__main__":
    main()
