# P4 phase 3 — process record (the successor flip)

Record of the 2026-08-31 → 2026-09-08 phase-3 cutover work. Preserved because
the SDD workspace is local-only and the decisions, repair mechanics, and review
adjudications are not recoverable from commit subjects alone. Companion state:
`docs/successor-events-framework.md`, the tracked `ttn2_ledger.json`, and the
local SDD ledger/report.

## What shipped

The phase-3 plan started at `d0f05ea`. Tasks 1–4 landed the append-only entity
builder, the successor mint gate, anchor-consistency defense, and the shadow
verification wiring. The shadow window then ran green for five nights,
2026-09-02 through 2026-09-06. The flip landed in `0757113` (with the registry
repair in `50aa751`): successor became the default source, the nightly builds
and renders successor-side, the registry sync is successor-side and mint-gated,
the legacy build was dropped, and entity materialization runs before the drift
gate. The old shadow/verdict/counter block and legacy auto-remap call sites are
gone; drift aborts with manual remap required.

The final review and fix rounds landed the frozen-reference parity behavior,
successor-side MBID artist sync, the parity re-spec, the override memo-key fix,
the registry repair batches, and the fixture/documentation hygiene. The branch
was merge-complete after the scoped re-review.

## Decisions and rulings

- **2026-09-02 — class-based green criterion.** The exact parked parity snapshot
  could not survive a moving corpus: aggregate counts and facet membership
  changed while identity keys stayed fixed. Green therefore means no unexpected
  identity-level row; pure aggregate/count/facet churn is the tolerated
  aggregate-ripple class. The snapshot was re-extracted at Task 4 wiring time.
- **2026-09-02 — repair now.** The first live build exposed 105 registered
  slugs whose stored keys existed in t2/ledger space but could never derive in
  the legacy space. They were repaired before the shadow window restarted,
  not deferred into the flip.
- **PID consistency.** All instances of a particular recording PID share one
  work identity. Where an existing `work_alias` could not express the ruling,
  the maintainer sanctioned a recording-scoped `recording_work_override`.
  This produced row 4703 for p04trmlq and rows 4704–4713 for the closure repair
  class, including the Poradowski fold.
- **Bella one-work ruling.** The same-work identity was kept together through
  the reviewed remap rather than preserving a false sibling split.
- **Sibling-retire policy.** Close-era suffixed mints that duplicate a frozen
  URL identity are retired when they were never publicly deployed; a frozen
  slug is kept or redirected when it has URL history. The flip-day batch retired
  17 unanchored work siblings; the final review retired 45 redundant successor
  mints.
- **Grieg trio.** The three held composer slugs were remapped only after the
  p04trmlq override made the medley one 15-airing group. The trio's redirects
  preserve the frozen composer URLs; no composer fold was guessed.

## Mechanism hunts worth preserving

### The 105-class and closure repair

The 105 entries were not cache drift. Their stored keys were t2/ledger keys:
76 were legacy alias-space divergences, 11 carried composer `arr` divergence,
17 carried attribution divergence, and one was the Bella same-composer work-key
drift. All 105 entity IDs resolved and the reanchor was value-identical, so the
repair was a reviewed remap/retire/anchor batch. The closure-83 investigation
then found a separate structural gap: Medium presentation links supplied
`rp_shown` for display but not to the override identity arm. Nine PID pins plus
one work fold repaired the recording/works join; the companion code change made
the override arm reach presentation-linked airings.

### Lost update

The registry loss was not an admin-tool lost update. `_run_remap` and
`_run_retire` load once, fold the whole batch in memory, and dump once; a
scratch reproduction preserved the batch across separate invocations. The
cause was an explicit `git checkout -- ttn_site_registry.json` during cleanup,
which discarded 17 retires and 15 composer remaps. The batches were reapplied
with persistence probes. Lesson: commit registry decisions promptly; never
checkout over uncommitted registry state.

### Ledger-model mismatch

The first p04trmlq experiment tried to solve a composer-plus-work identity with
`work_alias`. That model resolves only work keys and cannot move `traditional`
to `traditional edvard grieg`. The experiment was rolled back rather than
leaving an ineffective row. The sanctioned per-PID override class was the
minimal mechanism that preserved the ruling without globalizing attribution.

### Mint-before-reanchor ordering

The C1 review found that successor sync could mint a suffixed identity before
the entity gate reanchored an orphaned frozen slug to that same identity. The
result was duplicate identity URLs and dead frozen paths. The immediate repair
retired 45 redundant mints and remapped the remaining stale registrations (36
in the URL-set repair accounting); the general mint-before-reanchor guard is a
phase-4 follow-up. The registry's entity anchor remains the authority.

### Parity legacy-arm corruption and artist sync

The parity tool's legacy arm originally rebuilt through the real tracked
registry and could dump legacy-derived keys into successor-owned frozen state.
It now treats an existing `site.sqlite` as the frozen reference; explicit
`--rebuild-legacy` uses scratch registry copies. The artist registry is
MBID-anchored and mint-once, so successor builds now sync it directly instead
of freezing new artist pages forever.

## Verification

- Successor build-only: closure 0 violations; 20,011 works and 20,255
  recordings.
- Successor render: 54,039 pages, 20,255/20,255 recordings joined, internal
  crawl passed, and the 30,802-document search catalogue was written.
- Full suite: 2,712 passed, 45 deselected.
- URL set: 23,547/23,547 registered baseline URLs, 0 real 404s.
- Parity before flip had 0 unexpected works. Post-flip parity is a
  manual/offline, class-based audit rather than a deploy gate; the first
  post-flip nightly runs it against the legacy `site.sqlite` reference. The
  nightly invariants are closure, URL-set, and the successor drift gate.

## Phase-4 handoff

The phase-4 queue is carried in `docs/successor-events-framework.md`: the
tier-3 redirect queue, fold-ripple mirrors, vacated-key mint cleanup,
Atlanta-chorus performer-credit correction, kyurkchiyski fold, and a possible
composer entity table. It also carries the named-but-unapplied Takemitsu
bare-surname ratification, the p00zt8mv target-slug anchor, the 28 mint-gate
deferrals, the p00thzcc t2 site-pass gap, the mint-before-reanchor guard, and
the URL-checker complement scan beyond the 18ee4f6 baseline.
