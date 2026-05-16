"""Tests for ttn_analyze canonicalization.

Run: uv run --with pytest pytest test_ttn_analyze.py
"""
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


def test_schubert_erlkonig_arrangements_stay_distinct():
    # The violin and organ arrangements of Erlkönig are different works —
    # the two alias pairs above must not fuse them.
    assert not _same_group("Erlkönig, D. 328 arr. for violin",
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
