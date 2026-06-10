#!/usr/bin/env python3
"""Warm ttn_analyze's cache for every slot — the whole-corpus summary and
each broadcast year.

The summary cache (ttn_summary_cache.json) is multi-slot and self-keyed on a
hash of the rows plus the bytes of ttn_analyze.py and ttn_aliases.py, so
editing an alias table or extending the scrape silently invalidates it (no
manual cache invalidation is ever needed).
Warming it used to be a hand-typed shell loop with a hardcoded year range
(`for y in $(seq 2016 2026)`), which both pays Python start-up 12× and rots
as the scrape extends. This rebuilds every slot in one process and derives
the year span from the DB, so it never drifts.

Sequential by design: all slots write the one cache file, so naive
parallelism would race the writes; the cold cost (~50s corpus + ~2s/year)
isn't worth a multiprocessing dance for a maintenance task run by hand.

    uv run ttn_warm.py                 # warm ttn.sqlite
    uv run ttn_warm.py /tmp/other.db
"""
import argparse
import sqlite3
import time

import ttn_analyze as A
import ttn_project as P

_BASE_SQL = ("SELECT t.composer, t.composer_line, t.title, t.episode_pid, t.position "
             "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")
# Must mirror ttn_analyze.main's --year clause exactly, or the row set (and
# therefore the cache fingerprint) won't match the one --summary reads back.
_YEAR_CLAUSE = (" WHERE substr(e.broadcast_date, 1, 10) >= ? "
                "AND substr(e.broadcast_date, 1, 10) <= ?")


def corpus_years(conn):
    """Distinct broadcast years present in the DB, ascending."""
    rows = conn.execute(
        "SELECT DISTINCT substr(broadcast_date, 1, 4) FROM episodes "
        "WHERE broadcast_date IS NOT NULL ORDER BY 1").fetchall()
    return [int(r[0]) for r in rows if r[0] and r[0].isdigit()]


def slice_rows(conn, year, projection, rec_meta):
    """The summary row set for one slot (year=None → whole corpus), projected
    onto recording identity then arranger-tail-stripped, exactly as
    ttn_analyze.main's default --summary does."""
    if year is None:
        cur = conn.execute(_BASE_SQL)
    else:
        cur = conn.execute(_BASE_SQL + _YEAR_CLAUSE,
                           (f"{year}-01-01", f"{year}-12-31"))
    projected = A._project_summary_rows(cur, projection, rec_meta)
    return [(A.strip_arranger_tail(c, cl), t, pid) for c, cl, t, pid in projected]


def warm_slice(conn, year, cache_path, projection, rec_meta):
    """Populate the cache slot for `year` (None = corpus). Returns
    (status, seconds) with status 'hit' or 'computed'."""
    t0 = time.perf_counter()
    rows = slice_rows(conn, year, projection, rec_meta)
    _stats, cached = A.summary_for_rows(rows, cache_path)
    return ("hit" if cached else "computed"), time.perf_counter() - t0


def warm_all(db_path, cache_path=None, report=None):
    """Warm the corpus slot plus one slot per broadcast year. Returns a list
    of (label, status, seconds). `report`, if given, is called per slot."""
    if cache_path is None:
        cache_path = A.summary_cache_path()
    conn = sqlite3.connect(db_path)
    try:
        projection, _ = P.ensure(conn, P.PROJECTION_PATH)
        rec_meta = A.build_rec_meta(conn) if projection else {}
        results = []
        for year in [None] + corpus_years(conn):
            label = "corpus" if year is None else str(year)
            status, secs = warm_slice(conn, year, cache_path, projection, rec_meta)
            results.append((label, status, secs))
            if report is not None:
                report(label, status, secs)
        return results
    finally:
        conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Warm ttn_analyze's --summary cache for every slot.")
    ap.add_argument("db", nargs="?", default="ttn.sqlite",
                    help="path to ttn.sqlite")
    args = ap.parse_args(argv)

    print(f"Warming summary cache for {args.db} ...")
    t0 = time.perf_counter()
    warm_all(args.db,
             report=lambda label, status, secs:
                 print(f"  {label:>6}  {status:>8}  {secs:5.1f}s"))
    print(f"Done in {time.perf_counter() - t0:.1f}s")
