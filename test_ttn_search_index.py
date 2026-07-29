"""ttn_search_index tests -- the search catalogue builder."""
import sqlite3

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
