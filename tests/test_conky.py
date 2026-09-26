"""Conky widget rendering tests (pure, run on any OS)."""

from __future__ import annotations

import pytest

from umbra import conky
from umbra.auditmodel import AuditReport, Check, Status
from umbra.capabilities import CapResult


def _report() -> AuditReport:
    checks = [
        Check("require:firewall", "Required: firewall", "required", Status.OK, "verified"),
        Check("require:tor", "Required: tor", "required", Status.FAIL, "not verified"),
        Check("exposure", "Listening TCP sockets", "exposure", Status.OK,
              "nothing listening beyond loopback"),
    ]
    required = [CapResult("firewall", True, True, "verified"),
                CapResult("tor", False, True, "drift")]
    return AuditReport("home", "2026-01-01T00:00:00+00:00", checks=checks, required=required)


def test_block_has_header_and_a_line_per_required_capability():
    out = conky.render_block(_report(), active="home")
    assert "umbra" in out and "posture" in out and "home" in out
    assert "firewall" in out and "tor" in out
    assert "nothing listening beyond loopback" in out          # the exposure probe line
    assert out.count("\n") == 3                                 # 4 lines: header + 2 caps + exposure


def test_color_markup_is_conky_and_toggleable():
    colored = conky.render_block(_report(), active="home", color=True)
    plain = conky.render_block(_report(), active="home", color=False)
    assert "${color " in colored and "${color}" in colored
    assert "${color" not in plain


def test_ok_and_fail_use_different_colors():
    out = conky.render_block(_report(), active="home", color=True)
    assert "8ae234" in out          # OK green (firewall)
    assert "ef2929" in out          # FAIL red (tor)


def test_score_field_and_counts():
    r = _report()
    assert conky.field(r, "home", "score") == "50"     # 1 of 2 required verified
    assert conky.field(r, "home", "profile") == "home"
    assert conky.field(r, "travel", "active") == "travel"
    assert conky.field(r, None, "active") == "none"
    assert conky.field(r, "home", "ok") == "2"         # firewall + exposure
    assert conky.field(r, "home", "fail") == "1"
    assert conky.field(r, "home", "tor") == "fail"


def test_score_field_is_blank_when_ungradeable():
    r = AuditReport("home", "t", checks=[], required=[])
    assert conky.field(r, "home", "score") == ""       # None -> empty for Conky


def test_unknown_field_raises():
    with pytest.raises(KeyError):
        conky.field(_report(), "home", "nonsense")
