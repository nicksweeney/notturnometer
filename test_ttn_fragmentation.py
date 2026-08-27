"""ttn_fragmentation --projected mode tests (synthetic DB + stubbed projection)."""
import sqlite3

import pytest

import ttn_fragmentation as F


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.sqlite"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE episodes (pid TEXT PRIMARY KEY, broadcast_date TEXT)")
    # full 5-col shape projected_rows consumes
    conn.execute("CREATE TABLE tracks (episode_pid TEXT, position INT, "
                 "composer TEXT, composer_line TEXT, title TEXT)")
    rows = [
        # ghost pair: two raw spellings of ONE work, both projecting to rp1
        ("e1", 0, "Heinrich Schutz", "Heinrich Schutz",
         "Also hat Gott die Welt geliebt, SWV.380; Jauchzet dem Herren"),
        ("e2", 0, "Heinrich Schutz", "Heinrich Schutz",
         "Also hat Gott die Welt geliebt"),
        ("e3", 0, "Heinrich Schutz", "Heinrich Schutz",
         "Also hat Gott die Welt geliebt"),
        # real pair: raw-keyed spellings NO alias covers (the historical
        # Tombeau pair would be wrong here -- folded live on 2026-08-27)
        ("e4", 0, "Marin Marais", "Marin Marais",
         "Pièce Zzzqux Alpha"),
        ("e5", 0, "Marin Marais", "Marin Marais",
         "Piece Zzzqux beta"),
        ("e6", 0, "Marin Marais", "Marin Marais",
         "Piece Zzzqux beta"),
    ]
    for ep, pos, c, cl, t in rows:
        conn.execute("INSERT INTO episodes VALUES (?, '2015-01-01')", (ep,))
        conn.execute("INSERT INTO tracks VALUES (?,?,?,?,?)", (ep, pos, c, cl, t))
    conn.commit()
    return str(p)


def _run(db, monkeypatch, capsys, argv):
    import ttn_project as P
    # ALL schutz rows project -> the two raw spellings converge fully.
    proj = {("e1", 0): "rp1", ("e2", 0): "rp1", ("e3", 0): "rp1"}
    meta = {"rp1": ("Heinrich Schutz",
                    "Also hat Gott die Welt geliebt, SWV.380; Jauchzet dem Herren")}
    orig = P.load
    monkeypatch.setattr(P, "load", lambda c: (proj, meta, "ok"))
    try:
        rc = F.main([db] + argv)
    finally:
        P.load = orig
    return rc, capsys.readouterr().out


def test_projected_mode_excludes_ghost_pair(db, monkeypatch, capsys):
    # e2/e3 fall back to RAW ('Also hat Gott...' bare) while e1 takes the
    # rec_meta identity -> those are still distinct keys here. Make ALL rows
    # project instead so the ghost fully converges:
    import ttn_project as P
    proj = {("e1", 0): "rp1", ("e2", 0): "rp1", ("e3", 0): "rp1"}
    meta = {"rp1": ("Heinrich Schutz",
                    "Also hat Gott die Welt geliebt, SWV.380; Jauchzet dem Herren")}
    orig = P.load
    monkeypatch.setattr(P, "load", lambda c: (proj, meta, "ok"))
    try:
        buf = capsys
        rc = F.main([db, "--projected"])
    finally:
        P.load = orig
    out = capsys.readouterr().out
    assert rc is None or rc == 0
    assert "(PROJECTED view)" in out
    # the fully-projected schutz ghost must not surface anywhere
    assert "Also hat Gott" not in out


def test_projected_mode_ranks_real_pairs(db, monkeypatch, capsys):
    rc, out = _run(db, monkeypatch, capsys, ["--projected"])
    assert rc in (None, 0)
    assert "marais" in out.lower()
    assert "Zzzqux" in out
    assert "Marin Marais" in out          # the ranked composer row


def test_default_spine_mode_untouched(db, monkeypatch, capsys):
    # The spine path still runs its own signals (stubbed oracle returns nothing).
    import ttn_spine
    monkeypatch.setattr(F, "work_alias_candidates", lambda conn: iter([]))
    rc = F.main([db])
    out = capsys.readouterr().out
    assert rc in (None, 0)
    assert "rec-proven" in out          # the spine-mode header shape


def test_dispatcher_unchanged():
    import ttn_curate as C
    assert C.SUBCOMMANDS["fragmentation"] == "ttn_fragmentation"
