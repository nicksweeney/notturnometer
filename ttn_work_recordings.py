"""Work-recordings evidence panel: the fold/split oracle for curation passes.

`ttn_curate.py work-recordings ttn.sqlite QUERY [QUERY...]` resolves each
query (title substring or slug substring, optionally narrowed by --composer)
to work groups and prints one RECORDING-FACT panel per group:

    recording_pid | airings | span (first-last) | durations seen

plus a TEXT bucket for unprojected airings and an UNMATCHED bucket for rows
the projection never linked. This is the evidence CLAUDE.md's triage
discipline asks for ("prefer the recording_pid + duration oracle over title
reasoning"): same-key fragments of one work show as ONE panel; genuinely
different works (the Corelli trumpet-cluster class) show DIFFERENT panels
with disjoint recordings/durations. No judgment is applied here -- it prints
facts for the human call.

Query resolution mirrors what a pass does by hand: every tracks row's group
key is computed from its PROJECTED identity where one exists (rec_meta clean
segment composer/title), else raw text; WORK_ALIASES resolved on top. The
display index also reads ttn_slug_cache.json if present (missing/stale ->
slugs shown as '-', never an error).
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict

import ttn_analyze as A
import ttn_project as P

_SLUG_PATH = "ttn_slug_cache.json"


def _load_slugs():
    """ttn_slug_cache.json -> {(ck,wk): slug}; [] on any problem.

    File shape: {"fingerprint":…, "generated_at":…, "slugs": [[ck, wk, slug], …]}.
    A stale/missing cache only degrades slugs to '-' (panels carry ck/wk too).
    """
    try:
        import json
        with open(_SLUG_PATH) as fh:
            data = json.load(fh)
        return {(t[0], t[1]): t[2] for t in data.get("slugs", [])}
    except Exception:
        return {}


def _fetch_rows(conn):
    """tracks x episodes -> [(ep,pos,date,title,composer)] in broadcast order."""
    return conn.execute(
        "SELECT t.episode_pid, t.position, substr(e.broadcast_date,1,10), "
        "       t.title, t.composer "
        "FROM tracks t JOIN episodes e ON t.episode_pid=e.pid "
        "WHERE t.title IS NOT NULL ORDER BY e.broadcast_date").fetchall()


def _build_index(rows, projection, rec_meta):
    """Group all airings under projected-or-raw identity.

    Returns groups[(ck, wk)] -> {"airings": n, "dates": [...],
                                  "recs": {rp: {"n","first","last"}},
                                  "text": n, "unmatched": n,
                                  "display": (composer, title)}
    """
    cache = {}
    groups = defaultdict(lambda: {"airings": 0, "dates": [], "recs": {},
                                  "text": 0, "unmatched": 0,
                                  "display": None})
    for ep, pos, date, title, comp in rows:
        rp = projection.get((ep, pos))
        if rp and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = comp or "", title or ""
        ck = A.resolve_composer_alias(A.canonical_key(cm))
        k2 = (tt, cm)
        wk = cache.get(k2)
        if wk is None:
            wk = A.resolve_work_alias(A.work_title_key(tt, composer=cm), composer=cm)
            cache[k2] = wk
        g = groups[(ck, wk)]
        g["airings"] += 1
        g["dates"].append(date)
        if not g["display"]:
            g["display"] = (cm, tt)
        if rp and rp in rec_meta:
            r = g["recs"].setdefault(rp, {"n": 0, "first": date, "last": date})
            r["n"] += 1
            r["first"] = min(r["first"], date)
            r["last"] = max(r["last"], date)
        elif rp:
            g["unmatched"] += 1      # projection carried an rp absent from rec_meta
        else:
            g["text"] += 1           # unprojected (pre-2012 or unmatched row-scan)
    return dict(groups)


def _durations(conn):
    """recording_pid -> sorted set of segment durations."""
    out = defaultdict(set)
    for rp, d in conn.execute(
            "SELECT recording_pid, duration_seconds FROM segment_events "
            "WHERE duration_seconds IS NOT NULL AND recording_pid IS NOT NULL"):
        out[rp].add(d)
    return out


_ROLE_ORDER = {"Conductor": 0, "Ensemble": 1, "Orchestra": 2, "Choir": 3,
               "Singer": 4}


def _forces(conn, rps):
    """rp -> short credited-performer string for the panel rows.

    Uses the spine's contributor parser so display names are the SAME
    MBID-else-name identities the artist pages use; the Composer role is
    skipped (the panel header already carries it), Conductor first, then
    ensembles, then soloists. Empty/failed parse -> rp absent (no suffix).
    """
    if not rps:
        return {}
    import ttn_spine as S
    try:
        contribs = S.build_contributors(conn, recording_pids=set(rps))
    except sqlite3.Error:
        return {}
    out = {}
    for rp, clist in contribs.items():
        parts = []
        for c in sorted(clist, key=lambda c: (_ROLE_ORDER.get(c.role, 5), c.display_name)):
            if c.role == "Composer":
                continue
            tag = "" if c.role == "Performer" else f" ({c.role})"
            parts.append(c.display_name + tag)
        s = "; ".join(parts)
        out[rp] = (s[:87] + "...") if len(s) > 90 else s
    return out


def _search(groups, slugs, query, composer=None):
    cq = A.canonical_key(composer) if composer else None
    # Work keys are TOKEN-SORTED, so "trumpet suite" must become "suite
    # trumpet" to reach them; raw-order and display/slug substrings also match.
    words = sorted(A.canonical_key(query).split())
    q_sorted = " ".join(words)
    q_raw = query.lower()
    hits = []
    for (ck, wk), g in groups.items():
        if cq and cq not in ck:
            continue
        cm, tt = g["display"]
        slug = slugs.get((ck, wk), "")
        if (q_raw in f"{ck}|{tt}|{slug}".lower()
                or q_sorted == wk or q_sorted in wk):
            hits.append(((ck, wk), g))
    hits.sort(key=lambda kv: -kv[1]["airings"])
    return hits


def render_panel(key, g, durs, slugs, forces=None):
    forces = forces or {}
    ck, wk = key
    cm, tt = g["display"]
    slug = slugs.get((ck, wk), "-")
    lines = []
    lines.append(f"== {cm} — {tt}")
    lines.append(f"   composer_key={ck!r}  work_key={wk!r}")
    lines.append(f"   slug={slug}")
    dates = sorted(g["dates"])
    lines.append(f"   total: {g['airings']} airings, {dates[0]} → {dates[-1]}"
                 f"   (projected {g['airings']-g['text']-g['unmatched']},"
                 f" text-only {g['text']}, unmatched {g['unmatched']})")
    for rp, r in sorted(g["recs"].items(), key=lambda kv: -kv[1]["n"]):
        ds = ",".join(str(x) for x in sorted(durs.get(rp, [])) or ("-",))
        f = forces.get(rp)
        lines.append(f"   {rp}  {r['n']:>3}×  {r['first']}→{r['last']}  "
                     f"dur[{ds}]" + (f"  {f}" if f else ""))
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(
        prog="ttn_curate.py work-recordings",
        description="recording-fact panel per resolved work (fold/split oracle)")
    ap.add_argument("db")
    ap.add_argument("queries", nargs="+", help="title/slug substring per work panel")
    ap.add_argument("--composer", help="narrow candidate matching by composer substring")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rows = _fetch_rows(conn)
    projection, rec_meta, _status = P.load(conn)
    groups = _build_index(rows, projection, rec_meta)
    slugs = _load_slugs()
    for (ck, wk), g in groups.items():
        s = slugs.get((ck, wk))
        if s:
            g["slug"] = s
    durs = _durations(conn)

    exit_code = 0
    for query in args.queries:
        hits = _search(groups, slugs, query, args.composer)
        if not hits:
            print(f"no work matches {query!r}"
                  + (f" under --composer {args.composer!r}" if args.composer else ""))
            exit_code = exit_code or 2
            continue
        if len(hits) > 1:
            print(f"{len(hits)} matches for {query!r} (top shown first); "
                  "panels below are ordered by airings:")
        shown = hits[:5]
        panel_rps = {rp for _k, g in shown for rp in g["recs"]}
        forces = _forces(conn, panel_rps)
        for key, g in shown:
            print(render_panel(key, g, durs, slugs, forces=forces))
            print()
        if len(hits) > 5:
            print(f"... {len(hits)-5} more matches suppressed "
                  "(narrow with --composer or a longer query)\n")
    return exit_code


if __name__ == "__main__":
    main()
