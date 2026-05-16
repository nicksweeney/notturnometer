#!/usr/bin/env python3
"""
Analyze the SQLite database produced by ttn_scrape.py to find the recurring
pieces, works, and composers on BBC Radio 3 'Through the Night'.

Five rollup modes:

  --by piece     : exact title (movement-level distinctions kept)
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

Usage:
    python ttn_analyze.py ttn.sqlite
    python ttn_analyze.py ttn.sqlite --by composer --top 50
    python ttn_analyze.py ttn.sqlite --after 2023-01-01 --before 2023-12-31
    python ttn_analyze.py ttn.sqlite --composer Sibelius --dates
    python ttn_analyze.py ttn.sqlite --by work --csv top_works.csv --dates
"""

import argparse
import csv
import datetime as dt
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict

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
    r"Variation[s]?|Theme|Cadenza|Intermezzo|Interlude|Overture|Sinfonia|"
    r"Introduction|Cavatina|Romanza|Romance|Nocturne|Notturno|Berceuse"
)

_movement_patterns = [
    re.compile(r"\s*[:;,\-]\s*(I{1,3}V?|IV|VI{0,3}|IX|X{1,3}V?|XI{1,3}|"
               r"XIV|XV|XVI{0,3}|XIX|XX)\.?\b.*$"),
    re.compile(r"\s*[:;,\-]\s*\d{1,2}\.\s+\S.*$"),
    re.compile(r"\s*\([^)]*\b(?:mvt|movement|movt)\b[^)]*\)\s*$",
               re.IGNORECASE),
    re.compile(rf"\s*[:;,\-]\s*(?:{TEMPO_TERMS})\b.*$", re.IGNORECASE),
    re.compile(rf"\s*[:;,\-]\s*(?:{FORM_TERMS})\b.*$", re.IGNORECASE),
    re.compile(r"\s*\((?:excerpts?|arr\.?[^)]*|transcr\.?[^)]*|"
               r"orch\.?[^)]*)\)\s*$", re.IGNORECASE),
]


def normalize_work(title: str) -> str:
    if not title:
        return ""
    t = title.strip()
    changed = True
    while changed:
        changed = False
        for pat in _movement_patterns:
            new = pat.sub("", t).strip()
            if new and new != t:
                t = new
                changed = True
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(" :;,-")
    return t


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
})


def ascii_fold(s: str) -> str:
    if not s:
        return ""
    s = s.translate(_EXTRA_FOLD)
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def canonical_key(s: str) -> str:
    """Diacritic-folded, lowercase, whitespace/punctuation-normalized key
    suitable for grouping spelling variants. Not for display."""
    if not s:
        return ""
    s = ascii_fold(s).lower().strip()
    # Various apostrophes and quotes → straight
    s = re.sub(r"[\u2018\u2019\u201A\u201B'`´]", "'", s)
    s = re.sub(r"[\u201C\u201D\u201E\u201F]", '"', s)
    # Drop a parenthesized composition year — "(1902)", "(1905-6)". The BBC
    # appends these inconsistently; they're annotation, not work identity.
    s = re.sub(r"\(\s*\d{4}(?:\s*[-–/]\s*\d{1,4})?\s*\)", " ", s)
    # "&" and "and" are interchangeable in BBC titles ("Romeo & Juliet").
    s = s.replace("&", " and ")
    # A space-flanked dash is a separator ("X - Suite No 2" vs "X, Suite
    # No 2") — collapse it. An intra-word hyphen (Rimsky-Korsakov) has no
    # flanking spaces and is left alone.
    s = re.sub(r"\s[-–—]+\s", " ", s)
    # Drop quote marks setting off a nickname ("'Jupiter'", '"Jupiter"').
    # A double quote is always noise here; an apostrophe is dropped only at
    # a word boundary — inside a word it's part of the name (l'apres-midi,
    # O'Connor, d'Indy).
    s = s.replace('"', "")
    s = re.sub(r"(?<![a-z0-9])'|'(?![a-z0-9])", "", s)
    # Normalize opus and number markers: "Op." / "Op " / "op." → "op ".
    # "nos" before "no" in the alternation — longest match wins, so "Nos."
    # is not chopped to "no" with an orphaned "s".
    s = re.sub(r"\b(op|nos|no)\.?\s*", r"\1 ", s)
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

_PERFORMER_PAREN_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")

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


# ---------------------------------------------------------------------------
# Composer aliases — hand-curated table of name variants that canonical_key
# alone can't unify. Each pair is (alternate_form, preferred_form). The
# matching is done on canonical_key(name), so capitalization, diacritics
# and minor punctuation in this table don't matter.
#
# To extend: just add a tuple. Entries are grouped by category for readability.
# Counts after each comment reflect the 5-year dataset that informed the choice
# of preferred form; the more common BBC spelling is usually preferred.
# ---------------------------------------------------------------------------

_COMPOSER_ALIAS_PAIRS = [
    # --- Older-BBC format variants (pre-~2017 episodes) ---
    # In the 2016 era, BBC included middle names and used German first-name
    # forms that the modern format normalises away. Once the 10-year scrape
    # lands, the analyzer's n_variants column will surface more of these
    # for review.
    ("Edvard Hagerup Grieg",        "Edvard Grieg"),
    ("Georg Frideric Handel",       "George Frideric Handel"),

    # --- Russian transliteration variants ---
    ("Sergei Prokofiev",            "Sergey Prokofiev"),          # 4 → 236
    ("Dmitri Shostakovich",         "Dmitry Shostakovich"),       # 8 → 228
    ("Pyotr Ilyich Tchaikovsky",    "Peter Ilyich Tchaikovsky"),  # 36 → 449
    ("Anatoly Lyadov",              "Anatol Lyadov"),             # 1 → 20
    # Forward-compat: variants not in the 5-year data but likely in older episodes
    ("Sergei Rachmaninov",          "Sergey Rachmaninov"),
    ("Sergei Rachmaninoff",         "Sergey Rachmaninov"),
    ("Sergey Rachmaninoff",         "Sergey Rachmaninov"),
    ("Modeste Moussorgsky",         "Modest Mussorgsky"),
    ("Modest Moussorgsky",          "Modest Mussorgsky"),
    ("Modest Musorgsky",            "Modest Mussorgsky"),
    ("Modest Petrovich Mussorgsky", "Modest Mussorgsky"),         # 34 → 128
    ("Aleksandr Borodin",           "Alexander Borodin"),
    ("Alexander Porfiryevich Borodin", "Alexander Borodin"),
    ("Mikhail Ivanovich Glinka",    "Mikhail Glinka"),
    ("Aram Khachaturyan",           "Aram Khachaturian"),
    ("Aram Khatchaturian",          "Aram Khachaturian"),

    # --- Polish / French rendering of same composer ---
    # Frédéric Chopin: BBC uses "Fryderyk Chopin" consistently (874 plays); forward-compat:
    ("Frederic Chopin",             "Fryderyk Chopin"),
    ("Frédéric Chopin",             "Fryderyk Chopin"),

    # --- German / Hungarian / Latin renderings ---
    ("Christoph Willibald Gluck",   "Christoph Gluck"),           #  8 → 22
    ("Alexander Zemlinsky",         "Alexander von Zemlinsky"),   # 16 → 18  (with "von" is more formal)
    ("Karoly Goldmark",             "Karl Goldmark"),             # 11 → 31
    ("Josef Rheinberger",           "Joseph Rheinberger"),        #  5 → 14
    ("Sebastian Le Camus",          "Sebastien Le Camus"),        #  6 →  7

    # --- Medieval / preposition variants ---
    ("Hildegard von Bingen",        "Hildegard of Bingen"),       # 38 → 71

    # --- Scandinavian language variants ---
    ("Ludwig Norman",               "Ludvig Norman"),             # 15 → 74

    # --- Honorifics, multi-rendering Latinizations etc. ---
    ("Dame Ethel Mary Smyth",       "Ethel Smyth"),               # 25 → 27
    ("Marianne Martines",                              "Marianne Martinez"),
    ("Marianna Martines",                              "Marianne Martinez"),
    ("Marianne von Martinez",                          "Marianne Martinez"),
    ("Marianne Martines or Marianne von Martinez",     "Marianne Martinez"),  # actual BBC string!
    ("Antoine Forqueray ['le pere']",                  "Antoine Forqueray"),
    ("Antoine Forqueray ['le père']",                  "Antoine Forqueray"),
]


def _build_alias_table():
    table = {}
    for variant, preferred in _COMPOSER_ALIAS_PAIRS:
        table[canonical_key(variant)] = canonical_key(preferred)
    return table


COMPOSER_ALIASES = _build_alias_table()


def resolve_composer_alias(canon_key: str) -> str:
    """Apply the alias table once. Returns the canonical key after resolution."""
    return COMPOSER_ALIASES.get(canon_key, canon_key)


# ---------------------------------------------------------------------------
# Ensemble aliases — same pattern as COMPOSER_ALIASES, for cases the
# city-suffix merger in parse_performers can't fix on its own. The merger
# handles the *phantom-city* case (where a comma split turns ", Cologne"
# into its own ensemble). This table handles the *bare-vs-suffixed* case,
# where the BBC alternates between writing the same orchestra with and
# without a city tag — e.g. "WDR Symphony Orchestra" vs "WDR Symphony
# Orchestra, Cologne". Counts shown are 10-year totals at the time of
# tabulation; the direction is cosmetic since display picks the most
# common original spelling regardless.
# ---------------------------------------------------------------------------

_ENSEMBLE_ALIAS_PAIRS = [
    # --- Bare ↔ city-suffixed forms of the same orchestra/chorus ---
    ("WDR Symphony Orchestra",                       "WDR Symphony Orchestra, Cologne"),          #  32 → 223
    ("WDR Radio Orchestra",                          "WDR Radio Orchestra, Cologne"),             #  84 →  91
    ("WDR Radio Chorus",                             "WDR Radio Chorus, Cologne"),                #   4 →  11
    ("RIAS Chamber Chorus",                          "RIAS Chamber Chorus, Berlin"),              #   4 → 115
    ("Hungarian Radio Symphony Orchestra, Budapest", "Hungarian Radio Symphony Orchestra"),       #  91 ← 208
    ("Hungarian Radio Chorus, Budapest",             "Hungarian Radio Chorus"),                   #  48 ↔  44
    ("Camerata Silesia, Katowice",                   "Camerata Silesia"),                         #   8 ←  83
    ("Polish Radio Orchestra, Warsaw",               "Polish Radio Orchestra"),                   #  35 ↔  35
    ("Polish National Radio Symphony Orchestra",     "Polish National Radio Symphony Orchestra, Katowice"),  # 68 → 217

    # --- Word-order variant: same orchestra (NOSPR, Katowice) ---
    ("National Polish Radio Symphony Orchestra",     "Polish National Radio Symphony Orchestra, Katowice"),  # 291 → 217

    # --- No-comma city suffix (the merger handles only the comma form) ---
    ("Slovak Radio Symphony Orchestra Bratislava",   "Slovak Radio Symphony Orchestra"),          #  90 → 567

    # --- German ↔ English name of one orchestra (SR, Saarbrücken) ---
    ("Rundfunk-Sinfonieorchester Saarbrücken",       "Saarbrücken Radio Symphony Orchestra"),     #  19 →  96
]


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
    "serenade", "cassation", "fantasia", "fantasy", "variations", "rondo",
    "rondeau", "capriccio", "scherzo", "ballade", "impromptu", "prelude",
    "preludes", "fugue", "toccata", "nocturne", "notturno", "intermezzo",
    "rhapsody", "overture", "march", "waltz", "polonaise", "mazurka",
    "dance", "dances", "etude", "study",
))


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
_EXCERPT_LOCATOR_RE = re.compile(
    r"\b(from|aria|arias|arioso|recit|recitativ\w*|cavatina|duet|duett\w*|"
    r"chorus|act|scene|part|excerpt\w*|interlude|prologue|movement\w*)\b")


def work_title_key(title: str) -> str:
    """Order-independent canonical key for a work title. Grouping key for
    the --by work rollup; never displayed.

    When a title carries a thematic-catalogue reference, the key is built
    from (catalogue ref, numbers, key signatures) alone — descriptive
    wording is dropped, so the BBC's endless rephrasings of one catalogued
    work all collapse. This fires when:

      - the title names a standalone instrumental form (Concerto, Sonata…),
        for which a catalogue number identifies a single work; or
      - the title names a whole vocal work — no excerpt locator (aria,
        recitative, 'from'…), and its number is not a song-cycle container.

    Otherwise the title's tokens are simply sorted, collapsing word-order
    churn for free without risking the fusion of distinct excerpts that
    share a container catalogue number."""
    canon = canonical_key(title)
    tokens = canon.split()
    refs = _catalogue_refs(title)
    if refs:
        has_form_word = not _STANDALONE_WORK_TERMS.isdisjoint(tokens)
        vocal_whole = (not has_form_word
                       and not _EXCERPT_LOCATOR_RE.search(canon)
                       and refs.isdisjoint(_CYCLE_CATALOGUE_REFS))
        if has_form_word or vocal_whole:
            nums = ",".join(sorted(set(re.findall(r"\d+", canon))))
            keys = ",".join(sorted(_key_signatures(canon)))
            return f"§{min(refs)}|{nums}|{keys}"
    return " ".join(sorted(tokens))


# Each pair is (a real BBC title-variant, the preferred real title). Both
# sides are run through work_title_key, so only the *words* matter here.
_WORK_ALIAS_PAIRS = [
    # --- Verdi: La Forza del Destino — overture ↔ bare opera name ---
    ("La Forza del Destino",                          "Overture to La Forza del destino"),
    ("La forza del destino (Overture)",               "Overture to La Forza del destino"),
    ("Overture from La Forza del Destino",            "Overture to La Forza del destino"),

    # --- Mussorgsky: Pictures at/from an Exhibition (+ arrangement tags) ---
    ("Pictures from an Exhibition",                   "Pictures at an Exhibition"),
    ("Pictures from an exhibition for piano",         "Pictures at an Exhibition"),
    ("Pictures at an Exhibition (orig for piano orch Ravel)", "Pictures at an Exhibition"),

    # --- Mussorgsky: Night on the Bare Mountain (Bald Mountain, ed. R-K) ---
    ("A Night on the bare mountain, ed. Rimsky-Korsakov", "Night on a Bare Mountain"),
    ("A Night on the Bare Mountain",                  "Night on a Bare Mountain"),
    ("A Night on Bare Mountain, symphonic poem",      "Night on a Bare Mountain"),
    ("St John's Night on the Bare Mountain",          "Night on a Bare Mountain"),
    ("Night on Bald Mountain",                        "Night on a Bare Mountain"),

    # --- Glinka: Ruslan and Lyudmila — overture (i ↔ and, to ↔ from) ---
    ("Overture to 'Ruslan and Lyudmila'",             "Ruslan i Lyudmila (overture)"),
    ("Overture from Ruslan i Lyudmila",               "Ruslan i Lyudmila (overture)"),
    ("Overture - from Ruslan & Lyudmila",             "Ruslan i Lyudmila (overture)"),
    ("Ruslan and Lyudmila Overture",                  "Ruslan i Lyudmila (overture)"),
    ("Overture to the opera 'Ruslan i Lyudmila'",     "Ruslan i Lyudmila (overture)"),

    # --- Mendelssohn: The Hebrides / Fingal's Cave overture, Op 26 ---
    ("The Hebrides (Fingal's Cave) - overture, Op 26", "The Hebrides, Op 26"),
    ("The Hebrides (Fingal's Cave)",                  "The Hebrides, Op 26"),
    ("The Hebrides, Op 26 (Fingal's Cave)",           "The Hebrides, Op 26"),
    ("The Hebrides (Fingal's Cave) overture",         "The Hebrides, Op 26"),
    ("Hebrides overture, Op 26",                      "The Hebrides, Op 26"),
    ("The Hebrides Overture, Op 26",                  "The Hebrides, Op 26"),
    ("Hebrides",                                      "The Hebrides, Op 26"),
    ("The Hebrides",                                  "The Hebrides, Op 26"),

    # --- Nicolai / Schumann: overture word-order the token sort can't reach ---
    ("Overture to \"The Merry Wives of Windsor\"",    "Overture, The Merry Wives of Windsor"),
    ("Overture Genoveva Op 81",                       "Overture to Genoveva, Op 81"),

    # --- Ravel: Daphnis et/and/& Chloé — Suite No 2 (cross-language "and") ---
    ("Daphnis et Chloé, Suite no 2",                  "Daphnis & Chloé, Suite No 2"),

    # --- Brahms: Hungarian Dances 17-21, Oslo PO / Aadland — one recording
    #     the BBC airs as a filler, titled with the dances spelled out
    #     vs. given as a range, with or without the "orch. Dvorak" tag.
    #     (The range forms — with and without "orch. Dvorak" — already share
    #     a token-sorted key once "Nos" canonicalises cleanly.)
    ("5 Hungarian Dances (originally for piano duet): Nos. 17 in F sharp minor; "
     "18 in D major; 19 in B minor; 20 in E minor; 21 in E minor",
     "5 Hungarian dances (nos.17-21) orch. Dvorak (orig. pf duet)"),
    ("5 Hungarian Dances: Nos. 17 in F sharp minor; 18 in D major; "
     "19 in B minor; 20 in E minor; 21 in E minor",
     "5 Hungarian dances (nos.17-21) orch. Dvorak (orig. pf duet)"),
    ("5 Hungarian dances (nos.17-21) (orig. pf duet)",
     "5 Hungarian dances (nos.17-21) orch. Dvorak (orig. pf duet)"),

    # --- Liszt: Au lac de Wallenstadt — book named as roman "I" vs. spelled
    #     "première année: Suisse" (S.160 is a 9-piece container, so the
    #     catalogue rule rightly leaves this to the alias table) ---
    ("Au lac de Wallenstadt, from 'Années de pèlerinage: première année: "
     "Suisse S.160'",
     "Au Lac de Wallenstadt from Années de pèlerinage I, S.160"),

    # --- Schubert: one-off re-airings surfaced by the --once + exact-
    #     performer audit. Each is a single recording the BBC aired twice
    #     under different titles. The catalogued ones are songs/dances, so
    #     work_title_key's form-word gate (rightly) leaves them to this
    #     table rather than the catalogue rule.
    ("Le Roi des aulnes for violin solo Op 26",
     "Le Roi des aulnes Op 26"),
    ("Nahe des Geliebten, D.162 (Op 5 no 2) (The Proximity of the Loved One)",
     "Nähe des Geliebten (D.162) (Op.5 No.2)"),
    ("An Mignon from 3 Songs, D.161",
     "An Mignon (D.161), Op.19 No.2 (To Mignon)"),
    ("Erlkönig, D. 328 arr. for violin (encore)",
     "Erlkönig, D. 328 arr. for violin"),
    ("Erlkönig, D328",
     "Erlkönig, D.328, arr. Carpenter for organ"),
    ("6 Deutsche Tanze for piano (D.820)",
     "6 Deutsche for piano (D.820) arr orch"),
    ("Widmung, transcribed for piano, S566",
     "Widmung, transcribed for piano"),
    ("Sehnsucht (D.636 Op.39)",
     "Sehnsucht, D.636"),
    ("Nine songs with orchestra (Romanze (no. 3b), from Rosamunde, D. 797; "
     "Die Forelle, D. 550 orch. Benjamin Britten; Gretchen am Spinnrade, "
     "D. 118 orch. Max Reger); Du bist die Ruh’, D. 776 orch. Anton Webern; "
     "An Silvia, D. 891 orch. Robert Schollum; Nacht und Träume, D. 827 "
     "orch. Max Reger; Im Abendrot, D. 799 orch. Max Reger; Erlkönig, "
     "D.328 orch. Max Reger; An die Musik, D.547 orch. Max Reger.",
     "Nine songs with orchestra [Romanze from Rosamunde, D. 797; "
     "Die Forelle, D. 550 orch. Benjamin Britten; Gretchen am Spinnrade, "
     "D. 118 orch. Max Reger; Du bist die Ruh’, D. 776 orch. Anton Webern; "
     "An Silvia, D. 891 orch. Robert Schollum; Nacht und Träume, D. 827 "
     "orch. Max Reger; Im Abendrot, D. 799 orch. Max Reger; Erlkönig, "
     "D.328 orch. Max Reger; An die Musik, D.547 orch. Max Reger]"),

    # --- Non-Bach one-off re-airings surfaced by the --once + exact-
    #     performer audit: recordings the BBC aired more than once under
    #     different titles. Phrasing the token sort and catalogue rule
    #     can't reach (separator churn, added/dropped form words, apostrophe-
    #     as-No notation, translations, arrangement tags).

    # --- Beethoven: 14 re-aired works ---
    ('2 Sonatinas WoO 43/1 and WoO 44/1',
     '2 Mandolin Sonatinas: C minor WoO 43/1 and C major WoO 44/1'),
    ("8 Variations on Mozart's 'La ci darem la mano' (WoO 28) arranged for oboe and piano 0",
     "8 Variations on Mozart's 'La ci darem la mano' (WoO 28) arranged for oboe and piano"),
    ('Trio in B flat major Op.11 for clarinet (or violin), cello and piano',
     'Clarinet Trio in B flat major, Op 11'),
    ('Duo in E flat major for viola and cello, WoO 32',
     'Duo for viola and cello in E flat major, WoO.32'),
    ('Grosse Fuge, Op 133 (version for orchestra)',
     'Grosse Fuge, Op 133'),
    ('Incidental music to König Stephan (King Stephen) (overture)',
     'Incidental music to "King Stephen"'),
    ('Overture: The Creatures of Prometheus',
     'Overture to The Creatures of Prometheus'),
    ('Piano Sonata (quasi una fantasia) in E flat major, Op.27 No.1',
     "Piano Sonata 'quasi una fantasia' in E flat major Op.27'1"),
    ('Sonata quasi una fantasia in E flat major, Op.27 No.1, for piano',
     "Piano Sonata 'quasi una fantasia' in E flat major Op.27'1"),
    ("Sonata quasi una fantasia in C sharp minor Op.27'2 (Moonlight)",
     'Piano Sonata quasi una fantasia in C sharp minor, Op 27 No 2, (Moonlight)'),
    ('Quartet for strings (Op.18`6) in B flat major',
     'Quartet for strings (Op.18 No 6) in B flat major'),
    ('Violin Sonata in E flat major Op 12`3',
     'Sonata in E flat major Op 12`3 for violin and piano'),
    ('Trio for piano and strings in E flat major Op 1 No 1 (4. Finale (Presto))',
     'Trio for piano and strings in E flat major (Op.1 No.1)'),
    ('Trio for strings in G major, Op.9 No.1',
     "Trio for strings (Op.9'1) in G major"),
    ('Violin Sonata in C minor, Op.30 No.2',
     "Violin Sonata in C minor Op.30'2"),

    # --- Mozart: 15 re-aired works ---
    ("Ch'io mi scordi di te ...? Non temer, amato bene, K 505",
     "'Ch'io mi scordi di te...?', K.505"),
    ('12 Variations for piano, K.500',
     '12 Variations for piano in B flat (K.500)'),
    ('Four Kontra Tänze, KV 267',
     '4 Kontra Tänze, KV 267'),
    ('Rivolgete a lui lo sguardo, K.584',
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),
    ("Aria: Un'aura amorosa - from 'Così fan tutte', K588",
     'Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1'),
    ("Un'aura amorosa (Così fan tutte)",
     'Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1'),
    ('Motet: Ave Verum Corpus (K.618)',
     'Ave verum corpus'),
    ('Der Schauspieldirektor, K.486',
     'Der Schauspieldirektor - singspiel in 1 act (K.486)'),
    ('Eine kleine Nachtmusik, K525',
     'Eine kleine Nachtmusik (Serenade No.13 in G) (K.525)'),
    ('Eine kleine Nachtmusik in G, K.525',
     'Eine kleine Nachtmusik in G, K. 525'),
    ("Excerpts from 'The Abduction from the Seraglio, K.384, Harmoniemusik'",
     "Excerpts from 'The Abduction from the Seraglio, K. 384, Harmoniemusik'"),
    ('La Clemenza di Tito (overture)',
     'La Clemenza di Tito'),
    ('Piano Sonata no 6 in D major - Tema con variazioni (var. 11)',
     'Piano Sonata No. 6 in D - Tema con variazioni (var. 11)'),
    ('Ridente la calma (K.152) transcribed from "Il Caro mio bene" by Myslivecek',
     'Ridente la calma (K.152) transcribed from "Il Caro mio bene"'),
    ('Serenata notturna in D, K.239',
     'Serenata notturna in D, K. 239'),
    ('Two Flute Quartets: no 3 in C major K.Anh.171 (K.285b) & no 1 in D major (K.285)',
     'Two Flute Quartets: no 3 in C major K.285b & no 1 in D major, K.285'),

    # --- Handel: 10 re-aired works ---
    ('"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\' (Act II Scene 8)',
     '"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\''),
    ("Al lampo dell'armi' (from Act II of Giulio Cesare in Egitto)",
     '"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\''),
    ('The Arrival of the Queen of Sheba (Solomon, HWV 67)',
     "'The Arrival of the Queen of Sheba' - from 'Solomon', HWV 67"),
    ("Tu, del ciel ministro eletto (Bellezza's aria) 'Il Trionfo del Tempo e del Disinganno', HWV 46a",
     "'Tu, del ciel ministro eletto' (Bellezza's aria) from 'Il Trionfo del Tempo e del Disinganno', HWV.46a"),
    ('Die ihr aus dunkeln Grüften den eiteln Mammon grabt (HWV.208) - No.7 from German Arias',
     "Aria: 'Die ihr aus dunkeln Grüften den eiteln Mammon grabt' (HWV.208)"),
    ('Concerto Grosso in Dmajor, HWV 323',
     'Concerto Grosso in D, HWV 323'),
    ("Già che morir non posso'",
     "Già che morir non posso - from 'Radamisto'"),
    ('Il pianto di Maria, cantata, HWV 234',
     'Il Pianto di Maria, cantata, HWV.234'),
    ('Lascia la spina cogli la rose, from Il Trionfo del Tempo e del disinganno, HWV.46a',
     "Lascia la spina cogli la rose, from 'Il Trionfo del Tempo e del disinganno'"),
    ("Lascia la spina, cogli la rosa, from 'Il Trionfo del Tempo e del Disinganno'",
     "Lascia la spina cogli la rose, from 'Il Trionfo del Tempo e del disinganno'"),
    ('Sonata in F major Op 1 No 5',
     'Oboe Sonata in F major Op 1 No 5'),
    ('Utrecht Te Deum in D, HWV 278',
     'Utrecht Te Deum in D major, HWV 278'),

    # --- Brahms: 5 re-aired works ---
    ('3 Hungarian Dances arr. for string orchestra: No 1 in G minor; No 3 in F major; No 5 in F sharp minor',
     '3 Hungarian Dances (originally for piano duet) arr. for string orchestra: No.1 in G minor; No.3 in F major; No.5 in F sharp minor'),
    ('Hungarian Dance No.1 in G minor (originally for piano duet, orchestrated by the composer)',
     'Hungarian Dance No.1 in G minor (originally for piano duet)'),
    ('Intermezzo in A minor,Op 116, No 2',
     'Intermezzo in A minor, Op 116, No 2'),
    ('Quintet in F minor Op 34',
     'Piano Quintet in F minor'),
    ("Three Songs: 'Meine Liebe ist grun' Op 63 No 5",
     "Three Songs: 'Meine Liebe ist grun' (Op.63 No.5) etc"),

    # --- Schumann: 2 re-aired works ---
    ('Die Braut von Messina, Op 100 (Overture)',
     'Die Braut von Messina, Op 100'),
    ('Introduction and Allegro appassionato in G major Op 92 for piano and orchestra',
     'Introduction and Allegro appassionato in G major Op 92'),

    # --- Bach: 12 re-aired works the systematic vocal rule can't reach —
    #     one airing gives "No.N" with no BWV, or an excerpt locator sends
    #     both sides to the token sort.
    ("'Herr! Warum trittest du'(recitative) and 'Die schaumenden Welle' (aria) from Cantata BWV 81, 'Jesus schlaft, was soll ich hoffen'",
     "'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria) - from Cantata No. 81, 'Jesus schlaft, was soll ich hoffen'"),
    ("Cantata no. 81 BWV.81 'Jesus schlaft, was soll ich hoffen': 'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria)",
     "'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria) - from Cantata No. 81, 'Jesus schlaft, was soll ich hoffen'"),
    ('Ich traue seiner Gnaden (from Cantata BWV.97)',
     "Aria 'Ich traue seiner Gnaden' from Cantata no. 97 (BWV.97) 'In allen meinen Taten'"),
    ('Cantata No.11 (Lobet Gott in seinen Reichen) (Ascension Oratorio)',
     'Cantata BWV.11, Lobet Gott in seinen Reichen (Ascension oratorio)'),
    ("Duet from Cantata BWV 134, 'Wir danken und preisen'",
     "Cantata BWV.134: 'Wir danken und preisen' (duet)"),
    ('Cantata No.43 (Gott fahret auf mit Jauchzen)',
     'Cantata BWV.43, Gott fahret auf mit Jauchzen'),
    ('The Well-Tempered Clavier - Book 2, BWV 874-881',
     'Excerpts from The Well-Tempered Clavier, Vol. 2, BWV 874-881'),
    ("Fuga ricercata No.2 from Bach's 'Musikalischen Opfer' (BWV.1079)",
     "Fuga ricercata No 2 a 6 voci from Bach's 'Musikalischen Opfer' BWV.1079"),
    ('Gavotte en rondeau, from Partita no 3 in E major',
     'Gavotte en rondeau (Partita No. 3 in E major for solo violin)'),
    ('Minuet 1 and 2 in F; Fantasia in d',
     'Minuet 1 and 2 in F major; Fantasia in D minor'),
    ('Prelude, from Partita no 3 in E major',
     'Prelude, from Partita no 3 in E'),
    ('Sonata a 5 No.1 in C major & No.2 in F major, for two violins, two violas and continuo',
     'Sonata No 1 in C major & Sonata No 2 in F major for two violins, two violas and continuo'),
    ('Wer ist so würdig als du, Wq.222',
     'Wer ist so würdig als du (Wq.222) (Hamburg 1774)'),

    # --- Source data errors: one airing carries a wrong opus or key. The
    #     performance is the same; fold the mistaken title into the correct
    #     work. (The raw title stays untouched in the DB.)
    ('Passacaglia and Fugue in C, BWV 582',          # mode dropped
     'Passacaglia and Fugue in C minor, BWV 582'),
    ('Passacaglia and Fugue in D minor, BWV 582',    # BWV 582 is in C minor
     'Passacaglia and Fugue in C minor, BWV 582'),
    ('Quartet in F major Op.1 No.1 arr. for string orchestra',  # Op.1 are trios
     'Quartet in F major Op.18 No. 1 arr. for string orchestra'),
    ('Scherzo from Piano Quintet in E minor, Op.44',  # Op.44 is in E flat
     'Scherzo from Piano Quintet in E flat major, Op.44'),
]


def _build_work_alias_table():
    table = {}
    for variant, preferred in _WORK_ALIAS_PAIRS:
        table[work_title_key(variant)] = work_title_key(preferred)
    return table


WORK_ALIASES = _build_work_alias_table()


def resolve_work_alias(work_key: str) -> str:
    return WORK_ALIASES.get(work_key, work_key)


def _date_arg(s):
    """argparse type for YYYY-MM-DD; returns the canonical ISO string."""
    try:
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date {s!r}; expected YYYY-MM-DD")


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db")
    ap.add_argument("--top", type=int, default=30,
                    help="How many rows to show on stdout (default: 30)")
    ap.add_argument("--by",
                    choices=["piece", "work", "composer", "ensemble", "conductor"],
                    default="work",
                    help="Rollup level (default: work)")
    ap.add_argument("--composer", default=None,
                    help="Restrict to tracks whose composer contains this "
                         "string (case-insensitive)")
    ap.add_argument("--surname", action="store_true",
                    help="When --by composer, group by surname only")
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
    args = ap.parse_args()

    if args.year is not None:
        if args.after or args.before:
            ap.error("--year cannot be combined with --after or --before")
        args.after = f"{args.year:04d}-01-01"
        args.before = f"{args.year:04d}-12-31"

    conn = sqlite3.connect(args.db)
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

    # Main aggregation query -- joins to episodes so we can pull the date.
    track_clauses = ["t.title IS NOT NULL", "t.title != ''"]
    track_params = []
    if args.composer:
        track_clauses.append("LOWER(t.composer) LIKE ?")
        track_params.append(f"%{args.composer.lower()}%")
    if args.after:
        track_clauses.append("substr(e.broadcast_date, 1, 10) >= ?")
        track_params.append(args.after)
    if args.before:
        track_clauses.append("substr(e.broadcast_date, 1, 10) <= ?")
        track_params.append(args.before)
    if args.christmas:
        track_clauses.append("substr(e.broadcast_date, 6, 5) = '12-25'")

    sql = ("SELECT t.title, t.composer, t.composer_line, t.performers, "
           "       substr(e.broadcast_date, 1, 10) "
           "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid "
           "WHERE " + " AND ".join(track_clauses))

    # Group by canonical key but track display strings via a Counter so we
    # can show the most common original spelling for each group.
    groups = defaultdict(lambda: {"n": 0, "display": Counter(), "dates": [],
                                  "performers": []})
    aliases_applied = 0

    for title, composer, composer_line, performers, bdate in cur.execute(sql, track_params):
        composer = strip_arranger_tail(composer, composer_line)
        entries = []  # list of (key, display) tuples to record for this track
        if args.by == "composer":
            disp_composer = (composer_surname(composer)
                             if args.surname else normalize_composer(composer))
            display = disp_composer
            if args.raw:
                key = display
            else:
                ck = canonical_key(disp_composer)
                resolved = resolve_composer_alias(ck)
                if resolved != ck:
                    aliases_applied += 1
                key = resolved
            entries.append((key, display))
        elif args.by == "piece":
            display = (normalize_composer(composer), title.strip())
            if args.raw:
                key = display
            else:
                ck_c = canonical_key(display[0])
                resolved_c = resolve_composer_alias(ck_c)
                if resolved_c != ck_c:
                    aliases_applied += 1
                key = (resolved_c, canonical_key(display[1]))
            entries.append((key, display))
        elif args.by in ("ensemble", "conductor"):
            ensembles, conductors = parse_performers(performers)
            names = ensembles if args.by == "ensemble" else conductors
            for name in names:
                if args.raw:
                    key = name
                else:
                    ck = canonical_key(name)
                    if args.by == "ensemble":
                        resolved = resolve_ensemble_alias(ck)
                        if resolved != ck:
                            aliases_applied += 1
                        ck = resolved
                    key = ck
                if key:
                    entries.append((key, name))
        else:  # work
            display = (normalize_composer(composer), normalize_work(title))
            if args.raw:
                key = display
            else:
                ck_c = canonical_key(display[0])
                resolved_c = resolve_composer_alias(ck_c)
                if resolved_c != ck_c:
                    aliases_applied += 1
                wk = work_title_key(display[1])
                resolved_w = resolve_work_alias(wk)
                if resolved_w != wk:
                    aliases_applied += 1
                key = (resolved_c, resolved_w)
            entries.append((key, display))

        for key, display in entries:
            if not key or (isinstance(key, tuple) and not any(key)):
                continue
            groups[key]["n"] += 1
            groups[key]["display"][display] += 1
            if bdate:
                groups[key]["dates"].append(bdate)
            groups[key]["performers"].append(performers or "")

    # Rank by count; pick the most common original spelling for each group
    ranked = sorted(groups.values(), key=lambda g: -g["n"])
    if args.once:
        ranked = [g for g in ranked if g["n"] == 1]

        def _alpha_key(g):
            d = g["display"].most_common(1)[0][0]
            if isinstance(d, tuple):
                return tuple(s.lower() for s in d)
            return (d.lower(),)
        ranked.sort(key=_alpha_key)

    label = f"top {args.top} by {args.by}"
    if args.once:
        label += " (one-offs only)"
    if args.composer:
        label += f" (composer~='{args.composer}')"
    print(label + ":")
    if args.once:
        print(f"  ({len(ranked):,} entries appear exactly once)")
    if args.verbose and not args.raw and aliases_applied:
        alias_kind = {"ensemble": "ensemble",
                      "work": "composer/work"}.get(args.by, "composer")
        print(f"  ({aliases_applied:,} {alias_kind} aliases resolved via lookup table)")
    print()
    if ranked:
        width = len(str(ranked[0]["n"]))
    else:
        width = 1
    show_performer = args.once and args.by in ("piece", "work")
    for i, g in enumerate(ranked[: args.top], 1):
        display = g["display"].most_common(1)[0][0]
        text = " — ".join(p for p in display if p) if isinstance(display, tuple) else display
        # If the group has variants, mark it (verbose only)
        n_variants = len(g["display"])
        marker = (f" ({n_variants} spelling variants)"
                  if args.verbose and n_variants > 1 else "")
        print(f"{i:>3}.  {g['n']:>{width}}×   {text}{marker}")
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
                display = g["display"].most_common(1)[0][0]
                if single_value_by:
                    row = [g["n"], display, len(g["display"])]
                else:
                    row = [g["n"], *display, len(g["display"])]
                if args.dates:
                    row.append("|".join(sorted(g["dates"])))
                if show_performer:
                    row.append(g["performers"][0] if g["performers"] else "")
                w.writerow(row)
        print(f"\nFull ranking ({len(ranked)} rows) written to {args.csv}",
              file=sys.stderr)

    conn.close()


if __name__ == "__main__":
    main()
