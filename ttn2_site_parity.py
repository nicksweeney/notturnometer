"""ttn2_site_parity — P4 gate: site.sqlite (legacy) vs site2.sqlite
(successor), table by table, with ledger-derived expected-diff
classification (docs/successor-events-framework.md §6).

A diff is EXPECTED iff its identity keys intersect the ledger delta (the
de-globalization key set computed exactly as ttn2_parity's identity check),
or it carries an exception token: the ratified ledger kind='link' rows'
resolved recording pids + link episode pids, PLUS both sides' recording pids
of any presentation-map diff at a link episode. All linkage/presentation
differences at the ratified EBU-anomaly positions are EXPECTED — they are
the same artifact class the link rows ratify (the DP cascade changes which
matches land at medium tier, shifting the (episode_pid, position) ->
recording_pid map at those positions; both sides show a real airing of the
episode, only the linked recording differs).
Anything else is UNEXPECTED and blocks cutover.

Run: uv run python ttn2_site_parity.py [--force] [--build]
  default    build either site DB that is missing or fingerprint-stale,
             then diff
  --build    synonym of the default (build-then-diff)
  --force    rebuild BOTH site DBs unconditionally, then diff
Writes scratch/p4-site-parity.json; exit 1 on UNEXPECTED diffs.
"""
import json
import os
import sqlite3
import sys
from collections import Counter

import ttn2_ledger as L
import ttn2_parity as TP
import ttn2_site as T2
import ttn_project as P
import ttn_work_recordings as WR
import ttn_site

DB = "ttn.sqlite"
SUCCESSOR = "successor.sqlite"
LEGACY_SITE = "site.sqlite"
SITE2 = "site2.sqlite"
REPORT_PATH = "scratch/p4-site-parity.json"

# Every content table in the site schema (browse included -- the brief's
# TABLES snippet omitted it; its own step-3 text diffs it). meta is stamped
# per build (built_at always differs) and is never diffed.
TABLES = ["works", "composers", "episodes", "recordings", "years",
          "broadcasters", "forms", "artists", "countries", "browse"]


def load_table(conn, table):
    cur = conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def classify(old_rows, new_rows, delta_keys, key_extractors,
             pk_extractors=None, exception_rps=frozenset()):
    """Per-table keyed diff -> {'expected': [...], 'unexpected': [...]}.
    delta_keys: set of (composer_key, work_key) tuples from the ledger delta.
    key_extractors: table -> callable(row_dict) -> LIST of identity keys to
    test (a row is expected-diff iff ANY extracted key is in delta_keys).
    Rows with no identity reference (empty key list) are UNEXPECTED on any
    diff. pk_extractors: table -> callable(row_dict) -> the row's stable
    primary key, so the same logical row on both sides pairs into ONE
    'changed' entry carrying old AND new (the schema PKs; default = full-row
    JSON, the brief's pairing). 'key' reports the primary key.
    exception_rps: ratified-link tokens (the ledger kind='link' rows'
    resolved recording pids PLUS the link episodes' pids) — a diff is
    EXPECTED when any token appears in the serialized old or new row (the
    human-ratified EBU-order links' facet ripple). Default empty = existing
    behavior."""
    expected, unexpected = [], []
    pk_of_default = lambda r: json.dumps(r, sort_keys=True)  # noqa: E731
    for table, extract in key_extractors.items():
        pk_of = (pk_extractors or {}).get(table, pk_of_default)
        old, new = {}, {}
        for r in old_rows.get(table, []):
            old[pk_of(r)] = r
        for r in new_rows.get(table, []):
            new[pk_of(r)] = r
        for k in set(old) | set(new):
            if old.get(k) == new.get(k):
                continue
            row = old.get(k) if old.get(k) is not None else new.get(k)
            keys = extract(row)
            side = "old-only" if k not in new else (
                "new-only" if k not in old else "changed")
            blob = (json.dumps([old.get(k), new.get(k)], default=str)
                    if exception_rps else None)
            hit = (any(kk in delta_keys for kk in keys)
                   or (blob is not None
                       and any(tok in blob for tok in exception_rps)))
            bucket = expected if hit else unexpected
            bucket.append({"table": table, "key": k, "side": side,
                           "old": old.get(k), "new": new.get(k)})
    return {"expected": expected, "unexpected": unexpected}


def presentation_diff_rps(succ_pres, legacy_pres, link_eps):
    """Presentation-map diffs at the ratified link episodes:
    {(ep, pos): (succ_rp, legacy_rp)} wherever the successor's presentation
    map disagrees with the legacy projection's at a link episode. The same
    ratified EBU-anomaly class as the link rows themselves (the DP cascade
    changes which matches land at medium tier, shifting which recording a
    position links) -- each side shows a real airing of the position, only
    the linked recording differs. Both sides' rps join the exception set."""
    return {k: (succ_pres.get(k), legacy_pres.get(k))
            for k in set(succ_pres) | set(legacy_pres)
            if k[0] in link_eps and succ_pres.get(k) != legacy_pres.get(k)}


def compute_delta_keys(src=DB, dst=SUCCESSOR):
    """The (composer_key, work_key) multiset delta between the current
    pipeline (aliases + FULL projection: 2012+ DP half + trusted bridge) and
    the successor ledger resolution -- exactly ttn2_parity's identity check
    (both sides through the full legacy chain: strip_arranger_tail with the
    row's composer_line + normalize_composer before resolution, ruling
    2026-08-29; the shared implementations are ttn2_parity.current_identity
    and ttn2_site._identity_of), returning the differing keys instead of
    counting them. These keys are what classifies site diffs as EXPECTED
    (the de-globalization conversions: bare-generic folds scoped to their
    dominant composer)."""
    comp, ws, wg = L.load_maps(dst)
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    projection, rec_meta, status = P.load(conn)
    assert status == "ok", "projection cache must be fresh for parity"
    s2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    ev_rp = {eid: rp for eid, rp in s2.execute(
        "SELECT id, recording_pid FROM event "
        "WHERE method IN ('recording_pid','bridge') "
        "AND recording_pid IS NOT NULL")}

    def identity(cm, tt, cl, side):
        if side == "cur":
            return TP.current_identity(cm, tt, cl)
        return T2._identity_of(cm, tt, comp, ws, wg, composer_line=cl)

    cur_ms, succ_ms = Counter(), Counter()
    for ep, pos, _date, t, c, cl in WR._fetch_rows(conn):
        rp = projection.get((ep, pos))
        if rp is not None and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = c or "", t or ""
        cur_ms[identity(cm, tt, cl, "cur")] += 1
    for _oid, _ep, _ordv, _date10, comp_raw, title, cl, eid in s2.execute(
            "SELECT id, episode_pid, ord, date10, composer_raw, title, "
            "composer_line, event_id FROM obs WHERE source='text'"):
        rp = ev_rp.get(eid)
        if rp is not None and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = comp_raw or "", title or ""
        succ_ms[identity(cm, tt, cl, "succ")] += 1
    s2.close()
    conn.close()
    return {k for k in set(cur_ms) | set(succ_ms)
            if cur_ms.get(k, 0) != succ_ms.get(k, 0)}, cur_ms, succ_ms


def build_indexes(old_rows, new_rows):
    """Slug indexes over BOTH sides' works/composers tables, so extractors
    can resolve identity references in any table's payloads. work_ix: work
    slug -> (composer_key, work_key); comp_ix: composer slug -> the work
    keys of that composer's works_json (for composer-only payload
    references, e.g. years' top_composers entries)."""
    work_ix, comp_ix = {}, {}
    for rows in (old_rows.get("works", []), new_rows.get("works", [])):
        for r in rows:
            if r.get("composer_key") is not None or r.get("work_key") is not None:
                work_ix[r.get("slug")] = (r.get("composer_key"),
                                          r.get("work_key"))
    for rows in (old_rows.get("composers", []), new_rows.get("composers", [])):
        for r in rows:
            slugs = r.get("slug")
            if not slugs:
                continue
            keys = set()
            try:
                entries = json.loads(r.get("works_json") or "[]")
            except ValueError:
                entries = []
            for w in entries:
                k = work_ix.get(w.get("slug")) if isinstance(w, dict) else None
                if k is not None:
                    keys.add(k)
            if keys:
                comp_ix.setdefault(slugs, set()).update(keys)
    return work_ix, comp_ix


def _identity_keys(row, work_ix, comp_ix):
    """(composer_key, work_key) keys referenced anywhere in a row's columns
    or JSON payloads. Every string value is looked up exactly in work_ix
    then comp_ix -- slugs are structurally distinctive (kebab/colon forms),
    so exact-match collisions with display text do not occur in practice."""
    keys = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            k = work_ix.get(v)
            if k is not None:
                keys.add(k)
            else:
                cks = comp_ix.get(v)
                if cks:
                    keys.update(cks)

    for v in row.values():
        if isinstance(v, str) and v[:1] in "[{":
            try:
                walk(json.loads(v))
            except ValueError:
                pass
        else:
            walk(v)
    return keys


def make_extractors(work_ix, comp_ix):
    """table -> row_dict -> list of identity keys. works reads its
    composer_key/work_key columns directly; every other table walks the
    row's payloads (the generic extractor), so rows with no identity
    reference return [] and classify as UNEXPECTED on any diff."""
    def works(r):
        k = (r.get("composer_key"), r.get("work_key"))
        return [k] if any(k) else []

    def generic(r):
        return list(_identity_keys(r, work_ix, comp_ix))

    return {t: (works if t == "works" else generic) for t in TABLES}


def make_pk_extractors():
    """table -> row_dict -> the row's stable primary key (the schema PKs) so
    classify pairs same-identity rows into 'changed' entries."""
    pks = {"works": lambda r: r.get("slug"),
           "composers": lambda r: r.get("slug"),
           "episodes": lambda r: r.get("pid"),
           "recordings": lambda r: r.get("recording_pid"),
           "years": lambda r: r.get("year"),
           "broadcasters": lambda r: r.get("slug"),
           "forms": lambda r: r.get("slug"),
           "artists": lambda r: r.get("slug"),
           "countries": lambda r: r.get("slug"),
           "browse": lambda r: r.get("name")}
    assert set(pks) == set(TABLES)
    return pks


def _ensure_site_db(out_path, force, source, db_path, registry_path,
                    artist_reg_path):
    """Build out_path via _run_build when missing/stale (or --force).
    Freshness comes from the site DB's own fingerprint slot list; a parity
    gate comparing stale sides is meaningless, so stale ALWAYS rebuilds."""
    if source == "successor":
        fp = ttn_site.site_fingerprint_t2(registry_path, artist_reg_path,
                                          db_path=db_path)
    else:
        fp = ttn_site.site_fingerprint(registry_path, artist_reg_path)
    status = ttn_site.site_status(out_path, fp)
    if status == "fresh" and not force:
        print(f"ttn2_site_parity: {out_path} fresh -- skipping")
        return
    print(f"ttn2_site_parity: building {out_path} "
          f"(source={source}, was {status})...")
    ttn_site._run_build(db_path, registry_path, out_path, force=True,
                        source=source)


def _ripple_shape(e):
    """True when the unexpected row is aggregate-ripple-shaped: present on
    both sides (side == 'changed') with unchanged composer_key/work_key
    identity columns. Rows without those columns (browse rollups, episodes,
    recordings) are ripple when 'changed' -- their diff is count/facet
    churn; a row present on one side only is an identity-level diff."""
    if e.get("side") != "changed":
        return False
    old, new = e.get("old"), e.get("new")
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    return (old.get("composer_key") == new.get("composer_key")
            and old.get("work_key") == new.get("work_key"))


def shadow_verdict(report_path, parked_path):
    """The shadow-window green check (P4 phase 3, task 4): classify the
    parity report's unexpected rows against the parked aggregate-ripple
    snapshot + the ripple-class shape rule.

    Returns (green, new_unexpected): green = no unexpected row OUTSIDE the
    aggregate-ripple class; new_unexpected = the rows that are neither
    known-parked nor ripple-shaped (the identity-level diffs that block the
    flip).

    Ripple class (maintainer ruling 2026-09-02, superseding the exact-
    equality criterion): an unexpected row whose identity is unchanged on
    both sides -- side == 'changed' (the row's slug/pid exists on both
    sides) with unchanged composer_key/work_key columns -- and whose diff is
    confined to count/facet churn (airings, works_json membership at rank
    boundaries, facets_json, by_year, rollup aggregates). RED = any
    identity-level diff: a row present on one side only (new-only/missing),
    or a changed composer_key/work_key identity mapping."""
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    with open(parked_path, encoding="utf-8") as fh:
        parked = json.load(fh)
    parked_pairs = {(e["table"], e["key"])
                    for e in parked.get("unexpected", [])}
    new_unexpected = [
        e for e in report.get("unexpected", [])
        if (e["table"], e["key"]) not in parked_pairs and not _ripple_shape(e)]
    return (not new_unexpected), new_unexpected


def main(argv=None):
    force = "--force" in (argv if argv is not None else sys.argv[1:])
    build = "--build" in (argv if argv is not None else sys.argv[1:])
    registry_path = ttn_site.REGISTRY_PATH
    artist_reg_path = ttn_site.artist_registry_path()

    delta, cur_ms, succ_ms = compute_delta_keys(DB, SUCCESSOR)
    print(f"ttn2_site_parity: ledger delta {len(delta)} identity keys "
          f"({sum(cur_ms.values())} vs {sum(succ_ms.values())} airings)")

    # Ratified ledger link rows (kind='link'): their resolved rps AND their
    # episodes' pids make a diff EXPECTED (the EBU-ordering artifact's facet
    # ripple is human-ratified, not a delta key).
    links = L.load_link_rows(SUCCESSOR)
    exception_rps = set(rp for _ep, _pos, rp in links) | set(
        ep for ep, _pos, _rp in links)
    # Presentation-map diffs at the link episodes: the same ratified
    # EBU-anomaly class (see presentation_diff_rps).
    s2 = sqlite3.connect(f"file:{SUCCESSOR}?mode=ro", uri=True)
    succ_pres = {(ep, int(float(ordv))): rp for ep, ordv, rp in s2.execute(
        "SELECT episode_pid, ord, recording_pid FROM presentation")}
    s2.close()
    legacy_pres = P.load_presentation()
    link_eps = {ep for ep, _pos, _rp in links}
    pres_diffs = presentation_diff_rps(succ_pres, legacy_pres, link_eps)
    exception_rps |= {rp for pair in pres_diffs.values() for rp in pair if rp}
    exception_rps = frozenset(exception_rps)
    print(f"ttn2_site_parity: {len(links)} ratified ledger link rows, "
          f"{len(pres_diffs)} presentation diffs at link episodes "
          f"({len(exception_rps)} exception tokens)")

    _ensure_site_db(LEGACY_SITE, force, "legacy", DB, registry_path,
                    artist_reg_path)
    _ensure_site_db(SITE2, force or build, "successor", DB, registry_path,
                    artist_reg_path)

    old_c = sqlite3.connect(f"file:{LEGACY_SITE}?mode=ro", uri=True)
    new_c = sqlite3.connect(f"file:{SITE2}?mode=ro", uri=True)
    try:
        old_rows = {t: load_table(old_c, t) for t in TABLES}
        new_rows = {t: load_table(new_c, t) for t in TABLES}
    finally:
        old_c.close()
        new_c.close()

    work_ix, comp_ix = build_indexes(old_rows, new_rows)
    report = classify(old_rows, new_rows, delta,
                      make_extractors(work_ix, comp_ix),
                      pk_extractors=make_pk_extractors(),
                      exception_rps=exception_rps)

    per_table = {}
    for t in TABLES:
        exp = [e for e in report["expected"] if e["table"] == t]
        unexp = [e for e in report["unexpected"] if e["table"] == t]
        per_table[t] = {"rows_old": len(old_rows[t]), "rows_new": len(new_rows[t]),
                        "expected": len(exp), "unexpected": len(unexp)}
        print(f"  {t:12s} {len(old_rows[t]):6d}/{len(new_rows[t]):<6d} rows  "
              f"expected {len(exp):5d}  unexpected {len(unexp)}")

    os.makedirs("scratch", exist_ok=True)
    doc = {
        "delta_keys": sorted(list(k) for k in delta),
        "delta_key_count": len(delta),
        "per_table": per_table,
        # Expected diffs are the gate's background noise (counts above);
        # only the unexpected entries carry full rows for debugging.
        "expected": [{"table": e["table"], "key": e["key"],
                      "side": e["side"]} for e in report["expected"]],
        "unexpected": [{"table": e["table"], "key": e["key"],
                        "side": e["side"], "old": e["old"], "new": e["new"]}
                       for e in report["unexpected"]],
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    print(f"ttn2_site_parity: report written -- {REPORT_PATH}")

    unexpected = report["unexpected"]
    if unexpected:
        print(f"ttn2_site_parity: UNEXPECTED diffs: {len(unexpected)} "
              f"(first 10):")
        for e in unexpected[:10]:
            print(f"  {e['table']} {e['key']} [{e['side']}]")
        print("parity verdict: FAIL -- diffs outside the ledger delta block "
              "cutover")
        return 1
    print("parity verdict: PASS -- every diff is ledger-explained (EXPECTED)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
