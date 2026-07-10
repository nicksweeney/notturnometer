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
}
