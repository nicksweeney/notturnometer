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

_CHAMBER_RE = re.compile(r"quartet|quintet|trio|sextet|octet|duo|consort", re.I)
_ORCHESTRA_RE = re.compile(r"orchestra|philharmon|symphony|sinfoni", re.I)

def _is_chamber_ensemble(name):
    """A named chamber body (quartet/trio/...) is specific enough to be the
    recording; a bare orchestra is not. Classified by the ensemble's display
    name, since parse_credit drops role text once it buckets names into sets."""
    s = name or ""
    return bool(_CHAMBER_RE.search(s)) and not _ORCHESTRA_RE.search(s)

def text_recordings(conn, ctx, *, after=None, before=None):
    """Text-only recordings (decision B): ttn_rebroadcast.build_units over the
    segment-absent population, grouped by (composer, work_key, credit_key), each
    lifted into MBID-else-name identity space via the spine's name_mbid backfill.
    A group qualifies if it is a cluster (>=2 airings) OR a strong singleton
    (non-degraded + >=1 conductor/soloist resolving to an MBID). Returns a list
    of TextRec."""
    name_mbid = ctx.name_mbid
    rows = with_track_lengths(load_text_only_tracks(conn))
    units = build_units(rows)
    groups = defaultdict(list)
    for u in units:
        if after and (u.date or "") < after:
            continue
        if before and (u.date or "") > before:
            continue
        groups[(u.composer, u.work_key, u.credit_key)].append(u)
    out = []
    for (comp_ck, work_key, ckey), members in groups.items():
        good = [u for u in members if not u.credit.degraded]
        src = good or members
        degraded = not good
        cond_names, solo_names, ens_names = set(), set(), set()
        for u in src:
            cond_names |= u.credit.conductors
            solo_names |= u.credit.soloists
            ens_names |= u.credit.ensembles
        conductors = frozenset(resolve_identity(n, None, name_mbid, role="Conductor")[0]
                               for n in cond_names)
        soloists = frozenset(resolve_identity(n, None, name_mbid, role="Performer")[0]
                             for n in solo_names)
        ens_pairs = [(n, resolve_identity(n, None, name_mbid, role="Ensemble")[0])
                     for n in ens_names]
        ensembles = frozenset(k for _n, k in ens_pairs)
        chamber = frozenset(k for n, k in ens_pairs if _is_chamber_ensemble(n))
        comp_id = resolve_identity(members[0].composer_display, None, name_mbid,
                                   role="Composer")[0]
        dates = [u.date for u in members if u.date]
        is_singleton = len(set(dates)) < 2
        strong_singleton = (not degraded) and bool(_mbids(conductors) or _mbids(soloists))
        if is_singleton and not strong_singleton:
            continue                                    # drop weak singletons (FP gate)
        out.append(TextRec(
            comp_id, members[0].composer_display, work_key,
            representative_title(members), conductors, soloists, ensembles, chamber,
            degraded, cluster_length(members), len(members),
            min(dates) if dates else "", max(dates) if dates else "",
            is_singleton, ckey))
    return out

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
