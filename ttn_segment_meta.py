#!/usr/bin/env python3
"""Segment-level curation constants shared by tools that read segment_events
(ttn_broadcasters, the most-repeated cut, …). Pure data — no heavy imports.

INTERSTITIAL_RECORDING_PIDS: BBC recording ids used as inter-programme
schedule-fillers ("joins"), NOT repertoire — excluded from segment-based
rankings by default. Identified empirically as the only recordings that are
both very short (32s) and extremely repeated (827x / 381x); a duration floor
alone is not clean (1,265 legitimate 30-60s segments exist). Both are the
Milhaud 'La Cheminée du Roi René' / 'Madrigal-Nocturne' excerpt, and both are
segments-only (≈absent from long_synopsis, so the tracks-based rankings never
saw them)."""

import re


# BBC internal QC markers that leaked from the music-scheduling library into the
# public segments feed's track_title (never customer-facing). The site anchors a
# recording's display + work-grouping on its segment title, so a marker both
# shows on the page AND fragments the work key (a stray 'EXPIRED' token splits the
# airing from the clean-titled ones, and orphans a registered work slug when a
# nightly refresh makes it the recording's first-seen title).
#   The family is the DISTINCTIVE QC directives — EXPIRED / AVOID / DO NOT USE /
# DON'T USE — none of which is ever a real title word, in any case, wrapped in
# **/()/[] and sometimes a '!'. They are stripped only as a CLEAN AFFIX: the
# marker plus its decoration must run to the start OR the end of the title with
# nothing else between it and that boundary. That anchoring is deliberate — the
# DO NOT USE family also carries free-text QC notes ('... DO NOT USE Pianist awol
# c,8.13', '... Please DO NOT USE again 2015 bn', '... DO NOT USE - AMADEUS
# ORCHESTRA'); those are NOT clean affixes (real text sits between the marker and
# the end), so the anchored pattern leaves them untouched rather than stripping
# the directive and publishing the dangling note. Leaving them keeps their
# current key (no new drift), which is the conservative outcome for a title we
# cannot cleanly recover.
#   NOT folded in: the `check` / `not for` / `Please` / editor-initial markers —
# real titles contain those words, the false-positive risk parked in memory
# segment-title-internal-annotations. Add a family here only when it is as
# unambiguous a directive as these four.
_QC_MARKERS = r"(?:EXPIRED|AVOID|DO\s+NOT\s+USE|DON['’]?T\s+USE)"
# Marker decoration: whitespace, wrapper '*'/'!'/'-' and the OPENING brackets
# '(' '[' (the '**EXPIRED(**' stray-paren case). The CLOSING ')' ']' are
# deliberately excluded so a real title's trailing bracket is not eaten off
# (e.g. '... (Op.47) DON'T USE!' must keep its ')').
_QC_DECOR = r"[\s*!(\[-]*"
_QC_MARKER_RE = re.compile(
    r"(?:^" + _QC_DECOR + _QC_MARKERS + _QC_DECOR +      # leading clean affix
    r"|" + _QC_DECOR + _QC_MARKERS + _QC_DECOR + r"$)",  # trailing clean affix
    re.IGNORECASE)


def sanitize_segment_title(title):
    """Strip a leaked BBC QC marker (_QC_MARKER_RE) when it is a clean affix at
    the start or end of a segment title. PURE. Idempotent. Returns the title
    UNCHANGED when no marker matched (so a title the pattern does not touch is
    byte-identical, not merely whitespace-normalised); tidies only the residue a
    strip leaves, and never returns empty — a title that is ONLY a marker
    degrades to the original rather than vanishing (defensive; no such case in
    the corpus)."""
    if not title:
        return title
    cleaned, n = _QC_MARKER_RE.subn(" ", title)
    if not n:
        return title
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -*")
    return cleaned or title


INTERSTITIAL_RECORDING_PIDS = frozenset({
    "p03hd05x",   # Milhaud, "La Cheminée du Roi René" excerpt — 827x, 32s
    "p02ggvkg",   # Milhaud, "Madrigal-Nocturne" from the same — 381x, 32s
})


def is_interstitial(recording_pid):
    """True if this recording_pid is a known TTN schedule-filler interstitial."""
    return recording_pid in INTERSTITIAL_RECORDING_PIDS


# Curated per-RECORDING composer corrections for upstream BBC/EBU
# mis-attributions — cases where the segment metadata itself (name AND MBID)
# credits the wrong person, so no alias or projection can fix it (the
# projection trusts the segment as the clean identity; here the segment IS the
# error). recording_pid -> the correct composer display name, spelled as the
# BBC's segment name for that person so the corrected airings group with their
# MBID-anchored siblings. Applied in ttn_project.build_rec_meta (the default
# recording-anchored view); the segment-NATIVE rankings (--source segments /
# spine drills) read segment_events directly and still show the raw upstream
# credit — acceptable for staff views, revisit only if this list grows.
RECORDING_COMPOSER_OVERRIDES = {
    # Radetzky March, Op.228 is by Johann Strauss I (the father, 1804-1849),
    # but this recording's segment credits 'Johann Strauss II' (the son, MBID
    # 8255db36...). MusicBrainz-verified 2026-07-09: 725fb443 = the father,
    # whose BBC segment name is bare 'Johann Strauss'; the corpus's other
    # Radetzky recording (p08gqzpg) carries the father's MBID correctly.
    "p03ctfzj": "Johann Strauss",
    # "Imagine Chopin-Fandango" (rec p08s07g4, 2 airings) is credited to Frederic
    # Chopin by BBC + MusicBrainz (his source theme, the Waltz in B minor), but it
    # is the performers' OWN variation-arrangement for piano + guitar from Sinziana
    # Mircea's "Imagine Chopin" project ("arrangements crafted by the performers
    # themselves"). A paraphrase = a new work by the arranger, not Chopin's, so
    # re-attribute to the project's composer. (Nick-ratified 2026-07-15.)
    "p08s07g4": "Sînziana Mircea",
}


# Curated per-RECORDING title corrections — the title analogue of
# RECORDING_COMPOSER_OVERRIDES. Same premise: the segment metadata itself is
# defective (not the tracks parse), so no work-alias can reach it — and the
# generic bare title makes a work-alias unsafe anyway (blast radius). Because a
# recording_pid maps to exactly one work, an override here is composer-
# implicitly-scoped: zero blast radius, unlike a global work-alias. Applied in
# ttn_project.build_rec_meta so the projection anchors airings onto the CLEAN
# title; the string is spelled to land on the canonical work_title_key group.
# Only for recordings DEDICATED to the one work (no correctly-titled airing to
# disturb). Segment-native views still show the raw upstream title.
RECORDING_TITLE_OVERRIDES = {
    # Brahms Symphony No.2 in D major, Op.73. Both recordings' segment titles
    # drop the opus ("Symphony No 2 in D" / "...in D major"), keying the airings
    # to the bare `2 d in no symphony` group — shared with Sibelius's No.2, so a
    # global work-alias can't fold it. recording_pid -> canonical title. Fixes
    # the 4 segment-backed airings; the lone pre-2012 text-only airing is out of
    # this mechanism's reach. (2026-07-27.)
    "p00r4gc3": "Symphony no 2 in D major, Op 73",
    "p055jz2z": "Symphony no 2 in D major, Op 73",
    # Berlioz, Roméo et Juliette Op.17 (COMPLETE, ~100 min w/ soloists+chorus).
    # The segment title is truncated mid-word ("...chorus and orchestr"), keying
    # this recording apart from the other complete recording (p077cr9k, the
    # English "dramatic symphony" spelling, folded in by a composer-scoped alias).
    # Restore the full title so both complete recordings share one work-key,
    # distinct from the ~50-min orchestral-movements-only selection (p03s02mm).
    # (2026-08-09; see musicological-notes.txt.)
    "p04wwxy6": "Romeo et Juliette - symphonie dramatique, Op 17 for soloists, chorus and orchestra",
}
