"""ttn_propose_remaps tests: vote mechanics on synthetic registries + DBs."""
import json
import os
import sqlite3
import tempfile

import pytest

import ttn_propose_remaps as PR


@pytest.fixture
def db(tmp_path):
    """Raw tables; rec_meta/projection stubbed by the caller."""
    p = tmp_path / "t.sqlite"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT)")
    conn.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, "
                 "title TEXT, composer TEXT, composer_line TEXT)")
    dates = ["2015-01-01", "2016-01-01", "2021-01-01"]
    rows = [("e1", 0, "Awake, and with attention hear, Z181", "Henry Purcell"),
            ("e2", 1, "Awake, and with attention hear, Z181", "Henry Purcell"),
            ("e3", 2, "Prelude to Te Deum", "Marc-Antoine Charpentier")]
    for (ep, pos, t, c), d in zip(rows, dates):
        conn.execute("INSERT INTO episodes VALUES (?,?)", (ep, d))
        conn.execute("INSERT INTO tracks (episode_pid, position, title, composer) "
                     "VALUES (?,?,?,?)", (ep, pos, t, c))
    conn.commit()
    return str(p)


def _stub(monkeypatch, proj, meta):
    import ttn_project as P
    monkeypatch.setattr(P, "load", lambda c: (proj, meta, "ok"))


def _run(db, slugs, monkeypatch, kind="works",
         registry=None, evidence=None, out=None):
    # Point module paths at temp fixtures.
    reg_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(registry if registry is not None else {}, reg_file)
    reg_file.close()
    ev_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(evidence or {"works": {}}, ev_file)
    ev_file.close()
    monkeypatch.setattr(PR, "_REGISTRY_PATH", reg_file.name)
    monkeypatch.setattr(PR, "_EVIDENCE_PATH", ev_file.name)
    argv = [db] + slugs + ["--kind", kind]
    if out:
        argv += ["--out", out]
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = PR.main(argv)
    os.unlink(reg_file.name); os.unlink(ev_file.name)
    return rc, buf.getvalue()


import json


def test_alias_path_proposes_scoped_successor(db, monkeypatch):
    # Registry holds the OLD variant key ('and attention awake hear with z181'
    # == work_title_key of '... Z181'); the edited scoped alias table resolves
    # it onward. Evidence empty -> alias vote alone must carry majority (1/1).
    _stub(monkeypatch, {("e1", 0): "rpA", ("e2", 1): "rpA"},
          {"rpA": ("Henry Purcell",
                   "Awake, and with attention hear for bass and continuo (Z.181)")})
    wk_old = PR.A.work_title_key("Awake, and with attention hear, Z181",
                                 composer="Henry Purcell")
    assert PR.A.resolve_work_alias(wk_old, "henry purcell") != wk_old
    registry = {"works": {"purcell:awake-z181": {
        "composer_key": "henry purcell", "work_key": wk_old}}}
    rc, out = _run(db, ["purcell:awake-z181"], monkeypatch,
                   registry=registry, evidence={"works": {}})
    assert rc == 0
    assert "+ purcell:awake-z181" in out and "[alias]" in out
    wk_new = PR.A.work_title_key(
        "Awake, and with attention hear for bass and continuo (Z.181)",
        composer="Henry Purcell")
    spec = next(l for l in out.splitlines() if l.startswith("purcell:awake-z181|"))
    assert spec.endswith(f"|{wk_new}")


def test_evidence_votes_drive_the_work_move_case(db, monkeypatch):
    # Work MOVED under projection (no alias fire): evidence sample votes carry it.
    _stub(monkeypatch, {("e1", 0): "rpB", ("e2", 1): "rpB"},
          {"rpB": ("Henry Purcell", "The Duke of Gloucester's trumpet suite")})
    registry = {"works": {"purcell:trumpet-suite-old": {
        "composer_key": "henry purcell", "work_key": "suite old"}}}
    evp = PR._EVIDENCE_PATH
    import ttn_work_recordings as WR
    slug = "purcell:trumpet-suite-old"
    evidence = {"works": {slug: ["rpB"]}}
    rc, out = _run(db, [slug], monkeypatch, registry=registry, evidence=evidence)
    assert rc == 0
    assert "[evidence]" in out
    wk_new = PR.A.work_title_key("The Duke of Gloucester's trumpet suite",
                                 composer="Henry Purcell")
    assert f"henry purcell|{wk_new}" in out


def test_not_an_orphan_skips(db, monkeypatch):
    _stub(monkeypatch, {("e1", 0): "rpA"},
          {"rpA": ("Henry Purcell", "Prelude to Te Deum")})
    wk = PR.A.work_title_key("Prelude to Te Deum",
                             composer="Marc-Antoine Charpentier")
    registry = {"works": {"charpentier:prelude-to-te-deum": {
        "composer_key": "marc-antoine charpentier", "work_key": wk}}}
    rc, out = _run(db, ["charpentier:prelude-to-te-deum"], monkeypatch,
                   registry=registry, evidence={"works": {}})
    assert rc == 0
    assert "- charpentier:prelude-to-te-deum" in out and "NOT an orphan" in out


def test_tie_is_ambiguous_skip(db, monkeypatch):
    _stub(monkeypatch,
          {("e1", 0): "rp1", ("e2", 1): "rp2"},
          {"rp1": ("Henry Purcell", "Trumpet Suite"),
           "rp2": ("Henry Purcell",
                   "The Duke of Gloucester's trumpet suite")})
    slug = "purcell:some-orphan"
    rc, out = _run(db, [slug], monkeypatch,
                   registry={"works": {slug: {"composer_key": "henry purcell",
                                              "work_key": "zzzqux orphan"}}},
                   evidence={"works": {slug: ["rp1", "rp2"]}})
    assert rc == 0
    assert "- " + slug in out and "AMBIGUOUS tie" in out


def test_no_candidates_suggests_retire(db, monkeypatch):
    _stub(monkeypatch, {("e1", 0): "rpX"}, {"rpX": ("W A Mozart", "Something Else")})
    slug = "anon:dissolved-identity"
    rc, out = _run(db, [slug], monkeypatch,
                   registry={"works": {slug: {"composer_key": "anonymous",
                                              "work_key": "4 works"}}},
                   evidence={"works": {}})
    assert rc == 0
    assert "? " + slug in out and "RETIRE" in out


def test_composer_namespace_resolves_onward(db, monkeypatch):
    # Ground the resolved identity in the corpus first: one Lassus airing.
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO episodes VALUES ('e9','2018-01-01')")
    conn.execute("INSERT INTO tracks (episode_pid, position, title, composer) "
                 "VALUES ('e9',0,'Musica Dei donum optimi','Orlando di Lasso')")
    conn.commit(); conn.close()
    import ttn_project as P
    monkeypatch.setattr(P, "load",
                        lambda c: ({("e9", 0): "rpL"},
                                   {"rpL": ("Orlande de Lassus", "Musica Dei donum optimi")},
                                   "ok"))
    slug = "lassus:orlando-di-lasso"
    rc, out = _run(db, [slug], monkeypatch, kind="composers",
                   registry={"composers": {slug: {"composer_key": "orlando di lasso"}}},
                   evidence={})
    assert rc == 0
    rk = PR.A.resolve_composer_alias("orlando di lasso")
    assert rk != "orlando di lasso"
    assert f"{slug}|{rk}" in out


def test_out_writes_spec_lines_only(db, monkeypatch, tmp_path):
    _stub(monkeypatch, {("e1", 0): "rpA"}, {"rpA": ("Henry Purcell", "Trumpet Suite")})
    slug = "purcell:old"
    out_f = tmp_path / "remap.txt"
    ev_slug_vote = {"works": {slug: ["rpA"]}}
    rc, out = _run(db, [slug], monkeypatch, registry=
                   {"works": {slug: {"composer_key": "henry purcell",
                                     "work_key": "suite old"}}},
                   evidence=ev_slug_vote, out=str(out_f))
    assert rc == 0
    content = out_f.read_text().strip().split("\n")
    assert len(content) == 1 and content[0].startswith(f"{slug}|henry purcell|")


def test_stdin_paste_of_site_failure_list(db, monkeypatch):
    _stub(monkeypatch, {("e1", 0): "rpA"}, {"rpA": ("Henry Purcell", "Trumpet Suite")})
    slug = "purcell:legacy"
    import io, contextlib, json as J
    reg_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    J.dump({"works": {slug: {"composer_key": "henry purcell",
                             "work_key": "suite old"}}}, reg_file)
    reg_file.close()
    ev_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    J.dump({"works": {slug: ["rpA"]}}, ev_file)
    ev_file.close()
    monkeypatch.setattr(PR, "_REGISTRY_PATH", reg_file.name)
    monkeypatch.setattr(PR, "_EVIDENCE_PATH", ev_file.name)
    stdin_text = f"['{slug}']\n"        # literal paste of the site-failure list
    class FakeStdin:
        def read(self): return stdin_text
    buf = io.StringIO()
    saved = PR.sys.stdin
    PR.sys.stdin = FakeStdin()
    try:
        with contextlib.redirect_stdout(buf):
            rc = PR.main([db, "-", "--kind", "works"])
    finally:
        PR.sys.stdin = saved
        os.unlink(reg_file.name); os.unlink(ev_file.name)
    assert rc == 0 and slug in buf.getvalue()


def test_dispatcher_routes_propose_remaps(monkeypatch):
    import ttn_curate as C
    captured = {}
    monkeypatch.setattr(PR, "main",
                        lambda argv, _c=captured: _c.setdefault("argv", argv))
    C.main(["propose-remaps", "db.sqlite", "some:slug"])
    assert captured["argv"] == ["db.sqlite", "some:slug"]


def test_composer_fold_only_orphan_proposes_tier1(db, monkeypatch):
    # Tier-1 mechanical: composer half folded, work key byte-identical --
    # the signal that rescued the Tchaikovsky composer-fold orphans.
    _stub(monkeypatch, {("e1", 0): "rpA"}, {"rpA": ("Peter Ilyich Tchaikovsky", "Symphony no 5 in E minor, Op 64")})
    wk = PR.A.work_title_key("Symphony no 5 in E minor, Op 64",
                             composer="Peter Ilyich Tchaikovsky")
    slug = "tchaikovsky:symphony-no-5"
    rc, out = _run(db, [slug], monkeypatch,
                   registry={"works": {slug: {"composer_key": "pytor illyich tchaikovsky",
                                              "work_key": wk}}},
                   evidence={"works": {}})
    assert rc == 0
    assert "composer-fold" in out
    assert f"{slug}|peter ilyich tchaikovsky|{wk}" in out
