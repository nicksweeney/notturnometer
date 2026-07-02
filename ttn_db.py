"""Shared CLI guard for opening an existing SQLite database.

sqlite3.connect() silently CREATES an empty file for a missing path, which
then surfaces as a confusing "no such table: tracks" — so every tool that
operates on an already-scraped DB errors cleanly up front instead.
(ttn_scrape is the deliberate exception: creating the DB on first run is
its job.) Kept dependency-free (os + sqlite3 only) so the kitchen tools can
import it without ttn_analyze's alias-table import tax.
"""
import os
import sqlite3


def ensure_db_exists(path, parser):
    """Error cleanly through `parser` (argparse-style .error, which exits)
    when no file exists at `path`."""
    if not os.path.isfile(path):
        parser.error(f"database not found: {path}")


def open_db(path, parser):
    """sqlite3.connect(path), guarded by ensure_db_exists."""
    ensure_db_exists(path, parser)
    return sqlite3.connect(path)
