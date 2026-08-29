"""ttn2_parity — P0 harness: successor vs current pipeline, exactly.

Three diffs, all of which must be ZERO for parity:
   1. LINKAGE  — per (episode_pid, position): successor text-obs event linkage
      (recording_pid when DP-high-linked) must equal ttn_project's
      projection.get((ep, pos)) for every projected row. Successor-only
      links count too; the ratified EBU-ordering artifact class
      (ttn2_ledger._EBU_ORDER_LINKS) is the only legitimate occupant.
  2. IDENTITY — the (composer_key, work_key) multiset over text observations
     (full legacy chain on BOTH sides: strip_arranger_tail + normalize_composer
     before resolution -- ruling 2026-08-29; ledger resolution on the
     successor, alias tables on the current side; segment-clean identity where
     the event is recording-backed) must equal the current projected
     pipeline's multiset.
  3. YEARS    — text-observation airings per year must match.

A non-zero diff is a bug in the successor's reproduction of the current
kludges, not a data finding — parity first, semantics later.
Run: uv run ttn2_parity.py
"""
import collections
import sqlite3
import sys

sys.path.insert(0, '.')
import ttn_analyze as A
import ttn2_ledger as L
import ttn2_site as T2
import ttn_work_recordings as WR
import ttn_project as P


def current_identity(cm, tt, cl):
    """The CURRENT side's full legacy chain, shared with
    ttn2_site_parity.compute_delta_keys (one implementation, no drift):
    strip_arranger_tail with the row's composer_line + normalize_composer ->
    canonical_key -> alias resolution; work_title_key scoped on the STRIPPED
    composer. Mirrors ttn_site.accumulate_entities / ttn_analyze
    .build_work_index key derivation."""
    stripped = A.strip_arranger_tail(cm, cl) if cl else cm
    ck = A.resolve_composer_alias(A.canonical_key(A.normalize_composer(stripped)))
    wk = A.resolve_work_alias(A.work_title_key(tt, composer=stripped), stripped)
    return ck, wk


def main(src="ttn.sqlite", dst="successor.sqlite"):
    comp, ws, wg = L.load_maps(dst)
    src = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    # Reference = the FULL projection (2012+ DP half merged with the trusted
    # cross-era bridge links). The successor now ingests both halves, so the
    # linkage check covers bridge links too; identity diffs must remain exactly
    # the known de-globalization delta.
    projection, rec_meta, status = P.load(src)
    assert status == "ok", "projection cache must be fresh for parity"
    s2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)

    # event -> recording_pid (for the rec_meta lookup). Identity rule mirrors
    # _project_identity EXACTLY: rec_meta[rp] when the recording has clean
    # segment metadata, else the observation's own raw fields -- per obs, not
    # per event (rows under one recording can diverge when rec_meta is absent,
    # e.g. segment rows with NULL titles). Both recording_pid AND bridge events
    # carry event.recording_pid directly (bridge events have no segment obs to
    # read it from), so read the column, not the segment obs.
    ev_rp = {}
    for eid, rp in s2.execute(
            "SELECT id, recording_pid FROM event "
            "WHERE method IN ('recording_pid','bridge') "
            "AND recording_pid IS NOT NULL"):
        ev_rp[eid] = rp

    # ---- 1. LINKAGE
    succ_link = {}
    for oid, ep, ordv, eid in s2.execute(
            "SELECT id, episode_pid, ord, event_id FROM obs "
            "WHERE source='text' AND event_id IS NOT NULL"):
        rp = ev_rp.get(eid)
        if rp:
            succ_link[(ep, int(ordv))] = rp
    link_diff = checked_link = 0
    for (ep, pos), rp_expected in projection.items():
        checked_link += 1
        if succ_link.get((ep, pos)) != rp_expected:
            link_diff += 1
            if link_diff <= 5:
                print(f"LINK DIFF {ep}#{pos}: current={rp_expected} "
                      f"successor={succ_link.get((ep, pos))}")
    # Successor-only links: (ep, pos) pairs the successor links but the
    # projection lacks. The EBU-syndication ordering artifact (ruling
    # 2026-08-29): the legacy DP's temporal cascade demotes these matches;
    # the successor's are CORRECT and ratified as ledger kind='link' rows.
    ratified = {(ep, pos) for ep, pos, _rp in L._EBU_ORDER_LINKS}
    succ_only = sorted(set(succ_link) - set(projection))
    unratified = [k for k in succ_only if k not in ratified]
    for ep, pos in succ_only[:5]:
        print(f"LINK succ-only {ep}#{pos} -> {succ_link[(ep, pos)]}"
              f"{'' if (ep, pos) in ratified else '  UNRATIFIED'}")
    if unratified:
        print(f"WARNING: {len(unratified)} successor-only links are NOT "
              f"ledger-ratified: {unratified[:5]}")
    link_diff += len(succ_only)

    # ---- 2. IDENTITY multiset
    succ_ms = collections.Counter()
    cur_ms = collections.Counter()
    succ_years = collections.Counter()
    cur_years = collections.Counter()
    rows = WR._fetch_rows(src)
    for ep, pos, date, t, c, cl in rows:
        rp = projection.get((ep, pos))
        if rp is not None and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = c or "", t or ""
        cur_ms[current_identity(cm, tt, cl)] += 1
        cur_years[date[:4]] += 1
    for oid, ep, ordv, date10, comp_raw, title, cl, eid in s2.execute(
            "SELECT id, episode_pid, ord, date10, composer_raw, title, "
            "composer_line, event_id FROM obs WHERE source='text'"):
        rp = ev_rp.get(eid)
        if rp is not None and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = comp_raw or "", title or ""
        # successor side: ONE implementation with the site accumulator --
        # ttn2_site._identity_of (strip + normalize before ledger resolution).
        succ_ms[T2._identity_of(cm, tt, comp, ws, wg, composer_line=cl)] += 1
        succ_years[date10[:4]] += 1
    ident_diff = 0
    for key in set(cur_ms) | set(succ_ms):
        if cur_ms.get(key, 0) != succ_ms.get(key, 0):
            ident_diff += 1
            if ident_diff <= 8:
                print(f"IDENT DIFF {key}: current={cur_ms.get(key, 0)} "
                      f"successor={succ_ms.get(key, 0)}")

    year_diff = {y: (cur_years.get(y, 0), succ_years.get(y, 0))
                 for y in set(cur_years) | set(succ_years)
                 if cur_years.get(y, 0) != succ_years.get(y, 0)}
    s2.close()
    print(f"\nparity: linkage {link_diff}/{checked_link} diffs "
          f"(successor-only {len(succ_only)}, "
          f"ledger-explained {len(succ_only) - len(unratified)}); "
          f"identity {ident_diff} keys differ "
          f"({sum(cur_ms.values())} vs {sum(succ_ms.values())} airings); "
          f"year diffs: {year_diff or 'none'}")
    return link_diff + ident_diff + len(year_diff)


if __name__ == "__main__":
    sys.exit(1 if main(*(sys.argv[1:3] or [])) else 0)
