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


def test_run_audit_returns_checks_without_error():
    # On any OS: probes must not throw; off-Linux they degrade to NA/INFO.
    report = run_audit(Runner(dry_run=False), load_profile("home"))
    assert len(report.checks) == 8
    assert all(isinstance(c.status, Status) for c in report.checks)
