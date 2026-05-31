"""Tests for ttn_analyze canonicalization.

Run: uv run --with pytest pytest test_ttn_analyze.py
"""
import argparse
import pytest

import re

from ttn_analyze import (canonical_key, catalogue_ref, parse_performers,
                         resolve_composer_alias, resolve_ensemble_alias,
                         resolve_work_alias, work_title_key,
                         _strip_arrangement_tail, _squash_separators,
                         _drop_implicit_major, _title_filter_pattern,
                         _normalize_title_filter, _form_filter_clauses,
                         _FORM_SYNONYMS,
                         compute_summary, render_summary,
                         _summary_data_fingerprint,
                         _read_summary_cache, _write_summary_cache,
                         _has_parent_work_reference, strip_arranger_tail,
                         _movement_slug)
from ttn_analyze import _WORK_ALIAS_PAIRS, _COMPOSER_ALIAS_PAIRS


# --- WORK_ALIASES table invariants ---------------------------------------

def test_work_aliases_are_chain_free():
    # Every alias must resolve in a SINGLE step: both sides land on the same
    # final key. A chain (preferred key is itself another alias's alternate,
    # mapping onward) silently strands airings in a different group. This is
    # the exact trap the duplicate-harvest verification keeps catching; the
    # whole table must satisfy it.
    broken = [(a, b) for a, b in _WORK_ALIAS_PAIRS
              if resolve_work_alias(work_title_key(a))
              != resolve_work_alias(work_title_key(b))]
    assert not broken, f"{len(broken)} chained alias(es), e.g. {broken[:3]}"


def test_no_dead_work_aliases():
    # A no-op alias (both sides already share a work_title_key) does nothing
    # — work_title_key alone merges them. New ones usually mean a gate now
    # subsumes a hand-fold; lift it out rather than leaving dead weight.
    dead = [(a, b) for a, b in _WORK_ALIAS_PAIRS
            if work_title_key(a) == work_title_key(b)]
    assert not dead, f"{len(dead)} dead no-op alias(es), e.g. {dead[:3]}"


def test_composer_aliases_are_chain_free_and_live():
    broken = [(a, b) for a, b in _COMPOSER_ALIAS_PAIRS
              if resolve_composer_alias(canonical_key(a))
              != resolve_composer_alias(canonical_key(b))]
    assert not broken, f"{len(broken)} chained composer alias(es): {broken[:3]}"
    dead = [(a, b) for a, b in _COMPOSER_ALIAS_PAIRS
            if canonical_key(a) == canonical_key(b)]
    assert not dead, f"{len(dead)} dead composer alias(es): {dead[:3]}"


def test_elgar_honorific_and_moniuszko_mojibake_fold():
    def grp(s):
        return resolve_composer_alias(canonical_key(s))
    edward = grp("Edward Elgar")
    for v in ("Elgar, Sir Edward", "Sir Edward Elgar", "Edward Sir Elgar"):
        assert grp(v) == edward
    assert grp("Stanis?aw Moniuszko") == grp("Stanislaw Moniuszko")
    # false matches must stay out (Bulgaria substring; a different person)
    assert grp("Traditional Bulgarian") != edward
    assert grp("Giles Farnaby, Elgar Howarth") != edward


# --- canonical_key -------------------------------------------------------

def test_canonical_key_nos_marker_kept_whole():
    # "Nos" must normalize as one marker — not match "no" and orphan an "s"
    assert canonical_key("Nos. 17-21") == "nos 17-21"
    assert canonical_key("nos.17-21") == "nos 17-21"


def test_canonical_key_marker_normalizes_before_a_number():
    # the op/no/nos rule still does its job when a digit follows
    assert (canonical_key("Op. 26") == canonical_key("Op 26")
            == canonical_key("op26") == "op 26")
    assert canonical_key("Symphony No.5") == "symphony no 5"


def test_canonical_key_marker_rule_spares_ordinary_words():
    # the op/no/nos marker rule must not fire on words that merely begin
    # with those letters — with no digit following, nothing is normalized
    assert (canonical_key("Norwegian Radio Orchestra")
            == "norwegian radio orchestra")
    assert canonical_key("Opera North") == "opera north"
    assert canonical_key("Nocturne") == "nocturne"


# --- catalogue_ref -------------------------------------------------------

def test_catalogue_ref_extracts_rv():
    assert catalogue_ref("Concerto in C major, RV.444") == "rv444"


def test_catalogue_ref_normalizes_separators():
    # "RV.425" / "RV 425" / "RV425" / "(RV 425)" all the same ref
    assert (catalogue_ref("Mandolin Concerto, RV.425")
            == catalogue_ref("Mandolin Concerto, RV 425")
            == catalogue_ref("Mandolin Concerto (RV425)")
            == "rv425")


def test_catalogue_ref_ignores_opus():
    # Op is handled by the token sort, not treated as a catalogue ref
    assert catalogue_ref("Egmont Overture, Op 84") == ""


def test_catalogue_ref_ignores_bare_key_letter():
    # "in D major" must not be read as a Deutsch catalogue number
    assert catalogue_ref("Symphony in D major") == ""


def test_catalogue_ref_compound_locator():
    # Telemann's "TWV 55:D1" is one ref — the ":D1" tail must not be
    # mis-read as a separate Deutsch "D1" catalogue number.
    assert catalogue_ref("Overture-Suite in D, TWV 55:D1") == "twv55d1"


def test_compound_locator_siblings_stay_distinct():
    # TWV 55:D1 and TWV 55:e1 are different suites of Tafelmusik
    a = "Overture-Suite in D major, TWV 55:D1"
    b = "Overture-Suite in E minor, TWV 55:e1"
    assert work_title_key(a) != work_title_key(b)


# --- work_title_key: catalogue merging -----------------------------------

def test_catalogue_variants_merge():
    # Same Vivaldi concerto (RV.444), wildly different descriptive wording
    a = "Concerto in C major, RV.444 for recorder, strings & continuo"
    b = "Sopranino Recorder Concerto in C major RV.444"
    assert work_title_key(a) == work_title_key(b)


def test_catalogue_separator_variants_merge():
    a = "Mandolin Concerto in C major, RV.425"
    b = "Mandolin Concerto in C major, RV 425"
    assert work_title_key(a) == work_title_key(b)


# --- work_title_key: safety ----------------------------------------------

def test_d899_impromptus_stay_distinct():
    # D.899 is one Deutsch number covering FOUR impromptus, distinguished
    # only by key. The catalogue rule must NOT merge them.
    g_flat = "Impromptu in G flat major, D.899"
    a_flat = "Impromptu in A flat major, D.899"
    assert work_title_key(g_flat) != work_title_key(a_flat)


def test_different_catalogue_numbers_stay_distinct():
    a = "Cello Suite No 1 in G major, BWV 1007"
    b = "Cello Suite No 6 in D major, BWV 1012"
    assert work_title_key(a) != work_title_key(b)


def test_no_catalogue_still_token_sorts():
    # Existing behaviour preserved: word-order churn collapses for free
    a = "Egmont Overture, Op 84"
    b = "Overture (Egmont, Op 84)"
    assert work_title_key(a) == work_title_key(b)


# --- work_title_key: vocal "container" catalogue numbers -----------------
# An opera / oratorio / song cycle carries ONE catalogue number across all
# its arias and songs. The catalogue rule must not collapse those excerpts.

def test_opera_aria_not_merged_with_overture():
    overture = "Overture to The Marriage of Figaro, K.492"
    aria = "Recit and aria 'Dove Sono' - from Act III of Le Nozze di Figaro, K.492"
    assert work_title_key(overture) != work_title_key(aria)


def test_song_cycle_members_stay_distinct():
    # Two different songs from Schwanengesang, D.957
    a = "Ständchen, from Schwanengesang, D.957"
    b = "Der Doppelgänger, from Schwanengesang, D.957"
    assert work_title_key(a) != work_title_key(b)


def test_opera_overtures_still_merge():
    # All overtures of one opera ARE the same work — translation-independent
    a = "Overture from Die Zauberflöte, K.620"
    b = "Overture to 'The Magic Flute', K620"
    assert work_title_key(a) == work_title_key(b)


# --- WORK_ALIASES --------------------------------------------------------

def test_oslo_hungarian_dances_one_group():
    # One Oslo PO / Aadland performance of Hungarian Dances 17-21, aired 14
    # times with the dances spelled out vs. given as a range, and with /
    # without the "orch. Dvorak" tag.
    variants = [
        "5 Hungarian Dances (originally for piano duet): Nos. 17 in F sharp "
        "minor; 18 in D major; 19 in B minor; 20 in E minor; 21 in E minor",
        "5 Hungarian Dances: Nos. 17 in F sharp minor; 18 in D major; "
        "19 in B minor; 20 in E minor; 21 in E minor",
        "5 Hungarian dances (nos.17-21) orch. Dvorak (orig. pf duet)",
        "5 Hungarian dances Nos 17-21 orch. Dvorak (orig. pf duet)",
        "5 Hungarian dances (nos.17-21) (orig. pf duet)",
        "5 Hungarian dances (nos 17-21) orch. Dvorak (orig. pf duet)",
    ]
    keys = {resolve_work_alias(work_title_key(v)) for v in variants}
    assert len(keys) == 1


def test_liszt_wallenstadt_one_group():
    # One Piemontesi recording of Liszt's "Au lac de Wallenstadt" (S.160
    # No.2), aired with the book as roman "I" vs. spelled "première année".
    a = "Au Lac de Wallenstadt from Années de pèlerinage I, S.160"
    b = ("Au lac de Wallenstadt, from 'Années de pèlerinage: première "
         "année: Suisse S.160'")
    assert resolve_work_alias(work_title_key(a)) == resolve_work_alias(
        work_title_key(b))


# --- WORK_ALIASES: Schubert one-off re-airings -----------------------------
# Pairs surfaced by the --once + exact-performer audit: one recording aired
# twice, the two airings titled differently. Each is a song/dance carrying a
# Deutsch number, so the catalogue rule's form-word gate (rightly) leaves
# them to the alias table.

def _same_group(a, b):
    return resolve_work_alias(work_title_key(a)) == resolve_work_alias(
        work_title_key(b))


def _same_composer(a, b):
    return resolve_composer_alias(canonical_key(a)) == resolve_composer_alias(
        canonical_key(b))


def test_schubert_roi_des_aulnes_one_group():
    assert _same_group("Le Roi des aulnes for violin solo Op 26",
                       "Le Roi des aulnes Op 26")


def test_schubert_nahe_des_geliebten_one_group():
    assert _same_group(
        "Nähe des Geliebten (D.162) (Op.5 No.2)",
        "Nahe des Geliebten, D.162 (Op 5 no 2) (The Proximity of the Loved One)")


def test_schubert_an_mignon_one_group():
    assert _same_group("An Mignon (D.161), Op.19 No.2 (To Mignon)",
                       "An Mignon from 3 Songs, D.161")


def test_schubert_erlkonig_violin_one_group():
    assert _same_group("Erlkönig, D. 328 arr. for violin",
                       "Erlkönig, D. 328 arr. for violin (encore)")


def test_schubert_erlkonig_organ_one_group():
    assert _same_group("Erlkönig, D328",
                       "Erlkönig, D.328, arr. Carpenter for organ")


def test_schubert_erlkonig_arrangements_fold_into_one_work():
    # The catalogue rule folds descriptive wording, "arr. for X" included,
    # so every arrangement of Erlkönig D.328 collapses into one work — the
    # same way the rule folds arrangements of a catalogued concerto.
    assert _same_group("Erlkönig, D. 328 arr. for violin",
                       "Erlkönig, D.328, arr. Carpenter for organ")


def test_schubert_deutsche_tanze_one_group():
    assert _same_group("6 Deutsche Tanze for piano (D.820)",
                       "6 Deutsche for piano (D.820) arr orch")


def test_schubert_widmung_one_group():
    assert _same_group("Widmung, transcribed for piano, S566",
                       "Widmung, transcribed for piano")


def test_schubert_sehnsucht_one_group():
    assert _same_group("Sehnsucht (D.636 Op.39)", "Sehnsucht, D.636")


def test_schubert_nine_songs_medley_one_group():
    # One Kielland / Norwegian RO medley, aired twice; the two airings differ
    # only in bracket placement and an added "(no. 3b)" locator.
    a = ("Nine songs with orchestra [Romanze from Rosamunde, D. 797; "
         "Die Forelle, D. 550 orch. Benjamin Britten; Gretchen am Spinnrade, "
         "D. 118 orch. Max Reger; Du bist die Ruh’, D. 776 orch. Anton Webern; "
         "An Silvia, D. 891 orch. Robert Schollum; Nacht und Träume, D. 827 "
         "orch. Max Reger; Im Abendrot, D. 799 orch. Max Reger; Erlkönig, "
         "D.328 orch. Max Reger; An die Musik, D.547 orch. Max Reger]")
    b = ("Nine songs with orchestra (Romanze (no. 3b), from Rosamunde, D. 797; "
         "Die Forelle, D. 550 orch. Benjamin Britten; Gretchen am Spinnrade, "
         "D. 118 orch. Max Reger); Du bist die Ruh’, D. 776 orch. Anton Webern; "
         "An Silvia, D. 891 orch. Robert Schollum; Nacht und Träume, D. 827 "
         "orch. Max Reger; Im Abendrot, D. 799 orch. Max Reger; Erlkönig, "
         "D.328 orch. Max Reger; An die Musik, D.547 orch. Max Reger.")
    assert _same_group(a, b)


# --- WORK_ALIASES: Pärt ----------------------------------------------------

def test_part_cantus_in_memoriam_one_group():
    # Pärt's Cantus, aired with the dedication as the Latin "in memoriam"
    # vs the English "in Memory of" — a cross-language phrasing the token
    # sort can't bridge.
    assert _same_group("Cantus in memoriam Benjamin Britten",
                       "Cantus in Memory of Benjamin Britten")


def test_part_magnificat_for_chorus_one_group():
    # "for chorus" is a scoring tag, not a different work
    assert _same_group("Magnificat", "Magnificat for chorus")


def test_part_alabaster_box_for_chorus_one_group():
    assert _same_group("The Woman with the Alabaster Box",
                       "The Woman with the Alabaster Box for chorus")


def test_part_bogoroditse_djevo_transliterations_one_group():
    # one work — Pärt's Богородице Дево — under four BBC transliterations
    # (devo / djevo / dyevo, with and without "Ráduisya" / "Ave Maria")
    variants = ["Bogoróditse Djevo", "Bogoroditse devo",
                "Bogoróditse Djevo (Ave Maria)",
                "Bogoróditse Dyévo Ráduisya"]
    keys = {resolve_work_alias(work_title_key(v)) for v in variants}
    assert len(keys) == 1


def test_part_passio_short_title_one_group():
    # "Passio" is the short name for the full-titled St John Passion
    assert _same_group(
        "Passio", "Passio Domini nostri Jesu Christi secundam Joannem")


def test_part_zwei_beter_one_group():
    # the parenthetical is an English gloss, not a separate work
    assert _same_group("Zwei Beter", "Zwei Beter (Two Prayers)")


# --- WORK_ALIASES: non-Bach one-off re-airings -----------------------------
# Recordings the BBC aired more than once under different titles, surfaced by
# the --once + exact-performer audit across Beethoven, Mozart, Handel, Brahms
# and Schumann. Each inner list is one recording; all its title variants must
# collapse to a single work-group. Strings are the analyzer's normalized
# titles, taken verbatim from the DB.
_REAIRING_GROUPS = [
    ['2 Mandolin Sonatinas: C minor WoO 43/1 and C major WoO 44/1', '2 Sonatinas WoO 43/1 and WoO 44/1'],
    ["8 Variations on Mozart's 'La ci darem la mano' (WoO 28) arranged for oboe and piano", "8 Variations on Mozart's 'La ci darem la mano' (WoO 28) arranged for oboe and piano 0"],
    ['Clarinet Trio in B flat major, Op 11', 'Trio in B flat major Op.11 for clarinet (or violin), cello and piano'],
    ['Duo for viola and cello in E flat major, WoO.32', 'Duo in E flat major for viola and cello, WoO 32'],
    ['Grosse Fuge, Op 133', 'Grosse Fuge, Op 133 (version for orchestra)'],
    ['Incidental music to "King Stephen"', 'Incidental music to König Stephan (King Stephen) (overture)'],
    ['Overture to The Creatures of Prometheus', 'Overture: The Creatures of Prometheus'],
    ["Piano Sonata 'quasi una fantasia' in E flat major Op.27'1", 'Piano Sonata (quasi una fantasia) in E flat major, Op.27 No.1', 'Sonata quasi una fantasia in E flat major, Op.27 No.1, for piano'],
    ['Piano Sonata quasi una fantasia in C sharp minor, Op 27 No 2, (Moonlight)', "Sonata quasi una fantasia in C sharp minor Op.27'2 (Moonlight)"],
    ['Quartet for strings (Op.18 No 6) in B flat major', 'Quartet for strings (Op.18`6) in B flat major'],
    ['Sonata in E flat major Op 12`3 for violin and piano', 'Violin Sonata in E flat major Op 12`3'],
    ['Trio for piano and strings in E flat major (Op.1 No.1)', 'Trio for piano and strings in E flat major Op 1 No 1 (4. Finale (Presto))'],
    ["Trio for strings (Op.9'1) in G major", 'Trio for strings in G major, Op.9 No.1'],
    ["Violin Sonata in C minor Op.30'2", 'Violin Sonata in C minor, Op.30 No.2'],
    ["'Ch'io mi scordi di te...?', K.505", "Ch'io mi scordi di te ...? Non temer, amato bene, K 505"],
    ['12 Variations for piano in B flat (K.500)', '12 Variations for piano, K.500'],
    ['4 Kontra Tänze, KV 267', 'Four Kontra Tänze, KV 267'],
    ["Aria 'Rivolgete a lui lo sguardo' (K.584)", 'Rivolgete a lui lo sguardo, K.584'],
    ['Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1', "Aria: Un'aura amorosa - from 'Così fan tutte', K588", "Un'aura amorosa (Così fan tutte)"],
    ['Ave verum corpus', 'Motet: Ave Verum Corpus (K.618)'],
    ['Der Schauspieldirektor - singspiel in 1 act (K.486)', 'Der Schauspieldirektor, K.486'],
    ['Eine kleine Nachtmusik (Serenade No.13 in G) (K.525)', 'Eine kleine Nachtmusik, K525'],
    ['Eine kleine Nachtmusik in G, K. 525', 'Eine kleine Nachtmusik in G, K.525'],
    ["Excerpts from 'The Abduction from the Seraglio, K. 384, Harmoniemusik'", "Excerpts from 'The Abduction from the Seraglio, K.384, Harmoniemusik'"],
    ['La Clemenza di Tito', 'La Clemenza di Tito (overture)', 'Overture to La Clemenza di Tito (K.621)'],
    ['Piano Sonata No. 6 in D - Tema con variazioni (var. 11)', 'Piano Sonata no 6 in D major - Tema con variazioni (var. 11)'],
    ['Ridente la calma (K.152) transcribed from "Il Caro mio bene"', 'Ridente la calma (K.152) transcribed from "Il Caro mio bene" by Myslivecek'],
    ['Serenata notturna in D, K. 239', 'Serenata notturna in D, K.239'],
    ['Two Flute Quartets: no 3 in C major K.285b & no 1 in D major, K.285', 'Two Flute Quartets: no 3 in C major K.Anh.171 (K.285b) & no 1 in D major (K.285)'],
    ['"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\'', '"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\' (Act II Scene 8)', "Al lampo dell'armi' (from Act II of Giulio Cesare in Egitto)"],
    ["'The Arrival of the Queen of Sheba' - from 'Solomon', HWV 67", 'The Arrival of the Queen of Sheba (Solomon, HWV 67)'],
    ["'Tu, del ciel ministro eletto' (Bellezza's aria) from 'Il Trionfo del Tempo e del Disinganno', HWV.46a", "Tu, del ciel ministro eletto (Bellezza's aria) 'Il Trionfo del Tempo e del Disinganno', HWV 46a"],
    ["Aria: 'Die ihr aus dunkeln Grüften den eiteln Mammon grabt' (HWV.208)", 'Die ihr aus dunkeln Grüften den eiteln Mammon grabt (HWV.208) - No.7 from German Arias'],
    ['Concerto Grosso in D, HWV 323', 'Concerto Grosso in Dmajor, HWV 323'],
    ["Già che morir non posso - from 'Radamisto'", "Già che morir non posso'"],
    ['Il Pianto di Maria, cantata, HWV.234', 'Il pianto di Maria, cantata, HWV 234'],
    ["Lascia la spina cogli la rose, from 'Il Trionfo del Tempo e del disinganno'", 'Lascia la spina cogli la rose, from Il Trionfo del Tempo e del disinganno, HWV.46a', "Lascia la spina, cogli la rosa, from 'Il Trionfo del Tempo e del Disinganno'"],
    ['Oboe Sonata in F major Op 1 No 5', 'Sonata in F major Op 1 No 5'],
    ['Utrecht Te Deum in D major, HWV 278', 'Utrecht Te Deum in D, HWV 278'],
    ['3 Hungarian Dances (originally for piano duet) arr. for string orchestra: No.1 in G minor; No.3 in F major; No.5 in F sharp minor', '3 Hungarian Dances arr. for string orchestra: No 1 in G minor; No 3 in F major; No 5 in F sharp minor'],
    ['Hungarian Dance No.1 in G minor (originally for piano duet)', 'Hungarian Dance No.1 in G minor (originally for piano duet, orchestrated by the composer)'],
    ['Intermezzo in A minor, Op 116, No 2', 'Intermezzo in A minor,Op 116, No 2'],
    ['Piano Quintet in F minor', 'Quintet in F minor Op 34'],
    ["Three Songs: 'Meine Liebe ist grun' (Op.63 No.5) etc", "Three Songs: 'Meine Liebe ist grun' Op 63 No 5"],
    ['Die Braut von Messina, Op 100', 'Die Braut von Messina, Op 100 (Overture)'],
    ['Introduction and Allegro appassionato in G major Op 92', 'Introduction and Allegro appassionato in G major Op 92 for piano and orchestra'],
]


@pytest.mark.parametrize("variants", _REAIRING_GROUPS,
                         ids=[g[0][:45] for g in _REAIRING_GROUPS])
def test_reairing_variants_collapse_to_one_group(variants):
    keys = {resolve_work_alias(work_title_key(v)) for v in variants}
    assert len(keys) == 1


# --- WORK_ALIASES: 2026-05-20 multi-play harvest ---------------------------
# High-airing spelling-only merges surfaced by ttn_rebroadcast --multiplay.
# Each inner list is one work; all its title variants (the dominant spelling
# plus the work_title_keys the token sort left distinct) must collapse to a
# single group. Arrangement and excerpt labellings were excluded from the
# harvest; the safety tests below assert those stay distinct.
_MULTIPLAY_HARVEST_GROUPS = [
    ["Serenade for Strings in E minor, Op 20",
     "Serenade for Strings Op 20",
     "Serenade for string orchestra in E minor, Op 20",
     "Serenade in E minor for string orchestra"],
    ["Fantasia on a theme by Thomas Tallis",
     "Fantasia on a theme by Thomas Tallis for double string orchestra",
     "Fantasia on a theme of Thomas Tallis for double string orchestra",
     "Fantasia on a theme of Thomas Tallis"],
    ["24 Preludes, Op 28",
     "24 Preludes Op.28 for piano"],
    ["Ballade No 1 in G minor, Op 23",
     "Ballade for piano no. 1 (Op.23) in G minor",
     "Ballade No.1 (Op.23)"],
    ["Clarinet Quintet in B flat major, Op 34",
     "Quintet in B flat major Op.34 for clarinet and strings (J.182)",
     "Quintet in B flat major for clarinet and strings, Op 34",
     "Quintet for Clarinet and Strings in B flat J.182 Op 34",
     "Clarinet Quintet in B flat, op. 34",
     "Clarinet Quintet (Op.34) in B flat major (J.182) (1815)"],
    ["Nocturne No 1 in E flat minor, Op 33 No 1",
     "Nocturne for piano in E flat minor, Op 33 no 1",
     "Nocturne in E flat minor Op 33 No 1",
     "Nocturne for piano no.1 (Op.33 No.1) in E flat minor"],
    ["String Quartet in G minor, Op 10",
     "Quartet for strings in G minor , Op 10",
     "String Quartet in G minor"],
    ["Finlandia, Op 26",
     "Finlandia Op.26 for orchestra"],
    ["Holberg Suite, Op 40",
     "Holberg suite Op 40 vers. for string orchestra",
     "Holberg Suite Op 40 for string orchestra"],
    ["Norwegian Dance (Allegro marcato) (Op.35 No.1)",
     "Norwegian Dance No 1 Op 35 for piano duet",
     "Norwegian Dance, Op 35 No 1",
     "Norwegian Dance (Allegro marcato), Op.35'1",
     "Norwegian Dance No.1 for piano duet"],
    ["Cello Sonata in D minor",
     "Sonata for cello and piano in D minor"],
    ["Piano Trio in A minor",
     "Trio for piano and strings in A minor",
     "Piano Trio in A minor (1914)"],
]


@pytest.mark.parametrize("variants", _MULTIPLAY_HARVEST_GROUPS,
                         ids=[g[0][:45] for g in _MULTIPLAY_HARVEST_GROUPS])
def test_multiplay_harvest_variants_collapse_to_one_group(variants):
    keys = {resolve_work_alias(work_title_key(v)) for v in variants}
    assert len(keys) == 1


def test_chopin_preludes_whole_set_vs_excerpt_stay_distinct():
    # The full Op 28 set must NOT fold into a "nos 11-15" excerpt — the
    # harvest folded only whole-set spellings.
    assert not _same_group("24 Preludes, Op 28",
                           "From 24 Preludes, Op 28: nos 11-15")


def test_chopin_ballade_1_and_2_stay_distinct():
    assert not _same_group("Ballade No 1 in G minor, Op 23",
                           "Ballade no 2 in F major, Op 38")


def test_faure_nocturne_1_and_6_stay_distinct():
    assert not _same_group("Nocturne No 1 in E flat minor, Op 33 No 1",
                           "Nocturne for piano no 6 in D flat major, Op 63")


def test_grieg_norwegian_dance_1_and_2_stay_distinct():
    assert not _same_group("Norwegian Dance (Allegro marcato) (Op.35 No.1)",
                           "Norwegian Dance No 2 in A major, Op 35")


# --- safety: distinct works the audit flagged but must NOT merge -----------

def test_beethoven_distinct_violin_sonatas_stay_distinct():
    # No.4 in A minor (Op.23) and No.6 in A major (Op.30/1) are different
    # sonatas — shared performers don't make them one work.
    assert not _same_group(
        "Sonata for Piano and Violin No.4 in A minor (Op.23)",
        "Sonata for Violin and Piano No.6 in A major (Op.30 No.1)")


def test_brahms_hungarian_dances_1_and_5_stay_distinct():
    assert not _same_group("Hungarian Dance no 1 in G minor",
                           "Hungarian Dance no 5 in G minor")


def test_handel_messiah_parts_stay_distinct():
    assert not _same_group("Messiah, HWV 56 - Part 2",
                           "Messiah, HWV 56 - Part 3")


def test_mozart_song_bundle_not_merged_with_standalone_song():
    # A 4-song recital set is not the same work as one of its songs played
    # alone by a different singer.
    bundle = ("4 Songs: Oiseaux, si tous les ans, K.307; Dans un bois "
              "solitaire, K.308; Als Luise die Briefe, K.520; Ridente la "
              "calma, K.152")
    assert not _same_group(
        bundle, 'Ridente la calma (K.152) transcribed from "Il Caro mio bene"')


# --- work_title_key: catalogue rule for whole vocal works ------------------
# A cantata / Passion / Mass / motet is one work with one catalogue number.
# When a vocal title names the WHOLE work (no excerpt locator) and its
# number is not a cycle container, the catalogue rule applies just as it
# does for instrumental forms — so catalogue-format churn collapses.

def test_vocal_whole_work_catalogue_separator_merges():
    assert (work_title_key("St John Passion, BWV.245")
            == work_title_key("St John Passion, BWV 245"))


def test_vocal_whole_work_word_order_collapses():
    # Same cantata, the BWV number and the incipit in either order.
    assert (work_title_key("Cantata - 'Ich hatte viel Bekummernis' BWV 21")
            == work_title_key("Cantata BWV 21, 'Ich hatte viel Bekummernis'"))


def test_vocal_whole_work_mass_merges():
    assert (work_title_key("Mass in G major, BWV.236")
            == work_title_key("Mass in G, BWV 236"))


def test_vocal_catalogue_nums_deduplicated():
    # "Cantata No. 51, BWV.51" repeats the number 51 — it must not key
    # differently from "... (BWV.51)".
    assert (work_title_key("Cantata No. 51, BWV.51 (Jauchzet Gott in allen Landen)")
            == work_title_key("Jauchzet Gott in allen Landen (BWV.51)"))


def test_vocal_excerpt_not_merged_with_whole_work():
    # An aria carrying its parent's catalogue number must not fuse with the
    # whole work — the excerpt locator keeps the rule off.
    whole = "Cantata BWV.43, Gott fahret auf mit Jauchzen"
    aria = "Aria 'Halleluja' from Cantata BWV.43"
    assert work_title_key(whole) != work_title_key(aria)


def test_song_cycle_catalogue_number_not_collapsed():
    # D.957 is the number of the whole Schwanengesang cycle. A song listed
    # bare as "Ständchen, D.957" must NOT fuse into the cycle — the cycle
    # denylist keeps the rule off.
    assert work_title_key("Ständchen, D.957") != work_title_key(
        "Schwanengesang, D.957")


# --- WORK_ALIASES: Bach one-off re-airings ---------------------------------
# Bach re-airings the systematic vocal rule structurally can't reach: one
# airing gives "No.N" with no BWV at all, or excerpt locators send both
# sides to the token sort. Hand-curated from the --once + performer audit.
_BACH_REAIRING_GROUPS = [
    ["'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria) - from Cantata No. 81, 'Jesus schlaft, was soll ich hoffen'", "'Herr! Warum trittest du'(recitative) and 'Die schaumenden Welle' (aria) from Cantata BWV 81, 'Jesus schlaft, was soll ich hoffen'", "Cantata no. 81 BWV.81 'Jesus schlaft, was soll ich hoffen': 'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria)"],
    ["Aria 'Ich traue seiner Gnaden' from Cantata no. 97 (BWV.97) 'In allen meinen Taten'", 'Ich traue seiner Gnaden (from Cantata BWV.97)'],
    ['Cantata BWV.11, Lobet Gott in seinen Reichen (Ascension oratorio)', 'Cantata No.11 (Lobet Gott in seinen Reichen) (Ascension Oratorio)'],
    ["Cantata BWV.134: 'Wir danken und preisen' (duet)", "Duet from Cantata BWV 134, 'Wir danken und preisen'"],
    ['Cantata BWV.43, Gott fahret auf mit Jauchzen', 'Cantata No.43 (Gott fahret auf mit Jauchzen)'],
    ['Excerpts from The Well-Tempered Clavier, Vol. 2, BWV 874-881', 'The Well-Tempered Clavier - Book 2, BWV 874-881'],
    ["Fuga ricercata No 2 a 6 voci from Bach's 'Musikalischen Opfer' BWV.1079", "Fuga ricercata No.2 from Bach's 'Musikalischen Opfer' (BWV.1079)"],
    ['Gavotte en rondeau (Partita No. 3 in E major for solo violin)', 'Gavotte en rondeau, from Partita no 3 in E major'],
    ['Minuet 1 and 2 in F major; Fantasia in D minor', 'Minuet 1 and 2 in F; Fantasia in d'],
    ['Prelude, from Partita no 3 in E', 'Prelude, from Partita no 3 in E major'],
    ['Sonata No 1 in C major & Sonata No 2 in F major for two violins, two violas and continuo', 'Sonata a 5 No.1 in C major & No.2 in F major, for two violins, two violas and continuo'],
    ['Wer ist so würdig als du (Wq.222) (Hamburg 1774)', 'Wer ist so würdig als du, Wq.222'],
]


@pytest.mark.parametrize("variants", _BACH_REAIRING_GROUPS,
                         ids=[g[0][:45] for g in _BACH_REAIRING_GROUPS])
def test_bach_reairing_variants_collapse_to_one_group(variants):
    keys = {resolve_work_alias(work_title_key(v)) for v in variants}
    assert len(keys) == 1


# --- WORK_ALIASES: source data errors --------------------------------------
# Pairs where one airing carries a factual mistake (wrong opus or key). The
# performance is the same; the alias folds the mistaken title into the
# correct work. The raw title is, as always, left untouched in the DB.

def test_bwv582_key_mislabels_fold_to_one_work():
    # BWV 582 is the Passacaglia and Fugue in C minor. One airing drops the
    # mode ("in C"), another mislabels it "in D minor".
    correct = "Passacaglia and Fugue in C minor, BWV 582"
    assert _same_group("Passacaglia and Fugue in C, BWV 582", correct)
    assert _same_group("Passacaglia and Fugue in D minor, BWV 582", correct)


def test_beethoven_quartet_op1_typo_folds_to_op18():
    # Beethoven's Op.1 are piano trios; "Quartet ... Op.1 No.1" is a BBC
    # typo for the Op.18 No.1 string quartet.
    assert _same_group(
        "Quartet in F major Op.1 No.1 arr. for string orchestra",
        "Quartet in F major Op.18 No. 1 arr. for string orchestra")


def test_schumann_quintet_key_typo_folds_to_e_flat():
    # The Piano Quintet Op.44 is in E flat major; "E minor" is a BBC error.
    assert _same_group("Scherzo from Piano Quintet in E minor, Op.44",
                       "Scherzo from Piano Quintet in E flat major, Op.44")


# --- ENSEMBLE_ALIASES ------------------------------------------------------

def test_saarbruecken_orchestra_german_english_names_merge():
    # One orchestra credited under its German and English names.
    assert (resolve_ensemble_alias(
                canonical_key("Rundfunk-Sinfonieorchester Saarbrücken"))
            == resolve_ensemble_alias(
                canonical_key("Saarbrücken Radio Symphony Orchestra")))


def test_saarbruecken_kaiserslautern_city_tail_not_split_off():
    # "<orchestra>, Saarbrücken Kaiserslautern" — the comma must not orphan
    # the two-word city tail as a phantom ensemble.
    ensembles, conductors = parse_performers(
        "German Radio Philharmonic Orchestra, Saarbrücken Kaiserslautern, "
        "Pietari Inkinen (conductor)")
    assert ensembles == [
        "German Radio Philharmonic Orchestra, Saarbrücken Kaiserslautern"]
    assert conductors == ["Pietari Inkinen"]


def test_parse_performers_tolerates_trailing_period_after_role():
    # the BBC sometimes writes a "." after "(conductor)" — at the end of the
    # line (handled by the rstrip) or mid-string. Either way the conductor
    # must be recognised, not dropped into the ensembles bucket.
    ensembles, conductors = parse_performers(
        "Risör Festival Strings, Andrew Manze (conductor)., Ole Antonsen")
    assert conductors == ["Andrew Manze"]
    assert ensembles == ["Risör Festival Strings", "Ole Antonsen"]


def test_deutsche_radio_philharmonie_renderings_merge():
    # One orchestra (the post-2007 DRP) under its German/English renderings.
    variants = [
        "Deutsche Radio Philharmonie Saarbrücken Kaiserslautern",
        "German Radio Philharmonic Orchestra, Saarbrücken Kaiserslautern",
        "German Radio Saarbrücken-Kaiserslautern Philharmonic Orchestra",
        "Deutsche Radio Philharmonie",
        "German Radio Philharmonic Orchestra",
        "German Radio Philharmonic",
    ]
    keys = {resolve_ensemble_alias(canonical_key(v)) for v in variants}
    assert len(keys) == 1


def test_erik_westberg_vocal_ensemble_genitive_artifact_merges():
    # "Erik Westbergs Vocal Ensemble" carries a stray Swedish genitive -s
    # from "Erik Westbergs Vokalensemble"; merge it with the English form.
    variants = ["Erik Westberg Vocal Ensemble",
                "Erik Westbergs Vocal Ensemble"]
    keys = {resolve_ensemble_alias(canonical_key(v)) for v in variants}
    assert len(keys) == 1


def test_deutsche_radio_philharmonie_distinct_from_rso_saarbruecken():
    # The post-2007 DRP is a different institution from its pre-merger
    # predecessor — they must not collapse together.
    assert (resolve_ensemble_alias(canonical_key(
                "Deutsche Radio Philharmonie Saarbrücken Kaiserslautern"))
            != resolve_ensemble_alias(canonical_key(
                "Saarbrücken Radio Symphony Orchestra")))


# --- COMPOSER_ALIASES ------------------------------------------------------

def test_mendelssohn_bartholdy_double_barreled_surname_merges():
    # The BBC credits Felix Mendelssohn under his full surname
    # Mendelssohn-Bartholdy on a handful of episodes; same composer.
    variants = [
        "Felix Mendelssohn",
        "Felix Mendelssohn-Bartholdy",
        "Felix Mendelssohn Bartholdy",
    ]
    keys = {resolve_composer_alias(canonical_key(v)) for v in variants}
    assert len(keys) == 1


def test_handel_german_and_english_renderings_merge():
    # Handel is credited five ways across the archive — English "George
    # Frideric", a "Georg Frideric" hybrid, and the German "Georg Friedrich"
    # (with umlauted Händel or not). All must collapse to one composer key.
    variants = [
        "George Frideric Handel",
        "Georg Frideric Handel",
        "Georg Friedrich Händel",
        "Georg Friedrich Handel",
        "George Friedrich Handel",
    ]
    keys = {resolve_composer_alias(canonical_key(v)) for v in variants}
    assert len(keys) == 1


# --- WORK_ALIASES: --once re-airings, audit batch 2 ------------------------
# Vivaldi, Haydn, Dvořák, Tchaikovsky, Chopin, Mendelssohn, Grieg, Telemann.
_AUDIT_REAIRING_GROUPS = [
    ['Allegro non molto from Oboe Concerto in A minor', 'Allegro non molto from Oboe Concerto in A minor, RV.461'],
    ['Violin Concerto in C major, Op 8 No 12 (RV 178)', 'Violin Concerto in C major, RV.178'],
    ["2nd movement (Largo assai) - from String Quartet in G minor, Op 74 No 3 'Rider'", "String Quartet in G minor, Op 74, No 3 'Rider' - 2nd movt"],
    ['Ave Regina for double choir', 'Ave Regina for double choir, MH 140'],
    ['Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and bc', 'Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and continuo'],
    ["Divertimento in C major, Hob.IV No 1 'London Trio'", 'Divertimento in C major, London Trio no 1, Hob.4:1'],
    ['Keyboard Sonata in B flat major, H.16.41', 'Sonata in B flat major, H.16.41'],
    ['Overture to Lo Speziale', 'Overture to Lo Speziale (The Apothecary)'],
    ['Piano Sonata for piano in F major, Hob 16.29', 'Sonata for piano (H.16.29) in F major'],
    ['Symphony No 4 (H.1.4) in D major (Presto', 'Symphony No.4 in D major'],
    ['Symphony No.88 (H.1.88)', 'Symphony No.88 in G (H.1.88)'],
    ["Variations on the hymn 'Gott erhalte Franz den Kaiser'", "Variations on the hymn 'Gott erhalte'"],
    ['Slavonic Dance in G minor, Op 46 No 8, orch composer (orig for pf duet)', 'Slavonic dance No 8 in G minor Op 46 No 8 orch. composer (orig. for pf duet)'],
    ['Symphony No. 8 in G major, Op. 88, B. 163', 'Symphony no 8 in G major, Op 88, B.163'],
    ['Three Slavonic Dances (No 8 in G minor, Op 46 No 8; No 10 in E minor, Op 72 No 2; No 15 in C major, Op 72 No 7)', 'Three Slavonic Dances: Slavonic Dance No.8 in G minor, Op.46 no.8; Slavonic Dance No.10 in E minor, Op.72 no.2; Slavonic Dance No.15 in C major, Op.72 no.7'],
    ['Two Waltzes, Op 54', 'Two Waltzes, Op 54 [1.Moderato; 2.Allegro vivace]'],
    ["1. Cherubim's Song, No. 3 from 'Nine Sacred Pieces'", "Cherubim's Song, No. 3 from 'Nine Sacred Pieces' (encore)"],
    ['Andante Cantabile (String Quartet, Op11), arranged by the composer', 'Andante Cantabile from the string quartet (Op.11)'],
    ['Cradle Song (Andantino) from Six Romances, Op.16', "Cradle Song (Andantino) from Six Romances, Op.16'1"],
    ['Introduction and Waltz (Eugene Onegin)', "Introduction and Waltz from 'Eugene Onegin'"],
    ["Jurists' March in D", "Jurists' March in D major"],
    ["March in B flat minor, Op.31, 'Marche slave'", "Slavonic March in B flat minor 'Marche slave' (Op.31)"],
    ['Nocturne in C sharp minor, Op 19 no 4', 'Nocturne in C sharp minor, Op 19 no 4 (encore)'],
    ["Souvenir de Florence (4th mvt, 'Allegro vivace') Op 70", 'Souvenir de Florence, Op.70 (Allegro vivace)'],
    ["Symphony No 6 in B minor, Op 74, 'Pathétique' (3rd movt)", 'Symphony No. 6 in B minor Op.74 (Pathétique) - 3rd mov arr. Carpenter for organ'],
    ['Symphony No.1 in G minor', "Symphony No.1 in G minor (Op.13) 'Reves d'hiver'"],
    ['2 Nocturnes for piano (Op.48) no.1 in C minor', '2 Nocturnes for piano (Op.48)no.1 in C minor'],
    ['24 Preludes Op.28: No.11 in B major; No.12 in G sharp minor; No.13 in F sharp major; No.14 in E flat minor; No.15 in D flat major', 'Preludes No.11 in B major; No.12 in G sharp minor; No.13 in F sharp major; No.14 in E flat minor; No.15 in D flat major - from 24 Preludes (Op.28)'],
    ['Etude in C sharp minor, Op 10 no 4', 'Etude in C sharp minor, op. 10/4'],
    ['Finale. Presto ma non tanto agitato, (Excerpt Sonata No 3 in B flat, Op 58)', 'Finale. Presto ma non tanto agitato, (Excerpt Sonata No 3 in B minor, Op 58)'],
    ['From 24 Preludes, Op 28: nos 11-15', 'From Preludes, Op 28: nos 11-15'],
    ['Impromptu in A flat major, Op.29', 'Impromptu in Ab major, Op 29'],
    ['Nocturne No 20 C sharp minor Op posth. B49', 'Nocturne No 20 in C sharp minor Op posth. B49'],
    ["Nocturne in C sharp minor Op.27'1, arr. for violin and piano", 'Nocturne in C sharp minor, Op.27 No.1, arr. for violin and piano'],
    ['Nocturne in D Flat major, from 2 Nocturnes Op 27', 'Nocturne in D flat major, Op.27'],
    ['Prelude No 1 in C major, Op 28 No 1', 'Prelude No 1 in C, Op 28 No 1'],
    ["Three Polonaises: Polonaise in A major, Op 40'1; Polonaise in E flat minor, Op 26'2; Polonaise in F sharp minor, Op 44", 'Three Polonaises: Polonaise in A major, Op.40 No.1, Polonaise in E flat minor, Op.26 No.2; Polonaise in F sharp minor, Op.44'],
    ['Waltz No 42 in A flat, Op 42', 'Waltz No. 42 in A flat, оp. 42'],
    ['Waltz No. 7 in C sharp minor, op. 64/2', "Waltz No. 7 in C sharp minor, op.64'2"],
    ['6 Lieder for mixed voices Op.59', '6 Lieder, Op 59'],
    ["Allegro vivace, 1st movement from 'Symphony No. 4 in A, op. 90 (Italian)'", "Allegro vivace, from 'Symphony No. 4 in A, op. 90 (Italian)'"],
    ['Elias (Elijah), Op.70 - oratorio (Carus version): Part I', 'Elias (Elijah), Op.70 - oratorio: Part I'],
    ['Elias (Elijah), Op.70 - oratorio (Carus version): Part II', 'Elias (Elijah), Op.70 - oratorio: Part II'],
    ['Piano Trio in C minor', 'Piano Trio in C minor, MWV Q3', 'Piano Trio in C minor, MWV.Q3'],
    ["Spinning Song, Op 67 no 4, from 'Songs without Words'", "Spinning Song, op. 67/4, from 'Songs without Words'"],
    ['String Symphony No 9 in C minor', 'Symphony for String Orchestra No 9 in C minor'],
    ["Wedding March & Elfin Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase", "Wedding March & Elfins Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase"],
    ["3 Pieces from Norwegian Peasant Dances, Op 72: The Goblins' Wedding Procession at Vossevangen; Wedding march after the Miller's boy; Jon Vestafe's springar", "3 Pieces from Slatter (Norwegian Peasant Dances), Op 72: Forspel/Tussebrurefedera pa Vossevangen (The Goblins' Wedding Procession at Vossevangen); Bruremarsj etter Myllarguten (Wedding march after the Miller's boy); Jon Vestafes springar (Jon Vestafe's springar)"],
    ['3 Pieces from Norwegian Peasant Dances, Op.72', '3 Pieces from Slåtter (3 Pieces from Norwegian Peasant Dances) (Op.72)'],
    ["5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) (Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) (Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)", "Lyric Pieces (Lyriske stykker): Aften på højfjellet (Evening in the mountains) Op.68 No.4; For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) Op.71 No.2; Forbi (Gone) Op.71 No.6; Etterklang (Remembrances) Op.71 No.7", "Selected Lyric Pieces: Evening in the mountains (Op.68 No.4); At your feet (Op.68 No.3); Summer's evening (Op.71 No.2); Gone (Op.71 No.6); Remembrances (Op.71 No.7)"],
    ['Fra ungdomsdagene (From Early Years) from Lyric Pieces, Book 8 for piano, Op.65', 'Fra ungdomsdagene (From early years) from Lyric pieces, book 8 for piano (Op.65 No.1)'],
    ['Gammelnorsk Romance met Variasjoner (Old Norwegian Romance with Variations) - orig. for 2 pianos arr for orchestra (Op.51) (1890)', 'Old Norwegian Romance with Variations - orig. for 2 pianos arr. for orchestra (Op.51) (1890)'],
    ["Hvad est du dog skiøn (How fair thou art) , from 'Four Salmer (Hymns), Op 74/1", 'Hvad est du dog skiøn (How fair thou art), No.1 of Four Pslams, Op 74'],
    ["Morning Mood, from 'Peer Gynt, Suite No.1, Op.46' - arranged for piano four hands", 'Morning Mood, from Peer Gynt Suite No.1', 'Morning Mood, from Peer Gynt, Suite No.1, Op.46'],
    ["Shepherd’s boy, from 'Lyric Suite, op. 54 no. 1'", "Shepherd’s boy, from 'Lyric Suite, op. 54/1'"],
    ['3 arias: Harte Fessel, strenge Ketten (Die syrische Unruh); Der Himmel will, ich soll ein Ziel (Mario, TWV 21:6); Ach was für Qual und Schmerz (Der unglückliche Alcmeon)', "Harte Fessel, strenge Ketten, from 'Die syrische Unruh'; Der Himmel will, from 'Mario, TWV 21:6; Ach was für Qual und Schmerz, from 'Der unglückliche Alcmeon'"],
    ['Affettuoso & Wandelt in der Liebe, gleich wie Christus uns geliebt! (aria)', 'Duet (Affetuoso) TWV 40:107 & Wandelt in der Liebe, gleich wie Christus uns geliebt! (aria)'],
    ['Concerto in F minor for 3 violins (Musique de table)', 'Concerto in F minor for 3 violins and orchestra from Musique de table, partagée en trois productions', 'Concerto in F minor for 3 violins and orchestra, from Musique de table'],
    ["Quartet No 12 in E minor, TWV 43:e4 'Paris Quartet'", "Quartet in E minor, TWV.43:e4 'Paris Quartet' for flute, violin, bass viol and continuo"],
    ['Sonata à 4 in F major, for alto and tenor chalumeaux, two violins and basso continuo', 'Sonata à 4 in F, for alto and tenor chalumeaux, two violins and basso continuo'],
    ['Heidenroslein; Das Wandern', 'Heidenröslein; Heidenröslein; Das Wanderern; Das Wandern'],
    ['Adagio & Allegro in E flat major (K.Anh.C 17.07) for wind octet', 'Adagio / Allegro in E flat major (K.Anh.C 17.07) for wind octet'],
    ["4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)", "4 Songs: Svarta rosor [Black Roses] (Op.36 No.1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36 No.4); Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37 No.5); Varen flyktar hastigt [Spring is flying] (Op.13 No.4)", "4 Songs: Svarta rosor [Black Roses] (Op.36 No.1); Säv, sav, susa [Sigh Sedges sigh] (Op.36 No.4); Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37 No.5); Varen flyktar hastigt [Spring is flying] (Op.13 No.4)", "Svarta rosor (Black Rose), Op 36 No 1; Säv, sav, susa (Sigh Sedges sigh), Op 36 No 4; Klickan kom ifran sin äls klings möte (The Maiden's Tryst), Op 37 No 5; Varen flyktar hastigt (Spring is Flying), Op 13 No 4", "Svarta rosor (Black Roses) (Op.36 No.1); Säv, sav, susa (Sigh Sedges sigh) (Op.36 No.4); Klickan kom ifran sin äls klings möte (The Maiden's tryst) (Op.37 No.5); Varen flyktar hastigt (Spring is flying) (Op.13 No.4)"],
    ["Excerpts from 'Six Pieces for violin and piano, op. 79'", 'Souvenir, Tanz-Idylle and Berceuse from Six Pieces for violin and piano, op. 79'],
    ['Romance in D flat major Op. 24, No. 9 (encore)', 'Romance in D flat major Op. 24, No. 9 (encore) (10 Pieces Op.24 for piano, No. 9)'],
    ['Valse triste Op 44 no 1', 'Valso triste op 44, No 1'],
    ['Abschied, Russisches Volkslied [1885]', 'Abschied, russisches Volkslied (1885)'],
    ['Auf Flügeln des Gesanges - from No 1 of 7 Songs by Mendelssohn (S547) transc. for piano', 'Auf flügeln des Gesanges - from (Mendelssohn) No.1 of Songs (S.547) transc. for piano'],
    ['Ave Maria (1846)', 'Ave Maria, S.20'],
    ['Christus - Pastorale and Herald Angels Sing', 'Christus - Pastorale and Herald Angels Sing (extract)', 'Christus - Pastorale; Herald Angels Sing'],
    ['Concert Study No. 2, "Gnomenreigen", S. 145', 'Concert Study no. 2."Gnomenreigen" (S. 145)'],
    ["Funerailles - No.7 from 'Harmonies poétiques et religieuses, S.173 - 10 pieces for piano'", "Funerailles - No.7 from 'Harmonies poétiques et religieuses, S.173'"],
    ['Hungarian Coronation Mass', 'Hungarian Coronation Mass, S 11)', 'Hungarian Coronation Mass, S.11)'],
    ['Les Préludes - symphonic poem after Lamartine', 'Préludes - symphonic poem after Lamartine (S.97)'],
    ['Liebestod, from Tristan und Isolde, S. 447', 'Liebestod, from Tristan und Isolde, S. 447 (encore)'],
    ['Nuages gris, S.199', 'Nuages gris, S.199 for piano'],
    ['Rhapsody No. 5 in E minor, S.244 No 5', 'Rhapsody No. 5 in E minor, S.244/5'],
    ['St François de Paule marchant sur les flots - from 2 Légendes (S.175 No.2)', 'St François de Paule marchant sur les flots - from 2 Légends (S.175 No.2)'],
    ["'Dica il falso, dica il vero' from Alessandro", 'Dica il falso, dica il vero -- from Alessandro Act 2 Scene 8'],
    ['Concerto for harp and orchestra in B flat major (Op.4 No.6)', 'Harp Concerto in B flat major, Op 4, No 6'],
    # one Handel aria, one recording, aired 5x under 3 work-keys — a miss
    # ttn_audit can't reach (3-play form is not a one-off; the 1-play forms
    # score 0.4 Jaccard), folded here by hand
    ["Alessandro (excerpt 'Solitudini amate')", '"Solitudini amate" (Alessandro)', '"Solitudini amate" (Beloved solitude)'],
    # likewise — 6 airings, 3 work-keys; the "HWV 20" form is a typo for 202
    ["Kunft'ger Zeiten eitler Kummer (HWV.202) - no.1 from Deutsche Arien", 'Künft\'ger Zeiten eitler Kummer, HWV 20 - No 1 from Deutsche Arien (originally for soprano, violin & bc, arranged for oboe, violin and organ)', "Künft'ger Zeiten eitler Kummer (HWV.202) (arr. for oboe, violin and organ)"],
    ['Arrival of the Guests (Minuet) from Romeo and Juliet', 'Arrival of the Guests (Romeo and Juliet)'],
    ['Dance of the Knights from the ballet suite Romeo and Juliet arr. Borisovsky', 'Dance of the Knights from the ballet suite Romeo and Juliet arr. Borisovsky for viola and piano', 'Dance of the Knights from the ballet suite Romeo and Juliet arr. for viola and piano'],
    ['God of Evil and Pagan Dance (Allegro sostenuto) - No.2 from Scythian Suite', 'God of evil and pagan dance (Allegro sostenuto) - no.2 from Scythian suite from "Ala i Lolly", Op.20'],
    ["Moderato, from 'Sonata Solo Violin in D, op. 115'", 'Moderato, from Sonata for Solo Violin in D, op. 115'],
    ['Piano Sonata no.5 in C major, Op.135 (version revised)', 'Sonata no.5 in C major, Op 135', 'Sonata no.5 in C major, Op.135 (vers. revised)'],
    ['Prelude - No.7 from Pieces for piano (Op.12)', 'Prelude Op.12 No.7'],
    ['2 Madrigals by Monteverdi and a Sonata a 3 by Dario Castello', '2 Madrigals by Monteverdi and a Sonate a 3 by Dario Castello'],
    ["Lamento d'Arianna, a 5 (SV 107)", "Lamento d'Arianna, a 5 SV.107"],
    ['"Caro nome" Gilda\'s aria from Rigoletto', 'Caro nome (Rigoletto)'],
    ["'Quando le sere al placido' (Rodolfo's aria) from Luisa Miller", "Quando le sere al placido (Rodolfo's aria from act 2 of 'Luisa Miller')"],
    ['Anvil Chorus (Il Trovatore)', 'Anvil Chorus (Il Troviatore)'],
    ['Danza sacra e Duetto finale - Aida S.436', "Danza sacra e duetto finale d'Aida, S436"],
    ['Lina pensai che un angelo (Stiffelio, Act III)', 'Lina, pensai che un angelo (Stiffelio)'],
    ['Son io mio Carlo (Don Carlo)', 'Son io mio Carlo (Don Carlos Act III)'],
    ["Cloches à travers les feuilles; Et la lune déscend sur la temple qui fut; Poissons d'or (Images Bk 2)", "Images II (Cloches à travers les feuilles; Et la lune déscend sur la temple qui fut; Poissons d'or)"],
    # only the two 5-prelude airings — the 3-prelude airing is a different
    # selection and is recorded as a rejection in ttn_audit_decisions.json
    ['Danseuses de Delphes, La cathédrale engloutie, La danse de Puck, Le vent dans la plaine, Minstrels - from Preludes (Book 1)', 'Danseuses de Delphes, La cathÃ©drale engloutie, La danse de Puck, Le vent dans la plaine, Minstrels - from Preludes (Book 1)'],
    ['Des pas sur la neige (Preludes Book One, No 6)', 'Des pas sur la neige; No.6 from Preludes Book One'],
    ['Des pas sur la neige - Preludes Book', 'Des pas sur la neige - from Preludes Book 1'],
    ["Preludes (excerpts) - [Book 1 no.2: Voiles; Book 1 no.10: La Cathedrale engloutie; Book 1 no.9: La Serenade interrompue; Book 2 no.2: Feuilles mortes; Book 2 no.3 La puerta del vino; Book 2 no.4: Les Fees sont d'exquises danseuses]", "Preludes (excerpts): Voiles; La Cathedrale engloutie; La Serenade interrompue; Feuilles mortes; La puerta del vino; Les Fees sont d'exquises danseuses"],
    ['Kdyz men stara matka zpivat , from Ciganske melodie', 'Kdyz men stara matka zpivat , from Ciganske melodie Op 55 No 4'],
    ["Klid ('Silent Woods') for cello and orchestra, B.182, arr. from 'From the Bohemian Forest'", 'Klid (Silent Woods) for cello and orchestra (B.182)'],
    ['Legend in C major (Molto maestoso) Op 59 No 4 orchestrated by the composer', 'Legend in C major (Molto maestoso), Op.59 No.4, orch. by the composer'],
    ['Slavonic Dances, Op.46 (No. 8 In G minor', 'Two Slavonic Dances (Op.46): No.8 (Presto) in G minor & No.3 (Poco Allegro) in A flat major', 'Two Slavonic Dances: Op 46 No 8 in G minor (Presto) & Op 46 No 3 in A flat major (Poco allegro)', 'Two Slavonic Dances: Op 46 No 8 in G minor (Presto); Op 46 No 3 in A flat major (Poco Allegro)', 'Two Slavonic Dances: Op 46 No 8 in G minor and Op 46 No 3 in A flat major'],
    ['"See, even Night herself is here" (Z.62/11) from \'The Fairy Queen\'', "Song 'See, even Night herself is here' (Z.62/11) - from 'The Fairy Queen', Act II Scene 3", "Song 'See, see, even Night herself is here' Z 62/11 - from 'The Fairy Queen', Act II Scene 3"],
    ["1. See, Even Night Herself Is Here from 'The Fairy Queen'", "Various Works [1. See, Even Night Herself Is Here from 'The Fairy Queen'"],
    ['Come, ye sons of Art, away (Ode for the birthday of Queen Mary [1694], Z323)', "Ode for the Birthday of Queen Mary 'Come, ye sons of Art, away'"],
    ['Four Works: [1. Sing, ye Druids all from Bonduca, or The British heroine - incidental music Z.574', 'Four works: Sing, ye Druids all; Divine Andate; Sing, ye Druids all (reprise) - from Bonduca, or The British heroine - incidental music Z.574'],
    ['Sonata - 1683 no. 2 in B flat major Z.791 for 2 violins and continuo', 'Sonata in B flat major, Z.791, for 2 violins and continuo'],
    ['Cello Sonata in A major (M.8)', 'Sonata for cello and piano (M.8) in A major'],
    ['Cello Sonata in A major, FWV 8', 'Cello Sonata in A, FWV 8'],
    ['Le Chasseur maudit (The Accursed Huntsman), symphonic poem', 'Le Chausseur maudit (The Accursed Huntsman), symphonic poem'],
    ['Organ Piece in D flat major', 'Piece in D flat (1863)'],
    ['Piano Quintet in F minor, Op.34', 'Piano Quintet in F minor, Op.34 (Molto moderato quasi lento'],
    ['4 Lieder (Ständchen, Op.17 No.2; Morgen, Op.27 No.4; Für fünfzehn Pfennige, Op.36 No.2; Zueignung, Op.10 No.1)', '4 Lieder: Ständchen (Serenade) (Op.17 No.2); Morgen (Tomorrow) (Op.27 No.4); Für fünfzehn Pfennige (For 15 Pennies) (Op.36 No.2) (brief appl); Zueignung (Dedication) (Op.10 No.1)', '4 Lieder: Ständchen (Serenade) (Op.17 No.2); Morgen (Tomorrow) (Op.27 No.4); Für fünfzehn Pfennige (For 15 Pennies) (Op.36 No.2); Zueignung (Dedication) (Op.10 No.1)', 'Ständchen (Op.17 No.2); Morgen (Op.27 No.4); Für fünfzehn Pfennige (Op.36 No.2); Zueignung (Op.10 No.1)'],
    ["Ewig einsam ... Wenn du einst die Gauen (from 'Guntram' Op 25)", 'Ewig einsam/Wenn du einst die Gauen from "Guntram" Op 25'],
    ['Lieder: Das Rosenband (Op.36 No.1); Glückes genug (Op.37 No.1); Standchen (Op.17 No.2); Ein Obdach gegen Sturm und Regen (Op.46 No.1); Morgen (Op.27 No.4); In goldener Fülle (Op.49 No.2)', 'Lieder: Das Rosenband (Op.36 No.1); Glückes genug (Op.37 No.1); Ständchen (Op.17 No.2); Ein Obdach gegen Strum und Regen (Op.46 No.1); Morgen (Op.27 No.4); In goldener Fülle (Op.49 No.2)'],
    ["Love Scene - from the opera 'Feuersnot'", 'Love Scene from Feuersnot, Op 50'],
    ["1. Prélude – Air accompagné Tristes apprêts from 'Castor et Pollux'", "Various Works [1. Prélude – Air accompagné Tristes apprêts from 'Castor et Pollux'"],
    ['3 Pieces from Les Indes galantes; Le Rappel des oiseaux', '3 pieces from "Les Indes Galantes" & Le Rappel des Oiseaux [1. Air pour Zéphire', "3 pieces from 'Les Indes Galantes' (Air pour Zéphire; Musette en Rondeau; Air pour Borée et la Rose); Le Rappel des Oiseaux"],
    ["Ces oiseaux ('Le Temple de la gloire')", "Ces oiseaux (à Le Temple de la gloire') (Trajan's aria)", "Ces oiseaux, from 'Le Temple de la Gloire'"],
    ['Le Rappel des Oiseaux in E minor, from Pieces de clavecin (1724, revised.1731)', 'Le Rappel des Oiseaux, in E minor, from Pieces de clavecin'],
    ['Canzonetta for violin and piano in D major, Op.8', 'Canzonetta for violin and piano in D, op. 8'],
    ['Four piano pieces: Barcarole, Op.4; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9', 'Four piano pieces: Barcarole; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9'],
    ['Romanze for violin and piano in F major, Op.22', 'Romanze for violin and piano in F, op. 22'],
    ['Trio for violin, cello and piano in C major, Op.29', 'Trio for violin, cello and piano in C, op. 29'],
    ['Keyboard Sonata in D major, Kk.443; Sonata in A major, Kk.208; Sonata in D major, Kk.29)', 'Sonata in D major Kk.443; Sonata in A major Kk.208; Sonata in D major Kk.29'],
    ['Sonata for keyboard in E major (K.46/L.25)', 'Sonata for keyboard in E major, Kk.46', 'Sonata in E major, Kk.46'],
    ['Sonata in G major', 'Sonata in G major, K14'],
    ['6 Pieces for four hands, Op.11', 'Six Pieces for four hands, Op 11'],
    ['Andante from Cello Sonata in G minor, Op 19', 'Cello Sonata in G minor Op 19 (excerpt Andante)'],
    ['Bogoroditse Devo, from Vespers (All-Night Vigil)', 'Bogoroditse Devo, from Vespers (All-Night Vigil) (Ave Maria)'],
    ['Blues, from Violin Sonata no 2 in G', 'Blues, from Violin Sonata no 2 in G major'],
    ['Le Tombeau de Couperin (Forlane', 'Le Tombeau de Couperin (Forlane & Allegretto)'],
    ["Soupir, 'Trois Poèmes de Stéphane Mallarmé'", "Soupir, from 'Trois Poèmes de Stéphane Mallarmé'"],
    ['3 sacred pieces - Anima mea liquefacta; Adjuro vos, filiae Hierusalem; Siehe, wi', '3 sacred pieces - Anima mea liquefacta; Adjuro vos, filiae Hierusalem; Siehe, wie fein und lieblich ist'],
    ['Die Himmel erzählen die Ehre Gottes, BWV 76', 'Die Himmel erzählen die Ehre Gottes, SWV 76'],
    ['Saul, Saul, was verfolgst du mich, SWV 415; Nun will sich scheiden Nacht und Tag, after SWV 138; Herr, unser Herrscher (Psalm 8), SWV 27', 'Saul, Saul, was verfolgst du mich, SWV.415; Nun will sich scheiden Nacht und Tag, after SWV.138; Herr, unser Herrscher (Psalm 8), SWV.27'],
    ['Concert Prelude to Tristan und Isolde', 'Concert Prelude to Tristan und Isolde arr. Kocsis for piano'],
    ['Die Meistersinger von Nürnberg', 'Die Meistersinger von Nürnberg (Prelude)'],
    ["Overture to 'Der fliegende Holländer'", "Overture to 'Der fliegende Holländer' - The Flying Dutchman"],
    ['20 Mazurkas for piano, Op 50 nos 1, 2 & 13', 'Excerpts from 20 Mazurkas for piano (Op.50): no.1, no.2 & no.13', 'Excerpts from 20 Mazurkas for piano (Op.50): nos.1, 2 & 13', 'From 20 Mazurkas for piano Op 50: No 1 in E major; No 2; No 13', 'From 20 Mazurkas for piano, Op.50: No.1; No.2; No.13'],
    ['Concert Overture in E major, Op 12', 'Concert Overture in E, Op 12'],
    ['Prelude in C minor (Op.1/7)', 'Prelude in C minor, Op.1 No. 7'],
    ['Les Barricades mystérieuses', 'Rondeau: Les Barricades mystérieuses'],
    ['Les Fastes de la grande et ancienne Menestrandise from Pieces de clavecin - ordre no.11', 'Les Fastes de la grande et ancienne Ménestrandise (Mxnxstrxndxsx) (Pièces de clavecin - ordre 11)', 'Les Fastes de la grande et ancienne Ménestrandise (Mxnxstrxndxsx) (Pièces de clavecin - ordre no.11)', 'Les Fastes de la grande et ancienne Ménestrandise (Pièces de clavecin - ordre no.11)'],
    ["Les Pièces de clavecin - Première ordre (Paris, 1713) (L'Auguste (Allemande); Première Courante; Seconde Courante; La Majestueuse (Sarabande); Gavotte; La Milordine (Gigue); Menuet; Les Sylvains (Rondeau); Les Abeilles (Rondeau); La Nanète; les Sentiments (Sarabande); la Pastorelle; Les Nonètes. Les Blondes. Les Brunes; La Bourbonnoise (Gavotte); La Manon; L'Enchantresse (Rondeau); La Fleurie ou la tendre Nanette; Les plaisirs de Saint-Germain-en-Laye)", "Pièces de clavecin - Première ordre (Paris, 1713) (L'Auguste (Allemande); Première Courante; Seconde Courante; La Majestueuse (Sarabande); Gavotte; La Milordine (Gigue); Menuet; Les Sylvains (Rondeau); Les Abeilles (Rondeau); La Nanète; les Sentiments (Sarabande); la Pastorelle; Les Nonètes. Les Blondes. Les Brunes; La Bourbonnoise (Gavotte); La Manon; L'Enchantresse (Rondeau); La Fleurie ou la tendre Nanette; Les plaisirs de Saint-Fermain-en-Laye)"],
    ['El Amor brujo (Suite)', "Suite from 'El Amor brujo'"],
    ['Excerpts from Suite of Spanish Folksongs nos 2 & 4', 'Suite of Spanish Folksongs (nos 2 & 4)'],
    ['Serenata andaluza', 'Serenata andaluza (encore)'],
    ['Concerto in C major (Op.6 No.10)', 'Organ Concerto in C major (Op 6 No 10)'],
    ['Calicem Salutaris, Psalmus 115 Processionale', 'Calicem salutaris, Psalmus 115 (processional)'],
    ['Quasi Stella Matutina Antiphona', 'Quasi stella matutina (antiphon)'],
    ['Simile Est Regnum Antiphona and Magnificat', 'Simile est regnum (antiphon and Magnificat)'],
    ['Veni Sancte Spiritus (antiphon)', 'Veni Sancte Spiritus Antiphona'],
    ['Yo me soy la morenica', 'Yo me soy la morenica (encore)'],

    ['Drei Bruchstücke aus Wozzeck (Three fragments from Wozzeck) Op 7', 'Drei Bruchstücke aus Wozzeck, (Three fragments frm Wozzeck) Op 7', 'Three Fragments from Wozzeck (Op. 7)'],
    ['Lyric Suite (string orchestra version)', 'Lyric Suite (version for string orchestra)'],
    ['15 Preludes (selection from Opp 11, 16, 17, 22, 27 & 31)', '15 Preludes (selection from Opp.11, 16, 17, 22, 27 & 31)'],
    ['From 3 Pieces for piano (Op. 2): No. 1, Study in C sharp minor', 'Study in C sharp minor (3 Pieces for piano Op. 2 No. 1)'],
    ['1. Agnus Dei. Gloriosa spes reorum', '1. Agnus Dei. Gloriosa spes reorum - or'],
    ['1. O monialis concio burgensis', '1. O monialis concio burgensis - planctus'],
    ['44 Duos for 2 violin, Sz 98/4: Vol 4 (excerpts) - No 39 Szerb tanc; No 40 Olah tanc; No 41 Scherzo; No 42 Arab dal; No 43 Pizzicato; No 44 Erdelyi tanc (Ardeleana)', '44 Duos for 2 violins, Sz 98/4: Vol.4', 'Volume 4 from 44 Duos for 2 violins, Sz.98/4'],
    ["Excerpts from 'Twenty Hungarian Folksongs, BB 98'", 'Twenty Hungarian Folksongs, BB 98'],
    ['Canadian Carnival', 'Canadian Carnival Overture'],
    ['Les Illuminations for organ and string orchestra', 'Les Illuminations for voice and string orchestra'],
    ["Ballet music (excerpt 'Paris e Helena'", 'Paris e Helena, ballet music'],
    ['Cello Concerto No 1 in E flat', 'Cello Concerto no 1 in E flat major'],
    ['Cello Concerto No. 2 in G major Op.126', 'Concerto no. 2 in G major Op.126 for cello and orchestra'],
    ["Danse rustique, from 'Sonata No. 5 in G'", 'Danse rustique, from Sonata No.5 in G major'],
    ['Prelude from Solo Violin Sonata No 2 in A minor Op 27 No 2 (Obsession)', 'Prelude from Sonata No 2 in A minor, Op 27 No 2 (Obsession) for violin solo'],
    ['Excerpts from Songs Without Words (Op.6) (1846)', 'Excerpts from Songs Without Words (Op.6) (1846): Nos.1, 3 & 4', 'Excerpts from Songs Without Words, Op 6: no 1'],
    ['Piano Trio in D minor, Op.11', 'Trio Op.11 in D minor'],
    ['Symphony No. 103 (H.1.103) in E flat major "Drum Roll"', "Symphony No. 103 in E flat major 'Drum Roll'"],
    ['Symphony No.104 in D major "London"', 'Symphony No.104 in D major "London" (H.1.104)'],
    ['Excerpts from La Damnation de Faust (Op.24)', 'La Damnation de Faust, Op 24'],
    ['Marche hongroise (Rakoczy march) from La Damnation de Faust', 'Marche hongroise (Rakoczy march) from La Damnation de Faust - Part 1, scene 3'],
    ['Menuet in G (Humoresques de Concert, Op 14 (1886))', 'Menuet in G (Humoresques de Concert, Op.14 no.1 (1886))'],
    ['Nocturne in B flat (Op 16 no 4) & Dans le désert (Op 15)', 'Nocturne in B flat (Op.16/4) & Dans le désert (Op.15)'],
    ['El Albaicín (Iberia, Book 3)', "El Albaicín, from 'Iberia, Book 3'"],
    ['Fantasia in D minor', 'Fantasia in D minor (3)'],
    ['Fantasia in G major', 'Fantasia in G major (2) (10)'],
    ['Sinfonie in E flat', 'Symphony in E flat'],
    ['Dulcis amor Jesu', 'Dulcis amor Jesu KBPJ 16'],
    ['Vanitas vanitatum - dialogus de Divite et paupere Lazaro', 'Vanitas vanitatum - dialogus de Divite et paupere Lazaro for soprano, tenor, bass and instruments'],
    ['Excerpts from Eight Pieces for clarinet, viola and piano, Op 83', 'Excerpts from Eight Pieces for clarinet, viola and piano, Op 83 (nos 5-8)'],
    ['Fantasy for Violin and Orchestra with Harp (Op.46)', 'Scottish Fantasy (Fantasy for Violin and Orchestra with Harp, freely using Scottish Folk Melodies), Op 46', 'Scottish fantasy for violin and orchestra (Op.46)'],
    ['Hymne au Saint Sacrament', 'Hymne au Saint Sacrament for orchestra'],
    ["Louange à l'Éternité de Jésus (No.5, Quatuor pour la fin du temps for clarinet, piano, violin and cello)", "Louange à l'Éternité de Jésus: No 5 from Quatuor pour la fin du temps"],
    ['Waltz (Sleeping Beauty)', 'Waltz from Sleeping Beauty'],
    ["Ya vas lyublyu bezmerno (I love you beyond measure) - Prince Yeletsky's aria", "Ya vas lyublyu bezmerno (I love you beyond measure) - Prince Yeletsky's aria from The Queen of Spades"],
    ['Choral Songs (The Cossack; Little Wandering Bird)', "From 4 Choral Songs: Kozak ('The Cossack'), Wedrowna ptaszyna ('Little Wandering Bird')"],
    ['Triolet', 'Triolet (Triolet)'],
    ['A u sviecie nam navina byla', 'A u sviecie nam navina byla (Belarusian Christmas Song)'],
    ['Trei cantece de stea din Dobrogea', 'Trei cantece de stea din Dobrogea (Steaua sus rasare)'],
    # --- ttn_audit --all triage (2026-05) ---
    ["'Elle ne croyait pas' (aria from Mignon)", "Elle ne croyait pas ('Mignon', Act 3)"],
    ['2 French airs and 1 piece for harpsichord [Air à deux parties “Délices des étés”; Pièce pour clavecin; Air de cour “Goûtons un doux repos”]', 'Air à deux parties “Délices des étés” (Le Camus); Pièce pour clavecin (Le Roux); Air de cour “Goûtons un doux repos” (Lambert)'],
    ['2 Motets arr. for brass quintet: Peccantem me quotidiae; O vos omnes', '2 Motets: Peccantem me quotidiae; O vos omnes'],
    ['2 Motets: Pater noster, qui es in coelis (OM 1/69), Ave verum corpus (OM 3/25) - from Opus Musicum', '2 Motets: Pater noster, qui es in coelis (OM 1/69), Ave verum corpus (OM 3/25)- from Opus Musicum'],
    ['2 Songs: Najpiekniejsze pionski (The most beautiful songs, words by Adam Asnyk) (Op.4); Pod jaworem (Under the sycamore, folk song from Wloszczowa region)', 'Najpiękniejsze pionski (The most beautiful songs) Op.4 - words by Adam Asnyk; Pod jaworem (Under the sycamore) - folk song from Włoszczowa region'],
    ['3 Bulgarian Dances', '3 Bulgarian Dances arr. Wingfield'],
    ['3 Fairy Tales (Fairy Tale in A minor, Op 51 No 2; Fairy Tale in E flat major, Op 26 No 2; Fairy Tale in B flat minor Op 20 No 1)', 'Fairy Tale in A minor, Op.51 No.2; Fairy Tale in E flat major, Op.26 No.2; Fairy Tale in B flat minor Op.20 No.1'],
    ['3 Pieces for Cello and Piano - exceprts', '3 Pieces for Cello and Piano - excerpts'],
    ["3 Pieces for organ from 'Richard III'", '3 Pieces for organ from the film Richard III (March; Elegy; Scherzetto)'],
    ['3 pieces: Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi, Giorgio - Salterello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)', '3 pieces: Josquin: In te Domine speravi; Anon: Zorzi; Giorgio - Saltarello; Anon: Forte cosa e la speranza', '3 pieces: [Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi; Giorgio - Saltarello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)]'],
    ['4th movement from Viola Sonata, Op 25 No 1 (Rasendes Zeitmass. Wild. Tonschönheit ist Nebensache)', '4th movement from Viola Sonata, Op 25 No.1', 'Rasendes Zeitmaß. Wild. Tonschönheit ist Nebensache, from Viola Sonata op 25'],
    ['Adagio patetico (excerpt Piano Quintet, Op 5)', 'Adagio patetico, 3rd movement from Piano Quintet, Op 5 (1901)'],
    ['Adagio, from String Quintet in F', 'Adagio, from String Quintet in F major'],
    ["Allegro con spirito, from 'Partita, S. 48'", "Allegro con spirito, from 'Partita, S.48'"],
    ['Alma Redemptoris Mater; Ave Maria, O auctrix vite', 'Alma Redemptoris Mater; Ave Maria, O auctrix vite - Responsorium'],
    ['Arabesques on Themes from The Blue Danube Waltz by Johann Strauss, for piano', 'Concert Arabesques on Themes from The Blue Danube Waltz by Johann Strauss'],
    ['Aria "Oh! Ne t\'éveille pas encor" - from \'Jocelyn\', Act 1', 'Aria "Oh! Ne t\'éveille pas encore" - from \'Jocelyn\', Act 1', "Oh! Ne t'eveille pas encore (Jocelyn, Act 1)"],
    ['Aria "Voi lo sapete, O Mamma" from \'Cavalleria Rusticana\'', "Aria 'Voi lo sapete, O Mamma' from 'Cavalleria Rusticana' (from Scene 1, sung by Santuzza)", "Santuzza's Aria 'Voi lo sapete, O Mamma' - from 'Cavalleria Rusticana', Scene 1", "Santuzza's aria 'Voi lo sapete, O mamma' from 'Cavalleria Rusticana'"],
    ['Aria No 2 (Vocalise)', 'Aria No.2 (Vocalise No.2)'],
    ['Bassoon Concerto in C major', 'Concerto in C major for bassoon and orchestra'],
    ['Beautiful Blue Danube (Op.314)', 'On the Beautiful Blue Danube (Op.314)'],
    ["Bride's Waltz (from Et folkesagn)", "Bride's Waltz - from Et folksagn"],
    ['Canzon II Septimi Toni a 8 from Sacrae Symphoniae', 'Canzon II Septimi Toni a 8 from Sacrae Symphoniae 1597'],
    ['Carmen (Prés des remparts de Séville)', 'Prés des remparts de Séville, from Carmen'],
    ['Cello Concerto', 'Cello Concerto (T.120)'],
    ['Cello Concerto in C (Op.4)', 'Concerto for Cello and Orchestra in C (Op.4)'],
    ['Cello Sonata in E major (orig. for violin and piano)', 'Sonata in E major arr. for cello and piano'],
    ["Cello Sonata in G, Op 5 No 8 - from 'Eight solos for the violincello with a thorough bass'", "Cello Sonata in G, Op 5 No 8 - from 'Eight solos for the violoncello with a thorough bass'"],
    ['Cinq Danses exotiques, for saxophone and piano', 'Cinques Danses exotiques, for saxophone and piano'],
    ['Clarinet Trio in E flat (1900)', 'Trio in E flat major'],
    ['Come on my bull', 'Yel-yel (Come on, bull)'],
    ["Concert transcription for cello and piano of Figaro's aria 'Largo al factotum' from Rossini's 'Il barbiere di Siviglia'", "Concert transcription of 'Largo al factotum' from Rossini's 'Il barbiere di Siviglia'"],
    ['Concerto for Violin and Orchestra, Op 18', 'Violin Concerto, Op 18'],
    ['Concerto for flute, (2) oboes, strings & basso continuo in G minor', 'Concerto for flute, (2) oboes, strings & bc in G minor (S.Uu (i hs 58:5))'],
    ['Contre qui Rose (1993) - 2nd movement from Les Chanson des Roses', 'Contre qui Rose - 2nd movement from Les Chansons des Roses'],
    ['Credo From Missa Si Deus pro nobis à 16', 'Credo From Missa Si Deus pro nobis à16'],
    ['Csardas (orig. for violin and piano)', 'Csardas (originally for violin and piano)'],
    ['Danube Afterpoint (2015), octet for two pianos, string quartet and two brass instruments', 'Danube Afterpoint, octet for 2 pianos, string quartet and 2 brass instruments'],
    ['De profundis (Psalm 129) in C minor', 'De profundis (Psalm 129) in C minor, ZWV 96'],
    ['Die Leichte Kavallerie (Light cavalry)', 'Overture from Die Leichte Kavallerie', 'Overture from Die Leichte Kavallerie (Light cavalry)'],
    ["Divertimento 'Feldpartita' in B flat major, H.2.46", 'Divertimento (Feldpartita) (H.2.46) in B flat major arr. for wind quintet'],
    ['Dixit Dominus - for 5 voices & basso continuo', 'Dixit Dominus for 5 voices and continuo'],
    ['Drommarne (Dreams) - version for orchestra and choir', 'Drommarne - version for orchestra and choir'],
    ['Duos from "Don Giovanni" arranged for 2 cellos (\'Giovinette che fate all\'amore\'; \'La ci darem la mano\', \'Finch han dal vino\')', "Duos from Mozart's Don Giovanni arranged for 2 cellos ('Giovinette che fate all'amore'; 'La ci darem la mano', 'Finch han dal vino')"],
    ['Dwie Chatki (Two Cottages): The Overture', 'Overture, Dwie Chatki (Two Huts)'],
    ["Ed io che farò, Zefiro's aria for voice, two violins and basso continuo", "Ed io che farò, Zefiro's aria for voice, two violins and continuo"],
    ['Egyptian March, Op.335', 'Egyptischer March, Op 335'],
    ['Elegy in D flat major, Op 23', 'Elegy in D flat, Op 23 (encore)'],
    ['En ny himmel och en ny jord (A New Heaven and a New Earth) for a capella chorus', 'En ny himmel och en ny jord for a capella chorus', 'En ny himmel och en ny jord for a cappella chorus'],
    ['Eroticon (Op 10): No 2 in D flat; No 3 in A flat for piano', 'Eroticon Op 10): No 2 in D flat; No 3 in A flat', 'Eroticon, Op 10: no 2 in D flat major; no 3 in A flat major for piano'],
    ['Etude in F major, Op 72 no 6', 'Etude in F, Op 72 no 6 (encore)'],
    ["Excerpts from 'Livre de Guitare'", "Excerpts from 'Livre de Guitarre'", "Excerpts from 'Livre de Guittare'"],
    ['Excerpts from Trios de la Chambre du Roi', 'Excerpts from Trios de la chambre du roi simphonie', 'Trios de la Chambre du Roi Simphonie - Excerpts'],
    ['Excerpts of Ballet music from "A Hut out of the Village"', "Excerpts of Ballet music from 'A Hut out of the Village' - 'Gypsy Dance' & 'Kolomyika' (Ukrainian Dance)"],
    ['Exsulta satis - Offertorium for countertenor, tenor, two violins, viola and basso continuo', 'Exulta satis - Offertorium for countertenor, tenor, two violins, viola and basso continuo'],
    ['Fantaisie et variations brillantes sur 2 airs favoris connus for guitar (Op.30) in E minor', 'Fantaisie et variations brillantes sur 2 airs favoris connus, Op.30'],
    ['Fantasia sul linguaggio perduto for string instruments', 'Fantasia sul un linguaggio perduto for string instruments'],
    ["First Movement (Allegretto), from 'Rock Symphony'", "First movement from 'Rock Symphony'"],
    ['Five Songs: Auch kleine Dinge (Italienisches Liederbuch); Gesang Weylas (de Mörike Lieder); Nachtzauber (Eichendorff-Lieder); Mignon IV: Kennst du das Land (Goethe Lieder); Die Zigeunerin (Eichendorff-Lieder)', "Five Songs: Auch kleine Dinge, from 'Italienisches Liederbuch'; Gesang Weylas, no. 46 from 'de Mörike Lieder'; Nachtzauber, from 'Eichendorff-Lieder'; Mignon IV: Kennst du das Land, no. 9, from 'Goethe Lieder'; Die Zigeunerin, from 'Eichendorff-Lieder'"],
    ['From 5 Tone Poems for piano op 7', 'From 5 Tone Poems, Op 7'],
    ['Galathea & Mahnung - from Brettl-Lieder (Cabaret Songs) (Galathea & Warning)', 'Galathea; Mahnung (Warning) - from Brettl-Lieder (Cabaret Songs)'],
    ['Grande Sonata for piano in G minor, Op 3', 'Grande Sonata in G minor, Op.3'],
    ["Improvisation on 'Somewhere over the Rainbow'", "Improvisation on 'Somewhere over the Rainbow' by Harold Arlen"],
    ["Improvisations on 'Toccata'; 'La Spagna'; H. Butler's Theme; 'Passamezzo antico'", "Improvisations on 'Toccata'; 'La Spagna'; H. Butler's Theme; 'Passamezzo antico'; 'Ciaccona'"],
    ['Interlude from "Sången" (The Song)', 'Mellanspel ur Sången (Interlude from the cantata: The Song)'],
    ['Intraden und Tanze - from Conviviorum Deliciae', 'Intraden und Tänze - from Conviviorum Deliciae, Nuremburg 1608'],
    ['It was a lover and his lasse', 'It was a lover and his lasse (London, 1600)'],
    ['Jolly Soldier (An American Independence song taken from the Social Harp, 1855)', 'Jolly Soldier: An American Independence Song taken from the Social Harp (1855)'],
    ['Kaiser-Walzer (Op.437) (1888), arranged by Schoenberg (1925) for chamber ensemble', 'Kaiser-Walzer, Op 437, arr Schoenberg for chamber ensemble'],
    ['Kamennoi Ostrov [Portraits], Op 10 no 22', "Rêve angélique, Op.10 No.22 ('Kamennoi Ostrov', 24 Musical Portraits)"],
    ['Kantate No. 2 Ad genua - Ad ubera portabimini', 'Kantate No. 2 Ad genua - Ad ubera prtabimini'],
    ['Kyrie And Gloria From Missa Si Deus pro nobis à 16', 'Kyrie And Gloria From Missa Si Deus pro nobis à16'],
    ['La Captive: Suite from Act I (Ballet-Pantomime compilation by Frits Celis)', 'Pantomime-Ballet: La Captive - Suite from Act I (compiled by Frits Celis)'],
    ["La Noce Champetre ou l'Himen Pastoral - from Pieces pour la Muzette", "La Noce Champetre ou l'Himen Pastoral - from Pieces pour la Muzette, Paris"],
    ['La Tourière from Concerto Comique XVlll', 'La Touriére from Concerto comique No.18'],
    ['Laudate pueri', 'Laudate pueri - psalm'],
    ['Lute pieces in F minor', 'Pièces de luth in F minor'],
    ['Lyric Poem for small orchestra', 'Lyrical Poem for small orchestra'],
    ['Matteis: Passages in Imitation of the Trumpet (Ayres & Pieces IV, 1685)', 'Passages in Imitation of the Trumpet (Ayres & Pieces IV (1685)'],
    ['Melody (Orfeo ed Eurydice)', "Melody, 'Orfeo ed Euridice'"],
    ['Missa Septimus for 5 part choir, soloists, strings and continuo', 'Missa Septimus for 5-part choir, soloists, strings and continuo'],
    ["Missa sancta No.1 in E flat major 'Freischützmesse' for soli, chorus & orchestra", "Missa sancta No.1 in E flat major, J.224, 'Freischutzmesse' for soli, chorus & orchestra", "Missa sancta No.1 in E flat major, J224, 'Freischützmesse', for soloists, chorus & orchestra"],
    ["Morning Hymn from Elverskud (The Elf King's Daughter)", "Morning Hymn from Elverskud (The Elf King's Daughter), Op 30", "Morning Hymn from The Elf King's Daughter"],
    ['Moses Fantasy (after Rossini) for cello and piano (Bravura Variations on one chord from a Rossini theme)', 'Moses Fantasy for cello and piano (Bravura variations on one chord from a Rossini theme)'],
    ['Much ado about nothing - 4 pieces, arr. for viola and piano', 'Much ado about nothing - 4 pieces, arr. for violin and piano'],
    ['My River Runs To', 'My River Runs To Thee'],
    ['Mzeo Tibatvis (June Sun)', 'Mzeo tibatvisa (June Sun)'],
    ['Nocturne (Andante) - 3rd movement from Quartet for strings no.2 in D major arr. Sargent for orchestra', 'Nocturne (Andante) - 3rd movement from Quartet for strings no.2 in D major arr. for orchestra', 'Nocturne (Andante) - 3rd movement from String Quartet No 2 in D major arr. Sargent for orchestra'],
    ['O Lord, make thy servant Elizabeth', 'O Lord, make thy servant Elizabeth – for 6 voices'],
    ['O quam bonus es - motet for 2 voices (Si Lodano le Piaghe di Christo & le Mamelle Della Madonna)', 'O quam bonus es - motet for 2 voices (Si Lodano le Piaghe di Christo e le Mammelle Della Madonna)'],
    ["Oce náš hlapca jerneja (Bailif Yerney's Prayer)", "Oce náš hlapca jerneja [The Bailiff Yerney's Prayer]"],
    ['Orchestral Suite in D minor, BeRI 6', 'Suite for orchestra (BeRI 6) in D minor'],
    ["Ouverture from the opera 'Taras Bulba'", "Overture from the opera 'Taras Bulba'"],
    ['Overture from The Wasps - An Aristophanic suite', 'Overture from The Wasps - Aristophanic suite (from incidental music)'],
    ['Overture to Elverhøj', "Overture to Elverhøj (Elve's Hill)"],
    ["Overture to Hermina im Venusberg (Hermania in Venus' cave)", 'Overture to Hermina im Venusberg (Hermania in the Cave of Venus)'],
    ['Overture à 3 in C major, for alto, tenor and bass chalumeaux', 'Overture à 3 in C, for alto, tenor and bass chalumeaux'],
    ['Partita for Violin in a Sixth-tone System (1936)', 'Partita for Violins in Sixth-Tone System (1936)'],
    ['Pavane (Andante molto moderato) in F minor (Op.50) arr. for harmonica and orchestra', 'Pavane in F minor (Op.50) arr. for harmonica and orchestra', 'Pavane, Op.50, arr. for harmonica and orchestra'],
    ['Pavane de Spaigne; La Spagnolletta', 'Two works: Pavane de Spaigne; La Spagnolletta'],
    ['Piano Concerto in C', 'Piano Concerto in C major, Op 14'],
    ['Piano Quintet, Op 18', 'Quintet Op 18 for piano and strings'],
    ["Piano Sonata in C major,Op.8 No.1, 'Sonate facile'", "Sonata for piano (Op.8 No.1) in C major, 'Sonate facile'"],
    ['Piano Suite in B flat major, Op 45', 'Suite in B flat major, Op 45', 'Suite in B flat major, Op.45, for piano'],
    ['Prayer (From Jewish Life)', "Prayer, from 'From Jewish Life'"],
    ["Prima la Musica, Poì le Parole ('First the Music and then the Words') - Divertimento teatrale in one act", 'Prima la Musica, Poì le Parole - Divertimento teatrale in one act'],
    ['Quartet in E flat for clarinet, basson, horn and piano', 'Quartet in E flat for clarinet, bassoon, horn and piano'],
    ["Quartet in F for horn, oboe d'amore, violin and basso continuo FWV N:F3", "Quartet in F major for horn, oboe d'amore, violin and continuo, FWV N:F3"],
    ['Rodolfo\'s aria ("Your tiny hand is frozen") from \'La bohème\'', 'Rodolphe\'s aria ("Your tiny hand is frozen") from La Boheme, Act 1 (sung in Hungarian)'],
    ['Sanctus And Agnus Dei From Missa Si Deus pro nobis à 16', 'Sanctus And Agnus Dei From Missa Si Deus pro nobis à16'],
    ['Seemorgh - The Sunrise', 'Seemorgh - The Sunrise for Orchestra'],
    ['Serenata in vano', 'Serenata in vano, FS 68'],
    ['Sinfonia No. 14 in G - excerpt', 'Sinfonia no 14 in G'],
    ['Sinfonia in E flat, Op.1 No.4', 'Sinfonia, Op.1 No.4', 'Sinphonia No.4 (Op.1)'],
    ['Siwy koniu (You Grey Horse)', 'You Grey Horse'],
    ['Sonata 1.x.1905 for piano in E flat minor', "Sonata 1.x.1905 for piano in E flat minor, 'Zulice'"],
    ['Sonata No 11 for cornet, violin and continuo', 'Sonata No 11 for cornett, violin and continuo'],
    ['Sonata No 7 for 3 flutes Op 1 No 4', 'Sonata for 3 recorders or flutes in C minor, Op 1 no 4', 'Sonata in C minor, Op 1 no 4'],
    ['Sonata da Camera in C major, CSWV Anh:4', 'Sonata da Camera in C, CSWV Anh:4'],
    ['Sonata for oboe, bassoon and basso continuo in C minor, WD. 695', 'Sonata for oboe, bassoon and basso continuo in C minor, WD.695'],
    ["Sonata for violin and continuo (Op.8 No.2) in D major, from 'X Sonate'", "Violin Sonata in D major, Op 8 No 2, from 'X Sonate' (Amsterdam, 1744)"],
    ["Sonata for violin and continuo, Op.9 No.12, 'La Folia'", "Violin Sonata Op.9 No.12 'La Folia'"],
    ['Sonatina I in G - from Six Sonatines, Op 8', 'Sonatina No.1 in G - from Six Sonatines, Op.8', 'Sonatina in G, Op 8 No 1'],
    ['Sonatina for Violin and Piano in A flat', 'Violin Sonatina in A flat'],
    ["String Quintet No.60 (G.324) (Op.30 No.6) in C major 'La Musica notturna delle strade di Madrid'", "String Quintet No.60 in C major, Op.30 No.6 (G.324), 'La Musica notturna delle strade di Madrid' arr. for string orchestra"],
    ['String Trio in D major, Op 3 no 6', 'String Trio in D, Op 3 no 6'],
    ['Suite No 1 in F major for two pianos, Op 15', 'Suite No 1 in G major, Op 15', 'Suite No.1 in F for 2 pianos (Op.15)', 'Suite No.1 in F major for 2 pianos, Op.15'],
    ["Suite from 'A Midsummer Night's Dream', Op.61", "Wind music from 'A Midsummer Night's Dream', Op.61"],
    ["Symphonie à grand orchestre de l'opera Cora", 'Symphonie à grand orchestre de l\'opéra Cora (Overture to "Cora and Alonzo")'],
    ['Symphony for Winds in G minor, A. 509', 'Symphony for Winds in G minor, A.509'],
    ['Symphony in C', 'Symphony in C major'],
    ['Tassilone (comp. Dusseldorf 1709) - excerpts', 'Tassilone (comp. Dusseldorf 1709)- excerpts'],
    ['The Spring Came on a Walpurgis Night', 'Varen kom en valborgsnatt (The spring came on a Walpurgis night)'],
    ['Three Pieces for Clarinet and Piano', 'Three pieces for clarinet'],
    ['Three Songs with texts by JP Contamine de La Tour', 'Three Songs with texts by JPContamine de La Tour'],
    ["Three Songs: Die stille Stadt, from 'Vier Lieder'; Licht in der Nacht, from 'Vier Lieder'; Bei dir ist es Traut, from 'Fünf Lieder'", 'Three Songs: Die stille Stadt; Licht in der Nacht; Bei dir ist es Traut'],
    ['To be Sung of a Summer Night on the Water', 'To be Sung of a Summer Night on the Water (RT.4.5)'],
    ['Toccatina from No 1 in D (Toccatina', "Toccatina from No.1 in D major from 'Fasciculus Musicus'"],
    ['Traces of Magic (Octet for clarinet, bassoon, horn, string qtet & double bass)', 'Traces of Magic (Octet for clarinet, bassoon, horn, string quartet & double bass)'],
    ["Tre madrigal di Torquato Tasso (Op.13): A Virgilio (To Virgil); All' Aurora (To the Dawn); Non e questo un morire (This is not to die)", "Tre madrigali di Torquato Tasso, Op.13: A Virgilio (To Virgil); All' aurora (To the Dawn); Non e questo un morire (This is Not to Die)"],
    ["Two Love Songs: 1.The Passionate Shepherd to His Love (Text Christopher Marlowe); 2.The Nymph's Reply to the Shepherd (Text Sir Walter Raleigh)", "Two Love Songs: The Passionate Shepherd to His Love (Text Christopher Marlowe); The Nymph's Reply to the Shepherd (Text Sir Walter Raleigh)"],
    ['Two Psalm-tunes: Kittery (1786); Cobham (1794)', 'Two psalm-tunes: Kittery (1786) & Cobham (1794)'],
    ["Una notte in Ellade (sull'Acropoli), orchestral nocturne, Op.31", "Una notte in Ellade (sull'Acropoli), orchestral notturno, Op.31"],
    ["Variations on the old Swedish air 'Och liten Karin tjente' in E minor, Op.91", 'Variations on the old Swedish air Och liten Karin tjente, Op 91'],
    ['Weihnacht in der uralten Marienkirche zu Krakau', 'Weihnacht in der uralten Marienkirche zu Krakau. Fantasie Felix Nowowiejski'],
    ["When Mary thro' the garden went (from 8 Partsongs, Op 127 no 3)", "When Mary thro' the garden went, Op 127 No 3"],
]


@pytest.mark.parametrize("variants", _AUDIT_REAIRING_GROUPS,
                         ids=[g[0][:45] for g in _AUDIT_REAIRING_GROUPS])
def test_audit_reairing_variants_collapse_to_one_group(variants):
    keys = {resolve_work_alias(work_title_key(v)) for v in variants}
    assert len(keys) == 1


def test_vivaldi_four_seasons_movements_stay_distinct():
    # Spring/Summer/Autumn/Winter share a title prefix but are distinct works.
    assert not _same_group("The Four Seasons rearranged - Spring",
                           "The Four Seasons rearranged - Summer")


def test_four_seasons_rearranged_distinct_from_original():
    # A "rearranged" Four Seasons (e.g. a recomposition) is a separate work
    # from Vivaldi's original — the 'rearranged' token keeps them apart.
    for season in ("Spring", "Summer", "Autumn", "Winter"):
        assert not _same_group(f"The Four Seasons - {season}",
                               f"The Four Seasons rearranged - {season}")


def test_mendelssohn_elias_parts_stay_distinct():
    # Part I and Part II of the oratorio must not fuse — a bare "(Carus
    # edition)" with no part number was deliberately left out of the merges.
    assert not _same_group("Elias (Elijah), Op.70 - oratorio: Part I",
                           "Elias (Elijah), Op.70 - oratorio: Part II")


# --- arrangement folding (token-sort path) -------------------------------

def test_strip_arrangement_tail_drops_arr_clause():
    assert _strip_arrangement_tail(
        "Prélude à l'après-midi d'un faune arr. for chamber ensemble"
    ) == "Prélude à l'après-midi d'un faune"


def test_strip_arrangement_tail_drops_transcribed_clause():
    assert _strip_arrangement_tail(
        "Danse macabre, Op.40, transcribed for 2 pianos by the composer"
    ) == "Danse macabre, Op.40"


def test_strip_arrangement_tail_drops_orig_annotation():
    assert _strip_arrangement_tail(
        "Romance in F major, Op 50 (orig. for violin and orchestra)"
    ) == "Romance in F major, Op 50"


def test_strip_arrangement_tail_preserves_movement_after_colon():
    assert _strip_arrangement_tail(
        "3 Hungarian Dances arr. for string orchestra: No 1 in G minor"
    ) == "3 Hungarian Dances: No 1 in G minor"


def test_strip_arrangement_tail_leaves_bare_scoring_alone():
    # bare "for <scoring>" is NOT an explicit arrangement marker
    assert _strip_arrangement_tail(
        "Concerto for Orchestra") == "Concerto for Orchestra"
    assert _strip_arrangement_tail(
        "Fratres for cello and piano") == "Fratres for cello and piano"


def test_strip_arrangement_tail_word_boundary_safety():
    # "orig" must not match inside "Original"
    assert _strip_arrangement_tail("Original Rags") == "Original Rags"


def test_strip_arrangement_tail_marker_at_start_keeps_title():
    # a title that is only an arrangement clause is returned unchanged
    assert _strip_arrangement_tail(
        "Arrangement of a theme") == "Arrangement of a theme"


# --- _squash_separators ---------------------------------------------------

def test_squash_separators_hyphen_to_space():
    assert _squash_separators("l'apres-midi") == "lapres midi"


def test_squash_separators_drops_apostrophe():
    assert _squash_separators("toy soldier's") == "toy soldiers"


def test_squash_separators_leaves_clean_text_alone():
    # No hyphen or apostrophe present -> unchanged.
    assert _squash_separators("rimsky korsakov") == "rimsky korsakov"


# --- arrangement folding in work_title_key (token-sort path) -------


def test_arrangement_folds_faune():
    assert _same_group(
        "Prélude à l'après-midi d'un faune",
        "Prelude a l'apres-midi d'un faune arr. for chamber ensemble")


def test_arrangement_folds_ravel_pavane():
    assert _same_group(
        "Pavane pour une infante défunte",
        "Pavane pour une infante defunte arr. for oboe and piano")


def test_arrangement_folds_danse_macabre_transcription():
    assert _same_group(
        "Danse macabre, Op 40",
        "Danse macabre Op 40 transcr. Saint-Saens for 2 pianos")


def test_arrangement_folds_gershwin_rhapsody():
    assert _same_group(
        "Rhapsody in Blue",
        "Rhapsody in Blue arr. Lundin for piano and string quintet")


def test_arrangement_folds_orig_annotation():
    assert _same_group(
        "Romance in F major, Op 50",
        "Romance in F major, Op 50 (orig. for violin and orchestra)")


def test_arrangement_bare_scoring_stays_distinct():
    # "for cello and piano" is not an explicit marker -> Fratres stays split
    assert not _same_group("Fratres", "Fratres for cello and piano")


def test_by_piece_keeps_arrangements_separate():
    # --by piece keys on canonical_key(title), which retains the arrangement
    # wording, so the scorings stay distinct under --by piece, unlike --by work
    assert canonical_key("Prélude à l'après-midi d'un faune") != \
        canonical_key("Prelude a l'apres-midi d'un faune arr. for chamber ensemble")


def test_arrangement_distinct_works_stay_split():
    # the strip removes only the arrangement clause, not work identity: two
    # different works, each with an arrangement marker, must not collapse
    assert not _same_group(
        "Prelude a l'apres-midi d'un faune arr. for chamber ensemble",
        "Pavane pour une infante defunte arr. for oboe and piano")


# --- separator folding in work_title_key (token-sort path) ----------

def test_hyphen_variant_folds_faune():
    assert _same_group("Prélude à l'après-midi d'un faune",
                       "Prélude à l'après midi d'un faune")


def test_hyphen_variant_folds_siegfried_idyll():
    assert _same_group("Siegfried-Idyll", "Siegfried Idyll")


def test_apostrophe_placement_folds_toy_soldiers():
    assert _same_group("Toy Soldier's March", "Toy Soldiers' March")


def test_digit_sibling_works_stay_split_after_squash():
    # The squash must NOT collapse works differing by a number.
    assert not _same_group("Hungarian Dance No 1", "Hungarian Dance No 5")


def test_hyphenated_key_signature_folds():
    # A hyphenated key signature is the same key as the spaced form (same
    # work): "B-flat major" splits to "b flat major", matching "B flat major".
    assert _same_group("Sonata in B-flat major", "Sonata in B flat major")


# --- _drop_implicit_major --------------------------------------------------

def test_drop_implicit_major_bare_note():
    assert _drop_implicit_major("symphony in f major op 68") == \
        "symphony in f op 68"


def test_drop_implicit_major_flat_note():
    assert _drop_implicit_major("symphony no 3 in e flat major op 55") == \
        "symphony no 3 in e flat op 55"


def test_drop_implicit_major_sharp_note():
    assert _drop_implicit_major("barcarolle in f sharp major op 60") == \
        "barcarolle in f sharp op 60"


def test_drop_implicit_major_leaves_minor_alone():
    # No implicit-minor convention; minor must always remain.
    assert _drop_implicit_major("symphony no 5 in c minor op 67") == \
        "symphony no 5 in c minor op 67"


def test_drop_implicit_major_no_op_no_change():
    # Plain key+major outside the 'in <note>' pattern is untouched.
    assert _drop_implicit_major("major league baseball") == \
        "major league baseball"


# --- implicit-major folding in work_title_key (token-sort path) -----------

def test_eroica_implicit_major_folds():
    assert _same_group("Symphony No. 3 in E flat, op. 55 ('Eroica')",
                       "Symphony no 3 in E flat major, Op 55 'Eroica'")


def test_pastoral_implicit_major_folds():
    assert _same_group("Symphony no 6 in F major, Op 68 (Pastoral)",
                       "Symphony no 6 in F, Op 68 ('Pastoral')")


def test_mendelssohn_italian_implicit_major_folds():
    assert _same_group("Symphony no 4 in A major, Op 90 'Italian'",
                       "Symphony no 4 in A, Op 90 'Italian'")


def test_dvorak_american_quartet_implicit_major_folds():
    assert _same_group("String Quartet no 12 in F major, Op 96 'American'",
                       "String Quartet No. 12 in F, op. 96 'American'")


def test_chopin_nocturne_flat_major_folds():
    # 'D flat' / 'D flat major' on a token-sort-path piece (Op present
    # but not in the catalogue ref list).
    assert _same_group("Nocturne in D flat major, Op 27 no 2",
                       "Nocturne in D flat, Op 27 no 2")


def test_minor_works_stay_split_from_their_major_namesakes():
    # If the rule misfired and dropped 'major' indiscriminately, this would
    # fold. Guard: distinct works in major vs minor must stay distinct.
    assert not _same_group("Symphony no 1 in C major, Op 21",
                           "Symphony no 1 in C minor, Op 21")


# --- WORK_ALIASES: spelling/transliteration audit (2026-05-25) -------------

def test_scheherazade_spellings_consolidate():
    canon = "Scheherazade - symphonic suite, Op.35"
    for variant in ("Sheherazade - symphonic suite Op.35",
                    "Scheherezade - symphonic suite, Op.35",
                    "Scheherazade - symphonic suite after 1001 Nights, Op 35",
                    "Sheherazade, Op 35",
                    "Sheherazade",
                    "Scheherazade, Op 35"):
        assert _same_group(variant, canon), variant


def test_scheherazade_arabian_song_excerpt_stays_separate():
    # An excerpt 'from' the suite is a derived piece, not the suite itself.
    assert not _same_group("Arabian Song, from 'Scheherezade', Op 35",
                           "Scheherazade - symphonic suite, Op.35")


def test_auf_dem_wasser_deutsch_number_typo_folds():
    # D744 is a transposition typo for D.774 (both on the catalogue path).
    assert _same_group("Auf dem wasser zu singen, D744",
                       "Auf dem Wasser zu singen, D.774")


def test_doppler_fantaisie_spelling_folds():
    assert _same_group("Fantasie Pastorale Hongroise, Op 26",
                       "Fantaisie pastorale hongroise, Op 26")


def test_faune_dune_typo_folds():
    assert _same_group("Prélude à l'àpres midi d'une faune",
                       "Prélude à l'après-midi d'un faune")


# --- WORK_ALIASES: catalogue-path phantom-ordering audit (2026-05-26) ------
# The catalogue path includes all digits in the key, which keeps set-catalogue
# siblings distinct (impromptus, arias) but causes false splits when the BBC
# inconsistently includes the within-form ordering number. Each test merges a
# real variant pair surfaced in the corpus audit.

def test_bwv1056_keyboard_no5_folds():
    assert _same_group("Keyboard Concerto in F minor, BWV.1056",
                       "Harpsichord Concerto no 5 in F minor, BWV.1056")


def test_bwv1056_oboe_reconstruction_folds():
    # Two scorings of the same lost original — F-minor harpsichord and the
    # G-minor oboe reconstruction. Same BWV; merge accepted.
    assert _same_group(
        "Concerto for oboe and strings in G minor (reconstructed from BWV.1056)",
        "Harpsichord Concerto no 5 in F minor, BWV.1056")


def test_bwv1068_bare_air_folds_into_suite():
    assert _same_group("Air, Overture in D major, BWV1068",
                       "Orchestral Suite No 3 in D major, BWV 1068")


def test_bwv1006_prelude_excerpt_splits_from_whole():
    # Movement-marker gate: the Prelude excerpt keys §bwv1006|prelude,
    # distinct from the whole Partita.
    assert not _same_group(
        "Prelude from Partita no 3 in E major (BWV 1006) arr. for 2 harps",
        "Partita for solo violin No.3 in E major, BWV.1006")


def test_bwv1007_sarabande_splits_from_whole():
    assert not _same_group("Sarabande from Suite for cello solo (BWV.1007) in G major",
                           "Suite for solo cello no 1 in G major (BWV 1007)")


def test_bwv1009_sarabande_splits_from_whole():
    assert not _same_group("Sarabande from Suite for solo cello in C (BWV.1009)",
                           "Suite for solo Cello No.3 in C major (BWV.1009)")


def test_bwv1005_largo_splits_from_whole():
    # "Largo from Suite for solo violin … BWV.1005" is a movement excerpt;
    # the gate keys it §bwv1005|largo, split from the whole sonata.
    assert not _same_group("Largo from Suite for solo violin no.3, BWV.1005",
                           "Violin Sonata No.3 in C, BWV.1005")


# --- Catalogue-path phantom-ordering: batch 3 (composer/ref scan) ----------

def test_d590_italian_overture_missing_key_folds():
    assert _same_group("Overture in the Italian Style, D.590",
                       "Overture in D major 'In the Italian Style', D.590")


def test_d667_trout_phantom_op114_folds():
    assert _same_group("Piano Quintet in A major 'The Trout', Op 114 (D.667)",
                       "Piano Quintet in A major 'The Trout', D.667")


def test_d958_piano_sonata_no19_folds():
    # Mirrors the D.845/D.959/D.960 pattern from the sonata batch.
    assert _same_group("Piano sonata no 19 in C minor, D.958",
                       "Piano Sonata in C minor, D.958")


def test_bwv1003_violin_sonata_2_bare_folds():
    assert _same_group("Sonata for solo violin no 2, BWV.1003",
                       "Violin Sonata no 2 in A minor, BWV.1003")


def test_bwv1041_violin_concerto_1_bare_folds():
    assert _same_group("Violin Concerto in A minor, BWV.1041",
                       "Concerto for violin and string orchestra No.1 in A minor (BWV.1041)")


def test_bwv1055_bare_and_c_major_typo_fold():
    main = "Concerto for oboe d'amore and string orchestra No.4 in A major, BWV.1055"
    assert _same_group("Concerto in A major, BWV.1055", main)
    # The "Allegro from Concerto …" movement excerpt now keys §bwv1055|allegro
    # via the movement-marker gate — split from the whole concerto.
    assert not _same_group("Allegro from Concerto in C major, BWV.1055", main)


def test_rv428_goldfinch_phantom_op10no3_folds():
    assert _same_group(
        "Flute Concerto in D major, RV.428 (Op.10 No.3) ('Il Gardellino')",
        "Flute Concerto in D major, RV.428 ('Il Gardellino')")


def test_rv297_winter_phantom_op8no4_folds():
    main = "Violin Concerto in F minor, RV.297 'L'Inverno'"
    assert _same_group(
        "Violin Concerto in F minor, RV.297 (Op.8 No.4), arr. for accordion",
        main)
    # The "Largo from L'Inverno" movement excerpt now keys §rv297|largo via
    # the movement-marker gate — split from the whole concerto.
    assert not _same_group(
        "Largo from L'Inverno (Winter), Violin Concerto no 4 in F minor, RV.297",
        main)


def test_d958_d959_d960_late_sonatas_stay_split_after_no19_alias():
    # Defensive: the D.958 phantom-19 alias must not bleed into D.959/D.960.
    assert not _same_group("Piano sonata no 19 in C minor, D.958",
                           "Piano Sonata no 20 in A major, D.959")
    assert not _same_group("Piano Sonata in C minor, D.958",
                           "Piano Sonata no 21 in B flat major, D.960")


# --- Long-tail follow-up to catalogue-path batch 3 -------------------------

def test_rv269_la_primavera_phantom_op8_folds():
    assert _same_group(
        "La Primavera (Spring), Violin Concerto no 1 in E, RV 269",
        "Concerto for violin & orchestra (RV.269) (Op.8 No.1) in E major 'La Primavera'")


def test_k421_string_quartet_15_bare_folds():
    assert _same_group("String Quartet no 15 in D minor, K.421",
                       "Quartet for Strings in D minor, K.421")


def test_k418_vorrei_spiegarvi_aria_folds():
    # Catalogue path skipped on "aria" excerpt marker; aliases bridge the
    # token-sort variants for this standalone concert aria.
    assert _same_group(
        "Vorrei spiegarvi, oh Dio - aria K.418",
        "Vorrei spiegarvi, oh Dio - aria for soprano and orchestra, K.418")


def test_rv269_distinct_from_rv315_summer():
    # Sibling Four Seasons concertos must stay split.
    assert not _same_group(
        "La Primavera (Spring), Violin Concerto no 1 in E, RV 269",
        "L'Estate (Summer), Violin Concerto no 2 in G minor, RV 315")


# --- --form audit surfacings -----------------------------------------------

def test_symphonie_fantastique_bare_form_folds():
    # `--form symphony` (cross-language fold) surfaced this split that
    # `--title symphony` would have missed.
    assert _same_group("Symphonie fantastique",
                       "Symphonie Fantastique, Op 14")


def test_faure_nocturne_op107_phantom_no12_folds():
    assert _same_group("Nocturne no 12 in E minor, Op 107",
                       "Nocturne in E minor, Op 107")


def test_bartok_sz56_six_phantom_folds():
    assert _same_group("6 Romanian folk dances, Sz.56",
                       "Romanian Folk Dances, Sz.56")


def test_mendelssohn_italian_bare_form_folds():
    # Bare-form titles lack Op 90 (and sometimes the key signature too).
    main = "Symphony No 4 in A major, Op 90 'Italian'"
    assert _same_group("Symphony no.4, 'Italian'", main)
    assert _same_group("Symphony No.4 in A major, 'Italian'", main)


def test_mendelssohn_italian_alias_does_not_bleed_to_no_3():
    # The Italian-nickname tag is the discriminator. A bare "Symphony No 4"
    # without the nickname should not match the Italian (it would be
    # ambiguous since Mendelssohn's no 3 is the Scottish, no 5 the
    # Reformation, etc.). The alias key explicitly requires "italian".
    assert not _same_group("Symphony no 3 in A minor, Op 56 'Scottish'",
                           "Symphony No 4 in A major, Op 90 'Italian'")
    assert not _same_group("Symphony No 4 in A major",
                           "Symphony No 4 in A major, Op 90 'Italian'")


def test_tchaikovsky_marche_slave_cross_language_folds():
    # Five distinct token-sort groups under one work — French, English,
    # bilingual, and mixed-locator variants. `--form march` made this
    # visible; --title march in English alone caught only ~half.
    main = "Marche Slave, Op 31"
    assert _same_group("Slavonic March in B flat minor 'March Slave'", main)
    assert _same_group("Slavonic March in B flat minor, op. 31", main)
    assert _same_group("Slavonic March in B flat minor (Op.31) 'March Slave'", main)
    assert _same_group("Slavonic March in B flat minor 'Marche slave' (Op.31)", main)


def test_chopin_12_studies_for_piano_scoring_folds():
    assert _same_group("12 Studies Op 25", "12 Studies Op 25 for piano")
    assert _same_group("12 Studies Op 10", "12 Studies Op 10 for piano")


def test_chopin_op25_does_not_merge_with_op10():
    # Sibling etude sets must stay split.
    assert not _same_group("12 Studies Op 25",
                           "12 Studies Op 10 for piano")


def test_beethoven_woo46_bare_variations_folds():
    assert _same_group(
        "Variations on 'Bei Mannern, welche Liebe fuhlen' (WoO.46)",
        "7 Variations on 'Bei Mannern, welche Liebe fuhlen' WoO 46")


def test_grieg_holberg_suite_variants_fold():
    main = "Holberg Suite (Op.40)"
    assert _same_group("Holberg Suite", main)
    assert _same_group("Holberg suite (Op.40) version for string orchestra", main)


def test_grieg_holberg_movement_excerpt_stays_split():
    # The Praeludium excerpt is a single movement of the suite; correctly
    # stays in its own group rather than merging into the whole.
    assert not _same_group("Holberg Suite, Op 40 - Praeludium",
                           "Holberg Suite (Op.40)")


def test_weber_clarinet_concertino_op26_word_order_folds():
    # "Clarinet Concertino" and "Concertino for clarinet and orchestra"
    # are the same work — Op 26 in E flat. Word-order split, plus a
    # bare-form variant that drops "clarinet" entirely.
    main = "Clarinet Concertino in E flat major, Op 26"
    assert _same_group("Concertino for clarinet and orchestra in E flat major, Op 26", main)
    assert _same_group("Concertino in E flat, Op 26", main)


def test_weber_clarinet_concertino_distinct_from_oboe_concertino():
    # Weber wrote both a Clarinet Concertino (Op 26 in E flat) and an Oboe
    # Concertino (in C major). The alias must not bleed.
    assert not _same_group("Clarinet Concertino in E flat major, Op 26",
                           "Concertino for oboe and wind ensemble in C major")


def test_mendelssohn_octet_op20_variants_fold():
    # Same Weber-Concertino pattern: word-order split + bare-form variant.
    main = "String Octet in E flat major, Op 20"
    assert _same_group("Octet for strings in E flat major, Op 20", main)
    assert _same_group("Octet in E flat major, Op 20", main)


def test_spohr_nonet_op31_bare_form_folds():
    assert _same_group(
        "Nonet in F major, Op 31",
        "Nonet for wind quintet, string trio and double bass in F major, Op 31")


def test_tchaikovsky_violin_concerto_op35_bare_form_folds():
    # Bare "Violin Concerto in D major" folds into the Op 35 group.
    # Note: title-key is shared with Stravinsky's own Violin Concerto in
    # D, but composer-scoped grouping keeps them separate.
    assert _same_group("Violin Concerto in D major",
                       "Violin Concerto in D major (Op.35)")


# --- Op-bucket scan batch -------------------------------------------------

def test_mendelssohn_hebrides_fingals_cave_alt_title_folds():
    # The ×17 B-minor / "Fingal's Cave" form folds into the same group as
    # the existing Hebrides alias block.
    assert _same_group(
        "The Hebrides - Overture in B minor, Op.26, 'Fingal's Cave'",
        "The Hebrides, Op 26")


def test_beethoven_coriolan_with_key_signature_folds():
    assert _same_group("Coriolan - Overture in C minor, Op.62 (1807)",
                       "Coriolan Overture Op 62")


def test_chopin_barcarolle_op60_bare_form_folds():
    assert _same_group("Barcarolle, Op 60",
                       "Barcarolle in F sharp major, Op 60")


def test_schumann_kinderszenen_bare_form_folds():
    assert _same_group("Kinderszenen, Op 15",
                       "Kinderszenen for piano, Op 15")


def test_schumann_kinderszenen_traumerei_excerpt_stays_split():
    # Movement excerpts must NOT fold into the parent work.
    assert not _same_group("Träumerei from 'Kinderszenen', Op 15",
                           "Kinderszenen for piano, Op 15")


def test_suk_elegy_op23_cross_language_and_keysig_fold():
    main = "Elegy (Op 23) arr. for piano trio"
    assert _same_group("Elegie, Op 23", main)
    assert _same_group("Elegy in D flat major, Op 23", main)
    assert _same_group(
        "Elegie (Pod dojmem Zeyerova Vysehradu), Op 23, arr. for piano trio",
        main)


def test_chaminade_flute_concertino_op107_bare_form_folds():
    assert _same_group("Concertino, Op 107",
                       "Flute Concertino, Op 107")


def test_dvorak_american_quartet_word_order_folds():
    assert _same_group(
        "Quartet no. 12 in F major Op 96 (American) for strings",
        "String Quartet No 12 in F Major 'American' Op 96")


def test_schumann_phantasiestucke_op73_spelling_and_arr_fold():
    main = "Phantasiestucke Op 73 for clarinet & piano"
    assert _same_group("Fantasiestucke, Op 73", main)
    assert _same_group("Phantasiestucke, Op.73", main)
    # English translation and word-order variant also fold:
    assert _same_group("3 Fantasy Pieces, Op 73", main)
    assert _same_group("Fantasiestucke, Op 73, for clarinet and piano", main)


def test_schumann_phantasiestucke_op12_distinct_from_op73():
    # Two distinct works share the form name; opus number is the
    # discriminator.
    assert not _same_group("Fantasiestucke, Op 12",
                           "Phantasiestucke Op 73 for clarinet & piano")


def test_d821_arpeggione_sonata_bare_form_folds():
    assert _same_group("Arpeggione Sonata (D.821)",
                       "Arpeggione Sonata in A minor, D.821")


def test_hwv350_water_music_phantom_2_folds():
    assert _same_group(
        "Water Music: Suite in G major for 'flauto piccolo', 2 oboes, bassoon and strings, HWV.350",
        "Water Music - suite HWV.350 in G major")


# --- Satie audit ----------------------------------------------------------

def test_satie_je_te_veux_variants_fold():
    main = "Je te veux, valse"
    assert _same_group("Je te veux", main)
    assert _same_group("Je te Veux (Valse chantée pour piano)", main)


def test_satie_trois_melodies_latour_variants_fold():
    main = "Three melodies with texts by J.P.Contamine de La Tour"
    assert _same_group("Three melodies with texts by J.P. Contamine de La Tour", main)
    assert _same_group("Three Songs with texts by JPContamine de La Tour", main)
    assert _same_group("Three Songs with texts by JP Contamine de La Tour", main)


def test_satie_gnossienne_no1_for_piano_scoring_folds():
    assert _same_group("Gnossienne No.1",
                       "Gnossienne No 1 for piano")


def test_satie_4_pieces_program_folds():
    # The bare "4 Pieces" is Satie-exclusive; the BBC airs a standard
    # 4-piece program (Gymnopédie No 1; Les anges; Le chapelier; Je te
    # veux) under both detailed and truncated titles.
    assert _same_group(
        "4 Pieces",
        "4 Pieces: [1.Gymnopedie No.1; 2.Les anges, from 'Trois melodies' "
        "(Latour); 3.Le chapelier, from 'Trois melodies'; 4.Je te veux]")


def test_satie_gymnopedies_set_distinct_from_pair_program():
    # "Three Gymnopedies" (the full set) vs "Gymnopédies no 1 and no 3"
    # (a 2-piece BBC program). These are different programs and stay split.
    assert not _same_group("Three Gymnopedies",
                           "Gymnopédies no 1 and no 3")


# --- Liszt audit ----------------------------------------------------------

def test_liszt_hungarian_rhapsody_2_s244_variants_fold():
    main = "Hungarian Rhapsody No 2 in C sharp minor"
    assert _same_group("Hungarian Rhapsody No 2 in C sharp minor (from S.244)", main)
    assert _same_group(
        "Hungarian Rhapsody no 2 for piano in C sharp minor (S.244 No.2)", main)


def test_liszt_hungarian_rhapsody_6_bare_form_folds():
    assert _same_group("Hungarian Rhapsody No 6",
                       "Hungarian Rhapsody No 6 in D flat major")


def test_liszt_piano_concerto_2_s125_folds():
    assert _same_group("Piano Concerto No 2 in A major, S125",
                       "Piano Concerto no 2 in A major")


def test_liszt_piano_concerto_1_s_number_tokenization_folds():
    # "S. 124" (period+space) tokenizes as two tokens; "S124" as one.
    # Without the alias these split. (Same pattern as the B-minor sonata.)
    assert _same_group("Piano Concerto no 1 in E flat, S 124",
                       "Piano Concerto no 1 in E flat, S124")


def test_liszt_b_minor_sonata_variants_fold():
    main = "Piano Sonata in B minor, S.178"
    assert _same_group("Sonata in B minor S.178 for piano", main)
    assert _same_group("Piano Sonata in B minor, S 178", main)


def test_liszt_rhapsodie_espagnole_typo_and_scoring_fold():
    # "Aragone" is a BBC typo for "aragonesa"; plus scoring annotation
    # and bare-form variants all collapse.
    main = "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"
    assert _same_group(
        "Rhapsodie espagnole (Folies d'Espagne et jota aragonesa) S.254 for piano", main)
    assert _same_group(
        "Rhapsodie espagnole (Folies d'Espagne et jota aragonesa) S.254", main)
    assert _same_group("Rhapsodie Espagnole, S 254", main)


def test_liszt_petrarch_sonnet_104_variants_fold():
    main = ("Sonetto 104 del Petrarca, 'Années de pèlerinage, "
            "deuxième année: Italie, S.161'")
    assert _same_group(
        "Petrarch Sonnet No 104 (Années de Pelerinage, année 2, S 161)", main)
    assert _same_group(
        "Sonetto 104 from 'Tre Sonetti del Petrarca' (S.161 No.5)", main)
    assert _same_group(
        "Sonetto 104 (Tre Sonetti del Petrarca), S 161 No 5", main)
    assert _same_group("Petrarch Sonnet no 104 S.161", main)


def test_liszt_transcendental_study_11_harmonies_du_soir_folds():
    assert _same_group(
        "Transcendental study No 11 in D flat major 'Harmonies du soir' "
        "- from Etudes d'execution transcendante for piano (S.139)",
        "Transcendental study No 11 in D flat major")


def test_liszt_csardas_macabre_spelling_folds():
    assert _same_group("Czardas macabre",
                       "Csardas macabre")


def test_liszt_legendes_stay_split():
    # The two Légendes are distinct works; my Hungarian Rhapsody folds
    # must not leak into them.
    assert not _same_group(
        "Legende No.1: St. Francois d'Assise prechant aux oiseaux (S.175)",
        "St Francois de Paule marchant sur les flots")


def test_liszt_mazeppa_etude_vs_symphonic_poem_stays_split():
    # Liszt wrote both — Transcendental Étude No 4 'Mazeppa' (piano)
    # and Mazeppa, Symphonic Poem No 6 (orchestra). Different works.
    assert not _same_group(
        "Etude no 4 in D minor 'Mazeppa'",
        "Mazeppa - Symphonic Poem")


def test_liszt_petrarch_sonnet_123_parent_set_framing_folds():
    # Parallel to the Sonnet 104 case: one variant prefixes the parent
    # set "Années de Pèlerinage" framing.
    assert _same_group(
        "From 'Années de Pèlerinage' (deuxième année - Italie): "
        "Sonetto 123 del Petrarca (S.158 No.3): "
        "Io vidi in terra angelici costumi",
        "Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi")


# --- Debussy audit --------------------------------------------------------

def test_debussy_danses_english_translation_folds():
    assert _same_group("Two Dances for Harp and Strings",
                       "Danse sacree et danse profane for harp and strings")


def test_debussy_premiere_rhapsodie_variants_fold():
    main = "Premiere rapsodie"
    assert _same_group("Premiere Rhapsodie", main)
    assert _same_group("Premiere rapsodie for clarinet and orchestra", main)
    assert _same_group("Premiere rhapsodie for clarinet and orchestra", main)


def test_debussy_premiere_rhapsodie_distinct_from_saxophone_rhapsodie():
    # Debussy wrote both Première Rhapsodie (clarinet) and a separate
    # Rhapsodie for saxophone — they must stay split.
    assert not _same_group("Premiere rapsodie",
                           "Rhapsodie for saxophone and orchestra")


def test_debussy_la_mer_subtitle_variants_fold():
    main = "La Mer"
    assert _same_group("La Mer - 3 symphonic sketches for orchestra", main)
    assert _same_group("La mer - three symphonic sketches", main)
    assert _same_group("La Mer - trois esquisses symphoniques", main)


def test_debussy_cathedrale_engloutie_bare_form_folds():
    main = "La cathedrale engloutie - (No 10 from Preludes - Book 1)"
    assert _same_group("La cathédrale engloutie", main)
    assert _same_group("La Cathédrale engloutie - from Préludes Book 1", main)


def test_debussy_estampes_scoring_folds():
    assert _same_group("Estampes for piano", "Estampes")


def test_debussy_jardins_sous_la_pluie_typo_folds():
    # "Puie" is a typo for "pluie".
    assert _same_group("Jardins sous la puie (Estampes, L.100)",
                       "Jardins sous la pluie (Estampes, L.100)")


def test_debussy_images_for_orchestra_variants_fold():
    assert _same_group("3 Images for orchestra", "Images for orchestra")


def test_debussy_images_set_1_distinct_from_set_2():
    # Sibling sets must stay split.
    assert not _same_group("Images - set 1 for piano",
                           "Images - set 2 for piano")


def test_debussy_rondes_de_printemps_variants_fold():
    main = "Rondes de Printemps, from 'Images'"
    assert _same_group("Rondes de Printemps, from 'Images' for Orchestra", main)
    assert _same_group("Rondes de Printemps, 'Images'", main)


def test_debussy_flute_viola_harp_sonata_l137_folds():
    main = "Sonata for Flute, Viola & Harp"
    assert _same_group("Sonata for Flute, Viola & Harp, L. 137", main)
    assert _same_group("Sonata for Flute, Viola & Harp (L.137)", main)


def test_debussy_tarantelle_styrienne_danse_alttitle_folds():
    assert _same_group("Tarantelle styrienne (Danse)",
                       "Tarantelle styrienne")


def test_debussy_clair_de_lune_bergamasque_variants_fold():
    main = "Clair de Lune - from Suite Bergamasque (1890)"
    assert _same_group(
        "Clair de lune (No.3 from Suite bergamesque for piano)", main)
    assert _same_group(
        "Clair de lune (no 3 from Suite bergamasque for piano)", main)
    assert _same_group("Clair de lune (encore)", main)


# --- Mompou audit ---------------------------------------------------------

def test_mompou_damunt_de_tu_bare_form_folds():
    assert _same_group("Damunt de tu, nomes les flors",
                       "Damunt de tu només les flors (Combat del somni)")


def test_mompou_musica_callada_piano_cycle_descriptor_folds():
    assert _same_group("Musica callada, piano cycle",
                       "Música callada")


def test_mompou_canco_i_dansa_no6_distinct_from_no3():
    # Numbered pieces in the Cançó i dansa series stay split.
    assert not _same_group("Cançó i dansa (Song and Dance) No 6",
                           "Canco i dansa no. 3")


# --- Grieg Lyric Pieces audit --------------------------------------------

def test_grieg_notturno_op54_no4_variants_fold():
    # Italian Notturno spelling vs English Nocturne, and two notations
    # for "Op.54 No. 4" / "Op.54'4". All the same piece.
    main = "Nocturne in C from Lyric Suite, Op.54'4"
    assert _same_group("Notturno from Lyric Pieces, Op 54 no 4", main)
    assert _same_group("Nocturne in C from Lyric Suite, Op.54 No. 4", main)


def test_grieg_peer_gynt_suite_no1_bare_form_folds():
    assert _same_group("Peer Gynt, Suite No.1",
                       "Peer Gynt - Suite No 1 Op 46")


def test_grieg_peer_gynt_suite_1_distinct_from_suite_2():
    # Op 46 (Suite 1) vs Op 55 (Suite 2) — distinct works.
    assert not _same_group("Peer Gynt - Suite No 1 Op 46",
                           "Peer Gynt Suite No 2, Op 55")


def test_grieg_slatter_op72_for_piano_folds():
    assert _same_group("Slatter Op.72 for piano",
                       "Slatter Op 72")


# --- Granados audit -------------------------------------------------------

def test_granados_maja_y_el_ruisenor_variants_fold():
    main = "La Maja y el Ruisenor - from Goyescas"
    assert _same_group(
        "Quejas o la maja y el ruisenor (The Maiden and the Nightingale)", main)
    assert _same_group(
        "Quejas o la Maja y el Ruiseñor (from Goyescas)", main)
    assert _same_group(
        "La maja y el ruiseñor (The Maiden and the Nightingale) - from Goyescas",
        main)
    assert _same_group(
        "Quejas o la maja y el ruisenor (The Maiden and the Nightingale) "
        "- from Goyescas: 7 pieces for piano Op 11 No 4", main)


def test_granados_el_pelele_variants_fold():
    main = "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)"
    assert _same_group(
        "El Pelele (excerpt Goyescas: 7 pieces for piano, Op 11, No 7)", main)
    assert _same_group("Goyescas - El Pelele", main)
    assert _same_group("El Pelele, from 'Goyescas'", main)


def test_granados_concert_allegro_op46_translation_folds():
    assert _same_group("Concert Allegro, Op 46",
                       "Allegro de concierto, Op 46")


def test_granados_orientale_op37no2_variants_fold():
    assert _same_group(
        "Orientale Op 37 no 2 from '12 Spanish Dances'",
        "No.2 Oriental in C minor – from Danzas espanolas (Set 1) for piano")


def test_granados_maja_y_el_ruisenor_distinct_from_el_pelele():
    # Both are Goyescas Op 11 movements (No 4 vs No 7); must stay split.
    assert not _same_group(
        "La Maja y el Ruisenor - from Goyescas",
        "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)")


# --- Albéniz audit --------------------------------------------------------

def test_albeniz_asturias_variants_fold():
    main = "Asturias (Suite española, Op 47) (1887)"
    assert _same_group("Asturias Op 47 no 5", main)
    assert _same_group("Asturias, from Suite española, Op.47 (1887)", main)


def test_albeniz_cordoba_variants_fold():
    main = "Cordoba (Nocturne) from Cantos de Espana (Op.232 No.4)"
    assert _same_group(
        "Cordoba from 'Cantos de Espana' for piano, Op 232 no 4", main)
    assert _same_group("Cordoba - from Cantos de Espana (Op.232 No.4)", main)


def test_albeniz_catalunya_sevilla_program_folds():
    assert _same_group(
        "Catalunya; Sevilla, Suite Espanola No 1",
        "Catalunya; Sevilla - from Suite Espanola No 1")


def test_albeniz_suite_espanola_movements_stay_split():
    # Asturias (Op 47 No 5), Cuba (Op 47 No 8), Cádiz are distinct
    # movements of the same suite and must stay split.
    assert not _same_group(
        "Asturias (Suite española, Op 47) (1887)",
        "Cuba (Suite espanola no 1, Op 47 no 8)")
    assert not _same_group(
        "Asturias (Suite española, Op 47) (1887)",
        "Cádiz, from 'Suite española, Op 47' (1887)")


# --- Falla audit ----------------------------------------------------------

def test_falla_noches_en_los_jardines_english_folds():
    main = "Noches en los jardines de Espana"
    assert _same_group("Nights in the Gardens of Spain", main)
    assert _same_group(
        "Noches en los jardines de España (En el Generalife; Danza lejana; "
        "En los jardines de la Sierra de Córdoba)", main)


def test_falla_ritual_fire_dance_variants_fold():
    main = "Ritual Fire Dance"
    assert _same_group("Ritual Fire Dance, from 'El amor brujo'", main)
    assert _same_group("El Amor Brujo, Ritual Fire Dance", main)
    assert _same_group("Danza Ritual del Fuego", main)


def test_falla_siete_canciones_english_folds():
    assert _same_group("Seven Spanish Popular Songs",
                       "Siete canciones populares espanolas")


def test_falla_canciones_arrangements_stay_split():
    # The Maréchal cello/viola arrangement ("Suite populaire espagnole")
    # and the trumpet+piano arrangement are distinct scorings; must NOT
    # fold into the vocal original.
    assert not _same_group("Siete canciones populares espanolas",
                           "Suite populaire espagnole")
    assert not _same_group(
        "Siete canciones populares espanolas",
        "7 Canciones populares espanolas arr. for trumpet and piano")


def test_falla_el_amor_brujo_ballet_variants_fold():
    main = "El amor brujo - ballet-pantomime"
    assert _same_group(
        "El amor brujo (Love, the Magician) - ballet pantomime", main)
    assert _same_group(
        "El amor brujo - ballet pantomime in one act (1920 vers)", main)


def test_falla_el_amor_brujo_suite_stays_split_from_ballet():
    # Falla extracted a Suite from the ballet — distinct work.
    assert not _same_group("El amor brujo - ballet-pantomime",
                           "El Amor brujo (Suite)")


def test_falla_spanish_dance_no1_la_vida_breve_folds():
    assert _same_group(
        "Spanish Dance No.1 (Molto Ritmico) from La Vida Breve",
        "Spanish Dance no 1 from 'La Vida breve'")


def test_falla_danza_del_molinero_english_folds():
    assert _same_group(
        "Danza del Molinero",
        "Dance of the Miller from 'El Sombrero de tres picos'")


def test_falla_molinero_distinct_from_molinera():
    # The Miller's Dance (Farruca) and the Miller's Wife's Dance (Fandango)
    # are different dances from the same ballet.
    assert not _same_group(
        "Dance of the Miller from 'El Sombrero de tres picos'",
        "Fandango (Molinera Dance) from 'El Sombrero de tres picos'")


# --- Turina audit ---------------------------------------------------------

def test_turina_oracion_del_torero_bare_form_folds():
    assert _same_group("La Oración del Torero",
                       "La Oración del Torero, Op 34")


# --- Ravel audit ----------------------------------------------------------

def test_ravel_gaspard_de_la_nuit_for_piano_folds():
    assert _same_group("Gaspard de la nuit for piano",
                       "Gaspard de la nuit")


def test_ravel_alborada_del_gracioso_variants_fold():
    main = "Alborada del gracioso 'Miroirs' (1905)"
    assert _same_group("Alborada del gracioso - from the suite 'Miroirs' (1905)",
                       main)
    assert _same_group("Alborada del gracioso", main)


def test_ravel_une_barque_sur_locean_parent_set_folds():
    assert _same_group("Une Barque sur l'ocean (no 3 from Miroirs)",
                       "Une Barque sur l'ocean")


def test_ravel_violin_sonata_word_order_folds():
    assert _same_group("Sonata for violin and piano in G major",
                       "Violin Sonata in G major")


def test_ravel_ma_mere_loye_ballet_variants_fold():
    assert _same_group("Ma Mere l'Oye (Mother Goose) - ballet",
                       "Ma Mere l'Oye - ballet")


def test_ravel_tzigane_violin_piano_variants_fold():
    main = "Tzigane"
    assert _same_group("Tzigane - rapsodie de concert for violin and piano", main)
    assert _same_group("Tzigane - rapsodie de concert pour violon et piano", main)


def test_ravel_tzigane_violin_piano_distinct_from_orchestra_arrangement():
    # Different scoring stays split.
    assert not _same_group(
        "Tzigane",
        "Tzigane - rapsodie de concert arr. for violin & orchestra")


def test_ravel_string_quartet_op35_bbc_mislabel_folds():
    # BBC sometimes mistags as "Op 35" (likely a confusion with M.35).
    assert _same_group("String Quartet in F major, Op 35",
                       "String Quartet in F major")


def test_ravel_la_valse_choreographic_poem_subtitle_folds():
    assert _same_group("La Valse - choreographic poem for orchestra",
                       "La Valse")


# --- Poulenc audit --------------------------------------------------------

def test_poulenc_oboe_sonata_word_order_folds():
    assert _same_group("Sonata for oboe and piano (1962)",
                       "Oboe Sonata")


def test_poulenc_concerto_for_two_pianos_variants_fold():
    main = "Concerto in D minor for 2 pianos and orchestra"
    assert _same_group("Concerto for Two Pianos in D minor, FP 61", main)
    assert _same_group("Concerto in D minor for 2 pianos", main)


def test_poulenc_sinfonietta_variants_fold():
    main = "Sinfonietta for orchestra"
    assert _same_group("Sinfonietta, FP 141", main)
    assert _same_group("Sinfonietta", main)


def test_poulenc_organ_concerto_variants_fold():
    main = "Concerto for Organ, Timpani and Strings in G minor, FP 93"
    assert _same_group("Concerto for organ, strings and timpani", main)
    assert _same_group("Concerto for Organ, Timpani and Strings in G minor, FP.93",
                       main)


def test_poulenc_sept_chansons_numeric_form_folds():
    assert _same_group("7 chansons, for mixed choir a cappella (1936)",
                       "Sept chansons")


def test_poulenc_petites_voix_bare_form_folds():
    assert _same_group("Petites voix",
                       "Petites voix pour voix egales a capella")


def test_poulenc_capriccio_bal_masque_variants_fold():
    main = "Capriccio for Two Pianos"
    assert _same_group("Capriccio (excerpt Finale of 'Bal masque')", main)
    assert _same_group(
        "Capriccio - after Finale of cantata 'Le Bal masqué' vers. for 2 pianos",
        main)


def test_poulenc_chemins_de_lamour_valse_chantee_folds():
    assert _same_group("Les Chemins de l'amour (valse chantée for voice and piano)",
                       "Les Chemins de l'amour")


def test_poulenc_sextet_word_order_folds():
    assert _same_group("Sextet for Piano and Wind Quintet",
                       "Sextet for piano and winds")


# --- Saint-Saëns audit (via ttn_audit_composer) ---------------------------

def test_saintsaens_bassoon_sonata_op168_folds():
    assert _same_group("Sonata for bassoon and piano (Op.168) in G major",
                       "Bassoon Sonata in G major, Op 168")


def test_saintsaens_havanaise_op83_variants_fold():
    main = "Havanaise, Op 83"
    assert _same_group("Havanaise for violin and orchestra, Op 83", main)
    assert _same_group("Havanaise For Violin and Orchestra in F, op. 83",
                       main)


def test_saintsaens_introduction_rondo_capriccioso_variants_fold():
    main = "Introduction and rondo capriccioso (Op.28), arr. for violin & piano"
    assert _same_group(
        "Introduction and rondo capriccioso for violin and orchestra, Op 28",
        main)
    assert _same_group(
        "Introduction and Rondo capriccioso in A minor, Op 28", main)


def test_saintsaens_cello_concerto_1_word_order_folds():
    assert _same_group(
        "Concerto for cello and orchestra No 1 in A minor Op 33",
        "Cello Concerto No 1 in A minor, Op 33")


def test_saintsaens_danse_macabre_symphonic_poem_variant_folds():
    assert _same_group("Danse macabre - symphonic poem (Op.40)",
                       "Danse macabre, Op 40")


def test_saintsaens_organ_symphony_subtitle_variant_folds():
    assert _same_group("Symphony no.3 in C minor, Op.78 'Organ'",
                       "Symphony No.3 in C minor Op.78 \"Organ Symphony\"")


def test_saintsaens_etude_op52no6_bare_form_folds():
    assert _same_group("Etude in D flat (Op.52 No.6)",
                       "Etude in D flat, Op 52, No 6 (Etude en forme de valse)")


def test_saintsaens_le_cygne_variants_fold():
    main = "Le Cygne (The Swan) from 'Le Carnaval des Animaux'"
    assert _same_group("The Swan, from 'The Carnival of the Animals'", main)
    assert _same_group(
        "Le Cygne (The Swan), from 'The Carnival of the Animals'", main)
    assert _same_group(
        "Le Cygne (The Swan) (excerpt The Carnival des Animaux)", main)


def test_saintsaens_mon_coeur_arrangements_stay_split():
    # The trumpet+orchestra arrangement is a distinct scoring from the
    # vocal aria original. Same piece, different scoring → stay split.
    assert not _same_group(
        "Mon coeur s'ouvre from 'Samson et Dalila' (arr for trumpet & orchestra)",
        "Dalila's aria: 'Mon coeur s'ouvre' (from \"Samson et Dalila\", Act 2 Scene 3)")


# --- Robert Schumann audit (via ttn_audit_composer) -----------------------

def test_schumann_abegg_variations_op1_variants_fold():
    main = "Abegg variations Op.1 for piano"
    assert _same_group("Abegg Variations, Op 1", main)
    assert _same_group("Theme and variations on the Name \"Abegg\", Op 1", main)


def test_schumann_adagio_allegro_op70_variants_fold():
    main = "Adagio and allegro in A flat major, Op 70"
    assert _same_group("Adagio and allegro, Op 70", main)
    assert _same_group("Adagio and allegro for horn and piano Op 70 in A flat major", main)
    assert _same_group("Adagio and allegro in A flat (Op.70), for horn or other and piano", main)


def test_schumann_arabeske_op18_variants_fold():
    main = "Arabeske for piano in C major, Op 18"
    assert _same_group("Arabeske in C major, Op 18", main)
    assert _same_group("Arabesque in C major (Op.18)", main)


def test_schumann_dichterliebe_full_cycle_variants_fold():
    main = "Dichterliebe for voice and piano, Op 48"
    assert _same_group("Dichterliebe (Op.48) (song cycle)", main)
    assert _same_group("Dichterliebe, Op 48 - song-cycle for voice and piano", main)
    assert _same_group("Dichterliebe, Op 48", main)


def test_schumann_dichterliebe_song_excerpts_stay_split():
    # Single-song excerpts from Dichterliebe are not the full cycle.
    assert not _same_group(
        "Hor' ich das Liedchen klingen - from Dichterliebe Op 48 No 10",
        "Dichterliebe for voice and piano, Op 48")


def test_schumann_manfred_overture_op115_variants_fold():
    main = "Overture (Manfred, Op 115)"
    assert _same_group("Manfred - Overture to the Incidental Music (Op.115)", main)
    assert _same_group("Manfred - incidental music Op 115 (Overture)", main)
    assert _same_group("Overture to Manfred, Op 115", main)
    assert _same_group("Overture to 'Manfred', Op 115, after Byron", main)


def test_schumann_symphonische_etuden_op13_variants_fold():
    main = "Symphonische Etuden for piano, Op 13"
    assert _same_group("Symphonische Etuden, Op.13", main)
    assert _same_group("Etudes en formes de variations, Op 13", main)
    assert _same_group("Etudes en formes de variations Op.13 for piano", main)


def test_schumann_string_quartet_3_op41no3_word_order_folds():
    main = "String Quartet in A major, Op 41 no 3"
    assert _same_group("Quartet for strings in A major (Op.41 No.3)", main)
    assert _same_group("String Quartet no 3 in A, op 41 no 3", main)


def test_schumann_string_quartet_1_distinct_from_3():
    # Op 41 No 1 and No 3 are different works; must stay split.
    assert not _same_group(
        "String Quartet no 1 in A minor, Op 41 no 1",
        "String Quartet in A major, Op 41 no 3")


def test_schumann_manfred_op115_variants_fold_extras():
    # Additional folds: piano sonata 1, violin fantasy, piano trio 1.
    assert _same_group("Sonata no. 1 in F sharp minor Op.11 for piano",
                       "Piano Sonata no 1 in F sharp minor, Op 11")
    assert _same_group("Violin Fantasy in C major, Op 131",
                       "Fantasy for violin and orchestra in C major, Op 131")
    assert _same_group("Piano Trio in D minor (Op.63)",
                       "Piano Trio No.1 in D minor (Op.63)")


def test_schumann_marchenbilder_op113_scoring_folds():
    assert _same_group("Marchenbilder for viola and piano, Op 113",
                       "Marchenbilder, Op 113")


def test_schumann_faschingsschwank_subtitle_folds():
    assert _same_group("Faschingsschwank aus Wien - Phantasiebilder, Op 26",
                       "Faschingsschwank aus Wien, Op 26")


def test_schumann_toccata_op7_word_order_folds():
    assert _same_group("Toccata for piano (Op.7) in C major",
                       "Toccata in C major, Op 7")


def test_schumann_clara_wieck_variations_parent_context_folds():
    assert _same_group(
        "Variations on a Theme by Clara Wieck (from Schumann's Piano Sonata No 3 in F minor, Op 14)",
        "Variations on a Theme by Clara Wieck")


def test_schumann_symphony_4_1841_original_version_folds():
    # The 1841 original version variants fold together. The 1851 published
    # version stays split from the 1841 original — Schumann revised it
    # heavily and the two are musically distinct.
    assert _same_group(
        "Symphony No. 4 in D minor, op. 120 (original version, 1841)",
        "Symphony No.4 in D minor (Op.120), version original (1841)")
    assert not _same_group(
        "Symphony No.4 in D minor (Op.120), version original (1841)",
        "Symphony No. 4 in D minor, op. 120 (published version 1851)")


def test_schumann_humoreske_op20_bare_form_folds():
    assert _same_group("Humoreske in B flat major, Op.20",
                       "Humoreske for piano in B flat major Op 20")


def test_schumann_kinderszenen_traumerei_excerpts_fold_together():
    # Within the excerpt-group (NOT into the whole work), all Träumerei
    # variants collapse.
    main = "Träumerei, from Kinderszenen, Op.15"
    assert _same_group("Traumerei (Kinderszenen, Op 15 no 7)", main)
    assert _same_group("Traumerei (Kinderszenen, Op 15)", main)
    assert _same_group("Träumerei – from Kinderszenen for piano (Op.15)", main)


def test_schumann_kinderszenen_traumerei_excerpt_distinct_from_whole():
    # Excerpt vs whole work must stay split.
    assert not _same_group(
        "Träumerei, from Kinderszenen, Op.15",
        "Kinderszenen for piano (Op.15)")


def test_schumann_op94_three_romances_word_order_folds():
    assert _same_group("Three Romances for Oboe and Piano, op. 94",
                       "Three Romances Op 94")


# --- Fauré audit (via ttn_audit_composer) ---------------------------------

def test_faure_pavane_op50_tempo_marking_folds():
    assert _same_group("Pavane (Andante molto moderato) in F minor Op 50",
                       "Pavane for orchestra Op 50")


def test_faure_nocturne_6_op63_scoring_folds():
    assert _same_group("Nocturne No 6 in D flat major, Op 63",
                       "Nocturne for piano no 6 in D flat major, Op 63")


def test_faure_elegie_op24_variants_fold():
    main = "Elegy, Op 24"
    assert _same_group("Elegie (Op.24) arr. for cello and orchestra", main)
    assert _same_group("Elegy for cello and piano (Op.24)", main)


def test_faure_pelleas_suite_word_order_folds():
    assert _same_group("Suite from 'Pelléas et Mélisande', Op.80",
                       "Pelleas et Melisande suite, Op 80")


def test_faure_piano_trio_op120_date_variant_folds():
    assert _same_group("Piano Trio in D minor, Op 120",
                       "Trio for piano and strings (Op.120) in D minor (1923)")


def test_faure_dolly_suite_op56_bare_form_folds():
    assert _same_group("Dolly Suite, op. 56",
                       "Dolly - Suite for piano duet Op.56")


def test_faure_op33_nocturnes_stay_split():
    # Op 33 contains three distinct nocturnes (Nos 1, 2, 3). The tool
    # flagged them as sharing Op 33 — false positive; sibling pieces.
    assert not _same_group("Nocturne for piano in E flat minor, Op 33 no 1",
                           "Nocturne in B major Op 33 No 2")
    assert not _same_group("Nocturne in B major Op 33 No 2",
                           "Nocturne in A flat major (Op.33 No.3)")


# --- Brahms audit (via ttn_audit_composer) -------------------------------

def test_brahms_clarinet_quintet_op115_word_order_folds():
    assert _same_group("Quintet for clarinet and strings in B minor, Op 115",
                       "Clarinet Quintet in B minor, Op 115")


def test_brahms_handel_variations_op24_variants_fold():
    main = "25 Variations and fugue on a theme by G F Handel, Op 24"
    assert _same_group(
        "25 Variations and fugue on a theme by G F Handel for piano, Op 24",
        main)
    assert _same_group(
        "25 variations and fugue on a theme by G.F. Handel for piano (Op.24)",
        main)
    assert _same_group("Variations and Fugue on a Theme by Handel, Op 24", main)


def test_brahms_rhapsody_no1_bare_form_folds():
    assert _same_group("Rhapsody in B minor Op.79 No.1",
                       "Rhapsody for piano in B minor, Op 79 No 1")


def test_brahms_rhapsody_op79_no1_distinct_from_no2():
    # Op 79 contains two distinct rhapsodies; sibling pieces stay split.
    assert not _same_group("Rhapsody for piano in B minor, Op 79 No 1",
                           "Rhapsody in G minor, Op 79 no 2")


def test_brahms_gestillte_sehnsucht_op91no1_variants_fold():
    main = "Gestillte Sehnsucht for alto, viola and piano Op 91 No 1"
    assert _same_group("Gestillte Sehnsucht Op 91 no 1", main)
    assert _same_group(
        "Gestillte Sehnsucht - song for alto, viola and piano, Op.91 No.1",
        main)


def test_brahms_op91_two_songs_stay_split():
    # Op 91 contains two songs (Gestillte Sehnsucht and Geistliches
    # Wiegenlied). Distinct pieces.
    assert not _same_group("Gestillte Sehnsucht Op 91 no 1",
                           "Geistliches Wiegenlied Op 91 no 2")


def test_brahms_op118_no2_intermezzo_slash_notation_folds():
    main = "Intermezzo in A major, Op 118 no 2"
    assert _same_group("Intermezzo, op. 118/2", main)
    assert _same_group("Intermezzo in A, op. 118/2", main)


def test_brahms_op118_sibling_intermezzi_stay_split():
    # Op 118 contains six pieces; Intermezzi Nos 1, 2, 6 are distinct.
    assert not _same_group("Intermezzo in A major, Op 118 no 2",
                           "Intermezzo in A minor, Op 118 No 1")
    assert not _same_group("Intermezzo in A major, Op 118 no 2",
                           "Intermezzo in E flat minor (Op.118 No.6)")


def test_brahms_double_concerto_op102_variants_fold():
    main = "Double Concerto in A minor for Violin and Cello, Op 102"
    assert _same_group(
        "Concerto for violin, cello and orchestra in A minor, Op.102", main)
    assert _same_group("Double Concerto in A minor, Op 102", main)
    assert _same_group(
        "Concerto in A minor for violin and cello, Op 102", main)


def test_brahms_piano_quintet_op34_variants_fold():
    main = "Piano Quintet in F minor, Op 34"
    assert _same_group("Quintet in F minor Op.34 for piano and strings", main)
    # Bare "Quintet in F minor Op 34" — title-key shared with Franck's
    # Piano Quintet (also F minor, no Op number); composer-scoped
    # grouping isolates the merges.
    assert _same_group("Quintet in F minor Op 34", main)


def test_brahms_cello_sonata_no1_op38_variants_fold():
    main = "Cello Sonata no 1 in E minor, Op 38"
    assert _same_group("Cello Sonata in E minor, Op 38", main)
    assert _same_group("Sonata for Cello and piano No.1 (Op.38) in E minor",
                       main)


def test_brahms_gesang_der_parzen_op89_variants_fold():
    main = "Gesang der Parzen (Song of the Fates), Op 89"
    assert _same_group("Gesang der Parzen  Op 89 for chorus and orchestra",
                       main)
    assert _same_group(
        "Gesang der Parzen (Song of the Fates) for chorus and orchestra (Op.89)",
        main)
    assert _same_group("Gesang der Parzen, Op.89", main)


def test_brahms_op17_four_songs_spelled_out_folds():
    assert _same_group("Four Songs, Op 17",
                       "4 Songs for women's voices, 2 horns and harp, Op 17")


def test_brahms_violin_concerto_op77_word_order_folds():
    assert _same_group("Concerto for violin and orchestra (Op.77) in D major",
                       "Violin Concerto in D major, Op 77")


def test_brahms_piano_trio_op101_variants_fold():
    main = "Piano Trio No 3 in C minor, Op 101"
    assert _same_group("Trio for piano and strings No.3 in C minor (Op.101)",
                       main)
    assert _same_group("Piano Trio in C minor, op. 101", main)


def test_brahms_op76_eight_piano_pieces_variants_fold():
    main = "8 Pieces for Piano, Op 76"
    assert _same_group("Eight Piano Pieces (Op.76)", main)
    assert _same_group("8 Piano Pieces, Op.76", main)


# --- Franck audit (via ttn_audit_composer) --------------------------------

def test_franck_violin_sonata_word_order_folds():
    assert _same_group("Sonata for violin and piano (M.8) in A major",
                       "Violin Sonata in A major, M.8")


def test_franck_prelude_fugue_variation_variants_fold():
    main = "Prelude, fugue and variation for organ in B minor (M.30)"
    assert _same_group("Prelude, fugue et variation for organ (M.30) (Op.18)",
                       main)
    assert _same_group("Prelude, Fugue et Variation Op 18", main)
    assert _same_group("Prelude, fugue and variation, Op.18", main)


def test_franck_cantabile_m36_bare_form_folds():
    assert _same_group(
        "Cantabile in B major, M.36",
        "Cantabile in B major (M.36), no 2 from 3 Pieces pour grand orgue (M.35-37)")


def test_franck_piano_quintet_m7_folds_with_brahms_op34_via_composer_scoping():
    # Franck's Piano Quintet M.7 chains via the same key as Brahms' Op 34;
    # composer-scoping keeps the two composers' groups separate.
    assert _same_group("Quintet for piano and strings (M.7) in F minor",
                       "Piano Quintet in F minor, Op 34")


# --- Bartók audit (via ttn_audit_composer) --------------------------------

def test_bartok_sz40_string_quartet_1_key_sig_folds():
    assert _same_group("String Quartet No. 1 in A minor, Sz. 40",
                       "Quartet for strings no. 1 (Sz.40)")


def test_bartok_sz106_music_for_strings_percussion_celesta_folds():
    assert _same_group("Music for strings, percussion and celesta, Sz.106",
                       "Music for Strings, Percussion and Celesta")


def test_bartok_sz93_hungarian_folk_songs_variants_fold():
    main = "4 Hungarian folk songs for chorus, Sz 93, 1930"
    assert _same_group("4 Hungarian folk songs for chorus, Sz.93", main)
    assert _same_group("Hungarian Folksongs (Magyar népdalok), Sz. 93", main)


def test_bartok_sz95_piano_concerto_2_bare_key_sig_folds():
    assert _same_group("Piano Concerto No 2 (Sz.95)",
                       "Piano Concerto No. 2 in G, Sz. 95")


# --- Tchaikovsky audit (via ttn_audit_composer) ---------------------------

def test_tchaikovsky_romeo_and_juliet_variants_fold():
    main = "Romeo and Juliet - fantasy overture"
    assert _same_group("Romeo and Juliet fantasy overture (1880 version)", main)
    assert _same_group("Romeo and Juliet, fantasy overture after Shakespeare",
                       main)
    assert _same_group("Romeo and Juliet - fantasy overture vers. standard",
                       main)


def test_tchaikovsky_rococo_variations_op33_variants_fold():
    main = "Variations on a rococo theme for cello and String orchestra, Op 33"
    assert _same_group("Variations on a Rococo Theme, Op.33", main)
    assert _same_group(
        "Variations on a rococo theme in A for cello and orchestra, Op 33",
        main)
    assert _same_group(
        "Variations on a Roccoco Theme, Op 33, for cello and orchestra", main)


def test_tchaikovsky_rococo_original_version_stays_split():
    # The Tchaikovsky-autograph "original version" is musically distinct
    # from the Fitzenhagen-edited standard version that's normally played.
    assert not _same_group(
        "Variations on a rococo theme for cello and String orchestra, Op 33",
        "Variations on a Rococo Theme for cello and orchestra, Op 33 (original version)")


def test_tchaikovsky_string_quartet_1_op11_word_order_folds():
    assert _same_group("Quartet for strings No 1 in D major Op 11",
                       "String Quartet no 1 in D major, Op 11")


def test_tchaikovsky_andante_cantabile_excerpt_stays_split():
    # Excerpt (slow movement) vs whole work — stay split.
    assert not _same_group("Andante Cantabile (String Quartet, Op 11)",
                           "String Quartet no 1 in D major, Op 11")


def test_tchaikovsky_mozartiana_op61_variants_fold():
    main = "Suite No.4 in G major, Op 61, 'Mozartiana'"
    assert _same_group("Suite No.4 in G major for orchestra (Op.61), 'Mozartiana'",
                       main)
    assert _same_group("Suite No.4, Op.61, 'Mozartiana'", main)


def test_tchaikovsky_serenade_for_strings_op48_variants_fold():
    main = "Serenade for string orchestra in C major Op.48"
    assert _same_group("Serenade in C major for strings (Op.48)", main)
    assert _same_group("Serenade in C, op. 48", main)


def test_tchaikovsky_tempest_op18_russian_english_variants_fold():
    main = "The Tempest (Burya) - symphonic fantasia Op 18"
    assert _same_group("Burya  - symphonic fantasia after Shakespeare, Op 18",
                       main)
    assert _same_group(
        "Burya (The Tempest) - symphonic fantasia after Shakespeare (Op.18)",
        main)
    assert _same_group("The Tempest, op. 18, fantasy after Shakespeare", main)


def test_tchaikovsky_dumka_op59_scoring_folds():
    assert _same_group("Dumka - Russian rustic scene for piano (Op.59)",
                       "Dumka, Op 59 'Russian rustic scene'")


def test_tchaikovsky_voyevoda_op78_russian_german_folds():
    main = "Voyevoda - Symphonic Ballad Op 78"
    assert _same_group("Wojewode, symphonic ballad, Op 78", main)
    assert _same_group("The Voyevoda, symphonic ballad (Op.78)", main)


def test_tchaikovsky_waltz_of_the_flowers_word_order_folds():
    assert _same_group("The Nutcracker: Waltz of the Flowers",
                       "Waltz of the Flowers (from The Nutcracker)")


def test_tchaikovsky_eugene_onegin_intro_waltz_variants_fold():
    main = "Eugene Onegin, Op 24 (Act 2: Introduction & waltz)"
    assert _same_group("Eugene Onegin, Op 24 (Introduction & waltz)", main)
    assert _same_group(
        "Introduction and waltz from 'Eugene Onegin' - lyric scenes in 3 acts (Op.24)",
        main)


def test_tchaikovsky_souvenir_florence_mvt_mvmt_typo_folds():
    assert _same_group(
        "Souvenir de Florence (4th mvmt, 'Allegro vivace') Op 70",
        "Souvenir de Florence (4th mvt, 'Allegro vivace') Op 70")


# --- Dvořák audit (via ttn_audit_composer) --------------------------------

def test_dvorak_slavonic_dance_op72_no2_variants_fold():
    # Op 72 No 2 = No 10 of the complete set of 16. Multiple numbering
    # variants and the 'Starodávny' nickname all fold.
    main = "Slavonic Dance in E minor, Op.72 no.2"
    assert _same_group("Slavonic Dance no 10 in E minor Op 72 no 2", main)
    assert _same_group(
        "Slavonic Dance No 10 in E minor, Op 72 no 2, 'Starodavny'", main)
    assert _same_group(
        "Slavonic dance no 10 in E minor for piano duet, Op 72 no 2", main)


def test_dvorak_slavonic_dance_op72_no4_variants_fold():
    main = "Slavonic Dance No 12 in D flat major Op 72 No 4"
    assert _same_group("Slavonic Dance No 12 in D flat major Op 72'4", main)
    assert _same_group(
        "Slavonic Dance No.12 (Op.72 No.4) in D flat major for piano duet",
        main)


def test_dvorak_slavonic_dance_op46_no2_bare_form_folds():
    assert _same_group("Slavonic Dance (Op.46 No.2)",
                       "Slavonic Dance in E minor, Op 46 no 2")


def test_dvorak_slavonic_dance_op46_no8_orch_variant_folds():
    assert _same_group(
        "Slavonic Dance in G minor, Op 46 No 8, orch composer (orig for pf duet)",
        "Slavonic Dance No. 8 in G minor, op. 46")


def test_dvorak_slavonic_dance_op46_no2_distinct_from_no8():
    # Sibling dances within Op 46 stay split.
    assert not _same_group("Slavonic Dance in E minor, Op 46 no 2",
                           "Slavonic Dance No. 8 in G minor, op. 46")


def test_dvorak_piano_quintet_op81_variants_fold():
    main = "Piano Quintet in A major, Op 81"
    assert _same_group("Piano Quintet no 2 in A major, Op 81", main)
    assert _same_group("Quintet no. 2 in A major Op.81 for piano and strings",
                       main)


def test_dvorak_cello_concerto_op104_variants_fold():
    main = "Cello Concerto in B minor, Op 104"
    assert _same_group(
        "Concerto for cello and orchestra no.2 (Op.104) in B minor", main)
    assert _same_group(
        "Concerto for cello and orchestra in B minor, Op 104", main)


def test_dvorak_wind_serenade_op44_variants_fold():
    main = "Wind Serenade in D minor, Op 44"
    assert _same_group("Serenade for wind instruments in D minor Op 44", main)
    assert _same_group("Serenade for winds in D minor, Op.44", main)
    assert _same_group("Serenade in D minor, op. 44", main)


def test_dvorak_dumky_trio_op90_variants_fold():
    main = "Piano Trio no 4 in E minor, Op 90 'Dumky'"
    assert _same_group("Trio in E minor, \"Dumky\" Op 90", main)
    assert _same_group("Trio for piano and strings no 4, Op 90 \"Dumky\"",
                       main)
    assert _same_group("Piano Trio in E minor 'Dumky', Op 90", main)


def test_dvorak_song_to_the_moon_bare_form_folds():
    assert _same_group("Song to the Moon from Rusalka",
                       "Song to the Moon from Rusalka, Op 114")


def test_dvorak_romance_op11_variants_fold():
    main = "Romance Op 11 in F minor vers. for violin and piano"
    assert _same_group("Romance for violin and orchestra in F minor, Op 11",
                       main)
    assert _same_group("Romance in F minor, Op 11", main)


def test_dvorak_legend_op59_no4_variants_fold():
    main = "Legend in C major, Op 59 no 4"
    assert _same_group(
        "From \"Legends\" Op 59 No 4 (Molto maestoso) in C major", main)
    assert _same_group("Legend in C major (Molto maestoso) (Op.59 No.4)",
                       main)


def test_dvorak_string_serenade_op22_variants_fold():
    main = "Serenade for strings in E major, Op.22"
    assert _same_group("String Serenade in E, op. 22", main)
    assert _same_group(
        "Serenade for String Orchestra in E major, Op.22, B.52", main)


def test_dvorak_piano_trio_3_op65_word_order_folds():
    assert _same_group("Trio for piano and strings no 3 in F minor, Op 65",
                       "Piano Trio no 3 in F minor, Op 65")


def test_dvorak_piano_trio_1_op21_word_order_folds():
    assert _same_group(
        "Trio for piano and strings No.1 (Op.21) in B flat major",
        "Piano Trio No 1 in B flat major, Op 21")


def test_dvorak_op75_romantic_pieces_spelled_out_folds():
    assert _same_group("Four Romantic Pieces, op. 75",
                       "4 Romantic pieces, Op 75")


def test_dvorak_in_natures_realm_op91_subtitle_folds():
    assert _same_group("In Nature's Realm, op. 91, concert overture",
                       "In Nature's Realm (Overture), Op 91")


# --- Rachmaninov audit (via ttn_audit_composer) ---------------------------

def test_rachmaninov_vocalise_variants_fold():
    main = "Vocalise (Op.34 No.14)"
    assert _same_group("Vocalise, Op 34 No 14 for orchestra", main)
    assert _same_group("Vocalise, Op.34'14", main)


def test_rachmaninov_the_bells_op35_variants_fold():
    main = "The Bells (Kolokola) for soloists, chorus and orchestra, Op 35"
    assert _same_group(
        "The Bells - poem for soloists, mixed choir and symphony orchestra (Op.35)",
        main)
    assert _same_group("The Bells, op. 35, choral symphony", main)


def test_rachmaninov_corelli_variations_op42_scoring_folds():
    assert _same_group("Variations on a theme of Corelli for piano (Op.42)",
                       "Variations on a Theme of Corelli, Op 42")


def test_rachmaninov_paganini_rhapsody_op43_scoring_folds():
    assert _same_group(
        "Rhapsody on a theme of Paganini Op.43 for piano and orchestra",
        "Rhapsody on a Theme of Paganini, Op 43")


def test_rachmaninov_suite_no2_op17_bare_form_folds():
    assert _same_group("Suite No 2 Op 17",
                       "Suite no 2 for 2 pianos, Op 17")


def test_rachmaninov_cello_sonata_op19_variants_fold():
    assert _same_group("Cello Sonata in G minor, op. 19",
                       "Sonata for cello and piano in G minor (Op.19)")
    # Andante excerpt variants fold together within the excerpt group.
    assert _same_group("Andante from Cello Sonata in G minor, Op 19",
                       "Cello Sonata in G minor Op 19 (Andante)")


def test_rachmaninov_cello_sonata_excerpt_stays_split_from_whole():
    assert not _same_group("Cello Sonata in G minor Op 19 (Andante)",
                           "Sonata for cello and piano in G minor (Op.19)")


def test_rachmaninov_op11_six_duets_variants_fold():
    main = "6 Duets Op 11 for piano 4 hands"
    assert _same_group("Pieces for four hands (Op.11)", main)
    assert _same_group("Six Pieces for four hands, Op 11", main)


def test_rachmaninov_vespers_op37_bare_form_folds():
    assert _same_group("Vespers (All-Night Vigil), Op 37",
                       "Vespers (All-night vigil) for chorus (Op.37)")


def test_rachmaninov_piano_concerto_4_op40_word_order_folds():
    assert _same_group(
        "Concerto for piano and orchestra no.4 (Op.40) in G minor",
        "Piano Concerto No 4 in G minor, Op 40")


def test_rachmaninov_chopin_variations_op22_scoring_folds():
    assert _same_group("Variations on a theme of Chopin, Op 22",
                       "Variations on a theme of Chopin, Op 22 for piano")


def test_rachmaninov_piano_sonata_2_op36_word_order_folds():
    assert _same_group("Sonata No.2 in B flat Minor (Op.36)",
                       "Piano Sonata No. 2 in B flat minor, op. 36")


def test_rachmaninov_caprice_bohemien_op12_subtitle_folds():
    assert _same_group("Caprice bohémien, Op 12 (Capriccio on Gypsy Themes)",
                       "Caprice Bohemien, Op 12")


def test_rachmaninov_2_songs_two_spelled_out_folds():
    assert _same_group(
        "Two Songs: When night descends in silence ; Oh, stop thy singing, maiden fair",
        "2 Songs: When Night Descends in silence; Oh stop thy singing maiden fair")


def test_rachmaninov_etudes_tableaux_op39_excerpts_program_folds():
    assert _same_group(
        "Etudes-Tableaux (Op.39) (I to VI only)",
        "Etudes-Tableaux, Op 39 (excerpts - I to VI)")


# --- Prokofiev audit (via ttn_audit_composer) -----------------------------

def test_prokofiev_violin_concerto_2_op63_bare_form_folds():
    assert _same_group("Violin Concerto No 2, Op 63",
                       "Violin Concerto No 2 in G minor, Op 63")


def test_prokofiev_lieutenant_kije_op60_word_order_folds():
    assert _same_group("Lieutenant Kije Suite, Op.60",
                       "Lieutenant Kije - suite for orchestra, Op 60")


def test_prokofiev_piano_sonata_7_op83_word_order_folds():
    assert _same_group("Piano Sonata No 7 in B flat, Op 83",
                       "Sonata for piano no 7 in B flat major, Op 83")


def test_prokofiev_violin_sonata_2_op94a_op94bis_fold():
    # Op 94a and Op 94bis are both valid catalogue notations for
    # Prokofiev's own violin arrangement of his Op 94 flute sonata.
    assert _same_group("Violin Sonata No. 2 in D, op. 94a",
                       "Sonata for violin and piano no. 2 (Op.94bis) in D major")


def test_prokofiev_op94_flute_vs_op94bis_violin_stay_split():
    # The flute original and the violin arrangement are distinct
    # scorings — different works in the catalogue.
    assert not _same_group(
        "Flute Sonata in D major, Op.94",
        "Sonata for violin and piano no. 2 (Op.94bis) in D major")


def test_prokofiev_symphony_5_op100_bare_form_folds():
    assert _same_group("Symphony No.5 (Op.100)",
                       "Symphony No. 5 in B flat, op. 100")


def test_prokofiev_violin_sonata_1_op80_word_order_folds():
    assert _same_group("Sonata no. 1 in F minor Op.80 for violin and piano",
                       "Violin Sonata no 1 in F minor, Op 80")


def test_prokofiev_op12_no7_prelude_bare_form_folds():
    assert _same_group(
        "Prelude Op.12 No.7",
        "Prelude - No. 7 from 10 Pieces for piano (Op.12)")


def test_prokofiev_classical_symphony_gavotte_excerpt_stays_split():
    # Gavotte 2nd movement excerpt vs whole symphony.
    assert not _same_group(
        "Gavotte from Symphony no.1 in D major, Op. 25 'Classical'",
        "Symphony No 1 in D major, Op 25, 'Classical'")


# --- Janáček audit (via ttn_audit_composer) -------------------------------

def test_janacek_taras_bulba_bare_form_folds():
    assert _same_group("Taras Bulba - Rhapsody",
                       "Taras Bulba - rhapsody for orchestra")


def test_janacek_pohadka_variants_fold():
    main = "Pohádka (Fairy Tale)"
    assert _same_group("Pohadka", main)
    assert _same_group("Pohadka for cello and piano", main)
    assert _same_group("Pohadka (Fairy tale) for cello and piano", main)


def test_janacek_fiddlers_child_orchestral_variant_folds():
    assert _same_group(
        "The fiddler's child (Sumarovo dite) - ballad for orchestra",
        "Sumarovo dite (The Fiddler's Child)")


def test_janacek_kreutzer_sonata_string_orchestra_arr_stays_split():
    # The string-orchestra arrangement of String Quartet 1 is a distinct
    # scoring; stays split per existing policy.
    assert not _same_group(
        "String Quartet No 1 'The Kreutzer Sonata'",
        "String Quartet no.1 (Kreutzer Sonata) arr for string orchestra")


# --- Sibelius audit (via ttn_audit_composer) -----------------------------

def test_sibelius_pohjolas_daughter_op49_bare_form_folds():
    assert _same_group("Pohjola's Daughter, Op 49",
                       "Pohjola's daughter - symphonic fantasia, Op 49")


def test_sibelius_karelia_ballad_op11_word_order_folds():
    assert _same_group("Ballad from Karelia suite, Op 11",
                       "Ballad (Karelia suite, Op 11)")


def test_sibelius_tapiola_op112_subtitle_variants_fold():
    main = "Tapiola, Op 112"
    assert _same_group("Tapiola - symphonic poem, Op. 112 (1926)", main)
    assert _same_group("Tapiola - tone poem Op.112", main)


def test_sibelius_lemminkainen_return_parent_set_variant_folds():
    assert _same_group(
        "Lemminkainen's Return - No.4 from Lemminkainen Suite, Op.22",
        "Lemminkainen's Return (Lemminkainen Suite) Op 22")


def test_sibelius_lemminkainen_suite_full_set_folds():
    assert _same_group(
        "Lemminkainen Suite, op 22",
        "Lemminkainen Suite: 4 Legends from the Kalevala for orchestra (Op 22)")


def test_sibelius_lemminkainen_return_distinct_from_swan_of_tuonela():
    # Two distinct pieces from the suite.
    assert not _same_group(
        "Lemminkainen's Return (Lemminkainen Suite) Op 22",
        "The Swan of Tuonela (Lemminkainen suite, Op 22)")


def test_sibelius_jordens_sang_op93_scoring_folds():
    assert _same_group(
        "Jordens sang (Song of the Earth) - cantata for chorus and orchestra (Op.93)",
        "Jordens sang (Song of the Earth), Op 93")


def test_sibelius_esquisses_op114_bare_form_folds():
    assert _same_group("Esquisses, Op 114",
                       "5 Esquisses for piano, Op 114")


def test_sibelius_valse_triste_op44_variants_fold():
    main = "Valse triste, from Kuolema, incidental music Op 44"
    assert _same_group("Valse Triste - from Kuolemo (Op.44 No.1)", main)
    assert _same_group("Valse Triste, from 'Kuolema, Op 44'", main)
    assert _same_group("Valse triste (Kuolema - incidental music, Op 44)", main)
    assert _same_group("Valse triste Op 44 no 1", main)


def test_sibelius_romance_strings_op42_word_order_folds():
    assert _same_group("Romance for string orchestra in C major (Op.42)",
                       "Romance for strings in C major, Op 42")


def test_sibelius_belshazzars_feast_op51_subtitle_folds():
    assert _same_group(
        "Belshazzar's Feast - suite from the incidental music, Op 51",
        "Belshazzar's feast suite, Op 51")


def test_sibelius_pensees_lyriques_op40_bare_form_folds():
    assert _same_group("Pensees Lyriques, Op.40",
                       "10 Pensees lyriques for piano, Op 40")


def test_sibelius_luonnotar_op70_subtitle_variants_fold():
    main = "Luonnotar, Op 70"
    assert _same_group("Luonnotar, Op 70, symphonic poem", main)
    assert _same_group("Luonnotar, tone poem, Op 70", main)


def test_sibelius_andante_festivo_subset_detection_fold():
    # Caught by the tool's subset-detection pass (bare form has a
    # composer-rare token "festivo" + "andante").
    assert _same_group("Andante Festivo",
                       "Andante Festivo for strings and timpani")


def test_sibelius_symphony_7_op105_subtitle_folds():
    assert _same_group(
        "Symphony No 7 in C major Op 105 (in one continuous movement)",
        "Symphony no 7 in C major, Op 105")


# --- --summary flag -------------------------------------------------------

def test_compute_summary_empty_corpus():
    stats = compute_summary([])
    assert stats["n_distinct_composers"] == 0
    assert stats["n_distinct_works"] == 0
    assert stats["tracks_per_episode_median"] == 0


def test_compute_summary_basic_counts():
    rows = [
        ("Wolfgang Amadeus Mozart", "Symphony no 41 in C, K.551", "ep1"),
        ("Wolfgang Amadeus Mozart", "Symphony no 41 in C major, K.551", "ep2"),
        ("Johann Sebastian Bach", "Mass in B minor, BWV 232", "ep1"),
        ("Johann Sebastian Bach", "Mass in B minor, BWV 232", "ep2"),
        ("Ludwig van Beethoven", "Symphony No 5 in C minor, Op 67", "ep1"),
    ]
    stats = compute_summary(rows)
    # Mozart K.551 variants fold (catalogue path); Bach Mass twice
    # under one work; Beethoven one airing.
    assert stats["n_distinct_composers"] == 3
    assert stats["n_distinct_works"] == 3
    # ep1 has 3 tracks, ep2 has 2 tracks → median 3 (5 elements → middle is
    # index 2 → 3). Actually sorted: [2,3] → middle of 2-element list is
    # index 1 → 3. Let me re-check: track_counts = sorted(values) where
    # values = [3 (ep1), 2 (ep2)] → sorted [2,3], n_eps=2, median = [n_eps//2]
    # = [1] = 3.
    assert stats["tracks_per_episode_median"] == 3


def test_compute_summary_attributes_arranger_tail_to_principal_composer():
    # The summary feed strips arranger-tail co-credits (mirroring --by
    # composer), so an "X, Y (Arranger)" track is attributed to principal
    # composer X, not a phantom "X, Y" composer. Regression for the Mozart/
    # Danzi off-by-one between --summary and --by composer.
    raw = [
        ("Wolfgang Amadeus Mozart, Franz Danzi",
         "Wolfgang Amadeus Mozart, Franz Danzi (Arranger)",
         "Extracts from 'Die Zauberflote' arr. Danzi for 2 cellos", "ep1"),
        ("Wolfgang Amadeus Mozart", "Wolfgang Amadeus Mozart (1756-1791)",
         "Symphony no 40 in G minor, K.550", "ep1"),
    ]
    rows = [(strip_arranger_tail(c, cl), t, e) for c, cl, t, e in raw]
    stats = compute_summary(rows)
    assert stats["n_distinct_composers"] == 1
    assert stats["top_composers"][0] == ("Wolfgang Amadeus Mozart", 2)


def test_compute_summary_distribution_buckets():
    # 1 composer with 1 airing, 1 with 3 airings, 1 with 100+ airings.
    rows = []
    rows.append(("OneTimer", "Work A", "ep-x"))
    for i in range(3):
        rows.append(("MidComposer", f"Work {i}", f"ep-{i}"))
    for i in range(120):
        rows.append(("BigComposer", f"Big Work {i}", f"big-ep-{i}"))
    stats = compute_summary(rows)
    assert stats["composer_buckets"]["1"] == 1
    assert stats["composer_buckets"]["2-5"] == 1
    assert stats["composer_buckets"]["100+"] == 1


def test_compute_summary_top_5_truncates():
    rows = [(f"Comp{i}", f"Work {i}", f"ep{i}")
            for i in range(10)]
    stats = compute_summary(rows)
    assert len(stats["top_composers"]) == 5
    assert len(stats["top_works"]) == 5


def test_compute_summary_top_composers_by_works_truncates_to_5():
    rows = [(f"Comp{i}", f"Work {j}", f"ep{i}-{j}")
            for i in range(10) for j in range(3)]
    stats = compute_summary(rows)
    assert len(stats["top_composers_by_works"]) == 5
    # Each composer has 3 distinct works; all top-5 entries should show 3.
    assert all(n == 3 for _, n in stats["top_composers_by_works"])


def test_compute_summary_top_composers_by_works_ranks_by_breadth_not_airings():
    """A composer with many airings of one work ranks LOWER by works
    than a composer with fewer airings spread across many works."""
    rows = []
    # ProlificButRepeated — 1 work, 100 airings
    for i in range(100):
        rows.append(("ProlificButRepeated", "One Famous Work", f"a-{i}"))
    # BroadCatalogue — 20 works, 1 airing each
    for j in range(20):
        rows.append(("BroadCatalogue", f"Work {j}", f"b-{j}"))
    stats = compute_summary(rows)
    by_airings = [name for name, _ in stats["top_composers"]]
    by_works = [name for name, _ in stats["top_composers_by_works"]]
    assert by_airings[0] == "ProlificButRepeated"
    assert by_works[0] == "BroadCatalogue"


def test_render_summary_includes_key_sections():
    rows = [("Bach", "Mass", "ep1"), ("Mozart", "Symphony", "ep1")]
    output = render_summary(compute_summary(rows))
    assert "Distinct composers" in output
    assert "Distinct works" in output
    assert "Top composers by airings" in output
    assert "Top composers by works" in output
    assert "Top works by airings" in output
    assert "Tracks per episode" in output


def test_summary_data_fingerprint_is_order_independent():
    a = [("Bach", "Mass", "ep1"), ("Mozart", "Symphony", "ep2")]
    b = list(reversed(a))
    assert _summary_data_fingerprint(a) == _summary_data_fingerprint(b)


def test_summary_data_fingerprint_changes_when_rows_change():
    a = [("Bach", "Mass", "ep1")]
    b = [("Bach", "Mass", "ep1"), ("Mozart", "Symphony", "ep2")]
    assert _summary_data_fingerprint(a) != _summary_data_fingerprint(b)


def test_summary_cache_roundtrip_hit(tmp_path):
    path = tmp_path / "summary_cache.json"
    stats = compute_summary([("Bach", "Mass", "ep1")])
    _write_summary_cache(str(path), "data_fp", "code_fp", stats)
    cached = _read_summary_cache(str(path), "data_fp", "code_fp")
    assert cached is not None
    # JSON normalises tuples to lists; render_summary iterates via
    # unpacking, so the rendered output is what actually matters.
    assert render_summary(cached) == render_summary(stats)


def test_summary_cache_miss_on_stale_fingerprint(tmp_path):
    path = tmp_path / "summary_cache.json"
    stats = compute_summary([("Bach", "Mass", "ep1")])
    _write_summary_cache(str(path), "data_fp", "code_fp", stats)
    assert _read_summary_cache(str(path), "DIFFERENT", "code_fp") is None
    assert _read_summary_cache(str(path), "data_fp", "DIFFERENT") is None


def test_summary_cache_miss_when_file_absent(tmp_path):
    assert _read_summary_cache(str(tmp_path / "nope.json"), "x", "y") is None


def test_summary_cache_holds_multiple_slots(tmp_path):
    """A single cache file holds one entry per data fingerprint, keyed by
    that hash. This is what lets every --year YYYY pre-populate alongside
    the bare-invocation entry."""
    path = tmp_path / "summary_cache.json"
    stats_a = compute_summary([("Bach", "Mass", "ep1")])
    stats_b = compute_summary([("Mozart", "Symphony", "ep2")])
    _write_summary_cache(str(path), "data_a", "code_v1", stats_a)
    _write_summary_cache(str(path), "data_b", "code_v1", stats_b)
    assert render_summary(
        _read_summary_cache(str(path), "data_a", "code_v1")
    ) == render_summary(stats_a)
    assert render_summary(
        _read_summary_cache(str(path), "data_b", "code_v1")
    ) == render_summary(stats_b)


def test_summary_cache_code_change_drops_all_slots(tmp_path):
    """A code-fingerprint change invalidates every slot — the canonical
    rules or alias tables have shifted, so stale year-stats can't be
    trusted."""
    path = tmp_path / "summary_cache.json"
    stats = compute_summary([("Bach", "Mass", "ep1")])
    _write_summary_cache(str(path), "data_a", "code_v1", stats)
    _write_summary_cache(str(path), "data_b", "code_v1", stats)
    # First write under the new code_hash drops both prior slots
    _write_summary_cache(str(path), "data_c", "code_v2", stats)
    assert _read_summary_cache(str(path), "data_a", "code_v2") is None
    assert _read_summary_cache(str(path), "data_b", "code_v2") is None
    assert _read_summary_cache(str(path), "data_c", "code_v2") is not None


def test_grieg_selected_lyric_pieces_5piece_program_folds():
    assert _same_group(
        "Selected Lyric Pieces (Lyriske stykker): Aften på højfjellet "
        "(Evening in the mountains), Op.68 No.4; For dine føtter "
        "(At your feet), Op.68 No.3; Sommeraften (Summer's evening), "
        "Op.71 No.2; Forbi (Gone), Op.71 No.6; Etterklang "
        "(Remembrances), Op.71 No.7",
        "5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) "
        "(Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); "
        "Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) "
        "(Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)")


def test_d940_originally_for_4_hands_folds():
    assert _same_group("Fantasia in F minor, D.940 (originally for 4 hands)",
                       "Fantasie in F minor for Piano Four Hands, D940")


def test_k298_bare_flute_quartet_folds():
    assert _same_group("Quartet for flute and strings (K 298) in A major",
                       "Flute Quartet no 4 in A major, K 298")


# --- Mozart quartets & quintets: numbered-vs-unnumbered folds (2026-05-28) --

def test_k387_string_quartet_14_bare_folds():
    assert _same_group("String Quartet no.14 in G major, K.387",
                       "Quartet in G major (K.387)")


def test_k465_dissonance_quartet_ordinal_variants_fold():
    bare = 'String Quartet in C major (K.465) "Dissonance"'
    assert _same_group("String Quartet no 19 in C major, K.465 'Dissonance'", bare)
    assert _same_group('String Quartet no 19, K.465 "Dissonance"', bare)


def test_k458_hunt_quartet_ordinal_folds():
    assert _same_group("String Quartet no 17 in B flat, K. 458 'Hunt'",
                       "String Quartet in B flat major, K458, 'Hunt'")


def test_k589_prussian_quartet_ordinal_folds():
    assert _same_group("String Quartet no.22 in B flat major, K. 589 'Prussian'",
                       "Quartet for strings (K.589) in B flat major 'Prussian'")


def test_k493_piano_quartet_2_ordinal_folds():
    assert _same_group("Piano Quartet no 2 in E flat major, K. 493",
                       "Piano Quartet in E flat major, K493")


def test_k515_string_quintet_3_ordinal_folds():
    assert _same_group("String Quintet no.3 in C major, K.515",
                       "String Quintet in C major, K515")


def test_k516_no4_folds_now_excerpt_split_off():
    # Unblocked by the movement-marker gate: no.4 whole-work folds into bare,
    # while the Adagio excerpt stays separate.
    assert _same_group("String Quintet no.4 in G minor, K.516",
                       "Quintet for strings in G minor (K.516)")
    assert not _same_group(
        "Adagio ma non troppo, from String Quintet no 4 in G minor, K.516",
        "Quintet for strings in G minor (K.516)")


def test_k576_no18_folds_now_excerpt_split_off():
    assert _same_group("Piano Sonata No 18 In D major, K576",
                       "Piano Sonata in D major (K.576)")
    assert not _same_group("Adagio, from 'Piano Sonata no 18 In D, K. 576'",
                           "Piano Sonata in D major (K.576)")


def test_k331_rondo_alla_turca_unified_and_split_from_whole():
    rondo = "Rondo alla turca, from Piano Sonata no.11 in A major, K.331"
    # "Alla turca, from …" (leads with Alla, not gated) folds into the Rondo
    assert _same_group("Alla turca, from Piano Sonata no.11 in A major, K.331", rondo)
    assert _same_group("Rondo alla Turca (3rd movement from Piano Sonata No 11 in A, K.331)",
                       rondo)
    # whole sonata and the Fazıl Say fantasy stay separate
    assert not _same_group(rondo, "Piano Sonata in A major, K.331 'Alla Turca'")
    assert not _same_group(rondo,
                           "Alla Turca - Fantasia on Rondo from Piano Sonata K. 331 by Mozart")


# --- ttn_duplicates straggler harvest (2026-05-30) --------------------------

def test_wolf_italian_serenade_scoring_and_key_fold():
    assert _same_group("Italian Serenade for string quartet", "Italian Serenade")
    assert _same_group("Italian Serenade in G major", "Italian Serenade")


def test_debussy_danse_sacree_catalogue_and_scoring_fold():
    canon = "Danse sacree et danse profane for harp and strings"
    assert _same_group("Danse sacrée et Danse profane, L.103", canon)
    assert _same_group("Danse sacrée et danse profane", canon)


def test_brahms_handel_variations_by_handel_folds():
    assert _same_group("25 Variations and Fugue on a Theme by Handel, Op 24",
                       "25 Variations and fugue on a theme by G F Handel for piano, Op 24")


def test_elgar_enigma_for_orchestra_folds():
    assert _same_group("Variations on an original theme (Enigma) Op 36",
                       "Variations on an original theme ('Enigma') Op.36 for orchestra")


def test_dvorak_american_quartet_word_order_folds():
    assert _same_group("American Quartet no 12 in F major, Op 96",
                       "String Quartet No 12 in F major, Op 96, 'American'")


def test_chopin_ballade3_for_piano_folds():
    assert _same_group("Ballade for piano no 3 in A flat major, Op 47",
                       "Ballade no 3 in A flat major, Op 47")


def test_schumann_cello_concerto_word_order_folds():
    assert _same_group("Concerto for cello and orchestra in A minor, Op.129",
                       "Cello Concerto in A minor, Op 129")


def test_k285_flute_quartet_1_ordinal_folds():
    assert _same_group("Flute Quartet No.1 in D major, K.285",
                       "Flute Quartet in D major, K.285")


def test_k456_dissonance_typo_folds_to_real_k465():
    # BBC mislabels the Dissonance Quartet K.456; its real number is K.465.
    assert _same_group("String Quartet no.19 in C major K.456, 'Dissonance'",
                       'String Quartet in C major (K.465) "Dissonance"')


def test_k456_piano_concerto_18_not_dragged_by_dissonance_typo():
    # The genuine K.456 work (Piano Concerto No 18) must stay distinct from
    # the mislabelled Dissonance Quartet.
    assert not _same_group("Piano Concerto no.18 in B flat major K.456",
                           "String Quartet no.19 in C major K.456, 'Dissonance'")


def test_k285_distinct_from_k285a_flute_quartet():
    # K.285 (D major) and K.285a (G major) are different flute quartets.
    assert not _same_group("Flute Quartet in D major, K.285",
                           "Flute Quartet in G major, K.285a")


# --- ttn_duplicates harvest, 2nd pass (2026-05-30, siblings guard) ----------

def test_2p_op_number_omitted_folds():
    assert _same_group("Coriolan Overture", "Coriolan Overture, Op 62")
    assert _same_group("Finlandia", "Finlandia, Op 26")
    assert _same_group("Adagio for Strings", "Adagio for Strings, Op 11")
    assert _same_group("Academic Festival Overture",
                       "Academic Festival Overture, Op 80")


def test_2p_lesure_catalogue_added_folds():
    assert _same_group("La Mer, L.109", "La Mer")
    assert _same_group("Estampes, L.100", "Estampes")
    assert _same_group("L'isle joyeuse, L.106", "L'Isle joyeuse")


def test_2p_hebrides_chain_safe_to_final_canonical():
    # Target the FINAL canonical ("The Hebrides, Op 26"), not the intermediate
    # "Hebrides overture, Op 26" alias key — aliases are single-step.
    assert _same_group("The Hebrides - overture", "The Hebrides, Op 26")
    assert _same_group("Hebrides overture, Op 26", "The Hebrides, Op 26")


def test_2p_accent_and_translation_fold():
    canon = "Vltava (Moldau) - from 'Ma Vlast'"
    assert _same_group("Vltava (Moldau), from 'Má vlast' (My Homeland)", canon)
    assert _same_group("Vltava from Má vlast", canon)
    assert _same_group("Spring Night", "Varnatt (Spring Night)")


def test_2p_typo_and_punctuation_fold():
    assert _same_group("3 Songs for choru, Op 42", "3 Songs for chorus, Op 42")
    assert _same_group("Suite for oboe and strings,Op.32",
                       "Suite for oboe and strings, Op 32")


def test_2p_nickname_added_folds():
    canon = "Piano Sonata no 2 in B flat minor, Op 35"
    assert _same_group("Piano Sonata no 2 in B flat minor, Op 35 "
                       "'Funeral March'", canon)
    assert _same_group("Piano sonata no 2 in B flat minor, Op 35 "
                       "'Marche funebre'", canon)


def test_2p_redundant_scoring_annotation_folds():
    assert _same_group("Trois Pieces Breves for wind quintet",
                       "Trois Pieces Breves")
    assert _same_group("Stabat Mater for 8 voices", "Stabat Mater")
    assert _same_group("Italian Serenade in G major for string quartet, Op 120",
                       "Italian Serenade")


def test_2p_catalogue_ref_typos_fold():
    assert _same_group('Piano Quintet in A major, D66), (Trout)',
                       'Piano Quintet in A major (D.667) "Trout"')
    assert _same_group("Cello Suite No 2 in D minor, BWV 1008o",
                       "Cello Suite no 2 in D minor, BWV 1008")
    assert _same_group(
        "Sonata Polonaise in A minor for violin, viola and continuo TWV 42",
        "Sonata Polonaise in A minor for violin, viola and continuo, TWV.42:a8")


def test_2p_catalogue_ref_typos_do_not_overmerge():
    # Adjacent catalogue numbers are DIFFERENT works — the typo folds must not
    # bleed into them.
    assert not _same_group("Cello Suite no 2 in D minor, BWV 1008",
                           "Cello Suite no 3 in C major, BWV 1009")
    assert not _same_group("Concerto da Camera in C major RV.87",
                           "Concerto da Camera in C major RV.88")


def test_2p_sibling_works_stay_distinct():
    # The folds must NOT bleed into genuine set-siblings the siblings guard
    # keeps apart.
    assert not _same_group("Scherzo No 2 in B flat minor, Op 31",
                           "Scherzo no 1 in B minor, Op 20")
    assert not _same_group("Hungarian Rhapsody No 2 in C sharp minor",
                           "Hungarian Rhapsody No 6 in D flat major")
    assert not _same_group("Symphony no 5 in E flat major, Op 82",
                           "Symphony no 3 in F major, Op 90")


# --- Mozart audit, rest of catalogue (2026-05-29) ---------------------------

def test_k385_haffner_keyless_folds():
    assert _same_group("Symphony No.35 (K. 385) 'Haffner'",
                       'Symphony no 35 in D major, K.385, "Haffner"')


def test_k595_piano_concerto_27_bare_folds():
    assert _same_group("Piano Concerto in B flat major, K.595",
                       "Piano Concerto no 27 in B flat major, K.595")


def test_k388_serenade_altkochel_and_ordinal_fold():
    main = "Serenade in C minor for Wind Octet (K.388)"
    assert _same_group("Serenade (K.388) in C minor for wind octet (K.384a)", main)
    assert _same_group("Serenade No. 12 in C minor, K. 388", main)


def test_k365_two_pianos_altkochel_and_ordinal_fold():
    main = "Concerto for 2 pianos and orchestra in E flat major (K.365)"
    assert _same_group("Concerto for 2 pianos in E flat major, K365/316a", main)
    assert _same_group("Piano Concerto no 10 in E flat for Two Pianos, K. 365", main)


def test_k299_flute_harp_altkochel_variants_fold():
    main = "Concerto for Flute, Harp and Orchestra in C major, K.299"
    assert _same_group("Concerto for Flute and Harp in C, K. 299/297c", main)
    assert _same_group("Concerto for Flute and Harp in C, K.299/277c", main)


def test_k525_serenade_phrasing_folds_into_no13_canonical():
    # Existing canonical is the No.13 form; the Serenade-in-G phrasing joins it.
    assert _same_group("Serenade in G major, K525 'Eine kleine Nachtmusik'",
                       "Eine kleine Nachtmusik (Serenade No.13 in G) (K.525)")
    assert _same_group("Serenade in G major, K525 'Eine kleine Nachtmusik'",
                       "Eine kleine Nachtmusik, K525")


def test_k212_kirchensonate_scoring_folds():
    assert _same_group(
        "Kirchen-Sonate in B flat (K. 212) for 2 violins, double bass and organ",
        "Kirchen-Sonate in B flat, K212")


def test_k549_notturni_numberword_folds():
    assert _same_group("4 Notturni", "Four Notturni")


def test_k618_ave_verum_motet_scoring_folds():
    assert _same_group("Ave Verum Corpus (K.618) (motet for chorus and strings)",
                       "Ave verum corpus, K.618")


def test_k505_concert_aria_phrasings_fold():
    assert _same_group(
        "Ch'io mi scordi di te ...? Non temer, amato bene, K.505",
        "Concert aria: Ch'io mi scordi di te...? Non temer, amato bene (K.505)")


def test_k528_bella_mia_fiamma_concert_aria_folds():
    assert _same_group('Concert aria "Bella mia fiamma...Resta, O cara" (K.528)',
                       "Bella mia fiamma - Resta, o cara, K.528")


def test_k584_rivolgete_cosi_phrasings_unify():
    canon = "Aria 'Rivolgete a lui lo sguardo' (K.584)"
    assert _same_group("Rivolgete a lui lo sguardo, K.584 (from 'Cosi fan tutte')", canon)
    assert _same_group('Aria: \'Rivolgete a lui lo sguardo\' (from "Cosí fan tutte", Act 1)', canon)
    assert _same_group("Rivolgete a lui lo sguardo, K.584", canon)


# --- Mozart audit, opera overtures & arias (2026-05-29) ---------------------

def test_figaro_overture_phrasings_unify():
    canon = "Le Nozze di Figaro, K492, Overture"
    for v in ["Marriage of Figaro - overture",
              "The Marriage of Figaro (Overture)",
              "Le Nozze di Figaro - overture",
              "Overture to Le Nozze di Figaro",
              "Overture to Le Nozze di Figaro - opera in 4 acts K.492"]:
        assert _same_group(v, canon), v


def test_don_giovanni_overture_acts_tail_folds():
    assert _same_group("Overture from Don Giovanni - opera in 2 acts (K.527)",
                       "Overture from 'Don Giovanni' (K.527)")


def test_magic_flute_overture_english_folds_to_german():
    canon = "Overture from Die Zauberflote (K 620)"
    assert _same_group("Overture to the Magic Flute", canon)
    assert _same_group("The Magic Flute (overture)", canon)


def test_clemenza_overture_token_forms_unify_at_k621():
    canon = "Overture to La Clemenza di Tito (K.621)"
    assert _same_group("La Clemenza di Tito - overture", canon)
    assert _same_group("La Clemenza di Tito (overture)", canon)


def test_figaro_arias_do_not_fold_into_overture():
    overture = "Le Nozze di Figaro, K492, Overture"
    dove_sono = "Recit and aria 'Dove Sono' - from Act III of Le Nozze di Figaro, K.492"
    deh_vieni = "Le Nozze di Figaro, Act 4: Susanna's aria 'Deh vieni, non tardar'"
    assert not _same_group(dove_sono, overture)
    assert not _same_group(deh_vieni, overture)
    assert not _same_group(dove_sono, deh_vieni)


def test_figaro_dove_sono_phrasings_fold():
    assert _same_group(
        "'Dove sono i bei momenti' - Countess' aria from The Marriage of Figaro. K.492",
        "Recit and aria 'Dove Sono' - from Act III of Le Nozze di Figaro, K.492")


def test_figaro_deh_vieni_phrasings_fold():
    assert _same_group("Aria: Deh vieni, non tardar - from Le Nozze di Figaro",
                       "Le Nozze di Figaro, Act 4: Susanna's aria 'Deh vieni, non tardar'")


def test_zauberflote_ein_madchen_phrasings_fold():
    assert _same_group("Ein Mädchen oder Weibchen - from 'Die Zauberflöte' K 620, Act 2",
                       '"Ein Mädchen oder Weibchen" - from \'Die Zauberflöte\' (K620), Act 2')


def test_cosi_unaura_amorosa_phrasings_fold():
    assert _same_group(
        'Aria: "Un\'aura amorosa" from Cosi fan tutte (K.588), Act 1',
        'Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1')


# --- Haydn audit (2026-05-29): Hoboken-format fragmentation folds -----------

def test_haydn_symphony6_le_matin_hob_forms_fold():
    canon = 'Symphony no 6 in D major (H.1.6) "Le Matin"'
    assert _same_group("Symphony no 6 in D major 'Le Matin'", canon)
    assert _same_group("Symphony no 6 in D, Hob. I:6 'Le matin'", canon)


def test_haydn_symphony49_la_passione_forms_fold():
    canon = 'Symphony No.49 in F minor (Hob.1.49)  "La Passione"'
    for v in ["Symphony no 49 in F minor, Hob.I:49 'La Passione'",
              "Symphony No 49 in F minor H.1.49 (La Passione)",
              "Symphony no.49 in F minor, H.I:49, 'La Passione'"]:
        assert _same_group(v, canon), v


def test_haydn_lark_quartet_op64_5_forms_fold():
    canon = 'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"'
    assert _same_group("String Quartet in D major (Op. 64 No.5) 'The Lark'", canon)
    assert _same_group("String Quartet in D major, Op 64 no 5 'Lark'", canon)


def test_haydn_op64_lark_distinct_from_op64_3():
    # Set-catalogue siblings: Op 64/5 (Lark) and Op 64/3 are different works.
    assert not _same_group(
        'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"',
        'String Quartet no 50 in B flat major, Op 64 no 3 (Hob.III:67)')


def test_haydn_emperor_quartet_backtick_forms_fold():
    canon = "String Quartet No.62 in C Major, Op.76'3 'Emperor'"
    assert _same_group("String Quartet in C major Op 76`3 (Emperor)", canon)
    assert _same_group("Quartet in C major Op 76`3 (Emperor)", canon)


def test_haydn_london_trio_no1_all_forms_converge():
    canon = "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"
    for v in ["Divertimento in C major, London Trio no 1, Hob.4:1",
              "Divertimento in C, Hob. IV:1 (attacca)",
              "Divertimento in C major, Hob.IV No.1",
              "Divertimento in C major, Hob.IV No 1 'London Trio'"]:
        assert _same_group(v, canon), v


def test_haydn_cello_concerto_roman_arabic_hob_fold():
    assert _same_group("Cello Concerto No. 1 in C, Hob. 7b:1",
                       "Cello Concerto No. 1 in C, Hob. VIIb:1")
    # but No 1 (C) and No 2 (D) stay distinct
    assert not _same_group("Cello Concerto No. 1 in C, Hob. VIIb:1",
                           "Cello Concerto in D major, Hob.VIIb No.2")


def test_haydn_te_deum_xxiiic1_distinct_from_xxiiic2():
    # Two different Te Deums (early H.23c.1 vs Grosses Hob.XXIIIc:2).
    assert not _same_group("Te Deum (H.23c.1) in C major (c.1765)",
                           "(Grosses) Te Deum in C major (Hob XXIIIc:2)")


def test_haydn_composer_name_variants_fold_to_joseph():
    assert _same_composer("Franz Joseph Haydn", "Joseph Haydn")
    assert _same_composer("Josef Haydn", "Joseph Haydn")
    assert _same_composer("Jozef Haydn", "Joseph Haydn")


def test_michael_haydn_stays_distinct_from_joseph():
    assert not _same_composer("Michael Haydn", "Joseph Haydn")
    assert _same_composer("Johann Michael Haydn", "Michael Haydn")


# --- Haydn re-audit (2026-05-29): second-pass Hob-notation folds ------------

def test_haydn_symphony103_drumroll_hob_notations_fold():
    assert _same_group("Symphony No 103 in E flat major, Hob.1/103 ('Drum roll')",
                       "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'")


def test_haydn_symphony100_military_notations_fold():
    canon = "Symphony no 100 in G major, Hob.1.100 \"Military\""
    assert _same_group("Symphony no 100 in G major, Hob. I:100 'Military'", canon)
    assert _same_group('Symphony No.100 in G major, "Military"', canon)


def test_haydn_lobkowitz_pure_hob_form_joins_op77():
    assert _same_group("Quartet for strings in G major Hob III:81 'Lobkowitz'",
                       "String Quartet in G major Op 77 No 1")


def test_haydn_sonata_xvi33_h_prefix_and_hob_fold():
    canon = "Piano Sonata in D major, Hob.XVI.33"
    assert _same_group("Piano Sonata in D major, H.XVI.33", canon)
    assert _same_group("Sonata for piano (H.XVI.33) in D major", canon)


def test_haydn_gypsy_rondo_all_notations_unify():
    canon = "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"
    for v in ["Piano Trio No 39 in G Hob XV:25",
              "Piano Trio in G major, 'Gypsy rondo' Hob.15.25",
              "Piano Trio in G major, Hob XV:25"]:
        assert _same_group(v, canon), v


def test_haydn_feldpartita_hob_ii46_notations_fold():
    assert _same_group("Divertimento in B flat, Hob.II:46",
                       "Divertimento 'Feldpartita' in B flat major, Hob.2.46")


def test_haydn_sonata_xvi37_distinct_from_xvi38():
    assert not _same_group("Keyboard Sonata in D major, Hob.XVI/37",
                           "Keyboard Sonata in E flat major, Hob.XVI/38")


# --- Wagner audit (2026-05-29): opera-excerpt phrasing folds ----------------

def test_wagner_siegfried_idyll_scoring_folds():
    assert _same_group("Siegfried Idyll for small orchestra", "Siegfried Idyll")
    assert _same_group("Siegfried-Idyll", "Siegfried Idyll")


def test_wagner_tristan_prelude_phrasings_fold():
    canon = "Tristan and Isolde (Prelude)"
    assert _same_group("Prelude to 'Tristan and Isolde'", canon)
    assert _same_group("Tristan und Isolde: Prelude to Act 1", canon)


def test_wagner_tristan_prelude_and_liebestod_phrasings_fold():
    canon = "Prelude and Liebestod - from the opera 'Tristan and Isolde'"
    assert _same_group("Prelude and Liebestod from 'Tristan und Isolde'", canon)
    assert _same_group("Prelude and Isolde's Liebestod - from 'Tristan und Isolde'", canon)


def test_wagner_tristan_prelude_distinct_from_prelude_and_liebestod():
    # The Prelude alone and the combined Prelude+Liebestod are different items.
    assert not _same_group(
        "Tristan and Isolde (Prelude)",
        "Prelude and Liebestod - from the opera 'Tristan and Isolde'")


def test_wagner_meistersinger_act1_prelude_folds():
    canon = "Prelude to Act 1 from 'Die Meistersinger von Nurnberg'"
    assert _same_group("Prelude to Die Meistersinger von Nurnberg", canon)
    assert _same_group("Prelude (Act 1 'Die Meistersinger von Nurnberg')", canon)
    # Act 3 prelude is a different excerpt
    assert not _same_group(canon, "Prelude to act 3 of 'Die Meistersinger von Nürnberg'")


def test_wagner_parsifal_prelude_distinct_from_good_friday_music():
    assert _same_group("Prelude to Act 1 of 'Parsifal'", "Prelude to Parsifal")
    assert not _same_group("Prelude to Parsifal", "Good Friday music from 'Parsifal'")


def test_wagner_lohengrin_act1_prelude_folds_act3_distinct():
    canon = "Prelude to Act 1 from Lohengrin"
    assert _same_group("Lohengrin - Prelude to Act 1", canon)
    assert _same_group("Prelude to Act I of 'Lohengrin'", canon)  # Act I == Act 1
    assert not _same_group(canon, "Prelude to act 3 of 'Lohengrin'")


def test_wagner_abendstern_phrasings_fold():
    canon = 'O du mein holder Abendstern – from "Tannhauser"'
    assert _same_group(
        'Recitative and aria "O du mein holder Abendstern" from Tannhäuser (Act 3)', canon)
    assert _same_group("O du mein holder Abendstern - from 'Tannhäuser', Act 3", canon)


def test_wagner_flying_dutchman_overture_forms_converge():
    canon = "Overture: Der Fliegende Hollander (The Flying Dutchman)"
    assert _same_group("Overture to 'Der fliegende Holländer'", canon)
    assert _same_group("Overture to 'Der fliegende Holländer' - The Flying Dutchman", canon)


def test_wagner_wesendonck_lieder_spelling_folds():
    assert _same_group("Fünf Lieder von Mathilde von Wesendonk",
                       "Funf Lieder von Mathilde von Wesendonck")


# --- Guards: distinct works under the same catalogue must stay split -------

def test_d899_impromptus_stay_split_after_phantom_ordering_aliases():
    # The new aliases must not break the set-catalogue case: Schubert's
    # D.899 impromptus are different sub-works distinguished by key.
    assert not _same_group("Impromptu in C minor, D.899 no 1",
                           "Impromptu in E flat major, D.899 no 2")


def test_bwv1007_and_bwv1009_stay_split():
    # Cello Suites 1 (BWV 1007) and 3 (BWV 1009) are different works.
    # Different catalogue refs already keep them apart — guard against any
    # alias leakage.
    assert not _same_group(
        "Sarabande from Suite for cello solo (BWV.1007) in G major",
        "Sarabande from Suite for solo cello in C (BWV.1009)")


# --- fantasie (German spelling) added to _STANDALONE_WORK_TERMS ------------

def test_schubert_d940_fantasie_piano_duet_folds():
    # "fantasie" (German) now treated as a standalone-form word alongside
    # "fantasia" / "fantasy", so the catalogue path fires even when an
    # excerpt-looking word ('duet') is in the title.
    assert _same_group("Fantasie in F minor, D.940, for piano duet",
                       "Fantasie in F minor for Piano Four Hands, D940")


# --- 'duet' removed from _EXCERPT_LOCATOR_RE -------------------------------
# Bare 'duet' is overwhelmingly a scoring word ("piano duet", "Duet for viola
# and cello") rather than an opera excerpt marker. Removing it fixes false
# splits for standalone "Duet" works and piano-duet scoring contexts.

def test_beethoven_woo32_duet_and_duo_fold():
    # WoO 32 is Beethoven's "Duet for viola and cello in E flat" — a
    # standalone work titled "Duet". The "Duo" variant names the same work.
    # Both now fall to catalogue path with the same key.
    assert _same_group("Duet for viola and cello in E flat major, WoO.32",
                       "Duo in E flat major for viola and cello, WoO 32")
    assert _same_group("Duet in E flat major, WoO.32",
                       "Duet for viola and cello in E flat major, WoO.32")


def test_schubert_d947_piano_duet_folds():
    # Lebensstürme — Allegro in A minor for piano duet. The scoring tail
    # ("for piano duet") no longer triggers the excerpt locator.
    assert _same_group("Allegro in A minor, D.947 'Lebensstürme'",
                       "Allegro in A minor D.947 (Lebenssturme) for piano duet")


def test_opera_duet_excerpt_still_detected_via_from():
    # Genuine opera-duet excerpts contain 'from', which IS still an excerpt
    # locator. They must NOT collapse into a whole-opera entry.
    assert not _same_group(
        "Don Giovanni, K.527",
        "La ci darem la mano - duet from Don Giovanni, K.527")


def test_italian_duetto_still_detected_as_excerpt():
    # duetto/duettino (the Italian operatic forms) remain in the locator
    # regex via `duett\w*`. So a "duetto" excerpt from a catalogued opera
    # should still NOT fuse with the whole-opera entry.
    assert not _same_group(
        "Le Nozze di Figaro, K.492",
        "Crudel! perchè finora - duetto, from Le Nozze di Figaro, K.492")


# --- WORK_ALIASES: sonata phantom-ordering batch (2026-05-26) --------------

def test_mozart_k332_phantom_orderings_fold():
    main = "Piano Sonata no 12 in F major, K.332"
    assert _same_group("Sonata for piano K.332 in F major", main)
    # The "2nd mvt Adagio" excerpt now keys §k332|adagio via the gate.
    assert not _same_group("Piano Sonata in F major, K 332 (2nd mvt Adagio)", main)


def test_schubert_d845_op42_dual_identifiers_fold():
    main = "Piano Sonata in A minor D.845, Op 42"
    assert _same_group("Piano Sonata no 16 in A minor, D.845", main)
    assert _same_group("Piano Sonata in A minor, D845", main)


def test_schubert_d960_bare_folds():
    assert _same_group("Piano Sonata in B flat major, D.960",
                       "Piano Sonata no 21 in B flat major, D.960")


def test_scarlatti_k88_bare_folds_into_arrangement():
    assert _same_group("Sonata in G minor, K88",
                       "Sonata in G minor (K 88) arranged for 2 harpsichords")


def test_bach_bwv1001_violin_sonata_1_folds():
    main = "Sonata for violin solo no 1 in G minor, BWV.1001"
    assert _same_group("Sonata for violin solo in G minor, BWV.1001", main)
    # The "Adagio & Fugue - 2 movements from" excerpt now keys
    # §bwv1001|adagio,fugue via the gate — split from the whole sonata.
    assert not _same_group(
        "Adagio & Fugue - 2 movements from Sonata for solo violin in G major BWV.1001",
        main)


def test_schubert_d959_no20_folds_into_andantino_excerpt():
    # Andantino is the most-aired BBC form (14 airings); no-20 is the
    # whole-work form (8). Both describe D.959 — merge.
    assert _same_group(
        "Piano Sonata no 20 in A, D. 959",
        "Andantino (second movement) from Piano Sonata in A major, D.959")


def test_schubert_d850_op53_dual_identifiers_fold():
    main = "Piano Sonata no 17 in D major, D.850"
    assert _same_group("Sonata (Op.53) in D major (D.850)", main)
    assert _same_group("Sonata in D major D.850 for piano", main)


def test_mozart_k330_bare_folds():
    assert _same_group("Piano Sonata in C K.330",
                       "Piano Sonata no 10 in C major, K.330")


def test_mozart_k381_allegro_splits_from_whole():
    # "Allegro Molto from Piano Sonata … K.381" keys §k381|allegro via the
    # gate — split from the whole 4-hands sonata.
    assert not _same_group("Allegro Molto from Piano Sonata in D major, K.381",
                           "Sonata for piano 4 hands in D major, K 381")


def test_handel_hwv363a_bare_folds():
    assert _same_group(
        "Sonata in F major, HWV.363a vers. oboe & bc",
        "Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc")


def test_handel_hwv362_oboe_violin_scorings_fold():
    # Same work in two scorings — original oboe, traditional violin arr.
    # Parallel to the BWV.1056 oboe-reconstruction case.
    assert _same_group("Sonata for oboe and continuo, HWV.362",
                       "Violin Sonata in A minor (Op.1 No.4) (HWV.362)")


def test_vivaldi_rv63_la_folia_variants_fold():
    main = "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"
    assert _same_group("Trio Sonata in D minor, RV 63 (Op 1 No 12), 'La Folia'", main)
    assert _same_group("Sonata no 12 in D minor, RV.63 ('La Follia')", main)
    assert _same_group("Trio Sonata in D minor, RV 63 'La Follia'", main)


def test_vivaldi_rv63_la_folia_tokensort_tail_folds():
    # Titles lacking the RV reference fall to the token-sort path; both
    # the "Trio Sonata" and "Sonata" forms must fold into the catalogue
    # group. Covers ~32 airings the earlier aliases missed.
    main = "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"
    assert _same_group("Trio Sonata in D minor Op 1 No 12 'La Folia' (1705)", main)
    assert _same_group("Trio Sonata in D minor, Op 1 No 12, 'La Folia' (1705)", main)
    assert _same_group("Trio Sonata in D minor (Op.1 No.12) 'La Folia' (1705)", main)
    assert _same_group("Sonata in D minor 'La Folia' Op 1 no 12", main)
    assert _same_group("Sonata in D minor 'La folia', Op.1 No.12", main)


# --- Guards: sibling sonatas under same composer must stay split -----------

def test_schubert_late_piano_sonatas_stay_split():
    # D.958, D.959, D.960 are Schubert's three last piano sonatas; distinct
    # Deutsch numbers. The new aliases must not leak across them.
    assert not _same_group("Piano Sonata in C minor, D.958",
                           "Piano Sonata in A major, D.959")
    assert not _same_group("Piano Sonata no 21 in B flat major, D.960",
                           "Piano Sonata in A major, D.959")


def test_haydn_hob16_keyboard_sonatas_stay_split():
    # Hob.16 is a SET catalogue across Haydn's keyboard sonatas. Each
    # Hob.16.N is a distinct sonata.
    assert not _same_group("Keyboard Sonata in B flat major, Hob.16.41",
                           "Keyboard Sonata in C major, Hob.16.48")


# --- --title filter: word-boundary contract ------------------------------

def _title_matches(user_input: str, title: str) -> bool:
    """Mirror the SQL REGEXP used by main(): case-insensitive whole-word search."""
    return re.search(_title_filter_pattern(user_input), title,
                     re.IGNORECASE) is not None


def test_title_filter_matches_whole_word():
    assert _title_matches("symphony", "Symphony no 7 in D minor, Op 70")
    assert _title_matches("concerto", "Violin Concerto in E minor, Op 64")


def test_title_filter_case_insensitive():
    assert _title_matches("symphony", "SYMPHONY No 5")
    assert _title_matches("SYMPHONY", "symphony no 5")


def test_title_filter_rejects_prefix_match():
    # The canonical contract: 'concerto' does NOT match 'concertino'.
    assert not _title_matches("concerto", "Flute Concertino, Op 107")
    assert not _title_matches("sonata", "Sonatina in G major")
    assert not _title_matches("symphony", "Symphonic Variations")


def test_title_filter_rejects_substring_in_middle():
    # No word boundary inside a longer word, on either side.
    assert not _title_matches("song", "Songbird")        # suffix attached
    assert not _title_matches("song", "Birdsong tower")  # prefix attached
    assert _title_matches("song", "Birdsong tower song")  # standalone match


def test_title_filter_escapes_special_chars():
    # User input is re.escape'd: dots stay literal, not regex any-char.
    assert _title_matches("no. 5", "Symphony No. 5 in C minor")
    assert not _title_matches("no. 5", "Symphony no 5 in C minor")  # no period


def test_title_filter_multi_token():
    # Multi-word substring still has \b at both ends; matches the whole phrase.
    assert _title_matches("string quartet", "String Quartet no 14")
    assert not _title_matches("string quartet", "Stringquartet")


def test_normalize_title_filter_passes_real_input_through():
    assert _normalize_title_filter("symphony") == "symphony"


def test_normalize_title_filter_strips_whitespace():
    assert _normalize_title_filter("  symphony  ") == "symphony"
    assert _normalize_title_filter("symphony ") == "symphony"


def test_normalize_title_filter_empty_and_whitespace_become_none():
    # Otherwise \b\b would match everywhere and the header would still
    # report (title~='') — both surprising.
    assert _normalize_title_filter(None) is None
    assert _normalize_title_filter("") is None
    assert _normalize_title_filter("   ") is None
    assert _normalize_title_filter("\t") is None


# --- --form filter: form-family folding ----------------------------------

def _form_matches(form_name: str, title: str) -> bool:
    """Mirror the SQL OR-of-REGEXPs that main() builds for --form."""
    _, patterns = _form_filter_clauses(form_name)
    return any(re.search(p, title, re.IGNORECASE) for p in patterns)


def test_form_clause_param_count_matches_synonym_count():
    # The SQL clause must have exactly one '?' per synonym (the params
    # list and the placeholders must line up).
    for form_name, synonyms in _FORM_SYNONYMS.items():
        clause, params = _form_filter_clauses(form_name)
        assert len(params) == len(synonyms), form_name
        assert clause.count("?") == len(synonyms), form_name


def test_form_symphony_folds_cross_language():
    # The motivating case: Berlioz "Symphonie fantastique" matches --form
    # symphony, alongside English titles.
    assert _form_matches("symphony", "Symphony no 5 in D, Op 47")
    assert _form_matches("symphony", "Symphonie fantastique, Op 14")


def test_form_overture_folds_cross_language():
    assert _form_matches("overture", "Overture to The Hebrides, Op 26")
    assert _form_matches("overture", "Ouverture solennelle 1812, Op 49")


def test_form_prelude_folds_accent_and_plural():
    assert _form_matches("prelude", "Prelude in C major, BWV.846")
    assert _form_matches("prelude", "Prélude à l'après-midi d'un faune")
    assert _form_matches("prelude", "24 Preludes, Op 28")


def test_form_fantasia_folds_three_spellings():
    assert _form_matches("fantasia", "Fantasia on a theme by Tallis")
    assert _form_matches("fantasia", "Fantasie in F minor, D.940")
    assert _form_matches("fantasia", "Chromatic Fantasy and Fugue, BWV.903")


def test_form_nocturne_folds_italian():
    assert _form_matches("nocturne", "Nocturne in E flat, Op 9 no 2")
    assert _form_matches("nocturne", "Notturno in D, K.286")


def test_form_concerto_does_not_match_concertino():
    # Sibling diminutive — must stay split.
    assert _form_matches("concerto", "Violin Concerto in E minor, Op 64")
    assert not _form_matches("concerto", "Flute Concertino, Op 107")
    # And the inverse direction.
    assert _form_matches("concertino", "Flute Concertino, Op 107")
    assert not _form_matches("concertino", "Violin Concerto in E minor")


def test_form_sonata_does_not_match_sonatina():
    assert _form_matches("sonata", "Piano Sonata no 21 in B flat, D.960")
    assert not _form_matches("sonata", "Sonatina for clarinet & piano")


def test_form_symphony_does_not_match_sinfonia_or_symphonic():
    # Sinfonia is a distinct form (Bach's sinfonias, Vivaldi's sinfonie
    # for strings are NOT symphonies). Symphonic/symphonique are
    # adjectives, not form names.
    assert not _form_matches("symphony", "Sinfonia in F major (Wq.183/3)")
    assert not _form_matches("symphony", "Symphonic Variations, Op 78")


def test_form_dance_folds_plural():
    assert _form_matches("dance", "Slavonic Dance in G minor")
    assert _form_matches("dance", "Hungarian Dances, WoO 1")


def test_form_etude_folds_study():
    assert _form_matches("etude", "Etude in C minor 'Revolutionary'")
    assert _form_matches("etude", "Symphonic Studies, Op 13")
    assert _form_matches("etude", "Étude-tableau")


@pytest.mark.parametrize("variant", [
    "Dixit Dominus - Psalm 110, HWV.232",
    "Dixit Dominus - Psalm 110 HWV.232",
    "Dixit Dominus - Psalm 110 HWV 232",
    "Dixit Dominus in G minor, HWV.232",
])
def test_handel_dixit_dominus_folds(variant):
    assert _same_group(variant, "Dixit Dominus, HWV 232")


def test_handel_dixit_dominus_de_torrente_excerpt_stays_split():
    """The 7th-movement aria 'De torrente in via bibet' is a genuine
    excerpt and must NOT fold into the whole-work group."""
    assert not _same_group(
        "Dixit Dominus - Psalm 110 HWV.232 no.7; De torrente in via bibet",
        "Dixit Dominus, HWV 232")


@pytest.mark.parametrize("variant", [
    "Concerto grosso in A minor, HWV 322, Op 6 no 4",
    "Concerto grosso in A minor, Op 6 no 4 (HWV 322)",
    "Concerto grosso in A minor, Op 6 No 4 (HWV 322)",
])
def test_handel_op6_no4_hwv322_folds(variant):
    assert _same_group(variant, "Concerto Grosso in A minor, Op 6 no 4")


@pytest.mark.parametrize("variant", [
    "Concerto Grosso in Dmajor, HWV 323",
    "Concerto Grosso in D, HWV 323",
    "Concerto grosso in D major Op.6`5",
])
def test_handel_op6_no5_hwv323_folds(variant):
    assert _same_group(variant, "Concerto Grosso in D major, Op 6 no 5")


@pytest.mark.parametrize("variant", [
    "Concerto Grosso in B flat Op.6 No.7",
    "Concerto Grosso in B flat, Op 6 No 7",
])
def test_handel_op6_no7_hwv325_folds(variant):
    assert _same_group(variant,
                       "Concerto grosso in B flat major Op.6 No.7 HWV.325")


def test_handel_op6_no11_hwv329_backtick_folds():
    assert _same_group("Concerto grosso in A major, Op.6`11",
                       "Concerto Grosso in A major (Op.6 No.11)")


@pytest.mark.parametrize("variant", [
    "Sonata in F major Op 1 No 5",
    "Oboe Sonata in F major Op 1 No 5",
])
def test_handel_op1_no5_hwv363a_folds(variant):
    assert _same_group(variant,
                       "Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc")


@pytest.mark.parametrize("variant", [
    "Oboe Sonata Op 1 No 4",
    "Oboe Sonata, Op 1 no 4",
    "Oboe Sonata Op.1 No.4",
    "Oboe Sonata in A minor Op.1 No.4",
    "Oboe Sonata in A minor, Op.1 No.4",
])
def test_handel_hwv362_no_hwv_oboe_variants_fold(variant):
    """Pellerin's no-HWV oboe forms join the HWV.362 canonical (which
    already absorbs Lorenz's violin forms + the HWV-coded oboe alias).
    Recorder forms stay split — see [[hwv362-alt-scoring-deferred]]."""
    assert _same_group(variant,
                       "Violin Sonata in A minor (Op.1 No.4) (HWV.362)")


def test_handel_hwv362_recorder_stays_separate():
    """Roed's recorder forms remain in §hwv362|362|aminor — the parked
    decision is whether to extend the scoring fold further."""
    assert not _same_group(
        "Sonata in A minor HWV 362",
        "Violin Sonata in A minor (Op.1 No.4) (HWV.362)")


def test_handel_op1_no7_hwv365_folds():
    assert _same_group(
        "Sonata in C major, Op 1 No 7",
        "Sonata for recorder and continuo (HWV.365) (Op.1`7) in C major")


def test_handel_op5_no4_hwv399_folds():
    assert _same_group(
        "Trio Sonata in G major, Op 5 No 4",
        "Trio Sonata in G major (HWV 399) for 2 violins, viola and continuo Op 5 No 4")


def test_handel_hwv430_harmonious_blacksmith_piano_suite_quirk_folds():
    assert _same_group(
        'Aria with variations from Piano Suite No.5 in E major (HWV.430) "The harmonious blacksmith"',
        "Aria with Variations, HWV 430 'Harmonious Blacksmith'")


def test_handel_hwv237_laudate_pueri_key_sig_folds():
    assert _same_group("Laudate pueri Dominum in D, HWV 237",
                       "Laudate pueri Dominum, HWV 237")


@pytest.mark.parametrize("variant", [
    "Gentle Morpheus, son of night (Calliope's song) from 'Alceste' (HWV.45)",
    "Gentle Morpheus, Son of Night (Calliope's song) from 'Alceste' (HWV.45)",
])
def test_handel_hwv45_gentle_morpheus_folds(variant):
    assert _same_group(variant,
                       "Gentle Morpheus, son of night (Calliope's song) from Alceste")


@pytest.mark.parametrize("variant", [
    "'Va tacito e nascosto' (Giulio Cesare)",
    "'Va tacito e nascosto' (from Giulio Cesare in Egitto)",
    "'Va tacito e nascosto' from 'Giulio Cesare in Egitto'",
])
def test_handel_va_tacito_folds(variant):
    assert _same_group(variant,
                       "Caesar's aria: 'Va tacito e nascosto' (from 'Giulio Cesare in Egitto', Act 1 Sc.9)")


@pytest.mark.parametrize("variant", [
    "Piangerò la sorte mia, from 'Giulio Cesare, HWV.17'",
    "Piangerò la sorte mia (excerpt 'Giulio Cesare', HWV 17)",
    "Cleopatra's aria: 'Piangerò la sorte mia' - from 'Giulio Cesare', Act 3 Scene 3",
])
def test_handel_piangero_la_sorte_token_sort_phrasings_fold(variant):
    assert _same_group(variant,
                       "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)")


@pytest.mark.parametrize("title", [
    "Piangerò la sorte mia (Giulio Cesare, HWV 17)",
    "Chaconne (Almira, HWV 1)",
    "Jesu, joy of man's desiring (Cantata BWV 147)",
    "The Arrival of the Queen of Sheba (Solomon, HWV 67)",
    "Tu del ciel ministro eletto (Il Trionfo del Tiempo e del Disinganno, HWV 46a)",
    "Der Leiermann (Winterreise, D 311) for bassoon and piano",
])
def test_has_parent_work_reference_true_for_named_parent(title):
    """Parenthetical contains a catalogue ref + a name-like word (the
    parent work title). Routes vocal-whole titles to token-sort so they
    don't collide with the parent's catalogue-path key."""
    assert _has_parent_work_reference(title)


@pytest.mark.parametrize("title", [
    # Bare cat ref in parens — no parent name to identify
    "Concerto Grosso in G major, HWV 319 (Op 6 no 1)",
    "Aria with Variations, HWV.430 'Harmonious Blacksmith'",
    "Sonata for recorder and continuo (HWV.365) in C major",
    # Multi-cat-ref listing — collection enumeration, not parent ref
    "4 Schemelli Chorales (BWV.478, 484, 492 and 502)",
    # Within-form ordering in parens, no parent name
    "Brandenburg Concerto in G major (No 3, BWV 1048)",
    # No parens at all
    "Dixit Dominus, HWV 232",
    "Messiah, HWV 56",
    "Almira, HWV 1 (Dance Suite)",  # parenthetical has no cat ref
])
def test_has_parent_work_reference_false_for_annotations_or_listings(title):
    assert not _has_parent_work_reference(title)


def test_handel_piangero_catalogue_path_form_routes_to_token_sort():
    """The 'Piangerò la sorte mia (Giulio Cesare, HWV 17)' form was
    previously a catalogue-path FP grouped with 'Suite from Giulio
    Cesare in Egitto, HWV 17' under key §hwv17|17|. The
    _has_parent_work_reference gate routes it to the token-sort path
    instead, where an alias folds it with the other Piangerò phrasings."""
    from ttn_analyze import work_title_key
    aria = work_title_key("Piangerò la sorte mia (Giulio Cesare, HWV 17)")
    suite = work_title_key("Suite from Giulio Cesare in Egitto, HWV 17")
    assert aria != suite
    assert not aria.startswith("§")  # token-sort, not catalogue
    assert suite.startswith("§")     # catalogue, with form word "suite"


def test_handel_piangero_catalogue_form_folds_with_other_phrasings():
    """The catalogue-form now folds with the other 4 Piangerò phrasings
    via a real alias (added once the structural FP was removed)."""
    assert _same_group(
        "Piangerò la sorte mia (Giulio Cesare, HWV 17)",
        "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)")


@pytest.mark.parametrize("variant", [
    "Cara sposa, aria from Rinaldo",
    "Cara sposa - aria from Rinaldo",
    "Cara sposa - aria from 'Rinaldo'",
    "Cara sposa, (Rinaldo)",
    "Cara sposa (Rinaldo)",
])
def test_handel_cara_sposa_folds(variant):
    assert _same_group(variant,
                       "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)")


@pytest.mark.parametrize("variant", [
    "Lascia ch'io pianga (from Act 2 Sc 2 of 'Rinaldo' HWV.7)",
    "Almirena's aria 'Lascia ch'io pianga' from Act 2 Sc.2 of 'Rinaldo' (HWV.7)",
])
def test_handel_lascia_chio_pianga_folds(variant):
    assert _same_group(variant,
                       "Lascia ch'io pianga from Act 2 Sc.2 of Rinaldo (HWV.7)")


@pytest.mark.parametrize("variant", [
    "Radamisto (excerpt 'Già che morir non posso')",
    "'Già che morir non posso' – aria from Radamisto",
    'Aria "Già che morir non posso" - from \'Radamisto\'',
])
def test_handel_gia_che_morir_folds(variant):
    assert _same_group(variant, "Già che morir non posso - from 'Radamisto'")


@pytest.mark.parametrize("variant", [
    "Aria \"Ombra mai fu\" from Act 1 of the opera 'Serse'",
    "Serse (Ombra mai fu, Act 1) HWV 40",
    "Ombra mai fu (Serse, HWV 40 Act 1)",
    "Ombra mai fu – from the opera \"Xerxes\"",
    "'Ombra mai fu' from the opera 'Xerxes', arr. for piano",
])
def test_handel_ombra_mai_fu_folds(variant):
    assert _same_group(variant,
                       "\"Ombra mai fu\" - from the opera 'Xerxes' arr. for piano")


def test_handel_rejoice_greatly_messiah_folds():
    assert _same_group(
        "Rejoice Greatly, O Daughter of Sion (Messiah)",
        "Rejoice greatly, O daughter of Zion' (aria from \"The Messiah\")")


@pytest.mark.parametrize("variant", [
    'Aria "Lascia la spina" - from the oratorio Il Trionfo del Tempo e del Disinganno',
    'Aria \'Lascia la spina\' - from the oratorio "Il Trionfo del Tempo e del Disinganno"',
    "Lascia la spina cogli la rose, from 'Il Trionfo del tempo e del disinganno'",
    "Lascia la spina cogli la rose, from Il Trionfo del Tempo e del disinganno, HWV.46a",
    "Lascia la spina, cogli la rosa, from 'Il Trionfo del Tempo e del Disinganno'",
    "Lascia la spina, from 'Almira', HWV 1",
    "Lascia la spina - from Il trionfo del Tempo e del Disinganno",
])
def test_handel_lascia_la_spina_folds(variant):
    assert _same_group(variant,
                       "Lascia la spina, from Il Trionfo del tempo e del disinganno")


def test_handel_lascia_la_spina_almira_vocal_does_not_drag_almira_suite():
    """The Lezhneva 'Lascia la spina, from Almira, HWV 1' vocal folds
    into the Il Trionfo group via the token-sort path (it carries 'from'
    as an excerpt locator). The instrumental Almira HWV 1 (Dance Suite /
    Chaconne, key §hwv1|1|) must stay separate."""
    assert not _same_group("Lascia la spina, from 'Almira', HWV 1",
                           "Almira, HWV 1 (Dance Suite)")
    assert not _same_group("Lascia la spina, from 'Almira', HWV 1",
                           "Chaconne (Almira, HWV 1)")


def test_handel_lascia_la_spina_does_not_fuse_with_lascia_chio_pianga():
    """Same melody, different text — the Rinaldo retext stays its own
    group per the user's musicological call."""
    assert not _same_group(
        "Lascia la spina, from Il Trionfo del tempo e del disinganno",
        "Lascia ch'io pianga from Act 2 Sc.2 of Rinaldo (HWV.7)")


@pytest.mark.parametrize("variant", [
    "\"Tu del Ciel ministro eletto\" - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
    "Tu del ciel ministro eletto - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
    "Tu, del ciel ministro eletto from 'Il Trionfo del Tempo e del Disinganno'",
    "Tu, del ciel ministro eletto",
])
def test_handel_tu_del_ciel_folds(variant):
    assert _same_group(variant,
                       "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')")


def test_handel_chaconne_almira_stays_split_from_dance_suite():
    """The Chaconne is one movement of the Almira Dance Suite. The
    _has_parent_work_reference gate routes "Chaconne (Almira, HWV 1)"
    to token-sort; that split is the intended state per the user's
    movement-vs-whole-work call. Same recording (Steger/La Cetra) but
    different scope of music — don't fold."""
    assert not _same_group(
        "Chaconne (Almira, HWV 1)",
        "Almira, HWV 1 (Dance Suite)")


@pytest.mark.parametrize("variant", [
    "Symphony No 4 in E flat major, WAB 104, 'Romantic'",
    "Symphony No 4 in E flat major, WAB.104, 'Romantic'",
])
def test_bruckner_sym4_wab_annotation_folds(variant):
    assert _same_group(variant,
                       "Symphony No.4 in E flat major, 'Romantic'")


def test_bruckner_sym5_wab_annotation_folds():
    assert _same_group("Symphony no 5 in B flat major, WAB 105",
                       "Symphony No. 5 in B flat")


def test_bruckner_sym6_wab_annotation_folds():
    assert _same_group("Symphony no 6 in A major, WAB 106",
                       "Symphony No 6 in A major")


@pytest.mark.parametrize("variant", [
    "Te Deum in C (1870)",
    "Te Deum",
])
def test_bruckner_te_deum_variants_fold(variant):
    assert _same_group(
        variant,
        "Te Deum for soloists, chorus and orchestra in C major")


def test_bruckner_2_graduals_punctuation_variant_folds():
    assert _same_group(
        "2 graduals for chorus: Locus iste; Christus Factus est",
        "2 graduals for chorus: Locus iste & Christus Factus est")


def test_bruckner_3_motets_parenthesis_variant_folds():
    assert _same_group(
        "Ave Maria; Christus factus est; Locus iste (motets)",
        "3 Motets: Ave Maria; Christus factus est; Locus iste")


def test_bruckner_psalm150_wab_dot_space_folds():
    assert _same_group("Psalm 150, WAB.38", "Psalm 150, WAB 38")


def test_bruckner_mass3_wab_dot_space_folds():
    assert _same_group("Mass no 3 in F minor, WAB.28",
                       "Mass no 3 in F minor, WAB 28")


def test_bruckner_sym3_schalk_revision_stays_split():
    """Bruckner symphony versions are a deliberate split — different
    versions of the same symphony are treated as different works.
    Parked decision (see Schumann Sym 4 1841/1851 batch)."""
    assert not _same_group(
        "Symphony no.3 in D minor rev. composer and Schalk",
        "Symphony no 3 in D minor")


def test_bruckner_sym2_1877_version_stays_split():
    assert not _same_group(
        "Symphony No 2 in C minor (1877 version)",
        "Symphony no 2 in C minor")


def test_schumann_op73_phantasiestucke_extended_scoring_folds():
    assert _same_group(
        "Fantasiestücke for clarinet (violin or cello) and piano, Op 73",
        "Phantasiestucke Op 73 for clarinet & piano")


def test_schumann_op18_arabeske_english_spelling_folds():
    assert _same_group("Arabesque, Op 18",
                       "Arabeske for piano in C major, Op 18")


@pytest.mark.parametrize("variant", [
    "Widmung S.566, transc. for piano",
    "Widmung from Liederkreise, S.566",
])
def test_schumann_widmung_s566_liszt_transcription_folds(variant):
    assert _same_group(variant, "Widmung S.566, transcribed for piano")


def test_schumann_op133_gesange_extended_subtitle_folds():
    assert _same_group(
        "Gesänge der Frühe (Chants de l'Aube) (Op.133) - 5 pieces for piano dedicated to the poet Bettina Brentano",
        "Gesange der Fruhe - Songs of Dawn, Op 133")


@pytest.mark.parametrize("variant", [
    "5 Gedichte der Konigen Maria Stuart (5 Poems of Queen Mary Stuart), Op 135",
    "Gedichte der Königin Maria Stuart, Op 135",
])
def test_schumann_op135_mary_stuart_spellings_fold(variant):
    assert _same_group(
        variant,
        "5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135")


def test_schumann_violin_concerto_op_posthumous_word_order_folds():
    assert _same_group(
        "Concerto for Violin and Orchestra in D minor (Op.posthumous)",
        "Violin Concerto in D minor (Op.posthumous)")


@pytest.mark.parametrize("variant", [
    "Koncertstuck in F major for 4 Horns and Orchestra, Op 86",
    "Konzertstück for four horns and Orchestra, Op.86",
])
def test_schumann_op86_konzertstuck_variants_fold(variant):
    assert _same_group(
        variant,
        "Konzertstück in F major for 4 Horns and Orchestra, Op 86")


def test_schumann_op85_abendlied_slash_form_folds():
    assert _same_group("Abendlied, op. 85/12", "Abendlied, Op 85 no 12")


def test_schumann_op92_introduction_allegro_keysig_folds():
    assert _same_group(
        "Introduction and Allegro appassionato in G major Op 92",
        "Introduction and Allegro appassionato (Op.92)")


def test_schumann_op126_klavierstucke_excerpts_form_folds():
    assert _same_group(
        "7 Klavierstucke in Fughettenform Op.126 for piano (excerpts)",
        "7 Klavierstucke in Fughettenform Op.126 for piano (nos.5-7)")


def test_schumann_op48_dichterliebe_individual_songs_stay_split():
    """Op 48 is in the cycle-token list — individual songs of
    Dichterliebe legitimately stay split."""
    whole = "Dichterliebe for voice and piano, Op 48"
    assert not _same_group(
        "Hor' ich das Liedchen klingen - from Dichterliebe Op 48 No 10",
        whole)


def test_mendelssohn_hebrides_short_form_folds():
    assert _same_group("Hebrides - overture", "The Hebrides, Op 26")


@pytest.mark.parametrize("variant", [
    "Quartet for strings No 2 Op 13 in A minor",
    "String Quartet No 2 in A major, Op 13",
])
def test_mendelssohn_op13_string_quartet_folds(variant):
    assert _same_group(variant, "String Quartet no 2 in A minor, Op 13")


def test_mendelssohn_op14_rondo_capriccioso_word_order_folds():
    assert _same_group(
        "Rondo capriccioso for piano in E major/minor (Op.14)",
        "Rondo capriccioso in E major/minor, Op 14")


def test_mendelssohn_op15_fantasia_fantasy_spelling_folds():
    assert _same_group(
        "Fantasy on an Irish Song 'The Last Rose of Summer', Op.15",
        "Fantasia on an Irish song \"The last rose of summer\" for piano Op 15")


@pytest.mark.parametrize("variant", [
    "Meeresstille und gluckliche Fahrt (Calm sea and a prosperous voyage) - overture (Op.27)",
    "Calm Sea and a Prosperous Voyage - overture, Op.27",
])
def test_mendelssohn_op27_meeresstille_folds(variant):
    assert _same_group(variant,
                       "Meeresstille und gluckliche Fahrt - Overture, Op 27")


def test_mendelssohn_op32_melusine_english_folds():
    assert _same_group("The Fair Melusina, op. 32, overture",
                       "Die schöne Melusine  - overture Op 32")


def test_mendelssohn_op36_st_paul_overture_word_order_folds():
    assert _same_group("Overture to 'St Paul', Op 36",
                       "St.Paul, Op 36, Overture")


@pytest.mark.parametrize("variant", [
    "Laudate Pueri - motet, Op.39'2",
    "Motet: Laudate Pueri (O praise the Lord), Op 39 No 2",
])
def test_mendelssohn_op39_laudate_pueri_folds(variant):
    assert _same_group(variant, "Laudate Pueri - motet, Op 39 no 2")


def test_mendelssohn_op44_string_quartet_backtick_folds():
    assert _same_group("Quartet for strings in D major, Op.44'1",
                       "Quartet for strings in D major, Op  44 no 1")


def test_mendelssohn_op54_variations_serieuses_folds():
    assert _same_group("Variations Serieuses, Op54",
                       "Variations serieuses in D minor (Op.54) (1841)")


def test_mendelssohn_op56_scottish_short_form_folds():
    assert _same_group("Symphony No.3 in A minor, 'Scottish'",
                       "Symphony no 3 in A minor, Op 56 'Scottish'")


def test_mendelssohn_op61_midsummer_excerpts_form_folds():
    assert _same_group(
        "Excerpts from 'A Midsummer Night's Dream, op. 61' (incidental music)",
        "A Midsummer Night's Dream - incidental music (Op.61)")


def test_mendelssohn_op61_midsummer_suite_phrasings_fold():
    assert _same_group("A Midsummer Night's Dream, suite, op. 61",
                       "Suite from 'A Midsummer Night's Dream', Op.61")


def test_mendelssohn_op61_midsummer_incidental_vs_suite_stay_split():
    """The incidental music as a whole and the concert Suite are
    distinct curations — keep them as separate groups."""
    assert not _same_group(
        "A Midsummer Night's Dream - incidental music (Op.61)",
        "Suite from 'A Midsummer Night's Dream', Op.61")


def test_mendelssohn_op64_violin_concerto_word_order_folds():
    assert _same_group(
        "Concerto for violin and orchestra in E minor (Op.64)",
        "Violin Concerto in E minor, Op 64")


def test_mendelssohn_op66_piano_trio_word_order_folds():
    assert _same_group(
        "Trio for piano and strings No.2 (Op.66) in C minor",
        "Piano Trio no 2 in C minor, Op 66")


def test_mendelssohn_op81_capriccio_no3_form_folds_with_backtick():
    assert _same_group("Capriccio in E minor, Op 81 no 3",
                       "Capriccio in E minor, Op.81`3")


def test_mendelssohn_op87_string_quintet_short_form_folds():
    assert _same_group("String Quintet in B flat, op. 87",
                       "String Quintet No 2 in B flat major, Op 87")


def test_mendelssohn_op107_reformation_d_minor_typo_folds():
    """The Reformation Symphony IS in D major; the BBC's "D minor"
    annotation on some airings is a typo. Same edge case as Mahler
    Symphony 1 'Titan' implicit-major handling."""
    assert _same_group(
        "Symphony no 5 in D minor, op 107 'Reformation'",
        'Symphony No.5 in D major "Reformation" (Op.107)')


def test_mendelssohn_op109_song_without_words_english_folds():
    assert _same_group("Song Without Words, Op 109",
                       "Lied ohne Worte in D major, Op 109")


def test_mendelssohn_hora_est_long_form_folds():
    assert _same_group("Hora est (antiphon and responsorium)", "Hora est")


def test_mendelssohn_op78_richte_mich_psalm43_form_folds():
    assert _same_group(
        "Richte mich, Gott (Psalm 43), from 3 Psalmen, Op 78",
        "Richte mich, Gott, Op 78 no 2")


def test_mendelssohn_op42_psalm42_long_subtitle_folds():
    assert _same_group(
        "Psalm 42 'Wie der Hirsch schreit nach frischem Wasser, op. 42'",
        "Psalm 42 'Wie der Hirsch schreit', Op 42, cantata")


def test_mendelssohn_denn_er_hat_engeln_befohlen_folds():
    assert _same_group(
        "Denn er hat seinen Engeln befohlen, from 'Elias'",
        "Denn er hat seinen Engeln befohlen")


def test_vivaldi_rv595_dixit_dominus_no_rv_folds():
    assert _same_group(
        "Dixit Dominus for SSATB soloists and double choir and orchestra in D major",
        "Dixit Dominus in D major, RV.595")


@pytest.mark.parametrize("variant", [
    "Magnificat RV 610/RV 611",
    "Magnificat in G minor, RV.610, for SSAT soloists, choir, 2 oboes, strings and continuo",
])
def test_vivaldi_rv610_magnificat_folds(variant):
    assert _same_group(variant, "Magnificat in G minor, RV 610")


def test_vivaldi_rv93_lute_concerto_short_form_folds():
    assert _same_group(
        "Lute Concerto in D major, RV 93",
        "Concerto for lute, 2 violins & continuo in D major, RV.93")


def test_vivaldi_rv178_op8_no12_keysig_annotation_folds():
    assert _same_group(
        "Violin Concerto in C major, Op 8 No 12 (RV 178)",
        "Violin Concerto, Op 8 No 12, RV 178")


@pytest.mark.parametrize("variant", [
    "Concerto for 4 violins, cello and orchestra in F major, RV.567",
    "Concerto for four violins & basso continuo in F, Op.3 No.7, RV.567",
])
def test_vivaldi_rv567_op3_no7_folds(variant):
    assert _same_group(
        variant,
        "Concerto for 4 violins, cello and orchestra (RV.567) Op 3 No 7 in F major")


def test_vivaldi_rv315_lestate_bare_folds():
    assert _same_group(
        "Concerto for violin & orchestra in G minor 'L'Estate', RV.315",
        "Concerto for violin & orchestra (RV.315) (Op.8 No.2) in G minor 'L'Estate'")


def test_vivaldi_rv315_lestate_movement_excerpt_stays_split():
    """A single-movement excerpt of L'Estate is a different scope from
    the whole concerto."""
    assert not _same_group(
        "Presto from Violin Concerto no.2 'L'Estate', RV315",
        "Concerto for violin & orchestra (RV.315) (Op.8 No.2) in G minor 'L'Estate'")


@pytest.mark.parametrize("variant", [
    "Psalm: Nisi Dominus, RV.608",
    "Nisi Dominus in G minor, RV 608",
])
def test_vivaldi_rv608_nisi_dominus_folds(variant):
    assert _same_group(variant,
                       "Nisi Dominus (Psalm 127) for voice and orchestra (RV.608)")


def test_vivaldi_rv108_sopranino_recorder_variant_folds():
    assert _same_group(
        "Concerto for sopranino recorder, two violins and continuo, RV 108",
        "Concerto in A minor for recorder, two violins and basso continuo, RV 108")


def test_vivaldi_rv522_op3_no8_lestro_form_folds():
    assert _same_group(
        "Concerto VIII in A minor for 2 violins, strings and continuo, RV 522, from 'L'estro Armonico', Op 3",
        "Concerto VIII in A minor for 2 violins, strings and continuo, RV 522")


def test_vivaldi_rv104_la_notte_extended_scoring_folds():
    assert _same_group(
        "Concerto in G minor, RV 104, (La notte) for flute, 2 violins, bassoon and continuo",
        "Flute Concerto in G minor, RV104 (La Notte)")


def test_vivaldi_rv293_lautunno_english_title_folds():
    assert _same_group(
        "Violin Concerto in F major, RV 293, 'Autumn'",
        "Concerto for violin & orchestra RV.293 Op 8 No 3 in F major 'L'Autunno'")


def test_vivaldi_rv230_op3_no9_roman_numeral_form_folds():
    assert _same_group(
        "Concerto IX in D major (RV.230), from 'L'Estro Armonico', Op 3",
        "Violin Concerto in D (Op.3 No.9) (RV.230)")


def test_vivaldi_sonata_a_quattro_extended_scoring_folds():
    assert _same_group(
        "Sonata a quattro in C major for 2 oboes, bassoon & continuo",
        "Sonata a quattro in C major")


def test_vivaldi_op3_siblings_stay_split():
    """L'Estro Armonico Op 3 has 12 distinct concertos. The
    set-catalogue flag steered us away from collapsing them — these
    guards lock that decision in."""
    assert not _same_group(
        "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'",
        "Violin Concerto in D (Op.3 No.9) (RV.230)")
    assert not _same_group(
        "Violin Concerto in D (Op.3 No.9) (RV.230)",
        "Concerto for 4 violins, cello and orchestra (RV.567) Op 3 No 7 in F major")


@pytest.mark.parametrize("variant", [
    "Concerto in D minor for 2 violins, cello and orchestra RV.565 Op 3 No 11",
    "Concerto in D minor (Op.3 No.11) from 'L'Estro",
    "Concerto in D minor, RV.565",
    "Concerto in D minor for 2 violins, cello and orchestra RV.565",
    "Concerto in D minor, RV.565 Op 3 no 11",
])
def test_vivaldi_rv565_op3_no11_folds(variant):
    """First catch from ttn_audit_composer Pass 1b — the
    catalogue-bearing form bridged via Op 3 No 11 ↔ RV.565."""
    assert _same_group(variant,
                       "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'")


def test_mahler_ruckert_lieder_collection_phantom_5_folds():
    assert _same_group("Rückert-Lieder", "5 Ruckert-Lieder")


@pytest.mark.parametrize("variant", [
    "Ich bin der Welt abhanden gekommen, from 'Rückert-Lieder",
    "Ich bin der Welt abhanden gekommen, from 'Rückert-Lieder'",
])
def test_mahler_ich_bin_der_welt_phrasings_fold(variant):
    assert _same_group(variant,
                       "Ich bin der Welt abhanden gekommen (Rückert Lieder)")


def test_mahler_ich_ging_mit_lust_with_source_paren_folds():
    assert _same_group(
        "Ich ging mit Lust durch einen grünen Wald (I walked with joy through a green forest) (no.7 from Lieder und Gesänge aus der Jugendzeit)",
        "Ich ging mit lust durch einen grunen Wald")


def test_mahler_symphony_1_titan_implicit_major_bare_folds():
    """`_drop_implicit_major` strips "major" after "in <note>" but bare
    "D major" (without "in") doesn't match. Alias bridges the gap."""
    assert _same_group("Symphony No.1 D major, 'Titan'",
                       "Symphony no 1 in D major, 'Titan'")


def test_mahler_symphony_2_resurrection_verbose_scoring_folds():
    assert _same_group(
        "Symphony No.2 in C minor for soprano, alto, chorus and orchestra \"Resurrection\"",
        "Symphony No. 2 in C minor ('Resurrection')")


def test_mahler_adagietto_short_form_folds():
    assert _same_group("Adagietto, from Symphony No. 5",
                       "Adagietto, from Symphony no 5 in C sharp minor")


def test_mahler_symphony_10_adagio_phrasings_fold():
    assert _same_group(
        "Symphony No 10 (Adagio)",
        "Adagio, from 'Symphony No. 10 in F sharp' (unfinished)")


@pytest.mark.parametrize("variant", [
    "Songs from 'Des Knaben Wunderhorn'",
    "Songs from Des Knaben Wunderhorn",
])
def test_mahler_des_knaben_wunderhorn_collection_folds(variant):
    assert _same_group(variant, "Des Knaben Wunderhorn")


def test_mahler_des_knaben_wunderhorn_individual_songs_stay_split():
    """Individual Wunderhorn songs (Rheinlegendchen, Verlorne Müh, etc.)
    are separate works from the whole collection — don't fuse."""
    whole = "Des Knaben Wunderhorn"
    assert not _same_group("Rheinlegendchen, from 'Des Knaben Wunderhorn'", whole)
    assert not _same_group("Verlorne Müh, from 'Des Knaben Wunderhorn'", whole)


def test_mahler_kindertotenlieder_individual_songs_stay_split():
    """Individual songs of Kindertotenlieder are distinct works from
    the collection (parallel to Rückert-Lieder, Schwanengesang)."""
    whole = "Kindertotenlieder"
    assert not _same_group(
        "Nun seh'ich wohl warum so dunkle Flammen (Kindertotenlieder)", whole)
    assert not _same_group(
        "Oft denk' ich, sie sind nur ausgegangen (Kindertotenlieder)", whole)


@pytest.mark.parametrize("variant", [
    "Arpeggione Sonata in A minor",
    "Arpeggione Sonata",
])
def test_schubert_d821_arpeggione_bare_forms_fold(variant):
    assert _same_group(variant,
                       "Sonata in A minor D.821 for arpeggione (or viola or cello) and piano")


def test_schubert_d780_moments_musicaux_whole_collection_folds():
    assert _same_group("6 Moments Musicaux (D.780)",
                       "Six Moments musicaux, D. 780")


def test_schubert_d780_individual_movement_stays_split():
    """Individual movement of Moments musicaux stays its own group
    (set-catalogue: each movement is a distinct work)."""
    assert not _same_group(
        "Six Moments musicaux, D.780: no 3 in F minor",
        "Six Moments musicaux, D. 780")


def test_schubert_d703_quartettsatz_movement_form_folds():
    assert _same_group(
        "Quartettsatz (movement) for strings in C minor (D.703)",
        "Quartettsatz in C minor, D.703")


def test_schubert_d774_barcarolle_alt_title_folds():
    assert _same_group("Barcarolle (Auf dem Wasser zu singen)",
                       "Auf dem Wasser zu singen, D.774")


@pytest.mark.parametrize("variant", [
    "Ständchen arr. for piano - from Schwanengesang (D. 957)",
    "Standchen from Schwanengesang (D.957)",
    "Ständchen, D.957'4",
    "Ständchen, D. 957/4",
])
def test_schubert_d957_standchen_phrasings_fold(variant):
    assert _same_group(variant, "Standchen, D957")


def test_schubert_d957_other_schwanengesang_songs_stay_split():
    """Other songs from Schwanengesang are DIFFERENT works — D.957 is
    a song cycle (in the cycle denylist), each song has its own identity."""
    assert not _same_group("Standchen, D957",
                           "Der Atlas from \"Schwanengesang\" (D.957)")
    assert not _same_group("Standchen, D957",
                           "Die Taubenpost, from 'Schwanengesang, D. 957'")


def test_schubert_d810_death_and_maiden_bare_form_folds():
    assert _same_group(
        "String Quartet in D minor, D810 'Death and the Maiden'",
        "String Quartet No 14 in D minor, D 810 'Death and the Maiden'")


def test_schubert_d810_mahler_arrangement_stays_split():
    """Mahler's string-orchestra arrangement of D.810 stays split —
    composer-non-authored alt-scoring per scoring-policy."""
    assert not _same_group(
        "'Death and the Maiden' Quartet, D810, arranged by Mahler for string orchestra",
        "String Quartet No 14 in D minor, D 810 'Death and the Maiden'")


def test_schubert_d312b_hektors_op58_folds():
    assert _same_group("Hektors Abschied (D.312b, Op.58 No.1)",
                       "Hektors Abschied D.312b")


def test_schubert_d544_ganymed_op19_folds():
    assert _same_group("Ganymed (D.544) - from 3 Songs (Op.19 No.3)",
                       "Ganymed, D.544")


def test_schubert_d161_an_mignon_op19_folds():
    assert _same_group(
        "An Mignon (D.161) from 3 Songs, Op 19 no 2 (To Mignon)",
        "An Mignon from 3 Songs, D.161")


def test_schubert_s366_wandererfantasie_liszt_phrasings_fold():
    """Liszt's S.366 transcription of Schubert's D.760 — the two
    phrasings fold. The Schubert original D.760 stays split (different
    work)."""
    assert _same_group(
        "Wandererfantasie, transcribed for piano and orchestra (S.366)",
        "Wandererfantasie, D760 arranged by Liszt (S.366)")


@pytest.mark.parametrize("variant", [
    "Der Hirt auf dem Felsen, Op.129 (D965)",
    "Der Hirt auf dem Felsen, Op.129",
])
def test_schubert_d965_hirt_op129_folds(variant):
    assert _same_group(variant, "Der Hirt auf dem Felsen, D965")


def test_schubert_d478_einsamkeit_typo_folds():
    assert _same_group(
        "Wer sich der Einsamkeit ergibit (D.478) from Three Songs of the Harpist Op 12",
        "Wer sich der Einsamkeit ergibt (D.478) from Three Songs of the Harpist")


@pytest.mark.parametrize("variant", [
    "Winterreise, D.911 (arr. for voice & piano trio)",
    "Winterreise - song-cycle, D.911",
])
def test_schubert_d911_winterreise_whole_cycle_phrasings_fold(variant):
    assert _same_group(variant, "Winterreise, D.911")


def test_schubert_d911_individual_winterreise_songs_stay_split():
    """Individual songs from Winterreise stay their own groups — D.911
    is in the cycle denylist for exactly this reason."""
    assert not _same_group(
        "Gute Nacht - No.1 from Winterreise (song-cycle) (D.911)",
        "Winterreise, D.911")
    assert not _same_group(
        "Der Leiermann - No.24 from Winterreise (song-cycle) (D.911)",
        "Winterreise, D.911")


def test_schubert_3_songs_between_songs_annotation_folds():
    assert _same_group(
        "3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest (including between songs)",
        "3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest")


def test_schubert_d899_impromptus_stay_split_across_numbers():
    """D.899 is 4 different impromptus distinguished by key signature —
    legitimate set-catalogue split, do NOT fuse."""
    no2_eflat = "Impromptu No 2 in E Flat, D899"
    no3_gflat = "Impromptu in G flat major, D899 no 3"
    no4_aflat = "Impromptu in A flat d 899/4"
    assert not _same_group(no2_eflat, no3_gflat)
    assert not _same_group(no3_gflat, no4_aflat)
    assert not _same_group(no2_eflat, no4_aflat)


def test_bach_bwv4_christ_lag_annotation_paren_folds_back():
    """`_has_parent_work_reference` fires on "(Cantata BWV 4)" because
    "Cantata" reads as a name-like word, but semantically the title is
    annotation (Christ lag IS BWV 4). Alias folds it back into the
    §bwv4|4| canonical."""
    assert _same_group(
        "Christ lag in Todesbanden (Cantata BWV 4)",
        "Cantata 'Christ lag in Todesbanden', BWV 4")


def test_handel_op6_concerto_grossi_stay_split_across_numbers():
    """Sibling Op 6 concerti grossi must NOT fuse — they are distinct
    works under different HWV numbers."""
    op6_no4 = "Concerto Grosso in A minor, Op 6 no 4"
    op6_no5 = "Concerto Grosso in D major, Op 6 no 5"
    op6_no7 = "Concerto grosso in B flat major Op.6 No.7 HWV.325"
    op6_no11 = "Concerto Grosso in A major (Op.6 No.11)"
    assert not _same_group(op6_no4, op6_no5)
    assert not _same_group(op6_no5, op6_no7)
    assert not _same_group(op6_no7, op6_no11)
    assert not _same_group(op6_no4, op6_no11)


# --- instrumental movement-excerpt marker (2026-05-29) ----------------------

def test_movement_slug_named_movement():
    assert _movement_slug("Sarabande from Cello Suite No 3 in C, BWV 1009") == "sarabande"
    assert _movement_slug("Largo, from 'Violin Sonata No. 3 in C, BWV 1005'") == "largo"


def test_movement_slug_combined_movements_sorted():
    assert _movement_slug("Adagio and Fugue, from Toccata … in C major, BWV.564") == "adagio,fugue"


def test_movement_slug_numbered_movement_uses_name_when_present():
    assert _movement_slug("Adagio, 2nd movement from Piano Quartet no 1 in G minor, K.478") == "adagio"


def test_movement_slug_ordinal_when_no_name():
    assert _movement_slug("Symphony No. 15 in G, K. 124 (4th mvt - encore)") == "4"


def test_movement_slug_generic_excerpt():
    assert _movement_slug("Piano Sonata in C major, K.545 (excerpt)") == "excerpt"


def test_movement_slug_rondo_excerpt():
    # 'rondo' is in the gate vocabulary: Rondo movement excerpts split from
    # their whole work and collapse across phrasings.
    assert _movement_slug("Rondo from Flute Quartet in D, K 285") == "rondo"
    assert not _same_group("Rondo from Flute Quartet in D, K 285",
                           "Flute Quartet in D major, K.285")
    assert _same_group(
        "Rondo alla turca, from Piano Sonata no.11 in A major, K.331",
        "Rondo alla Turca (3rd movement from Piano Sonata No 11 in A, K.331)")
    # whole works named "Rondo" (no "from") stay whole
    assert _movement_slug("Rondo in A minor, K.511") is None


def test_movement_slug_paren_from_excerpt():
    # "(from <parent>)" is a valid excerpt locator (the lead regex allows a
    # parenthesis before "from").
    assert _movement_slug("Chaconne (from Violin Partita No 2 in D minor, BWV 1004)") == "chaconne"
    assert _movement_slug("Rondo alla Turca (from Piano Sonata in A, K.331)") == "rondo"
    # so the last K.331 Rondo phrasing now joins the §k331|rondo group
    assert _same_group("Rondo alla Turca (from Piano Sonata in A, K.331)",
                       "Rondo alla turca, from Piano Sonata no.11 in A major, K.331")


def test_movement_slug_ref_before_from_is_whole_work():
    # A catalogue ref BEFORE "from" → the title carries its own work number
    # (a WTC prelude-and-fugue named "from Das Wohltemperierte Klavier"),
    # not a movement excerpt.
    assert _movement_slug(
        "Prelude and fugue No.5 in D major (BWV.874) from Das Wohltemperierte Klavier") is None
    assert _same_group(
        "Prelude & Fugue in B flat minor BWV867 (from Das Wohltemperierte Clavier)",
        "Prelude and Fugue in B flat minor, BWV 867")


def test_movement_slug_spelling_normalised():
    # siciliano→siciliana, aria→air so phrasings collapse
    assert _movement_slug("Siciliano, from Flute Sonata in G minor, BWV 1031") == "siciliana"
    assert _movement_slug("Aria from Orchestral Suite No 3 in D, BWV 1068") == "air"


def test_movement_slug_none_for_whole_tempo_named_works():
    # lead with a tempo name but no "from"/marker → whole work, not excerpt
    assert _movement_slug("Adagio and Fugue in C minor, K.546") is None
    assert _movement_slug("Rondo in A minor, K.511") is None
    assert _movement_slug("Scherzo No 1 in B flat, D.593") is None


def test_movement_slug_none_for_theme_variations():
    # "from <opera>" attributes the theme source, not an excerpt
    assert _movement_slug("Variations on 'Bei Männern, welche Liebe fühlen', WoO.46") is None
    assert _movement_slug("9 Variations on 'Quant' è più bello' for piano, from Paisiello") is None


def test_excerpt_split_from_whole_work():
    whole = "Cello Suite no 3 in C, BWV.1009"
    assert not _same_group("Sarabande from Cello Suite no 3 in C, BWV.1009", whole)
    assert not _same_group("Gigue from Cello Suite No 3 in C BWV 1009", whole)
    # the K.516 / Hob.XVI:37 cases the audits had to skip
    assert not _same_group("Adagio ma non troppo, from String Quintet no 4 in G minor, K.516",
                           "String Quintet in G minor, K.516")
    assert not _same_group("Allegro con brio, from Sonata in D, Hob. XVI:37",
                           "Keyboard Sonata in D major, Hob.XVI/37")


def test_excerpt_phrasings_collapse():
    # all wordings of one movement collapse (the marker-key payoff)
    a = "Sarabande from Cello Suite no 3 in C, BWV.1009"
    b = "Sarabande from Suite for solo cello in C (BWV.1009)"
    c = "Sarabande, from Cello Suite No. 3 in C, BWV 1009"
    assert _same_group(a, b)
    assert _same_group(a, c)


def test_different_movements_of_one_work_stay_split():
    assert not _same_group("Sarabande from Cello Suite no 3 in C, BWV.1009",
                           "Gigue from Cello Suite no.3 in C, BWV.1009")


def test_bwv1056_arioso_reconstructions_merge():
    # same Largo/Arioso, two reconstructions (F minor harpsichord, G minor
    # violin) — keysig dropped, so they group
    assert _same_group("Largo from Harpsichord Concerto no 5 in F minor, BWV 1056",
                       "Largo, from Violin Concerto in G minor, BWV 1056")


def test_whole_tempo_named_work_unaffected():
    # K.546 "Adagio and Fugue" leads with a tempo name but is a WHOLE work
    # (no "from"/movement marker) → _movement_slug is None, it stays on the
    # catalogue path, and two same-key phrasings still group.
    assert _movement_slug("Adagio and Fugue in C minor, K.546") is None
    assert _same_group("Adagio and Fugue in C minor, K.546",
                       "Adagio and Fugue in C minor, K 546")


def test_cached_summary_and_audit_slots_coexist(tmp_path):
    from ttn_analyze import cached
    cache = str(tmp_path / "c.json")
    rows = [("Beethoven", "Symphony no 5", "e1")]
    calls = {"n": 0}

    def fake(_rows):
        calls["n"] += 1
        return {"value": calls["n"]}

    a1, hit1 = cached(rows, "summary", fake, cache_path=cache)
    a2, hit2 = cached(rows, "summary", fake, cache_path=cache)
    b1, _ = cached(rows, "audit", fake, cache_path=cache)
    assert (hit1, hit2) == (False, True)         # second summary call is a hit
    assert a1 == a2                              # same cached value
    assert b1["value"] != a1["value"]            # audit is a DIFFERENT slot
    assert calls["n"] == 2                       # summary computed once, audit once


# --- _resolve_mode ----------------------------------------------------------

def _args(**kw):
    base = dict(mode=None, summary=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_resolve_mode_contract():
    from ttn_analyze import _resolve_mode
    # bare invocation (no dash-flags) -> summary
    assert _resolve_mode(_args(), ["ttn.sqlite"]) == ("summary", None)
    # any dash-flag -> rank
    assert _resolve_mode(_args(), ["--by", "work"]) == ("rank", None)
    # --summary is an alias for --mode summary
    assert _resolve_mode(_args(summary=True), ["--summary"]) == ("summary", None)
    # explicit --mode wins
    assert _resolve_mode(_args(mode="audit"), ["--mode", "audit"]) == ("audit", None)
    # conflict surfaces a message, no mode
    mode, msg = _resolve_mode(_args(mode="rank", summary=True),
                              ["--mode", "rank", "--summary"])
    assert mode is None and "conflicts" in msg


# --- _invalid_modifiers -----------------------------------------------------

def _args_full(**kw):
    base = dict(mode=None, summary=False, by="work", composer=None, title=None,
                form=None, once=False, dates=False, csv=None, raw=False,
                after=None, before=None, year=None, christmas=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_invalid_modifiers():
    from ttn_analyze import _invalid_modifiers
    # rank accepts everything
    assert _invalid_modifiers(_args_full(top=10), "rank", ["--top", "10"]) == []
    # summary rejects rank-only flags, but date flags are fine
    assert _invalid_modifiers(_args_full(), "summary",
                              ["--summary", "--top", "5"]) == ["--top"]
    assert _invalid_modifiers(_args_full(year=2024), "summary",
                              ["--summary", "--year", "2024"]) == []
    # audit rejects rank-only AND date flags (whole-corpus v1)
    assert _invalid_modifiers(_args_full(year=2024), "audit",
                              ["--mode", "audit", "--year", "2024"]) == ["--year"]
    # explicit --by even at its default value is rejected in summary
    assert _invalid_modifiers(_args_full(by="work"), "summary",
                              ["--summary", "--by", "work"]) == ["--by"]


def test_alias_health_on_live_tables():
    from ttn_analyze import (_alias_health, _COMPOSER_ALIAS_PAIRS,
                             _WORK_ALIAS_PAIRS, canonical_key, work_title_key,
                             resolve_composer_alias, resolve_work_alias)
    ch = _alias_health(_COMPOSER_ALIAS_PAIRS, canonical_key,
                       resolve_composer_alias)
    wh = _alias_health(_WORK_ALIAS_PAIRS, work_title_key, resolve_work_alias)
    assert ch["n"] == len(_COMPOSER_ALIAS_PAIRS)
    assert ch["chained"] == 0 and ch["dead"] == 0     # invariants hold
    assert wh["chained"] == 0 and wh["dead"] == 0
    assert 0 < ch["targets"] <= ch["n"]


def test_compute_audit_variant_pressure():
    from ttn_analyze import compute_audit
    rows = [
        # ONE identity via diacritic fold (alias-independent), THREE distinct
        # original spellings -> variant pressure 3
        ("Antonín Dvořák", "Symphony No 9", "e1"),
        ("Antonin Dvořák", "Symphony No 9", "e2"),
        ("Antonín Dvorak", "Symphony No 9", "e3"),
        # a clean composer, one spelling
        ("Edward Elgar", "Cello Concerto in E minor, Op 85", "e4"),
    ]
    stats = compute_audit(rows)
    # alias-table health present
    assert stats["health"]["composer"]["chained"] == 0
    # the Dvořák group tops composer variant pressure with 3 distinct spellings
    top = stats["composer_variants"][0]
    assert top[1] == 3 and "vo" in top[0].lower()
    assert isinstance(stats["work_variants"], list)
    # candidates/spans keys exist (filled in Task 6)
    assert "candidates" in stats and "spans" in stats


def test_compute_audit_surname_discriminator():
    from ttn_analyze import compute_audit
    # Synthetic names, NOT in any alias table, so identities stay distinct and
    # the test exercises the subset/disjoint discriminator itself — not the
    # alias layer. (Real "Sir Edward Elgar" is already aliased to "Edward
    # Elgar", i.e. one identity, so it would NOT surface as a candidate.)
    rows = [
        ("Edmund Quibble", "W1", "e1"),
        ("Sir Edmund Quibble", "W2", "e2"),          # honorific -> candidate
        ("Robert Frobnitz", "W3", "e3"),
        ("Clara Frobnitz", "W4", "e4"),              # distinct given names -> NOT
        ("Johann Sebastian Wurgle", "W5", "e5"),
        ("Carl Philipp Wurgle", "W6", "e6"),         # distinct initials -> NOT
    ]
    stats = compute_audit(rows)
    cand_pairs = {frozenset((a, b)) for a, b, _na, _nb in stats["candidates"]}
    assert frozenset(("Edmund Quibble", "Sir Edmund Quibble")) in cand_pairs
    assert not any("Frobnitz" in a or "Frobnitz" in b
                   for a, b, _na, _nb in stats["candidates"])
    assert not any("Wurgle" in a or "Wurgle" in b
                   for a, b, _na, _nb in stats["candidates"])
    # informational spans: 'quibble' surname spans 2 distinct identities
    span_surnames = {s for s, _ids in stats["spans"]}
    assert "quibble" in span_surnames
    # internal scratch field dropped
    assert "_comp" not in stats


def test_compute_audit_candidate_noise_and_particles():
    from ttn_analyze import compute_audit
    # All synthetic names, not in any alias table.
    rows = [
        # 1. Attribution noise: Anonymous* rows must NOT surface as candidates.
        ("Anonymous", "W", "x1"),
        ("Anonymous, arr. Foo Bar", "W", "x2"),
        # 2. Attribution noise: Traditional/arr. must NOT produce candidates.
        ("Igor Testov", "W", "x3"),
        ("Traditional arr. Igor Testov", "W", "x4"),
        # 3. Middle-name variant IS a candidate (no noise tokens).
        ("Edward Quibble", "W", "x5"),
        ("Edward William Quibble", "W", "x6"),
        # 4. Nobiliary particle keeps distinct same-surname people apart.
        #    {von, blarp} is NOT a subset of {hans, blarp}, so no candidate.
        ("von Blarp", "W", "x7"),
        ("Hans Blarp", "W", "x8"),
    ]
    stats = compute_audit(rows)
    cand_pairs = {frozenset((a, b)) for a, b, _na, _nb in stats["candidates"]}

    # 1 & 2: no attribution-noise candidates
    assert not any(
        "anonymous" in (a + b).lower() or "traditional" in (a + b).lower()
        or " arr." in (a + b).lower()
        for a, b, _na, _nb in stats["candidates"]
    ), "attribution-noise keys must not appear in candidates"

    # 3: middle-name variant surfaces
    assert frozenset(("Edward Quibble", "Edward William Quibble")) in cand_pairs, \
        "middle-name variant should be a candidate"

    # 4: particle-bearing name not a candidate for bare-surname form
    assert not any("Blarp" in a or "Blarp" in b
                   for a, b, _na, _nb in stats["candidates"]), \
        "von Blarp vs Hans Blarp should NOT be a candidate (particle not stripped)"
