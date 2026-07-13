"""Site renderer (website Phase 2): turns site.sqlite into the static dist/
tree. ttn_site.py builds the substrate (site.sqlite + slug registry); this
module renders it. Reached as `ttn_data.py site` (render stage).

This module holds the pure core (the URL authority url_for, the dist-path
mapping dist_path, and the write-if-changed file writer) plus the per-page
context builders (render_work / render_composer / render_recording /
render_episode_date / render_home / render_browse / render_about /
render_redirect) and the Jinja2 Environment that renders templates/*.html
into page HTML. The site-wide driver (iterating every row and writing
dist/) lands in a later task.
"""
import datetime
import json
import os

import jinja2

import ttn_ebu_codes

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

_ROLE_ORDER = ("Composer", "Conductor", "Orchestra", "Ensemble", "Performer",
               "Singer", "Choir")

_env_singleton = None

# render_browse's `name` -> (URL segment via browse_url_name, template file).
# The DB's browse.name PK uses 'top_works' (ttn_site.build_browse_payloads);
# the URL/customer-facing name is 'works' (see the URL contract in the Phase
# 2 preamble: /browse/works/, not /browse/top-works/) -- so both spellings
# are accepted here, and both resolve to the same URL/template.
_BROWSE_TEMPLATES = {
    "works": "browse_works.html",
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
        built_at=None,
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
        built_at=None,
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
        built_at=None,
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
        built_at=None,
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
        built_at=None,
    )
    return "/", html


def render_browse(name, payload, env=None):
    """Build one browse page. name: the browse axis, either the DB's
    browse.name PK ('top_works', 'house_recordings', 'years',
    'broadcasters') or the URL-facing spelling ('works' for 'top_works') --
    both are accepted and resolve to the same page. payload: the list of
    dicts from browse.payload_json (ttn_site.build_browse_payloads' shapes).
    Unknown name -> ValueError (never silently render an empty/wrong page).
    Returns (url, html)."""
    env = env or _env()
    template_name = _BROWSE_TEMPLATES.get(name)
    if template_name is None:
        raise ValueError(f"render_browse: unknown browse name {name!r}; "
                         f"known: {sorted(set(_BROWSE_TEMPLATES) - {'top_works'})}")

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
    html = template.render(rows=rows, built_at=None)
    return url, html


def render_about(env=None):
    """Build the about page. Ships STRUCTURE only -- headings, the
    attribution sentence, a takedown-contact placeholder, and TODO(nick)
    comments marking where the maintainer's prose goes. This module never
    drafts customer-facing prose (hard boundary; see CLAUDE.md's Prose
    ownership boundary). Returns ('/about/', html)."""
    env = env or _env()
    template = env.get_template("about.html")
    html = template.render(built_at=None)
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
    html = template.render(new_url=new_url, built_at=None)
    return old_url, html
