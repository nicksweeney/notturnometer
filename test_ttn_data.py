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
