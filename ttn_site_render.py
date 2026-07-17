"""Site renderer (website Phase 2): turns site.sqlite into the static dist/
tree. ttn_site.py builds the substrate (site.sqlite + slug registry); this
module renders it. Reached as `ttn_data.py site` (render stage).

This module holds the pure core (the URL authority url_for, the dist-path
mapping dist_path, and the write-if-changed file writer) plus the per-page
context builders (render_work / render_composer / render_performance /
render_episode_date / render_home / render_browse / render_about /
render_redirect), the Jinja2 Environment that renders templates/*.html into
page HTML, the non-HTML builders (build_sitemaps / build_robots /
build_atom_feed), the Pagefind search-index post-pass (run_pagefind), and
the site-wide driver render_site that ties everything together: load
site.sqlite + the registry, render every page, prune stale ones, crawl for
dangling internal links, write the non-HTML outputs + static/, and (opt-in
via pagefind=True) run the search post-pass.
"""
import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_quoteattr

import jinja2

import ttn_ebu_codes

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

_ROLE_ORDER = ("Composer", "Conductor", "Orchestra", "Ensemble", "Performer",
               "Singer", "Choir")

_env_singleton = None

# The Phase-3 domain decision hasn't been made yet -- every absolute-URL
# builder (build_sitemaps, build_robots, build_atom_feed) takes base_url as a
# parameter defaulting to this constant, so there is exactly one place to
# change once a real domain is chosen.
BASE_URL = "https://example.invalid"

# render_browse's `name` -> template file. Keys are EXACTLY the DB's
# browse.name PK values (ttn_site.build_browse_payloads: top_works/years/
# broadcasters/house_performances) -- the canonical input is what the table
# stores. The URL-facing spelling ('works' for 'top_works', see the URL
# contract in the Phase 2 preamble: /browse/works/, not /browse/top-works/)
# is a rendering detail handled internally via browse_url_name; it is NOT
# an accepted alias for `name` (narrowed in task 5 -- the Task-3 reviewer
# note: canonical input = what the table stores, the URL mapping stays
# internal).
# recordings.broadcaster stores the DECODED broadcaster name (not the EBU
# code), so the performance page derives its country flag + name via this
# reverse map, built from the EBU table itself -- a NULL/unknown broadcaster
# simply gets no flag. The country name is the flag's hover tooltip.
_BROADCASTER_FLAG = {name: (ttn_ebu_codes.flag(cc), country)
                     for name, cc, country in ttn_ebu_codes.EBU_CODES.values()}

_BROWSE_TEMPLATES = {
    "top_works": "browse_works.html",
    "top_performances": "browse_performances.html",
    "composers": "browse_composers.html",
    "ensembles": "browse_ensembles.html",
    "lengths": "browse_lengths.html",
    "forms": "browse_forms.html",
    "christmas": "browse_christmas.html",
    "house_performances": "browse_house_performances.html",
    "years": "browse_years.html",
    "broadcasters": "browse_broadcasters.html",
}


def url_for(kind: str, key: str) -> str:
    """The single URL authority — every template link goes through this, no
    hand-built hrefs anywhere.

    kind in {"work", "composer", "episode", "performance", "browse", "year",
    "broadcaster", "form"}; ValueError on anything else. ("performance" is the customer-facing name
    for a BBC recording PID page — renamed from "recording" 2026-07-16,
    tester feedback: "recording" implied a link to playable music.)

    - "work": split on the FIRST ':' -> /work/{composer_part}/{work_part}/.
      A colon-less slug (the hash-fallback class, e.g. 'wbd926ff4') ->
      /work/{slug}/. A collision suffix ('abel:trio-in-f-major-for-2') flows
      through the same first-colon split.
    - "episode": key is an ISO date 'YYYY-MM-DD' -> /episode/YYYY/MM/DD/.
    - "composer" / "performance" / "year": key verbatim -> /{kind}/{key}/
      ("performance" key is a recording_pid; "year" key is a 4-digit year ->
      /year/YYYY/).
    - "browse": key is the URL name (hyphenated) -> /browse/{key}/, OR the
      empty string -> /browse/ (the browse landing index). Callers holding a
      payload name (underscore-separated, e.g. 'house_performances') must map
      it first via browse_url_name.
    """
    if kind == "work":
        composer_part, sep, work_part = key.partition(":")
        if sep:
            return f"/work/{composer_part}/{work_part}/"
        return f"/work/{key}/"
    if kind == "episode":
        year, month, day = key.split("-")
        return f"/episode/{year}/{month}/{day}/"
    if kind == "composer":
        return f"/composer/{key}/"
    if kind == "performance":
        return f"/performance/{key}/"
    if kind == "year":
        return f"/year/{key}/"
    if kind == "broadcaster":
        return f"/broadcaster/{key}/"
    if kind == "form":
        return f"/form/{key}/"
    if kind == "browse":
        return f"/browse/{key}/" if key else "/browse/"
    raise ValueError(f"url_for: unknown kind {kind!r}")


def browse_url_name(payload_name: str) -> str:
    """Map a browse payload name (underscore-separated, as stored in
    browse.name) to the URL segment (hyphenated) that url_for("browse", ...)
    expects. 'house_performances' -> 'house-performances'; 'works' -> 'works'."""
    return payload_name.replace("_", "-")


def dist_path(url: str, dist_dir: str) -> str:
    """Map a url_for()-produced URL to its dist/ file path: strip leading/
    trailing slashes, join under dist_dir, append index.html. Root '/' ->
    '{dist_dir}/index.html'."""
    trimmed = url.strip("/")
    if trimmed:
        return os.path.join(dist_dir, trimmed, "index.html")
    return os.path.join(dist_dir, "index.html")


def write_if_changed(path: str, content: str) -> bool:
    """Write content (str, UTF-8, verbatim — no trailing newline appended) to
    path, creating parent directories as needed. Skips the write (mtime
    untouched) when the existing file's bytes already match; returns True iff
    it wrote."""
    new_bytes = content.encode("utf-8")
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == new_bytes:
                return False
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(new_bytes)
    return True


# --- Jinja2 environment -------------------------------------------------------

def _env():
    """Lazy singleton Jinja2 Environment: FileSystemLoader on templates/
    beside this module, autoescape ON (non-negotiable — titles carry
    &/"/<), keep_trailing_newline. url_for is exposed as a template global
    so no template ever hand-builds an href."""
    global _env_singleton
    if _env_singleton is None:
        _env_singleton = jinja2.Environment(
            loader=jinja2.FileSystemLoader(_TEMPLATES_DIR),
            autoescape=True,
            keep_trailing_newline=True,
        )
        _env_singleton.globals["url_for"] = url_for
        _env_singleton.filters["clock"] = format_clock
    return _env_singleton


def _built_at(env):
    """The built_at value every page builder stamps into its footer: read
    from env.globals (render_site sets it once, from site.sqlite's
    meta.built_at, before rendering any page) -- absent -> None (a builder
    called standalone, e.g. from a unit test, renders with no footer
    timestamp, exactly today's behaviour)."""
    return env.globals.get("built_at")


def format_date(date10: str) -> str:
    """Format an ISO 'YYYY-MM-DD' date as a human-readable string for page
    h1s ('2026-07-11' -> '11 July 2026'). Uses the glibc '%-d' no-leading-
    zero directive -- fine, this project runs Linux only (not portable to
    other platforms' libc, e.g. macOS/BSD, which don't support '%-d').
    <title> elements keep the ISO form; only the h1 uses this."""
    d = datetime.date.fromisoformat(date10)
    return d.strftime("%-d %B %Y")


_CLOCK_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*:?\s*([AaPp][Mm]?)?")


def format_clock(time_str):
    """Reformat a stored BBC clock string to dotted lowercase 'h.mmam'
    ('12:31 AM' -> '12.31am', '1.05am' -> '1.05am', '01:00 BST' -> '1.00am').

    Through the Night is an overnight show, so a source time with NO meridiem
    is read as AM (the same convention ttn_mbid_audit uses). A 24-hour source
    hour (>12, or 0 for just-after-midnight) is converted. Anything the regex
    can't parse is returned unchanged -- display never loses the source value.
    The variety of source spellings (dot/colon separator, stray colon,
    attached/detached am, timezone suffix) is the Known-parser-quirks time
    family."""
    if not time_str:
        return time_str
    m = _CLOCK_RE.match(time_str)
    if not m:
        return time_str
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= minute < 60) or hour > 23:
        return time_str
    mer = (m.group(3) or "").lower()
    if mer:
        meridiem = "am" if mer.startswith("a") else "pm"
    elif hour > 12:                        # unambiguous 24-hour source
        meridiem = "pm"
    else:
        meridiem = "am"                    # overnight-show default
    if hour == 0:
        hour = 12                          # 00:31 -> 12.31am
    elif hour > 12:
        hour -= 12                         # 13:00 -> 1.00pm
    return f"{hour}.{minute:02d}{meridiem}"


def format_duration(seconds):
    """Format a duration in seconds as M:SS ('3671' -> '61:11'). None/falsy
    (but not 0) -> None (the caller omits the fact)."""
    if seconds is None:
        return None
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


# --- per-page context builders ------------------------------------------------

def render_work(row, env=None):
    """Build the work page. row: the works-table tuple/sqlite3.Row (see
    ttn_site._SITE_SCHEMA's works columns). Returns (url, html)."""
    env = env or _env()
    facets = json.loads(row["facets_json"]) if row["facets_json"] else {}

    recordings = []
    for r in facets.get("recordings", []):
        r = dict(r)
        r["duration_display"] = format_duration(r.get("duration"))
        # older facets (pre-broadcaster-column) lack the keys -> plain absent
        r.setdefault("broadcaster", None)
        r.setdefault("broadcaster_slug", None)
        r["broadcaster_flag"] = _BROADCASTER_FLAG.get(
            r["broadcaster"], ("", ""))[0] if r["broadcaster"] else ""
        r["broadcaster_country"] = _BROADCASTER_FLAG.get(
            r["broadcaster"], ("", ""))[1] if r["broadcaster"] else ""
        recordings.append(r)

    by_year = facets.get("by_year", [])

    broadcasters = []
    for b in facets.get("broadcasters", []):
        name = ttn_ebu_codes.decode(b.get("key"))[0] or b.get("key")
        broadcasters.append({**b, "display_name": name})

    slug = row["slug"]
    url = url_for("work", slug)
    template = env.get_template("work.html")
    html = template.render(
        work_display=row["work_display"],
        composer_display=row["composer_display"],
        composer_slug=row["composer_slug"],
        catalogue=row["catalogue"],
        airings=row["airings"],
        n_recordings=row["n_recordings"],
        n_text_only=row["n_text_only"],
        first_aired=row["first_aired"],
        last_aired=row["last_aired"],
        recordings=recordings,
        top_performers=facets.get("top_performers", []),
        top_conductors=facets.get("top_conductors", []),
        top_ensembles=facets.get("top_ensembles", []),
        by_year=by_year,
        broadcasters=broadcasters,
        built_at=_built_at(env),
    )
    return url, html


def render_composer(row, env=None):
    """Build the composer page. row: the composers-table tuple/sqlite3.Row.
    facets_json (2026-07-17) carries the work-page-style analytics: by_year
    ({year, airings, works}, newest-first) plus top_performers/top_conductors/
    top_ensembles/broadcasters (2012+, performance-linked -- the page states
    that scope when any are present). Returns (url, html)."""
    env = env or _env()
    works = json.loads(row["works_json"]) if row["works_json"] else []
    facets = json.loads(row["facets_json"]) if row["facets_json"] else {}

    broadcasters = []
    for b in facets.get("broadcasters", []):
        name = ttn_ebu_codes.decode(b.get("key"))[0] or b.get("key")
        broadcasters.append({**b, "display_name": name})

    slug = row["slug"]
    url = url_for("composer", slug)
    template = env.get_template("composer.html")
    html = template.render(
        display=row["display"],
        airings=row["airings"],
        n_works=row["n_works"],
        works=works,
        top_performers=facets.get("top_performers", []),
        top_conductors=facets.get("top_conductors", []),
        top_ensembles=facets.get("top_ensembles", []),
        by_year=facets.get("by_year", []),
        broadcasters=broadcasters,
        built_at=_built_at(env),
    )
    return url, html


def render_performance(row, env=None, *, work_display, composer_display=None,
                       broadcaster_slug_of=None):
    """Build the performance page (one BBC recording PID; site-facing name
    "performance"). row: the recordings-table tuple/sqlite3.Row
    (recording_pid, work_slug, composer_slug, duration, broadcaster,
    airings, first_aired, last_aired, contributors_json, airing_dates_json).

    The recordings table carries only slugs, not display titles, so
    `work_display` is a REQUIRED keyword-only argument: the caller (the
    site-wide driver) must join against works and pass the work's display
    title. A default-with-fallback here would silently ship ~18.9k performance
    pages titled with bare pids if the driver forgot the join; the required
    keyword makes that structurally impossible (the Phase-1 known_rps
    precedent — cross-table join inputs are mandatory, never defaulted).
    `composer_display` stays optional: when None it derives from the
    Composer-role contributor in contributors_json, which is the correct
    per-recording credit. Returns (url, html)."""
    env = env or _env()
    contributors = json.loads(row["contributors_json"]) if row["contributors_json"] else []
    airing_dates_raw = json.loads(row["airing_dates_json"]) if row["airing_dates_json"] else []

    by_role = {}
    for c in contributors:
        by_role.setdefault(c["role"], []).append(c["name"])
    contributors_by_role = [
        (role, by_role[role]) for role in _ROLE_ORDER if role in by_role
    ]
    # Any role outside the known vocabulary still renders, appended in
    # first-seen order, rather than silently dropping a contributor.
    for role in by_role:
        if role not in _ROLE_ORDER:
            contributors_by_role.append((role, by_role[role]))

    airing_dates = [{"date": d, "episode_pid": ep} for d, ep in airing_dates_raw]

    broadcaster_display = row["broadcaster"] or ""
    broadcaster_flag, broadcaster_country = _BROADCASTER_FLAG.get(
        broadcaster_display, ("", ""))
    # broadcaster_slug_of: {decoded display name -> drill-in page slug}, the
    # driver's join against the broadcasters table. Absent/unmatched -> the
    # name renders as plain text (safe degrade, never a dangling link).
    _bslug = (broadcaster_slug_of or {}).get(broadcaster_display)
    broadcaster_url = url_for("broadcaster", _bslug) if _bslug else None

    rp = row["recording_pid"]
    if composer_display is None:
        composer_display = ", ".join(by_role.get("Composer", [])) or None

    url = url_for("performance", rp)
    template = env.get_template("performance.html")
    html = template.render(
        recording_pid=rp,
        work_slug=row["work_slug"],
        work_display=work_display,
        composer_slug=row["composer_slug"],
        composer_display=composer_display,
        duration_display=format_duration(row["duration"]),
        broadcaster_display=broadcaster_display,
        broadcaster_flag=broadcaster_flag,
        broadcaster_country=broadcaster_country,
        broadcaster_url=broadcaster_url,
        airings=row["airings"],
        first_aired=row["first_aired"],
        last_aired=row["last_aired"],
        contributors_by_role=contributors_by_role,
        airing_dates=airing_dates,
        built_at=_built_at(env),
    )
    return url, html


def render_episode_date(date10, episode_rows, env=None, *, prev_date=None, next_date=None):
    """Build the one page per broadcast DATE. episode_rows: the date's
    episodes-table rows (usually 1; the 7 multi-pid dates carry 2-3), each a
    tuple/sqlite3.Row/dict with (pid, date, title, bbc_url, tracks_json).
    Each renders as its own <section id="{pid}"> with the episode title, the
    bbc.co.uk outlink, and its playlist (the shared _playlist.html macro). A
    row whose tracks_json is [] (the 75 zero-track anchor episodes) shows the
    honest "no parseable tracklist" line via the macro itself.

    prev_date/next_date (ISO date strings or None): the driver computes these
    from the actual sorted date list, so a gap (a displaced night) is simply
    absent -- this builder never guesses or interpolates a neighbour.
    Returns (url, html)."""
    env = env or _env()
    episodes = []
    for row in episode_rows:
        tracks = json.loads(row["tracks_json"]) if row["tracks_json"] else []
        episodes.append({
            "pid": row["pid"],
            "title": row["title"],
            "bbc_url": row["bbc_url"],
            "tracks": tracks,
        })

    url = url_for("episode", date10)
    template = env.get_template("episode.html")
    html = template.render(
        date10=date10,
        date_display=format_date(date10),
        episodes=episodes,
        prev_date=prev_date,
        next_date=next_date,
        built_at=_built_at(env),
    )
    return url, html


def render_home(stats, last_night, env=None, *, last_night_date=None,
                on_this_night=()):
    """Build the home page. stats: dict {works, composers, ensembles,
    episodes, recordings, date_min, date_max} (the driver derives these from
    table counts, except ensembles -- the browse payload's identity total). last_night: the most recent date's episode_rows, in the SAME
    shape render_episode_date takes (tuple/sqlite3.Row/dict rows with pid,
    title, bbc_url, tracks_json) -- rendered via the shared _playlist.html
    macro so the home and episode playlists never diverge.
    last_night_date (ISO YYYY-MM-DD or None): the most recent broadcast date;
    shown formatted under the "Last night" heading and linked to that night's
    /episode/ page. None -> no date line (empty corpus).
    on_this_night: ISO dates of the SAME calendar night (month-day) in
    previous years, newest first -- rendered as year links under an "On this
    night" heading (empty -> no block). Anchored to last_night_date by the
    driver, NEVER to the wall clock: the render must stay a pure function of
    site.sqlite (byte-identical re-renders). Returns ("/", html)."""
    env = env or _env()
    episodes = []
    for row in last_night:
        tracks = json.loads(row["tracks_json"]) if row["tracks_json"] else []
        episodes.append({
            "pid": row["pid"],
            "title": row["title"],
            "bbc_url": row["bbc_url"],
            "tracks": tracks,
        })

    template = env.get_template("home.html")
    html = template.render(
        stats=stats,
        last_night=episodes,
        last_night_date=last_night_date,
        last_night_date_display=format_date(last_night_date) if last_night_date else None,
        last_night_url=url_for("episode", last_night_date) if last_night_date else None,
        on_this_night=[{"url": url_for("episode", d), "year": d[:4]}
                       for d in on_this_night],
        built_at=_built_at(env),
    )
    return "/", html


def render_browse(name, payload, env=None):
    """Build one browse page. name: the browse axis, EXACTLY the DB's
    browse.name PK ('top_works', 'house_performances', 'years',
    'broadcasters') -- the URL-facing spelling ('works' for 'top_works') is
    not accepted here (narrowed in task 5; see _BROWSE_TEMPLATES). payload:
    the list of dicts from browse.payload_json (ttn_site.build_browse_
    payloads' shapes). Unknown name -> ValueError (never silently render an
    empty/wrong page). Returns (url, html)."""
    env = env or _env()
    template_name = _BROWSE_TEMPLATES.get(name)
    if template_name is None:
        raise ValueError(f"render_browse: unknown browse name {name!r}; "
                         f"known: {sorted(_BROWSE_TEMPLATES)}")

    # 'top_'-prefixed payload names shed the prefix in the URL
    # (top_works -> /browse/works/, top_performances -> /browse/performances/).
    url_name = browse_url_name(name[4:] if name.startswith("top_") else name)
    url = url_for("browse", url_name)

    rows = payload
    extra = {}
    if name == "broadcasters":
        rows = []
        for b in payload:
            b = dict(b)
            b["display_name"] = ttn_ebu_codes.decode(b.get("key"))[0] or b.get("key")
            # Flag only RECOGNIZED EBU codes -- decode()'s fallback fabricates
            # a pseudo country from an unknown label's first two letters, and
            # the UNATTRIBUTED/OTHER buckets have no country at all. The
            # country name rides along as the flag's hover tooltip.
            if b.get("key") and ttn_ebu_codes.is_ebu_code(b["key"]):
                _n, cc, country = ttn_ebu_codes.decode(b["key"])
                b["flag"] = ttn_ebu_codes.flag(cc)
                b["country"] = country
            else:
                b["flag"] = ""
                b["country"] = ""
            rows.append(b)
    elif name == "ensembles":
        # dict payload {cut, total, rows} (ttn_site.build_browse_payloads):
        # the template needs the inclusion line + the whole-corpus identity
        # count for its scope blurb, not just the rows.
        rows = payload.get("rows", [])
        extra = {"cut": payload.get("cut"), "total": payload.get("total")}
    elif name == "lengths":
        # dict payload {short_max, long_min, short, medium, long}: three
        # ranked sections; the median formats here (M:SS, like durations
        # everywhere else on the site).
        sections = {}
        for s in ("short", "medium", "long"):
            sections[s] = [dict(w, median_display=format_duration(
                               w.get("median_seconds")))
                           for w in payload.get(s, [])]
        rows = []
        extra = {"sections": sections}
    elif name == "christmas":
        # dict payload {window, top_works, nights}: the nights become
        # episode-date links labelled with the formatted date.
        rows = payload.get("top_works", [])
        extra = {"nights": [{"url": url_for("episode", d),
                              "display": format_date(d)}
                             for d in payload.get("nights", [])]}
    elif name == "years":
        # Flag endpoint years whose coverage is bounded by the corpus, not
        # the calendar (mirrors ttn_analyze._partial_years: ONLY the first
        # and last chronological buckets can be truncated). The payload is
        # newest-first, so the endpoints are rows[0] (latest) and rows[-1]
        # (earliest). Without the flag a mid-cut final year reads as a
        # programming collapse.
        rows = [dict(y) for y in payload]
        if rows:
            latest, earliest = rows[0], rows[-1]
            if (latest.get("date_max") or "") < f"{latest['year']}-12-31":
                latest["partial"] = True
            if (earliest.get("date_min") or "9999") > f"{earliest['year']}-01-01":
                earliest["partial"] = True
        extra = {"any_partial": any(y.get("partial") for y in rows)}

    template = env.get_template(template_name)
    html = template.render(rows=rows, built_at=_built_at(env), **extra)
    return url, html


# The browse landing index: ordered (payload-name, label) pairs. The index
# lists only the axes actually rendered (defensive: never link a page that
# wasn't emitted), in this canonical order.
_BROWSE_INDEX_LABELS = [
    ("top_works", "Works"),
    ("composers", "Composers"),
    ("ensembles", "Ensembles"),
    ("top_performances", "Performances"),
    ("lengths", "Works by length"),
    ("forms", "Works by form"),
    ("christmas", "Christmas"),
    ("years", "Years"),
    ("broadcasters", "Broadcasters"),
    ("house_performances", "House performances"),
]


def render_browse_index(rendered_browse, env=None):
    """Build the /browse/ landing page -- a simple index of the browse axes.
    rendered_browse: {payload_name: url} for the browse pages that WERE
    emitted this run; the index links only those (so it can never dangle),
    in _BROWSE_INDEX_LABELS order. Returns ('/browse/', html)."""
    env = env or _env()
    items = [
        {"url": rendered_browse[name], "label": label}
        for name, label in _BROWSE_INDEX_LABELS
        if name in rendered_browse
    ]
    template = env.get_template("browse_index.html")
    html = template.render(items=items, built_at=_built_at(env))
    return url_for("browse", ""), html


def render_year(row, env=None):
    """Build one /year/YYYY/ drill-in page from a years-table row
    (sqlite3.Row/dict/tuple-like with year, airings, n_works, n_composers,
    top_works_json, top_composers_json). top_works/top_composers render as
    ranked link lists (already ordered by airings in the row JSON). Returns
    (url, html)."""
    env = env or _env()
    year = row["year"]
    top_works = json.loads(row["top_works_json"]) if row["top_works_json"] else []
    top_composers = (json.loads(row["top_composers_json"])
                     if row["top_composers_json"] else [])
    template = env.get_template("year.html")
    html = template.render(
        year=year,
        airings=row["airings"],
        n_works=row["n_works"],
        n_composers=row["n_composers"],
        top_works=top_works,
        top_composers=top_composers,
        built_at=_built_at(env),
    )
    return url_for("year", year), html


def render_broadcaster(row, env=None):
    """Build one /broadcaster/{slug}/ drill-in page from a broadcasters-table
    row (slug, key, display, country, airings, n_recordings, top_works_json,
    top_performances_json, top_ensembles_json). The display keeps any
    curatorial parenthetical (the slug stripped it); the flag rides the
    standard tip.flag tooltip and is absent for pseudo/withdrawn country
    codes. top_works/top_performances render as ranked link tables;
    top_ensembles is a link-less list. Returns (url, html)."""
    env = env or _env()
    _name, cc, _country = ttn_ebu_codes.decode(row["key"])
    template = env.get_template("broadcaster.html")
    html = template.render(
        display=row["display"],
        country=row["country"],
        flag=ttn_ebu_codes.flag(cc),
        airings=row["airings"],
        n_recordings=row["n_recordings"],
        top_works=json.loads(row["top_works_json"]) if row["top_works_json"] else [],
        top_performances=(json.loads(row["top_performances_json"])
                          if row["top_performances_json"] else []),
        top_ensembles=(json.loads(row["top_ensembles_json"])
                       if row["top_ensembles_json"] else []),
        built_at=_built_at(env),
    )
    return url_for("broadcaster", row["slug"]), html


def render_form(row, env=None):
    """Build one /form/{slug}/ drill-in page from a forms-table row (slug,
    airings, n_works, terms_json, top_works_json). The display name is the
    capitalized slug (form slugs ARE the canonical vocabulary names);
    other_terms lists the synonym spellings beyond the canonical one, so the
    page can state its matching honestly ('also counts: Symphonie'). Returns
    (url, html)."""
    env = env or _env()
    slug = row["slug"]
    terms = json.loads(row["terms_json"]) if row["terms_json"] else []
    other_terms = [t for t in terms if t.lower() != slug]
    template = env.get_template("form.html")
    html = template.render(
        display=slug.capitalize(),
        other_terms=other_terms,
        airings=row["airings"],
        n_works=row["n_works"],
        top_works=(json.loads(row["top_works_json"])
                   if row["top_works_json"] else []),
        built_at=_built_at(env),
    )
    return url_for("form", slug), html


def render_about(env=None):
    """Build the about page. Ships STRUCTURE only -- headings, the
    attribution sentence, a takedown-contact placeholder, and TODO(nick)
    comments marking where the maintainer's prose goes. This module never
    drafts customer-facing prose (hard boundary; see CLAUDE.md's Prose
    ownership boundary). Returns ('/about/', html)."""
    env = env or _env()
    template = env.get_template("about.html")
    html = template.render(built_at=_built_at(env))
    return "/about/", html


def render_redirect(kind, old_slug, new_slug, env=None):
    """Build a redirect stub page for a registry redirect (old slug -> new
    slug, within one namespace). kind: 'work' or 'composer' (the registry's
    two redirect namespaces). The stub page lives at the OLD url and points
    (meta refresh + rel=canonical + a plain fallback link) at the NEW url.
    Returns (old_url, html)."""
    env = env or _env()
    old_url = url_for(kind, old_slug)
    new_url = url_for(kind, new_slug)
    template = env.get_template("redirect.html")
    html = template.render(new_url=new_url, built_at=_built_at(env))
    return old_url, html


# --- sitemap / robots / Atom feed (non-HTML outputs) ---------------------------

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_SITEMAP_KINDS = ("works", "composers", "episodes", "performances", "misc")


def _absolute(base_url, url):
    """Join a relative url_for()-produced path onto base_url. base_url is
    used verbatim minus a trailing slash; url always starts with '/'."""
    return base_url.rstrip("/") + url


def _sitemap_urlset(urls):
    """Render one <urlset> chunk (XML declaration + sitemaps.org namespace,
    one <url><loc> per absolute url, sorted for determinism)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<urlset xmlns="{_SITEMAP_NS}">',
    ]
    for loc in sorted(urls):
        lines.append(f"  <url><loc>{_xml_escape(loc)}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def build_sitemaps(urls_by_kind, base_url=BASE_URL):
    """Build the sitemap index + five per-entity chunk files.

    urls_by_kind: {"works": [url, ...], "composers": [...], "episodes": [...],
    "performances": [...], "misc": [...]} of RELATIVE url_for()-produced paths
    (any of the five keys may be absent/empty -- treated as no urls of that
    kind, never an error). Every url is made absolute against base_url in the
    output. sitemap.xml is a <sitemapindex> pointing at the five chunk files
    (also absolute); each chunk is a <urlset> with one <url><loc> per page --
    no <lastmod>/<priority>, since we don't have honest per-page dates and
    won't fake them. Deterministic: urls are sorted within each chunk, and
    the index lists chunks in the fixed _SITEMAP_KINDS order.

    Returns {relpath: content} for all six files: "sitemap.xml" (the index)
    plus "sitemap-{kind}.xml" for each of works/composers/episodes/
    performances/misc.
    """
    files = {}
    for kind in _SITEMAP_KINDS:
        urls = urls_by_kind.get(kind) or []
        absolute_urls = [_absolute(base_url, u) for u in urls]
        files[f"sitemap-{kind}.xml"] = _sitemap_urlset(absolute_urls)

    index_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<sitemapindex xmlns="{_SITEMAP_NS}">',
    ]
    for kind in _SITEMAP_KINDS:
        chunk_url = _absolute(base_url, f"/sitemap-{kind}.xml")
        index_lines.append(f"  <sitemap><loc>{_xml_escape(chunk_url)}</loc></sitemap>")
    index_lines.append("</sitemapindex>")
    files["sitemap.xml"] = "\n".join(index_lines) + "\n"

    return files


def build_robots(base_url=BASE_URL):
    """Build robots.txt: allow all crawlers, point at the sitemap index."""
    return (
        "User-agent: *\n"
        "Disallow:\n"
        f"Sitemap: {base_url.rstrip('/')}/sitemap.xml\n"
    )


def _feed_night_id(date10):
    """Stable Atom entry id for one broadcast date -- a tag: URI, so it does
    NOT depend on base_url and survives a future domain change."""
    return f"tag:notturnometer,2026:night/{date10}"


def _feed_night_content(episode_rows):
    """Plain-text 'Composer — Title' lines (one per track across all of the
    date's episodes, in order) as an HTML fragment for the entry <content>.
    A zero-track night (the 75 anchor episodes) still returns honest text,
    never an empty/absent content element."""
    lines = []
    for row in episode_rows:
        tracks_json = row["tracks_json"] if row["tracks_json"] else "[]"
        tracks = json.loads(tracks_json)
        for t in tracks:
            composer = t.get("composer") or ""
            title = t.get("title") or ""
            if composer:
                lines.append(f"{composer} — {title}")
            else:
                lines.append(title)
    if not lines:
        return "<p>No parseable tracklist survives for this night.</p>"
    items = "".join(f"<li>{_xml_escape(line)}</li>" for line in lines)
    return f"<ul>{items}</ul>"


def build_atom_feed(recent_dates, built_at, base_url=BASE_URL):
    """Build the Atom last-nights feed (/feed.xml).

    recent_dates: [(date10, episode_rows), ...] for the most recent ~14
    broadcast dates, NEWEST FIRST (the driver slices the corpus and decides
    how many; this builder just renders what it's given). episode_rows is
    the same shape render_episode_date/render_home take (tuple/sqlite3.Row/
    dict rows with pid, title, bbc_url, tracks_json) -- usually one row, the
    7 multi-pid dates carry more.

    One <entry> per DATE (not per episode_pid): id is a domain-independent
    tag: URI derived from the date (stable across a future domain change);
    title reuses format_date ("Through the Night — 11 July 2026"); link is
    the absolute episode-date url; updated is the broadcast date itself
    (date10 + midnight UTC) -- NOT built_at, so a rebuild doesn't re-mark
    every entry unread in a feed reader; content is an escaped HTML list of
    that night's works.

    Feed-level id is a fixed tag: URI (also domain-independent); updated is
    built_at, passed straight through -- the caller supplies an RFC3339
    string (site.sqlite's meta.built_at), this function does not parse or
    reformat it; link rel="self" is the absolute /feed.xml url, plus a plain
    <link> to base_url; author name is a generic constant.

    Returns the feed XML as a str.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        "  <id>tag:notturnometer,2026:feed</id>",
        "  <title>Notturnometer — Through the Night, last nights</title>",
        f"  <updated>{_xml_escape(built_at)}</updated>",
        f'  <link rel="self" href={_xml_quoteattr(_absolute(base_url, "/feed.xml"))}/>',
        f'  <link href={_xml_quoteattr(base_url)}/>',
        "  <author><name>Notturnometer</name></author>",
    ]
    for date10, episode_rows in recent_dates:
        entry_url = _absolute(base_url, url_for("episode", date10))
        title = f"Through the Night — {format_date(date10)}"
        content = _feed_night_content(episode_rows)
        lines.append("  <entry>")
        lines.append(f"    <id>{_xml_escape(_feed_night_id(date10))}</id>")
        lines.append(f"    <title>{_xml_escape(title)}</title>")
        lines.append(f"    <link href={_xml_quoteattr(entry_url)}/>")
        lines.append(f"    <updated>{date10}T00:00:00Z</updated>")
        lines.append(f'    <content type="html">{_xml_escape(content)}</content>')
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


# --- the full render driver ----------------------------------------------------
# render_site is the site-wide counterpart to ttn_site._run_build: a pure(ish)
# function of site.sqlite + the registry that renders every page, prunes stale
# ones, crawls for dangling internal links, and writes the non-HTML outputs +
# static/. Reached as the render half of `ttn_data.py site`.

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# The only roots prune is allowed to touch -- pagefind/, static/, and any
# root file (sitemap.xml, robots.txt, feed.xml, index.html, about/) are
# never walked or removed by prune, no matter what it finds there.
_ENTITY_ROOTS = ("work", "composer", "episode", "performance", "browse",
                 "year", "broadcaster", "form")

_HREF_RE = re.compile(r'href="([^"]+)"')


class RenderClosureError(Exception):
    """Raised by render_site when the internal-link crawl finds an href="/..."
    in some rendered page that does not resolve to a rendered page or a known
    static asset. Lists up to 20 violations (each "FROM_URL -> HREF"), plus
    the total count -- the render-time counterpart of ttn_site.check_closure.
    Raised AFTER every file is written (dist/ is a local, rebuildable
    artifact; Phase 3's deploy step is the one that must actually gate on
    this, not the render itself)."""


def _copy_if_changed(src_path, dst_path):
    """Bytes-mode counterpart to write_if_changed, for static/ assets (which
    may not be UTF-8 text, e.g. a future image/font). Skips the copy when the
    destination's bytes already match; returns True iff it wrote."""
    with open(src_path, "rb") as fh:
        new_bytes = fh.read()
    if os.path.exists(dst_path):
        with open(dst_path, "rb") as fh:
            if fh.read() == new_bytes:
                return False
    parent = os.path.dirname(dst_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst_path, "wb") as fh:
        fh.write(new_bytes)
    return True


def _prune_entity_roots(dist_dir, rendered_relpaths):
    """Walk dist_dir's entity roots (work/composer/episode/performance/browse)
    ONLY, removing any index.html not in rendered_relpaths (paths relative to
    dist_dir, forward-slash form) -- an entity page whose source row vanished
    from site.sqlite between renders. Removes now-empty directories upward,
    stopping at the entity root itself (never removes the entity root
    directory). Never touches pagefind/, static/, or any dist_dir root file.
    Returns the count of index.html files removed."""
    pruned = 0
    for root_name in _ENTITY_ROOTS:
        root_dir = os.path.join(dist_dir, root_name)
        if not os.path.isdir(root_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir, topdown=False):
            if "index.html" in filenames:
                full = os.path.join(dirpath, "index.html")
                rel = os.path.relpath(full, dist_dir).replace(os.sep, "/")
                if rel not in rendered_relpaths:
                    os.remove(full)
                    pruned += 1
            # Clean up now-empty directories, stopping at the entity root.
            if dirpath != root_dir and not os.listdir(dirpath):
                os.rmdir(dirpath)
    return pruned


def _internal_targets(html):
    """Yield (raw_href, fragment-stripped target) for every internal
    href="/..." in an HTML string, skipping externals/mailto/relative links
    and the /pagefind/ prefix (base.html emits /pagefind/*.css/js hrefs on
    every page, task 6 -- dist/pagefind/ is populated only by the post-pass;
    whitelisted by prefix rather than exact-matched, since pagefind names its
    own bundle files internally and this module must not hardcode them).
    The ONE authority for the crawl's href-parsing rules -- _crawl and
    render_site's streaming collector both consume it, so the rules can't
    drift apart."""
    for href in _HREF_RE.findall(html):
        if not href.startswith("/"):
            continue  # external / mailto / relative -- not this crawl's job
        target = href.split("#", 1)[0]
        if target.startswith("/pagefind/"):
            continue
        yield href, target


def _crawl(pages, static_relpaths, non_page_urls):
    """Scan every rendered HTML string for href="/..." internal links and
    verify each resolves to a rendered page (pages: {url: html} -- includes
    '/' and '/about/', both rendered pages already), a known static asset
    (static_relpaths, joined under /static/), or a non-page output the driver
    also writes (non_page_urls: sitemap.xml + its chunks, robots.txt,
    feed.xml). Href-parsing rules (incl. the /pagefind/ whitelist) live in
    _internal_targets. Returns a list of "FROM_URL -> HREF" violation strings
    (empty = pass).

    NB render_site does NOT call this (it collects hrefs page-by-page as it
    streams, holding only the small href->source map -- see the streaming
    note in render_site); _crawl stays as the same-rules convenience for
    tests and small in-memory page dicts."""
    known_urls = set(pages) | non_page_urls
    known_static = {f"/static/{rel}" for rel in static_relpaths}

    violations = []
    for from_url, html in pages.items():
        for href, target in _internal_targets(html):
            if target in known_urls or target in known_static:
                continue
            violations.append(f"{from_url} -> {href}")
    return violations


def run_pagefind(dist_dir):
    """Run the Pagefind search-index post-pass over an already-rendered
    dist_dir: `npx --yes pagefind --site <dist_dir>`. Indexes only the pages
    carrying `data-pagefind-body` (work/composer/browse templates, opted in
    at task 2) into dist_dir/pagefind/, excluding `.facts`/`table`/`ul.plain`
    from the indexed text so excerpts read as prose, not glued cell values.

    Search is an enhancement, not a gate (the projection-cache degrade-don't-
    abort lesson applied here): ANY failure -- npx not on PATH
    (FileNotFoundError), a non-zero exit, or a timeout -- prints a loud
    stderr warning (including the captured stderr tail, when there is one)
    and returns False. Never raises. Returns True iff pagefind exited 0.

    timeout=600s: the first invocation on a fresh machine downloads
    pagefind's own platform binary in addition to indexing."""
    # Exclude the tabular/stats guts (.facts stat lists, data tables, plain
    # performer/broadcaster lists) from indexing, so result EXCERPTS are built
    # from the prose (composer name / work title / byline) rather than glued
    # cell text -- the source has no whitespace between `<dt>Airings</dt><dd>N</dd>`
    # etc., which Pagefind otherwise indexes as "Airings3655" / "WorkAirings".
    cmd = ["npx", "--yes", "pagefind", "--site", dist_dir,
           "--exclude-selectors", ".facts, table, ul.plain"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=600)
    except FileNotFoundError as e:
        print(f"ttn_site_render: PAGEFIND SKIPPED -- npx not found ({e}); "
              f"search will be unavailable on this build. Install Node/npx "
              f"to enable it.", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print(f"ttn_site_render: PAGEFIND SKIPPED -- `npx pagefind` timed "
              f"out after 600s; search will be unavailable on this build.",
              file=sys.stderr)
        return False

    if result.returncode != 0:
        stderr_tail = (result.stderr or b"").decode("utf-8", "replace")[-2000:]
        print(f"ttn_site_render: PAGEFIND SKIPPED -- `npx pagefind` exited "
              f"{result.returncode}; search will be unavailable on this "
              f"build. stderr:\n{stderr_tail}", file=sys.stderr)
        return False

    return True


def render_site(site_db, registry_path, dist_dir, base_url=BASE_URL, pagefind=False):
    """The full render driver: render EVERY page in site_db + the registry's
    redirects, prune stale pages, crawl for dangling internal links, write
    the non-HTML outputs (sitemaps/robots/feed), copy static/, and (when
    pagefind=True) run the Pagefind search-index post-pass.

    site_db: path to a built site.sqlite (opened read-only, row_factory =
    sqlite3.Row). registry_path: path to the slug registry JSON (loaded via
    ttn_site.load_registry, for its redirects only -- the entity tables are
    already registry-authoritative). dist_dir: output directory.

    pagefind: when True, run_pagefind(dist_dir) is invoked AFTER the internal-
    link crawl passes (never index a site that failed closure) and its result
    feeds summary["pagefind"]. Default False (the fast-test / --build-only-
    adjacent path never touches npx/network) -- callers that want search
    (the real `ttn_data.py site` run) opt in explicitly.

    Iteration is deterministic throughout (every SELECT is ORDER BY its PK).

    Returns a summary dict: {pages, written, skipped, pruned, crawl_ok,
    pagefind}. pagefind is None when pagefind=False (not attempted), else the
    bool run_pagefind returned -- a pagefind failure never fails the render
    (search is an enhancement, not a gate).
    Raises RenderClosureError (after all writes, before the pagefind pass) if
    the internal-link crawl finds a dangling href="/..." -- dist/ is a local,
    rebuildable artifact, so a failed crawl still leaves dist/ on disk for
    inspection; the gate is enforced by the caller (Phase 3's deploy), not by
    refusing to write.
    """
    # Local import: ttn_site depends on this module's package neighbours
    # (ttn_project etc.) only at ITS import time, not this module's -- keep
    # ttn_site_render importable standalone (as every earlier task's tests
    # already rely on), and avoid a circular import at module load time.
    import ttn_site

    env = _env()

    conn = sqlite3.connect(f"file:{site_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # _env() is a session-lifetime singleton: restore the prior built_at on
    # exit so a render_site call can't leak this DB's stamp into later
    # standalone-builder renders (test-order coupling, task-5 review note).
    prior_built_at = env.globals.get("built_at")
    try:
        built_at_row = conn.execute(
            "SELECT value FROM meta WHERE key = 'built_at'").fetchone()
        built_at = built_at_row[0] if built_at_row else None
        env.globals["built_at"] = built_at

        registry = ttn_site.load_registry(registry_path)

        # STREAMING SHAPE (the 1 GB Pi-3 lesson, 2026-07-13): never hold the
        # rendered site in memory. Each page is rendered, written, and href-
        # scanned by _emit, then its HTML is DROPPED -- what survives the loop
        # is only the small bookkeeping (URL/relpath sets + an href->source
        # map), ~tens of MB instead of the ~400 MB the old url->html dict
        # cost, which drove the whole machine into OOM/swap-thrash alongside
        # the SQL cursors below (also streamed now, not list()-materialized:
        # the works/episodes rows carry multi-KB JSON blobs).
        written = 0
        skipped = 0
        n_pages = 0
        rendered_urls = set()
        rendered_relpaths = set()
        href_sources = {}   # target -> (first source url, raw href)

        def _emit(url, html):
            nonlocal written, skipped, n_pages
            n_pages += 1
            rendered_urls.add(url)
            path = dist_path(url, dist_dir)
            rel = os.path.relpath(path, dist_dir).replace(os.sep, "/")
            rendered_relpaths.add(rel)
            if write_if_changed(path, html):
                written += 1
            else:
                skipped += 1
            for href, target in _internal_targets(html):
                href_sources.setdefault(target, (url, href))

        # --- works ---------------------------------------------------------
        work_urls = []
        for row in conn.execute("SELECT * FROM works ORDER BY slug"):
            url, html = render_work(row, env)
            _emit(url, html)
            work_urls.append(url)

        # --- composers -------------------------------------------------------
        composer_urls = []
        for row in conn.execute("SELECT * FROM composers ORDER BY slug"):
            url, html = render_composer(row, env)
            _emit(url, html)
            composer_urls.append(url)

        # --- performances (recordings table; INNER JOIN works for
        # work_display, decision 2) -------------------------------------------
        n_recordings_total = conn.execute(
            "SELECT COUNT(*) FROM recordings").fetchone()[0]
        broadcaster_slug_of = dict(conn.execute(
            "SELECT display, slug FROM broadcasters"))
        performance_urls = []
        for row in conn.execute(
                "SELECT r.*, w.work_display, w.composer_display "
                "FROM recordings r JOIN works w ON r.work_slug = w.slug "
                "ORDER BY r.recording_pid"):
            url, html = render_performance(
                row, env, work_display=row["work_display"],
                composer_display=row["composer_display"],
                broadcaster_slug_of=broadcaster_slug_of)
            _emit(url, html)
            performance_urls.append(url)
        if len(performance_urls) != n_recordings_total:
            # A raise, not an assert: this invariant must survive python -O
            # (the house rule for hard closure/drift checks). Checked after
            # the streamed loop -- same guarantee as the old pre-loop check,
            # since the raise still aborts before the summary/pagefind.
            raise RenderClosureError(
                f"render_site: recordings/works join dropped rows -- "
                f"{len(performance_urls)} joined vs {n_recordings_total} in "
                f"recordings (a recording with a NULL or dangling work_slug "
                f"is a Phase-1 closure bug, not something this driver should "
                f"paper over)")

        # --- episodes, grouped by date (decision 3) --------------------------
        # Two passes so the full rows (tracks_json is multi-KB) never sit in
        # memory all at once: a cheap date list first (for prev/next and the
        # feed window), then the real rows streamed in date order, rendering
        # each date's group as it completes. Only the last 14 dates' rows are
        # RETAINED (the Atom feed window; the last of them is also last-night
        # for the home page).
        dates_sorted = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM episodes ORDER BY date")]
        date_index = {d: i for i, d in enumerate(dates_sorted)}
        feed_window = set(dates_sorted[-14:])
        feed_rows_by_date = {}

        episode_urls = []

        def _render_date(date10, rows):
            i = date_index[date10]
            url, html = render_episode_date(
                date10, rows, env,
                prev_date=dates_sorted[i - 1] if i > 0 else None,
                next_date=dates_sorted[i + 1] if i < len(dates_sorted) - 1 else None)
            _emit(url, html)
            episode_urls.append(url)
            if date10 in feed_window:
                feed_rows_by_date[date10] = rows

        n_episodes_total = 0
        current_date, current_rows = None, []
        for row in conn.execute("SELECT * FROM episodes ORDER BY date, pid"):
            n_episodes_total += 1
            if row["date"] != current_date:
                if current_date is not None:
                    _render_date(current_date, current_rows)
                current_date, current_rows = row["date"], []
            current_rows.append(row)
        if current_date is not None:
            _render_date(current_date, current_rows)

        # --- home (decision 4) ------------------------------------------------
        # The Ensembles stat is the browse payload's whole-corpus identity
        # count (there is no ensembles TABLE -- the axis is a listing-only
        # browse page); a site.sqlite without the payload renders 0.
        ens_row = conn.execute(
            "SELECT payload_json FROM browse WHERE name = 'ensembles'").fetchone()
        n_ensembles = (json.loads(ens_row[0]).get("total", 0)
                       if ens_row and ens_row[0] else 0)
        stats = {
            "works": len(work_urls),
            "composers": len(composer_urls),
            "ensembles": n_ensembles,
            "episodes": n_episodes_total,
            "recordings": n_recordings_total,
            "date_min": dates_sorted[0] if dates_sorted else None,
            "date_max": dates_sorted[-1] if dates_sorted else None,
        }
        last_night_date = dates_sorted[-1] if dates_sorted else None
        last_night_rows = (feed_rows_by_date[last_night_date]
                           if dates_sorted else [])
        # "On this night": the same calendar night (month-day) in previous
        # years, newest first. Anchored to the corpus' latest date, not the
        # wall clock (byte-identical re-renders; Nick-approved 2026-07-17 as
        # sufficiently different from the BBC's own date-archive pages).
        on_this_night = ([d for d in reversed(dates_sorted[:-1])
                          if d[5:] == last_night_date[5:]]
                         if dates_sorted else [])
        home_url, home_html = render_home(stats, last_night_rows, env,
                                          last_night_date=last_night_date,
                                          on_this_night=on_this_night)
        _emit(home_url, home_html)

        # --- browse ------------------------------------------------------------
        browse_urls = []
        rendered_browse = {}          # payload name -> url (for the index)
        for row in conn.execute("SELECT * FROM browse ORDER BY name"):
            payload = json.loads(row["payload_json"]) if row["payload_json"] else []
            url, html = render_browse(row["name"], payload, env)
            _emit(url, html)
            browse_urls.append(url)
            rendered_browse[row["name"]] = url

        # browse landing index (/browse/) -- links the axes just rendered
        index_url, index_html = render_browse_index(rendered_browse, env)
        _emit(index_url, index_html)
        browse_urls.append(index_url)

        # --- per-year drill-in pages (/year/YYYY/) -----------------------------
        year_urls = []
        for row in conn.execute("SELECT * FROM years ORDER BY year"):
            url, html = render_year(row, env)
            _emit(url, html)
            year_urls.append(url)

        # --- per-broadcaster drill-in pages (/broadcaster/{slug}/) -------------
        broadcaster_urls = []
        for row in conn.execute("SELECT * FROM broadcasters ORDER BY slug"):
            url, html = render_broadcaster(row, env)
            _emit(url, html)
            broadcaster_urls.append(url)

        # --- per-form drill-in pages (/form/{slug}/) ----------------------------
        form_urls = []
        for row in conn.execute("SELECT * FROM forms ORDER BY slug"):
            url, html = render_form(row, env)
            _emit(url, html)
            form_urls.append(url)

        # --- about ---------------------------------------------------------
        about_url, about_html = render_about(env)
        _emit(about_url, about_html)

        # --- redirects (decision 6) --------------------------------------------
        redirect_urls = []
        for old_slug, new_slug in sorted(registry["redirects"]["works"].items()):
            url, html = render_redirect("work", old_slug, new_slug, env)
            _emit(url, html)
            redirect_urls.append(url)
        for old_slug, new_slug in sorted(registry["redirects"]["composers"].items()):
            url, html = render_redirect("composer", old_slug, new_slug, env)
            _emit(url, html)
            redirect_urls.append(url)

    finally:
        conn.close()
        env.globals["built_at"] = prior_built_at

    # --- static/ (decision 8) ----------------------------------------------
    static_relpaths = []
    if os.path.isdir(_STATIC_DIR):
        for name in sorted(os.listdir(_STATIC_DIR)):
            src = os.path.join(_STATIC_DIR, name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(dist_dir, "static", name)
            _copy_if_changed(src, dst)
            static_relpaths.append(name)

    # --- prune stale entity pages (decision 9) ------------------------------
    pruned = _prune_entity_roots(dist_dir, rendered_relpaths)

    # --- non-HTML outputs (decision 7) --------------------------------------
    urls_by_kind = {
        "works": work_urls,
        "composers": composer_urls,
        "episodes": episode_urls,
        "performances": performance_urls,
        "misc": ([home_url, about_url, "/feed.xml"]
                 + browse_urls + year_urls + broadcaster_urls + form_urls
                 + redirect_urls),
    }
    sitemap_files = build_sitemaps(urls_by_kind, base_url=base_url)
    for name, content in sitemap_files.items():
        write_if_changed(os.path.join(dist_dir, name), content)

    robots_content = build_robots(base_url=base_url)
    write_if_changed(os.path.join(dist_dir, "robots.txt"), robots_content)

    # Atom feed: 14 most recent broadcast dates, newest first (decision 7).
    recent_dates = [(date10, feed_rows_by_date[date10])
                    for date10 in reversed(dates_sorted[-14:])]
    # `built_at` is the LOCAL captured inside the try block -- the env global
    # has already been restored by the finally, deliberately.
    feed_content = build_atom_feed(recent_dates, built_at or "", base_url=base_url)
    write_if_changed(os.path.join(dist_dir, "feed.xml"), feed_content)

    # --- internal-link crawl check (decision 10, streaming form) ------------
    # The hrefs were collected page-by-page by _emit (rules: _internal_targets,
    # shared with _crawl); here we just resolve the deduplicated target set.
    # One violation per unique dangling TARGET (first source page named) --
    # the old whole-site _crawl reported every occurrence; the streaming form
    # can't, and one-per-target is the more readable worklist anyway.
    # sitemap_files keys are bare filenames ("sitemap.xml", ...); everything
    # else here is already a proper "/..." path.
    non_page_urls = {f"/{name}" for name in sitemap_files} | {"/robots.txt", "/feed.xml"}
    known_urls = rendered_urls | non_page_urls
    known_static = {f"/static/{rel}" for rel in static_relpaths}
    violations = [
        f"{src} -> {href}"
        for target, (src, href) in sorted(href_sources.items())
        if target not in known_urls and target not in known_static
    ]
    crawl_ok = not violations

    if violations:
        shown = violations[:20]
        raise RenderClosureError(
            f"render_site: internal-link crawl failed "
            f"({len(violations)} dangling href(s)): " + "; ".join(shown)
            + (f" ... ({len(violations) - 20} more)" if len(violations) > 20 else ""))

    # --- pagefind search post-pass (task 6) ---------------------------------
    # Only reached once the crawl has passed (never index a site that failed
    # closure). pagefind=False (the default) leaves this None -- "not
    # attempted", distinct from a run that was attempted and failed.
    pagefind_ok = run_pagefind(dist_dir) if pagefind else None

    return {
        "pages": n_pages,
        "written": written,
        "skipped": skipped,
        "pruned": pruned,
        "crawl_ok": crawl_ok,
        "pagefind": pagefind_ok,
    }
