# Successor framework: events-first ingestion and analysis

Status: scope/design, 2026-08-27. Not a build plan yet — this is the
agreed-shape document for what a successor to the ttn.sqlite pipeline looks
like, given everything the curation sessions have learned about the corpus.

## 0. Why a successor, and why not a rewrite

The current pipeline froze around its first data source. `tracks` (parsed
from long_synopsis) is the substrate; `segment_events` is a parallel table;
the projection cache is a JSON-file reconciliation layer that answers "what
is a performance?" at analysis time instead of the data saying so. Identity
is derived from credit *strings* at runtime (3,537 global alias pairs, 552
composer pairs), with MBID demoted to an audit signal. The 2026-08-27 alias
audit showed the cost: ~450 airings mis-grouped by bare-generic global
folds, and every identity edit re-keys work_keys, churning the slug
registry.

The successor inverts the layering: **observations** (what each source
says) are stored side by side; **events** (what actually aired) are linked
from them; **entities** (composers, works, people) carry stable IDs; and
every identity decision lives in a **ledger**, not in executable tables.

Deliberately NOT a big-bang rewrite. The current pipeline stays frozen and
deployed; the successor is built alongside it and adopts by parity (see §7).

## 1. Non-negotiables carried over

- Preserve-raw, normalize-late: raw_json / segments_raw_json untouched;
  every interpretation is downstream and re-runnable.
- Human-ratify-not-auto: matchers propose, ledgers record, nothing silent.
- SQLite + Python + uv, same repo, single-file simplicity per stage.
- URL stability: mint-once slugs, retire-forever — but anchored to entity
  IDs, not to alias-dependent strings.
- Honesty on pages: data-window hedges, partial-year flags, disclosure
  lines all survive.

## 2. Model

### 2.1 Layers

```
SOURCES                OBSERVATIONS                 EVENTS / ENTITIES
-----------            ----------------------------  ----------------------
episodes.raw_json  ->  track_obs      (text era)    event        (what aired)
episodes.seg_raw   ->  segment_obs    (2012+)            | linked from
                       |                                   | observations
                       +-> matched into -------->----------+
                                                           |
                       ledger (decisions)  ---------> entity: composer / work /
                       (alias folds, obs->event        person / ensemble
                       links, entity merges,           (stable IDs; MBID and
                       splits, remaps)                 credit-key as identifiers)
```

### 2.2 Observations (the side-by-side core)

One row per source statement about a piece of music on a night:

```sql
CREATE TABLE obs (
  id INTEGER PRIMARY KEY,
  episode_pid TEXT NOT NULL,        -- both sources share this anchor
  ord REAL NOT NULL,                -- temporal/positional anchor (see below)
  source TEXT NOT NULL,             -- 'text' | 'segment'
  raw_fields_json TEXT NOT NULL,    -- verbatim extraction, no cleanup
  -- extracted fields, each nullable (absence != zero):
  composer_raw TEXT, composer_mbid TEXT,
  title_raw TEXT, recording_pid TEXT,
  duration_s INTEGER,
  performers_json TEXT,             -- role-typed, verbatim
  source_grade TEXT NOT NULL,       -- 'seg' | 'seg_early' | 'text'  (§3)
  event_id INTEGER                  -- NULL until linked
);
```

- `ord`: segments carry `version_offset`/position; the text era has
  time_str and parse order. Both normalize to a comparable per-night
  ordinal. Where a text-era time is missing, ord = parse order (same
  convention the DP matcher uses today).
- No field is *trusted* because of its source; every field carries
  `source_grade`, and the grades are honest about the corpus: `seg_early`
  (2012–2014) is NOT grade A — the QC-marker leaks, wrong instruments and
  key mislabels found in 2026 all came from there. Grades are era+field
  aware and reviewed by the qc-audit port at ingest.
- Parsing bugs stay fixed at extract time, but the extract is re-runnable
  from raw (same discipline as today's reparse, now per-source).

### 2.3 Events

An event = one broadcast performance as *identified across sources*. The
matcher (the existing DP matcher, promoted from cache-rebuilder to
ingest-time reconciler) clusters observations:

```sql
CREATE TABLE event (
  id INTEGER PRIMARY KEY,
  episode_pid TEXT NOT NULL,
  ord REAL NOT NULL,
  work_id INTEGER, person_ids_json, ensemble_ids_json,  -- entity refs
  confidence TEXT,               -- link grade (single-source, matched, merged)
  method TEXT                    -- which matcher/decision created the link
);
-- obs.event_id points back; unmatched obs form singleton events, so the
-- analysis spine is complete even where matching failed.
```

The decisive property: **rankings count events, not observations.**
Double-counting across sources becomes structurally impossible instead of
a dedup heuristic. Pre-2012 text-only observations are simply events with
one observation — the "two regimes" disappear from every downstream tool.

### 2.4 Entities

```sql
CREATE TABLE entity (            -- composers, works, people, ensembles
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,            -- composer|work|person|ensemble
  name TEXT NOT NULL,            -- display (corpus-majority, override-able)
  ids_json TEXT                  -- {"mbid": ..., "recording_pids": [...],
);                               --  "credit_key": "§..."} -- all optional
```

- Works-as-performed are entities: an arrangement/alt-scoring is its own
  work entity with an optional `derived_from` relation. The alt-scoring
  policy becomes structure, not convention.
- The credit string (`work_title_key`) demotes to a *matching signal* kept
  on observations and in the ledger — never the grouping key.
- Unresolved entities are first-class: a work entity with no MBID and a
  provisional name is a normal citizen until a decision merges it.

### 2.5 The ledger (aliases become data)

Every identity decision is a row: scope (composer or global), matcher
(credit-key / mbid / recording-pid / human), variant, target, evidence
(pid sample / counts), method, actor, date, confidence. The three existing
tables migrate mechanically:

- `_WORK_ALIAS_PAIRS` → ledger rows, `method='legacy-global'`,
  `confidence='review'` — the 2026-08-27 audit flags (bare-generic,
  cross-composer) ride along as review flags.
- `_COMPOSER_SCOPED_WORK_ALIAS_PAIRS` → `method='legacy-scoped'`,
  `confidence='medium'` (oracle-backed where the comment says so).
- Composer pairs → entity merges.

Resolution at analysis time = ledger lookup (a query, not Python imports),
so "which decisions affect this page" is answerable, and the
blast-radius class of bug (bare-generic global folds) is structurally
dead: a global-scope row with no catalogue ref is rejected at write time.

## 3. Mess handling (the honest part)

- **2012–2013 segment metadata is not grade A.** `seg_early` exists so
  analysis can demand better evidence where it matters (work pages) and
  accept it where it doesn't (year tallies).
- **The match will never be perfect.** The framework's job is to make each
  unmatched/ambiguous case visible (qc-audit and fragmentation become
  ledger/observation queries) and cheap to ratify (propose-remaps writes
  ledger rows), not to auto-perfect it.
- **Text-era credit churn is permanent.** Composer transliteration variants
  stay a per-composer, evidence-gated merge problem (the Tchaikovsky-class),
  but now one ledger row per merge, with provenance, instead of an
  executable line in a 9k-file.

## 4. What each existing tool becomes

| Today | Successor |
|---|---|
| ttn_scrape / ttn_segments | ingest stages writing obs (raw stores unchanged) |
| ttn_project (projection cache) | matcher at ingest; events table |
| ttn_analyze | ranking queries over events/entities (no --source modes) |
| ttn_aliases.py | ledger (+ a thin read shim during transition) |
| ttn_mbid_audit / ttn_duplicates / composer-duplicates | observation/entity queries |
| fragmentation --projected, work-recordings, qc-audit, propose-remaps | direct queries — these four were prototypes of the successor's queries |
| ttn_site / ttn_site_render / registry | unchanged consumers; registry re-anchored to entity IDs at cutover |
| ttn_data (kitchen) | same door shape: ingest / reconcile / materialize / render |

## 5. Migration of decisions (the risky part, made boring)

1. Export all current tables to the ledger with method/confidence tags.
2. Re-run the audit script against the ledger; dump the review worklist
   (the 12 de-globalized folds are already done; ~135 residual
   cross-composer keys get triaged).
3. Slug registry: current slugs map 1:1 to (composer_key, work_key) —
   at cutover each maps to its work *entity*; collisions on merge are
   resolved by the existing redirect/retire machinery. No slug is ever
   re-keyed again, because entity IDs don't move.

## 6. Parity harness (how we know it's right)

Before any cutover: the successor materializes the same aggregates
site.sqlite holds today. A harness diffs old-vs-new for (a) every ranking,
(b) every work/composer/artist page's airing set, (c) airings-per-year
totals, classifying diffs as expected (this session's folds + the
de-globalization) vs unexpected. Expected-diff manifest is generated from
the ledger — a diff with no ledger explanation blocks cutover.

## 7. Phases (each lands something usable)

- **P0 — parity harness + ledger schema.** Nothing user-visible; the
  safety net that makes everything after it cheap.
- **P1 — dual-write ingestion.** Both sources → obs in a *side* DB
  (successor.sqlite); current pipeline untouched. Ingest-time qc-audit.
- **P2 — matcher + ledger import.** Events materialize; legacy aliases
  imported as tagged ledger rows; audit worklist triaged.
- **P3 — analysis parity.** Rankings/counts diffed against the old
  pipeline; the 4 prototype tools (fragmentation --projected,
  work-recordings, propose-remaps, qc-audit) re-issued as ledger queries.
- **P4 — site cutover.** site.sqlite built from successor; registry
  re-anchored to entity IDs; old pipeline freezes read-only (kept for
  reparse archaeology).
  - Phase 1 (landed 2026-08-29): `ttn_data.py site --source successor`
    builds site2.sqlite from events/entities via ttn2_site.py; the full
    graduated-trust link set (bridge events + medium presentation) is
    ingested; ttn2_site_parity.py diffs legacy vs successor site.sqlite -
    final state 988 ledger-explained / 13 traced-ripple (parked: arithmetic
    shadow of the 21 ratified exception recordings through rp_stats-weighted
    aggregates) / 1 parked curation item (kyurkchiiski composer spelling) -
    0 unexplained. The ledger is the decisions record: `ttn2_ledger.py
    import` restores from the tracked ttn2_ledger.json + link-row top-up
    (from-aliases demoted to bootstrap-from-aliases). Registry/evidence stay
    read-only in successor mode; legacy remains the default.
  - Phase 2 (remaining): registry entity-ID re-anchor, the drift batch for
    the de-globalized identities, default flip, legacy read-path freeze, and
    the parked curation items (kyurkchiiski/kyurkchiyski alias candidate;
    the 13-row ripple becomes ledger-shaped or is re-derived at cutover).

Effort honesty: P1–P2 are the bulk (ingestion rewrite + matcher promotion);
call it the largest single work item the project has had. P3–P4 are
mechanical once parity is green. Nothing before P4 changes the live site.

## 8. Explicit non-goals

- No new stack, no server, no Postgres — SQLite is the right size.
- No attempt to *solve* credit-spelling ambiguity automatically; the
  framework makes it visible and ratifiable.
- No rewrite of the renderer or templates.
- No backfill of pre-2012 data that doesn't exist; text-era observations
  are sparse by nature and the framework says so instead of hiding it.
