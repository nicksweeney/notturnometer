#!/usr/bin/env python3
"""Fetch BBC /programmes/{pid}/segments.json into the DB: a raw source-of-truth
blob per episode plus a derived segment_events table. Gap-driven, the
counterpart to ttn_scrape (fetch) and ttn_reparse (offline re-derive).

Library-only (SP4d-4): no standalone CLI — reached through the kitchen door.

    uv run ttn_data.py segments                 # fetch+store+derive episodes never attempted
    uv run ttn_data.py segments --dry-run       # report what would be fetched; writes nothing
    uv run ttn_data.py segments --reparse       # re-derive segment_events from blobs (offline)
    uv run ttn_data.py segments --retry-absent  # re-attempt episodes previously marked absent
    uv run ttn_data.py segments --pids b01d0zy2 # specific episodes
"""
import argparse
import datetime as dt
import json
import sqlite3
import sys
import time

import requests

from ttn_db import open_db
from ttn_scrape import BASE, USER_AGENT, fetch_json

# The BBC introduced the /segments.json system on 2012-03-15: b01d0zy2 is the
# first episode that carries segments, and 2012-03-14 (b01d0yf2) is confirmed
# segment-absent. Nothing exists below this date — the 2010-01-17 → 2012-03-15
# block is text-only (the same 2012+ boundary the spine/projection use). The
# gap selector floors here so it never wastes BBC round-trips on the pre-segments
# era; an explicit --pids still reaches below it for a deliberate spot-check.
SEGMENTS_FLOOR_DATE = "2012-03-15"


def ensure_segments_schema(conn):
    """Idempotently add the two episodes columns and the segment_events table.
    Self-contained so ttn_scrape.init_db stays untouched."""
    cur = conn.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(episodes)")}
    if "segments_raw_json" not in cols:
        cur.execute("ALTER TABLE episodes ADD COLUMN segments_raw_json TEXT")
    if "segments_fetched_at" not in cols:
        cur.execute("ALTER TABLE episodes ADD COLUMN segments_fetched_at TEXT")
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS segment_events (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            event_pid          TEXT UNIQUE,
            episode_pid        TEXT,
            position           INTEGER,   -- BBC event position, 1-indexed, stored verbatim
            version_offset     INTEGER,
            track_title        TEXT,
            composer_name      TEXT,
            composer_pid       TEXT,
            composer_mbid      TEXT,
            duration_seconds   INTEGER,
            recording_pid      TEXT,
            record_id          TEXT,
            record_label       TEXT,
            contributions_json TEXT,
            FOREIGN KEY (episode_pid) REFERENCES episodes(pid)
        );
        CREATE INDEX IF NOT EXISTS idx_segevents_episode   ON segment_events(episode_pid);
        CREATE INDEX IF NOT EXISTS idx_segevents_composer  ON segment_events(composer_mbid);
        CREATE INDEX IF NOT EXISTS idx_segevents_recording ON segment_events(recording_pid);
        CREATE INDEX IF NOT EXISTS idx_segevents_label     ON segment_events(record_label);
    """)
    conn.commit()


def derive_segment_events(raw_json):
    """Pure: blob (dict or JSON string) -> list of segment_events row dicts.
    Filters to type=='music'; takes primary_contributor as the authoritative
    composer; preserves the full contributions[] array as JSON. Returns []
    on empty/malformed input. Shared by the fetch path and --reparse."""
    try:
        data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except (TypeError, ValueError):
        return []
    if not data:
        return []
    out = []
    for ev in data.get("segment_events", []):
        seg = ev.get("segment") or {}
        if seg.get("type") != "music":
            continue
        pc = seg.get("primary_contributor") or {}
        out.append({
            "event_pid": ev.get("pid"),
            "position": ev.get("position"),
            "version_offset": ev.get("version_offset"),
            "track_title": seg.get("track_title"),
            "composer_name": pc.get("name") or seg.get("artist"),
            "composer_pid": pc.get("pid"),
            "composer_mbid": pc.get("musicbrainz_gid"),
            "duration_seconds": seg.get("duration"),
            "recording_pid": seg.get("pid"),
            "record_id": seg.get("record_id"),
            "record_label": seg.get("record_label"),
            "contributions_json": json.dumps(
                seg.get("contributions") or [], ensure_ascii=False),
        })
    return out


_SEGCOLS = ("event_pid, episode_pid, position, version_offset, track_title, "
            "composer_name, composer_pid, composer_mbid, duration_seconds, "
            "recording_pid, record_id, record_label, contributions_json")


def rebuild_segment_events(conn, episode_pid, raw_json):
    """Delete and re-derive segment_events rows for one episode from its blob.
    Does NOT commit — the caller owns the transaction. Returns the derived
    row dicts. The counterpart of ttn_scrape.rebuild_tracks."""
    cur = conn.cursor()
    cur.execute("DELETE FROM segment_events WHERE episode_pid = ?", (episode_pid,))
    rows = derive_segment_events(raw_json)
    for r in rows:
        cur.execute(
            f"INSERT OR IGNORE INTO segment_events ({_SEGCOLS}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["event_pid"], episode_pid, r["position"], r["version_offset"],
             r["track_title"], r["composer_name"], r["composer_pid"],
             r["composer_mbid"], r["duration_seconds"], r["recording_pid"],
             r["record_id"], r["record_label"], r["contributions_json"]))
    return rows


def select_episodes(conn, *, pids=None, retry_absent=False):
    """Return the ordered list of episode PIDs to operate on.
    - pids given: exactly those that exist, in the given order.
    - retry_absent: episodes attempted but found absent (blob NULL).
    - default: episodes never attempted (segments_fetched_at IS NULL)."""
    cur = conn.cursor()
    if pids is not None:
        out = []
        for pid in pids:
            if cur.execute("SELECT 1 FROM episodes WHERE pid = ?", (pid,)).fetchone():
                out.append(pid)
        return out
    # Both gap paths floor at the segments era — pre-2012-03 is text-only, so a
    # never-attempted (or absent) episode below the floor is not work, just waste.
    if retry_absent:
        q = ("SELECT pid FROM episodes WHERE segments_fetched_at IS NOT NULL "
             "AND segments_raw_json IS NULL AND broadcast_date >= ? "
             "ORDER BY broadcast_date")
    else:
        q = ("SELECT pid FROM episodes WHERE segments_fetched_at IS NULL "
             "AND broadcast_date >= ? ORDER BY broadcast_date")
    return [r[0] for r in cur.execute(q, (SEGMENTS_FLOOR_DATE,))]


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _has_music(raw):
    return bool(raw) and any(
        (e.get("segment") or {}).get("type") == "music"
        for e in raw.get("segment_events", []))


def ingest(conn, episodes, fetch_fn, *, dry_run=False, delay=0.8, progress=None):
    """Fetch+store+derive each episode. fetch_fn(pid) returns the parsed
    segments.json (dict) or None for 404/absent, and raises on network failure.
    Per-episode commit for resumability. Returns a result dict.

    `progress`, if given, is called once per episode as
    progress(n, pid, status, nsegs) where status is 'present'/'absent'/'failed'
    — the per-episode stdout stream, mirroring the scraper's walk output."""
    result = {"dry_run": dry_run, "attempted": 0, "present": 0,
              "absent": 0, "failed": 0, "segments": 0,
              "absent_pids": [], "failed_pids": [],
              "coverage_with": 0, "coverage_total": 0}
    if dry_run:
        # A dry-run is a gap PREVIEW: report how many episodes would be
        # attempted, with NO network fetch (present/absent is unknowable
        # without fetching, and isn't needed to preview the gap).
        result["attempted"] = len(list(episodes))
        return result
    cur = conn.cursor()
    for pid in episodes:
        result["attempted"] += 1
        try:
            raw = fetch_fn(pid)
        except Exception:
            result["failed"] += 1
            result["failed_pids"].append(pid)
            if progress:
                progress(result["attempted"], pid, "failed", 0)
            if delay:
                time.sleep(delay)
            continue
        present = _has_music(raw)
        nsegs = 0
        try:
            if present:
                cur.execute("UPDATE episodes SET segments_raw_json = ?, "
                            "segments_fetched_at = ? WHERE pid = ?",
                            (json.dumps(raw, ensure_ascii=False), _now_iso(), pid))
                nsegs = len(rebuild_segment_events(conn, pid, raw))
                result["segments"] += nsegs
            else:
                cur.execute("UPDATE episodes SET segments_raw_json = NULL, "
                            "segments_fetched_at = ? WHERE pid = ?",
                            (_now_iso(), pid))
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            result["failed"] += 1
            result["failed_pids"].append(pid)
            if progress:
                progress(result["attempted"], pid, "failed", 0)
            if delay:
                time.sleep(delay)
            continue
        status = "present" if present else "absent"
        result[status] += 1
        if not present:
            result["absent_pids"].append(pid)
        if progress:
            progress(result["attempted"], pid, status, nsegs)
        if delay:
            time.sleep(delay)
    result["coverage_with"], result["coverage_total"] = _coverage(conn)
    return result


def _coverage(conn):
    """(episodes with a stored segments blob, total episodes) — the running
    segments coverage of the corpus, for the end-of-run report."""
    with_segs = conn.execute(
        "SELECT COUNT(*) FROM episodes "
        "WHERE segments_raw_json IS NOT NULL").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    return with_segs, total


def reparse_segments(conn, *, pids=None, dry_run=False):
    """Re-derive segment_events from stored segments_raw_json blobs (offline,
    no network). Skips episodes with a NULL blob. Returns a result dict.
    No 'skipped' tally needed: blobs are json.dumps output (always well-formed)."""
    cur = conn.cursor()
    if pids is not None:
        rows = []
        for pid in pids:
            r = cur.execute("SELECT pid, segments_raw_json FROM episodes "
                            "WHERE pid = ?", (pid,)).fetchone()
            if r and r[1] is not None:
                rows.append(r)
    else:
        rows = cur.execute("SELECT pid, segments_raw_json FROM episodes "
                           "WHERE segments_raw_json IS NOT NULL").fetchall()
    result = {"dry_run": dry_run, "episodes": 0,
              "segments_before": 0, "segments_after": 0}
    for pid, raw in rows:
        before = cur.execute("SELECT COUNT(*) FROM segment_events "
                             "WHERE episode_pid = ?", (pid,)).fetchone()[0]
        new = derive_segment_events(raw)
        result["segments_before"] += before
        result["segments_after"] += len(new)
        if not dry_run:
            rebuild_segment_events(conn, pid, raw)
        result["episodes"] += 1
    if not dry_run:
        conn.commit()
    return result


# When a run's absent/failed set is at most this many PIDs, list them inline so
# they're actionable; beyond that the count alone keeps the report readable.
_REPORT_PID_LIMIT = 20


def _pid_tail(pids):
    """Inline '[pid, pid, …]' tail for a small enough PID set, else ''."""
    if pids and len(pids) <= _REPORT_PID_LIMIT:
        return "   [" + ", ".join(pids) + "]"
    return ""


def render_ingest(result, db_path):
    if result["dry_run"]:
        return "\n".join([
            f"Segments ingest {db_path}  [DRY RUN]",
            f"  would attempt: {result['attempted']:,} episode(s) in the gap "
            "(no fetch performed)",
        ])
    with_segs, total = result["coverage_with"], result["coverage_total"]
    pct = (100.0 * with_segs / total) if total else 0.0
    return "\n".join([
        f"Segments ingest {db_path}",
        f"  attempted: {result['attempted']:,}",
        f"  present:   {result['present']:,}   (+{result['segments']:,} segment rows)",
        f"  absent:    {result['absent']:,}   (no segments.json / pre-2012)"
        + _pid_tail(result["absent_pids"]),
        f"  failed:    {result['failed']:,}   (network; retried next run)"
        + _pid_tail(result["failed_pids"]),
        f"  coverage:  {with_segs:,} / {total:,} episodes have segments "
        f"({pct:.1f}%)",
    ])


def render_reparse(result, db_path):
    mode = "  [DRY RUN]" if result["dry_run"] else ""
    before, after = result["segments_before"], result["segments_after"]
    return "\n".join([
        f"Segments reparse {db_path}{mode}  (re-derive from blobs)",
        f"  Episodes:  {result['episodes']:,} processed",
        f"  Segments:  {before:,} → {after:,}   ({after - before:+,})",
    ])


def _make_fetch(session):
    def fetch(pid):
        return fetch_json(session, f"{BASE}/programmes/{pid}/segments.json")
    return fetch


# BBC-politeness floor. Enforced at the CLI only: the ingest() function itself
# accepts any delay (tests pass 0), but the command line cannot go below this.
# Dropping under 0.5s is a deliberate code edit, not a runtime flag.
_MIN_CLI_DELAY = 0.5


def _cli_delay(value):
    """argparse type for --delay: parse to float and enforce _MIN_CLI_DELAY.
    Raising ArgumentTypeError makes argparse reject the run before it opens the
    DB or touches the network."""
    d = float(value)
    if d < _MIN_CLI_DELAY:
        raise argparse.ArgumentTypeError(
            f"must be >= {_MIN_CLI_DELAY} (BBC politeness floor); "
            "to go lower, edit the code")
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Fetch BBC segments.json into segment_events (and a raw "
                    "blob); offline --reparse re-derives from the blobs.")
    ap.add_argument("db", nargs="?", default="ttn.sqlite",
                    help="path to the SQLite DB (default: ttn.sqlite)")
    ap.add_argument("--pids", help="comma-separated episode PIDs (default: the gap)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report without writing")
    ap.add_argument("--reparse", action="store_true",
                    help="re-derive segment_events from stored blobs (offline)")
    ap.add_argument("--retry-absent", action="store_true",
                    help="re-attempt episodes previously marked absent")
    ap.add_argument("--delay", type=_cli_delay, default=0.8,
                    help="inter-request delay seconds (default 0.8; CLI floor "
                         f"{_MIN_CLI_DELAY}s — edit the code to go lower)")
    args = ap.parse_args(argv)

    pids = [p.strip() for p in args.pids.split(",")] if args.pids else None
    conn = open_db(args.db, ap)
    try:
        ensure_segments_schema(conn)
        if args.reparse:
            result = reparse_segments(conn, pids=pids, dry_run=args.dry_run)
            print(render_reparse(result, args.db))
        else:
            episodes = select_episodes(conn, pids=pids,
                                       retry_absent=args.retry_absent)
            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})

            def _progress(n, pid, status, nsegs):
                extra = f"  +{nsegs} segs" if status == "present" else ""
                print(f"  [{n:>4}] {pid}  {status}{extra}", file=sys.stderr)

            result = ingest(conn, episodes, _make_fetch(session),
                            dry_run=args.dry_run, delay=args.delay,
                            progress=None if args.dry_run else _progress)
            print(render_ingest(result, args.db))
    finally:
        conn.close()
