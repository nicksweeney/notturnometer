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
    python ttn_analyze.py ttn.sqlite
    python ttn_analyze.py ttn.sqlite --by composer --top 50
    python ttn_analyze.py ttn.sqlite --after 2023-01-01 --before 2023-12-31
    python ttn_analyze.py ttn.sqlite --composer Sibelius --dates
    python ttn_analyze.py ttn.sqlite --title symphony --top 10
    python ttn_analyze.py ttn.sqlite --by composer --title concerto --top 10
    python ttn_analyze.py ttn.sqlite --form prelude --top 10
    python ttn_analyze.py ttn.sqlite --composer Berlioz --form symphony
    python ttn_analyze.py ttn.sqlite --by work --csv top_works.csv --dates
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
    # German form — "Friedrich" + umlauted "Händel"; canonical_key folds the
    # umlaut, so this one pair also covers the de-umlauted "Georg Friedrich
    # Handel". "George Friedrich" (Georg-e) needs its own entry.
    ("Georg Friedrich Händel",      "George Frideric Handel"),
    ("George Friedrich Handel",     "George Frideric Handel"),

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

    # --- High-confidence audit-surfaced splits: typos, mojibake, accents,
    # bare surnames, same-name spelling variants (May 2026 alias sweep) ---
    ("Vicente Adán",                "Vincente Adan"),
    ("Tomasi Albinoni",             "Tomaso Albinoni"),
    ("Juan CrisÃ³stomo Arriaga",    "Juan Crisostomo Arriaga"),
    ("Ludvig van Beethoven",        "Ludwig van Beethoven"),
    ("George Bizet",                "Georges Bizet"),
    ("Brahms",                      "Johannes Brahms"),
    ("Firminius Caron",             "Firminus Caron"),
    ("Iacobus Gallus Carniolus",    "Jacobus Gallus Carniolus"),
    ("FrÃ©dÃ©ric Chopin",           "Fryderyk Chopin"),
    ("Cornelius Dopper",            "Cornelis Dopper"),
    ("Anton Dvorak",                "Antonin Dvorak"),
    ("Hans Eisler",                 "Hanns Eisler"),
    ("Manuela de Falla",            "Manuel de Falla"),
    ("Niels Wilhelm Gade",          "Niels Gade"),
    ("Johnny Greenwood",            "Jonny Greenwood"),
    ("Sofiya Gubaidulina",          "Sofia Gubaidulina"),
    ("Johann Halvorsen",            "Johan Halvorsen"),
    ("Johann Adolfe Hasse",         "Johann Adolf Hasse"),
    ("Haydn",                       "Joseph Haydn"),
    ("Franz Joseph Haydn",          "Joseph Haydn"),
    ("Josef Haydn",                 "Joseph Haydn"),
    ("Jozef Haydn",                 "Joseph Haydn"),
    ("Johann Michael Haydn",        "Michael Haydn"),  # brother — distinct from Joseph
    ("Nicolo Jommelli",             "Niccolo Jommelli"),
    ("Dimitri Kabalevsky",          "Dmitri Kabalevsky"),
    ("Uno Klami",                   "Uuno Klami"),
    ("Victor Kosenko",              "Viktor Kosenko"),
    ("Frederik Kuhlau",             "Friedrich Kuhlau"),
    ("Johan Kuhnau",                "Johann Kuhnau"),
    ("Krassimir Kyurkchiyski",      "Krasimir Kyurkchiyski"),
    ("Oscar Merikanto",             "Oskar Merikanto"),
    ("Tarquino Merula",             "Tarquinio Merula"),
    ("Goesta Nystroem",             "Gosta Nystroem"),
    ("Jakob Obrecht",               "Jacob Obrecht"),
    ("Frederik Pacius",             "Fredrik Pacius"),
    ("Nicolò Paganini",             "Niccolo Paganini"),
    ("Kryzstof Penderecki",         "Krzysztof Penderecki"),
    ("Lubomir Pipkov",              "Lyubomir Pipkov"),
    ("Puccini",                     "Giacomo Puccini"),
    ("Gioacchino Rossini",          "Gioachino Rossini"),
    ("Dimitri Shostakovich",        "Dmitry Shostakovich"),
    ("Ludwig Spohr",                "Louis Spohr"),
    ("Stanford",                    "Charles Villiers Stanford"),
    ("Bernado Storace",             "Bernardo Storace"),
    ("Johann II Strauss",           "Johann Jr Strauss"),
    ("Sullivan",                    "Arthur Sullivan"),
    ("Johann Svendsen",             "Johan Svendsen"),
    ("Kjohn Tavener",               "John Tavener"),
    ("Eduardo Toldrá",              "Eduard Toldra"),
    ("Verdi",                       "Giuseppe Verdi"),
    ("Guiseppe Verdi",              "Giuseppe Verdi"),
    ("Mykhalo Verbytsky",           "Mykhailo Verbytsky"),
    ("Charles Marie Widor",         "Charles-Marie Widor"),
    ("Giacches de Wert",            "Giaches de Wert"),

    # --- Audit-surfaced splits, patronymic added/dropped (May 2026 sweep) ---
    ("Anton Stepanovich Arensky",         "Anton Arensky"),
    ("Alexander Konstantinovich Glazunov", "Alexander Glazunov"),
    ("Mily Balakirev",                    "Mily Alexeyevich Balakirev"),
    ("Aram Ilyich Khachaturian",          "Aram Khachaturian"),
    ("Anton Grigoryevich Rubinstein",     "Anton Rubinstein"),
    ("Dmitry Borisovich Kabalevsky",      "Dmitri Kabalevsky"),
    ("Anatoly Konstantinovich Lyadov",    "Anatol Lyadov"),
    ("Maxim Sosontovitch Berezovsky",     "Maxim Berezovsky"),
    ("Dmitri Dmitriyevich Shostakovich",  "Dmitry Shostakovich"),
    ("Dmitry Dmitriyevich Shostakovich",  "Dmitry Shostakovich"),
    ("Alexander Grechaninov",             "Alexandr Tikhonovich Grechaninov"),
    ("Boris Lyatoshynsky",                "Boris Mykolayovich Lyatoshynsky"),
    ("Borys Mykolayovich Lyatoshynsky",   "Boris Mykolayovich Lyatoshynsky"),
    ("Nicolay Andreyevich Rimsky-Korsakov", "Nikolai Rimsky-Korsakov"),
    ("Nicolai Rimsky-Korsakov",           "Nikolai Rimsky-Korsakov"),
    ("Nikolay Rimsky-Korsakov",           "Nikolai Rimsky-Korsakov"),
    ("Rodion Konstantinovich Shchedrin",  "Rodion Shchedrin"),
    ("Sergei Taneyev",                    "Sergey Ivanovich Taneyev"),
    ("Sergei Ivanovich Taneyev",          "Sergey Ivanovich Taneyev"),
    ("Sergey Sergeyevich Prokofiev",      "Sergey Prokofiev"),
    ("Serge Prokofiev",                   "Sergey Prokofiev"),
    ("Sergei Sergeyevich Prokofiev",      "Sergey Prokofiev"),
    ("Pyotr Il'yich Tchaikovsky",         "Peter Ilyich Tchaikovsky"),
    ("Pyotr Tchaikovsky",                 "Peter Ilyich Tchaikovsky"),
    ("Pitor Illyich Tchaikovsky",         "Peter Ilyich Tchaikovsky"),
    ("Piotr Ilyich Tchaikovsky",          "Peter Ilyich Tchaikovsky"),
    ("Pytor Il'yich Tchaikovsky",         "Peter Ilyich Tchaikovsky"),
    ("Peter Illych Tchaikovsky",          "Peter Ilyich Tchaikovsky"),
    ("Peter Ilych Tchaikovsky",           "Peter Ilyich Tchaikovsky"),
    ("Peter Tchaikovsky",                 "Peter Ilyich Tchaikovsky"),

    # --- Audit-surfaced splits, middle/given name added or dropped ---
    ("Daniel-Francois-Esprit Auber",      "Daniel Auber"),
    ("Adrien Boieldieu",                  "Francois-Adrien Boieldieu"),
    ("Charles Hubert Hastings Parry",     "Hubert Parry"),
    ("Max Christian Friedrich Bruch",     "Max Bruch"),
    ("William Elden Bolcom",              "William Bolcom"),
    ("Henry Charles Litolff",             "Henry Litolff"),
    ("Horatio William Parker",            "Horatio Parker"),
    ("Etienne-Nicolas Méhul",             "Etienne Mehul"),
    ("Johann Peter Emilius Hartmann",     "Johan Peter Emilius Hartmann"),
    ("Jeanne Louise Dumont Farrenc",      "Louise Farrenc"),
    ("Louise Dumont Farrenc",             "Louise Farrenc"),
    ("Johann Franz Xaver Sterkel",        "Franz Xaver Sterkel"),
    ("Friedrich Ludwig Aemilius Kunzen",  "Friedrich Kunzen"),
    ("Erich Korngold",                    "Erich Wolfgang Korngold"),
    ("Count Unico Van Wassenaer",         "Unico Wilhelm Van Wassenaer"),
    ("Grzegorz G Gorczycki",              "Grzegorz Gerwazy Gorczycki"),
    ("Francesco Paolo Tosti",             "Paolo Tosti"),
    ("Bedrich Antonin Wiedermann",        "Bedrich Anton Wiedermann"),
    ("Francesco Veracini",                "Francesco Maria Veracini"),
    ("Daniel Jean Yves Daniel-Lesur",     "Jean-Yves Daniel-Lesur"),
    ("Jean Yves Daniel-Lesur",            "Jean-Yves Daniel-Lesur"),
    ("Antonín Reichenauer",               "Johann Anton Reichenauer"),
    ("Jean-Joseph Cassanéa de Mondonville", "Jean-Joseph de Mondonville"),
    ("Heinrich Ignaz Franz Biber",        "Heinrich Ignaz Franz von Biber"),
    ("Pietro Antonio Cesti",              "Antonio Cesti"),
    ("Pietro Marc'Antonio Cesti",         "Antonio Cesti"),
    ("Fanny Hensel Mendelssohn",          "Fanny Mendelssohn"),
    ("Felix Mendelssohn-Bartholdy",       "Felix Mendelssohn"),
    ("Felix Mendelssohn Bartholdy",       "Felix Mendelssohn"),

    # --- Audit-surfaced splits, name-form / language renderings; merged,
    # display follows the most-aired BBC spelling (May 2026 sweep) ---
    ("Erno Dohnanyi",                     "Ernst von Dohnanyi"),
    ("Dohnányi Ernő",                     "Ernst von Dohnanyi"),
    ("Anton Reicha",                      "Antoine Reicha"),
    ("Carl von Dittersdorf",              "Carl Ditters von Dittersdorf"),
    ("Bernard Henrik Crusell",            "Bernhard Henrik Crusell"),
    ("Józef Antoni Franciszek Elsner",    "Jozef Elsner"),
    ("Imre Kalman",                       "Emmerich Imre Kalman"),
    ("Johann Kaspar Kerll",               "Johann Caspar Kerll"),
    ("Valentin Bakfark",                  "Balint Bakfark"),
    ("Mihail Ivanovic Glinka",            "Mikhail Glinka"),
    ("Christoph Wilibald Gluck",          "Christoph Gluck"),
    ("Komitas",                           "Vardapet Komitas"),
    ("Soghomon Komitas",                  "Vardapet Komitas"),
    ("Orlando Lassus",                    "Orlande de Lassus"),
    ("Orlando di Lasso",                  "Orlande de Lassus"),
    ("Petr Machajdík",                    "Peter Machajdík"),
    ("Pierre van Maldere",                "Pieter van Maldere"),
    ("Henri Du Mont",                     "Henry du Mont"),
    ("Frederic Mompou",                   "Federico Mompou"),
    ("Manuel Ponce",                      "Manuel Maria Ponce"),
    ("Mykola Dmytrovich Leontovych",      "Mykola Leontovych"),
    ("Suor Chiara Margarita Cozzolani",   "Chiara Margarita Cozzolani"),
    ("Anton Kraft",                       "Antonin Kraft"),
    ("Carl Otto Nicolai",                 "Otto Nicolai"),
    ("E.J. Moeran",                       "Ernest John Moeran"),
    ("JA Hasse",                          "Johann Adolf Hasse"),

    # --- Bortniansky: 5 spellings of one composer; display resolves to the
    # most-aired form by play-count (no manual canonical-form pick) ---
    ("Dmitry Bortniansky",                "Dmytro Bortniansky"),
    ("Dmitry Bortnyansky",                "Dmytro Bortniansky"),
    ("Dmitro Bortnyansky",                "Dmytro Bortniansky"),
    ("Dmitri Bortnyansky",                "Dmytro Bortniansky"),
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

    # --- Deutsche Radio Philharmonie Saarbrücken Kaiserslautern: the
    #     post-2007 merger successor, credited under German and English
    #     names (and truncations). Kept DISTINCT from its pre-merger
    #     predecessor, the Saarbrücken Radio Symphony Orchestra above.
    ("German Radio Philharmonic Orchestra, Saarbrücken Kaiserslautern",
     "Deutsche Radio Philharmonie Saarbrücken Kaiserslautern"),
    ("German Radio Saarbrücken-Kaiserslautern Philharmonic Orchestra",
     "Deutsche Radio Philharmonie Saarbrücken Kaiserslautern"),
    ("German Radio Philharmonic Orchestra",
     "Deutsche Radio Philharmonie Saarbrücken Kaiserslautern"),
    ("German Radio Philharmonic",
     "Deutsche Radio Philharmonie Saarbrücken Kaiserslautern"),
    ("Deutsche Radio Philharmonie",
     "Deutsche Radio Philharmonie Saarbrücken Kaiserslautern"),

    # --- Translation artefact: a stray Swedish genitive -s ---
    # "Erik Westbergs Vokalensemble" anglicised two ways — one rendering
    # keeps the Swedish genitive ("Westbergs"), the other drops it.
    ("Erik Westbergs Vocal Ensemble",                "Erik Westberg Vocal Ensemble"),             #  21 →  28
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
    r"[\s,(]*\b(?:arrangement|arranged|arr|transcription|transcribed|transcr|"
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
# phrasings collapse. See
# docs/superpowers/specs/2026-05-29-instrumental-excerpt-gate-design.md.
_MOVEMENT_NAMES = (
    "adagio|adagietto|allegro|allegretto|andante|andantino|largo|"
    "larghetto|lento|presto|prestissimo|vivace|moderato|grave|"
    "menuett?o?|minuet|scherzo|finale|gavotte|sarabande|gigue|courante|"
    "allemande|bourree|sicilian[oa]|romanze|romance|air|rondeau|rondo|loure|"
    "passepied|musette|prelude|fugue|aria|chaconne|giga|capriccio|"
    "intermezzo|nocturne")

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
              "menuet": "menuetto", "menuett": "menuetto", "giga": "gigue"}


def _movement_slug(title):
    """A normalized movement marker for an instrumental movement excerpt, or
    None if the title is not an excerpt. The slug is the sorted set of
    movement-name tokens; failing that a movement ordinal; failing that
    'excerpt' for a bare '(excerpt)'/'(extract)' title. Detection requires a
    leading movement name + 'from', or an explicit mvt/excerpt marker — so a
    whole work named after a tempo (Adagio and Fugue, K.546) returns None."""
    if not (_MOVEMENT_LEAD_RE.search(title) or _MOVEMENT_MARK_RE.search(title)):
        return None
    # A catalogue ref BEFORE the first "from" means the title carries its own
    # work number — it is a whole work (e.g. "Prelude and fugue No.5 in D
    # major (BWV.874) from Das Wohltemperierte Klavier", where "from" names
    # the collection, not a parent), not a movement excerpt.
    fm = re.search(r"\bfrom\b", title, re.I)
    if fm and _catalogue_refs(title[:fm.start()]):
        return None
    names = sorted({_SLUG_NORM.get(m, m)
                    for m in (g.lower()
                              for g in _MOVEMENT_NAME_RE.findall(title))})
    if names:
        return ",".join(names)
    o = _MOVEMENT_ORD_RE.search(title)
    if o:
        return o.group(1) or o.group(2)
    return "excerpt"


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
        recitative, 'from'…), no parenthetical naming a parent work via
        its own catalogue ref (see `_has_parent_work_reference`), and
        its number is not a song-cycle container.

    Otherwise the title's tokens are simply sorted, collapsing word-order
    churn for free without risking the fusion of distinct excerpts that
    share a container catalogue number."""
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
    canon = _squash_separators(canon)
    canon = _drop_implicit_major(canon)
    return " ".join(sorted(canon.split()))


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
    ("An Mignon from 3 Songs, D.161",
     "An Mignon (D.161), Op.19 No.2 (To Mignon)"),
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

    # --- Mozart: 12 re-aired works ---
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
    ("Excerpts from 'The Abduction from the Seraglio, K.384, Harmoniemusik'",
     "Excerpts from 'The Abduction from the Seraglio, K. 384, Harmoniemusik'"),
    # La Clemenza di Tito — the bare/overture token forms unify with the
    # K.621 catalogue overture group (2026-05-29 audit). The opera never airs
    # whole in the corpus, so the bare title is taken as the overture.
    ('La Clemenza di Tito (overture)',
     'Overture to La Clemenza di Tito (K.621)'),
    ('La Clemenza di Tito',
     'Overture to La Clemenza di Tito (K.621)'),
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
    # Op 6 No 5 in D — HWV 323. Retargeted from "D, HWV 323" to the
    # Op-numbered plurality canonical so the spaceless-typo, the bare
    # HWV-only forms, and the Op-numbered token-sort group all fuse.
    # See the Concerto Grosso audit (2026-05-28) at the file tail for
    # the matching variants.
    ('Concerto Grosso in Dmajor, HWV 323',
     'Concerto Grosso in D major, Op 6 no 5'),
    ("Già che morir non posso'",
     "Già che morir non posso - from 'Radamisto'"),
    # Lascia la spina (Il Trionfo HWV.46a, 1707) — same melody as the
    # earlier Almira Sarabande (HWV 1, 1705, instrumental) and later
    # "Lascia ch'io pianga" in Rinaldo (HWV 7, 1711, retexted). The TTN
    # plurality (26×) uses the short "Lascia la spina, from Il Trionfo"
    # phrasing. These two aliases were originally targeted at the
    # full-text "cogli la rose" canonical; retargeted to the short
    # plurality so the cogli-la-rose form, the long "Aria 'Lascia la
    # spina'" form, and the Lezhneva Almira-attributed vocal all fuse.
    # See Handel audit (2026-05-28) at the file tail.
    ('Lascia la spina cogli la rose, from Il Trionfo del Tempo e del disinganno, HWV.46a',
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),
    ("Lascia la spina, cogli la rosa, from 'Il Trionfo del Tempo e del Disinganno'",
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),
    # Op 1 no 5 F major — HWV.363a. Retargeted from the no-HWV oboe form
    # to the catalogue-path canonical so the 2× token-sort sibling fuses
    # with the 19× HWV-bearing group. See Handel audit (2026-05-28) at
    # the file tail.
    ('Sonata in F major Op 1 No 5',
     'Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc'),

    # --- Brahms: 3 re-aired works ---
    ('Intermezzo in A minor,Op 116, No 2',
     'Intermezzo in A minor, Op 116, No 2'),
    # (Superseded by the Brahms audit batch below — both this and bare
    # 'Piano Quintet in F minor' fold to 'Piano Quintet in F minor, Op 34'.
    # Note: bare form is shared with Franck; composer-scoped grouping
    # isolates the relabel.)
    ('Piano Quintet in F minor',
     'Piano Quintet in F minor, Op 34'),
    ("Three Songs: 'Meine Liebe ist grun' Op 63 No 5",
     "Three Songs: 'Meine Liebe ist grun' (Op.63 No.5) etc"),

    # --- Schumann: 2 re-aired works ---
    ('Die Braut von Messina, Op 100 (Overture)',
     'Die Braut von Messina, Op 100'),
    # Retargeted 2026-05-28 (Schumann batch at file tail) — the
    # intermediate "in G major Op 92" was itself folded onward to the
    # short canonical via my new alias. Skip the chain per
    # [[aliases-do-not-chain]].
    ('Introduction and Allegro appassionato in G major Op 92 for piano and orchestra',
     'Introduction and Allegro appassionato (Op.92)'),

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

    # --- --once re-airings, audit batch 2 (Vivaldi, Haydn, Dvořák,
    #     Tchaikovsky, Chopin, Mendelssohn, Grieg, Telemann).

    # --- Vivaldi: 2 re-aired works ---
    ('Allegro non molto from Oboe Concerto in A minor, RV.461',
     'Allegro non molto from Oboe Concerto in A minor'),
    # Retargeted 2026-05-28 (Vivaldi batch at file tail) — the
    # intermediate "Op 8 No 12 (RV 178)" canonical was itself folded
    # onward to the no-key-sig form. Skip the chain per
    # [[aliases-do-not-chain]].
    ('Violin Concerto in C major, RV.178',
     'Violin Concerto, Op 8 No 12, RV 178'),

    # --- Haydn: 10 re-aired works ---
    ("String Quartet in G minor, Op 74, No 3 'Rider' - 2nd movt",
     "2nd movement (Largo assai) - from String Quartet in G minor, Op 74 No 3 'Rider'"),
    ('Ave Regina for double choir, MH 140',
     'Ave Regina for double choir'),
    ('Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and continuo',
     'Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and bc'),
    # London Trio No 1 in C (Hob.IV:1 = Hob.4:1) — retargeted to the larger
    # §hob4 group in the 2026-05-29 Haydn audit so all forms converge.
    ('Divertimento in C major, London Trio no 1, Hob.4:1',
     'Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)'),
    ('Sonata in B flat major, H.16.41',
     'Keyboard Sonata in B flat major, H.16.41'),
    ('Overture to Lo Speziale (The Apothecary)',
     'Overture to Lo Speziale, H.28.3'),
    ('Sonata for piano (H.16.29) in F major',
     'Piano Sonata for piano in F major, Hob 16.29'),
    ('Symphony No.4 in D major',
     'Symphony No 4 (H.1.4) in D major (Presto'),
    ('Symphony No.88 in G (H.1.88)',
     'Symphony No.88 (H.1.88)'),
    ("Variations on the hymn 'Gott erhalte'",
     "Variations about the hymn 'Gott erhalte'"),

    # --- Dvořák: 4 re-aired works ---
    # Retargeted to align with the Dvořák audit batch — both this and the
    # orig-target now resolve to "Slavonic Dance No. 8 in G minor, op. 46".
    ('Slavonic dance No 8 in G minor Op 46 No 8 orch. composer (orig. for pf duet)',
     'Slavonic Dance No. 8 in G minor, op. 46'),
    ('Symphony no 8 in G major, Op 88, B.163',
     'Symphony No. 8 in G major, Op. 88, B. 163'),
    ('Three Slavonic Dances: Slavonic Dance No.8 in G minor, Op.46 no.8; Slavonic Dance No.10 in E minor, Op.72 no.2; Slavonic Dance No.15 in C major, Op.72 no.7',
     'Three Slavonic Dances (No 8 in G minor, Op 46 No 8; No 10 in E minor, Op 72 No 2; No 15 in C major, Op 72 No 7)'),
    ('Two Waltzes, Op 54 [1.Moderato; 2.Allegro vivace]',
     'Two Waltzes, Op 54'),

    # --- Tchaikovsky: 8 re-aired works ---
    ("Cherubim's Song, No. 3 from 'Nine Sacred Pieces' (encore)",
     "1. Cherubim's Song, No. 3 from 'Nine Sacred Pieces'"),
    ('Andante Cantabile from the string quartet (Op.11)',
     'Andante Cantabile (String Quartet, Op11), arranged by the composer'),
    ("Cradle Song (Andantino) from Six Romances, Op.16'1",
     'Cradle Song (Andantino) from Six Romances, Op.16'),
    ("Introduction and Waltz from 'Eugene Onegin'",
     'Introduction and Waltz (Eugene Onegin)'),
    # (Earlier Marche slave alias superseded by the consolidated batch
    # below, which folds all five Marche slave / Slavonic March variants
    # into "Marche Slave, Op 31".)
    ('Nocturne in C sharp minor, Op 19 no 4 (encore)',
     'Nocturne in C sharp minor, Op 19 no 4'),
    ('Souvenir de Florence, Op.70 (Allegro vivace)',
     "Souvenir de Florence (4th mvt, 'Allegro vivace') Op 70"),
    ('Symphony No. 6 in B minor Op.74 (Pathétique) - 3rd mov arr. Carpenter for organ',
     "Symphony No 6 in B minor, Op 74, 'Pathétique' (3rd movt)"),
    ("Symphony No.1 in G minor (Op.13) 'Reves d'hiver'",
     'Symphony No.1 in G minor'),

    # --- Chopin: 12 re-aired works ---
    ('2 Nocturnes for piano (Op.48)no.1 in C minor',
     '2 Nocturnes for piano (Op.48) no.1 in C minor'),
    ('Preludes No.11 in B major; No.12 in G sharp minor; No.13 in F sharp major; No.14 in E flat minor; No.15 in D flat major - from 24 Preludes (Op.28)',
     '24 Preludes Op.28: No.11 in B major; No.12 in G sharp minor; No.13 in F sharp major; No.14 in E flat minor; No.15 in D flat major'),
    ('Etude in C sharp minor, op. 10/4',
     'Etude in C sharp minor, Op 10 no 4'),
    ('Finale. Presto ma non tanto agitato, (Excerpt Sonata No 3 in B flat, Op 58)',  # No 3 is in B minor
     'Finale. Presto ma non tanto agitato, (Excerpt Sonata No 3 in B minor, Op 58)'),
    ('From Preludes, Op 28: nos 11-15',
     'From 24 Preludes, Op 28: nos 11-15'),
    ('Impromptu in Ab major, Op 29',
     'Impromptu in A flat major, Op.29'),
    ('Nocturne No 20 in C sharp minor Op posth. B49',
     'Nocturne No 20 C sharp minor Op posth. B49'),
    ('Nocturne in C sharp minor, Op.27 No.1, arr. for violin and piano',
     "Nocturne in C sharp minor Op.27'1, arr. for violin and piano"),
    ('Nocturne in D flat major, Op.27',
     'Nocturne in D Flat major, from 2 Nocturnes Op 27'),
    ('Three Polonaises: Polonaise in A major, Op.40 No.1, Polonaise in E flat minor, Op.26 No.2; Polonaise in F sharp minor, Op.44',
     "Three Polonaises: Polonaise in A major, Op 40'1; Polonaise in E flat minor, Op 26'2; Polonaise in F sharp minor, Op 44"),
    ('Waltz No. 42 in A flat, оp. 42',           # leading char is a Cyrillic 'о'
     'Waltz No 42 in A flat, Op 42'),
    ("Waltz No. 7 in C sharp minor, op.64'2",
     'Waltz No. 7 in C sharp minor, op. 64/2'),

    # --- Mendelssohn: 9 re-aired works ---
    ('6 Lieder, Op 59',
     '6 Lieder for mixed voices Op.59'),
    ("Allegro vivace, from 'Symphony No. 4 in A, op. 90 (Italian)'",
     "Allegro vivace, 1st movement from 'Symphony No. 4 in A, op. 90 (Italian)'"),
    ('Elias (Elijah), Op.70 - oratorio: Part I',
     'Elias (Elijah), Op.70 - oratorio (Carus version): Part I'),
    ('Elias (Elijah), Op.70 - oratorio: Part II',
     'Elias (Elijah), Op.70 - oratorio (Carus version): Part II'),
    ('Piano Trio in C minor, MWV Q3',
     'Piano Trio in C minor'),
    ('Piano Trio in C minor, MWV.Q3',
     'Piano Trio in C minor'),
    ("Spinning Song, op. 67/4, from 'Songs without Words'",
     "Spinning Song, Op 67 no 4, from 'Songs without Words'"),
    ('Symphony for String Orchestra No 9 in C minor',
     'String Symphony No 9 in C minor'),
    ("Wedding March & Elfins Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase",
     "Wedding March & Elfin Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase"),

    # --- Grieg: 9 re-aired works ---
    ("3 Pieces from Slatter (Norwegian Peasant Dances), Op 72: Forspel/Tussebrurefedera pa Vossevangen (The Goblins' Wedding Procession at Vossevangen); Bruremarsj etter Myllarguten (Wedding march after the Miller's boy); Jon Vestafes springar (Jon Vestafe's springar)",
     "3 Pieces from Norwegian Peasant Dances, Op 72: The Goblins' Wedding Procession at Vossevangen; Wedding march after the Miller's boy; Jon Vestafe's springar"),
    ('3 Pieces from Slåtter (3 Pieces from Norwegian Peasant Dances) (Op.72)',
     '3 Pieces from Norwegian Peasant Dances, Op.72'),
    ("Lyric Pieces (Lyriske stykker): Aften på højfjellet (Evening in the mountains) Op.68 No.4; For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) Op.71 No.2; Forbi (Gone) Op.71 No.6; Etterklang (Remembrances) Op.71 No.7",
     "5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) (Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) (Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)"),
    ("Selected Lyric Pieces: Evening in the mountains (Op.68 No.4); At your feet (Op.68 No.3); Summer's evening (Op.71 No.2); Gone (Op.71 No.6); Remembrances (Op.71 No.7)",
     "5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) (Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) (Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)"),
    ('Fra ungdomsdagene (From early years) from Lyric pieces, book 8 for piano (Op.65 No.1)',
     'Fra ungdomsdagene (From Early Years) from Lyric Pieces, Book 8 for piano, Op.65'),
    ('Old Norwegian Romance with Variations - orig. for 2 pianos arr. for orchestra (Op.51) (1890)',
     'Gammelnorsk Romance met Variasjoner (Old Norwegian Romance with Variations) - orig. for 2 pianos arr for orchestra (Op.51) (1890)'),
    ('Hvad est du dog skiøn (How fair thou art), No.1 of Four Pslams, Op 74',
     "Hvad est du dog skiøn (How fair thou art) , from 'Four Salmer (Hymns), Op 74/1"),
    ('Morning Mood, from Peer Gynt Suite No.1',
     "Morning Mood, from 'Peer Gynt, Suite No.1, Op.46' - arranged for piano four hands"),
    ("Shepherd’s boy, from 'Lyric Suite, op. 54/1'",
     "Shepherd’s boy, from 'Lyric Suite, op. 54 no. 1'"),

    # --- Telemann: 5 re-aired works ---
    ("Harte Fessel, strenge Ketten, from 'Die syrische Unruh'; Der Himmel will, from 'Mario, TWV 21:6; Ach was für Qual und Schmerz, from 'Der unglückliche Alcmeon'",
     '3 arias: Harte Fessel, strenge Ketten (Die syrische Unruh); Der Himmel will, ich soll ein Ziel (Mario, TWV 21:6); Ach was für Qual und Schmerz (Der unglückliche Alcmeon)'),
    ('Duet (Affetuoso) TWV 40:107 & Wandelt in der Liebe, gleich wie Christus uns geliebt! (aria)',
     'Affettuoso & Wandelt in der Liebe, gleich wie Christus uns geliebt! (aria)'),
    ('Concerto in F minor for 3 violins and orchestra from Musique de table, partagée en trois productions',
     'Concerto in F minor for 3 violins (Musique de table)'),
    ('Concerto in F minor for 3 violins and orchestra, from Musique de table',
     'Concerto in F minor for 3 violins (Musique de table)'),
    ("Quartet in E minor, TWV.43:e4 'Paris Quartet' for flute, violin, bass viol and continuo",
     "Quartet No 12 in E minor, TWV 43:e4 'Paris Quartet'"),

    # --- ttn_audit --once finds: re-airings the token sort can't reach ---
    ('Heidenröslein; Heidenröslein; Das Wanderern; Das Wandern',
     'Heidenroslein; Das Wandern'),
    ('Adagio / Allegro in E flat major (K.Anh.C 17.07) for wind octet',
     'Adagio & Allegro in E flat major (K.Anh.C 17.07) for wind octet'),

    # --- Sibelius: ttn_audit --once finds ---
    ("4 Songs: Svarta rosor [Black Roses] (Op.36 No.1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36 No.4); Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37 No.5); Varen flyktar hastigt [Spring is flying] (Op.13 No.4)",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),
    ("4 Songs: Svarta rosor [Black Roses] (Op.36 No.1); Säv, sav, susa [Sigh Sedges sigh] (Op.36 No.4); Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37 No.5); Varen flyktar hastigt [Spring is flying] (Op.13 No.4)",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),
    ("Svarta rosor (Black Rose), Op 36 No 1; Säv, sav, susa (Sigh Sedges sigh), Op 36 No 4; Klickan kom ifran sin äls klings möte (The Maiden's Tryst), Op 37 No 5; Varen flyktar hastigt (Spring is Flying), Op 13 No 4",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),
    ("Svarta rosor (Black Roses) (Op.36 No.1); Säv, sav, susa (Sigh Sedges sigh) (Op.36 No.4); Klickan kom ifran sin äls klings möte (The Maiden's tryst) (Op.37 No.5); Varen flyktar hastigt (Spring is flying) (Op.13 No.4)",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),
    ('Souvenir, Tanz-Idylle and Berceuse from Six Pieces for violin and piano, op. 79',
     "Excerpts from 'Six Pieces for violin and piano, op. 79'"),
    ('Romance in D flat major Op. 24, No. 9 (encore) (10 Pieces Op.24 for piano, No. 9)',
     'Romance in D flat major Op. 24, No. 9 (encore)'),
    # Retargeted to align with the Sibelius audit batch canonical.
    ('Valso triste op 44, No 1',
     'Valse triste, from Kuolema, incidental music Op 44'),

    # --- Liszt: ttn_audit --once finds ---
    ('Abschied, russisches Volkslied (1885)',
     'Abschied, Russisches Volkslied [1885]'),
    ('Auf flügeln des Gesanges - from (Mendelssohn) No.1 of Songs (S.547) transc. for piano',
     'Auf Flügeln des Gesanges - from No 1 of 7 Songs by Mendelssohn (S547) transc. for piano'),
    ('Ave Maria, S.20',
     'Ave Maria (1846)'),
    ('Christus - Pastorale and Herald Angels Sing (extract)',
     'Christus - Pastorale and Herald Angels Sing'),
    ('Christus - Pastorale; Herald Angels Sing',
     'Christus - Pastorale and Herald Angels Sing'),
    ('Concert Study no. 2."Gnomenreigen" (S. 145)',
     'Concert Study No. 2, "Gnomenreigen", S. 145'),
    ("Funerailles - No.7 from 'Harmonies poétiques et religieuses, S.173'",
     "Funerailles - No.7 from 'Harmonies poétiques et religieuses, S.173 - 10 pieces for piano'"),
    ('Hungarian Coronation Mass, S 11)',
     'Hungarian Coronation Mass'),
    ('Hungarian Coronation Mass, S.11)',
     'Hungarian Coronation Mass'),
    ('Préludes - symphonic poem after Lamartine (S.97)',
     'Les Préludes - symphonic poem after Lamartine'),
    ('Liebestod, from Tristan und Isolde, S. 447 (encore)',
     'Liebestod, from Tristan und Isolde, S. 447'),
    ('Nuages gris, S.199 for piano',
     'Nuages gris, S.199'),
    ('Rhapsody No. 5 in E minor, S.244/5',
     'Rhapsody No. 5 in E minor, S.244 No 5'),
    ('St François de Paule marchant sur les flots - from 2 Légends (S.175 No.2)',
     'St François de Paule marchant sur les flots - from 2 Légendes (S.175 No.2)'),

    # --- Handel: ttn_audit --once finds ---
    ('Dica il falso, dica il vero -- from Alessandro Act 2 Scene 8',
     "'Dica il falso, dica il vero' from Alessandro"),
    ('Harp Concerto in B flat major, Op 4, No 6',
     'Concerto for harp and orchestra in B flat major (Op.4 No.6)'),
    # 'Solitudini amate' (Alessandro) — one Boulin/La Petite Bande recording
    # aired 5 times under 3 work-keys. ttn_audit missed it: the 3-play form
    # is not a one-off, and the two 1-play forms score only 0.4 Jaccard.
    ('"Solitudini amate" (Alessandro)',
     "Alessandro (excerpt 'Solitudini amate')"),
    ('"Solitudini amate" (Beloved solitude)',
     "Alessandro (excerpt 'Solitudini amate')"),
    # 'Künft'ger Zeiten eitler Kummer' (HWV 202, Deutsche Arie No 1) — one
    # Plouffe/Pellerin/Laberge recording aired 6 times under 3 work-keys.
    # "HWV 20" in the second title is a typo for HWV 202.
    ('Künft\'ger Zeiten eitler Kummer, HWV 20 - No 1 from Deutsche Arien (originally for soprano, violin & bc, arranged for oboe, violin and organ)',
     "Kunft'ger Zeiten eitler Kummer (HWV.202) - no.1 from Deutsche Arien"),
    ("Künft'ger Zeiten eitler Kummer (HWV.202) (arr. for oboe, violin and organ)",
     "Kunft'ger Zeiten eitler Kummer (HWV.202) - no.1 from Deutsche Arien"),

    # --- Prokofiev: ttn_audit --once finds ---
    ('Arrival of the Guests (Romeo and Juliet)',
     'Arrival of the Guests (Minuet) from Romeo and Juliet'),
    ('God of evil and pagan dance (Allegro sostenuto) - no.2 from Scythian suite from "Ala i Lolly", Op.20',
     'God of Evil and Pagan Dance (Allegro sostenuto) - No.2 from Scythian Suite'),
    ('Moderato, from Sonata for Solo Violin in D, op. 115',
     "Moderato, from 'Sonata Solo Violin in D, op. 115'"),
    ('Sonata no.5 in C major, Op 135',
     'Piano Sonata no.5 in C major, Op.135 (version revised)'),
    ('Sonata no.5 in C major, Op.135 (vers. revised)',
     'Piano Sonata no.5 in C major, Op.135 (version revised)'),
    # Retargeted to align with the Prokofiev audit batch canonical.
    ('Prelude - No.7 from Pieces for piano (Op.12)',
     'Prelude - No. 7 from 10 Pieces for piano (Op.12)'),

    # --- Monteverdi: ttn_audit --once finds ---
    ('2 Madrigals by Monteverdi and a Sonate a 3 by Dario Castello',
     '2 Madrigals by Monteverdi and a Sonata a 3 by Dario Castello'),
    ("Lamento d'Arianna, a 5 SV.107",
     "Lamento d'Arianna, a 5 (SV 107)"),

    # --- Verdi: ttn_audit --once finds ---
    ('Caro nome (Rigoletto)',
     '"Caro nome" Gilda\'s aria from Rigoletto'),
    ("Quando le sere al placido (Rodolfo's aria from act 2 of 'Luisa Miller')",
     "'Quando le sere al placido' (Rodolfo's aria) from Luisa Miller"),
    ('Anvil Chorus (Il Troviatore)',
     'Anvil Chorus (Il Trovatore)'),
    ("Danza sacra e duetto finale d'Aida, S436",
     'Danza sacra e Duetto finale - Aida S.436'),
    ('Lina, pensai che un angelo (Stiffelio)',
     'Lina pensai che un angelo (Stiffelio, Act III)'),
    ('Son io mio Carlo (Don Carlos Act III)',
     'Son io mio Carlo (Don Carlo)'),

    # --- Debussy: ttn_audit --once finds ---
    ("Images II (Cloches à travers les feuilles; Et la lune déscend sur la temple qui fut; Poissons d'or)",
     "Cloches à travers les feuilles; Et la lune déscend sur la temple qui fut; Poissons d'or (Images Bk 2)"),
    # mojibake "Ã©" for "é" in 'cathédrale' split one 5-prelude airing off
    ('Danseuses de Delphes, La cathÃ©drale engloutie, La danse de Puck, Le vent dans la plaine, Minstrels - from Preludes (Book 1)',
     'Danseuses de Delphes, La cathédrale engloutie, La danse de Puck, Le vent dans la plaine, Minstrels - from Preludes (Book 1)'),
    ('Des pas sur la neige; No.6 from Preludes Book One',
     'Des pas sur la neige (Preludes Book One, No 6)'),
    ('Des pas sur la neige - from Preludes Book 1',
     'Des pas sur la neige - Preludes Book'),
    ("Preludes (excerpts): Voiles; La Cathedrale engloutie; La Serenade interrompue; Feuilles mortes; La puerta del vino; Les Fees sont d'exquises danseuses",
     "Preludes (excerpts) - [Book 1 no.2: Voiles; Book 1 no.10: La Cathedrale engloutie; Book 1 no.9: La Serenade interrompue; Book 2 no.2: Feuilles mortes; Book 2 no.3 La puerta del vino; Book 2 no.4: Les Fees sont d'exquises danseuses]"),

    # --- Dvořák: ttn_audit --once finds ---
    ('Kdyz men stara matka zpivat , from Ciganske melodie Op 55 No 4',
     'Kdyz men stara matka zpivat , from Ciganske melodie'),
    # Retargeted to align with the Dvořák audit batch — both forms now
    # fold into "Legend in C major, Op 59 no 4".
    ('Legend in C major (Molto maestoso), Op.59 No.4, orch. by the composer',
     'Legend in C major, Op 59 no 4'),
    ('Legend in C major (Molto maestoso) Op 59 No 4 orchestrated by the composer',
     'Legend in C major, Op 59 no 4'),
    # the last form's title is truncated mid-string; its ~10m length
    # confirms it carries both dances, like the other four
    ('Two Slavonic Dances (Op.46): No.8 (Presto) in G minor & No.3 (Poco Allegro) in A flat major',
     'Slavonic Dances, Op.46 (No. 8 In G minor'),
    ('Two Slavonic Dances: Op 46 No 8 in G minor (Presto) & Op 46 No 3 in A flat major (Poco allegro)',
     'Slavonic Dances, Op.46 (No. 8 In G minor'),
    ('Two Slavonic Dances: Op 46 No 8 in G minor (Presto); Op 46 No 3 in A flat major (Poco Allegro)',
     'Slavonic Dances, Op.46 (No. 8 In G minor'),
    ('Two Slavonic Dances: Op 46 No 8 in G minor and Op 46 No 3 in A flat major',
     'Slavonic Dances, Op.46 (No. 8 In G minor'),

    # --- Purcell: ttn_audit --once finds ---
    ("Song 'See, even Night herself is here' (Z.62/11) - from 'The Fairy Queen', Act II Scene 3",
     '"See, even Night herself is here" (Z.62/11) from \'The Fairy Queen\''),
    ("Song 'See, see, even Night herself is here' Z 62/11 - from 'The Fairy Queen', Act II Scene 3",
     '"See, even Night herself is here" (Z.62/11) from \'The Fairy Queen\''),
    ("Various Works [1. See, Even Night Herself Is Here from 'The Fairy Queen'",
     "1. See, Even Night Herself Is Here from 'The Fairy Queen'"),
    ("Ode for the Birthday of Queen Mary 'Come, ye sons of Art, away'",
     'Come, ye sons of Art, away (Ode for the birthday of Queen Mary [1694], Z323)'),
    ('Four works: Sing, ye Druids all; Divine Andate; Sing, ye Druids all (reprise) - from Bonduca, or The British heroine - incidental music Z.574',
     'Four Works: [1. Sing, ye Druids all from Bonduca, or The British heroine - incidental music Z.574'),
    ('Sonata in B flat major, Z.791, for 2 violins and continuo',
     'Sonata - 1683 no. 2 in B flat major Z.791 for 2 violins and continuo'),

    # --- Franck: ttn_audit --once finds ---
    ('Sonata for cello and piano (M.8) in A major',
     'Cello Sonata in A major (M.8)'),
    ('Le Chausseur maudit (The Accursed Huntsman), symphonic poem',
     'Le Chasseur maudit (The Accursed Huntsman), symphonic poem'),
    ('Piece in D flat (1863)',
     'Organ Piece in D flat major'),
    ('Piano Quintet in F minor, Op.34 (Molto moderato quasi lento',
     'Piano Quintet in F minor, Op.34'),

    # --- Richard Strauss: ttn_audit --once finds ---
    ('4 Lieder: Ständchen (Serenade) (Op.17 No.2); Morgen (Tomorrow) (Op.27 No.4); Für fünfzehn Pfennige (For 15 Pennies) (Op.36 No.2) (brief appl); Zueignung (Dedication) (Op.10 No.1)',
     '4 Lieder (Ständchen, Op.17 No.2; Morgen, Op.27 No.4; Für fünfzehn Pfennige, Op.36 No.2; Zueignung, Op.10 No.1)'),
    ('4 Lieder: Ständchen (Serenade) (Op.17 No.2); Morgen (Tomorrow) (Op.27 No.4); Für fünfzehn Pfennige (For 15 Pennies) (Op.36 No.2); Zueignung (Dedication) (Op.10 No.1)',
     '4 Lieder (Ständchen, Op.17 No.2; Morgen, Op.27 No.4; Für fünfzehn Pfennige, Op.36 No.2; Zueignung, Op.10 No.1)'),
    ('Ständchen (Op.17 No.2); Morgen (Op.27 No.4); Für fünfzehn Pfennige (Op.36 No.2); Zueignung (Op.10 No.1)',
     '4 Lieder (Ständchen, Op.17 No.2; Morgen, Op.27 No.4; Für fünfzehn Pfennige, Op.36 No.2; Zueignung, Op.10 No.1)'),
    ('Ewig einsam/Wenn du einst die Gauen from "Guntram" Op 25',
     "Ewig einsam ... Wenn du einst die Gauen (from 'Guntram' Op 25)"),
    ('Lieder: Das Rosenband (Op.36 No.1); Glückes genug (Op.37 No.1); Ständchen (Op.17 No.2); Ein Obdach gegen Strum und Regen (Op.46 No.1); Morgen (Op.27 No.4); In goldener Fülle (Op.49 No.2)',
     'Lieder: Das Rosenband (Op.36 No.1); Glückes genug (Op.37 No.1); Standchen (Op.17 No.2); Ein Obdach gegen Sturm und Regen (Op.46 No.1); Morgen (Op.27 No.4); In goldener Fülle (Op.49 No.2)'),
    ('Love Scene from Feuersnot, Op 50',
     "Love Scene - from the opera 'Feuersnot'"),

    # --- Rameau: ttn_audit --once finds ---
    ("Various Works [1. Prélude – Air accompagné Tristes apprêts from 'Castor et Pollux'",
     "1. Prélude – Air accompagné Tristes apprêts from 'Castor et Pollux'"),
    ('3 pieces from "Les Indes Galantes" & Le Rappel des Oiseaux [1. Air pour Zéphire',
     '3 Pieces from Les Indes galantes; Le Rappel des oiseaux'),
    ("3 pieces from 'Les Indes Galantes' (Air pour Zéphire; Musette en Rondeau; Air pour Borée et la Rose); Le Rappel des Oiseaux",
     '3 Pieces from Les Indes galantes; Le Rappel des oiseaux'),
    ("Ces oiseaux (à Le Temple de la gloire') (Trajan's aria)",
     "Ces oiseaux ('Le Temple de la gloire')"),
    ("Ces oiseaux, from 'Le Temple de la Gloire'",
     "Ces oiseaux ('Le Temple de la gloire')"),
    ('Le Rappel des Oiseaux, in E minor, from Pieces de clavecin',
     'Le Rappel des Oiseaux in E minor, from Pieces de clavecin (1724, revised.1731)'),

    # --- Pejačević: ttn_audit --once finds ---
    ('Four piano pieces: Barcarole; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9',
     'Four piano pieces: Barcarole, Op.4; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9'),

    # --- Scarlatti: ttn_audit --once finds ---
    ('Sonata in D major Kk.443; Sonata in A major Kk.208; Sonata in D major Kk.29',
     'Keyboard Sonata in D major, Kk.443; Sonata in A major, Kk.208; Sonata in D major, Kk.29)'),
    ('Sonata for keyboard in E major, Kk.46',
     'Sonata for keyboard in E major (K.46/L.25)'),
    ('Sonata in E major, Kk.46',
     'Sonata for keyboard in E major (K.46/L.25)'),
    ('Sonata in G major, K14',
     'Sonata in G major'),

    # --- Rachmaninov: ttn_audit --once finds ---
    # (Both retargeted to the Rachmaninov audit batch canonicals below.)
    ('Six Pieces for four hands, Op 11',
     '6 Duets Op 11 for piano 4 hands'),
    ('6 Pieces for four hands, Op.11',
     '6 Duets Op 11 for piano 4 hands'),
    ('Cello Sonata in G minor Op 19 (excerpt Andante)',
     'Cello Sonata in G minor Op 19 (Andante)'),
    ('Bogoroditse Devo, from Vespers (All-Night Vigil) (Ave Maria)',
     'Bogoroditse Devo, from Vespers (All-Night Vigil)'),

    # --- Ravel: ttn_audit --once finds ---
    ('Le Tombeau de Couperin (Forlane & Allegretto)',
     'Le Tombeau de Couperin (Forlane'),
    ("Soupir, from 'Trois Poèmes de Stéphane Mallarmé'",
     "Soupir, 'Trois Poèmes de Stéphane Mallarmé'"),

    # --- Schütz: ttn_audit --once finds (incl. a BWV->SWV catalogue typo) ---
    ('3 sacred pieces - Anima mea liquefacta; Adjuro vos, filiae Hierusalem; Siehe, wie fein und lieblich ist',
     '3 sacred pieces - Anima mea liquefacta; Adjuro vos, filiae Hierusalem; Siehe, wi'),
    ('Die Himmel erzählen die Ehre Gottes, SWV 76',
     'Die Himmel erzählen die Ehre Gottes, BWV 76'),
    ('Saul, Saul, was verfolgst du mich, SWV.415; Nun will sich scheiden Nacht und Tag, after SWV.138; Herr, unser Herrscher (Psalm 8), SWV.27',
     'Saul, Saul, was verfolgst du mich, SWV 415; Nun will sich scheiden Nacht und Tag, after SWV 138; Herr, unser Herrscher (Psalm 8), SWV 27'),

    # --- Wagner: ttn_audit --once finds ---
    ('Die Meistersinger von Nürnberg (Prelude)',
     'Die Meistersinger von Nürnberg'),
    # Flying Dutchman overture — retargeted to the larger "(The Flying
    # Dutchman)" group in the 2026-05-29 Wagner audit so all forms converge.
    ("Overture to 'Der fliegende Holländer' - The Flying Dutchman",
     "Overture: Der Fliegende Hollander (The Flying Dutchman)"),
    ("Overture to 'Der fliegende Holländer'",
     "Overture: Der Fliegende Hollander (The Flying Dutchman)"),

    # --- Szymanowski: ttn_audit --once finds ---
    ('Excerpts from 20 Mazurkas for piano (Op.50): no.1, no.2 & no.13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('Excerpts from 20 Mazurkas for piano (Op.50): nos.1, 2 & 13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('From 20 Mazurkas for piano Op 50: No 1 in E major; No 2; No 13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('From 20 Mazurkas for piano, Op.50: No.1; No.2; No.13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('Prelude in C minor, Op.1 No. 7',
     'Prelude in C minor (Op.1/7)'),

    # --- Couperin: ttn_audit --once finds ---
    ('Rondeau: Les Barricades mystérieuses',
     'Les Barricades mystérieuses'),
    ('Les Fastes de la grande et ancienne Ménestrandise (Mxnxstrxndxsx) (Pièces de clavecin - ordre 11)',
     'Les Fastes de la grande et ancienne Menestrandise from Pieces de clavecin - ordre no.11'),
    ('Les Fastes de la grande et ancienne Ménestrandise (Mxnxstrxndxsx) (Pièces de clavecin - ordre no.11)',
     'Les Fastes de la grande et ancienne Menestrandise from Pieces de clavecin - ordre no.11'),
    ('Les Fastes de la grande et ancienne Ménestrandise (Pièces de clavecin - ordre no.11)',
     'Les Fastes de la grande et ancienne Menestrandise from Pieces de clavecin - ordre no.11'),
    ("Pièces de clavecin - Première ordre (Paris, 1713) (L'Auguste (Allemande); Première Courante; Seconde Courante; La Majestueuse (Sarabande); Gavotte; La Milordine (Gigue); Menuet; Les Sylvains (Rondeau); Les Abeilles (Rondeau); La Nanète; les Sentiments (Sarabande); la Pastorelle; Les Nonètes. Les Blondes. Les Brunes; La Bourbonnoise (Gavotte); La Manon; L'Enchantresse (Rondeau); La Fleurie ou la tendre Nanette; Les plaisirs de Saint-Fermain-en-Laye)",
     "Les Pièces de clavecin - Première ordre (Paris, 1713) (L'Auguste (Allemande); Première Courante; Seconde Courante; La Majestueuse (Sarabande); Gavotte; La Milordine (Gigue); Menuet; Les Sylvains (Rondeau); Les Abeilles (Rondeau); La Nanète; les Sentiments (Sarabande); la Pastorelle; Les Nonètes. Les Blondes. Les Brunes; La Bourbonnoise (Gavotte); La Manon; L'Enchantresse (Rondeau); La Fleurie ou la tendre Nanette; Les plaisirs de Saint-Germain-en-Laye)"),

    # --- Falla: ttn_audit --once finds ---
    ("Suite from 'El Amor brujo'",
     'El Amor brujo (Suite)'),
    ('Suite of Spanish Folksongs (nos 2 & 4)',
     'Excerpts from Suite of Spanish Folksongs nos 2 & 4'),
    ('Serenata andaluza (encore)',
     'Serenata andaluza'),

    # --- Corelli: ttn_audit --once finds ---
    ('Organ Concerto in C major (Op 6 No 10)',
     'Concerto in C major (Op.6 No.10)'),

    # --- Anonymous: ttn_audit --once finds (a Schola Cantorum Riga
    # chant programme aired twice, plus an encore) ---
    ('Calicem salutaris, Psalmus 115 (processional)',
     'Calicem Salutaris, Psalmus 115 Processionale'),
    ('Quasi stella matutina (antiphon)',
     'Quasi Stella Matutina Antiphona'),
    ('Simile est regnum (antiphon and Magnificat)',
     'Simile Est Regnum Antiphona and Magnificat'),
    ('Veni Sancte Spiritus Antiphona',
     'Veni Sancte Spiritus (antiphon)'),
    ('Yo me soy la morenica (encore)',
     'Yo me soy la morenica'),

    # --- Alban Berg: ttn_audit --once finds ---
    ('Drei Bruchstücke aus Wozzeck, (Three fragments frm Wozzeck) Op 7',
     'Drei Bruchstücke aus Wozzeck (Three fragments from Wozzeck) Op 7'),
    ('Three Fragments from Wozzeck (Op. 7)',
     'Drei Bruchstücke aus Wozzeck (Three fragments from Wozzeck) Op 7'),
    ('Lyric Suite (version for string orchestra)',
     'Lyric Suite (string orchestra version)'),
    # --- Alexander Scriabin: ttn_audit --once finds ---
    ('15 Preludes (selection from Opp.11, 16, 17, 22, 27 & 31)',
     '15 Preludes (selection from Opp 11, 16, 17, 22, 27 & 31)'),
    ('Study in C sharp minor (3 Pieces for piano Op. 2 No. 1)',
     'From 3 Pieces for piano (Op. 2): No. 1, Study in C sharp minor'),
    # --- Anon: ttn_audit --once finds ---
    ('1. Agnus Dei. Gloriosa spes reorum - or',
     '1. Agnus Dei. Gloriosa spes reorum'),
    ('1. O monialis concio burgensis - planctus',
     '1. O monialis concio burgensis'),
    # --- Bela Bartok: ttn_audit --once finds ---
    ('44 Duos for 2 violins, Sz 98/4: Vol.4',
     '44 Duos for 2 violin, Sz 98/4: Vol 4 (excerpts) - No 39 Szerb tanc; No 40 Olah tanc; No 41 Scherzo; No 42 Arab dal; No 43 Pizzicato; No 44 Erdelyi tanc (Ardeleana)'),
    ('Volume 4 from 44 Duos for 2 violins, Sz.98/4',
     '44 Duos for 2 violin, Sz 98/4: Vol 4 (excerpts) - No 39 Szerb tanc; No 40 Olah tanc; No 41 Scherzo; No 42 Arab dal; No 43 Pizzicato; No 44 Erdelyi tanc (Ardeleana)'),
    ('Twenty Hungarian Folksongs, BB 98',
     "Excerpts from 'Twenty Hungarian Folksongs, BB 98'"),
    # --- Benjamin Britten: ttn_audit --once finds ---
    ('Canadian Carnival Overture',
     'Canadian Carnival'),
    ('Les Illuminations for voice and string orchestra',
     'Les Illuminations for organ and string orchestra'),
    # --- Christoph Willibald Gluck: ttn_audit --once finds ---
    ('Paris e Helena, ballet music',
     "Ballet music (excerpt 'Paris e Helena'"),
    # --- Dmitry Shostakovich: ttn_audit --once finds ---
    ('Concerto no. 2 in G major Op.126 for cello and orchestra',
     'Cello Concerto No. 2 in G major Op.126'),
    # --- Eugene Ysaye: ttn_audit --once finds ---
    ('Prelude from Sonata No 2 in A minor, Op 27 No 2 (Obsession) for violin solo',
     'Prelude from Solo Violin Sonata No 2 in A minor Op 27 No 2 (Obsession)'),
    # --- Fanny Hensel Mendelssohn: ttn_audit --once finds ---
    ('Excerpts from Songs Without Words (Op.6) (1846): Nos.1, 3 & 4',
     'Excerpts from Songs Without Words (Op.6) (1846)'),
    ('Excerpts from Songs Without Words, Op 6: no 1',
     'Excerpts from Songs Without Words (Op.6) (1846)'),
    ('Trio Op.11 in D minor',
     'Piano Trio in D minor, Op.11'),
    # --- Haydn: ttn_audit --once finds ---
    ("Symphony No. 103 in E flat major 'Drum Roll'",
     'Symphony No. 103 (H.1.103) in E flat major "Drum Roll"'),
    ('Symphony No.104 in D major "London" (H.1.104)',
     'Symphony No.104 in D major "London"'),
    # --- Hector Berlioz: ttn_audit --once finds ---
    ('La Damnation de Faust, Op 24',
     'Excerpts from La Damnation de Faust (Op.24)'),
    ('Marche hongroise (Rakoczy march) from La Damnation de Faust - Part 1, scene 3',
     'Marche hongroise (Rakoczy march) from La Damnation de Faust'),
    # --- Ignacy Jan Paderewski: ttn_audit --once finds ---
    ('Menuet in G (Humoresques de Concert, Op.14 no.1 (1886))',
     'Menuet in G (Humoresques de Concert, Op 14 (1886))'),
    ('Nocturne in B flat (Op.16/4) & Dans le désert (Op.15)',
     'Nocturne in B flat (Op 16 no 4) & Dans le désert (Op 15)'),
    # --- Isaac Albeniz: ttn_audit --once finds ---
    ("El Albaicín, from 'Iberia, Book 3'",
     'El Albaicín (Iberia, Book 3)'),
    # --- Jan Pieterszoon Sweelinck: ttn_audit --once finds ---
    ('Fantasia in D minor (3)',
     'Fantasia in D minor'),
    ('Fantasia in G major (2) (10)',
     'Fantasia in G major'),
    # --- Joseph Martin Kraus: ttn_audit --once finds ---
    ('Symphony in E flat',
     'Sinfonie in E flat'),
    # --- Kaspar Forster: ttn_audit --once finds ---
    ('Dulcis amor Jesu KBPJ 16',
     'Dulcis amor Jesu'),
    ('Vanitas vanitatum - dialogus de Divite et paupere Lazaro for soprano, tenor, bass and instruments',
     'Vanitas vanitatum - dialogus de Divite et paupere Lazaro'),
    # --- Max Bruch: ttn_audit --once finds ---
    ('Excerpts from Eight Pieces for clarinet, viola and piano, Op 83 (nos 5-8)',
     'Excerpts from Eight Pieces for clarinet, viola and piano, Op 83'),
    ('Scottish Fantasy (Fantasy for Violin and Orchestra with Harp, freely using Scottish Folk Melodies), Op 46',
     'Fantasy for Violin and Orchestra with Harp (Op.46)'),
    ('Scottish fantasy for violin and orchestra (Op.46)',
     'Fantasy for Violin and Orchestra with Harp (Op.46)'),
    # --- Olivier Messiaen: ttn_audit --once finds ---
    ('Hymne au Saint Sacrament for orchestra',
     'Hymne au Saint Sacrament'),
    ("Louange à l'Éternité de Jésus: No 5 from Quatuor pour la fin du temps",
     "Louange à l'Éternité de Jésus (No.5, Quatuor pour la fin du temps for clarinet, piano, violin and cello)"),
    # --- Peter Ilyich Tchaikovsky: ttn_audit --once finds ---
    ('Waltz from Sleeping Beauty',
     'Waltz (Sleeping Beauty)'),
    ("Ya vas lyublyu bezmerno (I love you beyond measure) - Prince Yeletsky's aria from The Queen of Spades",
     "Ya vas lyublyu bezmerno (I love you beyond measure) - Prince Yeletsky's aria"),
    # --- Stanislaw Moniuszko: ttn_audit --once finds ---
    ("From 4 Choral Songs: Kozak ('The Cossack'), Wedrowna ptaszyna ('Little Wandering Bird')",
     'Choral Songs (The Cossack; Little Wandering Bird)'),
    ('Triolet (Triolet)',
     'Triolet'),
    # --- Traditional: ttn_audit --once finds ---
    ('A u sviecie nam navina byla (Belarusian Christmas Song)',
     'A u sviecie nam navina byla'),
    ('Trei cantece de stea din Dobrogea (Steaua sus rasare)',
     'Trei cantece de stea din Dobrogea'),
    # --- ttn_audit --all triage (2026-05): 146 re-airing merge groups ---
    ("Elle ne croyait pas ('Mignon', Act 3)",
     "'Elle ne croyait pas' (aria from Mignon)"),
    ('Air à deux parties “Délices des étés” (Le Camus); Pièce pour clavecin (Le Roux); Air de cour “Goûtons un doux repos” (Lambert)',
     '2 French airs and 1 piece for harpsichord [Air à deux parties “Délices des étés”; Pièce pour clavecin; Air de cour “Goûtons un doux repos”]'),
    ('Najpiękniejsze pionski (The most beautiful songs) Op.4 - words by Adam Asnyk; Pod jaworem (Under the sycamore) - folk song from Włoszczowa region',
     '2 Songs: Najpiekniejsze pionski (The most beautiful songs, words by Adam Asnyk) (Op.4); Pod jaworem (Under the sycamore, folk song from Wloszczowa region)'),
    ('Fairy Tale in A minor, Op.51 No.2; Fairy Tale in E flat major, Op.26 No.2; Fairy Tale in B flat minor Op.20 No.1',
     '3 Fairy Tales (Fairy Tale in A minor, Op 51 No 2; Fairy Tale in E flat major, Op 26 No 2; Fairy Tale in B flat minor Op 20 No 1)'),
    ('3 Pieces for Cello and Piano - excerpts',
     '3 Pieces for Cello and Piano - exceprts'),
    ('3 Pieces for organ from the film Richard III (March; Elegy; Scherzetto)',
     "3 Pieces for organ from 'Richard III'"),
    ('3 pieces: Josquin: In te Domine speravi; Anon: Zorzi; Giorgio - Saltarello; Anon: Forte cosa e la speranza',
     '3 pieces: Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi, Giorgio - Salterello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)'),
    ('3 pieces: [Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi; Giorgio - Saltarello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)]',
     '3 pieces: Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi, Giorgio - Salterello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)'),
    ('4th movement from Viola Sonata, Op 25 No.1',
     '4th movement from Viola Sonata, Op 25 No 1 (Rasendes Zeitmass. Wild. Tonschönheit ist Nebensache)'),
    ('Rasendes Zeitmaß. Wild. Tonschönheit ist Nebensache, from Viola Sonata op 25',
     '4th movement from Viola Sonata, Op 25 No 1 (Rasendes Zeitmass. Wild. Tonschönheit ist Nebensache)'),
    ('Adagio patetico, 3rd movement from Piano Quintet, Op 5 (1901)',
     'Adagio patetico (excerpt Piano Quintet, Op 5)'),
    ("Allegro con spirito, from 'Partita, S.48'",
     "Allegro con spirito, from 'Partita, S. 48'"),
    ('Alma Redemptoris Mater; Ave Maria, O auctrix vite - Responsorium',
     'Alma Redemptoris Mater; Ave Maria, O auctrix vite'),
    ('Concert Arabesques on Themes from The Blue Danube Waltz by Johann Strauss',
     'Arabesques on Themes from The Blue Danube Waltz by Johann Strauss, for piano'),
    ('Aria "Oh! Ne t\'éveille pas encore" - from \'Jocelyn\', Act 1',
     'Aria "Oh! Ne t\'éveille pas encor" - from \'Jocelyn\', Act 1'),
    ("Oh! Ne t'eveille pas encore (Jocelyn, Act 1)",
     'Aria "Oh! Ne t\'éveille pas encor" - from \'Jocelyn\', Act 1'),
    ("Aria 'Voi lo sapete, O Mamma' from 'Cavalleria Rusticana' (from Scene 1, sung by Santuzza)",
     'Aria "Voi lo sapete, O Mamma" from \'Cavalleria Rusticana\''),
    ("Santuzza's Aria 'Voi lo sapete, O Mamma' - from 'Cavalleria Rusticana', Scene 1",
     'Aria "Voi lo sapete, O Mamma" from \'Cavalleria Rusticana\''),
    ("Santuzza's aria 'Voi lo sapete, O mamma' from 'Cavalleria Rusticana'",
     'Aria "Voi lo sapete, O Mamma" from \'Cavalleria Rusticana\''),
    ('Aria No.2 (Vocalise No.2)',
     'Aria No 2 (Vocalise)'),
    ('Concerto in C major for bassoon and orchestra',
     'Bassoon Concerto in C major'),
    ('On the Beautiful Blue Danube (Op.314)',
     'Beautiful Blue Danube (Op.314)'),
    ("Bride's Waltz - from Et folksagn",
     "Bride's Waltz (from Et folkesagn)"),
    ('Canzon II Septimi Toni a 8 from Sacrae Symphoniae 1597',
     'Canzon II Septimi Toni a 8 from Sacrae Symphoniae'),
    ('Prés des remparts de Séville, from Carmen',
     'Carmen (Prés des remparts de Séville)'),
    ('Cello Concerto (T.120)',
     'Cello Concerto'),
    ('Concerto for Cello and Orchestra in C (Op.4)',
     'Cello Concerto in C (Op.4)'),
    ('Sonata in E major arr. for cello and piano',
     'Cello Sonata in E major (orig. for violin and piano)'),
    ("Cello Sonata in G, Op 5 No 8 - from 'Eight solos for the violoncello with a thorough bass'",
     "Cello Sonata in G, Op 5 No 8 - from 'Eight solos for the violincello with a thorough bass'"),
    ('Cinques Danses exotiques, for saxophone and piano',
     'Cinq Danses exotiques, for saxophone and piano'),
    ('Trio in E flat major',
     'Clarinet Trio in E flat (1900)'),
    ('Yel-yel (Come on, bull)',
     'Come on my bull'),
    ('Violin Concerto, Op 18',
     'Concerto for Violin and Orchestra, Op 18'),
    ('Concerto for flute, (2) oboes, strings & bc in G minor (S.Uu (i hs 58:5))',
     'Concerto for flute, (2) oboes, strings & basso continuo in G minor'),
    ('Contre qui Rose - 2nd movement from Les Chansons des Roses',
     'Contre qui Rose (1993) - 2nd movement from Les Chanson des Roses'),
    ('Credo From Missa Si Deus pro nobis à16',
     'Credo From Missa Si Deus pro nobis à 16'),
    ('Danube Afterpoint, octet for 2 pianos, string quartet and 2 brass instruments',
     'Danube Afterpoint (2015), octet for two pianos, string quartet and two brass instruments'),
    ('De profundis (Psalm 129) in C minor, ZWV 96',
     'De profundis (Psalm 129) in C minor'),
    ('Overture from Die Leichte Kavallerie',
     'Die Leichte Kavallerie (Light cavalry)'),
    ('Overture from Die Leichte Kavallerie (Light cavalry)',
     'Die Leichte Kavallerie (Light cavalry)'),
    ('Dixit Dominus for 5 voices and continuo',
     'Dixit Dominus - for 5 voices & basso continuo'),
    ('Drommarne - version for orchestra and choir',
     'Drommarne (Dreams) - version for orchestra and choir'),
    ("Duos from Mozart's Don Giovanni arranged for 2 cellos ('Giovinette che fate all'amore'; 'La ci darem la mano', 'Finch han dal vino')",
     'Duos from "Don Giovanni" arranged for 2 cellos (\'Giovinette che fate all\'amore\'; \'La ci darem la mano\', \'Finch han dal vino\')'),
    ('Overture, Dwie Chatki (Two Huts)',
     'Dwie Chatki (Two Cottages): The Overture'),
    ("Ed io che farò, Zefiro's aria for voice, two violins and continuo",
     "Ed io che farò, Zefiro's aria for voice, two violins and basso continuo"),
    ('Egyptischer March, Op 335',
     'Egyptian March, Op.335'),
    ('Elegy in D flat, Op 23 (encore)',
     'Elegy (Op 23) arr. for piano trio'),
    ('En ny himmel och en ny jord for a capella chorus',
     'En ny himmel och en ny jord (A New Heaven and a New Earth) for a capella chorus'),
    ('En ny himmel och en ny jord for a cappella chorus',
     'En ny himmel och en ny jord (A New Heaven and a New Earth) for a capella chorus'),
    ('Eroticon Op 10): No 2 in D flat; No 3 in A flat',
     'Eroticon (Op 10): No 2 in D flat; No 3 in A flat for piano'),
    ('Etude in F, Op 72 no 6 (encore)',
     'Etude in F major, Op 72 no 6'),
    ("Excerpts from 'Livre de Guitarre'",
     "Excerpts from 'Livre de Guitare'"),
    ("Excerpts from 'Livre de Guittare'",
     "Excerpts from 'Livre de Guitare'"),
    ('Excerpts from Trios de la chambre du roi simphonie',
     'Excerpts from Trios de la Chambre du Roi'),
    ('Trios de la Chambre du Roi Simphonie - Excerpts',
     'Excerpts from Trios de la Chambre du Roi'),
    ("Excerpts of Ballet music from 'A Hut out of the Village' - 'Gypsy Dance' & 'Kolomyika' (Ukrainian Dance)",
     'Excerpts of Ballet music from "A Hut out of the Village"'),
    ('Exulta satis - Offertorium for countertenor, tenor, two violins, viola and basso continuo',
     'Exsulta satis - Offertorium for countertenor, tenor, two violins, viola and basso continuo'),
    ('Fantaisie et variations brillantes sur 2 airs favoris connus, Op.30',
     'Fantaisie et variations brillantes sur 2 airs favoris connus for guitar (Op.30) in E minor'),
    ('Fantasia sul un linguaggio perduto for string instruments',
     'Fantasia sul linguaggio perduto for string instruments'),
    ("First movement from 'Rock Symphony'",
     "First Movement (Allegretto), from 'Rock Symphony'"),
    ("Five Songs: Auch kleine Dinge, from 'Italienisches Liederbuch'; Gesang Weylas, no. 46 from 'de Mörike Lieder'; Nachtzauber, from 'Eichendorff-Lieder'; Mignon IV: Kennst du das Land, no. 9, from 'Goethe Lieder'; Die Zigeunerin, from 'Eichendorff-Lieder'",
     'Five Songs: Auch kleine Dinge (Italienisches Liederbuch); Gesang Weylas (de Mörike Lieder); Nachtzauber (Eichendorff-Lieder); Mignon IV: Kennst du das Land (Goethe Lieder); Die Zigeunerin (Eichendorff-Lieder)'),
    ('From 5 Tone Poems, Op 7',
     'From 5 Tone Poems for piano op 7'),
    ('Galathea; Mahnung (Warning) - from Brettl-Lieder (Cabaret Songs)',
     'Galathea & Mahnung - from Brettl-Lieder (Cabaret Songs) (Galathea & Warning)'),
    ('Grande Sonata in G minor, Op.3',
     'Grande Sonata for piano in G minor, Op 3'),
    ("Improvisation on 'Somewhere over the Rainbow' by Harold Arlen",
     "Improvisation on 'Somewhere over the Rainbow'"),
    ("Improvisations on 'Toccata'; 'La Spagna'; H. Butler's Theme; 'Passamezzo antico'; 'Ciaccona'",
     "Improvisations on 'Toccata'; 'La Spagna'; H. Butler's Theme; 'Passamezzo antico'"),
    ('Mellanspel ur Sången (Interlude from the cantata: The Song)',
     'Interlude from "Sången" (The Song)'),
    ('Intraden und Tänze - from Conviviorum Deliciae, Nuremburg 1608',
     'Intraden und Tanze - from Conviviorum Deliciae'),
    ('It was a lover and his lasse (London, 1600)',
     'It was a lover and his lasse'),
    ('Jolly Soldier: An American Independence Song taken from the Social Harp (1855)',
     'Jolly Soldier (An American Independence song taken from the Social Harp, 1855)'),
    ("Rêve angélique, Op.10 No.22 ('Kamennoi Ostrov', 24 Musical Portraits)",
     'Kamennoi Ostrov [Portraits], Op 10 no 22'),
    ('Kantate No. 2 Ad genua - Ad ubera prtabimini',
     'Kantate No. 2 Ad genua - Ad ubera portabimini'),
    ('Kyrie And Gloria From Missa Si Deus pro nobis à16',
     'Kyrie And Gloria From Missa Si Deus pro nobis à 16'),
    ('Pantomime-Ballet: La Captive - Suite from Act I (compiled by Frits Celis)',
     'La Captive: Suite from Act I (Ballet-Pantomime compilation by Frits Celis)'),
    ("La Noce Champetre ou l'Himen Pastoral - from Pieces pour la Muzette, Paris",
     "La Noce Champetre ou l'Himen Pastoral - from Pieces pour la Muzette"),
    ('La Touriére from Concerto comique No.18',
     'La Tourière from Concerto Comique XVlll'),
    ('Laudate pueri - psalm',
     'Laudate pueri'),
    ('Pièces de luth in F minor',
     'Lute pieces in F minor'),
    ('Lyrical Poem for small orchestra',
     'Lyric Poem for small orchestra'),
    ('Passages in Imitation of the Trumpet (Ayres & Pieces IV (1685)',
     'Matteis: Passages in Imitation of the Trumpet (Ayres & Pieces IV, 1685)'),
    ("Melody, 'Orfeo ed Euridice'",
     'Melody (Orfeo ed Eurydice)'),
    ("Missa sancta No.1 in E flat major, J.224, 'Freischutzmesse' for soli, chorus & orchestra",
     "Missa sancta No.1 in E flat major 'Freischützmesse' for soli, chorus & orchestra"),
    ("Missa sancta No.1 in E flat major, J224, 'Freischützmesse', for soloists, chorus & orchestra",
     "Missa sancta No.1 in E flat major 'Freischützmesse' for soli, chorus & orchestra"),
    ("Morning Hymn from Elverskud (The Elf King's Daughter), Op 30",
     "Morning Hymn from Elverskud (The Elf King's Daughter)"),
    ("Morning Hymn from The Elf King's Daughter",
     "Morning Hymn from Elverskud (The Elf King's Daughter)"),
    ('Moses Fantasy for cello and piano (Bravura variations on one chord from a Rossini theme)',
     'Moses Fantasy (after Rossini) for cello and piano (Bravura Variations on one chord from a Rossini theme)'),
    ('My River Runs To Thee',
     'My River Runs To'),
    ('Mzeo tibatvisa (June Sun)',
     'Mzeo Tibatvis (June Sun)'),
    ('Nocturne (Andante) - 3rd movement from String Quartet No 2 in D major arr. Sargent for orchestra',
     'Nocturne (Andante) - 3rd movement from Quartet for strings no.2 in D major arr. Sargent for orchestra'),
    ('O Lord, make thy servant Elizabeth – for 6 voices',
     'O Lord, make thy servant Elizabeth'),
    ('O quam bonus es - motet for 2 voices (Si Lodano le Piaghe di Christo e le Mammelle Della Madonna)',
     'O quam bonus es - motet for 2 voices (Si Lodano le Piaghe di Christo & le Mamelle Della Madonna)'),
    ("Oce náš hlapca jerneja [The Bailiff Yerney's Prayer]",
     "Oce náš hlapca jerneja (Bailif Yerney's Prayer)"),
    ('Suite for orchestra (BeRI 6) in D minor',
     'Orchestral Suite in D minor, BeRI 6'),
    ("Overture from the opera 'Taras Bulba'",
     "Ouverture from the opera 'Taras Bulba'"),
    ('Overture from The Wasps - Aristophanic suite (from incidental music)',
     'Overture from The Wasps - An Aristophanic suite'),
    ("Overture to Elverhøj (Elve's Hill)",
     'Overture to Elverhøj'),
    ('Overture to Hermina im Venusberg (Hermania in the Cave of Venus)',
     "Overture to Hermina im Venusberg (Hermania in Venus' cave)"),
    ('Partita for Violins in Sixth-Tone System (1936)',
     'Partita for Violin in a Sixth-tone System (1936)'),
    # Pavane harmonica-arr. variants — target retargeted to the orchestral
    # canonical "Pavane for orchestra Op 50" (the most-aired form). The
    # `_strip_arrangement_tail` machinery already collapses the harmonica
    # scoring into the same work_title_key as the orchestral original.
    ('Pavane in F minor (Op.50) arr. for harmonica and orchestra',
     'Pavane for orchestra Op 50'),
    ('Pavane, Op.50, arr. for harmonica and orchestra',
     'Pavane for orchestra Op 50'),
    ('Two works: Pavane de Spaigne; La Spagnolletta',
     'Pavane de Spaigne; La Spagnolletta'),
    ('Piano Concerto in C major, Op 14',
     'Piano Concerto in C'),
    ('Quintet Op 18 for piano and strings',
     'Piano Quintet, Op 18'),
    ("Sonata for piano (Op.8 No.1) in C major, 'Sonate facile'",
     "Piano Sonata in C major,Op.8 No.1, 'Sonate facile'"),
    ('Suite in B flat major, Op 45',
     'Piano Suite in B flat major, Op 45'),
    ('Suite in B flat major, Op.45, for piano',
     'Piano Suite in B flat major, Op 45'),
    ("Prayer, from 'From Jewish Life'",
     'Prayer (From Jewish Life)'),
    ('Prima la Musica, Poì le Parole - Divertimento teatrale in one act',
     "Prima la Musica, Poì le Parole ('First the Music and then the Words') - Divertimento teatrale in one act"),
    ('Quartet in E flat for clarinet, bassoon, horn and piano',
     'Quartet in E flat for clarinet, basson, horn and piano'),
    ("Quartet in F major for horn, oboe d'amore, violin and continuo, FWV N:F3",
     "Quartet in F for horn, oboe d'amore, violin and basso continuo FWV N:F3"),
    ('Rodolphe\'s aria ("Your tiny hand is frozen") from La Boheme, Act 1 (sung in Hungarian)',
     'Rodolfo\'s aria ("Your tiny hand is frozen") from \'La bohème\''),
    ('Sanctus And Agnus Dei From Missa Si Deus pro nobis à16',
     'Sanctus And Agnus Dei From Missa Si Deus pro nobis à 16'),
    ('Seemorgh - The Sunrise for Orchestra',
     'Seemorgh - The Sunrise'),
    ('Serenata in vano, FS 68',
     'Serenata in vano'),
    ('Sinfonia no 14 in G',
     'Sinfonia No. 14 in G - excerpt'),
    ('Sinfonia, Op.1 No.4',
     'Sinfonia in E flat, Op.1 No.4'),
    ('Sinphonia No.4 (Op.1)',
     'Sinfonia in E flat, Op.1 No.4'),
    ('You Grey Horse',
     'Siwy koniu (You Grey Horse)'),
    ("Sonata 1.x.1905 for piano in E flat minor, 'Zulice'",
     'Sonata 1.x.1905 for piano in E flat minor'),
    ('Sonata No 11 for cornett, violin and continuo',
     'Sonata No 11 for cornet, violin and continuo'),
    ('Sonata for 3 recorders or flutes in C minor, Op 1 no 4',
     'Sonata No 7 for 3 flutes Op 1 No 4'),
    ('Sonata in C minor, Op 1 no 4',
     'Sonata No 7 for 3 flutes Op 1 No 4'),
    ('Sonata for oboe, bassoon and basso continuo in C minor, WD.695',
     'Sonata for oboe, bassoon and basso continuo in C minor, WD. 695'),
    ("Violin Sonata in D major, Op 8 No 2, from 'X Sonate' (Amsterdam, 1744)",
     "Sonata for violin and continuo (Op.8 No.2) in D major, from 'X Sonate'"),
    ("Violin Sonata Op.9 No.12 'La Folia'",
     "Sonata for violin and continuo, Op.9 No.12, 'La Folia'"),
    ('Sonatina No.1 in G - from Six Sonatines, Op.8',
     'Sonatina I in G - from Six Sonatines, Op 8'),
    ('Sonatina in G, Op 8 No 1',
     'Sonatina I in G - from Six Sonatines, Op 8'),
    ('Violin Sonatina in A flat',
     'Sonatina for Violin and Piano in A flat'),
    ('Suite No 1 in G major, Op 15',
     'Suite No 1 in F major for two pianos, Op 15'),
    ('Suite No.1 in F for 2 pianos (Op.15)',
     'Suite No 1 in F major for two pianos, Op 15'),
    ('Suite No.1 in F major for 2 pianos, Op.15',
     'Suite No 1 in F major for two pianos, Op 15'),
    ("Wind music from 'A Midsummer Night's Dream', Op.61",
     "Suite from 'A Midsummer Night's Dream', Op.61"),
    ('Symphonie à grand orchestre de l\'opéra Cora (Overture to "Cora and Alonzo")',
     "Symphonie à grand orchestre de l'opera Cora"),
    ('Symphony for Winds in G minor, A.509',
     'Symphony for Winds in G minor, A. 509'),
    ('Varen kom en valborgsnatt (The spring came on a Walpurgis night)',
     'The Spring Came on a Walpurgis Night'),
    ('Three pieces for clarinet',
     'Three Pieces for Clarinet and Piano'),
    ('Three Songs with texts by JPContamine de La Tour',
     'Three Songs with texts by JP Contamine de La Tour'),
    ('Three Songs: Die stille Stadt; Licht in der Nacht; Bei dir ist es Traut',
     "Three Songs: Die stille Stadt, from 'Vier Lieder'; Licht in der Nacht, from 'Vier Lieder'; Bei dir ist es Traut, from 'Fünf Lieder'"),
    ('To be Sung of a Summer Night on the Water (RT.4.5)',
     'To be Sung of a Summer Night on the Water'),
    ("Toccatina from No.1 in D major from 'Fasciculus Musicus'",
     'Toccatina from No 1 in D (Toccatina'),
    ('Traces of Magic (Octet for clarinet, bassoon, horn, string quartet & double bass)',
     'Traces of Magic (Octet for clarinet, bassoon, horn, string qtet & double bass)'),
    ("Tre madrigali di Torquato Tasso, Op.13: A Virgilio (To Virgil); All' aurora (To the Dawn); Non e questo un morire (This is Not to Die)",
     "Tre madrigal di Torquato Tasso (Op.13): A Virgilio (To Virgil); All' Aurora (To the Dawn); Non e questo un morire (This is not to die)"),
    ("Two Love Songs: The Passionate Shepherd to His Love (Text Christopher Marlowe); The Nymph's Reply to the Shepherd (Text Sir Walter Raleigh)",
     "Two Love Songs: 1.The Passionate Shepherd to His Love (Text Christopher Marlowe); 2.The Nymph's Reply to the Shepherd (Text Sir Walter Raleigh)"),
    ('Two psalm-tunes: Kittery (1786) & Cobham (1794)',
     'Two Psalm-tunes: Kittery (1786); Cobham (1794)'),
    ("Una notte in Ellade (sull'Acropoli), orchestral notturno, Op.31",
     "Una notte in Ellade (sull'Acropoli), orchestral nocturne, Op.31"),
    ('Variations on the old Swedish air Och liten Karin tjente, Op 91',
     "Variations on the old Swedish air 'Och liten Karin tjente' in E minor, Op.91"),
    ('Weihnacht in der uralten Marienkirche zu Krakau. Fantasie Felix Nowowiejski',
     'Weihnacht in der uralten Marienkirche zu Krakau'),
    ("When Mary thro' the garden went, Op 127 No 3",
     "When Mary thro' the garden went (from 8 Partsongs, Op 127 no 3)"),

    # --- Arvo Pärt — title variants the token sort can't reach ---
    # Cantus: the dedication as the Latin "in memoriam" vs English "in
    # Memory of".
    ("Cantus in Memory of Benjamin Britten",
     "Cantus in memoriam Benjamin Britten"),
    # A "for chorus" scoring tag dropped.
    ("Magnificat for chorus", "Magnificat"),
    ("The Woman with the Alabaster box for chorus",
     "The Woman with the Alabaster Box"),
    # Bogoróditse Djévo — four BBC transliterations of one work
    # (devo/djevo/dyevo, ± "Ráduisya"/"Ave Maria").
    ("Bogoroditse devo",                  "Bogoróditse Djevo"),
    ("Bogoróditse Djevo (Ave Maria)",     "Bogoróditse Djevo"),
    ("Bogoróditse Dyévo Ráduisya",        "Bogoróditse Djevo"),
    # Passio: the short title vs the full Latin.
    ("Passio", "Passio Domini nostri Jesu Christi secundam Joannem"),
    # Zwei Beter: a parenthetical English gloss dropped.
    ("Zwei Beter (Two Prayers)", "Zwei Beter"),

    # --- 2026-05-20 multi-play harvest: high-airing spelling-only merges
    # surfaced by ttn_rebroadcast --multiplay, grouped by work. Each maps a
    # work_title_key the token-sort path leaves distinct (a "Strings" vs
    # "string orchestra" wording, a "for piano" suffix, a dropped opus) onto
    # the dominant spelling of the same work. Arrangement variants and
    # excerpt/movement labellings were deliberately excluded. ---

    # Elgar: Serenade for Strings in E minor, Op 20
    ("Serenade for Strings Op 20",                     "Serenade for Strings in E minor, Op 20"),
    ("Serenade for string orchestra in E minor, Op 20", "Serenade for Strings in E minor, Op 20"),
    ("Serenade in E minor for string orchestra",       "Serenade for Strings in E minor, Op 20"),

    # Vaughan Williams: Fantasia on a Theme by Thomas Tallis (by ↔ of,
    # ± "for double string orchestra")
    ("Fantasia on a theme by Thomas Tallis for double string orchestra", "Fantasia on a theme by Thomas Tallis"),
    ("Fantasia on a theme of Thomas Tallis for double string orchestra", "Fantasia on a theme by Thomas Tallis"),
    ("Fantasia on a theme of Thomas Tallis",           "Fantasia on a theme by Thomas Tallis"),

    # Chopin: 24 Preludes, Op 28 (whole set only — the "nos 11-15" excerpt
    # is a different work and is NOT folded here)
    ("24 Preludes Op.28 for piano",                    "24 Preludes, Op 28"),

    # Chopin: Ballade No 1 in G minor, Op 23
    ("Ballade for piano no. 1 (Op.23) in G minor",     "Ballade No 1 in G minor, Op 23"),
    ("Ballade No.1 (Op.23)",                           "Ballade No 1 in G minor, Op 23"),

    # Weber: Clarinet Quintet in B flat major, Op 34 (J.182) — Quintet ↔
    # Clarinet Quintet, ± J-number/year
    ("Quintet in B flat major Op.34 for clarinet and strings (J.182)", "Clarinet Quintet in B flat major, Op 34"),
    ("Quintet in B flat major for clarinet and strings, Op 34", "Clarinet Quintet in B flat major, Op 34"),
    ("Quintet for Clarinet and Strings in B flat J.182 Op 34", "Clarinet Quintet in B flat major, Op 34"),
    ("Clarinet Quintet (Op.34) in B flat major (J.182) (1815)", "Clarinet Quintet in B flat major, Op 34"),

    # Fauré: Nocturne No 1 in E flat minor, Op 33 No 1
    ("Nocturne for piano in E flat minor, Op 33 no 1", "Nocturne No 1 in E flat minor, Op 33 No 1"),
    ("Nocturne in E flat minor Op 33 No 1",            "Nocturne No 1 in E flat minor, Op 33 No 1"),
    ("Nocturne for piano no.1 (Op.33 No.1) in E flat minor", "Nocturne No 1 in E flat minor, Op 33 No 1"),

    # Debussy: String Quartet in G minor, Op 10 (he wrote only one quartet,
    # so the bare "in G minor" is unambiguous)
    ("Quartet for strings in G minor , Op 10",         "String Quartet in G minor, Op 10"),
    ("String Quartet in G minor",                      "String Quartet in G minor, Op 10"),

    # Sibelius: Finlandia, Op 26 (orchestral original; the "hymn tune arr.
    # for chamber choir" is a separate work_key, not folded)
    ("Finlandia Op.26 for orchestra",                  "Finlandia, Op 26"),

    # Grieg: Holberg Suite, Op 40 (string-orchestra version)
    ("Holberg suite Op 40 vers. for string orchestra", "Holberg Suite, Op 40"),
    ("Holberg Suite Op 40 for string orchestra",       "Holberg Suite, Op 40"),

    # Grieg: Norwegian Dance No 1, Op 35 (Allegro marcato is No 1's marking)
    ("Norwegian Dance No 1 Op 35 for piano duet",      "Norwegian Dance (Allegro marcato) (Op.35 No.1)"),
    ("Norwegian Dance, Op 35 No 1",                    "Norwegian Dance (Allegro marcato) (Op.35 No.1)"),
    ("Norwegian Dance (Allegro marcato), Op.35'1",     "Norwegian Dance (Allegro marcato) (Op.35 No.1)"),
    ("Norwegian Dance No.1 for piano duet",            "Norwegian Dance (Allegro marcato) (Op.35 No.1)"),

    # Debussy: Cello Sonata in D minor (Cello Sonata ↔ Sonata for cello and piano)
    ("Sonata for cello and piano in D minor",          "Cello Sonata in D minor"),

    # Ravel: Piano Trio in A minor (Piano Trio ↔ Trio for piano and strings)
    ("Trio for piano and strings in A minor",          "Piano Trio in A minor"),

    # --- Spelling/transliteration variants from the 2026-05-25 variant audit ---

    # Rimsky-Korsakov: Scheherazade, Op 35 — consolidate spelling
    # (Scheherazade/Sheherazade/Scheherezade), the "after 1001 Nights"
    # subtitle, and bare-vs-"symphonic suite" phrasings into one work. The
    # excerpt "Arabian Song, from 'Scheherezade'" is deliberately NOT mapped
    # (it carries a 'from' locator — a derived piece, not the suite).
    ("Scheherazade - symphonic suite after 1001 Nights, Op 35", "Scheherazade - symphonic suite, Op.35"),
    ("Sheherazade - symphonic suite Op.35",            "Scheherazade - symphonic suite, Op.35"),
    ("Scheherezade - symphonic suite, Op.35",          "Scheherazade - symphonic suite, Op.35"),
    ("Sheherazade, Op 35",                             "Scheherazade - symphonic suite, Op.35"),
    ("Sheherazade",                                    "Scheherazade - symphonic suite, Op.35"),
    ("Scheherazade, Op 35",                            "Scheherazade - symphonic suite, Op.35"),

    # Schubert: Auf dem Wasser zu singen — D744 is a transposition typo for
    # the correct Deutsch number D.774 (catalogue-path key; the only tracks
    # keyed D744 are this song). Folds the typo'd airings into the original.
    ("Auf dem wasser zu singen, D744",                 "Auf dem Wasser zu singen, D.774"),

    # Doppler: Fantaisie pastorale hongroise, Op 26 — Fantaisie (Fr) vs the
    # Fantasie/pastoral misspellings. (The "version for flute & piano" stays
    # separate, per the bare-scoring policy.)
    ("Fantasie Pastorale Hongroise, Op 26",            "Fantaisie pastorale hongroise, Op 26"),
    ("Fantasie pastoral hongroise (Op.26)",            "Fantaisie pastorale hongroise, Op 26"),

    # Debussy: Prélude à l'après-midi d'un faune — "d'une faune" typo (faune
    # is masculine). The hyphen/apostrophe fold already unifies the rest.
    ("Prélude à l'àpres midi d'une faune",             "Prélude à l'après-midi d'un faune"),

    # --- Catalogue-path phantom-ordering splits (2026-05-26 audit) -----------
    # Same catalogue ref, but the BBC inconsistently includes the within-form
    # ordering number ("Cello Suite No 3, BWV 1009" vs "Suite for solo cello
    # in C, BWV 1009"). The catalogue path includes all digits in the key —
    # essential for set-catalogue siblings (D.899 impromptus, K.620 arias) —
    # so these variants split. Each alias merges one variant key into the main
    # work_key. Variant keys checked corpus-wide for exclusivity (no
    # cross-pollution into other works).

    # Bach BWV 1056 — Harpsichord/Keyboard Concerto No 5 in F minor. Both the
    # bare-form keyboard variant AND the G-minor oboe reconstruction (same
    # work in two scorings) fold into the most-aired form.
    ("Keyboard Concerto in F minor, BWV.1056",
     "Harpsichord Concerto no 5 in F minor, BWV.1056"),
    ("Concerto for oboe and strings in G minor (reconstructed from BWV.1056)",
     "Harpsichord Concerto no 5 in F minor, BWV.1056"),

    # Bach BWV 1068 — Orchestral Suite No 3 in D. The bare "Air, Overture in
    # D" form (Air on the G String) lacks the suite-ordering "3".
    ("Air, Overture in D major, BWV1068",
     "Orchestral Suite No 3 in D major, BWV 1068"),

    # Schubert D.940 — Fantasia in F minor for 4 hands. The "(originally for
    # 4 hands)" parenthetical picks up a phantom "4" digit; the more common
    # "four hands" / "piano duet" wording spells it out and stays clean.
    ("Fantasia in F minor, D.940 (originally for 4 hands)",
     "Fantasie in F minor for Piano Four Hands, D940"),

    # Mozart K.298 — Flute Quartet No 4 in A. Bare-form lacks the "no 4".
    ("Quartet for flute and strings (K 298) in A major",
     "Flute Quartet no 4 in A major, K 298"),

    # --- Mozart quartets & quintets audit (2026-05-28) ----------------------
    # Numbered-vs-unnumbered split: the bare form ("Quartet in G major
    # (K.387)") takes the catalogue path (§k387|387|g), while the numbered
    # form carries the ordinal into the key (§k387|14,387|g), so they don't
    # collapse. The K number pins identity; "no.N" is a redundant ordinal.
    # Each numbered group verified pure whole-work (no excerpts). Bare form
    # is the most-aired in every case here.

    # K.387 — String Quartet No 14 in G ('Spring').
    ("String Quartet no.14 in G major, K.387",
     "Quartet in G major (K.387)"),
    # K.465 — String Quartet No 19 in C ('Dissonance'). Two ordinal variants
    # (one keyless) fold in.
    ("String Quartet no 19 in C major, K.465 'Dissonance'",
     'String Quartet in C major (K.465) "Dissonance"'),
    ("String Quartet no 19, K.465 \"Dissonance\"",
     'String Quartet in C major (K.465) "Dissonance"'),
    # K.458 — String Quartet No 17 in B flat ('Hunt').
    ("String Quartet no 17 in B flat, K. 458 'Hunt'",
     "String Quartet in B flat major, K458, 'Hunt'"),
    # K.589 — String Quartet No 22 in B flat ('Prussian').
    ("String Quartet no.22 in B flat major, K. 589 'Prussian'",
     "Quartet for strings (K.589) in B flat major 'Prussian'"),
    # K.493 — Piano Quartet No 2 in E flat.
    ("Piano Quartet no 2 in E flat major, K. 493",
     "Piano Quartet in E flat major, K493"),
    # K.515 — String Quintet No 3 in C.
    ("String Quintet no.3 in C major, K.515",
     "String Quintet in C major, K515"),
    # K.516 — String Quintet No 4 in G minor. Now foldable: the movement-
    # marker gate (2026-05-29) split the "Adagio … from" excerpt off to
    # §k516|adagio, so the no.4 whole-work group is clean.
    ("String Quintet no.4 in G minor, K.516",
     "Quintet for strings in G minor (K.516)"),
    # K.576 — Piano Sonata No 18 in D. Now foldable: the "Adagio … from"
    # excerpt split off to §k576|adagio via the movement-marker gate.
    ("Piano Sonata No 18 In D major, K576",
     "Piano Sonata in D major (K.576)"),
    # K.331 Rondo alla Turca — the movement-marker gate keys the Rondo
    # excerpt §k331|rondo (its own famous-movement group, distinct from the
    # whole sonata). The "Alla turca, from …" phrasings lead with "Alla"
    # (not a movement name) so they escape the gate — fold them into the
    # §k331|rondo canonical. (The whole sonata and the Fazıl Say fantasy
    # stay separate.)
    ("Alla turca, from 'Piano Sonata No. 11 in A, K. 331'",
     "Rondo alla turca, from Piano Sonata no.11 in A major, K.331"),
    ("Alla turca, from Piano Sonata no.11 in A major, K.331",
     "Rondo alla turca, from Piano Sonata no.11 in A major, K.331"),

    # --- ttn_duplicates straggler harvest (2026-05-30) ----------------------
    # Genuine same-work folds surfaced by the post-alias duplicate detector
    # (high-Jaccard pairs): redundant scoring annotation, word-order, or an
    # added/dropped catalogue ref. Alt-scorings, excerpts, and whole-vs-
    # subset noise from that run are deliberately excluded.

    # Wolf — Italian Serenade (string quartet IS its scoring; key annotation).
    ("Italian Serenade for string quartet", "Italian Serenade"),
    ("Italian Serenade in G major", "Italian Serenade"),
    # Debussy — L'Isle joyeuse (piano work) + Danse sacrée et danse profane
    # (harp+strings is its scoring; L.103 catalogue form).
    ("L'Isle joyeuse for piano", "L'Isle joyeuse"),
    ("Danse sacrée et Danse profane, L. 103",
     "Danse sacree et danse profane for harp and strings"),
    ("Danse sacrée et Danse profane, L.103",
     "Danse sacree et danse profane for harp and strings"),
    ("Danse sacrée et danse profane",
     "Danse sacree et danse profane for harp and strings"),
    # Dvořák — Slavonic Dance Op.72 no.2 (key present/absent); American Quartet.
    ("Slavonic Dance Op.72 No.2", "Slavonic Dance in E minor, Op.72 no.2"),
    ("American Quartet no 12 in F major, Op 96",
     "String Quartet No 12 in F major, Op 96, 'American'"),
    # Brahms — Handel Variations Op 24 (the "by Handel" form, no "G F");
    # Symphony 3 (key); Double Concerto (scoring word-order).
    ("25 Variations and Fugue on a Theme by Handel, Op 24",
     "25 Variations and fugue on a theme by G F Handel, Op 24"),
    ("Symphony no 3 Op 90", "Symphony no 3 in F major, Op 90"),
    ("Double Concerto in A minor, Op.102, for violin, cello and orchestra",
     "Double Concerto in A minor for Violin and Cello, Op 102"),
    # Elgar — Enigma Variations Op 36 ("for orchestra" annotation).
    ("Variations on an original theme (Enigma) Op 36",
     "Variations on an original theme ('Enigma') Op.36 for orchestra"),
    # Chopin — "for piano" annotation / word-order on Op-numbered works.
    ("Barcarolle for piano (Op.60) in F sharp major",
     "Barcarolle in F sharp major, Op 60"),
    ("Ballade for piano no 3 in A flat major, Op 47",
     "Ballade no 3 in A flat major, Op 47"),
    ("Ballade for piano no 4 in F minor, Op 52",
     "Ballade No 4 in F minor Op 52"),
    ("Scherzo for piano no. 2 (Op.31) in B flat minor",
     "Scherzo No 2 in B flat minor, Op 31"),
    ("Scherzo for piano no. 1 (Op.20) in B minor",
     "Scherzo no 1 in B minor, Op 20"),
    ("Sonata No.3 in B minor (Op.58)",
     "Piano Sonata no 3 in B minor, Op 58"),
    ("Sonata no. 2 in B flat minor Op.35 for piano",
     "Piano Sonata no 2 in B flat minor, Op 35"),
    # Schumann — Cello Concerto Op 129 (word-order).
    ("Concerto for cello and orchestra in A minor, Op.129",
     "Cello Concerto in A minor, Op 129"),
    # Clara Schumann — Variations Op 20 (scoring annotation).
    ("Variations on a Theme of Robert Schumann in F sharp minor (Op.20)",
     "Variations on a theme of Robert Schumann for piano in F sharp minor, Op 20"),
    # Berlioz — Le Carnaval romain Op 9 ("overture" added/dropped).
    ("Le Carnaval Romain, Op 9", "Le Carnaval romain overture Op 9"),
    # Vaughan Williams — The Wasps overture ("Overture to" added/dropped).
    ("The Wasps - Aristophanic suite (from incidental music) (1909)",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),
    # Korngold — Violin Concerto Op 35 (word-order).
    ("Concerto in D major Op.35 for violin and orchestra",
     "Violin Concerto in D, Op 35"),
    # Beethoven — Piano Sonata no 18 Op 31/3 (word-order + "for piano").
    ("Sonata no. 18 in E flat major Op.31 no.3 for piano",
     "Piano Sonata no 18 in E flat major, Op 31 no 3"),
    # Nielsen — Wind Quintet Op 43 (word-order).
    ("Quintet for wind (Op.43)", "Wind Quintet (Op.43)"),
    # Ravel — Alborada del gracioso (the standalone vs 'from Miroirs' framing
    # both name the same piece).
    ("Alborada del gracioso, from 'Miroirs'",
     "Alborada del gracioso  'Miroirs' (1905)"),
    # Farkas — 5 Ancient Hungarian Dances (wind-quintet scoring annotation).
    ("5 Ancient Hungarian Dances",
     "5 Ancient Hungarian Dances for wind quintet"),
    # K.285 — Flute Quartet No 1 in D. (Bare D-major group already carries a
    # couple of "Rondo" movement excerpts — pre-existing, not introduced by
    # this fold; the no-1 whole-work form joins them.)
    ("Flute Quartet No.1 in D major, K.285",
     "Flute Quartet in D major, K.285"),
    # K.456 — BBC source typo: the "String Quartet no.19 ... 'Dissonance'"
    # airing is mislabelled K.456 (which is the B-flat Piano Concerto No 18,
    # correctly tagged elsewhere in the same cluster). The title text names
    # the Dissonance Quartet unambiguously, so fold to its real catalogue
    # number K.465 rather than preserve the wrong ref.
    ("String Quartet no.19 in C major K.456, 'Dissonance'",
     'String Quartet in C major (K.465) "Dissonance"'),

    # --- ttn_duplicates harvest, 2nd pass (2026-05-30, siblings guard) -------
    # A second post-alias sweep after the precision pass (bare-number boosts
    # dropped, whole-vs-subset and token-sort siblings suppressed). These are
    # genuine same-work folds: an op number / catalogue ref / accent / nick-
    # name added or dropped, a translated or word-order variant, a redundant
    # scoring annotation matching the work's sole scoring, or an obvious typo.
    # Alt-scorings, arrangements to different forces, movement excerpts, and
    # distinct works of one set are deliberately left split.
    # Beethoven
    ("Coriolan Overture", "Coriolan Overture, Op 62"),
    ("Piano Concerto no 3 in C minor", "Piano Concerto no 3 in C minor, Op 37"),
    ("Concerto for piano and orchestra no. 3 in C minor",
     "Piano Concerto no 3 in C minor, Op 37"),
    ("String Quartet in C sharp minor, Op 131",
     "String Quartet no.14 (Op.131) in C sharp minor"),
    # Debussy
    ("L' Isle joyeuse", "L'Isle joyeuse"),
    ("L'isle joyeuse, L.106", "L'Isle joyeuse"),
    ("La Mer, L.109", "La Mer"),
    ("Estampes, L.100", "Estampes"),
    # Mendelssohn (Felix)
    ("The Hebrides - overture", "The Hebrides, Op 26"),
    ("Symphony No.3 in A minor (Op.56), 'Scottish' (Andante con moto - "
     "allegro un poco; Vivace non troppo; Adagio; Allegro un poco)",
     "Symphony no 3 in A minor, Op 56 'Scottish'"),
    # Sibelius
    ("Finlandia", "Finlandia, Op 26"),
    ("Symphony no 5 in E flat major", "Symphony no 5 in E flat major, Op 82"),
    # Elgar
    ("Enigma Variations, op. 36",
     "Variations on an original theme ('Enigma') Op.36 for orchestra"),
    # Suk
    ("Elegy (Under the impression of Zeyer's Vyšehrad), Op 23, arranged "
     "for piano trio", "Elegy Op 23 arr. for piano trio"),
    # Saint-Saëns
    ("Havanaise", "Havanaise, Op 83"),
    ("Bassoon Sonata in G major", "Bassoon Sonata in G major, Op 168"),
    ("Bassoon Sonata in G major,Op.168", "Bassoon Sonata in G major, Op 168"),
    ("Danse Macabre", "Danse macabre, Op 40"),
    # Berlioz
    ("Le Carnaval Romain - overture", "Le Carnaval romain overture Op 9"),
    ("Le Carnaval romain, op. 9, overture after 'Benvenuto Cellini'",
     "Le Carnaval romain overture Op 9"),
    # Barber
    ("Adagio for Strings", "Adagio for Strings, Op 11"),
    # (Tchaikovsky Rococo "original version" deliberately NOT folded: the
    # autograph original is musically distinct from the Fitzenhagen-edited
    # standard version — see test_tchaikovsky_rococo_original_version_stays_split.)
    # Chopin
    ("Ballade in A flat, Op 47", "Ballade no 3 in A flat major, Op 47"),
    ("Scherzo No.2 in B flat, Op.31", "Scherzo No 2 in B flat minor, Op 31"),
    ("Scherzo No 2 B flat minor, Op 31", "Scherzo No 2 in B flat minor, Op 31"),
    ("Sonata in B flat minor (Op.35)",
     "Piano Sonata no 2 in B flat minor, Op 35"),
    ("Piano Sonata No 2, Op 35", "Piano Sonata no 2 in B flat minor, Op 35"),
    ("Piano Sonata no 2 in B flat minor, Op 35 'Funeral March'",
     "Piano Sonata no 2 in B flat minor, Op 35"),
    ("Piano sonata no 2 in B flat minor, Op 35 'Marche funebre'",
     "Piano Sonata no 2 in B flat minor, Op 35"),
    ("Concerto for piano and orchestra no.1 (Op.11) in E minor",
     "Piano Concerto no 1 in E minor, Op 11"),
    # Smetana — Vltava (accent / parenthetical translation)
    ("Vltava (Moldau), from 'Má vlast' (My Homeland)",
     "Vltava (Moldau) - from 'Ma Vlast'"),
    ("Vltava from Má vlast", "Vltava (Moldau) - from 'Ma Vlast'"),
    ("Vltava from Má vlast - My Homeland", "Vltava (Moldau) - from 'Ma Vlast'"),
    # Grieg
    ("String Quartet No 1 in G minor", "String Quartet no 1 in G minor, Op 27"),
    # Schubert — Great C major (D.944; trailing semicolon variant)
    ('Symphony No. 9 in C major, "Great";',
     'Symphony no 9 in C major, D.944 "Great"'),
    # Clara Schumann
    ("Variations on a theme by Robert Schumann for piano in F sharp minor, "
     "Op 20",
     "Variations on a theme of Robert Schumann for piano in F sharp minor, "
     "Op 20"),
    ("Variations on a Theme of Robert Schumann, Op 20",
     "Variations on a theme of Robert Schumann for piano in F sharp minor, "
     "Op 20"),
    ("Quatre pièces fugitives, Op 15", "4 Pieces fugitives for piano, Op 15"),
    # Vaughan Williams — The Wasps overture. (Only the "Incidental Music"
    # phrasing folded here; "Overture from The Wasps - An Aristophanic suite"
    # is left in its existing multiplay group — see
    # test_audit_reairing_variants_collapse_to_one_group.)
    ("The Wasps - Overture from the Incidental Music",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),
    # Dvořák
    ("Cello Concerto No.2 in B minor, Op 104",
     "Cello Concerto in B minor, Op 104"),
    ("Piano Quintet in A major (B.155) (Op.81)",
     "Piano Quintet in A major, Op 81"),
    ("Symphony No.9 in E minor Op 95 'From the New World' (Adagio - allegro "
     "molto; Largo; Molto vivace - poco sostenuto; Allegro con fuoco)",
     "Symphony no 9 in E minor, Op 95 'From the New World'"),
    # Holst
    ("St Paul's Suite in C, op. 29/2", "St Paul's Suite, Op 29 no 2"),
    # Prokofiev — Classical Symphony
    ("Symphony No.1 in D major, 'Classical'",
     "Symphony No 1 in D major, Op 25, 'Classical'"),
    # Brahms
    ("Symphony No.3 in F major", "Symphony no 3 in F major, Op 90"),
    ("Academic Festival Overture", "Academic Festival Overture, Op 80"),
    ("3 Songs for choru, Op 42", "3 Songs for chorus, Op 42"),
    # Handel — Water Music suite (HWV 350; the "No. 3" suite number)
    ("Water Music, Suite No. 3 in G, HWV 350",
     "Water Music: Suite in G major for 'flauto piccolo' HWV 350"),
    # Shostakovich
    ("Sonata for cello and piano (Op.40) in D minor",
     "Cello Sonata in D minor, Op 40"),
    # Schütz
    ("Magnificat anima mea Dominum SWV 468",
     "Magnificat anima mea Dominum, SWV468"),
    # Fanny Mendelssohn
    ("Allegro moderato for piano, Op 8 no 1",
     "Allegro moderato (Song without words), Op 8 No 1 (1840)"),
    # Purcell
    ('Rejoice in the Lord alway, Z 49 (Bell Anthem)',
     'Rejoice in the Lord alway (Z.49) "Bell Anthem"'),
    # Pylkkänen
    ("Suite for oboe and strings,Op.32", "Suite for oboe and strings, Op 32"),
    # Liszt — Hungarian Rhapsody No 2 (S.244/2 catalogue added)
    ("Hungarian Rhapsody No 2, S244/2",
     "Hungarian Rhapsody No 2 in C sharp minor"),
    # Spohr
    ("Fantasie and variations on a theme of Danzi in B flat, Op 81",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),
    # Rimsky-Korsakov
    ("Capriccio espagnol", "Capriccio Espagnol, Op 34"),
    # Mahler — Symphony 4 (soprano finale; scoring annotation)
    ("Symphony No 4 in G major for soprano and orchestra",
     "Symphony No 4 in G major"),
    # Stenhammar
    ("Spring Night", "Varnatt (Spring Night)"),
    # Ibert — Trois Pièces Brèves (wind quintet IS its scoring)
    ("Trois Pieces Breves for wind quintet", "Trois Pieces Breves"),
    # Palestrina — Stabat Mater (8 voices IS its scoring)
    ("Stabat Mater for 8 voices", "Stabat Mater"),
    # Wolf — the spurious-"Op 120" string-quartet phrasing (string quartet IS
    # the Italian Serenade's scoring; Wolf has no Op 120). Missed in the first
    # pass of this batch; the bare "...in G major" form was already folded.
    ("Italian Serenade in G major for string quartet, Op 120",
     "Italian Serenade"),
    # Fanny Mendelssohn — Allegro moderato, Op 8 No 1 (third phrasing).
    ("Allegro moderato (Op.8 No.1) (1840)",
     "Allegro moderato (Song without words), Op 8 No 1 (1840)"),

    # --- Catalogue-ref typos / incomplete refs (2026-05-30) -----------------
    # Surfaced auditing the different-ref §-key false-positive class in
    # ttn_duplicates: a handful of pairs there were one work under a mistyped
    # or truncated catalogue number, not two adjacent works. Folding them to
    # the correct ref both fixes the grouping and lets the new "distinct §-ref
    # = distinct work" detector guard stay clean.
    # Schubert — D66 is a typo for D667 (the Trout Quintet; no D66 Trout).
    ('Piano Quintet in A major, D66), (Trout)',
     'Piano Quintet in A major (D.667) "Trout"'),
    # Bach — "BWV 1008o" carries a stray 'o' (Cello Suite No 2 is BWV 1008).
    ("Cello Suite No 2 in D minor, BWV 1008o",
     "Cello Suite no 2 in D minor, BWV 1008"),
    # Telemann — Sonata Polonaise is TWV 42:a8; bare "TWV 42" / "(TWV.42: A
    # minor 8)" are incomplete renderings of the same work.
    ("Sonata Polonaise in A minor for violin, viola and continuo TWV 42",
     "Sonata Polonaise in A minor for violin, viola and continuo, TWV.42:a8"),
    ("Sonata Polonaise in A minor for violin, viola and continuo "
     "(TWV.42: A minor 8)",
     "Sonata Polonaise in A minor for violin, viola and continuo, TWV.42:a8"),
    # Telemann — the D-minor Musique de table quartet is TWV 43:d1; "TWV 42."
    # and "TWV 42:d1" are ref errors for the same (identically-titled) work.
    ("Quartet in D Minor for flutes and basso continuo from 'Musique de "
     "Table' TWV 42.",
     "Quartet in D minor for flutes and bass continuo from 'Musique de "
     "Table' TWV 43:d1"),
    ("Quartet in D minor for flutes and basso continuo from 'Musique de "
     "Table', TWV 42:d1",
     "Quartet in D minor for flutes and bass continuo from 'Musique de "
     "Table' TWV 43:d1"),

    # --- Mozart audit, rest of catalogue (2026-05-29) -----------------------
    # Same numbered-vs-unnumbered / keyless / alt-Köchel / redundant-scoring
    # catalogue-path splits as the quartets batch, across the instrumental
    # and concert-aria repertoire. Each pair verified chain-safe and
    # composer-exclusive (or, for Ave verum, cross-composer-safe via
    # composer-scoped grouping). Excerpt-vs-whole splits, set-catalogue
    # siblings, and multi-work programme items are deliberately left split.

    # Symphonies / concertos / chamber: keyless or phantom-ordinal variants.
    ("Symphony No.35 (K. 385) 'Haffner'",
     "Symphony no 35 in D major, K.385, \"Haffner\""),
    ("Piano Concerto in B flat major, K.595",
     "Piano Concerto no 27 in B flat major, K.595"),
    ("Sinfonia Concertante (K.364)",
     "Sinfonia Concertante in E flat major, K364"),
    ("Sinfonia concertante for oboe, clarinet, horn, bassoon and orchestra (K.297b)",
     "Sinfonia concertante in E flat major, K297b"),
    ("Piano Sonata No 13 in B flat major, K333",
     "Sonata in B flat (K.333)"),
    ("Piano Trio no 2 in E flat, K.498 'Kegelstatt'",
     "Trio for piano, clarinet and viola in E flat major, K498, 'Kegelstatt'"),
    ("Violin Sonata no 18 in G major, K301",
     "Sonata for violin and keyboard (K.301) in G major"),
    ("Piano Trio no 3 in B flat major, K. 502",
     "Piano Trio in B flat major, K 502"),
    ("Flute Concerto No. 2 in D, K. 314",
     "Flute Concerto in D major, K314"),
    # K.525 Eine kleine Nachtmusik — existing canonical is the No.13 form;
    # fold the Serenade-in-G phrasing into it (matching direction, no chain).
    ("Serenade in G major, K525 'Eine kleine Nachtmusik'",
     "Eine kleine Nachtmusik (Serenade No.13 in G) (K.525)"),
    # K.388 Serenade No 12 in C minor — alt-Köchel K.384a + "no 12" variants.
    ("Serenade (K.388) in C minor for wind octet (K.384a)",
     "Serenade in C minor for Wind Octet (K.388)"),
    ("Serenade No. 12 in C minor, K. 388",
     "Serenade in C minor for Wind Octet (K.388)"),
    # K.299 Flute & Harp Concerto — alt-Köchel 297c (one BBC typo "277c").
    ("Concerto for Flute and Harp in C, K.299/277c",
     "Concerto for Flute, Harp and Orchestra in C major, K.299"),
    ("Concerto for Flute and Harp in C, K. 299/297c",
     "Concerto for Flute, Harp and Orchestra in C major, K.299"),
    # K.365 Concerto for 2 pianos — alt-Köchel 316a + "no 10" variants.
    ("Concerto for 2 pianos in E flat major, K365/316a",
     "Concerto for 2 pianos and orchestra in E flat major (K.365)"),
    ("Piano Concerto no 10 in E flat for Two Pianos, K. 365",
     "Concerto for 2 pianos and orchestra in E flat major (K.365)"),
    # K.242 Concerto No 7 for 3 pianos — bare form lacks the "no 7".
    ("Concerto in F major K.242 for 3 pianos and orchestra",
     "Concerto no 7 for 3 pianos and orchestra in F major (K.242)"),
    # K.254 Divertimento in B flat — "B-flat"/"B major" spelling vs "B flat".
    ("Divertimento in B flat major for violin, cello and piano, K.254",
     "Divertimento in B-flat major for violin, cello and piano, K254"),
    # K.32 Gallimathias musicum — key-sig added / spelling variant.
    ("Galimathias musicum in D, K 32",
     "Gallimathias Musicum (K.32)"),

    # Variations / church sonatas / cantata: count-prefix or scoring variants.
    ("Variations on 'Ah, vous dirai-je, Maman' in C major, K.265",
     "12 Variations on 'Ah! Vous dirai-je, maman' (K.265)"),
    # K.212 / K.328 Kirchen-Sonaten — redundant scoring annotation; K.328
    # also carries alt-Köchel 317c.
    ("Kirchen-Sonate in B flat (K. 212) for 2 violins, double bass and organ",
     "Kirchen-Sonate in B flat, K212"),
    ("Church Sonata no 15 in C, K.328 (317c)",
     "Kirchen-Sonate no 15 in C major for 2 violins, bass and solo organ, K.328"),
    # K.469 Davidde Penitente — redundant "cantata for …" scoring annotation.
    ("Davidde Penitente (K.469) - cantata for 2 sopranos, tenor, choir and orchestra",
     "Davidde Penitente, K 469"),
    # K.549 Notturni — number-word vs digit.
    ("4 Notturni",
     "Four Notturni"),
    # K.618 Ave verum corpus — fold the "motet for chorus and strings"
    # scoring form into the bare token canonical (cross-composer-safe).
    ("Ave Verum Corpus (K.618) (motet for chorus and strings)",
     "Ave verum corpus"),

    # Standalone concert arias (not opera excerpts) — phrasing variants fold,
    # same precedent as K.418 'Vorrei spiegarvi'.
    ("Ch'io mi scordi di te ...? Non temer, amato bene, K.505",
     "Concert aria: Ch'io mi scordi di te...? Non temer, amato bene (K.505)"),
    ("Concert aria: Non piu, tutto ascoltai... Non temer amato bene, K.490",
     "Non piu, tutto ascoltai...Non temer amato bene, K490"),
    ("Concert aria \"Bella mia fiamma...Resta, O cara\" (K.528)",
     "Bella mia fiamma - Resta, o cara, K.528"),
    ("\"Basta vincesti\" (recit) and \"Ah, non lasciami\" (aria) (K.486a)",
     "Basta vincesti ... Ah, non lasciarmi K.486a"),
    # K.584 Rivolgete a lui lo sguardo — the alternate Così aria; fold the
    # "from Così fan tutte" phrasings into the existing K.584 canonical.
    ("Rivolgete a lui lo sguardo, K.584 (from 'Cosi fan tutte')",
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),
    ("Aria: 'Rivolgete a lui lo sguardo' (from \"Cosí fan tutte\", Act 1)",
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),

    # --- Mozart audit, opera overtures & arias (2026-05-29) -----------------
    # Overtures: the BBC phrases each opera overture many ways (English vs
    # Italian/German title, "opera in N acts" tail, with/without K). They all
    # name the same overture, so they fold to one group. None of these operas
    # airs whole in the corpus (verified), so there's no overture/whole-opera
    # collision to worry about here. Arias are folded only with OTHER
    # phrasings of the SAME aria — never into the overture, and never across
    # different arias.

    # K.492 Le Nozze di Figaro — overture (English + Italian phrasings).
    ("Marriage of Figaro - overture",
     "Le Nozze di Figaro, K492, Overture"),
    ("The Marriage of Figaro (Overture)",
     "Le Nozze di Figaro, K492, Overture"),
    ("Le Nozze di Figaro - overture",
     "Le Nozze di Figaro, K492, Overture"),
    ("Overture to Le Nozze di Figaro",
     "Le Nozze di Figaro, K492, Overture"),
    ("Overture to Le Nozze di Figaro - opera in 4 acts K.492",
     "Le Nozze di Figaro, K492, Overture"),
    # K.527 Don Giovanni — overture ("opera in 2 acts" tail).
    ("Overture from Don Giovanni - opera in 2 acts (K.527)",
     "Overture from 'Don Giovanni' (K.527)"),
    # K.620 Die Zauberflöte — overture (English "Magic Flute" → German group).
    ("Overture to the Magic Flute",
     "Overture from Die Zauberflote (K 620)"),
    ("The Magic Flute (overture)",
     "Overture from Die Zauberflote (K 620)"),
    # K.486 Der Schauspieldirektor — overture into the existing canonical.
    ("Overture - from Der Schauspieldirektor, singspiel in 1 act (K.486)",
     "Der Schauspieldirektor - singspiel in 1 act (K.486)"),

    # Arias — same-aria phrasing folds (cross-language opera name + locator
    # rewording). Deliberately NOT folded into the overtures above.
    # K.492 Figaro: 'Dove sono' (Countess) and 'Deh vieni' (Susanna).
    ("'Dove sono i bei momenti' - Countess' aria from The Marriage of Figaro. K.492",
     "Recit and aria 'Dove Sono' - from Act III of Le Nozze di Figaro, K.492"),
    ("Aria: Deh vieni, non tardar - from Le Nozze di Figaro",
     "Le Nozze di Figaro, Act 4: Susanna's aria 'Deh vieni, non tardar'"),
    # K.620 Zauberflöte: 'Ein Mädchen oder Weibchen' (two phrasings).
    ("Ein Mädchen oder Weibchen - from 'Die Zauberflöte' K 620, Act 2",
     "\"Ein Mädchen oder Weibchen\" - from 'Die Zauberflöte' (K620), Act 2"),
    # K.588 Così: 'Un'aura amorosa' phrasing into the existing canonical.
    ("Aria: \"Un'aura amorosa\" from Cosi fan tutte (K.588), Act 1",
     "Aria: \"Un'aura amorosa\" from the opera 'Così fan tutte' (K.588), Act 1"),

    # --- Haydn audit (2026-05-29) -------------------------------------------
    # Haydn fragments heavily across Hoboken-format variants: H.1.6 vs
    # Hob.I:6 vs Hob.1.6, roman vs arabic (Hob.VIIb vs Hob.7b), colon vs
    # slash vs period, with/without the Hob ref, backtick ordinals
    # ("Op.76`3" → glued "763"). Each group below is ONE work whose variants
    # the token sort / catalogue path left split; distinct set-catalogue
    # siblings (different Op/Hob numbers) and movement excerpts stay split.

    # Symphonies — nickname works fragmenting across H./Hob. forms.
    ("Symphony no 6 in D major 'Le Matin'",
     'Symphony no 6 in D major (H.1.6) "Le Matin"'),
    ("Symphony no 6 in D, Hob. I:6 'Le matin'",
     'Symphony no 6 in D major (H.1.6) "Le Matin"'),
    ("Symphony No 92 in G, Hob I:92 'Oxford'",
     'Symphony No 92 (H.1.92) in G major, "Oxford"'),
    ("Symphony No 92 'Oxford'",
     'Symphony No 92 (H.1.92) in G major, "Oxford"'),
    ("Symphony No 73 in D major, Hob.1.73,  'La Chasse'",
     "Symphony no 73 in D major 'La Chasse' (H.1.73)"),
    ("Symphony no 49 in F minor, Hob.I:49 'La Passione'",
     'Symphony No.49 in F minor (Hob.1.49)  "La Passione"'),
    ("Symphony No 49 in F minor H.1.49 (La Passione)",
     'Symphony No.49 in F minor (Hob.1.49)  "La Passione"'),
    ("Symphony no.49 in F minor, H.I:49, 'La Passione'",
     'Symphony No.49 in F minor (Hob.1.49)  "La Passione"'),
    ("Symphony No. 104 in D, Hob. I:104 'London'",
     "Symphony no 104 in D major, 'London', Hob.1.104"),
    ("Symphony No 43 in E flat, 'Mercury'",
     "Symphony No 43 in E flat major, Hob.1.43, 'Mercury'"),
    ("Symphony No. 43 in E flat, Hob. I:43 ('Mercury')",
     "Symphony No 43 in E flat major, Hob.1.43, 'Mercury'"),
    ('Symphony No.100 in G major, "Military"',
     'Symphony no 100 in G major, Hob.1.100 "Military"'),

    # String quartets — Op N/M nickname works split by Hob ref, backtick
    # ordinals, "Quartet for strings" wording, redundant Hob.III refs.
    ("String Quartet in D major (Op. 64 No.5) 'The Lark'",
     'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"'),
    ("String Quartet in D major, Op 64 no 5 'Lark'",
     'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"'),
    ('Quartet for strings Op 64 No 5 in D major "Lark"',
     'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"'),
    ("String Quartet no 62 in C Major, Op 76 no 3 'Emperor'",
     "String Quartet No.62 in C Major, Op.76'3 'Emperor'"),
    ("String Quartet in C major Op 76`3 (Emperor)",
     "String Quartet No.62 in C Major, Op.76'3 'Emperor'"),
    ("Quartet in C major Op 76`3 (Emperor)",
     "String Quartet No.62 in C Major, Op.76'3 'Emperor'"),
    ("Quartet for strings (Op.76, No.1) in G major",
     "String Quartet in G major (Op.76 No.1)"),
    ('Quartet for strings (Op.77`1) in G major Hob III/81 "Lobkowitz"',
     "String Quartet in G major Op 77 No 1"),
    ("String Quartet in G major, Op.77'1, Hob.III:81 'Lobkowitz'",
     "String Quartet in G major Op 77 No 1"),
    ("String Quartet (Op.77'1) in G major",
     "String Quartet in G major Op 77 No 1"),
    ("String Quartet in B minor, Op.33'1",
     "String Quartet in B minor, Op 33 no 1"),
    ("String Quartet no 30 in E flat, Op 33 no 2 'The Joke'",
     "String Quartet in E flat major, Op.33 No.2, 'Joke'"),
    ("Quartet for strings Op 33'2 in E flat major 'Joke'",
     "String Quartet in E flat major, Op.33 No.2, 'Joke'"),
    ('String Quartet (Op.33\'2) in E flat major "Joke"',
     "String Quartet in E flat major, Op.33 No.2, 'Joke'"),
    ("String Quartet in G minor, Op 20 no 3, Hob.III:33",
     "String Quartet in G minor, Op 20, No 3"),
    ("String Quartet in C major, Op 20`2",
     "String Quartet in C major, Op 20 No 2"),
    ("Quartet for strings (Op.42) in D minor",
     "String Quartet in D minor, Op 42"),

    # Chamber / concertos / divertimenti.
    ("String Trio in B flat major, Op 53 No 2, arr. from Piano Sonata, H.16.41",
     "Trio for strings in B flat major, Op 53 no 2"),
    ("Trio for keyboard and strings in G major (H. 15.25) 'Gypsy Rondo'",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),
    ("Cello Concerto No. 1 in C, Hob. 7b:1",
     "Cello Concerto No. 1 in C, Hob. VIIb:1"),
    ("Cello Concerto in D major, Hob. 7b:2",
     "Cello Concerto in D major, Hob.VIIb No.2"),
    ("Sinfonia concertante in B flat major, Hob.1:105",
     "Sinfonia Concertante in B flat, Hob. I:105"),
    # London Trio No 1 in C (Hob.IV:1) — remaining forms into the §hob4 group.
    ("Divertimento in C, Hob. IV:1 (attacca)",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),
    ("Divertimento in C major, Hob.IV No.1",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),
    ("Divertimento in C major (Hob.IV No.1) (London Trio No.1)",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),
    ("Divertimento in C major, Hob.IV No 1 'London Trio'",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),
    # London Trio No 1 — "for 2 flutes and cello" scoring forms (Hob.4.1
    # period parses as a separate key) and the bare no-Hob form.
    ("Divertimento for 2 flutes and cello  in C major , Hob.4.1, 'London trio' No 1",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),
    ('Divertimento for 2 flutes and cello (H.4.1) in C major "London trio" No.1',
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),
    ('Divertimento in C major, "London Trio" No 1',
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),
    # London Trio No 4 in G — "Hob.IV No.4" form into the Hob.IV:4 group.
    ("Divertimento in G major Hob.IV No.4 (London Trio No.4)",
     "Divertimento in G major, Hob.IV:4 (London Trio No.4)"),

    # Keyboard sonata Hob.XVI:52 — slash vs colon, "No 52" vs catalogue.
    ("Keyboard Sonata No 52 in E Flat,  Hob XVI/52",
     "Keyboard Sonata in B flat, Hob. XVI:52"),
    ("Keyboard Sonata no 52 in E Flat, Hob.XVI/52",
     "Keyboard Sonata in B flat, Hob. XVI:52"),

    # Vocal / choral / overtures.
    ("Mass No. 9 in C, Hob. XXII:9 'Missa in tempore belli'",
     "Mass in C major, Missa in tempore belli 'Paukenmesse' H.22.9"),
    ("Missa in tempore belli (Hob. XXII. 9) 'Paukenmesse'",
     "Mass in C major, Missa in tempore belli 'Paukenmesse' H.22.9"),
    ("L'Isola disabitata - Overture/Sinfonia",
     "Overture, L'Isola disabitata"),
    ("Overture to  Speziale (H.28.3)",
     "Overture to Lo Speziale, H.28.3"),
    ("Overture to Lo Speziale",
     "Overture to Lo Speziale, H.28.3"),
    ("Der Sturm - chorus for SATB choir and orchestra (H.24a.8)",
     "Der Sturm (The Storm) - madrigal for chorus and orchestra (H.24a.8)"),
    ("Der Sturm, H.24a.8",
     "Der Sturm (The Storm) - madrigal for chorus and orchestra (H.24a.8)"),
    ("The Creation, H.21.2",
     "The Creation - oratorio, Hob XXI:2"),
    ("Variations on the hymn 'Gott erhalte Franz den Kaiser'",
     "Variations about the hymn 'Gott erhalte'"),
    ("The Mermaid's song (H.26a.25) from 6 Original canzonettas set 1",
     "The Mermaid's song, H.26a.25"),

    # --- Haydn re-audit (2026-05-29) ----------------------------------------
    # Surfaced after the audit tool learned roman-numeral Hob refs + edge-
    # apostrophe tokenization (commit 6e711aa): one work split across Hob
    # notations that previously scattered into separate clusters. Mostly
    # roman-colon (Hob.I:103) vs arabic-period (Hob.1/103) vs "H." prefix
    # (H.XVI.33) of the same work.

    # Symphonies — second-pass Hob-notation splits.
    ("Symphony No 103 in E flat major, Hob.1/103 ('Drum roll')",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),
    ("Symphony no 100 in G major, Hob. I:100 'Military'",
     "Symphony no 100 in G major, Hob.1.100 \"Military\""),
    ("Symphony No 95 in C minor, Hob I:95",
     "Symphony No 95 in C minor, Hob.1.95"),
    ("Symphony No 60 in C major, Hob.1.60, 'Il distratto'",
     "Symphony no 60 in C major 'Il distratto' (Hob.1:60)"),
    # "H.1.NNN" prefix forms (the audit's Hob bucket can't see "H." prefix);
    # these are the dominant Drum-Roll / 95 spellings, plus bare forms.
    ("Symphony no 103 in E flat major \"Drum Roll\" (H.1.103)",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),
    ("Symphony No 103 in E flat major \"Drumroll\"",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),
    ("Symphony No. 103 in E flat major 'Drum Roll'",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),
    ("Symphony No 95 in C minor H.1.95",
     "Symphony No 95 in C minor, Hob.1.95"),
    ("Symphony No 95 in C minor",
     "Symphony No 95 in C minor, Hob.1.95"),

    # String quartets.
    ("Quartet for strings in G major Hob III:81 'Lobkowitz'",
     "String Quartet in G major Op 77 No 1"),
    # Hob.III:69 — "Op 7 No 1" is a BBC mislabel of Op 71 No 1.
    ("String Quartet in B flat major (Op.7 No.1) (Hob III:69)",
     "String Quartet in B flat major, Op 71 no 1 (Hob III:69)"),

    # Keyboard sonatas — colon vs slash, and "H." prefix vs "Hob.".
    ("Sonata in D, HobXVI:37",
     "Keyboard Sonata in D major, Hob.XVI/37"),
    ("Piano Sonata in D major, H.XVI.33",
     "Piano Sonata in D major, Hob.XVI.33"),
    ("Sonata for piano (H.XVI.33) in D major",
     "Piano Sonata in D major, Hob.XVI.33"),

    # Piano trios — Hob.15.NN period vs Hob XV:NN colon, H. prefix.
    ("Piano Trio in C major,  Hob.15.27",
     "Piano trio in C major Hob XV:27"),
    ("Piano Trio in A major, Hob 15.18",
     "Keyboard Trio No.18 in A major (Hob XV:18)"),
    ("Trio Sonata in E flat major (H.XV.29)",
     "Piano Trio in E flat major, Hob:15.29"),
    # Gypsy Rondo (Hob.XV:25 = H.15.25 = No 39) — five canonicals unify.
    ("Piano Trio No 39 in G Hob XV:25",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),
    ("Piano Trio in G major, 'Gypsy rondo' Hob.15.25",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),
    ("Piano Trio in G major, H15.25 'Gypsy rondo'",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),
    ("Piano Trio in G major, Hob XV:25",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),
    ("Trio for keyboard and strings in G major, 'Gypsy rondo'",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),

    # Divertimenti / Feldpartita (Hob.II:46).
    ("Divertimento in B flat, Hob.II:46",
     "Divertimento 'Feldpartita' in B flat major, Hob.2.46"),
    ("Divertimento in B flat major H.2.46 arr. for wind quintet",
     "Divertimento 'Feldpartita' in B flat major H.2.46 arr. for wind quintet"),

    # Cello Concerto No 1 (Hob.7b.1 period form).
    ("Cello Concerto no 1 in C major, Hob.7b.1",
     "Cello Concerto No. 1 in C, Hob. VIIb:1"),

    # L'Isola disabitata overture — the Hob.Ia:13 form.
    ("Overture to 'L'isola disabitata', Hob.Ia:13",
     "Overture, L'Isola disabitata"),

    # --- Wagner audit (2026-05-29) ------------------------------------------
    # Mostly opera-excerpt phrasing folds. Same-excerpt phrasings fold;
    # DIFFERENT excerpts stay split — Prelude vs Liebestod vs the combined
    # "Prelude and Liebestod", Act 1 vs Act 3 preludes, Prelude vs Good
    # Friday Music. Piano/organ arrangements kept separate from the original.

    # Siegfried Idyll — "for small orchestra" scoring annotation folds in.
    ("Siegfried Idyll for small orchestra",
     "Siegfried Idyll"),

    # Tristan und Isolde — Prelude (Act 1) alone; phrasing variants.
    ("Prelude to 'Tristan and Isolde'",
     "Tristan and Isolde (Prelude)"),
    ("Tristan und Isolde: Prelude to Act 1",
     "Tristan and Isolde (Prelude)"),
    # Tristan — the combined "Prelude and Liebestod" (distinct from Prelude
    # alone and from Liebestod alone).
    ("Prelude and Liebestod from 'Tristan und Isolde'",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),
    ("Prelude and Isolde's Liebestod - from \"Tristan & Isolde\"",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),
    ("Prelude and Isolde's Liebestod - from 'Tristan und Isolde'",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),
    ("Prelude and Liebestod - from Tristan and Isolde",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),

    # Die Meistersinger — Act 1 Prelude (bare "Prelude" = Act 1 by default);
    # Act 3 prelude and the arias stay separate.
    ("Prelude to Die Meistersinger von Nurnberg",
     "Prelude to Act 1 from 'Die Meistersinger von Nurnberg'"),
    ("Prelude (Act 1 'Die Meistersinger von Nurnberg')",
     "Prelude to Act 1 from 'Die Meistersinger von Nurnberg'"),

    # Der fliegende Holländer — Daland's aria (Die/Der spelling).
    ("Mögst du, mein kind (Daland's aria) - from Der Fliegende Holländer, Act 2",
     "\"Mogst du, mein kind\" (Daland's aria from Act II Die Fliegende Hollander)"),

    # Tannhäuser — Wolfram's aria 'O du mein holder Abendstern' (Act 3).
    ("Recitative and aria \"O du mein holder Abendstern\" from Tannhäuser (Act 3)",
     "O du mein holder Abendstern – from \"Tannhauser\""),
    ("Recitative and aria \"O du mein holder Abendstern\" (Evening Star), from 'Tannhäuser' (Act 3)",
     "O du mein holder Abendstern – from \"Tannhauser\""),
    ("O du mein holder Abendstern - from 'Tannhäuser', Act 3",
     "O du mein holder Abendstern – from \"Tannhauser\""),

    # Parsifal — Prelude (Act 1); Good Friday Music stays a distinct excerpt.
    ("Prelude to Act 1 of 'Parsifal'",
     "Prelude to Parsifal"),

    # Lohengrin — Act 1 Prelude ("Act I" roman = Act 1); Act 3 stays split.
    ("Lohengrin - Prelude to Act 1",
     "Prelude to Act 1 from Lohengrin"),
    ("Prelude to Act I of 'Lohengrin'",
     "Prelude to Act 1 from Lohengrin"),

    # Wesendonck-Lieder cycle — Wesendonk/Wesendonck spelling.
    ("Fünf Lieder von Mathilde von Wesendonk",
     "Funf Lieder von Mathilde von Wesendonck"),

    # Isolde's Liebestod, Liszt piano transcription S.447.
    ("Isolde's Liebestod transc. for piano (S.447)",
     "Isolde's Liebestod transc. Liszt for piano, S447"),

    # Tannhäuser — Overture + Venusberg Music (the concert/Paris version).
    ("Overture and Venusberg Music, from 'Tannhäuser'",
     "Tannhauser: Overture; Venusberg music (concert version)"),

    # Faust Overture, WWV 59.
    ("Overture to 'Faust' WWV 59",
     "Faust Overture, WWV 59"),

    # --- Catalogue-path phantom-ordering: sonatas batch (2026-05-26) ---------
    # Same shape as the earlier batch — BBC inconsistently includes one of
    # several legitimate identifiers per work (sonata index, opus number,
    # movement marker, scoring digit). Each variant key was verified
    # corpus-exclusive before adding.

    # Mozart K.332 — Piano Sonata No 12 in F. Bare form folds into the
    # no-12 form. (The "2nd mvt Adagio" excerpt now keys §k332|adagio via
    # the movement-marker gate, kept distinct from the whole sonata.)
    ("Sonata for piano K.332 in F major",
     "Piano Sonata no 12 in F major, K.332"),

    # Schubert D.845 — Piano Sonata No 16 in A minor. Also published as
    # Op. 42, so titles alternate between catalogue + opus references.
    ("Piano Sonata no 16 in A minor, D.845",
     "Piano Sonata in A minor D.845, Op 42"),
    ("Piano Sonata in A minor, D845",
     "Piano Sonata in A minor D.845, Op 42"),

    # Schubert D.960 — Piano Sonata No 21 in B flat. Bare form fold-in.
    ("Piano Sonata in B flat major, D.960",
     "Piano Sonata no 21 in B flat major, D.960"),

    # Scarlatti K.88 — Sonata in G minor. The "arranged for 2 harpsichords"
    # variant is the most-aired form (an arrangement preserved); fold bare
    # into it.
    ("Sonata in G minor, K88",
     "Sonata in G minor (K 88) arranged for 2 harpsichords"),

    # Bach BWV.1001 — Violin Sonata No 1 in G minor. Bare form folds into
    # the no-1 form. (The "Adagio & Fugue - 2 movements from" excerpt now
    # keys §bwv1001|adagio,fugue via the movement-marker gate.)
    ("Sonata for violin solo in G minor, BWV.1001",
     "Sonata for violin solo no 1 in G minor, BWV.1001"),

    # Schubert D.959 — Piano Sonata No 20 in A. Most-aired form is the
    # Andantino excerpt (movement of the same work).
    ("Piano Sonata no 20 in A, D. 959",
     "Andantino (second movement) from Piano Sonata in A major, D.959"),

    # Schubert D.850 — Piano Sonata No 17 in D. Op.53 variant + bare variant.
    ("Sonata (Op.53) in D major (D.850)",
     "Piano Sonata no 17 in D major, D.850"),
    ("Sonata in D major D.850 for piano",
     "Piano Sonata no 17 in D major, D.850"),

    # Mozart K.330 — Piano Sonata No 10 in C. Bare form fold-in.
    ("Piano Sonata in C K.330",
     "Piano Sonata no 10 in C major, K.330"),

    # Handel HWV.363a — Op. 1 No. 5 oboe sonata in F. Bare form (lacks Op
    # numbering) fold-in.
    ("Sonata in F major, HWV.363a vers. oboe & bc",
     "Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc"),

    # Handel HWV.362 — Op. 1 No. 4 oboe sonata in A minor; the violin
    # version is a long-standing arrangement of the same work. Same-work,
    # two-scorings (parallel to the BWV.1056 oboe-reconstruction case).
    ("Sonata for oboe and continuo, HWV.362",
     "Violin Sonata in A minor (Op.1 No.4) (HWV.362)"),

    # Vivaldi RV.63 'La Folia' — Trio Sonata Op. 1 No. 12 in D minor. Four
    # variant title-keys collapse into the most-aired form (with Op + No
    # + scoring digit).
    ("Trio Sonata in D minor, RV 63 (Op 1 No 12), 'La Folia'",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),
    ("Sonata no 12 in D minor, RV.63 ('La Follia')",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),
    ("Trio Sonata in D minor, RV 63 'La Follia'",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),
    # La Folia token-sort tail: titles lacking the RV reference fall to the
    # token-sort path, splitting "Trio Sonata …" (×23) and "Sonata …" (×9)
    # off from the catalogue group. Both token-sort keys are Vivaldi-
    # exclusive.
    ("Trio Sonata in D minor Op 1 No 12 'La Folia' (1705)",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),
    ("Sonata in D minor 'La Folia' Op 1 no 12",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),

    # --- Catalogue-path phantom-ordering: audit batch 3 (2026-05-26) --------
    # Surfaced by the composer/ref split scan: same catalogue ref splits when
    # the BBC inconsistently includes (or omits) a key signature, sonata
    # index, or opus reference alongside the catalogue number. Each variant
    # key verified corpus-exclusive.

    # Schubert D.590 — Overture in the Italian Style in D. Bare-form titles
    # omit the key signature (×17).
    ("Overture in the Italian Style, D.590",
     "Overture in D major 'In the Italian Style', D.590"),

    # Schubert D.667 — Trout Quintet. D.667 IS Op.114; the ×8 group carries
    # both references redundantly.
    ("Piano Quintet in A major 'The Trout', Op 114 (D.667)",
     "Piano Quintet in A major 'The Trout', D.667"),

    # Schubert D.958 — Piano Sonata No 19 in C minor. Same pattern as
    # D.845/D.959/D.960 (already aliased): bare form folds with no-19 form.
    ("Piano sonata no 19 in C minor, D.958",
     "Piano Sonata in C minor, D.958"),

    # Bach BWV.1003 — Violin Sonata No 2 in A minor. Bare form (no key
    # signature) folds in.
    ("Sonata for solo violin no 2, BWV.1003",
     "Violin Sonata no 2 in A minor, BWV.1003"),

    # Bach BWV.1041 — Violin Concerto No 1 in A minor. Bare form (no "no 1")
    # folds into the indexed form.
    ("Violin Concerto in A minor, BWV.1041",
     "Concerto for violin and string orchestra No.1 in A minor (BWV.1041)"),

    # Bach BWV.1055 — Harpsichord/oboe d'amore Concerto No 4 in A major.
    # Bare-A-major form (×2) folds into the No 4 form. (The "Allegro from
    # Concerto in C major" movement excerpt now keys §bwv1055|allegro via
    # the movement-marker gate.)
    ("Concerto in A major, BWV.1055",
     "Concerto for oboe d'amore and string orchestra No.4 in A major, BWV.1055"),

    # Vivaldi RV.428 — 'Il Gardellino' Flute Concerto. RV.428 IS Op.10 No.3;
    # the ×5 group carries both references redundantly.
    ("Flute Concerto in D major, RV.428 (Op.10 No.3) ('Il Gardellino')",
     "Flute Concerto in D major, RV.428 ('Il Gardellino')"),

    # Vivaldi RV.297 — 'L'Inverno' (Winter) Violin Concerto in F minor.
    # RV.297 IS Op.8 No.4. The accordion-arrangement whole-work variant
    # folds in. (The "Largo from L'Inverno" movement excerpt now keys
    # §rv297|largo via the movement-marker gate.)
    ("Violin Concerto in F minor, RV.297 (Op.8 No.4), arr. for accordion",
     "Violin Concerto in F minor, RV.297 'L'Inverno'"),

    # --- Long-tail follow-up to batch 3 (2026-05-26) ------------------------
    # 2-4 airing splits surfaced by the composer/ref scan, kept separate from
    # the main batch because the impact-per-alias is small.

    # Vivaldi RV.269 — 'La Primavera' (Spring) Violin Concerto in E.
    # RV.269 IS Op.8 No.1; ×4 group omits the Op reference.
    ("La Primavera (Spring), Violin Concerto no 1 in E, RV 269",
     "Concerto for violin & orchestra (RV.269) (Op.8 No.1) in E major 'La Primavera'"),

    # Mozart K.421 — String Quartet No 15 in D minor. ×2 group adds "no 15"
    # phantom-ordering digit.
    ("String Quartet no 15 in D minor, K.421",
     "Quartet for Strings in D minor, K.421"),

    # Mozart K.418 — 'Vorrei spiegarvi, oh Dio' concert aria. The catalogue
    # path skips because "aria" is an excerpt marker (correctly preventing
    # opera-aria merges); the token-sort variant omits "for orchestra
    # soprano" so it splits. K.418 is a standalone concert aria, not an
    # opera excerpt — alias rather than relax the excerpt-locator gate.
    ("Vorrei spiegarvi, oh Dio - aria K.418",
     "Vorrei spiegarvi, oh Dio - aria for soprano and orchestra, K.418"),

    # --- --form audit surfacing (2026-05-26) --------------------------------
    # `--form symphony` and `--form nocturne` revealed splits that `--title`
    # alone (English-only) would have missed.

    # Berlioz Symphonie Fantastique — bare-form variant (×4) lacks the Op 14
    # reference. Token-sort split; composer-exclusive.
    ("Symphonie fantastique",
     "Symphonie Fantastique, Op 14"),

    # Fauré Nocturne Op 107 — phantom "no 12" ordering digit (×5). Same
    # work, distinguished by opus number.
    ("Nocturne no 12 in E minor, Op 107",
     "Nocturne in E minor, Op 107"),

    # Bartók Romanian Folk Dances Sz.56 — phantom "6" (Sz.56 has 6 dances,
    # which the BBC sometimes spells out in the title).
    ("6 Romanian folk dances, Sz.56",
     "Romanian Folk Dances, Sz.56"),

    # Mendelssohn Symphony No 4 'Italian' — bare-form variants lacking Op 90.
    # Token-sort path (no catalogue ref for Mendelssohn's Op-numbered works).
    # "Italian" nickname is the discriminator: bare "Symphony No 4" alone
    # would NOT match — only titles carrying the nickname fold here.
    ("Symphony no.4, 'Italian'",
     "Symphony No 4 in A major, Op 90 'Italian'"),
    ("Symphony No.4 in A major, 'Italian'",
     "Symphony No 4 in A major, Op 90 'Italian'"),

    # Tchaikovsky Marche Slave Op 31 — the BBC oscillates between French
    # ("Marche slave") and English ("Slavonic March") and sometimes both,
    # creating 5 distinct token-sort groups for one work. All fold to the
    # most-aired form. Op 31 + B flat minor pin identity.
    ("Slavonic March in B flat minor 'March Slave'",
     "Marche Slave, Op 31"),
    ("Slavonic March in B flat minor, op. 31",
     "Marche Slave, Op 31"),
    ("Slavonic March in B flat minor (Op.31) 'March Slave'",
     "Marche Slave, Op 31"),
    ("Slavonic March in B flat minor 'Marche slave' (Op.31)",
     "Marche Slave, Op 31"),
    ("March in B flat minor, Op.31, 'Marche slave'",
     "Marche Slave, Op 31"),

    # Chopin 12 Studies — same "for piano" scoring-annotation split on both
    # Op 10 and Op 25. Two aliases.
    ("12 Studies Op 25",
     "12 Studies Op 25 for piano"),
    ("12 Studies Op 10",
     "12 Studies Op 10 for piano"),

    # Beethoven WoO.46 'Bei Mannern' Variations — bare form (×12) lacks the
    # "7" ordering digit. WoO.46 is uniquely this work; the "7" describes
    # the variation count, not a sibling index.
    ("Variations on 'Bei Mannern, welche Liebe fuhlen' (WoO.46)",
     "7 Variations on 'Bei Mannern, welche Liebe fuhlen' WoO 46"),

    # Grieg Holberg Suite, Op 40 — bare form (×7) and "version for string
    # orchestra" scoring annotation (×3) both fold into the main group.
    # Movement excerpts (Praeludium etc.) correctly stay split.
    ("Holberg Suite",
     "Holberg Suite (Op.40)"),
    ("Holberg suite (Op.40) version for string orchestra",
     "Holberg Suite (Op.40)"),

    # Weber Clarinet Concertino in E flat, Op 26 — split on word order
    # ("Clarinet Concertino" vs "Concertino for clarinet and orchestra")
    # and on a bare-form variant that drops "clarinet" entirely. Same Op,
    # same scoring; all three keys composer-exclusive.
    ("Concertino for clarinet and orchestra in E flat major, Op 26",
     "Clarinet Concertino in E flat major, Op 26"),
    ("Concertino in E flat, Op 26",
     "Clarinet Concertino in E flat major, Op 26"),

    # Mendelssohn Octet for Strings, Op 20 — same Weber-style word-order
    # split: "String Octet" vs "Octet for strings" (×21) and a bare-form
    # variant lacking the scoring word (×7). Op 20 + E flat pins identity.
    ("Octet for strings in E flat major, Op 20",
     "String Octet in E flat major, Op 20"),
    ("Octet in E flat major, Op 20",
     "String Octet in E flat major, Op 20"),

    # Spohr Nonet Op 31 in F — bare form (×8) lacks the detailed scoring.
    # Op 31 + F major + nonet pins identity.
    ("Nonet in F major, Op 31",
     "Nonet for wind quintet, string trio and double bass in F major, Op 31"),

    # Tchaikovsky Violin Concerto in D, Op 35 — bare form (×4) lacks the
    # Op reference. NOTE: this variant key is shared with Stravinsky's
    # own Violin Concerto in D (1931), but composer-scoped grouping in
    # downstream tools (ttn_analyze, ttn_audit, ttn_rebroadcast all key
    # on (composer, work) tuples) keeps them separate. Stravinsky's
    # tracks pick up the relabeled work_key with no false merge.
    ("Violin Concerto in D major",
     "Violin Concerto in D major (Op.35)"),

    # --- Op-bucket scan batch (2026-05-27) ----------------------------------
    # Broad scan grouped tracks by (composer, op_number) to find pairs of
    # high-airing groups for the same opus. ~134 airings across 8 works.

    # Mendelssohn Op 26 'The Hebrides' / 'Fingal's Cave' — ×17 carries the
    # alt-title "Fingal's Cave" and the B-minor key sig that the main form
    # omits. Target string matches the existing Hebrides alias block above.
    ("The Hebrides - Overture in B minor, Op.26, 'Fingal's Cave'",
     "The Hebrides, Op 26"),

    # Beethoven Op 62 Coriolan Overture — ×6 with the key sig "in C minor".
    ("Coriolan - Overture in C minor, Op.62 (1807)",
     "Coriolan Overture Op 62"),

    # Chopin Op 60 Barcarolle in F sharp major — ×19 lacks the key sig.
    ("Barcarolle, Op 60",
     "Barcarolle in F sharp major, Op 60"),

    # Schumann Op 15 Kinderszenen — bare form (×20) lacks the "for piano"
    # scoring annotation. Movement excerpts (Träumerei, Von fremden
    # Ländern) correctly stay split.
    ("Kinderszenen, Op 15",
     "Kinderszenen for piano, Op 15"),

    # Suk Op 23 Elegy — three variant forms: German "Elegie" spelling
    # (×11), key-sig-bearing English variant (×5), and the official
    # Czech subtitle "Pod dojmem Zeyerova Vyšehradu" (×4). All same work.
    ("Elegie, Op 23",
     "Elegy (Op 23) arr. for piano trio"),
    ("Elegy in D flat major, Op 23",
     "Elegy (Op 23) arr. for piano trio"),
    ("Elegie (Pod dojmem Zeyerova Vysehradu), Op 23, arr. for piano trio",
     "Elegy (Op 23) arr. for piano trio"),

    # Chaminade Op 107 Flute Concertino — bare form (×8) drops "flute"
    # entirely. Composer-exclusive.
    ("Concertino, Op 107",
     "Flute Concertino, Op 107"),

    # Dvořák Op 96 'American' String Quartet — Weber-pattern word-order
    # split: "Quartet…for strings" vs "String Quartet…" (×6).
    ("Quartet no. 12 in F major Op 96 (American) for strings",
     "String Quartet No 12 in F Major 'American' Op 96"),

    # Schumann Op 73 Phantasiestücke — four variant forms collapse together:
    # bare "Fantasie" spelling (×28), arrangement annotation (×10), English
    # translation "3 Fantasy Pieces" (×11), and a "for clarinet and piano"
    # word-order variant (×7). All Op 73, same work.
    ("Fantasiestucke, Op 73",
     "Phantasiestucke Op 73 for clarinet & piano"),
    ("Phantasiestucke, Op.73",
     "Phantasiestucke Op 73 for clarinet & piano"),
    ("3 Fantasy Pieces, Op 73",
     "Phantasiestucke Op 73 for clarinet & piano"),
    ("Fantasiestucke, Op 73, for clarinet and piano",
     "Phantasiestucke Op 73 for clarinet & piano"),

    # --- Catalogue-ref scan follow-ups (2026-05-27) -------------------------

    # Schubert D.821 Arpeggione Sonata — bare-form variant (×16) lacks the
    # A-minor key sig.
    ("Arpeggione Sonata (D.821)",
     "Arpeggione Sonata in A minor, D.821"),

    # Handel HWV.350 Water Music suite in G — ×5 carries a phantom "2"
    # (from "2 oboes" scoring) in the catalogue path.
    ("Water Music: Suite in G major for 'flauto piccolo', 2 oboes, bassoon and strings, HWV.350",
     "Water Music - suite HWV.350 in G major"),

    # --- Satie audit (2026-05-27) -------------------------------------------

    # Satie 'Je te veux' (valse-chanson) — three forms collapse: bare title
    # (×6), full Valse-chantée parenthetical (×1), and the most-aired
    # "Je te veux, valse" form (target).
    ("Je te veux",
     "Je te veux, valse"),
    ("Je te Veux (Valse chantée pour piano)",
     "Je te veux, valse"),

    # Satie Trois mélodies (Contamine de Latour texts, 1916) — four
    # variants across "melodies" / "Songs" English translation and
    # spacing of "J.P. Contamine". All the same set of three songs.
    ("Three melodies with texts by J.P. Contamine de La Tour",
     "Three melodies with texts by J.P.Contamine de La Tour"),
    ("Three Songs with texts by JPContamine de La Tour",
     "Three melodies with texts by J.P.Contamine de La Tour"),
    ("Three Songs with texts by JP Contamine de La Tour",
     "Three melodies with texts by J.P.Contamine de La Tour"),

    # Satie Gnossienne No 1 — split on the "for piano" scoring annotation
    # (the Gnossiennes are written for solo piano; the qualifier is
    # redundant). ×10 + ×10 same piece.
    ("Gnossienne No.1",
     "Gnossienne No 1 for piano"),

    # Satie '4 Pieces' broadcast program — the BBC airs a 4-piece Satie
    # selection (Gymnopédie No 1; Les anges; Le chapelier; Je te veux)
    # under two title forms: the detailed list and the bare "4 Pieces".
    # ×1 + ×1; Satie-exclusive on the bare title-key.
    ("4 Pieces",
     "4 Pieces: [1.Gymnopedie No.1; 2.Les anges, from 'Trois melodies' (Latour); 3.Le chapelier, from 'Trois melodies'; 4.Je te veux]"),

    # --- Liszt audit (2026-05-27) -------------------------------------------
    # Liszt's catalogue has heavy cross-language / spelling churn and
    # frequent optional-S-number variants. Audit findings below; sibling
    # works (different Legendes, Mazeppa etude vs symphonic poem, etc.)
    # correctly stay split.

    # Hungarian Rhapsody No 2 in C sharp minor — three groups merge into
    # the no-S-number form (the most-aired). 'from S.244' and 'for piano
    # (S.244 No.2)' both denote the same piece, the piano original.
    ("Hungarian Rhapsody No 2 in C sharp minor (from S.244)",
     "Hungarian Rhapsody No 2 in C sharp minor"),
    ("Hungarian Rhapsody no 2 for piano in C sharp minor (S.244 No.2)",
     "Hungarian Rhapsody No 2 in C sharp minor"),

    # Hungarian Rhapsody No 6 in D flat major — bare form (×4) drops key sig.
    ("Hungarian Rhapsody No 6",
     "Hungarian Rhapsody No 6 in D flat major"),

    # Piano Concerto No 2 in A major, S.125 — variant with S.125 (×7)
    # folds into bare-form group (×11). Same work; S-number optional.
    ("Piano Concerto No 2 in A major, S125",
     "Piano Concerto no 2 in A major"),

    # Piano Concerto No 1 in E flat, S.124 — tokenization split: "S. 124"
    # (period+space) splits into two tokens "s" "124", while "S124" or
    # "S.124" tokenize as a single "s124" token. Fold the split form.
    ("Piano Concerto no 1 in E flat, S 124",
     "Piano Concerto no 1 in E flat, S124"),

    # Piano Sonata in B minor, S.178 — three groups: word-order split
    # ("Sonata…for piano" vs "Piano Sonata") and the same tokenization
    # issue as the Op-1 concerto ("S 178" vs "S.178").
    ("Sonata in B minor S.178 for piano",
     "Piano Sonata in B minor, S.178"),
    ("Piano Sonata in B minor, S 178",
     "Piano Sonata in B minor, S.178"),

    # Rhapsodie espagnole, S.254 — four groups collapse. The 'jota
    # aragone' form is a BBC typo for 'jota aragonesa'. Plus a 'for
    # piano' scoring annotation, a bare form, and a no-parenthetical form.
    ("Rhapsodie espagnole (Folies d'Espagne et jota aragonesa) S.254 for piano",
     "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"),
    ("Rhapsodie espagnole (Folies d'Espagne et jota aragonesa) S.254",
     "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"),
    ("Rhapsodie Espagnole, S 254",
     "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"),

    # Petrarch Sonnet No 104 (S.161 No.5) — five variants across the Italian
    # "Sonetto del Petrarca" form, English "Petrarch Sonnet", and the
    # alternate "Tre Sonetti del Petrarca" parent-set framing. Same piece.
    ("Petrarch Sonnet No 104 (Années de Pelerinage, année 2, S 161)",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),
    ("Sonetto 104 from 'Tre Sonetti del Petrarca' (S.161 No.5)",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),
    ("Sonetto 104 (Tre Sonetti del Petrarca), S 161 No 5",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),
    ("Petrarch Sonnet no 104 S.161",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),

    # Transcendental Étude No 11 'Harmonies du soir' (S.139) — full title
    # form (×4) folds into the bare form (×6). Same piece.
    ("Transcendental study No 11 in D flat major 'Harmonies du soir' - from Etudes d'execution transcendante for piano (S.139)",
     "Transcendental study No 11 in D flat major"),

    # Csárdás macabre — Czardas / Csardas spelling split.
    ("Czardas macabre",
     "Csardas macabre"),

    # Petrarch Sonnet 123 (S.158 No.3) — parent-set framing variant (×2)
    # parallel to the Sonnet 104 case. Same piece.
    ("From 'Années de Pèlerinage' (deuxième année - Italie): Sonetto 123 del Petrarca (S.158 No.3): Io vidi in terra angelici costumi",
     "Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi"),

    # --- Debussy audit (2026-05-27) -----------------------------------------
    # Heavy French/English title oscillation, scoring annotations, and
    # excerpt-from-parent-set framing. Sibling pieces (Images Set 1 vs
    # Set 2; Gigues/Iberia/Rondes as distinct movements of orchestral
    # Images; Première Rhapsodie clarinet vs Rhapsodie saxophone) all
    # correctly stay split.

    # Danses sacrée et profane / "Two Dances for Harp and Strings" —
    # English translation of the canonical title. Same work (1904).
    ("Two Dances for Harp and Strings",
     "Danse sacree et danse profane for harp and strings"),

    # Première Rhapsodie (clarinet, 1909-10) — four groups collapse:
    # rapsodie/rhapsodie spelling × with/without "for clarinet and
    # orchestra" scoring. All the same piece.
    ("Premiere Rhapsodie",
     "Premiere rapsodie"),
    ("Premiere rapsodie for clarinet and orchestra",
     "Premiere rapsodie"),
    ("Premiere rhapsodie for clarinet and orchestra",
     "Premiere rapsodie"),

    # La Mer (1903-05) — variants on the subtitle "3 symphonic sketches"
    # (English numeric, English spelled-out, French "trois esquisses").
    ("La Mer - 3 symphonic sketches for orchestra",
     "La Mer"),
    ("La mer - three symphonic sketches",
     "La Mer"),
    ("La Mer - trois esquisses symphoniques",
     "La Mer"),

    # La cathédrale engloutie (Préludes Book 1 No 10) — bare title (×15)
    # and "from Preludes Book 1" (×3, no No 10) both fold into the most-
    # aired "from Preludes - Book 1 (No 10)" form.
    ("La cathédrale engloutie",
     "La cathedrale engloutie - (No 10 from Preludes - Book 1)"),
    ("La Cathédrale engloutie - from Préludes Book 1",
     "La cathedrale engloutie - (No 10 from Preludes - Book 1)"),

    # Estampes — "for piano" scoring annotation drops (the set is for
    # solo piano; qualifier is redundant). Plus the "puie" typo (×4)
    # for "Jardins sous la pluie" (one of the three Estampes) folds
    # into the correctly-spelled form.
    ("Estampes for piano",
     "Estampes"),
    ("Jardins sous la puie (Estampes, L.100)",
     "Jardins sous la pluie (Estampes, L.100)"),

    # Images for orchestra (1905-12) — "3 Images for orchestra" piece-
    # count variant folds into the bare main form. The three constituent
    # pieces (Gigues, Iberia, Rondes de Printemps) correctly stay as
    # separate excerpt entries.
    ("3 Images for orchestra",
     "Images for orchestra"),

    # Rondes de Printemps (No 3 of orchestral Images) — three groups
    # collapse: with/without "for Orchestra", and a no-"from" variant.
    ("Rondes de Printemps, from 'Images' for Orchestra",
     "Rondes de Printemps, from 'Images'"),
    ("Rondes de Printemps, 'Images'",
     "Rondes de Printemps, from 'Images'"),

    # Sonata for Flute, Viola & Harp (L. 137) — three groups across the
    # L-number tokenization issue ("L. 137" vs "L.137") and a bare form.
    # Same as the Liszt S.124 case.
    ("Sonata for Flute, Viola & Harp, L. 137",
     "Sonata for Flute, Viola & Harp"),
    ("Sonata for Flute, Viola & Harp (L.137)",
     "Sonata for Flute, Viola & Harp"),

    # Tarantelle styrienne / Danse — Debussy retitled the piece "Danse"
    # later; the BBC sometimes notes both. Same work.
    ("Tarantelle styrienne (Danse)",
     "Tarantelle styrienne"),

    # Clair de lune (Suite Bergamasque No 3) — variants: a "bergamesque"
    # spelling typo, an unambiguous "no 3 from Suite bergamasque for
    # piano" form, and an encore tag. All fold into the main "from
    # Suite Bergamasque" group. Bare "Clair de lune" left split — title
    # is ambiguous between this piano piece and the song from Fêtes
    # galantes.
    ("Clair de lune (No.3 from Suite bergamesque for piano)",
     "Clair de Lune - from Suite Bergamasque (1890)"),
    ("Clair de lune (no 3 from Suite bergamasque for piano)",
     "Clair de Lune - from Suite Bergamasque (1890)"),
    ("Clair de lune (encore)",
     "Clair de Lune - from Suite Bergamasque (1890)"),

    # --- Mompou audit (2026-05-27) ------------------------------------------
    # Small corpus (~44 tracks). Composer-name alias Frederic↔Federico
    # was already in place. Two work-key folds:

    # 'Damunt de tu només les flors' (No 5 of Combat del somni, the
    # canonical framing). Bare-form variant lacks the parent-set tag.
    ("Damunt de tu, nomes les flors",
     "Damunt de tu només les flors (Combat del somni)"),

    # Música callada — bare "piano cycle" descriptor variant folds into
    # the bare title. The "excerpts" variant left split — could be any
    # subset of the 28-piece cycle.
    ("Musica callada, piano cycle",
     "Música callada"),

    # --- Grieg Lyric Pieces audit (2026-05-27) ------------------------------

    # Notturno / Nocturne in C, Lyric Pieces Book 5 Op 54 No 4 — three
    # variants (Italian Notturno spelling vs English Nocturne, two
    # punctuation forms of the Op number).
    ("Notturno from Lyric Pieces, Op 54 no 4",
     "Nocturne in C from Lyric Suite, Op.54'4"),
    ("Nocturne in C from Lyric Suite, Op.54 No. 4",
     "Nocturne in C from Lyric Suite, Op.54'4"),

    # Peer Gynt Suite No 1 Op 46 — bare-form group (no Op number, ×10)
    # folds into the main (×31) Op-tagged form.
    ("Peer Gynt, Suite No.1",
     "Peer Gynt - Suite No 1 Op 46"),

    # Slåtter Op 72 — "for piano" scoring annotation drop (Slåtter is for
    # solo piano; redundant). ×13 + ×9.
    ("Slatter Op.72 for piano",
     "Slatter Op 72"),

    # 5-piece Selected Lyric Pieces program (Aften / At your feet / Summer
    # / Gone / Remembrances) — the BBC frames the same broadcast set as
    # either "5 Lyric Pieces" or "Selected Lyric Pieces (Lyriske stykker)".
    ("Selected Lyric Pieces (Lyriske stykker): Aften på højfjellet (Evening in the mountains), Op.68 No.4; For dine føtter (At your feet), Op.68 No.3; Sommeraften (Summer's evening), Op.71 No.2; Forbi (Gone), Op.71 No.6; Etterklang (Remembrances), Op.71 No.7",
     "5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) (Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) (Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)"),

    # --- Granados audit (2026-05-27) ----------------------------------------

    # Quejas, o La Maja y el Ruiseñor (Goyescas, Op 11 No 4) — four
    # variants of the famous "Maiden and the Nightingale" piano piece.
    # The full title prefixes "Quejas, o" (the genre title); the BBC
    # sometimes drops "Quejas" and sometimes adds "(The Maiden and the
    # Nightingale)" English translation.
    ("Quejas o la maja y el ruisenor (The Maiden and the Nightingale)",
     "La Maja y el Ruisenor - from Goyescas"),
    ("Quejas o la Maja y el Ruiseñor (from Goyescas)",
     "La Maja y el Ruisenor - from Goyescas"),
    ("La maja y el ruiseñor (The Maiden and the Nightingale) - from Goyescas",
     "La Maja y el Ruisenor - from Goyescas"),
    ("Quejas o la maja y el ruisenor (The Maiden and the Nightingale) - from Goyescas: 7 pieces for piano Op 11 No 4",
     "La Maja y el Ruisenor - from Goyescas"),

    # El Pelele (Goyescas Op 11 No 7) — four variant forms collapse:
    # "excerpt" vs "from", bare title, and short-form "Goyescas - El
    # Pelele".
    ("El Pelele (excerpt Goyescas: 7 pieces for piano, Op 11, No 7)",
     "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)"),
    ("Goyescas - El Pelele",
     "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)"),
    ("El Pelele, from 'Goyescas'",
     "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)"),

    # Allegro de concierto, Op 46 — English "Concert Allegro" translation
    # of the canonical Spanish title.
    ("Concert Allegro, Op 46",
     "Allegro de concierto, Op 46"),

    # Spanish Dances Op 37 No 2 'Oriental(e)' — two variant forms across
    # English "Oriental" vs Italian "Orientale" and with/without the
    # "12 Spanish Dances" parent-set framing.
    ("Orientale Op 37 no 2 from '12 Spanish Dances'",
     "No.2 Oriental in C minor – from Danzas espanolas (Set 1) for piano"),

    # --- Albéniz audit (2026-05-27) -----------------------------------------

    # Asturias (Suite española Op 47 No 5) — three variant forms fold:
    # explicit "Op 47 no 5" framing (the "Leyenda" / piano transcription
    # provenance is well-known), "from" word-order, and a Guitar-instrument
    # provenance-tagged form. All same piece.
    ("Asturias Op 47 no 5",
     "Asturias (Suite española, Op 47) (1887)"),
    ("Asturias, from Suite española, Op.47 (1887)",
     "Asturias (Suite española, Op 47) (1887)"),
    ("Asturias, from 'Suite española, op. 47' (1887) (Guitar by Antonio de Torres Juardo (1817-1892) in Seville, 1859, and owned by Miquel Llobet (1878-1938))",
     "Asturias (Suite española, Op 47) (1887)"),

    # Córdoba (Cantos de España, Op 232 No 4 'Nocturne') — two variants:
    # the bare form (no "Nocturne" descriptor) and a "for piano" scoring
    # variant. All same piece.
    ("Cordoba from 'Cantos de Espana' for piano, Op 232 no 4",
     "Cordoba (Nocturne) from Cantos de Espana (Op.232 No.4)"),
    ("Cordoba - from Cantos de Espana (Op.232 No.4)",
     "Cordoba (Nocturne) from Cantos de Espana (Op.232 No.4)"),

    # Catalunya & Sevilla from Suite Española No 1 — a 2-piece program;
    # with/without "from" preposition.
    ("Catalunya; Sevilla, Suite Espanola No 1",
     "Catalunya; Sevilla - from Suite Espanola No 1"),

    # --- Falla audit (2026-05-27) -------------------------------------------

    # Noches en los jardines de España / Nights in the Gardens of Spain —
    # Spanish ↔ English fold, plus a movement-tagged variant.
    ("Nights in the Gardens of Spain",
     "Noches en los jardines de Espana"),
    ("Noches en los jardines de España (En el Generalife; Danza lejana; En los jardines de la Sierra de Córdoba)",
     "Noches en los jardines de Espana"),

    # Ritual Fire Dance (from El amor brujo) — three variants fold: with
    # the parent ballet tag, with "El Amor Brujo" prefix, and the Spanish
    # title "Danza Ritual del Fuego".
    ("Ritual Fire Dance, from 'El amor brujo'",
     "Ritual Fire Dance"),
    ("El Amor Brujo, Ritual Fire Dance",
     "Ritual Fire Dance"),
    ("Danza Ritual del Fuego",
     "Ritual Fire Dance"),

    # Siete canciones populares españolas — English translation "Seven
    # Spanish Popular Songs" folds with the full Spanish title. The
    # trumpet+piano arrangement and the Maréchal cello arrangement
    # (Suite populaire espagnole) stay split as distinct scorings.
    ("Seven Spanish Popular Songs",
     "Siete canciones populares espanolas"),

    # El amor brujo (full ballet) — three variant forms fold (English
    # translation, year/act detail). The Suite arrangement stays split.
    ("El amor brujo (Love, the Magician) - ballet pantomime",
     "El amor brujo - ballet-pantomime"),
    ("El amor brujo - ballet pantomime in one act (1920 vers)",
     "El amor brujo - ballet-pantomime"),

    # Spanish Dance No 1 from La Vida breve — "(Molto Ritmico)" tempo
    # annotation variant folds.
    ("Spanish Dance No.1 (Molto Ritmico) from La Vida Breve",
     "Spanish Dance no 1 from 'La Vida breve'"),

    # Danza del Molinero (Miller's Dance from El Sombrero de tres picos,
    # the Farruca) — Spanish ↔ English title.
    ("Danza del Molinero",
     "Dance of the Miller from 'El Sombrero de tres picos'"),

    # --- Turina audit (2026-05-27) ------------------------------------------

    # La Oración del Torero, Op 34 — bare form (no Op number) folds.
    ("La Oración del Torero",
     "La Oración del Torero, Op 34"),

    # --- Ravel audit (2026-05-27) -------------------------------------------

    # Gaspard de la nuit — "for piano" scoring annotation drop (it's for
    # solo piano; redundant). 33+22 = 55× total.
    ("Gaspard de la nuit for piano",
     "Gaspard de la nuit"),

    # Alborada del gracioso (Miroirs No 4) — three variants fold across
    # with/without "from the suite" framing and a bare form.
    ("Alborada del gracioso - from the suite 'Miroirs' (1905)",
     "Alborada del gracioso 'Miroirs' (1905)"),
    ("Alborada del gracioso",
     "Alborada del gracioso 'Miroirs' (1905)"),

    # Une Barque sur l'océan (Miroirs No 3) — parent-set framing variant.
    ("Une Barque sur l'ocean (no 3 from Miroirs)",
     "Une Barque sur l'ocean"),

    # Violin Sonata in G major (1923-27) — word-order split. Note: the
    # variant key is shared with Pergolesi's Sonata for violin and bc
    # in G; composer-scoped grouping keeps them separate.
    ("Sonata for violin and piano in G major",
     "Violin Sonata in G major"),

    # Ma mère l'Oye (ballet, 1911) — two ballet-form variants collapse.
    # Bare "Ma Mère l'Oye" (×9) and "Mother Goose Suite" (×10) left split
    # — could each refer to the piano duet, orchestral Suite, or ballet.
    ("Ma Mere l'Oye (Mother Goose) - ballet",
     "Ma Mere l'Oye - ballet"),

    # Tzigane (rapsodie de concert) for violin and piano — three variants
    # collapse across bare title, English "for violin and piano", and
    # French "pour violon et piano". The orchestral-arrangement version
    # stays split as a distinct scoring.
    ("Tzigane - rapsodie de concert for violin and piano",
     "Tzigane"),
    ("Tzigane - rapsodie de concert pour violon et piano",
     "Tzigane"),

    # String Quartet in F major — BBC's "Op 35" reference is incorrect
    # (Ravel didn't use opus numbers; M.35 is the Marnat number, possibly
    # mistaken for an Op number). Same work.
    ("String Quartet in F major, Op 35",
     "String Quartet in F major"),

    # La Valse — "choreographic poem for orchestra" subtitle variant.
    ("La Valse - choreographic poem for orchestra",
     "La Valse"),

    # --- Poulenc audit (2026-05-27) -----------------------------------------

    # Oboe Sonata (FP 185, 1962) — word-order variant. Variant key is
    # shared with Srul Irving Glick's Oboe Sonata; composer-scoped
    # grouping keeps them separate.
    ("Sonata for oboe and piano (1962)",
     "Oboe Sonata"),

    # Concerto in D minor for Two Pianos and Orchestra (FP 61) — three
    # variants: bare, FP 61, and a "for 2 pianos" no-orchestra form.
    ("Concerto for Two Pianos in D minor, FP 61",
     "Concerto in D minor for 2 pianos and orchestra"),
    ("Concerto in D minor for 2 pianos",
     "Concerto in D minor for 2 pianos and orchestra"),

    # Sinfonietta (FP 141) — bare and FP-numbered variants fold. The
    # bare "Sinfonietta" key is shared with several other composers but
    # composer-scoped grouping isolates each.
    ("Sinfonietta, FP 141",
     "Sinfonietta for orchestra"),
    ("Sinfonietta",
     "Sinfonietta for orchestra"),

    # Concerto for Organ, Timpani and Strings in G minor (FP 93) — three
    # variants: word-order ("organ, strings and timpani") and "FP.93" vs
    # "FP 93" punctuation.
    ("Concerto for organ, strings and timpani",
     "Concerto for Organ, Timpani and Strings in G minor, FP 93"),
    ("Concerto for Organ, Timpani and Strings in G minor, FP.93",
     "Concerto for Organ, Timpani and Strings in G minor, FP 93"),

    # Sept chansons (1936) — "7" vs "Sept" + scoring annotation.
    ("7 chansons, for mixed choir a cappella (1936)",
     "Sept chansons"),

    # Petites voix — bare form folds into the scoring-annotated form.
    ("Petites voix",
     "Petites voix pour voix egales a capella"),

    # Capriccio (FP 155, 1953) — based on the Finale of 'Le Bal masqué';
    # two variants fold into the main "for Two Pianos" form.
    ("Capriccio (excerpt Finale of 'Bal masque')",
     "Capriccio for Two Pianos"),
    ("Capriccio - after Finale of cantata 'Le Bal masqué' vers. for 2 pianos",
     "Capriccio for Two Pianos"),

    # Les Chemins de l'amour (FP 106) — "valse chantée" scoring/genre
    # annotation variant.
    ("Les Chemins de l'amour (valse chantée for voice and piano)",
     "Les Chemins de l'amour"),

    # Sextet for piano and winds (FP 100) — "Wind Quintet" word-order
    # variant.
    ("Sextet for Piano and Wind Quintet",
     "Sextet for piano and winds"),

    # --- Saint-Saëns audit (2026-05-27, via ttn_audit_composer) -------------

    # Bassoon Sonata in G major, Op 168 — word-order split. 37× total.
    ("Sonata for bassoon and piano (Op.168) in G major",
     "Bassoon Sonata in G major, Op 168"),

    # Havanaise, Op 83 — two variants fold: with "for violin and orchestra"
    # scoring and with explicit "in F" key signature. 34× total.
    ("Havanaise for violin and orchestra, Op 83",
     "Havanaise, Op 83"),
    ("Havanaise For Violin and Orchestra in F, op. 83",
     "Havanaise, Op 83"),

    # Introduction and Rondo Capriccioso, Op 28 — three variants:
    # scoring annotations and an A-minor key sig variant. 28× total.
    ("Introduction and rondo capriccioso for violin and orchestra, Op 28",
     "Introduction and rondo capriccioso (Op.28), arr. for violin & piano"),
    ("Introduction and Rondo capriccioso in A minor, Op 28",
     "Introduction and rondo capriccioso (Op.28), arr. for violin & piano"),

    # Cello Concerto No 1 in A minor, Op 33 — word-order split. 25× total.
    ("Concerto for cello and orchestra No 1 in A minor Op 33",
     "Cello Concerto No 1 in A minor, Op 33"),

    # Danse macabre, Op 40 — "symphonic poem" subtitle variant.
    ("Danse macabre - symphonic poem (Op.40)",
     "Danse macabre, Op 40"),

    # Symphony No 3 in C minor 'Organ', Op 78 — "Organ" vs "Organ Symphony"
    # parenthetical variant.
    ("Symphony no.3 in C minor, Op.78 'Organ'",
     "Symphony No.3 in C minor Op.78 \"Organ Symphony\""),

    # Étude en forme de valse (Op 52 No 6) — bare form (no "valse"
    # subtitle) folds into main. The Ysaÿe Caprice transcription stays
    # split (cross-composer title-key overlap flagged by ttn_audit_composer).
    ("Etude in D flat (Op.52 No.6)",
     "Etude in D flat, Op 52, No 6 (Etude en forme de valse)"),

    # Le Cygne / The Swan (from Le Carnaval des Animaux) — four variants
    # fold across French/English title and parent-set framing.
    ("The Swan, from 'The Carnival of the Animals'",
     "Le Cygne (The Swan) from 'Le Carnaval des Animaux'"),
    ("Le Cygne (The Swan), from 'The Carnival of the Animals'",
     "Le Cygne (The Swan) from 'Le Carnaval des Animaux'"),
    ("Le Cygne (The Swan) (excerpt The Carnival des Animaux)",
     "Le Cygne (The Swan) from 'Le Carnaval des Animaux'"),

    # --- Schumann audit (2026-05-27, via ttn_audit_composer) ----------------

    # Abegg Variations, Op 1 — 3 variants (bare, full "Theme and
    # Variations on the Name Abegg" form). 53× total.
    ("Abegg Variations, Op 1",
     "Abegg variations Op.1 for piano"),
    ("Theme and variations on the Name \"Abegg\", Op 1",
     "Abegg variations Op.1 for piano"),

    # Adagio and Allegro, Op 70 — 4 variants (key sig present/absent,
    # "for horn and piano" scoring, "or other" instrumentation note).
    ("Adagio and allegro, Op 70",
     "Adagio and allegro in A flat major, Op 70"),
    ("Adagio and allegro for horn and piano Op 70 in A flat major",
     "Adagio and allegro in A flat major, Op 70"),
    ("Adagio and allegro in A flat (Op.70), for horn or other and piano",
     "Adagio and allegro in A flat major, Op 70"),

    # Arabeske, Op 18 — 3 variants: word-order ("Arabeske for piano in C
    # major" vs "Arabeske in C major"), plus English "Arabesque" spelling.
    ("Arabeske in C major, Op 18",
     "Arabeske for piano in C major, Op 18"),
    ("Arabesque in C major (Op.18)",
     "Arabeske for piano in C major, Op 18"),

    # Dichterliebe, Op 48 — 4 full-cycle variants fold; single-song
    # excerpts ("Hor' ich das Liedchen" etc.) correctly stay split.
    ("Dichterliebe (Op.48) (song cycle)",
     "Dichterliebe for voice and piano, Op 48"),
    ("Dichterliebe, Op 48 - song-cycle for voice and piano",
     "Dichterliebe for voice and piano, Op 48"),
    ("Dichterliebe, Op 48",
     "Dichterliebe for voice and piano, Op 48"),

    # Manfred Overture, Op 115 — 5 variants across word-order and
    # "incidental music" framing. All the same Overture.
    ("Manfred - Overture to the Incidental Music (Op.115)",
     "Overture (Manfred, Op 115)"),
    ("Manfred - incidental music Op 115 (Overture)",
     "Overture (Manfred, Op 115)"),
    ("Overture to Manfred, Op 115",
     "Overture (Manfred, Op 115)"),
    ("Overture to 'Manfred', Op 115, after Byron",
     "Overture (Manfred, Op 115)"),

    # Symphonische Etuden, Op 13 — 4 variants: bare, "for piano" scoring,
    # and the French alternate title "Etudes en formes de variations".
    ("Symphonische Etuden, Op.13",
     "Symphonische Etuden for piano, Op 13"),
    ("Etudes en formes de variations, Op 13",
     "Symphonische Etuden for piano, Op 13"),
    ("Etudes en formes de variations Op.13 for piano",
     "Symphonische Etuden for piano, Op 13"),

    # String Quartet No 3 in A, Op 41 No 3 — word-order split + no-key-sig
    # variant. (No 1 in A minor has its own fold below.)
    ("Quartet for strings in A major (Op.41 No.3)",
     "String Quartet in A major, Op 41 no 3"),
    ("String Quartet no 3 in A, op 41 no 3",
     "String Quartet in A major, Op 41 no 3"),
    # String Quartet No 1 in A minor, Op 41 No 1
    ("String Quartet in A minor, Op 41 no 1",
     "String Quartet no 1 in A minor, Op 41 no 1"),

    # Piano Sonata No 1 in F sharp minor, Op 11 — word-order.
    ("Sonata no. 1 in F sharp minor Op.11 for piano",
     "Piano Sonata no 1 in F sharp minor, Op 11"),

    # Fantasy for violin and orchestra, Op 131 — word-order ("Violin
    # Fantasy" vs "Fantasy for violin and orchestra").
    ("Violin Fantasy in C major, Op 131",
     "Fantasy for violin and orchestra in C major, Op 131"),

    # Piano Trio No 1 in D minor, Op 63 — bare-form (no "No 1") variant.
    ("Piano Trio in D minor (Op.63)",
     "Piano Trio No.1 in D minor (Op.63)"),

    # Märchenbilder, Op 113 — "for viola and piano" scoring annotation.
    ("Marchenbilder for viola and piano, Op 113",
     "Marchenbilder, Op 113"),

    # Faschingsschwank aus Wien, Op 26 — "Phantasiebilder" subtitle
    # variant. Both groups at ×8. The single-movement excerpt (Intermezzo
    # in E flat minor) correctly stays split.
    ("Faschingsschwank aus Wien - Phantasiebilder, Op 26",
     "Faschingsschwank aus Wien, Op 26"),

    # Toccata in C major, Op 7 — word-order split.
    ("Toccata for piano (Op.7) in C major",
     "Toccata in C major, Op 7"),

    # Variations on a Theme by Clara Wieck (slow movement of Piano Sonata
    # No 3 in F minor, Op 14) — parent-context variant folds into bare.
    ("Variations on a Theme by Clara Wieck (from Schumann's Piano Sonata No 3 in F minor, Op 14)",
     "Variations on a Theme by Clara Wieck"),

    # Symphony No 4 in D minor, Op 120 — the 1841 original version splits
    # into two variants that fold together. Note: the 1841 original and
    # the 1851 published version are MUSICALLY DISTINCT (Schumann revised
    # heavily); the published 1851 form and the unspecified-version main
    # group stay separate from the 1841 original group.
    ("Symphony No. 4 in D minor, op. 120 (original version, 1841)",
     "Symphony No.4 in D minor (Op.120), version original (1841)"),

    # Three Romances, Op 94 — word-order variant.
    ("Three Romances for Oboe and Piano, op. 94",
     "Three Romances Op 94"),
    # Romanze for oboe and piano, Op 94 No 1 (single-romance excerpt) —
    # "Op. 94/1" notation variant.
    ("Romanze for Oboe and Piano (Op. 94/1)",
     "Romanze for Oboe and Piano, Op 94 no 1"),

    # Humoreske, Op 20 — bare-form (no "for piano") variant.
    ("Humoreske in B flat major, Op.20",
     "Humoreske for piano in B flat major Op 20"),

    # Kinderszenen, Op 15 — Träumerei single-piece excerpt (No 7) has
    # several variant keys; all fold to the most-aired form.
    ("Traumerei (Kinderszenen, Op 15 no 7)",
     "Träumerei, from Kinderszenen, Op.15"),
    ("Traumerei (Kinderszenen, Op 15)",
     "Träumerei, from Kinderszenen, Op.15"),
    ("Träumerei – from Kinderszenen for piano (Op.15)",
     "Träumerei, from Kinderszenen, Op.15"),
    # Von fremden Ländern und Menschen (No 1) — punctuation variant.
    ("Von fremden Ländern und Menschen (Kinderszenen, op 15)",
     "Von fremden Ländern und Menschen, from 'Kinderszenen, Op 15'"),

    # --- Fauré audit (2026-05-27, via ttn_audit_composer) -------------------
    # Op 33 nocturnes (Nos 1, 2, 3) are distinct sibling pieces under one
    # Op — same pattern as Schubert D.899 impromptus — and correctly stay
    # split.

    # Pavane, Op 50 — "Andante molto moderato" tempo marking variant.
    ("Pavane (Andante molto moderato) in F minor Op 50",
     "Pavane for orchestra Op 50"),

    # Nocturne No 6 in D flat, Op 63 — "for piano" scoring annotation drop.
    ("Nocturne No 6 in D flat major, Op 63",
     "Nocturne for piano no 6 in D flat major, Op 63"),

    # Élégie, Op 24 — three variants fold: French "Elegie" spelling and
    # "for cello and piano" scoring annotation.
    ("Elegie (Op.24) arr. for cello and orchestra",
     "Elegy, Op 24"),
    ("Elegy for cello and piano (Op.24)",
     "Elegy, Op 24"),

    # Pelléas et Mélisande Suite, Op 80 — word-order ("Pelleas Suite"
    # vs "Suite from Pelleas").
    ("Suite from 'Pelléas et Mélisande', Op.80",
     "Pelleas et Melisande suite, Op 80"),

    # Piano Trio in D minor, Op 120 — bare-form (no "(1923)" date) variant.
    ("Piano Trio in D minor, Op 120",
     "Trio for piano and strings (Op.120) in D minor (1923)"),

    # Dolly Suite, Op 56 — bare-form variant.
    ("Dolly Suite, op. 56",
     "Dolly - Suite for piano duet Op.56"),

    # --- Brahms audit (2026-05-27, via ttn_audit_composer) ------------------
    # Op 56 Haydn Variations (Op 56a 2-pianos vs Op 56b orchestral) left
    # split per scoring policy. Op 120 Clarinet Sonatas (clarinet/viola
    # alt-scorings) left split for the same reason. Op 118 sibling
    # intermezzi and Op 42 song-set excerpts correctly stay split.

    # Op 115 Clarinet Quintet in B minor — word-order variant.
    ("Quintet for clarinet and strings in B minor, Op 115",
     "Clarinet Quintet in B minor, Op 115"),

    # Op 24 Variations and Fugue on a Theme by Handel — 3 variants fold:
    # "for piano" scoring, G.F.-with-dot punctuation, and a no-"25"-count
    # bare-form variant.
    ("25 Variations and fugue on a theme by G F Handel for piano, Op 24",
     "25 Variations and fugue on a theme by G F Handel, Op 24"),
    ("25 variations and fugue on a theme by G.F. Handel for piano (Op.24)",
     "25 Variations and fugue on a theme by G F Handel, Op 24"),
    ("Variations and Fugue on a Theme by Handel, Op 24",
     "25 Variations and fugue on a theme by G F Handel, Op 24"),

    # Op 79 Rhapsody No 1 in B minor — bare-form variant (without "for
    # piano"). Op 79 No 2 in G minor stays split as the sibling piece.
    ("Rhapsody in B minor Op.79 No.1",
     "Rhapsody for piano in B minor, Op 79 No 1"),

    # Op 91 Gestillte Sehnsucht (No 1) — 2 variants fold. Geistliches
    # Wiegenlied (No 2) stays split as the sibling song.
    ("Gestillte Sehnsucht Op 91 no 1",
     "Gestillte Sehnsucht for alto, viola and piano Op 91 No 1"),
    ("Gestillte Sehnsucht - song for alto, viola and piano, Op.91 No.1",
     "Gestillte Sehnsucht for alto, viola and piano Op 91 No 1"),

    # Op 118 No 2 Intermezzo in A major — "118/2" notation variant.
    ("Intermezzo, op. 118/2",
     "Intermezzo in A major, Op 118 no 2"),
    ("Intermezzo in A, op. 118/2",
     "Intermezzo in A major, Op 118 no 2"),

    # Op 102 Double Concerto for Violin and Cello — 3 variants fold.
    ("Concerto for violin, cello and orchestra in A minor, Op.102",
     "Double Concerto in A minor for Violin and Cello, Op 102"),
    ("Double Concerto in A minor, Op 102",
     "Double Concerto in A minor for Violin and Cello, Op 102"),
    ("Concerto in A minor for violin and cello, Op 102",
     "Double Concerto in A minor for Violin and Cello, Op 102"),

    # Op 34 Piano Quintet in F minor — 2 variants fold. Note: the bare
    # title-key is shared with César Franck's Piano Quintet in F minor
    # (also no-Op); composer-scoped grouping isolates them.
    ("Quintet in F minor Op.34 for piano and strings",
     "Piano Quintet in F minor, Op 34"),
    ("Quintet in F minor Op 34",
     "Piano Quintet in F minor, Op 34"),

    # Op 38 Cello Sonata No 1 in E minor — 2 variants fold.
    ("Cello Sonata in E minor, Op 38",
     "Cello Sonata no 1 in E minor, Op 38"),
    ("Sonata for Cello and piano No.1 (Op.38) in E minor",
     "Cello Sonata no 1 in E minor, Op 38"),

    # Op 89 Gesang der Parzen — 3 variants fold across word-order
    # ("for chorus and orchestra") and bare-form.
    ("Gesang der Parzen  Op 89 for chorus and orchestra",
     "Gesang der Parzen (Song of the Fates), Op 89"),
    ("Gesang der Parzen (Song of the Fates) for chorus and orchestra (Op.89)",
     "Gesang der Parzen (Song of the Fates), Op 89"),
    ("Gesang der Parzen, Op.89",
     "Gesang der Parzen (Song of the Fates), Op 89"),

    # Op 17 4 Songs for women's voices, 2 horns and harp — "Four" spelled
    # out variant.
    ("Four Songs, Op 17",
     "4 Songs for women's voices, 2 horns and harp, Op 17"),

    # Op 77 Violin Concerto in D major — word-order variant.
    ("Concerto for violin and orchestra (Op.77) in D major",
     "Violin Concerto in D major, Op 77"),

    # Op 101 Piano Trio No 3 in C minor — word-order + bare-form variants.
    ("Trio for piano and strings No.3 in C minor (Op.101)",
     "Piano Trio No 3 in C minor, Op 101"),
    ("Piano Trio in C minor, op. 101",
     "Piano Trio No 3 in C minor, Op 101"),

    # Op 76 8 Piano Pieces — "Eight" spelled out + word-order variants.
    ("Eight Piano Pieces (Op.76)",
     "8 Pieces for Piano, Op 76"),
    ("8 Piano Pieces, Op.76",
     "8 Pieces for Piano, Op 76"),

    # --- Franck audit (2026-05-27, via ttn_audit_composer) ------------------

    # Violin Sonata in A major, M.8 — word-order variant fold. The
    # cello-arrangement variants stay split as distinct scorings.
    ("Sonata for violin and piano (M.8) in A major",
     "Violin Sonata in A major, M.8"),

    # Prélude, fugue et variation, Op 18 (M.30) — four variants fold
    # across French "et" / English "and" connective and bare/scoring/Op
    # tag variants.
    ("Prelude, fugue et variation for organ (M.30) (Op.18)",
     "Prelude, fugue and variation for organ in B minor (M.30)"),
    ("Prelude, Fugue et Variation Op 18",
     "Prelude, fugue and variation for organ in B minor (M.30)"),
    ("Prelude, fugue and variation, Op.18",
     "Prelude, fugue and variation for organ in B minor (M.30)"),

    # Cantabile in B major, M.36 (No 2 of 3 Pièces pour grand orgue
    # M.35-37) — bare M.36 form folds into the parent-set framing.
    ("Cantabile in B major, M.36",
     "Cantabile in B major (M.36), no 2 from 3 Pieces pour grand orgue (M.35-37)"),

    # Piano Quintet in F minor (M.7) — adjacent fold not surfaced by
    # the tool's main detection (no Op/standard-catalogue match) but
    # noticed in passing: the bare "Piano Quintet in F minor" form
    # (already aliased via the Brahms-side retarget) and the M.7-tagged
    # form should both reach the same key within Franck. Note: the
    # work_key ends up labeled with Brahms' "Op 34" — composer-scoping
    # keeps Franck/Brahms separate; the label is opaque.
    ("Quintet for piano and strings (M.7) in F minor",
     "Piano Quintet in F minor, Op 34"),

    # --- Bartók audit (2026-05-27, via ttn_audit_composer) ------------------
    # Sz.56 vs Sz.68 (piano original vs orchestral arrangement) stays
    # split per scoring policy. For Children Sz.42 excerpt programs and
    # Mikrokosmos selections stay split as distinct programs.

    # Sz.40 String Quartet No 1 in A minor — key-signature variant.
    ("String Quartet No. 1 in A minor, Sz. 40",
     "Quartet for strings no. 1 (Sz.40)"),

    # Sz.106 Music for Strings, Percussion and Celesta — Sz-tagged variant.
    ("Music for strings, percussion and celesta, Sz.106",
     "Music for Strings, Percussion and Celesta"),

    # Sz.93 4 Hungarian Folk Songs — 3 variants (date variant + alt Magyar
    # title).
    ("4 Hungarian folk songs for chorus, Sz.93",
     "4 Hungarian folk songs for chorus, Sz 93, 1930"),
    ("Hungarian Folksongs (Magyar népdalok), Sz. 93",
     "4 Hungarian folk songs for chorus, Sz 93, 1930"),

    # Sz.95 Piano Concerto No 2 in G — bare-key-sig variant.
    ("Piano Concerto No 2 (Sz.95)",
     "Piano Concerto No. 2 in G, Sz. 95"),

    # --- Tchaikovsky audit (2026-05-27, via ttn_audit_composer) -------------
    # Op 33 Rococo Variations: "original version" (Tchaikovsky's autograph,
    # pre-Fitzenhagen) stays split from the Fitzenhagen-edited standard
    # version per existing version-distinction precedent (Schumann Op 120).
    # Op 71a Nutcracker Suite excerpts and Op 24 Eugene Onegin per-aria
    # excerpts stay split (excerpt-vs-whole boundary).

    # Romeo and Juliet, fantasy overture — 3 variants fold. The 1880
    # version IS the standard published form (Tchaikovsky's final
    # revision).
    ("Romeo and Juliet fantasy overture (1880 version)",
     "Romeo and Juliet - fantasy overture"),
    ("Romeo and Juliet, fantasy overture after Shakespeare",
     "Romeo and Juliet - fantasy overture"),
    ("Romeo and Juliet - fantasy overture vers. standard",
     "Romeo and Juliet - fantasy overture"),

    # Op 33 Variations on a Rococo Theme — 4 standard-version variants
    # fold. The "(original version)" form correctly stays split.
    ("Variations on a Rococo Theme, Op.33",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),
    ("Variations on a rococo theme in A for cello and orchestra, Op 33",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),
    ("Variations on a Roccoco Theme, Op 33, for cello and orchestra",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),
    ("Variations on a Rococo Theme for cello and orchestra, Op.33",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),

    # Op 11 String Quartet No 1 in D — word-order. Andante Cantabile
    # excerpt correctly stays split.
    ("Quartet for strings No 1 in D major Op 11",
     "String Quartet no 1 in D major, Op 11"),

    # Op 61 Suite No 4 'Mozartiana' — 2 variants fold.
    ("Suite No.4 in G major for orchestra (Op.61), 'Mozartiana'",
     "Suite No.4 in G major, Op 61, 'Mozartiana'"),
    ("Suite No.4, Op.61, 'Mozartiana'",
     "Suite No.4 in G major, Op 61, 'Mozartiana'"),

    # Op 48 Serenade for Strings — 2 word-order variants fold.
    ("Serenade in C major for strings (Op.48)",
     "Serenade for string orchestra in C major Op.48"),
    ("Serenade in C, op. 48",
     "Serenade for string orchestra in C major Op.48"),

    # Op 18 The Tempest (Burya) — 3 variants fold across Russian/English
    # title and "after Shakespeare" annotation.
    ("Burya  - symphonic fantasia after Shakespeare, Op 18",
     "The Tempest (Burya) - symphonic fantasia Op 18"),
    ("Burya (The Tempest) - symphonic fantasia after Shakespeare (Op.18)",
     "The Tempest (Burya) - symphonic fantasia Op 18"),
    ("The Tempest, op. 18, fantasy after Shakespeare",
     "The Tempest (Burya) - symphonic fantasia Op 18"),

    # Op 59 Dumka 'Russian rustic scene' — "for piano" scoring annotation.
    ("Dumka - Russian rustic scene for piano (Op.59)",
     "Dumka, Op 59 'Russian rustic scene'"),

    # Op 78 Voyevoda / Wojewode (Symphonic Ballad) — Russian/German title.
    ("Wojewode, symphonic ballad, Op 78",
     "Voyevoda - Symphonic Ballad Op 78"),
    ("The Voyevoda, symphonic ballad (Op.78)",
     "Voyevoda - Symphonic Ballad Op 78"),

    # Op 13 Symphony No 1 'Winter Daydreams' / Rêves d'hiver French
    # variant skipped: the variant key is shared with Méhul (×10) while
    # Tchaikovsky has only ×2 — below tail threshold and the cross-
    # composer entanglement makes the internal relabel misleading.

    # Waltz of the Flowers (from The Nutcracker) — word-order variant.
    ("The Nutcracker: Waltz of the Flowers",
     "Waltz of the Flowers (from The Nutcracker)"),

    # Op 24 Eugene Onegin — Introduction & waltz program (the most-aired
    # excerpt combination); two variant forms fold. Other excerpts
    # (Polonaise, Lensky's aria, Waltz Scene alone) correctly stay split.
    ("Eugene Onegin, Op 24 (Introduction & waltz)",
     "Eugene Onegin, Op 24 (Act 2: Introduction & waltz)"),
    ("Introduction and waltz from 'Eugene Onegin' - lyric scenes in 3 acts (Op.24)",
     "Eugene Onegin, Op 24 (Act 2: Introduction & waltz)"),

    # Op 70 Souvenir de Florence — "Allegro vivace" 4th-movement excerpt;
    # mvt/mvmt typo fold within the excerpt group.
    ("Souvenir de Florence (4th mvmt, 'Allegro vivace') Op 70",
     "Souvenir de Florence (4th mvt, 'Allegro vivace') Op 70"),

    # --- Dvořák audit (2026-05-27, via ttn_audit_composer) ------------------

    # Slavonic Dance Op 72 No 2 in E minor (= No 10 of the complete set
    # of 16) — multiple variants fold across full-set vs Op-only
    # numbering and the "Starodávny" nickname.
    ("Slavonic Dance no 10 in E minor Op 72 no 2",
     "Slavonic Dance in E minor, Op.72 no.2"),
    ("Slavonic Dance No 10 in E minor, Op 72 no 2, 'Starodavny'",
     "Slavonic Dance in E minor, Op.72 no.2"),
    ("Slavonic dance no 10 in E minor for piano duet, Op 72 no 2",
     "Slavonic Dance in E minor, Op.72 no.2"),
    ("Slavonic Dance No.9 in B minor, Op.72 No.1",
     "Slavonic Dance No.9 in B minor (Op.72 No.1) orch. composer"),

    # Slavonic Dance Op 72 No 4 in D flat major (= No 12 of 16) —
    # apostrophe notation + piano duet variant.
    ("Slavonic Dance No 12 in D flat major Op 72'4",
     "Slavonic Dance No 12 in D flat major Op 72 No 4"),
    ("Slavonic Dance No.12 (Op.72 No.4) in D flat major for piano duet",
     "Slavonic Dance No 12 in D flat major Op 72 No 4"),

    # Slavonic Dance Op 46 No 2 in E minor — bare-form (no key sig).
    ("Slavonic Dance (Op.46 No.2)",
     "Slavonic Dance in E minor, Op 46 no 2"),

    # Slavonic Dance Op 46 No 8 in G minor — orchestrated variant fold.
    ("Slavonic Dance in G minor, Op 46 No 8, orch composer (orig for pf duet)",
     "Slavonic Dance No. 8 in G minor, op. 46"),

    # Op 96 American Quartet — only ×2 excerpt currently splits; movement
    # excerpts correctly stay split.

    # Op 81 Piano Quintet in A major — bare-form (no "no 2"). Same work
    # as the indexed form. The Scherzo movement excerpt correctly stays
    # split.
    ("Piano Quintet no 2 in A major, Op 81",
     "Piano Quintet in A major, Op 81"),
    ("Quintet no. 2 in A major Op.81 for piano and strings",
     "Piano Quintet in A major, Op 81"),

    # Op 104 Cello Concerto in B minor — 2 word-order variants fold.
    ("Concerto for cello and orchestra no.2 (Op.104) in B minor",
     "Cello Concerto in B minor, Op 104"),
    ("Concerto for cello and orchestra in B minor, Op 104",
     "Cello Concerto in B minor, Op 104"),

    # Op 44 Wind Serenade in D minor — 3 variant forms fold.
    ("Serenade for wind instruments in D minor Op 44",
     "Wind Serenade in D minor, Op 44"),
    ("Serenade for winds in D minor, Op.44",
     "Wind Serenade in D minor, Op 44"),
    ("Serenade in D minor, op. 44",
     "Wind Serenade in D minor, Op 44"),

    # Op 90 'Dumky' Piano Trio No 4 — 3 variants fold (with/without "no 4"
    # and word-order).
    ("Trio in E minor, \"Dumky\" Op 90",
     "Piano Trio no 4 in E minor, Op 90 'Dumky'"),
    ("Trio for piano and strings no 4, Op 90 \"Dumky\"",
     "Piano Trio no 4 in E minor, Op 90 'Dumky'"),
    ("Piano Trio in E minor 'Dumky', Op 90",
     "Piano Trio no 4 in E minor, Op 90 'Dumky'"),

    # 'Song to the Moon' from Rusalka, Op 114 — bare-form (no Op) folds.
    ("Song to the Moon from Rusalka",
     "Song to the Moon from Rusalka, Op 114"),

    # Op 11 Romance in F minor — 2 variants fold (word-order and bare).
    ("Romance for violin and orchestra in F minor, Op 11",
     "Romance Op 11 in F minor vers. for violin and piano"),
    ("Romance in F minor, Op 11",
     "Romance Op 11 in F minor vers. for violin and piano"),

    # Op 59 No 4 Legend in C major — 2 variants fold (with "Molto
    # maestoso" tempo marking and "From Legends" parent-set framing).
    ("From \"Legends\" Op 59 No 4 (Molto maestoso) in C major",
     "Legend in C major, Op 59 no 4"),
    ("Legend in C major (Molto maestoso) (Op.59 No.4)",
     "Legend in C major, Op 59 no 4"),

    # Op 22 Serenade for Strings in E major — 2 variants fold. Larghetto
    # movement excerpt correctly stays split.
    ("String Serenade in E, op. 22",
     "Serenade for strings in E major, Op.22"),
    ("Serenade for String Orchestra in E major, Op.22, B.52",
     "Serenade for strings in E major, Op.22"),

    # Op 65 Piano Trio No 3 in F minor — word-order variant.
    ("Trio for piano and strings no 3 in F minor, Op 65",
     "Piano Trio no 3 in F minor, Op 65"),

    # Op 21 Piano Trio No 1 in B flat major — word-order variant.
    ("Trio for piano and strings No.1 (Op.21) in B flat major",
     "Piano Trio No 1 in B flat major, Op 21"),

    # Op 75 4 Romantic Pieces — "Four" spelled out variant. Single-piece
    # excerpt (Allegro appassionato) correctly stays split.
    ("Four Romantic Pieces, op. 75",
     "4 Romantic pieces, Op 75"),

    # Op 91 In Nature's Realm Overture — "concert overture" subtitle variant.
    ("In Nature's Realm, op. 91, concert overture",
     "In Nature's Realm (Overture), Op 91"),

    # --- Rachmaninov audit (2026-05-27, via ttn_audit_composer) -------------

    # Op 34 No 14 Vocalise — "for orchestra" scoring annotation + apostrophe
    # notation. Main group already merges multiple arrangement scorings
    # via _strip_arrangement_tail; "for orchestra" doesn't trigger the
    # strip (no "arr." marker) so needs explicit alias.
    ("Vocalise, Op 34 No 14 for orchestra",
     "Vocalise (Op.34 No.14)"),
    ("Vocalise, Op.34'14",
     "Vocalise (Op.34 No.14)"),

    # Op 35 The Bells (Kolokola) — 2 variant forms fold (poem subtitle +
    # "choral symphony" alt-subtitle).
    ("The Bells - poem for soloists, mixed choir and symphony orchestra (Op.35)",
     "The Bells (Kolokola) for soloists, chorus and orchestra, Op 35"),
    ("The Bells, op. 35, choral symphony",
     "The Bells (Kolokola) for soloists, chorus and orchestra, Op 35"),

    # Op 42 Variations on a Theme of Corelli — "for piano" scoring fold.
    ("Variations on a theme of Corelli for piano (Op.42)",
     "Variations on a Theme of Corelli, Op 42"),

    # Op 43 Rhapsody on a Theme of Paganini — "for piano and orchestra"
    # scoring fold.
    ("Rhapsody on a theme of Paganini Op.43 for piano and orchestra",
     "Rhapsody on a Theme of Paganini, Op 43"),

    # Op 17 Suite No 2 for 2 pianos — bare-form (no scoring) variant.
    ("Suite No 2 Op 17",
     "Suite no 2 for 2 pianos, Op 17"),

    # Op 19 Cello Sonata in G minor — bare-form word-order + Andante
    # movement excerpt variants. The Andante excerpt stays split from
    # the whole sonata; "(Andante)" and "from ... (Andante)" excerpt
    # forms fold together.
    ("Cello Sonata in G minor, op. 19",
     "Sonata for cello and piano in G minor (Op.19)"),
    ("Andante from Cello Sonata in G minor, Op 19",
     "Cello Sonata in G minor Op 19 (Andante)"),

    # Op 11 6 Duets for piano 4 hands — "Pieces" vs "Duets" + "Six"
    # spelled out variants.
    ("Pieces for four hands (Op.11)",
     "6 Duets Op 11 for piano 4 hands"),
    ("Six Pieces for four hands, Op 11",
     "6 Duets Op 11 for piano 4 hands"),

    # Op 37 Vespers (All-Night Vigil) — bare-form variant. Excerpt
    # programs correctly stay split.
    ("Vespers (All-Night Vigil), Op 37",
     "Vespers (All-night vigil) for chorus (Op.37)"),

    # Op 40 Piano Concerto No 4 in G minor — word-order variant.
    ("Concerto for piano and orchestra no.4 (Op.40) in G minor",
     "Piano Concerto No 4 in G minor, Op 40"),

    # Op 22 Variations on a Theme of Chopin — "for piano" scoring fold.
    ("Variations on a theme of Chopin, Op 22",
     "Variations on a theme of Chopin, Op 22 for piano"),

    # Op 36 Piano Sonata No 2 in B flat minor — word-order variant.
    ("Sonata No.2 in B flat Minor (Op.36)",
     "Piano Sonata No. 2 in B flat minor, op. 36"),

    # Op 12 Caprice bohémien — "Capriccio on Gypsy Themes" alt-subtitle.
    ("Caprice bohémien, Op 12 (Capriccio on Gypsy Themes)",
     "Caprice Bohemien, Op 12"),

    # 2 Songs (When Night Descends / Oh stop thy singing maiden fair)
    # — "Two" spelled out variant.
    ("Two Songs: When night descends in silence ; Oh, stop thy singing, maiden fair",
     "2 Songs: When Night Descends in silence; Oh stop thy singing maiden fair"),

    # Op 39 Etudes-Tableaux — excerpts I-VI program with 2 variant
    # framings. Single-excerpt entries (No 3, No 8 etc.) stay split.
    ("Etudes-Tableaux (Op.39) (I to VI only)",
     "Etudes-Tableaux, Op 39 (excerpts - I to VI)"),

    # --- Prokofiev audit (2026-05-27, via ttn_audit_composer) ---------------
    # Op 64 Romeo and Juliet — many generic "(excerpts)" forms whose
    # contents aren't specified left split as distinct broadcast units.
    # Op 115 Solo Violin Sonata movement excerpts (single movements
    # split across multiple notation variants) too risky to bulk-fold.
    # Op 33 Love for Three Oranges Suite vs Scherzo&March stay split.

    # Op 63 Violin Concerto No 2 — bare-key-sig variant.
    ("Violin Concerto No 2, Op 63",
     "Violin Concerto No 2 in G minor, Op 63"),

    # Op 60 Lieutenant Kijé Suite — word-order. Troika excerpt stays
    # split.
    ("Lieutenant Kije Suite, Op.60",
     "Lieutenant Kije - suite for orchestra, Op 60"),

    # Op 83 Piano Sonata No 7 — word-order. Precipitato 3rd-mvt excerpt
    # stays split.
    ("Piano Sonata No 7 in B flat, Op 83",
     "Sonata for piano no 7 in B flat major, Op 83"),

    # Op 94/94a/94bis Violin Sonata No 2 in D — Prokofiev's own violin
    # arrangement of his Op 94 flute sonata is catalogued as both 94a
    # and 94bis. Same work, two valid catalogue notations.
    ("Violin Sonata No. 2 in D, op. 94a",
     "Sonata for violin and piano no. 2 (Op.94bis) in D major"),

    # Op 100 Symphony No 5 — bare-key-sig variant.
    ("Symphony No.5 (Op.100)",
     "Symphony No. 5 in B flat, op. 100"),

    # Op 80 Violin Sonata No 1 in F minor — word-order.
    ("Sonata no. 1 in F minor Op.80 for violin and piano",
     "Violin Sonata no 1 in F minor, Op 80"),

    # Op 12 No 7 Prelude (from 10 Pieces for Piano) — bare-form variant.
    ("Prelude Op.12 No.7",
     "Prelude - No. 7 from 10 Pieces for piano (Op.12)"),

    # --- Janáček audit (2026-05-27, via ttn_audit_composer) -----------------
    # Kreutzer Sonata string-orchestra arrangement stays split per scoring
    # policy.

    # Taras Bulba (rhapsody for orchestra) — bare-form variant.
    ("Taras Bulba - Rhapsody",
     "Taras Bulba - rhapsody for orchestra"),

    # Pohádka (Fairy Tale) for cello and piano — 4 variants fold across
    # Czech-only "Pohadka", with/without English "(Fairy Tale)" subtitle,
    # and with/without "for cello and piano" scoring. All the same work.
    ("Pohadka",
     "Pohádka (Fairy Tale)"),
    ("Pohadka for cello and piano",
     "Pohádka (Fairy Tale)"),
    ("Pohadka (Fairy tale) for cello and piano",
     "Pohádka (Fairy Tale)"),

    # Šumařovo dítě (The Fiddler's Child) — "ballad for orchestra"
    # scoring annotation variant.
    ("The fiddler's child (Sumarovo dite) - ballad for orchestra",
     "Sumarovo dite (The Fiddler's Child)"),

    # --- Sibelius audit (2026-05-27, via ttn_audit_composer) ----------------
    # Op 14 Rakastava arrangements (chorus vs string orchestra) stay split
    # per scoring policy. Op 22 sibling pieces (Lemminkäinen's Return vs
    # The Swan of Tuonela) correctly stay split.

    # Op 49 Pohjola's daughter — bare-form (no subtitle).
    ("Pohjola's Daughter, Op 49",
     "Pohjola's daughter - symphonic fantasia, Op 49"),

    # Op 11 Ballad from Karelia Suite — "Ballad (Karelia suite)" vs
    # "Ballad from Karelia suite".
    ("Ballad from Karelia suite, Op 11",
     "Ballad (Karelia suite, Op 11)"),

    # Op 112 Tapiola — "symphonic poem" / "tone poem" subtitle variants.
    ("Tapiola - symphonic poem, Op. 112 (1926)",
     "Tapiola, Op 112"),
    ("Tapiola - tone poem Op.112",
     "Tapiola, Op 112"),

    # Op 22 Lemminkäinen's Return (No 4 of the Suite) — "from Lemminkainen
    # Suite" parent-set framing variant.
    ("Lemminkainen's Return - No.4 from Lemminkainen Suite, Op.22",
     "Lemminkainen's Return (Lemminkainen Suite) Op 22"),

    # Op 22 Lemminkäinen Suite (full set) — bare-form variant.
    ("Lemminkainen Suite, op 22",
     "Lemminkainen Suite: 4 Legends from the Kalevala for orchestra (Op 22)"),

    # Op 93 Jordens sang (Song of the Earth) — "cantata for chorus and
    # orchestra" scoring annotation.
    ("Jordens sang (Song of the Earth) - cantata for chorus and orchestra (Op.93)",
     "Jordens sang (Song of the Earth), Op 93"),

    # Op 114 5 Esquisses for piano — bare-form variant.
    ("Esquisses, Op 114",
     "5 Esquisses for piano, Op 114"),

    # Op 44 Valse triste (from Kuolema) — 4 variant forms collapse.
    ("Valse Triste - from Kuolemo (Op.44 No.1)",
     "Valse triste, from Kuolema, incidental music Op 44"),
    ("Valse Triste, from 'Kuolema, Op 44'",
     "Valse triste, from Kuolema, incidental music Op 44"),
    ("Valse triste (Kuolema - incidental music, Op 44)",
     "Valse triste, from Kuolema, incidental music Op 44"),
    ("Valse triste Op 44 no 1",
     "Valse triste, from Kuolema, incidental music Op 44"),

    # Op 42 Romance for strings in C major — word-order variant.
    ("Romance for string orchestra in C major (Op.42)",
     "Romance for strings in C major, Op 42"),

    # Op 51 Belshazzar's Feast Suite — "incidental music" framing variant.
    ("Belshazzar's Feast - suite from the incidental music, Op 51",
     "Belshazzar's feast suite, Op 51"),

    # Op 40 10 Pensées lyriques for piano — bare-form variant (no "10").
    ("Pensees Lyriques, Op.40",
     "10 Pensees lyriques for piano, Op 40"),

    # Op 70 Luonnotar — "symphonic poem" / "tone poem" subtitle variants.
    ("Luonnotar, Op 70, symphonic poem",
     "Luonnotar, Op 70"),
    ("Luonnotar, tone poem, Op 70",
     "Luonnotar, Op 70"),

    # Andante Festivo — bare-form (no scoring) variant. Caught by the
    # tool's new subset-detection pass.
    ("Andante Festivo",
     "Andante Festivo for strings and timpani"),

    # Op 105 Symphony No 7 in C — "(in one continuous movement)"
    # parenthetical variant.
    ("Symphony No 7 in C major Op 105 (in one continuous movement)",
     "Symphony no 7 in C major, Op 105"),

    # --- Handel audit (2026-05-28, via ttn_audit_composer) ------------------
    # 46 candidate clusters from the tool. This batch handles the high-
    # confidence merges: catalogue↔token bridges, catalogue-path quirks
    # (key-sig appendage, phantom numbers), HWV-bearing/no-HWV splits,
    # and multi-phrasing aria folds. Skipped: HWV.362 violin/oboe alt
    # scoring (precedent exists but warrants a separate explicit pass),
    # Lascia la spina (existing aliases need retarget decision), Aure deh
    # per pieta scena vs aria-only boundary, set-catalogue siblings.

    # HWV.363a / Op 1 no 5 F major — the existing line ~1092 alias was
    # retargeted. The "Oboe Sonata" variant needs its own bridge since it
    # tokenises with "oboe" and skips that alias's source key.
    ("Oboe Sonata in F major Op 1 No 5",
     "Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc"),

    # HWV.362 / Op 1 no 4 A minor — Pellerin's no-HWV oboe variants fold
    # into the HWV-bearing canonical (which already merges Lorenz violin
    # forms + the HWV-coded oboe form via line ~2286). Extends the
    # documented scoring-policy precedent (BWV.1056 / HWV.362 composer-
    # authored alt-scoring fold). Roed's recorder forms in
    # §hwv362|362|aminor stay separate for now — the broader "should all
    # three scorings collapse?" question is parked. See [[hwv362-alt-
    # scoring-deferred]] memory note for the open question.
    ("Oboe Sonata Op 1 No 4",
     "Violin Sonata in A minor (Op.1 No.4) (HWV.362)"),
    ("Oboe Sonata in A minor Op.1 No.4",
     "Violin Sonata in A minor (Op.1 No.4) (HWV.362)"),

    # HWV.365 / Op 1 no 7 C major. 2× no-HWV token-sort → 14× catalogue.
    ("Sonata in C major, Op 1 No 7",
     "Sonata for recorder and continuo (HWV.365) (Op.1`7) in C major"),

    # HWV.399 / Op 5 no 4 G major. 4× no-HWV token-sort → 8× catalogue.
    ("Trio Sonata in G major, Op 5 No 4",
     "Trio Sonata in G major (HWV 399) for 2 violins, viola and continuo Op 5 No 4"),

    # HWV.430 — Aria with Variations 'Harmonious Blacksmith'. The 4×
    # variant titled with "Piano Suite No.5" pushes a phantom "5" into
    # the catalogue path (§hwv430|430,5|e). Fold into the bare canonical.
    ("Aria with variations from Piano Suite No.5 in E major (HWV.430) \"The harmonious blacksmith\"",
     "Aria with Variations, HWV 430 'Harmonious Blacksmith'"),
    ("Aria with Variations from Piano Suite No.5 in E major, HWV.430, \"The harmonious blacksmith\"",
     "Aria with Variations, HWV 430 'Harmonious Blacksmith'"),
    ("Aria with Variations from Piano Suite No.5 in E major (HWV.430) \"The harmonious blacksmith\"",
     "Aria with Variations, HWV 430 'Harmonious Blacksmith'"),

    # HWV.237 — Laudate pueri Dominum. Key-signature appendage "in D"
    # on a multi-movement work that has no canonical home key. Same
    # case as Dixit Dominus in G minor (yesterday's batch).
    ("Laudate pueri Dominum in D, HWV 237",
     "Laudate pueri Dominum, HWV 237"),

    # HWV.45 — Gentle Morpheus from Alceste. 3× HWV-bearing form folds
    # into the 27× no-HWV plurality.
    ("Gentle Morpheus, son of night (Calliope's song) from 'Alceste' (HWV.45)",
     "Gentle Morpheus, son of night (Calliope's song) from Alceste"),
    ("Gentle Morpheus, Son of Night (Calliope's song) from 'Alceste' (HWV.45)",
     "Gentle Morpheus, son of night (Calliope's song) from Alceste"),

    # --- Handel arias from Giulio Cesare (2026-05-28) -----------------------

    # Va tacito e nascosto — Caesar's aria, Act 1 Sc 9. Three phrasings.
    ("'Va tacito e nascosto' (Giulio Cesare)",
     "Caesar's aria: 'Va tacito e nascosto' (from 'Giulio Cesare in Egitto', Act 1 Sc.9)"),
    ("'Va tacito e nascosto' (from Giulio Cesare in Egitto)",
     "Caesar's aria: 'Va tacito e nascosto' (from 'Giulio Cesare in Egitto', Act 1 Sc.9)"),
    ("'Va tacito e nascosto' from 'Giulio Cesare in Egitto'",
     "Caesar's aria: 'Va tacito e nascosto' (from 'Giulio Cesare in Egitto', Act 1 Sc.9)"),

    # Piangerò la sorte mia — Cleopatra's aria, Act 3 Sc 3. All five
    # phrasings now fold to the plurality canonical. The "Giulio Cesare,
    # HWV 17" parenthetical form (4×) was previously a catalogue-path FP
    # grouped with the §hwv17|17| suite; the _has_parent_work_reference
    # gate routes it to the token-sort path now, so this alias is safe.
    ("Piangerò la sorte mia (Giulio Cesare, HWV 17)",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),
    ("Piangerò la sorte mia, from 'Giulio Cesare, HWV.17'",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),
    ("Piangerò la sorte mia (excerpt 'Giulio Cesare', HWV 17)",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),
    ("Cleopatra's aria: 'Piangerò la sorte mia' - from 'Giulio Cesare', Act 3 Scene 3",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),

    # --- Handel arias from other operas (2026-05-28) ------------------------

    # Cara sposa — Rinaldo, Act 1 Sc 7. Five phrasings fold into the
    # plurality (12×) full-title form.
    ("Cara sposa, aria from Rinaldo",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),
    ("Cara sposa - aria from Rinaldo",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),
    ("Cara sposa - aria from 'Rinaldo'",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),
    ("Cara sposa, (Rinaldo)",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),
    ("Cara sposa (Rinaldo)",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),

    # Lascia ch'io pianga — Almirena's aria, Rinaldo Act 2 Sc 2.
    ("Lascia ch'io pianga (from Act 2 Sc 2 of 'Rinaldo' HWV.7)",
     "Lascia ch'io pianga from Act 2 Sc.2 of Rinaldo (HWV.7)"),
    ("Almirena's aria 'Lascia ch'io pianga' from Act 2 Sc.2 of 'Rinaldo' (HWV.7)",
     "Lascia ch'io pianga from Act 2 Sc.2 of Rinaldo (HWV.7)"),

    # Già che morir non posso — Radamisto aria. Existing 1084-1085 alias
    # already targets "Già che morir non posso - from 'Radamisto'"; add
    # the remaining phrasings to the same target.
    ("Radamisto (excerpt 'Già che morir non posso')",
     "Già che morir non posso - from 'Radamisto'"),
    ("'Già che morir non posso' – aria from Radamisto",
     "Già che morir non posso - from 'Radamisto'"),
    ("Aria \"Già che morir non posso\" - from 'Radamisto'",
     "Già che morir non posso - from 'Radamisto'"),

    # Ombra mai fu — Serse/Xerxes, Act 1. The piano-arr. plurality (4×)
    # absorbs Serse-named and HWV-coded variants. Same aria across all
    # five phrasings.
    ("Aria \"Ombra mai fu\" from Act 1 of the opera 'Serse'",
     "\"Ombra mai fu\" - from the opera 'Xerxes' arr. for piano"),
    ("Serse (Ombra mai fu, Act 1) HWV 40",
     "\"Ombra mai fu\" - from the opera 'Xerxes' arr. for piano"),
    ("Ombra mai fu (Serse, HWV 40 Act 1)",
     "\"Ombra mai fu\" - from the opera 'Xerxes' arr. for piano"),

    # Rejoice greatly, O daughter of Zion — Messiah aria.
    ("Rejoice Greatly, O Daughter of Sion (Messiah)",
     "Rejoice greatly, O daughter of Zion' (aria from \"The Messiah\")"),

    # Lascia la spina — same melody appears across Almira (1705,
    # instrumental Sarabande), Il Trionfo (1707, "Lascia la spina"
    # vocal), and Rinaldo (1711, "Lascia ch'io pianga", different text).
    # The Lezhneva/Petrou Almira-attributed VOCAL airing (m001dxyp) is
    # the Il Trionfo aria with the Almira ancestry credited; folds with
    # the other Il Trionfo airings. Instrumental Almira HWV 1 (Steger /
    # La Cetra) and the Rinaldo Lascia ch'io pianga group stay separate.
    ("Lascia la spina, from 'Almira', HWV 1",
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),
    # Long-form 9× group: "Aria 'Lascia la spina' - from the oratorio
    # \"Il Trionfo...\"" — all 4 sub-variants share the same work_key, so
    # one alias source covers them.
    ('Aria "Lascia la spina" - from the oratorio Il Trionfo del Tempo e del Disinganno',
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),
    # The bare cogli-la-rose form (no HWV.46a tag) that the existing
    # 1088-1091 aliases targeted; now itself aliased to the short
    # canonical so the cogli-la-rose group fuses with the plurality.
    ("Lascia la spina cogli la rose, from 'Il Trionfo del tempo e del disinganno'",
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),

    # Tu del Ciel ministro eletto — Bellezza's aria from Il Trionfo.
    # Five no-HWV phrasings collapse to the plurality (6×). The HWV.46a-
    # coded variant (at lines ~1073-1074) keeps its own target.
    ("\"Tu del Ciel ministro eletto\" - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),
    ("Tu del ciel ministro eletto - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),
    ("Tu del Ciel ministro eletto - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),
    ("Tu, del ciel ministro eletto from 'Il Trionfo del Tempo e del Disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),
    ("Tu, del ciel ministro eletto",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),

    # --- Bruckner audit (2026-05-28, via ttn_audit_composer) ---------------
    # Small catalogue (4 candidate clusters surfaced + a few symphony
    # WAB-annotation folds). Bruckner's symphonies have multiple known
    # versions (1873/1877/1889 for Sym 3, 1877/etc for Sym 2, Nowak/Schalk
    # editorial revisions) which the BBC sometimes flags explicitly —
    # those variants STAY SPLIT as a deliberate decision (parked per
    # [[composer-audit-campaign]] note on version-distinguishing splits).

    # Symphonies — WAB-catalogue annotation forms fold to the canonical
    # short forms (these are just catalogue annotations, not version tags).
    ("Symphony No 4 in E flat major, WAB 104, 'Romantic'",
     "Symphony No.4 in E flat major, 'Romantic'"),
    ("Symphony No 4 in E flat major, WAB.104, 'Romantic'",
     "Symphony No.4 in E flat major, 'Romantic'"),
    ("Symphony no 5 in B flat major, WAB 105",
     "Symphony No. 5 in B flat"),
    ("Symphony no 6 in A major, WAB 106",
     "Symphony No 6 in A major"),

    # Te Deum in C — extended-scoring form, "(1870)" date-annotated form,
    # and the bare "Te Deum" all fold (Bruckner has only one Te Deum).
    # The bare key is cross-composer (shared with Lassus, Sandström) —
    # composer-scoping keeps each composer's group correct.
    ("Te Deum in C (1870)",
     "Te Deum for soloists, chorus and orchestra in C major"),
    ("Te Deum",
     "Te Deum for soloists, chorus and orchestra in C major"),

    # Motets — 17×/5× "Locus iste & Christus Factus est" punctuation pair
    # folds; 15×/3× "3 Motets" / "(motets)" parenthesis pair folds.
    ("2 graduals for chorus: Locus iste; Christus Factus est",
     "2 graduals for chorus: Locus iste & Christus Factus est"),
    ("Ave Maria; Christus factus est; Locus iste (motets)",
     "3 Motets: Ave Maria; Christus factus est; Locus iste"),

    # Psalm 150 WAB 38 — dot/space catalogue variants fold.
    ("Psalm 150, WAB.38",
     "Psalm 150, WAB 38"),

    # Mass no 3 in F minor WAB.28 — dot/space catalogue variants fold.
    ("Mass no 3 in F minor, WAB.28",
     "Mass no 3 in F minor, WAB 28"),

    # --- Schumann audit (2026-05-28, via ttn_audit_composer) ----------------
    # 36 candidate clusters. Cycle/collection flag correctly fired on Op 48
    # Dichterliebe + Op 39 Liederkreis + Op 25 Myrthen (after extending the
    # token list with 'liederkreis' / 'myrten'). Skipped: Op 7 / Op 10 /
    # Op 13 / Op 15 / Op 16 / Op 17 / Op 20 (Clara Schumann's DIFFERENT
    # Op N works — cross-composer not same-work), Op 41 String Quartets
    # (3 distinct works, set-catalogue siblings), Op 44 / Op 47 / Op 12
    # / Op 23 / Op 6 / Op 82 individual movement excerpts (stay split),
    # Op 35 / Op 21 individual songs/novelettes (distinct works), Op 120
    # Symphony 4 1841 vs 1851 versions (parked like the Bruckner-versions
    # question — stay split for now), Op 46 alt-scoring (parked).

    # Op 73 Phantasiestücke for clarinet — extended-scoring "violin or
    # cello" variant folds (composer-authored alternative instrument
    # specifications, but the same work).
    ("Fantasiestücke for clarinet (violin or cello) and piano, Op 73",
     "Phantasiestucke Op 73 for clarinet & piano"),

    # Op 18 Arabeske in C — "Arabesque" English spelling folds.
    ("Arabesque, Op 18",
     "Arabeske for piano in C major, Op 18"),

    # S.566 Widmung (Liszt transcription of Schumann) — three phrasings fold.
    ("Widmung S.566, transc. for piano",
     "Widmung S.566, transcribed for piano"),
    ("Widmung from Liederkreise, S.566",
     "Widmung S.566, transcribed for piano"),

    # Op 133 Gesänge der Frühe — extended-subtitle form folds.
    ("Gesänge der Frühe (Chants de l'Aube) (Op.133) - 5 pieces for piano dedicated to the poet Bettina Brentano",
     "Gesange der Fruhe - Songs of Dawn, Op 133"),

    # Op 135 Mary Stuart Gedichte — "Konigen" BBC misspelling and short-form
    # variants fold to the corrected "Konigin" spelling.
    ("5 Gedichte der Konigen Maria Stuart (5 Poems of Queen Mary Stuart), Op 135",
     "5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135"),
    ("Gedichte der Königin Maria Stuart, Op 135",
     "5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135"),

    # Violin Concerto in D minor (Op.posthumous) — word-order variant.
    ("Concerto for Violin and Orchestra in D minor (Op.posthumous)",
     "Violin Concerto in D minor (Op.posthumous)"),

    # Op 86 Konzertstück for 4 Horns in F — typo + word-order variants.
    ("Koncertstuck in F major for 4 Horns and Orchestra, Op 86",
     "Konzertstück in F major for 4 Horns and Orchestra, Op 86"),
    ("Konzertstück for four horns and Orchestra, Op.86",
     "Konzertstück in F major for 4 Horns and Orchestra, Op 86"),

    # Op 85 Abendlied no 12 — slash-format Op number folds.
    ("Abendlied, op. 85/12",
     "Abendlied, Op 85 no 12"),

    # Op 92 Introduction and Allegro appassionato — "in G major" key-sig
    # annotation folds.
    ("Introduction and Allegro appassionato in G major Op 92",
     "Introduction and Allegro appassionato (Op.92)"),

    # Op 126 7 Klavierstücke in Fughettenform — "(excerpts)" generic form
    # folds with the specific "(nos.5-7)" canonical. The two refer to
    # the same airing selection in practice.
    ("7 Klavierstucke in Fughettenform Op.126 for piano (excerpts)",
     "7 Klavierstucke in Fughettenform Op.126 for piano (nos.5-7)"),

    # --- Mendelssohn audit (2026-05-28, via ttn_audit_composer) ------------
    # 35 candidate clusters. Skipped: Op 6 / Op 8 / Op 11 (Fanny Mendelssohn's
    # different Op N works — cross-composer not same-work; composer-scoping
    # handles those naturally). Other set-catalogue ops (Op 30 / Op 67 /
    # Op 65 organ sonatas) contain distinct Songs Without Words / sonatas.

    # Hebrides Op 26 — bare "Hebrides - overture" short form. Existing
    # alias chain (line ~977) targets "The Hebrides, Op 26"; reuse that.
    ("Hebrides - overture",
     "The Hebrides, Op 26"),

    # Op 13 String Quartet No 2 in A minor — word-order variant + "A major"
    # BBC typo (the work IS in A minor).
    ("Quartet for strings No 2 Op 13 in A minor",
     "String Quartet no 2 in A minor, Op 13"),
    ("String Quartet No 2 in A major, Op 13",
     "String Quartet no 2 in A minor, Op 13"),

    # Op 14 Rondo capriccioso — word-order variant ("for piano").
    ("Rondo capriccioso for piano in E major/minor (Op.14)",
     "Rondo capriccioso in E major/minor, Op 14"),

    # Op 15 Fantasia / "Fantasy" on an Irish Song — spelling variant.
    ("Fantasy on an Irish Song 'The Last Rose of Summer', Op.15",
     "Fantasia on an Irish song \"The last rose of summer\" for piano Op 15"),

    # Op 27 Meeresstille und glückliche Fahrt — English subtitle + bare
    # English-title forms fold to German canonical.
    ("Meeresstille und gluckliche Fahrt (Calm sea and a prosperous voyage) - overture (Op.27)",
     "Meeresstille und gluckliche Fahrt - Overture, Op 27"),
    ("Calm Sea and a Prosperous Voyage - overture, Op.27",
     "Meeresstille und gluckliche Fahrt - Overture, Op 27"),

    # Op 32 Die schöne Melusine — English title folds to German canonical.
    ("The Fair Melusina, op. 32, overture",
     "Die schöne Melusine  - overture Op 32"),

    # Op 36 St Paul Overture — "Overture to" word-order variant.
    ("Overture to 'St Paul', Op 36",
     "St.Paul, Op 36, Overture"),

    # Op 39 Laudate Pueri — backtick form + English subtitle fold to canonical.
    ("Laudate Pueri - motet, Op.39'2",
     "Laudate Pueri - motet, Op 39 no 2"),
    ("Motet: Laudate Pueri (O praise the Lord), Op 39 No 2",
     "Laudate Pueri - motet, Op 39 no 2"),

    # Op 44 String Quartet in D major No 1 — backtick form folds.
    ("Quartet for strings in D major, Op.44'1",
     "Quartet for strings in D major, Op  44 no 1"),

    # Op 54 Variations sérieuses — the "(1841)" annotated form folds with
    # the short canonical. Plurality tied; pick the (1841) form arbitrarily.
    ("Variations Serieuses, Op54",
     "Variations serieuses in D minor (Op.54) (1841)"),

    # Op 56 Symphony No 3 'Scottish' — short form (no Op number) folds.
    ("Symphony No.3 in A minor, 'Scottish'",
     "Symphony no 3 in A minor, Op 56 'Scottish'"),

    # Op 61 A Midsummer Night's Dream — "Excerpts from" form folds with
    # the incidental music canonical; the two "Suite from" forms fold
    # with each other.
    ("Excerpts from 'A Midsummer Night's Dream, op. 61' (incidental music)",
     "A Midsummer Night's Dream - incidental music (Op.61)"),
    ("A Midsummer Night's Dream, suite, op. 61",
     "Suite from 'A Midsummer Night's Dream', Op.61"),

    # Op 64 Violin Concerto in E minor — word-order variant ("Concerto
    # for violin and orchestra in E minor (Op.64)").
    ("Concerto for violin and orchestra in E minor (Op.64)",
     "Violin Concerto in E minor, Op 64"),

    # Op 66 Piano Trio No 2 — word-order variant ("Trio for piano and
    # strings No.2 (Op.66) in C minor").
    ("Trio for piano and strings No.2 (Op.66) in C minor",
     "Piano Trio no 2 in C minor, Op 66"),

    # Op 81 Capriccio in E minor No 3 — "Op 81 no 3" folds with the
    # plurality "Op.81`3" backtick form.
    ("Capriccio in E minor, Op 81 no 3",
     "Capriccio in E minor, Op.81`3"),

    # Op 87 String Quintet No 2 in B flat — short form (no "No 2") folds.
    ("String Quintet in B flat, op. 87",
     "String Quintet No 2 in B flat major, Op 87"),

    # Op 107 Symphony No 5 'Reformation' — the "D minor" BBC typo (the
    # work IS in D major). Same edge case as Mahler Symphony 1 'Titan'
    # implicit-major handling.
    ("Symphony no 5 in D minor, op 107 'Reformation'",
     'Symphony No.5 in D major "Reformation" (Op.107)'),

    # Op 109 Song Without Words in D — English title folds to the German
    # canonical (Lied ohne Worte). Plurality tied 3/3; original language wins.
    ("Song Without Words, Op 109",
     "Lied ohne Worte in D major, Op 109"),

    # Hora est — "(antiphon and responsorium)" form folds to bare.
    ("Hora est (antiphon and responsorium)",
     "Hora est"),

    # Op 78 Richte mich, Gott (Psalm 43) — the long-form English "(Psalm
    # 43), from 3 Psalmen" variant folds with the short canonical.
    ("Richte mich, Gott (Psalm 43), from 3 Psalmen, Op 78",
     "Richte mich, Gott, Op 78 no 2"),

    # Op 42 Psalm 42 'Wie der Hirsch schreit' — long "nach frischem
    # Wasser" subtitle folds with the short canonical.
    ("Psalm 42 'Wie der Hirsch schreit nach frischem Wasser, op. 42'",
     "Psalm 42 'Wie der Hirsch schreit', Op 42, cantata"),

    # 'Denn er hat seinen Engeln befohlen' (from Elias) — the "from 'Elias'"
    # annotation folds with the bare aria title (same Elias aria either way).
    ("Denn er hat seinen Engeln befohlen, from 'Elias'",
     "Denn er hat seinen Engeln befohlen"),

    # --- Vivaldi audit (2026-05-28, via ttn_audit_composer) -----------------
    # 23 candidate clusters surfaced. The new set-catalogue flag fired
    # correctly on 4 collections (Op 3 / Op 4 / Op 8 / multi-RV 'cellos'
    # cluster) — those are SKIPPED. Pass 1b cross-path bridges: 0 new
    # candidates (RV.565 was the only one, already aliased above). This
    # batch handles the multi-phrasing folds within distinct RV works.

    # RV.595 Dixit Dominus — no-RV scoring form folds to canonical.
    ("Dixit Dominus for SSATB soloists and double choir and orchestra in D major",
     "Dixit Dominus in D major, RV.595"),

    # RV.610 Magnificat — "RV 610/611" (lists both versions) and the
    # extended-scoring form fold to the bare canonical.
    ("Magnificat RV 610/RV 611",
     "Magnificat in G minor, RV 610"),
    ("Magnificat in G minor, RV.610, for SSAT soloists, choir, 2 oboes, strings and continuo",
     "Magnificat in G minor, RV 610"),

    # RV.93 Lute Concerto in D — short title folds to scored canonical.
    ("Lute Concerto in D major, RV 93",
     "Concerto for lute, 2 violins & continuo in D major, RV.93"),

    # RV.178 Violin Concerto Op 8 No 12 — the "in C major" key-sig
    # annotation folds (the work IS in C; the annotation is descriptive).
    ("Violin Concerto in C major, Op 8 No 12 (RV 178)",
     "Violin Concerto, Op 8 No 12, RV 178"),

    # RV.567 Concerto for 4 violins, cello in F — Op 3 No 7. The no-Op
    # variant and the alt-ordering "Op.3 No.7, RV.567" variant fold.
    ("Concerto for 4 violins, cello and orchestra in F major, RV.567",
     "Concerto for 4 violins, cello and orchestra (RV.567) Op 3 No 7 in F major"),
    ("Concerto for four violins & basso continuo in F, Op.3 No.7, RV.567",
     "Concerto for 4 violins, cello and orchestra (RV.567) Op 3 No 7 in F major"),

    # RV.315 L'Estate (Summer) — the bare form (no Op 8 No 2) folds.
    # Movement excerpts ("Presto from...", "(excerpt)") stay split.
    ("Concerto for violin & orchestra in G minor 'L'Estate', RV.315",
     "Concerto for violin & orchestra (RV.315) (Op.8 No.2) in G minor 'L'Estate'"),

    # RV.608 Nisi Dominus — "Psalm:" prefix form and key-sig form fold
    # to the "(Psalm 127)" canonical.
    ("Psalm: Nisi Dominus, RV.608",
     "Nisi Dominus (Psalm 127) for voice and orchestra (RV.608)"),
    ("Nisi Dominus in G minor, RV 608",
     "Nisi Dominus (Psalm 127) for voice and orchestra (RV.608)"),

    # RV.108 Concerto for recorder in A minor — the "sopranino recorder"
    # scoring variant folds to canonical.
    ("Concerto for sopranino recorder, two violins and continuo, RV 108",
     "Concerto in A minor for recorder, two violins and basso continuo, RV 108"),

    # RV.522 Op 3 No 8 — the "from L'estro Armonico" form folds to bare.
    ("Concerto VIII in A minor for 2 violins, strings and continuo, RV 522, from 'L'estro Armonico', Op 3",
     "Concerto VIII in A minor for 2 violins, strings and continuo, RV 522"),

    # RV.104 La Notte (flute concerto in G minor) — extended-scoring
    # form folds to the canonical.
    ("Concerto in G minor, RV 104, (La notte) for flute, 2 violins, bassoon and continuo",
     "Flute Concerto in G minor, RV104 (La Notte)"),

    # RV.293 L'Autunno (Autumn from Four Seasons) — the "Autumn" bare
    # English title folds to the canonical Italian Op 8 No 3 form.
    ("Violin Concerto in F major, RV 293, 'Autumn'",
     "Concerto for violin & orchestra RV.293 Op 8 No 3 in F major 'L'Autunno'"),

    # RV.230 Op 3 No 9 — "Concerto IX" Roman-numeral form folds to the
    # canonical. The 2× Larghetto excerpt stays its own group.
    ("Concerto IX in D major (RV.230), from 'L'Estro Armonico', Op 3",
     "Violin Concerto in D (Op.3 No.9) (RV.230)"),

    # Sonata a quattro in C — the extended-scoring form folds.
    ("Sonata a quattro in C major for 2 oboes, bassoon & continuo",
     "Sonata a quattro in C major"),

    # --- Vivaldi RV.565 audit (2026-05-28, ttn_audit_composer Pass 1b) ----
    # First catch by the new Op↔catalogue-ref cross-path bridge. The
    # 10× catalogue-bearing form ("RV.565 Op 3 No 11") bridged the 23×
    # token-sort canonical ("Op.3 No.11 from L'Estro Armonico") and a
    # 4× truncated variant ("from 'L'Estro" without "Armonico"). All
    # three groups are the same L'Estro Armonico concerto for 2 violins,
    # cello and continuo in D minor.
    ("Concerto in D minor for 2 violins, cello and orchestra RV.565 Op 3 No 11",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),
    ("Concerto in D minor (Op.3 No.11) from 'L'Estro",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),
    # Stragglers found while applying the Pass 1b candidate: bare RV.565
    # forms and a minimal Op-bearing form, each below the 4-airing tool
    # threshold.
    ("Concerto in D minor, RV.565",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),
    ("Concerto in D minor for 2 violins, cello and orchestra RV.565",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),
    ("Concerto in D minor, RV.565 Op 3 no 11",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),

    # --- Mahler audit (2026-05-28, via ttn_audit_composer) -----------------
    # 8 candidate clusters surfaced. Mahler's catalogue is uniformly
    # attributed by the BBC; lower yield than Schubert/Handel. Skipped:
    # Kindertotenlieder individual songs ("Nun seh' ich…", "Oft denk'
    # ich…"), individual Wunderhorn songs, Alma Mahler cross-composer
    # cluster, "Excerpts from Des Knaben Wunderhorn" multi-song program.

    # Rückert-Lieder whole-collection — bare and "5 Rückert-Lieder"
    # (phantom "5" prefix counting the 5 songs in the set) fold. The
    # individual songs (Ich bin der Welt, Ich atmet, Liebst du um
    # Schönheit) stay split — each is its own group.
    ("Rückert-Lieder",
     "5 Ruckert-Lieder"),

    # Ich bin der Welt abhanden gekommen — the most-aired Rückert song.
    # The "from 'Rückert-Lieder'" phrasing folds with the parenthetical
    # canonical (both refer to the same song, in the same collection).
    ("Ich bin der Welt abhanden gekommen, from 'Rückert-Lieder",
     "Ich bin der Welt abhanden gekommen (Rückert Lieder)"),
    ("Ich bin der Welt abhanden gekommen, from 'Rückert-Lieder'",
     "Ich bin der Welt abhanden gekommen (Rückert Lieder)"),

    # Ich ging mit Lust durch einen grünen Wald — same song, the
    # parenthetical "(no.7 from Lieder und Gesänge aus der Jugendzeit)"
    # variant identifies the source collection. Same melody also forms
    # the 1st-movement opening theme of Symphony No 1, but the song
    # and the symphonic appearance stay as their own works.
    ("Ich ging mit Lust durch einen grünen Wald (I walked with joy through a green forest) (no.7 from Lieder und Gesänge aus der Jugendzeit)",
     "Ich ging mit lust durch einen grunen Wald"),

    # Symphony No 1 'Titan' — edge case: `_drop_implicit_major` strips
    # the trailing "major" only after the "in <note>" pattern, so
    # "in D major" → "in D" but bare "D major" stays. The 2× "Symphony
    # No.1 D major, 'Titan'" form lacks "in" and so doesn't fold with
    # the 24× canonical. One alias bridges the gap.
    ("Symphony No.1 D major, 'Titan'",
     "Symphony no 1 in D major, 'Titan'"),

    # Symphony No 2 'Resurrection' — the verbose-scoring form (with
    # "for soprano, alto, chorus and orchestra") folds with the short
    # canonical. Same work, scoring annotation is redundant.
    ("Symphony No.2 in C minor for soprano, alto, chorus and orchestra \"Resurrection\"",
     "Symphony No. 2 in C minor ('Resurrection')"),

    # Adagietto from Symphony No 5 — the short form (no key signature)
    # folds with the canonical. The Adagietto is the famous 4th-movement
    # excerpt; both forms are the same excerpt.
    ("Adagietto, from Symphony No. 5",
     "Adagietto, from Symphony no 5 in C sharp minor"),

    # Symphony No 10 — Adagio is the only completed movement. The two
    # variants (parenthetical "(Adagio)" vs "Adagio, from ... (unfinished)")
    # fold. The 4 airings are split 2/2 between the forms.
    ("Symphony No 10 (Adagio)",
     "Adagio, from 'Symphony No. 10 in F sharp' (unfinished)"),

    # Des Knaben Wunderhorn whole-collection — the "Songs from" prefix
    # folds with the bare canonical. Individual songs (Rheinlegendchen,
    # Verlorne Müh, etc.) stay split.
    ("Songs from 'Des Knaben Wunderhorn'",
     "Des Knaben Wunderhorn"),
    ("Songs from Des Knaben Wunderhorn",
     "Des Knaben Wunderhorn"),

    # --- Schubert audit (2026-05-28, via ttn_audit_composer) ---------------
    # 54 candidate clusters surfaced. This batch handles the high-confidence
    # high-yield merges. Skipped: D.899 / D.935 Impromptus (set-catalogue
    # siblings, distinguished by key — DO NOT touch), D.780 individual
    # movements, individual Winterreise songs (cycle denylist), Sehnsucht
    # as distinct settings (D.123, D.636, D.658, D.879 are different works),
    # Mahler arrangement of D.810 (alt scoring, stays split), Liszt's
    # transcription of D.760 Wandererfantasie (different work from the
    # original).

    # D.821 Arpeggione Sonata — bare-form / token-sort siblings of the 60×
    # catalogue canonical.
    ("Arpeggione Sonata in A minor",
     "Sonata in A minor D.821 for arpeggione (or viola or cello) and piano"),
    ("Arpeggione Sonata",
     "Sonata in A minor D.821 for arpeggione (or viola or cello) and piano"),

    # D.780 Six Moments musicaux — phantom "6" from "6 Moments Musicaux"
    # vs "Six Moments musicaux" splits two whole-collection groups. The
    # individual movement (": no 3 in F minor") stays split via its own
    # number/key.
    ("6 Moments Musicaux (D.780)",
     "Six Moments musicaux, D. 780"),

    # D.703 Quartettsatz — D.703 IS the only completed movement; the
    # "(movement) for strings" parenthetical triggers the existing
    # 'movement' locator and routes to token-sort.
    ("Quartettsatz (movement) for strings in C minor (D.703)",
     "Quartettsatz in C minor, D.703"),

    # D.774 Auf dem Wasser zu singen — "Barcarolle" alt-title.
    ("Barcarolle (Auf dem Wasser zu singen)",
     "Auf dem Wasser zu singen, D.774"),

    # D.957 Ständchen from Schwanengesang. The 10× canonical "Standchen,
    # D957" is the plurality. Four other phrasings (arr.-for-piano, "from
    # Schwanengesang", D.957'4 backtick, D.957/4 slash) fold to it. Note:
    # the bare "Ständchen" key is shared with Strauss — the alias relabels
    # the key but composer-scoping keeps Schubert and Strauss in separate
    # groups (display follows airing count within each).
    ("Ständchen arr. for piano - from Schwanengesang (D. 957)",
     "Standchen, D957"),
    ("Standchen from Schwanengesang (D.957)",
     "Standchen, D957"),
    ("Ständchen, D.957'4",
     "Standchen, D957"),
    ("Ständchen, D. 957/4",
     "Standchen, D957"),

    # D.810 String Quartet No 14 "Death and the Maiden". 3× bare form
    # folds into 27× canonical. Mahler's string-orchestra arrangement
    # stays split as composer-non-authored alt-scoring.
    ("String Quartet in D minor, D810 'Death and the Maiden'",
     "String Quartet No 14 in D minor, D 810 'Death and the Maiden'"),

    # D.312b Hektors Abschied — Op.58 No.1 annotation form folds to bare.
    ("Hektors Abschied (D.312b, Op.58 No.1)",
     "Hektors Abschied D.312b"),

    # D.544 Ganymed — Op.19 No.3 + "from 3 Songs" annotation folds to bare.
    ("Ganymed (D.544) - from 3 Songs (Op.19 No.3)",
     "Ganymed, D.544"),

    # D.161 An Mignon — Op.19 No.2 + "from 3 Songs" annotation. The
    # token-sort 5× form folds into the catalogue-path 2× canonical.
    # Target chosen to bypass the existing line ~1017 alias chain (which
    # itself folds "An Mignon from 3 Songs, D.161" → this string).
    ("An Mignon (D.161) from 3 Songs, Op 19 no 2 (To Mignon)",
     "An Mignon (D.161), Op.19 No.2 (To Mignon)"),

    # S.366 Wandererfantasie (Liszt's transcription of D.760) — the two
    # phrasings "arranged by Liszt" and "transcribed for piano and
    # orchestra" fold; Schubert's original D.760 stays split.
    ("Wandererfantasie, transcribed for piano and orchestra (S.366)",
     "Wandererfantasie, D760 arranged by Liszt (S.366)"),

    # D.965 Der Hirt auf dem Felsen — Op.129 annotation forms fold to
    # the bare D.965 canonical.
    ("Der Hirt auf dem Felsen, Op.129 (D965)",
     "Der Hirt auf dem Felsen, D965"),
    ("Der Hirt auf dem Felsen, Op.129",
     "Der Hirt auf dem Felsen, D965"),

    # D.478 Wer sich der Einsamkeit — "ergibit" typo folds with the
    # correct "ergibt".
    ("Wer sich der Einsamkeit ergibit (D.478) from Three Songs of the Harpist Op 12",
     "Wer sich der Einsamkeit ergibt (D.478) from Three Songs of the Harpist"),

    # D.911 Winterreise whole-cycle forms (NOT the individual songs,
    # which the cycle denylist correctly keeps split).
    ("Winterreise, D.911 (arr. for voice & piano trio)",
     "Winterreise, D.911"),
    ("Winterreise - song-cycle, D.911",
     "Winterreise, D.911"),

    # 3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest —
    # the "(including between songs)" annotation form folds.
    ("3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest (including between songs)",
     "3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest"),

    # --- Handel audit follow-up (2026-05-28): gate-fix mop-up ---------------

    # Bach BWV 4 — Christ lag in Todesbanden. The
    # `_has_parent_work_reference` gate fires on "(Cantata BWV 4)"
    # because "Cantata" reads as a name-like word in the parenthetical's
    # residue. Semantically this is annotation, not a parent reference
    # — Christ lag IS BWV 4 (the whole cantata). The 1× variant goes
    # to token-sort via the gate; this alias folds it back into the
    # 11× §bwv4|4| canonical group. See [[catalogue-path-phantom-
    # ordering]] for the gate's known FP shape.
    ("Christ lag in Todesbanden (Cantata BWV 4)",
     "Cantata 'Christ lag in Todesbanden', BWV 4"),

    # --- Handel Concerto Grosso Op 6 audit (2026-05-28) ---------------------
    # 85 airings across 17 groups. The main split mechanism is HWV-bearing
    # title (catalogue path, key includes HWV###) vs no-HWV (token-sort
    # path, key is sorted tokens). Backtick "Op.6`N" forms tokenize as
    # glued digits ("65" = "Op.6`5") and split too.
    #
    # Op 6 No 4 in A minor — HWV 322. Plurality (5×) lacks HWV; fold the
    # 5× HWV-bearing variants into it (10× total → 15× consolidated).
    ("Concerto grosso in A minor, HWV 322, Op 6 no 4",
     "Concerto Grosso in A minor, Op 6 no 4"),
    ("Concerto grosso in A minor, Op 6 no 4 (HWV 322)",
     "Concerto Grosso in A minor, Op 6 no 4"),
    ("Concerto grosso in A minor, Op 6 No 4 (HWV 322)",
     "Concerto Grosso in A minor, Op 6 no 4"),

    # Op 6 No 5 in D — HWV 323. Plurality (15×) is no-HWV "Op 6 no 5";
    # fold the 2× HWV-only forms and the 1× backtick. The existing
    # Dmajor-typo alias was retargeted earlier in the table.
    ("Concerto Grosso in D, HWV 323",
     "Concerto Grosso in D major, Op 6 no 5"),
    ("Concerto grosso in D major Op.6`5",
     "Concerto Grosso in D major, Op 6 no 5"),

    # Op 6 No 7 in B flat — HWV 325. Plurality (9×) is HWV-bearing;
    # fold the 2× no-HWV variants into it (→ 11× consolidated).
    ("Concerto Grosso in B flat Op.6 No.7",
     "Concerto grosso in B flat major Op.6 No.7 HWV.325"),
    ("Concerto Grosso in B flat, Op 6 No 7",
     "Concerto grosso in B flat major Op.6 No.7 HWV.325"),

    # Op 6 No 11 in A — HWV 329. Plurality (3×) is no-HWV "Op 6 no 11";
    # fold the 1× backtick form (→ 4× consolidated).
    ("Concerto grosso in A major, Op.6`11",
     "Concerto Grosso in A major (Op.6 No.11)"),

    # --- Handel Dixit Dominus (2026-05-28) ----------------------------------
    # HWV.232 is Handel's 1707 setting of Psalm 110. Bare-form (×15) is the
    # plurality. Three variants split on the catalogue path:
    #   - "Psalm 110" descriptive suffix pushes a phantom "110" into the key
    #     (×13 across three spacings)
    #   - "in G minor" key-signature appendage (×2) on a multi-movement work
    #     that has no canonical home key
    # The ×3 "no.7; De torrente in via bibet" group is the 7th-movement aria
    # — genuine excerpt, stays split.
    ("Dixit Dominus - Psalm 110, HWV.232",
     "Dixit Dominus, HWV 232"),
    ("Dixit Dominus - Psalm 110 HWV.232",
     "Dixit Dominus, HWV 232"),
    ("Dixit Dominus - Psalm 110 HWV 232",
     "Dixit Dominus, HWV 232"),
    ("Dixit Dominus in G minor, HWV.232",
     "Dixit Dominus, HWV 232"),
]


def _build_work_alias_table():
    table = {}
    for variant, preferred in _WORK_ALIAS_PAIRS:
        table[work_title_key(variant)] = work_title_key(preferred)
    return table


WORK_ALIASES = _build_work_alias_table()


def resolve_work_alias(work_key: str) -> str:
    return WORK_ALIASES.get(work_key, work_key)


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
        wk = resolve_work_alias(work_title_key(title))
        composer_keys[ck] += 1
        work_keys[(ck, wk)] += 1
        tracks_per_episode[episode_pid] += 1
        composer_display_counts[ck][composer] += 1
        work_display_counts[(ck, wk)][title] += 1

    for ck, counter in composer_display_counts.items():
        composer_display[ck] = counter.most_common(1)[0][0]
    for key, counter in work_display_counts.items():
        work_display[key] = counter.most_common(1)[0][0]

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

    top_composers = sorted(composer_keys.items(), key=lambda kv: -kv[1])[:5]
    top_works = sorted(work_keys.items(), key=lambda kv: -kv[1])[:5]

    # Composers ranked by distinct works (breadth of repertoire) rather
    # than total airings. Derived from work_keys' (ck, wk) tuples.
    composer_n_works = defaultdict(int)
    for (ck, _wk) in work_keys:
        composer_n_works[ck] += 1
    top_composers_by_works = sorted(
        composer_n_works.items(), key=lambda kv: -kv[1])[:5]

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
    """sha1 over ttn_analyze.py's bytes. Editing canonical_key, an alias
    table, or compute_summary itself invalidates the cache."""
    h = hashlib.sha1()
    try:
        with open(__file__, "rb") as fh:
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


def summary_for_rows(rows, cache_path=None):
    """Cached compute_summary for an already-prepared row set (arranger
    tails stripped). Reads the self-keyed slot, computing and writing it on
    a miss. Returns (stats, was_cached) — the single source of truth for the
    cache dance, shared by `main`'s --summary path and ttn_warm.py."""
    if cache_path is None:
        cache_path = summary_cache_path()
    data_fp = _summary_data_fingerprint(rows)
    code_fp = _summary_code_fingerprint()
    stats = _read_summary_cache(cache_path, data_fp, code_fp)
    if stats is not None:
        return stats, True
    stats = compute_summary(rows)
    _write_summary_cache(cache_path, data_fp, code_fp, stats)
    return stats, False


_BUCKET_ORDER = ("1", "2-5", "6-10", "11-50", "51-100", "100+")


def render_summary(stats):
    out = []
    out.append(f"Tracks per episode:   {stats['tracks_per_episode_mean']:.1f} mean, "
               f"{stats['tracks_per_episode_median']} median")
    out.append("")
    out.append(f"Distinct composers:   {stats['n_distinct_composers']:,}")
    out.append(f"Distinct works:       {stats['n_distinct_works']:,}  "
               f"(composer × work groups, post-alias)")
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
    escaped (so '.' / parens / numbers stay literal) and wrapped in \\b…\\b
    so e.g. 'concerto' does not match 'concertino'."""
    return r"\b" + re.escape(user_input) + r"\b"


def _form_filter_clauses(form_name):
    """Build a (sql_clause, params) pair for the --form filter. The clause
    is an OR of word-boundary REGEXP predicates over t.title, one per
    synonym. Combinable with --title (caller AND-joins them)."""
    synonyms = _FORM_SYNONYMS[form_name]
    patterns = [_title_filter_pattern(s) for s in synonyms]
    clause = "(" + " OR ".join("t.title REGEXP ?" for _ in patterns) + ")"
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

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", nargs="?", default="ttn.sqlite",
                    help="Path to the SQLite DB (default: ttn.sqlite)")
    ap.add_argument("--top", type=int, default=30,
                    help="How many rows to show on stdout (default: 30)")
    ap.add_argument("--by",
                    choices=["piece", "work", "composer", "ensemble", "conductor"],
                    default="work",
                    help="Rollup level (default: work)")
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
    ap.add_argument("--summary", action="store_true",
                    help="Print corpus-wide summary statistics (episodes, "
                         "tracks, distinct composers/works, repertoire "
                         "distribution) and exit. Respects date filters "
                         "(--after/--before/--year/--christmas); ignores "
                         "--composer/--title/--form/--by/--top/--csv.")
    args = ap.parse_args()

    if not any(a.startswith("-") for a in sys.argv[1:]):
        args.summary = True

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

    if args.summary:
        sql = ("SELECT t.composer, t.composer_line, t.title, t.episode_pid "
               "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")
        if date_clauses:
            # date_clauses target the episodes table column directly;
            # qualify for the join.
            qualified = [c.replace("broadcast_date", "e.broadcast_date")
                         for c in date_clauses]
            sql += " WHERE " + " AND ".join(qualified)
        # Strip arranger-tail co-credits before keying, exactly as the
        # --by composer ranking does, so an "X, Y (Arranger)" track is
        # attributed to its principal composer X rather than spawning a
        # phantom "X, Y" composer (which would also inflate the distinct-
        # composer count).
        rows = [(strip_arranger_tail(composer, composer_line), title, episode_pid)
                for composer, composer_line, title, episode_pid
                in cur.execute(sql, date_params).fetchall()]
        stats, _ = summary_for_rows(rows)
        print(render_summary(stats))
        return

    # Main aggregation query -- joins to episodes so we can pull the date.
    track_clauses = ["t.title IS NOT NULL", "t.title != ''"]
    track_params = []
    if args.composer:
        track_clauses.append("LOWER(t.composer) LIKE ?")
        track_params.append(f"%{args.composer.lower()}%")
    if args.title:
        track_clauses.append("t.title REGEXP ?")
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
    if args.title:
        label += f" (title~='{args.title}')"
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
