"""Tests for ttn_scrape seed discovery (pure selection logic; no network)."""
import datetime as dt
import json

import pytest

from ttn_scrape import (
    _choose_seed_pid,
    _resolve_seed_date,
    _segment_clock_time,
    SPARSE_TRACK_THRESHOLD,
    TIME_RE,
    init_db,
    parse_tracks,
    parse_tracks_inline,
    rebuild_tracks,
    render_walk_summary,
    tracks_from_segments,
    walk_backwards,
)
from ttn_segments import ensure_segments_schema

UTC = dt.timezone.utc


def _b(pid, start):
    return {"start": start, "programme": {"pid": pid}}


def test_choose_seed_prefers_most_recent_aired():
    # now is midday 2026-06-02 UTC; the two 00:30 broadcasts have aired,
    # the 06-03/06-04 ones have not.
    now = dt.datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bs = [
        _b("aired_old", "2026-06-01T00:30:00+01:00"),
        _b("aired_new", "2026-06-02T00:30:00+01:00"),   # most recent aired
        _b("future1",   "2026-06-03T00:30:00+01:00"),
        _b("future2",   "2026-06-04T00:30:00+01:00"),
    ]
    assert _choose_seed_pid(bs, now) == "aired_new"


def test_choose_seed_falls_back_to_soonest_upcoming_when_none_aired():
    # now is before any listed broadcast → none have aired; take the soonest.
    now = dt.datetime(2026, 6, 1, 23, 0, tzinfo=UTC)
    bs = [
        _b("future_late", "2026-06-04T00:30:00+01:00"),
        _b("future_soon", "2026-06-02T00:30:00+01:00"),
    ]
    assert _choose_seed_pid(bs, now) == "future_soon"


def test_choose_seed_empty_returns_none():
    now = dt.datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    assert _choose_seed_pid([], now) is None


def test_choose_seed_ignores_entry_without_pid():
    now = dt.datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bs = [{"start": "2026-06-02T00:30:00+01:00", "programme": {}}]
    assert _choose_seed_pid(bs, now) is None


# ---------- seed-date anchoring (--days) ------------------------------------


def test_resolve_seed_date_reads_cached_seed_without_network():
    # A cached seed: --days must anchor on the seed's broadcast date, so the
    # resolver returns it straight from the DB and never touches `session`.
    c = init_db(":memory:")
    c.execute(
        "INSERT INTO episodes (pid, broadcast_date) VALUES (?, ?)",
        ("b07b27lk", "2016-05-16T00:30:00+01:00"))
    c.commit()
    # session=None proves the cached path makes no request.
    got = _resolve_seed_date(None, c, "b07b27lk")
    assert got == dt.datetime(2016, 5, 16, 0, 30,
                              tzinfo=dt.timezone(dt.timedelta(hours=1)))
    c.close()


def test_resolve_seed_date_anchors_cutoff_to_seed_not_today():
    # Regression for the --days-from-today bug: with a 2016 seed, the cutoff is
    # `seed_date - days`, so 1523 days reaches 2012-03-15 regardless of `now`.
    c = init_db(":memory:")
    c.execute(
        "INSERT INTO episodes (pid, broadcast_date) VALUES (?, ?)",
        ("b07b27lk", "2016-05-16T00:30:00+01:00"))
    c.commit()
    anchor = _resolve_seed_date(None, c, "b07b27lk")
    cutoff = anchor - dt.timedelta(days=1523)
    assert cutoff.date() == dt.date(2012, 3, 15)
    c.close()


def test_resolve_seed_date_does_not_store_unaired_seed(monkeypatch):
    # The discovered seed is usually the soonest UPCOMING episode: its date must
    # still anchor the cutoff, but it must NOT be stored (provisional synopsis,
    # no segments) — that's what let m002xfhf leak into the DB before the fix.
    import ttn_scrape
    now = dt.datetime(2026, 6, 17, 19, 0, tzinfo=UTC)
    prog = {"pid": "future", "first_broadcast_date": "2026-06-18T00:30:00+01:00",
            "peers": {"previous": {"pid": "aired"}}, "long_synopsis": ""}
    monkeypatch.setattr(ttn_scrape, "fetch_one", lambda session, pid: {"programme": prog})
    c = init_db(":memory:")
    anchor = _resolve_seed_date(None, c, "future", now=now)
    assert anchor == dt.datetime(2026, 6, 18, 0, 30,
                                 tzinfo=dt.timezone(dt.timedelta(hours=1)))  # date anchored
    assert c.execute("SELECT COUNT(*) FROM episodes WHERE pid='future'").fetchone()[0] == 0  # not stored
    c.close()


def test_resolve_seed_date_returns_none_for_unknown_uncached_seed():
    # Uncached seed with no usable fetch result → None (main() then falls back
    # to `now`). A stub session that yields nothing stands in for a 404.
    class _NoData:
        def get(self, *a, **k):
            raise AssertionError("should not be reached in this test")
    c = init_db(":memory:")
    c.commit()
    # broadcast_date NULL row is treated as uncached and falls through to fetch.
    c.execute("INSERT INTO episodes (pid) VALUES ('ghost')")
    c.commit()
    import ttn_scrape
    orig = ttn_scrape.fetch_one
    ttn_scrape.fetch_one = lambda session, pid: None
    try:
        assert _resolve_seed_date(_NoData(), c, "ghost") is None
    finally:
        ttn_scrape.fetch_one = orig
    c.close()


# ---------- end-of-run walk summary ----------------------------------------


def test_render_walk_summary_lists_zero_and_sparse():
    result = {"fetched": 1471, "skipped": 1,
              "newest_date": "2016-05-15", "oldest_date": "2012-03-15",
              "anomalies": [("b04jjq83", "2014-10-04", 0, "Musica Aeterna"),
                            ("b0xsparse", "2015-10-28", 5, "Short night")],
              "stop": "cutoff"}
    out = render_walk_summary(result)
    assert "fetched: 1,471 new   skipped: 1 cached" in out
    assert "range: 2012-03-15 → 2016-05-15" in out
    assert 'zero-track (1): b04jjq83 2014-10-04 "Musica Aeterna"' in out
    assert f"sparse <{SPARSE_TRACK_THRESHOLD} (1): b0xsparse 2015-10-28 (5)" in out


def test_render_walk_summary_clean_run():
    result = {"fetched": 5, "skipped": 0, "newest_date": "2020-01-05",
              "oldest_date": "2020-01-01", "anomalies": [], "stop": "exhausted"}
    out = render_walk_summary(result)
    assert "no track-count anomalies" in out


def test_walk_backwards_cached_chain_counts_skips(capsys):
    # A fully-cached 3-episode chain: no network (session=None), the walk skips
    # each and returns a result with the skip count and an 'exhausted' stop.
    c = init_db(":memory:")
    for pid, prev, date in [("ep1", "ep2", "2020-01-03T01:00:00Z"),
                            ("ep2", "ep3", "2020-01-02T01:00:00Z"),
                            ("ep3", None, "2020-01-01T01:00:00Z")]:
        c.execute("INSERT INTO episodes (pid, previous_pid, broadcast_date) "
                  "VALUES (?, ?, ?)", (pid, prev, date))
    c.commit()
    cutoff = dt.datetime(2000, 1, 1, tzinfo=UTC)     # below all -> never trips
    result = walk_backwards(None, c, "ep1", cutoff, 0, None)
    assert result["skipped"] == 3 and result["fetched"] == 0
    assert result["stop"] == "exhausted" and result["anomalies"] == []
    c.close()


def test_walk_backwards_skips_unaired_seed_anchor_only(monkeypatch, capsys):
    # The discovered seed is the soonest UPCOMING episode (upcoming.json lists
    # only future broadcasts): it must be used as an ANCHOR only — fetched to
    # read peers.previous, never stored — and the walk stores from the aired one.
    import ttn_scrape
    now = dt.datetime(2026, 6, 17, 19, 0, tzinfo=UTC)
    chain = {
        # starts 2026-06-18 00:30 BST -> after `now` -> anchor only, not stored
        "future": {"pid": "future",
                   "first_broadcast_date": "2026-06-18T00:30:00+01:00",
                   "peers": {"previous": {"pid": "aired"}}, "long_synopsis": ""},
        # aired 2026-06-17 00:30 BST -> before `now` -> stored
        "aired": {"pid": "aired",
                  "first_broadcast_date": "2026-06-17T00:30:00+01:00",
                  "peers": {"previous": {"pid": None}}, "long_synopsis": ""},
    }
    monkeypatch.setattr(ttn_scrape, "fetch_one",
                        lambda session, pid: {"programme": chain[pid]} if pid in chain else None)
    c = init_db(":memory:")
    cutoff = dt.datetime(2000, 1, 1, tzinfo=UTC)
    result = walk_backwards(None, c, "future", cutoff, 0, None, now=now)
    assert c.execute("SELECT COUNT(*) FROM episodes WHERE pid='future'").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM episodes WHERE pid='aired'").fetchone()[0] == 1
    assert result["skipped_future"] == 1 and result["fetched"] == 1
    c.close()


def test_walk_backwards_stores_seed_once_aired(monkeypatch):
    # Boundary: an episode whose start is at/just before `now` is aired -> stored
    # (the mid-broadcast case — synopsis is final; segments come via the segments
    # stage). Confirms the gate keys on absolute time, not a naive date string.
    import ttn_scrape
    now = dt.datetime(2026, 6, 18, 2, 0, tzinfo=UTC)   # 02:00 UTC, mid-broadcast
    chain = {"airing": {"pid": "airing",
                        "first_broadcast_date": "2026-06-18T00:30:00+01:00",  # started 23:30 UTC
                        "peers": {"previous": {"pid": None}}, "long_synopsis": ""}}
    monkeypatch.setattr(ttn_scrape, "fetch_one",
                        lambda session, pid: {"programme": chain[pid]} if pid in chain else None)
    c = init_db(":memory:")
    cutoff = dt.datetime(2000, 1, 1, tzinfo=UTC)
    result = walk_backwards(None, c, "airing", cutoff, 0, None, now=now)
    assert c.execute("SELECT COUNT(*) FROM episodes WHERE pid='airing'").fetchone()[0] == 1
    assert result["skipped_future"] == 0 and result["fetched"] == 1
    c.close()


# ---------- segment_events backfill (allowlisted unparseable episodes) ------


def _seg_db():
    c = init_db(":memory:")
    ensure_segments_schema(c)
    return c


def _add_segment(c, pid, offset, title, composer, contribs):
    c.execute(
        "INSERT INTO segment_events (episode_pid, version_offset, track_title, "
        "composer_name, contributions_json) VALUES (?, ?, ?, ?, ?)",
        (pid, offset, title, composer, json.dumps(contribs)))


def test_segment_clock_time_synthesizes_from_offset():
    assert _segment_clock_time("2016-11-21T00:30:00Z", 0) == "12:30 AM"
    assert _segment_clock_time("2016-11-21T00:30:00Z", 70) == "12:31 AM"
    assert _segment_clock_time("2014-10-04T01:00:00Z", 72) == "1:01 AM"
    assert _segment_clock_time("2016-11-21T00:30:00Z", None) == ""
    assert _segment_clock_time(None, 0) == ""


def test_tracks_from_segments_orders_by_offset_and_splits_roles():
    c = _seg_db()
    c.execute("INSERT INTO episodes (pid, broadcast_date) "
              "VALUES ('b0833vgj', '2016-11-21T00:30:00Z')")
    # inserted out of offset order to prove version_offset ordering
    _add_segment(c, "b0833vgj", 70, "Mein Odem", "Max Reger",
                 [{"name": "Max Reger", "role": "Composer"},
                  {"name": "SWR Vocal Ensemble", "role": "Choir"},
                  {"name": "Frieder Bernius", "role": "Director"}])
    _add_segment(c, "b0833vgj", 0, "La Cheminee", "Darius Milhaud",
                 [{"name": "Darius Milhaud", "role": "Composer"},
                  {"name": "BBC Concert Orchestra", "role": "Ensemble"}])
    c.commit()
    tr = tracks_from_segments(c, "b0833vgj")
    assert [t["composer"] for t in tr] == ["Darius Milhaud", "Max Reger"]
    assert tr[0]["time"] == "12:30 AM" and tr[1]["time"] == "12:31 AM"
    assert tr[0]["title"] == "La Cheminee"
    assert tr[0]["performers"] == "BBC Concert Orchestra (ensemble)"
    assert tr[1]["contributors"] == [("Max Reger", "composer")]
    assert tr[1]["performers"] == \
        "SWR Vocal Ensemble (choir), Frieder Bernius (director)"


def test_rebuild_tracks_falls_back_to_segments_for_allowlisted_pid():
    c = _seg_db()
    c.execute("INSERT INTO episodes (pid, broadcast_date) "
              "VALUES ('b0833vgj', '2016-11-21T00:30:00Z')")
    _add_segment(c, "b0833vgj", 0, "La Cheminee", "Darius Milhaud",
                 [{"name": "Darius Milhaud", "role": "Composer"}])
    c.commit()
    # the inline-Composer dot-time format the parser can't read -> empty parse
    rebuild_tracks(c, "b0833vgj", "12.31 Reger: Title, Op X")
    assert c.execute("SELECT composer, title, time_str FROM tracks "
                     "WHERE episode_pid='b0833vgj'").fetchall() == \
        [("Darius Milhaud", "La Cheminee", "12:30 AM")]


def test_rebuild_tracks_no_segment_fallback_for_unlisted_pid():
    c = _seg_db()
    c.execute("INSERT INTO episodes (pid, broadcast_date) "
              "VALUES ('b06cb8q0', '2015-09-26T00:00:00Z')")
    _add_segment(c, "b06cb8q0", 0, "X", "Y",
                 [{"name": "Y", "role": "Composer"}])
    c.commit()
    rebuild_tracks(c, "b06cb8q0", "")        # unparseable AND not allowlisted
    assert c.execute("SELECT COUNT(*) FROM tracks WHERE "
                     "episode_pid='b06cb8q0'").fetchone()[0] == 0


def test_segment_backfill_survives_a_reparse():
    # Durability: a second rebuild_tracks pass (what ttn_reparse does) must
    # reproduce the backfill, not wipe it.
    c = _seg_db()
    c.execute("INSERT INTO episodes (pid, broadcast_date) "
              "VALUES ('b04jjq83', '2014-10-04T01:00:00Z')")
    _add_segment(c, "b04jjq83", 72, "Concerto a 5", "Tomaso Giovanni Albinoni",
                 [{"name": "Tomaso Giovanni Albinoni", "role": "Composer"}])
    c.commit()
    rebuild_tracks(c, "b04jjq83", "")
    rebuild_tracks(c, "b04jjq83", "")        # reparse pass
    assert c.execute("SELECT composer FROM tracks WHERE "
                     "episode_pid='b04jjq83'").fetchall() == \
        [("Tomaso Giovanni Albinoni",)]


# ---------- TIME_RE / bare-time recovery -----------------------------------


def test_time_re_accepts_malformed_and_bare_variants():
    # Bucket A: meridiem present, dot separator / stray colon / no space.
    for s in ["1.29am", "02.00AM", "03.08 AM", "02:46:AM"]:
        assert TIME_RE.match(s), s
    # Bucket B: no meridiem at all (colon, colon+TZ, dot).
    for s in ["12:31", "01:00", "01:00 BST", "01:00 GMT", "12.31"]:
        assert TIME_RE.match(s), s


def test_time_re_still_accepts_canonical_forms():
    for s in ["12:31 AM", "01:02 AM", "12:31 AM BST", "12:31AM", "11:30 PM"]:
        assert TIME_RE.match(s), s


def test_time_re_rejects_non_time_lines():
    for s in ["3 works", "Margret Köll", "Asturias & Cadiz, from 'Suite'",
              "Wolfgang Amadeus Mozart (1756-1791)", "Op 62", ""]:
        assert not TIME_RE.match(s), s


_BARE_SYNOPSIS = (
    "12:31\n"
    "Wolfgang Amadeus Mozart (1756-1791)\n"
    "Symphony No 40 in G minor, K.550\n"
    "Some Orchestra\n"
    "01:00\n"
    "Ludwig van Beethoven (1770-1827)\n"
    "Coriolan Overture, Op 62\n"
    "Another Orchestra\n"
)

_MIXED_SYNOPSIS = (
    "12:31 AM\n"
    "Wolfgang Amadeus Mozart (1756-1791)\n"
    "Symphony No 40 in G minor, K.550\n"
    "Some Orchestra\n"
    "1:00\n"
    "Ludwig van Beethoven (1770-1827)\n"
    "Coriolan Overture, Op 62\n"
    "Another Orchestra\n"
)


def test_parse_tracks_recovers_bare_time_block():
    tracks = parse_tracks(_BARE_SYNOPSIS)
    assert [(t["time"], t["composer"], t["title"]) for t in tracks] == [
        ("12:31", "Wolfgang Amadeus Mozart", "Symphony No 40 in G minor, K.550"),
        ("01:00", "Ludwig van Beethoven", "Coriolan Overture, Op 62"),
    ]


def test_parse_tracks_recovers_mixed_meridiem_block():
    # One meridiem line + one bare line in the same episode (the m000ql1y shape).
    tracks = parse_tracks(_MIXED_SYNOPSIS)
    assert [t["composer"] for t in tracks] == [
        "Wolfgang Amadeus Mozart", "Ludwig van Beethoven"]
    assert tracks[0]["time"] == "12:31 AM" and tracks[1]["time"] == "1:00"


# ---------- parse_tracks_inline (pre-2010 inline format) -------------------

# A real excerpt from b007z0nt (2007-09-16), verbatim — the canonical anchor.
_INLINE_REAL = (
    "With John Shea.\n"
    "\n"
    "1.00am\n"
    "Mussorgsky, Modest (1839-1881): Night on the Bare Mountain\n"
    "Oslo Philharmonic\n"
    "Vladimir Jurowski (conductor)\n"
    "\n"
    "1.14am\n"
    "Grieg, Edvard (1843-1907): Piano Concerto in A minor\n"
    "Boris Berezovsky (piano)\n"
    "Oslo Philharmonic\n"
    "Jukka-Pekka Saraste (conductor)\n"
)


def test_parse_tracks_inline_real_excerpt():
    tracks = parse_tracks_inline(_INLINE_REAL)
    assert [(t["time"], t["composer"], t["title"]) for t in tracks] == [
        ("1.00am", "Modest Mussorgsky", "Night on the Bare Mountain"),
        ("1.14am", "Edvard Grieg", "Piano Concerto in A minor"),
    ]
    # header line ("With John Shea.") produced no track
    assert len(tracks) == 2
    # performer lines after the composer:title line are joined
    assert tracks[0]["performers"] == "Oslo Philharmonic | Vladimir Jurowski (conductor)"
    assert tracks[1]["performers"] == (
        "Boris Berezovsky (piano) | Oslo Philharmonic | Jukka-Pekka Saraste (conductor)")


def test_parse_tracks_inline_4line_parser_misaligns_same_input():
    # Why a separate parser exists: parse_tracks reads the orchestra line as the
    # title and loses the real title (the silent count-blind misalignment trap).
    misparsed = parse_tracks(_INLINE_REAL)
    assert misparsed[0]["title"] == "Oslo Philharmonic"          # WRONG (the orchestra)
    assert parse_tracks_inline(_INLINE_REAL)[0]["title"] == "Night on the Bare Mountain"


def test_parse_tracks_inline_skips_header_variants():
    for header in ("With John Shea.", "Presented by Susan Sharpe.", "Including:"):
        syn = f"{header}\n\n1.00am\nGrieg, Edvard (1843-1907): Holberg Suite\nEnsemble\n"
        tracks = parse_tracks_inline(syn)
        assert len(tracks) == 1
        assert tracks[0]["composer"] == "Edvard Grieg"
        assert tracks[0]["title"] == "Holberg Suite"


def test_parse_tracks_inline_colon_and_dotted_times():
    syn = ("12:31 AM\nMozart, Wolfgang Amadeus (1756-1791): Adagio in B minor\n"
           "1.00am\nBach, Johann Sebastian (1685-1750): Keyboard Concerto No 5\n")
    tracks = parse_tracks_inline(syn)
    assert [t["time"] for t in tracks] == ["12:31 AM", "1.00am"]
    assert [t["composer"] for t in tracks] == [
        "Wolfgang Amadeus Mozart", "Johann Sebastian Bach"]


def test_parse_tracks_inline_title_with_colon_preserved():
    # Split is on the FIRST colon only — a title that contains one survives.
    syn = "1.00am\nBeethoven, Ludwig van (1770-1827): Symphony No 6: Pastoral\n"
    t = parse_tracks_inline(syn)[0]
    assert t["composer"] == "Ludwig van Beethoven"
    assert t["title"] == "Symphony No 6: Pastoral"


def test_parse_tracks_inline_bracket_dates():
    syn = "1.00am\nBach, Johann Sebastian [1685-1750]: Cello Suite No 1\nSoloist\n"
    t = parse_tracks_inline(syn)[0]
    assert t["composer"] == "Johann Sebastian Bach"
    assert t["title"] == "Cello Suite No 1"


def test_parse_tracks_inline_trad_and_no_performers():
    syn = "1.00am\nTrad: Kilden\n2.00am\nAnon: A Plainchant\n"
    tracks = parse_tracks_inline(syn)
    assert [(t["composer"], t["title"], t["performers"]) for t in tracks] == [
        ("Trad", "Kilden", ""), ("Anon", "A Plainchant", "")]


def test_parse_tracks_inline_bare_surname_shortform_passthrough():
    # Known limitation: a forename-less repeat yields a bare surname (not
    # forward-filled from the earlier full credit).
    syn = ("1.00am\nGrieg, Edvard (1843-1907): Piano Sonata in E minor, Op 7\n"
           "1.19am\nGrieg: Lyric Pieces (Book 1, Op 12)\n")
    tracks = parse_tracks_inline(syn)
    assert [t["composer"] for t in tracks] == ["Edvard Grieg", "Grieg"]


def test_parse_tracks_inline_contributors_shape_matches_parse_tracks():
    t = parse_tracks_inline(
        "1.00am\nMussorgsky, Modest (1839-1881): Night on the Bare Mountain\nO\n")[0]
    assert t["composer_line"] == "Mussorgsky, Modest (1839-1881)"
    assert t["contributors"][0] == ("Modest Mussorgsky", "composer")
    assert set(t) == {"time", "composer_line", "composer", "contributors",
                      "title", "performers"}


def test_parse_tracks_inline_empty():
    assert parse_tracks_inline("") == []
    assert parse_tracks_inline(None) == []


def test_parse_tracks_inline_forward_fills_continuation_set():
    # The real b00p6bp1 Lassus-set shape: composer once, then bare titles.
    syn = ("With Susan Sharpe.\n\nIncluding:\n\n"
           "1.00am\nLassus, Orlande de (1532-1594): Musica, dei donum optimi\n"
           "1.04am\nOmnia tempus habent\n"
           "1.09am\nIl etait une religieuse\n")
    tracks = parse_tracks_inline(syn)
    assert [(t["composer"], t["title"]) for t in tracks] == [
        ("Orlande de Lassus", "Musica, dei donum optimi"),
        ("Orlande de Lassus", "Omnia tempus habent"),
        ("Orlande de Lassus", "Il etait une religieuse")]


def test_parse_tracks_inline_forward_fill_resets_on_new_composer():
    syn = ("1.00am\nLassus, Orlande de (1532-1594): Matona mia cara\n"
           "1.04am\nChi chilichi?\n"                        # still Lassus
           "1.10am\nByrd, William (1543-1623): Ave verum corpus\n"
           "1.14am\nSing joyfully\n")                       # now Byrd
    assert [t["composer"] for t in parse_tracks_inline(syn)] == [
        "Orlande de Lassus", "Orlande de Lassus", "William Byrd", "William Byrd"]


def test_parse_tracks_inline_leading_continuation_stays_empty():
    # No prior credit to inherit -> empty composer (degenerate, can't be helped).
    t = parse_tracks_inline("1.00am\nA Bare Title\n")[0]
    assert t["composer"] == "" and t["title"] == "A Bare Title"


# ---------- derive_tracks format switch (pre-2010 floor) -------------------

from ttn_scrape import derive_tracks, _detect_inline_format, SYNOPSIS_FLOOR_DATE

_INLINE_TRACK = ("1.00am\n"
                 "Mussorgsky, Modest (1839-1881): Night on the Bare Mountain\n"
                 "Oslo Philharmonic\n")

# A real b00gsj8k excerpt (2009-01-17): a PRE-floor episode in the modern BLOCK
# format (composer and title on separate lines), which must NOT be inline-parsed.
_BLOCK_PRE2010 = (
    "With Jonathan Swain\n\n"
    "01:00AM\n"
    "Prokofiev, Sergey (1891-1953)\n"
    "Symphony no. 1 (Op. 25) in D major, 'Classical'\n\n"
    "01:16AM\n"
    "Tchaikovsky, Pyotr Il'yich (1840-1893)\n"
    "Concerto for violin & orchestra (Op. 35) in D major\n"
)


def test_detect_inline_format_true_for_inline():
    assert _detect_inline_format(_INLINE_REAL) is True


def test_detect_inline_format_false_for_block():
    assert _detect_inline_format(_BLOCK_PRE2010) is False


def test_detect_inline_format_continuation_set_is_inline():
    # one colon-head + bare continuations -> still inline (block heads never
    # carry a colon, so a single colon-head is decisive)
    syn = "1.00am\nLassus, Orlande de (1532-1594): Matona mia cara\n1.04am\nChi chilichi?\n"
    assert _detect_inline_format(syn) is True


def test_detect_inline_format_trad_heads_are_inline():
    assert _detect_inline_format("1.00am\nTrad: Kilden\n2.00am\nAnon: Plainchant\n") is True


def test_detect_inline_format_empty_defaults_inline():
    assert _detect_inline_format("") is True


def test_derive_tracks_pre_floor_block_format_uses_block_parser():
    # A pre-floor episode in the modern block format must route to parse_tracks
    # via content detection — inline-parsing it would strand the composers.
    c = _conn_with_episode("e_blk", "2009-01-17T01:00:00Z")
    try:
        tracks = derive_tracks(c, "e_blk", _BLOCK_PRE2010)
        assert [(t["composer"], t["title"]) for t in tracks] == [
            ("Sergey Prokofiev", "Symphony no. 1 (Op. 25) in D major, 'Classical'"),
            ("Pyotr Il'yich Tchaikovsky",
             "Concerto for violin & orchestra (Op. 35) in D major")]
    finally:
        c.close()


def _conn_with_episode(pid, bdate):
    c = init_db(":memory:")
    c.execute("INSERT INTO episodes (pid, broadcast_date) VALUES (?, ?)", (pid, bdate))
    c.commit()
    return c


def test_floor_date_is_the_cutover():
    assert SYNOPSIS_FLOOR_DATE == "2010-01-17"


def test_derive_tracks_uses_inline_parser_before_floor():
    c = _conn_with_episode("e_old", "2009-09-16T01:00:00+01:00")
    try:
        tracks = derive_tracks(c, "e_old", _INLINE_TRACK)
        assert [(t["composer"], t["title"]) for t in tracks] == [
            ("Modest Mussorgsky", "Night on the Bare Mountain")]
    finally:
        c.close()


def test_derive_tracks_uses_block_parser_on_floor():
    # The floor date itself (b00ps0x1) is the first 4-line episode -> block parser.
    # The same inline text mis-parses there (title = orchestra), proving the
    # switch routes by DATE, not content.
    c = _conn_with_episode("e_floor", "2010-01-17T01:00:00Z")
    try:
        assert derive_tracks(c, "e_floor", _INLINE_TRACK)[0]["title"] == "Oslo Philharmonic"
    finally:
        c.close()


def test_derive_tracks_missing_date_defaults_to_block():
    c = _conn_with_episode("e_nodate", None)
    try:
        block = "12:31 AM\nWolfgang Amadeus Mozart (1756-1791)\nSymphony No 40\nOrch\n"
        tracks = derive_tracks(c, "e_nodate", block)
        assert [(t["composer"], t["title"]) for t in tracks] == [
            ("Wolfgang Amadeus Mozart", "Symphony No 40")]
    finally:
        c.close()


def test_derive_tracks_switch_changes_result_for_same_input():
    old = _conn_with_episode("o", "2009-12-31T01:00:00Z")
    new = _conn_with_episode("n", "2010-06-01T01:00:00Z")
    try:
        assert derive_tracks(old, "o", _INLINE_TRACK)[0]["title"] == "Night on the Bare Mountain"
        assert derive_tracks(new, "n", _INLINE_TRACK)[0]["title"] == "Oslo Philharmonic"
    finally:
        old.close(); new.close()


# ---------- rebuild_tracks tests -------------------------------------------

_SYNOPSIS = (
    "12:31 AM\n"
    "Wolfgang Amadeus Mozart (1756-1791)\n"
    "Symphony No 40 in G minor, K.550\n"
    "Some Orchestra, Some Conductor (conductor)\n"
    "01:02 AM\n"
    "Ludwig van Beethoven (1770-1827)\n"
    "Coriolan Overture, Op 62\n"
    "Another Orchestra\n"
)


@pytest.fixture
def conn():
    c = init_db(":memory:")
    c.execute("INSERT INTO episodes (pid) VALUES ('ep1')")
    c.execute("INSERT INTO episodes (pid) VALUES ('ep2')")
    c.commit()                 # clean baseline so in_transaction test is meaningful
    yield c
    c.close()


def test_rebuild_tracks_matches_parser(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    rows = conn.execute(
        "SELECT position, composer, title FROM tracks "
        "WHERE episode_pid='ep1' ORDER BY position").fetchall()
    assert rows == [
        (0, "Wolfgang Amadeus Mozart", "Symphony No 40 in G minor, K.550"),
        (1, "Ludwig van Beethoven", "Coriolan Overture, Op 62"),
    ]


def test_rebuild_tracks_is_idempotent(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    n = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep1'").fetchone()[0]
    assert n == 2


def test_rebuild_tracks_touches_only_its_pid(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    rebuild_tracks(conn, "ep2", _SYNOPSIS)
    rebuild_tracks(conn, "ep1", "")          # ep1 now parses to 0 tracks
    assert conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep1'").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE episode_pid='ep2'").fetchone()[0] == 2


def test_rebuild_tracks_returns_parsed_dicts(conn):
    parsed = rebuild_tracks(conn, "ep1", _SYNOPSIS)
    assert parsed == parse_tracks(_SYNOPSIS)


def test_rebuild_tracks_does_not_commit(conn):
    rebuild_tracks(conn, "ep1", _SYNOPSIS)
    # baseline was committed, so a pending (uncommitted) transaction here means
    # rebuild_tracks did not commit.
    assert conn.in_transaction


def test_main_accepts_argv_not_sys_argv(monkeypatch):
    """ttn_scrape.main(argv) parses the passed list, not sys.argv (SP4d-4)."""
    import ttn_scrape
    # Poison sys.argv: if main() ignored its argument and read sys.argv, it
    # would try a real scrape. Passing --help must short-circuit via argparse.
    monkeypatch.setattr("sys.argv", ["ttn_scrape.py", "--days", "1"])
    import pytest
    with pytest.raises(SystemExit) as ei:
        ttn_scrape.main(["--help"])
    assert ei.value.code == 0
