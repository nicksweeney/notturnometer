#!/usr/bin/env python3
"""
Scraper for BBC Radio 3 'Through the Night' (series PID b006tmq9).

Walks the show's episodes as a linked list, starting from a known recent
episode (default: m002vw4j) and following peers.previous.pid backwards in
time until either:
  - the broadcast date falls outside the requested window, or
  - the chain runs out (no previous peer).

Tracklists are pulled from the episode's `long_synopsis` text, which the
BBC populates with a consistent 4-line-per-piece format
(time / composer + dates / title / performers). This is far more reliable
than the /segments.json endpoint, which is sparsely populated for this
show.

Idempotent: episodes already present in the DB are skipped.

Usage:
    uv run ttn_scrape.py                      # last 365 days, ttn.sqlite
    uv run ttn_scrape.py --days 730 --db ttn.sqlite
    uv run ttn_scrape.py --seed m002vw4j      # start from a different PID
    uv run ttn_scrape.py --pids m002vw4j,m002vvxt   # just these episodes
"""

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
import time

import requests

SERIES_PID = "b006tmq9"           # 'Through the Night' (current parent PID)
DEFAULT_SEED = "m002vw4j"          # any recent episode works as a starting point
BASE = "https://www.bbc.co.uk"
USER_AGENT = "ttn-scraper/2.0 (personal listening-pattern analysis)"
UPCOMING_URL = f"{BASE}/programmes/{SERIES_PID}/episodes/upcoming.json"

TIME_RE = re.compile(
    r"^\d{1,2}[.:]\d{2}\s*:?\s*(?:[AP]M)?(?:\s+[A-Z]{2,4})?\s*$", re.IGNORECASE
)


# ---------- HTTP -----------------------------------------------------------

def fetch_json(session, url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=30)
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(1 + attempt)
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return None
    return None


# ---------- Track parsing --------------------------------------------------

def classify_role(paren_info, is_first):
    s = paren_info.lower()
    if "arr" in s:
        return "arranger"
    if "lyric" in s or "libret" in s or "text" in s or "words" in s:
        return "lyricist"
    if "trad" in s:
        return "traditional"
    return "composer" if is_first else "contributor"


_NAME_PARTICLES = frozenset({
    "von", "van", "de", "der", "den", "del", "di", "da", "du", "le", "la",
    "st", "st.", "y", "of", "the", "le", "el", "ten", "ter", "auf",
})

# Title or honorific words. If the part after the comma *starts* with one,
# the comma introduces an epithet ("Joseph Bologne, Chevalier de Saint-Georges",
# "Moritz, Landgrave of Hessen-Kassel"), not a Surname-first inversion.
_TITLE_WORDS = (
    r"the|chevalier|landgrave|sir|sieur|don|dame|lord|lady|"
    r"dr|mr|mrs|père|pere|jr|sr|elder|younger|prince|princess|duke|duchess|"
    r"count|countess|baron|baroness|emperor|king|queen|saint"
)
_TITLE_RE = re.compile(rf"^(?:{_TITLE_WORDS})\b", re.IGNORECASE)

# Source-attribution markers found in the modern data at the start of a
# composer line: "Traditional, arr. X", "Anonymous, Harry Freedman", etc.
_MARKER_RE = re.compile(
    r"\b(trad|trad\.|anon|anon\.|anonymous|traditional)\b", re.IGNORECASE)

# Role abbreviations that signal "and then another contributor": never
# present in a true surname-first form.
_ROLE_ABBREV_RE = re.compile(r"\b(arr|trans|orch|ed|text)[.:]", re.IGNORECASE)


def _capitalized_name_tokens(s):
    """Count capitalized tokens that aren't lowercase particles or honorifics
    — i.e., the count of 'real name' words."""
    return sum(
        1 for tok in s.split()
        if tok and tok[0].isupper() and tok.lower() not in _NAME_PARTICLES
    )


def _looks_like_name(s):
    """Every token must be either capitalized or a known particle —
    'Vaughan Williams', 'von Beethoven', 'de la Mare' all pass, but
    'With darkness deep' or 'from Solomon' fail."""
    tokens = s.split()
    if not tokens:
        return False
    for tok in tokens:
        clean = tok.rstrip(",.;:").lstrip(",.;:")
        if not clean:
            continue
        if clean[0].isupper():
            continue
        if clean.lower() in _NAME_PARTICLES:
            continue
        return False
    return True


def maybe_flip_surname_first(name):
    """Detect 'Surname, Firstname [Middle]' form and flip to 'Firstname [Middle] Surname'.

    Older BBC episodes (pre-~2017) used surname-first composer names.
    The modern format uses firstname-first. To make canonical keys match
    across the format boundary, we flip when we recognise the surname-first
    pattern — but only when we're confident, because the modern data also
    contains comma-bearing strings that must be left alone:

      - "Joseph Bologne, Chevalier de Saint-Georges" — name + epithet
      - "Brian Eno, Julia Wolfe"                     — two contributors
      - "Anonymous, arr. Lila Hajosi"                — source + arranger
      - "Traditional, Edvard Grieg"                  — source + composer
      - "Moritz, Landgrave of Hessen-Kassel"         — name + title

    True surname-first cases like "Beethoven, Ludwig van", "Bach, Carl
    Philipp Emanuel", "Dall'Abaco, Evaristo Felice" still flip correctly.
    """
    if "," not in name:
        return name
    parts = name.split(",", 1)
    if len(parts) != 2:
        return name
    surname, given = parts[0].strip(), parts[1].strip()
    if not surname or not given:
        return name

    # Block 1: role abbreviations anywhere — "arr.", "trans.", "orch.", etc.
    if _ROLE_ABBREV_RE.search(surname) or _ROLE_ABBREV_RE.search(given):
        return name

    # Block 2: source-attribution markers in the first half
    # ("Traditional, ...", "Anonymous, ...", "Anon, ...")
    if _MARKER_RE.search(surname):
        return name

    # Block 3: quoted surname half — likely a work/group name, not a surname
    # ("'Les Six', Marius Constant")
    if surname.startswith(("'", '"', "\u2018", "\u201C")) or \
       surname.endswith(("'", '"', "\u2019", "\u201D")):
        return name

    # Block 4: title/epithet at the start of the given half
    # ("Bologne, Chevalier...", "Moritz, Landgrave...", "Smyth, Dame Ethel")
    if _TITLE_RE.match(given):
        return name

    # Block 5: both halves look like complete First-Last names (two contributors)
    # E.g., "Brian Eno, Julia Wolfe". Use capitalized non-particle token count.
    if _capitalized_name_tokens(surname) >= 2 and _capitalized_name_tokens(given) >= 2:
        return name

    # Block 6: surname half is sentence-style, not name-style — catches
    # mis-parsed track titles that happen to contain commas
    # ("With darkness deep, from Theodora, HWV 68")
    if not _looks_like_name(surname):
        return name

    # Sanity: word count
    surname_words, given_words = surname.split(), given.split()
    if not (1 <= len(surname_words) <= 3 and 1 <= len(given_words) <= 4):
        return name

    return f"{given} {surname}"


# Years inside a balanced (...) are handled fine by the (...) parser
# below — classify_role tells a date apart from a role. The bug is only
# date spans that ESCAPE a balanced paren: bare years, or years fenced
# by one-sided / mismatched brackets ("Antonin 1841-1904 Dvorak",
# "Couperin 1668-1733]", "(1770-1827 Beethoven", "[1840-1893)"). Left
# alone, those get folded into the composer's name. _strip_malformed_-
# dates finds every balanced (...) span — even nested ones — keeps
# those verbatim, and scrubs date spans only from the gaps between.
#
# A leading qualifier the BBC writes for an uncertain year: "c."/"ca."
# (circa), "fl." (floruit), "b." (born), "after"/"before", "?". The
# dotless "c"/"ca"/"fl" forms only count glued straight to digits
# ("c1702"), so a forename ending in those letters isn't eaten.
_DATE_QUALIFIER = (
    r"(?:ca\.\s*|ca(?=\d)|c\.\s*|c(?=\d)|fl\.\s*|fl(?=\d)"
    r"|b\.\s*|after\s+|before\s+|\?)?"
)
_LOOSE_DATE_RE = re.compile(
    r"[\[\](){}]*\s*" + _DATE_QUALIFIER + r"\d{3,4}\s*[-–—]+\s*"
    + _DATE_QUALIFIER + r"\d*\s*[\[\](){}]*"
)


def _strip_malformed_dates(line):
    # Flag every char enclosed in a balanced (...) pair, nesting included.
    protected = bytearray(len(line))
    opens = []
    for idx, ch in enumerate(line):
        if ch == "(":
            opens.append(idx)
        elif ch == ")" and opens:
            for k in range(opens.pop(), idx + 1):
                protected[k] = 1
    # Rebuild: protected spans verbatim, unprotected gaps scrubbed of date
    # spans and orphan brackets. "(" is kept — parse_composer_line tolerates
    # an unclosed one (it scans to the next ")"); a stray ")" or "[" is not.
    out, i, n = [], 0, len(line)
    while i < n:
        j = i
        while j < n and not protected[j]:
            j += 1
        if j > i:
            seg = _LOOSE_DATE_RE.sub(" ", line[i:j])
            out.append(re.sub(r"[\[\]){}]", "", seg))
            i = j
        j = i
        while j < n and protected[j]:
            j += 1
        out.append(line[i:j])
        i = j
    return re.sub(r"\s{2,}", " ", "".join(out))


def parse_composer_line(line):
    """Parse 'Brahms (1833-1897), Schoenberg (arr.)' into a list of
    (name, role) tuples. The first contributor is the principal composer.

    Handles two BBC format generations:
      - Modern (~2017+): 'Firstname Lastname (dates), Other Person (role)'
      - Older:           'Lastname, Firstname (dates), arr. Other Person (dates)'
                         and occasional [dates] in square brackets instead of ()."""
    # Older episodes sometimes use [1698-1778] instead of (1698-1778).
    # Normalise once up front; safe because brackets in composer-lines are dates.
    line = re.sub(r"\[([^\[\]]*)\]", r"(\1)", line)
    # Then drop any malformed date span (bare or one-sided brackets) that
    # survived — otherwise it gets absorbed into the composer's name.
    line = _strip_malformed_dates(line)

    contributors = []
    paren_re = re.compile(r"\(([^)]*)\)")
    pos = 0
    while pos < len(line):
        m = paren_re.search(line, pos)
        if not m:
            tail = line[pos:].strip(" ,")
            if tail:
                contributors.append(
                    (maybe_flip_surname_first(tail),
                     "composer" if not contributors else "contributor"))
            break
        name = line[pos:m.start()].strip(" ,")
        info = m.group(1).strip()
        role = classify_role(info, is_first=(not contributors))
        if name:
            contributors.append((maybe_flip_surname_first(name), role))
        pos = m.end()
        while pos < len(line) and line[pos] in " ,":
            pos += 1
    if not contributors:
        contributors.append((maybe_flip_surname_first(line.strip()), "composer"))
    return contributors


def parse_tracks(long_synopsis):
    """Yield one dict per piece in the episode's long_synopsis text."""
    if not long_synopsis:
        return []
    lines = long_synopsis.split("\n")
    out = []
    i = 0
    while i < len(lines):
        if TIME_RE.match(lines[i].strip()):
            time_str = lines[i].strip()
            block = []
            j = i + 1
            while j < len(lines) and not TIME_RE.match(lines[j].strip()):
                if lines[j].strip():
                    block.append(lines[j].strip())
                j += 1
            if len(block) >= 2:
                composer_line = block[0]
                title = block[1]
                performers = " | ".join(block[2:]) if len(block) > 2 else ""
                contributors = parse_composer_line(composer_line)
                out.append({
                    "time": time_str,
                    "composer_line": composer_line,
                    "composer": contributors[0][0] if contributors else "",
                    "contributors": contributors,
                    "title": title,
                    "performers": performers,
                })
            i = j
        else:
            i += 1
    return out


# ---------- Database -------------------------------------------------------

def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            pid              TEXT PRIMARY KEY,
            title            TEXT,
            subtitle         TEXT,
            broadcast_date   TEXT,
            duration_seconds INTEGER,
            parent_pid       TEXT,
            previous_pid     TEXT,
            next_pid         TEXT,
            raw_json         TEXT,
            fetched_at       TEXT
        );
        CREATE TABLE IF NOT EXISTS tracks (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_pid       TEXT,
            position          INTEGER,
            time_str          TEXT,
            composer          TEXT,
            composer_line     TEXT,
            contributors_json TEXT,
            title             TEXT,
            performers        TEXT,
            FOREIGN KEY (episode_pid) REFERENCES episodes(pid)
        );
        CREATE INDEX IF NOT EXISTS idx_tracks_episode  ON tracks(episode_pid);
        CREATE INDEX IF NOT EXISTS idx_tracks_composer ON tracks(composer);
        CREATE INDEX IF NOT EXISTS idx_tracks_title    ON tracks(title);
    """)
    return conn


def rebuild_tracks(conn, pid, long_synopsis):
    """Delete and re-derive the tracks rows for one episode from its
    long_synopsis, using the current parser. Returns the list of parsed
    track dicts. Does NOT commit — the caller owns the transaction."""
    cur = conn.cursor()
    cur.execute("DELETE FROM tracks WHERE episode_pid = ?", (pid,))
    parsed = parse_tracks(long_synopsis)
    for pos, t in enumerate(parsed):
        cur.execute(
            "INSERT INTO tracks "
            "(episode_pid, position, time_str, composer, composer_line, "
            " contributors_json, title, performers) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pos, t["time"], t["composer"], t["composer_line"],
             json.dumps(t["contributors"], ensure_ascii=False),
             t["title"], t["performers"]))
    return parsed


def upsert_episode(conn, prog, raw_json):
    pid = prog["pid"]
    display = prog.get("display_title") or {}
    title = display.get("title") or prog.get("title")
    subtitle = display.get("subtitle")
    fbd = prog.get("first_broadcast_date")
    parent = (prog.get("parent") or {}).get("programme") or {}
    parent_pid = parent.get("pid")
    versions = prog.get("versions") or []
    duration = versions[0].get("duration") if versions else None
    peers = prog.get("peers") or {}
    prev_pid = (peers.get("previous") or {}).get("pid")
    next_pid = (peers.get("next") or {}).get("pid")

    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO episodes "
        "(pid, title, subtitle, broadcast_date, duration_seconds, "
        " parent_pid, previous_pid, next_pid, raw_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, title, subtitle, fbd, duration, parent_pid,
         prev_pid, next_pid,
         json.dumps(raw_json, ensure_ascii=False),
         dt.datetime.now(dt.timezone.utc).isoformat()))

    rebuild_tracks(conn, pid, prog.get("long_synopsis", ""))
    conn.commit()
    return prev_pid, fbd


def render_walk_summary(result):
    """End-of-run QC summary for a backward walk: counts, the fetched date
    range, and the low-track-count episodes worth eyeballing (zero-track =
    genuine gap or new synopsis quirk; sparse = possible parser loss)."""
    lines = ["Walk summary:"]
    rng = ""
    if result["newest_date"] and result["oldest_date"]:
        rng = f"   range: {result['oldest_date']} → {result['newest_date']}"
    lines.append(f"  fetched: {result['fetched']:,} new   "
                 f"skipped: {result['skipped']:,} cached{rng}")
    zero = [a for a in result["anomalies"] if a[2] == 0]
    sparse = [a for a in result["anomalies"] if a[2] != 0]
    if zero:
        items = ", ".join(f'{p} {d} "{t}"' for p, d, _, t in zero)
        lines.append(f"  zero-track ({len(zero)}): {items}")
    if sparse:
        items = ", ".join(f"{p} {d} ({n})" for p, d, n, _ in sparse)
        lines.append(f"  sparse <{SPARSE_TRACK_THRESHOLD} ({len(sparse)}): {items}")
    if not result["anomalies"]:
        lines.append("  no track-count anomalies")
    return "\n".join(lines)


def _resolve_seed_date(session, conn, seed_pid):
    """Broadcast date of the seed, to anchor --days to the seed (not 'now').

    Reads the DB if the seed is already cached; otherwise fetches it once and
    upserts it, so the subsequent walk sees it cached and never re-fetches.
    Returns a tz-aware datetime, or None if it can't be determined.
    """
    row = conn.execute(
        "SELECT broadcast_date FROM episodes WHERE pid = ?",
        (seed_pid,)).fetchone()
    if row and row[0]:
        return parse_date(row[0])
    data = fetch_one(session, seed_pid)
    if not data:
        return None
    _, fbd = upsert_episode(conn, data["programme"], data)
    return parse_date(fbd)


# ---------- Main loop ------------------------------------------------------

def fetch_one(session, pid):
    data = fetch_json(session, f"{BASE}/programmes/{pid}.json")
    if not data or "programme" not in data:
        return None
    return data


def parse_date(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _choose_seed_pid(broadcasts, now):
    """Pick a seed episode PID from upcoming.json `broadcasts`.

    Prefer the most recent broadcast that has already aired (so the seed is
    guaranteed to carry a tracklist); if none have aired yet, take the soonest
    upcoming one (its first peers.previous hop reaches the latest aired
    episode). Returns the episode PID, or None if no usable broadcast.
    """
    aired = [b for b in broadcasts
             if (d := parse_date(b.get("start"))) and d <= now]
    if aired:
        chosen = max(aired, key=lambda b: parse_date(b["start"]))
    elif broadcasts:
        chosen = min(broadcasts, key=lambda b: parse_date(b.get("start")) or now)
    else:
        return None
    return (chosen.get("programme") or {}).get("pid")


def discover_seed(session):
    """Find a recent episode PID to start the backward walk from.

    The brand's `episodes/upcoming.json` is the one episode-listing endpoint
    that still serves usable JSON (the player/guide pages went JavaScript-only),
    so we read the scheduled broadcasts from it and pick a seed via
    _choose_seed_pid. Falls back to DEFAULT_SEED if the request fails or returns
    nothing, so the scraper still runs if the endpoint ever changes.
    """
    try:
        data = fetch_json(session, UPCOMING_URL)
    except Exception as e:
        print(f"  seed discovery failed ({e}); using default seed {DEFAULT_SEED}",
              file=sys.stderr)
        return DEFAULT_SEED
    pid = _choose_seed_pid((data or {}).get("broadcasts") or [],
                           dt.datetime.now(dt.timezone.utc))
    if not pid:
        print(f"  seed discovery returned nothing; using default seed "
              f"{DEFAULT_SEED}", file=sys.stderr)
        return DEFAULT_SEED
    print(f"  seed: discovered {pid} from upcoming.json", file=sys.stderr)
    return pid


# Below this many parsed tracks an episode is flagged in the end-of-run report
# as a possible parser anomaly (matches the QC "sparse episode" query). Zero is
# the genuine-gap case; 1-9 usually means a synopsis-format quirk.
SPARSE_TRACK_THRESHOLD = 10


def walk_backwards(session, conn, seed_pid, cutoff, delay, max_episodes):
    """Follow peers.previous from seed_pid until we run out or hit cutoff.

    Returns a result dict summarising the run (fetched/skipped counts, the
    fetched date range, the stop reason, and an `anomalies` list of episodes
    that parsed to fewer than SPARSE_TRACK_THRESHOLD tracks) for the
    end-of-run report. Per-episode progress is still streamed to stderr.
    """
    cur = conn.cursor()
    result = {"fetched": 0, "skipped": 0, "anomalies": [],
              "newest_date": None, "oldest_date": None, "stop": "exhausted"}
    pid = seed_pid
    n = 0
    while pid and (max_episodes is None or n < max_episodes):
        row = cur.execute(
            "SELECT previous_pid, broadcast_date FROM episodes WHERE pid = ?",
            (pid,)).fetchone()
        if row is not None:
            prev_pid, fbd = row
            result["skipped"] += 1
            print(f"  [skip] {pid} ({(fbd or '?')[:10]}) already in DB",
                  file=sys.stderr)
            d = parse_date(fbd)
            if d and d < cutoff:
                print("  reached cutoff (cached).", file=sys.stderr)
                result["stop"] = "cutoff"
                return result
            pid = prev_pid
            continue

        try:
            data = fetch_one(session, pid)
        except Exception as e:
            print(f"  [err]  {pid}: {e}", file=sys.stderr)
            time.sleep(delay)
            result["stop"] = "error"
            return result
        if not data:
            print(f"  [404]  {pid} not found, stopping.", file=sys.stderr)
            result["stop"] = "not_found"
            return result

        prog = data["programme"]
        prev_pid, fbd = upsert_episode(conn, prog, data)
        ntracks = cur.execute(
            "SELECT COUNT(*) FROM tracks WHERE episode_pid = ?",
            (pid,)).fetchone()[0]
        n += 1
        result["fetched"] = n
        date10 = (fbd or "?")[:10]
        if result["newest_date"] is None:
            result["newest_date"] = date10
        result["oldest_date"] = date10
        label = (prog.get("display_title", {}).get("subtitle")
                 or prog.get("title") or "")
        if ntracks < SPARSE_TRACK_THRESHOLD:
            result["anomalies"].append((pid, date10, ntracks, label[:55]))
        print(f"  [{n:>4}] {pid} {date10}  {ntracks:>2} tracks  "
              f"{label[:55]}", file=sys.stderr)

        d = parse_date(fbd)
        if d and d < cutoff:
            print("  reached cutoff.", file=sys.stderr)
            result["stop"] = "cutoff"
            return result
        pid = prev_pid
        time.sleep(delay)
    if pid and max_episodes is not None and n >= max_episodes:
        result["stop"] = "max_episodes"
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="ttn.sqlite",
                    help="SQLite output path (default: ttn.sqlite)")
    ap.add_argument("--days", type=int, default=365,
                    help="Walk back this many days from the seed's broadcast "
                         "date (default: 365)")
    ap.add_argument("--seed", default=None,
                    help="Starting episode PID for the backward walk. Default: "
                         "auto-discover the most recent episode from the BBC "
                         f"schedule (falls back to {DEFAULT_SEED} if that fails).")
    ap.add_argument("--pids", default=None,
                    help="Comma-separated PIDs to fetch instead of walking. "
                         "Useful for spot-checks.")
    ap.add_argument("--max-episodes", type=int, default=None,
                    help="Hard cap on episodes fetched (safety net).")
    ap.add_argument("--delay", type=float, default=0.8,
                    help="Seconds between requests (default: 0.8)")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    conn = init_db(args.db)

    if args.pids:
        pids = [p.strip() for p in args.pids.split(",") if p.strip()]
        print(f"Fetching {len(pids)} explicit episode(s)…", file=sys.stderr)
        for pid in pids:
            try:
                data = fetch_one(session, pid)
            except Exception as e:
                print(f"  {pid}: {e}", file=sys.stderr)
                continue
            if data:
                _, fbd = upsert_episode(conn, data["programme"], data)
                cur = conn.cursor()
                ntracks = cur.execute(
                    "SELECT COUNT(*) FROM tracks WHERE episode_pid = ?",
                    (pid,)).fetchone()[0]
                print(f"  {pid} {(fbd or '?')[:10]}  {ntracks} tracks",
                      file=sys.stderr)
            time.sleep(args.delay)
    else:
        seed = args.seed or discover_seed(session)
        anchor = (_resolve_seed_date(session, conn, seed)
                  or dt.datetime.now(dt.timezone.utc))
        cutoff = anchor - dt.timedelta(days=args.days)
        print(f"Walking back from {seed} ({anchor.date()}) until "
              f"{cutoff.date()}…", file=sys.stderr)
        result = walk_backwards(session, conn, seed, cutoff,
                                args.delay, args.max_episodes)
        print(render_walk_summary(result), file=sys.stderr)

    conn.close()
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
