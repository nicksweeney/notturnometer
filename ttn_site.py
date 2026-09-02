"""Site substrate builder (website Phase 1): the frozen slug registry +
site.sqlite entity aggregates. ttn_site_render.py renders it. Both are
reached as `ttn_data.py site` (build, then render)."""
import argparse
import calendar
import hashlib
import json
import os
import re
import sqlite3
import sys
import datetime as dt
from collections import Counter, defaultdict

import ttn_project
from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                          strip_arranger_tail, resolve_composer_alias,
                          resolve_work_alias, work_title_key, _best_spelling,
                          override_composer_display, build_work_index,
                          _project_rows, load_slug_map, _project_identity,
                          compute_year_breakdown, _FORM_SYNONYMS,
                          parse_performers, resolve_ensemble_alias)
import ttn_broadcasters
import ttn_ebu_codes
import ttn_mbid_audit
import ttn_segment_meta
import ttn_spine
from ttn_site_render import BASE_URL, render_site, tally_years

REGISTRY_PATH = "ttn_site_registry.json"
SITE_DB_FILENAME = "site.sqlite"

# Absolute paths to the first-party modules whose bytes feed site_fingerprint,
# resolved once at import time beside THIS module (not the caller's cwd).
# Module-level names (not inlined into site_fingerprint) so tests can
# monkeypatch them. These are the SUBSTRATE-affecting modules ttn_site uses at
# build time that are NOT already covered transitively: ttn_analyze/ttn_aliases
# shape the projected rows and grouping; ttn_ebu_codes/ttn_broadcasters shape
# the broadcasters table + facet lists and are in NEITHER the projection
# cache's fingerprint nor here previously (the gap that let a country-code fix
# render against a 'fresh' site.sqlite). ttn_spine/ttn_segment_meta are covered
# already -- they're in the projection cache's _FINGERPRINT_FILES, so a change
# there makes the projection stale and _run_build hard-errors to `warm` before
# it can fresh-skip.
_ANALYZE_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_analyze.py")
_ALIASES_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_aliases.py")
_EBU_CODES_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_ebu_codes.py")
_BROADCASTERS_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_broadcasters.py")


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
    base = {code: (broadcaster_slug(name), ttn_ebu_codes.display_name(code), country)
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


def country_slug(country_name: str) -> str:
    """URL slug for a source country: the country name kebabbed. Country names
    are unique in the decode table (many EBU codes roll up to one name), so no
    collision qualification is needed -- build_country_rows still guards."""
    return composer_slug(country_name)


def _source_ranking_facets(per_rp, rec_meta, disp_of, cons, top_n):
    """The (top_works, top_performances, top_ensembles) triple shared by the
    broadcaster and country pages. per_rp: {recording_pid: airings under THIS
    source}. rec_meta: {rp: (work_slug, composer_slug)}. disp_of: {work_slug:
    (work_display, composer_display)}. Works carry links plus recording_pids
    (the tapes this source used for the work, busiest first -- the works
    block is the AGGREGATING view: one row, N performances); performances
    carry links (top_n each); ensemble rows carry the identity's mbid (None
    for name-only) so the renderer can link MBID-backed ones to their
    /artist/ page. PURE."""
    work_counts: dict = {}
    work_rps: dict = {}         # work_slug -> [(rp, airings under this source)]
    for rp, n in per_rp.items():
        ws = rec_meta.get(rp, (None, None))[0]
        if ws in disp_of:
            work_counts[ws] = work_counts.get(ws, 0) + n
            work_rps.setdefault(ws, []).append((rp, n))
    top_works = [
        {"slug": ws, "display": disp_of[ws][0],
         "composer_display": disp_of[ws][1], "airings": n,
         # the tapes this source used for the work, busiest first -- the
         # aggregating view's payload: one work row, N performances. rec_meta
         # comes from the BUILT recordings tuples, so every rp here has a
         # recordings row (closure-safe by construction).
         "recording_pids": [rp for rp, _ in sorted(
             work_rps[ws], key=lambda t: (-t[1], t[0]))]}
        for ws, n in sorted(work_counts.items(),
                             key=lambda kv: (-kv[1], kv[0]))[:top_n]
    ]

    top_performances = []
    for rp, n in sorted(per_rp.items(), key=lambda kv: (-kv[1], kv[0])):
        if len(top_performances) == top_n:
            break
        ws, cslug = rec_meta.get(rp, (None, None))
        if ws not in disp_of:
            continue
        wd, cd = disp_of[ws]
        top_performances.append({
            "recording_pid": rp, "work_slug": ws, "work_display": wd,
            "composer_slug": cslug, "composer_display": cd, "airings": n,
        })

    # Aggregated by identity (MBID-else-name), carrying the mbid so the
    # renderer can link MBID-backed ensembles to their /artist/ page (exact
    # MBID, never display-string); display stays the identity's canonical
    # spelling (segment names are 1-spelling-per-MBID).
    ens_counts: dict = {}   # identity_key -> [display, mbid, airings]
    for rp, n in per_rp.items():
        seen = set()
        for c in cons.get(rp, []):
            if c.role in ("Ensemble", "Orchestra", "Choir") \
                    and c.identity_key not in seen:
                seen.add(c.identity_key)
                ent = ens_counts.setdefault(c.identity_key,
                                            [c.display_name, c.mbid, 0])
                ent[2] += n
    top_ensembles = [
        {"display": d, "mbid": m, "airings": n}
        for d, m, n in sorted(ens_counts.values(),
                               key=lambda v: (-v[2], v[0]))[:top_n]
    ]
    return top_works, top_performances, top_ensembles


def _rec_disp_maps(rec_rows, work_entries, composer_display_of):
    """The (rec_meta, disp_of) lookups the source-ranking helper needs:
    rec_meta = {rp: (work_slug, composer_slug)} from the BUILT recordings
    tuples; disp_of = {work_slug: (work_display, composer_display SSOT)}."""
    rec_meta = {r[0]: (r[1], r[2]) for r in rec_rows}
    disp_of = {
        e["slug"]: (e["work_display"],
                    composer_display_of.get(e["key"][0]) or e["composer_display"])
        for e in work_entries
    }
    return rec_meta, disp_of


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
    rec_meta, disp_of = _rec_disp_maps(rec_rows, work_entries, composer_display_of)

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
        top_works, top_performances, top_ensembles = _source_ranking_facets(
            per_rp, rec_meta, disp_of, cons, _BROADCASTER_TOP_N)
        rows.append((slug, key, display, country, airings[key], len(per_rp),
                     json.dumps(top_works), json.dumps(top_performances),
                     json.dumps(top_ensembles)))

    rows.sort(key=lambda r: (-r[4], r[0]))
    return rows


def build_country_rows(all_brc_rows, rec_rows, work_entries,
                        composer_display_of, cons) -> list:
    """Build countries-table row tuples -- the source-country rollup behind
    /country/{slug}/ pages. PURE. Same inputs as build_broadcaster_rows, but
    grouped one level up by ttn_broadcasters.country_key (the EBU code's
    country NAME, so a nation's broadcasters roll up: Germany's ARD regional
    stations, Switzerland's language services, the Slovakia/Hungary legacy-
    rename pairs). OTHER/UNATTRIBUTED get no row (accounting buckets, like
    broadcasters).

    The page is HUB-FIRST: broadcasters_json lists the country's own
    broadcasters (each with its /broadcaster/ slug -- the drill-down), and
    the top_works/top_performances/top_ensembles are the NATIONAL PROFILE
    over the union of all the country's recordings -- the one view no single
    broadcaster page can show.

    Returns 9-tuples in countries-schema column order, airings-DESC (tie slug):
      (slug, country, airings, n_recordings, n_broadcasters,
       broadcasters_json, top_works_json, top_performances_json,
       top_ensembles_json)"""
    minted = mint_broadcaster_slugs()
    rec_meta, disp_of = _rec_disp_maps(rec_rows, work_entries, composer_display_of)

    # country -> {rp: union airings}, and country -> {broadcaster key: airings}
    country_rp: dict = {}
    country_brc: dict = {}
    for label, rp in all_brc_rows:
        if not label or not ttn_ebu_codes.is_ebu_code(label) or not rp:
            continue
        bkey = ttn_ebu_codes.fold(label)
        country = ttn_ebu_codes.decode(bkey)[2]
        country_rp.setdefault(country, {})
        country_rp[country][rp] = country_rp[country].get(rp, 0) + 1
        country_brc.setdefault(country, {})
        country_brc[country][bkey] = country_brc[country].get(bkey, 0) + 1

    slug_seen: dict = {}
    rows = []
    for country, per_rp in country_rp.items():
        slug = country_slug(country)
        if slug in slug_seen:
            raise RegistryDriftError(
                f"country slug collision: {slug!r} for {country!r} and "
                f"{slug_seen[slug]!r} (two country names kebab identically)")
        slug_seen[slug] = country

        # hub: the country's broadcasters, each with its own page slug
        brc_per_rp = country_brc[country]
        broadcasters = []
        for bkey, n in sorted(brc_per_rp.items(), key=lambda kv: (-kv[1], kv[0])):
            bslug, bdisplay, _c = minted[bkey]
            broadcasters.append({"slug": bslug, "display": bdisplay, "airings": n})

        top_works, top_performances, top_ensembles = _source_ranking_facets(
            per_rp, rec_meta, disp_of, cons, _BROADCASTER_TOP_N)

        total_airings = sum(per_rp.values())
        rows.append((
            slug, country, total_airings, len(per_rp), len(brc_per_rp),
            json.dumps(broadcasters), json.dumps(top_works),
            json.dumps(top_performances), json.dumps(top_ensembles)))

    rows.sort(key=lambda r: (-r[2], r[0]))
    return rows


_NATIONAL_DAY_MIN_SEGMENTS = 10
_NATIONAL_DAY_DOMINANCE = 0.70


def detect_national_day_slots(segment_rows):
    """Segment-side national-day detection. segment_rows: iterable of
    (episode_pid, date10, record_label, recording_pid). PURE.

    A night is a national-day night when, over its non-interstitial segments
    carrying a recognised EBU source label, ONE country holds >= 0.70 of them
    AND there are >= 10 such segments. Returns
    {(country, "MM-DD"): [(year, date10, episode_pid), ...] sorted by year} --
    the recurring + one-off slots (the caller separates them).
    """
    from collections import Counter, defaultdict
    by_ep = defaultdict(Counter)
    date_of = {}
    for ep, date10, label, rp in segment_rows:
        date_of[ep] = date10
        if rp and ttn_segment_meta.is_interstitial(rp):
            continue
        if not label:
            continue
        code = ttn_ebu_codes.fold(label)
        if not ttn_ebu_codes.is_ebu_code(code):
            continue
        _bc, _cc, country = ttn_ebu_codes.decode(code)
        if not country or country == "(multilateral)":
            continue
        by_ep[ep][country] += 1
    slots = defaultdict(list)
    for ep, ctr in by_ep.items():
        n = sum(ctr.values())
        if n < _NATIONAL_DAY_MIN_SEGMENTS:
            continue
        country, cnt = ctr.most_common(1)[0]
        if cnt / n < _NATIONAL_DAY_DOMINANCE:
            continue
        d = date_of[ep]
        slots[(country, d[5:])].append((d[:4], d, ep))
    return {k: sorted(v) for k, v in slots.items()}


def national_day_signature(slot_counts, corpus_counts, *, display, top=5, floor=3):
    """Night-lift signature composers for one slot. slot_counts /
    corpus_counts: Counters of canonical-composer-key -> airings (slot vs whole
    2012+ tracks corpus). display: {key: shown name}. PURE.

    Score = (key's share of the slot) / (key's share of the corpus); keep keys
    with >= floor slot airings; rank desc; return the top `top` display names.
    Ties break by (score, slot_count, key) for build determinism.
    """
    slot_total = sum(slot_counts.values()) or 1
    corpus_total = sum(corpus_counts.values()) or 1
    scored = []
    for key, k in slot_counts.items():
        if k < floor:
            continue
        base = corpus_counts.get(key, k) / corpus_total
        lift = (k / slot_total) / base if base else 0.0
        scored.append((lift, k, key))
    scored.sort(reverse=True)
    return [display.get(key, key) for _lift, _k, key in scored[:top]]


def build_national_days(national_day_segment_rows, episode_tracks,
                         composer_display_of, country_slug_of) -> dict:
    """The `national_days` browse payload. PURE.

    national_day_segment_rows: (episode_pid, date10, record_label,
        recording_pid) -- fed straight to detect_national_day_slots.
    episode_tracks: acc["episode_tracks"] from accumulate_entities -- each
        track is (pos, time_str, key_or_None, composer_display, title_display,
        performers, rp_or_None); key is the resolved (composer_key, work_key).
    composer_display_of: {composer_key: corpus-wide SSOT display}.
    country_slug_of: {country: slug} -- from the BUILT country_rows, so a
        card's country_slug always resolves to a real /country/ page.

    Slots with >=2 distinct-year airings are 'recurring'; exactly one airing
    is 'also_marked'. Each card carries the night-lift composer signature
    (national_day_signature) over that slot's episodes vs. the whole corpus.
    Returns {"recurring": [...], "also_marked": [...]}.
    """
    slots = detect_national_day_slots(national_day_segment_rows)

    corpus_counts = Counter()
    for tracks in episode_tracks.values():
        for track in tracks:
            key = track[2]
            if key:
                corpus_counts[key[0]] += 1

    def _card(country, mmdd, airings):
        slot_counts = Counter()
        display = {}
        for _year, _date10, ep in airings:
            for track in episode_tracks.get(ep, ()):
                key, composer = track[2], track[3]
                if key:
                    ck = key[0]
                    slot_counts[ck] += 1
                    display.setdefault(ck, composer_display_of.get(ck) or composer)
        month, day = int(mmdd[:2]), int(mmdd[3:])
        return {
            "country": country,
            "country_slug": country_slug_of.get(country),
            "flag": ttn_ebu_codes.country_flag(country) or "",
            "mmdd": mmdd,
            "day_label": f"{day} {calendar.month_name[month]}",
            "airings": [{"year": year, "url_date": date10}
                        for year, date10, _ep in airings],
            "composers": national_day_signature(slot_counts, corpus_counts,
                                                display=display),
        }

    recurring, also_marked = [], []
    for (country, mmdd), airings in slots.items():
        card = _card(country, mmdd, airings)
        if len(airings) >= 2:
            recurring.append((country, airings[0][0], card))
        else:
            also_marked.append((country, mmdd, card))

    recurring.sort(key=lambda t: (t[0], t[1]))
    also_marked.sort(key=lambda t: (t[0], t[1]))
    return {
        "recurring": [card for _country, _year, card in recurring],
        "also_marked": [card for _country, _mmdd, card in also_marked],
    }


def attach_national_days(country_rows, nd_payload) -> list:
    """Append national_days_json (the 10th countries column) to each 9-tuple
    country row: that country's own national-day slots, pulled from the already-
    built national_days browse payload and re-grouped by country_slug into the
    same {"recurring": [...], "also_marked": [...]} shape. A country with no
    national-day night gets "" (renders no block). Cards keep payload order
    (country + oldest-first within recurring), so re-renders stay byte-identical.
    PURE -- reuses Phase-1 cards, so the episode links are already closure-checked.
    """
    by_slug: dict = {}
    for group in ("recurring", "also_marked"):
        for card in nd_payload.get(group, []):
            slug = card.get("country_slug")
            if not slug:
                continue
            by_slug.setdefault(slug, {"recurring": [], "also_marked": []})
            by_slug[slug][group].append(card)
    return [row + (json.dumps(by_slug[row[0]]) if row[0] in by_slug else "",)
            for row in country_rows]


def national_day_by_date(nd_payload) -> dict:
    """{url_date: {"country", "country_slug", "flag"}} from the national_days
    browse payload -- BOTH recurring AND also_marked (the one-offs are genuine
    tributes too, Nick 2026-07-28). Every airing date of every card. A night is
    >=70% one country by construction, so a date maps to at most one country; on
    the theoretical tie the last card in payload order wins (deterministic).
    PURE. Feeds the per-episode 'An episode celebrating {country}' chip."""
    out: dict = {}
    for group in ("recurring", "also_marked"):
        for card in nd_payload.get(group, []):
            info = {"country": card["country"],
                    "country_slug": card.get("country_slug"),
                    "flag": card.get("flag", "")}
            for airing in card.get("airings", []):
                out[airing["url_date"]] = info
    return out


def attach_episode_national_days(episode_rows, by_date) -> list:
    """Append national_day_json (the 8th episodes column) to each 7-tuple
    episode row: the {country, country_slug, flag} for that episode's DATE
    (row[1]) when the night is a detected national-day tribute, else "" (renders
    no chip). by_date: national_day_by_date output. PURE -- reuses the already-
    built national_days cards, so the country link is already closure-covered.
    Mirrors attach_national_days, the Phase-2 post-hoc column pattern (the
    payload is built after build_episode_rows, so this appends rather than
    threading a required param through the row builder)."""
    return [row + (json.dumps(by_date[row[1]]) if row[1] in by_date else "",)
            for row in episode_rows]


def build_composer_index(rows) -> list:
    """Per-composer identity entries from projected 5-tuple ranking rows.

    rows: iterable of (title, composer, composer_line, performers, bdate)
          with arranger tails NOT yet stripped.

    Mirrors build_work_index's key derivation on the composer side:
      stripped = strip_arranger_tail(composer, composer_line)
      ck       = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
      wk       = resolve_work_alias(work_title_key(title, stripped), stripped)

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
        wk = resolve_work_alias(work_title_key(title, stripped), stripped)

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


def accumulate_entities(rows8, projection, rec_meta, presentation=None) -> dict:
    """One pass over the whole-corpus 8-tuple cursor, building the three
    per-entity accumulators the page-aggregate builders (Tasks 6-7) slice
    from. Pure: no SQL, no I/O.

    rows8: iterable of (title, composer, composer_line, performers, bdate,
           episode_pid, position, time_str) -- the profile-card 7-tuple
           (ttn_analyze.work_airings' cursor7 shape) extended with time_str
           (episode pages need the on-air clock time).
    projection: {(episode_pid, position): recording_pid}
    rec_meta:   {recording_pid: (clean_composer, clean_title)}
    presentation: {(episode_pid, position): recording_pid} -- the MEDIUM-tier
        links (ttn_project.load_presentation), or None. GRADUATED TRUST: these
        rows get a recording to SHOW (a performance page, an episode-page link,
        artist facets) but their IDENTITY still comes from the tracks text --
        _project_identity is called with the projection ALONE, never with this.
        That asymmetry is the whole point: a medium match is medium precisely
        because the two lineages disagree about the composer, and in 60% of
        cases it is the SEGMENT side that is wrong (a performer sitting in
        composer_name). Substituting rec_meta here would import that error as
        clean identity -- the exact failure RECORDING_COMPOSER_OVERRIDES exists
        to prevent, at 700x the scale.

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
      recording_airings: {rp: [(bdate, ep, pos), ...]} -- one entry per
        PROJECTED row (rp is not None), input order. pos carries through so the
        performance page's date links can anchor at their own track row.

    Key derivation mirrors ttn_analyze.work_airings exactly, applied AFTER
    _project_identity:
      c, cl, t = _project_identity(ep, pos, composer, composer_line, title,
                                    projection, rec_meta)
      stripped = strip_arranger_tail(c, cl)
      ck = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
      wk = resolve_work_alias(work_title_key(t, stripped), stripped)
    """
    work_airings: dict = {}
    episode_tracks: dict = {}
    recording_airings: dict = {}
    composer_births: dict = {}   # ck -> {year: count}
    composer_deaths: dict = {}   # ck -> {year: count}

    for title, composer, composer_line, performers, bdate, ep, pos, time_str in rows8:
        c, cl, t = _project_identity(ep, pos, composer, composer_line, title,
                                     projection, rec_meta)
        stripped = strip_arranger_tail(c, cl)
        ck = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
        wk = resolve_work_alias(work_title_key(t, stripped), stripped)

        b, d = parse_composer_years(composer_line)
        if b is not None:
            counts = composer_births.setdefault(ck, {})
            counts[b] = counts.get(b, 0) + 1
        if d is not None:
            counts = composer_deaths.setdefault(ck, {})
            counts[d] = counts.get(d, 0) + 1

        # Identity above came from the projection alone. The recording SHOWN
        # may additionally come from the presentation tier; a track has one DP
        # match so the two key-spaces are disjoint and this never overrides.
        rp = projection.get((ep, pos))
        if rp is None and presentation:
            rp = presentation.get((ep, pos))
        key = None if (not ck and not wk) else (ck, wk)

        if key is not None:
            work_airings.setdefault(key, []).append((bdate, rp, performers, ep, pos))

        episode_tracks.setdefault(ep, []).append(
            (pos, time_str, key, c, t, performers, rp))

        if rp is not None:
            recording_airings.setdefault(rp, []).append((bdate, ep, pos))

    for ep in episode_tracks:
        episode_tracks[ep].sort(key=lambda row: row[0])

    def _modal(counter):
        return max(counter, key=counter.get) if counter else None

    composer_dates = {}
    for ck in set(composer_births) | set(composer_deaths):
        composer_dates[ck] = (_modal(composer_births.get(ck)),
                               _modal(composer_deaths.get(ck)))

    return {
        "work_airings": work_airings,
        "episode_tracks": episode_tracks,
        "recording_airings": recording_airings,
        "composer_dates": composer_dates,
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


# Segment durations below this (seconds) are measurement artifacts, not real
# pieces -- the feed carries e.g. a 2s Borodin quartet movement and a 3s
# Schumann one. Treated as UNMEASURED (None) everywhere the SITE consumes a
# duration (the recordings/artist tables + the work-page recording list, and
# transitively the works-by-length classification, which already skips a None
# duration), so a phantom can't drag a work into the 'short' class or show
# '0:02' on a page. The Milhaud interstitials (32s) sit well above the floor
# and stay measured (they're excluded elsewhere, by recording_pid). Site-side
# only: the spine and CLI keep the raw value.
_DURATION_SANITY_FLOOR = 10


def _sane_duration(seconds):
    """A segment duration below _DURATION_SANITY_FLOOR -> None (unmeasured);
    otherwise passed through unchanged."""
    if seconds is not None and seconds < _DURATION_SANITY_FLOOR:
        return None
    return seconds


def _majority_broadcaster(labels, slug_map=None):
    """The ONE majority-broadcaster rule: the modal non-null record_label of a
    recording, decoded to its display name -- plus the drill-in slug when the
    label is a recognized EBU code and a slug map ({folded code: (slug, ...)})
    is given. Null/empty labels never win the vote (an unlabelled airing is
    UNATTRIBUTED, not a broadcaster). Was hand-copied in _work_facets,
    build_recording_rows and the national-days house-performances builder.
    Returns (display_or_None, slug_or_None)."""
    labels = [lab for lab in labels if lab]
    if not labels:
        return None, None
    majority = Counter(labels).most_common(1)[0][0]
    display = ttn_ebu_codes.display_name(majority) or majority
    slug_val = None
    if slug_map and ttn_ebu_codes.is_ebu_code(majority):
        slug_val = slug_map[ttn_ebu_codes.fold(majority)][0]
    return display, slug_val


def _contributor_facets(rps, recs, cons, brc_rows_by_rp, rp_stats=None):
    """The contributor/broadcaster facet dict for a recording_pid set: top-10
    performer/conductor/ensemble rankings + the EBU source ranking, sliced
    from the WHOLE-CORPUS recs/cons/brc_rows_by_rp via dict-comprehension
    subsets -- never a fresh spine build. Shared by _work_facets (which adds
    the per-recording list) and build_composer_rows (which doesn't -- a
    composer's per-recording detail lives on its work pages). Empty rps
    (fully text-only entity) -> all-empty facets.

    rp_stats ({rp: (count, first, last)}, bridged whole-corpus, derived from
    the recordings table): when given, each recording's airing_count is
    substituted with the bridged count before ranking, so a contributor's
    facet airings agree with the recordings table / artist pages instead of
    the spine's 2012+-only values."""
    if not rps:
        return {"top_performers": [], "top_conductors": [],
                "top_ensembles": [], "broadcasters": []}

    recs_sub = {}
    for rp, r in recs.items():
        if rp not in rps:
            continue
        n = rp_stats[rp][0] if rp_stats and rp in rp_stats else r.airing_count
        # rank_contributors weights by airing_count; substitute the bridged
        # whole-corpus count (Recording is a namedtuple -- cheap copy).
        recs_sub[rp] = r._replace(airing_count=n)
    cons_sub = {rp: c for rp, c in cons.items() if rp in rps}

    top_performers = ttn_spine.rank_contributors(recs_sub, cons_sub, "Performer")[:10]
    top_conductors = ttn_spine.rank_contributors(recs_sub, cons_sub, "Conductor")[:10]
    # ONE combined call over the ensemble role set (Orchestra/Ensemble/Choir),
    # NOT two single-role calls concatenated: rank_contributors dedupes an
    # identity per recording across the set, so a body credited Orchestra on
    # some airings and Ensemble on others (the Finnish RSO on Toivo Kuula's
    # page) collapses to ONE row with the union count -- concatenation showed
    # it twice, same MBID/link, split airings.
    top_ensembles = ttn_spine.rank_contributors(
        recs_sub, cons_sub, ttn_spine._ENSEMBLE_ROLES)[:10]

    b_rows = [(lab, rp) for rp in rps for lab in brc_rows_by_rp.get(rp, [])]
    broadcasters = ttn_broadcasters.rank_broadcasters(
        b_rows, rank_key=ttn_broadcasters.broadcaster_key)

    return {
        "top_performers": [_contrib_stat_dict(s) for s in top_performers],
        "top_conductors": [_contrib_stat_dict(s) for s in top_conductors],
        "top_ensembles": [_contrib_stat_dict(s) for s in top_ensembles],
        "broadcasters": [_broadcaster_stat_dict(s) for s in broadcasters],
    }


def _work_facets(rps, recs, cons, brc_rows_by_rp, rp_stats=None):
    """The segment-side facet dict for one work's recording_pid set: the same
    five keys gather_work_profile computes (recordings/top_performers/
    top_conductors/top_ensembles/broadcasters), sliced from the WHOLE-CORPUS
    recs/cons/brc_rows_by_rp via dict-comprehension subsets -- never a fresh
    spine build. Empty rps (fully text-only work) -> all-empty facets.

    rp_stats ({rp: (count, first, last)}, bridged whole-corpus, derived from
    the recordings table): when given, each recording's airing_count/first/
    last come from it instead of the spine's 2012+-only values, so the work
    page's performances table agrees with the recordings table and the
    performance page (the p01pnwwj class: a bridged 2009 airing invisible in
    the spine stats showed '16 airings, 2014-2026' here vs '17, 2009-' on the
    performance page)."""
    contributor_facets = _contributor_facets(rps, recs, cons, brc_rows_by_rp,
                                             rp_stats)
    if not rps:
        return {"recordings": [], **contributor_facets}

    recs_sub = {rp: r for rp, r in recs.items() if rp in rps}
    cons_sub = {rp: c for rp, c in cons.items() if rp in rps}
    minted_slugs = mint_broadcaster_slugs()

    def _rec_dict(r):
        clist = cons_sub.get(r.recording_pid, [])
        # Bridged-truth count/dates (see docstring): spine values are the
        # fallback when rp_stats is absent or lacks the rp.
        if rp_stats:
            count, first, last = rp_stats.get(
                r.recording_pid,
                (r.airing_count, r.first_aired, r.last_aired))
        else:
            count, first, last = r.airing_count, r.first_aired, r.last_aired
        # per-recording broadcaster: the majority label, decoded -- the same
        # rule as the recordings-table broadcaster column -- plus the
        # drill-in page slug when the label is a recognized EBU code.
        broadcaster, broadcaster_slug_val = _majority_broadcaster(
            brc_rows_by_rp.get(r.recording_pid, []), minted_slugs)
        return {
            "recording_pid": r.recording_pid,
            "duration": _sane_duration(r.duration_seconds),
            "airing_count": count,
            "first": first,
            "last": last,
            "broadcaster": broadcaster,
            "broadcaster_slug": broadcaster_slug_val,
            # {name, mbid} per contributor so render_work can link each to its
            # /artist/ page by EXACT MBID (the performance page's rule), matching
            # the top-performer/conductor/ensemble facet lists.
            "conductors": [{"name": c.display_name, "mbid": c.mbid}
                           for c in clist if c.role == "Conductor"],
            "ensembles": [{"name": c.display_name, "mbid": c.mbid}
                          for c in clist if c.role in ("Ensemble", "Orchestra")],
            "soloists": [{"name": c.display_name, "mbid": c.mbid}
                         for c in clist if c.role in ("Performer", "Singer", "Choir")],
        }

    # Order: most-recently-aired first, so a visitor sees the likeliest
    # candidates for a recent performance at the top. Within a shared last-airing
    # date the more-aired recording leads, then pid -- deterministic. `last` is a
    # date10 string (compares chronologically); None sorts last via "". Two
    # stable passes because a string primary key can't take unary minus: the
    # first fixes the (airings desc, pid asc) secondary order, the second lifts
    # last-aired to primary while stability preserves the secondary within ties.
    recordings_list = sorted(
        (_rec_dict(r) for r in recs_sub.values()),
        key=lambda d: (-d["airing_count"], d["recording_pid"]))
    recordings_list.sort(key=lambda d: d["last"] or "", reverse=True)

    return {"recordings": recordings_list, **contributor_facets}


def build_work_rows(entries, work_airings, composer_slug_of,
                    composer_display_of, recs, cons,
                    brc_rows_by_rp, rp_stats=None) -> list:
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
        facets = _work_facets(rps, recs, cons, brc_rows_by_rp, rp_stats)
        # by_year renders newest-first (compute_year_breakdown is chronological).
        facets["by_year"] = list(reversed(by_year))
        # Every night this work aired, for the airing-dates block. The UNION
        # across its performances PLUS its text-only airings -- and the second
        # half is the point: a text-only airing has no recording, so it appears
        # on no performance page, and 29.8% of works have no performance page
        # at all. Before this the site had exactly one route to an episode page
        # (from a performance), leaving those works navigational dead ends.
        # (date, episode_pid, pos) per night. The pid and position are what
        # anchor the link at THIS work's track instead of the top of a 25-track
        # page -- the episode URL is keyed by date (it groups the multi-pid
        # nights), so the pid is carried for the fragment, not the path.
        # One entry per night, keeping the earliest track: a work aired twice
        # in one night is one line in the block, and it should point at the
        # first of the two.
        first_track_of_night = {}
        for (bd, _rp, _p, ep, pos) in airings:
            if not bd:
                continue
            prior = first_track_of_night.get(bd)
            if prior is None or pos < prior[1]:
                first_track_of_night[bd] = (ep, pos)
        facets["airing_dates"] = [
            [bd, ep, pos] for bd, (ep, pos) in sorted(first_track_of_night.items())]

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
    recording_airings:  {rp: [(bdate, ep, pos), ...]} -- whole corpus (includes
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
        broadcaster, _slug = _majority_broadcaster(brc_rows_by_rp.get(rp, []))

        sorted_dates = sorted(dates_eps, key=lambda t: (t[0], t[1], t[2]))
        first_aired = sorted_dates[0][0]
        last_aired = sorted_dates[-1][0]

        contributors_json = json.dumps(
            [{"role": c.role, "name": c.display_name, "mbid": c.mbid}
             for c in cons.get(rp, [])])
        # Airing-dates table renders newest-first; first/last above stay
        # derived from the ascending sort.
        airing_dates_json = json.dumps(
            [[bd, ep, pos] for bd, ep, pos in reversed(sorted_dates)])

        rows.append((
            rp,
            work_slug,
            composer_slug_val,
            _sane_duration(r.duration_seconds),
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
                         recs, cons, brc_rows_by_rp, rp_stats=None) -> list:
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
    rp_stats:          optional {rp: (count, first, last)} bridged whole-
                       corpus stats from the recordings table -- bridges the
                       contributor-facet weights (see _contributor_facets).

    Returns a list of 7-tuples in composers-schema column order:
      (slug, composer_key, display, airings, n_works, works_json, facets_json)

    works_json is that composer's works ranked by -airings then slug (ties
    broken deterministically): [{slug, display, airings}, ...].
    facets_json carries the composer-level analytics the work pages already
    have (2026-07-17 panel review): top_performers/top_conductors/
    top_ensembles/broadcasters over the composer's recording set (broadcaster
    attribution is 2012+ segment-side; contributor counts include bridged
    pre-2012 airings when recording_airings is given), plus by_year -- NEWEST-first {year, airings, works}
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
        facets = _contributor_facets(rps, recs, cons, brc_rows_by_rp,
                                     rp_stats)
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


def compute_rebroadcasts(rows):
    """Identify exact rebroadcasts: episodes whose position-ordered
    recording_pid playlist is identical. rows: iterable of
    (episode_pid, date10, fingerprint) -- the caller runs _REBROADCAST_SQL
    (GROUP_CONCAT supplies the fingerprint). PURE.

    Returns {episode_pid: [date10, ...]}: for every LATER airing in a
    fingerprint group of >=2 episodes, ALL prior distinct dates in the
    group, oldest first. The first airing gets nothing (only rebroadcasts
    carry the notice). Same-date pairs are excluded -- two PIDs on one
    night sharing a playlist are a fragmented night (the 2021-10-31 Music
    for the Hours class), not a temporal rebroadcast.
    """
    dates_of = {}
    groups = {}
    for pid, date10, fingerprint in rows:
        dates_of[pid] = date10
        groups.setdefault(fingerprint, []).append(pid)
    out = {}
    for pids in groups.values():
        if len(pids) < 2:
            continue
        seen_dates = []
        for pid in sorted(pids, key=lambda p: (dates_of[p], p)):
            d = dates_of[pid]
            prior = [x for x in seen_dates if x != d]
            if prior:
                out[pid] = list(prior)
            if d not in seen_dates:
                seen_dates.append(d)
    return out


def _lcp_len(a, b):
    """Length of the common leading run of two strings."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


_CONFIRMED_ENSEMBLE_FLOOR = 10


def _track_ensembles(performers):
    """Ensemble identities credited on a track -- the --by ensemble grouping
    key (resolve_ensemble_alias . canonical_key) over parse_performers'
    ensemble list. PURE. Empty/None performers -> empty set."""
    return {i for i in (resolve_ensemble_alias(canonical_key(n))
                        for n in parse_performers(performers or "")[0]) if i}


def build_confirmed_ensembles(episode_tracks, floor=_CONFIRMED_ENSEMBLE_FLOOR):
    """Ensemble identities with >= floor tracks-lineage airings across the
    corpus. PURE. episode_tracks: the accumulate_entities accumulator
    ({ep: [(pos, time, key, composer, title, performers, rp), ...]}), so the
    confirmed set derives from exactly the performers the detector reads. The
    floor stops a coincidental capitalized phrase or a parse-junk token (the
    'director) Musica Florea' comma-split shape) from corroborating a
    concert -- an ensemble carries weight only once the corpus has seen it
    recur."""
    c = Counter()
    for rows in episode_tracks.values():
        for r in rows:
            for i in _track_ensembles(r[5]):
                c[i] += 1
    return frozenset(i for i, n in c.items() if n >= floor)


def _confirmed_ensemble_index(confirmed):
    """token -> [(identity, token_frozenset)] for the MULTI-TOKEN confirmed
    ensembles. PURE. Lets a parsed ensemble candidate match any confirmed
    identity whose tokens it CONTAINS (a subset) -- recovering a real ensemble
    that parse_performers emitted with a junk affix ('director musica florea'
    from the comma-elided '(cello, director) Musica Florea' contains 'musica
    florea'). Single-token confirmed identities are EXCLUDED: a bare
    'sinfonia'/'orchestra'/'ensemble' token subsets too many distinct names."""
    idx = defaultdict(list)
    for c in confirmed:
        ts = frozenset(c.split())
        if len(ts) >= 2:
            for t in ts:
                idx[t].append((c, ts))
    return idx


def _track_confirmed_ensembles(performers, confirmed, index):
    """Confirmed ensembles a track credits: exact identity matches PLUS
    multi-token confirmed identities whose tokens are a SUBSET of a parsed
    ensemble candidate's tokens (via index). PURE. The subset arm inspects
    ONLY parsed ensembles (parse_performers output), never the raw performers
    text, so a role annotation like '(piano)' can never match -- the failure
    mode that sinks a raw-substring approach. Subset addends are still gated
    by the confirmed floor (they are keys of `confirmed`)."""
    parsed = _track_ensembles(performers)
    present = parsed & confirmed
    for e in parsed:
        te = frozenset(e.split())
        if len(te) < 2:
            continue
        seen = set()
        for t in te:
            for c, ts in index.get(t, ()):
                if c not in seen:
                    seen.add(c)
                    if ts <= te:
                        present.add(c)
    return present


def _contributor_names(rp, meta):
    """Lowercased contributor names of a recording. Composer/Music Arranger
    were already excluded at meta build time. An rpid missing from meta
    (shouldn't happen -- detection pids come from the projection, whose
    targets are all in segment_events) yields an empty set, so the chain
    conservatively breaks."""
    return {n.lower() for _r, n in meta.get(rp, {}).get("credits", ())}


def _conductor_names(rp, meta):
    """Lowercased Conductor-role names of a recording (empty if none credited).
    The ensemble-arm conductor-contradiction veto in detect_opening_concert
    consumes it -- an ensemble under a DIFFERENT named conductor is a different
    performance, not the same concert relay."""
    return {n.lower() for r, n in meta.get(rp, {}).get("credits", ())
            if r == "Conductor"}


# STAFF override for opening-concert length, keyed by episode_pid. The
# detector is a DISPLAY heuristic; where it still mis-bounds a specific night
# after the rejoin-bridge, name it here rather than loosen the heuristic for
# everyone (the ttn_segment_meta override precedent). Value n>=2 forces a
# concert of that many leading tracks; n=0 (or 1) SUPPRESSES a false-positive
# concert. Clamped to the night's track count. Part of the site fingerprint
# (ttn_site.py bytes), so an edit here rebuilds the affected episode pages.
_OPENING_CONCERT_OVERRIDES: dict = {}


def compute_opening_concerts(episode_tracks, projection, presentation, meta,
                             brc_slugs, confirmed_ensembles):
    """Detect + label every episode's opening concert. PURE.

    episode_tracks: accumulate_entities' accumulator {episode_pid: [(pos,
    time_str, key, composer, title, performers, rp), ...]} -- consulted for
    the POSITION LIST and the per-track PERFORMERS. Detection pids come from
    the HIGH-tier projection ({(episode_pid, pos): recording_pid}) FALLING BACK
    to the MEDIUM presentation link when High is absent. The graduated-trust
    rule excludes Medium from IDENTITY (a Medium link says "this airing is this
    recording", not what the WORK is) -- but detection never consumes work
    identity; it needs only the recording GROUPING (the pid-prefix chain) plus
    contributor/ensemble corroboration, both of which a Medium pid supplies,
    and every Medium pid must still independently pass the prefix AND
    corroboration gates. This recovers the early-era (2012-14) concerts whose
    OPENING track matched only at Medium tier, which the High-only source could
    not even start (pids[0] None -> 0) -- e.g. the b04b2c0w Orchestre National
    de France night. `presentation` is the spine-FILTERED map (rp in recs), so
    a fallback pid always has a recordings row. `projection`/`presentation`:
    {(episode_pid, pos): recording_pid}. meta: build_recording_concert_meta
    output. brc_slugs: mint_broadcaster_slugs(). confirmed_ensembles:
    build_confirmed_ensembles output -- the ensemble corroboration arm. Per
    track the confirmed-ensemble set is exact identity matches UNION multi-
    token subset matches (_track_confirmed_ensembles), so a real ensemble
    parse_performers emitted with a junk affix still corroborates.

    Returns {episode_pid: {"n", "label", "broadcaster_name",
    "broadcaster_slug"}} -- only episodes WITH a detected concert.
    """
    index = _confirmed_ensemble_index(confirmed_ensembles)
    out = {}
    for ep, rows in episode_tracks.items():
        perf_by_pos = {r[0]: r[5] for r in rows}
        positions = sorted(perf_by_pos)
        pids = [projection.get((ep, pos)) or presentation.get((ep, pos))
                for pos in positions]
        ens = [_track_confirmed_ensembles(perf_by_pos[pos], confirmed_ensembles,
                                          index)
               for pos in positions]
        n = detect_opening_concert(pids, meta, ens)
        override = _OPENING_CONCERT_OVERRIDES.get(ep)
        if override is not None:
            n = min(override, len(positions))
            if n < 2:
                n = 0                                   # 0/1 = suppress
        if n:
            label = _concert_label(pids[:n], meta, brc_slugs)
            # A single-work concert (n == 1, reachable only from the single-work
            # arm -- multi-track returns >=2, an override never yields 1) earns a
            # header ONLY when its EBU source resolves: over one row the source is
            # the sole thing the header adds, so a bare "Opening concert" would be
            # pure clutter. Multi-track headers keep the bare form (they still
            # group N rows visually).
            if n == 1 and not label["broadcaster_name"]:
                continue
            out[ep] = label
    return out


# Broadcaster display names that take a definite article after "from" --
# "Opening concert from the BBC", not "from BBC". English-acronym public
# broadcasters only; every other name reads correctly bare ("from Polskie
# Radio", "from Catalunya Musica").
_ARTICLE_BROADCASTERS = frozenset({"BBC", "ABC", "CBC (English)"})


def _concert_label(run_pids, meta, brc_slugs):
    """Derive the display object for a detected opening concert. run_pids:
    the run's pids (length n -- may contain the one bridged None gap row).
    meta: build_recording_concert_meta output. brc_slugs:
    mint_broadcaster_slugs() output ({code: (slug, name, country)}). PURE.

    Returns {"n", "broadcaster_name", "broadcaster_slug"}.

    Only the EBU SOURCE BROADCASTER is named. Computed "forces" were dropped
    (hedydd 2026-07-26): the concert's performers are already shown per-track
    in the Performers column, and the BBC's own per-night subtitle names the
    concert humanly, so naming forces here only duplicated the row below,
    clashed with it on spelling (segment lineage vs tracks lineage), or
    misattributed a recital's lead (the continuo player wins a count over the
    soloist). The broadcaster is the one thing the header adds -- the source
    appears nowhere in the rows.

    Broadcaster: the modal non-null record_label across the run, folded to
    its canonical EBU code and looked up in brc_slugs; an undecodable label
    (commercial codes like DECCA) yields None/None -- the header degrades to
    a bare "Opening concert".
    """
    labels = [meta[rp]["label"] for rp in run_pids
              if rp is not None and meta.get(rp) and meta[rp]["label"]]
    broadcaster_name = broadcaster_slug = None
    if labels:
        modal = Counter(labels).most_common(1)[0][0]
        hit = brc_slugs.get(ttn_ebu_codes.fold(modal))
        if hit:
            broadcaster_slug, broadcaster_name = hit[0], hit[1]
    return {"n": len(run_pids),
            "broadcaster_name": broadcaster_name,
            "broadcaster_slug": broadcaster_slug,
            "broadcaster_article": broadcaster_name in _ARTICLE_BROADCASTERS}


# Rejoin-bridge tuning. PREFIX_MIN is deliberately tighter than the
# contributor arm's 4 (a bridge waives the corroboration a normal step needs,
# so it must be more certain the tracks are one mint batch); MAX caps how many
# consecutive interior tracks a single bridge may span (>2 consecutive solo
# interludes is rare, and a looser cap starts admitting whole-night batches).
_CONCERT_BRIDGE_PREFIX_MIN = 5
_CONCERT_BRIDGE_MAX = 2

# SINGLE-WORK concert floor. When the multi-track relay finds nothing, an opening
# track this long (seconds) is itself the night's featured concert -- a Mass,
# oratorio, opera act, or long symphony presented whole (TTN's block-1 shape).
# 50 min: above the ordinary symphony/concerto length (~40 min, where "one work
# = a concert" is a weak claim and the count balloons), below the shortest genuine
# single-work centrepieces (Mahler 1, Symphonie fantastique ~54 min). Measured
# 2026-08-10 on the corpus: admits ~160 nights, every one a real centrepiece.
_LONG_CONCERT_SECONDS = 3000

# STAFF allowlist of opener RECORDINGS that are a single-work concert BELOW the
# length floor -- a genuine featured concert (a live relay of a complete choral
# work, a short oratorio) that the conservative floor can't auto-catch without
# admitting ordinary ~40-min first tracks. Keyed by the opener's recording_pid
# (NOT episode_pid) so it is airing-invariant: one entry covers every rebroadcast
# of that concert automatically -- the RECORDING_TITLE_OVERRIDES pattern. It
# waives ONLY the length test; the single-work arm's standalone guard (track 2
# shares no broadcaster/prefix/ensemble) still runs, so an allowlisted recording
# is never flagged on an airing where it's actually part of a multi-track relay.
_SINGLE_WORK_CONCERT_RECORDINGS = frozenset({
    "p0mgv76b",   # Pergolesi Stabat Mater, live Kyiv relay (UAPBC), 39:05 --
                  # m002lnzj 2025-11-15 + m002x4rd 2026-06-11 rebroadcast
    "p0fsh442",   # Papandopulo Slavoslovije, cantata for soloists/chorus/orch
                  # (HRHRTR), 49:54 -- m001md94 2023-06-06 + m001vcrc 2024-01-22
    "p0c1f56v",   # Haydn, Seven Last Words (Stenhammar Quartet, SESR), 43:37 --
                  # m001629y 2022-04-15, the night's headline concert
})


def detect_opening_concert(pids, meta, ens):
    """Find the opening concert relay: the run of >=2 leading tracks that
    are one concert. pids: [recording_pid|None, ...] over an episode's
    tracks in broadcast order (the High-tier projection). meta:
    build_recording_concert_meta output. ens: per-track confirmed-ensemble
    identity sets aligned with pids (compute_opening_concerts builds them via
    _track_ensembles & the confirmed set). Returns the number of leading rows
    belonging to the concert (>= 2), or 0 when there is none.

    The run extends against the previous pid-carrying track when EITHER arm
    holds -- `ens_ok OR (prefix AND contributor)`:
      - ENSEMBLE arm (ens_ok): the track shares >= 1 CONFIRMED ENSEMBLE with
        the run's ensembles so far (the RUNNING UNION), AND does not name a
        conductor DISJOINT from every conductor seen so far (the veto below).
        This arm WAIVES the prefix gate -- a single confirmed ensemble threading
        the run carries it across a mint-batch break, recovering concerts whose
        works were minted APART (a concerto whose soloist recording is minted
        separately; a 2010-16 Baroque-ensemble programme where each work is its
        own mint batch -- b081tgr1 Warsaw Phil, b01s5mff Il Giardino Armonico).
        It also recovers the false negatives where the early segment feed credits
        ONLY the composer, so the contributor union is empty across one real
        concert and the ensemble lives only in the tracks-lineage performers
        (b0375qn6, the Musica Florea shape).
        CONDUCTOR-CONTRADICTION VETO: because the arm waives the prefix, the same
        ensemble under a DIFFERENT named conductor would otherwise fuse two
        performances into one "concert" -- the b046cpx2 shape (an Oslo Phil /
        Petrenko concert with a separately-minted Oslo Phil / Holliger Rosamunde
        appended) and, larger, the same-orchestra-different-conductor ARCHIVE
        COMPILATIONS the BBC strings together (b04mb5rf, "great conductors of the
        Concertgebouw"; m0002cby, RTV Slovenia under three conductors). So a
        joining track whose conductor set is non-empty and disjoint from
        cond_union vetoes the waiver. It is silent when either side credits no
        conductor, so the Baroque-ensemble cases (one director throughout, or
        composer-only segment credits) are untouched. Measured 2026-07-27: 87
        episodes tighten (25 dissolve as pure compilations, 62 trim to the
        genuine same-conductor concert core) -- the docstring's former "<= 9"
        estimate counted only same-CONDUCTOR library segues and missed this
        larger class.
      - CONTRIBUTOR arm: the track shares >= 1 CONTRIBUTOR name with the run's
        contributors so far AND the pids share >= 4 leading chars (prefix; a
        chain, not anchored to the first pid, so a mint-digit rollover like
        p0nkp6k7 -> p0nkq2ab inside one concert does not truncate it). The
        prefix is REQUIRED on this arm: contributor overlap alone (a shared
        soloist/conductor) is weaker evidence, and the prefix confines the
        running union to the same mint batch so it cannot spuriously rejoin an
        unrelated later recording. This arm rejects the 2012-13 whole-night
        mint batches (different ensembles per track -> no shared contributor)
        and lets a concerto's orchestra REJOIN after solo encores crediting
        only the soloist (the m001znsw shape).
    Why the ensemble arm can waive the prefix safely: the whole-night mint
    batch it must not re-admit carries DIFFERENT ensembles per track, so ens_ok
    never fires there; and a same-ensemble different-performance segue is caught
    by the conductor-contradiction veto above whenever both sides name a
    conductor. The run is NO LONGER strictly contiguous: a track holding by
    neither arm may be BRIDGED to a later track that rejoins the running union,
    but only under the tight-prefix + single-broadcaster + no-conductor-clash
    gates in the bridge block below (see there). Exactly one None gap may also
    be bridged (a single missing High projection should not truncate a real
    concert); the boundary checks compare across it, and a bridged gap row
    counts in n (it sits between two concert tracks). pids[0] None -> 0: the
    concert must start the night.
    """
    if not pids or pids[0] is None:
        return 0
    last = 0
    prev = pids[0]
    union = set(_contributor_names(pids[0], meta))
    ens_union = set(ens[0])
    cond_union = set(_conductor_names(pids[0], meta))
    run_labels = {(meta.get(pids[0]) or {}).get("label")} - {None}
    gap_used = False
    i = 1
    n_total = len(pids)
    while i < n_total:
        rp = pids[i]
        if rp is None:
            if gap_used:
                break
            gap_used = True
            i += 1
            continue
        names = _contributor_names(rp, meta)
        conds = _conductor_names(rp, meta)
        # The ensemble arm waives the prefix -- but a track naming a conductor
        # DISJOINT from every conductor seen so far is a different performance of
        # the same ensemble (an archive segue, or a "great conductors of X"
        # compilation strung under one orchestra), not one concert relay. Veto
        # the waiver in that case. Silent when either side names no conductor, so
        # the Baroque-ensemble cases (one director, or composer-only credits) are
        # untouched; the contributor arm is deliberately NOT gated (a shared
        # prefix already confines it to one mint batch).
        cond_clash = bool(conds and cond_union and not (conds & cond_union))
        ens_ok = bool(ens[i] & ens_union) and not cond_clash
        if ens_ok or (_lcp_len(rp, prev) >= 4 and (names & union)):
            last = i
            prev = rp
            union |= names
            ens_union |= ens[i]
            cond_union |= conds
            lab = (meta.get(rp) or {}).get("label")
            if lab:
                run_labels.add(lab)
            i += 1
            continue

        # REJOIN-BRIDGE: this track corroborates by neither arm. Rather than stop
        # (the old greedy contiguity), bridge up to _CONCERT_BRIDGE_MAX interior
        # tracks to a later track that REJOINS the running union -- a solo
        # interlude inside a choral concert (b06pxjfw) or an ensemble handover
        # (m001slz5). Gated hard so it cannot fuse an ADJACENT different concert
        # that merely shares the mint batch (b06pxjfw pos 10, a Slovak quartet
        # under the same p0399 prefix that rejoins nothing): every non-None track
        # in the bridged span must
        #   (a) stay in the TIGHT mint family (>= _CONCERT_BRIDGE_PREFIX_MIN
        #       leading chars vs the last concert pid -- tighter than the arm's 4),
        #   (b) introduce NO second non-null record_label (one concert is one EBU
        #       source relay; two sources = a themed compilation minted together,
        #       the Pau Casals-tribute shape), and
        #   (c) name NO conductor disjoint from those seen (the ensemble arm's
        #       veto, extended here -- kills the same-broadcaster/different-
        #       conductor archive compilation).
        # Without all three this is exactly the whole-night-batch fusion the
        # contiguity guard existed to prevent. The corpus measurement
        # (scratch/concert_bridge_measure) backs the reversal: +126 real concerts
        # recovered, 0 cross-broadcaster fuses left.
        bridged_to = None
        for r in range(i + 1, min(i + _CONCERT_BRIDGE_MAX, n_total - 1) + 1):
            span = [p for p in pids[i:r + 1] if p is not None]
            if any(_lcp_len(p, prev) < _CONCERT_BRIDGE_PREFIX_MIN for p in span):
                break                                   # mint family ended
            span_labels = {(meta.get(p) or {}).get("label") for p in span} - {None}
            if len(run_labels | span_labels) > 1:
                break                                   # second broadcaster
            if any(_conductor_names(p, meta) and cond_union
                   and not (_conductor_names(p, meta) & cond_union) for p in span):
                break                                   # conductor contradiction
            rp_r = pids[r]
            if rp_r is None:
                continue
            names_r = _contributor_names(rp_r, meta)
            if (ens[r] & ens_union) or (_lcp_len(rp_r, prev) >= 4 and (names_r & union)):
                bridged_to = r
                break
        if bridged_to is None:
            break
        for k in range(i, bridged_to + 1):              # absorb interludes + rejoin
            pk = pids[k]
            if pk is None:
                continue
            union |= _contributor_names(pk, meta)
            ens_union |= set(ens[k])
            cond_union |= _conductor_names(pk, meta)
            lab = (meta.get(pk) or {}).get("label")
            if lab:
                run_labels.add(lab)
        last = bridged_to
        prev = pids[bridged_to]
        i = bridged_to + 1
    n = last + 1
    if n >= 2:
        return n

    # SINGLE-WORK concert arm: no multi-track relay was found (last == 0), so the
    # featured concert -- if there is one -- is the lone opener presented whole.
    # Flag it only when it is (a) long enough to BE the concert (>=
    # _LONG_CONCERT_SECONDS) and (b) genuinely standalone: the next track shares
    # no mint prefix, no broadcaster, and no confirmed ensemble with it. Any of
    # those three would mark an under-detected relay (e.g. a segment feed that
    # credits only the composer, so the contributor arm couldn't join two tracks
    # of one concert) rather than a solo work -- exactly the case this arm must
    # NOT mislabel. The broadcaster-NAMING gate (the single-row header's whole
    # value is the EBU source) lives in compute_opening_concerts.
    d0 = (meta.get(pids[0]) or {}).get("duration") or 0
    if d0 < _LONG_CONCERT_SECONDS and pids[0] not in _SINGLE_WORK_CONCERT_RECORDINGS:
        return 0
    if n_total == 1:
        return 1                                    # lone track: trivially standalone
    p1 = pids[1]
    lab0 = (meta.get(pids[0]) or {}).get("label")
    lab1 = (meta.get(p1) or {}).get("label") if p1 else None
    same_brc = lab0 is not None and lab0 == lab1
    prefix = p1 is not None and _lcp_len(pids[0], p1) >= 4
    ens_cont = bool(ens[0] & ens[1])
    if same_brc or prefix or ens_cont:
        return 0
    return 1


def build_recording_concert_meta(rows):
    """Per-recording contributor index for opening-concert detection.
    rows: iterable of (recording_pid, contributions_json, record_label[,
    duration_seconds]) -- the caller runs _OPENING_CONCERT_SQL. A 3-tuple row
    (no duration) is tolerated: the recording simply carries no "duration" key.
    PURE.

    -> {recording_pid: {"credits": frozenset of (role, name),
                        "label": record_label or None,
                        "duration": max duration_seconds seen (only if any)}}.

    Composer and Music Arranger roles are dropped: they vary per track BY
    CONSTRUCTION (a concert is several works; an encore its own arranger),
    so they can only fake or dilute corroboration, never supply it. An
    unparseable contributions_json yields an empty credit set (the chain
    simply breaks there -- conservative, never fatal). Duration is the MAX
    across a recording's airings (a recording's length is a property of the
    recording); it feeds the single-work concert arm in detect_opening_concert.
    """
    out = {}
    durs = {}
    for row in rows:
        rpid, contributions_json, record_label = row[0], row[1], row[2]
        duration = row[3] if len(row) > 3 else None
        if duration is not None:
            durs[rpid] = max(durs.get(rpid, 0), duration)
        credits = set()
        try:
            contribs = json.loads(contributions_json)
        except (TypeError, ValueError):
            contribs = []
        for c in contribs:
            role = c.get("role")
            name = (c.get("name") or "").strip()
            if name and role not in ("Composer", "Music Arranger"):
                credits.add((role, name))
        out[rpid] = {"credits": frozenset(credits),
                     "label": record_label or None}
    for rpid, d in durs.items():
        out[rpid]["duration"] = d
    return out


# TTN's signature theme (the 32s Milhaud interstitial) airs at the ~2h and ~4h
# block boundaries but is carried in neither tracks nor segment_events, so the
# playlist loses those mid-night anchor points. Re-insert them as display-only
# markers keyed off each night's OWN cadence (start times varied until mid-2024
# -- ttn-start-time-grid), never as tracks: they enter no ranking and carry no
# slug/pid, so check_closure ignores them by construction.
_THEME_BOUNDARIES = (2 * 3600, 4 * 3600)


def insert_theme_markers(tracks):
    """Return tracks with synthetic {"theme_marker": True} entries inserted at
    the 2h/4h block boundaries. PURE. tracks is the build_episode_rows dict
    list in broadcast order; real entries keep their pos untouched (the
    position-keyed airing anchors must stay valid). A boundary gets a marker
    only if a track exists BEFORE and AT/AFTER it (the straddle guard), so
    short / fragmented / pre-2012-structured nights naturally get fewer or none
    -- no hard era gate. Offsets are relative-to-first-track with midnight-wrap
    handling (ttn_mbid_audit.episode_offsets); unparseable times don't shift or
    trigger a marker."""
    offsets = ttn_mbid_audit.episode_offsets([t["time"] for t in tracks])
    insert_before = set()
    for b in _THEME_BOUNDARIES:
        if not any(o is not None and o < b for o in offsets):
            continue
        after = next((i for i, o in enumerate(offsets)
                      if o is not None and o >= b), None)
        if after is not None:
            insert_before.add(after)
    if not insert_before:
        return tracks
    out = []
    for i, t in enumerate(tracks):
        if i in insert_before:
            out.append({"theme_marker": True})
        out.append(t)
    return out


# The novelty maturity floor: work-first badges/notes display only on airings
# at/after this date. It equals ttn_segments.SEGMENTS_FLOOR_DATE (the first date
# with recording PIDs / segment_events), but is an INDEPENDENT knob -- the
# novelty claim rests on recording-anchored identity, which begins here; before
# it, "first in our records" is dominated by left-censoring (the work almost
# certainly aired before our data starts). Kept as its own constant so a change
# to the segments backfill floor does not silently move the novelty gate.
_NOVELTY_FLOOR_DATE = "2012-03-15"


def build_work_first_dates(episode_tracks, date_of_pid):
    """{(ck, wk): earliest date10} over ALL corpus airings. PURE.

    episode_tracks: accumulate_entities' {pid: [(pos, time, key, composer,
                    title, performers, rp), ...]} -- key is (ck, wk) or None.
    date_of_pid:    {episode_pid: date10} (from episode_meta).

    Uses the full history (both lineages) so a later airing of an early work
    correctly does NOT read as a first. Rows with key None (unkeyed junk) and
    episodes with no date are skipped.
    """
    out = {}
    for pid, rows in episode_tracks.items():
        d = date_of_pid.get(pid)
        if not d:
            continue
        for row in rows:
            key = row[2]
            if key is None:
                continue
            if key not in out or d < out[key]:
                out[key] = d
    return out


def build_episode_rows(episode_meta, episode_tracks, work_slug_of,
                        composer_slug_of, known_rps, rec_duration_of,
                        rebroadcasts, concerts, work_first_dates) -> list:
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
    rec_duration_of: {recording_pid: seconds|None} -- measured recording
                     duration (already _sane_duration-guarded). A track whose rp
                     is absent (unprojected/pre-2012) or maps to None (sub-floor)
                     gets duration=None -> a blank Length cell. Required, not
                     defaulted (the known_rps precedent).
    rebroadcasts:    {episode_pid: [date10, ...]} from compute_rebroadcasts --
                     prior dates of identical full broadcasts. Required, not
                     defaulted, for the same loud-failure reason as known_rps.
    concerts:        {episode_pid: {"n", "label", "broadcaster_name",
                     "broadcaster_slug"}} from compute_opening_concerts.
                     Required, not defaulted (the known_rps precedent).
    work_first_dates: {(ck, wk): earliest date10} from build_work_first_dates.
                     A track earns "work_first": True when its work key's
                     earliest airing IS this night AND this night is at/after
                     _NOVELTY_FLOOR_DATE. Required, not defaulted (the known_rps
                     precedent -- a missing map must fail loud, not silently
                     un-badge every track).

    Returns a list of 7-tuples in episodes-schema column order:
      (pid, date, title, bbc_url, tracks_json, rebroadcast_dates_json,
       opening_concert_json)
    The 8th column (national_day_json) is appended downstream by
    attach_episode_national_days, once the national_days payload exists (that
    payload is built after this row builder runs).

    tracks_json is a list of {pos, time, work_slug, composer_slug, composer,
    title, performers, recording_pid, duration} in broadcast order. A junk row (key is
    None) gets work_slug=None and composer_slug=None -- it renders as plain
    text rather than a dead link. A pid with no rows in episode_tracks (the
    75 pre-2010 zero-track anchors) gets tracks_json = []. Synthetic
    {"theme_marker": True} entries (insert_theme_markers) may be interleaved
    at the 2h/4h block boundaries -- display-only, no slug/pid, not a track.
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
                "duration": rec_duration_of.get(rp),
                "work_first": (
                    key is not None
                    and date >= _NOVELTY_FLOOR_DATE
                    and work_first_dates.get(key) == date
                ),
            })
        tracks = insert_theme_markers(tracks)
        rows.append((
            pid,
            date,
            title,
            f"https://www.bbc.co.uk/programmes/{pid}",
            json.dumps(tracks),
            json.dumps(rebroadcasts.get(pid, [])),
            json.dumps(concerts[pid]) if pid in concerts else None,
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
                           form_rows=(), artist_slug_of=None,
                           country_rows=(), year_texture=None,
                           year_breakdown=None) -> list:
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
    artist_slug_of:    {mbid: artist slug} from the SYNCED artist registry
                       (keyword-only). Links the contributor-listing rows
                       (ensembles/conductors/performers/singers) to their
                       /artist/ pages; omitted/None -> all rows link-less.
    year_texture:      {year: {"anniversaries": [...], "distinctive": [...]}}
                       from build_year_texture (keyword-only). Enriches each
                       `years` entry with a single pre-rendered `notables`
                       string: the top effect_visible headline-tier
                       anniversary composer's SURNAME + " (anniversary)"
                       (if any), then up to two distinctive composers' full
                       display names, comma-joined -- e.g. "Palestrina
                       (anniversary), Henriette Bosmans, Mel Bonis", or ""
                       when there's nothing to show -- so the index card is
                       self-contained and Jinja stays logic-free.
                       Omitted/None -> "".
    year_breakdown:    compute_year_breakdown's output shape (keyword-only),
                       precomputed by the CALLER. The default path re-derives
                       identity keys from all_rows5 through the LEGACY alias
                       chain (strip_arranger_tail + resolve_composer_alias +
                       resolve_work_alias), which would re-fold the
                       de-globalized successor identities -- so the
                       successor build passes year_breakdown_t2(acc) here and
                       all_rows5 goes unconsumed. None (default) = the legacy
                       computation, byte-identical.

    Returns [(name, payload_json), ...] with THIRTEEN payloads:
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
      conductors / performers / singers
                        -- per-role identity rankings (2012+), each the same
                           dict shape as `ensembles`: {cut, total, rows} with
                           rows at/above the airings cut; a row whose MBID is
                           a registered artist carries its slug (else null,
                           rendered link-less). Note the listing cut is
                           per-ROLE while page minting is combined-role, so a
                           page can exist for someone below a single role's
                           cut (reachable via collaborators/search) -- an
                           accepted edge.
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
      years             -- compute_year_breakdown(all_rows5), each entry
                           enriched with `notables` (see year_texture above).
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

    # ensembles + the per-role people listings: identity rankings over the
    # whole-corpus spine structures (already built by the caller -- near-zero
    # marginal cost), cut at the airings quality line. total counts EVERY
    # identity (ensembles' feeds the home-page stat), rows only those above
    # the cut; a registered artist's row carries its /artist/ page slug.
    slug_of_mbid = artist_slug_of or {}

    def _contributor_listing(roles, cut):
        stats = ttn_spine.rank_contributors(recs, cons, roles)
        return {
            "cut": cut,
            "total": len(stats),
            "rows": [
                {"display": s.display_name, "airings": s.airings,
                 "performances": s.recordings,
                 "slug": slug_of_mbid.get(s.mbid)}
                for s in stats if s.airings >= cut
            ],
        }

    ensembles = _contributor_listing(_ENSEMBLE_ROLES, _ENSEMBLES_AIRINGS_CUT)
    conductors = _contributor_listing({"Conductor"}, _ARTIST_LISTING_CUT)
    performers = _contributor_listing({"Performer"}, _ARTIST_LISTING_CUT)
    singers = _contributor_listing({"Singer"}, _ARTIST_LISTING_CUT)

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
    def _surname(name):
        return name.split()[-1] if name else ""

    years = list(reversed(year_breakdown if year_breakdown is not None
                          else compute_year_breakdown(all_rows5)))
    texture = year_texture or {}
    for y in years:
        tex = texture.get(y["year"], {})
        a = next(
            (a for a in tex.get("anniversaries", [])
             if a["tier"] == "headline" and a["badge"] == "effect_visible"),
            None)
        parts = []
        if a is not None:
            parts.append(f"{_surname(a['composer'])} (anniversary)")
        for d in tex.get("distinctive", [])[:(2 if a else 3)]:
            parts.append(d["composer"])
        y["notables"] = ", ".join(parts)

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

    # countries: the source-country rollup ranking. Ordered/accounted by
    # rank_broadcasters(country_key) (so OTHER/UNATTRIBUTED are link-less rows,
    # pinned last, exactly like broadcasters); slug + n_broadcasters join from
    # the BUILT country_rows (closure-safe -- a real country always has a page).
    country_meta = {r[1]: (r[0], r[4]) for r in country_rows}  # country -> (slug, n_brc)
    country_stats = ttn_broadcasters.rank_broadcasters(
        all_brc_rows, rank_key=ttn_broadcasters.country_key)
    countries = []
    for s in country_stats:
        slug, n_brc = country_meta.get(s.key, (None, None))
        countries.append({"display": s.key, "slug": slug, "airings": s.airings,
                          "recordings": s.recordings, "n_broadcasters": n_brc})

    # house_performances: top-50 works by total airings; within each, restrict
    # to 2016+ recording-anchored airings and find the dominant recording_pid.
    # Per-recording EBU labels, for the house recording's majority broadcaster
    # (same rule as the recordings-table / work-facet broadcaster column).
    brc_by_rp: dict = {}
    for label, rp in all_brc_rows:
        if label:
            brc_by_rp.setdefault(rp, []).append(label)
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

        broadcaster, broadcaster_slug_val = _majority_broadcaster(
            brc_by_rp.get(dominant_rp, []), minted_slugs)

        clist = cons.get(dominant_rp, [])
        house_performances.append({
            "work_slug": e["slug"],
            "work_display": e["work_display"],
            "composer_display": composer_display_of.get(ck) or e["composer_display"],
            "composer_slug": composer_slug_of.get(ck),
            "recording_pid": dominant_rp,
            "rec_airings": rec_airings,
            "total_2016": total_2016,
            "broadcaster": broadcaster,
            "broadcaster_slug": broadcaster_slug_val,
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
        ("conductors", json.dumps(conductors)),
        ("performers", json.dumps(performers)),
        ("singers", json.dumps(singers)),
        ("lengths", json.dumps(lengths)),
        ("forms", json.dumps(forms)),
        ("christmas", json.dumps(christmas)),
        ("years", json.dumps(years)),
        ("broadcasters", json.dumps(broadcasters)),
        ("countries", json.dumps(countries)),
        ("house_performances", json.dumps(house_performances)),
    ]


# Year-texture tunables (cerys-reviewed 2026-08-12; see the spec).
_DISTINCTIVE_MIN_PLAYS = 10
_DISTINCTIVE_MIN_LIFT = 1.4
_ANNIVERSARY_MIN_PLAYS = 15
_ANNIVERSARY_LIFT_VISIBLE = 1.3
_NON_PERSON_COMPOSER_DISPLAYS = frozenset({
    "anonymous", "anon", "anon.", "traditional", "trad", "trad.", "various",
})
_YEAR_TOP_N = 20
# Texture is validated only from the clean-synopsis floor (2010-01-17) up --
# below it identity/parsing is unreliable (the "Bach forever" distinctive-top
# artifact). Baselines still use full history; only the returned years are cut.
_YEAR_TEXTURE_FLOOR_YEAR = 2010

# A composer_line endpoint is CONFIDENT only as a bare 4-digit year. The regex
# captures the two endpoints of a "(birth-death)" span; each endpoint is then
# accepted only if it is exactly 4 digits with no confidence-eroding prefix
# (c., ?, fl.). An absent/open endpoint (living composer, "(1935-)") is None.
_COMPOSER_SPAN_RE = re.compile(r"\(\s*([^)\-–]*?)\s*[-–]\s*([^)]*?)\s*\)")
_CONFIDENT_YEAR_RE = re.compile(r"^\d{4}$")


def _confident_year(tok):
    tok = (tok or "").strip()
    return int(tok) if _CONFIDENT_YEAR_RE.match(tok) else None


def parse_composer_years(composer_line):
    """(birth, death) as CONFIDENT 4-digit years or None each. PURE.
    'c.1650'/'?'/'fl.'/missing -> None for that endpoint, so a documented death
    survives an uncertain birth (cerys 2026-08-12)."""
    if not composer_line:
        return (None, None)
    m = _COMPOSER_SPAN_RE.search(composer_line)
    if not m:
        return (None, None)
    return (_confident_year(m.group(1)), _confident_year(m.group(2)))


def build_composer_year_counts(work_airings):
    """{ck: {year: plays}} from the accumulator. PURE."""
    out = {}
    for (ck, _wk), airings in work_airings.items():
        d = out.setdefault(ck, {})
        for (bd, _rp, _perf, _ep, _pos) in airings:
            if not bd:
                continue
            yr = bd[:4]
            d[yr] = d.get(yr, 0) + 1
    return out


def year_lift(year_counts, year):
    """(plays, baseline, lift) for `year` vs the composer's OTHER active years.
    baseline = mean of the other years' counts; single-year -> (plays, None,
    None). PURE."""
    plays = year_counts.get(year, 0)
    others = [n for y, n in year_counts.items() if y != year]
    if not others:
        return (plays, None, None)
    baseline = sum(others) / len(others)
    return (plays, baseline, plays / baseline if baseline else None)


def _anniversary_badge(plays, baseline, lift):
    if lift is None:
        return None
    return "effect_visible" if lift >= _ANNIVERSARY_LIFT_VISIBLE else "no_lift"


def build_year_anniversaries(composer_year_counts, composer_dates,
                             composer_slug_of, composer_display_of):
    """{year: [anniversary entry, ...]} -- round (multiple-of-50) birth/death
    anniversaries of composers with >= _ANNIVERSARY_MIN_PLAYS that year, each
    baseline-badged; birth+death in one year merges to a `double`. Entries
    with no measurable rise (badge == "no_lift") are dropped. PURE."""
    out = {}
    for ck, dates in composer_dates.items():
        if not ck:
            continue
        if (composer_display_of.get(ck, "") or "").strip().lower() in _NON_PERSON_COMPOSER_DISPLAYS:
            continue
        birth, death = dates
        yc = composer_year_counts.get(ck, {})
        disp = composer_display_of.get(ck, ck)
        slug = composer_slug_of.get(ck)
        for year, plays in yc.items():
            if plays < _ANNIVERSARY_MIN_PLAYS:
                continue
            yi = int(year)
            hits = []           # (kind, nth)
            for base, kind in ((birth, "birth"), (death, "death")):
                if base is None:
                    continue
                nth = yi - base
                if nth > 0 and nth % 50 == 0:
                    hits.append((kind, nth))
            if not hits:
                continue
            _plays, baseline, lift = year_lift(yc, year)
            badge = _anniversary_badge(plays, baseline, lift)
            if len(hits) == 2:                     # birth AND death same year
                entry = {"composer": disp, "slug": slug, "kind": "double",
                        "nth": None, "births": hits[0][1], "deaths": hits[1][1],
                        "base_year": None, "plays": plays, "baseline": baseline,
                        "tier": "headline", "badge": badge, "double": True}
            else:
                kind, nth = hits[0]
                base = birth if kind == "birth" else death
                entry = {"composer": disp, "slug": slug, "kind": kind, "nth": nth,
                        "base_year": base, "plays": plays, "baseline": baseline,
                        "tier": "headline" if nth % 50 == 0 else "secondary",
                        "badge": badge, "double": False}
            if entry["badge"] == "no_lift":
                continue
            out.setdefault(year, []).append(entry)
    for year in out:
        out[year].sort(key=lambda e: (e["badge"] != "effect_visible", -e["plays"]))
    return out


def build_year_distinctive(composer_year_counts, composer_slug_of,
                           composer_display_of):
    """{year: [distinctive entry, ...]} -- composers played furthest above their
    OWN long-run average, floored by _DISTINCTIVE_MIN_PLAYS/_MIN_LIFT, top 10 by
    lift. PURE."""
    by_year = {}
    for ck, yc in composer_year_counts.items():
        for year in yc:
            plays, baseline, lift = year_lift(yc, year)
            if lift is None or plays < _DISTINCTIVE_MIN_PLAYS:
                continue
            if lift < _DISTINCTIVE_MIN_LIFT:
                continue
            by_year.setdefault(year, []).append({
                "composer": composer_display_of.get(ck, ck),
                "slug": composer_slug_of.get(ck),
                "plays": plays, "baseline": baseline, "lift": lift})
    for year in by_year:
        by_year[year].sort(key=lambda e: -e["lift"])
        by_year[year] = by_year[year][:10]
    return by_year


# Year-arrivals tunables (v1.5; see the spec).
_ARRIVAL_MIN_LATER_YEARS = 4
_ARRIVAL_FLOOR_YEAR = 2016
_ARRIVAL_HINDSIGHT_YEARS = 3


def build_year_arrivals(work_airings, work_first_year, work_slug_of,
                        work_display_of, composer_display_of, current_year):
    """{debut_year: [arrival entry, ...]} -- works that first aired in a
    window-valid year and then aired in >= _ARRIVAL_MIN_LATER_YEARS distinct
    LATER years (sustained, not a burst). PURE."""
    ceiling = current_year - _ARRIVAL_HINDSIGHT_YEARS
    out = {}
    for key, airings in work_airings.items():
        fy = work_first_year.get(key)
        if not fy:
            continue
        fyi = int(fy)
        if fyi < _ARRIVAL_FLOOR_YEAR or fyi > ceiling:
            continue
        years = {a[0][:4] for a in airings if a[0]}
        later = sorted(y for y in years if int(y) > fyi)
        if len(later) < _ARRIVAL_MIN_LATER_YEARS:
            continue
        post = sum(1 for a in airings if a[0] and int(a[0][:4]) > fyi)
        ck = key[0]
        out.setdefault(fy, []).append({
            "work": work_display_of.get(key, ""),
            "slug": work_slug_of.get(key),
            "composer": composer_display_of.get(ck, ck),
            "plays_total": sum(1 for a in airings if a[0]),
            "later_years": len(later), "post_airings": post})
    for y in out:
        out[y].sort(key=lambda e: (-e["later_years"], -e["post_airings"]))
        out[y] = out[y][:10]
    return out


def build_year_texture(composer_year_counts, composer_dates,
                       composer_slug_of, composer_display_of,
                       work_airings, work_first_year, work_slug_of,
                       work_display_of, current_year):
    """{year: {"anniversaries": [...], "distinctive": [...], "arrivals": [...]}}
    -- computed ONCE, consumed by both the years table (build_year_rows) and
    the index cards. PURE."""
    ann = build_year_anniversaries(composer_year_counts, composer_dates,
                                   composer_slug_of, composer_display_of)
    dist = build_year_distinctive(composer_year_counts, composer_slug_of,
                                  composer_display_of)
    arr = build_year_arrivals(work_airings, work_first_year, work_slug_of,
                              work_display_of, composer_display_of, current_year)
    years = set(ann) | set(dist) | set(arr)
    return {y: {"anniversaries": ann.get(y, []), "distinctive": dist.get(y, []),
                "arrivals": arr.get(y, [])}
            for y in years if int(y) >= _YEAR_TEXTURE_FLOOR_YEAR}


def build_year_rows(work_entries, work_airings, composer_slug_of,
                    composer_display_of, work_slug_of, composer_dates,
                    work_first_year, current_year) -> list:
    """Build years-table row tuples -- the per-year DRILL-IN pages (distinct
    from the browse 'years' payload, which is just the year list). PURE.

    For every broadcast year seen in work_airings, aggregates that year's
    airings into a top-N works ranking and a top-N composers ranking (each
    by airings that year, ties broken by slug, capped at _YEAR_TOP_N), plus
    the year's distinct-work and distinct-composer counts and its texture
    (anniversaries/distinctive/arrivals, from build_year_texture). An airing
    with no bdate is skipped (it can't be dated to a year). work_airings
    already excludes the both-key-empty junk rows (accumulate_entities), so a
    year with ONLY junk airings would not get a page here; it can't occur in a
    real corpus (every year has keyed airings) and the render crawl backstops
    any browse-Years link that somehow outran a page.

    work_entries:      build_work_index entries WITH canonical slugs overlaid
                       (source of work_display per key).
    work_airings:      {(ck, wk): [(bdate, rp_or_None, performers, ep, pos), ...]}.
    composer_slug_of:  {composer_key: composer_slug}.
    composer_display_of: {composer_key: corpus-wide best-spelling display} (SSOT).
    work_slug_of:      {(ck, wk): slug}.
    composer_dates:    {composer_key: (birth_or_None, death_or_None)}.
    work_first_year:   {(ck, wk): "YYYY"} -- from build_work_first_dates, [:4]'d.
    current_year:      int -- today's year, for the arrivals hindsight ceiling.

    Returns a list of 9-tuples in years-schema column order, year-ASCENDING:
      (year, airings, n_works, n_composers, top_works_json, top_composers_json,
       anniversaries_json, distinctive_json, arrivals_json)
    (the renderer orders the page lists; the browse index orders the years).
    """
    work_meta = {e["key"]: e["work_display"] for e in work_entries}

    counts = build_composer_year_counts(work_airings)
    texture = build_year_texture(counts, composer_dates, composer_slug_of,
                                 composer_display_of, work_airings,
                                 work_first_year, work_slug_of, work_meta,
                                 current_year)

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
            if len(top_works) >= _YEAR_TOP_N:
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
            if len(top_composers) >= _YEAR_TOP_N:
                break

        tex = texture.get(yr, {"anniversaries": [], "distinctive": [], "arrivals": []})
        rows.append((
            yr,
            year_airings[yr],
            len(wc),
            len(cc),
            json.dumps(top_works),
            json.dumps(top_composers),
            json.dumps(tex["anniversaries"]),
            json.dumps(tex["distinctive"]),
            json.dumps(tex["arrivals"]),
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
            "redirects": {"works": {}, "composers": {}},
            "retired": {"works": {}, "composers": {}}}


def _resolve_redirect_map(redirects, registered):
    """Collapse a namespace's redirect chains to single hops, retaining every
    source. PURE: no I/O, no mutation of inputs; dict insertion order is the
    input order.

    Raises ValueError on a redirect cycle, a final target that is not a
    currently registered slug, or a redirect source that is itself registered
    (sources and live registrations must be disjoint)."""
    resolved = {}
    for source in redirects:
        seen = []
        current = source
        while current in redirects:
            if current in seen:
                cycle = seen[seen.index(current):] + [current]
                raise ValueError(f"redirect cycle: {' -> '.join(cycle)}")
            seen.append(current)
            current = redirects[current]
        if current not in registered:
            raise ValueError(
                f"redirect {source!r} targets unregistered slug {current!r}")
        if source in registered:
            raise ValueError(
                f"redirect source {source!r} is also a registered slug")
        resolved[source] = current
    return resolved


def load_registry(path=REGISTRY_PATH):
    """Load the slug registry. Missing file -> a fresh empty v1 shell (first
    run). A file that exists but is corrupt JSON or the wrong shape is a HARD
    error -- unlike the derived caches (missing/corrupt -> degrade), this is a
    git-tracked, human-consequential file, so silent degradation would mean
    silently reassigning URLs. Shape check is shallow (top-level keys present
    with the right container types), not a full schema validation.

    'retired' (slugs whose identity DISSOLVED rather than moved -- see
    apply_retire) is deliberately NOT in `required`: the live registry
    predates it, and a hard error on a missing key would block every build.
    A registry without it loads with 'retired' normalised to empty maps; a
    registry that HAS it still gets the same shape check as 'redirects'."""
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
    if "retired" in data:
        retired = data["retired"]
        if (not isinstance(retired, dict)
                or not isinstance(retired.get("works"), dict)
                or not isinstance(retired.get("composers"), dict)):
            raise ValueError(f"{path}: 'retired' must be {{'works': {{}}, 'composers': {{}}}}")
    else:
        data["retired"] = {"works": {}, "composers": {}}
    for ns in ("works", "composers"):
        for slug, entry in data[ns].items():
            if "entity_id" in entry and not isinstance(entry["entity_id"], int):
                raise ValueError(
                    f"{path}: {ns}/{slug}: entity_id must be an int")
    data["redirects"]["works"] = _resolve_redirect_map(
        data["redirects"]["works"], data["works"])
    data["redirects"]["composers"] = _resolve_redirect_map(
        data["redirects"]["composers"], data["composers"])
    return data


def dump_registry(registry, path=REGISTRY_PATH):
    """Write the registry as deterministic, git-reviewable bytes (sorted
    keys, indent=2, trailing newline). Atomic PER WRITER: writes a
    pid-unique tmp then os.replace. The tmp name carries the pid because a
    FIXED name let two concurrent writers share one tmp file -- writer A
    os.replace()d a half-written B file, corrupting the tracked registry
    (2026-07-19, two overlapping --remap batch runs). Concurrent writers
    still last-write-win on the final path, but each replace is now a
    complete document."""
    tmp = f"{path}.{os.getpid()}.tmp"
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
                     today, record_key, retired_keys=()):
    """Shared engine for one namespace (works or composers).

    registered:       {slug: entry-dict} from the registry (NOT mutated)
    redirected_keys:   set of slugs that are redirect sources in this namespace
    entries:           derived entries (work_entries or composer_entries)
    identity_of(entry): the identity key (a tuple for works, a str for composers)
    slug_of(entry):     the entry's derived slug
    record_key(identity, published) -> dict to store under the winning slug
    retired_keys:      slugs retired (apply_retire) in this namespace -- a
                        retired identity is no longer in `registered` (that's
                        the point: it stops being an orphan, see below), but
                        its SLUG must never be re-minted for a different
                        identity, so it joins `taken` alongside registered/
                        redirected slugs.

    Returns (new_registered, added_count, slug_drift, collisions, orphans).
    orphans = registered slugs whose identity is absent from `entries` (for
    the caller to collect across both namespaces before raising). A retired
    slug is NOT in `registered`, so it can never appear here -- retiring a
    slug is exactly how an operator stops an unrecoverable orphan from
    blocking every future sync.
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
    taken = set(registered.keys()) | set(redirected_keys) | set(retired_keys)
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


def sync_registry(registry, work_entries, composer_entries, today,
                  entity_view=None, anchors=None):
    """Reconcile the frozen slug registry against the current corpus. PURE:
    no I/O, does not mutate `registry` -- returns a new (registry, report).

    today: 'YYYY-MM-DD' string stamped onto newly-registered entries
           (caller-supplied so the function stays deterministic/testable).

    entity_view/anchors (optional): the successor entity view
           {entity_id: (composer_key, work_key)} (each entity's dominant
           member key, ttn2_query.load_entity_view) and the tracked anchors
           {slug: {work_entity_id, legacy_ck, legacy_wk}}
           (ttn2_ledger.load_anchors). entity_id reaches an entry ONLY via
           these -- human-ratified data, never auto-anchored.

    Semantics:
      - a derived identity NOT already registered -> registered under its
        derived slug (or a '-2', '-3', ... suffix on collision), published
        = today.
      - a REGISTERED identity keeps its registered slug forever, even when
        the derived slug for that identity has since changed (informational
        report["slug_drift"], mapping unchanged).
      - a REGISTERED identity absent from the current derived entries is an
        ORPHAN. An orphan whose entry carries a resolving entity_id (or
        whose slug has a tracked anchor supplying one) is REANCHORED in
        place from the entity's dominant member key -- the frozen slug
        keeps its URL and published date (informational
        report["reanchored"]). Unanchored orphans, and orphans whose
        entity_id does not resolve in entity_view (stale), remain orphans
        and raise RegistryDriftError -- collected across BOTH namespaces,
        so one error message lists every orphan. Nothing is returned or
        written in that case. The reanchor arm is WORKS-ONLY: composer
        entries have no work_key and no composer entity table, so a composer
        orphan always drifts (entity_id or not).
      - a PRESENT registered entry whose slug has a tracked anchor whose
        entity resolves is annotated with entity_id (informational; the
        entry just predates the anchor). Malformed anchors (no usable
        work_entity_id) and entries whose entity does not resolve are
        never touched.

    report keys:
      added_works, added_composers -- counts of newly-registered identities
      slug_drift  -- list of (registered_slug, derived_slug) pairs, both
                     namespaces pooled
      collisions  -- list of (identity, base_slug, assigned_slug) tuples for
                     newly-registered identities that needed a suffix
      reanchored  -- list of (slug, old_ck, old_wk, new_ck, new_wk) for
                     entity-reanchored orphans
    """
    # .get, not [] -- a raw registry dict (pre-'retired'-key files, and many
    # tests) may not carry 'retired' at all; load_registry normalises it, but
    # sync_registry must tolerate the unnormalised shape too.
    retired = registry.get("retired", {"works": {}, "composers": {}})

    new_works, added_works, work_drift, work_collisions, work_orphans = \
        _sync_namespace(registry["works"], registry["redirects"]["works"],
                         work_entries, _work_identity,
                         lambda e: e["slug"], today,
                         lambda identity, published: {
                             "composer_key": identity[0], "work_key": identity[1],
                             "published": published},
                         retired.get("works", {}))

    new_composers, added_composers, composer_drift, composer_collisions, composer_orphans = \
        _sync_namespace(registry["composers"], registry["redirects"]["composers"],
                         composer_entries, _composer_identity,
                         lambda e: e["slug"], today,
                         lambda identity, published: {
                             "composer_key": identity, "published": published},
                         retired.get("composers", {}))

    # Entity gate (P4 phase 2): an orphaned entry with a resolving entity_id
    # -- carried on the entry, or supplied by its tracked anchor -- is
    # REANCHORED in place from the entity's dominant member key (the frozen
    # slug keeps its URL and published date; entity_id is human-ratified
    # ledger/anchor data, never auto-anchored). Unanchored orphans, and
    # orphans whose entity_id does not resolve in the view (stale), stay
    # orphans -> drift error below.
    reanchored = []
    unanchored = set()
    stale = set()
    # WORKS-ONLY: composer entries have no work_key and there is no composer
    # entity table, so a composer orphan carrying an entity_id would KeyError
    # on entry["work_key"] below. The deleted evidence pre-pass was also
    # explicitly works-only ("composers are out of scope: their drift is
    # alias-folds"); a composer orphan with an entity_id stays an orphan and
    # drifts cleanly (the unanchored/stale classification below is
    # works-namespace only).
    for new_entries, orphans in ((new_works, work_orphans),):
        for slug in sorted(orphans):
            entry = new_entries[slug]
            eid = entry.get("entity_id")
            if eid is None:
                eid = (anchors or {}).get(slug, {}).get("work_entity_id")
            if eid is None or isinstance(eid, bool) \
                    or not isinstance(eid, int):
                # bool is an int subclass (isinstance(True, int) is True):
                # a bool entity_id is stale -- no anchor fallback fires (only
                # None triggers it) and the entry drifts (counted unanchored).
                unanchored.add(slug)
                continue                  # stays an orphan -> drift error
            view = (entity_view or {}).get(eid)
            if view is None:
                stale.add(slug)
                continue                  # stale entity -> drift error
            # copy before mutating: new_entries aliases the caller's registry
            entry = dict(entry)
            new_entries[slug] = entry
            old_ck, old_wk = entry["composer_key"], entry["work_key"]
            new_ck, new_wk = view
            entry["composer_key"], entry["work_key"] = new_ck, new_wk
            entry["entity_id"] = eid
            reanchored.append((slug, old_ck, old_wk, new_ck, new_wk))
            orphans.remove(slug)

    if work_orphans or composer_orphans:
        raise RegistryDriftError(
            "registered identity missing from the current corpus -- "
            f"orphaned work slugs: {sorted(work_orphans)}; "
            f"orphaned composer slugs: {sorted(composer_orphans)} "
            f"({len(unanchored)} unanchored, {len(stale)} stale entity)")

    # Anchor annotation: a PRESENT registered entry whose slug has a tracked
    # anchor whose entity resolves gains its entity_id (informational; the
    # entry just predates the anchor). The anchor is read with .get and the
    # gate's type guard -- a malformed anchor degrades to annotated-nothing,
    # consistent with the gate. Never touch entries whose entity does not
    # resolve.
    for slug, anchor in (anchors or {}).items():
        eid = anchor.get("work_entity_id")
        if not isinstance(eid, int) or isinstance(eid, bool):
            continue
        for ns_entries in (new_works, new_composers):
            if slug in ns_entries and "entity_id" not in ns_entries[slug] \
                    and eid in (entity_view or {}):
                entry = dict(ns_entries[slug])
                entry["entity_id"] = eid
                ns_entries[slug] = entry

    new_registry = {
        "version": registry["version"],
        "works": new_works,
        "composers": new_composers,
        "redirects": {
            "works": dict(registry["redirects"]["works"]),
            "composers": dict(registry["redirects"]["composers"]),
        },
        "retired": {
            "works": dict(retired.get("works", {})),
            "composers": dict(retired.get("composers", {})),
        },
    }
    report = {
        "added_works": added_works,
        "added_composers": added_composers,
        "slug_drift": work_drift + composer_drift,
        "collisions": work_collisions + composer_collisions,
        "reanchored": reanchored,
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
    same published date), leaving redirects[namespace][old] = new and
    re-pointing any inbound redirect to `old` at `new`. Refuses
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
    new_redirects = {src: (new if tgt == old else tgt)
                     for src, tgt in redirects.items()}
    new_redirects[old] = new

    new_registry = _with_namespace(registry, namespace, new_registered, new_redirects)
    return new_registry


def apply_remap(registry, namespace, slug, composer_key, work_key=None):
    """Re-point an orphaned registered `slug` at its successor identity (the
    alias-fold recovery path: a canonicalization edit moved the group key an
    old slug pointed at). If the successor identity is ALREADY registered
    under some OTHER slug, `slug` instead becomes a redirect to that slug and
    its own registration is removed (two slugs must never both claim to be
    canonical for one identity); any inbound redirect to `slug` is re-pointed
    at that successor. Otherwise `slug`'s stored identity is updated in place
    (published date preserved). Refuses (RegistryActionError, registry
    unchanged) if `slug` isn't registered."""
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
        new_redirects = {src: (existing_slug if tgt == slug else tgt)
                         for src, tgt in redirects.items()}
        new_redirects[slug] = existing_slug
    else:
        published = registered[slug]["published"]
        if namespace == "works":
            new_registered[slug] = {"composer_key": composer_key, "work_key": work_key,
                                     "published": published}
        else:
            new_registered[slug] = {"composer_key": composer_key, "published": published}

    return _with_namespace(registry, namespace, new_registered, new_redirects)


def apply_retire(registry, namespace, slug, reason=None, today=None):
    """Retire a registered `slug` whose identity DISSOLVED rather than moved
    -- --remap can only re-point a slug at a successor identity that EXISTS,
    but some identities have no successor at all (an 'anonymous: 4 works'
    entry whose airings turned out to be four different named composers'
    works once better metadata arrived; a pre-2012 text-only work with no
    traceable heir). Moves `registry[namespace][slug]` into
    `registry['retired'][namespace][slug]`, adding a `retired` date (=
    `today`, caller-supplied for determinism, matching sync_registry's
    style) and, if given, a free-text `reason` -- the ORIGINAL stored fields
    (composer_key/work_key/published) are preserved verbatim alongside them,
    so the retired entry is the permanent record of what the slug used to
    mean, not a bare tombstone. PURE: returns a new registry, never mutates
    the input.

    Refuses (RegistryActionError, registry unchanged) if `slug` isn't
    registered, or if `slug` is a redirect TARGET in this namespace (some
    other slug redirects to it) -- retiring it would strand that redirect
    pointing at nothing live. Being a redirect SOURCE is unrelated (and, by
    construction, impossible for a currently-registered slug: apply_rename/
    apply_remap always remove a slug from `registered` before adding it as a
    source), so no such check is needed here."""
    registered = registry[namespace]
    redirects = registry["redirects"][namespace]
    if slug not in registered:
        raise RegistryActionError(f"{namespace}: {slug!r} is not registered")
    redirect_sources = sorted(s for s, target in redirects.items() if target == slug)
    if redirect_sources:
        raise RegistryActionError(
            f"{namespace}: {slug!r} is a redirect target (from "
            f"{redirect_sources!r}) -- retiring it would strand those redirects")

    new_registered = dict(registered)
    entry = dict(new_registered.pop(slug))
    entry["retired"] = today
    if reason is not None:
        entry["reason"] = reason

    existing_retired = registry.get("retired", {"works": {}, "composers": {}})
    other = "composers" if namespace == "works" else "works"
    new_retired_ns = dict(existing_retired.get(namespace, {}))
    new_retired_ns[slug] = entry
    new_retired = {
        namespace: new_retired_ns,
        other: dict(existing_retired.get(other, {})),
    }

    return _with_namespace(registry, namespace, new_registered, dict(redirects),
                            retired=new_retired)


def apply_anchor(registry, namespace, slug, entity_id, composer_key, work_key=None):
    """Stamp a registered `slug` with its ratified successor identity:
    `entity_id` (the ledger's work_entity id) plus the entity's derived
    (composer_key, work_key) strings. The ratification write-path for the
    P4 phase-2 drift batch -- the human-approved counterpart of
    sync_registry's auto reanchor pass, which only fires on orphans whose
    anchor chain already carries the id. `published` and every other stored
    field are preserved. PURE: returns a new registry, never mutates the
    input.

    Existing-identity guard (mirrors apply_remap exactly): if the target
    identity is ALREADY registered under some OTHER slug, `slug` instead
    becomes a redirect to that slug and its own registration is removed
    (two slugs must never both claim to be canonical for one identity --
    the batch-1 duplicate lesson: an anchor onto a held identity used to
    stamp a second registration); any inbound redirect to `slug` is
    re-pointed at that holder. `entity_id` is dropped with the entry --
    a redirect has no identity of its own.

    Refuses (RegistryActionError, registry unchanged) if `slug` isn't
    registered, if `namespace` is neither 'works' nor 'composers', or if
    `entity_id` isn't a usable int -- load_registry hard-errors on a
    non-int entity_id, so writing one here would corrupt the tracked file
    into unloadable state (a bool is an int subclass: the sync gate's
    staleness rule applies here too). The composers namespace has no
    work_key; `work_key` is ignored there."""
    if namespace not in ("works", "composers"):
        raise RegistryActionError(f"unknown namespace {namespace!r}")
    registered = registry[namespace]
    redirects = registry["redirects"][namespace]
    if slug not in registered:
        raise RegistryActionError(f"{namespace}: {slug!r} is not registered")
    if isinstance(entity_id, bool) or not isinstance(entity_id, int):
        raise RegistryActionError(
            f"{namespace}: {slug!r}: entity_id must be an int, got {entity_id!r}")

    target_identity = (composer_key, work_key) if namespace == "works" else composer_key
    existing_slug = None
    for s, stored in registered.items():
        if s == slug:
            continue
        if _namespace_identity(namespace, stored) == target_identity:
            existing_slug = s
            break

    new_registered = dict(registered)
    if existing_slug is not None:
        del new_registered[slug]
        new_redirects = {src: (existing_slug if tgt == slug else tgt)
                         for src, tgt in redirects.items()}
        new_redirects[slug] = existing_slug
        return _with_namespace(registry, namespace, new_registered, new_redirects)

    new_redirects = dict(redirects)
    entry = dict(new_registered[slug])
    # composer entity_id is UNDEFINED (no composer entity table) -- phase-3 queue owns defining or prohibiting
    entry["entity_id"] = entity_id
    entry["composer_key"] = composer_key
    if namespace == "works":
        entry["work_key"] = work_key
    new_registered[slug] = entry

    return _with_namespace(registry, namespace, new_registered, new_redirects)


def _with_namespace(registry, namespace, registered, redirects, retired=None):
    """New registry dict with `namespace`'s registered map and redirect map
    replaced; the other namespace and 'version' pass through unchanged.

    retired: when given, replaces registry['retired'] wholesale (both
    namespaces -- apply_retire uses this to add one retirement while copying
    the other namespace's retired map through unchanged). When omitted
    (apply_rename/apply_remap, which never touch retirements), the existing
    'retired' map passes through untouched -- and .get, not [], because a raw
    registry dict predating the 'retired' key has no such key to index."""
    other = "composers" if namespace == "works" else "works"
    if retired is None:
        existing = registry.get("retired", {"works": {}, "composers": {}})
        retired = {"works": dict(existing.get("works", {})),
                   "composers": dict(existing.get("composers", {}))}
    return {
        "version": registry["version"],
        namespace: registered,
        other: dict(registry[other]),
        "redirects": {
            namespace: redirects,
            other: dict(registry["redirects"][other]),
        },
        "retired": retired,
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
    dump_registry contract, incl. the pid-unique tmp -- concurrent writers
    must never share a tmp file)."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


# Two decoupled airings cuts. The PAGE cut mints an /artist/ page; it is set
# lower than the LISTING cut so a recurring (20-49 airing) contributor -- of
# which there are ~1,400, more than the whole >=50 set -- becomes a link on the
# work/composer/performance pages instead of a dead plain-text name, WITHOUT
# flooding the conductors/performers/singers rankings with a long low-airing
# tail (those stay a tight "who appears most" at 50). Both apply at MINT time
# only: an already-registered artist later dropping below the page cut keeps its
# page (mint once, keep forever), so lowering the page cut only ever ADDS pages.
_ARTIST_PAGE_CUT = 20
_ARTIST_LISTING_CUT = 50

# The artist page's LEAD block. 96% of artists have <=20 recordings, so this
# is the complete performance list for almost every page rather than a top-N.
_ARTIST_PERFORMANCES_TOP_N = 20

# Role groupings for artist qualification/facets. One MBID can hold several
# roles; the people-set and group-set are ranked separately (each role set
# dedupes identity-per-rp inside rank_contributors) and 'person' wins a
# dual-qualified MBID.
_ARTIST_PEOPLE_ROLES = frozenset(("Conductor", "Performer", "Singer"))
_ARTIST_GROUP_ROLES = frozenset(("Ensemble", "Orchestra", "Choir"))


def artist_qualifiers(recs, cons):
    """The gate: [(mbid, display)] for every MBID-backed identity at/above
    _ARTIST_PAGE_CUT combined-role airings, in DETERMINISTIC mint order
    (airings-DESC, then mbid) -- feeds sync_artist_registry. A name-keyed
    identity never qualifies (the MBID-only gate: no stable anchor, no URL).
    An MBID qualifying on both the people and group sets appears once
    (people stat wins -- the soloist-director case)."""
    people = ttn_spine.rank_contributors(recs, cons, _ARTIST_PEOPLE_ROLES)
    groups = ttn_spine.rank_contributors(recs, cons, _ARTIST_GROUP_ROLES)
    best = {}
    for stats in (people, groups):          # people first: wins dual-qualified
        for s in stats:
            if s.mbid and s.airings >= _ARTIST_PAGE_CUT and s.mbid not in best:
                best[s.mbid] = s
    ordered = sorted(best.values(), key=lambda s: (-s.airings, s.mbid))
    return [(s.mbid, s.display_name) for s in ordered]


def _pick_display(votes):
    """The shown spelling for a multi-spelling contributor identity: the
    corpus-majority spelling by airings, EXCEPT a lowercase-initial majority
    loses to any properly-capitalized variant (the 'moni Fischaleck' feed
    slip). Ties break alphabetically, so the pick is deterministic -- the
    old first-seen-over-an-unordered-set rule let pages flip between builds."""
    caps = {d: n for d, n in votes.items() if d[:1].isupper()}
    pool = caps or votes
    return min(pool, key=lambda d: (-pool[d], d))


def build_artist_rows(registry, recs, cons, brc_rows_by_rp, rec_rows,
                      work_entries, composer_display_of,
                      rp_stats=None) -> list:
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
    rp_stats:          optional {rp: (count, first, last)} bridged whole-
                       corpus stats derived from the recordings table. When
                       given, the facts first/last and each performances
                       entry's airings/first/last come from it instead of the
                       spine's 2012+-only values -- so the artist page agrees
                       with the performance page (the p01pnwwj class). The
                       top-composers / collaborators facet WEIGHTS are
                       bridged too. The headline stat.airings rank cut is
                       spine-scoped by design (changing it would move the
                       page cut).

    Returns 10-tuples in artists-schema column order, airings-DESC (tie slug):
      (slug, mbid, display, kind, roles_json, airings, n_recordings,
       first_aired, last_aired, facets_json)

    display is the CURRENT corpus display (rank stat), never display_at_mint
    -- the shown name evolves with the corpus, the URL does not. kind =
    'person' when the MBID ranks on the people role-set (wins dual), else
    'ensemble'. facets_json: top_composers / collaborators
    {conductors, soloists, ensembles} (self excluded; each entry carries the
    collaborator's artist slug when registered, else null) / by_year (from
    rec_rows' airing dates -- bridged via the recordings table) /
    broadcasters /
    performances (the page's LEAD block, top 20 by airings, closure-safe via
    rec_rows)."""
    people_by_mbid = {s.mbid: s for s in ttn_spine.rank_contributors(
        recs, cons, _ARTIST_PEOPLE_ROLES) if s.mbid}
    group_by_mbid = {s.mbid: s for s in ttn_spine.rank_contributors(
        recs, cons, _ARTIST_GROUP_ROLES) if s.mbid}

    slug_by_mbid = {v["mbid"]: slug for slug, v in registry["artists"].items()}

    rec_meta = {r[0]: (r[1], r[2]) for r in rec_rows}   # rp -> (work_slug, composer_slug)
    dates_by_rp = {r[0]: [entry[0] for entry in json.loads(r[9] or "[]")]
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

    def _stat(rp):
        """(airings, first, last) from the bridged recordings-table stats
        when available, else the spine's 2012+-only values (legacy callers)."""
        if rp_stats and rp in rp_stats:
            return rp_stats[rp]
        r = recs[rp]
        return r.airing_count, r.first_aired, r.last_aired

    rows = []
    for slug, entry in registry["artists"].items():
        mbid = entry["mbid"]
        rps = rps_of_mbid.get(mbid, set())
        if not rps:
            continue                        # vanished from the corpus entirely

        # An MBID present in BOTH role-sets is the upstream per-airing role
        # mis-tag (e.g. an orchestra carrying a stray "Performer" credit on a
        # handful of airings). Pick the role-set the identity predominates in,
        # rather than always preferring people -- otherwise a 1-airing mis-tag
        # hijacks the headline count, name and kind from the real ~1,900-airing
        # ensemble. Single-role-set MBIDs (the vast majority) are unchanged.
        p_stat = people_by_mbid.get(mbid)
        g_stat = group_by_mbid.get(mbid)
        if p_stat and g_stat:
            stat = p_stat if p_stat.airings >= g_stat.airings else g_stat
        else:
            stat = p_stat or g_stat
        kind = "person" if stat is not None and stat is p_stat else "ensemble"

        _pairs = [_stat(rp) for rp in rps]
        _firsts = [f for _n, f, _l in _pairs if f]
        _lasts = [l for _n, _f, l in _pairs if l]
        first = min(_firsts) if _firsts else None
        last = max(_lasts) if _lasts else None
        n_of_rp = dict(zip(rps, (p[0] for p in _pairs)))

        # top composers, weighted by each recording's airing count. (No top
        # works: see the performances facet -- on an artist page a work row is
        # a performance row 98.7% of the time, so the works block was pure
        # duplication and the page leads with performances instead.)
        composer_counts: dict = {}          # composer_slug -> [airings, display]
        for rp in rps:
            ws, cslug = rec_meta.get(rp, (None, None))
            if ws not in disp_of:
                continue
            n = n_of_rp[rp]
            if cslug:
                cc = composer_counts.setdefault(cslug, [0, disp_of[ws][1]])
                cc[0] += n
        top_composers = [
            {"slug": cslug, "display": disp, "airings": n}
            for cslug, (n, disp) in sorted(
                composer_counts.items(),
                key=lambda kv: (-kv[1][0], kv[0]))[:10]
        ]

        # collaborators: other contributors on the same recordings, bucketed
        # by role group, identity-deduped per rp, self excluded; linked when
        # the collaborator is themselves a registered artist. Each identity
        # tallies its spellings' airings and _pick_display chooses the shown
        # one deterministically (majority, capitalization-guarded) -- the old
        # first-seen rule varied with set iteration order between builds.
        buckets = {"conductors": {}, "soloists": {}, "ensembles": {}}
        for rp in rps:
            n = n_of_rp[rp]
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
                    c.identity_key, [{}, slug_by_mbid.get(c.mbid)])
                b[0][c.display_name] = b[0].get(c.display_name, 0) + n

        def _collab_rows(bucket):
            entries = [(sum(votes.values()), _pick_display(votes), cslug)
                       for votes, cslug in bucket.values()]
            entries.sort(key=lambda e: (-e[0], e[1]))
            return [{"display": disp, "airings": n, "slug": cslug}
                    for n, disp, cslug in entries[:10]]

        collaborators = {
            name: _collab_rows(bucket) for name, bucket in buckets.items()
        }

        # by-year over the recordings' airing dates (bridged via rec_rows)
        year_counts = tally_years(d for rp in rps for d in dates_by_rp.get(rp, []))
        by_year = [{"year": y, "airings": n}
                   for y, n in sorted(year_counts.items(), reverse=True)]

        b_rows = [(lab, rp) for rp in rps for lab in brc_rows_by_rp.get(rp, [])]
        broadcasters = [
            _broadcaster_stat_dict(s)
            for s in ttn_broadcasters.rank_broadcasters(
                b_rows, rank_key=ttn_broadcasters.broadcaster_key)
        ]

        performances = []
        for rp in sorted(rps, key=lambda rp: (-_stat(rp)[0], rp)):
            if len(performances) == _ARTIST_PERFORMANCES_TOP_N:
                break
            ws, _cslug = rec_meta.get(rp, (None, None))
            if ws not in disp_of:
                continue
            n, f, l = _stat(rp)
            performances.append({
                "recording_pid": rp,
                "work_slug": ws,
                "work_display": disp_of[ws][0],
                "composer_display": disp_of[ws][1],
                "duration": _sane_duration(recs[rp].duration_seconds),
                "airings": n,
                "first": f,
                "last": l,
            })

        facets = {
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
                         bbc_url TEXT, tracks_json TEXT,
                         rebroadcast_dates_json TEXT NOT NULL DEFAULT '[]',
                         opening_concert_json TEXT,
                         national_day_json TEXT);
CREATE TABLE recordings (recording_pid TEXT PRIMARY KEY, work_slug TEXT,
                         composer_slug TEXT, duration INTEGER,
                         broadcaster TEXT, airings INTEGER,
                         first_aired TEXT, last_aired TEXT,
                         contributors_json TEXT, airing_dates_json TEXT);
CREATE TABLE browse     (name TEXT PRIMARY KEY, payload_json TEXT);
CREATE TABLE years      (year TEXT PRIMARY KEY, airings INTEGER,
                         n_works INTEGER, n_composers INTEGER,
                         top_works_json TEXT, top_composers_json TEXT,
                         anniversaries_json TEXT, distinctive_json TEXT,
                         arrivals_json TEXT);
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
CREATE TABLE countries  (slug TEXT PRIMARY KEY, country TEXT, airings INTEGER,
                         n_recordings INTEGER, n_broadcasters INTEGER,
                         broadcasters_json TEXT, top_works_json TEXT,
                         top_performances_json TEXT, top_ensembles_json TEXT,
                         national_days_json TEXT);
"""

# The content tables write_site_db accepts rows for (meta is stamped by
# write_site_db itself). Per-table arity is derived from the created schema
# via PRAGMA table_info, never hand-counted -- a hand-maintained count map
# drifted from the CREATE TABLE text once (works: 12 vs 13, task-4 review).
_SITE_TABLES = ("works", "composers", "episodes", "recordings", "browse",
                "years", "broadcasters", "forms", "artists", "countries")


def site_fingerprint(registry_path, artist_reg_path=None):
    """sha1 hex over, in order: this module's bytes, ttn_analyze.py,
    ttn_aliases.py, ttn_ebu_codes.py, ttn_broadcasters.py, the projection
    cache file, the registry file at `registry_path`, and the artist registry
    (default: beside this module) -- an artist mint must invalidate a stale
    site.sqlite, as must a broadcaster-table-shaping edit (ebu_codes /
    broadcasters, neither of which is in the projection cache's fingerprint).
    A missing file hashes as the empty string for that slot (tolerant, like
    _slug_cache_fingerprint) -- site_fingerprint itself never raises; only a
    hard build-time consumer (_run_build) treats a missing
    projection/registry as an error, and it does so explicitly, not via this
    function silently failing."""
    if artist_reg_path is None:
        artist_reg_path = artist_registry_path()
    h = hashlib.sha1()
    for path in (os.path.abspath(__file__), _ANALYZE_MODULE_PATH,
                 _ALIASES_MODULE_PATH, _EBU_CODES_MODULE_PATH,
                 _BROADCASTERS_MODULE_PATH, ttn_project.PROJECTION_PATH,
                 registry_path, artist_reg_path):
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"")
    return h.hexdigest()


def site_fingerprint_t2(registry_path, artist_reg_path=None,
                        db_path="ttn.sqlite"):
    """Successor-source fingerprint: the successor DB + ledger export + the
    ttn2 modules' bytes replace the projection-cache slot, and the SHARED
    legacy modules the successor build executes are hashed too (same slot
    list as site_fingerprint minus the projection cache: ttn_site itself,
    ttn_analyze, ttn_aliases, ttn_project, ttn_segment_meta, ttn_spine,
    ttn_ebu_codes, ttn_broadcasters) -- an edit to any shared module must
    stale site2.sqlite, never fresh-skip it (sha256 -- a new file, no sha1-
    compat constraint). The successor.sqlite / ttn2_ledger.json slots are
    CWD-RELATIVE, exactly as the successor stack's own defaults (ttn2_site.DB)
    are. db_path (the legacy corpus DB -- the successor build reads raw8/
    rec_meta from it) is hashed too, so a corpus change without a successor
    re-ingest cannot fresh-skip a stale site2.sqlite. Hashing style mirrors
    site_fingerprint: in-order byte streams, and a missing file hashes as the
    empty string for that slot (tolerant -- this function never raises)."""
    import ttn2_ingest, ttn2_ledger, ttn2_match, ttn2_site
    paths = [ttn2_ingest.__file__, ttn2_match.__file__, ttn2_ledger.__file__,
             ttn2_site.__file__, "successor.sqlite", db_path,
             "ttn2_ledger.json", registry_path,
             # shared legacy modules the successor build executes (site-
             # fingerprint slot list minus the projection-cache slot)
             os.path.abspath(__file__), _ANALYZE_MODULE_PATH,
             _ALIASES_MODULE_PATH, ttn_project.__file__,
             ttn_segment_meta.__file__, ttn_spine.__file__,
             _EBU_CODES_MODULE_PATH, _BROADCASTERS_MODULE_PATH]
    if artist_reg_path:
        paths.append(artist_reg_path)
    h = hashlib.sha256()
    for path in paths:
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
      - broadcasters: top_works_json[].slug in works and its
        recording_pids[] in recordings; top_performances_json[]
        work_slug/composer_slug/recording_pid in works/composers/recordings
      - browse 'forms': slug in forms
      - browse 'christmas': top_works[].slug/composer_slug in works/composers
      - browse 'national_days': recurring/also_marked[].country_slug in
        countries; their airings[].url_date in episodes.date
      - browse 'ensembles'/'conductors'/'performers'/'singers': a non-null
        rows[].slug in artists
      - forms: top_works_json[].slug/composer_slug in works/composers
      - countries: broadcasters_json[].slug in broadcasters;
        top_works_json[].slug/composer_slug in works/composers and its
        recording_pids[] in recordings; top_performances_json[]
        work_slug/composer_slug/recording_pid in works/composers/recordings
      - artists: facets top_composers[].slug in composers;
        performances[].recording_pid/work_slug in recordings/works;
        collaborators[*][].slug (non-null) in artists

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
    country_slugs = {row[0] for row in conn.execute("SELECT slug FROM countries")}
    episode_dates = {row[0] for row in conn.execute("SELECT date FROM episodes")}

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

    # episodes.national_day_json.country_slug -> countries (the 'An episode
    # celebrating {country}' chip link). Reuses the national_days cards, so
    # already covered, but validated as the standing net.
    for pid, ndj in conn.execute("SELECT pid, national_day_json FROM episodes"):
        if ndj:
            nd = json.loads(ndj)
            _check(nd.get("country_slug"), country_slugs, "countries",
                   "episodes", pid, "national_day_json.country_slug")

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
                _check(h.get("broadcaster_slug"), broadcaster_slugs, "broadcasters",
                       "browse", name, f"house_performances[{i}].broadcaster_slug")
        elif name == "broadcasters":
            for i, b in enumerate(payload):
                _check(b.get("slug"), broadcaster_slugs, "broadcasters",
                       "browse", name, f"broadcasters[{i}].slug")
        elif name == "forms":
            for i, f in enumerate(payload):
                _check(f.get("slug"), form_slugs, "forms",
                       "browse", name, f"forms[{i}].slug")
        elif name in ("ensembles", "conductors", "performers", "singers"):
            for i, row in enumerate(payload.get("rows", [])):
                _check(row.get("slug"), artist_slugs, "artists",
                       "browse", name, f"{name}.rows[{i}].slug")
        elif name == "countries":
            for i, c in enumerate(payload):
                _check(c.get("slug"), country_slugs, "countries",
                       "browse", name, f"countries[{i}].slug")
        elif name == "christmas":
            for i, w in enumerate(payload.get("top_works", [])):
                _check(w.get("slug"), work_slugs, "works",
                       "browse", name, f"christmas.top_works[{i}].slug")
                _check(w.get("composer_slug"), composer_slugs, "composers",
                       "browse", name, f"christmas.top_works[{i}].composer_slug")
        elif name == "national_days":
            for group in ("recurring", "also_marked"):
                for i, card in enumerate(payload.get(group, [])):
                    _check(card.get("country_slug"), country_slugs, "countries",
                           "browse", name, f"national_days.{group}[{i}].country_slug")
                    for j, a in enumerate(card.get("airings", [])):
                        _check(a.get("url_date"), episode_dates, "episodes",
                               "browse", name,
                               f"national_days.{group}[{i}].airings[{j}].url_date")

    # years: per-year page top_works + top_composers + anniversaries +
    # distinctive + arrivals link out
    for year, tw_json, tc_json, an_json, di_json, ar_json in conn.execute(
            "SELECT year, top_works_json, top_composers_json, "
            "anniversaries_json, distinctive_json, arrivals_json FROM years"):
        for i, w in enumerate(json.loads(tw_json) if tw_json else []):
            _check(w.get("slug"), work_slugs, "works",
                   "years", year, f"top_works[{i}].slug")
            _check(w.get("composer_slug"), composer_slugs, "composers",
                   "years", year, f"top_works[{i}].composer_slug")
        for i, c in enumerate(json.loads(tc_json) if tc_json else []):
            _check(c.get("slug"), composer_slugs, "composers",
                   "years", year, f"top_composers[{i}].slug")
        for i, a in enumerate(json.loads(an_json) if an_json else []):
            _check(a.get("slug"), composer_slugs, "composers",
                   "years", year, f"anniversaries[{i}].slug")
        for i, d in enumerate(json.loads(di_json) if di_json else []):
            _check(d.get("slug"), composer_slugs, "composers",
                   "years", year, f"distinctive[{i}].slug")
        for i, a in enumerate(json.loads(ar_json) if ar_json else []):
            _check(a.get("slug"), work_slugs, "works",
                   "years", year, f"arrivals[{i}].slug")

    # broadcasters: each drill-in page's top_works + top_performances link out
    for slug, tw_json, tp_json in conn.execute(
            "SELECT slug, top_works_json, top_performances_json FROM broadcasters"):
        for i, w in enumerate(json.loads(tw_json) if tw_json else []):
            _check(w.get("slug"), work_slugs, "works",
                   "broadcasters", slug, f"top_works[{i}].slug")
            for j, rp in enumerate(w.get("recording_pids", [])):
                _check(rp, recording_pids, "recordings", "broadcasters", slug,
                       f"top_works[{i}].recording_pids[{j}]")
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

    # countries: hub broadcaster slugs + national-profile work/performance links
    for slug, brc_json, tw_json, tp_json, nd_json in conn.execute(
            "SELECT slug, broadcasters_json, top_works_json, "
            "top_performances_json, national_days_json FROM countries"):
        nd = json.loads(nd_json) if nd_json else {}
        for group in ("recurring", "also_marked"):
            for i, card in enumerate(nd.get(group, [])):
                for j, a in enumerate(card.get("airings", [])):
                    _check(a.get("url_date"), episode_dates, "episodes",
                           "countries", slug,
                           f"national_days.{group}[{i}].airings[{j}].url_date")
        for i, b in enumerate(json.loads(brc_json) if brc_json else []):
            _check(b.get("slug"), broadcaster_slugs, "broadcasters",
                   "countries", slug, f"broadcasters[{i}].slug")
        for i, w in enumerate(json.loads(tw_json) if tw_json else []):
            _check(w.get("slug"), work_slugs, "works",
                   "countries", slug, f"top_works[{i}].slug")
            _check(w.get("composer_slug"), composer_slugs, "composers",
                   "countries", slug, f"top_works[{i}].composer_slug")
            for j, rp in enumerate(w.get("recording_pids", [])):
                _check(rp, recording_pids, "recordings", "countries", slug,
                       f"top_works[{i}].recording_pids[{j}]")
        for i, p in enumerate(json.loads(tp_json) if tp_json else []):
            _check(p.get("work_slug"), work_slugs, "works",
                   "countries", slug, f"top_performances[{i}].work_slug")
            _check(p.get("composer_slug"), composer_slugs, "composers",
                   "countries", slug, f"top_performances[{i}].composer_slug")
            _check(p.get("recording_pid"), recording_pids, "recordings",
                   "countries", slug, f"top_performances[{i}].recording_pid")

    # artists: each page's facet links out (incl. artist->artist collaborator
    # links, checked against the artists table itself)
    for slug, facets_json in conn.execute(
            "SELECT slug, facets_json FROM artists"):
        facets = json.loads(facets_json) if facets_json else {}
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

# One row per segments-having episode: its position-ordered recording_pid
# playlist as a single fingerprint string. Grouping by the fingerprint finds
# exact rebroadcasts (compute_rebroadcasts).
_REBROADCAST_SQL = (
    "SELECT se.episode_pid, substr(e.broadcast_date, 1, 10), "
    "GROUP_CONCAT(se.recording_pid, '|' ORDER BY se.position) "
    "FROM segment_events se JOIN episodes e ON se.episode_pid = e.pid "
    "GROUP BY se.episode_pid")

# One row per recording: its role-typed credits + EBU source label, the raw
# material of opening-concert corroboration (build_recording_concert_meta).
# A recording's credits are USUALLY identical across airings, so DISTINCT
# collapses them -- but ~115 recordings carry varying contributions_json, so
# without a stable ORDER the dict's last-wins pick would be build-order-
# dependent and could flip opening_concert_json between builds (spurious page
# rewrites against the byte-identical-render invariant). ORDER BY makes the
# survivor deterministic.
_OPENING_CONCERT_SQL = (
    "SELECT recording_pid, contributions_json, record_label, "
    "MAX(duration_seconds) "
    "FROM segment_events "
    "GROUP BY recording_pid, contributions_json, record_label "
    "ORDER BY recording_pid, contributions_json, record_label")


def _die_needs_warm(reason):
    print(f"ttn_site: {reason} -- run `uv run ttn_data.py warm` first, "
          f"then re-run `uv run ttn_data.py site`.", file=sys.stderr)
    raise SystemExit(1)


def _derive_registry_entries(db_path):
    """Return (work_entries, composer_entries, raw8, rows5, projection,
    rec_meta) from the current corpus, with the canonical slug-map overlay
    applied to the work entries -- the exact input `_run_build` feeds
    `sync_registry`, `accumulate_entities` and the browse builders.
    Raises ValueError (with a warm/status hint) on a stale/missing
    projection or slug-map cache, so a read-only caller can report it
    without touching the registry or site.sqlite."""
    conn = sqlite3.connect(db_path)
    try:
        projection, rec_meta, status = ttn_project.load(conn)
        if status != "ok":
            raise ValueError(f"projection cache status is {status!r} -- "
                             "run `uv run ttn_data.py warm` first")

        slug_map = load_slug_map(ttn_project.PROJECTION_PATH)
        if slug_map is None:
            raise ValueError("the work-slug cache is missing or stale -- "
                             "run `uv run ttn_data.py warm` first")

        cursor = conn.execute(_WHOLE_CORPUS_SQL)
        raw8 = list(cursor)
        rows5 = list(_project_rows((r[:7] for r in raw8), projection, rec_meta))
    finally:
        conn.close()

    work_entries = build_work_index(rows5)
    for e in work_entries:
        e["slug"] = slug_map.get(e["key"], e["slug"])
    composer_entries = build_composer_index(rows5)
    return (work_entries, composer_entries, raw8, rows5, projection, rec_meta)


def _run_check(db_path, registry_out_path):
    """Read-only registry drift check: derive the current entries, run
    `sync_registry` in memory, and report. Exits non-zero on orphans WITHOUT
    writing the registry or site.sqlite -- the fast local/CI gate that the
    full build currently only reaches after a warm + corpus pass. The
    successor entity view + tracked anchors are consulted (would-be
    reanchors are reported) but never written."""
    try:
        (work_entries, composer_entries, _raw8, _rows5, _projection,
         _rec_meta) = _derive_registry_entries(db_path)
    except ValueError as e:
        print(f"ttn_site: {e}", file=sys.stderr)
        raise SystemExit(1)

    registry = load_registry(registry_out_path)
    import ttn2_ledger
    import ttn2_query
    try:
        new_registry, report = sync_registry(
            registry, work_entries, composer_entries,
            today=dt.date.today().isoformat(),
            entity_view=ttn2_query.load_entity_view(),
            anchors=ttn2_ledger.load_anchors())
    except RegistryDriftError as e:
        print(f"ttn_site: {e}", file=sys.stderr)
        print("fix: `uv run ttn_data.py site --remap \"SLUG|COMPOSER_KEY[|WORK_KEY]\"` "
              "(add --composer for the composers namespace)", file=sys.stderr)
        raise SystemExit(1)

    print(f"ttn_site: registry check OK -- {registry_out_path}")
    print(f"  registered works:     {len(new_registry['works'])} "
          f"(+{report['added_works']} would be new)")
    print(f"  registered composers: {len(new_registry['composers'])} "
          f"(+{report['added_composers']} would be new)")
    print(f"  slug drift (informational, mapping unchanged): {len(report['slug_drift'])}")
    print(f"  collisions (suffixed on assignment):            {len(report['collisions'])}")
    for slug, old_ck, old_wk, new_ck, new_wk in report["reanchored"]:
        print(f"  would reanchor: {slug}  "
              f"{old_ck}|{old_wk} -> {new_ck}|{new_wk}")
    return 0


def _gate_successor_mints(work_entries, composer_entries, registry, db_path):
    """The mint-time defense (P4 phase 3, task 2): filter the successor-side
    derived entries' NEW identities (absent from the registry) through the
    corroboration gate (ttn2_query.mint_gate_candidate: MBID-present OR
    dual-lineage-agrees). Gated identities are REMOVED from the entries --
    they can never reach sync_registry (the gate rides the CALLER;
    sync_registry itself is untouched, so the legacy path keeps mint-all
    semantics) -- and returned as [(ck, wk, slug)] for the review queue.
    wk=None marks a composer identity. The ghost-key poison class (a phantom
    identity deriving in one lineage only) defers here instead of freezing
    into the tracked registry."""
    import ttn2_query
    reg_works = {(v["composer_key"], v["work_key"])
                 for v in registry["works"].values()}
    reg_composers = {v["composer_key"] for v in registry["composers"].values()}
    deferred = []
    kept = []
    for e in work_entries:
        ck, wk = e["key"]
        if (ck, wk) in reg_works or ttn2_query.mint_gate_candidate(
                db_path, ttn2_query.DB, ck, wk):
            kept.append(e)
        else:
            deferred.append((ck, wk, e["slug"]))
    work_entries[:] = kept
    kept = []
    for ce in composer_entries:
        ck = ce["composer_key"]
        if ck in reg_composers or ttn2_query.mint_gate_candidate(
                db_path, ttn2_query.DB, ck, None):
            kept.append(ce)
        else:
            deferred.append((ck, None, ce["slug"]))
    composer_entries[:] = kept
    return deferred


def _run_build(db_path, registry_out_path, site_db_out_path, force=False,
               artist_registry_out_path=None, source="legacy"):
    """The default action: sync the registry against the current corpus, then
    build/refresh site.sqlite. Explicit consumer of the projection (SP4a
    rule) -- `ttn_project.load`, never `ensure`: a stale/missing projection is
    a hard error naming `uv run ttn_data.py warm`, not a silent ~5-minute
    rebuild kicked off from a site build. Same for a missing/stale slug-map
    cache.

    source: "legacy" (default) derives identity from the projection + alias
    chain and syncs the registry as always. "successor"
    derives identity from the ttn2 events ledger (ttn2_site.derive_site_inputs)
    instead, writes NO tracked file -- the registry and artist registry are
    read-only inputs -- and fingerprints
    against site_fingerprint_t2. Everything from the spine build down is
    shared code reading only the acc dict + entry lists.

    site.sqlite step: the fingerprint is computed AFTER the registry dump, so
    it covers the just-written registry bytes (a registry sync that added
    slugs must invalidate a stale site.sqlite). A 'fresh' status (and no
    --force) short-circuits without touching the file (the heavy corpus-pass +
    spine build below never runs on a fresh skip); otherwise the five content
    tables are built and write_site_db rebuilds the file."""
    if artist_registry_out_path is None:
        artist_registry_out_path = artist_registry_path()

    if source == "successor":
        import ttn2_site
        registry = load_registry(registry_out_path)
        # Fingerprint + fresh-skip BEFORE the heavy work (spine build +
        # whole-corpus pass): the t2 fingerprint is file-based and successor
        # mode writes no tracked file, so nothing upstream is needed.
        fp = site_fingerprint_t2(registry_out_path, artist_registry_out_path,
                                 db_path=db_path)
        if not force and site_status(site_db_out_path, fp) == "fresh":
            print(f"ttn_site: {site_db_out_path} fresh -- skipping")
            return 0
        # Spine FIRST (legacy builds it below, after accumulate). The
        # successor's presentation map must be spine-filtered BEFORE
        # accumulate: build_work_rows' n_recordings/n_text_only counters read
        # work_airings directly, before any downstream spine gating, so an
        # unfiltered map leaks non-spine rps into those counts (+1 rec / -1
        # text on the affected rows) while the facets stay byte-identical.
        # Legacy gets the same invariant by construction via the filter below.
        conn = sqlite3.connect(db_path)
        try:
            ctx = ttn_spine.build_context(conn)
            recs = ttn_spine.build_recordings(conn, ctx=ctx)
            cons = ttn_spine.build_contributors(conn, ctx=ctx)
        finally:
            conn.close()
        (work_entries, composer_entries, raw8, acc, counters,
         text_rp, presentation_map, _pids) = \
             ttn2_site.derive_site_inputs(db_path, registry, spine_rps=set(recs))
        # Mint-time defense (P4 phase 3, task 2): NEW identities (absent
        # from the registry) pass through the corroboration gate before they
        # could ever reach sync_registry; gated ones are pulled from the
        # derived entries and reported (the review queue). sync_registry
        # itself is untouched -- the gate rides the caller.
        mint_deferred = _gate_successor_mints(
            work_entries, composer_entries, registry, db_path)
        if mint_deferred:
            print(f"ttn_site: mint gate deferred {len(mint_deferred)} "
                  f"uncorroborated new identity(ies) to the review queue "
                  f"(no slug minted):")
            for ck, wk, slug in mint_deferred:
                print(f"  {slug}  {ck}|{wk}")
        rows5 = counters["rows5"]   # browse passes year_breakdown; rows5 unused
        projection = text_rp        # the High-tier link set plays the legacy
                                    # projection's role (opening-concert gates)
        rec_meta = None             # consumed inside derive_site_inputs; no
                                    # downstream reader in this function
        presentation = presentation_map   # already spine-filtered (above)
    else:
        try:
            (work_entries, composer_entries, raw8, rows5, projection,
             rec_meta) = _derive_registry_entries(db_path)
        except ValueError as e:
            _die_needs_warm(str(e).replace(" -- run `uv run ttn_data.py warm` first", ""))

        # The presentation map (graduated-trust MEDIUM tier) is needed by the
        # page-aggregate builders, but only AFTER the registry sync has cleared.
        presentation = ttn_project.load_presentation(ttn_project.PROJECTION_PATH)

    if source == "successor":
        print("ttn_site: registry: read-only (successor source)")
        # fp already computed (and fresh-skipped on) in the successor branch
        # above -- successor mode writes nothing, so it cannot go stale here.
        # The t2 entries already carry the registry-wins slug (mints dodge
        # registry slugs), so the ENTRIES are the slug maps here -- overlaying
        # from the read-only registry would drop the minted unregistered
        # identities and break every table's PK/links.
        work_slug_of = {e["key"]: e["slug"] for e in work_entries}
        composer_slug_of = {ce["composer_key"]: ce["slug"]
                            for ce in composer_entries}
    else:
        registry = load_registry(registry_out_path)
        import ttn2_ledger
        import ttn2_query
        try:
            new_registry, report = sync_registry(
                registry, work_entries, composer_entries,
                today=dt.date.today().isoformat(),
                entity_view=ttn2_query.load_entity_view(),
                anchors=ttn2_ledger.load_anchors())
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
        for slug, old_ck, old_wk, new_ck, new_wk in report["reanchored"]:
            print(f"  reanchored: {slug}  {old_ck}|{old_wk} -> {new_ck}|{new_wk}")

        fp = site_fingerprint(registry_out_path, artist_registry_out_path)
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
    if not force and site_status(site_db_out_path, fp) == "fresh":
        print(f"ttn_site: {site_db_out_path} fresh -- skipping")
        return 0
    # Corpus-wide composer display SSOT: every surface that shows a composer's
    # name (work byline, browse tables, recording page via the works join)
    # reads this map so the spelling never varies between pages. The composer
    # page (build_composer_rows) already uses centry["display"] -- the same
    # value -- so this aligns the work-side surfaces to it.
    composer_display_of = {ce["composer_key"]: ce["display"]
                           for ce in composer_entries}

    conn = sqlite3.connect(db_path)
    try:
        if source == "successor":
            # Spine (ctx/recs/cons) already built in the successor branch
            # above -- BEFORE derive_site_inputs, so its presentation map
            # could be spine-filtered pre-accumulate. No double build.
            pass
        else:
            ctx = ttn_spine.build_context(conn)
            recs = ttn_spine.build_recordings(conn, ctx=ctx)
            cons = ttn_spine.build_contributors(conn, ctx=ctx)
        # The spine is the authority on which recordings can HAVE a page: it
        # drops the interstitial fillers and anything else it excludes. A
        # presentation link to an rp with no recordings row would put a dead
        # /performance/ link on an episode page -- exactly the b0833vgj Milhaud
        # violation check_closure caught on its first live run. Filter here so
        # the invariant holds by construction, not by veto.
        presentation = {k: rp for k, rp in presentation.items() if rp in recs}
        if source == "legacy":
            acc = accumulate_entities(raw8, projection, rec_meta, presentation)
        all_brc_rows = ttn_broadcasters.load_rows(conn)
        episode_meta = list(conn.execute(_EPISODE_META_SQL))
        rebroadcast_rows = list(conn.execute(_REBROADCAST_SQL))
        concert_meta_rows = list(conn.execute(_OPENING_CONCERT_SQL))
        national_day_segment_rows = list(conn.execute(
            "SELECT se.episode_pid, substr(e.broadcast_date, 1, 10), "
            "se.record_label, se.recording_pid FROM segment_events se "
            "JOIN episodes e ON se.episode_pid = e.pid"))
    finally:
        conn.close()

    rebroadcasts = compute_rebroadcasts(rebroadcast_rows)
    concert_meta = build_recording_concert_meta(concert_meta_rows)
    confirmed_ensembles = build_confirmed_ensembles(acc["episode_tracks"])
    concerts = compute_opening_concerts(acc["episode_tracks"], projection,
                                        presentation, concert_meta,
                                        mint_broadcaster_slugs(),
                                        confirmed_ensembles)

    brc_rows_by_rp: dict = {}
    for label, rp in all_brc_rows:
        if rp:
            brc_rows_by_rp.setdefault(rp, []).append(label)

    # The recordings table is the SINGLE SOURCE of bridged per-recording
    # stats: build it first, then derive rp_stats from its own columns so
    # every other builder (works/composers/artists facets) reads the exact
    # numbers the performance pages show. Nothing downstream of rec_rows
    # re-derives count/first/last from raw airings.
    rec_rows, n_multi_work, n_skipped = build_recording_rows(
        acc["work_airings"], acc["recording_airings"], work_slug_of,
        composer_slug_of, recs, cons, brc_rows_by_rp)
    rp_stats = {r[0]: (r[5], r[6], r[7]) for r in rec_rows}

    work_rows = build_work_rows(work_entries, acc["work_airings"],
                                composer_slug_of, composer_display_of,
                                recs, cons, brc_rows_by_rp, rp_stats)
    composer_rows = build_composer_rows(
        composer_entries, work_entries, acc["work_airings"],
        composer_slug_of, work_slug_of, recs, cons, brc_rows_by_rp,
        rp_stats)
    work_first_dates = build_work_first_dates(
        acc["episode_tracks"], {p: d for p, d, _t in episode_meta})
    episode_rows = build_episode_rows(
        episode_meta, acc["episode_tracks"], work_slug_of, composer_slug_of,
        {r[0] for r in rec_rows}, {r[0]: r[3] for r in rec_rows},
        rebroadcasts, concerts, work_first_dates)
    form_rows = build_form_rows(
        work_entries, acc["work_airings"], composer_slug_of,
        composer_display_of)

    # Artist registry-lite: sync (mint-once, MBID-anchored -- see the module
    # section above), dump, then build the artists table with the SYNCED
    # registry as the page-list authority. BEFORE the browse payloads: the
    # contributor listings link via the just-synced slug map. Successor mode
    # writes NO tracked file: the registry is loaded as-is (read-only) and
    # build_artist_rows intersects it with the spine, so only MBIDs present in
    # the corpus emit rows either way.
    art_registry = load_artist_registry(artist_registry_out_path)
    if source == "legacy":
        new_art_registry, art_report = sync_artist_registry(
            art_registry, artist_qualifiers(recs, cons),
            today=dt.date.today().isoformat())
        dump_artist_registry(new_art_registry, artist_registry_out_path)
        print(f"ttn_site: artist registry synced -- {artist_registry_out_path}")
        print(f"  registered artists:   {len(new_art_registry['artists'])} "
             f"(+{art_report['added']} new)")
        art_registry = new_art_registry
    else:
        print("ttn_site: artist registry: read-only (successor source)")
    artist_rows = build_artist_rows(
        art_registry, recs, cons, brc_rows_by_rp, rec_rows,
        work_entries, composer_display_of, rp_stats)
    artist_slug_of = {v["mbid"]: slug
                      for slug, v in art_registry["artists"].items()}

    broadcaster_rows = build_broadcaster_rows(
        all_brc_rows, rec_rows, work_entries, composer_display_of, cons)
    country_rows = build_country_rows(
        all_brc_rows, rec_rows, work_entries, composer_display_of, cons)
    # Year texture (anniversaries/distinctive/arrivals): computed ONCE here,
    # threaded into both the browse 'years' card payload (below) and the
    # per-year drill-in rows (build_year_rows, which also builds it
    # internally off the same inputs -- see its docstring).
    work_first_year = {key: d[:4] for key, d in work_first_dates.items()}
    current_year = dt.date.today().year
    work_display_of = {e["key"]: e["work_display"] for e in work_entries}
    year_texture = build_year_texture(
        build_composer_year_counts(acc["work_airings"]), acc["composer_dates"],
        composer_slug_of, composer_display_of, acc["work_airings"],
        work_first_year, work_slug_of, work_display_of, current_year)
    browse_rows = build_browse_payloads(
        work_entries, acc["work_airings"], rows5, all_brc_rows,
        composer_slug_of, composer_display_of, work_slug_of, recs, cons,
        composer_entries=composer_entries, recording_rows=rec_rows,
        form_rows=form_rows, artist_slug_of=artist_slug_of,
        country_rows=country_rows, year_texture=year_texture,
        year_breakdown=(ttn2_site.year_breakdown_t2(acc)
                        if source == "successor" else None))
    # national_days: reuses build_country_rows' own slug derivation (r[0] is
    # the slug, r[1] the country name) so a card's country link always
    # matches the real /country/ page -- built separately from
    # build_browse_payloads since it needs acc["episode_tracks"], which that
    # function doesn't otherwise take.
    country_slug_of = {r[1]: r[0] for r in country_rows}
    nd_payload = build_national_days(
        national_day_segment_rows, acc["episode_tracks"],
        composer_display_of, country_slug_of)
    browse_rows.append(("national_days", json.dumps(nd_payload)))
    # Phase 2: the same slots feed a per-country block on each /country/ page.
    country_rows = attach_national_days(country_rows, nd_payload)
    # ... and an 'An episode celebrating {country}' chip on each tribute night's
    # episode page (the reciprocal of the topic page; recurring AND one-off).
    episode_rows = attach_episode_national_days(
        episode_rows, national_day_by_date(nd_payload))
    year_rows = build_year_rows(
        work_entries, acc["work_airings"], composer_slug_of,
        composer_display_of, work_slug_of, acc["composer_dates"],
        work_first_year, current_year)

    # Re-stamp the fingerprint AFTER the artist-registry dump: its bytes are
    # a site_fingerprint slot, so stamping the pre-sync value would leave a
    # freshly built site.sqlite permanently 'stale' after any mint.
    # (Successor mode dumps no registry, so its t2 fingerprint below is
    # stable; the slot list itself covers the artist registry either way.)
    if source == "legacy":
        fp = site_fingerprint(registry_out_path, artist_registry_out_path)
    else:
        fp = site_fingerprint_t2(registry_out_path, artist_registry_out_path,
                                 db_path=db_path)

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
        "countries": country_rows,
    }, fp, validate=check_closure)

    print(f"ttn_site: site.sqlite built -- {site_db_out_path}")
    print(f"  works: {len(work_rows)}  composers: {len(composer_rows)}  "
         f"episodes: {len(episode_rows)}  recordings: {len(rec_rows)}  "
         f"browse: {len(browse_rows)}  years: {len(year_rows)}  "
         f"broadcasters: {len(broadcaster_rows)}  forms: {len(form_rows)}  "
         f"artists: {len(artist_rows)}  countries: {len(country_rows)}")
    print(f"  recordings spanning >1 work key: {n_multi_work}  "
         f"skipped (absent from spine): {n_skipped}")
    return 0


def _run_render(registry_out_path, site_db_out_path, dist_out_path, *,
                require_fresh, base_url=BASE_URL,
                artist_registry_out_path=None):
    """Render site_db_out_path + the registry's redirects into dist_out_path.

    require_fresh: the --render-only hard-error gate (SP4a explicit-consumer
    rule, same discipline as _run_build's projection/slug-map checks) --
    True means site_db_out_path MUST already be 'fresh' against the CURRENT
    registry's fingerprint, or this refuses to render a stale/missing
    substrate silently. False (the default build-then-render path) skips the
    check: _run_build has JUST rebuilt (or confirmed fresh) site_db_out_path
    immediately before this runs, so re-deriving the fingerprint here would
    be redundant, not a safety net.

    base_url: absolute-URL base for the sitemap/robots/feed artifacts (page
    HTML is all-relative and never sees it). Defaults to the production
    domain (ttn_site_render.BASE_URL); wired from --base-url for a
    staging/preview render.
    """
    if require_fresh:
        fp = site_fingerprint(registry_out_path, artist_registry_out_path)
        status = site_status(site_db_out_path, fp)
        if status != "fresh":
            print(f"ttn_site: {site_db_out_path} is {status!r}, not fresh -- "
                  f"run `uv run ttn_data.py site` (build + render) first, "
                  f"or drop --render-only.", file=sys.stderr)
            raise SystemExit(1)

    summary = render_site(site_db_out_path, registry_out_path, dist_out_path,
                          base_url=base_url)
    print(f"ttn_site: rendered -- {dist_out_path}")
    print(f"  pages: {summary['pages']}  written: {summary['written']}  "
         f"skipped: {summary['skipped']}  pruned: {summary['pruned']}  "
         f"crawl ok: {summary['crawl_ok']}")
    search_status = ("ok" if summary.get("search_docs") is not None
                      else "SKIPPED (see warning above)")
    print(f"  search index: {search_status}  docs: {summary.get('search_docs')}")
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


def _parse_remap_spec(namespace, spec):
    """Parse one --remap SPEC string into (slug, composer_key, work_key).
    Pure parsing, no registry access -- raises ValueError (not SystemExit)
    on a malformed spec, so a caller assembling a BATCH of specs can
    collect every parse failure before deciding whether to apply anything.

    maxsplit: catalogue-path work keys legitimately CONTAIN pipes
    ('§hwv232|232|'), so a works spec splits with maxsplit=2 and the
    work_key is everything after the second delimiter -- a plain
    split("|") shatters a §-key into bogus extra parts and rejects the
    spec (first hit: the 2026-07-19 Handel batch)."""
    if namespace == "works":
        parts = spec.split("|", 2)
        if len(parts) != 3 or not parts[2]:
            raise ValueError(
                "--remap for works needs \"SLUG|COMPOSER_KEY|WORK_KEY\", "
                f"got {spec!r}")
        slug, composer_key, work_key = parts
        return slug, composer_key, work_key
    parts = spec.split("|")
    if len(parts) != 2:
        raise ValueError(
            f"--remap --composer needs \"SLUG|COMPOSER_KEY\", got {spec!r}")
    slug, composer_key = parts
    return slug, composer_key, None


def _run_remap(registry_out_path, namespace, specs, dry_run=False,
               db_path=None, verify_corpus=False):
    """Apply a BATCH of (source_label, spec) pairs to the registry,
    all-or-nothing. A drift repair after an alias/canonicalization edit is
    inherently a batch -- e.g. 35 orphaned slugs in one curation pass --
    and a half-applied batch leaves a git-tracked decisions file with no
    record of where it stopped.

    Three gates, all BEFORE any write:
      1. every spec is parsed (_parse_remap_spec); failures are collected
         and reported TOGETHER, each identified by its source label.
      2. with --verify-corpus, every successor identity is checked against
         the current derived entries (the corpus pass in `db_path`) -- a
         typo'd key that is registered-valid but corpus-invalid is refused
         instead of becoming the same orphan again on the next sync.
      3. the parsed specs are folded onto the in-memory registry via
         apply_remap (pure -- returns a new registry each time), so a
         later spec correctly sees an earlier one's effect within the
         SAME batch; if any apply_remap raises RegistryActionError, that
         spec's source is reported and nothing is written.
    Only once every spec in the batch has applied cleanly does
    dump_registry run, ONCE. --dry-run walks the identical parse+apply
    path and prints the identical per-spec summary, but stops short of
    the write -- the review step for a large batch before it touches a
    git-tracked file."""
    parsed = []
    errors = []
    for source, spec in specs:
        try:
            slug, composer_key, work_key = _parse_remap_spec(namespace, spec)
        except ValueError as e:
            errors.append(f"  {source}: {e}")
            continue
        parsed.append((source, slug, composer_key, work_key))
    if errors:
        print(f"ttn_site: --remap batch has {len(errors)} invalid spec(s) -- "
              "nothing applied:", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        raise SystemExit(1)

    if verify_corpus:
        if db_path is None:
            print("ttn_site: --verify-corpus needs --db", file=sys.stderr)
            raise SystemExit(1)
        try:
            work_entries, composer_entries, _raw8, _rows5, _projection, \
                _rec_meta = _derive_registry_entries(db_path)
        except ValueError as e:
            print(f"ttn_site: {e}", file=sys.stderr)
            raise SystemExit(1)
        corpus_identities = (
            {e["key"] for e in work_entries}
            if namespace == "works"
            else {e["composer_key"] for e in composer_entries}
        )
        corpus_errors = []
        for source, slug, composer_key, work_key in parsed:
            target = (composer_key, work_key) if namespace == "works" else composer_key
            if target not in corpus_identities:
                corpus_errors.append(
                    f"  {source} ({slug!r}): successor {target!r} not in the current corpus")
        if corpus_errors:
            print(f"ttn_site: --verify-corpus refused {len(corpus_errors)} "
                  "spec(s) -- nothing applied:", file=sys.stderr)
            for line in corpus_errors:
                print(line, file=sys.stderr)
            raise SystemExit(1)

    current = load_registry(registry_out_path)
    messages = []
    redirects_created = 0
    for source, slug, composer_key, work_key in parsed:
        try:
            current = apply_remap(current, namespace, slug, composer_key, work_key)
        except RegistryActionError as e:
            print(f"ttn_site: remap refused ({source}: {slug!r}) -- {e} -- "
                 "nothing applied", file=sys.stderr)
            raise SystemExit(1)
        if slug in current["redirects"][namespace]:
            redirects_created += 1
            messages.append(
                f"ttn_site: remapped {namespace} slug {slug!r} -> redirect to "
                f"{current['redirects'][namespace][slug]!r} (successor already registered)")
        else:
            messages.append(
                f"ttn_site: remapped {namespace} slug {slug!r} to its successor identity")

    for m in messages:
        print(m)
    n = len(parsed)
    if dry_run:
        print(f"ttn_site: --dry-run -- {n} remap(s) would apply "
             f"({redirects_created} as redirects); registry NOT written")
    else:
        dump_registry(current, registry_out_path)
        print(f"ttn_site: applied {n} remap(s) ({redirects_created} as redirects)")
    return 0


def _run_retire(registry_out_path, namespace, slugs, reason=None, dry_run=False):
    """Apply a BATCH of slugs to retire, all-or-nothing -- same discipline as
    _run_remap. Unlike a remap spec, a slug string needs no separate parse
    step, so there's one gate instead of two: each slug is folded onto the
    in-memory registry via apply_retire (pure), continuing past a refusal
    rather than stopping at the first one, so EVERY bad slug in the batch is
    collected and reported together (also catches a slug listed twice: its
    second application refuses because the first already removed it from
    `registered`). Only once every slug in the batch has applied cleanly
    does dump_registry run, ONCE. --dry-run walks the identical fold path
    and prints the identical summary, but stops short of the write."""
    current = load_registry(registry_out_path)
    today = dt.date.today().isoformat()
    errors = []
    retired_slugs = []
    for slug in slugs:
        try:
            current = apply_retire(current, namespace, slug, reason=reason, today=today)
        except RegistryActionError as e:
            errors.append(f"  {slug!r}: {e}")
            continue
        retired_slugs.append(slug)

    if errors:
        print(f"ttn_site: --retire batch has {len(errors)} refusal(s) -- "
             "nothing applied:", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        raise SystemExit(1)

    for slug in retired_slugs:
        print(f"ttn_site: retired {namespace} slug {slug!r}")
    n = len(retired_slugs)
    if dry_run:
        print(f"ttn_site: --dry-run -- {n} retirement(s) would apply; "
             "registry NOT written")
    else:
        dump_registry(current, registry_out_path)
        print(f"ttn_site: retired {n} slug(s)")
    return 0


def _parse_anchor_spec(namespace, spec):
    """Parse one --anchor-file SPEC string into (slug, entity_id,
    composer_key, work_key). Pure parsing, no registry access -- raises
    ValueError (not SystemExit) on a malformed spec, so a caller assembling
    a BATCH of specs can collect every parse failure before deciding
    whether to apply anything.

    maxsplit: catalogue-path work keys legitimately CONTAIN pipes
    ('§hwv232|232|'), so a works spec splits with maxsplit=3 and the
    work_key is everything after the third delimiter -- the same discipline
    _parse_remap_spec applies one field earlier."""
    if namespace == "works":
        parts = spec.split("|", 3)
        if len(parts) != 4 or not parts[3]:
            raise ValueError(
                "--anchor-file for works needs "
                f"\"SLUG|ENTITY_ID|COMPOSER_KEY|WORK_KEY\", got {spec!r}")
        slug, eid_str, composer_key, work_key = parts
    else:
        parts = spec.split("|")
        if len(parts) != 3:
            raise ValueError(
                f"--anchor-file --composer needs \"SLUG|ENTITY_ID|COMPOSER_KEY\", "
                f"got {spec!r}")
        slug, eid_str, composer_key = parts
        work_key = None
    try:
        entity_id = int(eid_str)
    except ValueError:
        raise ValueError(
            f"entity_id must be an integer, got {eid_str!r}") from None
    return slug, entity_id, composer_key, work_key


def _run_anchor(registry_out_path, namespace, specs, dry_run=False):
    """Apply a BATCH of (source_label, spec) anchor specs to the registry,
    all-or-nothing -- the --remap-file discipline applied to entity
    anchoring (P4 phase 2): the drift batch is inherently a batch (88+ slugs
    in one ratification round) and a half-applied batch leaves a git-tracked
    decisions file with no record of where it stopped.

    Two gates, both BEFORE any write:
      1. every spec is parsed (_parse_anchor_spec); failures are collected
         and reported TOGETHER, each identified by its source label.
      2. the parsed specs are folded onto the in-memory registry via
         apply_anchor (pure -- returns a new registry each time), so a
         later spec correctly sees an earlier one's effect within the
         SAME batch; if any apply_anchor raises RegistryActionError, that
         spec's source is reported and nothing is written.
    Only once every spec in the batch has applied cleanly does
    dump_registry run, ONCE. --dry-run walks the identical parse+apply
    path and prints the identical per-spec summary, but stops short of
    the write -- the review step for a large batch before it touches a
    git-tracked file."""
    parsed = []
    errors = []
    for source, spec in specs:
        try:
            slug, entity_id, composer_key, work_key = \
                _parse_anchor_spec(namespace, spec)
        except ValueError as e:
            errors.append(f"  {source}: {e}")
            continue
        parsed.append((source, slug, entity_id, composer_key, work_key))
    if errors:
        print(f"ttn_site: --anchor batch has {len(errors)} invalid spec(s) -- "
              "nothing applied:", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        raise SystemExit(1)

    current = load_registry(registry_out_path)
    messages = []
    for source, slug, entity_id, composer_key, work_key in parsed:
        try:
            current = apply_anchor(current, namespace, slug, entity_id,
                                    composer_key, work_key)
        except RegistryActionError as e:
            print(f"ttn_site: anchor refused ({source}: {slug!r}) -- {e} -- "
                  "nothing applied", file=sys.stderr)
            raise SystemExit(1)
        if namespace == "works":
            if slug not in current[namespace]:
                # existing-identity guard fired: the anchored slug became a
                # redirect onto the holder (mirror apply_remap's arm)
                messages.append(
                    f"ttn_site: anchored {namespace} slug {slug!r} -> entity "
                    f"{entity_id} ({composer_key!r}, {work_key!r}) -- identity "
                    f"already registered, became REDIRECT to "
                    f"{current['redirects'][namespace][slug]!r}")
            else:
                messages.append(
                    f"ttn_site: anchored {namespace} slug {slug!r} -> entity "
                    f"{entity_id} ({composer_key!r}, {work_key!r})")
        else:
            messages.append(
                f"ttn_site: anchored {namespace} slug {slug!r} -> entity "
                f"{entity_id} ({composer_key!r})")

    for m in messages:
        print(m)
    n = len(parsed)
    if dry_run:
        print(f"ttn_site: --dry-run -- {n} anchor(s) would apply; "
             "registry NOT written")
    else:
        dump_registry(current, registry_out_path)
        print(f"ttn_site: applied {n} anchor(s)")
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
    ap.add_argument("--source", choices=("legacy", "successor"), default="legacy",
                    help="identity source for the build: 'legacy' (the "
                        "projection + alias chain, default) or 'successor' "
                        "(the ttn2 events ledger; reads the registry "
                        "read-only, writes no tracked file, and defaults "
                        "--site-db to site2.sqlite)")
    ap.add_argument("--build-only", action="store_true",
                    help="build/refresh site.sqlite only -- skip rendering")
    ap.add_argument("--render-only", action="store_true",
                    help="render only, from the EXISTING site.sqlite -- skip the build; "
                        "hard-errors unless it's already fresh")
    ap.add_argument("--base-url", default=BASE_URL, metavar="URL",
                    help="absolute-URL base for sitemaps/robots/feed "
                        f"(default: the production domain, {BASE_URL}); "
                        "page HTML is all-relative and unaffected")
    ap.add_argument("--composer", action="store_true",
                    help="apply --rename/--remap in the composers namespace (default: works)")
    ap.add_argument("--rename", nargs=2, metavar=("OLD", "NEW"),
                    help="move a registered slug's identity from OLD to NEW, leaving a redirect")
    ap.add_argument("--remap", metavar="SPEC", action="append",
                    help="re-point an orphaned slug at its successor identity: "
                        "\"SLUG|COMPOSER_KEY|WORK_KEY\" (or \"SLUG|COMPOSER_KEY\" with "
                        "--composer). Repeatable -- combines with --remap-file (file "
                        "specs first, then --remap flags in order) into one "
                        "all-or-nothing batch")
    ap.add_argument("--remap-file", metavar="PATH", default=None,
                    help="read --remap SPECs from PATH, one per line (blank lines "
                        "and lines starting with # skipped); combines with --remap")
    ap.add_argument("--verify-corpus", action="store_true",
                    help="with --remap/--remap-file: refuse any successor identity "
                        "not present in the current corpus (needs --db)")
    ap.add_argument("--retire", metavar="SLUG", action="append",
                    help="retire a registered slug whose identity DISSOLVED rather "
                        "than moved -- no successor to --remap to. Moves it into "
                        "the registry's 'retired' record (see --reason); the URL "
                        "renders no page and 404s. Repeatable -- combines with "
                        "--retire-file into one all-or-nothing batch")
    ap.add_argument("--retire-file", metavar="PATH", default=None,
                    help="read --retire SLUGs from PATH, one per line (blank lines "
                        "and lines starting with # skipped); combines with --retire")
    ap.add_argument("--anchor-file", metavar="PATH", action="append", default=None,
                    help="anchor registered slugs to their ratified successor "
                        "entity IDs (P4 phase 2 drift batch): read specs from "
                        "PATH, one per line -- \"SLUG|ENTITY_ID|COMPOSER_KEY|WORK_KEY\" "
                        "(or \"SLUG|ENTITY_ID|COMPOSER_KEY\" with --composer); blank "
                        "lines and lines starting with # skipped; repeatable -- "
                        "all named files fold into one all-or-nothing batch")
    ap.add_argument("--reason", metavar="TEXT", default=None,
                    help="free-text reason recorded against every slug in a "
                        "--retire/--retire-file batch (optional)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --remap/--remap-file, --retire/--retire-file or "
                        "--anchor-file: "
                        "parse, validate and apply the batch in memory and report "
                        "what would happen, but don't write the registry")
    ap.add_argument("--check", action="store_true",
                    help="read-only registry drift check: derive current entries, "
                        "run sync_registry in memory, and report -- writes nothing")
    args = ap.parse_args(argv)

    if (args.remap or args.remap_file) and (args.retire or args.retire_file):
        ap.error("--remap/--remap-file and --retire/--retire-file can't be "
                 "combined in one run -- do them as separate batches")
    if args.anchor_file and (args.remap or args.remap_file
                             or args.retire or args.retire_file):
        ap.error("--anchor-file can't be combined with --remap/--retire in "
                 "one run -- do them as separate batches")

    reg_path = args.registry if args.registry is not None else registry_path()
    artist_reg_path = (args.artist_registry if args.artist_registry is not None
                       else artist_registry_path())
    # Successor default is the LITERAL cwd-relative 'site2.sqlite': the rest of
    # the successor ecosystem (successor.sqlite via ttn2_site.DB,
    # ttn2_ledger.json, the t2 fingerprint's DB/ledger slots) is cwd-relative
    # too, so the whole successor state lives in one place. Legacy keeps the
    # beside-module default.
    site_db_out = args.site_db if args.site_db is not None else (
        "site2.sqlite" if args.source == "successor" else site_db_path())
    dist_out = args.dist if args.dist is not None else dist_path_default()
    namespace = "composers" if args.composer else "works"

    if args.check:
        return _run_check(args.db, reg_path)

    if args.rename:
        return _run_rename(reg_path, namespace, args.rename[0], args.rename[1])
    if args.remap or args.remap_file:
        specs = []
        if args.remap_file:
            try:
                with open(args.remap_file, encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as e:
                print(f"ttn_site: --remap-file: {e}", file=sys.stderr)
                raise SystemExit(1)
            for lineno, raw in enumerate(lines, 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                specs.append((f"{args.remap_file}:{lineno}", line))
        for i, spec in enumerate(args.remap or [], 1):
            specs.append((f"--remap #{i}", spec))
        return _run_remap(reg_path, namespace, specs, dry_run=args.dry_run,
                          db_path=args.db, verify_corpus=args.verify_corpus)
    if args.retire or args.retire_file:
        slugs = []
        if args.retire_file:
            try:
                with open(args.retire_file, encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as e:
                print(f"ttn_site: --retire-file: {e}", file=sys.stderr)
                raise SystemExit(1)
            for raw in lines:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                slugs.append(line)
        slugs.extend(args.retire or [])
        return _run_retire(reg_path, namespace, slugs, reason=args.reason,
                           dry_run=args.dry_run)

    if args.anchor_file:
        specs = []
        for anchor_path in args.anchor_file:
            try:
                with open(anchor_path, encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as e:
                print(f"ttn_site: --anchor-file: {e}", file=sys.stderr)
                raise SystemExit(1)
            for lineno, raw in enumerate(lines, 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                specs.append((f"{anchor_path}:{lineno}", line))
        return _run_anchor(reg_path, namespace, specs, dry_run=args.dry_run)

    if args.render_only:
        return _run_render(reg_path, site_db_out, dist_out, require_fresh=True,
                           base_url=args.base_url,
                           artist_registry_out_path=artist_reg_path)

    rc = _run_build(args.db, reg_path, site_db_out, force=args.force,
                    artist_registry_out_path=artist_reg_path,
                    source=args.source)
    if rc not in (0, None):
        return rc
    if args.build_only:
        return 0
    return _run_render(reg_path, site_db_out, dist_out, require_fresh=False,
                       base_url=args.base_url)


if __name__ == "__main__":
    main()
