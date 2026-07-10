"""Recording-anchored identity projection (SP3): precompute the tracks->recording
mapping (ttn_mbid_audit.reconcile_corpus, High tier only) plus the
recording->clean-identity rec_meta into one fingerprinted cache that
ttn_analyze --source auto consumes. Slow cold build, sub-second load;
rebuilt only when its inputs (tracks, segment_events, the matcher) change.
Derived/offline; the cache is gitignored.
See docs/superpowers/specs/2026-06-09-identity-substrate-design.md."""
import argparse, hashlib, json, os, sqlite3

from ttn_db import open_db

PROJECTION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "ttn_projection_cache.json")

def projection_from_matches(matches):
    """{(episode_pid, track_position): recording_pid} for High-tier matches only.
    Pure — the High gate + keying, independent of the DP matcher."""
    out = {}
    for m in matches:
        if m.get("tier") == "high" and m.get("recording_pid"):
            out[(m["episode_pid"], m["track_position"])] = m["recording_pid"]
    return out

def build_projection_mbid(conn):
    """The 2012+ DP reconcile, High matches only. ~6.6 min."""
    from ttn_mbid_audit import reconcile_corpus
    return projection_from_matches(reconcile_corpus(conn))

def build_projection(conn):
    """The full projection: 2012+ MBID High matches merged with the pre-2012
    trusted bridge links. The key-spaces are disjoint (2012+ episodes carry
    segments -> MBID path; text-only episodes -> bridge path), so update() is
    safe. The slow path (DP reconcile + spine/bridge build)."""
    proj = build_projection_mbid(conn)
    proj.update(bridge_projection(conn))
    return proj


def build_rec_meta(conn):
    """recording_pid -> (segment_composer_name, segment_track_title), first
    non-empty title per recording. The clean identity source the projection
    substitutes in — derived from exactly the segment_events columns _rows_sha
    fingerprints, so it shares the projection's freshness domain: built at
    warm time and stored in the cache (the full segment_events scan costs
    ~17 s on the Pi), loaded alongside the projection.

    RECORDING_COMPOSER_OVERRIDES (ttn_segment_meta) is applied here: the rare
    recording whose segment metadata itself mis-credits the composer (name AND
    MBID wrong upstream — the Radetzky/Strauss-II case) gets the curated
    correct name, so the projection doesn't import the upstream error as the
    clean identity. ttn_segment_meta.py is in _FINGERPRINT_FILES, so editing
    an override rebuilds the cache."""
    from ttn_segment_meta import RECORDING_COMPOSER_OVERRIDES as overrides
    rec_meta = {}
    for rp, cn, tt in conn.execute(
            "SELECT recording_pid, composer_name, track_title FROM segment_events "
            "WHERE recording_pid IS NOT NULL AND track_title IS NOT NULL "
            "AND track_title != ''"):
        rec_meta.setdefault(rp, (overrides.get(rp, cn), tt))
    return rec_meta


def _expand_links(links, airings, *, key_of):
    """Pure: {(episode_pid, position): recording_pid} from TRUSTED links only.
    `key_of(link.text_rec)` -> the airing-map key; `airings` maps that key to
    the airing list. v1 ingests link.tier == 'trusted' (auto); 'accepted'
    (ledger-promoted candidates) is deferred to v2."""
    out = {}
    for lk in links:
        if lk.tier != "trusted":
            continue
        rp = lk.pid_sig.recording_pid
        for ep_pos in airings.get(key_of(lk.text_rec), []):
            out[ep_pos] = rp
    return out


def bridge_projection(conn):
    """Pre-2012 (text-only) {(episode_pid, position): recording_pid} from the
    cross-era bridge, TRUSTED tier only (v1). Builds the spine + bridge in
    memory (slow), so this is part of the build path, not load."""
    import ttn_bridge as B
    ctx = B.build_context(conn)
    pid_sigs = B.pid_signatures(conn, ctx)
    units = B.load_text_units(conn)      # shared by text_recordings + airings
    text_recs = B.text_recordings(conn, ctx, units=units)
    decisions = B.load_decisions()
    result = B.bridge(text_recs, pid_sigs, decisions)
    airings = B.airings_by_text_key(conn, ctx, units=units)
    return _expand_links(result.trusted, airings, key_of=B.text_recording_key)


# Files whose bytes feed the projection: the 2012+ matcher (ttn_mbid_audit +
# ttn_analyze's folding), and the pre-2012 bridge chain (ttn_bridge + its
# spine/credits/audit deps + the alias tables) and its accept/reject ledger.
_FINGERPRINT_FILES = (
    "ttn_project.py",                       # the projection-BUILD logic self-hashes
    "ttn_mbid_audit.py", "ttn_analyze.py",
    "ttn_bridge.py", "ttn_credits.py", "ttn_spine.py", "ttn_audit.py",
    "ttn_aliases.py", "ttn_bridge_decisions.json",
    "ttn_segment_meta.py",                  # RECORDING_COMPOSER_OVERRIDES feeds rec_meta
)

def _db_marker(conn):
    """A cheap, exact 'rows unchanged since' witness for the DB behind `conn`:
    SQLite's file change counter (header bytes 24-27) increments on every
    rollback-journal commit, so an unchanged (counter, file size) pair means no
    transaction has touched the file — the expensive row scan in _rows_sha can
    be skipped and its cached digest trusted. The marker also binds the DB's
    IDENTITY (resolved path): counter+size alone can collide across two
    different DBs (both freshly built -> same counter; similar content ->
    same size), which would serve DB-A's cached projection against DB-B as
    fresh with the row-content check bypassed (adversarial-review finding
    2026-07-10). A path mismatch just drops to the conservative full rescan —
    same-DB-copied-elsewhere pays one scan, never trusts wrongly. Returns
    None (= never trust, always rescan) when the witness doesn't hold:
    in-memory/temp DBs (no file) and WAL mode (WAL defers the counter bump
    to checkpoints)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    if not path:
        return None
    if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
        return None
    try:
        with open(path, "rb") as fh:
            header = fh.read(28)
        size = os.path.getsize(path)
    except OSError:
        return None
    if len(header) < 28:
        return None
    return [int.from_bytes(header[24:28], "big"), size, os.path.realpath(path)]

def _rows_sha(conn):
    """sha1 over the reconcile INPUT rows (tracks + segment_events). The slow
    part of the fingerprint (~23 s on the Pi: a full scan of both tables) —
    load() skips it via _db_marker when the DB file hasn't changed. Rows are
    ordered over EVERY selected column — a total order over row content (ties
    are identical rows), so identical data hashes identically regardless of
    insertion order."""
    h = hashlib.sha1()
    for q in ("SELECT episode_pid, position, time_str, composer, title "
              "FROM tracks ORDER BY 1, 2, 3, 4, 5",
              "SELECT episode_pid, position, version_offset, composer_name, "
              "track_title, composer_mbid, recording_pid "
              "FROM segment_events ORDER BY 1, 2, 3, 4, 5, 6, 7"):
        for row in conn.execute(q):
            h.update(repr(row).encode("utf-8"))
    return h.hexdigest()

def _fingerprint(conn, rows_sha=None):
    """sha1 over the reconcile INPUTS (tracks + segment_events rows, via
    _rows_sha — pass a precomputed digest to skip the scan) plus the bytes of
    every file in _FINGERPRINT_FILES — the 2012+ matcher AND the pre-2012
    bridge chain + its decisions ledger. A reparse, a segments re-derive, a
    matcher/fold/bridge/alias edit, or a ledger verdict invalidates the
    cache."""
    h = hashlib.sha1((rows_sha or _rows_sha(conn)).encode("utf-8"))
    here = os.path.dirname(os.path.abspath(__file__))
    for mod in _FINGERPRINT_FILES:
        try:
            with open(os.path.join(here, mod), "rb") as fh:
                h.update(fh.read())
        except OSError:
            if mod == "ttn_bridge_decisions.json":
                continue            # ledger may not exist yet; absence is stable
            return ""
    return h.hexdigest()

def _write_cache(path, projection, fingerprint, rows_sha=None, db_marker=None,
                 rec_meta=None):
    data = {"fingerprint": fingerprint,
            "rows_sha": rows_sha, "db_marker": db_marker,
            "projection": {f"{ep}\t{pos}": rp for (ep, pos), rp in projection.items()},
            "rec_meta": {rp: list(ct) for rp, ct in (rec_meta or {}).items()}}
    _atomic_json_dump(path, data)


def _atomic_json_dump(path, data):
    """Write JSON via tmp-file + os.replace so an interrupted write (killed
    warm, power loss) can never leave a TRUNCATED cache at the real path —
    the reader sees either the old complete file or the new complete file.
    Matters doubly for load()'s re-stamp, which rewrites a GOOD cache on a
    routine fast-path miss."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)

def _has_table(conn, name):
    """True iff `name` is a table in this connection. Used to treat a DB with
    no segment lineage as 'missing projection' rather than erroring."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None

def load(conn, path=PROJECTION_PATH):
    """Return (projection_dict, rec_meta, status). status: 'ok' | 'missing' |
    'stale'. Never builds — staleness is the caller's cue to run
    `ttn_data.py warm`. A DB lacking the tracks/segment_events lineage is
    reported 'missing' (no projection is possible), not an error. A CORRUPT
    or wrong-shape cache (truncated write, hand-edit) is also 'missing' —
    it must degrade exactly like an absent file, never raise: an uncaught
    JSONDecodeError here used to wedge every consumer INCLUDING `warm`
    itself (ensure -> load -> crash), so no tool could self-heal short of a
    manual rm of the cache."""
    if not (_has_table(conn, "tracks") and _has_table(conn, "segment_events")):
        return {}, {}, "missing"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}, {}, "missing"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}, {}, "missing"                   # corrupt = rebuildable
    if not isinstance(data, dict) or "projection" not in data:
        return {}, {}, "missing"                   # parses, but not a cache
    # The marker fast-path: when the DB file provably hasn't changed since the
    # cache was written, reuse the cached row digest instead of rescanning
    # ~283k rows (~23 s -> sub-second on the everyday warm-hit load).
    marker = _db_marker(conn)
    rows_sha = None
    if marker is not None and data.get("rows_sha") and data.get("db_marker") == marker:
        rows_sha = data["rows_sha"]
    if rows_sha is None:
        rows_sha = _rows_sha(conn)
    if data.get("fingerprint") != _fingerprint(conn, rows_sha):
        return {}, {}, "stale"
    if marker is not None and (data.get("db_marker") != marker
                               or data.get("rows_sha") != rows_sha):
        # Fresh, but the marker moved (a write that left the reconcile-input
        # rows intact — e.g. an episodes-only update). Re-stamp the cache so
        # the next load takes the fast path again; best-effort only.
        data.update(rows_sha=rows_sha, db_marker=marker)
        try:
            _atomic_json_dump(path, data)          # never truncate a good cache
        except OSError:
            pass
    proj = {}
    for k, rp in data["projection"].items():
        ep, pos = k.split("\t")
        proj[(ep, int(pos))] = rp
    rec_meta = {rp: tuple(ct) for rp, ct in data.get("rec_meta", {}).items()}
    return proj, rec_meta, "ok"

def build(conn, path=PROJECTION_PATH):
    """Build the projection + rec_meta and write the fingerprinted cache. The
    slow path. The fingerprint, DB marker and rec_meta are all taken BEFORE
    the ~10-min build so they describe the inputs the projection was actually
    built from — a mid-build DB change then reads as stale on the next load
    instead of silently fresh."""
    marker = _db_marker(conn)
    rows_sha = _rows_sha(conn)
    fp = _fingerprint(conn, rows_sha)
    rec_meta = build_rec_meta(conn)
    proj = build_projection(conn)
    _write_cache(path, proj, fp, rows_sha, marker, rec_meta)
    return proj, rec_meta

def ensure(conn, path=PROJECTION_PATH):
    """Make-current entry point (ttn_warm calls it): return (projection,
    rec_meta, 'ok'), building the cache first if load reports it missing or
    stale. Returns ({}, {}, 'missing') WITHOUT building when there's no
    segment lineage to project."""
    proj, rec_meta, status = load(conn, path)
    if status == "ok":
        return proj, rec_meta, "ok"
    if not (_has_table(conn, "tracks") and _has_table(conn, "segment_events")):
        return {}, {}, "missing"
    proj, rec_meta = build(conn, path)
    return proj, rec_meta, "ok"

def _dual_lineage_track_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid IN "
        "(SELECT DISTINCT episode_pid FROM segment_events)").fetchone()[0]

def _bridge_coverage(projection, segment_episodes):
    """How many projection entries are pre-2012 (text-only) bridge links —
    i.e. their episode has no segment_events of its own."""
    return sum(1 for (ep, _pos) in projection if ep not in segment_episodes)

def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the recording-anchored projection cache (SP3).")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--status", action="store_true",
                    help="report cache status + coverage; writes nothing")
    a = ap.parse_args(argv)
    conn = open_db(a.db, ap)
    if a.status:
        proj, _rec_meta, status = load(conn)
        seg_eps = {r[0] for r in conn.execute(
            "SELECT DISTINCT episode_pid FROM segment_events")}
        bridged = _bridge_coverage(proj, seg_eps)
        mbid_links = len(proj) - bridged              # the 2012+ High half
        dual = _dual_lineage_track_count(conn)
        cov = (100.0 * mbid_links / dual) if dual else 0.0
        textonly = conn.execute(
            "SELECT COUNT(*) FROM tracks t WHERE t.episode_pid NOT IN "
            "(SELECT DISTINCT episode_pid FROM segment_events)").fetchone()[0]
        pct = (100.0 * bridged / textonly) if textonly else 0.0
        print(f"projection cache: {status}   ({len(proj):,} links)")
        print(f"  2012+ High:    {mbid_links:,} / {dual:,} dual-lineage tracks "
              f"({cov:.1f}%)")
        print(f"  pre-2012 bridge: {bridged:,} / {textonly:,} text-only airings "
              f"({pct:.1f}%)")
        return
    print("building projection (this runs the DP reconcile — ~6 min)...")
    proj, _ = build(conn)
    print(f"wrote {len(proj):,} High-confidence track->recording links to {PROJECTION_PATH}")
