"""Site substrate builder (website Phase 1): the frozen slug registry +
site.sqlite entity aggregates. Reached as `ttn_data.py site`."""
import hashlib
import json
import os
import re
from collections import Counter

from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                          strip_arranger_tail, resolve_composer_alias,
                          resolve_work_alias, work_title_key, _best_spelling,
                          override_composer_display)

REGISTRY_PATH = "ttn_site_registry.json"


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
      spellings    -- list of distinct normalized composer spellings seen

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


# --- frozen slug registry ---------------------------------------------------
# ttn_site_registry.json gives every work/composer identity a PERMANENT slug.
# Once registered, the slug never moves on its own -- a canonicalization edit
# that changes the derived slug is reported (report["slug_drift"]) but not
# applied; a registered identity that vanishes from the current corpus is a
# hard failure (RegistryDriftError), not a silent drop. See global-context.md
# "Design decision locked".

class RegistryDriftError(Exception):
    """Raised by sync_registry when a REGISTERED identity (work or composer)
    is absent from the current derived entries -- an alias/gate edit moved
    or removed a group key out from under a frozen slug. Lists every orphaned
    slug found (not just the first) so one sync surfaces the whole remap job.
    Fix: the explicit --remap admin action (a later task), not a re-sync."""


def _empty_registry():
    return {"version": 1, "works": {}, "composers": {},
            "redirects": {"works": {}, "composers": {}}}


def load_registry(path=REGISTRY_PATH):
    """Load the slug registry. Missing file -> a fresh empty v1 shell (first
    run). A file that exists but is corrupt JSON or the wrong shape is a HARD
    error -- unlike the derived caches (missing/corrupt -> degrade), this is a
    git-tracked, human-consequential file, so silent degradation would mean
    silently reassigning URLs. Shape check is shallow (top-level keys present
    with the right container types), not a full schema validation."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return _empty_registry()

    required = ("version", "works", "composers", "redirects")
    if not isinstance(data, dict) or any(k not in data for k in required):
        raise ValueError(f"{path}: not a valid registry (missing top-level key)")
    if not isinstance(data["works"], dict) or not isinstance(data["composers"], dict):
        raise ValueError(f"{path}: 'works'/'composers' must be objects")
    redirects = data["redirects"]
    if (not isinstance(redirects, dict)
            or not isinstance(redirects.get("works"), dict)
            or not isinstance(redirects.get("composers"), dict)):
        raise ValueError(f"{path}: 'redirects' must be {{'works': {{}}, 'composers': {{}}}}")
    return data


def dump_registry(registry, path=REGISTRY_PATH):
    """Write the registry as deterministic, git-reviewable bytes (sorted
    keys, indent=2, trailing newline). Atomic: writes path+'.tmp' then
    os.replace, so a killed write can never leave a truncated tracked file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _unique_slug(base_slug, taken):
    """First of base_slug, base_slug-2, base_slug-3, ... not in `taken`."""
    if base_slug not in taken:
        return base_slug
    n = 2
    while f"{base_slug}-{n}" in taken:
        n += 1
    return f"{base_slug}-{n}"


def _sync_namespace(registered, redirected_keys, entries, identity_of, slug_of,
                     today, record_key):
    """Shared engine for one namespace (works or composers).

    registered:       {slug: entry-dict} from the registry (NOT mutated)
    redirected_keys:   set of slugs that are redirect sources in this namespace
    entries:           derived entries (work_entries or composer_entries)
    identity_of(entry): the identity key (a tuple for works, a str for composers)
    slug_of(entry):     the entry's derived slug
    record_key(identity, published) -> dict to store under the winning slug

    Returns (new_registered, added_count, slug_drift, collisions, orphans).
    orphans = registered slugs whose identity is absent from `entries` (for
    the caller to collect across both namespaces before raising).
    """
    inverse = {v_identity: slug for slug, v_identity in
               ((s, identity_of.from_stored(e)) for s, e in registered.items())}
    # inverse index {identity_key: slug} for registered entries, and the
    # reverse for detecting orphans -- built from the entry data itself so
    # both namespaces share this helper (identity_of.from_stored parses the
    # stored dict back into the same identity shape as identity_of(entry)).

    derived_by_identity = {identity_of(e): e for e in entries}

    orphans = [slug for slug, identity in
               ((s, identity_of.from_stored(e)) for s, e in registered.items())
               if identity not in derived_by_identity]

    new_registered = dict(registered)
    taken = set(registered.keys()) | set(redirected_keys)
    added = 0
    slug_drift = []
    collisions = []

    # deterministic order: sort new identities before assigning suffixes
    new_identities = sorted(
        (identity_of(e) for e in entries if identity_of(e) not in inverse),
        key=lambda k: (k if isinstance(k, tuple) else (k,)))

    for identity in new_identities:
        entry = derived_by_identity[identity]
        base_slug = slug_of(entry)
        assigned = _unique_slug(base_slug, taken)
        if assigned != base_slug:
            collisions.append((identity, base_slug, assigned))
        taken.add(assigned)
        new_registered[assigned] = record_key(identity, today)
        added += 1

    # frozen identities: report derived-slug divergence, change nothing
    for identity, slug in inverse.items():
        if identity in derived_by_identity:
            derived_slug = slug_of(derived_by_identity[identity])
            if derived_slug != slug:
                slug_drift.append((slug, derived_slug))

    return new_registered, added, slug_drift, collisions, orphans


class _WorkIdentity:
    """identity_of callable for the works namespace, plus the inverse parse
    (from_stored) needed to rebuild identities from registry entries."""
    def __call__(self, entry):
        return entry["key"]

    @staticmethod
    def from_stored(stored):
        return (stored["composer_key"], stored["work_key"])


class _ComposerIdentity:
    def __call__(self, entry):
        return entry["composer_key"]

    @staticmethod
    def from_stored(stored):
        return stored["composer_key"]


_work_identity = _WorkIdentity()
_composer_identity = _ComposerIdentity()


def sync_registry(registry, work_entries, composer_entries, today):
    """Reconcile the frozen slug registry against the current corpus. PURE:
    no I/O, does not mutate `registry` -- returns a new (registry, report).

    today: 'YYYY-MM-DD' string stamped onto newly-registered entries
           (caller-supplied so the function stays deterministic/testable).

    Semantics:
      - a derived identity NOT already registered -> registered under its
        derived slug (or a '-2', '-3', ... suffix on collision), published
        = today.
      - a REGISTERED identity keeps its registered slug forever, even when
        the derived slug for that identity has since changed (informational
        report["slug_drift"], mapping unchanged).
      - a REGISTERED identity absent from the current derived entries is a
        RegistryDriftError -- collected across BOTH namespaces before
        raising, so one error message lists every orphan. Nothing is
        returned or written in this case.

    report keys:
      added_works, added_composers -- counts of newly-registered identities
      slug_drift  -- list of (registered_slug, derived_slug) pairs, both
                     namespaces pooled
      collisions  -- list of (identity, base_slug, assigned_slug) tuples for
                     newly-registered identities that needed a suffix
    """
    new_works, added_works, work_drift, work_collisions, work_orphans = \
        _sync_namespace(registry["works"], registry["redirects"]["works"],
                         work_entries, _work_identity,
                         lambda e: e["slug"], today,
                         lambda identity, published: {
                             "composer_key": identity[0], "work_key": identity[1],
                             "published": published})

    new_composers, added_composers, composer_drift, composer_collisions, composer_orphans = \
        _sync_namespace(registry["composers"], registry["redirects"]["composers"],
                         composer_entries, _composer_identity,
                         lambda e: e["slug"], today,
                         lambda identity, published: {
                             "composer_key": identity, "published": published})

    if work_orphans or composer_orphans:
        raise RegistryDriftError(
            "registered identity missing from the current corpus -- "
            f"orphaned work slugs: {sorted(work_orphans)}; "
            f"orphaned composer slugs: {sorted(composer_orphans)}")

    new_registry = {
        "version": registry["version"],
        "works": new_works,
        "composers": new_composers,
        "redirects": {
            "works": dict(registry["redirects"]["works"]),
            "composers": dict(registry["redirects"]["composers"]),
        },
    }
    report = {
        "added_works": added_works,
        "added_composers": added_composers,
        "slug_drift": work_drift + composer_drift,
        "collisions": work_collisions + composer_collisions,
    }
    return new_registry, report
