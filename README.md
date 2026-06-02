## notturnometer: a scraper and analysis suite for BBC Radio 3's "Through The Night" (aka Euroclassic Notturno

## Introduction

"Through The Night" is a 6-hour overnight broadcast of classical music curated by BBC Radio 3 and on air since May 1996. It is unusual in that (with a few rare exceptions) it does not draw from commercial recordings: instead it primarily uses live concert recordings from European Broadcasting Union (EBU) members and associates and is distributed with cleared rights to EBU partner broadcasters. This makes it a unique and idiosyncratic corpus of music with its own metadata and extensive history.

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
episodes starting by default from the most recent episode or from a specific seed PID
by following each programme's `peers.previous` link backwards in time and
parses each episode's tracklist from the BBC's `long_synopsis` text.

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

`ttn_analyze.py` queries the SQLite database. 


### Maintenance

A handful of subsidiary scripts keep the analysis honest. The BBC writes the
same composer and work many different ways — transliterations, reorderings,
added or dropped subtitles — and `ttn_analyze.py` collapses those variants at
query time using hand-curated alias tables. These tools surface the variants
that still need a human decision, and warm the analyzer's cache. They all run
offline against your local database; none of them fetch from the BBC.

- **`ttn_audit.py`** — finds works aired only once that look like re-airings of
  the same recording under a reworded title (merge candidates for one composer,
  or `--all`). `--emit` appends paste-ready alias tuples and tests.
- **`ttn_audit_composer.py`** — a deep dive on a single composer's catalogue,
  grouping entries that share a catalogue/opus reference or strong title-word
  overlap so near-duplicates stand out.
- **`ttn_rebroadcast.py`** — ranks the recordings aired more than once, banded
  by piece length; `--multiplay` also surfaces multi-play merge candidates.
- **`ttn_duplicates.py`** — a post-alias straggler scan: same-composer work
  pairs that look like one work still keyed apart.
- **`ttn_warm.py`** — pre-computes the `--summary` cache for the whole corpus,
  each broadcast year, and the audit view, so later summaries are instant.

Most of what these flag is *correctly* distinct and meant to stay split, so
their output is a worklist for human triage, not an auto-merge.


## Examples

## Work in progress

- add timeline visualizations for when works are broadcast
- add per-work CLI analysis

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
  Cloning this repo gives you the *code* to build a dataset, not the data itself.
- Copyright in the underlying programme information, and in the broadcasts
  themselves, remains with the BBC and the respective rights holders.

## Responsible use

- **You are responsible for your own use** of the scraper, including compliance
  with the BBC's terms of use and any applicable law in your jurisdiction.
- Please scrape considerately. The scraper sleeps between requests by default
  (0.8 s) and skips already-cached episodes; **do not remove or shorten the
  rate limit** to hammer the BBC's endpoints.
- This tool is intended for personal research and curiosity, not for bulk
  redistribution of BBC content.

## No warranty

The software is provided "as is", without warranty of any kind. See the LICENSE
file for the full terms.
