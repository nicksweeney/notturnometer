import pytest
import ttn_curate as C


def test_each_subcommand_routes_with_passthrough_argv(monkeypatch):
    """Every subcommand calls its module's main() with argv[1:] verbatim."""
    import ttn_duplicates, ttn_composer_duplicates, ttn_audit
    import ttn_audit_composer, ttn_mbid_audit
    cases = {
        "duplicates":          ttn_duplicates,
        "composer-duplicates": ttn_composer_duplicates,
        "audit":               ttn_audit,
        "audit-composer":      ttn_audit_composer,
        "mbid-audit":          ttn_mbid_audit,
    }
    for sub, module in cases.items():
        captured = {}
        monkeypatch.setattr(module, "main", lambda argv, _c=captured: _c.setdefault("argv", argv))
        C.main([sub, "db.sqlite", "--emit", "--composer", "X"])
        assert captured["argv"] == ["db.sqlite", "--emit", "--composer", "X"]


def test_unknown_subcommand_errors_with_usage(capsys):
    with pytest.raises(SystemExit) as ei:
        C.main(["bogus"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err and "duplicates" in err


def test_no_args_prints_usage(capsys):
    rc = C.main([])
    out = capsys.readouterr().out
    for name in ("duplicates", "composer-duplicates", "audit", "audit-composer", "mbid-audit"):
        assert name in out
    assert rc == 0


def test_help_flag_prints_usage(capsys):
    rc = C.main(["--help"])
    assert "subcommand" in capsys.readouterr().out.lower()
    assert rc == 0


def test_delegates_real_help_to_tool(monkeypatch):
    """--help after a subcommand reaches the tool's argparse (SystemExit 0)."""
    with pytest.raises(SystemExit) as ei:
        C.main(["mbid-audit", "--help"])
    assert ei.value.code == 0


def test_bridge_and_oracle_subcommands_route(monkeypatch):
    import ttn_bridge, ttn_spine
    for sub, module in [("bridge", ttn_bridge), ("work-alias-candidates", ttn_spine)]:
        captured = {}
        monkeypatch.setattr(module, "main", lambda argv, _c=captured: _c.setdefault("argv", argv))
        C.main([sub, "db.sqlite", "--composer", "X"])
        assert captured["argv"] == ["db.sqlite", "--composer", "X"]


def test_staff_mains_drop_ranking_surface():
    """Repurposed mains reject the retired customer flags."""
    import pytest, ttn_bridge, ttn_spine
    with pytest.raises(SystemExit):
        ttn_bridge.main(["db", "--by", "recording"])     # bridge --by removed
    with pytest.raises(SystemExit):
        ttn_spine.main(["db", "--by", "recording"])       # spine ranking removed
