## notturnometer: a scraper and analysis suite for BBC Radio 3's "Through The Night" (aka Euroclassic Notturno

## Introduction

"Through The Night" is a 6-hour overnight broadcast of classical music curated by BBC Radio 3 and on air since May 1996. It is unusual in that (with a few rare exceptions) it does not draw from commercial recordings: instead it primarily uses live concert recordings from European Broadcasting Union (EBU) members and associates and is distributed with cleared rights to EBU partner broadcasters. This makes it a unique and idiosyncratic corpus of music with its own metadata and extensive history. 

This package contains two main CLI tools: **ttn_scrape.py** to fetch playlists from the BBC website into a SQLite database, and **ttn_analyze.py** to query that database by composer, work, and other criteria. It also contains a number of subsidiary scripts to identify variants in titles and spellings. It **does not** contain the database or any copyrighted material nor does it link to the broadcasts themselves. It was built to answer the question: "how often does this work feature in the broadcast?"

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
 
  2. Clone the repository:
  
  git clone <repository-url>
  cd notturnometer

  3. Provision the environment:
 
  uv sync

  This creates a local .venv from the locked dependencies (uv.lock) and
  fetches Python 3.12 if it isn't already present (per .python-version).
  This step is optional — any uv run command provisions the environment on
  first call.

  4. Verify it runs (note that there is no sqlite database yet):
  
  uv run ttn_analyze.py --help

  5. To run the test suite (pytest is fetched on demand, not a declared
  dependency):
  
  uv run --with pytest pytest

## Usage



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
