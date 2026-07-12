"""Site substrate builder (website Phase 1): the frozen slug registry +
site.sqlite entity aggregates. Reached as `ttn_data.py site`."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import datetime as dt
from collections import Counter

import ttn_project
from ttn_analyze import (ascii_fold, canonical_key, normalize_composer,
                          strip_arranger_tail, resolve_composer_alias,
                          resolve_work_alias, work_title_key, _best_spelling,
                          override_composer_display, build_work_index,
                          _project_rows, load_slug_map)

REGISTRY_PATH = "ttn_site_registry.json"
SITE_DB_FILENAME = "site.sqlite"

# Absolute paths to the two modules whose bytes feed site_fingerprint, resolved
# once at import time beside THIS module (not the caller's cwd). Module-level
# names (not inlined into site_fingerprint) so tests can monkeypatch them.
_ANALYZE_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_analyze.py")
_ALIASES_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ttn_aliases.py")


def registry_path():
    """Absolute path to the slug registry, beside this module (mirrors
    ttn_analyze.slug_cache_path)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        REGISTRY_PATH)


def site_db_path():
    """Absolute path to site.sqlite, beside this module (mirrors registry_path
    / ttn_analyze.slug_cache_path)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        SITE_DB_FILENAME)


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


# --- admin actions -----------------------------------------------------------
# Deliberate, explicit registry surgery -- the counterpart to sync_registry's
# hands-off drift detection. Both are PURE (registry in, new registry out;
# never mutate the input) so main() stays a thin load/modify/dump/report shell.

class RegistryActionError(Exception):
    """Raised by an admin action (apply_rename/apply_remap) when the requested
    surgery is unsafe -- e.g. the target slug is already taken, or the source
    slug isn't registered at all. main() reports this and exits 1 without
    writing the registry."""


def _namespace_identity(namespace, stored):
    if namespace == "works":
        return (stored["composer_key"], stored["work_key"])
    return stored["composer_key"]


def apply_rename(registry, namespace, old, new):
    """Move the registration at slug `old` to slug `new` (same identity,
    same published date), leaving redirects[namespace][old] = new. Refuses
    (RegistryActionError, registry unchanged) if `old` isn't registered, or
    if `new` is already taken -- either a live registration or an existing
    redirect source -- in that namespace."""
    registered = registry[namespace]
    redirects = registry["redirects"][namespace]
    if old not in registered:
        raise RegistryActionError(f"{namespace}: {old!r} is not registered")
    if new in registered:
        raise RegistryActionError(
            f"{namespace}: {new!r} is already registered (to "
            f"{_namespace_identity(namespace, registered[new])!r})")
    if new in redirects:
        raise RegistryActionError(
            f"{namespace}: {new!r} is already a redirect (to {redirects[new]!r})")

    new_registered = dict(registered)
    entry = new_registered.pop(old)
    new_registered[new] = entry
    new_redirects = dict(redirects)
    new_redirects[old] = new

    new_registry = _with_namespace(registry, namespace, new_registered, new_redirects)
    return new_registry


def apply_remap(registry, namespace, slug, composer_key, work_key=None):
    """Re-point an orphaned registered `slug` at its successor identity (the
    alias-fold recovery path: a canonicalization edit moved the group key an
    old slug pointed at). If the successor identity is ALREADY registered
    under some OTHER slug, `slug` instead becomes a redirect to that slug and
    its own registration is removed (two slugs must never both claim to be
    canonical for one identity). Otherwise `slug`'s stored identity is
    updated in place (published date preserved). Refuses (RegistryActionError,
    registry unchanged) if `slug` isn't registered."""
    registered = registry[namespace]
    redirects = registry["redirects"][namespace]
    if slug not in registered:
        raise RegistryActionError(f"{namespace}: {slug!r} is not registered")

    target_identity = (composer_key, work_key) if namespace == "works" else composer_key

    existing_slug = None
    for s, stored in registered.items():
        if s == slug:
            continue
        if _namespace_identity(namespace, stored) == target_identity:
            existing_slug = s
            break

    new_registered = dict(registered)
    new_redirects = dict(redirects)
    if existing_slug is not None:
        del new_registered[slug]
        new_redirects[slug] = existing_slug
    else:
        published = registered[slug]["published"]
        if namespace == "works":
            new_registered[slug] = {"composer_key": composer_key, "work_key": work_key,
                                     "published": published}
        else:
            new_registered[slug] = {"composer_key": composer_key, "published": published}

    return _with_namespace(registry, namespace, new_registered, new_redirects)


def _with_namespace(registry, namespace, registered, redirects):
    """New registry dict with `namespace`'s registered map and redirect map
    replaced; the other namespace and 'version' pass through unchanged."""
    other = "composers" if namespace == "works" else "works"
    return {
        "version": registry["version"],
        namespace: registered,
        other: dict(registry[other]),
        "redirects": {
            namespace: redirects,
            other: dict(registry["redirects"][other]),
        },
    }


# --- site.sqlite: schema, fingerprint, atomic write, status -----------------
# JSON-blob facets by design (see task brief): the renderer consumes one dict
# per page: relational decomposition of the *_json columns buys nothing here.
# The tables below are content-EMPTY as of this task; Tasks 5-7 populate them.

_SITE_SCHEMA = """
CREATE TABLE meta       (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE works      (slug TEXT PRIMARY KEY, composer_slug TEXT NOT NULL,
                         composer_key TEXT, work_key TEXT,
                         work_display TEXT, composer_display TEXT,
                         catalogue TEXT, airings INTEGER,
                         n_recordings INTEGER, n_text_only INTEGER,
                         first_aired TEXT, last_aired TEXT,
                         facets_json TEXT);
CREATE TABLE composers  (slug TEXT PRIMARY KEY, composer_key TEXT,
                         display TEXT, airings INTEGER, n_works INTEGER,
                         works_json TEXT);
CREATE TABLE episodes   (pid TEXT PRIMARY KEY, date TEXT, title TEXT,
                         bbc_url TEXT, tracks_json TEXT);
CREATE TABLE recordings (recording_pid TEXT PRIMARY KEY, work_slug TEXT,
                         composer_slug TEXT, duration INTEGER,
                         broadcaster TEXT, airings INTEGER,
                         first_aired TEXT, last_aired TEXT,
                         contributors_json TEXT, airing_dates_json TEXT);
CREATE TABLE browse     (name TEXT PRIMARY KEY, payload_json TEXT);
"""

# Column count per table, in insertion-tuple order -- used only to build the
# executemany placeholder string (?, ?, ...); the CREATE TABLE text above is
# the single source of truth for names/order, this just counts columns.
_SITE_TABLE_COLUMNS = {
    "works": 12,
    "composers": 6,
    "episodes": 5,
    "recordings": 10,
    "browse": 2,
}


def site_fingerprint(registry_path):
    """sha1 hex over, in order: this module's bytes, ttn_analyze.py,
    ttn_aliases.py, the projection cache file, and the registry file at
    `registry_path`. A missing file hashes as the empty string for that slot
    (tolerant, like _slug_cache_fingerprint) -- site_fingerprint itself never
    raises; only a hard build-time consumer (_run_build) treats a missing
    projection/registry as an error, and it does so explicitly, not via this
    function silently failing."""
    h = hashlib.sha1()
    for path in (os.path.abspath(__file__), _ANALYZE_MODULE_PATH,
                 _ALIASES_MODULE_PATH, ttn_project.PROJECTION_PATH,
                 registry_path):
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"")
    return h.hexdigest()


def write_site_db(path, tables, fingerprint):
    """Build the full site.sqlite schema at `path + ".tmp"`, insert `tables`'
    rows, stamp `meta` with the fingerprint + build time, then atomically
    os.replace onto `path`. `tables` is a dict {table_name: [row_tuple, ...]};
    a missing key means that table stays empty. Any exception (including a
    poisoned row failing executemany) leaves neither the tmp file nor a
    partial `path` behind -- the tmp is removed on failure, and `path` itself
    is only ever touched by the final os.replace, so a failed rebuild can
    never clobber a previously-good file there."""
    tmp = f"{path}.tmp"
    if os.path.exists(tmp):
        os.remove(tmp)   # a leftover tmp from a killed prior run

    try:
        conn = sqlite3.connect(tmp)
        try:
            conn.executescript(_SITE_SCHEMA)
            for table, n_cols in _SITE_TABLE_COLUMNS.items():
                rows = tables.get(table, [])
                if rows:
                    placeholders = ", ".join("?" * n_cols)
                    conn.executemany(
                        f"INSERT INTO {table} VALUES ({placeholders})", rows)
            built_at = dt.datetime.now().isoformat(timespec="seconds")
            conn.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [("fingerprint", fingerprint), ("built_at", built_at)])
            conn.commit()
        finally:
            conn.close()
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    os.replace(tmp, path)


def site_status(path, fingerprint):
    """'fresh' | 'stale' | 'missing'. A missing file, or a present-but-corrupt/
    wrong-shape one (not a valid SQLite file, no meta table, no fingerprint
    row), degrades to 'missing' -- never an exception. This is the DERIVED-
    cache convention (the projection-cache lesson): site.sqlite is rebuildable
    from the DB + registry, unlike the git-tracked registry's hard-error rule
    in load_registry. A readable fingerprint that doesn't match is 'stale'."""
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "missing"

    if row is None:
        return "missing"
    return "fresh" if row[0] == fingerprint else "stale"


# --- CLI -----------------------------------------------------------------

_WHOLE_CORPUS_SQL = (
    "SELECT t.title, t.composer, t.composer_line, t.performers, "
    "substr(e.broadcast_date, 1, 10), t.episode_pid, t.position "
    "FROM tracks t JOIN episodes e ON t.episode_pid = e.pid")


def _die_needs_warm(reason):
    print(f"ttn_site: {reason} -- run `uv run ttn_data.py warm` first, "
          f"then re-run `uv run ttn_data.py site`.", file=sys.stderr)
    raise SystemExit(1)


def _run_build(db_path, registry_out_path, site_db_out_path, force=False):
    """The default action: sync the registry against the current corpus, then
    build/refresh site.sqlite. Explicit consumer of the projection (SP4a
    rule) -- `ttn_project.load`, never `ensure`: a stale/missing projection is
    a hard error naming `uv run ttn_data.py warm`, not a silent ~5-minute
    rebuild kicked off from a site build. Same for a missing/stale slug-map
    cache.

    site.sqlite step: the fingerprint is computed AFTER the registry dump, so
    it covers the just-written registry bytes (a registry sync that added
    slugs must invalidate a stale site.sqlite). A 'fresh' status (and no
    --force) short-circuits without touching the file; otherwise
    write_site_db rebuilds it. Tables are EMPTY here -- Tasks 5-7 populate
    them; this task only wires the fingerprint/write/status machinery in."""
    conn = sqlite3.connect(db_path)
    try:
        projection, rec_meta, status = ttn_project.load(conn)
        if status != "ok":
            _die_needs_warm(f"projection cache status is {status!r}")

        slug_map = load_slug_map(ttn_project.PROJECTION_PATH)
        if slug_map is None:
            _die_needs_warm("the work-slug cache is missing or stale")

        cursor = conn.execute(_WHOLE_CORPUS_SQL)
        rows = list(_project_rows(cursor, projection, rec_meta))
    finally:
        conn.close()

    work_entries = build_work_index(rows)
    for e in work_entries:
        e["slug"] = slug_map.get(e["key"], e["slug"])
    composer_entries = build_composer_index(rows)

    registry = load_registry(registry_out_path)
    try:
        new_registry, report = sync_registry(
            registry, work_entries, composer_entries, today=dt.date.today().isoformat())
    except RegistryDriftError as e:
        print(f"ttn_site: {e}", file=sys.stderr)
        print("fix: `uv run ttn_data.py site --remap \"SLUG|COMPOSER_KEY[|WORK_KEY]\"` "
              "(add --composer for the composers namespace)", file=sys.stderr)
        raise SystemExit(1)

    dump_registry(new_registry, registry_out_path)

    print(f"ttn_site: registry synced -- {registry_out_path}")
    print(f"  registered works:     {len(new_registry['works'])} "
         f"(+{report['added_works']} new)")
    print(f"  registered composers: {len(new_registry['composers'])} "
         f"(+{report['added_composers']} new)")
    print(f"  slug drift (informational, mapping unchanged): {len(report['slug_drift'])}")
    print(f"  collisions (suffixed on assignment):            {len(report['collisions'])}")

    fp = site_fingerprint(registry_out_path)
    if not force and site_status(site_db_out_path, fp) == "fresh":
        print(f"ttn_site: {site_db_out_path} fresh -- skipping")
        return 0

    write_site_db(site_db_out_path, {}, fp)
    print(f"ttn_site: site.sqlite built -- {site_db_out_path}")
    return 0


def _run_rename(registry_out_path, namespace, old, new):
    registry = load_registry(registry_out_path)
    try:
        new_registry = apply_rename(registry, namespace, old, new)
    except RegistryActionError as e:
        print(f"ttn_site: rename refused -- {e}", file=sys.stderr)
        raise SystemExit(1)
    dump_registry(new_registry, registry_out_path)
    print(f"ttn_site: renamed {namespace} slug {old!r} -> {new!r} "
         f"(redirect left at {old!r})")
    return 0


def _run_remap(registry_out_path, namespace, spec):
    parts = spec.split("|")
    if namespace == "works":
        if len(parts) != 3:
            print("ttn_site: --remap for works needs "
                 "\"SLUG|COMPOSER_KEY|WORK_KEY\"", file=sys.stderr)
            raise SystemExit(1)
        slug, composer_key, work_key = parts
    else:
        if len(parts) != 2:
            print("ttn_site: --remap --composer needs \"SLUG|COMPOSER_KEY\"",
                 file=sys.stderr)
            raise SystemExit(1)
        slug, composer_key = parts
        work_key = None

    registry = load_registry(registry_out_path)
    try:
        new_registry = apply_remap(registry, namespace, slug, composer_key, work_key)
    except RegistryActionError as e:
        print(f"ttn_site: remap refused -- {e}", file=sys.stderr)
        raise SystemExit(1)
    dump_registry(new_registry, registry_out_path)
    if slug in new_registry["redirects"][namespace]:
        print(f"ttn_site: remapped {namespace} slug {slug!r} -> redirect to "
             f"{new_registry['redirects'][namespace][slug]!r} (successor already registered)")
    else:
        print(f"ttn_site: remapped {namespace} slug {slug!r} to its successor identity")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="ttn_site.py",
        description="Build the website substrate: sync the frozen slug registry, "
                    "then build/refresh site.sqlite, from the current corpus.")
    ap.add_argument("--db", default="ttn.sqlite", help="SQLite path (default: ttn.sqlite)")
    ap.add_argument("--registry", default=None,
                    help="registry JSON path (default: ttn_site_registry.json beside this module)")
    ap.add_argument("--site-db", default=None,
                    help="site.sqlite output path (default: site.sqlite beside this module)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild site.sqlite even if it's already fresh")
    ap.add_argument("--composer", action="store_true",
                    help="apply --rename/--remap in the composers namespace (default: works)")
    ap.add_argument("--rename", nargs=2, metavar=("OLD", "NEW"),
                    help="move a registered slug's identity from OLD to NEW, leaving a redirect")
    ap.add_argument("--remap", metavar="SPEC",
                    help="re-point an orphaned slug at its successor identity: "
                        "\"SLUG|COMPOSER_KEY|WORK_KEY\" (or \"SLUG|COMPOSER_KEY\" with --composer)")
    args = ap.parse_args(argv)

    reg_path = args.registry if args.registry is not None else registry_path()
    site_db_out = args.site_db if args.site_db is not None else site_db_path()
    namespace = "composers" if args.composer else "works"

    if args.rename:
        return _run_rename(reg_path, namespace, args.rename[0], args.rename[1])
    if args.remap:
        return _run_remap(reg_path, namespace, args.remap)
    return _run_build(args.db, reg_path, site_db_out, force=args.force)


if __name__ == "__main__":
    main()
