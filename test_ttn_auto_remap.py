"""Tests for ttn_auto_remap's resolution tiers.

Run: uv run --with pytest pytest test_ttn_auto_remap.py
"""
import ttn_auto_remap as arm


def _reg(works=None, composers=None):
    base = {
        "version": 1,
        "works": works or {},
        "composers": composers or {},
        "redirects": {"works": {}, "composers": {}},
        "retired": {"works": {}, "composers": {}},
    }
    return base


def test_token_overlap_is_symmetric():
    assert arm._token_overlap("excerpts janos vitez",
                              "excerpts hero janos john sir the vitez") == 1.0
    assert arm._token_overlap("c1863 pasquinade", "pasquinade") == 1.0
    assert arm._token_overlap("adagio", "adagio and fugue") == 1.0


def test_content_evidence_rejects_pure_movement_subset():
    # A movement-vs-whole-work subset has no non-generic shared token.
    assert arm._has_content_evidence("adagio", "adagio and fugue") is False
    assert arm._has_content_evidence("aria", "aria from tosca") is False
    # A real work rephrasing shares a content token.
    assert arm._has_content_evidence("pasquinade c1863", "pasquinade") is True
    assert arm._has_content_evidence("ardor humano llegais que",
                                     "ardor humano llegais que") is True


def test_resolve_work_orphan_tier_a_composer_folded_exact_key():
    reg = _reg(works={
        "auber:overture-from-le-cheval-de-bronze": {
            "composer_key": "daniel francois esprit auber",
            "work_key": "bronze cheval de from le overture",
            "published": "2026-01-01",
        },
    })
    # The current corpus has the same work key under the resolved composer.
    derived = {
        ("daniel auber", "bronze cheval de from le overture"): {"key": ("daniel auber", "bronze cheval de from le overture"), "slug": "auber:overture-from-le-cheval-de-bronze"},
    }
    result = arm.resolve_work_orphan(
        "auber:overture-from-le-cheval-de-bronze", reg, derived, {}, {})
    assert result["tier"] == "A"
    assert result["composer_key"] == "daniel auber"
    assert result["work_key"] == "bronze cheval de from le overture"


def test_resolve_work_orphan_tier_b_recording_pid_overlap():
    reg = _reg(works={
        "kacsoh:janos-vitez-excerpts": {
            "composer_key": "pongrac kacsoh",
            "work_key": "excerpts janos vitez",
            "published": "2026-01-01",
        },
    })
    stale = {"kacsoh:janos-vitez-excerpts": {"p00xc15f", "p01fgjfz"}}
    current = {
        ("pongrac kacsoh", "excerpts hero janos john sir the vitez"): {"p00xc15f", "p01fgjfz"},
        ("pongrac kacsoh", "hero janos john the vitez"): {"p00xbymr"},
    }
    # Empty derived: tier A won't fire (keys differ).
    derived = {k: {"key": k, "slug": "x"} for k in current}
    result = arm.resolve_work_orphan(
        "kacsoh:janos-vitez-excerpts", reg, derived, stale, current)
    assert result["tier"] == "B"
    assert result["composer_key"] == "pongrac kacsoh"
    assert result["work_key"] == "excerpts hero janos john sir the vitez"


def test_resolve_work_orphan_tier_b_requires_unique_overlap():
    reg = _reg(works={
        "x:ambiguous": {
            "composer_key": "composer",
            "work_key": "old key",
            "published": "2026-01-01",
        },
    })
    stale = {"x:ambiguous": {"rp-shared"}}
    current = {
        ("composer", "candidate a"): {"rp-shared"},
        ("composer", "candidate b"): {"rp-shared"},
    }
    derived = {k: {"key": k, "slug": "x"} for k in current}
    result = arm.resolve_work_orphan("x:ambiguous", reg, derived, stale, current)
    # Non-unique overlap falls through to token review; the two candidate work
    # keys share no content token with "old key", so it lands in D.
    assert result["tier"] in ("C", "D")


def test_resolve_work_orphan_tier_c_rejects_movement_subset():
    reg = _reg(works={
        "x:adagio": {
            "composer_key": "composer",
            "work_key": "adagio",
            "published": "2026-01-01",
        },
    })
    derived = {
        ("composer", "adagio and fugue"): {"key": ("composer", "adagio and fugue"), "slug": "x:adagio-and-fugue"},
    }
    result = arm.resolve_work_orphan("x:adagio", reg, derived, {}, {})
    assert result["tier"] == "D"


def test_resolve_work_orphan_tier_d_catalogue_key_no_token_overlap():
    reg = _reg(works={
        "bach:wq243": {
            "composer_key": "carl philipp emanuel bach",
            "work_key": "§wq243|243|",
            "published": "2026-01-01",
        },
    })
    derived = {
        ("carl philipp emanuel bach", "anbetung cantata dem easter erbarmer"): {
            "key": ("carl philipp emanuel bach", "anbetung cantata dem easter erbarmer"),
            "slug": "bach:anbetung",
        },
    }
    result = arm.resolve_work_orphan("bach:wq243", reg, derived, {}, {})
    # No shared content token: the catalogue key has no title words.
    assert result["tier"] == "D"


def test_resolve_composer_orphan_alias_fold():
    reg = _reg(composers={
        "daniel-francois-esprit-auber-2": {
            "composer_key": "daniel francois esprit auber",
            "published": "2026-01-01",
        },
    })
    derived = {"daniel auber": {"composer_key": "daniel auber"}}
    result = arm.resolve_composer_orphan("daniel-francois-esprit-auber-2", reg, derived)
    assert result["tier"] == "A"
    assert result["composer_key"] == "daniel auber"


def test_parse_orphans_extracts_both_namespaces():
    raw = ("orphaned work slugs: ['a', 'b']; orphaned composer slugs: ['c']")
    works, composers = arm._parse_orphans(raw)
    assert works == ["a", "b"]
    assert composers == ["c"]


def test_unparseable_nonempty_stdin_is_an_error(capsys):
    # The nightly feeds `site --check`'s stderr in; a non-drift failure
    # (stale projection etc.) produces text that matches neither orphan
    # regex. That must be exit 1 -- exit 0 would log "auto-remap succeeded"
    # and send the nightly into a doomed rebuild.
    import io
    from unittest.mock import patch

    with patch("sys.stdin", io.StringIO("projection cache status='stale'")):
        rc = arm.main(["--dry-run"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no orphan slugs parsed" in err
