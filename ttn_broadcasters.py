#!/usr/bin/env python3
"""Rank the EBU source broadcasters supplying BBC R3 'Through the Night',
from segment_events.record_label. Standalone; reads segment_events only.

MBID/EBU provenance lives on the segments side of the tracks<->segment_events
seam; this tool stays wholly on that side (see the design spec). --composer is a
raw ascii-fold filter, NOT a canonical grouping, by design.
"""

import argparse
import sqlite3
from collections import Counter, defaultdict, namedtuple

from ttn_analyze import ascii_fold
from ttn_ebu_codes import decode, fold, is_ebu_code
from ttn_segment_meta import INTERSTITIAL_RECORDING_PIDS

UNATTRIBUTED = "UNATTRIBUTED"
OTHER = "OTHER"   # non-EBU record_label values (commercial labels / freetext)

BroadcasterStat = namedtuple("BroadcasterStat", "key airings recordings")


def broadcaster_key(code):
    """Group key for the broadcaster level: a recognised EBU source folded to
    its canonical code, else the OTHER bucket."""
    return fold(code) if is_ebu_code(code) else OTHER


def country_key(code):
    """Group key for the country level: the EBU code's source country from the
    decode table — so a country's broadcasters roll up (Belgium's VRT/RTBF/
    legacy BRTN → one 'Belgium') and the BR-prefix collision stays split
    (BRTN→Belgium vs BRRC→Brazil). Non-EBU labels go to the OTHER bucket."""
    return decode(code)[2] if is_ebu_code(code) else OTHER


def rank_broadcasters(rows, rank_key=lambda code: code):
    """rows: iterable of (record_label, recording_pid). Group by rank_key(label)
    (empty/NULL label -> UNATTRIBUTED, never inferred). Returns
    [BroadcasterStat(key, airings, recordings)] where recordings = distinct
    non-NULL recording_pid, sorted by airings desc; OTHER then UNATTRIBUTED last."""
    airings = Counter()
    recs = defaultdict(set)
    for label, rec in rows:
        key = rank_key(label) if label else UNATTRIBUTED
        airings[key] += 1
        if rec:
            recs[key].add(rec)
    def sort_key(key):
        tier = 2 if key == UNATTRIBUTED else (1 if key == OTHER else 0)
        return (tier, -airings[key], key)
    return [BroadcasterStat(k, airings[k], len(recs[k]))
            for k in sorted(airings, key=sort_key)]


def load_rows(conn, *, after=None, before=None, year=None, composer=None,
              keep_interstitials=False):
    """Return (record_label, recording_pid) for every in-scope segment (NULL/''
    labels kept, so coverage is computable). Drops the known interstitial
    recordings by default. Filters: date range / single year (on
    episodes.broadcast_date) and composer (diacritic-insensitive substring on
    segment_events.composer_name)."""
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
    sql = ("SELECT s.record_label, s.recording_pid FROM segment_events s "
           "JOIN episodes e ON s.episode_pid = e.pid" + where)
    rows = conn.execute(sql, params).fetchall()
    if not keep_interstitials:
        rows = [(lab, rp) for lab, rp in rows
                if rp not in INTERSTITIAL_RECORDING_PIDS]
    return [(lab, rp) for lab, rp in rows]


def _coverage(stats):
    total = sum(s.airings for s in stats)
    unattr = next((s.airings for s in stats if s.key == UNATTRIBUTED), 0)
    return total, total - unattr, unattr


def render_report(stats, *, scope_label, top=None, composer=None,
                  level="broadcaster"):
    # Coverage and the % denominator are ALWAYS over the full stats — `top`
    # only trims which rows are displayed, never the totals.
    total, attributed, unattr = _coverage(stats)
    is_country = level == "country"
    title = "EBU source countries" if is_country else "EBU broadcasters"
    unit = "countries" if is_country else "EBU broadcasters"
    head = [f"{title} — {scope_label}"
            + (f" (composer~='{composer}')" if composer else ""),
            f"Coverage: {attributed:,} / {total:,} segments attributed "
            f"({100*attributed/total if total else 0:.1f}%); "
            f"UNATTRIBUTED: {unattr:,}",
            ""]

    def fmt(rank, label, country, airings, recs, pct_str):
        base = f"  {(f'{rank:>2}' if rank else '  ')} {label:28.28} "
        if not is_country:            # broadcaster level carries a country column
            base += f"{country:16.16} "
        return base + f"{airings:>8,} {recs:>7,} {pct_str}"

    main = [s for s in stats if s.key not in (UNATTRIBUTED, OTHER)]
    shown = main[:top] if (top and top > 0) else main
    rows, rank = [], 0
    for s in shown:
        rank += 1
        if is_country:
            label, country = s.key, ""
        else:
            name, _cc, cname = decode(s.key)
            label, country = f"{name} ({s.key})", cname
        pct = 100 * s.airings / attributed if attributed else 0
        rows.append(fmt(rank, label, country, s.airings, s.recordings, f"{pct:5.1f}"))
    rest = main[len(shown):]
    if rest:   # the ranking continues past --top: summarise the hidden tail
        r_air = sum(s.airings for s in rest)
        r_rec = sum(s.recordings for s in rest)
        pct = 100 * r_air / attributed if attributed else 0
        rows.append(fmt(None, f"… {len(rest):,} more {unit}", "",
                        r_air, r_rec, f"{pct:5.1f}"))
    other = next((s for s in stats if s.key == OTHER), None)
    if other:
        pct = 100 * other.airings / attributed if attributed else 0
        rows.append(fmt(None, "Other (non-EBU)", "",
                        other.airings, other.recordings, f"{pct:5.1f}"))
    un = next((s for s in stats if s.key == UNATTRIBUTED), None)
    if un:   # always keep UNATTRIBUTED for honesty, even under --top
        rows.append(fmt(None, "UNATTRIBUTED", "", un.airings, un.recordings, "    —"))
    hlabel = "country" if is_country else "broadcaster"
    header = f"  {'#':>2} {hlabel:28} "
    if not is_country:
        header += f"{'country':16} "
    header += f"{'airings':>8} {'recs':>7}     %"
    return "\n".join(head + [header] + rows)


def write_csv(stats, path, level="broadcaster"):
    import csv
    total, attributed, _ = _coverage(stats)
    is_country = level == "country"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        if is_country:
            w.writerow(["rank", "country", "airings", "recordings", "pct"])
        else:
            w.writerow(["rank", "code", "broadcaster", "country_code", "country",
                        "airings", "recordings", "pct"])
        rank = 0
        for s in stats:
            pct = 100 * s.airings / attributed if attributed else 0
            pct_s = "" if s.key == UNATTRIBUTED else f"{pct:.1f}"
            if s.key in (UNATTRIBUTED, OTHER):
                label = "Other (non-EBU)" if s.key == OTHER else UNATTRIBUTED
                if is_country:
                    w.writerow(["", label, s.airings, s.recordings, pct_s])
                else:
                    w.writerow(["", "", label, "", "", s.airings, s.recordings, pct_s])
                continue
            rank += 1
            if is_country:
                w.writerow([rank, s.key, s.airings, s.recordings, pct_s])
            else:
                name, cc, cname = decode(s.key)
                w.writerow([rank, s.key, name, cc, cname, s.airings, s.recordings, pct_s])


