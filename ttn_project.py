"""Recording-anchored identity projection (SP3): precompute the tracks->recording
mapping (ttn_mbid_audit.reconcile_corpus, High tier only) into a fingerprinted
cache that ttn_analyze --source auto consumes. ~6.6 min cold build,
sub-second load; rebuilt only when its inputs (tracks, segment_events, the
matcher) change. Derived/offline; the cache is gitignored.
See docs/superpowers/specs/2026-06-09-identity-substrate-design.md."""
import argparse, hashlib, json, os, sqlite3

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

def build_projection(conn):
    """Run the DP reconcile over the corpus, keep the High matches. ~6.6 min."""
    from ttn_mbid_audit import reconcile_corpus
    return projection_from_matches(reconcile_corpus(conn))

def _fingerprint(conn):
    """sha1 over the reconcile INPUTS — the tracks + segment_events rows the
    matcher reads — plus the bytes of ttn_mbid_audit.py (the matcher itself).
    A reparse, a segments re-derive, or a matcher edit invalidates the cache.
    Rows sorted for order-independence (mirrors ttn_analyze's summary cache)."""
    h = hashlib.sha1()
    for q in ("SELECT episode_pid, position, time_str, composer, title FROM tracks",
              "SELECT episode_pid, position, version_offset, composer_name, "
              "track_title, composer_mbid, recording_pid FROM segment_events"):
        for row in sorted(conn.execute(q), key=repr):
            h.update(repr(row).encode("utf-8"))
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "ttn_mbid_audit.py"), "rb") as fh:
            h.update(fh.read())
    except OSError:
        return ""
    return h.hexdigest()

def _write_cache(path, projection, fingerprint):
    data = {"fingerprint": fingerprint,
            "projection": {f"{ep}\t{pos}": rp for (ep, pos), rp in projection.items()}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)

def _has_table(conn, name):
    """True iff `name` is a table in this connection. Used to treat a DB with
    no segment lineage as 'missing projection' rather than erroring."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None

def load(conn, path=PROJECTION_PATH):
    """Return (projection_dict, status). status: 'ok' | 'missing' | 'stale'.
    Never builds — staleness is the caller's cue to run `ttn_project.py`. A DB
    lacking the tracks/segment_events lineage is reported 'missing' (no
    projection is possible), not an error."""
    if not (_has_table(conn, "tracks") and _has_table(conn, "segment_events")):
        return {}, "missing"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}, "missing"
    if data.get("fingerprint") != _fingerprint(conn):
        return {}, "stale"
    proj = {}
    for k, rp in data["projection"].items():
        ep, pos = k.split("\t")
        proj[(ep, int(pos))] = rp
    return proj, "ok"

def build(conn, path=PROJECTION_PATH):
    """Build the projection and write the fingerprinted cache. The slow path."""
    proj = build_projection(conn)
    _write_cache(path, proj, _fingerprint(conn))
    return proj

def ensure(conn, path=PROJECTION_PATH):
    """Make-current entry point (ttn_warm calls it): return (projection, 'ok'),
    building the cache first if load reports it missing or stale. Returns
    ({}, 'missing') WITHOUT building when there's no segment lineage to project."""
    proj, status = load(conn, path)
    if status == "ok":
        return proj, "ok"
    if not (_has_table(conn, "tracks") and _has_table(conn, "segment_events")):
        return {}, "missing"
    return build(conn, path), "ok"

def _dual_lineage_track_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid IN "
        "(SELECT DISTINCT episode_pid FROM segment_events)").fetchone()[0]

def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the recording-anchored projection cache (SP3).")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--status", action="store_true",
                    help="report cache status + coverage; writes nothing")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.db)
    if a.status:
        proj, status = load(conn)
        dual = _dual_lineage_track_count(conn)
        cov = (100.0 * len(proj) / dual) if dual else 0.0
        print(f"projection cache: {status}")
        print(f"  links: {len(proj):,}   dual-lineage tracks: {dual:,}   "
              f"High coverage: {cov:.1f}%")
        return
    print("building projection (this runs the DP reconcile — ~6 min)...")
    proj = build(conn)
    print(f"wrote {len(proj):,} High-confidence track->recording links to {PROJECTION_PATH}")

if __name__ == "__main__":
    main()
