"""QC-marker audit: standing finder for library annotations leaking through.

The Corelli lesson (2026-08-26): a 'CHECK BEFORE USING' prefix rode inside
rec_meta titles for months because nothing looked for it -- the 30-airing
group keyed apart until someone noticed a weird ranking. This tool makes
that discovery standing instead of accidental.

It scans segment-titles (rec_meta, the post-sanitization consumer view, by
default; --raw reads segment_events directly for pre-warm use) from three
angles:

1. DIRECTIVE SURVIVORS -- known vocabulary (_QC_MARKERS + CHECK BEFORE
   USING) that SURVIVES into the scan source. Leading/trailing clean-affix =
   a sanitizer GAP => action: extend _QC_MARKERS. Mid-title = free-text QC
   notes (`... DO NOT USE Pianist awol`) deliberately left unstripped =>
   parked by design; counted for visibility only.
2. DECORATION -- '**'-style asterisk runs without any directive (wrapper
   noise the marker regexes normally consume).
3. ALL-CAPS RUNS -- >=2 consecutive fully-uppercase words minus known
   directives: the DISCOVERY bucket where unknown families surface.
   Legit uppercase (Latin movements etc.) lands here too, so it prints
   ranked counts for triage rather than failing anything.

Read-only; exit code always 0 -- a look-around, not a gate.
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict

_MAX_EXAMPLES = 4

_DIRECTIVE_RE = re.compile(
    r"(EXPIRED|AVOID|DON['’]?T\s+USE|DO\s+NOT\s+USE|CHECK\s+BEFORE\s+USING)", re.I)

_DECOR_RE = re.compile(r"\*{2,}")

_CAPS_RE = re.compile(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,}){1,}\b")

_CLEAN_HEAD_RE = re.compile(r"[\s*!(\-]*\Z")
_CLEAN_TAIL_RE = re.compile(r"\A[\s*!)\-]*")


def _classify(title):
    """(kind, phrase) with kind in {'lead','trail','embedded'} or (None, None)."""
    m = _DIRECTIVE_RE.search(title)
    if not m:
        return None, None
    if _CLEAN_HEAD_RE.fullmatch(title[:m.start()]):
        return "lead", m.group(1).upper()
    if _CLEAN_TAIL_RE.fullmatch(title[m.end():]):
        return "trail", m.group(1).upper()
    return "embedded", m.group(1).upper()


def scan_titles(rows):
    """rows: iterable of (rp_or_None, title) -> scan dict of buckets."""
    dirs = Counter()                    # (kind, phrase) -> n recordings
    examples = defaultdict(list)        # (kind, phrase) | 'deco' | caps-key
    caps = Counter()                    # norm phrase -> n recordings

    for rp, title in rows:
        kind, phrase = _classify(title)
        if kind:
            dirs[(kind, phrase)] += 1
            _keep(examples[(kind, phrase)], rp, title)
        if _DECOR_RE.search(title):
            _keep(examples["deco"], rp, title)
        seen_here = set()
        for mm in _CAPS_RE.finditer(title):
            norm = re.sub(r"\s+", " ", mm.group(0).upper())
            if _DIRECTIVE_RE.search(norm) or norm in seen_here:
                continue
            seen_here.add(norm)
            caps[norm] += 1
            _keep(examples[("caps", norm)], rp, title)
    return {"dirs": dirs, "examples": examples, "caps": caps}


def _keep(lst, rp, title):
    if len(lst) < _MAX_EXAMPLES:
        lst.append((rp, title))


_KIND_SECTION = {
    "lead": "-- leading survivors (sanitizer GAP -> extend _QC_MARKERS)",
    "trail": "-- trailing survivors (sanitizer GAP)",
    "embedded": "-- embedded notes (parked BY DESIGN; visibility only)",
}


def render(scan, n_titles, airings):
    out = [f"=== QC-marker audit over {n_titles} recording titles ==="]
    anything = False

    for kind in ("lead", "trail", "embedded"):
        entries = sorted(((k, n) for (kd, k), n in scan["dirs"].items()
                          if kd == kind), key=lambda kv: -kv[1])
        if entries:
            anything = True
            out.append(f"\n{_KIND_SECTION[kind]}")
            for phrase, n in entries:
                out.append(f"   {phrase}   [{n} recording(s)]")
                for rp, t in scan["examples"][(kind, phrase)]:
                    out.append(f"      · ({airings.get(rp, '?')}×) {t!r}")

    decos = scan["examples"]["deco"]
    if decos:
        anything = True
        out.append(f"\n-- '**' decoration present on {len(decos)} shown "
                   "recording title(s)")
        for rp, t in decos:
            out.append(f"      · ({airings.get(rp, '?')}×) {t!r}")

    if scan["caps"]:
        anything = True
        out.append("\n-- other ALL-CAPS runs (discovery bucket - triage; may be legit)")
        top = scan["caps"].most_common(12)
        width = max(len(k) for k, _ in top)
        for phrase, n in top:
            out.append(f"   {phrase:<{width}}  {n:>4}")
            for rp, t in scan["examples"][("caps", phrase)][:_MAX_EXAMPLES]:
                out.append(f"      · ({airings.get(rp, '?')}×) {t!r}")

    if not anything:
        out.append("\nclean: no directive survivors, decorations, or caps runs found.")
    return "\n".join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(
        prog="ttn_curate.py qc-audit",
        description="surface leaked QC/library annotations in segment titles")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--raw", action="store_true",
                    help="scan raw segment_events titles instead of rec_meta")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        proj = {}
        if args.raw:
            src_rows = conn.execute(
                "SELECT DISTINCT recording_pid, track_title FROM segment_events "
                "WHERE track_title IS NOT NULL").fetchall()
        else:
            import ttn_project as P
            projection, rec_meta, _status = P.load(conn)
            src_rows = [(rp, tt) for rp, (_cm, tt) in rec_meta.items()]
            proj = projection

        airings = Counter()
        for ep, pos in conn.execute(
                "SELECT episode_pid, position FROM tracks WHERE title IS NOT NULL"):
            rp = proj.get((ep, pos))
            if rp:
                airings[rp] += 1
    finally:
        conn.close()

    print(render(scan_titles(src_rows), len(src_rows), airings))
    return 0


if __name__ == "__main__":
    main()
