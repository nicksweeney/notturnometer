"""Cross-era recording bridge (SP2): soft-link text-only airings (segment-absent
episodes) to PID-era spine recordings via a role-typed contributor-identity
signature. Trusted tier auto-links; everything weaker is a ratified candidate.
Offline, in-memory, no persisted link table (that is SP3). Additive — touches
nothing in tracks/ttn_analyze/the alias tables/the spine rankings.
See docs/superpowers/specs/2026-06-09-cross-era-bridge-design.md."""
import argparse, hashlib, json, os, re, sqlite3
from collections import Counter, defaultdict, namedtuple

from ttn_spine import (build_context, build_recordings, build_contributors,
                       assign_recording_work_keys, resolve_identity)
from ttn_rebroadcast import build_units, cluster_length, representative_title
from ttn_audit import load_tracks, with_track_lengths

# --- types -----------------------------------------------------------------
TextRec = namedtuple("TextRec",
    "composer_identity composer_display work_key work_display "
    "conductors soloists ensembles chamber_ensembles degraded "
    "length_proxy_min airing_count first_aired last_aired is_singleton credit_key")

PidSig = namedtuple("PidSig",
    "recording_pid composer_identity composer_display work_key "
    "conductors soloists ensembles duration_seconds airing_count "
    "first_aired last_aired")

MatchScore = namedtuple("MatchScore", "tier score detail")   # tier: trusted|candidate|none
Link = namedtuple("Link", "text_rec pid_sig tier method")
BridgeResult = namedtuple("BridgeResult", "trusted candidates unmatched")

# --- identity helpers ------------------------------------------------------
def _is_mbid(identity_key):
    """resolve_identity returns the bare MBID as the identity_key when resolved,
    else a 'name:...' key. So a key not starting with 'name:' IS an MBID."""
    return bool(identity_key) and not identity_key.startswith("name:")

def _mbids(bucket):
    return frozenset(k for k in bucket if _is_mbid(k))

DECISIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "ttn_bridge_decisions.json")

def text_recording_key(tr):
    """Stable ledger key for a text-recording: composer identity + work key +
    its flattened credit name-set (ttn_rebroadcast credit_key). Spelling-stable
    (credit_key is canonical-folded), so a verdict survives display churn."""
    credits = ",".join(sorted(tr.credit_key))
    return f"{tr.composer_identity}|{tr.work_key}|{credits}"

# --- text-only row loading -------------------------------------------------
def load_text_only_tracks(conn):
    """load_tracks rows (episode_pid, position, time_str, title, composer,
    performers, broadcast_date) for episodes with NO segment_events — the
    text-only population the bridge scopes to (the pre-2012 block + the
    scattered segment-absent tail). Whole episodes, so with_track_lengths'
    next-track length proxy stays intact."""
    covered = {r[0] for r in conn.execute(
        "SELECT DISTINCT episode_pid FROM segment_events")}
    return [r for r in load_tracks(conn) if r[0] not in covered]

# --- PID-era spine signatures -----------------------------------------------
# Composer is the work's author, not a performing credit -> excluded here.
_PID_ROLE_BUCKET = {"Conductor": "conductors",
                    "Performer": "soloists", "Singer": "soloists",
                    "Orchestra": "ensembles", "Ensemble": "ensembles",
                    "Choir": "ensembles"}

def pid_signatures(conn, ctx):
    """PID-era spine recordings as role-bucketed signatures, keyed by
    recording_pid. work_key from SP1's assign_recording_work_keys; the spine's
    7 contributor roles folded into the 3 credit buckets the text side uses."""
    recs = build_recordings(conn, ctx=ctx)
    con = build_contributors(conn, ctx=ctx)
    wkinfo = assign_recording_work_keys(conn, recs)
    out = {}
    for rp, rec in recs.items():
        buckets = {"conductors": set(), "soloists": set(), "ensembles": set()}
        for c in con.get(rp, []):
            b = _PID_ROLE_BUCKET.get(c.role)
            if b:
                buckets[b].add(c.identity_key)
        out[rp] = PidSig(rp, rec.composer_identity, rec.composer_display,
                         wkinfo[rp].work_key,
                         frozenset(buckets["conductors"]),
                         frozenset(buckets["soloists"]),
                         frozenset(buckets["ensembles"]),
                         rec.duration_seconds, rec.airing_count,
                         rec.first_aired, rec.last_aired)
    return out
