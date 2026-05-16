"""Tests for ttn_analyze canonicalization.

Run: uv run --with pytest pytest test_ttn_analyze.py
"""
import pytest

from ttn_analyze import (canonical_key, catalogue_ref, resolve_work_alias,
                         work_title_key)


# --- canonical_key -------------------------------------------------------

def test_canonical_key_nos_marker_kept_whole():
    # "Nos" must normalize as one marker — not match "no" and orphan an "s"
    assert canonical_key("Nos. 17-21") == "nos 17-21"
    assert canonical_key("nos.17-21") == "nos 17-21"


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
