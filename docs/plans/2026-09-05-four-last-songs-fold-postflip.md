# Four Last Songs fold — post-flip curation note (2026-09-05)

**Status:** applied post-flip (2026-09-08). Authored during the P4 phase-3
shadow window (3 green nights at time of writing). Identity-touching curation
was frozen until the flip landed — a ledger edit before then would re-key successor
groups mid-window, produce a new-unexpected parity diff, and reset the
5-green counter. Apply only after Task 6's flip commit.

## The finding

Richard Strauss's *Vier letzte Lieder* (AV 150) fragments into **11 successor
work entities / ~67 airings / 15 recordings** under ~11 BBC titlings. The
successor is NOT at fault: `site.sqlite` vs `site2.sqlite` works rows are
identical for the family, and the ledger carries exactly one row in this
family (id 1647: `4 av150 letzte lieder` → `4 Letzte Lieder for voice and
orchestra (AV.150)`). The fragmentation is the legacy fold-gap inherited
exactly — the keying can't reach it because:

- **Cross-language**: "Four Last Songs" shares zero tokens with the German
  keys; `_fold_conjunctions` covers et/und only, and translation doesn't exist
  in `work_title_key`. (`vier` ≠ `4` too — `_fold_number_words` maps English
  two–twelve only, deliberately.)
- **AV-catalogue glue**: `AV.150` / `AV 150` / bare tokenize three ways
  (`av150` / `150 av` / absent), mirroring the Lesure `L` trap. Do NOT add a
  keying rule for `AV` — fix at the ledger like this note does. (`letzte` is
  already in `ttn_audit_composer._CYCLE_COLLECTION_TOKENS` protecting the
  work's cycle-hood; leave keying alone.)
- The projection can't help: it unifies re-titlings of the *same recording*,
  but these spellings span *distinct* recordings from different EBU sources.

## Evidence all fragments are one work

Complete-cycle durations 1179–1402s across the family's recordings, including
the bare-English ones (p07rgvgy 1331s, p094ytk8 1226s); no excerpt-length
recordings under any fragment. The four songs surface individually only as
movement annotations (one `(Frühling; September; Beim Schlafengehen; Im
Abendrot)` parenthetical airing), never as separate recordings.

**Must stay separate:** Ralph Vaughan Williams, *Four Last Songs* (Roy Douglas
realization) — 1 airing, the ONLY non-Strauss item carrying the title family
corpus-wide. Composer-scoped ledger rows make it untouchable by construction;
verify its page post-fold anyway.

## The fix — 10 composer-scoped ledger `work_alias` rows

Target (the canonical, = the existing id-1647 target, the most-carried
spelling at 20 airings): `4 Letzte Lieder for voice and orchestra (AV.150)`,
key `4 and av150 for letzte lieder orchestra voice` (work_entity 16891).

Rows: `kind=work_alias`, `scope="richard strauss"`, one per variant key.
Variant keys are exact `work_title_key(title, composer)` outputs (measured
2026-09-05 on ttn.sqlite; re-verify at apply time — see checklist). Dedup
guard: `(kind, scope, variant_key)` unique (enforced by ttn2_ledger load).

| Variant key | Corpus spelling(s) it covers | Airings |
|---|---|---|
| `4 last songs` | Four Last Songs; Four Last Songs (1948) | 9 (incl. 4 text-only) |
| `4 last letzte lieder songs vier` | Vier letzte Lieder (Four Last Songs); Four Last Songs (Vier letzte Lieder); …[Vier letzte Lieder] (1948) | 8 |
| `4 and av150 for last letzte lieder orchestra songs vier voice` | Four Last Songs (Vier letzte Lieder) for voice & orchestra (AV.150) (1948) | 12 |
| `4 and av150 for last orchestra songs voice` | Four Last Songs, AV.150 for voice and orchestra | 1 |
| `150 4 av last letzte lieder songs vier` | Vier letzte Lieder (Four Last Songs), AV 150 | 6 |
| `150 av letzte lieder vier` | Vier letzte Lieder, AV 150 | 2 |
| `av150 letzte lieder vier` | Vier letzte Lieder, AV.150 | 2 |
| `4 letzte lieder` | 4 Letzte Lieder | 3 |
| `letzte lieder vier` | Vier letzte Lieder | 2 |
| `4 and for letzte lieder orchestra voice` | 4 Letzte Lieder for voice and orchestra (pre-2012 text-only) | 2 |

Total folded: 47 airings onto the survivor's 20 → one entity at ~67 airings,
~15 recordings. Ledger resolution applies to text rows too (`ttn2_site._identity_of`
resolves wk before projection), so the pre-2012 airings fold as well.

Row shape: copy a scoped precedent (e.g. ledger id 3526, Sibelius `triste
valse`). All current work_alias rows are `legacy-*`; these are the first
post-legacy curation rows — mint a method tag (`curation-scoped` or match
whatever the kyurkchiyski fold lands first uses) and record the choice here.

Apply choice: method tag `curation-scoped`, rows 4714–4723. The target/display
remain the existing survivor spelling and key; evidence cites this dossier.

## Registry impact (post-flip only)

10 registered slugs orphan when the keys fold → expect a 10-row drift batch on
the first post-flip `site` run. These identities MERGE (successor exists) →
**--remap to the survivor's key as redirects, never --retire**. The survivor
keeps its URL and date; entity-id continuity on the anchored entries follows
the phase-2 re-anchor mechanics.

Dissolving (entity): `strauss:4-letzte-lieder` (16896),
`strauss:4-letzte-lieder-for-voice-and-2` (16892), `strauss:four-last-songs`
(16895), `strauss:four-last-songs-av-150-for` (16890),
`strauss:four-last-songs-vier-letzte-lieder` (16889),
`strauss:vier-letzte-lieder` (16988), `strauss:vier-letzte-lieder-av-150`
(16833), `strauss:vier-letzte-lieder-av-150-2` (16963),
`strauss:vier-letzte-lieder-four-last-songs` (16832),
`strauss:vier-letzte-lieder-four-last-songs-2` (16894).

Survivor: `strauss:4-letzte-lieder-for-voice-and` (16891). Correctly EXCLUDED
from the fold: `strauss:allerseelen-*`, `strauss:georgine-from-8-lieder-*`,
`strauss:acht-gedichte-*` (Lieder aus Letzte Blätter, Op. 10 — distinct
works), `strauss:ramble-on-the-last-love-duet` (Rosenkavalier).

## Apply procedure (post-flip)

1. Re-verify the keys on current data:
   `uv run python -c "from ttn_analyze import work_title_key as w; [print(repr(t), '->', w(t, 'Richard Strauss')) for t in ['Four Last Songs','Vier letzte Lieder (Four Last Songs)','Vier letzte Lieder','4 Letzte Lieder']]"` —
   assert each still matches the table above (a keying change since 2026-09-05
   invalidates rows).
2. Append the 10 rows to `ttn2_ledger.json` (ids past the current max; dedup
   guard above; target/display exactly as the survivor's).
3. `uv run python ttn2_entities.py` — fragment keys leave `work_entity_key`
   (entities stay in place; the builder never deletes).
4. Rebuild site2 + `uv run python ttn2_site_parity.py --force` — the 10
   dissolved legacy rows must classify ledger-explained, 0 new-unexpected.
5. First post-flip `site` run after the fold: take the 10-row drift batch as a
   `--remap-file` (see Registry impact).

## Post-fold verification checklist

- [ ] `site2.works`: the family is ONE row (key `4 and av150 for letzte lieder
      orchestra voice`), ~67 airings, ~15 recordings, first_aired 2009-04-01.
- [ ] Work page /work/strauss:4-letzte-lieder-for-voice-and/ shows the merged
      history; the 10 remapped slugs redirect to it (curl each, expect 301).
- [ ] Recording facets unify: /work-recordings (ttn_curate) lists ~15 recs
      under the one work, durations 1179–1402s.
- [ ] RVW's four-last-songs page untouched (distinct composer namespace).
- [ ] Parity gate: works-table diffs all ledger-explained, 0 unexpected.

## Residue / caveats

- p031v7cq (1 airing, 2015-09-03) carries no measured duration — folded on
  title + repertoire evidence only (no competing Strauss work of that name).
- Future spellings pre-covered by the same keys: "Four Last Songs (1948)",
  "Four Last Songs (Vier letzte Lieder)", bracketed-(1948) variants.
- Legacy view stays fragmented by design (ledger doesn't touch the legacy
  path; legacy is unsupported post-flip).
