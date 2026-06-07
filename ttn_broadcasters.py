#!/usr/bin/env python3
"""Rank the EBU source broadcasters supplying BBC R3 'Through the Night',
from segment_events.record_label. Standalone; reads segment_events only.

MBID/EBU provenance lives on the segments side of the tracks<->segment_events
seam; this tool stays wholly on that side (see the design spec). --composer is a
raw ascii-fold filter, NOT a canonical grouping, by design.
"""

import argparse
import sqlite3
from collections import Counter, namedtuple

from ttn_analyze import ascii_fold
from ttn_ebu_codes import decode, fold, is_ebu_code

UNATTRIBUTED = "UNATTRIBUTED"
OTHER = "OTHER"   # non-EBU record_label values (commercial labels / freetext)

BroadcasterStat = namedtuple("BroadcasterStat", "key airings")


def broadcaster_key(code):
    """Group key for the broadcaster level: a recognised EBU source folded to
    its canonical code, else the OTHER bucket."""
    return fold(code) if is_ebu_code(code) else OTHER


def rank_broadcasters(rows, rank_key=lambda code: code):
    """rows: iterable of record_label values (one per segment). Group by
    rank_key(label); empty/NULL label -> the UNATTRIBUTED bucket (never
    inferred). Returns [BroadcasterStat(key, airings)] sorted by airings desc,
    then key asc, with UNATTRIBUTED forced last."""
    counts = Counter()
    for label in rows:
        counts[rank_key(label) if label else UNATTRIBUTED] += 1
    def sort_key(item):
        key, n = item
        tier = 2 if key == UNATTRIBUTED else (1 if key == OTHER else 0)
        return (tier, -n, key)   # real broadcasters, then OTHER, then UNATTRIBUTED
    return [BroadcasterStat(k, n) for k, n in sorted(counts.items(), key=sort_key)]


def load_rows(conn, *, after=None, before=None, year=None, composer=None):
    """Return record_label for every in-scope segment (NULL/'' kept, so coverage
    is computable). Filters: date range / single year (on episodes.broadcast_date)
    and composer (diacritic-insensitive substring on segment_events.composer_name)."""
    conn.create_function(
        "ascii_fold", 1, lambda s: ascii_fold(s) if s is not None else None)
    clauses, params = [], []
    if after:
        clauses.append("substr(e.broadcast_date,1,10) >= ?"); params.append(after)
    if before:
        clauses.append("substr(e.broadcast_date,1,10) <= ?"); params.append(before)
    if year:
        clauses.append("substr(e.broadcast_date,1,4) = ?"); params.append(str(year))
    if composer:
        clauses.append("LOWER(ascii_fold(s.composer_name)) LIKE ?")
        params.append(f"%{ascii_fold(composer).lower()}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = ("SELECT s.record_label FROM segment_events s "
           "JOIN episodes e ON s.episode_pid = e.pid" + where)
    return [r[0] for r in conn.execute(sql, params)]


def _coverage(stats):
    total = sum(s.airings for s in stats)
    unattr = next((s.airings for s in stats if s.key == UNATTRIBUTED), 0)
    return total, total - unattr, unattr


def render_report(stats, *, scope_label, top=None, composer=None):
    # Coverage and the % denominator are ALWAYS over the full stats — `top`
    # only trims which broadcaster rows are displayed, never the totals.
    total, attributed, unattr = _coverage(stats)
    head = [f"EBU broadcasters — {scope_label}"
            + (f" (composer~='{composer}')" if composer else ""),
            f"Coverage: {attributed:,} / {total:,} segments attributed "
            f"({100*attributed/total if total else 0:.1f}%); "
            f"UNATTRIBUTED: {unattr:,}",
            ""]
    broadcasters = [s for s in stats if s.key not in (UNATTRIBUTED, OTHER)]
    if top and top > 0:
        broadcasters = broadcasters[:top]
    rows, rank = [], 0
    for s in broadcasters:
        rank += 1
        name, _cc, cname = decode(s.key)
        label = f"{name} ({s.key})"
        pct = 100 * s.airings / attributed if attributed else 0
        rows.append(f"  {rank:>2} {label:28.28} {cname:16.16} {s.airings:>8,} {pct:5.1f}")
    other = next((s for s in stats if s.key == OTHER), None)
    if other:
        pct = 100 * other.airings / attributed if attributed else 0
        rows.append(f"     {'Other (non-EBU)':28} {'':16} {other.airings:>8,} {pct:5.1f}")
    if unattr:   # always keep UNATTRIBUTED for honesty, even under --top
        rows.append(f"     {'UNATTRIBUTED':28} {'':16} {unattr:>8,}     —")
    header = f"  {'#':>2} {'broadcaster':28} {'country':16} {'airings':>8}     %"
    return "\n".join(head + [header] + rows)


def write_csv(stats, path):
    import csv
    total, attributed, _ = _coverage(stats)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "code", "broadcaster", "country_code", "country",
                    "airings", "pct"])
        rank = 0
        for s in stats:
            pct = 100 * s.airings / attributed if attributed else 0
            if s.key == UNATTRIBUTED:   # the gap: no rank/code/country/pct
                w.writerow(["", "", UNATTRIBUTED, "", "", s.airings, ""])
                continue
            if s.key == OTHER:          # attributed but not a real broadcaster
                w.writerow(["", "", "Other (non-EBU)", "", "", s.airings, f"{pct:.1f}"])
                continue
            rank += 1
            name, cc, cname = decode(s.key)
            w.writerow([rank, s.key, name, cc, cname, s.airings, f"{pct:.1f}"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--top", type=int, default=30, help="top N (0 = all)")
    ap.add_argument("--after"); ap.add_argument("--before"); ap.add_argument("--year")
    ap.add_argument("--composer", help="diacritic-insensitive substring on composer_name")
    ap.add_argument("--csv", metavar="PATH")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    rows = load_rows(conn, after=args.after, before=args.before,
                     year=args.year, composer=args.composer)
    stats = rank_broadcasters(rows, rank_key=broadcaster_key)

    if args.csv:
        write_csv(stats, args.csv)
        print(f"Wrote {args.csv}")
        return

    bits = [b for b in (args.after and f"{args.after}→", args.before, args.year) if b]
    scope = "".join(str(b) for b in bits) or "all years"
    print(render_report(stats, scope_label=scope, top=args.top, composer=args.composer))


if __name__ == "__main__":
    main()
