"""Cross-era recording bridge (SP2): soft-link text-only airings (segment-absent
episodes) to PID-era spine recordings via a role-typed contributor-identity
signature. Trusted tier auto-links; everything weaker is a ratified candidate.
Offline, in-memory, no persisted link table (that is SP3). Additive — touches
nothing in tracks/ttn_analyze/the alias tables/the spine rankings.
See docs/superpowers/specs/2026-06-09-cross-era-bridge-design.md."""
import argparse, json, os, re, sqlite3
from collections import defaultdict, namedtuple

from ttn_spine import (build_context, build_recordings, build_contributors,
                       assign_recording_work_keys, resolve_identity)
from ttn_credits import build_units, cluster_length, representative_title
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

_DUR_TOL_FRAC = 0.25     # +/- of the PID duration, OR
_DUR_TOL_MIN = 4.0       # +/- minutes, whichever is larger (the text proxy is coarse)

def _duration_ok(pid_seconds, text_min):
    if text_min is None or not pid_seconds:
        return True                                   # non-corroborating, never blocks
    pid_min = pid_seconds / 60.0
    return abs(pid_min - text_min) <= max(_DUR_TOL_MIN, _DUR_TOL_FRAC * pid_min)

def score_match(text_rec, pid_sig):
    """Pure, pluggable scorer: (text_rec, pid_sig) -> MatchScore(tier, score,
    detail). tier in {trusted, candidate, none}. The B+ tier will register a
    second scorer of this exact shape; do not fold bucketing/enumeration in here."""
    if (text_rec.composer_identity != pid_sig.composer_identity
            or text_rec.work_key != pid_sig.work_key):
        return MatchScore("none", 0.0, "gate")
    # contradiction veto: both sides have an MBID-resolved member in a
    # discriminating role, with disjoint MBID sets -> different performance.
    for tb, pb in ((text_rec.conductors, pid_sig.conductors),
                   (text_rec.soloists, pid_sig.soloists)):
        tm, pm = _mbids(tb), _mbids(pb)
        if tm and pm and not (tm & pm):
            return MatchScore("none", 0.0, "veto")
    discriminating = bool(_mbids(text_rec.conductors) & _mbids(pid_sig.conductors)
                          or _mbids(text_rec.soloists) & _mbids(pid_sig.soloists)
                          or _mbids(text_rec.chamber_ensembles) & _mbids(pid_sig.ensembles))
    any_overlap = bool(text_rec.conductors & pid_sig.conductors
                       or text_rec.soloists & pid_sig.soloists
                       or text_rec.ensembles & pid_sig.ensembles)
    if not any_overlap:
        return MatchScore("none", 0.0, "no-overlap")
    if (not text_rec.degraded and discriminating
            and _duration_ok(pid_sig.duration_seconds, text_rec.length_proxy_min)):
        return MatchScore("trusted", 1.0, "trusted")
    return MatchScore("candidate", 0.5, "candidate")

# --- decisions ledger ------------------------------------------------------
def load_decisions(path=DECISIONS_PATH):
    """text_recording_key -> {recording_pid: 'accept'|'reject'}. Missing file
    -> empty (the bridge still runs, statelessly)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    out = defaultdict(dict)
    for v in data.get("verdicts", []):
        out[v["text_key"]][v["recording_pid"]] = v["verdict"]
    return dict(out)

def save_decision(path, text_key, recording_pid, verdict, *, method="mbid", note=""):
    """Append (or update) one verdict, carrying the method tag (the B+ seam)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {"verdicts": []}
    data["verdicts"] = [v for v in data.get("verdicts", [])
                        if not (v["text_key"] == text_key
                                and v["recording_pid"] == recording_pid)]
    data["verdicts"].append({"text_key": text_key, "recording_pid": recording_pid,
                             "verdict": verdict, "method": method, "note": note})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

# --- the bridge engine -----------------------------------------------------
def bridge(text_recs, pid_sigs, decisions):
    """Bucket PID sigs by (composer_identity, work_key); for each text-recording
    score its bucket, apply the ledger and the uniqueness rule, and split into
    BridgeResult(trusted, candidates, unmatched). Pure given its inputs."""
    by_bucket = defaultdict(list)
    for ps in pid_sigs.values():
        by_bucket[(ps.composer_identity, ps.work_key)].append(ps)
    trusted, candidates, unmatched = [], [], []
    for tr in text_recs:
        verdicts = decisions.get(text_recording_key(tr), {})
        scored = []
        for ps in by_bucket.get((tr.composer_identity, tr.work_key), []):
            if verdicts.get(ps.recording_pid) == "reject":
                continue
            ms = score_match(tr, ps)
            if ms.tier != "none":
                scored.append((ps, ms))
        if not scored:
            unmatched.append(tr)
            continue
        accepted = [(ps, ms) for ps, ms in scored
                    if verdicts.get(ps.recording_pid) == "accept"]
        trusted_hits = [(ps, ms) for ps, ms in scored if ms.tier == "trusted"]
        if len(trusted_hits) == 1:
            ps, _ms = trusted_hits[0]
            trusted.append(Link(tr, ps, "trusted", "mbid"))
        elif accepted:
            for ps, _ms in accepted:
                trusted.append(Link(tr, ps, "accepted", "mbid"))
        else:
            for ps, _ms in scored:                       # ambiguous/weak -> worklist
                candidates.append(Link(tr, ps, "candidate", "mbid"))
    return BridgeResult(trusted, candidates, unmatched)

def pid_signatures(conn, ctx):
    """PID-era spine recordings as role-bucketed signatures, keyed by
    recording_pid. work_key from SP1's assign_recording_work_keys; the spine's
    7 contributor roles folded into the 3 credit buckets the text side uses."""
    recs = build_recordings(conn, ctx=ctx)
    con = build_contributors(conn, ctx=ctx)
    wkinfo = assign_recording_work_keys(recs)
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

# --- report renderers -------------------------------------------------------
def render_report(result, *, top=20):
    t, c, u = result.trusted, result.candidates, result.unmatched
    lines = [f"cross-era bridge: {len(t)} trusted links, {len(c)} candidate(s), "
             f"{len(u)} unmatched text-recording(s)", "",
             "trusted (auto-linked) — sample:"]
    for lk in sorted(t, key=lambda l: -l.text_rec.airing_count)[:top]:
        tr, ps = lk.text_rec, lk.pid_sig
        lines.append(f"  {tr.first_aired}  {tr.composer_display} — {tr.work_display}"
                     f"  ->  {ps.recording_pid} (PID {ps.first_aired}..{ps.last_aired})")
    return "\n".join(lines)

def render_candidates(result, *, top=None):
    rows = result.candidates if top is None else result.candidates[:top]
    lines = [f"{len(result.candidates)} candidate link(s) for review "
             "(ratify with --accept / --reject 'text_key|recording_pid'):", ""]
    for lk in rows:
        tr, ps = lk.text_rec, lk.pid_sig
        lines.append(f"  {text_recording_key(tr)}  |  {ps.recording_pid}")
        lines.append(f"      {tr.composer_display} — {tr.work_display} "
                     f"({tr.first_aired}, {tr.airing_count}x)  vs PID {ps.recording_pid}")
    return "\n".join(lines)

def render_by_recording(result, pid_sigs, *, top=30):
    """PID recordings whose history extends across the boundary via a trusted
    link: first_aired now reaches into the text era."""
    bridged = defaultdict(list)                       # recording_pid -> [TextRec]
    for lk in result.trusted:
        bridged[lk.pid_sig.recording_pid].append(lk.text_rec)
    rows = []
    for rp, trs in bridged.items():
        ps = pid_sigs[rp]
        earliest = min([ps.first_aired] + [t.first_aired for t in trs if t.first_aired])
        pre = sum(t.airing_count for t in trs)
        rows.append((pre, earliest, ps, trs))
    rows.sort(key=lambda r: (-r[0], r[1]))
    lines = [f"recordings with cross-era history ({len(rows)}):", ""]
    for pre, earliest, ps, trs in rows[:top]:
        lines.append(f"  {earliest}..{ps.last_aired}  +{pre} pre-segment airing(s)   "
                     f"{ps.composer_display} — {ps.recording_pid}")
    return "\n".join(lines)

# --- CLI entry point --------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Cross-era recording bridge (SP2).")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--by", choices=["recording"], help="cross-era extended histories")
    ap.add_argument("--candidates", action="store_true", help="print the review worklist")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--accept", metavar="TEXTKEY|RECPID")
    ap.add_argument("--reject", metavar="TEXTKEY|RECPID")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if a.accept or a.reject:
        spec = a.accept or a.reject
        text_key, rp = spec.rsplit("|", 1)
        save_decision(DECISIONS_PATH, text_key, rp,
                      "accept" if a.accept else "reject", note=a.note)
        print(f"recorded {'accept' if a.accept else 'reject'}: {rp}")
        return
    conn = sqlite3.connect(a.db)
    ctx = build_context(conn)
    pid_sigs = pid_signatures(conn, ctx)
    text_recs = text_recordings(conn, ctx)
    result = bridge(text_recs, pid_sigs, load_decisions())
    if a.by == "recording":
        print(render_by_recording(result, pid_sigs, top=a.top))
    elif a.candidates:
        print(render_candidates(result, top=a.top))
    else:
        print(render_report(result, top=a.top))

if __name__ == "__main__":
    main()
