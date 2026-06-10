import pytest
import ttn_data as D


def test_each_stage_routes_with_passthrough_argv(monkeypatch):
    """Every stage subcommand calls its module's main() with argv[1:] verbatim."""
    import ttn_scrape, ttn_segments, ttn_reparse, ttn_project, ttn_warm
    cases = {
        "scrape":   ttn_scrape,
        "segments": ttn_segments,
        "reparse":  ttn_reparse,
        "project":  ttn_project,
        "warm":     ttn_warm,
    }
    for sub, module in cases.items():
        captured = {}
        monkeypatch.setattr(module, "main", lambda argv, _c=captured: _c.setdefault("argv", argv))
        D.main([sub, "db.sqlite", "--dry-run"])
        assert captured["argv"] == ["db.sqlite", "--dry-run"]


def test_unknown_subcommand_errors_with_usage(capsys):
    with pytest.raises(SystemExit) as ei:
        D.main(["bogus"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err and "scrape" in err


def test_no_args_prints_usage(capsys):
    rc = D.main([])
    out = capsys.readouterr().out
    for name in ("scrape", "segments", "reparse", "project", "warm"):
        assert name in out
    assert rc == 0


def test_help_flag_prints_usage(capsys):
    rc = D.main(["--help"])
    assert "subcommand" in capsys.readouterr().out.lower()
    assert rc == 0


def test_delegates_real_help_to_tool():
    """--help after a stage reaches the tool's argparse (SystemExit 0)."""
    with pytest.raises(SystemExit) as ei:
        D.main(["warm", "--help"])
    assert ei.value.code == 0


def _spy_stages(monkeypatch):
    """Replace the three update stages with order/argv-recording spies."""
    import ttn_scrape, ttn_segments, ttn_warm
    calls = []
    monkeypatch.setattr(ttn_scrape, "main", lambda argv: calls.append(("scrape", argv)))
    monkeypatch.setattr(ttn_segments, "main", lambda argv: calls.append(("segments", argv)))
    monkeypatch.setattr(ttn_warm, "main", lambda argv: calls.append(("warm", argv)))
    return calls


def test_update_runs_stages_in_order(monkeypatch):
    calls = _spy_stages(monkeypatch)
    rc = D.main(["update"])
    assert [name for name, _ in calls] == ["scrape", "segments", "warm"]
    assert rc == 0


def test_update_forwards_db_and_days(monkeypatch):
    calls = _spy_stages(monkeypatch)
    D.main(["update", "--db", "X.sqlite", "--days", "30"])
    by = dict(calls)
    assert by["scrape"] == ["--db", "X.sqlite", "--days", "30"]   # scrape: flags
    assert by["segments"] == ["X.sqlite"]                          # segments: positional
    assert by["warm"] == ["X.sqlite"]                             # warm: positional


def test_update_omits_days_when_absent(monkeypatch):
    calls = _spy_stages(monkeypatch)
    D.main(["update", "--db", "X.sqlite"])
    assert dict(calls)["scrape"] == ["--db", "X.sqlite"]          # no --days -> scrape's own default


def test_update_aborts_on_stage_failure(monkeypatch):
    import ttn_scrape, ttn_segments, ttn_warm
    calls = []
    def boom(argv):
        raise SystemExit(1)
    monkeypatch.setattr(ttn_scrape, "main", boom)
    monkeypatch.setattr(ttn_segments, "main", lambda argv: calls.append("segments"))
    monkeypatch.setattr(ttn_warm, "main", lambda argv: calls.append("warm"))
    with pytest.raises(SystemExit) as ei:
        D.main(["update"])
    assert ei.value.code == 1
    assert calls == []          # segments/warm never reached


def test_update_in_usage(capsys):
    D.main([])
    assert "update" in capsys.readouterr().out
