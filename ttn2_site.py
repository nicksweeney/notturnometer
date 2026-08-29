"""ttn2_site — P4 phase 1: successor-backed site substrate inputs.

Produces the exact structures ttn_site._run_build consumes, with identity
resolved through the successor ledger instead of the legacy projection +
alias-table chain. The de-globalization delta (bare-generic folds scoped to
their dominant composer in the ledger) is EXPECTED here — it is the
cutover's content, classified by ttn2_site_parity.

Identity rule (verbatim from ttn2_query.load_groups / ttn2_parity): per text
row, rec_meta[rp] when the row's event is recording-backed, else the raw
text fields; keys = ledger resolution. The legacy strip_arranger_tail ->
resolve chain is deliberately NOT applied on top: ledger targets are final
canonicals, and re-resolving would re-fold the de-globalized identities.
"""
import sqlite3

import ttn_analyze as A
import ttn2_ledger as L

DB = "successor.sqlite"
SRC = "ttn.sqlite"


def load_identity_maps(src=SRC, dst=DB):
    """(comp, ws, wg, rec_meta, text_rp, presentation_map).

    text_rp: {(episode_pid, position): recording_pid} — the successor's
    High-tier link set (DP-high + bridge events), the drop-in equivalent of
    the legacy projection. presentation_map: same shape, Medium tier,
    show-only (never identity)."""
    comp, ws, wg = L.load_maps(dst)
    from ttn_project import build_rec_meta
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    rec_meta = build_rec_meta(src_conn)
    src_conn.close()
    s2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    ev_rp = {}
    for eid, rp in s2.execute(
            "SELECT id, COALESCE(recording_pid, "
            "  (SELECT o.recording_pid FROM obs o WHERE o.event_id=e.id "
            "   AND o.source='segment' LIMIT 1)) "
            "FROM event e WHERE method IN ('recording_pid','bridge')"):
        if rp:
            ev_rp[eid] = rp
    text_rp, pres = {}, {}
    for ep, ordv, eid in s2.execute(
            "SELECT episode_pid, ord, event_id FROM obs "
            "WHERE source='text' AND event_id IS NOT NULL"):
        rp = ev_rp.get(eid)
        if rp:
            text_rp[(ep, int(ordv))] = rp
    for ep, ordv, rp in s2.execute(
            "SELECT episode_pid, ord, recording_pid FROM presentation"):
        pres[(ep, int(ordv))] = rp
    s2.close()
    return comp, ws, wg, rec_meta, text_rp, pres


def _identity_of(cm, tt, comp, ws, wg):
    ck = L.resolve_composer(A.canonical_key(cm), comp)
    wk = L.resolve_work(A.work_title_key(tt, composer=cm), cm, ws, wg)
    return ck, wk


def accumulate_entities_t2(rows8, comp, ws, wg, rec_meta, text_rp,
                           presentation=None):
    """Mirror of ttn_site.accumulate_entities with successor identity.

    rows8: (title, composer, composer_line, performers, bdate, episode_pid,
    position, time_str) — ttn_site._WHOLE_CORPUS_SQL's shape.
    Returns (acc, counters); acc has exactly the legacy accumulate_entities
    keys/shapes so every downstream builder is unchanged."""
    import ttn_site as S  # lazy: ttn_site imports this module lazily too
    from collections import Counter
    work_airings, episode_tracks, recording_airings = {}, {}, {}
    births, deaths = {}, {}
    title_counter, composer_counter = {}, {}
    comp_spelling, comp_works = {}, {}
    rows5 = []
    for title, composer, composer_line, performers, bdate, ep, pos, tstr in rows8:
        rp = text_rp.get((ep, pos))
        if rp is not None and rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = composer or "", title or ""
        rows5.append((tt, cm, composer_line, performers, bdate))
        ck, wk = _identity_of(cm, tt, comp, ws, wg)
        rp_shown = rp
        if rp_shown is None and presentation:
            rp_shown = presentation.get((ep, pos))
        key = None if (not ck and not wk) else (ck, wk)
        b, d = S.parse_composer_years(composer_line)
        if b is not None:
            births.setdefault(ck, {})
            births[ck][b] = births[ck].get(b, 0) + 1
        if d is not None:
            deaths.setdefault(ck, {})
            deaths[ck][d] = deaths[ck].get(d, 0) + 1
        if key is not None:
            work_airings.setdefault(key, []).append(
                (bdate, rp_shown, performers, ep, pos))
            title_counter.setdefault(key, Counter())[tt] += 1
            composer_counter.setdefault(key, Counter())[A.normalize_composer(cm)] += 1
        if ck:
            comp_spelling.setdefault(ck, Counter())[A.normalize_composer(cm)] += 1
            if wk:
                comp_works.setdefault(ck, set()).add(wk)
        episode_tracks.setdefault(ep, []).append(
            (pos, tstr, key, cm, tt, performers, rp_shown))
        if rp_shown is not None:
            recording_airings.setdefault(rp_shown, []).append((bdate, ep, pos))
    for ep in episode_tracks:
        episode_tracks[ep].sort(key=lambda row: row[0])
    def _modal(counter):
        return max(counter, key=counter.get) if counter else None
    composer_dates = {ck: (_modal(births.get(ck)), _modal(deaths.get(ck)))
                      for ck in set(births) | set(deaths)}
    counters = {"title_counter": title_counter, "composer_counter": composer_counter,
                "composer_spelling_counter": comp_spelling,
                "composer_work_keys": comp_works, "rows5": rows5}
    acc = {"work_airings": work_airings, "episode_tracks": episode_tracks,
           "recording_airings": recording_airings, "composer_dates": composer_dates}
    return acc, counters
