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
from ttn_analyze import ascii_fold
from ttn_site_render import browse_url_name, url_for


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

    return docs
