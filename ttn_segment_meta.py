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
