# notturnometer: a scraper and analysis suite for BBC Radio 3's "Through The Night" (aka Notturno)

## Introduction

"Through The Night" is a 6-hour overnight broadcast of classical music curated by BBC Radio 3, first broadcast in May 1996. In 1998 the BBC began sharing the programme with European neighbour broadcasters under the title "Notturno".

"Through The Night" in its current form is unusual in that (with a few rare exceptions) it does not draw from commercial recordings: instead it primarily uses live concert recordings from European Broadcasting Union (EBU) members and associates and is distributed with cleared rights to EBU partner broadcasters. This makes it a unique and idiosyncratic corpus of classical music with its own metadata and extensive history.

This package contains two main CLI tools: **ttn_scrape.py** to fetch playlists from the BBC website into a SQLite database, and **ttn_analyze.py** to query that database by composer, work, and other criteria. It also contains a number of subsidiary scripts to identify known variants in titles and spellings. It **does not** contain the database or any copyrighted material nor does it link to the broadcasts themselves. It was built to answer the question: "how often is this work featured in the broadcast?"

## Requirements

- **Python 3.12 or newer** (declared in `pyproject.toml`; pinned in `.python-version`).
- **[uv](https://docs.astral.sh/uv/)** for environment and dependency management.
    notturnometer is uv-managed throughout — the usage examples all invoke
    `uv run`, which provisions the environment on first call. (If you'd rather not
    use uv, the only hard runtime dependency is `requests`; everything else the
    analysis tools need is in the Python standard library.)
- **SQLite** — bundled with Python's standard library, so nothing to install
    separately.
- A network connection for the scraper (`ttn_scrape.py`), which fetches from the
    BBC's public programme JSON endpoints. The analysis tools run entirely offline
    against your local database.


## Installation

notturnometer is a set of scripts run in place — there is nothing to
`pip install` and no PyPI package. You clone the repository and run the tools
with `uv`, which provisions an isolated environment (and the right Python
version) automatically.

1. **Install uv** if you don't already have it — see the
   [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).
   On macOS/Linux:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone the repository:**

   ```bash
   git clone <repository-url>
   cd notturnometer
   ```

3. **Provision the environment:**

   ```bash
   uv sync
   ```

   This creates a local `.venv` from the locked dependencies (`uv.lock`) and
   fetches Python 3.12 if it isn't already present (per `.python-version`).
   This step is optional — any `uv run` command provisions the environment on
   first call.

4. **Verify it runs** (note that there is no SQLite database yet):

   ```bash
   uv run ttn_analyze.py --help
   ```

5. **Run the test suite** (pytest is fetched on demand, not a declared
   dependency):

   ```bash
   uv run --with pytest pytest
   ```

## Usage

The two main tools are `ttn_scrape.py` (build the local database) and
`ttn_analyze.py` (query it). Both are run with `uv run`.

### Scraper

`ttn_scrape.py` builds and extends the local SQLite database. It discovers
episodes starting by default from the most recent episode or from a specific
seed PID by following each programme's `peers.previous` link backwards in time
and parses each episode's tracklist from the BBC's `long_synopsis` text.

Build a database covering the last year (writes to `ttn.sqlite` by default):

```bash
uv run ttn_scrape.py
```

Walk further back — for example, ten years:

```bash
uv run ttn_scrape.py --days 3650
```

The scraper is **idempotent**: episodes already in the database are skipped, so
re-running is safe and widening the window only fetches what's missing. To go
deeper later, re-run with a larger `--days`.

**Options:**

| Flag | Default | Purpose |
|---|---|---|
| `--db PATH` | `ttn.sqlite` | SQLite output path. |
| `--days N` | `365` | How many days back to walk from the seed. |
| `--seed PID` | the most recent broadcast | Starting episode PID for the backward walk. |
| `--pids A,B,…` | — | Fetch these specific episodes instead of walking (spot-checks). |
| `--max-episodes N` | — | Hard cap on episodes fetched (a safety net). |
| `--delay SECONDS` | `0.8` | Pause between requests. |

Fetch just a few specific episodes — useful for testing, without touching your
main database:

```bash
uv run ttn_scrape.py --pids m002vw4j,m002vvxt --db /tmp/test.sqlite
```

**Please scrape considerately.** The default 0.8-second delay between requests
is deliberate; don't lower it below ~0.5 s. The BBC has not historically
rate-limited this kind of metadata fetching, but there is no published policy.

**On the seed.** The walk starts from the most recently broadcast PID; you only
need --seed if you wish to start from a specific episode PID.

### Analysis

`ttn_analyze.py` queries the SQLite database. Because the BBC writes the same
composer and work many different ways, the task of the analyzer is to
fold those variants together at query time: diacritics, word order, opus and
catalogue formatting, and a table of hand-curated aliases. A ranking counts
*Antonín Dvořák* and *Antonin Dvorak*, or every rephrasing of one catalogued
work, as a single entry. The database is never modified to do this; the
canonicalization is re-derived on every run, so it stays reversible and you can
always see the raw data with `--raw`.

Run with no flags, it prints a corpus summary (totals and the most-aired
composers and works):

```bash
uv run ttn_analyze.py
```

Add `--by` to get a ranking instead. The default rollup is by work:

```
$ uv run ttn_analyze.py ttn.sqlite --by work --top 4
top 4 by work:

  1.  138×   Claude Debussy — Prélude à l'après-midi d'un faune
  2.   93×   Robert Schumann — Phantasiestucke Op 73 for clarinet & piano
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
| `conductor` | a conductor or director (tracks with none don't contribute). |

**Filters** narrow the set before ranking and combine freely with each other
and with the date filters:

- `--composer S` — composer contains `S` (case-insensitive substring).
- `--title S` — title contains `S` as a whole word (so `--title concerto`
  does *not* match *concertino*).
- `--form NAME` — title names a compositional form, folding cross-language
  synonyms (`--form symphony` also matches *Symphonie*); sibling diminutives
  stay separate. See `--help` for the full form vocabulary.
- `--after` / `--before` / `--year` / `--christmas` — date-range filters
  (both bounds inclusive; `--christmas` restricts to Dec 25 broadcasts).
- `--min-airings` / `--max-airings` — keep only rows aired within a count
  band; `--once` is shorthand for exactly one airing.

**Options:**

| Flag | Default | Purpose |
|---|---|---|
| `db` | `ttn.sqlite` | Path to the database (positional). |
| `--top N` | `30` | How many rows to print. |
| `--sort {airings,works}` | `airings` | For `--by composer`: rank by total airings or by breadth (distinct works). |
| `--mode {rank,summary,audit}` | summary if no flags, else rank | Output mode; `audit` is the canonicalization-state dashboard. |
| `--dates` | — | Also list each entry's individual broadcast dates in YYYY-MM-DD format. |
| `--raw` | — | Disable canonicalization (group by exact strings). |
| `--csv PATH` | — | Write the full ranking to CSV. |
| `-v`, `--verbose` | — | Show per-entry spelling-variant counts (the audit signal). |

A canonicalized entry that still shows many spelling variants under `--verbose`
suggests that the alias tables should be updated. This is the job of the
Maintenance tools below.


### Maintenance

A set of subsidiary scripts hone the analysis. The BBC writes the
same composer and work many different ways — transliterations, reorderings,
added or dropped subtitles — and `ttn_analyze.py` collapses those variants at
query time using hand-curated alias tables. These tools surface variants
that still need a human decision, and warm the analyzer's cache. They all run
offline against the local database; none of them fetch from the BBC.

- **`ttn_audit.py`** — finds works aired only once that look like re-airings
  of the same recording under a reworded title (merge candidates for one
  composer, or `--all`). `--emit` appends paste-ready alias tuples and tests.
- **`ttn_audit_composer.py`** — a deep dive on a single composer's catalogue,
  grouping entries that share a catalogue/opus reference or strong title-word
  overlap so near-duplicates stand out.
- **`ttn_rebroadcast.py`** — ranks the recordings aired more than once, banded
  by piece length; `--multiplay` also surfaces multi-play merge candidates.
- **`ttn_duplicates.py`** — a post-alias straggler scan: same-composer work
  pairs that look like one work still keyed apart.
- **`ttn_warm.py`** — pre-computes the `--summary` cache for the whole corpus,
  each broadcast year, and the audit view, so later summaries are instant.

Most of what these tools flag is meant to stay split, so
their output is a worklist for human triage, not an auto-merge.

Decisions that survive triage live in **`ttn_aliases.py`** — not a script
you run, but a pure-data file imported by the analyzer holding hand-curated
alias tables: these contain composer, ensemble, and work-title pairs, each a
simple `(variant, preferred form)` tuple. When a maintenance tool's `--emit`
prints a paste-ready tuple, this is where it goes. The derived caches
fingerprint the file's contents, so editing a table here invalidates them
automatically — exactly as editing the analyzer itself would.


## Examples

NOTE: output will depend upon the extent of your local database. For obvious
reasons, date-specific queries will only work if you have fetched data for
those time periods.

Generate a summary of the whole database (the default DB name **ttn.sqlite**
can be omitted, otherwise you must specify the database name):

```
$ uv run ttn_analyze.py
```

Show the top 20 works broadcast in 2025:

```
$ uv run ttn_analyze.py ttn.sqlite --by work --year 2025 --top 20
```

Show all broadcast dates of Mozart's Symphony No. 41 K.551 ("Jupiter"):

```
$ uv run ttn_analyze.py ttn.sqlite --by work --composer Mozart --title jupiter --dates
```

Show the top ranked composers by repertoire (number of distinct works):

```
$ uv run ttn_analyze.py ttn.sqlite --by composer --sort works
```

Show the top 6 most-aired ensembles:

```
$ uv run ttn_analyze.py ttn.sqlite --by ensemble --top 6
```

Show the top 5 nocturnes broadcast between 2022 and 2024
(folds Notturno/Nocturne):

```
$ uv run ttn_analyze.py ttn.sqlite --form nocturne --top 5 --after 2022-01-01 --before 2024-12-31
```

Show the most aired composers on December 25 broadcasts:

```
$ uv run ttn_analyze.py ttn.sqlite --by composer --christmas
```

Show the number of variants plus the count of resolved aliases:

```
$ uv run ttn_analyze.py ttn.sqlite --by composer --top 30 --verbose
```

Show every variant used for a composer's name, e.g. Dvorak:

```
$ uv run ttn_analyze.py ttn.sqlite --by composer --composer dvorak --raw
```

Export to CSV a list of composers who have only been featured once (`--top 0`
writes the full ranking to CSV, including an `n_variants` column that flags
how many spellings folded into each entry):

```
$ uv run ttn_analyze.py ttn.sqlite --by composer --once --top 0 --csv composers.csv
```

Show the canonicalization dashboard:

```
$ uv run ttn_analyze.py ttn.sqlite --mode audit
```

## Work in progress

- timeline visualizations of when works are broadcast
- stable per-work identifiers / slugs
- per-work CLI analysis

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
  default (0.8 s) and skips already-cached episodes; **do not remove or
  shorten the rate limit** to hammer the BBC's endpoints.
- This tool is intended for personal research and curiosity, not for bulk
  redistribution of BBC content.

## No warranty

The software is provided "as is", without warranty of any kind. See the LICENSE
file for the full terms.
