"""Tests for ttn_site_render: URL authority + dist path mapping +
write-if-changed (website Phase 2, task 1); page builders + templates
(website Phase 2, task 2); episode/home/browse/about/redirect page builders
(website Phase 2, task 3).

Run: uv run --with pytest pytest test_ttn_site_render.py
"""
import json
import re
import sqlite3

import pytest

from ttn_site_render import (url_for, dist_path, write_if_changed, browse_url_name,
                              render_work, render_composer, render_recording,
                              render_episode_date, render_home, render_browse,
                              render_about, render_redirect, format_date, _env)


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
        r'^/episode/\d{4}/\d{2}/\d{2}/$', r'^/browse/[^/]+/$',
        r'^/static/.+$', r'^/about/$',
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

def test_render_browse_works_rows_link_work_and_composer():
    payload = [
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "airings": 100},
    ]
    url, html = render_browse("works", payload, _env())
    assert url == url_for("browse", "works")
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/composer/beethoven/"' in html
    assert "100" in html


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
