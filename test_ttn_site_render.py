"""Tests for ttn_site_render: URL authority + dist path mapping +
write-if-changed (website Phase 2, task 1).

Run: uv run --with pytest pytest test_ttn_site_render.py
"""
import pytest

from ttn_site_render import url_for, dist_path, write_if_changed, browse_url_name


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
