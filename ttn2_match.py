"""ttn2_match — layer 3: link observations into events.

Per episode:
  1. Segment observations sharing a recording_pid form one event
     (method='recording_pid') — the BBC's own performance identity.
  2. Text observations link to a segment event via the existing DP matcher
     (ttn_mbid_audit.reconcile_episode, imported verbatim) when the tier is
     HIGH — the same threshold the current pipeline's projection uses for
     grouping. Linked text obs inherit the event.
  3. Unlinked text observations become singleton events
     (method='singleton_text') — first-class, never dropped.

Parity note: the current projected view counts tracks rows whose identity
is the recording's clean segment metadata when the projection is High, else
the raw text fields. Event identity here follows the same rule, so
ttn2_parity can diff the two exactly.
"""
import collections
import sqlite3
import sys

from ttn_mbid_audit import reconcile_episode
from ttn_project import build_rec_meta

DB = "successor.sqlite"


def _episode_obs(conn, ep):
    seg = conn.execute(
        "SELECT id, ord, composer_raw, title, title_raw, composer_mbid, "
        "recording_pid, duration_s, version_offset FROM obs "
        "WHERE episode_pid=? AND source='segment' ORDER BY ord", (ep,)).fetchall()
    text = conn.execute(
        "SELECT id, ord, composer_raw, composer_line, title, time_str "
        "FROM obs WHERE episode_pid=? AND source='text' ORDER BY ord", (ep,)).fetchall()
    return seg, text


def link(dst="successor.sqlite", src="ttn.sqlite"):
    out = sqlite3.connect(dst)
    # Episodes come from the successor obs (a src with no obs for an episode is
    # a no-op anyway); this keeps link() usable against a src that is missing
    # or lacks the segment lineage (the medium/bridge tests exercise exactly
    # that). rec_meta is the identity anchor source; a missing/incomplete src
    # degrades to {} (no clean anchors, raw text identity everywhere).
    episodes = [r[0] for r in out.execute("SELECT DISTINCT episode_pid FROM obs")]
    rec_meta = {}
    try:
        src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        rec_meta = build_rec_meta(src_conn)
        src_conn.close()
    except sqlite3.OperationalError:
        pass

    n_seg_ev = n_linked = n_singleton = n_medium = 0
    out.execute("UPDATE obs SET event_id=NULL")
    out.execute("DELETE FROM event")
    for ep in episodes:
        seg, text = _episode_obs(out, ep)
        date10 = (out.execute("SELECT date10 FROM obs WHERE episode_pid=? "
                              "LIMIT 1", (ep,)).fetchone() or [None])[0]
        # 1) segment obs -> events keyed by recording_pid (NULL rp = own event)
        rp_event = {}
        for (oid, ordv, comp, title, title_raw, mbid, rp, dur, voff) in seg:
            key = rp or ("norpid", oid)
            if key not in rp_event:
                anchor = rec_meta.get(rp, (comp, title)) if rp else (comp, title)
                out.execute(
                    "INSERT INTO event (episode_pid, date10, ord, composer, "
                    "title, method, confidence, recording_pid) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (ep, date10, ordv, anchor[0], anchor[1],
                     "recording_pid", "high", rp))
                rp_event[key] = out.execute(
                    "SELECT last_insert_rowid()").fetchone()[0]
                n_seg_ev += 1
            out.execute("UPDATE obs SET event_id=? WHERE id=?",
                        (rp_event[key], oid))
        # 2) text obs -> DP matcher vs this episode's segment rows
        if text and seg:
            tracks = [{"position": int(ordv) if float(ordv) == int(ordv) else ordv,
                       "time_str": tstr or "", "composer": comp or "",
                       "title": title or ""}
                      for (oid, ordv, comp, cl, title, tstr) in text]
            segs = [{"position": None if False else _pos_of(ordv),
                     "version_offset": voff, "composer_name": comp or "",
                     "track_title": (traw or title or ""), "composer_mbid": mbid,
                     "recording_pid": rp}
                    for (oid, ordv, comp, title, traw, mbid, rp, dur, voff) in seg]
            matches = reconcile_episode(tracks, segs)
            for m, (oid, ordv, comp, cl, title, tstr) in zip(matches, text):
                rp = m.get("recording_pid")
                if m.get("tier") == "high" and rp and rp in rp_event:
                    eid = rp_event[m["recording_pid"]]
                    out.execute("UPDATE obs SET event_id=? WHERE id=?", (eid, oid))
                    n_linked += 1
                    continue
                if m.get("tier") == "medium" and rp and rp in rp_event:
                    # graduated trust: a Medium link SHOWS the recording but
                    # never carries identity -- the obs keeps a singleton event
                    # with raw text.
                    out.execute("INSERT OR REPLACE INTO presentation VALUES (?,?,?)",
                                (ep, ordv, rp))
                    n_medium += 1
                out.execute(
                    "INSERT INTO event (episode_pid, date10, ord, composer, "
                    "title, method, confidence, recording_pid) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (ep, date10, ordv, comp, title, "singleton_text",
                     "singleton", None))
                eid = out.execute("SELECT last_insert_rowid()").fetchone()[0]
                out.execute("UPDATE obs SET event_id=? WHERE id=?", (eid, oid))
                n_singleton += 1
        else:
            for (oid, ordv, comp, cl, title, tstr) in text:
                out.execute(
                    "INSERT INTO event (episode_pid, date10, ord, composer, "
                    "title, method, confidence, recording_pid) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (ep, date10, ordv, comp, title, "singleton_text",
                     "singleton", None))
                eid = out.execute("SELECT last_insert_rowid()").fetchone()[0]
                out.execute("UPDATE obs SET event_id=? WHERE id=?", (eid, oid))
                n_singleton += 1
    n_bridge = _bridge_links(out, src)
    out.commit()
    print(f"ttn2_match: {n_seg_ev} recording events, {n_linked} text obs "
          f"linked (DP high), {n_singleton} singleton text events, "
          f"{n_medium} medium presentation links, {n_bridge} bridge events")


def _bridge_links(out, src):
    """Ingest the legacy projection's bridge half as recording-backed events.
    The full projection (ttn_project.load) merges the 2012+ DP half with the
    trusted cross-era bridge DISJOINTLY, so any projection entry whose text
    obs is not already recording-linked IS a bridge link -- this covers both
    the pre-2012 block and the scattered tail. Reading the legacy projection
    cache here is the phase-1 shortcut; P2 re-derives these from the ledger
    directly."""
    import ttn_project
    try:
        conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return 0
    try:
        projection, rec_meta_full, status = ttn_project.load(conn)
    finally:
        conn.close()
    if status != "ok":
        return 0
    dates = dict(out.execute("SELECT episode_pid, date10 FROM obs"))
    linked = {r[0] for r in out.execute(
        "SELECT o.id FROM obs o JOIN event e ON o.event_id=e.id "
        "WHERE e.method IN ('recording_pid','bridge')")}
    n = 0
    for (ep, pos), rp in projection.items():
        if rp not in rec_meta_full:
            continue
        row = out.execute(
            "SELECT id FROM obs WHERE episode_pid=? AND source='text' "
            "AND ord=? ORDER BY id LIMIT 1", (ep, float(pos))).fetchone()
        if row is None or row[0] in linked:
            continue
        cm, tt = rec_meta_full[rp]
        out.execute("INSERT INTO event (episode_pid, date10, ord, composer, "
                    "title, method, confidence, recording_pid) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (ep, dates.get(ep), float(pos), cm, tt, "bridge", "high", rp))
        eid = out.execute("SELECT last_insert_rowid()").fetchone()[0]
        out.execute("UPDATE obs SET event_id=? WHERE id=?", (eid, row[0]))
        linked.add(row[0])
        n += 1
    return n


def _pos_of(ordv):
    """reconcile_episode expects the BBC 1-indexed position; segment obs ord
    is exactly that (version_offset fallbacks are >=1000 and only occur where
    the BBC position was NULL — reconcile handles NULL positions itself, so
    pass None for those)."""
    return int(ordv) if 0 < ordv < 1000 else None


if __name__ == "__main__":
    link(*(sys.argv[1:3] or []))
