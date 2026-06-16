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
    text_recs = B.text_recordings(conn, ctx)
    decisions = B.load_decisions()
    result = B.bridge(text_recs, pid_sigs, decisions)
    airings = B.airings_by_text_key(conn, ctx)
    return _expand_links(result.trusted, airings, key_of=B.text_recording_key)


# Files whose bytes feed the projection: the 2012+ matcher (ttn_mbid_audit +
# ttn_analyze's folding), and the pre-2012 bridge chain (ttn_bridge + its
# spine/credits/audit deps + the alias tables) and its accept/reject ledger.
_FINGERPRINT_FILES = (
    "ttn_project.py",                       # the projection-BUILD logic self-hashes
    "ttn_mbid_audit.py", "ttn_analyze.py",
    "ttn_bridge.py", "ttn_credits.py", "ttn_spine.py", "ttn_audit.py",
    "ttn_aliases.py", "ttn_bridge_decisions.json",
)

def _fingerprint(conn):
    """sha1 over the reconcile INPUTS (tracks + segment_events rows) plus the
    bytes of every file in _FINGERPRINT_FILES — the 2012+ matcher AND the
    pre-2012 bridge chain + its decisions ledger. A reparse, a segments
    re-derive, a matcher/fold/bridge/alias edit, or a ledger verdict
    invalidates the cache. Rows sorted for order-independence."""
    h = hashlib.sha1()
    for q in ("SELECT episode_pid, position, time_str, composer, title FROM tracks",
              "SELECT episode_pid, position, version_offset, composer_name, "
              "track_title, composer_mbid, recording_pid FROM segment_events"):
        for row in sorted(conn.execute(q), key=repr):
            h.update(repr(row).encode("utf-8"))
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
    conn = sqlite3.connect(a.db)
    if a.status:
        proj, status = load(conn)
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
    proj = build(conn)
    print(f"wrote {len(proj):,} High-confidence track->recording links to {PROJECTION_PATH}")
