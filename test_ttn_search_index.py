"""ttn_search_index tests -- the search catalogue builder."""
import json
import os
import shutil
import sqlite3
import subprocess

import pytest

import ttn_search_index


def _blank_db():
    """An empty site.sqlite built from the REAL schema.

    Deliberately imports _SITE_SCHEMA rather than hand-copying CREATE TABLE
    statements: a hand-copied fixture drifts from the real schema silently, and
    a fixture with the wrong column name lets wrong code pass. (ttn_site.py's
    own comment records this exact class of bug -- 'a hand-maintained count map
    drifted from the CREATE TABLE text once'.) Column names here are therefore
    always the real ones: works.work_display, NOT works.display."""
    from ttn_site import _SITE_SCHEMA
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SITE_SCHEMA)
    return conn


def _insert(conn, table, **cols):
    """Insert a partial row by column name -- the real tables have 9-13
    columns and these tests care about 3-5 of them."""
    names = ", ".join(cols)
    marks = ", ".join("?" * len(cols))
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})",
                 tuple(cols.values()))


def _db():
    """site.sqlite with one row per entity kind."""
    conn = _blank_db()
    _insert(conn, "works", slug="dvorak:symphony-no-9",
            work_display="Symphony No 9 'From the New World'",
            composer_slug="antonin-dvorak", composer_display="Antonín Dvořák",
            airings=96)
    _insert(conn, "composers", slug="antonin-dvorak",
            display="Antonín Dvořák", airings=2266, n_works=118)
    _insert(conn, "artists", slug="marc-andre-hamelin",
            display="Marc-André Hamelin", kind="performer",
            airings=212, n_recordings=140)
    _insert(conn, "broadcasters", slug="polskie-radio",
            display="Polskie Radio", country="Poland", airings=8123)
    _insert(conn, "countries", slug="poland", country="Poland", airings=8500)
    _insert(conn, "forms", slug="symphony", airings=5400, n_works=900)
    _insert(conn, "years", year="2019", airings=8700)
    _insert(conn, "browse", name="house_performances", payload_json="{}")
    _insert(conn, "recordings", recording_pid="b01abcde",
            work_slug="dvorak:symphony-no-9", airings=12)
    conn.commit()
    return conn


def _by_kind(docs, kind):
    return [d for d in docs if d["k"] == kind]


def test_every_kind_produces_a_document():
    docs = ttn_search_index.build_catalogue(_db())
    kinds = {d["k"] for d in docs}
    assert kinds == {"work", "composer", "artist", "broadcaster",
                     "country", "form", "year", "browse"}


def test_recordings_produce_no_documents():
    """Performance pages are deliberately excluded -- they duplicate the
    work's title and composer, so they would land as near-duplicate noise."""
    docs = ttn_search_index.build_catalogue(_db())
    assert _by_kind(docs, "performance") == []
    assert _by_kind(docs, "recording") == []
    assert not any("b01abcde" in d["u"] for d in docs)


def test_work_document_shape():
    doc, = _by_kind(ttn_search_index.build_catalogue(_db()), "work")
    assert doc["n"] == "Symphony No 9 'From the New World'"
    assert doc["s"] == "Antonín Dvořák"
    assert doc["u"] == "/work/dvorak/symphony-no-9/"
    assert doc["w"] == 96


def test_composer_document_carries_airings_and_facts():
    doc, = _by_kind(ttn_search_index.build_catalogue(_db()), "composer")
    assert doc["n"] == "Antonín Dvořák"
    assert doc["u"] == "/composer/antonin-dvorak/"
    assert doc["w"] == 2266
    assert "118 works" in doc["x"]
    assert "2,266 airings" in doc["x"]


def test_alias_field_carries_ascii_fold():
    """'Dvorak' must reach 'Dvořák' deterministically, not by luck of
    whatever folding the search library happens to do."""
    doc, = _by_kind(ttn_search_index.build_catalogue(_db()), "composer")
    assert "antonin dvorak" in doc["a"]


def test_alias_field_second_part_is_independently_findable():
    """The alias field joins multiple parts (name, country/slug/date) -- they
    must be SPACE-joined, not glued with a delimiter character. MiniSearch's
    default tokenizer splits on /[\\n\\r\\p{Z}\\p{P}]+/u, and '|' (Sm, not P)
    survives that split -- a '|' join would weld 'polskie radio' and 'poland'
    into one unsearchable token, making every part after the first
    unreachable. Assert the second part is a standalone whitespace-delimited
    token, not merely a substring (a '|' join still passes an `in` check)."""
    doc, = _by_kind(ttn_search_index.build_catalogue(_db()), "broadcaster")
    assert "poland" in doc["a"].split()


def test_airings_never_none():
    """boostDocument must not have to guard against a missing prior."""
    docs = ttn_search_index.build_catalogue(_db())
    assert all(isinstance(d["w"], int) for d in docs)


def test_every_url_is_absolute_rooted_and_slash_terminated():
    docs = ttn_search_index.build_catalogue(_db())
    assert all(d["u"].startswith("/") and d["u"].endswith("/") for d in docs)


def test_browse_url_maps_underscores_to_hyphens():
    """browse.name is the underscore payload name; url_for wants the
    hyphenated URL segment. Without this assertion, dropping the
    browse_url_name call would regress URLs silently -- every other test
    passes identically either way."""
    doc, = _by_kind(ttn_search_index.build_catalogue(_db()), "browse")
    assert doc["u"] == "/browse/house-performances/"


def _ep_db(rows):
    """An otherwise-empty site.sqlite carrying only episodes.
    rows = [(pid, date, title), ...].

    NB `title` here is the episode SUBTITLE -- that is what site.sqlite stores
    in this column (ttn_site.py _EPISODE_META_SQL selects
    COALESCE(NULLIF(subtitle, ''), title) into it). There is no `subtitle`
    column in site.sqlite."""
    conn = _blank_db()
    for pid, date10, title in rows:
        _insert(conn, "episodes", pid=pid, date=date10, title=title)
    conn.commit()
    return conn


def test_episode_document_uses_subtitle_and_date():
    docs = ttn_search_index.build_catalogue(_ep_db([
        ("m001", "2019-03-01", "Mahler at the BBC Proms")]))
    doc, = _by_kind(docs, "episode")
    assert doc["n"] == "1 March 2019"
    assert doc["s"] == "Mahler at the BBC Proms"
    assert doc["u"] == "/episode/2019/03/01/"
    assert doc["w"] == 0


def test_date_shaped_subtitles_are_dropped():
    """2,085 pre-2014 rows carry '30/11/2009' as their subtitle -- noise, and
    it would collide with the date recogniser."""
    for junk in ("30/11/2009", "22/12/2010", "05.01.2009", "1-2-09"):
        docs = ttn_search_index.build_catalogue(
            _ep_db([("m001", "2009-11-30", junk)]))
        assert _by_kind(docs, "episode") == [], junk


def test_literal_through_the_night_subtitle_is_dropped():
    docs = ttn_search_index.build_catalogue(
        _ep_db([("m001", "2019-03-01", "Through the Night")]))
    assert _by_kind(docs, "episode") == []


def test_title_plus_date_subtitles_are_dropped():
    """10 rows from the 2008 floor era carry the programme title followed by
    the broadcast date ('Through the Night 28/09/2008') -- zero editorial
    content, caught by neither _DATE_SHAPED (anchored) nor _NULL_SUBTITLE
    (equality check)."""
    for variant in ("Through the Night 28/09/2008", "Through the Night, 28-09-2008"):
        docs = ttn_search_index.build_catalogue(
            _ep_db([("m001", "2008-09-28", variant)]))
        assert _by_kind(docs, "episode") == [], variant


def test_title_plus_date_guard_keeps_real_subtitles():
    """A subtitle that starts with 'Through the Night' but carries real
    editorial text must still produce a document."""
    docs = ttn_search_index.build_catalogue(
        _ep_db([("m001", "2019-03-01", "Through the Night: Mahler from Oslo")]))
    doc, = _by_kind(docs, "episode")
    assert doc["s"] == "Through the Night: Mahler from Oslo"


def test_empty_subtitle_produces_no_document():
    docs = ttn_search_index.build_catalogue(
        _ep_db([("m001", "2019-03-01", ""), ("m002", "2019-03-02", None)]))
    assert _by_kind(docs, "episode") == []


def test_multi_pid_date_yields_one_document_with_joined_subtitles():
    """7 dates carry 2-3 pids; url_for('episode', date) groups them onto one
    page, so they must not produce two competing search results."""
    docs = ttn_search_index.build_catalogue(_ep_db([
        ("m001", "2021-10-31", "Music for the Hours"),
        ("m002", "2021-10-31", "Canonical Hours: Matins"),
    ]))
    doc, = _by_kind(docs, "episode")
    assert doc["u"] == "/episode/2021/10/31/"
    assert "Music for the Hours" in doc["s"]
    assert "Canonical Hours: Matins" in doc["s"]


def test_multi_pid_date_deduplicates_repeated_subtitles():
    docs = ttn_search_index.build_catalogue(_ep_db([
        ("m001", "2021-10-31", "Same Night"),
        ("m002", "2021-10-31", "Same Night"),
    ]))
    doc, = _by_kind(docs, "episode")
    assert doc["s"] == "Same Night"


def test_multi_pid_date_drops_only_the_junk_half():
    docs = ttn_search_index.build_catalogue(_ep_db([
        ("m001", "2013-06-01", "30/11/2009"),
        ("m002", "2013-06-01", "Mahler from Oslo"),
    ]))
    doc, = _by_kind(docs, "episode")
    assert doc["s"] == "Mahler from Oslo"


def test_episode_alias_field_carries_fold_of_subtitle():
    """The subtitle is the searchable text, so it must reach the alias field
    ascii-folded -- 'Dvorak and Bartok from Stockholm' must match the real
    'Dvořák and Bartók from Stockholm'."""
    docs = ttn_search_index.build_catalogue(_ep_db([
        ("m001", "2019-03-01", "Dvořák and Bartók from Stockholm")]))
    doc, = _by_kind(docs, "episode")
    assert "dvorak and bartok from stockholm" in doc["a"]


def test_write_catalogue_writes_valid_json_and_returns_count(tmp_path):
    conn = _db()
    n = ttn_search_index.write_catalogue(conn, str(tmp_path))
    path = tmp_path / "search-index.json"
    assert path.exists()
    docs = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(docs, list)
    assert len(docs) == n
    assert all("k" in d and "n" in d and "u" in d for d in docs)


def test_write_catalogue_is_byte_reproducible(tmp_path):
    """An unchanged catalogue must not churn the rsync -- the renderer's
    write-if-changed contract depends on stable output."""
    conn = _db()
    ttn_search_index.write_catalogue(conn, str(tmp_path))
    first = (tmp_path / "search-index.json").read_bytes()
    ttn_search_index.write_catalogue(conn, str(tmp_path))
    assert (tmp_path / "search-index.json").read_bytes() == first


def test_write_catalogue_leaves_no_tmp_file(tmp_path):
    ttn_search_index.write_catalogue(_db(), str(tmp_path))
    assert [p.name for p in tmp_path.iterdir()] == ["search-index.json"]


def test_write_catalogue_skips_the_write_when_unchanged(tmp_path):
    """Review Finding 6: an unchanged catalogue must not even get a fresh
    mtime, or `rsync -az` re-checksums the full 5.4 MB every night for
    nothing. write_if_changed's mtime-preserving skip is the actual fix --
    byte-reproducibility alone (the test above) doesn't prove it."""
    conn = _db()
    ttn_search_index.write_catalogue(conn, str(tmp_path))
    path = tmp_path / "search-index.json"
    mtime_before = path.stat().st_mtime_ns
    ttn_search_index.write_catalogue(conn, str(tmp_path))
    assert path.stat().st_mtime_ns == mtime_before


# query -> the URL that must rank first. Every case except 'brahms' is a
# CURRENTLY FAILING Pagefind result, measured 2026-07-29 by querying the live
# index headlessly (see the design doc). 'brahms' ranks correctly under
# Pagefind and is here to catch a regression, not to prove an improvement.
RANKING_CASES = [
    ("dvorak", "/composer/antonin-dvorak/"),
    ("mozart", "/composer/wolfgang-amadeus-mozart/"),
    ("chopin", "/composer/frederic-chopin/"),
    ("sibelius", "/composer/jean-sibelius/"),
    ("brahms", "/composer/johannes-brahms/"),
]


def _skip_unless_node():
    """node is fnm-resolved on this host, so a fresh shell (cron, a bare CI
    runner) may not have it on PATH. Without this, `subprocess.run(["node",
    ...])` raises FileNotFoundError, and the documented pre-merge gate
    (`pytest -m live`, CLAUDE.md) crashes rather than skipping --
    indistinguishable at a glance from a real ranking failure."""
    if not shutil.which("node"):
        pytest.skip("node not on PATH (fnm-resolved on this host)")


def _skip_unless_runnable():
    """Both guards a live-ranking test needs against the REAL catalogue: the
    file itself, built by `ttn_data.py site`, and node (see _skip_unless_node)."""
    if not os.path.exists("dist/search-index.json"):
        pytest.skip("no dist/search-index.json -- run `ttn_data.py site` first")
    _skip_unless_node()


@pytest.mark.live
def test_ranking_regressions_against_the_real_catalogue():
    """The relevance floor. Runs the REAL ranking function (static/search.js)
    over the REAL catalogue via node, because porting the ranking to Python
    for testability would create a second implementation free to diverge."""
    _skip_unless_runnable()

    cases = [{"q": q, "expect": u} for q, u in RANKING_CASES]
    proc = subprocess.run(
        ["node", "ttn_rank_check.mjs", "dist/search-index.json"],
        input=json.dumps(cases), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"rank_check failed:\n{proc.stderr}"

    results = json.loads(proc.stdout)
    # A crashed/empty harness output must not read as a clean pass.
    assert len(results) == len(RANKING_CASES)
    failures = [r for r in results if not r["ok"]]
    assert not failures, "ranking regressions:\n" + "\n".join(
        f"  {r['q']!r}: expected {r['expect']}, got {r['got']}"
        for r in failures)


@pytest.mark.live
def test_multi_term_query_finds_an_episode():
    """'mahler proms' matches 28 nights via the episode subtitle -- a result
    set no page surfaces today. AND-combining is what makes it work: OR gives
    557 hits dominated by Mahler works."""
    _skip_unless_runnable()

    proc = subprocess.run(
        ["node", "ttn_rank_check.mjs", "dist/search-index.json"],
        input=json.dumps([{"q": "mahler proms", "expect_prefix": "/episode/"}]),
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    result, = json.loads(proc.stdout)
    assert result["ok"], f"expected an /episode/ URL, got {result['got']}"


@pytest.mark.live
def test_or_fallback_fires_when_and_is_too_thin():
    """Deleting the whole OR-fallback branch currently breaks nothing the
    other tests check -- prove it fires. 'dvorak zzzznonexistent' yields 0
    hits under AND (the second term matches nothing real), so a non-empty,
    correctly-topped result is reachable only via the OR fallback."""
    _skip_unless_runnable()

    proc = subprocess.run(
        ["node", "ttn_rank_check.mjs", "dist/search-index.json"],
        input=json.dumps([{"q": "dvorak zzzznonexistent",
                            "expect": "/composer/antonin-dvorak/"}]),
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    result, = json.loads(proc.stdout)
    assert result["n_hits"] > 0
    assert result["ok"], f"expected the Dvorak composer page, got {result['got']}"


@pytest.mark.live
def test_bare_year_still_reaches_the_year_page():
    """Browser-pass Finding B's critical regression guard, proven end-to-end
    against the REAL catalogue and the real runSearch (not just the
    isDateShaped unit check in test_date_shape_diverts_lexical_search_but_
    bare_year_not_shaped): 'a bare year must keep working... verify this
    explicitly, because breaking it would be a worse regression than the bug
    you are fixing.' A bare year is not date-shaped (every date format needs
    a month+day component too), so it must still flow through runSearch
    exactly as before this fix wave. Deliberately a SEPARATE test rather
    than an addition to RANKING_CASES/test_ranking_regressions_against_the_
    real_catalogue -- that list is the pinned ranking-core regression floor
    and is not to be touched (this test only exercises the isDateShaped
    gate added around runSearch, not the ranking function itself)."""
    _skip_unless_runnable()

    proc = subprocess.run(
        ["node", "ttn_rank_check.mjs", "dist/search-index.json"],
        input=json.dumps([{"q": "2019", "expect": "/year/2019/"}]),
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    result, = json.loads(proc.stdout)
    assert result["ok"], f"expected /year/2019/, got {result['got']}"


@pytest.mark.live
def test_exact_pin_word_boundary_rejects_partial_word_match():
    """Guards nameWords itself: 'vorak' (a substring of 'dvorak') must never
    appear as if it were its own word. Necessary but NOT sufficient -- this
    is a tautology against a widening that bypasses nameWords entirely (see
    the runSearch-level test below, which is the one that actually closes
    task-4 review Finding 4). No catalogue needed."""
    _skip_unless_node()

    script = (
        "globalThis.window = globalThis;"
        "globalThis.MiniSearch = require(process.cwd() + '/static/minisearch.min.js');"
        "require(process.cwd() + '/static/search.js');"
        "var w = globalThis.TTNSearch.nameWords('Dvorak');"
        "console.log(JSON.stringify("
        "  w.indexOf('vorak') === -1 && w.indexOf('dvorak') !== -1));"
    )
    proc = subprocess.run(["node", "-e", script],
                           capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) is True, (
        "nameWords must yield whole words only -- 'vorak' (a substring of "
        "'dvorak') must not appear as if it were its own word")


@pytest.mark.live
def test_date_shape_diverts_lexical_search_but_bare_year_does_not():
    """Browser-pass Finding B: a date-shaped query (valid or not) must never
    reach the lexical search -- 'fuzzy: 0.2' turns a 4-digit year fragment
    into a false-positive match on every OTHER 4-digit year, so
    '2019-02-30' (an impossible date) came back with 2,526 hits topped by
    unrelated /year/2011/, /year/2012/, etc. isDateShaped is the structural
    gate for that diversion; the critical property is that a BARE year is
    NOT date-shaped (every format needs a month+day component too), or
    '2019' -> /year/2019/ -- today's correct behaviour -- breaks. No
    catalogue file needed; mirrors nameWords' shape above."""
    _skip_unless_node()

    script = (
        "globalThis.window = globalThis;"
        "globalThis.MiniSearch = require(process.cwd() + '/static/minisearch.min.js');"
        "require(process.cwd() + '/static/search.js');"
        "var S = globalThis.TTNSearch;"
        "console.log(JSON.stringify({"
        "  shaped_valid: S.isDateShaped('2019-03-14'),"
        "  shaped_invalid: S.isDateShaped('2019-02-30'),"
        "  shaped_slash: S.isDateShaped('14/03/2019'),"
        "  shaped_month_name: S.isDateShaped('14 March 2019'),"
        "  bare_year_not_shaped: S.isDateShaped('2019'),"
        "  plain_word_not_shaped: S.isDateShaped('mahler'),"
        "  parsed_valid: (S.parseDate('2019-03-14') || {}).date || null,"
        "  parsed_invalid: S.parseDate('2019-02-30'),"
        "  parsed_bare_year: S.parseDate('2019')"
        "}));"
    )
    proc = subprocess.run(["node", "-e", script],
                           capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)

    assert out["shaped_valid"] is True
    # The load-bearing case: STRUCTURALLY shaped even though the date is
    # impossible -- shape and validity are deliberately separate questions.
    assert out["shaped_invalid"] is True
    assert out["shaped_slash"] is True
    assert out["shaped_month_name"] is True

    # The critical regression guard the coordinator called out explicitly:
    # a bare year must NOT be date-shaped, or it stops reaching /year/2019/.
    assert out["bare_year_not_shaped"] is False
    assert out["plain_word_not_shaped"] is False

    assert out["parsed_valid"] == "2019-03-14"
    assert out["parsed_invalid"] is None
    assert out["parsed_bare_year"] is None


@pytest.mark.live
def test_search_page_status_distinguishes_loading_from_no_matches():
    """/search/'s status line (task-6 review Finding 1; extended by the final
    whole-branch review's Finding 1 for the too-short state, and the browser-
    pass Finding B for the invalid-date state): searchPageStatus is a pure
    function of (query, catalogueState, hits, n), unit-testable without a
    DOM. Pins the exact bug review caught -- a non-empty query with zero
    hits while the catalogue fetch is still in flight (index: null,
    failed: false) must say it's LOADING, not that the search ran and found
    nothing -- and a 1-2 character query (below MIN_QUERY_LENGTH, which
    run() never even passes to runSearch) must say it's too short, not that
    the search ran and found nothing. No catalogue file needed, mirrors
    test_exact_pin_word_boundary_rejects_partial_word_match's shape."""
    _skip_unless_node()

    script = (
        "globalThis.window = globalThis;"
        "globalThis.MiniSearch = require(process.cwd() + '/static/minisearch.min.js');"
        "require(process.cwd() + '/static/search.js');"
        "var f = globalThis.TTNSearch.searchPageStatus;"
        "console.log(JSON.stringify({"
        "  loading: f('dvorak', {failed: false, index: null}, [], 0),"
        "  no_query: f('', {failed: false, index: null}, [], 0),"
        "  too_short_loading: f('be', {failed: false, index: null}, [], 0),"
        "  too_short_loaded: f('be', {failed: false, index: {}}, [], 0),"
        "  no_matches: f('zzz', {failed: false, index: {}}, [], 0),"
        "  one_result: f('dvorak', {failed: false, index: {}}, [{}], 1),"
        "  many_results: f('aaaa', {failed: false, index: {}}, new Array(250), 250),"
        "  failed_overrides_query: f('dvorak', {failed: true, index: null}, [], 0),"
        "  failed_overrides_no_query: f('', {failed: true, index: null}, [], 0),"
        "  failed_overrides_too_short: f('be', {failed: true, index: null}, [], 0),"
        "  invalid_date: f('2019-02-30', {failed: false, index: {}}, [], 0),"
        "  invalid_date_ignores_hits: f('2019-02-30', {failed: false, index: {}}, [{}], 1),"
        "  invalid_date_loading: f('2019-02-30', {failed: false, index: null}, [], 0),"
        "  invalid_date_failed: f('2019-02-30', {failed: true, index: null}, [], 0),"
        "  valid_date_shows_count: f('2019-03-14', {failed: false, index: {}}, [{}], 1)"
        "}));"
    )
    proc = subprocess.run(["node", "-e", script],
                           capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)

    # The bug: a query typed before the catalogue arrives must read as
    # "loading", never as "no matches" -- the two are indistinguishable by
    # hits.length alone (both are []), which is exactly what collapsed them.
    assert out["loading"] == "Loading the search index…"
    assert "No matches" not in out["loading"]

    assert out["no_query"] == "Type to search works, composers, performers and nights."

    # The too-short state must win over BOTH "no matches" and "loading" --
    # a 1-2 character query never reaches runSearch either way, so neither
    # of those messages is true of it.
    too_short_msg = out["too_short_loading"]
    assert "No matches" not in too_short_msg
    assert "Loading" not in too_short_msg
    assert out["too_short_loaded"] == too_short_msg

    assert out["no_matches"] == "No matches for “zzz”."
    assert out["one_result"] == "1 result"
    assert out["many_results"] == "250 results (showing the first 200)"
    # A failed fetch is reported regardless of what's typed -- it's a
    # permanent state, not something more query-typing can fix.
    assert out["failed_overrides_query"] == "Search is unavailable on this build."
    assert out["failed_overrides_no_query"] == "Search is unavailable on this build."
    assert out["failed_overrides_too_short"] == "Search is unavailable on this build."

    # Browser-pass Finding B: an impossible date must be reported as such,
    # never as "No matches" (the two ARE distinguishable here, unlike the
    # loading/no-matches pair above: hits stays [] either way, so without
    # this branch a bogus date reads exactly like a real empty search).
    assert out["invalid_date"] == "“2019-02-30” isn’t a real date."
    assert "No matches" not in out["invalid_date"]
    # The message is about the QUERY SHAPE, not the hit count -- a caller
    # that (incorrectly) passed hits through anyway must not flip the message.
    assert out["invalid_date_ignores_hits"] == out["invalid_date"]
    # Must not mask failed or loading -- both stay reportable even for a
    # date-shaped-but-invalid query, per the coordinator's explicit ordering.
    assert out["invalid_date_loading"] == "Loading the search index…"
    assert out["invalid_date_failed"] == "Search is unavailable on this build."
    # A VALID date is not this branch at all -- run() gives it exactly one
    # hit (the jump row), so it reads as an ordinary single-result count.
    assert out["valid_date_shows_count"] == "1 result"


@pytest.mark.live
def test_exact_pin_word_boundary_via_runsearch(tmp_path):
    """The test that actually closes Finding 4. The nameWords test above
    checks a helper in isolation -- it can't see a regression that bypasses
    nameWords, e.g. widening the pin's predicate (static/search.js `isExact`)
    from a word-boundary check to a raw substring test
    (`fold(h.n).indexOf(folded) !== -1`). This drives a synthetic two-document
    catalogue through the REAL runSearch, where the pin's actual predicate
    runs, and needs no real catalogue -- ttn_rank_check.mjs takes any JSON
    file as argv[2].

    doc A: 'Mozartiana', 100,000 airings -- 'mozart' is a SUBSTRING of A's
           name but not a whole WORD of it.
    doc B: 'Wolfgang Amadeus Mozart', 10 airings -- 'mozart' IS a whole word.

    Both are kind 'composer', so the kind prior cancels and only the pin's
    width can decide the winner against a 10,000:1 airings gap:

    - word-boundary pin (correct): only B is exact -> B is pinned above A.
    - substring pin (the regression): both are exact -> A's airings prior
      wins the in-bucket sort -> A wins.

    So `top == '/composer/b/'` holds under the current code and would fail
    under exactly the widening this finding warned about -- verified by a
    deliberate break, see the task-4 report."""
    _skip_unless_node()

    docs = [
        {"k": "composer", "n": "Mozartiana", "a": "mozartiana",
         "u": "/composer/a/", "w": 100000},
        {"k": "composer", "n": "Wolfgang Amadeus Mozart",
         "a": "wolfgang amadeus mozart", "u": "/composer/b/", "w": 10},
    ]
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(docs), encoding="utf-8")

    proc = subprocess.run(
        ["node", "ttn_rank_check.mjs", str(fixture)],
        input=json.dumps([{"q": "mozart", "expect": "/composer/b/"}]),
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    result, = json.loads(proc.stdout)
    assert result["ok"], (
        f"expected /composer/b/ (word-boundary pin), got {result['got']} -- "
        "the pin's word boundary has regressed to a substring test")
