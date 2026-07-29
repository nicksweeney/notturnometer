"""The search-catalogue builder: site.sqlite -> the client-side search index.

Replaces Pagefind. Pagefind scored term frequency over page text, which on this
site is structurally wrong: a composer page's whole indexable body is its name
(twenty characters), so a page merely *containing* 'Chopin' four times scored
188 against the Frédéric Chopin page's 40, and no Pagefind knob could demote it
(see docs/superpowers/specs/2026-07-29-search-replacement-design.md for the
measured scores). Here the ranking is a function we own: per-kind priors and a
log-scaled airings prior, applied in static/search.js over these documents.

Document keys are short because there are ~31k of them:
    k  kind ('work', 'composer', 'artist', 'episode', 'broadcaster',
            'country', 'form', 'year', 'browse')
    n  primary display name (searched, boost 3)
    s  secondary text -- work's composer, artist's roles, episode's subtitle
       (searched, boost 1.5; absent on kinds that have none)
    a  alias field: ascii_fold(n) plus alias-table spellings, '|'-joined
       (searched, boost 2)
    u  URL -- STORED, never derived in JS. url_for is the single URL authority
       and a JS reimplementation would be a second one free to diverge (the
       work-slug ':'->'/' split alone is a trap). The strings gzip nearly free
       against their shared prefixes.
    w  airings -- the document prior. int always, 0 where the kind has none,
       so boostDocument needs no guard.
    x  pre-rendered facts line for the result row (absent where s suffices)

This module is render-side: it is NOT part of the site.sqlite substrate
fingerprint, so changes here ship on `ttn_data.py site --render-only`.
"""
import json
import os
import re

from ttn_analyze import ascii_fold
from ttn_site_render import browse_url_name, format_date, url_for


def _fold(*parts):
    """The alias field: ascii-folded, lowercased, '|'-joined, de-duplicated,
    empties dropped. Order-stable so the output is byte-reproducible."""
    seen, out = set(), []
    for p in parts:
        v = ascii_fold(p or "").lower().strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return "|".join(out)


def _facts(*pairs):
    """'118 works · 2,266 airings' from (count, singular) pairs, skipping
    zero/None counts. Thousands-separated, matching the site's number style."""
    bits = []
    for n, noun in pairs:
        if n:
            bits.append(f"{n:,} {noun}" if n != 1 else f"1 {noun.rstrip('s')}")
    return " · ".join(bits)


# site.sqlite's episodes.title column holds the SUBTITLE (ttn_site.py
# _EPISODE_META_SQL: COALESCE(NULLIF(subtitle, ''), title)). Three classes carry
# no information and are dropped before a document is made:
#
#   _DATE_SHAPED  the pre-2014 convention wrote the broadcast date as the
#                 subtitle ('30/11/2009') -- 2,085 rows. It is noise, and it
#                 would collide with the date recogniser in search.js.
#   _NULL_SUBTITLE  the uniform programme title repeated (10 rows). Indexing
#                 it would return thousands of identical rows for the query
#                 'through the night'.
#   _TITLE_PLUS_DATE  the programme title repeated with the broadcast date
#                 appended ('Through the Night 28/09/2008') -- 10 rows from the
#                 2008 floor era. Neither _DATE_SHAPED (anchored, so the prefix
#                 defeats it) nor the _NULL_SUBTITLE equality check catches this,
#                 but it is the same zero-information noise both of those exist
#                 to remove.
_DATE_SHAPED = re.compile(r"^\s*\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\s*$")
_NULL_SUBTITLE = "through the night"
_TITLE_PLUS_DATE = re.compile(
    r"^through the night[\s,:-]*\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\s*$", re.I)


def _useful_subtitle(text):
    """The subtitle if it carries editorial information, else None."""
    t = (text or "").strip()
    if not t or _DATE_SHAPED.match(t) or t.lower() == _NULL_SUBTITLE or _TITLE_PLUS_DATE.match(t):
        return None
    return t


def _episode_docs(conn):
    """One document per DATE, not per pid.

    url_for('episode', date10) groups a night's pids onto a single
    /episode/YYYY/MM/DD/ page (6,551 rows over 6,541 dates -- ~7 dates carry
    2-3 pids), so per-pid documents would put two competing results in front
    of the reader for one page. Subtitles of one date join with ' · ',
    de-duplicated because the multi-pid rows of a night often repeat it.

    A date whose every subtitle is junk gets NO document: it stays reachable
    by 'On this night', by browsing, and by the date recogniser."""
    by_date = {}
    for date10, title in conn.execute(
            "SELECT date, title FROM episodes ORDER BY date, pid"):
        text = _useful_subtitle(title)
        if not date10 or not text:
            continue
        subs = by_date.setdefault(date10, [])
        if text not in subs:
            subs.append(text)

    docs = []
    for date10, subs in sorted(by_date.items()):
        joined = " · ".join(subs)
        docs.append({
            "k": "episode", "n": format_date(date10), "s": joined,
            "a": _fold(joined, date10), "u": url_for("episode", date10),
            "w": 0,
        })
    return docs


def build_catalogue(conn):
    """site.sqlite connection -> the list of search documents.

    Read-only. No filesystem, no network -- fully testable against a synthetic
    in-memory DB. Kind coverage and exclusions are specified in the design doc;
    `recordings` is deliberately absent (a performance page duplicates its
    work's title and composer, so indexing 20k of them yields near-duplicate
    noise beside the work itself)."""
    docs = []

    # NB the column is work_display, NOT display -- `works` is the one table
    # that prefixes it (ttn_site.py _SITE_SCHEMA).
    for slug, display, comp_display, airings in conn.execute(
            "SELECT slug, work_display, composer_display, airings FROM works"):
        docs.append({
            "k": "work", "n": display, "s": comp_display or "",
            "a": _fold(display), "u": url_for("work", slug),
            "w": airings or 0,
        })

    for slug, display, airings, n_works in conn.execute(
            "SELECT slug, display, airings, n_works FROM composers"):
        docs.append({
            "k": "composer", "n": display, "a": _fold(display),
            "u": url_for("composer", slug), "w": airings or 0,
            "x": _facts((n_works, "works"), (airings, "airings")),
        })

    for slug, display, kind, airings, n_recs in conn.execute(
            "SELECT slug, display, kind, airings, n_recordings FROM artists"):
        docs.append({
            "k": "artist", "n": display, "s": kind or "",
            "a": _fold(display), "u": url_for("artist", slug),
            "w": airings or 0,
            "x": _facts((n_recs, "performances"), (airings, "airings")),
        })

    for slug, display, country, airings in conn.execute(
            "SELECT slug, display, country, airings FROM broadcasters"):
        docs.append({
            "k": "broadcaster", "n": display, "s": country or "",
            "a": _fold(display, country), "u": url_for("broadcaster", slug),
            "w": airings or 0, "x": _facts((airings, "airings")),
        })

    for slug, country, airings in conn.execute(
            "SELECT slug, country, airings FROM countries"):
        docs.append({
            "k": "country", "n": country, "a": _fold(country),
            "u": url_for("country", slug), "w": airings or 0,
            "x": _facts((airings, "airings")),
        })

    for slug, airings, n_works in conn.execute(
            "SELECT slug, airings, n_works FROM forms"):
        display = slug.replace("-", " ").capitalize()
        docs.append({
            "k": "form", "n": display, "a": _fold(display, slug),
            "u": url_for("form", slug), "w": airings or 0,
            "x": _facts((n_works, "works"), (airings, "airings")),
        })

    for year, airings in conn.execute("SELECT year, airings FROM years"):
        docs.append({
            "k": "year", "n": year, "a": _fold(year),
            "u": url_for("year", year), "w": airings or 0,
            "x": _facts((airings, "airings")),
        })

    # browse.name is the underscore payload name ('house_performances');
    # url_for("browse", ...) wants the hyphenated URL segment. browse_url_name
    # is the documented mapping -- don't inline the replace, it's an authority.
    for (name,) in conn.execute("SELECT name FROM browse"):
        display = name.replace("_", " ").capitalize()
        docs.append({
            "k": "browse", "n": display, "a": _fold(display, name),
            "u": url_for("browse", browse_url_name(name)), "w": 0,
        })

    docs.extend(_episode_docs(conn))

    return docs


CATALOGUE_FILENAME = "search-index.json"


def write_catalogue(conn, dist_dir):
    """Serialise build_catalogue to dist_dir/search-index.json. Returns the
    document count (for the render summary).

    Atomic (tmp + os.replace), matching every other derived artefact in this
    project. Output is byte-reproducible for an unchanged catalogue --
    separators are pinned and ensure_ascii=False keeps the payload small and
    the diff readable, so an unchanged build writes identical bytes and the
    nightly rsync ships nothing."""
    docs = build_catalogue(conn)
    payload = json.dumps(docs, ensure_ascii=False, separators=(",", ":"))
    path = os.path.join(dist_dir, CATALOGUE_FILENAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    os.replace(tmp, path)
    return len(docs)
