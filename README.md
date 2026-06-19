# notturnometer: a scraper and analysis suite for BBC Radio 3's "Through the Night" (aka Notturno)

## Introduction

"Through the Night" is a 6-hour overnight broadcast of classical music curated by
BBC Radio 3, first aired in May 1996. From 1998 the BBC began sharing it with
neighbouring European broadcasters under the title "Notturno".

The programme is unusual in that (with rare exceptions) it does not draw on
commercial recordings. It is built mostly from live concert recordings supplied
by members and associates of the European Broadcasting Union (EBU) and
distributed with cleared rights to EBU partners. That makes it a distinctive
corpus of classical music with its own metadata and a long history.

This package fetches each broadcast's playlist from the BBC's public programme
JSON into a local SQLite database, resolves differences in the many ways the BBC spells
one composer or work, and ranks what gets played. It was built to answer the
question: *how often is this work featured?* It **does not** contain the
database or any copyrighted material, and does not link to the broadcasts
themselves.

Everything runs through **three commands**:

- **`ttn_data.py`** — build and maintain the local database (the only tool that
  touches the network).
- **`ttn_analyze.py`** — query and rank it.
- **`ttn_curate.py`** — administrative tools that surface spelling/title variants
  for human review.

## Requirements

- **Python 3.12 or newer** (declared in `pyproject.toml`, pinned in
  `.python-version`).
- **[uv](https://docs.astral.sh/uv/)** for environment and dependency
  management. notturnometer is uv-managed throughout: the examples all invoke
  `uv run`, which provisions the environment on first call. (The only hard
  runtime dependency is `requests`; everything else needed by the analysis tools
  is in the standard library.)
- **SQLite** — bundled with Python, nothing to install separately.
- A network connection for `ttn_data.py scrape` / `segments`, which fetch from
  the BBC's public programme JSON. Everything else runs offline against your
  local database.

## Installation

There is nothing to `pip install` and no PyPI package — you clone the repo and
run the tools with `uv`, which provisions an isolated environment (and the right
Python) automatically.

1. **Install uv** if you don't have it (see the
   [installation guide](https://docs.astral.sh/uv/getting-started/installation/)):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone and enter the repo:**

   ```bash
   git clone <repository-url>
   cd notturnometer
   ```

3. **Provision the environment** (optional — any `uv run` does this on first
   call):

   ```bash
   uv sync
   ```

4. **Verify it runs** (there is no database yet):

   ```bash
   uv run ttn_analyze.py --help
   ```

5. **Run the tests** (pytest is fetched on demand):

   ```bash
   uv run --with pytest pytest
   ```

## Usage

### Building the database — `ttn_data.py`

`ttn_data.py` handles ingestion and caching. It discovers the most
recent broadcast, walks each programme's `peers.previous` link backwards in
time, and parses each episode's tracklist from the BBC's `long_synopsis` text.
Episodes from 2012 onward also carry structured per-recording metadata
(MusicBrainz composer IDs, recording IDs, and the EBU source broadcaster), which
`ttn_data.py` fetches separately from `/segments.json`.

Once the database is populated, the bare command brings everything up to date
in one step — fetch new broadcasts, top up the segment metadata, and rebuild the 
analysis caches:

```bash
uv run ttn_data.py update                 # the data-refresh recipe
uv run ttn_data.py update --days 3650      # reach further back, then refresh
```

`update` is **idempotent**: episodes already stored are skipped, so re-running
is safe and a wider window only fetches what's missing.

Individual stages are available when you need them:

```bash
uv run ttn_data.py scrape --days 3650      # extend the scrape (resumable)
uv run ttn_data.py segments                # backfill /segments.json metadata
uv run ttn_data.py warm                    # rebuild the analysis caches
uv run ttn_data.py reparse --dry-run       # check tracks still match the parser
```

**Please scrape considerately.** The default 0.8 s delay between requests is
deliberate and cannot be lowered below 0.5 s. The BBC has not historically
rate-limited this kind of metadata fetching, but there is no published policy.

### Querying — `ttn_analyze.py`

Because the BBC writes the same composer and work many different ways,
`ttn_analyze.py` folds those variants together *at query time* — diacritics,
word order, opus and catalogue formatting, and hand-curated aliases — so
*Antonín Dvořák* and *Antonin Dvorak*, or every rephrasing of one catalogued
work, count as a single entry. From 2012 on it goes further and groups by the
actual **recording**, so re-airings and the BBC's re-wordings of one performance
collapse together. The database is never modified; canonicalization is
re-derived on every run, so it stays reversible and `--raw` always shows the
unfolded data.

Run with no flags, it prints a corpus summary:

```bash
uv run ttn_analyze.py
```

Add `--by` to get a ranking. The default rollup is by work:

```
$ uv run ttn_analyze.py ttn.sqlite --by work --top 4
  1.  138×   Claude Debussy — Prélude à l'après-midi d'un faune
  2.   93×   Robert Schumann — Phantasiestücke Op 73 for clarinet & piano
  3.   93×   Edward Elgar — Serenade for Strings in E minor, Op 20
  4.   90×   Ralph Vaughan Williams — Fantasia on a theme by Thomas Tallis …
```

**Rollup level (`--by`)** chooses what each ranked row represents:

| Value | Each row is… |
|---|---|
| `work` *(default)* | a work, with movement and arrangement differences folded in. |
| `piece` | an exact title — movements and arrangements kept separate. |
| `composer` | a composer. |
| `ensemble` | a performing ensemble (orchestra, choir, quartet, …). |
| `conductor` | a conductor or director. |
| `year` | a chronological airings-per-year breakdown (a temporal drill-in). |
| `recording` / `performer` / `orchestra` / `singer` / `choir` | the recording metadata, 2012+ (see *segment data* below). |
| `broadcaster` / `country` | the EBU source broadcaster (or its country), 2012+. |

**Filters** narrow the set before ranking and combine freely:

- `--composer S` — composer matches `S` (resolves to identity, so every spelling
  is pulled in).
- `--title S` — title contains `S` as a whole word (`--title concerto` does
  *not* match *concertino*).
- `--form NAME` — title names a compositional form, folding cross-language
  synonyms (`--form symphony` also matches *Symphonie*; `--form nocturne` folds
  *Notturno*). See `--help` for the vocabulary.
- `--ensemble` / `--conductor` — restrict to one ensemble or conductor.
- `--after` / `--before` / `--year` / `--christmas` — date filters
  (`--christmas` restricts to Dec 25 broadcasts).
- `--min-airings` / `--max-airings` — keep rows aired within a count band
  (`--once` = exactly one airing).

`--composer`, `--title` and `--form` are diacritic-insensitive: `--composer
Dvorak` returns *Dvořák* and every other variant in the corpus.

**Work profile (`--work`).** Give it one work and it prints a fixed multi-facet
card — by-recording, top performers/ensembles/conductors, by-year, and source
broadcasters:

```bash
uv run ttn_analyze.py ttn.sqlite --work "Jupiter"
```

**Other options:** `--top N` (rows to print), `--sort {airings,works}`,
`--dates` (list each entry's broadcast dates), `--raw` (no canonicalization),
`--csv PATH`, `-v/--verbose` (per-entry spelling-variant counts — the audit
signal). A canonicalized entry that still shows many variants under `--verbose`
is a hint that the alias tables want updating; that's the job of the curation
tools.

#### Segment data (2012 onward)

Episodes from 2012 carry per-recording metadata the older text-only listings
lack. Pass `--source segments` to rank from it directly, or use the
segment-native axes above:

```bash
uv run ttn_analyze.py ttn.sqlite --by recording --top 30          # most-repeated performances
uv run ttn_analyze.py ttn.sqlite --by performer --top 30          # soloists
uv run ttn_analyze.py ttn.sqlite --by broadcaster --top 20        # EBU source ranking
uv run ttn_analyze.py ttn.sqlite --performer Hamelin --by composer --source segments
```

### Curation — `ttn_curate.py`

The BBC's spellings drift constantly, and the analyzer folds them with
hand-curated alias tables. `ttn_curate.py` is the back-of-house door to the
tools that *surface* variants still needing a human decision. Most of what they
flag is meant to stay split, so their output is a worklist for triage, not an
auto-merge. They all run offline.

```bash
uv run ttn_curate.py                              # list the subcommands
uv run ttn_curate.py duplicates ttn.sqlite --top 30          # same-composer works keyed apart
uv run ttn_curate.py composer-duplicates ttn.sqlite --top 20 # one composer split across spellings
uv run ttn_curate.py audit ttn.sqlite --composer Brahms      # one-off re-airing merge candidates
uv run ttn_curate.py mbid-audit ttn.sqlite --tier medium     # composer issues from MusicBrainz IDs
```

Decisions that survive triage live in **`ttn_aliases.py`** — not a script you
run, but a pure-data file of `(variant, preferred form)` tuples imported by the
analyzer. The derived caches fingerprint its contents, so editing a table there
invalidates them automatically. After any such edit, run `uv run ttn_data.py
warm` to rebuild.

## Examples

Output depends on the extent of your local database; date-specific queries only
work for periods you've fetched.

```bash
# Whole-database summary (the default DB name ttn.sqlite can be omitted)
uv run ttn_analyze.py

# Top 20 works broadcast in 2025
uv run ttn_analyze.py ttn.sqlite --by work --year 2025 --top 20

# Every broadcast date of Mozart's "Jupiter" Symphony
uv run ttn_analyze.py ttn.sqlite --by work --composer Mozart --title jupiter --dates

# Composers ranked by breadth of repertoire (distinct works)
uv run ttn_analyze.py ttn.sqlite --by composer --sort works

# Top 5 nocturnes broadcast 2022–2024 (folds Notturno/Nocturne)
uv run ttn_analyze.py ttn.sqlite --form nocturne --top 5 --after 2022-01-01 --before 2024-12-31

# Most-aired composers on December 25
uv run ttn_analyze.py ttn.sqlite --by composer --christmas

# Is a composer played more now than a decade ago?
uv run ttn_analyze.py ttn.sqlite --composer Sibelius --by year

# Export the full composer ranking to CSV (with an n_variants audit column)
uv run ttn_analyze.py ttn.sqlite --by composer --top 0 --csv composers.csv
```

## Work in progress

- timeline visualizations of when works are broadcast
- stable, persisted per-work identifiers (a re-derivable slug already backs
  `--work`)
- per-work composer attribution overrides for source mis-attributions the
  whole-composer alias table can't reach (e.g. Nicola Matteis Sr./Jr., keyed by
  recording and performer credits rather than by track)
- extending the parser before 2010-01-17, when the current synopsis format
  begins

## DISCLAIMER

This project is an independent, non-commercial hobby tool. It is **not
affiliated with, authorised by, or endorsed by the BBC** in any way. "BBC",
"Radio 3", and "Through the Night" are the property of the British Broadcasting
Corporation.

## What this tool does

It fetches publicly available programme metadata (broadcast dates, track
listings, composer/work/performer text) from the BBC's open
`/programmes/{pid}.json` endpoints and stores it in a local database for
personal analysis. The analysis it produces — rankings and aggregate
statistics — is derived from that metadata.

## Data

- **No BBC data is redistributed in this repository.** The scraped database
  (`ttn.sqlite`) and any exported CSVs are git-ignored and never committed.
  Cloning this repo gives you the *code* to build a dataset, not the data
  itself.
- Copyright in the underlying programme information, and in the broadcasts
  themselves, remains with the BBC and the respective rights holders.

## Responsible use

- **You are responsible for your own use** of the scraper, including compliance
  with the BBC's terms of use and any applicable law in your jurisdiction.
- Again: please scrape considerately. The scraper sleeps between requests by
  default (0.8 s) and skips already-cached episodes; **do not remove or shorten
  the rate limit** to hammer the BBC's endpoints.
- This tool is intended for personal research and curiosity, not for bulk
  redistribution of BBC content.

## No warranty

The software is provided "as is", without warranty of any kind. See the LICENSE
file for the full terms.
