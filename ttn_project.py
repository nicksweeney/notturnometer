"""Recording-anchored identity projection (SP3): precompute the tracks->recording
mapping (ttn_mbid_audit.reconcile_corpus, High tier only) plus the
recording->clean-identity rec_meta into one fingerprinted cache that
ttn_analyze --source auto consumes. Slow cold build, sub-second load;
rebuilt only when its inputs (tracks, segment_events, the matcher) change.
Derived/offline; the cache is gitignored.
See docs/superpowers/specs/2026-06-09-identity-substrate-design.md."""
import argparse, hashlib, json, os

from ttn_db import open_db

PROJECTION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "ttn_projection_cache.json")

RECORDING_DECISIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "ttn_recording_decisions.json")

def load_recording_decisions(path=RECORDING_DECISIONS_PATH):
    """Load and validate the recording-equivalence ledger: a tracked JSON of
    explicit staff decisions mapping non-canonical BBC recording PIDs to their
    preferred terminal PID. Returns {non_canonical_pid: terminal_pid}.

    Rejects a malformed shape, non-string PID values, self-links, and cycles
    with a ValueError. Absence is stable (returns {}) — like the bridge ledger,
    a missing file is not an error, just no equivalences."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"recording decisions ledger {path} is corrupt: {e}")
    if not isinstance(data, dict) or "aliases" not in data:
        raise ValueError(f"recording decisions ledger {path} has wrong shape")
    aliases = data["aliases"]
    if not isinstance(aliases, dict):
        raise ValueError(f"recording decisions ledger {path}: 'aliases' must be an object")
    for k, v in aliases.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(f"recording decisions ledger {path}: PIDs must be strings")
        if k == v:
            raise ValueError(f"recording decisions ledger {path}: self-link {k!r}")
    # cycle detection over the whole map (a cycle would hang resolve)
    for start in aliases:
        seen = set()
        cur = start
        while cur in aliases:
            if cur in seen:
                raise ValueError(f"recording decisions ledger {path}: cycle at {start!r}")
            seen.add(cur)
            cur = aliases[cur]
    return dict(aliases)

def resolve_recording_pid(pid, aliases):
    """Return the terminal canonical PID for `pid`, following multi-hop aliases
    to a terminal PID. A PID absent from `aliases` resolves to itself. Does not
    mutate `aliases`. `aliases` is the dict from load_recording_decisions
    (None/empty -> identity)."""
    if not aliases:
        return pid
    seen = set()
    cur = pid
    while cur in aliases:
        if cur in seen:
            break                      # cycle guard (load rejects cycles)
        seen.add(cur)
        cur = aliases[cur]
    return cur

def load_recording_rationale(path=RECORDING_DECISIONS_PATH):
    """Return {non_canonical_pid: rationale_string} from the ledger's optional
    'rationale' map — the concise reviewed evidence for each approved alias.
    Missing file or missing map -> {} (stable, like the aliases loader). A
    rationale entry that isn't a string-valued map is ignored rather than
    raising, so a partial/odd ledger still loads its aliases."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict) or "rationale" not in data:
        return {}
    r = data["rationale"]
    if not isinstance(r, dict):
        return {}
    return {k: v for k, v in r.items() if isinstance(k, str) and isinstance(v, str)}

def validate_recording_aliases(aliases, conn):
    """During a REAL projection build, ensure every alias target (the resolved
    terminal PID) is an actual recording_pid in segment_events — but ONLY for
    aliases whose SOURCE PID is itself present in segment_events. An alias whose
    source PID is absent from this DB is irrelevant to it (the recording was
    never ingested here), so it must not fail the build: a synthetic test DB or
    a partial corpus must not be rejected for a ledger entry that doesn't apply
    to it. A target that does not exist while its source DOES is a typo / stale
    decision and must be rejected, so airings are never canonicalized onto a
    phantom recording.

    Deliberately NOT called by the pure resolver functions
    (resolve_recording_pid / projection_from_matches / build_rec_meta): those
    take synthetic aliases in isolated unit tests and must not require a real
    DB. Validation lives only on the build() path, so the unit tests using
    synthetic IDs are unaffected."""
    known = {r[0] for r in conn.execute(
        "SELECT DISTINCT recording_pid FROM segment_events "
        "WHERE recording_pid IS NOT NULL")}
    for k, v in aliases.items():
        if k not in known:
            continue                      # source absent -> irrelevant to this DB
        target = resolve_recording_pid(v, aliases)   # terminal of the target
        if target not in known:
            raise ValueError(
                f"recording alias {k!r} -> {v!r} targets unknown recording "
                f"PID {target!r} (not present in segment_events)")
    return True

def projection_from_matches(matches, aliases=None):
    """{(episode_pid, track_position): recording_pid} for High-tier matches only.
    Pure — the High gate + keying, independent of the DP matcher. Recording PIDs
    are normalized to their canonical terminal PID via `aliases` (the
    recording-equivalence ledger) when supplied."""
    out = {}
    for m in matches:
        if m.get("tier") == "high" and m.get("recording_pid"):
            rp = resolve_recording_pid(m["recording_pid"], aliases)
            out[(m["episode_pid"], m["track_position"])] = rp
    return out

def presentation_from_matches(matches, aliases=None):
    """{(episode_pid, track_position): recording_pid} for MEDIUM-tier matches.

    The PRESENTATION half of graduated trust. A medium match means the DP is
    confident the track and the segment are the same AIRING but one
    corroborating signal disagreed — nearly always the composer NAME. Measured
    over the whole corpus 2026-07-21: of the 1,178 medium-tier recordings the
    site currently cannot show, 702 (60%) disagree only because the segment's
    composer_name holds a PERFORMER ('Mozart' vs 'Martha Argerich'), and fewer
    than ~10 are genuinely mis-aligned. See the classification pass under
    docs/superpowers/plans/2026-07-21-medium-tier-classification-pass.md.

    That is ample to say 'these are the musicians' and deliberately NOT enough
    to say what the work IS — so this map never reaches grouping, keying or any
    ranking. Identity stays High-only (projection_from_matches). Key-space is
    disjoint from the projection by construction: a track has ONE match, so it
    is either high or medium, never both.

    Pure — the Medium gate + keying, independent of the DP matcher."""
    out = {}
    for m in matches:
        if m.get("tier") == "medium" and m.get("recording_pid"):
            rp = resolve_recording_pid(m["recording_pid"], aliases)
            out[(m["episode_pid"], m["track_position"])] = rp
    return out

def build_projections_mbid(conn, aliases=None):
    """One DP reconcile -> (High projection, Medium presentation links). The
    reconcile is the ~5-min half of a warm, so both tiers come out of a SINGLE
    pass — never call the two builders separately."""
    from ttn_mbid_audit import reconcile_corpus
    matches = reconcile_corpus(conn)
    return projection_from_matches(matches, aliases), presentation_from_matches(matches, aliases)

def build_projection_mbid(conn, aliases=None):
    """The 2012+ DP reconcile, High matches only. ~6.6 min."""
    return build_projections_mbid(conn, aliases)[0]

def build_projection(conn, aliases=None):
    """The full projection: 2012+ MBID High matches merged with the pre-2012
    trusted bridge links. The key-spaces are disjoint (2012+ episodes carry
    segments -> MBID path; text-only episodes -> bridge path), so update() is
    safe. The slow path (DP reconcile + spine/bridge build)."""
    proj, _ = build_projections(conn, aliases)
    return proj

def build_projections(conn, aliases=None):
    """(full projection, presentation links) from one DP reconcile. The
    presentation half is 2012+ only — a pre-2012 text-only airing reaches its
    recording through the bridge, which has its own trusted/candidate tiers and
    no notion of a DP tier."""
    proj, pres = build_projections_mbid(conn, aliases)
    proj.update(bridge_projection(conn, aliases))
    return proj, pres


def build_rec_meta(conn, aliases=None):
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
    an override rebuilds the cache. RECORDING_TITLE_OVERRIDES is applied the same
    way for the rarer case where the segment TITLE is the defect (a bare/opus-
    less title on a recording dedicated to one work) — composer-implicitly-
    scoped, so it carries no work-alias blast radius.

    sanitize_segment_title then strips leaked BBC QC markers (EXPIRED / AVOID /
    DO NOT USE / DON'T USE, only as a clean affix) from whatever title survives
    the override — a corpus-wide cleanup, not a per-recording correction, so it
    needs no allowlist. Applied AFTER the override (overrides are already clean,
    so it is a no-op there)."""
    from ttn_segment_meta import (RECORDING_COMPOSER_OVERRIDES as comp_over,
                                    RECORDING_TITLE_OVERRIDES as title_over,
                                    sanitize_segment_title)
    # ORDER BY recording_pid, composer_name, track_title makes the scan a total
    # order over the selected columns, so when several raw rows share one
    # canonical PID the two-pass collapse below picks the SAME metadata
    # regardless of insertion/scan order (a bare ORDER BY recording_pid leaves
    # the within-PID order undefined, which made rec_meta non-deterministic).
    rows = list(conn.execute(
        "SELECT recording_pid, composer_name, track_title FROM segment_events "
        "WHERE recording_pid IS NOT NULL AND track_title IS NOT NULL "
        "AND track_title != '' ORDER BY recording_pid, composer_name, track_title"))
    rec_meta = {}
    # Pass 1: when aliases collapse several raw PIDs onto one terminal PID,
    # prefer the metadata carried by the row whose raw recording_pid IS that
    # canonical terminal (e.g. p01yzj4c's own segment over the aliased
    # p0gg1wdd's), so a stale non-canonical row can never shadow the reviewed
    # recording's clean identity.
    for rp, cn, tt in rows:
        crp = resolve_recording_pid(rp, aliases)
        if rp == crp and crp not in rec_meta:
            rec_meta[crp] = (comp_over.get(rp, cn),
                             sanitize_segment_title(title_over.get(rp, tt)))
    # Pass 2: fill any terminal PID that has no canonical-source row (only
    # reached via aliases) with the first available non-canonical row.
    for rp, cn, tt in rows:
        crp = resolve_recording_pid(rp, aliases)
        if crp not in rec_meta:
            rec_meta[crp] = (comp_over.get(rp, cn),
                             sanitize_segment_title(title_over.get(rp, tt)))
    return rec_meta


def _expand_links(links, airings, *, key_of, aliases=None):
    """Pure: {(episode_pid, position): recording_pid} from TRUSTED links only.
    `key_of(link.text_rec)` -> the airing-map key; `airings` maps that key to
    the airing list. v1 ingests link.tier == 'trusted' (auto); 'accepted'
    (ledger-promoted candidates) is deferred to v2. Recording PIDs are
    normalized to their canonical terminal PID via `aliases` when supplied."""
    out = {}
    for lk in links:
        if lk.tier != "trusted":
            continue
        rp = resolve_recording_pid(lk.pid_sig.recording_pid, aliases)
        for ep_pos in airings.get(key_of(lk.text_rec), []):
            out[ep_pos] = rp
    return out


def bridge_projection(conn, aliases=None):
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
    return _expand_links(result.trusted, airings, key_of=B.text_recording_key,
                          aliases=aliases)


# Files whose bytes feed the projection: the 2012+ matcher (ttn_mbid_audit +
# ttn_analyze's folding), and the pre-2012 bridge chain (ttn_bridge + its
# spine/credits/audit deps + the alias tables) and its accept/reject ledger.
_FINGERPRINT_FILES = (
    "ttn_project.py",                       # the projection-BUILD logic self-hashes
    "ttn_mbid_audit.py", "ttn_analyze.py",
    "ttn_bridge.py", "ttn_credits.py", "ttn_spine.py", "ttn_audit.py",
    "ttn_aliases.py", "ttn_bridge_decisions.json",
    "ttn_recording_decisions.json",         # recording-equivalence ledger
    "ttn_segment_meta.py",                  # RECORDING_COMPOSER_OVERRIDES feeds rec_meta
)

def _db_realpath(conn):
    """The resolved filesystem path behind `conn`, or '' when there is none
    (in-memory/temp DBs)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    return row[2] if row else ""


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
    to checkpoints).

    Path binding is deliberately COMPARE-ONLY: the returned marker carries a
    path-hash prefix, not the raw path. A raw path in the marker made load()
    re-stamp a pulled cache with the local absolute path on first read,
    rewriting bytes that should be host-invariant -- which invalidated the
    slug cache fingerprinted over the projection file's bytes (the
    2026-08-22 cross-host mirror lesson: identical data, three-byte path
    difference, every subsequent fingerprint mismatched)."""
    path = _db_realpath(conn)
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
    identity = hashlib.sha1(os.path.realpath(path).encode("utf-8",
                                                          "surrogateescape"))
    return [int.from_bytes(header[24:28], "big"), size,
            identity.hexdigest()[:16]]

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
        # the recording ledger is read from its canonical path (not here/mod),
        # so tests can repoint it at a temp file to prove fingerprint sensitivity
        path = (RECORDING_DECISIONS_PATH if mod == "ttn_recording_decisions.json"
                else os.path.join(here, mod))
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            if mod in ("ttn_bridge_decisions.json", "ttn_recording_decisions.json"):
                continue            # ledger may not exist yet; absence is stable
            return ""
    return h.hexdigest()

def _write_cache(path, projection, fingerprint, rows_sha=None, db_marker=None,
                 rec_meta=None, presentation=None):
    data = {"fingerprint": fingerprint,
            "rows_sha": rows_sha, "db_marker": db_marker,
            "projection": {f"{ep}\t{pos}": rp for (ep, pos), rp in projection.items()},
            "presentation": {f"{ep}\t{pos}": rp
                             for (ep, pos), rp in (presentation or {}).items()},
            "rec_meta": {rp: list(ct) for rp, ct in (rec_meta or {}).items()}}
    _atomic_json_dump(path, data)


def _atomic_json_dump(path, data):
    """Write JSON via tmp-file + os.replace so an interrupted write (killed
    warm, power loss) can never leave a TRUNCATED cache at the real path —
    the reader sees either the old complete file or the new complete file.
    Matters doubly for load()'s re-stamp, which rewrites a GOOD cache on a
    routine fast-path miss. The tmp name is pid-unique: a FIXED name lets
    two concurrent writers share one tmp file, so writer A can os.replace a
    half-written B document (the 2026-07-19 registry-corruption lesson)."""
    tmp = f"{path}.{os.getpid()}.tmp"
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
        # NEVER re-stamp across an IDENTITY change (the path-hash component):
        # a pulled cache read on another host would otherwise be rewritten
        # with local-path noise, mutating bytes that other caches fingerprint
        # over -- the 2026-08-22 cross-host lesson. Cross-host reads just pay
        # the rescan every time; the file stays pristine.
        stored = data.get("db_marker")
        # Identity match rules: hash-form markers compare component [2];
        # a LEGACY raw-path marker (a str) is treated as same-identity when
        # it equals this host's realpath, so pre-fix caches still re-stamp
        # normally on the host that wrote them. A legacy marker for a
        # DIFFERENT path (pulled from elsewhere) is foreign: no re-stamp.
        if isinstance(stored, list) and len(stored) == 3:
            same_identity = stored[2] == marker[2]
        elif isinstance(stored, str):
            same_identity = stored == _db_realpath(conn)
        else:
            same_identity = False
        if same_identity:
            data.update(rows_sha=rows_sha, db_marker=marker)
            try:
                _atomic_json_dump(path, data)      # never truncate a good cache
            except OSError:
                pass
    proj = {}
    for k, rp in data["projection"].items():
        ep, pos = k.split("\t")
        proj[(ep, int(pos))] = rp
    rec_meta = {rp: tuple(ct) for rp, ct in data.get("rec_meta", {}).items()}
    return proj, rec_meta, "ok"

def load_presentation(path=PROJECTION_PATH):
    """The MEDIUM-tier presentation links from the cache, or {} if this cache
    predates them / is absent / is corrupt.

    Deliberately NOT part of load()'s return tuple: load() is monkeypatched as
    a 3-tuple in a lot of places and its arity is a contract. Deliberately does
    NOT re-validate the fingerprint either — that costs a row scan, and the
    only caller (the site build) has already taken load()'s 'ok'. Call it only
    after load() reports 'ok'; on anything else it is meaningless, not wrong.

    Degrades to {} on every failure, like every derived cache: an older cache
    with no 'presentation' key simply shows what it showed before."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, rp in (data.get("presentation") or {}).items():
        ep, _, pos = k.partition("\t")
        if pos.isdigit():
            out[(ep, int(pos))] = rp
    return out

def build(conn, path=PROJECTION_PATH):
    """Build the projection + rec_meta and write the fingerprinted cache. The
    slow path. The fingerprint, DB marker and rec_meta are all taken BEFORE
    the ~10-min build so they describe the inputs the projection was actually
    built from — a mid-build DB change then reads as stale on the next load
    instead of silently fresh."""
    marker = _db_marker(conn)
    rows_sha = _rows_sha(conn)
    fp = _fingerprint(conn, rows_sha)
    aliases = load_recording_decisions()
    validate_recording_aliases(aliases, conn)   # reject typo targets before publishing
    rec_meta = build_rec_meta(conn, aliases)
    proj, pres = build_projections(conn, aliases)
    _write_cache(path, proj, fp, rows_sha, marker, rec_meta, pres)
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
