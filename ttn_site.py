"""Site substrate builder (website Phase 1): the frozen slug registry +
site.sqlite entity aggregates. ttn_site_render.py renders it. Both are
reached as `ttn_data.py site` (build, then render)."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import datetime as dt
from collections import Counter

import ttn_project
from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                          strip_arranger_tail, resolve_composer_alias,
                          resolve_work_alias, work_title_key, _best_spelling,
                          override_composer_display, build_work_index,
                          _project_rows, load_slug_map, _project_identity,
                          compute_year_breakdown, _FORM_SYNONYMS)
import ttn_broadcasters
import ttn_ebu_codes
import ttn_ebu_codes
import ttn_spine
from ttn_site_render import render_site

REGISTRY_PATH = "ttn_site_registry.json"
SITE_DB_FILENAME = "site.sqlite"

# Absolute paths to the two modules whose bytes feed site_fingerprint, resolved
# once at import time beside THIS module (not the caller's cwd). Module-level
# names (not inlined into site_fingerprint) so tests can monkeypatch them.
_ANALYZE_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_analyze.py")
_ALIASES_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_aliases.py")


def registry_path():
    """Absolute path to the slug registry, beside this module (mirrors
    ttn_analyze.slug_cache_path)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        REGISTRY_PATH)


def site_db_path():
    """Absolute path to site.sqlite, beside this module (mirrors registry_path
    / ttn_analyze.slug_cache_path)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        SITE_DB_FILENAME)


def dist_path_default():
    """Absolute path to the default dist/ output directory, beside this
    module (mirrors registry_path / site_db_path)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")


def composer_slug(display: str) -> str:
    """kebab-case the full canonical display name (ascii-fold, lowercase,
    non-alnum runs -> '-'). Empty survivor -> 'c' + sha1[:8] of the input."""
    folded = ascii_fold(display).lower()
    slug = "-".join(t for t in re.split(r"[^a-z0-9]+", folded) if t)
    if not slug:
        return "c" + hashlib.sha1(display.encode()).hexdigest()[:8]
    return slug


def broadcaster_slug(display_name: str) -> str:
    """URL slug for a broadcaster: the decoded display name with any trailing
    parenthetical STRIPPED (annotations like '(legacy)'/'(current)' are
    curatorial notes, and exactly the fragment most likely to be edited --
    they stay in the page display, never in the permanent URL), then the
    composer_slug kebab."""
    return composer_slug(re.sub(r"\s*\([^)]*\)\s*$", "", display_name))


def mint_broadcaster_slugs() -> dict:
    """{broadcaster_key: (slug, display_name, country_name)} for every
    canonical EBU code -- derived deterministically from ttn_ebu_codes (a
    git-tracked decisions file, so slugs are reproducible without a registry
    namespace). A base-slug collision (distinct institutions sharing an
    acronym, e.g. the Swiss and Serbian RTS) qualifies BOTH sides with their
    kebabbed country name; a residual collision is a HARD ERROR (a decode-
    table edit must never silently double-assign a URL)."""
    base = {code: (broadcaster_slug(name), name, country)
            for code, (name, _cc, country) in ttn_ebu_codes.EBU_CODES.items()}
    counts: dict = {}
    for slug, _n, _c in base.values():
        counts[slug] = counts.get(slug, 0) + 1
    out = {}
    for code, (slug, name, country) in base.items():
        if counts[slug] > 1:
            slug = f"{slug}-{composer_slug(country)}"
        out[code] = (slug, name, country)
    assigned: dict = {}
    for code, (slug, _n, _c) in out.items():
        if slug in assigned:
            raise RegistryDriftError(
                f"broadcaster slug collision after country qualification: "
                f"{slug!r} claimed by {assigned[slug]!r} and {code!r}")
        assigned[slug] = code
    return out


_BROADCASTER_TOP_N = 10


def build_broadcaster_rows(all_brc_rows, rec_rows, work_entries,
                            composer_display_of, cons) -> list:
    """Build broadcasters-table row tuples. PURE.

    all_brc_rows:  (record_label, recording_pid) per in-scope segment airing
                   (ttn_broadcasters.load_rows output -- interstitials already
                   dropped). Non-EBU / empty labels are skipped: the
                   OTHER/UNATTRIBUTED buckets are accounting rows on the
                   browse table, not entities that get pages.
    rec_rows:      the BUILT recordings-table tuples (rp -> work/composer
                   slugs come from here, so links agree with the recordings
                   table by construction).
    work_entries:  build_work_index entries WITH canonical slugs (display
                   strings per work slug).
    composer_display_of: {composer_key: corpus display} (the SSOT).
    cons:          whole-corpus spine contributors dict (ensemble names).

    Returns 9-tuples in broadcasters-schema column order, airings-DESC:
      (slug, key, display, country, airings, n_recordings,
       top_works_json, top_performances_json, top_ensembles_json)
    top_works/top_performances carry work/composer/performance links (top
    10 each, by THIS broadcaster's airings of them); top_ensembles is a
    link-less name list (ensembles deliberately have no pages)."""
    minted = mint_broadcaster_slugs()
    rec_meta = {r[0]: (r[1], r[2]) for r in rec_rows}   # rp -> (work_slug, composer_slug)
    disp_of = {
        e["slug"]: (e["work_display"],
                    composer_display_of.get(e["key"][0]) or e["composer_display"])
        for e in work_entries
    }

    airings: dict = {}          # key -> total airings
    rp_counts: dict = {}        # key -> {rp: airings under this broadcaster}
    for label, rp in all_brc_rows:
        if not label or not ttn_ebu_codes.is_ebu_code(label) or not rp:
            continue
        key = ttn_ebu_codes.fold(label)
        airings[key] = airings.get(key, 0) + 1
        rp_counts.setdefault(key, {})[rp] = rp_counts.get(key, {}).get(rp, 0) + 1

    rows = []
    for key, per_rp in rp_counts.items():
        slug, display, country = minted[key]

        work_counts: dict = {}
        for rp, n in per_rp.items():
            ws = rec_meta.get(rp, (None, None))[0]
            if ws in disp_of:
                work_counts[ws] = work_counts.get(ws, 0) + n
        top_works = [
            {"slug": ws, "display": disp_of[ws][0],
             "composer_display": disp_of[ws][1], "airings": n}
            for ws, n in sorted(work_counts.items(),
                                 key=lambda kv: (-kv[1], kv[0]))[:_BROADCASTER_TOP_N]
        ]

        top_performances = []
        for rp, n in sorted(per_rp.items(), key=lambda kv: (-kv[1], kv[0])):
            if len(top_performances) == _BROADCASTER_TOP_N:
                break
            ws, cslug = rec_meta.get(rp, (None, None))
            if ws not in disp_of:
                continue
            wd, cd = disp_of[ws]
            top_performances.append({
                "recording_pid": rp, "work_slug": ws, "work_display": wd,
                "composer_slug": cslug, "composer_display": cd, "airings": n,
            })

        ens_counts: dict = {}
        for rp, n in per_rp.items():
            seen = set()
            for c in cons.get(rp, []):
                if c.role in ("Ensemble", "Orchestra", "Choir") \
                        and c.identity_key not in seen:
                    seen.add(c.identity_key)
                    ens_counts[c.display_name] = ens_counts.get(c.display_name, 0) + n
        top_ensembles = [
            {"display": name, "airings": n}
            for name, n in sorted(ens_counts.items(),
                                   key=lambda kv: (-kv[1], kv[0]))[:_BROADCASTER_TOP_N]
        ]

        rows.append((slug, key, display, country, airings[key], len(per_rp),
                     json.dumps(top_works), json.dumps(top_performances),
                     json.dumps(top_ensembles)))

    rows.sort(key=lambda r: (-r[4], r[0]))
    return rows


def build_composer_index(rows) -> list:
    """Per-composer identity entries from projected 5-tuple ranking rows.

    rows: iterable of (title, composer, composer_line, performers, bdate)
          with arranger tails NOT yet stripped.

    Mirrors build_work_index's key derivation on the composer side:
      stripped = strip_arranger_tail(composer, composer_line)
      ck       = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
      wk       = resolve_work_alias(work_title_key(title, stripped))

    Each entry dict has keys:
      composer_key -- resolved canonical composer key
      slug         -- composer_slug of the display name
      display      -- best-spelling display name (curated override applied)
      airings      -- total airing count
      n_works      -- count of distinct work keys seen for this composer
      spellings    -- list of distinct normalized composer spellings seen

    Rows with an empty composer key are skipped. No collision handling here
    (registry-time concern)."""
    airing_count: dict = {}          # ck -> int
    spelling_counter: dict = {}      # ck -> Counter of normalize_composer(stripped)
    work_keys: dict = {}             # ck -> set of wk
    key_order: list = []             # insertion-ordered unique ck

    for title, composer, composer_line, performers, bdate in rows:
        stripped = strip_arranger_tail(composer, composer_line)
        ck = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
        if not ck:
            continue
        wk = resolve_work_alias(work_title_key(title, stripped))

        if ck not in airing_count:
            airing_count[ck] = 0
            spelling_counter[ck] = Counter()
            work_keys[ck] = set()
            key_order.append(ck)

        airing_count[ck] += 1
        spelling_counter[ck][normalize_composer(stripped)] += 1
        work_keys[ck].add(wk)

    entries = []
    for ck in key_order:
        best = _best_spelling(spelling_counter[ck])
        display = override_composer_display(ck, "composer", best)
        entries.append({
            "composer_key": ck,
            "slug": composer_slug(display),
            "display": display,
            "airings": airing_count[ck],
            "n_works": len(work_keys[ck]),
            "spellings": list(spelling_counter[ck]),
        })

    return entries


def accumulate_entities(rows8, projection, rec_meta) -> dict:
    """One pass over the whole-corpus 8-tuple cursor, building the three
    per-entity accumulators the page-aggregate builders (Tasks 6-7) slice
    from. Pure: no SQL, no I/O.

    rows8: iterable of (title, composer, composer_line, performers, bdate,
           episode_pid, position, time_str) -- the profile-card 7-tuple
           (ttn_analyze.work_airings' cursor7 shape) extended with time_str
           (episode pages need the on-air clock time).
    projection: {(episode_pid, position): recording_pid}
    rec_meta:   {recording_pid: (clean_composer, clean_title)}

    Returns a dict with three keys:
      work_airings: {(ck, wk): [(bdate, rp_or_None, performers, ep, pos), ...]}
        -- only rows that pass build_work_index's inclusion test (not both ck
        and wk empty). List order = input row order.
      episode_tracks: {ep: [(pos, time_str, key_or_None, composer_display,
        title_display, performers, rp_or_None), ...]} sorted by pos per
        episode. EVERY row lands here, including junk rows (key=None).
        composer_display/title_display are the PROJECTED identity strings
        (_project_identity's output) -- the recording's clean credit for a
        projected row, the raw text otherwise.
      recording_airings: {rp: [(bdate, ep), ...]} -- one entry per PROJECTED
        row (rp is not None), input order.

    Key derivation mirrors ttn_analyze.work_airings exactly, applied AFTER
    _project_identity:
      c, cl, t = _project_identity(ep, pos, composer, composer_line, title,
                                    projection, rec_meta)
      stripped = strip_arranger_tail(c, cl)
      ck = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
      wk = resolve_work_alias(work_title_key(t, stripped))
    """
    work_airings: dict = {}
    episode_tracks: dict = {}
    recording_airings: dict = {}

    for title, composer, composer_line, performers, bdate, ep, pos, time_str in rows8:
        c, cl, t = _project_identity(ep, pos, composer, composer_line, title,
                                     projection, rec_meta)
        stripped = strip_arranger_tail(c, cl)
        ck = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
        wk = resolve_work_alias(work_title_key(t, stripped))

        rp = projection.get((ep, pos))
        key = None if (not ck and not wk) else (ck, wk)

        if key is not None:
            work_airings.setdefault(key, []).append((bdate, rp, performers, ep, pos))

        episode_tracks.setdefault(ep, []).append(
            (pos, time_str, key, c, t, performers, rp))

        if rp is not None:
            recording_airings.setdefault(rp, []).append((bdate, ep))

    for ep in episode_tracks:
        episode_tracks[ep].sort(key=lambda row: row[0])

    return {
        "work_airings": work_airings,
        "episode_tracks": episode_tracks,
        "recording_airings": recording_airings,
    }


# --- work + recording aggregate row builders (batched spine facets) --------
# PURE: no conn, no I/O. The caller builds the whole-corpus spine/broadcaster
# structures ONCE (ttn_spine.build_recordings/build_contributors,
# ttn_broadcasters.load_rows pre-grouped by recording_pid) and passes them in
# here; per-work/per-recording facets are plain dict-comprehension SUBSETS
# over each entity's recording_pid set. This lifts gather_work_profile's body
# (ttn_analyze.py) -- same ranking calls, same dict keys -- but must NEVER be
# called per work (that rebuilds spine context on every call; the cardinal
# rule from the plan risk-watch).

def _contrib_stat_dict(stat):
    """ContribStat(identity, display_name, mbid, airings, recordings) -> a
    plain JSON-safe dict with explicit field names."""
    return {
        "identity": stat.identity,
        "display_name": stat.display_name,
        "mbid": stat.mbid,
        "airings": stat.airings,
        "recordings": stat.recordings,
    }


def _broadcaster_stat_dict(stat):
    """BroadcasterStat(key, airings, recordings) -> a plain JSON-safe dict.
    `key` is already the rank_key's output (an EBU code or OTHER/UNATTRIBUTED
    bucket name) -- the renderer decodes it to a display name as needed."""
    return {"key": stat.key, "airings": stat.airings, "recordings": stat.recordings}


def _contributor_facets(rps, recs, cons, brc_rows_by_rp):
    """The contributor/broadcaster facet dict for a recording_pid set: top-10
    performer/conductor/ensemble rankings + the EBU source ranking, sliced
    from the WHOLE-CORPUS recs/cons/brc_rows_by_rp via dict-comprehension
    subsets -- never a fresh spine build. Shared by _work_facets (which adds
    the per-recording list) and build_composer_rows (which doesn't -- a
    composer's per-recording detail lives on its work pages). Empty rps
    (fully text-only entity) -> all-empty facets."""
    if not rps:
        return {"top_performers": [], "top_conductors": [],
                "top_ensembles": [], "broadcasters": []}

    recs_sub = {rp: r for rp, r in recs.items() if rp in rps}
    cons_sub = {rp: c for rp, c in cons.items() if rp in rps}

    top_performers = ttn_spine.rank_contributors(recs_sub, cons_sub, "Performer")[:10]
    top_conductors = ttn_spine.rank_contributors(recs_sub, cons_sub, "Conductor")[:10]
    ens_stats = ttn_spine.rank_contributors(recs_sub, cons_sub, "Ensemble")
    orch_stats = ttn_spine.rank_contributors(recs_sub, cons_sub, "Orchestra")
    top_ensembles = sorted(ens_stats + orch_stats, key=lambda s: -s.airings)[:10]

    b_rows = [(lab, rp) for rp in rps for lab in brc_rows_by_rp.get(rp, [])]
    broadcasters = ttn_broadcasters.rank_broadcasters(
        b_rows, rank_key=ttn_broadcasters.broadcaster_key)

    return {
        "top_performers": [_contrib_stat_dict(s) for s in top_performers],
        "top_conductors": [_contrib_stat_dict(s) for s in top_conductors],
        "top_ensembles": [_contrib_stat_dict(s) for s in top_ensembles],
        "broadcasters": [_broadcaster_stat_dict(s) for s in broadcasters],
    }


def _work_facets(rps, recs, cons, brc_rows_by_rp):
    """The segment-side facet dict for one work's recording_pid set: the same
    five keys gather_work_profile computes (recordings/top_performers/
    top_conductors/top_ensembles/broadcasters), sliced from the WHOLE-CORPUS
    recs/cons/brc_rows_by_rp via dict-comprehension subsets -- never a fresh
    spine build. Empty rps (fully text-only work) -> all-empty facets."""
    contributor_facets = _contributor_facets(rps, recs, cons, brc_rows_by_rp)
    if not rps:
        return {"recordings": [], **contributor_facets}

    recs_sub = {rp: r for rp, r in recs.items() if rp in rps}
    cons_sub = {rp: c for rp, c in cons.items() if rp in rps}
    minted_slugs = mint_broadcaster_slugs()

    def _rec_dict(r):
        clist = cons_sub.get(r.recording_pid, [])
        # per-recording broadcaster: the majority label, decoded -- the same
        # rule as the recordings-table broadcaster column -- plus the
        # drill-in page slug when the label is a recognized EBU code.
        labels = [lab for lab in brc_rows_by_rp.get(r.recording_pid, []) if lab]
        broadcaster = broadcaster_slug_val = None
        if labels:
            majority = Counter(labels).most_common(1)[0][0]
            broadcaster = ttn_ebu_codes.decode(majority)[0] or majority
            if ttn_ebu_codes.is_ebu_code(majority):
                broadcaster_slug_val = minted_slugs[ttn_ebu_codes.fold(majority)][0]
        return {
            "recording_pid": r.recording_pid,
            "duration": r.duration_seconds,
            "airing_count": r.airing_count,
            "first": r.first_aired,
            "last": r.last_aired,
            "broadcaster": broadcaster,
            "broadcaster_slug": broadcaster_slug_val,
            "conductors": [c.display_name for c in clist if c.role == "Conductor"],
            "ensembles": [c.display_name for c in clist
                          if c.role in ("Ensemble", "Orchestra")],
            "soloists": [c.display_name for c in clist
                         if c.role in ("Performer", "Singer", "Choir")],
        }

    recordings_list = sorted(
        (_rec_dict(r) for r in recs_sub.values()),
        key=lambda d: (-d["airing_count"], d["recording_pid"]))

    return {"recordings": recordings_list, **contributor_facets}


def build_work_rows(entries, work_airings, composer_slug_of,
                    composer_display_of, recs, cons,
                    brc_rows_by_rp) -> list:
    """Build works-table row tuples from a work index + the whole-corpus
    accumulators/spine structures. PURE.

    entries:          build_work_index entries WITH canonical slugs already
                       overlaid (caller's job -- see _run_build's slug_map
                       overlay).
    work_airings:      {(ck, wk): [(bdate, rp_or_None, performers, ep, pos), ...]}
                       from accumulate_entities.
    composer_slug_of:  {composer_key: composer_slug}.
    composer_display_of: {composer_key: corpus-wide best-spelling display}
                       from build_composer_index -- the SINGLE source of
                       truth for a composer's shown name, so the byline here
                       (and the recording page, which joins it) never diverges
                       from the composer page. build_work_index's own per-work
                       best-spelling is kept ONLY for slug derivation; an
                       empty-composer work (no composer entry) falls back to it.
    recs / cons:       ONE whole-corpus ttn_spine.build_recordings/
                       build_contributors result (dicts keyed recording_pid).
    brc_rows_by_rp:    {recording_pid: [record_label, ...]} -- whole-corpus
                       ttn_broadcasters.load_rows(conn) pre-grouped by rp.

    Returns a list of 13-tuples in works-schema column order:
      (slug, composer_slug, composer_key, work_key, work_display,
       composer_display, catalogue, airings, n_recordings, n_text_only,
       first_aired, last_aired, facets_json)

    composer_slug is nullable BY DESIGN: build_work_index admits an
    empty-composer key ("", wk) (its inclusion test excludes only
    both-empty), and build_composer_index skips empty ck -- so such a work
    has no composer page and its composer_slug is None (the page renders
    without a composer link, like a junk episode row). Zero such rows on
    the current corpus, but rec_meta already carries blank-composer
    recordings; a NOT NULL here would turn the first future one into an
    opaque whole-build IntegrityError abort (final-review finding).
    """
    rows = []
    for entry in entries:
        ck, wk = entry["key"]
        composer_display = composer_display_of.get(ck) or entry["composer_display"]
        airings = work_airings.get((ck, wk), [])

        if wk.startswith("§"):
            catalogue = wk[1:].split("|")[0]
        else:
            catalogue = None

        n_recordings_seen = sum(1 for (_bd, rp, _p, _ep, _pos) in airings if rp is not None)
        n_text_only = len(airings) - n_recordings_seen

        bdates = [bd for (bd, _rp, _p, _ep, _pos) in airings if bd]
        first_aired = min(bdates) if bdates else None
        last_aired = max(bdates) if bdates else None

        yr_rows = [
            (entry["work_display"], composer_display,
             composer_display, perf, bd)
            for (bd, _rp, perf, _ep, _pos) in airings
        ]
        by_year = compute_year_breakdown(yr_rows)

        rps = {rp for (_bd, rp, _p, _ep, _pos) in airings if rp is not None}
        facets = _work_facets(rps, recs, cons, brc_rows_by_rp)
        # by_year renders newest-first (compute_year_breakdown is chronological).
        facets["by_year"] = list(reversed(by_year))

        rows.append((
            entry["slug"],
            composer_slug_of.get(ck),
            ck,
            wk,
            entry["work_display"],
            composer_display,
            catalogue,
            len(airings),
            len(rps),
            n_text_only,
            first_aired,
            last_aired,
            json.dumps(facets),
        ))
    return rows


def build_recording_rows(work_airings, recording_airings, work_slug_of,
                          composer_slug_of, recs, cons, brc_rows_by_rp):
    """Build recordings-table row tuples. PURE.

    work_airings:      {(ck, wk): [(bdate, rp_or_None, performers, ep, pos), ...]}
    recording_airings:  {rp: [(bdate, ep), ...]} -- whole corpus (includes
                        bridged pre-2012 airings; used for first/last, NOT
                        the spine's own 2012+-only first/last).
    work_slug_of:       {(ck, wk): slug}.
    composer_slug_of:   {composer_key: composer_slug}.
    recs / cons:        whole-corpus spine dicts, as in build_work_rows.
    brc_rows_by_rp:     {recording_pid: [record_label, ...]}.

    A recording spans >1 work key occasionally (title-variant residue): it is
    assigned to the work with the MOST of that recording's airings, ties
    broken by lexicographically smallest work slug.

    Returns (rows, n_multi_work, n_skipped):
      rows          -- list of 10-tuples in recordings-schema column order
                       (recording_pid, work_slug, composer_slug, duration,
                        broadcaster, airings, first_aired, last_aired,
                        contributors_json, airing_dates_json)
      n_multi_work  -- count of recordings assigned across >1 work key
      n_skipped     -- count of recordings present in the projection
                       (recording_airings) but absent from `recs` (should not
                       happen; guarded rather than raising)
    """
    # rp -> {work_key: airing_count}
    rp_work_counts: dict = {}
    for (ck, wk), airings in work_airings.items():
        for (_bd, rp, _p, _ep, _pos) in airings:
            if rp is None:
                continue
            rp_work_counts.setdefault(rp, {})
            rp_work_counts[rp][(ck, wk)] = rp_work_counts[rp].get((ck, wk), 0) + 1

    rows = []
    n_multi_work = 0
    n_skipped = 0

    for rp, dates_eps in recording_airings.items():
        if rp not in recs:
            n_skipped += 1
            continue

        work_counts = rp_work_counts.get(rp, {})
        if len(work_counts) > 1:
            n_multi_work += 1

        def _sort_key(item):
            wk_tuple, count = item
            slug = work_slug_of.get(wk_tuple, "")
            return (-count, slug)

        if work_counts:
            (ck, wk), _count = sorted(work_counts.items(), key=_sort_key)[0]
            work_slug = work_slug_of.get((ck, wk))
            composer_slug_val = composer_slug_of.get(ck)
        else:
            work_slug = None
            composer_slug_val = None

        r = recs[rp]
        labels = brc_rows_by_rp.get(rp, [])
        if labels:
            counted = Counter(labels)
            majority_label = counted.most_common(1)[0][0]
            broadcaster = ttn_ebu_codes.decode(majority_label)[0] or majority_label or None
        else:
            broadcaster = None

        sorted_dates = sorted(dates_eps, key=lambda t: (t[0], t[1]))
        first_aired = sorted_dates[0][0]
        last_aired = sorted_dates[-1][0]

        contributors_json = json.dumps(
            [{"role": c.role, "name": c.display_name} for c in cons.get(rp, [])])
        # Airing-dates table renders newest-first; first/last above stay
        # derived from the ascending sort.
        airing_dates_json = json.dumps(
            [[bd, ep] for bd, ep in reversed(sorted_dates)])

        rows.append((
            rp,
            work_slug,
            composer_slug_val,
            r.duration_seconds,
            broadcaster,
            len(dates_eps),
            first_aired,
            last_aired,
            contributors_json,
            airing_dates_json,
        ))

    return rows, n_multi_work, n_skipped


def build_composer_rows(composer_entries, work_entries, work_airings,
                         composer_slug_of, work_slug_of,
                         recs, cons, brc_rows_by_rp) -> list:
    """Build composers-table row tuples. PURE.

    composer_entries:  build_composer_index entries.
    work_entries:      build_work_index entries WITH canonical slugs overlaid
                       (same objects the works table is built from).
    work_airings:      {(ck, wk): [(bdate, rp_or_None, performers, ep, pos), ...]}
                       from accumulate_entities.
    composer_slug_of:  {composer_key: composer_slug}.
    work_slug_of:      {(ck, wk): slug}.
    recs / cons / brc_rows_by_rp: the SAME whole-corpus spine/broadcaster
                       structures build_work_rows takes -- the composer facets
                       are dict subsets over them, selected by the union of
                       the composer's works' recording_pids.

    Returns a list of 7-tuples in composers-schema column order:
      (slug, composer_key, display, airings, n_works, works_json, facets_json)

    works_json is that composer's works ranked by -airings then slug (ties
    broken deterministically): [{slug, display, airings}, ...].
    facets_json carries the composer-level analytics the work pages already
    have (2026-07-17 panel review): top_performers/top_conductors/
    top_ensembles/broadcasters over the composer's recording set (2012+,
    performance-linked), plus by_year -- NEWEST-first {year, airings, works}
    buckets over ALL the composer's airings (whole corpus; works = distinct
    work keys that year, counted from the real group keys, never re-derived
    from display strings).
    """
    works_by_composer: dict = {}   # ck -> list of (slug, display, airings)
    airings_by_composer: dict = {} # ck -> list of (bdate, rp, wk)
    for entry in work_entries:
        ck, wk = entry["key"]
        airing_rows = work_airings.get((ck, wk), [])
        works_by_composer.setdefault(ck, []).append(
            (entry["slug"], entry["work_display"], len(airing_rows)))
        airings_by_composer.setdefault(ck, []).extend(
            (bd, rp, wk) for (bd, rp, _p, _ep, _pos) in airing_rows)

    rows = []
    for centry in composer_entries:
        ck = centry["composer_key"]
        works = sorted(works_by_composer.get(ck, []), key=lambda w: (-w[2], w[0]))
        works_json = json.dumps(
            [{"slug": slug, "display": display, "airings": airings}
             for slug, display, airings in works])

        composer_airings = airings_by_composer.get(ck, [])
        rps = {rp for (_bd, rp, _wk) in composer_airings if rp is not None}
        buckets: dict = {}          # year -> [airings, set(wk)]
        for bd, _rp, wk in composer_airings:
            if not bd:
                continue
            b = buckets.setdefault(bd[:4], [0, set()])
            b[0] += 1
            b[1].add(wk)
        facets = _contributor_facets(rps, recs, cons, brc_rows_by_rp)
        facets["by_year"] = [
            {"year": y, "airings": b[0], "works": len(b[1])}
            for y, b in sorted(buckets.items(), reverse=True)
        ]

        rows.append((
            centry["slug"],
            ck,
            centry["display"],
            centry["airings"],
            centry["n_works"],
            works_json,
            json.dumps(facets),
        ))
    return rows


def build_episode_rows(episode_meta, episode_tracks, work_slug_of,
                        composer_slug_of, known_rps) -> list:
    """Build episodes-table row tuples. PURE.

    episode_meta:    list of (pid, date10, title) -- ONE _EPISODE_META_SQL
                     query covering ALL episodes (the caller runs it; every
                     pid gets a row, including zero-track anchor episodes).
                     "title" here is the episode SUBTITLE (falling back to
                     the uniform "Through the Night" title only if empty).
    episode_tracks:  {episode_pid: [(pos, time_str, key_or_None,
                     composer_display, title_display, performers, rp_or_None),
                     ...]} from accumulate_entities, already sorted by pos.
    work_slug_of:    {(ck, wk): slug}.
    composer_slug_of: {composer_key: composer_slug}.
    known_rps:       set of recording_pids that actually have a recordings-table
                     row. A projected rp OUTSIDE this set (an interstitial the
                     spine excludes -- b0833vgj's segment-backfilled Milhaud
                     filler is the live case -- or a build_recording_rows skip)
                     is emitted as recording_pid=None: the track renders as
                     text rather than linking to a recording page that
                     deliberately doesn't exist. Required, not defaulted -- a
                     "link everything" default would silently re-introduce the
                     dangling-link class check_closure exists to catch.

    Returns a list of 5-tuples in episodes-schema column order:
      (pid, date, title, bbc_url, tracks_json)

    tracks_json is a list of {pos, time, work_slug, composer_slug, composer,
    title, performers, recording_pid} in broadcast order. A junk row (key is
    None) gets work_slug=None and composer_slug=None -- it renders as plain
    text rather than a dead link. A pid with no rows in episode_tracks (the
    75 pre-2010 zero-track anchors) gets tracks_json = [].
    """
    rows = []
    for pid, date, title in episode_meta:
        tracks = []
        pid_tracks = sorted(episode_tracks.get(pid, []), key=lambda row: row[0])
        for pos, time_str, key, composer, track_title, performers, rp in pid_tracks:
            if key is None:
                work_slug = None
                composer_slug_val = None
            else:
                ck, wk = key
                work_slug = work_slug_of.get(key)
                composer_slug_val = composer_slug_of.get(ck)
            tracks.append({
                "pos": pos,
                "time": time_str,
                "work_slug": work_slug,
                "composer_slug": composer_slug_val,
                "composer": composer,
                "title": track_title,
                "performers": performers,
                "recording_pid": rp if rp in known_rps else None,
            })
        rows.append((
            pid,
            date,
            title,
            f"https://www.bbc.co.uk/programmes/{pid}",
            json.dumps(tracks),
        ))
    return rows


# The ensembles browse table's inclusion line: identities with fewer airings
# than this stay out of the table (they're in the `total` count). A quality
# threshold, not a rank cut -- the name-keyed junk tail lives below it.
_ENSEMBLES_AIRINGS_CUT = 50

# The Christmas topic window (month-day). Measured 2026-07-17 (festive-title
# fraction per broadcast date): 12-25 = 29.7%, 12-24 = 23.4%, 12-26 = 7.4%,
# 12-27 = 0.5%, corpus baseline 0.6% -- so the window is the two genuinely
# festive nights (12-26, initially included, was dropped as considerably
# less festive -- Nick's recollection, data-confirmed -- then 12-24 added
# after the widened-top-10 preview showed it purely additive: Britten's
# Ceremony of Carols is programmed 7-of-10 on the Eve). The site labels
# 12-24 "Christmas Eve" and 12-25 "Christmas Day" broadcasts.
_CHRISTMAS_MMDD = ("12-24", "12-25")
_CHRISTMAS_TOP_N = 50

# Works-by-length class lines (seconds) + per-class rank cut. The lines are
# round numbers a public page can say out loud ("under ten minutes", "over
# half an hour"); 600s is almost exactly the corpus median recording
# duration, 1800s sits near p87. Classes apply to the WORK's airing-weighted
# median performance duration, never to individual performances -- 3 of the
# top-10 works straddle the 10m line recording-by-recording (Faune 5/16), so
# per-performance classification would list one work in two classes.
_LENGTH_SHORT_MAX = 600
_LENGTH_LONG_MIN = 1800
_LENGTH_TOP_N = 25


def _weighted_median(pairs):
    """Median of (value, weight) pairs -- the value at which cumulative
    weight first reaches half the total. pairs must be non-empty."""
    pairs = sorted(pairs)
    total = sum(w for _v, w in pairs)
    acc = 0
    for v, w in pairs:
        acc += w
        if acc * 2 >= total:
            return v
# The role set is the spine's own ensemble-role concept -- share it, don't fork it.
_ENSEMBLE_ROLES = ttn_spine._ENSEMBLE_ROLES


def build_browse_payloads(work_entries, work_airings, all_rows5, all_brc_rows,
                           composer_slug_of, composer_display_of,
                           work_slug_of, recs, cons, *,
                           composer_entries=(), recording_rows=(),
                           form_rows=()) -> list:
    """Build the browse-table (name, payload_json) rows. PURE.

    work_entries:      build_work_index entries WITH canonical slugs overlaid.
    work_airings:      {(ck, wk): [(bdate, rp_or_None, performers, ep, pos), ...]}.
    all_rows5:         the whole-corpus projected 5-tuple ranking rows
                       (title, composer, composer_line, performers, bdate) --
                       feeds compute_year_breakdown.
    all_brc_rows:      whole-corpus (record_label, recording_pid) pairs from
                       ttn_broadcasters.load_rows(conn).
    composer_slug_of:  {composer_key: composer_slug}.
    composer_display_of: {composer_key: corpus-wide best-spelling display} --
                       the SSOT for a composer's shown name (see
                       build_work_rows); an empty-composer work falls back to
                       the work entry's own per-work spelling.
    work_slug_of:      {(ck, wk): slug}.
    recs / cons:       whole-corpus ttn_spine.build_recordings/
                       build_contributors dicts (as in build_work_rows).

    composer_entries:  build_composer_index entries (keyword-only). Feeds the
                       `composers` payload; omitted -> that payload is empty.
    recording_rows:    the BUILT recordings-table row tuples (keyword-only;
                       build_recording_rows output). Feeds `top_performances`
                       from the exact rows the recordings table gets, so every
                       link is closure-safe by construction; omitted -> empty.
    form_rows:         the BUILT forms-table row tuples (keyword-only;
                       build_form_rows output). Feeds the `forms` listing
                       payload from the exact rows the forms table gets
                       (closure-safe by construction); omitted -> empty.

    Returns [(name, payload_json), ...] with TEN payloads:
      top_works        -- top 100 work entries by airings.
      lengths           -- works classified short/medium/long by the
                           AIRING-WEIGHTED median duration of their measured
                           (2012+) performances, ranked by total airings
                           within each class (top _LENGTH_TOP_N). A dict:
                           {"short_max", "long_min", "short", "medium",
                           "long"}. Per-WORK classification by design --
                           per-performance classes would list one work in
                           two sections (the Faune straddle).
      top_performances -- top 100 recordings by airings (the most-repeated
                          individual performances; 2012+ by construction --
                          recordings are segment-era). A row whose work_slug
                          is unset or unknown to work_entries is skipped
                          (nothing to display; cannot occur at top-100
                          airings in a real corpus).
      composers         -- top 100 composer entries by airings.
      ensembles         -- combined Orchestra/Ensemble/Choir identity ranking
                           (2012+ segment metadata; one COMBINED table, not
                           role sections -- the BBC role tag is known-wrong at
                           the ~300-airing scale, and sectioning would turn
                           that into invisible dropouts). A DICT, not a list:
                           {"cut", "total", "rows"} -- rows are the identities
                           at/above _ENSEMBLES_AIRINGS_CUT airings (a quality
                           line, stated in the page blurb), total is ALL
                           distinct identities (feeds the home-page stat).
                           Link-less by design: no /ensemble/ entity pages
                           (deliberately deferred -- publishing frozen slugs
                           onto identities still being consolidated would
                           trade cheap alias folds for registry remaps).
      forms             -- the compositional-form listing behind the
                           /form/{slug}/ drill-in pages: one entry per built
                           forms-table row (airings-DESC), whole-corpus
                           (title-based classification spans both lineages).
      christmas         -- the seasonal topic page (Nick-approved 2026-07-17):
                           a dict {window, top_works, nights}. top_works =
                           the works most aired on the _CHRISTMAS_MMDD nights
                           (top 50, ranked by IN-WINDOW airings; whole
                           corpus); nights = every corpus broadcast date in
                           the window, newest first (each has an episode-date
                           page -- the "spider off into each year's
                           broadcast" links).
      years             -- compute_year_breakdown(all_rows5), serialized as-is.
      broadcasters      -- corpus-wide EBU ranking (same dict shape as a work
                           facet's broadcasters list).
      house_performances -- for each of the top-50 works by total airings, its
                           dominant 2016+ recording + that recording's share
                           of the work's 2016+ recording-anchored airings.
                           A work with no 2016+ recorded airing is skipped.
                           (Site-facing name; "recording" -> "performance"
                           rename 2026-07-16.)
    """
    # top_works: rank ALL work entries by total airings, take the top 100.
    ranked = sorted(
        work_entries,
        key=lambda e: (-len(work_airings.get(e["key"], [])), e["slug"]))
    top_works = [
        {
            "slug": e["slug"],
            "display": e["work_display"],
            "composer_display": composer_display_of.get(e["key"][0]) or e["composer_display"],
            "composer_slug": composer_slug_of.get(e["key"][0]),
            "airings": len(work_airings.get(e["key"], [])),
        }
        for e in ranked[:100]
    ]

    # composers: rank composer entries by total airings, take the top 100
    # (the composer-side parallel to top_works).
    ranked_composers = sorted(
        composer_entries, key=lambda c: (-c["airings"], c["slug"]))
    composers = [
        {
            "slug": c["slug"],
            "display": c["display"],
            "airings": c["airings"],
            "n_works": c["n_works"],
        }
        for c in ranked_composers[:100]
    ]

    # top_performances: the most-aired individual recordings, from the same
    # rows destined for the recordings table. Display strings join via
    # work_entries (the recordings schema carries slugs only).
    disp_of = {
        e["slug"]: (e["work_display"],
                    composer_display_of.get(e["key"][0]) or e["composer_display"])
        for e in work_entries
    }
    top_performances = []
    for r in sorted(recording_rows, key=lambda r: (-r[5], r[0])):
        if len(top_performances) == 100:
            break
        rp, work_slug, composer_slug_val, airings = r[0], r[1], r[2], r[5]
        if work_slug not in disp_of:
            continue
        work_display, composer_display = disp_of[work_slug]
        clist = cons.get(rp, [])
        top_performances.append({
            "recording_pid": rp,
            "work_slug": work_slug,
            "work_display": work_display,
            "composer_slug": composer_slug_val,
            "composer_display": composer_display,
            "airings": airings,
            "conductors": [c.display_name for c in clist if c.role == "Conductor"],
            "ensembles": [c.display_name for c in clist
                          if c.role in ("Ensemble", "Orchestra")],
            "soloists": [c.display_name for c in clist
                         if c.role in ("Performer", "Singer", "Choir")],
        })

    # ensembles: combined-role identity ranking over the whole-corpus spine
    # structures (already built by the caller -- near-zero marginal cost),
    # cut at the airings quality line. total counts EVERY identity (the
    # home-page stat), rows only those above the cut.
    ens_stats = ttn_spine.rank_contributors(recs, cons, _ENSEMBLE_ROLES)
    ensembles = {
        "cut": _ENSEMBLES_AIRINGS_CUT,
        "total": len(ens_stats),
        "rows": [
            {"display": s.display_name, "airings": s.airings,
             "performances": s.recordings}
            for s in ens_stats if s.airings >= _ENSEMBLES_AIRINGS_CUT
        ],
    }

    # lengths: works classified short/medium/long by the AIRING-WEIGHTED
    # median duration of their measured performances (2012+ -- duration is
    # segment metadata; a work with no measured performance is absent).
    # Ranked by the work's TOTAL airings within each class, top 25.
    dur_weights: dict = {}          # work_slug -> [(duration, airings)]
    for r in recording_rows:
        if r[1] and r[3] is not None:
            dur_weights.setdefault(r[1], []).append((r[3], r[5]))
    length_sections = {"short": [], "medium": [], "long": []}
    for e in ranked:                # already airings-DESC over all works
        pairs = dur_weights.get(e["slug"])
        if not pairs:
            continue
        med = _weighted_median(pairs)
        cls = ("short" if med < _LENGTH_SHORT_MAX
               else "long" if med >= _LENGTH_LONG_MIN else "medium")
        section = length_sections[cls]
        if len(section) == _LENGTH_TOP_N:
            continue
        section.append({
            "slug": e["slug"],
            "display": e["work_display"],
            "composer_display": composer_display_of.get(e["key"][0]) or e["composer_display"],
            "composer_slug": composer_slug_of.get(e["key"][0]),
            "airings": len(work_airings.get(e["key"], [])),
            "median_seconds": med,
        })
    lengths = {"short_max": _LENGTH_SHORT_MAX, "long_min": _LENGTH_LONG_MIN,
               **length_sections}

    # forms: the listing rows behind the per-form pages, straight from the
    # built table tuples (slug, airings, n_works, terms_json, top_works_json)
    # -- already airings-DESC.
    forms = [
        {"slug": r[0], "display": r[0].capitalize(),
         "airings": r[1], "n_works": r[2]}
        for r in form_rows
    ]

    # christmas: rank works by their airings on the Christmas-window nights;
    # collect every in-window broadcast date (episode-date pages exist for
    # all of them -- the render crawl backstops the links).
    xmas_counts: dict = {}
    xmas_nights: set = set()
    for e in work_entries:
        n = 0
        for (bd, _rp, _p, _ep, _pos) in work_airings.get(e["key"], []):
            if bd and bd[5:] in _CHRISTMAS_MMDD:
                n += 1
                xmas_nights.add(bd)
        if n:
            xmas_counts[e["slug"]] = (n, e)
    xmas_top = [
        {
            "slug": e["slug"],
            "display": e["work_display"],
            "composer_display": composer_display_of.get(e["key"][0]) or e["composer_display"],
            "composer_slug": composer_slug_of.get(e["key"][0]),
            "airings": n,
        }
        for n, e in sorted(xmas_counts.values(),
                            key=lambda ne: (-ne[0], ne[1]["slug"]))[:_CHRISTMAS_TOP_N]
    ]
    christmas = {"window": list(_CHRISTMAS_MMDD), "top_works": xmas_top,
                 "nights": sorted(xmas_nights, reverse=True)}

    # Years browse renders newest-first (compute_year_breakdown is chronological).
    years = list(reversed(compute_year_breakdown(all_rows5)))

    # Recognized EBU rows carry their drill-in page slug; the OTHER/
    # UNATTRIBUTED accounting buckets stay link-less.
    minted_slugs = mint_broadcaster_slugs()
    broadcasters_stats = ttn_broadcasters.rank_broadcasters(
        all_brc_rows, rank_key=ttn_broadcasters.broadcaster_key)
    broadcasters = []
    for s in broadcasters_stats:
        d = _broadcaster_stat_dict(s)
        d["slug"] = minted_slugs[s.key][0] if s.key in minted_slugs else None
        broadcasters.append(d)

    # house_performances: top-50 works by total airings; within each, restrict
    # to 2016+ recording-anchored airings and find the dominant recording_pid.
    house_performances = []
    for e in ranked[:50]:
        ck, wk = e["key"]
        airings = work_airings.get((ck, wk), [])
        rp_2016_counts: dict = {}
        for bd, rp, _p, _ep, _pos in airings:
            # rp not in recs: a spine-excluded recording (interstitial /
            # skip class) has no recordings-table page, so it can neither
            # be the house recording nor count in the share denominator --
            # structural, mirroring _work_facets' recs-intersection, rather
            # than relying on check_closure to catch the dangling pid.
            if rp is None or rp not in recs or not bd or bd < "2016-01-01":
                continue
            rp_2016_counts[rp] = rp_2016_counts.get(rp, 0) + 1

        total_2016 = sum(rp_2016_counts.values())
        if total_2016 == 0:
            continue

        dominant_rp = min(
            rp_2016_counts,
            key=lambda rp: (-rp_2016_counts[rp], rp))
        rec_airings = rp_2016_counts[dominant_rp]
        share_pct = round(rec_airings / total_2016 * 100)

        clist = cons.get(dominant_rp, [])
        house_performances.append({
            "work_slug": e["slug"],
            "work_display": e["work_display"],
            "composer_display": composer_display_of.get(ck) or e["composer_display"],
            "composer_slug": composer_slug_of.get(ck),
            "recording_pid": dominant_rp,
            "rec_airings": rec_airings,
            "total_2016": total_2016,
            "share_pct": share_pct,
            "conductors": [c.display_name for c in clist if c.role == "Conductor"],
            "ensembles": [c.display_name for c in clist
                          if c.role in ("Ensemble", "Orchestra")],
            "soloists": [c.display_name for c in clist
                         if c.role in ("Performer", "Singer", "Choir")],
        })

    return [
        ("top_works", json.dumps(top_works)),
        ("top_performances", json.dumps(top_performances)),
        ("composers", json.dumps(composers)),
        ("ensembles", json.dumps(ensembles)),
        ("lengths", json.dumps(lengths)),
        ("forms", json.dumps(forms)),
        ("christmas", json.dumps(christmas)),
        ("years", json.dumps(years)),
        ("broadcasters", json.dumps(broadcasters)),
        ("house_performances", json.dumps(house_performances)),
    ]


_YEAR_PAGE_TOP_N = 50


def build_year_rows(work_entries, work_airings, composer_slug_of,
                    composer_display_of, work_slug_of) -> list:
    """Build years-table row tuples -- the per-year DRILL-IN pages (distinct
    from the browse 'years' payload, which is just the year list). PURE.

    For every broadcast year seen in work_airings, aggregates that year's
    airings into a top-50 works ranking and a top-50 composers ranking (each
    by airings that year, ties broken by slug), plus the year's distinct-work
    and distinct-composer counts. An airing with no bdate is skipped (it can't
    be dated to a year). work_airings already excludes the both-key-empty junk
    rows (accumulate_entities), so a year with ONLY junk airings would not get
    a page here; it can't occur in a real corpus (every year has keyed
    airings) and the render crawl backstops any browse-Years link that
    somehow outran a page.

    work_entries:      build_work_index entries WITH canonical slugs overlaid
                       (source of work_display per key).
    work_airings:      {(ck, wk): [(bdate, rp_or_None, performers, ep, pos), ...]}.
    composer_slug_of:  {composer_key: composer_slug}.
    composer_display_of: {composer_key: corpus-wide best-spelling display} (SSOT).
    work_slug_of:      {(ck, wk): slug}.

    Returns a list of 6-tuples in years-schema column order, year-ASCENDING:
      (year, airings, n_works, n_composers, top_works_json, top_composers_json)
    (the renderer orders the page lists; the browse index orders the years).
    """
    work_meta = {e["key"]: e["work_display"] for e in work_entries}

    year_work_counts: dict = {}       # year -> {(ck,wk): count}
    year_composer_counts: dict = {}   # year -> {ck: count}
    year_airings: dict = {}           # year -> total

    for (ck, wk), airings in work_airings.items():
        for (bd, _rp, _perf, _ep, _pos) in airings:
            if not bd:
                continue
            yr = bd[:4]
            year_work_counts.setdefault(yr, {})
            year_work_counts[yr][(ck, wk)] = year_work_counts[yr].get((ck, wk), 0) + 1
            year_composer_counts.setdefault(yr, {})
            year_composer_counts[yr][ck] = year_composer_counts[yr].get(ck, 0) + 1
            year_airings[yr] = year_airings.get(yr, 0) + 1

    rows = []
    for yr in sorted(year_work_counts):
        wc = year_work_counts[yr]
        cc = year_composer_counts[yr]

        top_works = []
        for (ck, wk), count in sorted(wc.items(), key=lambda kv: (-kv[1], work_slug_of.get(kv[0], ""))):
            slug = work_slug_of.get((ck, wk))
            if slug is None:
                continue                       # unslugged (empty-key) work: no page
            top_works.append({
                "slug": slug,
                "display": work_meta.get((ck, wk), ""),
                "composer_display": composer_display_of.get(ck) or "",
                "composer_slug": composer_slug_of.get(ck),
                "airings": count,
            })
            if len(top_works) >= _YEAR_PAGE_TOP_N:
                break

        top_composers = []
        for ck, count in sorted(cc.items(), key=lambda kv: (-kv[1], composer_slug_of.get(kv[0], ""))):
            slug = composer_slug_of.get(ck)
            if slug is None:
                continue                       # empty composer key: no page
            top_composers.append({
                "slug": slug,
                "display": composer_display_of.get(ck) or "",
                "airings": count,
            })
            if len(top_composers) >= _YEAR_PAGE_TOP_N:
                break

        rows.append((
            yr,
            year_airings[yr],
            len(wc),
            len(cc),
            json.dumps(top_works),
            json.dumps(top_composers),
        ))
    return rows


# Per-form drill-in page rank cut (matches the per-year pages).
_FORM_PAGE_TOP_N = 50


def _form_matchers() -> dict:
    """{canonical form name: compiled regex} from ttn_analyze._FORM_SYNONYMS.
    Each pattern is the exact `--form` predicate lifted into one alternation:
    word-boundary, ascii-folded, case-insensitive terms -- so 'concerto'
    never matches 'concertino' and 'Prélude' folds onto 'prelude'. Matching
    is against ascii_fold(title), mirroring the CLI's
    `ascii_fold(t.title) REGEXP` clause."""
    matchers = {}
    for name, terms in _FORM_SYNONYMS.items():
        folded = list(dict.fromkeys(re.escape(ascii_fold(t)) for t in terms))
        matchers[name] = re.compile(
            r"\b(?:" + "|".join(folded) + r")\b", re.IGNORECASE)
    return matchers


def build_form_rows(work_entries, work_airings, composer_slug_of,
                    composer_display_of) -> list:
    """Build forms-table row tuples -- the per-form drill-in pages behind
    /form/{slug}/. PURE.

    A work belongs to a form when its DISPLAY TITLE names it (word-boundary,
    diacritic-insensitive -- the exact `--form` semantics, via
    _form_matchers). Classification is title-based, so it spans BOTH lineages
    (no 2012+ scope stamp needed, unlike lengths). A work naming several
    forms counts under EVERY one ('Waltz... dance...' lands in both) -- the
    multi-form share was measured at ~4% and sectioning would silently drop
    it from one home. The known residue is honest: ~43% of the corpus is
    name-titled (no form word) and appears under no form, and an excerpt
    whose display cites its parent ('Air (Suite in D...)') counts under the
    parent's form word, same as the CLI filter.

    Slugs are the canonical form names themselves (already lowercase-ascii
    single words -- no registry namespace, the broadcaster precedent).

    Returns 5-tuples in forms-schema column order, airings-DESC (tie: slug):
      (slug, airings, n_works, terms_json, top_works_json)
    top_works is the form's top _FORM_PAGE_TOP_N works by total airings;
    terms_json is the synonym tuple as written in the vocabulary (the page
    states its matching honestly). A form matching zero works gets no row."""
    matchers = _form_matchers()

    matched: dict = {}          # form name -> [(airings, entry)]
    for e in work_entries:
        folded_title = ascii_fold(e["work_display"])
        n = len(work_airings.get(e["key"], []))
        for name, rx in matchers.items():
            if rx.search(folded_title):
                matched.setdefault(name, []).append((n, e))

    rows = []
    for name, hits in matched.items():
        hits.sort(key=lambda ne: (-ne[0], ne[1]["slug"]))
        top_works = [
            {
                "slug": e["slug"],
                "display": e["work_display"],
                "composer_display": composer_display_of.get(e["key"][0]) or e["composer_display"],
                "composer_slug": composer_slug_of.get(e["key"][0]),
                "airings": n,
            }
            for n, e in hits[:_FORM_PAGE_TOP_N]
        ]
        rows.append((
            name,
            sum(n for n, _e in hits),
            len(hits),
            json.dumps(list(_FORM_SYNONYMS[name])),
            json.dumps(top_works),
        ))

    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


# --- frozen slug registry ---------------------------------------------------
# ttn_site_registry.json gives every work/composer identity a PERMANENT slug.
# Once registered, the slug never moves on its own -- a canonicalization edit
# that changes the derived slug is reported (report["slug_drift"]) but not
# applied; a registered identity that vanishes from the current corpus is a
# hard failure (RegistryDriftError), not a silent drop. See global-context.md
# "Design decision locked".

class RegistryDriftError(Exception):
    """Raised by sync_registry when a REGISTERED identity (work or composer)
    is absent from the current derived entries -- an alias/gate edit moved
    or removed a group key out from under a frozen slug. Lists every orphaned
    slug found (not just the first) so one sync surfaces the whole remap job.
    Fix: the explicit --remap admin action (a later task), not a re-sync."""


def _empty_registry():
    return {"version": 1, "works": {}, "composers": {},
            "redirects": {"works": {}, "composers": {}}}


def load_registry(path=REGISTRY_PATH):
    """Load the slug registry. Missing file -> a fresh empty v1 shell (first
    run). A file that exists but is corrupt JSON or the wrong shape is a HARD
    error -- unlike the derived caches (missing/corrupt -> degrade), this is a
    git-tracked, human-consequential file, so silent degradation would mean
    silently reassigning URLs. Shape check is shallow (top-level keys present
    with the right container types), not a full schema validation."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return _empty_registry()

    required = ("version", "works", "composers", "redirects")
    if not isinstance(data, dict) or any(k not in data for k in required):
        raise ValueError(f"{path}: not a valid registry (missing top-level key)")
    if not isinstance(data["works"], dict) or not isinstance(data["composers"], dict):
        raise ValueError(f"{path}: 'works'/'composers' must be objects")
    redirects = data["redirects"]
    if (not isinstance(redirects, dict)
            or not isinstance(redirects.get("works"), dict)
            or not isinstance(redirects.get("composers"), dict)):
        raise ValueError(f"{path}: 'redirects' must be {{'works': {{}}, 'composers': {{}}}}")
    return data


def dump_registry(registry, path=REGISTRY_PATH):
    """Write the registry as deterministic, git-reviewable bytes (sorted
    keys, indent=2, trailing newline). Atomic: writes path+'.tmp' then
    os.replace, so a killed write can never leave a truncated tracked file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _unique_slug(base_slug, taken):
    """First of base_slug, base_slug-2, base_slug-3, ... not in `taken`."""
    if base_slug not in taken:
        return base_slug
    n = 2
    while f"{base_slug}-{n}" in taken:
        n += 1
    return f"{base_slug}-{n}"


def _sync_namespace(registered, redirected_keys, entries, identity_of, slug_of,
                     today, record_key):
    """Shared engine for one namespace (works or composers).

    registered:       {slug: entry-dict} from the registry (NOT mutated)
    redirected_keys:   set of slugs that are redirect sources in this namespace
    entries:           derived entries (work_entries or composer_entries)
    identity_of(entry): the identity key (a tuple for works, a str for composers)
    slug_of(entry):     the entry's derived slug
    record_key(identity, published) -> dict to store under the winning slug

    Returns (new_registered, added_count, slug_drift, collisions, orphans).
    orphans = registered slugs whose identity is absent from `entries` (for
    the caller to collect across both namespaces before raising).
    """
    inverse = {v_identity: slug for slug, v_identity in
               ((s, identity_of.from_stored(e)) for s, e in registered.items())}
    # inverse index {identity_key: slug} for registered entries, and the
    # reverse for detecting orphans -- built from the entry data itself so
    # both namespaces share this helper (identity_of.from_stored parses the
    # stored dict back into the same identity shape as identity_of(entry)).

    derived_by_identity = {identity_of(e): e for e in entries}

    orphans = [slug for slug, identity in
               ((s, identity_of.from_stored(e)) for s, e in registered.items())
               if identity not in derived_by_identity]

    new_registered = dict(registered)
    taken = set(registered.keys()) | set(redirected_keys)
    added = 0
    slug_drift = []
    collisions = []

    # deterministic order: sort new identities before assigning suffixes
    new_identities = sorted(
        (identity_of(e) for e in entries if identity_of(e) not in inverse),
        key=lambda k: (k if isinstance(k, tuple) else (k,)))

    for identity in new_identities:
        entry = derived_by_identity[identity]
        base_slug = slug_of(entry)
        assigned = _unique_slug(base_slug, taken)
        if assigned != base_slug:
            collisions.append((identity, base_slug, assigned))
        taken.add(assigned)
        new_registered[assigned] = record_key(identity, today)
        added += 1

    # frozen identities: report derived-slug divergence, change nothing
    for identity, slug in inverse.items():
        if identity in derived_by_identity:
            derived_slug = slug_of(derived_by_identity[identity])
            if derived_slug != slug:
                slug_drift.append((slug, derived_slug))

    return new_registered, added, slug_drift, collisions, orphans


class _WorkIdentity:
    """identity_of callable for the works namespace, plus the inverse parse
    (from_stored) needed to rebuild identities from registry entries."""
    def __call__(self, entry):
        return entry["key"]

    @staticmethod
    def from_stored(stored):
        return (stored["composer_key"], stored["work_key"])


class _ComposerIdentity:
    def __call__(self, entry):
        return entry["composer_key"]

    @staticmethod
    def from_stored(stored):
        return stored["composer_key"]


_work_identity = _WorkIdentity()
_composer_identity = _ComposerIdentity()


def sync_registry(registry, work_entries, composer_entries, today):
    """Reconcile the frozen slug registry against the current corpus. PURE:
    no I/O, does not mutate `registry` -- returns a new (registry, report).

    today: 'YYYY-MM-DD' string stamped onto newly-registered entries
           (caller-supplied so the function stays deterministic/testable).

    Semantics:
      - a derived identity NOT already registered -> registered under its
        derived slug (or a '-2', '-3', ... suffix on collision), published
        = today.
      - a REGISTERED identity keeps its registered slug forever, even when
        the derived slug for that identity has since changed (informational
        report["slug_drift"], mapping unchanged).
      - a REGISTERED identity absent from the current derived entries is a
        RegistryDriftError -- collected across BOTH namespaces before
        raising, so one error message lists every orphan. Nothing is
        returned or written in this case.

    report keys:
      added_works, added_composers -- counts of newly-registered identities
      slug_drift  -- list of (registered_slug, derived_slug) pairs, both
                     namespaces pooled
      collisions  -- list of (identity, base_slug, assigned_slug) tuples for
                     newly-registered identities that needed a suffix
    """
    new_works, added_works, work_drift, work_collisions, work_orphans = \
        _sync_namespace(registry["works"], registry["redirects"]["works"],
                         work_entries, _work_identity,
                         lambda e: e["slug"], today,
                         lambda identity, published: {
                             "composer_key": identity[0], "work_key": identity[1],
                             "published": published})

    new_composers, added_composers, composer_drift, composer_collisions, composer_orphans = \
        _sync_namespace(registry["composers"], registry["redirects"]["composers"],
                         composer_entries, _composer_identity,
                         lambda e: e["slug"], today,
                         lambda identity, published: {
                             "composer_key": identity, "published": published})

    if work_orphans or composer_orphans:
        raise RegistryDriftError(
            "registered identity missing from the current corpus -- "
            f"orphaned work slugs: {sorted(work_orphans)}; "
            f"orphaned composer slugs: {sorted(composer_orphans)}")

    new_registry = {
        "version": registry["version"],
        "works": new_works,
        "composers": new_composers,
        "redirects": {
            "works": dict(registry["redirects"]["works"]),
            "composers": dict(registry["redirects"]["composers"]),
        },
    }
    report = {
        "added_works": added_works,
        "added_composers": added_composers,
        "slug_drift": work_drift + composer_drift,
        "collisions": work_collisions + composer_collisions,
    }
    return new_registry, report


# --- admin actions -----------------------------------------------------------
# Deliberate, explicit registry surgery -- the counterpart to sync_registry's
# hands-off drift detection. Both are PURE (registry in, new registry out;
# never mutate the input) so main() stays a thin load/modify/dump/report shell.

class RegistryActionError(Exception):
    """Raised by an admin action (apply_rename/apply_remap) when the requested
    surgery is unsafe -- e.g. the target slug is already taken, or the source
    slug isn't registered at all. main() reports this and exits 1 without
    writing the registry."""


def _namespace_identity(namespace, stored):
    if namespace == "works":
        return (stored["composer_key"], stored["work_key"])
    return stored["composer_key"]


def apply_rename(registry, namespace, old, new):
    """Move the registration at slug `old` to slug `new` (same identity,
    same published date), leaving redirects[namespace][old] = new. Refuses
    (RegistryActionError, registry unchanged) if `old` isn't registered, or
    if `new` is already taken -- either a live registration or an existing
    redirect source -- in that namespace."""
    registered = registry[namespace]
    redirects = registry["redirects"][namespace]
    if old not in registered:
        raise RegistryActionError(f"{namespace}: {old!r} is not registered")
    if new in registered:
        raise RegistryActionError(
            f"{namespace}: {new!r} is already registered (to "
            f"{_namespace_identity(namespace, registered[new])!r})")
    if new in redirects:
        raise RegistryActionError(
            f"{namespace}: {new!r} is already a redirect (to {redirects[new]!r})")

    new_registered = dict(registered)
    entry = new_registered.pop(old)
    new_registered[new] = entry
    new_redirects = dict(redirects)
    new_redirects[old] = new

    new_registry = _with_namespace(registry, namespace, new_registered, new_redirects)
    return new_registry


def apply_remap(registry, namespace, slug, composer_key, work_key=None):
    """Re-point an orphaned registered `slug` at its successor identity (the
    alias-fold recovery path: a canonicalization edit moved the group key an
    old slug pointed at). If the successor identity is ALREADY registered
    under some OTHER slug, `slug` instead becomes a redirect to that slug and
    its own registration is removed (two slugs must never both claim to be
    canonical for one identity). Otherwise `slug`'s stored identity is
    updated in place (published date preserved). Refuses (RegistryActionError,
    registry unchanged) if `slug` isn't registered."""
    registered = registry[namespace]
    redirects = registry["redirects"][namespace]
    if slug not in registered:
        raise RegistryActionError(f"{namespace}: {slug!r} is not registered")

    target_identity = (composer_key, work_key) if namespace == "works" else composer_key

    existing_slug = None
    for s, stored in registered.items():
        if s == slug:
            continue
        if _namespace_identity(namespace, stored) == target_identity:
            existing_slug = s
            break

    new_registered = dict(registered)
    new_redirects = dict(redirects)
    if existing_slug is not None:
        del new_registered[slug]
        new_redirects[slug] = existing_slug
    else:
        published = registered[slug]["published"]
        if namespace == "works":
            new_registered[slug] = {"composer_key": composer_key, "work_key": work_key,
                                     "published": published}
        else:
            new_registered[slug] = {"composer_key": composer_key, "published": published}

    return _with_namespace(registry, namespace, new_registered, new_redirects)


def _with_namespace(registry, namespace, registered, redirects):
    """New registry dict with `namespace`'s registered map and redirect map
    replaced; the other namespace and 'version' pass through unchanged."""
    other = "composers" if namespace == "works" else "works"
    return {
        "version": registry["version"],
        namespace: registered,
        other: dict(registry[other]),
        "redirects": {
            namespace: redirects,
            other: dict(registry["redirects"][other]),
        },
    }


# --- site.sqlite: schema, fingerprint, atomic write, status -----------------
# JSON-blob facets by design (see task brief): the renderer consumes one dict
# per page: relational decomposition of the *_json columns buys nothing here.
# The tables below are content-EMPTY as of this task; Tasks 5-7 populate them.

# --- artist registry-lite ----------------------------------------------------
# ttn_site_artist_registry.json gives each MBID-backed contributor identity a
# PERMANENT /artist/ slug. Deliberately NOT the frozen works/composers
# registry: the binding is to the MusicBrainz MBID, so a name->MBID alias
# fold merges airings into the existing page and moves no URL -- there is no
# freeze/drift-failure/remap workflow at all. Mint once, keep forever (an
# identity later dropping below the airings cut keeps its page; no dead
# URLs). Git-tracked decisions file: corrupt = HARD ERROR, never degrade.
# Design: docs/superpowers/specs/2026-07-17-contributor-entity-pages-design.md

ARTIST_REGISTRY_PATH = "ttn_site_artist_registry.json"


def artist_registry_path():
    """Absolute path to the artist registry, beside this module (mirrors
    registry_path)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ARTIST_REGISTRY_PATH)


def _empty_artist_registry():
    return {"version": 1, "artists": {}, "redirects": {}}


def load_artist_registry(path=ARTIST_REGISTRY_PATH):
    """Load the artist registry. Missing file -> a fresh empty v1 shell
    (first run). Corrupt JSON or wrong shape -> HARD error (the decisions-
    file rule, exactly like load_registry): silent degradation would mean
    silently reassigning URLs."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return _empty_artist_registry()

    required = ("version", "artists", "redirects")
    if not isinstance(data, dict) or any(k not in data for k in required):
        raise ValueError(f"{path}: not a valid artist registry (missing top-level key)")
    if not isinstance(data["artists"], dict) or not isinstance(data["redirects"], dict):
        raise ValueError(f"{path}: 'artists'/'redirects' must be objects")
    return data


def dump_artist_registry(registry, path=ARTIST_REGISTRY_PATH):
    """Deterministic, git-reviewable bytes; atomic tmp+os.replace (the
    dump_registry contract)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


# Airings cut for MINTING an /artist/ page (the ensembles-listing precedent).
# Applies at mint time only: an already-registered artist later dropping
# below it keeps its page (mint once, keep forever).
_ARTIST_AIRINGS_CUT = 50

# Role groupings for artist qualification/facets. One MBID can hold several
# roles; the people-set and group-set are ranked separately (each role set
# dedupes identity-per-rp inside rank_contributors) and 'person' wins a
# dual-qualified MBID.
_ARTIST_PEOPLE_ROLES = frozenset(("Conductor", "Performer", "Singer"))
_ARTIST_GROUP_ROLES = frozenset(("Ensemble", "Orchestra", "Choir"))


def artist_qualifiers(recs, cons):
    """The gate: [(mbid, display)] for every MBID-backed identity at/above
    _ARTIST_AIRINGS_CUT combined-role airings, in DETERMINISTIC mint order
    (airings-DESC, then mbid) -- feeds sync_artist_registry. A name-keyed
    identity never qualifies (the MBID-only gate: no stable anchor, no URL).
    An MBID qualifying on both the people and group sets appears once
    (people stat wins -- the soloist-director case)."""
    people = ttn_spine.rank_contributors(recs, cons, _ARTIST_PEOPLE_ROLES)
    groups = ttn_spine.rank_contributors(recs, cons, _ARTIST_GROUP_ROLES)
    best = {}
    for stats in (people, groups):          # people first: wins dual-qualified
        for s in stats:
            if s.mbid and s.airings >= _ARTIST_AIRINGS_CUT and s.mbid not in best:
                best[s.mbid] = s
    ordered = sorted(best.values(), key=lambda s: (-s.airings, s.mbid))
    return [(s.mbid, s.display_name) for s in ordered]


def build_artist_rows(registry, recs, cons, brc_rows_by_rp, rec_rows,
                      work_entries, composer_display_of) -> list:
    """Build artists-table row tuples. PURE. The SYNCED registry is the page-
    list authority: one row per registered slug whose MBID still has spine
    recordings (mint once, keep forever -- a below-cut drop keeps its page;
    only an MBID that vanished from the corpus entirely emits no row).

    registry:          the artist registry AFTER sync_artist_registry.
    recs / cons / brc_rows_by_rp: the whole-corpus spine/broadcaster
                       structures (as build_work_rows/build_composer_rows).
    rec_rows:          the BUILT recordings-table tuples -- rp->work/composer
                       slugs and per-airing dates come from here, so links
                       agree with the recordings table by construction.
    work_entries:      build_work_index entries WITH canonical slugs.
    composer_display_of: {composer_key: corpus display} -- the composer-
                       display SSOT (every facet's composer spelling comes
                       from it, per-work spelling only as fallback).

    Returns 10-tuples in artists-schema column order, airings-DESC (tie slug):
      (slug, mbid, display, kind, roles_json, airings, n_recordings,
       first_aired, last_aired, facets_json)

    display is the CURRENT corpus display (rank stat), never display_at_mint
    -- the shown name evolves with the corpus, the URL does not. kind =
    'person' when the MBID ranks on the people role-set (wins dual), else
    'ensemble'. facets_json: top_works / top_composers / collaborators
    {conductors, soloists, ensembles} (self excluded; each entry carries the
    collaborator's artist slug when registered, else null) / by_year (from
    rec_rows' airing dates -- 2012+ by construction) / broadcasters /
    performances (top 15 by airings, closure-safe via rec_rows)."""
    people_by_mbid = {s.mbid: s for s in ttn_spine.rank_contributors(
        recs, cons, _ARTIST_PEOPLE_ROLES) if s.mbid}
    group_by_mbid = {s.mbid: s for s in ttn_spine.rank_contributors(
        recs, cons, _ARTIST_GROUP_ROLES) if s.mbid}

    slug_by_mbid = {v["mbid"]: slug for slug, v in registry["artists"].items()}

    rec_meta = {r[0]: (r[1], r[2]) for r in rec_rows}   # rp -> (work_slug, composer_slug)
    dates_by_rp = {r[0]: [d for d, _ep in json.loads(r[9] or "[]")]
                   for r in rec_rows}
    disp_of = {
        e["slug"]: (e["work_display"],
                    composer_display_of.get(e["key"][0]) or e["composer_display"])
        for e in work_entries
    }

    rps_of_mbid: dict = {}
    roles_of_mbid: dict = {}
    for rp, clist in cons.items():
        if rp not in recs:
            continue
        for c in clist:
            if c.mbid:
                rps_of_mbid.setdefault(c.mbid, set()).add(rp)
                roles_of_mbid.setdefault(c.mbid, set()).add(c.role)

    rows = []
    for slug, entry in registry["artists"].items():
        mbid = entry["mbid"]
        rps = rps_of_mbid.get(mbid, set())
        if not rps:
            continue                        # vanished from the corpus entirely

        stat = people_by_mbid.get(mbid) or group_by_mbid.get(mbid)
        kind = "person" if mbid in people_by_mbid else "ensemble"

        first = min(recs[rp].first_aired for rp in rps)
        last = max(recs[rp].last_aired for rp in rps)

        # top works / composers, weighted by each recording's airing count
        work_counts: dict = {}
        composer_counts: dict = {}          # composer_slug -> [airings, display]
        for rp in rps:
            ws, cslug = rec_meta.get(rp, (None, None))
            if ws not in disp_of:
                continue
            n = recs[rp].airing_count
            work_counts[ws] = work_counts.get(ws, 0) + n
            if cslug:
                cc = composer_counts.setdefault(cslug, [0, disp_of[ws][1]])
                cc[0] += n
        top_works = [
            {"slug": ws, "display": disp_of[ws][0],
             "composer_display": disp_of[ws][1], "airings": n}
            for ws, n in sorted(work_counts.items(),
                                 key=lambda kv: (-kv[1], kv[0]))[:10]
        ]
        top_composers = [
            {"slug": cslug, "display": disp, "airings": n}
            for cslug, (n, disp) in sorted(
                composer_counts.items(),
                key=lambda kv: (-kv[1][0], kv[0]))[:10]
        ]

        # collaborators: other contributors on the same recordings, bucketed
        # by role group, identity-deduped per rp, self excluded; linked when
        # the collaborator is themselves a registered artist.
        buckets = {"conductors": {}, "soloists": {}, "ensembles": {}}
        for rp in rps:
            n = recs[rp].airing_count
            seen = set()
            for c in cons.get(rp, []):
                if c.identity_key == mbid or c.identity_key in seen:
                    continue
                if c.role == "Conductor":
                    bucket = buckets["conductors"]
                elif c.role in ("Performer", "Singer"):
                    bucket = buckets["soloists"]
                elif c.role in _ARTIST_GROUP_ROLES:
                    bucket = buckets["ensembles"]
                else:
                    continue
                seen.add(c.identity_key)
                b = bucket.setdefault(
                    c.identity_key,
                    [0, c.display_name, slug_by_mbid.get(c.mbid)])
                b[0] += n
        collaborators = {
            name: [
                {"display": disp, "airings": n, "slug": cslug}
                for _ik, (n, disp, cslug) in sorted(
                    bucket.items(), key=lambda kv: (-kv[1][0], kv[1][1]))[:10]
            ]
            for name, bucket in buckets.items()
        }

        # by-year over the recordings' airing dates (2012+ by construction)
        year_counts: dict = {}
        for rp in rps:
            for d in dates_by_rp.get(rp, []):
                year_counts[d[:4]] = year_counts.get(d[:4], 0) + 1
        by_year = [{"year": y, "airings": n}
                   for y, n in sorted(year_counts.items(), reverse=True)]

        b_rows = [(lab, rp) for rp in rps for lab in brc_rows_by_rp.get(rp, [])]
        broadcasters = [
            _broadcaster_stat_dict(s)
            for s in ttn_broadcasters.rank_broadcasters(
                b_rows, rank_key=ttn_broadcasters.broadcaster_key)
        ]

        performances = []
        for rp in sorted(rps, key=lambda rp: (-recs[rp].airing_count, rp)):
            if len(performances) == 15:
                break
            ws, _cslug = rec_meta.get(rp, (None, None))
            if ws not in disp_of:
                continue
            performances.append({
                "recording_pid": rp,
                "work_slug": ws,
                "work_display": disp_of[ws][0],
                "composer_display": disp_of[ws][1],
                "duration": recs[rp].duration_seconds,
                "airings": recs[rp].airing_count,
                "first": recs[rp].first_aired,
                "last": recs[rp].last_aired,
            })

        facets = {
            "top_works": top_works,
            "top_composers": top_composers,
            "collaborators": collaborators,
            "by_year": by_year,
            "broadcasters": broadcasters,
            "performances": performances,
        }

        rows.append((
            slug,
            mbid,
            stat.display_name if stat else entry["display_at_mint"],
            kind,
            json.dumps(sorted(roles_of_mbid.get(mbid, set()))),
            stat.airings if stat else 0,
            stat.recordings if stat else len(rps),
            first,
            last,
            json.dumps(facets),
        ))

    rows.sort(key=lambda r: (-r[5], r[0]))
    return rows


def sync_artist_registry(registry, qualifiers, today):
    """Sync the artist registry against the current qualifier list. PURE
    (input registry never mutated).

    qualifiers: [(mbid, display), ...] for every identity passing the gate,
    in DETERMINISTIC caller-chosen order (airings-DESC then mbid) -- the
    order decides who wins a collision-free base slug first, so it must not
    depend on dict iteration.

    Rules: an mbid already registered keeps its slug and its stored record
    VERBATIM (display_at_mint is a mint-time record, never updated); a new
    mbid mints slug = composer_slug(display), collision with any existing
    slug or redirect source -> '-2'/'-3'... (_unique_slug). Entries are NEVER
    removed -- mint once, keep forever. Returns (new_registry, report) with
    report = {"added": n}."""
    artists = dict(registry["artists"])
    by_mbid = {v["mbid"]: slug for slug, v in artists.items()}
    taken = set(artists) | set(registry["redirects"])

    added = 0
    for mbid, display in qualifiers:
        if mbid in by_mbid:
            continue
        slug = _unique_slug(composer_slug(display), taken)
        artists[slug] = {"mbid": mbid, "minted": today,
                         "display_at_mint": display}
        by_mbid[mbid] = slug
        taken.add(slug)
        added += 1

    new_registry = {"version": registry.get("version", 1),
                    "artists": artists,
                    "redirects": dict(registry["redirects"])}
    return new_registry, {"added": added}


_SITE_SCHEMA = """
CREATE TABLE meta       (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE works      (slug TEXT PRIMARY KEY, composer_slug TEXT,
                         composer_key TEXT, work_key TEXT,
                         work_display TEXT, composer_display TEXT,
                         catalogue TEXT, airings INTEGER,
                         n_recordings INTEGER, n_text_only INTEGER,
                         first_aired TEXT, last_aired TEXT,
                         facets_json TEXT);
CREATE TABLE composers  (slug TEXT PRIMARY KEY, composer_key TEXT,
                         display TEXT, airings INTEGER, n_works INTEGER,
                         works_json TEXT, facets_json TEXT);
CREATE TABLE episodes   (pid TEXT PRIMARY KEY, date TEXT, title TEXT,
                         bbc_url TEXT, tracks_json TEXT);
CREATE TABLE recordings (recording_pid TEXT PRIMARY KEY, work_slug TEXT,
                         composer_slug TEXT, duration INTEGER,
                         broadcaster TEXT, airings INTEGER,
                         first_aired TEXT, last_aired TEXT,
                         contributors_json TEXT, airing_dates_json TEXT);
CREATE TABLE browse     (name TEXT PRIMARY KEY, payload_json TEXT);
CREATE TABLE years      (year TEXT PRIMARY KEY, airings INTEGER,
                         n_works INTEGER, n_composers INTEGER,
                         top_works_json TEXT, top_composers_json TEXT);
CREATE TABLE broadcasters (slug TEXT PRIMARY KEY, key TEXT, display TEXT,
                         country TEXT, airings INTEGER, n_recordings INTEGER,
                         top_works_json TEXT, top_performances_json TEXT,
                         top_ensembles_json TEXT);
CREATE TABLE forms      (slug TEXT PRIMARY KEY, airings INTEGER,
                         n_works INTEGER, terms_json TEXT,
                         top_works_json TEXT);
CREATE TABLE artists    (slug TEXT PRIMARY KEY, mbid TEXT, display TEXT,
                         kind TEXT, roles_json TEXT, airings INTEGER,
                         n_recordings INTEGER, first_aired TEXT,
                         last_aired TEXT, facets_json TEXT);
"""

# The content tables write_site_db accepts rows for (meta is stamped by
# write_site_db itself). Per-table arity is derived from the created schema
# via PRAGMA table_info, never hand-counted -- a hand-maintained count map
# drifted from the CREATE TABLE text once (works: 12 vs 13, task-4 review).
_SITE_TABLES = ("works", "composers", "episodes", "recordings", "browse",
                "years", "broadcasters", "forms", "artists")


def site_fingerprint(registry_path, artist_reg_path=None):
    """sha1 hex over, in order: this module's bytes, ttn_analyze.py,
    ttn_aliases.py, the projection cache file, the registry file at
    `registry_path`, and the artist registry (default: beside this module) --
    an artist mint must invalidate a stale site.sqlite. A missing file hashes
    as the empty string for that slot (tolerant, like
    _slug_cache_fingerprint) -- site_fingerprint itself never raises; only a
    hard build-time consumer (_run_build) treats a missing
    projection/registry as an error, and it does so explicitly, not via this
    function silently failing."""
    if artist_reg_path is None:
        artist_reg_path = artist_registry_path()
    h = hashlib.sha1()
    for path in (os.path.abspath(__file__), _ANALYZE_MODULE_PATH,
                 _ALIASES_MODULE_PATH, ttn_project.PROJECTION_PATH,
                 registry_path, artist_reg_path):
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"")
    return h.hexdigest()


def check_closure(conn) -> list:
    """Walk a BUILT site.sqlite connection and return a list of violation
    strings for every non-NULL cross-table reference that fails to resolve
    (empty list = pass). A JSON null (None) link is the deliberate junk-row
    case (a row the corpus pass couldn't key) and is never a violation --
    only a non-null dangling reference is.

    Checks, each against a PK set loaded ONCE (not a per-row query):
      - works.composer_slug in composers
      - recordings.work_slug in works; recordings.composer_slug in composers
      - every episodes.tracks_json entry: work_slug in works,
        composer_slug in composers, recording_pid in recordings
      - every composers.works_json entry's slug in works
      - every works.facets_json recordings[].recording_pid in recordings
      - browse 'top_works': slug in works, composer_slug in composers
      - browse 'top_performances': work_slug in works, composer_slug in
        composers, recording_pid in recordings
      - browse 'composers': slug in composers
      - browse 'house_performances': work_slug in works,
        composer_slug in composers, recording_pid in recordings
      - years: each per-year page's top_works[].slug/composer_slug in
        works/composers and top_composers[].slug in composers
      - browse 'broadcasters': a non-null slug in broadcasters
      - broadcasters: top_works_json[].slug in works; top_performances_json[]
        work_slug/composer_slug/recording_pid in works/composers/recordings
      - browse 'forms': slug in forms
      - forms: top_works_json[].slug/composer_slug in works/composers
      - browse 'christmas': top_works[].slug/composer_slug in works/composers
      - artists: facets top_works[].slug in works; top_composers[].slug in
        composers; performances[].recording_pid/work_slug in recordings/
        works; collaborators[*][].slug (non-null) in artists

    Each violation names the table, the row's primary key, the offending
    field path, and the dangling reference value, e.g.
    "episodes[b0abc123] tracks_json[3].work_slug 'x:y' not in works".
    """
    work_slugs = {row[0] for row in conn.execute("SELECT slug FROM works")}
    composer_slugs = {row[0] for row in conn.execute("SELECT slug FROM composers")}
    recording_pids = {row[0] for row in conn.execute("SELECT recording_pid FROM recordings")}
    broadcaster_slugs = {row[0] for row in conn.execute("SELECT slug FROM broadcasters")}
    form_slugs = {row[0] for row in conn.execute("SELECT slug FROM forms")}
    artist_slugs = {row[0] for row in conn.execute("SELECT slug FROM artists")}

    violations = []

    def _check(value, valid_set, target_name, table_name, row_key, field_path):
        if value is not None and value not in valid_set:
            violations.append(
                f"{table_name}[{row_key}] {field_path} {value!r} not in {target_name}")

    # works.composer_slug -> composers
    for slug, composer_slug_val in conn.execute(
            "SELECT slug, composer_slug FROM works"):
        _check(composer_slug_val, composer_slugs, "composers",
               "works", slug, "composer_slug")

    # recordings.work_slug -> works; recordings.composer_slug -> composers
    for rp, work_slug_val, composer_slug_val in conn.execute(
            "SELECT recording_pid, work_slug, composer_slug FROM recordings"):
        _check(work_slug_val, work_slugs, "works",
               "recordings", rp, "work_slug")
        _check(composer_slug_val, composer_slugs, "composers",
               "recordings", rp, "composer_slug")

    # episodes.tracks_json[*].{work_slug, composer_slug, recording_pid}
    for pid, tracks_json in conn.execute("SELECT pid, tracks_json FROM episodes"):
        tracks = json.loads(tracks_json) if tracks_json else []
        for i, track in enumerate(tracks):
            _check(track.get("work_slug"), work_slugs, "works",
                   "episodes", pid, f"tracks_json[{i}].work_slug")
            _check(track.get("composer_slug"), composer_slugs, "composers",
                   "episodes", pid, f"tracks_json[{i}].composer_slug")
            _check(track.get("recording_pid"), recording_pids, "recordings",
                   "episodes", pid, f"tracks_json[{i}].recording_pid")

    # composers.works_json[*].slug -> works
    for slug, works_json in conn.execute("SELECT slug, works_json FROM composers"):
        works = json.loads(works_json) if works_json else []
        for i, w in enumerate(works):
            _check(w.get("slug"), work_slugs, "works",
                   "composers", slug, f"works_json[{i}].slug")

    # works.facets_json.recordings[*].recording_pid -> recordings
    for slug, facets_json in conn.execute("SELECT slug, facets_json FROM works"):
        facets = json.loads(facets_json) if facets_json else {}
        for i, rec in enumerate(facets.get("recordings", [])):
            _check(rec.get("recording_pid"), recording_pids, "recordings",
                   "works", slug, f"facets_json.recordings[{i}].recording_pid")
            _check(rec.get("broadcaster_slug"), broadcaster_slugs, "broadcasters",
                   "works", slug, f"facets_json.recordings[{i}].broadcaster_slug")

    # browse: top_works + house_performances
    for name, payload_json in conn.execute("SELECT name, payload_json FROM browse"):
        payload = json.loads(payload_json) if payload_json else []
        if name == "top_works":
            for i, w in enumerate(payload):
                _check(w.get("slug"), work_slugs, "works",
                       "browse", name, f"top_works[{i}].slug")
                _check(w.get("composer_slug"), composer_slugs, "composers",
                       "browse", name, f"top_works[{i}].composer_slug")
        elif name == "top_performances":
            for i, p in enumerate(payload):
                _check(p.get("work_slug"), work_slugs, "works",
                       "browse", name, f"top_performances[{i}].work_slug")
                _check(p.get("composer_slug"), composer_slugs, "composers",
                       "browse", name, f"top_performances[{i}].composer_slug")
                _check(p.get("recording_pid"), recording_pids, "recordings",
                       "browse", name, f"top_performances[{i}].recording_pid")
        elif name == "lengths":
            for section in ("short", "medium", "long"):
                for i, w in enumerate(payload.get(section, [])):
                    _check(w.get("slug"), work_slugs, "works",
                           "browse", name, f"lengths.{section}[{i}].slug")
                    _check(w.get("composer_slug"), composer_slugs, "composers",
                           "browse", name, f"lengths.{section}[{i}].composer_slug")
        elif name == "composers":
            for i, c in enumerate(payload):
                _check(c.get("slug"), composer_slugs, "composers",
                       "browse", name, f"composers[{i}].slug")
        elif name == "house_performances":
            for i, h in enumerate(payload):
                _check(h.get("work_slug"), work_slugs, "works",
                       "browse", name, f"house_performances[{i}].work_slug")
                _check(h.get("composer_slug"), composer_slugs, "composers",
                       "browse", name, f"house_performances[{i}].composer_slug")
                _check(h.get("recording_pid"), recording_pids, "recordings",
                       "browse", name, f"house_performances[{i}].recording_pid")
        elif name == "broadcasters":
            for i, b in enumerate(payload):
                _check(b.get("slug"), broadcaster_slugs, "broadcasters",
                       "browse", name, f"broadcasters[{i}].slug")
        elif name == "forms":
            for i, f in enumerate(payload):
                _check(f.get("slug"), form_slugs, "forms",
                       "browse", name, f"forms[{i}].slug")
        elif name == "christmas":
            for i, w in enumerate(payload.get("top_works", [])):
                _check(w.get("slug"), work_slugs, "works",
                       "browse", name, f"christmas.top_works[{i}].slug")
                _check(w.get("composer_slug"), composer_slugs, "composers",
                       "browse", name, f"christmas.top_works[{i}].composer_slug")

    # years: per-year page top_works + top_composers link out
    for year, tw_json, tc_json in conn.execute(
            "SELECT year, top_works_json, top_composers_json FROM years"):
        for i, w in enumerate(json.loads(tw_json) if tw_json else []):
            _check(w.get("slug"), work_slugs, "works",
                   "years", year, f"top_works[{i}].slug")
            _check(w.get("composer_slug"), composer_slugs, "composers",
                   "years", year, f"top_works[{i}].composer_slug")
        for i, c in enumerate(json.loads(tc_json) if tc_json else []):
            _check(c.get("slug"), composer_slugs, "composers",
                   "years", year, f"top_composers[{i}].slug")

    # broadcasters: each drill-in page's top_works + top_performances link out
    for slug, tw_json, tp_json in conn.execute(
            "SELECT slug, top_works_json, top_performances_json FROM broadcasters"):
        for i, w in enumerate(json.loads(tw_json) if tw_json else []):
            _check(w.get("slug"), work_slugs, "works",
                   "broadcasters", slug, f"top_works[{i}].slug")
        for i, p in enumerate(json.loads(tp_json) if tp_json else []):
            _check(p.get("work_slug"), work_slugs, "works",
                   "broadcasters", slug, f"top_performances[{i}].work_slug")
            _check(p.get("composer_slug"), composer_slugs, "composers",
                   "broadcasters", slug, f"top_performances[{i}].composer_slug")
            _check(p.get("recording_pid"), recording_pids, "recordings",
                   "broadcasters", slug, f"top_performances[{i}].recording_pid")

    # forms: each drill-in page's top_works link out
    for slug, tw_json in conn.execute(
            "SELECT slug, top_works_json FROM forms"):
        for i, w in enumerate(json.loads(tw_json) if tw_json else []):
            _check(w.get("slug"), work_slugs, "works",
                   "forms", slug, f"top_works[{i}].slug")
            _check(w.get("composer_slug"), composer_slugs, "composers",
                   "forms", slug, f"top_works[{i}].composer_slug")

    # artists: each page's facet links out (incl. artist->artist collaborator
    # links, checked against the artists table itself)
    for slug, facets_json in conn.execute(
            "SELECT slug, facets_json FROM artists"):
        facets = json.loads(facets_json) if facets_json else {}
        for i, w in enumerate(facets.get("top_works", [])):
            _check(w.get("slug"), work_slugs, "works",
                   "artists", slug, f"facets.top_works[{i}].slug")
        for i, c in enumerate(facets.get("top_composers", [])):
            _check(c.get("slug"), composer_slugs, "composers",
                   "artists", slug, f"facets.top_composers[{i}].slug")
        for i, p in enumerate(facets.get("performances", [])):
            _check(p.get("recording_pid"), recording_pids, "recordings",
                   "artists", slug, f"facets.performances[{i}].recording_pid")
            _check(p.get("work_slug"), work_slugs, "works",
                   "artists", slug, f"facets.performances[{i}].work_slug")
        for bucket, entries in facets.get("collaborators", {}).items():
            for i, c in enumerate(entries):
                _check(c.get("slug"), artist_slugs, "artists",
                       "artists", slug, f"facets.collaborators.{bucket}[{i}].slug")

    return violations


def write_site_db(path, tables, fingerprint, validate=None):
    """Build the full site.sqlite schema at `path + ".tmp"`, insert `tables`'
    rows, stamp `meta` with the fingerprint + build time, then atomically
    os.replace onto `path`. `tables` is a dict {table_name: [row_tuple, ...]};
    a missing key means that table stays empty; a key that isn't a known
    content table is a ValueError (a silently-ignored typo would drop a whole
    table's content). Any exception (including a
    poisoned row failing executemany) leaves neither the tmp file nor a
    partial `path` behind -- the tmp is removed on failure, and `path` itself
    is only ever touched by the final os.replace, so a failed rebuild can
    never clobber a previously-good file there.

    `validate`, if given, is called as `validate(conn)` on the tmp connection
    after all inserts + meta stamping but BEFORE the publishing os.replace --
    it must return a list of violation strings (empty = pass). A non-empty
    list removes the tmp and raises ValueError listing up to 20 violations
    plus the total count, so a closure failure (check_closure is the intended
    caller) can never publish a broken substrate; a pre-existing good `path`
    is left completely untouched, since os.replace is never reached."""
    unknown = set(tables) - set(_SITE_TABLES)
    if unknown:
        raise ValueError(f"write_site_db: unknown table(s) {sorted(unknown)}; "
                         f"known: {list(_SITE_TABLES)}")

    tmp = f"{path}.tmp"
    if os.path.exists(tmp):
        os.remove(tmp)   # a leftover tmp from a killed prior run

    try:
        conn = sqlite3.connect(tmp)
        try:
            conn.executescript(_SITE_SCHEMA)
            for table in _SITE_TABLES:
                rows = tables.get(table, [])
                if rows:
                    # arity from the schema itself, so a column edit there
                    # can never drift from the INSERT placeholder count
                    n_cols = len(conn.execute(
                        f"PRAGMA table_info({table})").fetchall())
                    placeholders = ", ".join("?" * n_cols)
                    conn.executemany(
                        f"INSERT INTO {table} VALUES ({placeholders})", rows)
            built_at = dt.datetime.now().isoformat(timespec="seconds")
            conn.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [("fingerprint", fingerprint), ("built_at", built_at)])
            conn.commit()

            if validate is not None:
                violations = validate(conn)
                if violations:
                    shown = violations[:20]
                    raise ValueError(
                        f"write_site_db: closure validation failed "
                        f"({len(violations)} violation(s)): "
                        + "; ".join(shown)
                        + (f" ... ({len(violations) - 20} more)"
                           if len(violations) > 20 else ""))
        finally:
            conn.close()
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    os.replace(tmp, path)


def site_status(path, fingerprint):
    """'fresh' | 'stale' | 'missing'. A missing file, or a present-but-corrupt/
    wrong-shape one (not a valid SQLite file, no meta table, no fingerprint
    row), degrades to 'missing' -- never an exception. This is the DERIVED-
    cache convention (the projection-cache lesson): site.sqlite is rebuildable
    from the DB + registry, unlike the git-tracked registry's hard-error rule
    in load_registry. A readable fingerprint that doesn't match is 'stale'."""
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "missing"

    if row is None:
        return "missing"
    return "fresh" if row[0] == fingerprint else "stale"


# --- CLI -----------------------------------------------------------------

_WHOLE_CORPUS_SQL = (
    "SELECT t.title, t.composer, t.composer_line, t.performers, "
    "substr(e.broadcast_date, 1, 10), t.episode_pid, t.position, t.time_str "
    "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")

# The per-episode display title is the SUBTITLE ("Ligeti, Szymanowski and
# Stravinsky from Oslo") -- episodes.title is uniformly "Through the Night",
# useless as a heading. Every corpus row carries a subtitle; the COALESCE
# fallback covers a hypothetical future row without one.
_EPISODE_META_SQL = ("SELECT pid, substr(broadcast_date, 1, 10), "
                     "COALESCE(NULLIF(subtitle, ''), title) FROM episodes")


def _die_needs_warm(reason):
    print(f"ttn_site: {reason} -- run `uv run ttn_data.py warm` first, "
          f"then re-run `uv run ttn_data.py site`.", file=sys.stderr)
    raise SystemExit(1)


def _run_build(db_path, registry_out_path, site_db_out_path, force=False,
               artist_registry_out_path=None):
    """The default action: sync the registry against the current corpus, then
    build/refresh site.sqlite. Explicit consumer of the projection (SP4a
    rule) -- `ttn_project.load`, never `ensure`: a stale/missing projection is
    a hard error naming `uv run ttn_data.py warm`, not a silent ~5-minute
    rebuild kicked off from a site build. Same for a missing/stale slug-map
    cache.

    site.sqlite step: the fingerprint is computed AFTER the registry dump, so
    it covers the just-written registry bytes (a registry sync that added
    slugs must invalidate a stale site.sqlite). A 'fresh' status (and no
    --force) short-circuits without touching the file (the heavy corpus-pass +
    spine build below never runs on a fresh skip); otherwise the five content
    tables are built and write_site_db rebuilds the file."""
    if artist_registry_out_path is None:
        artist_registry_out_path = artist_registry_path()

    conn = sqlite3.connect(db_path)
    try:
        projection, rec_meta, status = ttn_project.load(conn)
        if status != "ok":
            _die_needs_warm(f"projection cache status is {status!r}")

        slug_map = load_slug_map(ttn_project.PROJECTION_PATH)
        if slug_map is None:
            _die_needs_warm("the work-slug cache is missing or stale")

        cursor = conn.execute(_WHOLE_CORPUS_SQL)
        raw8 = list(cursor)
        rows5 = list(_project_rows((r[:7] for r in raw8), projection, rec_meta))
    finally:
        conn.close()

    work_entries = build_work_index(rows5)
    for e in work_entries:
        e["slug"] = slug_map.get(e["key"], e["slug"])
    composer_entries = build_composer_index(rows5)

    registry = load_registry(registry_out_path)
    try:
        new_registry, report = sync_registry(
            registry, work_entries, composer_entries, today=dt.date.today().isoformat())
    except RegistryDriftError as e:
        print(f"ttn_site: {e}", file=sys.stderr)
        print("fix: `uv run ttn_data.py site --remap \"SLUG|COMPOSER_KEY[|WORK_KEY]\"` "
              "(add --composer for the composers namespace)", file=sys.stderr)
        raise SystemExit(1)

    dump_registry(new_registry, registry_out_path)

    print(f"ttn_site: registry synced -- {registry_out_path}")
    print(f"  registered works:     {len(new_registry['works'])} "
         f"(+{report['added_works']} new)")
    print(f"  registered composers: {len(new_registry['composers'])} "
         f"(+{report['added_composers']} new)")
    print(f"  slug drift (informational, mapping unchanged): {len(report['slug_drift'])}")
    print(f"  collisions (suffixed on assignment):            {len(report['collisions'])}")

    fp = site_fingerprint(registry_out_path, artist_registry_out_path)
    if not force and site_status(site_db_out_path, fp) == "fresh":
        print(f"ttn_site: {site_db_out_path} fresh -- skipping")
        return 0

    # Registry-authoritative slug maps: the just-synced registry is the source
    # of truth for every table (a collision suffix or a pre-sync overlay miss
    # is resolved by the registry, not the raw entry.slug). Overlay BOTH entry
    # kinds' slugs from THIS map, here in the shell and nowhere else (distinct
    # from the slug_map overlay above, which seeds sync_registry's input), so
    # build_work_rows/build_composer_rows/build_episode_rows/
    # build_browse_payloads all agree with the registry that was just written.
    # Skipping either overlay re-introduces the collision bug: two identities
    # deriving one slug would emit identical PKs and abort the executemany.
    work_slug_of = {(v["composer_key"], v["work_key"]): slug
                    for slug, v in new_registry["works"].items()}
    composer_slug_of = {v["composer_key"]: slug
                        for slug, v in new_registry["composers"].items()}
    for e in work_entries:
        e["slug"] = work_slug_of.get(e["key"], e["slug"])
    for ce in composer_entries:
        ce["slug"] = composer_slug_of.get(ce["composer_key"], ce["slug"])
    # Corpus-wide composer display SSOT: every surface that shows a composer's
    # name (work byline, browse tables, recording page via the works join)
    # reads this map so the spelling never varies between pages. The composer
    # page (build_composer_rows) already uses centry["display"] -- the same
    # value -- so this aligns the work-side surfaces to it.
    composer_display_of = {ce["composer_key"]: ce["display"]
                           for ce in composer_entries}

    conn = sqlite3.connect(db_path)
    try:
        acc = accumulate_entities(raw8, projection, rec_meta)
        ctx = ttn_spine.build_context(conn)
        recs = ttn_spine.build_recordings(conn, ctx=ctx)
        cons = ttn_spine.build_contributors(conn, ctx=ctx)
        all_brc_rows = ttn_broadcasters.load_rows(conn)
        episode_meta = list(conn.execute(_EPISODE_META_SQL))
    finally:
        conn.close()

    brc_rows_by_rp: dict = {}
    for label, rp in all_brc_rows:
        if rp:
            brc_rows_by_rp.setdefault(rp, []).append(label)

    work_rows = build_work_rows(work_entries, acc["work_airings"],
                                composer_slug_of, composer_display_of,
                                recs, cons, brc_rows_by_rp)
    rec_rows, n_multi_work, n_skipped = build_recording_rows(
        acc["work_airings"], acc["recording_airings"], work_slug_of,
        composer_slug_of, recs, cons, brc_rows_by_rp)
    composer_rows = build_composer_rows(
        composer_entries, work_entries, acc["work_airings"],
        composer_slug_of, work_slug_of, recs, cons, brc_rows_by_rp)
    episode_rows = build_episode_rows(
        episode_meta, acc["episode_tracks"], work_slug_of, composer_slug_of,
        {r[0] for r in rec_rows})
    form_rows = build_form_rows(
        work_entries, acc["work_airings"], composer_slug_of,
        composer_display_of)
    browse_rows = build_browse_payloads(
        work_entries, acc["work_airings"], rows5, all_brc_rows,
        composer_slug_of, composer_display_of, work_slug_of, recs, cons,
        composer_entries=composer_entries, recording_rows=rec_rows,
        form_rows=form_rows)
    year_rows = build_year_rows(
        work_entries, acc["work_airings"], composer_slug_of,
        composer_display_of, work_slug_of)
    broadcaster_rows = build_broadcaster_rows(
        all_brc_rows, rec_rows, work_entries, composer_display_of, cons)

    # Artist registry-lite: sync (mint-once, MBID-anchored -- see the module
    # section above), dump, then build the artists table with the SYNCED
    # registry as the page-list authority.
    art_registry = load_artist_registry(artist_registry_out_path)
    new_art_registry, art_report = sync_artist_registry(
        art_registry, artist_qualifiers(recs, cons),
        today=dt.date.today().isoformat())
    dump_artist_registry(new_art_registry, artist_registry_out_path)
    print(f"ttn_site: artist registry synced -- {artist_registry_out_path}")
    print(f"  registered artists:   {len(new_art_registry['artists'])} "
         f"(+{art_report['added']} new)")
    artist_rows = build_artist_rows(
        new_art_registry, recs, cons, brc_rows_by_rp, rec_rows,
        work_entries, composer_display_of)

    # Re-stamp the fingerprint AFTER the artist-registry dump: its bytes are
    # a site_fingerprint slot, so stamping the pre-sync value would leave a
    # freshly built site.sqlite permanently 'stale' after any mint.
    fp = site_fingerprint(registry_out_path, artist_registry_out_path)

    write_site_db(site_db_out_path, {
        "works": work_rows,
        "composers": composer_rows,
        "episodes": episode_rows,
        "recordings": rec_rows,
        "browse": browse_rows,
        "years": year_rows,
        "broadcasters": broadcaster_rows,
        "forms": form_rows,
        "artists": artist_rows,
    }, fp, validate=check_closure)

    print(f"ttn_site: site.sqlite built -- {site_db_out_path}")
    print(f"  works: {len(work_rows)}  composers: {len(composer_rows)}  "
         f"episodes: {len(episode_rows)}  recordings: {len(rec_rows)}  "
         f"browse: {len(browse_rows)}  years: {len(year_rows)}  "
         f"broadcasters: {len(broadcaster_rows)}  forms: {len(form_rows)}  "
         f"artists: {len(artist_rows)}")
    print(f"  recordings spanning >1 work key: {n_multi_work}  "
         f"skipped (absent from spine): {n_skipped}")
    return 0


def _run_render(registry_out_path, site_db_out_path, dist_out_path, *,
                require_fresh, pagefind, artist_registry_out_path=None):
    """Render site_db_out_path + the registry's redirects into dist_out_path.

    require_fresh: the --render-only hard-error gate (SP4a explicit-consumer
    rule, same discipline as _run_build's projection/slug-map checks) --
    True means site_db_out_path MUST already be 'fresh' against the CURRENT
    registry's fingerprint, or this refuses to render a stale/missing
    substrate silently. False (the default build-then-render path) skips the
    check: _run_build has JUST rebuilt (or confirmed fresh) site_db_out_path
    immediately before this runs, so re-deriving the fingerprint here would
    be redundant, not a safety net.

    pagefind: passed straight through to render_site (True = run the search
    post-pass after a passing crawl; False = skip it, summary["pagefind"] is
    None). Wired from --no-pagefind (see main).
    """
    if require_fresh:
        fp = site_fingerprint(registry_out_path, artist_registry_out_path)
        status = site_status(site_db_out_path, fp)
        if status != "fresh":
            print(f"ttn_site: {site_db_out_path} is {status!r}, not fresh -- "
                  f"run `uv run ttn_data.py site` (build + render) first, "
                  f"or drop --render-only.", file=sys.stderr)
            raise SystemExit(1)

    summary = render_site(site_db_out_path, registry_out_path, dist_out_path, pagefind=pagefind)
    print(f"ttn_site: rendered -- {dist_out_path}")
    print(f"  pages: {summary['pages']}  written: {summary['written']}  "
         f"skipped: {summary['skipped']}  pruned: {summary['pruned']}  "
         f"crawl ok: {summary['crawl_ok']}")
    search_status = {True: "ok", False: "SKIPPED (see warning above)", None: "not attempted"}
    print(f"  search index: {search_status.get(summary.get('pagefind'))}")
    return 0


def _run_rename(registry_out_path, namespace, old, new):
    registry = load_registry(registry_out_path)
    try:
        new_registry = apply_rename(registry, namespace, old, new)
    except RegistryActionError as e:
        print(f"ttn_site: rename refused -- {e}", file=sys.stderr)
        raise SystemExit(1)
    dump_registry(new_registry, registry_out_path)
    print(f"ttn_site: renamed {namespace} slug {old!r} -> {new!r} "
         f"(redirect left at {old!r})")
    return 0


def _run_remap(registry_out_path, namespace, spec):
    parts = spec.split("|")
    if namespace == "works":
        if len(parts) != 3:
            print("ttn_site: --remap for works needs "
                 "\"SLUG|COMPOSER_KEY|WORK_KEY\"", file=sys.stderr)
            raise SystemExit(1)
        slug, composer_key, work_key = parts
    else:
        if len(parts) != 2:
            print("ttn_site: --remap --composer needs \"SLUG|COMPOSER_KEY\"",
                 file=sys.stderr)
            raise SystemExit(1)
        slug, composer_key = parts
        work_key = None

    registry = load_registry(registry_out_path)
    try:
        new_registry = apply_remap(registry, namespace, slug, composer_key, work_key)
    except RegistryActionError as e:
        print(f"ttn_site: remap refused -- {e}", file=sys.stderr)
        raise SystemExit(1)
    dump_registry(new_registry, registry_out_path)
    if slug in new_registry["redirects"][namespace]:
        print(f"ttn_site: remapped {namespace} slug {slug!r} -> redirect to "
             f"{new_registry['redirects'][namespace][slug]!r} (successor already registered)")
    else:
        print(f"ttn_site: remapped {namespace} slug {slug!r} to its successor identity")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="ttn_site.py",
        description="Build the website substrate (slug registry + site.sqlite), "
                    "then render it to dist/, from the current corpus.")
    ap.add_argument("--db", default="ttn.sqlite", help="SQLite path (default: ttn.sqlite)")
    ap.add_argument("--registry", default=None,
                    help="registry JSON path (default: ttn_site_registry.json beside this module)")
    ap.add_argument("--artist-registry", default=None,
                    help="artist registry JSON path (default: "
                        "ttn_site_artist_registry.json beside this module)")
    ap.add_argument("--site-db", default=None,
                    help="site.sqlite output path (default: site.sqlite beside this module)")
    ap.add_argument("--dist", default=None,
                    help="rendered dist/ output directory (default: dist/ beside this module)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild site.sqlite even if it's already fresh")
    ap.add_argument("--build-only", action="store_true",
                    help="build/refresh site.sqlite only -- skip rendering")
    ap.add_argument("--render-only", action="store_true",
                    help="render only, from the EXISTING site.sqlite -- skip the build; "
                        "hard-errors unless it's already fresh")
    ap.add_argument("--no-pagefind", action="store_true",
                    help="skip the Pagefind search-index post-pass (default: run it "
                        "on every render; irrelevant with --build-only, which never renders)")
    ap.add_argument("--composer", action="store_true",
                    help="apply --rename/--remap in the composers namespace (default: works)")
    ap.add_argument("--rename", nargs=2, metavar=("OLD", "NEW"),
                    help="move a registered slug's identity from OLD to NEW, leaving a redirect")
    ap.add_argument("--remap", metavar="SPEC",
                    help="re-point an orphaned slug at its successor identity: "
                        "\"SLUG|COMPOSER_KEY|WORK_KEY\" (or \"SLUG|COMPOSER_KEY\" with --composer)")
    args = ap.parse_args(argv)

    reg_path = args.registry if args.registry is not None else registry_path()
    artist_reg_path = (args.artist_registry if args.artist_registry is not None
                       else artist_registry_path())
    site_db_out = args.site_db if args.site_db is not None else site_db_path()
    dist_out = args.dist if args.dist is not None else dist_path_default()
    namespace = "composers" if args.composer else "works"

    if args.rename:
        return _run_rename(reg_path, namespace, args.rename[0], args.rename[1])
    if args.remap:
        return _run_remap(reg_path, namespace, args.remap)

    pagefind = not args.no_pagefind

    if args.render_only:
        return _run_render(reg_path, site_db_out, dist_out, require_fresh=True,
                           pagefind=pagefind,
                           artist_registry_out_path=artist_reg_path)

    rc = _run_build(args.db, reg_path, site_db_out, force=args.force,
                    artist_registry_out_path=artist_reg_path)
    if rc not in (0, None):
        return rc
    if args.build_only:
        return 0
    return _run_render(reg_path, site_db_out, dist_out, require_fresh=False, pagefind=pagefind)


if __name__ == "__main__":
    main()
