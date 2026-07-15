"""Tests for ttn_site_render: URL authority + dist path mapping +
write-if-changed (website Phase 2, task 1); page builders + templates
(website Phase 2, task 2); episode/home/browse/about/redirect page builders
(website Phase 2, task 3); sitemap index + robots.txt + Atom last-nights
feed (website Phase 2, task 4).

Run: uv run --with pytest pytest test_ttn_site_render.py
"""
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET

import pytest

from ttn_site_render import (url_for, dist_path, write_if_changed, browse_url_name,
                              render_work, render_composer, render_recording,
                              render_episode_date, render_home, render_browse,
                              render_browse_index, render_year,
                              render_about, render_redirect, format_date,
                              format_clock, _env,
                              build_sitemaps, build_robots, build_atom_feed,
                              render_site, RenderClosureError,
                              run_pagefind,
                              BASE_URL)


def test_url_for_work_colon_becomes_slash():
    assert url_for("work", "williams:lark-ascending") == "/work/williams/lark-ascending/"


def test_url_for_work_hash_fallback_no_colon():
    assert url_for("work", "wbd926ff4") == "/work/wbd926ff4/"


def test_url_for_work_collision_suffix_flows_through():
    assert url_for("work", "abel:trio-in-f-major-for-2") == "/work/abel/trio-in-f-major-for-2/"


def test_url_for_composer_episode_recording_browse():
    assert url_for("composer", "ralph-vaughan-williams") == "/composer/ralph-vaughan-williams/"
    assert url_for("episode", "2026-07-11") == "/episode/2026/07/11/"
    assert url_for("recording", "p0fhfv23") == "/recording/p0fhfv23/"
    assert url_for("browse", "house-recordings") == "/browse/house-recordings/"
    assert url_for("browse", "") == "/browse/"          # landing index
    assert url_for("year", "2026") == "/year/2026/"


def test_url_for_unknown_kind_raises():
    with pytest.raises(ValueError):
        url_for("bogus", "whatever")


def test_browse_url_name_underscore_to_hyphen():
    assert browse_url_name("house_recordings") == "house-recordings"
    assert browse_url_name("works") == "works"


def test_dist_path_mirrors_url():
    assert dist_path("/work/williams/lark-ascending/", "dist") \
        == "dist/work/williams/lark-ascending/index.html"


def test_dist_path_root():
    assert dist_path("/", "dist") == "dist/index.html"


def test_write_if_changed_skips_identical(tmp_path):
    p = tmp_path / "a" / "index.html"
    assert write_if_changed(str(p), "x") is True      # wrote (created dirs)
    m = p.stat().st_mtime_ns
    assert write_if_changed(str(p), "x") is False     # identical -> skipped
    assert p.stat().st_mtime_ns == m
    assert write_if_changed(str(p), "y") is True      # changed -> rewrote


def test_write_if_changed_writes_utf8_verbatim(tmp_path):
    p = tmp_path / "b" / "index.html"
    write_if_changed(str(p), "héllo")
    assert p.read_bytes() == "héllo".encode("utf-8")


# --- fixture builders --------------------------------------------------------

def _work_facets(recordings=None, top_performers=None, top_conductors=None,
                  top_ensembles=None, by_year=None, broadcasters=None):
    return json.dumps({
        "recordings": recordings or [],
        "top_performers": top_performers or [],
        "top_conductors": top_conductors or [],
        "top_ensembles": top_ensembles or [],
        "by_year": by_year or [],
        "broadcasters": broadcasters or [],
    })


def _make_site_db(path, *, works=None, composers=None, episodes=None,
                   recordings=None, browse=None):
    import ttn_site
    tables = {}
    if works is not None:
        tables["works"] = works
    if composers is not None:
        tables["composers"] = composers
    if episodes is not None:
        tables["episodes"] = episodes
    if recordings is not None:
        tables["recordings"] = recordings
    if browse is not None:
        tables["browse"] = browse
    ttn_site.write_site_db(str(path), tables, "fp-test")
    return str(path)


def _row(conn, table, pk_col, pk_val):
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f"SELECT * FROM {table} WHERE {pk_col} = ?", (pk_val,))
    return cur.fetchone()


# --- render_work --------------------------------------------------------------

def test_render_work_has_composer_link_recording_links_broadcaster_decoded_and_by_year(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets(
        recordings=[{
            "recording_pid": "p0000001", "duration": 1800, "airing_count": 4,
            "first": "2012-04-01", "last": "2026-01-01",
            "conductors": ["Simon Rattle"], "ensembles": ["Berlin Phil"],
            "soloists": [],
        }],
        top_performers=[{"identity": "x", "display_name": "Someone", "mbid": None,
                          "airings": 2, "recordings": 1}],
        top_conductors=[{"identity": "y", "display_name": "Simon Rattle", "mbid": None,
                          "airings": 4, "recordings": 1}],
        top_ensembles=[{"identity": "z", "display_name": "Berlin Phil", "mbid": None,
                         "airings": 4, "recordings": 1}],
        by_year=[{"year": "2020", "airings": 2, "works": 1, "composers": 1,
                   "date_min": "2020-01-01", "date_max": "2020-06-01"}],
        broadcasters=[{"key": "GBBBC", "airings": 4, "recordings": 1}],
    )
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 100,
              4, 10, "2010-01-17", "2026-06-01", facets)]
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "beethoven:symphony-5")
    conn.close()

    url, html = render_work(row)

    assert url == url_for("work", "beethoven:symphony-5")
    assert 'href="/composer/beethoven/"' in html
    assert 'href="/recording/p0000001/"' in html
    assert "SRF (German)" not in html  # sanity: wrong-code decode isn't leaking
    assert "BBC" in html               # GBBBC decoded display name
    assert "2020" in html              # by_year row rendered
    assert "30:00" in html             # 1800s duration formatted M:SS
    assert "Op.67" in html
    assert "n_text_only" not in html   # never leak raw field names as text


def test_render_work_null_composer_slug_renders_plain_text_no_link(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets()
    works = [("orphan-work", None, "", "orphan-work-key",
              "Orphan Work", "", None, 3, 0, 3, "2020-01-01", "2020-01-01", facets)]
    _make_site_db(db_path, works=works, composers=[])

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "orphan-work")
    conn.close()

    url, html = render_work(row)
    assert "/composer/" not in html
    # No anchor should wrap a composer reference at all since composer_slug is None
    assert not re.search(r'<a[^>]*href="/composer/', html)


def test_render_work_escapes_html_in_title(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets()
    nasty = 'Quartet "Lark" & <Friends>'
    works = [("lark-work", "haydn", "haydn", "lark-key",
              nasty, "Joseph Haydn", None, 1, 0, 1,
              "2020-01-01", "2020-01-01", facets)]
    composers = [("haydn", "haydn", "Joseph Haydn", 1, 1, "[]")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "lark-work")
    conn.close()

    url, html = render_work(row)
    assert nasty not in html
    assert "&amp;" in html
    assert "&lt;Friends&gt;" in html
    assert "&quot;Lark&quot;" in html or "&#34;Lark&#34;" in html


def test_render_work_text_only_disclosure_line(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets()
    works = [("some-work", "haydn", "haydn", "some-key",
              "Some Work", "Joseph Haydn", None, 5, 2, 3,
              "2010-01-17", "2020-01-01", facets)]
    composers = [("haydn", "haydn", "Joseph Haydn", 5, 1, "[]")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "some-work")
    conn.close()

    url, html = render_work(row)
    assert "3" in html
    assert "predate the recording-linked era" in html


def test_render_work_data_pagefind_body_present(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets()
    works = [("w1", "c1", "c1", "wk1", "Work One", "Composer One", None,
              1, 0, 1, "2020-01-01", "2020-01-01", facets)]
    composers = [("c1", "c1", "Composer One", 1, 1, "[]")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "w1")
    conn.close()

    url, html = render_work(row)
    assert 'data-pagefind-body' in html


# --- render_composer -----------------------------------------------------------

def test_render_composer_lists_ranked_works_as_links(tmp_path):
    db_path = tmp_path / "site.sqlite"
    works_json = json.dumps([
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5", "airings": 100},
        {"slug": "beethoven:symphony-9", "display": "Symphony No 9", "airings": 80},
    ])
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 180, 2, works_json)]
    _make_site_db(db_path, works=[], composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "composers", "slug", "beethoven")
    conn.close()

    url, html = render_composer(row)
    assert url == url_for("composer", "beethoven")
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/work/beethoven/symphony-9/"' in html
    assert "Symphony No 5" in html
    assert "Symphony No 9" in html
    assert "180" in html
    assert 'data-pagefind-body' in html


def test_render_composer_escapes_display_name(tmp_path):
    db_path = tmp_path / "site.sqlite"
    composers = [("nasty", "nasty", 'A & <B>', 1, 0, "[]")]
    _make_site_db(db_path, works=[], composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "composers", "slug", "nasty")
    conn.close()

    url, html = render_composer(row)
    assert "A & <B>" not in html
    assert "&amp;" in html
    assert "&lt;B&gt;" in html


# --- render_recording -----------------------------------------------------------

def test_render_recording_role_grouping_episode_links_and_duration(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([
        {"role": "Composer", "name": "Ludwig van Beethoven"},
        {"role": "Conductor", "name": "Simon Rattle"},
        {"role": "Orchestra", "name": "Berlin Philharmonic"},
        {"role": "Performer", "name": "Someone Soloist"},
    ])
    airing_dates = json.dumps([["2012-04-01", "b0000001"], ["2020-06-01", "b0000002"]])
    recordings = [("p0000001", "beethoven:symphony-5", "beethoven", 1800,
                    "BBC", 2, "2012-04-01", "2020-06-01", contributors, airing_dates)]
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 100,
              4, 10, "2010-01-17", "2026-06-01", _work_facets())]
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]")]
    _make_site_db(db_path, works=works, composers=composers, recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "p0000001")
    conn.close()

    url, html = render_recording(row, work_display="Symphony No 5")
    assert url == url_for("recording", "p0000001")
    assert "Symphony No 5" in html
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/composer/beethoven/"' in html
    assert 'href="/episode/2012/04/01/"' in html
    assert 'href="/episode/2020/06/01/"' in html
    assert "30:00" in html
    assert "Simon Rattle" in html
    assert "Berlin Philharmonic" in html
    assert "Someone Soloist" in html
    # role order preserved: Composer before Conductor before Orchestra before Performer
    ci = html.index("Ludwig van Beethoven")
    coi = html.index("Simon Rattle")
    oi = html.index("Berlin Philharmonic")
    pi_ = html.index("Someone Soloist")
    assert ci < coi < oi < pi_


def test_render_recording_null_work_and_composer_slug_renders_plain_text(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([{"role": "Composer", "name": "Anon"}])
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    recordings = [("pXXXXXXX", None, None, 120,
                    None, 1, "2020-01-01", "2020-01-01", contributors, airing_dates)]
    _make_site_db(db_path, works=[], composers=[], recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "pXXXXXXX")
    conn.close()

    url, html = render_recording(row, work_display="Some Work")
    assert not re.search(r'<a[^>]*href="/work/', html)
    assert not re.search(r'<a[^>]*href="/composer/', html)
    assert "2:00" in html


def test_render_recording_no_data_pagefind_body(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([{"role": "Composer", "name": "Anon"}])
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    recordings = [("pYYYYYYY", None, None, 60,
                    None, 1, "2020-01-01", "2020-01-01", contributors, airing_dates)]
    _make_site_db(db_path, works=[], composers=[], recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "pYYYYYYY")
    conn.close()

    url, html = render_recording(row, work_display="Some Work")
    assert 'data-pagefind-body' not in html


def test_render_recording_work_display_is_required():
    # The driver must join works and pass work_display; forgetting the join
    # must fail loudly (TypeError), never silently title ~18.9k pages with pids.
    with pytest.raises(TypeError):
        render_recording({"recording_pid": "p0000001"})


def test_render_recording_escapes_hostile_work_display(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([{"role": "Composer", "name": "Joseph Haydn"}])
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    recordings = [("pZZZZZZZ", None, None, 300,
                    None, 1, "2020-01-01", "2020-01-01", contributors, airing_dates)]
    _make_site_db(db_path, works=[], composers=[], recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "pZZZZZZZ")
    conn.close()

    nasty = 'Quartet "Lark" & <Friends>'
    url, html = render_recording(row, work_display=nasty)
    assert nasty not in html
    assert "&amp;" in html
    assert "&lt;Friends&gt;" in html
    assert "&quot;Lark&quot;" in html or "&#34;Lark&#34;" in html


def test_render_recording_unknown_role_renders_after_known_roles(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([
        {"role": "Narrator", "name": "A Narrator"},          # unknown role, listed first
        {"role": "Choir", "name": "Some Choir"},              # last of the known order
        {"role": "Conductor", "name": "Simon Rattle"},
    ])
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    recordings = [("pWWWWWWW", None, None, 600,
                    None, 1, "2020-01-01", "2020-01-01", contributors, airing_dates)]
    _make_site_db(db_path, works=[], composers=[], recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "pWWWWWWW")
    conn.close()

    url, html = render_recording(row, work_display="Some Work")
    # the unknown-role contributor is not dropped...
    assert "Narrator" in html
    assert "A Narrator" in html
    # ...and renders AFTER every known role, despite being first in the JSON
    assert html.index("Simon Rattle") < html.index("A Narrator")
    assert html.index("Some Choir") < html.index("A Narrator")


# --- href-shape sanity across all three page kinds ---------------------------

_HREF_RE = re.compile(r'href="(/[^"]*)"')

def _valid_href(href):
    if href == "/":
        return True
    for pattern in (
        r'^/work/[^/]+/[^/]+/$', r'^/work/[^/]+/$',
        r'^/composer/[^/]+/$', r'^/recording/[^/]+/$',
        r'^/episode/\d{4}/\d{2}/\d{2}/$', r'^/browse/[^/]+/$', r'^/browse/$',
        r'^/static/.+$', r'^/about/$', r'^/pagefind/.+$',
    ):
        if re.match(pattern, href):
            return True
    return False


def test_all_internal_hrefs_match_url_for_shapes(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([
        {"role": "Composer", "name": "Ludwig van Beethoven"},
        {"role": "Conductor", "name": "Simon Rattle"},
    ])
    airing_dates = json.dumps([["2012-04-01", "b0000001"]])
    recordings = [("p0000001", "beethoven:symphony-5", "beethoven", 1800,
                    "BBC", 1, "2012-04-01", "2012-04-01", contributors, airing_dates)]
    facets = _work_facets(recordings=[{
        "recording_pid": "p0000001", "duration": 1800, "airing_count": 1,
        "first": "2012-04-01", "last": "2012-04-01",
        "conductors": ["Simon Rattle"], "ensembles": [], "soloists": [],
    }])
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 1,
              1, 0, "2012-04-01", "2012-04-01", facets)]
    works_json = json.dumps([
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5", "airings": 1},
    ])
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 1, 1, works_json)]
    _make_site_db(db_path, works=works, composers=composers, recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    work_row = conn.execute("SELECT * FROM works WHERE slug=?",
                             ("beethoven:symphony-5",)).fetchone()
    composer_row = conn.execute("SELECT * FROM composers WHERE slug=?",
                                 ("beethoven",)).fetchone()
    rec_row = conn.execute("SELECT * FROM recordings WHERE recording_pid=?",
                            ("p0000001",)).fetchone()
    conn.close()

    renders = (
        (work_row, lambda r: render_work(r)),
        (composer_row, lambda r: render_composer(r)),
        (rec_row, lambda r: render_recording(r, work_display="Symphony No 5")),
    )
    for row, render_fn in renders:
        _url, html = render_fn(row)
        for href in _HREF_RE.findall(html):
            assert _valid_href(href), f"unexpected href shape: {href!r}"


# --- url_for negative test (Task-1 reviewer minor a) --------------------------

def test_url_for_episode_garbage_date_fails_loudly():
    with pytest.raises(ValueError):
        url_for("episode", "garbage")


# --- work slug only-first-colon split (Task-1 reviewer minor b) --------------

def test_url_for_work_only_first_colon_splits():
    assert url_for("work", "a:b:c") == "/work/a/b:c/"


# --- format_date --------------------------------------------------------------

def test_format_date_human_readable():
    assert format_date("2026-07-11") == "11 July 2026"


def test_format_date_single_digit_day_no_leading_zero():
    assert format_date("2026-07-01") == "1 July 2026"


# --- format_clock ---------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("12:31 AM", "12.31am"),      # canonical BBC form, just after midnight
    ("1:05 AM", "1.05am"),
    ("4:48 AM", "4.48am"),
    ("1.29am", "1.29am"),         # dot + attached am
    ("01:00 BST", "1.00am"),      # timezone suffix, no meridiem -> overnight am
    ("12.31", "12.31am"),         # dot separator, no meridiem
    ("02:46:AM", "2.46am"),       # stray colon before meridiem
    ("00:31", "12.31am"),         # 24-hour midnight-thirty
    ("13:00", "1.00pm"),          # 24-hour source converts
    ("5:59 AM BST", "5.59am"),    # meridiem + tz suffix
])
def test_format_clock_variants(src, expected):
    assert format_clock(src) == expected


def test_format_clock_unparseable_returns_unchanged():
    assert format_clock("b. 1966") == "b. 1966"
    assert format_clock("") == ""
    assert format_clock(None) is None


# --- render_episode_date --------------------------------------------------------

def _episode_row(pid, date, title, tracks):
    return {
        "pid": pid,
        "date": date,
        "title": title,
        "bbc_url": f"https://www.bbc.co.uk/programmes/{pid}",
        "tracks_json": json.dumps(tracks),
    }


def test_render_episode_date_multi_pid_renders_both_sections_and_playlists():
    tracks_a = [{"pos": 0, "time": "01:00 AM", "work_slug": "beethoven:symphony-5",
                 "composer_slug": "beethoven", "composer": "Ludwig van Beethoven",
                 "title": "Symphony No 5", "performers": "Berlin Phil",
                 "recording_pid": "p0000001"}]
    tracks_b = [{"pos": 0, "time": "01:45 AM", "work_slug": None,
                 "composer_slug": None, "composer": "Trad",
                 "title": "Some Folk Tune", "performers": "Someone",
                 "recording_pid": None}]
    rows = [
        _episode_row("m00113tp", "2021-10-31", "Music for the Hours", tracks_a),
        _episode_row("m00113tv", "2021-10-31", "Music for the Hours (2)", tracks_b),
    ]
    url, html = render_episode_date("2021-10-31", rows, _env())
    assert url == url_for("episode", "2021-10-31")
    assert 'id="m00113tp"' in html
    assert 'id="m00113tv"' in html
    assert 'href="https://www.bbc.co.uk/programmes/m00113tp"' in html
    assert 'href="https://www.bbc.co.uk/programmes/m00113tv"' in html
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/composer/beethoven/"' in html
    assert 'href="/recording/p0000001/"' in html
    assert "Some Folk Tune" in html
    assert "11 July 2026" not in html  # sanity: not leaking an unrelated date


def test_render_episode_date_zero_track_honest_message():
    rows = [_episode_row("b0anchor1", "2008-07-15", "Through the Night", [])]
    url, html = render_episode_date("2008-07-15", rows, _env())
    assert "No parseable tracklist survives for this night." in html


def test_render_episode_date_null_slug_renders_text_not_link():
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Anon",
               "title": "Untitled Fragment", "performers": "Someone",
               "recording_pid": None}]
    rows = [_episode_row("b0anon001", "2015-03-01", "Through the Night", tracks)]
    url, html = render_episode_date("2015-03-01", rows, _env())
    assert "Untitled Fragment" in html
    assert not re.search(r'<a[^>]*href="/work/', html)
    assert not re.search(r'<a[^>]*href="/composer/', html)
    assert not re.search(r'<a[^>]*href="/recording/', html)


def test_render_episode_date_recording_link_only_when_rp_present():
    tracks = [
        {"pos": 0, "time": "01:00 AM", "work_slug": "haydn:symphony-100",
         "composer_slug": "haydn", "composer": "Joseph Haydn",
         "title": "Symphony No 100", "performers": "LSO", "recording_pid": "p0000009"},
        {"pos": 1, "time": "01:30 AM", "work_slug": "haydn:symphony-101",
         "composer_slug": "haydn", "composer": "Joseph Haydn",
         "title": "Symphony No 101", "performers": "LSO", "recording_pid": None},
    ]
    rows = [_episode_row("b0hay0001", "2016-02-02", "Through the Night", tracks)]
    url, html = render_episode_date("2016-02-02", rows, _env())
    assert 'href="/recording/p0000009/"' in html
    assert html.count('href="/recording/') == 1


def test_render_episode_date_prev_next_present_when_supplied():
    rows = [_episode_row("b0abc0001", "2016-02-02", "Through the Night", [])]
    url, html = render_episode_date("2016-02-02", rows, _env(),
                                     prev_date="2016-02-01", next_date="2016-02-03")
    assert 'href="/episode/2016/02/01/"' in html
    assert 'href="/episode/2016/02/03/"' in html


def test_render_episode_date_prev_next_absent_when_none():
    rows = [_episode_row("b0abc0002", "2016-02-02", "Through the Night", [])]
    url, html = render_episode_date("2016-02-02", rows, _env())
    assert 'href="/episode/2016/02/01/"' not in html
    assert 'href="/episode/2016/02/03/"' not in html


def test_render_episode_date_h1_shows_human_date():
    rows = [_episode_row("b0abc0003", "2026-07-11", "Through the Night", [])]
    url, html = render_episode_date("2026-07-11", rows, _env())
    assert "11 July 2026" in html
    assert "<title>" in html and "2026-07-11" in html  # ISO stays in <title>


def test_render_episode_date_escapes_hostile_title():
    nasty = 'Special "Night" & <Extra>'
    rows = [_episode_row("b0nasty01", "2016-02-02", nasty, [])]
    url, html = render_episode_date("2016-02-02", rows, _env())
    assert nasty not in html
    assert "&amp;" in html
    assert "&lt;Extra&gt;" in html


# --- render_home ----------------------------------------------------------------

def test_render_home_reuses_playlist_partial_structure():
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": "beethoven:symphony-5",
               "composer_slug": "beethoven", "composer": "Ludwig van Beethoven",
               "title": "Symphony No 5", "performers": "Berlin Phil",
               "recording_pid": "p0000001"}]
    last_night_rows = [_episode_row("b0lastnt1", "2026-07-11", "Through the Night", tracks)]
    stats = {"works": 20721, "composers": 3557, "episodes": 6509,
              "recordings": 18885, "date_min": "2008-07-02", "date_max": "2026-07-11"}
    url, html = render_home(stats, last_night_rows, _env())
    assert url == "/"
    assert "20721" in html or "20,721" in html
    assert "3557" in html or "3,557" in html
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/browse/works/"' in html
    assert 'href="/browse/house-recordings/"' in html
    assert 'href="/browse/years/"' in html
    assert 'href="/browse/broadcasters/"' in html


def test_render_home_shows_last_night_date_linked_to_episode():
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Trad", "title": "A Tune",
               "performers": "Someone", "recording_pid": None}]
    rows = [_episode_row("b0lastnt1", "2026-07-11", "Through the Night", tracks)]
    stats = {"works": 1, "composers": 1, "episodes": 1, "recordings": 0,
             "date_min": "2026-07-11", "date_max": "2026-07-11"}
    _url, html = render_home(stats, rows, _env(), last_night_date="2026-07-11")
    assert "11 July 2026" in html
    assert 'href="/episode/2026/07/11/"' in html


def test_render_home_no_date_line_when_last_night_date_none():
    stats = {"works": 0, "composers": 0, "episodes": 0, "recordings": 0,
             "date_min": None, "date_max": None}
    _url, html = render_home(stats, [], _env(), last_night_date=None)
    assert "last-night-date" not in html


def test_render_home_and_episode_share_playlist_table_structure():
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Trad",
               "title": "A Tune", "performers": "Someone", "recording_pid": None}]
    rows = [_episode_row("b0shared01", "2026-07-11", "Through the Night", tracks)]
    _url1, home_html = render_home(
        {"works": 1, "composers": 1, "episodes": 1, "recordings": 0,
         "date_min": "2026-07-11", "date_max": "2026-07-11"},
        rows, _env())
    _url2, episode_html = render_episode_date("2026-07-11", rows, _env())
    # Both pages render a playlist table with the same header row structure --
    # the shared partial contract (extracted into templates/_playlist.html).
    header_re = re.compile(r"<thead>.*?</thead>", re.S)
    home_header = header_re.search(home_html)
    ep_header = header_re.search(episode_html)
    assert home_header and ep_header
    assert home_header.group(0) == ep_header.group(0)


# --- render_browse ---------------------------------------------------------------

def test_render_browse_top_works_rows_link_work_and_composer():
    payload = [
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "airings": 100},
    ]
    url, html = render_browse("top_works", payload, _env())
    assert url == url_for("browse", "works")
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/composer/beethoven/"' in html
    assert "100" in html


def test_render_browse_composers_rows_link_composer_pages():
    payload = [
        {"slug": "chopin", "display": "Frédéric Chopin", "airings": 3655,
         "n_works": 280},
        {"slug": "mozart", "display": "Wolfgang Amadeus Mozart", "airings": 3000,
         "n_works": 400},
    ]
    url, html = render_browse("composers", payload, _env())
    assert url == url_for("browse", "composers")
    assert 'href="/composer/chopin/"' in html
    assert 'href="/composer/mozart/"' in html
    assert "3655" in html and "280" in html


def test_render_browse_index_lists_rendered_axes_in_order():
    rendered = {
        "top_works": "/browse/works/",
        "composers": "/browse/composers/",
        "years": "/browse/years/",
        "broadcasters": "/browse/broadcasters/",
        "house_recordings": "/browse/house-recordings/",
    }
    url, html = render_browse_index(rendered, _env())
    assert url == "/browse/"
    # canonical order: Works, Composers, House recordings, Years, Broadcasters
    order = [html.index(u) for u in
             ["/browse/works/", "/browse/composers/", "/browse/house-recordings/",
              "/browse/years/", "/browse/broadcasters/"]]
    assert order == sorted(order)
    assert ">Composers<" in html


def test_render_browse_index_omits_unrendered_axis():
    # defensive: an axis absent from rendered_browse is not linked (never dangles)
    _url, html = render_browse_index({"top_works": "/browse/works/"}, _env())
    assert "/browse/works/" in html
    assert "/browse/composers/" not in html


def test_render_year_lists_top_works_and_composers():
    row = {
        "year": "2020", "airings": 42, "n_works": 30, "n_composers": 20,
        "top_works_json": json.dumps([
            {"slug": "beethoven:symphony-5", "display": "Symphony No 5",
             "composer_display": "Ludwig van Beethoven",
             "composer_slug": "beethoven", "airings": 5}]),
        "top_composers_json": json.dumps([
            {"slug": "beethoven", "display": "Ludwig van Beethoven",
             "airings": 12}]),
    }
    url, html = render_year(row, _env())
    assert url == "/year/2020/"
    assert "<h1>2020</h1>" in html
    assert "42" in html and "30" in html and "20" in html
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/composer/beethoven/"' in html


def test_render_browse_works_alias_no_longer_accepted():
    # Task-3 reviewer note, adopted in Task 5: render_browse is narrowed to
    # the DB's own browse.name PK values only -- 'works' (the old URL-facing
    # alias) is no longer accepted, 'top_works' is the one spelling.
    with pytest.raises(ValueError):
        render_browse("works", [], _env())


def test_render_browse_house_recordings_shows_share_and_roster():
    payload = [
        {"work_slug": "beethoven:symphony-5", "work_display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "recording_pid": "p0000001", "rec_airings": 6, "total_2016": 8,
         "share_pct": 75, "conductors": ["Simon Rattle"],
         "ensembles": ["Berlin Phil"], "soloists": []},
    ]
    url, html = render_browse("house_recordings", payload, _env())
    assert url == url_for("browse", "house-recordings")
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/recording/p0000001/"' in html
    assert "75" in html
    assert "6" in html and "8" in html
    assert "Simon Rattle" in html
    assert "Berlin Phil" in html


def test_render_browse_years_chronological_columns():
    payload = [
        {"year": "2014", "airings": 100, "works": 50, "composers": 30,
         "date_min": "2014-01-03", "date_max": "2014-12-30"},
        {"year": "2015", "airings": 110, "works": 55, "composers": 32,
         "date_min": "2015-01-01", "date_max": "2015-12-31"},
    ]
    url, html = render_browse("years", payload, _env())
    assert url == url_for("browse", "years")
    assert html.index("2014") < html.index("2015")
    assert "100" in html and "50" in html and "30" in html


def test_render_browse_broadcasters_decodes_ebu_code():
    payload = [{"key": "GBBBC", "airings": 500, "recordings": 300}]
    url, html = render_browse("broadcasters", payload, _env())
    assert url == url_for("browse", "broadcasters")
    assert "BBC" in html
    assert "500" in html


def test_render_browse_unknown_name_raises():
    with pytest.raises(ValueError):
        render_browse("bogus", [], _env())


# --- render_about ------------------------------------------------------------------

def test_render_about_has_todo_markers_and_no_drafted_prose():
    url, html = render_about(_env())
    assert url == "/about/"
    assert "TODO(nick)" in html
    # Structure only: section headings present, no long drafted paragraphs.
    assert "<h1>" in html
    assert "What this is" in html or "what this is" in html.lower()


# --- base.html search box (task 6) --------------------------------------------

def test_base_html_carries_pagefind_snippet():
    # Any rendered page extends base.html -- use the cheapest one.
    _, html = render_about(_env())
    assert '<link rel="stylesheet" href="/pagefind/pagefind-ui.css">' in html
    assert 'id="search"' in html
    assert '/pagefind/pagefind-ui.js' in html
    assert "PagefindUI" in html


def test_base_html_pagefind_script_has_graceful_onerror():
    _, html = render_about(_env())
    # The bundle only exists after the post-pass; a missing bundle must not
    # break the page -- some onerror/graceful-degradation mechanism is present.
    assert "onerror" in html


# --- render_redirect ---------------------------------------------------------------

def test_render_redirect_work_meta_refresh_canonical_and_fallback():
    old_url, html = render_redirect("work", "old-slug", "new-slug", _env())
    new_url = url_for("work", "new-slug")
    assert old_url == url_for("work", "old-slug")
    assert f'content="0; url={new_url}"' in html
    assert f'href="{new_url}"' in html
    assert 'rel="canonical"' in html


def test_render_redirect_composer():
    old_url, html = render_redirect("composer", "old-composer", "new-composer", _env())
    new_url = url_for("composer", "new-composer")
    assert old_url == url_for("composer", "old-composer")
    assert f'content="0; url={new_url}"' in html
    assert f'href="{new_url}"' in html


# --- build_sitemaps ------------------------------------------------------------

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _sample_urls_by_kind():
    return {
        "works": ["/work/beethoven/symphony-5/", "/work/haydn/symphony-100/"],
        "composers": ["/composer/beethoven/", "/composer/haydn/"],
        "episodes": ["/episode/2026/07/11/"],
        "recordings": ["/recording/p0000001/"],
        "misc": ["/", "/about/", "/browse/works/", "/feed.xml"],
    }


def test_build_sitemaps_returns_six_files():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    assert set(files) == {
        "sitemap.xml", "sitemap-works.xml", "sitemap-composers.xml",
        "sitemap-episodes.xml", "sitemap-recordings.xml", "sitemap-misc.xml",
    }


def test_build_sitemaps_index_references_five_chunks_absolute():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    root = ET.fromstring(files["sitemap.xml"])
    assert root.tag == f"{_SITEMAP_NS}sitemapindex"
    locs = [el.text for el in root.iter(f"{_SITEMAP_NS}loc")]
    assert sorted(locs) == sorted(
        f"https://example.invalid/sitemap-{chunk}.xml"
        for chunk in ("works", "composers", "episodes", "recordings", "misc")
    )


def test_build_sitemaps_chunk_is_urlset_with_absolute_urls():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    root = ET.fromstring(files["sitemap-works.xml"])
    assert root.tag == f"{_SITEMAP_NS}urlset"
    locs = [el.text for el in root.iter(f"{_SITEMAP_NS}loc")]
    assert locs == sorted([
        "https://example.invalid/work/beethoven/symphony-5/",
        "https://example.invalid/work/haydn/symphony-100/",
    ])


def test_build_sitemaps_misc_chunk_carries_home_and_feed():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    root = ET.fromstring(files["sitemap-misc.xml"])
    locs = {el.text for el in root.iter(f"{_SITEMAP_NS}loc")}
    assert "https://example.invalid/" in locs
    assert "https://example.invalid/feed.xml" in locs


def test_build_sitemaps_deterministic_same_input_same_bytes():
    urls = _sample_urls_by_kind()
    files1 = build_sitemaps(urls, "https://example.invalid")
    files2 = build_sitemaps(urls, "https://example.invalid")
    assert files1 == files2


def test_build_sitemaps_no_lastmod_or_priority():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    for content in files.values():
        assert "<lastmod>" not in content
        assert "<priority>" not in content


def test_build_sitemaps_xml_declaration_present():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    for content in files.values():
        assert content.startswith("<?xml version=")


def test_build_sitemaps_default_base_url_is_module_constant():
    files = build_sitemaps(_sample_urls_by_kind(), BASE_URL)
    root = ET.fromstring(files["sitemap-composers.xml"])
    locs = [el.text for el in root.iter(f"{_SITEMAP_NS}loc")]
    assert all(loc.startswith(BASE_URL) for loc in locs)


# --- build_robots ----------------------------------------------------------------

def test_build_robots_allows_all_and_points_at_sitemap():
    txt = build_robots("https://example.invalid")
    assert "User-agent: *" in txt
    assert "Disallow:" in txt
    # Allow-all: Disallow line must be empty (no path after it on the same line)
    disallow_line = [l for l in txt.splitlines() if l.startswith("Disallow:")][0]
    assert disallow_line.strip() == "Disallow:"
    assert "Sitemap: https://example.invalid/sitemap.xml" in txt


def test_build_robots_uses_default_base_url():
    txt = build_robots()
    assert f"Sitemap: {BASE_URL}/sitemap.xml" in txt


# --- build_atom_feed ---------------------------------------------------------------

def _feed_recent_dates():
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": "beethoven:symphony-5",
               "composer_slug": "beethoven", "composer": "Ludwig van Beethoven",
               "title": "Symphony No 5", "performers": "Berlin Phil",
               "recording_pid": "p0000001"}]
    rows_a = [_episode_row("b0abc0001", "2026-07-11", "Through the Night", tracks)]
    rows_b = [_episode_row("b0abc0002", "2026-07-10", "Through the Night", [])]
    return [("2026-07-11", rows_a), ("2026-07-10", rows_b)]


def test_build_atom_feed_well_formed_and_required_elements():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    assert root.tag == f"{_ATOM_NS}feed"
    assert root.find(f"{_ATOM_NS}id") is not None
    assert root.find(f"{_ATOM_NS}title") is not None
    assert root.find(f"{_ATOM_NS}updated") is not None
    entries = root.findall(f"{_ATOM_NS}entry")
    assert len(entries) == 2
    for entry in entries:
        assert entry.find(f"{_ATOM_NS}id") is not None
        assert entry.find(f"{_ATOM_NS}title") is not None
        assert entry.find(f"{_ATOM_NS}updated") is not None
        link = entry.find(f"{_ATOM_NS}link")
        assert link is not None
        assert link.get("href")
        content = entry.find(f"{_ATOM_NS}content")
        assert content is not None
        assert content.get("type") == "html"


def test_build_atom_feed_entry_ids_are_domain_independent():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    entries = root.findall(f"{_ATOM_NS}entry")
    ids = [e.find(f"{_ATOM_NS}id").text for e in entries]
    assert "tag:notturnometer,2026:night/2026-07-11" in ids
    assert "tag:notturnometer,2026:night/2026-07-10" in ids
    for id_ in ids:
        assert "example.invalid" not in id_

    # Rebuild against a DIFFERENT base_url -- ids must be unchanged.
    xml_text2 = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                 "https://other-domain.test")
    root2 = ET.fromstring(xml_text2)
    ids2 = [e.find(f"{_ATOM_NS}id").text for e in root2.findall(f"{_ATOM_NS}entry")]
    assert ids2 == ids


def test_build_atom_feed_entry_link_is_absolute_episode_url():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    entries = root.findall(f"{_ATOM_NS}entry")
    links = {e.find(f"{_ATOM_NS}link").get("href") for e in entries}
    assert "https://example.invalid/episode/2026/07/11/" in links
    assert "https://example.invalid/episode/2026/07/10/" in links


def test_build_atom_feed_entry_updated_is_broadcast_date_not_built_at():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    entries = root.findall(f"{_ATOM_NS}entry")
    updated_values = {e.find(f"{_ATOM_NS}updated").text for e in entries}
    assert "2026-07-11T00:00:00Z" in updated_values
    assert "2026-07-10T00:00:00Z" in updated_values
    # built_at must never appear as an entry-level updated value
    assert "2026-07-12T09:00:00Z" not in updated_values


def test_build_atom_feed_level_updated_is_built_at():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    assert root.find(f"{_ATOM_NS}updated").text == "2026-07-12T09:00:00Z"


def test_build_atom_feed_title_uses_format_date():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    entries = root.findall(f"{_ATOM_NS}entry")
    titles = {e.find(f"{_ATOM_NS}title").text for e in entries}
    assert any("11 July 2026" in t for t in titles)
    assert any("10 July 2026" in t for t in titles)


def test_build_atom_feed_content_lists_works_as_composer_title_lines():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    entries = root.findall(f"{_ATOM_NS}entry")
    content_by_date = {}
    for e in entries:
        eid = e.find(f"{_ATOM_NS}id").text
        content_by_date[eid] = e.find(f"{_ATOM_NS}content").text
    night = content_by_date["tag:notturnometer,2026:night/2026-07-11"]
    assert "Ludwig van Beethoven" in night
    assert "Symphony No 5" in night


def test_build_atom_feed_self_link_and_alternate_link():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    links = root.findall(f"{_ATOM_NS}link")
    rels = {(l.get("rel"), l.get("href")) for l in links}
    assert ("self", "https://example.invalid/feed.xml") in rels
    assert any(href == "https://example.invalid" or href == "https://example.invalid/"
               for rel, href in rels if rel != "self")


def test_build_atom_feed_feed_id_domain_independent():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    feed_id = root.find(f"{_ATOM_NS}id").text
    assert feed_id == "tag:notturnometer,2026:feed"


def test_build_atom_feed_author_present():
    xml_text = build_atom_feed(_feed_recent_dates(), "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    author = root.find(f"{_ATOM_NS}author")
    assert author is not None
    assert author.find(f"{_ATOM_NS}name") is not None
    assert author.find(f"{_ATOM_NS}name").text


def test_build_atom_feed_deterministic_same_input_same_bytes():
    args = (_feed_recent_dates(), "2026-07-12T09:00:00Z", "https://example.invalid")
    xml1 = build_atom_feed(*args)
    xml2 = build_atom_feed(*args)
    assert xml1 == xml2


def test_build_atom_feed_escapes_hostile_title_and_content():
    # A composer/title carrying &, <, > must survive well-formed XML parsing
    # (Atom type="html" content is escaped-HTML-as-text on the wire, so ET's
    # single unescape hands back real HTML markup with the hostile text still
    # HTML-escaped *within* it -- e.g. 'A &amp; &lt;B&gt;' inside a <ul><li>).
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": 'A & <B>',
               "title": 'Quartet "Lark" & <Friends>', "performers": "Someone",
               "recording_pid": None}]
    rows = [_episode_row("b0nasty02", "2026-07-09", 'Special "Night" & <Extra>', tracks)]
    xml_text = build_atom_feed([("2026-07-09", rows)], "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)  # must not raise -- well-formed despite hostile chars
    entries = root.findall(f"{_ATOM_NS}entry")
    content = entries[0].find(f"{_ATOM_NS}content").text
    assert "A &amp; &lt;B&gt;" in content
    assert 'Quartet "Lark"' in content
    assert "&lt;Friends&gt;" in content


def test_build_atom_feed_zero_track_night_honest():
    rows = [_episode_row("b0anchor2", "2008-07-15", "Through the Night", [])]
    xml_text = build_atom_feed([("2008-07-15", rows)], "2026-07-12T09:00:00Z",
                                "https://example.invalid")
    root = ET.fromstring(xml_text)
    entries = root.findall(f"{_ATOM_NS}entry")
    assert len(entries) == 1
    content = entries[0].find(f"{_ATOM_NS}content").text
    assert content is not None


# --- render_site: the full driver (website Phase 2, task 5) ------------------


def _full_fixture(tmp_path, *, with_redirect=False, static_dir=None):
    """A small but COMPLETE site.sqlite + registry: 1 composer, 1 work, 1
    recording, 2 episode dates (one zero-track anchor), 4 browse payloads.
    Built through the real ttn_site.write_site_db + dump_registry, never a
    hand-written schema. Returns (site_db_path, registry_path)."""
    import ttn_site

    facets = _work_facets(
        recordings=[{
            "recording_pid": "p0000001", "duration": 1800, "airing_count": 1,
            "first": "2020-01-01", "last": "2020-01-01",
            "conductors": ["Simon Rattle"], "ensembles": ["Berlin Phil"],
            "soloists": [],
        }],
        broadcasters=[{"key": "GBBBC", "airings": 1, "recordings": 1}],
        by_year=[{"year": "2020", "airings": 1, "works": 1, "composers": 1,
                   "date_min": "2020-01-01", "date_max": "2020-01-01"}],
    )
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 1,
              1, 0, "2020-01-01", "2020-01-01", facets)]
    works_json = json.dumps([
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5", "airings": 1}])
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 1, 1, works_json)]

    contributors = json.dumps([
        {"role": "Composer", "name": "Ludwig van Beethoven"},
        {"role": "Conductor", "name": "Simon Rattle"},
    ])
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    recordings = [("p0000001", "beethoven:symphony-5", "beethoven", 1800,
                    "BBC", 1, "2020-01-01", "2020-01-01", contributors, airing_dates)]

    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": "beethoven:symphony-5",
               "composer_slug": "beethoven", "composer": "Ludwig van Beethoven",
               "title": "Symphony No 5", "performers": "Berlin Phil",
               "recording_pid": "p0000001"}]
    episodes = [
        ("b0000001", "2020-01-01", "Through the Night",
         "https://www.bbc.co.uk/programmes/b0000001", json.dumps(tracks)),
        ("b0anchor1", "2008-07-15", "Through the Night",
         "https://www.bbc.co.uk/programmes/b0anchor1", json.dumps([])),
    ]

    top_works = json.dumps([
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "airings": 1}])
    years = json.dumps([{"year": "2020", "airings": 1, "works": 1, "composers": 1,
                          "date_min": "2020-01-01", "date_max": "2020-01-01"}])
    broadcasters = json.dumps([{"key": "GBBBC", "airings": 1, "recordings": 1}])
    house_recordings = json.dumps([
        {"work_slug": "beethoven:symphony-5", "work_display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "recording_pid": "p0000001", "rec_airings": 1, "total_2016": 1,
         "share_pct": 100, "conductors": ["Simon Rattle"],
         "ensembles": ["Berlin Phil"], "soloists": []}])
    composers_payload = json.dumps([
        {"slug": "beethoven", "display": "Ludwig van Beethoven",
         "airings": 1, "n_works": 1}])
    browse = [
        ("top_works", top_works),
        ("composers", composers_payload),
        ("years", years),
        ("broadcasters", broadcasters),
        ("house_recordings", house_recordings),
    ]
    years_table = [
        ("2020", 1, 1, 1,
         json.dumps([{"slug": "beethoven:symphony-5", "display": "Symphony No 5",
                      "composer_display": "Ludwig van Beethoven",
                      "composer_slug": "beethoven", "airings": 1}]),
         json.dumps([{"slug": "beethoven", "display": "Ludwig van Beethoven",
                      "airings": 1}])),
    ]

    site_db = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(site_db), {
        "works": works, "composers": composers, "episodes": episodes,
        "recordings": recordings, "browse": browse, "years": years_table,
    }, "fp-render-site-test")

    registry = ttn_site._empty_registry()
    registry["works"]["beethoven:symphony-5"] = {
        "composer_key": "beethoven", "work_key": "symphony-5", "published": "2020-01-01"}
    registry["composers"]["beethoven"] = {
        "composer_key": "beethoven", "published": "2020-01-01"}
    if with_redirect:
        registry["redirects"]["works"]["old-beethoven-5"] = "beethoven:symphony-5"
        registry["redirects"]["composers"]["old-beethoven"] = "beethoven"
    registry_path = tmp_path / "registry.json"
    ttn_site.dump_registry(registry, str(registry_path))

    return str(site_db), str(registry_path)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_render_site_renders_every_page_kind(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    summary = render_site(site_db, registry, str(dist))

    assert summary["crawl_ok"] is True
    # 1 work + 1 composer + 2 episode dates + 1 recording + 5 browse + browse
    # index + 1 year page + home + about
    assert summary["pages"] == 1 + 1 + 2 + 1 + 5 + 1 + 1 + 1 + 1
    assert summary["written"] == summary["pages"]
    assert summary["skipped"] == 0
    assert summary["pruned"] == 0

    assert (dist / "work" / "beethoven" / "symphony-5" / "index.html").exists()
    assert (dist / "composer" / "beethoven" / "index.html").exists()
    assert (dist / "recording" / "p0000001" / "index.html").exists()
    assert (dist / "episode" / "2020" / "01" / "01" / "index.html").exists()
    assert (dist / "episode" / "2008" / "07" / "15" / "index.html").exists()
    assert (dist / "browse" / "works" / "index.html").exists()
    assert (dist / "browse" / "composers" / "index.html").exists()
    assert (dist / "browse" / "house-recordings" / "index.html").exists()
    assert (dist / "browse" / "years" / "index.html").exists()
    assert (dist / "browse" / "broadcasters" / "index.html").exists()
    assert (dist / "browse" / "index.html").exists()          # /browse/ landing
    assert (dist / "year" / "2020" / "index.html").exists()   # per-year drill-in
    assert (dist / "index.html").exists()
    assert (dist / "about" / "index.html").exists()
    assert (dist / "static" / "style.css").exists()
    assert (dist / "sitemap.xml").exists()
    assert (dist / "robots.txt").exists()
    assert (dist / "feed.xml").exists()


def test_render_site_recording_page_gets_work_display_via_join(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    render_site(site_db, registry, str(dist))
    html = _read(dist / "recording" / "p0000001" / "index.html")
    assert "Symphony No 5" in html


def test_render_site_redirects_render_when_registry_has_them(tmp_path):
    site_db, registry = _full_fixture(tmp_path, with_redirect=True)
    dist = tmp_path / "dist"
    summary = render_site(site_db, registry, str(dist))
    assert (dist / "work" / "old-beethoven-5" / "index.html").exists()
    assert (dist / "composer" / "old-beethoven" / "index.html").exists()
    # +2 redirect pages over the no-redirect fixture's page count
    assert summary["pages"] == 1 + 1 + 2 + 1 + 5 + 1 + 1 + 1 + 1 + 2


def test_render_site_rerender_unchanged_writes_zero(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    render_site(site_db, registry, str(dist))
    summary2 = render_site(site_db, registry, str(dist))
    assert summary2["written"] == 0
    assert summary2["skipped"] == summary2["pages"]


def test_render_site_mtime_pinned_file_untouched_on_rerender(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    render_site(site_db, registry, str(dist))
    p = dist / "composer" / "beethoven" / "index.html"
    mtime_before = p.stat().st_mtime_ns
    render_site(site_db, registry, str(dist))
    assert p.stat().st_mtime_ns == mtime_before


def _fixture_without_beethoven(tmp_path, fp):
    """A REBUILT site.sqlite that no longer carries the Beethoven composer/
    work/recording -- the honest "an entity vanished from the corpus"
    scenario (unlike wiping every table, which would also strand the nav's
    own /browse/works/ link and fail the crawl for an unrelated reason).
    Browse payloads are emptied of references to the vanished entity so the
    rest of the site still renders link-clean. Same registry path/redirects
    are reused by the caller -- registry entries for a vanished identity are
    a RegistryDriftError concern for ttn_site's OWN build, not this
    renderer's job to detect."""
    import ttn_site
    empty_by_year = json.dumps([])
    empty_broadcasters = json.dumps([])
    empty_house_recordings = json.dumps([])
    empty_top_works = json.dumps([])
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Trad",
               "title": "Some Folk Tune", "performers": "Someone",
               "recording_pid": None}]
    episodes = [
        ("b0000001", "2020-01-01", "Through the Night",
         "https://www.bbc.co.uk/programmes/b0000001", json.dumps(tracks)),
        ("b0anchor1", "2008-07-15", "Through the Night",
         "https://www.bbc.co.uk/programmes/b0anchor1", json.dumps([])),
    ]
    browse = [
        ("top_works", empty_top_works),
        ("composers", json.dumps([])),
        ("years", empty_by_year),
        ("broadcasters", empty_broadcasters),
        ("house_recordings", empty_house_recordings),
    ]
    ttn_site.write_site_db(str(tmp_path), {
        "episodes": episodes, "browse": browse,
    }, fp)


def test_render_site_prunes_stale_page_of_deleted_entity(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    render_site(site_db, registry, str(dist))
    assert (dist / "composer" / "beethoven" / "index.html").exists()

    _fixture_without_beethoven(site_db, "fp-render-site-test-pruned")
    summary = render_site(site_db, registry, str(dist))

    assert not (dist / "composer" / "beethoven" / "index.html").exists()
    assert not (dist / "work" / "beethoven" / "symphony-5" / "index.html").exists()
    assert not (dist / "recording" / "p0000001" / "index.html").exists()
    assert summary["pruned"] >= 3


def test_render_site_prune_never_touches_static_or_pagefind(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    render_site(site_db, registry, str(dist))

    # Simulate a pagefind post-pass artifact + confirm static/ survives too.
    pagefind_dir = dist / "pagefind"
    pagefind_dir.mkdir()
    (pagefind_dir / "pagefind.js").write_text("// stub")
    assert (dist / "static" / "style.css").exists()

    _fixture_without_beethoven(site_db, "fp-render-site-test-pruned-2")
    render_site(site_db, registry, str(dist))

    assert (pagefind_dir / "pagefind.js").exists()
    assert (dist / "static" / "style.css").exists()


def test_render_site_static_copied_byte_identical(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    render_site(site_db, registry, str(dist))
    import ttn_site_render
    src = os.path.join(os.path.dirname(os.path.abspath(ttn_site_render.__file__)),
                        "static", "style.css")
    with open(src, "rb") as fh:
        expected = fh.read()
    assert (dist / "static" / "style.css").read_bytes() == expected


def test_render_site_crawl_catches_dangling_href(tmp_path, monkeypatch):
    import ttn_site_render as tsr
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"

    # Doctor render_composer to emit a dangling internal href that no page
    # or static asset will ever resolve to -- the render-time counterpart of
    # check_closure.
    real_render_composer = tsr.render_composer

    def _poisoned(row, env=None):
        url, html = real_render_composer(row, env)
        html = html.replace("</body>", '<a href="/composer/does-not-exist/">x</a></body>')
        return url, html

    monkeypatch.setattr(tsr, "render_composer", _poisoned)

    with pytest.raises(tsr.RenderClosureError) as ei:
        render_site(site_db, registry, str(dist))
    assert "does-not-exist" in str(ei.value)


def test_render_site_built_at_appears_in_footer(tmp_path):
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    render_site(site_db, registry, str(dist))
    html = _read(dist / "composer" / "beethoven" / "index.html")
    assert "Built " in html
    assert "None" not in html.split("Built ")[1][:40]


# --- pagefind post-pass (task 6) -----------------------------------------------

def test_run_pagefind_success_returns_true(tmp_path, monkeypatch):
    import ttn_site_render as tsr

    captured = {}

    class _FakeCompleted:
        returncode = 0
        stdout = b"indexed 3 pages\n"
        stderr = b""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted()

    monkeypatch.setattr(tsr.subprocess, "run", _fake_run)
    ok = run_pagefind(str(tmp_path))
    assert ok is True
    assert captured["cmd"] == ["npx", "--yes", "pagefind", "--site", str(tmp_path),
                               "--exclude-selectors", ".facts, table, ul.plain"]
    assert captured["kwargs"].get("capture_output") is True


def test_run_pagefind_nonzero_exit_returns_false_with_warning(tmp_path, monkeypatch, capsys):
    import ttn_site_render as tsr

    class _FakeCompleted:
        returncode = 1
        stdout = b""
        stderr = b"pagefind: something went wrong\n"

    monkeypatch.setattr(tsr.subprocess, "run", lambda cmd, **kwargs: _FakeCompleted())
    ok = run_pagefind(str(tmp_path))
    assert ok is False
    err = capsys.readouterr().err
    assert "pagefind" in err.lower()
    assert "something went wrong" in err


def test_run_pagefind_missing_npx_returns_false(tmp_path, monkeypatch, capsys):
    import ttn_site_render as tsr

    def _raise(cmd, **kwargs):
        raise FileNotFoundError("npx not found")

    monkeypatch.setattr(tsr.subprocess, "run", _raise)
    ok = run_pagefind(str(tmp_path))
    assert ok is False
    err = capsys.readouterr().err
    assert "pagefind" in err.lower()


def test_run_pagefind_timeout_returns_false(tmp_path, monkeypatch, capsys):
    import ttn_site_render as tsr
    import subprocess as real_subprocess

    def _raise(cmd, **kwargs):
        raise real_subprocess.TimeoutExpired(cmd="npx", timeout=600)

    monkeypatch.setattr(tsr.subprocess, "run", _raise)
    ok = run_pagefind(str(tmp_path))
    assert ok is False
    err = capsys.readouterr().err
    assert "pagefind" in err.lower()


def test_render_site_pagefind_false_by_default_skips_and_flags_none(tmp_path, monkeypatch):
    import ttn_site_render as tsr
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"

    def _boom(dist_dir):
        raise AssertionError("run_pagefind must not be called when pagefind=False")

    monkeypatch.setattr(tsr, "run_pagefind", _boom)
    summary = render_site(site_db, registry, str(dist), pagefind=False)
    assert summary["pagefind"] is None


def test_render_site_pagefind_true_invokes_run_pagefind_after_crawl(tmp_path, monkeypatch):
    import ttn_site_render as tsr
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"

    calls = []

    def _fake_run_pagefind(dist_dir):
        calls.append(dist_dir)
        return True

    monkeypatch.setattr(tsr, "run_pagefind", _fake_run_pagefind)
    summary = render_site(site_db, registry, str(dist), pagefind=True)
    assert calls == [str(dist)]
    assert summary["pagefind"] is True


def test_render_site_pagefind_failure_still_succeeds_with_flag_false(tmp_path, monkeypatch):
    import ttn_site_render as tsr
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"

    monkeypatch.setattr(tsr, "run_pagefind", lambda dist_dir: False)
    summary = render_site(site_db, registry, str(dist), pagefind=True)
    assert summary["pagefind"] is False
    # The rest of the render still succeeded -- search is an enhancement.
    assert summary["crawl_ok"] is True
    assert (dist / "composer" / "beethoven" / "index.html").exists()


def test_render_site_pagefind_not_run_before_crawl_passes(tmp_path, monkeypatch):
    """If the crawl were going to fail, pagefind must never have been called
    -- render_site raises RenderClosureError before summary assembly, so a
    monkeypatched run_pagefind that would blow up proves it wasn't reached."""
    import ttn_site_render as tsr
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"

    real_render_composer = tsr.render_composer

    def _poisoned(row, env=None):
        url, html = real_render_composer(row, env)
        html = html.replace("</body>", '<a href="/composer/does-not-exist/">x</a></body>')
        return url, html

    monkeypatch.setattr(tsr, "render_composer", _poisoned)
    monkeypatch.setattr(tsr, "run_pagefind",
                         lambda dist_dir: (_ for _ in ()).throw(
                             AssertionError("run_pagefind must not run before a passing crawl")))

    with pytest.raises(tsr.RenderClosureError):
        render_site(site_db, registry, str(dist), pagefind=True)


def test_crawl_whitelists_pagefind_prefix():
    import ttn_site_render as tsr
    pages = {
        "/": ('<link rel="stylesheet" href="/pagefind/pagefind-ui.css">'
              '<script src="/pagefind/pagefind-ui.js"></script>'),
    }
    violations = tsr._crawl(pages, [], set())
    assert violations == []


def test_render_site_base_html_pagefind_hrefs_do_not_fail_crawl(tmp_path):
    """base.html now emits /pagefind/ hrefs on every page (task 6) -- the
    crawl must not flag them even though dist/pagefind/ is only populated by
    a REAL pagefind run (never in the fast unit-test path)."""
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    summary = render_site(site_db, registry, str(dist), pagefind=False)
    assert summary["crawl_ok"] is True


@pytest.mark.live
def test_run_pagefind_real_binary_indexes_a_tiny_dist(tmp_path):
    """One real end-to-end smoke: render a tiny fixture dist for real, then
    run the REAL `npx --yes pagefind` against it (downloads the aarch64
    binary on a cold machine -- network, hence @pytest.mark.live and excluded
    from the fast suite by this project's `addopts = -m 'not live'`)."""
    site_db, registry = _full_fixture(tmp_path)
    dist = tmp_path / "dist"
    summary = render_site(site_db, registry, str(dist), pagefind=True)

    assert summary["crawl_ok"] is True
    assert summary["pagefind"] is True
    assert (dist / "pagefind").is_dir()
    assert any((dist / "pagefind").iterdir())


