"""Tests for ttn_analyze canonicalization.

Run: uv run --with pytest pytest test_ttn_analyze.py
"""
import pytest

import re

from ttn_analyze import (canonical_key, catalogue_ref, parse_performers,
                         resolve_composer_alias, resolve_ensemble_alias,
                         resolve_work_alias, work_title_key,
                         _strip_arrangement_tail, _squash_separators,
                         _drop_implicit_major, _title_filter_pattern,
                         _normalize_title_filter, _form_filter_clauses,
                         _FORM_SYNONYMS)


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
    ['La Clemenza di Tito', 'La Clemenza di Tito (overture)'],
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


def test_bwv1006_arr_two_harps_folds():
    assert _same_group(
        "Prelude from Partita no 3 in E major (BWV 1006) arr. for 2 harps",
        "Partita for solo violin No.3 in E major, BWV.1006")


def test_bwv1007_bare_cello_suite_folds():
    assert _same_group("Sarabande from Suite for cello solo (BWV.1007) in G major",
                       "Suite for solo cello no 1 in G major (BWV 1007)")


def test_bwv1009_bare_cello_suite_folds():
    assert _same_group("Sarabande from Suite for solo cello in C (BWV.1009)",
                       "Suite for solo Cello No.3 in C major (BWV.1009)")


def test_bwv1005_suite_mislabel_folds():
    # The BBC mislabels BWV.1005 as "Suite for solo violin" on two airings;
    # it's a violin sonata. Catalogue ref pins identity.
    assert _same_group("Largo from Suite for solo violin no.3, BWV.1005",
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
    # BBC key-sig error: BWV.1055 is in A, not C. Catalogue ref pins identity.
    assert _same_group("Allegro from Concerto in C major, BWV.1055", main)


def test_rv428_goldfinch_phantom_op10no3_folds():
    assert _same_group(
        "Flute Concerto in D major, RV.428 (Op.10 No.3) ('Il Gardellino')",
        "Flute Concerto in D major, RV.428 ('Il Gardellino')")


def test_rv297_winter_phantom_op8no4_folds():
    main = "Violin Concerto in F minor, RV.297 'L'Inverno'"
    assert _same_group(
        "Violin Concerto in F minor, RV.297 (Op.8 No.4), arr. for accordion",
        main)
    assert _same_group(
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


def test_d940_originally_for_4_hands_folds():
    assert _same_group("Fantasia in F minor, D.940 (originally for 4 hands)",
                       "Fantasie in F minor for Piano Four Hands, D940")


def test_k298_bare_flute_quartet_folds():
    assert _same_group("Quartet for flute and strings (K 298) in A major",
                       "Flute Quartet no 4 in A major, K 298")


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
    assert _same_group("Piano Sonata in F major, K 332 (2nd mvt Adagio)", main)
    assert _same_group("Sonata for piano K.332 in F major", main)


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
    assert _same_group(
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


def test_mozart_k381_allegro_molto_folds():
    assert _same_group("Allegro Molto from Piano Sonata in D major, K.381",
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
