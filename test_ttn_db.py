"""Tests for the shared missing-DB CLI guard (ttn_db) and its wiring: every
tool that operates on an already-scraped DB must refuse a missing path up
front, instead of letting sqlite3.connect() create a 0-byte file that later
fails with "no such table"."""
import importlib
import os
import sqlite3

import pytest

import ttn_db


class _Parser:
    def error(self, msg):
        raise SystemExit(f"error: {msg}")


def test_open_db_errors_and_creates_nothing(tmp_path):
    missing = str(tmp_path / "nope.sqlite")
    with pytest.raises(SystemExit):
        ttn_db.open_db(missing, _Parser())
    assert not os.path.exists(missing)


def test_open_db_opens_existing(tmp_path):
    path = str(tmp_path / "t.sqlite")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (x)")
    c.commit()
    c.close()
    conn = ttn_db.open_db(path, _Parser())
    assert conn.execute("SELECT 1").fetchone() == (1,)
    conn.close()


# Each tool's minimal argv (beyond the db positional) that would otherwise
# reach its sqlite3.connect. ttn_scrape is deliberately absent — creating
# the DB on first run is its job.
_MAINS = [
    ("ttn_audit", ["--all"]),
    ("ttn_audit_composer", ["--composer", "Liszt"]),
    ("ttn_duplicates", []),
    ("ttn_composer_duplicates", []),
    ("ttn_mbid_audit", []),
    ("ttn_bridge", []),
    ("ttn_spine", []),
    ("ttn_segments", []),
    ("ttn_reparse", []),
    ("ttn_project", ["--status"]),
    ("ttn_warm", []),
]


@pytest.mark.parametrize("mod,extra", _MAINS, ids=[m for m, _ in _MAINS])
def test_tool_mains_reject_missing_db(mod, extra, tmp_path):
    missing = str(tmp_path / "missing.sqlite")
    tool = importlib.import_module(mod)
    with pytest.raises(SystemExit):
        tool.main([missing] + extra)
    assert not os.path.exists(missing)
