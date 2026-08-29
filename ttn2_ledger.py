"""ttn2_ledger — layer 2: identity decisions as data + resolution.

Since P4 (fix round 4, 2026-08-29) the TRACKED ttn2_ledger.json IS the
decisions record: new identity decisions go to the ledger directly (via
curation) and are exported here — never back into ttn_aliases.py, which
is the frozen legacy read path. `import` therefore RESTORES the ledger
from the tracked JSON (rows verbatim — ids, flags and evidence included)
and tops up any missing ratified _EBU_ORDER_LINKS rows. The old
derivation from ttn_aliases.py survives as `bootstrap-from-aliases`
(archaeology only — it re-derives the legacy tables and DESTROYS the
curated deglob-* rows; that was the 2026-08-29 wipe).

Boundary: tokenization (canonical_key / work_title_key) is IMPORTED from
ttn_analyze — it is shared vocabulary, not an identity decision. Identity
DECISIONS (the alias maps) come from the ledger.

CLI:
  uv run ttn2_ledger.py import                  # restore ledger from ttn2_ledger.json
  uv run ttn2_ledger.py bootstrap-from-aliases  # derive from ttn_aliases (archaeology; destructive)
  uv run ttn2_ledger.py check                   # full-corpus resolution parity vs ttn_analyze
  uv run ttn2_ledger.py dump                    # export ledger -> ttn2_ledger.json
"""
import collections
import json
import sqlite3
import sys

import ttn_analyze as A
import ttn_aliases as T

DB = "successor.sqlite"

# --- Human-ratified link rows (EBU syndication ordering artifact) ----------
# The 19 successor-only links (controller ruling on Nick's domain evidence,
# 2026-08-29): on these 4 nights the segment feed's ordering reflects the EBU
# SYNDICATED playlist, not the BBC broadcast order — the synopsis (tracks) is
# the BBC truth. The legacy DP's temporal cascade (s_base poisoned by the
# misplaced position-0 segment rows) demotes the night's matches; the
# successor's links (via _pos_of's 0->None->voff fallback) are CORRECT and are
# preserved here as ledger rows so a ledger rebuild keeps them and the parity
# gate can classify their facet ripple as expected. Triples:
# (episode_pid, position, resolved_recording_pid) — position is the text
# observation's 0-indexed broadcast position, the projection's key space.
_EBU_ORDER_LINKS = [
    ("m0014y5c", 0, "p08hlbss"),
    ("m0014y5c", 1, "p08hlcmh"),
    ("m0014y5c", 13, "p00t5rxn"),
    ("m0014y5c", 15, "p00sj0p0"),
    ("m00154mb", 0, "p09gn3kp"),
    ("m00154mb", 9, "p02tf1d6"),
    ("m00154mb", 14, "p03gd8tj"),
    ("m00154mb", 23, "p00tkb5b"),
    ("m00154mb", 24, "p00q44c7"),
    ("m001554q", 0, "p0bvdd6b"),
    ("m001554q", 1, "p0bvddjg"),
    ("m001554q", 12, "p00ygtvf"),
    ("m001554q", 14, "p086hn4x"),
    ("m001554q", 17, "p00wchvn"),
    ("m001554q", 24, "p00txgjz"),
    ("m001556v", 0, "p0bvwd5l"),
    ("m001556v", 4, "p00q78ff"),
    ("m001556v", 10, "p00t4ls6"),
    ("m001556v", 21, "p01xvsfn"),
]

_EBU_ORDER_EVIDENCE = {
    "reason": "Ordering ground truth is the BBC synopsis (tracks), ignoring "
              "interstitials as always, wherever the segment JSON disagrees: "
              "EBU PDF playlists verify ordering WITHIN a 2-hour segment, but "
              "the ordering OF the 2-hour segments may differ from the BBC's, "
              "so the legacy DP's temporal cascade demotes these matches",
    "evidence": "https://www.ebu.ch/files/live/sites/ebu/files/notturno-"
                "playlists/2022/03/17%20March%202022.pdf",
    "programme_pages": {
        # exemplar episode (Nick's evidence, 2026-08-29): the programme page
        # confirms the synopsis order (opens Faure Requiem, ends
        # Kyurkchiyski/Poulenc) against the EBU PDF's syndicated ordering.
        "m001556v": "https://www.bbc.co.uk/programmes/m001556v",
    },
    "episodes": sorted({ep for ep, _pos, _rp in _EBU_ORDER_LINKS}),
}


def _paren_balance(s):
    for a, b in (("(", ")"), ("[", "]")):
        if s.count(a) != s.count(b):
            return False
    return s.count('"') % 2 == 0


def _flags(src, dst, raw_key_composers, scoped_keys):
    sk = A.work_title_key(src)
    xcomp = {c: n for c, n in raw_key_composers.get(sk, {}).items()}
    flags = {}
    if not _paren_balance(src) or not _paren_balance(dst):
        flags["malformed"] = True
    if len([1 for n in xcomp.values() if n]) >= 2:
        flags["xcomposer"] = xcomp
    if sk in scoped_keys:
        flags["scoped_shadow"] = True
    return flags


def _raw_key_composers(conn):
    """raw wk -> {resolved ck: airings} over both source tables."""
    out = collections.defaultdict(lambda: collections.Counter())
    for tbl, tcol, ccol in (("tracks", "title", "composer"),
                            ("segment_events", "track_title", "composer_name")):
        for c, t, n in conn.execute(
                f"SELECT {ccol}, {tcol}, COUNT(*) FROM {tbl} "
                f"WHERE {tcol} IS NOT NULL GROUP BY {ccol}, {tcol}"):
            ck = A.resolve_composer_alias(A.canonical_key(c or ""))
            out[A.work_title_key(t, composer=c or "")][ck] += n
    return out


def import_aliases(json_path="ttn2_ledger.json", dst=DB):
    """Restore the ledger from the tracked decisions JSON — the durable
    record since P4 (see module docstring). All JSON rows are inserted
    VERBATIM (ids, flags, evidence included; the old-shape ledger migrates
    in place first), then any missing ratified _EBU_ORDER_LINKS rows are
    topped up. meta is restored too, so import -> dump round-trips
    byte-stable."""
    t2 = sqlite3.connect(dst)
    # idempotent migration for ledgers predating the evidence_json column
    cols = {r[1] for r in t2.execute("PRAGMA table_info(ledger)")}
    if "evidence_json" not in cols:
        t2.execute("ALTER TABLE ledger ADD COLUMN evidence_json TEXT")
    with open(json_path) as fh:
        data = json.load(fh)
    rows = [dict(r) for r in data["ledger"]]
    have = {(r["kind"], r["scope"], r["variant_key"]) for r in rows}
    for ep, pos, rp in _EBU_ORDER_LINKS:
        if ("link", ep, str(pos)) in have:
            continue
        rows.append({"kind": "link", "scope": ep, "variant_key": str(pos),
                     "target": rp, "target_key": rp,
                     "method": "ebu-order-correction", "confidence": "ok",
                     "flags": None,
                     "evidence": json.dumps(_EBU_ORDER_EVIDENCE)})
    nxt = max((r["id"] for r in rows if r.get("id") is not None),
              default=0) + 1
    for r in rows:
        if r.get("id") is None:
            r["id"] = nxt
            nxt += 1
    rows.sort(key=lambda r: r["id"])
    t2.execute("DELETE FROM ledger")
    t2.executemany(
        "INSERT INTO ledger (id, kind, scope, variant_key, target, "
        "target_key, method, confidence, flags_json, evidence_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(r["id"], r["kind"], r["scope"], r["variant_key"], r["target"],
          r["target_key"], r["method"], r["confidence"], r.get("flags"),
          r.get("evidence")) for r in rows])
    t2.execute("CREATE TABLE IF NOT EXISTS meta "
               "(key TEXT PRIMARY KEY, value TEXT)")
    t2.execute("DELETE FROM meta")
    t2.executemany("INSERT INTO meta (key, value) VALUES (?,?)",
                   sorted(data.get("meta", {}).items()))
    t2.commit()
    n_flag = sum(1 for r in rows if r.get("flags"))
    print(f"ttn2_ledger: restored {len(rows)} decisions from {json_path} "
          f"(work {sum(1 for r in rows if r['kind']=='work_alias')}, "
          f"composer {sum(1 for r in rows if r['kind']=='composer_alias')}, "
          f"link {sum(1 for r in rows if r['kind']=='link')}); "
          f"{n_flag} flagged")


def bootstrap_from_aliases(src="ttn.sqlite", dst=DB):
    """ARCHAEOLOGY ONLY: re-derive the ledger from the frozen ttn_aliases
    tables + the ratified link rows. Destructive to curated state — the
    2026-08-29 wipe — because the de-globalization decisions (deglob-*)
    live ONLY in the tracked JSON. Kept for reconstructing what a fresh
    ttn_aliases-derived ledger looks like; the default is `import`."""
    t2 = sqlite3.connect(dst)
    t2.execute("DELETE FROM ledger")
    # idempotent migration for ledgers predating the evidence_json column
    cols = {r[1] for r in t2.execute("PRAGMA table_info(ledger)")}
    if "evidence_json" not in cols:
        t2.execute("ALTER TABLE ledger ADD COLUMN evidence_json TEXT")
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    rkc = _raw_key_composers(src_conn)
    src_conn.close()
    scoped_keys = {A.work_title_key(v, composer=c)
                   for c, v, _ in T._COMPOSER_SCOPED_WORK_ALIAS_PAIRS}
    rows = []
    for src_t, dst_t in T._WORK_ALIAS_PAIRS:
        sk = A.work_title_key(src_t)
        dk = A.work_title_key(dst_t)
        flags = _flags(src_t, dst_t, rkc, scoped_keys)
        conf = "review" if ("xcomposer" in flags or "malformed" in flags) else "legacy"
        rows.append(("work_alias", "global", sk, dst_t, dk,
                     "legacy-global", conf, json.dumps(flags) if flags else None,
                     None))
    for comp, v, p in T._COMPOSER_SCOPED_WORK_ALIAS_PAIRS:
        ck = A._scoped_composer_key(comp)
        rows.append(("work_alias", ck, A.work_title_key(v, composer=comp),
                     p, A.work_title_key(p, composer=comp),
                     "legacy-scoped", "medium", None, None))
    for src_c, dst_c in T._COMPOSER_ALIAS_PAIRS:
        rows.append(("composer_alias", "global", A.canonical_key(src_c),
                     dst_c, A.canonical_key(dst_c),
                     "legacy-composer", "legacy", None, None))
    # Human-ratified link rows, AFTER the alias rows: not alias decisions —
    # (episode, position) -> recording links the legacy projection demotes
    # via the EBU-ordering artifact (see _EBU_ORDER_LINKS above).
    for ep, pos, rp in _EBU_ORDER_LINKS:
        rows.append(("link", ep, str(pos), rp, rp,
                     "ebu-order-correction", "ok", None,
                     json.dumps(_EBU_ORDER_EVIDENCE)))
    t2.executemany(
        "INSERT INTO ledger (kind, scope, variant_key, target, target_key, "
        "method, confidence, flags_json, evidence_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    t2.commit()
    n_flag = sum(1 for r in rows if r[7])
    print(f"ttn2_ledger: {len(rows)} decisions "
          f"(work {sum(1 for r in rows if r[0]=='work_alias')}, "
          f"composer {sum(1 for r in rows if r[0]=='composer_alias')}, "
          f"link {sum(1 for r in rows if r[0]=='link')}); "
          f"{n_flag} flagged for review")


def load_maps(dst=DB):
    t2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    work_global, work_scoped, comp = {}, {}, {}
    for kind, scope, vk, tgt, tk in t2.execute(
            "SELECT kind, scope, variant_key, target, target_key FROM ledger"):
        if kind == "work_alias":
            if scope == "global":
                work_global[vk] = tk
            else:
                work_scoped[(scope, vk)] = tk
        elif kind == "composer_alias":
            comp[vk] = tk
        # kind == 'link' (ratified EBU-order (episode, position) -> recording
        # links) is deliberately IGNORED here: it is not an alias decision,
        # and treating it as one would poison the composer map.
    t2.close()
    return comp, work_scoped, work_global


def load_link_rows(dst=DB):
    """The ratified kind='link' rows as
    [(episode_pid, position:int, resolved_recording_pid)]. The parity gate
    derives its exception set (resolved rps + link episode pids) from these.
    A missing ledger table degrades to []."""
    t2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    try:
        out = [(scope, int(float(vk)), tgt) for kind, scope, vk, tgt in t2.execute(
            "SELECT kind, scope, variant_key, target FROM ledger "
            "WHERE kind='link'")]
    except sqlite3.OperationalError:
        out = []
    finally:
        t2.close()
    return out


def resolve_composer(ck, comp):
    return comp.get(ck, ck)


def resolve_work(wk, composer_str, work_scoped, work_global):
    # mirrors ttn_analyze.resolve_work_alias exactly: the scoped lookup is
    # keyed by _scoped_composer_key(RAW composer string) — which runs
    # normalize_composer — NOT by the pre-resolved composer key. Segment-side
    # compound credits ('X and Y', 'Pytor, Illyich ...') expose the
    # difference. Single step, no chaining.
    ck_scope = A._scoped_composer_key(composer_str)
    scoped = work_scoped.get((ck_scope, wk))
    if scoped is not None:
        return scoped
    return work_global.get(wk, wk)


def check(src="ttn.sqlite", dst=DB, sample=None):
    """Full-corpus parity: ledger resolution must equal ttn_analyze's."""
    comp, ws, wg = load_maps(dst)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    diffs = 0
    checked = 0
    q = ("SELECT composer, title FROM tracks WHERE title IS NOT NULL"
         + (f" LIMIT {int(sample)}" if sample else ""))
    for c, t in src_conn.execute(q):
        ck = A.resolve_composer_alias(A.canonical_key(c))
        wk = A.work_title_key(t, composer=c)
        mine_c = resolve_composer(A.canonical_key(c), comp)
        mine_w = resolve_work(wk, c, ws, wg)
        if (mine_c, mine_w) != (ck, A.resolve_work_alias(wk, composer=c)):
            diffs += 1
            if diffs <= 5:
                print("DIFF:", repr(c), repr(t), (ck, A.resolve_work_alias(wk, composer=c)),
                      "->", (mine_c, mine_w))
        checked += 1
    src_conn.close()
    print(f"ttn2_ledger check: {checked} rows, {diffs} resolution diffs")
    return diffs


def dump(path="ttn2_ledger.json", dst=DB):
    """Export the ledger to a tracked JSON file — decisions are durable
    state, not derived state; successor.sqlite is rebuildable from it."""
    t2 = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    rows = [dict(zip(("id", "kind", "scope", "variant_key", "target",
                      "target_key", "method", "confidence", "flags",
                      "evidence"), r)) for r in t2.execute(
        "SELECT id, kind, scope, variant_key, target, target_key, method, "
        "confidence, flags_json, evidence_json FROM ledger ORDER BY id")]
    meta = dict(t2.execute("SELECT key, value FROM meta"))
    anchor = [dict(zip(("slug", "work_entity_id", "legacy_ck", "legacy_wk"), r))
              for r in t2.execute(
        "SELECT slug, work_entity_id, legacy_ck, legacy_wk "
        "FROM work_slug_anchor ORDER BY slug")]
    entities = [dict(zip(("id", "name"), r)) for r in t2.execute(
        "SELECT id, name FROM work_entity ORDER BY id")]
    t2.close()
    with open(path, "w") as fh:
        json.dump({"ledger": rows, "meta": meta, "anchor": anchor,
                   "work_entities": entities}, fh, indent=0)
    print(f"ttn2_ledger dump: {len(rows)} decisions, {len(anchor)} anchors "
          f"-> {path}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "import"
    if cmd == "import":
        import_aliases()
    elif cmd == "bootstrap-from-aliases":
        bootstrap_from_aliases()
    elif cmd == "check":
        sys.exit(1 if check(sample=sys.argv[2] if len(sys.argv) > 2 else None) else 0)
    elif cmd == "dump":
        dump()
    else:
        print("usage: ttn2_ledger.py import|bootstrap-from-aliases|"
              "check [sample]|dump", file=sys.stderr)
        sys.exit(2)
