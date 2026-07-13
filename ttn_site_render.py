"""Site renderer (website Phase 2): turns site.sqlite into the static dist/
tree. ttn_site.py builds the substrate (site.sqlite + slug registry); this
module renders it. Reached as `ttn_data.py site` (render stage).

This module holds the pure core (the URL authority url_for, the dist-path
mapping dist_path, and the write-if-changed file writer) plus the per-page
context builders (render_work / render_composer / render_recording /
render_episode_date / render_home / render_browse / render_about /
render_redirect), the Jinja2 Environment that renders templates/*.html into
page HTML, the non-HTML builders (build_sitemaps / build_robots /
build_atom_feed), and the site-wide driver render_site that ties everything
together: load site.sqlite + the registry, render every page, prune stale
ones, crawl for dangling internal links, and write the non-HTML outputs +
static/.
"""
import datetime
import json
import os
import re
import sqlite3
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
# broadcasters/house_recordings) -- the canonical input is what the table
# stores. The URL-facing spelling ('works' for 'top_works', see the URL
# contract in the Phase 2 preamble: /browse/works/, not /browse/top-works/)
# is a rendering detail handled internally via browse_url_name; it is NOT
# an accepted alias for `name` (narrowed in task 5 -- the Task-3 reviewer
# note: canonical input = what the table stores, the URL mapping stays
# internal).
_BROWSE_TEMPLATES = {
    "top_works": "browse_works.html",
    "house_recordings": "browse_house_recordings.html",
    "years": "browse_years.html",
    "broadcasters": "browse_broadcasters.html",
}


def url_for(kind: str, key: str) -> str:
    """The single URL authority — every template link goes through this, no
    hand-built hrefs anywhere.

    kind in {"work", "composer", "episode", "recording", "browse"}; ValueError
    on anything else.

    - "work": split on the FIRST ':' -> /work/{composer_part}/{work_part}/.
      A colon-less slug (the hash-fallback class, e.g. 'wbd926ff4') ->
      /work/{slug}/. A collision suffix ('abel:trio-in-f-major-for-2') flows
      through the same first-colon split.
    - "episode": key is an ISO date 'YYYY-MM-DD' -> /episode/YYYY/MM/DD/.
    - "composer" / "recording": key is used verbatim -> /{kind}/{key}/.
    - "browse": key is the URL name (hyphenated) -> /browse/{key}/. Callers
      holding a payload name (underscore-separated, e.g. 'house_recordings')
      must map it first via browse_url_name.
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
    if kind == "recording":
        return f"/recording/{key}/"
    if kind == "browse":
        return f"/browse/{key}/"
    raise ValueError(f"url_for: unknown kind {kind!r}")


def browse_url_name(payload_name: str) -> str:
    """Map a browse payload name (underscore-separated, as stored in
    browse.name) to the URL segment (hyphenated) that url_for("browse", ...)
    expects. 'house_recordings' -> 'house-recordings'; 'works' -> 'works'."""
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
    Returns (url, html)."""
    env = env or _env()
    works = json.loads(row["works_json"]) if row["works_json"] else []

    slug = row["slug"]
    url = url_for("composer", slug)
    template = env.get_template("composer.html")
    html = template.render(
        display=row["display"],
        airings=row["airings"],
        n_works=row["n_works"],
        works=works,
        built_at=_built_at(env),
    )
    return url, html


def render_recording(row, env=None, *, work_display, composer_display=None):
    """Build the recording page. row: the recordings-table tuple/sqlite3.Row
    (recording_pid, work_slug, composer_slug, duration, broadcaster,
    airings, first_aired, last_aired, contributors_json, airing_dates_json).

    The recordings table carries only slugs, not display titles, so
    `work_display` is a REQUIRED keyword-only argument: the caller (the
    site-wide driver) must join against works and pass the work's display
    title. A default-with-fallback here would silently ship ~18.9k recording
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

    rp = row["recording_pid"]
    if composer_display is None:
        composer_display = ", ".join(by_role.get("Composer", [])) or None

    url = url_for("recording", rp)
    template = env.get_template("recording.html")
    html = template.render(
        recording_pid=rp,
        work_slug=row["work_slug"],
        work_display=work_display,
        composer_slug=row["composer_slug"],
        composer_display=composer_display,
        duration_display=format_duration(row["duration"]),
        broadcaster_display=broadcaster_display,
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


def render_home(stats, last_night, env=None):
    """Build the home page. stats: dict {works, composers, episodes,
    recordings, date_min, date_max} (the driver derives these from table
    counts). last_night: the most recent date's episode_rows, in the SAME
    shape render_episode_date takes (tuple/sqlite3.Row/dict rows with pid,
    title, bbc_url, tracks_json) -- rendered via the shared _playlist.html
    macro so the home and episode playlists never diverge. Returns
    ("/", html)."""
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
        built_at=_built_at(env),
    )
    return "/", html


def render_browse(name, payload, env=None):
    """Build one browse page. name: the browse axis, EXACTLY the DB's
    browse.name PK ('top_works', 'house_recordings', 'years',
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

    url_name = browse_url_name("works" if name == "top_works" else name)
    url = url_for("browse", url_name)

    rows = payload
    if name == "broadcasters":
        rows = []
        for b in payload:
            b = dict(b)
            b["display_name"] = ttn_ebu_codes.decode(b.get("key"))[0] or b.get("key")
            rows.append(b)

    template = env.get_template(template_name)
    html = template.render(rows=rows, built_at=_built_at(env))
    return url, html


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
_SITEMAP_KINDS = ("works", "composers", "episodes", "recordings", "misc")


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
    "recordings": [...], "misc": [...]} of RELATIVE url_for()-produced paths
    (any of the five keys may be absent/empty -- treated as no urls of that
    kind, never an error). Every url is made absolute against base_url in the
    output. sitemap.xml is a <sitemapindex> pointing at the five chunk files
    (also absolute); each chunk is a <urlset> with one <url><loc> per page --
    no <lastmod>/<priority>, since we don't have honest per-page dates and
    won't fake them. Deterministic: urls are sorted within each chunk, and
    the index lists chunks in the fixed _SITEMAP_KINDS order.

    Returns {relpath: content} for all six files: "sitemap.xml" (the index)
    plus "sitemap-{kind}.xml" for each of works/composers/episodes/
    recordings/misc.
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
_ENTITY_ROOTS = ("work", "composer", "episode", "recording", "browse")

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
    """Walk dist_dir's entity roots (work/composer/episode/recording/browse)
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


def _crawl(pages, static_relpaths, non_page_urls):
    """Scan every rendered HTML string for href="/..." internal links and
    verify each resolves to a rendered page (pages: {url: html} -- includes
    '/' and '/about/', both rendered pages already), a known static asset
    (static_relpaths, joined under /static/), or a non-page output the
    driver also writes (non_page_urls: sitemap.xml + its chunks, robots.txt,
    feed.xml). Returns a list of "FROM_URL -> HREF" violation strings
    (empty = pass)."""
    known_urls = set(pages) | non_page_urls
    known_static = {f"/static/{rel}" for rel in static_relpaths}

    violations = []
    for from_url, html in pages.items():
        for href in _HREF_RE.findall(html):
            if not href.startswith("/"):
                continue  # external / mailto / relative -- not this crawl's job
            target = href.split("#", 1)[0]
            if target in known_urls or target in known_static:
                continue
            violations.append(f"{from_url} -> {href}")
    return violations


def render_site(site_db, registry_path, dist_dir, base_url=BASE_URL):
    """The full render driver: render EVERY page in site_db + the registry's
    redirects, prune stale pages, crawl for dangling internal links, write
    the non-HTML outputs (sitemaps/robots/feed) and copy static/.

    site_db: path to a built site.sqlite (opened read-only, row_factory =
    sqlite3.Row). registry_path: path to the slug registry JSON (loaded via
    ttn_site.load_registry, for its redirects only -- the entity tables are
    already registry-authoritative). dist_dir: output directory.

    Iteration is deterministic throughout (every SELECT is ORDER BY its PK).

    Returns a summary dict: {pages, written, skipped, pruned, crawl_ok}.
    Raises RenderClosureError (after all writes) if the internal-link crawl
    finds a dangling href="/..." -- dist/ is a local, rebuildable artifact,
    so a failed crawl still leaves dist/ on disk for inspection; the gate is
    enforced by the caller (Phase 3's deploy), not by refusing to write.
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

        pages = {}   # url -> html, EVERY rendered page (for the crawl)

        # --- works ---------------------------------------------------------
        work_rows = list(conn.execute("SELECT * FROM works ORDER BY slug"))
        work_urls = []
        for row in work_rows:
            url, html = render_work(row, env)
            pages[url] = html
            work_urls.append(url)

        # --- composers -------------------------------------------------------
        composer_rows = list(conn.execute("SELECT * FROM composers ORDER BY slug"))
        composer_urls = []
        for row in composer_rows:
            url, html = render_composer(row, env)
            pages[url] = html
            composer_urls.append(url)

        # --- recordings (INNER JOIN works for work_display; decision 2) -----
        rec_rows = list(conn.execute(
            "SELECT r.*, w.work_display, w.composer_display "
            "FROM recordings r JOIN works w ON r.work_slug = w.slug "
            "ORDER BY r.recording_pid"))
        n_recordings_total = conn.execute(
            "SELECT COUNT(*) FROM recordings").fetchone()[0]
        if len(rec_rows) != n_recordings_total:
            # A raise, not an assert: this invariant must survive python -O
            # (the house rule for hard closure/drift checks).
            raise RenderClosureError(
                f"render_site: recordings/works join dropped rows -- "
                f"{len(rec_rows)} joined vs {n_recordings_total} in recordings "
                f"(a recording with a NULL or dangling work_slug is a Phase-1 "
                f"closure bug, not something this driver should paper over)")
        recording_urls = []
        for row in rec_rows:
            url, html = render_recording(
                row, env, work_display=row["work_display"],
                composer_display=row["composer_display"])
            pages[url] = html
            recording_urls.append(url)

        # --- episodes, grouped by date (decision 3) --------------------------
        episode_rows = list(conn.execute(
            "SELECT * FROM episodes ORDER BY date, pid"))
        by_date = {}
        for row in episode_rows:
            by_date.setdefault(row["date"], []).append(row)
        dates_sorted = sorted(by_date)

        episode_urls = []
        for i, date10 in enumerate(dates_sorted):
            prev_date = dates_sorted[i - 1] if i > 0 else None
            next_date = dates_sorted[i + 1] if i < len(dates_sorted) - 1 else None
            url, html = render_episode_date(
                date10, by_date[date10], env,
                prev_date=prev_date, next_date=next_date)
            pages[url] = html
            episode_urls.append(url)

        # --- home (decision 4) ------------------------------------------------
        stats = {
            "works": len(work_rows),
            "composers": len(composer_rows),
            "episodes": len(episode_rows),
            "recordings": n_recordings_total,
            "date_min": dates_sorted[0] if dates_sorted else None,
            "date_max": dates_sorted[-1] if dates_sorted else None,
        }
        last_night_rows = by_date[dates_sorted[-1]] if dates_sorted else []
        home_url, home_html = render_home(stats, last_night_rows, env)
        pages[home_url] = home_html

        # --- browse ------------------------------------------------------------
        browse_rows = list(conn.execute("SELECT * FROM browse ORDER BY name"))
        browse_urls = []
        for row in browse_rows:
            payload = json.loads(row["payload_json"]) if row["payload_json"] else []
            url, html = render_browse(row["name"], payload, env)
            pages[url] = html
            browse_urls.append(url)

        # --- about ---------------------------------------------------------
        about_url, about_html = render_about(env)
        pages[about_url] = about_html

        # --- redirects (decision 6) --------------------------------------------
        redirect_urls = []
        for old_slug, new_slug in sorted(registry["redirects"]["works"].items()):
            url, html = render_redirect("work", old_slug, new_slug, env)
            pages[url] = html
            redirect_urls.append(url)
        for old_slug, new_slug in sorted(registry["redirects"]["composers"].items()):
            url, html = render_redirect("composer", old_slug, new_slug, env)
            pages[url] = html
            redirect_urls.append(url)

    finally:
        conn.close()
        env.globals["built_at"] = prior_built_at

    # --- write every HTML page, write-if-changed --------------------------
    written = 0
    skipped = 0
    rendered_relpaths = set()
    for url, html in pages.items():
        path = dist_path(url, dist_dir)
        rel = os.path.relpath(path, dist_dir).replace(os.sep, "/")
        rendered_relpaths.add(rel)
        if write_if_changed(path, html):
            written += 1
        else:
            skipped += 1

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
        "recordings": recording_urls,
        "misc": [home_url, about_url, "/feed.xml"] + browse_urls + redirect_urls,
    }
    sitemap_files = build_sitemaps(urls_by_kind, base_url=base_url)
    for name, content in sitemap_files.items():
        write_if_changed(os.path.join(dist_dir, name), content)

    robots_content = build_robots(base_url=base_url)
    write_if_changed(os.path.join(dist_dir, "robots.txt"), robots_content)

    # Atom feed: 14 most recent broadcast dates, newest first (decision 7).
    recent_dates = [(date10, by_date[date10]) for date10 in reversed(dates_sorted[-14:])]
    # `built_at` is the LOCAL captured inside the try block -- the env global
    # has already been restored by the finally, deliberately.
    feed_content = build_atom_feed(recent_dates, built_at or "", base_url=base_url)
    write_if_changed(os.path.join(dist_dir, "feed.xml"), feed_content)

    # --- internal-link crawl (decision 10) ----------------------------------
    # sitemap_files keys are bare filenames ("sitemap.xml", ...); everything
    # else here is already a proper "/..." path.
    non_page_urls = {f"/{name}" for name in sitemap_files} | {"/robots.txt", "/feed.xml"}
    violations = _crawl(pages, static_relpaths, non_page_urls)
    crawl_ok = not violations

    summary = {
        "pages": len(pages),
        "written": written,
        "skipped": skipped,
        "pruned": pruned,
        "crawl_ok": crawl_ok,
    }

    if violations:
        shown = violations[:20]
        raise RenderClosureError(
            f"render_site: internal-link crawl failed "
            f"({len(violations)} dangling href(s)): " + "; ".join(shown)
            + (f" ... ({len(violations) - 20} more)" if len(violations) > 20 else ""))

    return summary
