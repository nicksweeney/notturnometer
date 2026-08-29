"""ttn2_ingest — successor events framework, layer 1: observations.

Builds successor.sqlite from the CURRENT pipeline's per-source stores. The
existing tools are reused, not forked: text observations come from the
`tracks` table (ttn_scrape.parse_tracks output, kept fresh by the reparse
discipline) and segment observations from `segment_events`
(ttn_segments.derive_segment_events output). Both are re-derivable from
raw_json / segments_raw_json, so obs stay re-runnable.

Design doc: docs/successor-events-framework.md.

Schema:
  obs(id, episode_pid, date10, ord, source, source_grade, composer_raw,
      composer_line, composer_mbid, title, title_raw, recording_pid,
      duration_s, time_str, version_offset, performers, contributors_json,
      interstitial, event_id)
  event(id, episode_pid, date10, ord, composer, title, method, confidence)
  ledger(...)                          -- built by ttn2_ledger
  meta(key, value)

ord: the broadcast anchor within the night. Segments use the BBC position
(1-indexed), falling back to a rank over version_offset where position is
NULL (the same fallback ttn_mbid_audit uses). Text obs use the 0-indexed
parse position; a +0.5 bias keeps text and segment obs from colliding on
the same ord before matching links them.

source_grade is era+field honest, per the design doc: 2012-2014 segment
rows are 'seg_early' (the QC-marker/instrument/key-mislabel era found in
2026), later segments 'seg', text era 'text'.
"""
import collections
import json
import sqlite3
import sys

import ttn_segment_meta as SM

DB = "successor.sqlite"

GRADE_CUTOFF = "2015-01-01"   # broadcast dates before this: 'seg_early'

SCHEMA = """
CREATE TABLE obs (
  id INTEGER PRIMARY KEY,
  episode_pid TEXT NOT NULL,
  date10 TEXT NOT NULL,
  ord REAL NOT NULL,
  source TEXT NOT NULL,
  source_grade TEXT NOT NULL,
  composer_raw TEXT,
  composer_line TEXT,
  composer_mbid TEXT,
  title TEXT,                     -- as the source's clean convention gives it
  title_raw TEXT,                 -- verbatim pre-sanitization (segments)
  recording_pid TEXT,
  duration_s INTEGER,
  time_str TEXT,
  version_offset REAL,
  performers TEXT,
  contributors_json TEXT,
  interstitial INTEGER NOT NULL DEFAULT 0,
  event_id INTEGER
);
CREATE INDEX idx_obs_ep ON obs(episode_pid);
CREATE INDEX idx_obs_rp ON obs(recording_pid);
CREATE TABLE event (
  id INTEGER PRIMARY KEY,
  episode_pid TEXT NOT NULL,
  date10 TEXT NOT NULL,
  ord REAL,
  composer TEXT,                  -- identity anchor (segment-clean where linked)
  title TEXT,
  method TEXT NOT NULL,           -- 'recording_pid' | 'dp_high' | 'singleton_text' | 'bridge'
  confidence TEXT NOT NULL,       -- 'high' | 'singleton'
  recording_pid TEXT,             -- set for 'recording_pid' and 'bridge' events
  work_key TEXT                   -- filled by ttn2_ledger resolve (analysis-time)
);
CREATE INDEX idx_event_ep ON event(episode_pid);
CREATE TABLE presentation (
  episode_pid TEXT NOT NULL,
  ord REAL NOT NULL,
  recording_pid TEXT NOT NULL,
  PRIMARY KEY (episode_pid, ord)
);
CREATE TABLE ledger (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,             -- 'work_alias' | 'composer_alias'
  scope TEXT NOT NULL,            -- 'global' | composer canonical key
  variant_key TEXT NOT NULL,
  target TEXT NOT NULL,
  target_key TEXT NOT NULL,
  method TEXT NOT NULL,           -- 'legacy-global' | 'legacy-scoped' | 'legacy-composer'
  confidence TEXT NOT NULL,       -- 'review' | 'medium' | 'ok'
  flags_json TEXT
);
CREATE INDEX idx_ledger_lookup ON ledger(kind, scope, variant_key);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _date10(conn):
    return {pid: d[:10] for pid, d in conn.execute(
        "SELECT pid, broadcast_date FROM episodes")}


def build(src="ttn.sqlite", dst=DB):
    out = sqlite3.connect(dst)
    out.executescript("DROP TABLE IF EXISTS obs; DROP TABLE IF EXISTS event;"
                      " DROP TABLE IF EXISTS presentation;"
                      " DROP TABLE IF EXISTS ledger; DROP TABLE IF EXISTS meta;"
                      + SCHEMA)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    dates = _date10(src_conn)

    n_text = n_seg = 0
    obs = []
    # --- text observations: tracks table == parse_tracks output (reparse-verified)
    for pid, pos, time_str, comp, comp_line, title, perf, contrib in src_conn.execute(
            "SELECT episode_pid, position, time_str, composer, composer_line, "
            "title, performers, contributors_json FROM tracks"):
        obs.append((pid, dates[pid], float(pos), "text", "text",
                    comp, comp_line, None, title, None, None, None,
                    time_str, None, perf, contrib, 0))
        n_text += 1
    # --- segment observations: segment_events == derive_segment_events output
    seg_rows = src_conn.execute(
        "SELECT episode_pid, position, version_offset, track_title, "
        "composer_name, composer_mbid, duration_seconds, recording_pid, "
        "contributions_json FROM segment_events").fetchall()
    # ord: BBC position (1-indexed). NULL positions (8.4% of segments) rank
    # by version_offset, sequenced after positioned rows of the same night --
    # the same fallback ttn_mbid_audit applies for its temporal anchor.
    null_pos = collections.defaultdict(list)
    for i, r in enumerate(seg_rows):
        if r[1] is None:
            null_pos[r[0]].append(i)
    for ep in null_pos:
        null_pos[ep].sort(key=lambda i: (seg_rows[i][2] or 0.0))
    null_rank = {i: 1000.0 + rank
                 for ep, idxs in null_pos.items()
                 for rank, i in enumerate(idxs)}
    for i, (ep, pos, voff, title_raw, comp, mbid, dur, rp, contrib) in enumerate(seg_rows):
        d10 = dates[ep]
        ordv = float(pos) if pos is not None else null_rank[i]
        grade = "seg_early" if d10 < GRADE_CUTOFF else "seg"
        title = SM.sanitize_segment_title(title_raw) or title_raw
        obs.append((ep, d10, ordv, "segment", grade, comp, None, mbid, title,
                    title_raw, rp, dur, None, voff, None, contrib,
                    1 if SM.is_interstitial(rp) else 0))
        n_seg += 1
    conn_cnt = src_conn.execute("SELECT COUNT(*) FROM segment_events").fetchone()[0]
    src_conn.close()

    out.executemany(
        "INSERT INTO obs (episode_pid, date10, ord, source, source_grade, "
        "composer_raw, composer_line, composer_mbid, title, title_raw, "
        "recording_pid, duration_s, time_str, version_offset, performers, "
        "contributors_json, interstitial) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        obs)
    out.executemany("INSERT INTO meta VALUES (?,?)", [
        ("source_db", src), ("text_obs", str(n_text)),
        ("segment_obs", str(n_seg)), ("segment_events_expected", str(conn_cnt)),
        ("built", "ttn2_ingest"),
    ])
    out.commit()
    assert n_seg == conn_cnt, "segment obs must be lossless vs segment_events"
    print(f"ttn2_ingest: {n_text} text obs, {n_seg} segment obs -> {dst}")
    return n_text, n_seg


if __name__ == "__main__":
    import collections
    build(*sys.argv[1:3])
