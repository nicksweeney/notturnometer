"""Site substrate builder (website Phase 1): the frozen slug registry +
site.sqlite entity aggregates. Reached as `ttn_data.py site`."""
import hashlib
import re
from collections import Counter

from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                          strip_arranger_tail, resolve_composer_alias,
                          resolve_work_alias, work_title_key, _best_spelling,
                          override_composer_display)


def composer_slug(display: str) -> str:
    """kebab-case the full canonical display name (ascii-fold, lowercase,
    non-alnum runs -> '-'). Empty survivor -> 'c' + sha1[:8] of the input."""
    folded = ascii_fold(display).lower()
    slug = "-".join(t for t in re.split(r"[^a-z0-9]+", folded) if t)
    if not slug:
        return "c" + hashlib.sha1(display.encode()).hexdigest()[:8]
    return slug


def build_composer_index(rows) -> list:
    """Per-composer identity entries from projected 5-tuple ranking rows.

    rows: iterable of (title, composer, composer_line, performers, bdate)
          with arranger tails NOT yet stripped.

    Mirrors build_work_index's key derivation on the composer side:
      stripped = strip_arranger_tail(composer, composer_line)
      ck       = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
      wk       = resolve_work_alias(work_title_key(title, stripped))

    Each entry dict has keys:
      composer_key -- resolved canonical composer key
      slug         -- composer_slug of the display name
      display      -- best-spelling display name (curated override applied)
      airings      -- total airing count
      n_works      -- count of distinct work keys seen for this composer
      spellings    -- list of distinct raw composer spellings seen

    Rows with an empty composer key are skipped. No collision handling here
    (registry-time concern)."""
    airing_count: dict = {}          # ck -> int
    spelling_counter: dict = {}      # ck -> Counter of normalize_composer(stripped)
    work_keys: dict = {}             # ck -> set of wk
    key_order: list = []             # insertion-ordered unique ck

    for title, composer, composer_line, performers, bdate in rows:
        stripped = strip_arranger_tail(composer, composer_line)
        ck = resolve_composer_alias(canonical_key(normalize_composer(stripped)))
        if not ck:
            continue
        wk = resolve_work_alias(work_title_key(title, stripped))

        if ck not in airing_count:
            airing_count[ck] = 0
            spelling_counter[ck] = Counter()
            work_keys[ck] = set()
            key_order.append(ck)

        airing_count[ck] += 1
        spelling_counter[ck][normalize_composer(stripped)] += 1
        work_keys[ck].add(wk)

    entries = []
    for ck in key_order:
        best = _best_spelling(spelling_counter[ck])
        display = override_composer_display(ck, "composer", best)
        entries.append({
            "composer_key": ck,
            "slug": composer_slug(display),
            "display": display,
            "airings": airing_count[ck],
            "n_works": len(work_keys[ck]),
            "spellings": list(spelling_counter[ck]),
        })

    return entries
