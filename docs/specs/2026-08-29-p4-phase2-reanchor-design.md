# P4 phase 2 — registry re-anchor + drift batch (design)

Status: approved design, 2026-08-29. Implementation plan follows in
`docs/plans/` (tracked). Phase 1 record: `docs/successor-events-phase1-record.md`.
Framework: `docs/successor-events-framework.md` §7.

## Context

Phase 1 shipped the successor-backed site substrate behind
`--source successor` (site2.sqlite) with a converged parity gate: 988
ledger-explained / 13 traced-ripple (parked) / 1 parked curation item /
0 unexplained. Phase 2 prepares the cutover (phase 3: default flip + legacy
freeze) by re-anchoring the slug registry to entity IDs and clearing the
string-key drift.

Grounded numbers (measured 2026-08-29):

- Registry: 20,042 work slugs, 3,525 composer slugs, 788 redirects, 2 retired.
- Successor groups: 20,098.
- All 20,044 slugs already have entity anchors in the ledger (phase-1 P4
  anchoring work, exported in `ttn2_ledger.json`).
- **151 orphaned work slugs** (registered (composer_key, work_key) absent
  from successor groups) + 10 orphaned composer slugs. Rough tiers:
  ~88 same-composer near-key (mechanically corroborable), ~51 same-composer
  no-near (review), ~12 composer-gone (dissolved/retire candidates). The
  orphan class is dominated by the `anonymous:`/`anon:` fold fallout and the
  traditional/bilingual class — de-globalization fallout, not missing anchors.
- The nightly (`ttn_nightly.sh`) already runs `site --check` with auto-remap
  for the LEGACY path and is untouched by this phase.

## Decisions (made interactively 2026-08-29)

1. **Staged end state**: phase 2 = re-anchor + drift batch only. The default
   flip, legacy read-path freeze, and nightly entity-aware minting move to
   phase 3, after the drift batch is human-validated.
2. **Additive entity_id schema**: registry entries gain `entity_id`; the
   (composer_key, work_key) strings remain as a derived cache refreshed from
   the entity. Rejected: entity-only schema (breaks every registry consumer
   at once) and string-remap-only (double-handles the 151 and leaves the
   re-key churn alive during exactly the curation window).
3. **Agent-proposed, maintainer-ratified** drift process (the phase-1
   bilingual/anon-trad precedent).
4. **Registry-centric additive implementation**: the entity authority lives
   in the ledger's anchor table; the registry gains entity_id and derived
   strings. Rejected: ledger-centric regeneration (collides with the
   nightly's johnson-side registry commits — a two-writer problem with no
   merge discipline) — its benefits land at phase 3's flip anyway.

## Design

### 1. Registry schema (additive)

Each works/composers entry gains `entity_id` (integer, the ledger's
work_entity id, resolved via the slug→entity anchor table). The
(composer_key, work_key) strings remain in the file, reclassified as a
**derived cache**: refreshed from the anchor entity's resolved keys at sync
time and written on dump.

- Authority: slug→entity = the ledger's anchor table (tracked
  `ttn2_ledger.json`). The registry keeps its human annotations: redirects,
  retired (+reasons), collision suffixes.
- Back-compat: `entity_id` is optional on load (the same `.get` discipline
  the `retired` namespace uses — an ordinary build after a partial edit must
  not wipe it). Entries without anchors are valid but flagged unanchored.
- Corrupt registry = hard error (unchanged). Corrupt ledger JSON = hard error
  (unchanged from phase 1's restore semantics).

### 2. sync_registry's new semantics

- The build gate becomes: **anchor exists in the ledger AND the anchor's
  entity resolves in successor groups** — an entity resolves when at least
  one of its member (composer_key, work_key) keys (the `work_entity_key`
  rows) is present in the successor groups. Failure = the existing drift
  error, keyed on entity (the fix hint names the anchor, not string remaps).
- String drift (stored ck/wk ≠ the entity's resolved keys) downgrades to
  **informational**: logged per entry, and the derived cache auto-refreshes
  in the dump. Never build-failing.
- Unanchored entries (new nightly mints): informational "unanchored" list;
  the drift pass anchors them incrementally as it re-runs.
- The evidence-heal machinery is **deleted** (its job — healing string drift
  — is obsolete once the entity is the identity). Deletion over addition.
- Collisions/redirects/retired machinery: unchanged (slug-level,
  entity-agnostic).
- Nightly coexistence: johnson's string-keyed mints are new entries, disjoint
  per-entry from local derived-refreshes of existing entries — git merges
  stay clean (the phase-1 coexistence experience).

### 3. The drift batch — 151-anchor validation

A new proposal generator (ttn2 subcommand, e.g. `ttn2_query drift-batch`)
emits per-slug evidence files: the anchor (entity_id, legacy keys), the
successor group(s) the entity resolves to (display, airing counts), the
registered strings, the corroboration tier, and a proposed verdict.

Three ratification batches (the generator's classification is authoritative;
the ~88/~51/~12 context numbers are the difflib-based estimates it starts
from):

- **~88 mechanical**: the anchor entity resolves under the registered
  composer with a corroborating near-key. One-word ratification per entry;
  emitted as a batch file in the `--remap-file` tradition.
- **~51 review**: same composer, no near key. Side-by-side displays + airing
  counts; accept-anchor or remap per case.
- **~12 dissolved**: composer gone. Retire candidates with reasons — the
  anon/trad precedent: retire rather than guess when the oracle cannot
  corroborate.

Ratification updates the registry (entity_id + derived strings) via the
existing batch machinery, extended to accept entity-verified entries. The
`kyurkchiyski` composer fold rides here (it is one of the drift cases — fold
first via the normal alias mechanics, then its anchor validates cleanly).
New nightly mints during phase 2 are anchored incrementally as the generator
re-runs; the unanchored list shrinks toward zero.

### 4. Ride-alongs and non-goals

In scope: `ttn2_query` reconciliation (ev_rp join → the COALESCE form;
strip/normalize via the shared `_identity_of` — one implementation, no
drift between the curation layer and the site layer).

Out of scope (phase 3): the default flip, legacy read-path freeze, nightly
entity-aware minting, the 13-row ripple becoming ledger-shaped, rp-blind
ratified-set hardening, `override_composer_display` migration off
`ttn_aliases`.

### 5. Testing and success criteria

Tests: registry round-trip (with/without entity_id; the `.get` discipline
pinned); sync_registry gate (anchor missing → drift error; entity unresolved
→ drift error; string drift → informational + derived refresh); generator
tier classification + batch-file emission on synthetic fixtures; the parity
gate stays green throughout (it reads successor groups, not the registry).

**Done means**: all 20,042 work slugs anchored and validated (the 151
resolved: accepted or retired-with-reason); the registry entity-anchored with
derived strings; string drift informational; parity gate 0 unexplained; full
suite green; the nightly's legacy build path untouched and green.

### 6. Sequencing (plan sketch)

1. Registry schema + load/save back-compat (+ tests).
2. sync_registry entity gate + derived-string refresh; evidence-heal
   deletion (+ tests).
3. Drift-batch proposal generator (+ tests).
4. The three ratification batches (maintainer reviews: mechanical ~88 →
   review ~51 → retire ~12).
5. Ride-alongs: kyurkchiyski fold; ttn2_query reconciliation.
6. Docs (framework doc phase state; CLAUDE.md registry section).
