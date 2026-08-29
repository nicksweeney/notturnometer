"""ttn2_site — P4 phase 1: successor-backed site substrate inputs.

Produces the exact structures ttn_site._run_build consumes, with identity
resolved through the successor ledger instead of the legacy projection +
alias-table chain. The de-globalization delta (bare-generic folds scoped to
their dominant composer in the ledger) is EXPECTED here — it is the
cutover's content, classified by ttn2_site_parity.

Identity rule (verbatim from ttn2_query.load_groups / ttn2_parity, amended by
the 2026-08-29 parity ruling): per text row, rec_meta[rp] when the row's
event is recording-backed, else the raw text fields. The legacy SITE chain's
strip_arranger_tail + normalize_composer join BEFORE ledger resolution --
they are canonicalization vocabulary, not alias decisions, and the legacy
accumulator keys through them (ttn_site.accumulate_entities). The
prohibition stays on resolve_composer_alias / resolve_work_alias (the
de-globalization trap): the ledger still governs all alias folds.
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
    from ttn_project import build_rec_meta, load_recording_decisions
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    # rec_meta with the recording-decisions ledger, so its keys (and the
    # keys it collapses) are ledger-resolved terminals -- event.recording_pid
    # and presentation.recording_pid store terminals since fix round 3
    # (ttn2_match), mirroring the legacy projection's rec_meta exactly.
    rec_meta = build_rec_meta(src_conn, load_recording_decisions())
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


def _identity_of(cm, tt, comp, ws, wg, composer_line=None):
    """The successor identity chain, mirroring ttn_site.accumulate_entities's
    order exactly: strip the arranger tail (legacy: strip_arranger_tail(c,
    cl)), then normalize_composer -> canonical_key -> ledger composer
    resolution; work_title_key scoped on the STRIPPED composer (not the
    normalized one), then ledger work resolution. No alias-table resolution
    here -- the ledger governs folds. composer_line=None (or empty) skips
    the strip: unchanged behavior."""
    stripped = A.strip_arranger_tail(cm, composer_line) if composer_line else cm
    ck = L.resolve_composer(A.canonical_key(A.normalize_composer(stripped)), comp)
    wk = L.resolve_work(A.work_title_key(tt, composer=stripped), stripped, ws, wg)
    return ck, wk


def accumulate_entities_t2(rows8, comp, ws, wg, rec_meta, text_rp,
                           presentation=None):
    """Mirror of ttn_site.accumulate_entities with successor identity.

    rows8: (title, composer, composer_line, performers, bdate, episode_pid,
    position, time_str) — ttn_site._WHOLE_CORPUS_SQL's shape.
    Returns (acc, counters); acc has exactly the legacy accumulate_entities
    keys/shapes so every downstream builder is unchanged.

    Keys go through the full legacy chain (strip_arranger_tail with the row's
    composer_line + normalize_composer, ruling 2026-08-29) BEFORE ledger
    resolution; the counters' composer spelling counts are
    normalize_composer(stripped), mirroring ttn_analyze.build_work_index /
    ttn_site.build_composer_index. Display strings (episode_tracks' cm/tt)
    stay the projected/raw credit — the strip affects keys only."""
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
        stripped = A.strip_arranger_tail(cm, composer_line) if composer_line else cm
        ck, wk = _identity_of(cm, tt, comp, ws, wg, composer_line=composer_line)
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
            composer_counter.setdefault(key, Counter())[A.normalize_composer(stripped)] += 1
        if ck:
            comp_spelling.setdefault(ck, Counter())[A.normalize_composer(stripped)] += 1
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


def build_work_entries_t2(acc, counters, registry_works):
    """Work entries with successor keys. Registry slugs WIN (URL stability);
    unregistered identities mint via build_work_slugs with the registry slugs
    as the taken set (collision -> '-2', '-3', ... suffix)."""
    from collections import Counter
    from ttn_analyze import _best_spelling, build_work_slugs
    reg_slug_of = {(v["composer_key"], v["work_key"]): slug
                   for slug, v in registry_works.items()}
    keys = list(acc["work_airings"])
    minted = build_work_slugs(
        (k, _best_spelling(counters["composer_counter"][k]),
         _best_spelling(counters["title_counter"][k])) for k in keys)
    taken = set(reg_slug_of.values())
    entries = []
    for k in keys:
        slug = reg_slug_of.get(k)
        if slug is None:
            slug = minted[k]
            if slug in taken:
                base, i = slug, 2
                while f"{base}-{i}" in taken:
                    i += 1
                slug = f"{base}-{i}"
        taken.add(slug)
        entries.append({
            "key": k,
            "slug": slug,
            "composer_display": _best_spelling(counters["composer_counter"][k]),
            "work_display": _best_spelling(counters["title_counter"][k]),
            "airings": len(acc["work_airings"][k]),
            "spellings": list(counters["title_counter"][k]),
        })
    return entries


def build_composer_entries_t2(counters, registry_composers):
    """Composer entries mirroring ttn_site.build_composer_index's dict shape,
    keyed from successor resolution. Registry slug wins; misses mint via
    ttn_site.composer_slug (collision suffixing mirrors the registry's own
    assignment, which is skipped in successor mode)."""
    from ttn_analyze import _best_spelling, override_composer_display
    from ttn_site import composer_slug
    reg_slug_of = {v["composer_key"]: slug
                   for slug, v in registry_composers.items()}
    taken = set(reg_slug_of.values())
    entries = []
    for ck, counter in counters["composer_spelling_counter"].items():
        best = _best_spelling(counter)
        display = override_composer_display(ck, "composer", best)
        slug = reg_slug_of.get(ck)
        if slug is None:
            slug = composer_slug(display)
            if slug in taken:
                base, i = slug, 2
                while f"{base}-{i}" in taken:
                    i += 1
                slug = f"{base}-{i}"
        taken.add(slug)
        entries.append({
            "composer_key": ck,
            "slug": slug,
            "display": display,
            "airings": sum(counter.values()),
            "n_works": len(counters["composer_work_keys"].get(ck, ())),
            "spellings": list(counter),
        })
    return entries


def pids_by_identity_t2(rows8, text_rp, comp, ws, wg, rec_meta):
    """{(ck, wk): set(recording_pid)} — mirrors
    ttn_evidence.current_pids_by_identity with successor identity (projection
    only; a Medium link is not identity proof)."""
    out = {}
    for row in rows8:
        title, composer, composer_line, _perf, _bdate, ep, pos, _t = row
        rp = text_rp.get((ep, pos))
        if rp is None:
            continue
        if rp in rec_meta:
            cm, tt = rec_meta[rp]
        else:
            cm, tt = composer or "", title or ""
        ck, wk = _identity_of(cm, tt, comp, ws, wg, composer_line=composer_line)
        if not ck and not wk:
            continue
        out.setdefault((ck, wk), set()).add(rp)
    return out


def derive_site_inputs(src, registry, spine_rps=None):
    """The successor counterpart of ttn_site._derive_registry_entries:
    (work_entries, composer_entries, raw8, acc, counters, text_rp,
    presentation_map, pids_by_identity).

    spine_rps: when provided (the spine's recording rps, built by the caller
    BEFORE this runs), the presentation map is filtered to them BEFORE
    accumulate_entities_t2 -- the legacy path's by-construction invariant
    (ttn_site._run_build filters after accumulate; here the filter must sit
    before it, because build_work_rows' n_recordings/n_text_only counters
    read work_airings directly, before any downstream spine gating, so an
    unfiltered map leaks non-spine rps into those counts)."""
    comp, ws, wg, rec_meta, text_rp, pres = load_identity_maps(src)
    if spine_rps is not None:
        pres = {k: rp for k, rp in pres.items() if rp in spine_rps}
    from ttn_site import _WHOLE_CORPUS_SQL   # lazy: ttn_site imports us lazily
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    raw8 = list(conn.execute(_WHOLE_CORPUS_SQL))
    conn.close()
    acc, counters = accumulate_entities_t2(
        raw8, comp, ws, wg, rec_meta, text_rp, pres)
    work_entries = build_work_entries_t2(acc, counters, registry["works"])
    composer_entries = build_composer_entries_t2(counters, registry["composers"])
    pids = pids_by_identity_t2(raw8, text_rp, comp, ws, wg, rec_meta)
    return (work_entries, composer_entries, raw8, acc, counters,
            text_rp, pres, pids)


def year_breakdown_t2(acc):
    """compute_year_breakdown's shape, keyed from successor identity."""
    buckets = {}
    for (ck, wk), airings in acc["work_airings"].items():
        for bdate, _rp, _perf, _ep, _pos in airings:
            if not bdate:
                continue
            year = bdate[:4]
            if not year.isdigit():
                continue
            b = buckets.get(year)
            if b is None:
                b = buckets[year] = {"airings": 0, "works": set(),
                                     "composers": set(), "dmin": bdate,
                                     "dmax": bdate}
            b["airings"] += 1
            b["works"].add((ck, wk))
            b["composers"].add(ck)
            b["dmin"] = min(b["dmin"], bdate)
            b["dmax"] = max(b["dmax"], bdate)
    return [{"year": y, "airings": b["airings"], "works": len(b["works"]),
             "composers": len(b["composers"]), "date_min": b["dmin"],
             "date_max": b["dmax"]}
            for y, b in sorted(buckets.items())]
