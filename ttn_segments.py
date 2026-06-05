#!/usr/bin/env python3
"""Fetch BBC /programmes/{pid}/segments.json into the DB: a raw source-of-truth
blob per episode plus a derived segment_events table. Standalone and gap-driven,
the counterpart to ttn_scrape (fetch) and ttn_reparse (offline re-derive).

    uv run ttn_segments.py                 # fetch+store+derive episodes never attempted
    uv run ttn_segments.py --dry-run       # report what would be fetched; writes nothing
    uv run ttn_segments.py --reparse       # re-derive segment_events from blobs (offline)
    uv run ttn_segments.py --retry-absent  # re-attempt episodes previously marked absent
    uv run ttn_segments.py --pids b01d0zy2 # specific episodes
"""
import argparse
import datetime as dt
import json
import sqlite3
import time

import requests

from ttn_scrape import BASE, USER_AGENT, fetch_json


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
            position           INTEGER,
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
