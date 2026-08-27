"""ttn_alias_check tests: verdict classes on real corpus strings + synthetic DB."""
import os
import sqlite3
import tempfile

import pytest

import ttn_alias_check as AC


@pytest.fixture
def db(tmp_path):
    """Minimal raw-tables DB: enough rows for grounding and effect counts."""
    p = tmp_path / "t.sqlite"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE tracks (composer TEXT, title TEXT)")
    conn.execute("CREATE TABLE segment_events (composer_name TEXT, track_title TEXT)")
    rows = [("Heinrich Schutz", "Magnificat anima mea Dominum, SWV.468")] * 7
    rows += [("Orlande de Lassus", "In hora ultima - motet for six voices"),
             ("Arcangelo Corelli", "Concerto Grosso in F major, Op 6, No 9"),
             ("Schutz", "Wohl denen, die ohne Wandel leben"),
             ("Schutz", "Wohl denen, die ohne Wandel leben")]
    conn.executemany("INSERT INTO tracks VALUES (?,?)", rows)
    conn.executemany("INSERT INTO segment_events VALUES (?,?)",
                     [("Heinrich Schutz", "Magnificat anima mea Dominum (SWV.468)")] * 3)
    conn.commit()
    return str(p)


def _run(db, text, kind=None):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    with open(path, "w") as fh:
        fh.write(text)
    argv = [path, "--db", db]
    if kind:
        argv += ["--kind", kind]
    try:
        return AC.main(argv)
    finally:
        os.unlink(path)


def test_clean_scoped_batch_exits_zero(db, capsys):
    rc = _run(db, "('Orlande de Lassus', 'In hora ultima - motet for six voices', 'In hora ultima')\n")
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out and "folds 1 airings" in out


def test_dead_scoped_fold_fails(db, capsys):
    # Two spellings that work_title_key collapses identically -> dead.
    text = "('Heinrich Schutz', 'Zzzqux motet', 'zzzqux motet ')\n"
    vk = AC.A.work_title_key('Zzzqux motet', composer='Heinrich Schutz')
    pk = AC.A.work_title_key('zzzqux motet ', composer='Heinrich Schutz')
    assert vk == pk, "fixture must be a genuine dead fold"
    with pytest.raises(SystemExit) as ei:
        _run(db, text)
    out = capsys.readouterr().out
    assert ei.value.code == 1 and "dead fold" in out


def test_trap_a_scoped_target_is_global_source(db, capsys):
    # The exact failure caught by the guard suite in the 2026-08-26 Purcell pass:
    # the preferred spelling's KEY is itself a WORK_ALIASES source.
    pref = ("Song 'See, see, even Night herself is here' (Z.62/11)"
            " - from The Fairy Queen, Act II Scene 3")
    tk = AC.A.work_title_key(pref, composer="Henry Purcell")
    assert tk in AC.A.WORK_ALIASES
    final = AC.A.resolve_work_alias(tk, composer="Henry Purcell")
    text = f"('Henry Purcell', 'See, even night herself is here (The Fairy Queen)', {pref!r})\n"
    with pytest.raises(SystemExit) as ei:
        _run(db, text)
    out = capsys.readouterr().out
    assert ei.value.code == 1 and "trap-A" in out
    assert final in out          # guidance names the resolved-final key


def test_chained_composer_preferred_is_alias_source(db, capsys):
    # ('Lassus', 'Orlande de Lassus') is in COMPOSER_ALIASES, so bare 'Lassus'
    # as a PREFERRED chains.
    pk = AC.A.canonical_key("Lassus")
    assert AC.A.resolve_composer_alias(pk) != pk
    with pytest.raises(SystemExit) as ei:
        _run(db, "('Orlando di Lasso', 'Lassus')\n", kind="composer")
    out = capsys.readouterr().out
    assert ei.value.code == 1 and "chained" in out


def test_clean_composer_pair_ok_with_grounding(db, capsys):
    # NB the umlauted spelling would be DEAD here (canonical_key ascii-folds);
    # a live pair needs two DIFFERENT canonical keys - bare-surname fold form.
    rc = _run(db, "('Schutz', 'Heinrich Schutz')\n", kind="composer")
    out = capsys.readouterr().out
    assert rc == 0 and "OK" in out and "2 airings seen under this spelling-family" in out


def test_unknown_variant_warns_not_fails(db, capsys):
    rc = _run(db, "('Zzzqq Nonesuch Personius', 'Heinrich Schutz')\n", kind="composer")
    out = capsys.readouterr().out
    assert rc == 0 and "WARN" in out and "unknown spelling-family" in out


def test_auto_kind_rejects_two_field_lines(db):
    with pytest.raises(SystemExit) as ei:
        _run(db, "('A', 'B')\n")
    assert ei.value.code == 2


def test_parse_error_reports_exit_2(db):
    with pytest.raises(SystemExit) as ei:
        _run(db, "('A', 'B'),  # inline comment is junk\n")
    assert ei.value.code == 2


def test_dead_work_pair_fails(db, capsys):
    text = "('Zzzqux overture', 'zzzqux  overture')\n"
    assert AC.A.work_title_key('Zzzqux overture') == AC.A.work_title_key('zzzqux  overture')
    with pytest.raises(SystemExit) as ei:
        _run(db, text, kind="work")
    out = capsys.readouterr().out
    assert ei.value.code == 1 and "dead fold" in out


def test_quiet_suppresses_ok_lines(db):
    import contextlib
    import io
    text = ("('Zzzqq Nonesuch Personius', 'Heinrich Schutz')\n"
            "('Orlande de Lassus', 'In hora ultima - motet for six voices', 'In hora ultima')\n")
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    with open(path, "w") as fh:
        fh.write(text)
    try:
        loud = io.StringIO()
        with contextlib.redirect_stdout(loud):
            assert AC.main([path, "--db", db, "--kind", "composer"]) == 0
        assert " OK " in loud.getvalue()

        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            assert AC.main([path, "--db", db, "--kind", "composer", "--quiet"]) == 0
    finally:
        os.unlink(path)
    q = quiet.getvalue()
    assert "WARN" in q and not any(" OK " in ln for ln in q.splitlines())


def test_dispatcher_routes_check_aliases(monkeypatch):
    import ttn_curate as C
    captured = {}
    monkeypatch.setattr(AC, "main", lambda argv, _c=captured: _c.setdefault("argv", argv))
    C.main(["check-aliases", "draft.txt", "--kind", "scoped"])
    assert captured["argv"] == ["draft.txt", "--kind", "scoped"]


def test_many_to_one_batch_targets_repeated_is_ok(db, capsys):
    # Two variants folding onto ONE shared target: the normal many-to-one
    # batch shape (Purcell's two Pavan+Chacony spellings etc.). Must NOT
    # flag as chained.
    text = ("('Marin Marais', 'Mop mqp nqp', 'Target one xx'),\n"
            "('Marin Marais', 'Qqq rr ss', 'Target one xx'),\n")
    rc = _run(db, text)
    out = capsys.readouterr().out
    assert rc == 0
    assert "chained" not in out


def test_true_chain_target_equals_earlier_variant_fails(db, capsys):
    # A->B then B->C: B was an earlier VARIANT => second line chains.
    # line 2's TARGET ('Mop mqp nqp' -> its key) equals line 1's VARIANT key
    text = ("('Marin Marais', 'Mop mqp nqp', 'Target one xx'),\n"
            "('Marin Marais', 'Qqq rr ss', 'Nqp mop mqp'),\n")
    with pytest.raises(SystemExit) as ei:
        _run(db, text)
    assert ei.value.code == 1 and "chained" in capsys.readouterr().out
