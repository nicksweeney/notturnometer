"""ttn2_query — P3: the curation prototype tools as successor-database queries.

One door, five subcommands, all reading successor.sqlite (obs + ledger) with
identity resolved through the ledger. Each is the successor port of its
current-pipeline prototype, with the same output shape so outputs can be
diffed side by side:

  fragmentation      rank composers by flaggable minority airings
                     (reuses ttn_duplicates.find_duplicates for pair logic;
                     grouping comes from successor identity)
  work-recordings    recording-fact panel per resolved work
                     (rp / airings / span / durations / forces; forces come
                     from ttn_spine over ttn.sqlite — recording_pids are the
                     shared identifier across both stores)
  qc-audit           directive/decoration/caps-run survivors over obs titles
                     (reuses ttn_qc_audit.scan_titles; ingest already
                     sanitized, so survivors are genuinely post-sanitize)
  propose-remaps     registry-slug presence check + nearest successor group
                     (BOUNDARY: full remap derivation stays in
                     ttn_propose_remaps until the registry re-anchors to
                     entity IDs at P4 — this command is the read-side half)
   drift-batch        P4 phase 2: classify registry work slugs whose stored
                      identity is absent from the successor groups into three
                      maintainer-ratification tiers via the successor group
                      KEYSPACE (same composer + near-key -> mechanical;
                      same composer, no near-key -> review; composer gone ->
                      retire), emitting batch files in the --remap-file
                      tradition (tier 1 mechanical re-anchor, tier 2 review,
                      tier 3 retire candidates)

Identity rule (mirrors ttn2_parity / ttn2_site): a text observation's
identity is rec_meta[rp] when its event is recording-backed — method
'recording_pid' OR 'bridge' (bridge events carry recording_pid on the event
row and have no segment obs for the old join, so ev_rp reads the COALESCE
form shared with ttn2_site.load_identity_maps) — else the observation's own
raw fields; per observation, never per event. Keys resolve through
ttn2_site._identity_of, the ONE successor identity chain (strip_arranger_tail
with the row's composer_line + normalize_composer before ledger resolution;
ruling 2026-08-29) — reconciling the curation layer with the site layer.
"""
import argparse
import collections
import json
import sqlite3
import sys

import ttn_analyze as A
import ttn2_ledger as L

DB = "successor.sqlite"
SRC = "ttn.sqlite"


def load_groups(src=SRC, dst=DB):
    """(ck, wk) -> {airings, display, recs{rp: {n, first, last}}, dates[]}.

    Identity per observation, mirroring ttn2_parity exactly; keys via
    ttn2_site._identity_of (the one implementation, site layer included)."""
    import ttn2_site as T2  # lazy: ttn2_site imports ttn2_ledger, this module
    comp, ws, wg = L.load_maps(dst)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    from ttn_project import build_rec_meta
    rec_meta = build_rec_meta(src_conn)
    src_conn.close()
    s2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    ev_rp = {}
    # ttn2_site.load_identity_maps' form verbatim: recording_pid AND bridge
    # events both carry event.recording_pid (bridge events have no segment
    # obs to join), so read the column, COALESCEd against the segment obs.
    for eid, rp in s2.execute(
            "SELECT id, COALESCE(recording_pid, "
            "  (SELECT o.recording_pid FROM obs o WHERE o.event_id=e.id "
            "   AND o.source='segment' LIMIT 1)) "
            "FROM event e WHERE method IN ('recording_pid','bridge')"):
        if rp:
            ev_rp[eid] = rp
    groups = collections.defaultdict(
        lambda: {"airings": 0, "dates": [], "recs": {}, "text": 0,
                 "unmatched": 0, "display": None, "titles": collections.Counter()})
    cache = {}
    for oid, ep, date10, comp_raw, cl, title, eid in s2.execute(
            "SELECT id, episode_pid, date10, composer_raw, composer_line, "
            "title, event_id FROM obs WHERE source='text'"):
        rp = ev_rp.get(eid)
        if rp is not None and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = comp_raw or "", title or ""
        k2 = (tt, cm, cl or "")
        got = cache.get(k2)
        if got is None:
            got = T2._identity_of(cm, tt, comp, ws, wg, composer_line=cl)
            cache[k2] = got
        ck, wk = got
        g = groups[(ck, wk)]
        g["airings"] += 1
        g["dates"].append(date10)
        g["titles"][(cm, tt)] += 1
        if not g["display"]:
            g["display"] = (cm, tt)
        if rp:
            r = g["recs"].setdefault(rp, {"n": 0, "first": date10, "last": date10})
            r["n"] += 1
            r["first"] = min(r["first"], date10)
            r["last"] = max(r["last"], date10)
        else:
            g["text"] += 1
    s2.close()
    # display = corpus-most-common original spelling (same rule the current
    # pipeline's grouping uses, so pair fingerprints diff cleanly)
    for g in groups.values():
        g["display"] = g["titles"].most_common(1)[0][0]
    return dict(groups)


def load_entity_view(dst=DB, groups=None):
    """{work_entity_id: (dominant_ck, dominant_wk)} -- the dominant member key
    per successor entity, by group airings (ties: lexicographically smallest
    (ck, wk)). groups: an injected load_groups() result for hermetic tests;
    loaded once via load_groups when None. Member keys absent from groups
    count as 0 airings (an entity with no airing member still resolves).

    A missing successor.sqlite, or one predating the entity migration (no
    work_entity_key table), raises RuntimeError naming the rebuild -- never
    a raw sqlite3.OperationalError."""
    try:
        airings = groups if groups is not None else load_groups(dst=dst)
        conn = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
        try:
            members = collections.defaultdict(list)
            for eid, ck, wk in conn.execute(
                    "SELECT work_entity_id, composer_key, work_key "
                    "FROM work_entity_key"):
                members[eid].append((ck, wk))
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            f"{dst} missing or stale (no work_entity_key) -- rebuild via "
            "uv run ttn2_ingest.py && uv run ttn2_match.py, then the entity "
            "migration") from e
    return {eid: min(keys, key=lambda k: (-airings.get(k, {}).get("airings", 0), k))
            for eid, keys in members.items()}


def _slug_map():
    try:
        with open("ttn_slug_cache.json") as fh:
            data = json.load(fh)
        return {(t[0], t[1]): t[2] for t in data.get("slugs", [])}
    except Exception:
        return {}


# ---------------------------------------------------------------- fragmentation

def cmd_fragmentation(args):
    from ttn_duplicates import Group, _fingerprint, find_duplicates
    groups = load_groups(args.src, args.dst)
    gs = []
    for (ck, wk), g in groups.items():
        disp = g["display"][1]
        gs.append(Group(ck, g["display"][0], wk, disp, g["airings"],
                        _fingerprint(disp)))
    pairs = find_duplicates(gs)
    score = collections.defaultdict(int)
    items = collections.defaultdict(list)
    for p in pairs:
        minority = min(p.a.airings, p.b.airings)
        score[p.composer] += minority
        items[p.composer].append((minority, p.a.display_title, p.b.display_title))
    display = {}
    for (ck, wk), g in groups.items():
        if ck not in display or g["airings"] > display[ck][1]:
            display[ck] = (g["display"][0], g["airings"])
    ranked = sorted(score.items(), key=lambda kv: -kv[1])[:args.top]
    print(f"=== ttn2 fragmentation (successor groups): top {args.top} "
          "by flaggable minority airings ===")
    print(f"{'score':>7}  {'pairs':>5}  composer")
    for ck, sc in ranked:
        print(f"{sc:>7}  {len(items[ck]):>5}  {display.get(ck, (ck, 0))[0]}")
        for minority, ta, tb in items[ck][:2]:
            print(f"         {minority}x {ta[:56]!r} vs {tb[:42]!r}")
    return 0


# -------------------------------------------------------------- work-recordings

def cmd_work_recordings(args):
    import ttn_work_recordings as WR
    groups = load_groups(args.src, args.dst)
    slugs = WR._load_slugs()
    src_conn = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True)
    durs = WR._durations(src_conn)
    src_conn.close()
    exit_code = 0
    for query in args.queries:
        words = sorted(A.canonical_key(query).split())
        q_sorted = " ".join(words)
        q_raw = query.lower()
        hits = []
        for (ck, wk), g in groups.items():
            if args.composer and args.composer.lower() not in ck:
                continue
            slug = slugs.get((ck, wk), "")
            cm, tt = g["display"]
            if (q_raw in f"{ck}|{tt}|{slug}".lower()
                    or q_sorted == wk or q_sorted in wk):
                hits.append(((ck, wk), g))
        hits.sort(key=lambda kv: -kv[1]["airings"])
        if not hits:
            print(f"no work matches {query!r}")
            exit_code = exit_code or 2
            continue
        shown = hits[:5]
        rps = {rp for _k, g in shown for rp in g["recs"]}
        src_conn = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True)
        forces = WR._forces(src_conn, rps)
        src_conn.close()
        for key, g in shown:
            ck, wk = key
            cm, tt = g["display"]
            slug = slugs.get((ck, wk), "-")
            dates = sorted(g["dates"])
            print(f"== {cm} — {tt}")
            print(f"   composer_key={ck!r}  work_key={wk!r}")
            print(f"   slug={slug}")
            print(f"   total: {g['airings']} airings, {dates[0]} → {dates[-1]}"
                  f"   (projected {g['airings']-g['text']-g['unmatched']},"
                  f" text-only {g['text']}, unmatched {g['unmatched']})")
            for rp, r in sorted(g["recs"].items(), key=lambda kv: -kv[1]["n"]):
                ds = ",".join(str(x) for x in sorted(durs.get(rp, [])) or ("-",))
                f = forces.get(rp)
                print(f"   {rp}  {r['n']:>3}×  {r['first']}→{r['last']}  "
                      f"dur[{ds}]" + (f"  {f}" if f else ""))
            print()
    return exit_code


# --------------------------------------------------------------------- qc-audit

def cmd_qc_audit(args):
    import ttn_qc_audit as QA
    if args.raw:
        src_conn = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True)
        rows = src_conn.execute(
            "SELECT DISTINCT recording_pid, track_title FROM segment_events "
            "WHERE track_title IS NOT NULL").fetchall()
        src_conn.close()
    else:
        # obs titles were sanitized at ingest; one deterministic title per rp
        dst_conn = sqlite3.connect(f"file:{args.dst}?mode=ro", uri=True)
        seen = {}
        for rp, t in dst_conn.execute(
                "SELECT recording_pid, title FROM obs "
                "WHERE source='segment' AND title IS NOT NULL "
                "ORDER BY recording_pid, ord"):
            seen.setdefault(rp, t)
        dst_conn.close()
        rows = [(rp, t) for rp, t in seen.items() if t]
    print(QA.render(QA.scan_titles(rows), len(rows), {}))
    return 0


# --------------------------------------------------------------- propose-remaps

def cmd_propose_remaps(args):
    groups = load_groups(args.src, args.dst)
    with open("ttn_site_registry.json") as fh:
        reg = json.load(fh)
    works = reg.get("works") or {}
    redirects = (reg.get("redirects") or {}).get("works") or {}
    import difflib
    for slug in args.slugs:
        if slug in redirects:
            print(f"- {slug}: redirected to {redirects[slug]!r}; nothing to do")
            continue
        entry = works.get(slug)
        if not entry:
            print(f"- {slug}: not in the works registry")
            continue
        ck = (entry.get("composer_key") or "").strip().lower()
        wk = (entry.get("work_key") or "").strip()
        if groups.get((ck, wk)):
            print(f"+ {slug}: identity present in successor groups "
                  f"({groups[(ck, wk)]['airings']} airings)")
            continue
        pool = [(k, g) for k, g in groups.items() if k[0] == ck]
        near = difflib.get_close_matches(
            wk, [k[1] for k, _ in pool], n=3, cutoff=0.5)
        cands = [(k, groups[k]) for k, g in pool if k[1] in near]
        if cands:
            best = max(cands, key=lambda kv: kv[1]["airings"])
            print(f"? {slug}: MISSING from successor groups; nearest under "
                  f"{ck}: {best[0][1][:48]!r} ({best[1]['airings']} airings)")
        else:
            print(f"? {slug}: MISSING; no near successor under {ck!r} "
                  "(derive with ttn_propose_remaps or retire)")
    print("\nBOUNDARY: full remap derivation stays in ttn_propose_remaps "
          "until the registry re-anchors to entity IDs (P4).")
    return 0


# ----------------------------------------------------------------- drift-batch

def cmd_drift_batch(args):
    """P4 phase 2 drift-batch generator: for each registry work slug whose
    stored (composer_key, work_key) is absent from the successor groups,
    classify via the GROUP KEYSPACE (fix round 1, 2026-08-30 ruling: the
    anchor chain is stale and the generator no longer consults it):

      tier 1 (mechanical): registered composer present in the group keyspace
              + near-key (difflib get_close_matches >= 0.5) between the
              registered wk and that composer's successor work keys
      tier 2 (review):     same composer, no near key
      tier 3 (retire):     registered composer absent from the group keyspace
              (identity dissolved -- the anon/trad precedent)

    The near-key match is a routing hint, not truth (under broad composers it
    emits junk); Task-4 ratification resolves the ratified entity for a
    tier-1/2 slug via work_entity_key lookup of the TARGET (ck, wk) -- never
    via the anchor chain. Writes one slug-per-line batch file per tier (each
    slug preceded by its `# ` evidence comment: tier 1 lists ALL near
    candidates ratio-descending with their airings -- the ratifier picks, the
    generator proposes; tier 2 lists the composer's top-5 keyspace so review
    is query-free; tier 3 keeps the retire reason) for maintainer
    ratification."""
    import difflib
    import os
    import ttn_site
    groups = load_groups(args.src, args.dst)
    reg = ttn_site.load_registry(args.registry)
    by_composer = collections.defaultdict(list)
    for (ck, wk), g in groups.items():
        by_composer[ck].append((wk, g["airings"]))
    tiers = {1: [], 2: [], 3: []}
    for slug, entry in reg["works"].items():
        ck = (entry.get("composer_key") or "").strip().lower()
        wk = (entry.get("work_key") or "").strip()
        if groups.get((ck, wk)):
            continue                      # identity present: not drifted
        pool = by_composer.get(ck)
        if pool is None:
            tiers[3].append((slug, f"retire candidate: composer {ck!r} "
                                   f"absent from the successor groups "
                                   f"(registered ({ck!r}, {wk!r}))"))
            continue
        near = difflib.get_close_matches(
            wk, [w for w, _n in pool], n=3, cutoff=0.5)
        if near:
            # fix round 1 (Important): name ALL near candidates, best-first
            # by RATIO (not airings -- the airings-best pick proposed the
            # Freischutz opera for the Agathe aria on the live corpus). The
            # ratifier picks; the generator proposes.
            airing_of = dict(pool)
            # fix round 2: display the SELECTION's orientation. get_close_matches
            # scores as SM(candidate, wk); ratio() is orientation-asymmetric, so
            # SM(wk, w) can display below the 0.5 cutoff for a candidate the
            # selection admitted (0.50 -> 0.44 on the live corpus). Selection
            # and display must agree.
            cands = sorted(
                ((w, airing_of[w], difflib.SequenceMatcher(None, w, wk).ratio())
                 for w in near),
                key=lambda p: (-p[2], p[0]))
            listed = " | ".join(
                f"{w} [{n} airings, ratio {r:.2f}]" for w, n, r in cands)
            tiers[1].append((slug, f"registered: ({ck!r}, {wk!r}) -> "
                                   f"candidates: {listed}"))
        else:
            top = sorted(pool, key=lambda p: (-p[1], p[0]))[:5]
            keyspace = " | ".join(f"{w} [{n}]" for w, n in top)
            tiers[2].append((slug, f"registered: ({ck!r}, {wk!r}) -> review: "
                                   f"same composer alive, no near key; "
                                   f"composer keyspace: {keyspace} "
                                   f"(+{len(pool) - len(top)} more)"))
    names = {1: "drift-batch-1-mechanical.txt",
             2: "drift-batch-2-review.txt",
             3: "drift-batch-3-retire.txt"}
    os.makedirs(args.out_dir, exist_ok=True)
    for tier in (1, 2, 3):
        path = os.path.join(args.out_dir, names[tier])
        with open(path, "w", encoding="utf-8") as fh:
            for slug, comment in sorted(tiers[tier]):
                fh.write(f"# {comment}\n{slug}\n")
        print(f"tier {tier}: {path} ({len(tiers[tier])})")
    print(f"drift batch: {len(tiers[1])} mechanical, {len(tiers[2])} review, "
          f"{len(tiers[3])} retire ({sum(map(len, tiers.values()))} orphans "
          f"of {len(reg['works'])} registered works)")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(prog="ttn2_query")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fragmentation")
    f.add_argument("--top", type=int, default=25)
    w = sub.add_parser("work-recordings")
    w.add_argument("queries", nargs="+")
    w.add_argument("--composer")
    q = sub.add_parser("qc-audit")
    q.add_argument("--raw", action="store_true")
    p = sub.add_parser("propose-remaps")
    p.add_argument("slugs", nargs="+")
    d = sub.add_parser("drift-batch",
                       help="classify drifted registry slugs into three "
                            "ratification tiers, writing batch files")
    d.add_argument("--registry", default="ttn_site_registry.json")
    d.add_argument("--out-dir", default="scratch/drift-batch")
    args = ap.parse_args(argv)
    return {"fragmentation": cmd_fragmentation,
            "work-recordings": cmd_work_recordings,
            "qc-audit": cmd_qc_audit,
            "propose-remaps": cmd_propose_remaps,
            "drift-batch": cmd_drift_batch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
