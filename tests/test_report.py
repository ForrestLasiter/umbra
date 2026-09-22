"""Audit report + HTML dashboard tests (pure, run on any OS)."""

from __future__ import annotations

from umbra.audit import AuditReport, Check, Status, run_audit
from umbra.profiles import load_profile
from umbra.report import render_html
from umbra.runner import Runner


def _sample() -> AuditReport:
    return AuditReport(
        profile="home",
        generated_at="2026-09-19T00:00:00+00:00",
        checks=[
            Check("firewall", "Inbound firewall", "firewall", Status.OK, "default DROP"),
            Check("exposure", "Listening TCP sockets", "exposure", Status.WARN,
                  "reachable: 0.0.0.0:22", "close it"),
            Check("evil", "Escaping test", "dns", Status.INFO, "<script>alert(1)</script>"),
        ],
    )


def test_counts():
    assert _sample().counts()["ok"] == 1
    assert _sample().counts()["warn"] == 1


def test_score_is_none_when_no_required_capabilities():
    # _sample() declares no required caps -> nothing to grade -> None
    assert _sample().score() is None


def test_html_is_accessible_and_escaped():
    doc = render_html(_sample())
    # WCAG basics
    assert '<html lang="en">' in doc
    assert doc.count("<h1") == 1
    assert 'scope="col"' in doc and 'scope="row"' in doc
    assert 'class="skip-link"' in doc
    # status conveyed by TEXT, not colour alone (SC 1.4.1)
    assert ">OK<" in doc and ">Warning<" in doc
    # evidence is HTML-escaped (no injection)
    assert "&lt;script&gt;" in doc
    assert "<script>alert(1)</script>" not in doc


def test_live_mode_adds_an_accessible_refresh_link():
    doc = render_html(_sample(), live=True)
    assert '<a href="/">Refresh</a>' in doc      # a real link, not a meta-refresh
    assert "http-equiv=\"refresh\"" not in doc    # no forced timing (WCAG 2.2.1)
    assert "live view" in doc


def test_run_audit_is_profile_aware_and_has_required_checks():
    # On any OS: probes must not throw; off-Linux they degrade to NA/INFO.
    report = run_audit(Runner(dry_run=False), load_profile("home"))
    assert len(report.checks) > 10                       # per-control + required + probes
    assert all(isinstance(c.status, Status) for c in report.checks)
    # every required capability the profile declares appears as a check
    for token in load_profile("home").requires:
        assert any(c.id == f"require:{token}" for c in report.checks)
    # off-Linux nothing is gradeable -> score is None (not a fake 100)
    assert report.score() is None
