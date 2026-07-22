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
                              render_work, render_composer, render_performance,
                              render_episode_date, render_home, render_browse,
                              render_browse_index, render_year,
                              render_broadcaster, render_form, render_artist,
                              render_country,
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
    assert url_for("performance", "p0fhfv23") == "/performance/p0fhfv23/"
    assert url_for("browse", "house-performances") == "/browse/house-performances/"
    assert url_for("browse", "") == "/browse/"          # landing index
    assert url_for("year", "2026") == "/year/2026/"


def test_url_for_unknown_kind_raises():
    with pytest.raises(ValueError):
        url_for("bogus", "whatever")


def test_browse_url_name_underscore_to_hyphen():
    assert browse_url_name("house_performances") == "house-performances"
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
            "broadcaster": "Polskie Radio", "broadcaster_slug": "polskie-radio",
            "conductors": [{"name": "Simon Rattle", "mbid": None}],
            "ensembles": [{"name": "Berlin Phil", "mbid": None}],
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
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "beethoven:symphony-5")
    conn.close()

    url, html = render_work(row)

    assert url == url_for("work", "beethoven:symphony-5")
    assert 'href="/composer/beethoven/"' in html
    assert 'href="/performance/p0000001/"' in html
    assert "SRF (German)" not in html  # sanity: wrong-code decode isn't leaking
    assert "BBC" in html               # GBBBC decoded display name
    # the performances table's Broadcaster column: linked name + flag tooltip
    assert 'href="/broadcaster/polskie-radio/">Polskie Radio</a>' in html
    assert "\U0001F1F5\U0001F1F1" in html and 'data-tip="Poland"' in html
    # by_year renders as the bar strip, LAST section (after broadcasters), and
    # the work page suppresses the works count (always 1 -- noise)
    assert 'data-tip="2020 &middot; 2 airings"' in html
    assert "1 work" not in html
    assert html.index("Source broadcasters") < html.index("By year")
    assert "30:00" in html             # 1800s duration formatted M:SS
    assert "Op.67" in html
    assert "n_text_only" not in html   # never leak raw field names as text


def test_render_work_performers_cell_is_one_column_in_recital_order(tmp_path):
    """The three role columns are one Performers cell: 82% of rows had at
    least one of them empty, and three narrow columns each wrapping made rows
    TALLER than one wide one. Order is recital order -- soloists, ensemble,
    conductor -- which is the reverse of the old column order. An absent role
    must take its separator with it, or an orchestral row opens with ' -- '."""
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets(recordings=[
        {"recording_pid": "p0000001", "duration": 1800, "airing_count": 4,
         "first": "2012-04-01", "last": "2026-01-01",
         "broadcaster": "BBC", "broadcaster_slug": None,
         "conductors": [{"name": "Simon Rattle", "mbid": None}],
         "ensembles": [{"name": "Berlin Phil", "mbid": None}],
         "soloists": [{"name": "Alice Sara Ott", "mbid": None}]},
        {"recording_pid": "p0000002", "duration": 600, "airing_count": 1,
         "first": "2013-04-01", "last": "2013-04-01",
         "broadcaster": "BBC", "broadcaster_slug": None,
         "conductors": [], "ensembles": [], "soloists": [
             {"name": "Angela Hewitt", "mbid": None}]},
    ])
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", None, 100,
              5, 0, "2012-04-01", "2026-01-01", facets)]
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9,
                  "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)
    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "beethoven:symphony-5")
    conn.close()

    _url, html = render_work(row)

    assert '<th scope="col">Performers</th>' in html
    for gone in ("Conductors", "Ensembles", "Soloists"):
        assert f">{gone}</th>" not in html
    assert ("Alice Sara Ott &middot; Berlin Phil &middot; Simon Rattle"
            in html)
    # the solo row carries no separator at all, leading or trailing
    assert "<td>Angela Hewitt</td>" in html


def test_render_work_recording_contributors_link_registered_mbids(tmp_path):
    # The Performances table links each per-recording contributor to its
    # /artist/ page by EXACT MBID; an unregistered contributor stays plain text
    # (Reviewer #2 round-3 should-fix: the work page previously dropped the
    # links the performance page already carried).
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets(
        recordings=[{
            "recording_pid": "p0000001", "duration": 1800, "airing_count": 3,
            "first": "2013-01-01", "last": "2020-01-01",
            "conductors": [{"name": "Registered Maestro", "mbid": "m-reg"}],
            "ensembles": [{"name": "Unlinked Band", "mbid": "m-unreg"}],
            "soloists": [],
        }])
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 100,
              3, 0, "2013-01-01", "2020-01-01", facets)]
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)
    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "beethoven:symphony-5")
    conn.close()

    _url, html = render_work(row, artist_slug_of={"m-reg": "registered-maestro"})
    assert 'href="/artist/registered-maestro/">Registered Maestro</a>' in html
    assert "Unlinked Band" in html            # present...
    assert ">Unlinked Band</a>" not in html   # ...but not linked (unregistered MBID)


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


def test_render_composer_facets_sections(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = json.dumps({
        "top_performers": [{"identity": "p", "display_name": "Steven Osborne",
                             "mbid": None, "airings": 12, "recordings": 3}],
        "top_conductors": [{"identity": "c", "display_name": "Maestro",
                             "mbid": None, "airings": 9, "recordings": 2}],
        "top_ensembles": [{"identity": "e", "display_name": "Band",
                            "mbid": None, "airings": 9, "recordings": 2}],
        "by_year": [{"year": "2021", "airings": 40, "works": 12},
                     {"year": "2020", "airings": 35, "works": 10}],
        "broadcasters": [{"key": "GBBBC", "airings": 20, "recordings": 5}],
    })
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven",
                   75, 12, "[]", facets)]
    _make_site_db(db_path, works=[], composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "composers", "slug", "beethoven")
    conn.close()

    _url, html = render_composer(row)
    assert "Steven Osborne (12)" in html
    assert "Maestro (9)" in html and "Band (9)" in html
    assert "<h2>By year</h2>" in html
    # by-year renders as the bar strip: readout text, scaled heights (40 is
    # the max -> 100%, 35 -> 87.5%), and the end-year axis
    assert 'data-tip="2021 &middot; 40 airings &middot; 12 works"' in html
    assert "height:100.0%" in html and "height:87.5%" in html
    assert '<span>2020</span><span>2021</span>' in html
    assert "BBC" in html and "(20)" in html         # EBU code decoded (now flagged)
    assert "\U0001F1EC\U0001F1E7" in html           # GB flag on the source
    assert "2012 onward" in html                    # the scope disclosure


def test_render_composer_empty_facets_renders_no_sections(tmp_path):
    db_path = tmp_path / "site.sqlite"
    composers = [("quiet", "quiet", "Quiet Composer", 1, 1, "[]", "{}")]
    _make_site_db(db_path, works=[], composers=composers)
    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "composers", "slug", "quiet")
    conn.close()
    _url, html = render_composer(row)
    assert "By year" not in html
    assert "2012 onward" not in html


def test_render_work_text_only_disclosure_agrees_in_number(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets()
    works = [("a:one", "a", "a", "one", "One", "A", None, 5, 1, 1,
              "2010-01-01", "2020-01-01", facets),
             ("a:many", "a", "a", "many", "Many", "A", None, 5, 1, 7,
              "2010-01-01", "2020-01-01", facets)]
    composers = [("a", "a", "A", 10, 2, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row_one = _row(conn, "works", "slug", "a:one")
    row_many = _row(conn, "works", "slug", "a:many")
    conn.close()

    _url, html_one = render_work(row_one)
    assert "1 airing exists in the broadcast history" in html_one
    assert "1 airings" not in html_one
    _url, html_many = render_work(row_many)
    assert "7 airings exist in the broadcast history" in html_many


def test_render_work_escapes_html_in_title(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets()
    nasty = 'Quartet "Lark" & <Friends>'
    works = [("lark-work", "haydn", "haydn", "lark-key",
              nasty, "Joseph Haydn", None, 1, 0, 1,
              "2020-01-01", "2020-01-01", facets)]
    composers = [("haydn", "haydn", "Joseph Haydn", 1, 1, "[]", "{}")]
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
    composers = [("haydn", "haydn", "Joseph Haydn", 5, 1, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "some-work")
    conn.close()

    url, html = render_work(row)
    assert "3 airings exist in the broadcast history" in html
    assert "without a match to specific performances" in html


def test_render_work_data_pagefind_body_present(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets()
    works = [("w1", "c1", "c1", "wk1", "Work One", "Composer One", None,
              1, 0, 1, "2020-01-01", "2020-01-01", facets)]
    composers = [("c1", "c1", "Composer One", 1, 1, "[]", "{}")]
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
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 180, 2, works_json, "{}")]
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
    composers = [("nasty", "nasty", 'A & <B>', 1, 0, "[]", "{}")]
    _make_site_db(db_path, works=[], composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "composers", "slug", "nasty")
    conn.close()

    url, html = render_composer(row)
    assert "A & <B>" not in html
    assert "&amp;" in html
    assert "&lt;B&gt;" in html


# --- render_performance -----------------------------------------------------------

def test_render_performance_role_grouping_episode_links_and_duration(tmp_path):
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
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers, recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "p0000001")
    conn.close()

    url, html = render_performance(row, work_display="Symphony No 5",
                                    broadcaster_slug_of={"BBC": "bbc"})
    assert url == url_for("performance", "p0000001")
    assert "Symphony No 5" in html
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/composer/beethoven/"' in html
    assert 'href="/episode/2012/04/01/"' in html
    assert 'href="/episode/2020/06/01/"' in html
    assert "30:00" in html
    assert "\U0001F1EC\U0001F1E7" in html          # broadcaster flag
    assert 'data-tip="United Kingdom"' in html     # country name on hover
    assert 'href="/broadcaster/bbc/">BBC</a>' in html   # broadcaster drill-in link
    # by-year bar strip closes the page, derived from the airing dates
    # (2012 + 2020 -> one airing each, 7 gap years between); the clickable
    # airing-dates table stays -- the strip is the summary, not a replacement
    assert 'data-tip="2012 &middot; 1 airing"' in html   # singular
    assert 'data-tip="2020 &middot; 1 airing"' in html
    assert html.count('class="bar gap"') == 7
    assert html.index("Airing dates") < html.index("By year")
    # airing dates render year-grouped: newest year first, day-month labels
    assert '<dt>2020</dt>' in html and '<dt>2012</dt>' in html
    assert html.index("<dt>2020</dt>") < html.index("<dt>2012</dt>")
    assert '>1 Apr</a>' in html and '>1 Jun</a>' in html
    # without the driver's join map the name degrades to plain text
    _u, html_plain = render_performance(row, work_display="Symphony No 5")
    assert 'href="/broadcaster' not in html_plain and "BBC" in html_plain
    assert "Simon Rattle" in html
    assert "Berlin Philharmonic" in html
    assert "Someone Soloist" in html
    # role order preserved: Composer before Conductor before Orchestra before Performer
    ci = html.index("Ludwig van Beethoven")
    coi = html.index("Simon Rattle")
    oi = html.index("Berlin Philharmonic")
    pi_ = html.index("Someone Soloist")
    assert ci < coi < oi < pi_


def test_render_performance_airing_years_within_year_order_and_separator(tmp_path):
    """A year with several airings renders as ONE dot-separated line, dates
    oldest-first within the year, even when the stored JSON is unordered."""
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([{"role": "Composer", "name": "Anon"}])
    airing_dates = json.dumps([["2025-10-09", "b0000004"],
                                ["2025-02-18", "b0000001"],
                                ["2025-05-11", "b0000002"],
                                ["2025-09-07", "b0000003"]])
    recordings = [("p0000001", None, None, 300,
                    None, 4, "2025-02-18", "2025-10-09", contributors, airing_dates)]
    _make_site_db(db_path, recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "p0000001")
    conn.close()

    _url, html = render_performance(row, work_display="Whatever")
    assert '<dt>2025</dt>' in html
    line = html.split("<dt>2025</dt>")[1].split("</dd>")[0]
    assert (line.index(">18 Feb</a>") < line.index(">11 May</a>")
            < line.index(">7 Sep</a>") < line.index(">9 Oct</a>"))
    assert line.count("&middot;") == 3                  # separators, no trailing dot
    assert 'href="/episode/2025/02/18/"' in line


def test_render_performance_links_registered_contributors_by_mbid(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([
        {"role": "Conductor", "name": "Hannu Lintu", "mbid": "m-lintu"},
        {"role": "Performer", "name": "Big Star", "mbid": None},   # name-keyed
        {"role": "Orchestra", "name": "Finnish RSO", "mbid": "m-unregistered"},
    ])
    airing_dates = json.dumps([["2015-01-01", "b0000001"]])
    recordings = [("p0000001", "sibelius:sym2", "sibelius", 1800,
                    None, 3, "2015-01-01", "2020-01-01", contributors, airing_dates)]
    _make_site_db(db_path, works=[], composers=[], recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "p0000001")
    conn.close()

    _u, html = render_performance(
        row, work_display="Symphony No 2",
        artist_slug_of={"m-lintu": "hannu-lintu"})   # only Lintu is registered
    assert 'href="/artist/hannu-lintu/">Hannu Lintu</a>' in html
    assert "Big Star" in html and 'href="/artist' not in html.split("Big Star")[0][-40:]
    # an MBID absent from the map stays plain text (no dangling link)
    assert "Finnish RSO" in html
    assert 'href="/artist/m-unregistered' not in html


def test_broadcaster_facet_rows_links_recognized_ebu_keys_only():
    import ttn_site_render as tsr
    entries = [{"key": "GBBBC", "airings": 40, "recordings": 5},
                {"key": "OTHER", "airings": 3, "recordings": 2}]   # accounting bucket
    rows = tsr._broadcaster_facet_rows(entries, {"GBBBC": "bbc"})
    assert rows[0]["display_name"] == "BBC" and rows[0]["slug"] == "bbc"
    assert rows[0]["flag"] == "\U0001F1EC\U0001F1E7"     # GB flag + country tip
    assert rows[0]["country"] == "United Kingdom"
    assert rows[1]["display_name"] == "OTHER" and rows[1]["slug"] is None
    assert rows[1]["flag"] == ""                          # accounting bucket flagless
    # no map -> everything plain text
    rows = tsr._broadcaster_facet_rows(entries)
    assert all(r["slug"] is None for r in rows)


def test_by_year_bars_fixed_corpus_span(tmp_path):
    """With corpus_span in the env globals (render_site sets it), the by-year
    strip covers the WHOLE corpus domain regardless of the entity's own
    history: a lone 2015 year renders 2008..2026 = 19 slots (18 gaps) with
    the axis endpoints pinned to the corpus years, not the data years."""
    import ttn_site_render as tsr
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets(
        by_year=[{"year": "2015", "airings": 3, "works": 1, "composers": 1,
                   "date_min": "2015-01-01", "date_max": "2015-06-01"}],
    )
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 100,
              4, 10, "2010-01-17", "2026-06-01", facets)]
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "beethoven:symphony-5")
    conn.close()

    env = tsr._env()
    prior = env.globals.get("corpus_span")
    try:
        env.globals["corpus_span"] = (2008, 2026)
        _url, html = render_work(row)
    finally:
        env.globals["corpus_span"] = prior

    assert html.count('class="bar gap"') == 18          # 19 slots, 1 data bar
    assert 'data-tip="2015 &middot; 3 airings"' in html
    assert "<span>2008</span><span>2026</span>" in html  # axis = corpus span

    # without the global (standalone render) the strip falls back to the
    # data's own span -- a single year means no gaps at all
    _url, html_plain = render_work(row)
    assert html_plain.count('class="bar gap"') == 0
    assert "<span>2015</span><span>2015</span>" in html_plain


def test_render_work_broadcasters_drop_accounting_buckets(tmp_path):
    """The work page's Source broadcasters list shows recognized EBU sources
    only: OTHER/UNATTRIBUTED are dropped and the disclosure line states the
    EBU-only scope."""
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets(
        broadcasters=[{"key": "GBBBC", "airings": 4, "recordings": 1},
                       {"key": "OTHER", "airings": 3, "recordings": 2},
                       {"key": "UNATTRIBUTED", "airings": 2, "recordings": 1}],
    )
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 100,
              4, 10, "2010-01-17", "2026-06-01", facets)]
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 100, 9, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "beethoven:symphony-5")
    conn.close()

    _url, html = render_work(row)

    assert "Source broadcasters" in html and "BBC" in html
    assert "OTHER" not in html and "UNATTRIBUTED" not in html
    assert "Only airings with an EBU country code are listed." in html


def test_render_country_h1_carries_flag(tmp_path):
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(db_path), {
        "countries": [("germany", "Germany", 8000, 1200, 6,
                        "[]", "[]", "[]", "[]")],
    }, "fp-country-flag")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM countries").fetchone()
    conn.close()
    _url, html = render_country(row)
    assert "\U0001F1E9\U0001F1EA" in html               # DE flag on the h1
    assert 'data-tip="Germany"' in html
    # a real country name needs no explanatory note -> not wrapped in abbr.tip
    assert '<h1>Germany' in html and '<abbr class="tip"' not in html.split("</h1>")[0]


def test_render_country_multilateral_h1_carries_note_no_flag(tmp_path):
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(db_path), {
        "countries": [("multilateral", "(multilateral)", 500, 80, 2,
                        "[]", "[]", "[]", "[]")],
    }, "fp-country-note")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM countries").fetchone()
    conn.close()
    _url, html = render_country(row)
    # the opaque bucket name gets an underlined tooltip, and NO flag
    assert ('<abbr class="tip" tabindex="0" '
            'data-tip="EBU / Euroradio shared and international relay">'
            '(multilateral)</abbr>') in html
    assert not any(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in html)   # no flag


def test_render_browse_countries_flags_and_links():
    payload = [
        {"display": "Germany", "slug": "germany", "airings": 8000,
         "recordings": 1200, "n_broadcasters": 6},
        {"display": "OTHER", "slug": None, "airings": 5,
         "recordings": 3, "n_broadcasters": None},
    ]
    _url, html = render_browse("countries", payload, _env())
    assert 'href="/country/germany/"' in html
    assert "\U0001F1E9\U0001F1EA" in html               # Germany flag
    # the OTHER accounting row is link-less AND flagless
    assert "OTHER" in html


def test_render_work_links_source_broadcasters_when_key_map_given(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets(broadcasters=[{"key": "GBBBC", "airings": 40,
                                          "recordings": 5}])
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", None, 40, 5, 0,
              "2015-01-01", "2020-01-01", facets)]
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 40, 1, "[]", "{}")]
    _make_site_db(db_path, works=works, composers=composers)
    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "works", "slug", "beethoven:symphony-5")
    conn.close()

    _u, html = render_work(row, broadcaster_slug_of={"GBBBC": "bbc"})
    assert 'href="/broadcaster/bbc/">BBC</a>' in html
    # without the map the same section is plain text (no dangling link)
    _u, html_plain = render_work(row)
    assert "BBC" in html_plain and 'href="/broadcaster/' not in html_plain


def test_render_work_and_composer_link_facet_contributors_by_mbid(tmp_path):
    db_path = tmp_path / "site.sqlite"
    facets = _work_facets(
        top_conductors=[{"identity": "m-lintu", "display_name": "Hannu Lintu",
                          "mbid": "m-lintu", "airings": 9, "recordings": 2}],
        top_performers=[{"identity": "name:x", "display_name": "Name Keyed",
                          "mbid": None, "airings": 3, "recordings": 1}],
    )
    works = [("sibelius:sym2", "sibelius", "sibelius", "sym2", "Symphony No 2",
              "Jean Sibelius", None, 9, 2, 0, "2015-01-01", "2020-01-01", facets)]
    comp_facets = json.dumps({
        "top_conductors": [{"identity": "m-lintu", "display_name": "Hannu Lintu",
                             "mbid": "m-lintu", "airings": 9, "recordings": 2}],
        "top_performers": [], "top_ensembles": [], "by_year": [], "broadcasters": []})
    composers = [("sibelius", "sibelius", "Jean Sibelius", 9, 1, "[]", comp_facets)]
    _make_site_db(db_path, works=works, composers=composers)

    conn = sqlite3.connect(str(db_path))
    wrow = _row(conn, "works", "slug", "sibelius:sym2")
    crow = _row(conn, "composers", "slug", "sibelius")
    conn.close()

    aslug = {"m-lintu": "hannu-lintu"}
    _u, whtml = render_work(wrow, artist_slug_of=aslug)
    assert 'href="/artist/hannu-lintu/">Hannu Lintu</a>' in whtml
    assert "Name Keyed" in whtml and "/artist/name" not in whtml  # unlinked
    _u, chtml = render_composer(crow, artist_slug_of=aslug)
    assert 'href="/artist/hannu-lintu/">Hannu Lintu</a>' in chtml


def test_render_performance_null_work_and_composer_slug_renders_plain_text(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([{"role": "Composer", "name": "Anon"}])
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    recordings = [("pXXXXXXX", None, None, 120,
                    None, 1, "2020-01-01", "2020-01-01", contributors, airing_dates)]
    _make_site_db(db_path, works=[], composers=[], recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "pXXXXXXX")
    conn.close()

    url, html = render_performance(row, work_display="Some Work")
    assert not re.search(r'<a[^>]*href="/work/', html)
    assert not re.search(r'<a[^>]*href="/composer/', html)
    assert "2:00" in html


def test_render_performance_no_data_pagefind_body(tmp_path):
    db_path = tmp_path / "site.sqlite"
    contributors = json.dumps([{"role": "Composer", "name": "Anon"}])
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    recordings = [("pYYYYYYY", None, None, 60,
                    None, 1, "2020-01-01", "2020-01-01", contributors, airing_dates)]
    _make_site_db(db_path, works=[], composers=[], recordings=recordings)

    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "recordings", "recording_pid", "pYYYYYYY")
    conn.close()

    url, html = render_performance(row, work_display="Some Work")
    assert 'data-pagefind-body' not in html


def test_render_performance_work_display_is_required():
    # The driver must join works and pass work_display; forgetting the join
    # must fail loudly (TypeError), never silently title ~18.9k pages with pids.
    with pytest.raises(TypeError):
        render_performance({"recording_pid": "p0000001"})


def test_render_performance_escapes_hostile_work_display(tmp_path):
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
    url, html = render_performance(row, work_display=nasty)
    assert nasty not in html
    assert "&amp;" in html
    assert "&lt;Friends&gt;" in html
    assert "&quot;Lark&quot;" in html or "&#34;Lark&#34;" in html


def test_render_performance_unknown_role_renders_after_known_roles(tmp_path):
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

    url, html = render_performance(row, work_display="Some Work")
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
        r'^/composer/[^/]+/$', r'^/performance/[^/]+/$',
        r'^/episode/\d{4}/\d{2}/\d{2}/$', r'^/browse/[^/]+/$', r'^/browse/$',
        r'^/broadcaster/[^/]+/$', r'^/form/[^/]+/$', r'^/artist/[^/]+/$',
        r'^/static/.+$', r'^/about/$', r'^/pagefind/.+$',
        r'^/feed\.xml$',   # the base.html Atom autodiscovery link, every page
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
        "conductors": [{"name": "Simon Rattle", "mbid": None}],
        "ensembles": [], "soloists": [],
    }])
    works = [("beethoven:symphony-5", "beethoven", "beethoven", "symphony-5",
              "Symphony No 5", "Ludwig van Beethoven", "Op.67", 1,
              1, 0, "2012-04-01", "2012-04-01", facets)]
    works_json = json.dumps([
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5", "airings": 1},
    ])
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 1, 1, works_json, "{}")]
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
        (rec_row, lambda r: render_performance(r, work_display="Symphony No 5")),
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
    assert 'href="/performance/p0000001/"' in html
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
    assert not re.search(r'<a[^>]*href="/performance/', html)


def test_render_episode_date_gives_every_track_row_an_anchor_id():
    """The target half of the airing-date links. Episode-qualified, because a
    multi-pid night puts several episodes on ONE page and a bare position
    would collide across them."""
    def _track(pos, title):
        return {"pos": pos, "time": "01:00 AM", "work_slug": None,
                "composer_slug": None, "composer": "Anon", "title": title,
                "performers": "Someone", "recording_pid": None}
    rows = [_episode_row("m00113tp", "2021-10-31", "One", [_track(0, "A"), _track(1, "B")]),
            _episode_row("m00113tv", "2021-10-31", "Two", [_track(0, "C")])]
    _, html = render_episode_date("2021-10-31", rows, _env())
    assert 'id="m00113tp-0"' in html
    assert 'id="m00113tp-1"' in html
    assert 'id="m00113tv-0"' in html


def test_the_work_page_anchor_matches_the_episode_page_target():
    """The two halves are built by different functions on different pages; if
    they ever disagree the link silently lands at the top of the night. Render
    both and check the fragment the work page emits is an id the episode page
    actually carries."""
    from ttn_site_render import render_work
    work_row = {"slug": "anon:some-fragment", "work_display": "Untitled Fragment",
                "composer_display": "Anon", "composer_slug": "anon",
                "catalogue": None, "n_text_only": 1, "airings": 1,
                "n_recordings": 0,
                "first_aired": "2026-03-26", "last_aired": "2026-03-26",
                "facets_json": json.dumps(
                    {"recordings": [],
                     "airing_dates": [["2026-03-26", "m002w1zk", 7]]})}
    _, work_html = render_work(work_row)
    fragment = re.search(r'href="/episode/2026/03/26/#([^"]+)"', work_html)
    assert fragment, work_html

    tracks = [{"pos": p, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Anon", "title": f"t{p}",
               # pos 7 is TEXT-ONLY -- no recording_pid. That row is exactly
               # why the anchor is keyed on position: 13.1% of tracks have no
               # PID and they are the ones with no other route in.
               "performers": "Someone", "recording_pid": None}
              for p in range(10)]
    ep_rows = [_episode_row("m002w1zk", "2026-03-26", "Through the Night", tracks)]
    _, ep_html = render_episode_date("2026-03-26", ep_rows, _env())
    assert f'id="{fragment.group(1)}"' in ep_html


def test_render_performance_airing_dates_anchor_at_their_own_track():
    """The performance page has the same problem and the same fix."""
    airing_dates = json.dumps([["2020-01-01", "b0000001", 4]])
    contributors = json.dumps([{"role": "Composer", "name": "Anon"}])
    row = {"recording_pid": "p0000009", "work_slug": None, "composer_slug": None,
           "duration": 300, "broadcaster": None, "airings": 1,
           "first_aired": "2020-01-01", "last_aired": "2020-01-01",
           "contributors_json": contributors, "airing_dates_json": airing_dates}
    _, html = render_performance(row, work_display="Some Work")
    assert 'href="/episode/2020/01/01/#b0000001-4"' in html


def test_render_performance_pre_anchor_airing_dates_still_link():
    """A site.sqlite built before this feature carries [date, pid] pairs. It
    must render un-anchored links, not a broken page."""
    airing_dates = json.dumps([["2020-01-01", "b0000001"]])
    contributors = json.dumps([{"role": "Composer", "name": "Anon"}])
    row = {"recording_pid": "p0000010", "work_slug": None, "composer_slug": None,
           "duration": 300, "broadcaster": None, "airings": 1,
           "first_aired": "2020-01-01", "last_aired": "2020-01-01",
           "contributors_json": contributors, "airing_dates_json": airing_dates}
    _, html = render_performance(row, work_display="Some Work")
    assert 'href="/episode/2020/01/01/"' in html
    assert "#" not in html.split('href="/episode/2020/01/01/"')[1][:40]


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
    assert 'href="/performance/p0000009/"' in html
    assert html.count('href="/performance/') == 1


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
    stats = {"works": 20721, "composers": 3557, "ensembles": 1897,
              "episodes": 6509, "recordings": 18885,
              "date_min": "2008-07-02", "date_max": "2026-07-11"}
    url, html = render_home(stats, last_night_rows, _env())
    assert url == "/"
    assert "20721" in html or "20,721" in html
    assert "3557" in html or "3,557" in html
    assert "1,897" in html                       # the Ensembles stat
    assert 'href="/browse/ensembles/"' in html   # ...linked to its browse page
    assert 'href="/browse/performances/"' in html  # Performances stat + browse list link
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/browse/works/"' in html
    assert 'href="/browse/house-performances/"' in html
    assert 'href="/browse/years/"' in html
    assert 'href="/browse/broadcasters/"' in html


def test_render_home_shows_last_night_date_linked_to_episode():
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Trad", "title": "A Tune",
               "performers": "Someone", "recording_pid": None}]
    rows = [_episode_row("b0lastnt1", "2026-07-11", "Through the Night", tracks)]
    stats = {"works": 1, "composers": 1, "ensembles": 0, "episodes": 1,
             "recordings": 0,
             "date_min": "2026-07-11", "date_max": "2026-07-11"}
    _url, html = render_home(stats, rows, _env(), last_night_date="2026-07-11")
    assert "11 July 2026" in html
    assert 'href="/episode/2026/07/11/"' in html


def test_render_home_no_date_line_when_last_night_date_none():
    stats = {"works": 0, "composers": 0, "ensembles": 0, "episodes": 0,
             "recordings": 0, "date_min": None, "date_max": None}
    _url, html = render_home(stats, [], _env(), last_night_date=None)
    assert "last-night-date" not in html


def test_render_home_and_episode_share_playlist_table_structure():
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Trad",
               "title": "A Tune", "performers": "Someone", "recording_pid": None}]
    rows = [_episode_row("b0shared01", "2026-07-11", "Through the Night", tracks)]
    _url1, home_html = render_home(
        {"works": 1, "composers": 1, "ensembles": 0, "episodes": 1,
         "recordings": 0, "date_min": "2026-07-11", "date_max": "2026-07-11"},
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


def test_render_browse_top_performances_links_and_columns():
    payload = [
        {"recording_pid": "p0jwxyz1", "work_slug": "brahms:symphony-4",
         "work_display": "Symphony No 4", "composer_slug": "brahms",
         "composer_display": "Johannes Brahms", "airings": 31,
         "conductors": ["Riccardo Frizza"],
         "ensembles": ["Hungarian Radio Symphony Orchestra"],
         "soloists": []},
    ]
    url, html = render_browse("top_performances", payload, _env())
    assert url == "/browse/performances/"
    assert 'href="/performance/p0jwxyz1/"' in html
    assert 'href="/work/brahms/symphony-4/"' in html
    assert 'href="/composer/brahms/"' in html
    assert "Riccardo Frizza" in html and "31" in html
    assert '<th scope="col">PID</th>' in html   # bare header, no gloss
    assert "2012" in html                       # the scope stamp


def test_render_broadcaster_page_sections_links_and_flag(tmp_path):
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(db_path), {
        "broadcasters": [
            ("polskie-radio", "PLPR", "Polskie Radio", "Poland", 4104, 1090,
             json.dumps([{"slug": "chopin:24-preludes-op-28",
                          "display": "24 Preludes, Op 28",
                          "composer_display": "Frédéric Chopin", "airings": 65}]),
             json.dumps([{"recording_pid": "p0abc0001",
                          "work_slug": "chopin:24-preludes-op-28",
                          "work_display": "24 Preludes, Op 28",
                          "composer_slug": "chopin",
                          "composer_display": "Frédéric Chopin", "airings": 40}]),
             json.dumps([{"display": "Polish Radio Symphony Orchestra",
                          "mbid": "m-prso", "airings": 900},
                         {"display": "Nameless Band", "mbid": None,
                          "airings": 5}])),
        ],
    }, "fp-brc-test")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM broadcasters").fetchone()
    conn.close()

    url, html = render_broadcaster(row, artist_slug_of={"m-prso": "polish-rso"})
    assert url == "/broadcaster/polskie-radio/"
    assert "Polskie Radio" in html and "Poland" in html
    assert "\U0001F1F5\U0001F1F1" in html                       # PL flag
    assert 'href="/work/chopin/24-preludes-op-28/"' in html
    assert 'href="/performance/p0abc0001/"' in html
    assert 'href="/composer/chopin/"' in html
    # MBID-registered ensemble links to its /artist/ page; the mbid-less one
    # renders as plain text (safe degrade)
    assert 'href="/artist/polish-rso/">Polish Radio Symphony Orchestra</a>' in html
    assert "Nameless Band" in html and 'href="/artist/nameless' not in html
    assert "2012" in html                                       # scope stamp


def test_render_broadcaster_display_keeps_annotation_and_zz_flagless(tmp_path):
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(db_path), {
        "broadcasters": [
            ("ebu-euroradio-shared-relay", "ZZEBU", "EBU / Euroradio shared relay",
             "(multilateral)", 128, 30, "[]", "[]", "[]"),
            ("mtva", "HUMTVA", "MTVA (current)", "Hungary", 500, 100,
             "[]", "[]", "[]"),
        ],
    }, "fp-brc-test-2")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = {r["slug"]: r for r in conn.execute("SELECT * FROM broadcasters")}
    conn.close()

    _url, html = render_broadcaster(rows["ebu-euroradio-shared-relay"])
    assert not any(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in html)   # ZZ flagless
    url2, html2 = render_broadcaster(rows["mtva"])
    assert url2 == "/broadcaster/mtva/"          # annotation stripped from URL
    assert "MTVA (current)" in html2             # ...but kept in the display


def test_render_browse_broadcasters_links_pages_when_slugged():
    payload = [{"key": "PLPR", "airings": 4104, "recordings": 1090,
                "slug": "polskie-radio"},
               {"key": "OTHER", "airings": 5, "recordings": 3, "slug": None}]
    _url, html = render_browse("broadcasters", payload, _env())
    assert 'href="/broadcaster/polskie-radio/"' in html
    assert "OTHER" in html and 'href="/broadcaster/OTHER' not in html


def test_render_browse_lengths_sections_links_and_median():
    payload = {"short_max": 600, "long_min": 1800,
               "short": [{"slug": "wolf:italian-serenade",
                          "display": "Italian Serenade",
                          "composer_display": "Hugo Wolf",
                          "composer_slug": "wolf", "airings": 161,
                          "median_seconds": 420}],
               "medium": [{"slug": "debussy:faune",
                           "display": "Prelude a l'apres-midi d'un faune",
                           "composer_display": "Claude Debussy",
                           "composer_slug": "debussy", "airings": 216,
                           "median_seconds": 637}],
               "long": []}
    url, html = render_browse("lengths", payload, _env())
    assert url == "/browse/lengths/"
    assert "Short — under 10 minutes" in html
    assert "Medium — 10 to 30 minutes" in html
    assert "Long — over 30 minutes" not in html    # empty section is skipped
    assert 'href="/work/wolf/italian-serenade/"' in html
    assert 'href="/composer/debussy/"' in html
    assert "7:00" in html and "10:37" in html      # medians formatted M:SS
    assert "typical performance length" in html     # the classification blurb
    assert "2012" in html                           # scope stamp


def test_url_for_form():
    assert url_for("form", "nocturne") == "/form/nocturne/"


def test_url_for_artist():
    assert url_for("artist", "hannu-lintu") == "/artist/hannu-lintu/"


def test_url_for_country():
    assert url_for("country", "germany") == "/country/germany/"


def test_env_finalize_renders_none_as_empty_not_the_word_none():
    # An unmeasured duration (NULL / below the sanity floor) renders via
    # format_duration to None, which the env finalize turns into a blank cell,
    # never the literal "None" (the pre-fix bug on NULL-duration recordings).
    tmpl = _env().from_string("<td>{{ d }}</td>")
    assert tmpl.render(d=None) == "<td></td>"
    assert tmpl.render(d=125) == "<td>125</td>"


def test_render_country_hub_and_national_profile(tmp_path):
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(db_path), {
        "countries": [
            ("germany", "Germany", 8000, 1200, 6,
             json.dumps([{"slug": "wdr-westdeutscher-rundfunk",
                          "display": "WDR – Westdeutscher Rundfunk", "airings": 5000},
                         {"slug": "ndr-norddeutscher-rundfunk",
                          "display": "NDR – Norddeutscher Rundfunk", "airings": 3000}]),
             json.dumps([{"slug": "bach:bwv1056", "display": "Keyboard Concerto",
                          "composer_display": "J.S. Bach", "airings": 40}]),
             json.dumps([{"recording_pid": "p0abc0001",
                          "work_slug": "bach:bwv1056", "work_display": "Keyboard Concerto",
                          "composer_slug": "bach", "composer_display": "J.S. Bach",
                          "airings": 20}]),
             json.dumps([{"display": "WDR Symphony Orchestra",
                          "mbid": "m-wdrso", "airings": 900}])),
        ],
    }, "fp-country-test")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM countries").fetchone()
    conn.close()

    url, html = render_country(row, artist_slug_of={"m-wdrso": "wdr-so"})
    assert url == "/country/germany/"
    assert "<h1>Germany" in html                     # h1 names the country (+ flag)
    # hub-first: the country's broadcasters, each linked to its /broadcaster/ page
    assert 'href="/broadcaster/wdr-westdeutscher-rundfunk/"' in html
    assert 'href="/broadcaster/ndr-norddeutscher-rundfunk/"' in html
    # national profile below
    assert 'href="/work/bach/bwv1056/"' in html
    assert 'href="/performance/p0abc0001/"' in html
    assert 'href="/artist/wdr-so/">WDR Symphony Orchestra</a>' in html
    assert "2012 onward" in html                 # scope stamp


def test_render_artist_page_sections_links_and_musicbrainz(tmp_path):
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    facets = json.dumps({
        "top_composers": [{"slug": "jean-sibelius", "display": "Jean Sibelius",
                            "airings": 65}],
        "collaborators": {
            "conductors": [],
            "soloists": [{"display": "Steven Osborne", "airings": 5,
                           "slug": None}],
            "ensembles": [{"display": "Finnish RSO", "airings": 65,
                            "slug": "finnish-rso"}],
        },
        "by_year": [{"year": "2026", "airings": 3}, {"year": "2013", "airings": 60}],
        "broadcasters": [{"key": "FIYLE", "airings": 65, "recordings": 2}],
        "performances": [{"recording_pid": "p0000001",
                           "work_slug": "sibelius:sym2",
                           "work_display": "Symphony No 2",
                           "composer_display": "Jean Sibelius",
                           "duration": 2700, "airings": 60,
                           "first": "2013-01-01", "last": "2026-01-01"}],
    })
    ttn_site.write_site_db(str(db_path), {
        "artists": [("hannu-lintu", "m-lintu-mbid", "Hannu Lintu", "person",
                      json.dumps(["Conductor", "Performer"]), 65, 2,
                      "2013-01-01", "2026-01-01", facets)],
    }, "fp-artist-test")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM artists").fetchone()
    conn.close()

    url, html = render_artist(row)
    assert url == "/artist/hannu-lintu/"
    assert "<h1" in html and "Hannu Lintu" in html
    assert "Conductor, Performer" in html                       # merged roles
    assert 'href="https://musicbrainz.org/artist/m-lintu-mbid"' in html
    assert 'href="/work/sibelius/sym2/"' in html                # colon slug split
    assert 'href="/composer/jean-sibelius/"' in html
    assert 'href="/artist/finnish-rso/"' in html                # linked collaborator
    assert "Steven Osborne" in html and 'href="/artist/steven' not in html
    assert 'href="/performance/p0000001/"' in html
    assert "45:00" in html                                      # 2700s formatted
    assert "2012 onward" in html                                # scope line
    assert "Conductors appeared with" not in html               # empty bucket skipped
    # heading is honest about completeness: this fixture lists 1 of 2
    # recordings, so it claims a ranking
    assert "<h2>Most-aired performances</h2>" in html
    assert "Most-played works" not in html          # works block is gone
    # by-year bar strip: 2013 + 2026 rows -> 12 transparent gap slots between,
    # readout on the airing bars (no works count on artist rows), end-year axis
    assert html.count('class="bar gap"') == 12
    assert 'data-tip="2013 &middot; 60 airings"' in html
    assert 'data-tip="2026 &middot; 3 airings"' in html
    assert '<span>2013</span><span>2026</span>' in html


def test_render_artist_complete_performance_list_drops_the_ranking_heading(tmp_path):
    # When the page lists every recording the artist has, "Most-aired" is a
    # false claim -- it is not a ranking of a larger set, it is the whole set.
    # 96% of artists land here (median 2 recordings, cut at 20).
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    facets = json.dumps({
        "top_composers": [], "collaborators": {}, "by_year": [],
        "broadcasters": [],
        "performances": [{"recording_pid": "p0000001",
                          "work_slug": "sibelius:sym2",
                          "work_display": "Symphony No 2",
                          "composer_display": "Jean Sibelius",
                          "duration": 2700, "airings": 60,
                          "first": "2013-01-01", "last": "2026-01-01"}],
    })
    ttn_site.write_site_db(str(db_path), {
        "artists": [("hannu-lintu", "m-lintu-mbid", "Hannu Lintu", "person",
                     json.dumps(["Conductor"]), 60, 1,
                     "2013-01-01", "2026-01-01", facets)],
    }, "fp-artist-complete")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM artists").fetchone()
    conn.close()

    _url, html = render_artist(row)
    assert "<h2>Performances</h2>" in html
    assert "Most-aired" not in html


def test_render_form_page_links_terms_and_facts(tmp_path):
    import ttn_site
    db_path = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(db_path), {
        "forms": [
            ("prelude", 4200, 310, json.dumps(["prelude", "prélude", "preludes"]),
             json.dumps([{"slug": "chopin:24-preludes-op-28",
                          "display": "24 Preludes, Op 28",
                          "composer_display": "Frédéric Chopin",
                          "composer_slug": "chopin", "airings": 65}])),
        ],
    }, "fp-form-test")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM forms").fetchone()
    conn.close()

    url, html = render_form(row)
    assert url == "/form/prelude/"
    assert "<h1>Prelude</h1>" in html                # capitalized slug
    assert "prélude, preludes" in html               # non-canonical terms stated
    assert "310" in html and "4200" in html          # works + airings facts
    assert 'href="/work/chopin/24-preludes-op-28/"' in html
    assert 'href="/composer/chopin/"' in html


def test_render_browse_christmas_ranking_and_night_links():
    payload = {
        "window": ["12-24", "12-25"],
        "top_works": [{"slug": "corelli:christmas-concerto",
                        "display": "Christmas Concerto",
                        "composer_display": "Arcangelo Corelli",
                        "composer_slug": "corelli", "airings": 14}],
        "nights": ["2024-12-25", "2024-12-24", "2023-12-25"],
    }
    url, html = render_browse("christmas", payload, _env())
    assert url == "/browse/christmas/"
    assert 'href="/work/corelli/christmas-concerto/"' in html
    assert 'href="/composer/corelli/"' in html
    # nights split into two compact year-links lines by role
    assert re.search(
        r'Christmas Eve:\s*<a href="/episode/2024/12/24/">2024</a>', html)
    assert re.search(
        r'Christmas Day:\s*<a href="/episode/2024/12/25/">2024</a> &middot; '
        r'<a href="/episode/2023/12/25/">2023</a>', html)
    assert "December 24th" in html            # the window blurb
    # empty payload -> page renders with the blurb, no tables
    _url, html = render_browse(
        "christmas", {"window": ["12-24", "12-25"],
                       "top_works": [], "nights": []}, _env())
    assert "Most-aired at Christmas" not in html
    assert "The Christmas broadcasts" not in html


def test_render_browse_forms_links_form_pages():
    payload = [{"slug": "concerto", "display": "Concerto",
                "airings": 24500, "n_works": 4097},
               {"slug": "nocturne", "display": "Nocturne",
                "airings": 900, "n_works": 120}]
    url, html = render_browse("forms", payload, _env())
    assert url == "/browse/forms/"
    assert 'href="/form/concerto/"' in html
    assert 'href="/form/nocturne/"' in html
    assert "4097" in html and "24500" in html
    # the classification blurb: title-based, cross-language, multi-form
    assert "title" in html and "Symphonie" in html


def test_every_page_head_carries_atom_autodiscovery_link():
    # base.html: feed readers find /feed.xml from any page.
    _url, html = render_browse("top_works", [], _env())
    assert ('<link rel="alternate" type="application/atom+xml"' in html
            and 'href="/feed.xml"' in html)


def test_render_home_links_the_feed_visibly():
    stats = {"works": 1, "composers": 1, "ensembles": 0, "episodes": 1,
             "recordings": 0, "date_min": "2020-01-01", "date_max": "2020-01-01"}
    _url, html = render_home(stats, [], _env(), last_night_date="2020-01-01")
    assert '<a href="/feed.xml">Atom feed</a>' in html


def test_render_home_on_this_night_links_previous_years():
    stats = {"works": 1, "composers": 1, "ensembles": 0, "episodes": 3,
             "recordings": 0, "date_min": "2018-07-16", "date_max": "2026-07-16"}
    _url, html = render_home(
        stats, [], _env(), last_night_date="2026-07-16",
        on_this_night=["2025-07-16", "2018-07-16"])
    assert "<h2>On this night</h2>" in html
    assert 'href="/episode/2025/07/16/">2025</a>' in html
    assert 'href="/episode/2018/07/16/">2018</a>' in html
    # empty list -> no block
    _url, html = render_home(stats, [], _env(), last_night_date="2026-07-16")
    assert "On this night" not in html


def test_render_browse_years_flags_partial_endpoint_years():
    # Newest-first payload (the browse shape): the mid-cut latest year and the
    # corpus-floor earliest year get the '*' + footnote; the interior year
    # doesn't (mirrors ttn_analyze._partial_years — endpoints only).
    payload = [
        {"year": "2026", "airings": 5010, "works": 2000, "composers": 500,
         "date_min": "2026-01-01", "date_max": "2026-06-30"},
        {"year": "2025", "airings": 9000, "works": 3000, "composers": 700,
         "date_min": "2025-01-01", "date_max": "2025-12-31"},
        {"year": "2010", "airings": 8000, "works": 2800, "composers": 650,
         "date_min": "2010-01-17", "date_max": "2010-12-31"},
    ]
    _url, html = render_browse("years", payload, _env())
    assert ">2026</a>*" in html
    assert ">2010</a>*" in html
    assert ">2025</a>*" not in html
    assert "partial year" in html            # the footnote


def test_render_browse_years_no_footnote_when_all_years_complete():
    payload = [
        {"year": "2025", "airings": 9000, "works": 3000, "composers": 700,
         "date_min": "2025-01-01", "date_max": "2025-12-31"},
    ]
    _url, html = render_browse("years", payload, _env())
    assert "*" not in html.split("<main")[1]  # no flag anywhere in the content
    assert "partial year" not in html


def test_render_browse_works_and_composers_have_blurbs():
    _url, html = render_browse("top_works", [], _env())
    assert "most-aired works" in html
    _url, html = render_browse("composers", [], _env())
    assert "most-aired composers" in html


def test_render_browse_ensembles_dict_payload_blurb_and_rows():
    # ensembles is the one DICT-shaped payload {cut, total, rows}: the blurb
    # states the inclusion line + whole-corpus identity count + the 2012+
    # scope stamp; rows are deliberately link-less (no /ensemble/ pages).
    payload = {"cut": 50, "total": 1897,
               "rows": [{"display": "Finnish Radio Symphony Orchestra",
                         "airings": 1941, "performances": 171}]}
    url, html = render_browse("ensembles", payload, _env())
    assert url == url_for("browse", "ensembles")
    assert "Finnish Radio Symphony Orchestra" in html
    assert "1941" in html and "171" in html
    assert "at least 50 airings" in html
    assert "1,897" in html
    assert "2012" in html
    assert 'href="/ensemble' not in html


def test_render_browse_index_renders_shared_grouped_nav():
    # The /browse/ landing renders the same grouped Browse menu as the home page
    # (the shared _browse_nav.html macro), unconditionally -- a missing payload
    # is caught by the render crawl, matching the home page's posture.
    url, html = render_browse_index(_env())
    assert url == "/browse/"
    # the four group headings, in canonical order (Works first since dd571ac)
    headings = ["Works &amp; performances", "People &amp; ensembles",
                "By characteristic", "Sources"]
    for h in headings:
        assert h in html
    assert [html.index(h) for h in headings] == sorted(html.index(h) for h in headings)
    # grouped, not the old flat order: a Works-group link precedes a People-group one
    assert html.index("/browse/works/") < html.index("/browse/composers/")
    assert ">Christmas nights<" in html and ">Countries<" in html


def test_render_browse_index_and_home_share_the_browse_nav():
    # The home Browse section and the /browse/ page emit byte-identical grouped
    # menus (same macro), so they can never drift.
    import re
    _u, index_html = render_browse_index(_env())
    tracks = [{"pos": 0, "time": "01:00 AM", "work_slug": None,
               "composer_slug": None, "composer": "Trad", "title": "A Tune",
               "performers": "x", "recording_pid": None}]
    rows = [_episode_row("b0brnav01", "2026-07-11", "Through the Night", tracks)]
    _u2, home_html = render_home(
        {"works": 1, "composers": 1, "ensembles": 0, "episodes": 1,
         "recordings": 0, "date_min": "2026-07-11", "date_max": "2026-07-11"},
        rows, _env(), last_night_date="2026-07-11")
    grab = re.compile(r'<div class="browse-groups">.*?</div>\s*</div>', re.S)
    assert grab.search(index_html).group(0) == grab.search(home_html).group(0)


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


def test_render_browse_house_performances_shows_roster_and_broadcaster():
    payload = [
        {"work_slug": "beethoven:symphony-5", "work_display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "recording_pid": "p0000001", "rec_airings": 6, "total_2016": 8,
         "conductors": ["Simon Rattle"], "ensembles": ["Berlin Phil"],
         "soloists": [], "broadcaster": "BBC", "broadcaster_slug": "bbc"},
    ]
    url, html = render_browse("house_performances", payload, _env())
    assert url == url_for("browse", "house-performances")
    assert 'href="/work/beethoven/symphony-5/"' in html
    assert 'href="/performance/p0000001/"' in html
    assert "6" in html and "8" in html            # the Airings fraction 6/8
    assert "Simon Rattle" in html
    assert "Berlin Phil" in html
    assert 'href="/broadcaster/bbc/">BBC</a>' in html   # linked Broadcaster column
    assert "Share" not in html                    # the retired column heading


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
    assert "\U0001F1EC\U0001F1E7" in html          # GB flag after the name
    assert 'data-tip="United Kingdom"' in html     # country name on hover


def test_render_browse_broadcasters_no_flag_for_unrecognized_or_empty():
    # OTHER-bucket labels (not EBU codes) must not flag from their first two
    # letters (decode()'s pseudo-country fallback); UNATTRIBUTED has no key.
    payload = [{"key": "Decca", "airings": 5, "recordings": 3},
               {"key": "", "airings": 2, "recordings": 1}]
    _url, html = render_browse("broadcasters", payload, _env())
    assert not any(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in html), \
        "no regional-indicator characters expected"


def test_render_browse_unknown_name_raises():
    with pytest.raises(ValueError):
        render_browse("bogus", [], _env())


# --- render_about ------------------------------------------------------------------

def test_render_about_renders_at_about_url():
    # The About PROSE is Nick's and changes freely (the old TODO-marker
    # skeleton assertion died when he wrote it); assert only the shell.
    # Its hard-linked corpus entities are covered by _about_linked_rows +
    # the closure crawl in the full-render tests.
    url, html = render_about(_env())
    assert url == "/about/"
    assert "<h1>" in html


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
        "performances": ["/performance/p0000001/"],
        "misc": ["/", "/about/", "/browse/works/", "/feed.xml"],
    }


def test_build_sitemaps_returns_seven_files():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    assert set(files) == {
        "sitemap.xml", "sitemap-works.xml", "sitemap-composers.xml",
        "sitemap-episodes.xml", "sitemap-performances.xml",
        "sitemap-artists.xml", "sitemap-misc.xml",
    }


def test_build_sitemaps_index_references_six_chunks_absolute():
    files = build_sitemaps(_sample_urls_by_kind(), "https://example.invalid")
    root = ET.fromstring(files["sitemap.xml"])
    assert root.tag == f"{_SITEMAP_NS}sitemapindex"
    locs = [el.text for el in root.iter(f"{_SITEMAP_NS}loc")]
    assert sorted(locs) == sorted(
        f"https://example.invalid/sitemap-{chunk}.xml"
        for chunk in ("works", "composers", "episodes", "performances",
                      "artists", "misc")
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


def test_base_url_is_the_production_domain():
    # The live-domain decision (2026-07-20). Pinned so an accidental edit --
    # or a placeholder regression -- fails loudly; a deliberate domain change
    # updates this alongside the constant.
    assert BASE_URL == "https://notturnometer.com"


# --- build_robots ----------------------------------------------------------------

def _robots_groups(txt):
    """Parse robots.txt into {user-agent: [directive lines]} the way a reader
    does: groups are separated by blank lines."""
    groups = {}
    for block in txt.strip().split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines[0].lower().startswith("user-agent:"):
            continue                      # non-group directive (Sitemap)
        agent = lines[0].split(":", 1)[1].strip()
        groups[agent] = lines[1:]
    return groups


def test_build_robots_allows_all_and_points_at_sitemap():
    txt = build_robots("https://example.invalid")
    groups = _robots_groups(txt)
    # the wildcard group is allow-all: its Disallow must have no path
    assert "Disallow:" in groups["*"]
    assert not any(l.startswith("Disallow: /") for l in groups["*"])
    assert "Sitemap: https://example.invalid/sitemap.xml" in txt


def test_build_robots_denies_the_named_agents():
    txt = build_robots()
    groups = _robots_groups(txt)
    for agent in ("MJ12bot", "ClaudeBot"):
        assert groups[agent] == ["Disallow: /"], agent


def test_build_robots_asks_for_a_crawl_delay():
    """Google ignores Crawl-delay; Bing/Yandex and most smaller bots honour
    it. Only the wildcard group carries it -- a denied agent has nothing to
    delay."""
    groups = _robots_groups(build_robots())
    assert any(l.startswith("Crawl-delay:") for l in groups["*"])
    assert not any(l.startswith("Crawl-delay:") for l in groups["MJ12bot"])


def test_build_robots_groups_are_blank_line_separated():
    """An unseparated run of User-agent lines can be read as ONE group, which
    would apply the denials to everybody."""
    txt = build_robots()
    assert "Disallow: /\n\nUser-agent:" in txt
    # Sitemap is a non-group directive: it must not sit inside a group
    assert txt.rstrip().endswith("/sitemap.xml")


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


def _about_linked_rows():
    """templates/about.html AND home.html are Nick's PROSE and hard-link real
    corpus entities; the closure crawl (rightly) validates those hrefs on
    every full render, so any fixture that renders the whole site must carry a
    page per linked entity. This is the ONE place to update when the prose
    gains/loses an entity link -- the production build validates the same
    links against the real corpus. Returns (works_rows, composers_rows).

    Currently linked: about.html -> williams:fantasia (+ williams),
    pyotr-tchaikovsky, franck:violin-sonata (+ franck); home.html ->
    darius-milhaud."""
    fantasia_works_json = json.dumps([
        {"slug": "williams:fantasia-on-a-theme-by-thomas",
         "display": "Fantasia on a Theme by Thomas Tallis", "airings": 1}])
    franck_works_json = json.dumps([
        {"slug": "franck:violin-sonata-in-a-major-m",
         "display": "Violin Sonata in A major", "airings": 1}])
    composers = [
        ("pyotr-tchaikovsky", "pyotr tchaikovsky", "Pyotr Ilyich Tchaikovsky",
         1, 0, json.dumps([]), "{}"),
        ("williams", "williams", "Ralph Vaughan Williams", 1, 1,
         fantasia_works_json, "{}"),
        ("franck", "franck", "César Franck", 1, 1, franck_works_json, "{}"),
        ("darius-milhaud", "darius milhaud", "Darius Milhaud",
         1, 0, json.dumps([]), "{}"),
    ]
    works = [
        ("williams:fantasia-on-a-theme-by-thomas", "williams", "williams",
         "fantasia-on-a-theme-by-thomas",
         "Fantasia on a Theme by Thomas Tallis", "Ralph Vaughan Williams",
         None, 1, 0, 1, "2020-01-01", "2020-01-01", _work_facets()),
        ("franck:violin-sonata-in-a-major-m", "franck", "franck",
         "violin-sonata-in-a-major-m", "Violin Sonata in A major",
         "César Franck", None, 1, 0, 1, "2020-01-01", "2020-01-01",
         _work_facets()),
    ]
    return works, composers


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
            "conductors": [{"name": "Simon Rattle", "mbid": None}],
            "ensembles": [{"name": "Berlin Phil", "mbid": None}],
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
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven", 1, 1, works_json, "{}")]
    about_works, about_composers = _about_linked_rows()
    works += about_works
    composers += about_composers

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
        ("b0000000", "2019-01-01", "Through the Night",
         "https://www.bbc.co.uk/programmes/b0000000", json.dumps([])),
        ("b0anchor1", "2008-07-15", "Through the Night",
         "https://www.bbc.co.uk/programmes/b0anchor1", json.dumps([])),
    ]

    top_works = json.dumps([
        {"slug": "beethoven:symphony-5", "display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "airings": 1}])
    years = json.dumps([{"year": "2020", "airings": 1, "works": 1, "composers": 1,
                          "date_min": "2020-01-01", "date_max": "2020-01-01"}])
    broadcasters = json.dumps([{"key": "GBBBC", "airings": 1, "recordings": 1,
                                 "slug": "bbc"}])
    house_performances = json.dumps([
        {"work_slug": "beethoven:symphony-5", "work_display": "Symphony No 5",
         "composer_display": "Ludwig van Beethoven", "composer_slug": "beethoven",
         "recording_pid": "p0000001", "rec_airings": 1, "total_2016": 1,
         "broadcaster": "BBC", "broadcaster_slug": "bbc",
         "conductors": ["Simon Rattle"],
         "ensembles": ["Berlin Phil"], "soloists": []}])
    composers_payload = json.dumps([
        {"slug": "beethoven", "display": "Ludwig van Beethoven",
         "airings": 1, "n_works": 1}])
    ensembles_payload = json.dumps({
        "cut": 50, "total": 2,
        "rows": [{"display": "Berlin Phil", "airings": 60, "performances": 1,
                   "slug": None}]})
    conductors_payload = json.dumps({
        "cut": 50, "total": 1,
        "rows": [{"display": "Simon Rattle", "airings": 60, "performances": 1,
                   "slug": "simon-rattle"}]})
    empty_listing = json.dumps({"cut": 50, "total": 0, "rows": []})
    top_performances = json.dumps([
        {"recording_pid": "p0000001", "work_slug": "beethoven:symphony-5",
         "work_display": "Symphony No 5", "composer_slug": "beethoven",
         "composer_display": "Ludwig van Beethoven", "airings": 1,
         "conductors": ["Simon Rattle"], "ensembles": ["Berlin Phil"],
         "soloists": []}])
    lengths_payload = json.dumps({
        "short_max": 600, "long_min": 1800,
        "short": [], "long": [],
        "medium": [{"slug": "beethoven:symphony-5", "display": "Symphony No 5",
                    "composer_display": "Ludwig van Beethoven",
                    "composer_slug": "beethoven", "airings": 1,
                    "median_seconds": 1800}]})
    forms_payload = json.dumps([
        {"slug": "symphony", "display": "Symphony", "airings": 1, "n_works": 1}])
    christmas_payload = json.dumps(
        {"window": ["12-24", "12-25"], "top_works": [], "nights": []})
    countries_payload = json.dumps([
        {"display": "United Kingdom", "slug": "united-kingdom", "airings": 1,
         "recordings": 1, "n_broadcasters": 1},
        {"display": "OTHER", "slug": None, "airings": 1,
         "recordings": 1, "n_broadcasters": None}])
    browse = [
        ("top_works", top_works),
        ("top_performances", top_performances),
        ("composers", composers_payload),
        ("ensembles", ensembles_payload),
        ("conductors", conductors_payload),
        ("performers", empty_listing),
        ("singers", empty_listing),
        ("lengths", lengths_payload),
        ("forms", forms_payload),
        ("christmas", christmas_payload),
        ("years", years),
        ("broadcasters", broadcasters),
        ("countries", countries_payload),
        ("house_performances", house_performances),
    ]
    years_table = [
        ("2020", 1, 1, 1,
         json.dumps([{"slug": "beethoven:symphony-5", "display": "Symphony No 5",
                      "composer_display": "Ludwig van Beethoven",
                      "composer_slug": "beethoven", "airings": 1}]),
         json.dumps([{"slug": "beethoven", "display": "Ludwig van Beethoven",
                      "airings": 1}])),
    ]

    forms_table = [
        ("symphony", 1, 1, json.dumps(["symphony", "symphonie"]),
         json.dumps([{"slug": "beethoven:symphony-5", "display": "Symphony No 5",
                      "composer_display": "Ludwig van Beethoven",
                      "composer_slug": "beethoven", "airings": 1}])),
    ]

    artists_table = [
        ("simon-rattle", "m-rattle", "Simon Rattle", "person",
         json.dumps(["Conductor"]), 1, 1, "2020-01-01", "2020-01-01",
         json.dumps({
             "top_works": [{"slug": "beethoven:symphony-5",
                             "display": "Symphony No 5",
                             "composer_display": "Ludwig van Beethoven",
                             "airings": 1}],
             "top_composers": [{"slug": "beethoven",
                                 "display": "Ludwig van Beethoven",
                                 "airings": 1}],
             "collaborators": {"conductors": [], "soloists": [],
                                "ensembles": [{"display": "Berlin Phil",
                                                "airings": 1, "slug": None}]},
             "by_year": [{"year": "2020", "airings": 1}],
             "broadcasters": [{"key": "GBBBC", "airings": 1, "recordings": 1}],
             "performances": [{"recording_pid": "p0000001",
                                "work_slug": "beethoven:symphony-5",
                                "work_display": "Symphony No 5",
                                "composer_display": "Ludwig van Beethoven",
                                "duration": 1800, "airings": 1,
                                "first": "2020-01-01", "last": "2020-01-01"}],
         })),
    ]

    broadcasters_table = [
        ("bbc", "GBBBC", "BBC", "United Kingdom", 1, 1,
         json.dumps([{"slug": "beethoven:symphony-5", "display": "Symphony No 5",
                      "composer_display": "Ludwig van Beethoven", "airings": 1}]),
         json.dumps([{"recording_pid": "p0000001",
                      "work_slug": "beethoven:symphony-5",
                      "work_display": "Symphony No 5",
                      "composer_slug": "beethoven",
                      "composer_display": "Ludwig van Beethoven", "airings": 1}]),
         json.dumps([{"display": "Berlin Phil", "airings": 1}])),
    ]

    countries_table = [
        ("united-kingdom", "United Kingdom", 1, 1, 1,
         json.dumps([{"slug": "bbc", "display": "BBC", "airings": 1}]),
         json.dumps([{"slug": "beethoven:symphony-5", "display": "Symphony No 5",
                      "composer_display": "Ludwig van Beethoven", "airings": 1}]),
         json.dumps([{"recording_pid": "p0000001",
                      "work_slug": "beethoven:symphony-5",
                      "work_display": "Symphony No 5",
                      "composer_slug": "beethoven",
                      "composer_display": "Ludwig van Beethoven", "airings": 1}]),
         json.dumps([{"display": "Berlin Phil", "airings": 1}])),
    ]

    site_db = tmp_path / "site.sqlite"
    ttn_site.write_site_db(str(site_db), {
        "works": works, "composers": composers, "episodes": episodes,
        "recordings": recordings, "browse": browse, "years": years_table,
        "broadcasters": broadcasters_table, "forms": forms_table,
        "artists": artists_table, "countries": countries_table,
    }, "fp-render-site-test")

    registry = ttn_site._empty_registry()
    registry["works"]["beethoven:symphony-5"] = {
        "composer_key": "beethoven", "work_key": "symphony-5", "published": "2020-01-01"}
    registry["composers"]["beethoven"] = {
        "composer_key": "beethoven", "published": "2020-01-01"}
    registry["works"]["williams:fantasia-on-a-theme-by-thomas"] = {
        "composer_key": "williams", "work_key": "fantasia-on-a-theme-by-thomas",
        "published": "2020-01-01"}
    registry["composers"]["williams"] = {
        "composer_key": "williams", "published": "2020-01-01"}
    registry["composers"]["pyotr-tchaikovsky"] = {
        "composer_key": "pyotr tchaikovsky", "published": "2020-01-01"}
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
    # 3 works + 5 composers (incl. the prose-linked entities) + 3 episode
    # dates + 1 recording + 14 browse + browse index + 1 year page +
    # 1 broadcaster page + 1 country page + 1 form page + 1 artist page +
    # home + about
    assert summary["pages"] == 3 + 5 + 3 + 1 + 14 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1
    # the 2019-01-01 fixture night shares last-night's month-day -> the home
    # "On this night" block links it
    home_html = _read(dist / "index.html")
    assert 'href="/episode/2019/01/01/">2019</a>' in home_html
    assert summary["written"] == summary["pages"]
    assert summary["skipped"] == 0
    assert summary["pruned"] == 0

    assert (dist / "work" / "beethoven" / "symphony-5" / "index.html").exists()
    assert (dist / "composer" / "beethoven" / "index.html").exists()
    assert (dist / "performance" / "p0000001" / "index.html").exists()
    assert (dist / "episode" / "2020" / "01" / "01" / "index.html").exists()
    assert (dist / "episode" / "2008" / "07" / "15" / "index.html").exists()
    assert (dist / "browse" / "works" / "index.html").exists()
    assert (dist / "browse" / "composers" / "index.html").exists()
    assert (dist / "browse" / "house-performances" / "index.html").exists()
    assert (dist / "browse" / "years" / "index.html").exists()
    assert (dist / "browse" / "broadcasters" / "index.html").exists()
    assert (dist / "browse" / "forms" / "index.html").exists()
    assert (dist / "browse" / "christmas" / "index.html").exists()
    assert (dist / "form" / "symphony" / "index.html").exists()  # per-form drill-in
    assert (dist / "artist" / "simon-rattle" / "index.html").exists()
    assert (dist / "sitemap-artists.xml").exists()               # sixth chunk
    assert (dist / "browse" / "countries" / "index.html").exists()
    assert (dist / "country" / "united-kingdom" / "index.html").exists()
    # the broadcaster page up-links to its country hub
    bbc_html = _read(dist / "broadcaster" / "bbc" / "index.html")
    assert 'href="/country/united-kingdom/">United Kingdom</a>' in bbc_html
    assert (dist / "browse" / "conductors" / "index.html").exists()
    # the conductors listing links its registered artist
    conductors_html = _read(dist / "browse" / "conductors" / "index.html")
    assert 'href="/artist/simon-rattle/">Simon Rattle</a>' in conductors_html
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
    html = _read(dist / "performance" / "p0000001" / "index.html")
    assert "Symphony No 5" in html


def test_render_site_redirects_render_when_registry_has_them(tmp_path):
    site_db, registry = _full_fixture(tmp_path, with_redirect=True)
    dist = tmp_path / "dist"
    summary = render_site(site_db, registry, str(dist))
    assert (dist / "work" / "old-beethoven-5" / "index.html").exists()
    assert (dist / "composer" / "old-beethoven" / "index.html").exists()
    # +2 redirect pages over the no-redirect fixture's page count
    assert summary["pages"] == 3 + 5 + 3 + 1 + 14 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 2


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
    empty_house_performances = json.dumps([])
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
        ("top_performances", json.dumps([])),
        ("composers", json.dumps([])),
        ("ensembles", json.dumps({"cut": 50, "total": 0, "rows": []})),
        ("conductors", json.dumps({"cut": 50, "total": 0, "rows": []})),
        ("performers", json.dumps({"cut": 50, "total": 0, "rows": []})),
        ("singers", json.dumps({"cut": 50, "total": 0, "rows": []})),
        ("lengths", json.dumps({"short_max": 600, "long_min": 1800,
                                 "short": [], "medium": [], "long": []})),
        ("forms", json.dumps([])),
        ("christmas", json.dumps({"window": ["12-24", "12-25"],
                                   "top_works": [], "nights": []})),
        ("years", empty_by_year),
        ("broadcasters", empty_broadcasters),
        ("countries", json.dumps([])),
        ("house_performances", empty_house_performances),
    ]
    about_works, about_composers = _about_linked_rows()
    ttn_site.write_site_db(str(tmp_path), {
        "episodes": episodes, "browse": browse,
        "works": about_works, "composers": about_composers,
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
    assert not (dist / "performance" / "p0000001" / "index.html").exists()
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

    def _poisoned(row, env=None, **kwargs):
        url, html = real_render_composer(row, env, **kwargs)
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

    def _poisoned(row, env=None, **kwargs):
        url, html = real_render_composer(row, env, **kwargs)
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




def test_render_composer_by_year_asterisks_partial_corpus_endpoint_years(tmp_path):
    # render_site sets env.globals["partial_years"] to the corpus-endpoint
    # years (archive start + in-progress latest); the by-year strip asterisks
    # those axis labels and notes "partial year" in the bar readout. Standalone
    # renders (no global) show neither -- covered by the facets test above.
    db_path = tmp_path / "site.sqlite"
    facets = json.dumps({
        "by_year": [{"year": "2021", "airings": 40, "works": 12},
                     {"year": "2020", "airings": 35, "works": 10}],
    })
    composers = [("beethoven", "beethoven", "Ludwig van Beethoven",
                   75, 12, "[]", facets)]
    _make_site_db(db_path, works=[], composers=composers)
    conn = sqlite3.connect(str(db_path))
    row = _row(conn, "composers", "slug", "beethoven")
    conn.close()

    import ttn_site_render
    env = ttn_site_render._env()
    had = "partial_years" in env.globals
    prior = env.globals.get("partial_years")
    env.globals["partial_years"] = {2021}
    try:
        _url, html = render_composer(row, env)
    finally:
        if had:
            env.globals["partial_years"] = prior
        else:
            env.globals.pop("partial_years", None)
    assert "<span>2021*</span>" in html                 # endpoint asterisked
    assert "<span>2020</span>" in html                  # mid-corpus year not
    assert ('data-tip="2021 &middot; 40 airings &middot; 12 works'
            ' &middot; partial year"') in html
    assert 'data-tip="2020 &middot; 35 airings &middot; 10 works"' in html


# --- table scroll containers -------------------------------------------------

def _template_dir():
    import ttn_site_render
    return os.path.join(
        os.path.dirname(os.path.abspath(ttn_site_render.__file__)), "templates")


def test_every_template_table_sits_in_a_scroll_container():
    """Structural invariant, checked over the TEMPLATES rather than one
    rendered page: a <table> with no .table-wrap around it overflows the
    document and pans the whole page sideways -- header and footer with it --
    because nothing else in the stylesheet establishes a scroll container.
    This guards the next table someone adds, which is where the regression
    would come from."""
    import glob
    offenders = []
    n_tables = 0
    for path in sorted(glob.glob(os.path.join(_template_dir(), "*.html"))):
        lines = open(path, encoding="utf-8").read().split("\n")
        for i, line in enumerate(lines):
            if re.search(r"<table\b", line):
                n_tables += 1
                if i == 0 or "table-wrap" not in lines[i - 1]:
                    offenders.append(f"{os.path.basename(path)}:{i + 1}")
    assert n_tables > 20, "expected the site's tables to be found"
    assert offenders == [], f"tables with no scroll container: {offenders}"


def test_table_wrap_carries_the_keyboard_and_at_recipe():
    """overflow-x alone makes a region only a mouse can reach (WCAG 2.1.1)."""
    import glob
    for path in sorted(glob.glob(os.path.join(_template_dir(), "*.html"))):
        for line in open(path, encoding="utf-8"):
            if "table-wrap" in line:
                assert 'tabindex="0"' in line, path
                assert 'role="region"' in line, path
                assert "aria-label=" in line, path


def test_stylesheet_defines_the_scroll_container():
    """The wrapper is inert without the rule; they ship together."""
    import ttn_site_render
    css = open(os.path.join(
        os.path.dirname(os.path.abspath(ttn_site_render.__file__)),
        "static", "style.css"), encoding="utf-8").read()
    assert ".table-wrap" in css
    assert "overflow-x: auto" in css


# --- stylesheet cache-busting -------------------------------------------------

def test_stylesheet_url_carries_a_content_hash():
    """The servers send validators but no Cache-Control, so a browser may pair
    a CACHED stylesheet with NEW html — which is exactly how the table-scroll
    wrappers appeared broken on a phone. The URL must change with the bytes."""
    from ttn_site_render import _env, _asset_version
    html = _env().get_template("base.html").render()
    v = _asset_version("style.css")
    assert len(v) == 8, "expected an 8-char content hash"
    assert f'href="/static/style.css?v={v}"' in html


def test_asset_version_tracks_content_and_degrades():
    from ttn_site_render import _asset_version
    import ttn_site_render
    assert _asset_version("style.css") == _asset_version("style.css")
    # a missing asset yields "" so the template omits the query entirely,
    # rather than the cache-busting nicety breaking the stylesheet link
    assert _asset_version("no-such-file.css") == ""


def test_versioned_asset_still_passes_the_link_crawl():
    """_internal_targets must strip the query as well as the fragment;
    without it EVERY page fails the crawl the moment versioning is on."""
    from ttn_site_render import _internal_targets, _crawl
    html = '<a href="/static/style.css?v=deadbeef">x</a>'
    assert list(_internal_targets(html)) == [
        ("/static/style.css?v=deadbeef", "/static/style.css")]
    assert _crawl({"/": html}, {"style.css"}, set()) == []


def _template_tables():
    """(template, wrapper line, header-cell count) for every table on the
    site, read from the templates rather than one rendered page."""
    import glob
    out = []
    for path in sorted(glob.glob(os.path.join(_template_dir(), "*.html"))):
        lines = open(path, encoding="utf-8").read().split("\n")
        wrapper = None
        n_th = 0
        for line in lines:
            if "table-wrap" in line:
                wrapper, n_th = line, 0
            if wrapper is not None:
                n_th += len(re.findall(r"<th[\s>]", line))
                if "</thead>" in line:
                    out.append((os.path.basename(path), wrapper, n_th))
                    wrapper = None
    return out


def test_only_the_browse_listings_escape_the_measure():
    """.wide lets a table out of main's 70ch measure. The axis is PAGE TYPE,
    not column count: those two pages are h1 -> one paragraph -> table, so the
    table is the page and misaligns against nothing. Anywhere else the widened
    table sits 264px left of every heading on the page. Pinned as an explicit
    set so the next wide table is a decision rather than a copy-paste."""
    tables = _template_tables()
    assert len(tables) > 20, "expected the site's tables to be found"
    wide = {name for name, wrapper, _ in tables if "wide" in wrapper}
    assert wide == {"browse_performances.html",
                    "browse_house_performances.html"}


def test_the_work_page_performances_table_fits_the_measure():
    """It fits because the three role columns became one. Eight columns need
    ~830px against the measure's ~575px, which is what sent it out of the
    measure in the first place."""
    tables = _template_tables()
    n_th = [n for name, _, n in tables if name == "work.html"]
    assert n_th == [6], n_th


def test_every_header_cell_declares_its_scope():
    """Without scope a screen reader infers the cell/column association from
    table shape, and gets it wrong on the tables that matter here (8 columns,
    mixed numeric and free text). Mechanical, invisible, and the kind of thing
    a new table silently omits -- hence the check over every template."""
    import glob
    offenders = []
    n = 0
    for path in sorted(glob.glob(os.path.join(_template_dir(), "*.html"))):
        for i, line in enumerate(open(path, encoding="utf-8")):
            for m in re.finditer(r"<th(?=[\s>])[^>]*>", line):
                n += 1
                if 'scope="' not in m.group(0):
                    offenders.append(f"{os.path.basename(path)}:{i + 1}")
    assert n > 100, "expected the site's header cells to be found"
    assert offenders == [], f"header cells with no scope: {offenders}"


def test_the_pid_gloss_survives_only_where_the_table_is_tall():
    """The tooltip is clipped by the scroll wrapper -- overflow-x: auto makes
    overflow-y auto too, and the bubble hangs below the header cell, so it is
    cut off whenever the rows beneath are shorter than the bubble is tall.
    Reserving space under short tables did not rescue it in practice.

    It survives on the PLAYLIST alone (home page and episode pages, one
    macro): a night's tracklist runs to ~24 rows, so the bubble opens into
    the table's own body and nothing clips it. Every other PID column is a
    bare header, and the explanation belongs elsewhere on the site.

    A CAPTION is not the alternative: a caption IS the table's accessible
    name, so it renamed every affected table after a footnote about column 1.
    """
    import glob
    tipped = set()
    for path in sorted(glob.glob(os.path.join(_template_dir(), "*.html"))):
        src = open(path, encoding="utf-8").read()
        if 'data-tip="The BBC' in src:
            tipped.add(os.path.basename(path))
        assert "<caption>PID" not in src, f"{path}: PID caption is back"
    assert tipped == {"_playlist.html"}, tipped


def test_every_pid_column_is_headed_the_same_way():
    """One name for one thing. /browse/house-performances/ headed its PID
    column 'Performance' while the other seven said PID."""
    import glob
    heads = set()
    for path in sorted(glob.glob(os.path.join(_template_dir(), "*.html"))):
        src = open(path, encoding="utf-8").read()
        heads |= set(re.findall(r'<th scope="col">(PID\(s\)|PID|Performance)'
                                r'</th>', src))
    assert heads <= {"PID", "PID(s)"}, heads


def test_stylesheet_lets_wide_tables_out_of_the_measure():
    """The modifier is inert without the rule; they ship together."""
    import ttn_site_render
    css = open(os.path.join(
        os.path.dirname(os.path.abspath(ttn_site_render.__file__)),
        "static", "style.css"), encoding="utf-8").read()
    block = css.split(".table-wrap.wide {", 1)[1].split("}", 1)[0]
    assert "min(94vw, 1100px)" in block
    # centred on the measure, not flush left
    assert block.count("margin-left") == 1 and block.count("margin-right") == 1


def test_table_wrap_has_a_scroll_affordance():
    """iOS shows no scrollbar until touched; without an edge cue a scrollable
    table reads as a broken one."""
    import ttn_site_render
    css = open(os.path.join(
        os.path.dirname(os.path.abspath(ttn_site_render.__file__)),
        "static", "style.css"), encoding="utf-8").read()
    block = css.split(".table-wrap {", 1)[1].split("}", 1)[0]
    assert "background-attachment: local, local, scroll, scroll" in block
    assert "radial-gradient" in block
