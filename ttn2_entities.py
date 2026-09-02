"""ttn2_entities — P4 phase 3, task 1: the entity-layer builder.

One derivation: the ledger resolution of the text obs (ttn2_query.load_groups)
-> one work_entity per resolved (composer_key, work_key) group. Ids are
assigned once, then append-only frozen: a rebuild reconciles BY KEY (a group
whose key already maps to an entity keeps that id), new groups append ids
past the high-water mark (sorted by key for determinism), and disappeared
groups stay in place (a rebuild never deletes -- the ratification owns
removals). The entity name = the group's display title (the corpus-majority
spelling). Composer entities: prohibited (the phase-2 ruling stands).

CLI: `uv run python ttn2_entities.py` runs the build against the real DBs
and prints (n_entities, n_keys, n_appended).
"""
import argparse
import sqlite3
import sys

import ttn2_query as Q

DB = "successor.sqlite"
SRC = "ttn.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_entity (
  id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS work_entity_key (
  composer_key TEXT, work_key TEXT, work_entity_id INTEGER,
  PRIMARY KEY(composer_key, work_key));
"""


def build_entities(src=SRC, dst=DB, groups=None):
    """Rebuild work_entity + work_entity_key idempotently.

    groups: an injected load_groups() result for hermetic tests; loaded via
    ttn2_query.load_groups(src, dst) when None. Returns
    (n_entities, n_keys, n_appended)."""
    if groups is None:
        groups = Q.load_groups(src, dst)
    conn = sqlite3.connect(dst)
    try:
        conn.executescript(_SCHEMA)
        entities = dict(conn.execute("SELECT id, name FROM work_entity"))
        keys = {(ck, wk): eid for ck, wk, eid in conn.execute(
            "SELECT composer_key, work_key, work_entity_id "
            "FROM work_entity_key")}
        # the high-water mark spans BOTH tables: an orphan key row (eid
        # absent from work_entity, group absent from the current groups — the
        # one state the heal doesn't cover) must still freeze its id, else an
        # append re-mints it and points the stale key at the wrong entity
        high = max(entities.keys() | keys.values(), default=0)
        appended = 0
        for (ck, wk), g in sorted(groups.items()):
            eid = keys.get((ck, wk))
            if eid is None:
                high += 1
                eid = high
                appended += 1
                keys[(ck, wk)] = eid
            entities[eid] = g["display"][1]   # name = the display title
        # DELETE + re-INSERT inside one transaction (atomic rebuild)
        conn.execute("DELETE FROM work_entity")
        conn.execute("DELETE FROM work_entity_key")
        conn.executemany("INSERT INTO work_entity VALUES (?,?)",
                         sorted(entities.items()))
        conn.executemany("INSERT INTO work_entity_key VALUES (?,?,?)",
                         sorted((ck, wk, eid) for (ck, wk), eid in keys.items()))
        conn.commit()
    finally:
        conn.close()
    return len(entities), len(keys), appended


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(prog="ttn2_entities")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DB)
    args = ap.parse_args(argv)
    n_entities, n_keys, n_appended = build_entities(args.src, args.dst)
    print(f"ttn2_entities: {n_entities} entities, {n_keys} keys, "
          f"{n_appended} appended")
    return 0


if __name__ == "__main__":
    sys.exit(main())