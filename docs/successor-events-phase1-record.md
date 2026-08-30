# P4 phase 1 — process record (successor-backed site substrate)

Record of how the 2026-08-28/29 phase-1 cutover work was executed, adjudicated,
and converged — preserved because the SDD workspace that held the live
narrative was deleted at completion, and because `docs/superpowers/` (the
plan doc's home) is gitignored, so the plan itself is local-only. Written
2026-08-29 from the session record at the maintainer's request. Companion
documents: `docs/successor-events-framework.md` (the design + phase state),
the plan at `docs/superpowers/plans/2026-08-28-p4-site-cutover-phase1.md`
(LOCAL ONLY — 953 lines, design + per-task specs), and the tracked
`ttn2_ledger.json` (the decisions record, incl. the 19 EBU-order link rows
with evidence).

## What shipped

8 commits on master (rebased onto the nightly's 2026-08-29 registry sync,
pushed as `f32d131`):

| commit | subject |
|---|---|
| `05b142a` | Anchor the 15 resolvable bilingual/traditional slugs; retire monsch (pre-plan curation tail) |
| `0a041d2` | ttn2: ingest the full graduated-trust link set (bridge events + medium presentation) |
| `fef47eb` | ttn2_site: successor identity maps + accumulate_entities_t2 (ledger-resolved keys) |
| `4b7575c` | ttn2_site: work/composer entries + evidence map from successor groups |
| `430c848` | ttn_site: --source successor builds site2.sqlite from the events framework |
| `eeef843` | ttn2: converge the site parity gate — pid resolution, ledger-as-decisions-record, EBU-order link rows, spine filter |
| `1fd7ab2` | docs: P4 phase 1 landed |
| `f32d131` | ttn2: final-review fixes — t2 fingerprint covers shared modules, parity gate exits on unratified+years only, loud ledger-wipe warnings |

Final verified state: suite 2,660 passed / 45 deselected; parity linkage
19/134,465 all ledger-explained (unratified 0); identity delta 225 keys
(report-only, the true de-globalization divergence); site gate 988
ledger-explained / 13 traced-ripple (parked) / 1 parked curation item /
**0 unexplained**. Legacy path byte-identical and still the default.

## Execution shape

Six tasks, each implementer-dispatched and independently reviewed (spec +
quality), then a final whole-branch review with one fix wave and a scoped
re-review. ~10 implementer dispatches, 7 reviews. Tasks 2-4 landed near
first-pass (the plan carried complete code); essentially all the effort went
into Task 5's gate convergence — five fix rounds, two of them turning on
human rulings, one on a refuted controller spec. Environment note: the fixer
agent lane degenerated mid-session (3x malformed generations, zero disk
effect); the sidekick lane carried all subsequent implementation.

## The four adjudicated rulings

1. **Strip/normalize joins the successor identity chain** (gate fail #1, 479
   unexpected). The legacy site accumulator folds compound composer credits
   via `strip_arranger_tail(c, COMPOSER_LINE)` — e.g. `Traditional,Edvard
   Grieg (1843-1907), Marius Loken (arranger)` -> `traditional` — while the
   successor chain (mirroring `ttn2_query.load_groups`, which never sees the
   line) kept `traditional edvard grieg` split. Verified by row trace: same 9
   airings, same recording `p04trmlq`, two keys; `strip_arranger_tail` is a
   no-op without the line. Ruling: `strip_arranger_tail(cm, composer_line)` +
   `normalize_composer` are canonicalization vocabulary (NOT alias decisions)
   and run before ledger resolution; the prohibition stays on
   `resolve_composer_alias`/`resolve_work_alias` (the de-globalization trap).
   Effect: 479 -> 149 unexpected.

2. **EBU ordering vs BBC synopsis** (the 19 successor-only links). The
   successor DP correctly links 4 episodes whose EBU syndicated-playlist
   ordering diverges from the BBC broadcast: `m001556v`/`m00154mb`/
   `m001554q`/`m0014y5c` carry the corpus's only 5 position-0 segment rows
   with late version_offsets (20311s/19315s/13300s/8615s+13696s) from the
   syndication schedule; the legacy DP's temporal cascade demotes those
   matches. Maintainer ruling, with evidence
   (https://www.ebu.ch/files/live/sites/ebu/files/notturno-playlists/2022/03/17%20March%202022.pdf
   + https://www.bbc.co.uk/programmes/m001556v): the BBC synopsis ordering is
   GROUND TRUTH for track ordering (interstitials ignored as always) when the
   segment JSON disagrees; EBU PDFs verify ordering WITHIN a 2-hour segment
   but the ordering OF THE SEGMENTS may differ, and the BBC sometimes does
   not broadcast all 6 hours. The 19 links are ratified as ledger rows
   (`kind='link'`, `method='ebu-order-correction'`, `_EBU_ORDER_LINKS` in
   `ttn2_ledger.py`); `_pos_of`'s 0->None->voff fallback is documented as the
   mechanism, not changed.

3. **The ledger is the decisions record** (after the round-3 wipe). The
   round-3 spec ordered `ttn2_ledger.py import`, which rebuilt the ledger
   from `ttn_aliases.py` and silently destroyed the 140 curated `deglob-*`
   ledger-only rows (the P4 triage's de-globalization conversions live ONLY
   in the ledger + tracked JSON). Recovered from HEAD's tracked export.
   Structural fix: `import` = restore-from-tracked-JSON + link-row top-up;
   the from-aliases derivation is demoted to `bootstrap-from-aliases`; a
   DB-only-row warning and an empty-ledger warning in `load_maps` make the
   wipe class loud (final review).

4. **Spine filter before accumulate** (gate fail #4, 84 works rows). Task 4's
   successor branch passed the UNFILTERED presentation map into
   accumulation; 94 entries carried spine-excluded rps (mostly `p02ggvkg`).
   `build_work_rows`' n_recordings/n_text_only counters read `work_airings`
   directly — BEFORE any downstream spine gating — so counts shifted while
   facets stayed byte-identical (bwv1041: n_rec 10->11, n_text 19->18, facets
   identical). This reversed part of the Task-4 review's "sound" ruling (the
   reviewer missed the counter path). Fix: the successor branch spine-filters
   presentation exactly like legacy (ttn_site.py's by-construction filter),
   before `accumulate_entities_t2`.

## The delta archaeology (why the "233-key delta" narrative was wrong)

The identity delta moved 233 -> 231 -> 225 -> 12 -> 225 across the session.
The 12-key collapse was NOT the raw-vs-resolved fix (that was tiny: 2
recording merges, 17 events) — it was the round-3 import wipe deleting the
deglob rows. The true composition of the 225: ~213 keys of genuine
ledger-vs-aliases de-globalization divergence + 6 keys of EBU-link identity
shadow + a few raw-vs-resolved keys. Corollary: the plan's "233-key
de-globalization delta" baseline (carried from the pre-plan parity runs)
conflated the reference-projection choice with real divergence — the early
parity harness compared against the 2012+-only projection where pre-2012 rows
were raw on BOTH sides.

## Gate convergence trail

479 unexpected (strip/normalize class) -> 149 (ruling 1 applied) -> 111
measured with the deglob rows wiped (invalid state) -> 104 (ledger restored,
delta 225) -> 14 (spine filter + exception classification) -> final: 988
expected / 13 traced-ripple / 1 parked. The 13: the arithmetic shadow of the
21 ratified exception recordings propagating through rp_stats-weighted
composer facets and browse aggregates, which carry no rp for the token
classifier to see — parked at the fix-loop cap rather than masked with
aggregate-exemption machinery. The 1: `kyurkchiiski` vs `krasimir-kyurkchiyski`
composer spelling, a real alias candidate for the phase-2 curation worklist.

## Final-review findings (all fixed in `f32d131`)

- `site_fingerprint_t2` covered only the ttn2 modules — the successor build
  also executes ttn_site/ttn_analyze/ttn_aliases/ttn_project/ttn_segment_meta/
  ttn_spine/ttn_ebu_codes/ttn_broadcasters; an edit to any of them
  fresh-skipped a stale site2.sqlite. Slots added, test pinned.
- `ttn2_parity` was a permanently-red gate (19 ratified links + the 225-key
  delta counted into the exit). Now exits on unratified linkage + year diffs;
  the identity delta is report-only. Lesson: parity-tool exit semantics are a
  deliverable, not an afterthought.
- `import_aliases` warns before losing DB-only rows; `load_maps` warns on an
  empty ledger (the silent raw-key-identity failure mode).
- `link()` resets `presentation`; the legacy drift stderr regained its
  `[|WORK_KEY]` brackets.

## Parked (phase-2 queue)

Registry entity-ID re-anchor + the drift batch (starts from
`ttn2_site_parity.compute_delta_keys`, which doubles as the drift worklist
generator); default flip + legacy read-path freeze; `ttn_nightly.sh` must go
entity-aware in the same window (it mints slugs keyed by (ck, wk));
`ttn2_query` curation-layer reconciliation (ev_rp join + missing
strip/normalize — the curation layer diverges from the site layer in two
ways); `kyurkchiiski` alias fold; the 13-row ripple becomes ledger-shaped or
is re-derived at cutover; the ratified link set is (ep, pos)-keyed and
rp-blind (a wrong-recording link at a ratified position would pass the gate —
the ledger rows carry the expected rp; tighten if it ever matters);
`override_composer_display` still reads `ttn_aliases` data (migrate when the
alias tables freeze).

## Lessons

- The SDD cleanup rule ("delete the workspace — the git history is the
  record") fails when plan docs are gitignored: `.gitignore:49` ignores all
  of `docs/superpowers/`, so the plan and the process narrative had no git
  record. This doc exists because of that; the skill's Finish step was
  amended (2026-08-29, maintainer request) to preserve the narrative before
  deletion.
- Adversarial verification paid twice: the round-2 implementer refuted the
  controller's mbid-mirror spec with corpus evidence (it would have exploded
  the delta to ~4,600), and the round-3 continuation refuted the
  delta-collapse hypothesis. Evidence beat the spec both times; the spec was
  amended rather than forced.
- Destructive rebuilds need loud guards BEFORE they bite: the ledger wipe was
  procedurally recoverable (tracked JSON) but structurally invisible until a
  test pin failed.
