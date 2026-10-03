"""`umbra apply` refuses up front when the profile can't succeed.

Found on Forrest's box: `doctor travel` said NOT READY (no WireGuard config), yet
`apply --confirm travel` changed 7 controls, failed on the tunnel, and -- travel
being fail-closed -- left them in place. A missing prerequisite must stop apply
BEFORE it touches the system.
"""

from __future__ import annotations

import argparse

import pytest

from umbra import cli, doctor
from umbra.engine import ApplyReport
from umbra.runner import Runner


@pytest.fixture()
def calls(monkeypatch):
    seen = {"applied": []}
    monkeypatch.setattr(cli, "_require_privilege", lambda dry_run: None)

    def fake_apply(self, profile):
        seen["applied"].append(profile.name)
        return ApplyReport(profile=profile.name, transaction_id="tx")
    monkeypatch.setattr(cli.Engine, "apply", fake_apply)
    return seen


def _doctor_says(monkeypatch, *checks):
    monkeypatch.setattr(doctor, "run_doctor",
                        lambda runner, profile: doctor.DoctorReport(profile.name, list(checks)))


def _args(profile="travel", **kw):
    return argparse.Namespace(profile=profile, profiles_dir=None, confirm=True, **kw)


_MISSING_CONF = doctor.DoctorCheck(
    "wireguard config (vpn)", False,
    "missing /etc/wireguard/vpn.conf - import yours:  sudo umbra vpn <file.conf>")


def test_not_ready_refuses_and_changes_nothing(calls, monkeypatch, capsys):
    _doctor_says(monkeypatch, doctor.DoctorCheck("nft", True), _MISSING_CONF)
    assert cli.cmd_apply(_args(), Runner(dry_run=False)) == 2
    assert calls["applied"] == []                            # never reached the engine
    out = capsys.readouterr().out
    assert "can't be applied yet" in out
    assert "wireguard config (vpn)" in out and "sudo umbra vpn" in out
    assert "nothing was changed" in out


def test_ready_profile_applies(calls, monkeypatch):
    _doctor_says(monkeypatch, doctor.DoctorCheck("nft", True))
    assert cli.cmd_apply(_args(), Runner(dry_run=False)) == 0
    assert calls["applied"] == ["travel"]


def test_optional_and_needs_sudo_checks_do_not_block(calls, monkeypatch):
    _doctor_says(monkeypatch,
                 doctor.DoctorCheck("pkexec", False, "missing", optional=True),
                 doctor.DoctorCheck("wireguard config (vpn)", False, "root-only", needs_root=True))
    assert cli.cmd_apply(_args(), Runner(dry_run=False)) == 0
    assert calls["applied"] == ["travel"]


def test_dry_run_warns_but_still_previews(calls, monkeypatch, capsys):
    _doctor_says(monkeypatch, _MISSING_CONF)
    cli.cmd_apply(_args(), Runner(dry_run=True))
    assert calls["applied"] == ["travel"]
    assert "would fail" in capsys.readouterr().out


def test_panic_skips_preflight_and_goes_dark_anyway(calls, monkeypatch):
    _doctor_says(monkeypatch, doctor.DoctorCheck("tor", False, "missing - needed for tor"))
    cli.cmd_panic(argparse.Namespace(profiles_dir=None), Runner(dry_run=False))
    assert calls["applied"] == ["paranoid"]                  # emergency: raise what we can


def test_preflight_runs_before_a_switch_unwinds_the_current_posture(calls, monkeypatch):
    # The refusal happens in cmd_apply, before Engine.apply (where the unwind
    # lives), so the current posture is never touched.
    _doctor_says(monkeypatch, _MISSING_CONF)
    unwound = []
    monkeypatch.setattr(cli.snapshots, "restore_chain", lambda r: unwound.append(1) or [])
    cli.cmd_apply(_args(), Runner(dry_run=False))
    assert unwound == [] and calls["applied"] == []
