"""Site renderer (website Phase 2): turns site.sqlite into the static dist/
tree. ttn_site.py builds the substrate (site.sqlite + slug registry); this
module renders it. Reached as `ttn_data.py site` (render stage).

This module holds the pure core (the URL authority url_for, the dist-path
mapping dist_path, and the write-if-changed file writer) plus the per-page
context builders (render_work / render_composer / render_recording) and the
Jinja2 Environment that renders templates/*.html into page HTML. The
site-wide driver (iterating every row and writing dist/) lands in a later
task.
"""
import json
import os

import jinja2

import ttn_ebu_codes

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

_ROLE_ORDER = ("Composer", "Conductor", "Orchestra", "Ensemble", "Performer",
               "Singer", "Choir")

_env_singleton = None


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
