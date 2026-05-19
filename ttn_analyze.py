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

    # --- --once re-airings, audit batch 2 (Vivaldi, Haydn, Dvořák,
    #     Tchaikovsky, Chopin, Mendelssohn, Grieg, Telemann).

    # --- Vivaldi: 2 re-aired works ---
    ('Allegro non molto from Oboe Concerto in A minor, RV.461',
     'Allegro non molto from Oboe Concerto in A minor'),
    ('Violin Concerto in C major, RV.178',
     'Violin Concerto in C major, Op 8 No 12 (RV 178)'),

    # --- Haydn: 10 re-aired works ---
    ("String Quartet in G minor, Op 74, No 3 'Rider' - 2nd movt",
     "2nd movement (Largo assai) - from String Quartet in G minor, Op 74 No 3 'Rider'"),
    ('Ave Regina for double choir, MH 140',
     'Ave Regina for double choir'),
    ('Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and continuo',
     'Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and bc'),
    ('Divertimento in C major, London Trio no 1, Hob.4:1',
     "Divertimento in C major, Hob.IV No 1 'London Trio'"),
    ('Sonata in B flat major, H.16.41',
     'Keyboard Sonata in B flat major, H.16.41'),
    ('Overture to Lo Speziale (The Apothecary)',
     'Overture to Lo Speziale'),
    ('Sonata for piano (H.16.29) in F major',
     'Piano Sonata for piano in F major, Hob 16.29'),
    ('Symphony No.4 in D major',
     'Symphony No 4 (H.1.4) in D major (Presto'),
    ('Symphony No.88 in G (H.1.88)',
     'Symphony No.88 (H.1.88)'),
    ("Variations on the hymn 'Gott erhalte'",
     "Variations on the hymn 'Gott erhalte Franz den Kaiser'"),

    # --- Dvořák: 4 re-aired works ---
    ('Slavonic dance No 8 in G minor Op 46 No 8 orch. composer (orig. for pf duet)',
     'Slavonic Dance in G minor, Op 46 No 8, orch composer (orig for pf duet)'),
    ('Symphony no 8 in G major, Op 88, B.163',
     'Symphony No. 8 in G major, Op. 88, B. 163'),
    ('Three Slavonic Dances: Slavonic Dance No.8 in G minor, Op.46 no.8; Slavonic Dance No.10 in E minor, Op.72 no.2; Slavonic Dance No.15 in C major, Op.72 no.7',
     'Three Slavonic Dances (No 8 in G minor, Op 46 No 8; No 10 in E minor, Op 72 No 2; No 15 in C major, Op 72 No 7)'),
    ('Two Waltzes, Op 54 [1.Moderato; 2.Allegro vivace]',
     'Two Waltzes, Op 54'),

    # --- Tchaikovsky: 10 re-aired works ---
    ("Cherubim's Song, No. 3 from 'Nine Sacred Pieces' (encore)",
     "1. Cherubim's Song, No. 3 from 'Nine Sacred Pieces'"),
    ('Andante Cantabile from the string quartet (Op.11)',
     'Andante Cantabile (String Quartet, Op11), arranged by the composer'),
    ("Cradle Song (Andantino) from Six Romances, Op.16'1",
     'Cradle Song (Andantino) from Six Romances, Op.16'),
    ("Introduction and Waltz from 'Eugene Onegin'",
     'Introduction and Waltz (Eugene Onegin)'),
    ("Jurists' March in D major",
     "Jurists' March in D"),
    ("Slavonic March in B flat minor 'Marche slave' (Op.31)",
     "March in B flat minor, Op.31, 'Marche slave'"),
    ('Nocturne in C sharp minor, Op 19 no 4 (encore)',
     'Nocturne in C sharp minor, Op 19 no 4'),
    ('Souvenir de Florence, Op.70 (Allegro vivace)',
     "Souvenir de Florence (4th mvt, 'Allegro vivace') Op 70"),
    ('Symphony No. 6 in B minor Op.74 (Pathétique) - 3rd mov arr. Carpenter for organ',
     "Symphony No 6 in B minor, Op 74, 'Pathétique' (3rd movt)"),
    ("Symphony No.1 in G minor (Op.13) 'Reves d'hiver'",
     'Symphony No.1 in G minor'),

    # --- Chopin: 13 re-aired works ---
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
    ('Prelude No 1 in C, Op 28 No 1',
     'Prelude No 1 in C major, Op 28 No 1'),
    ('Three Polonaises: Polonaise in A major, Op.40 No.1, Polonaise in E flat minor, Op.26 No.2; Polonaise in F sharp minor, Op.44',
     "Three Polonaises: Polonaise in A major, Op 40'1; Polonaise in E flat minor, Op 26'2; Polonaise in F sharp minor, Op 44"),
    ('Waltz No. 42 in A flat, оp. 42',           # leading char is a Cyrillic 'о'
     'Waltz No 42 in A flat, Op 42'),
    ("Waltz No. 7 in C sharp minor, op.64'2",
     'Waltz No. 7 in C sharp minor, op. 64/2'),

    # --- Mendelssohn: 8 re-aired works ---
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

    # --- Grieg: 8 re-aired works ---
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
    ('Morning Mood, from Peer Gynt, Suite No.1, Op.46',
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
    ('Sonata à 4 in F, for alto and tenor chalumeaux, two violins and basso continuo',
     'Sonata à 4 in F major, for alto and tenor chalumeaux, two violins and basso continuo'),

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
    ('Valso triste op 44, No 1',
     'Valse triste Op 44 no 1'),

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
    ('Dance of the Knights from the ballet suite Romeo and Juliet arr. Borisovsky for viola and piano',
     'Dance of the Knights from the ballet suite Romeo and Juliet arr. Borisovsky'),
    ('Dance of the Knights from the ballet suite Romeo and Juliet arr. for viola and piano',
     'Dance of the Knights from the ballet suite Romeo and Juliet arr. Borisovsky'),
    ('God of evil and pagan dance (Allegro sostenuto) - no.2 from Scythian suite from "Ala i Lolly", Op.20',
     'God of Evil and Pagan Dance (Allegro sostenuto) - No.2 from Scythian Suite'),
    ('Moderato, from Sonata for Solo Violin in D, op. 115',
     "Moderato, from 'Sonata Solo Violin in D, op. 115'"),
    ('Sonata no.5 in C major, Op 135',
     'Piano Sonata no.5 in C major, Op.135 (version revised)'),
    ('Sonata no.5 in C major, Op.135 (vers. revised)',
     'Piano Sonata no.5 in C major, Op.135 (version revised)'),
    ('Prelude Op.12 No.7',
     'Prelude - No.7 from Pieces for piano (Op.12)'),

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
    ('Klid (Silent Woods) for cello and orchestra (B.182)',
     "Klid ('Silent Woods') for cello and orchestra, B.182, arr. from 'From the Bohemian Forest'"),
    ('Legend in C major (Molto maestoso), Op.59 No.4, orch. by the composer',
     'Legend in C major (Molto maestoso) Op 59 No 4 orchestrated by the composer'),
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
    ('Cello Sonata in A, FWV 8',
     'Cello Sonata in A major, FWV 8'),
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
    ('Canzonetta for violin and piano in D, op. 8',
     'Canzonetta for violin and piano in D major, Op.8'),
    ('Four piano pieces: Barcarole; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9',
     'Four piano pieces: Barcarole, Op.4; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9'),
    ('Romanze for violin and piano in F, op. 22',
     'Romanze for violin and piano in F major, Op.22'),
    ('Trio for violin, cello and piano in C, op. 29',
     'Trio for violin, cello and piano in C major, Op.29'),

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
    ('Six Pieces for four hands, Op 11',
     '6 Pieces for four hands, Op.11'),
    ('Cello Sonata in G minor Op 19 (excerpt Andante)',
     'Andante from Cello Sonata in G minor, Op 19'),
    ('Bogoroditse Devo, from Vespers (All-Night Vigil) (Ave Maria)',
     'Bogoroditse Devo, from Vespers (All-Night Vigil)'),

    # --- Ravel: ttn_audit --once finds ---
    ('Blues, from Violin Sonata no 2 in G major',
     'Blues, from Violin Sonata no 2 in G'),
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
    ('Concert Prelude to Tristan und Isolde arr. Kocsis for piano',
     'Concert Prelude to Tristan und Isolde'),
    ('Die Meistersinger von Nürnberg (Prelude)',
     'Die Meistersinger von Nürnberg'),
    ("Overture to 'Der fliegende Holländer' - The Flying Dutchman",
     "Overture to 'Der fliegende Holländer'"),

    # --- Szymanowski: ttn_audit --once finds ---
    ('Excerpts from 20 Mazurkas for piano (Op.50): no.1, no.2 & no.13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('Excerpts from 20 Mazurkas for piano (Op.50): nos.1, 2 & 13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('From 20 Mazurkas for piano Op 50: No 1 in E major; No 2; No 13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('From 20 Mazurkas for piano, Op.50: No.1; No.2; No.13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),
    ('Concert Overture in E, Op 12',
     'Concert Overture in E major, Op 12'),
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
    ('Cello Concerto no 1 in E flat major',
     'Cello Concerto No 1 in E flat'),
    ('Concerto no. 2 in G major Op.126 for cello and orchestra',
     'Cello Concerto No. 2 in G major Op.126'),
    # --- Eugene Ysaye: ttn_audit --once finds ---
    ('Danse rustique, from Sonata No.5 in G major',
     "Danse rustique, from 'Sonata No. 5 in G'"),
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
    ('2 Motets: Peccantem me quotidiae; O vos omnes',
     '2 Motets arr. for brass quintet: Peccantem me quotidiae; O vos omnes'),
    ('2 Motets: Pater noster, qui es in coelis (OM 1/69), Ave verum corpus (OM 3/25)- from Opus Musicum',
     '2 Motets: Pater noster, qui es in coelis (OM 1/69), Ave verum corpus (OM 3/25) - from Opus Musicum'),
    ('Najpiękniejsze pionski (The most beautiful songs) Op.4 - words by Adam Asnyk; Pod jaworem (Under the sycamore) - folk song from Włoszczowa region',
     '2 Songs: Najpiekniejsze pionski (The most beautiful songs, words by Adam Asnyk) (Op.4); Pod jaworem (Under the sycamore, folk song from Wloszczowa region)'),
    ('3 Bulgarian Dances arr. Wingfield',
     '3 Bulgarian Dances'),
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
    ('Adagio, from String Quintet in F major',
     'Adagio, from String Quintet in F'),
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
    ("Concert transcription of 'Largo al factotum' from Rossini's 'Il barbiere di Siviglia'",
     "Concert transcription for cello and piano of Figaro's aria 'Largo al factotum' from Rossini's 'Il barbiere di Siviglia'"),
    ('Violin Concerto, Op 18',
     'Concerto for Violin and Orchestra, Op 18'),
    ('Concerto for flute, (2) oboes, strings & bc in G minor (S.Uu (i hs 58:5))',
     'Concerto for flute, (2) oboes, strings & basso continuo in G minor'),
    ('Contre qui Rose - 2nd movement from Les Chansons des Roses',
     'Contre qui Rose (1993) - 2nd movement from Les Chanson des Roses'),
    ('Credo From Missa Si Deus pro nobis à16',
     'Credo From Missa Si Deus pro nobis à 16'),
    ('Csardas (originally for violin and piano)',
     'Csardas (orig. for violin and piano)'),
    ('Danube Afterpoint, octet for 2 pianos, string quartet and 2 brass instruments',
     'Danube Afterpoint (2015), octet for two pianos, string quartet and two brass instruments'),
    ('De profundis (Psalm 129) in C minor, ZWV 96',
     'De profundis (Psalm 129) in C minor'),
    ('Overture from Die Leichte Kavallerie',
     'Die Leichte Kavallerie (Light cavalry)'),
    ('Overture from Die Leichte Kavallerie (Light cavalry)',
     'Die Leichte Kavallerie (Light cavalry)'),
    ('Divertimento (Feldpartita) (H.2.46) in B flat major arr. for wind quintet',
     "Divertimento 'Feldpartita' in B flat major, H.2.46"),
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
     'Elegy in D flat major, Op 23'),
    ('En ny himmel och en ny jord for a capella chorus',
     'En ny himmel och en ny jord (A New Heaven and a New Earth) for a capella chorus'),
    ('En ny himmel och en ny jord for a cappella chorus',
     'En ny himmel och en ny jord (A New Heaven and a New Earth) for a capella chorus'),
    ('Eroticon Op 10): No 2 in D flat; No 3 in A flat',
     'Eroticon (Op 10): No 2 in D flat; No 3 in A flat for piano'),
    ('Eroticon, Op 10: no 2 in D flat major; no 3 in A flat major for piano',
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
    ('Kaiser-Walzer, Op 437, arr Schoenberg for chamber ensemble',
     'Kaiser-Walzer (Op.437) (1888), arranged by Schoenberg (1925) for chamber ensemble'),
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
    ('Missa Septimus for 5-part choir, soloists, strings and continuo',
     'Missa Septimus for 5 part choir, soloists, strings and continuo'),
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
    ('Much ado about nothing - 4 pieces, arr. for violin and piano',
     'Much ado about nothing - 4 pieces, arr. for viola and piano'),
    ('My River Runs To Thee',
     'My River Runs To'),
    ('Mzeo tibatvisa (June Sun)',
     'Mzeo Tibatvis (June Sun)'),
    ('Nocturne (Andante) - 3rd movement from Quartet for strings no.2 in D major arr. for orchestra',
     'Nocturne (Andante) - 3rd movement from Quartet for strings no.2 in D major arr. Sargent for orchestra'),
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
    ('Overture à 3 in C, for alto, tenor and bass chalumeaux',
     'Overture à 3 in C major, for alto, tenor and bass chalumeaux'),
    ('Partita for Violins in Sixth-Tone System (1936)',
     'Partita for Violin in a Sixth-tone System (1936)'),
    ('Pavane in F minor (Op.50) arr. for harmonica and orchestra',
     'Pavane (Andante molto moderato) in F minor (Op.50) arr. for harmonica and orchestra'),
    ('Pavane, Op.50, arr. for harmonica and orchestra',
     'Pavane (Andante molto moderato) in F minor (Op.50) arr. for harmonica and orchestra'),
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
    ('Sonata da Camera in C, CSWV Anh:4',
     'Sonata da Camera in C major, CSWV Anh:4'),
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
    ("String Quintet No.60 in C major, Op.30 No.6 (G.324), 'La Musica notturna delle strade di Madrid' arr. for string orchestra",
     "String Quintet No.60 (G.324) (Op.30 No.6) in C major 'La Musica notturna delle strade di Madrid'"),
    ('String Trio in D, Op 3 no 6',
     'String Trio in D major, Op 3 no 6'),
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
    ('Symphony in C major',
     'Symphony in C'),
    ('Tassilone (comp. Dusseldorf 1709)- excerpts',
     'Tassilone (comp. Dusseldorf 1709) - excerpts'),
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
