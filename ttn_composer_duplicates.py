#!/usr/bin/env python3
"""Post-alias composer-duplicate detector — an independent cross-check that
flags distinct composer groups likely to be one person keyed apart by a
spelling / transliteration / name-order / typo difference that escapes both
canonical_key's diacritic-fold and the same-surname --mode audit gate (the
Ion Dimitrescu vs Ion Dumitrescu class). Reports candidates for human triage;
optionally emits paste-ready _COMPOSER_ALIAS_PAIRS tuples. Never folds.

Two tiers: date-corroborated (groups sharing a birth-death span, names
compared down to a 0.74 ratio floor with a 0.82 high-confidence divider) and
no-date-corroboration (surname-blocked, 0.88 floor). Dates are a detection
signal only — never folded into the grouping key.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from ttn_analyze import canonical_key, resolve_composer_alias, COMPOSER_ALIASES

PRIMARY_FLOOR = 0.74      # report date-corroborated pairs at/above this ratio
PRIMARY_HIGH = 0.82       # high-confidence divider within the primary tier
SECONDARY_FLOOR = 0.88    # stricter floor for no-date, surname-blocked pairs

# A leading b. (born) or c./ca. (circa) qualifier is skipped before each year.
# The circa skip matters on multi-composer lines: without it, a "(c.1570-1629)"
# span is missed and parse_span grabs a LATER composer's clean date instead
# (e.g. mis-dating Gasper Fernandes with Hernando Franco's 1532-1585).
_QUAL = r"(?:b\.?\s*|ca\.?\s*|c\.?\s*)?"   # ca before c so the longer wins
_DATE = re.compile(rf'[(\[]\s*{_QUAL}(\d{{3,4}})\s*(?:[-–—]\s*{_QUAL}(\d{{3,4}})?)?')


def parse_span(composer_line):
    """The (birth, death) year tuple from a composer_line, or None. death is
    '' for open / birth-only spans (e.g. '(b.1948)', '(1660-)'). A leading
    b./c./ca. qualifier on either year is skipped (so '(c.1570-1629)' yields
    ('1570','1629')). The dash and death year are optional so birth-only forms
    still yield a span. Detection signal only — never a key."""
    m = _DATE.search(composer_line or "")
    return (m.group(1), m.group(2) or "") if m else None


@dataclass
class ComposerGroup:
    key: str             # resolved canonical key — the group identity
    display: str         # most-common original spelling
    airings: int
    span: tuple | None   # (birth, death|'') most-common span, or None


_EXCLUDE_PREFIX = ("Traditional", "Anon", "Unknown")


_ARR = re.compile(r"\barr\b|arr\.")


def _excluded_name(composer):
    """True for rows that carry no clean single-composer identity: two-composer
    or surname-first malformed lines (comma), arranger credits (the *token*
    'arr'/'arr.', NOT the substring — a substring match would wrongly drop
    Parry, Tarrega, Larrocha, Barriere, Birtwistle, …), and the
    Traditional/Anon/Unknown source-attribution forms."""
    return bool("," in composer or _ARR.search(composer.lower())
                or composer.startswith(_EXCLUDE_PREFIX))


def build_groups(rows):
    """rows: iterable of (composer, composer_line). Returns list[ComposerGroup],
    one per resolved canonical key, with airings, the most-common spelling as
    display, and the most-common parsed date-span."""
    acc = defaultdict(lambda: {"airings": 0, "names": Counter(),
                               "spans": Counter()})
    for composer, line in rows:
        if not composer or _excluded_name(composer):
            continue
        key = resolve_composer_alias(canonical_key(composer))
        rec = acc[key]
        rec["airings"] += 1
        rec["names"][composer] += 1
        sp = parse_span(line)
        if sp:
            rec["spans"][sp] += 1
    groups = []
    for key, rec in acc.items():
        span = rec["spans"].most_common(1)[0][0] if rec["spans"] else None
        groups.append(ComposerGroup(key, rec["names"].most_common(1)[0][0],
                                    rec["airings"], span))
    return groups


@dataclass
class DupPair:
    tier: str            # "primary" | "secondary"
    ratio: float
    big: ComposerGroup   # the more-aired side
    small: ComposerGroup

    @property
    def min_airings(self):
        return min(self.big.airings, self.small.airings)


def _similarity(a, b):
    return SequenceMatcher(None, canonical_key(a), canonical_key(b)).ratio()


def _surname(key):
    parts = key.split()
    return parts[-1] if parts else ""


def _mk_pair(tier, ratio, a, b):
    big, small = (a, b) if a.airings >= b.airings else (b, a)
    return DupPair(tier, ratio, big, small)


def find_duplicates(groups, rejected=frozenset(),
                    primary_floor=PRIMARY_FLOOR,
                    secondary_floor=SECONDARY_FLOOR):
    """Candidate same-person split pairs across distinct groups, two tiers,
    ranked primary-first, then high-confidence (ratio >= PRIMARY_HIGH) before
    lower-confidence within the primary tier, then by min(airings) desc then
    ratio desc. The high-confidence partition makes render's 0.82 divider fire
    cleanly at the boundary. `rejected` is a set of frozenset({name_a, name_b})
    pairs to drop."""
    pairs = []
    seen = set()

    # Primary: bucket by exact date-span, compare all pairs in a bucket.
    by_span = defaultdict(list)
    for g in groups:
        if g.span:
            by_span[g.span].append(g)
    for gs in by_span.values():
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                a, b = gs[i], gs[j]
                if a.key == b.key:
                    continue
                r = _similarity(a.display, b.display)
                if r >= primary_floor:
                    pairs.append(_mk_pair("primary", r, a, b))
                    seen.add(frozenset((a.key, b.key)))

    # Secondary: no shared span; surname-blocked to stay tractable. Known
    # blind spot: a same-person split whose SURNAME token itself differs
    # (e.g. Dimitrescu/Dumitrescu) falls in different buckets here, so only
    # the primary tier (date-blocked, no surname requirement) can pair such a
    # split — and only when a date corroborates. Cross-surname + no/mismatched
    # date is the residual gap, accepted for tractability.
    by_sur = defaultdict(list)
    for g in groups:
        by_sur[_surname(g.key)].append(g)
    for gs in by_sur.values():
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                a, b = gs[i], gs[j]
                if a.key == b.key:
                    continue
                if a.span and b.span and a.span == b.span:
                    continue                       # handled in primary
                if frozenset((a.key, b.key)) in seen:
                    continue
                r = _similarity(a.display, b.display)
                if r >= secondary_floor:
                    pairs.append(_mk_pair("secondary", r, a, b))

    pairs = [p for p in pairs
             if frozenset((p.big.display, p.small.display)) not in rejected]
    pairs.sort(key=lambda p: (p.tier != "primary", p.ratio < PRIMARY_HIGH,
                              -p.min_airings, -p.ratio))
    return pairs


def load_decisions(path):
    """Set of frozenset({name_a, name_b}) pairs a human has rejected. Missing
    file -> empty set (the finder still runs, statelessly)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return set()
    return {frozenset(pair) for pair in data.get("rejected", [])}


def reject_pair(path, name_a, name_b):
    """Append a sorted [name_a, name_b] to the decisions file (de-duped),
    preserving any existing _comment. Creates the file if absent."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {"rejected": []}
    pair = sorted([name_a, name_b])
    existing = {frozenset(p) for p in data.get("rejected", [])}
    if frozenset(pair) not in existing:
        data.setdefault("rejected", []).append(pair)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")


def _majority_maybe_error(big, small):
    """Rough flag (no external lookup): the majority spelling may be the
    erroneous one — true when the majority is the shorter spelling, or carries
    fewer non-ASCII (diacritic) characters than the minority. Flag only — the
    human confirms and, if so, also adds the minority spelling to
    _COMPOSER_DISPLAY_PREFERENCES."""
    def non_ascii(s):
        return sum(1 for ch in s if ord(ch) > 127)
    if len(big.display) < len(small.display):
        return True
    if non_ascii(big.display) < non_ascii(small.display):
        return True
    return False


def _pair_line(p):
    sp = f"[{p.big.span[0]}-{p.big.span[1]}]" if p.big.span else "[no dates]"
    return (f"  min={p.min_airings:>3}  r={p.ratio:.2f}  {sp}  "
            f"{p.big.display!r}({p.big.airings}) | "
            f"{p.small.display!r}({p.small.airings})")


def _emit_block(pairs):
    lines = ["\n# --- paste-ready _COMPOSER_ALIAS_PAIRS (VERIFY before pasting) ---"]
    for p in pairs:
        vk, pk = canonical_key(p.small.display), canonical_key(p.big.display)
        if vk == pk:
            lines.append(f"#   skipped (dead): {p.small.display!r} == {p.big.display!r}")
            continue
        if pk in COMPOSER_ALIASES:
            lines.append(f"#   skipped (chained): {p.big.display!r} is itself a variant")
            continue
        lines.append(f"    ({p.small.display!r}, {p.big.display!r}),")
        if _majority_maybe_error(p.big, p.small):
            lines.append("    # ⚠ majority may be the error — if so also add to "
                         "_COMPOSER_DISPLAY_PREFERENCES:")
            lines.append(f"    #     {p.small.display!r},")
    return "\n".join(lines)


def render(pairs, emit=False, high=PRIMARY_HIGH):
    primary = [p for p in pairs if p.tier == "primary"]
    secondary = [p for p in pairs if p.tier == "secondary"]
    out = [f"=== {len(pairs)} candidate same-person split(s) ==="]
    out.append(f"\n-- date-corroborated ({len(primary)}) --")
    divider_done = False
    for p in primary:
        if not divider_done and p.ratio < high:
            out.append(f"  ----  below high-confidence ({high:.2f}) — eyeball these  ----")
            divider_done = True
        out.append(_pair_line(p))
    out.append(f"\n-- no date corroboration ({len(secondary)}) --")
    for p in secondary:
        out.append(_pair_line(p))
    if emit:
        out.append(_emit_block(pairs))
    return "\n".join(out)


_DECISIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "ttn_composer_dup_decisions.json")


def _write_csv(path, pairs):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tier", "ratio", "min_airings", "span",
                    "name_a", "airings_a", "name_b", "airings_b"])
        for p in pairs:
            span = f"{p.big.span[0]}-{p.big.span[1]}" if p.big.span else ""
            w.writerow([p.tier, f"{p.ratio:.2f}", p.min_airings, span,
                        p.big.display, p.big.airings,
                        p.small.display, p.small.airings])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Flag distinct composer groups likely to be one person "
                    "keyed apart (post-alias same-person split scan).")
    parser.add_argument("db", nargs="?", default="ttn.sqlite",
                        help="path to ttn.sqlite")
    parser.add_argument("--composer",
                        help="restrict to pairs whose display name contains "
                             "this substring (case-insensitive)")
    parser.add_argument("--top", type=int, default=0,
                        help="cap each tier (0 = all)")
    parser.add_argument("--emit", action="store_true",
                        help="append paste-ready _COMPOSER_ALIAS_PAIRS tuples")
    parser.add_argument("--reject", metavar="A|B",
                        help="record a rejected pair to the decisions file and exit")
    parser.add_argument("--csv", help="write all candidate pairs to CSV")
    args = parser.parse_args(argv)

    if args.reject:
        if "|" not in args.reject:
            parser.error("--reject expects two names separated by '|', "
                         'e.g. --reject "Name A|Name B"')
        a, b = args.reject.split("|", 1)
        reject_pair(_DECISIONS_PATH, a.strip(), b.strip())
        print(f"Recorded rejection: {a.strip()!r} | {b.strip()!r}")
        return

    conn = sqlite3.connect(args.db)
    rows = conn.execute("SELECT composer, composer_line FROM tracks").fetchall()
    conn.close()

    pairs = find_duplicates(build_groups(rows),
                            rejected=load_decisions(_DECISIONS_PATH))
    if args.composer:
        needle = args.composer.lower()
        pairs = [p for p in pairs
                 if needle in p.big.display.lower()
                 or needle in p.small.display.lower()]
    if args.top:
        prim = [p for p in pairs if p.tier == "primary"][:args.top]
        sec = [p for p in pairs if p.tier == "secondary"][:args.top]
        pairs = prim + sec
    if args.csv:
        _write_csv(args.csv, pairs)
        print(f"{len(pairs)} pairs written to {args.csv}", file=sys.stderr)
        return
    print(render(pairs, emit=args.emit))
