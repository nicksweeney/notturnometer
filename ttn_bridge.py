"""Cross-era recording bridge (SP2): soft-link text-only airings (segment-absent
episodes) to PID-era spine recordings via a role-typed contributor-identity
signature. Trusted tier auto-links; everything weaker is a ratified candidate.
Offline, in-memory, no persisted link table (that is SP3). Additive — touches
nothing in tracks/ttn_analyze/the alias tables/the spine rankings.
See docs/superpowers/specs/2026-06-09-cross-era-bridge-design.md."""
import argparse, json, os, re, sqlite3
from collections import Counter, defaultdict, namedtuple

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
    "recording_pid composer_identity composer_display work_key work_display "
    "conductors soloists ensembles duration_seconds airing_count "
    "first_aired last_aired")

MatchScore = namedtuple("MatchScore", "tier score detail")   # tier: trusted|candidate|none
Link = namedtuple("Link", "text_rec pid_sig tier method")
BridgeResult = namedtuple("BridgeResult", "trusted candidates unmatched")
AliasCandidate = namedtuple("AliasCandidate",
    "variant preferred tier recording_pid airings chained")

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
    its flattened credit name-set (ttn_credits credit_key). Spelling-stable
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
    """Text-only recordings (decision B): ttn_credits.build_units over the
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


def relaxed_score(text_rec, pid_sig):
    """score_match with the work_key half of the gate removed: scores a
    same-composer pair on performer overlap + contradiction veto + duration,
    IGNORING the work-title key. Used by relaxed_links to surface cross-era
    title variants (the pairs the strict work_key gate drops to unmatched).
    Duration is the real discriminator here, so a trusted tier still requires
    _duration_ok. Composer identity still gates."""
    if text_rec.composer_identity != pid_sig.composer_identity:
        return MatchScore("none", 0.0, "gate")
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

_SIG_TOKEN_RE = re.compile(r"[^a-z0-9]+")

def _sig_tokens(work_key):
    """Significant tokens of a work_key for cross-era title overlap: key
    substrings of length >=4 that are not bare numbers (drops structural
    stopwords like 'for'/'in'/'op'/'no' and bare opus/catalogue numbers, keeps
    content words like 'violin'/'concerto'/'suite' and catalogue tokens like
    'bwv988')."""
    return {t for t in _SIG_TOKEN_RE.split((work_key or "").lower())
            if len(t) >= 4 and not t.isdigit()}

# --- auto-fold trap detectors (seeded from the 12 manual curation batches) ---
# Deferral triggers: a false hit only DEFERS a genuine fold to the human flow
# (recoverable), so these are liberal on purpose.
_ANNOTATION_RE = re.compile(
    r"do not use|don'?t use|doubtful|\bcheck\b|not for\b|\bbn\b|please|\bok\b", re.I)
_ALTSCORING_RE = re.compile(r"vers\.|\barr\.|arranged|transc|version for", re.I)
# movement / selection excerpt locators (NOT bare 'from', which is a source note)
_EXCERPT_RE = re.compile(
    r"\bnos?\.? ?\d.*\b(movement|mvt|excerpt)|\bmovement\b|\bmvt\b|\bexcerpt\b"
    r"|from act\b|\bscene \d", re.I)
# a §-catalogue key whose first sub-field is alphabetic = a movement slug
# (e.g. §bwv1068|air), as opposed to the whole-work §ref|nums|keys form.
_MOVEMENT_KEY_RE = re.compile(r"§[^|]+\|[a-z]")
_KEY_SIG_RE = re.compile(r"\bin ([a-g](?: flat| sharp)?) (major|minor)\b", re.I)
_WORK_NUM_RE = re.compile(r"\bno\.? ?(\d+)", re.I)

def _key_sig(title):
    """(note, mode) of an 'in <note>[ flat|sharp] <major|minor>' key, or None."""
    m = _KEY_SIG_RE.search(title or "")
    return (m.group(1).lower(), m.group(2).lower()) if m else None

def _work_num(title):
    """primary work-number ('No.N'/'no N') as a string, or None."""
    m = _WORK_NUM_RE.search(title or "")
    return m.group(1) if m else None

_AUTO_JACCARD = 0.5

def _auto_fold_reason(link, cluster_size, *, work_title_key, resolve_work_alias,
                      alias_targets):
    """"" if the link is a safe auto-accept, else a short defer-reason. Conservative:
    a single text-recording candidate, strong tier, free/non-chained, no trap
    markers, and a high work-key token overlap. Order matters (cheapest/strongest
    signals first); the human flow handles every deferred case."""
    if cluster_size != 1:
        return "cluster"
    if link.tier != "strong":
        return "weak"
    v, p = link.text_rec.work_display, link.pid_sig.work_display
    comp = link.text_rec.composer_display
    # work-key checks use the already-derived keys on the signatures; the prose
    # marker checks (below) scan the readable display titles. work_title_key is
    # the keyer the call site threads (re-deriving from display) — applied to
    # the displays so a caller passing only displays still keys consistently.
    vk = link.text_rec.work_key or work_title_key(v, comp)
    pk = link.pid_sig.work_key or work_title_key(p, comp)
    if resolve_work_alias(vk) != vk or vk in alias_targets:
        return "guarded"
    if resolve_work_alias(pk) != pk:
        return "chained"
    # trap markers (display-scanned) and key/number conflicts are checked before
    # the already-grouped equality guard: a trap is a defer reason in its own
    # right even on a degenerate same-key link.
    if _MOVEMENT_KEY_RE.match(vk) or _MOVEMENT_KEY_RE.match(pk):
        return "catalogue-excerpt"
    for s in (v, p):
        if _ANNOTATION_RE.search(s or ""):
            return "annotation"
        if _ALTSCORING_RE.search(s or ""):
            return "alt-scoring"
    if bool(_EXCERPT_RE.search(v or "")) != bool(_EXCERPT_RE.search(p or "")):
        return "excerpt"
    ks_v, ks_p = _key_sig(v), _key_sig(p)
    if ks_v and ks_p and ks_v != ks_p:
        return "key-conflict"
    n_v, n_p = _work_num(v), _work_num(p)
    if n_v and n_p and n_v != n_p:
        return "number-conflict"
    if resolve_work_alias(vk) == resolve_work_alias(pk):
        return "already-grouped"
    T, P = _sig_tokens(vk), _sig_tokens(pk)
    if not (T and P and (T <= P or P <= T
                         or len(T & P) / len(T | P) >= _AUTO_JACCARD)):
        return "low-overlap"
    return ""

def auto_fold_ok(link, cluster_size, *, work_title_key, resolve_work_alias,
                 alias_targets):
    return _auto_fold_reason(link, cluster_size, work_title_key=work_title_key,
                             resolve_work_alias=resolve_work_alias,
                             alias_targets=alias_targets) == ""

def auto_fold_candidates(links, decisions, *, work_title_key, resolve_work_alias,
                         alias_targets):
    """One conservative pass: group links by text-recording for cluster size, skip
    already-decided (text_key, recording_pid) pairs, and split into auto-accepted
    links + a Counter of defer reasons. Pure given its inputs; writes nothing."""
    by_text = defaultdict(list)
    for lk in links:
        by_text[text_recording_key(lk.text_rec)].append(lk)
    accepted, reasons = [], Counter()
    for tk, group in by_text.items():
        size = len(group)
        verdicts = decisions.get(tk, {})
        for lk in group:
            if lk.pid_sig.recording_pid in verdicts:
                continue                                   # already decided
            r = _auto_fold_reason(lk, size, work_title_key=work_title_key,
                                  resolve_work_alias=resolve_work_alias,
                                  alias_targets=alias_targets)
            if r:
                reasons[r] += 1
            else:
                accepted.append(lk)
    return accepted, reasons

def relaxed_links(unmatched_text_recs, pid_sigs, decisions):
    """Cross-era title-variant finder: for each text recording the strict bridge
    left unmatched, find post-2012 recordings with the SAME composer + performer
    overlap + duration but a DIFFERENT work_key. Returns Link(text_rec, pid_sig,
    tier, "relaxed-work") with tier in {strong, weak} (relaxed_score
    trusted/candidate). Reject-ledger entries are suppressed; everything else is a
    ratifiable candidate (no auto-linking). Pure given its inputs."""
    by_composer = defaultdict(list)
    for ps in pid_sigs.values():
        by_composer[ps.composer_identity].append(ps)
    links = []
    for tr in unmatched_text_recs:
        verdicts = decisions.get(text_recording_key(tr), {})
        for ps in by_composer.get(tr.composer_identity, []):
            if ps.work_key == tr.work_key:
                continue                                   # already agrees -> not a fold
            if verdicts.get(ps.recording_pid) == "reject":
                continue
            ms = relaxed_score(tr, ps)
            if ms.tier == "none":
                continue
            if not (_sig_tokens(tr.work_key) & _sig_tokens(ps.work_key)):
                continue                                   # different works, same performer
            tier = "strong" if ms.tier == "trusted" else "weak"
            links.append(Link(tr, ps, tier, "relaxed-work"))
    return links

def bridge_alias_candidates(accepted_links, *, work_title_key, resolve_work_alias,
                            alias_targets=frozenset()):
    """Alias VIEW over accepted relaxed links: (text title -> spine segment
    title), composer-scoped. Drops folds that would chain or are already grouped,
    and flags chained preferreds. Emit-and-ratify: never writes the table.

    `alias_targets` is the set of work-keys other aliases already fold TO. A fold
    is suppressed when its VARIANT key is not 'free' — either already aliased away
    (resolve(vk)!=vk) or itself a canonical target (vk in alias_targets) — because
    redirecting an established target/source chains the existing table (the trap
    the chain-free test keeps catching: Falla/Bach/Vivaldi/Weber/Poulenc)."""
    out = []
    for lk in accepted_links:
        v = lk.text_rec.work_display
        p = lk.pid_sig.work_display
        comp = lk.text_rec.composer_display
        vk = work_title_key(v, comp)
        pk = work_title_key(p, comp)
        if resolve_work_alias(vk) != vk or vk in alias_targets:
            continue   # variant is not a free key (already a source/target) -> would chain
        if resolve_work_alias(vk) == resolve_work_alias(pk):
            continue   # already grouped (both sides resolve to one canonical)
        chained = resolve_work_alias(pk) != pk
        out.append(AliasCandidate(v, p, lk.tier, lk.pid_sig.recording_pid,
                                  lk.text_rec.airing_count, chained))
    return out

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
                         wkinfo[rp].work_key, rec.segment_title,
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

def render_relaxed_candidates(links, *, top=None):
    # Surface [strong] before [weak], then high-airing folds first, so the top-N
    # slice of a large worklist is the highest-value to ratify.
    links = sorted(links, key=lambda lk: (lk.tier != "strong", -lk.text_rec.airing_count))
    rows = links if top is None else links[:top]
    lines = [f"{len(links)} relaxed cross-era link(s) for review "
             "(ratify with --relaxed --accept / --reject 'text_key|recording_pid'):", ""]
    for lk in rows:
        tr, ps = lk.text_rec, lk.pid_sig
        lines.append(f"  [{lk.tier}] {text_recording_key(tr)}  |  {ps.recording_pid}")
        lines.append(f"      {tr.composer_display} — {tr.work_display!r} ({tr.airing_count}x)")
        lines.append(f"        vs  {ps.work_display!r}  (PID {ps.recording_pid})")
    return "\n".join(lines)


def render_relaxed_emit(cands):
    lines = [f"# {len(cands)} bridge-anchored WORK_ALIAS candidate(s) — ratify, "
             "then paste into _WORK_ALIAS_PAIRS:", ""]
    for c in cands:
        note = "   # NB preferred title is itself aliased — target the final canonical" if c.chained else ""
        lines.append(f'    ({c.variant!r}, {c.preferred!r}),'
                     f'   # [{c.tier}] {c.recording_pid} {c.airings}x{note}')
    return "\n".join(lines)


# --- CLI entry point (staff: ledger admin) ---------------------------------
def main(argv=None):
    # Staff-only surface (SP4d-3b): the cross-era ranking view moved to
    # `ttn_analyze --by recording --cross-era` (which imports the library
    # functions above, not this main). What's left here is the accept/reject
    # ledger + the review worklist, reached via `ttn_curate.py bridge`.
    ap = argparse.ArgumentParser(
        description="Cross-era recording bridge — ledger admin (staff).")
    ap.add_argument("db", nargs="?", default="ttn.sqlite")
    ap.add_argument("--relaxed", action="store_true",
                    help="work_key-relaxed cross-era title-variant mode (2010-2012 curation)")
    ap.add_argument("--candidates", action="store_true", help="print the review worklist")
    ap.add_argument("--emit", action="store_true", help="(--relaxed) paste-ready WORK_ALIASES from accepted links")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--accept", metavar="TEXTKEY|RECPID")
    ap.add_argument("--reject", metavar="TEXTKEY|RECPID")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    method = "relaxed-work" if a.relaxed else "mbid"
    if a.accept or a.reject:
        spec = a.accept or a.reject
        text_key, rp = spec.rsplit("|", 1)
        save_decision(DECISIONS_PATH, text_key.strip(), rp.strip(),
                      "accept" if a.accept else "reject", method=method, note=a.note)
        print(f"recorded {'accept' if a.accept else 'reject'} ({method}): {rp.strip()}")
        return
    conn = sqlite3.connect(a.db)
    ctx = build_context(conn)
    pid_sigs = pid_signatures(conn, ctx)
    if a.relaxed:
        from ttn_analyze import work_title_key, resolve_work_alias, WORK_ALIASES
        text_recs = text_recordings(conn, ctx, after="2010-01-17", before="2012-03-15")
        result = bridge(text_recs, pid_sigs, load_decisions())
        links = relaxed_links(result.unmatched, pid_sigs, load_decisions())
        if a.emit:
            decisions = load_decisions()
            accepted = [lk for lk in links
                        if decisions.get(text_recording_key(lk.text_rec), {})
                        .get(lk.pid_sig.recording_pid) == "accept"]
            print(render_relaxed_emit(bridge_alias_candidates(
                accepted, work_title_key=work_title_key, resolve_work_alias=resolve_work_alias,
                alias_targets=frozenset(WORK_ALIASES.values()))))
        else:
            print(render_relaxed_candidates(links, top=a.top))
        return
    text_recs = text_recordings(conn, ctx)
    result = bridge(text_recs, pid_sigs, load_decisions())
    if a.candidates:
        print(render_candidates(result, top=a.top))
    else:
        print(render_report(result, top=a.top))
