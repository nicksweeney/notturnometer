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
    return name


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
    # Normalize opus and number markers: "Op." / "Op " / "op." → "op "
    s = re.sub(r"\b(op|no|nos)\.?\s*", r"\1 ", s)
    # Collapse whitespace and drop minor punctuation noise
    s = re.sub(r"[.,;:]", "", s)
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
]


def _build_ensemble_alias_table():
    table = {}
    for variant, preferred in _ENSEMBLE_ALIAS_PAIRS:
        table[canonical_key(variant)] = canonical_key(preferred)
    return table


ENSEMBLE_ALIASES = _build_ensemble_alias_table()


def resolve_ensemble_alias(canon_key: str) -> str:
    return ENSEMBLE_ALIASES.get(canon_key, canon_key)


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

    sql = ("SELECT t.title, t.composer, t.performers, "
           "       substr(e.broadcast_date, 1, 10) "
           "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid "
           "WHERE " + " AND ".join(track_clauses))

    # Group by canonical key but track display strings via a Counter so we
    # can show the most common original spelling for each group.
    groups = defaultdict(lambda: {"n": 0, "display": Counter(), "dates": []})
    aliases_applied = 0

    for title, composer, performers, bdate in cur.execute(sql, track_params):
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
                key = (resolved_c, canonical_key(display[1]))
            entries.append((key, display))

        for key, display in entries:
            if not key or (isinstance(key, tuple) and not any(key)):
                continue
            groups[key]["n"] += 1
            groups[key]["display"][display] += 1
            if bdate:
                groups[key]["dates"].append(bdate)

    # Rank by count; pick the most common original spelling for each group
    ranked = sorted(groups.values(), key=lambda g: -g["n"])

    label = f"top {args.top} by {args.by}"
    if args.composer:
        label += f" (composer~='{args.composer}')"
    print(label + ":")
    if args.verbose and not args.raw and aliases_applied:
        alias_kind = "ensemble" if args.by == "ensemble" else "composer"
        print(f"  ({aliases_applied:,} {alias_kind} aliases resolved via lookup table)")
    print()
    if ranked:
        width = len(str(ranked[0]["n"]))
    else:
        width = 1
    for i, g in enumerate(ranked[: args.top], 1):
        display = g["display"].most_common(1)[0][0]
        text = " — ".join(p for p in display if p) if isinstance(display, tuple) else display
        # If the group has variants, mark it (verbose only)
        n_variants = len(g["display"])
        marker = (f" ({n_variants} spelling variants)"
                  if args.verbose and n_variants > 1 else "")
        print(f"{i:>3}.  {g['n']:>{width}}×   {text}{marker}")
        if args.dates:
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
            w.writerow(header)
            for g in ranked:
                display = g["display"].most_common(1)[0][0]
                if single_value_by:
                    row = [g["n"], display, len(g["display"])]
                else:
                    row = [g["n"], *display, len(g["display"])]
                if args.dates:
                    row.append("|".join(sorted(g["dates"])))
                w.writerow(row)
        print(f"\nFull ranking ({len(ranked)} rows) written to {args.csv}",
              file=sys.stderr)

    conn.close()


if __name__ == "__main__":
    main()
