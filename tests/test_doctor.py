"""umbra doctor tests (cross-platform; tool presence varies, structure doesn't)."""

from __future__ import annotations

from umbra.doctor import run_doctor
from umbra.profiles import load_profile
from umbra.runner import Runner


def test_doctor_reports_checks_and_readiness_flag():
    report = run_doctor(Runner(dry_run=False), load_profile("home"))
    assert report.profile == "home"
    assert report.checks                       # produced some checks
    assert isinstance(report.ready, bool)


def test_doctor_paranoid_checks_for_tor():
    report = run_doctor(Runner(dry_run=False), load_profile("paranoid"))
    names = [c.name for c in report.checks]
    assert "tor" in names                       # tor mode -> needs the tor daemon


def test_doctor_travel_checks_for_wireguard_config():
    report = run_doctor(Runner(dry_run=False), load_profile("travel"))
    assert any("wireguard config" in c.name for c in report.checks)
