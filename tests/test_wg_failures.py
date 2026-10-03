"""When the WireGuard tunnel won't start, say why and what to do.

Found on Forrest's box: `sudo umbra apply --confirm travel` failed with only
systemd's "see journalctl -xeu wg-quick@vpn.service", printed as a Python list
with literal \\n escapes, twice. On Kali the usual cause is a `DNS =` line (every
commercial VPN config has one) with no resolvconf installed. These pin: the
journal is read and turned into a fix, doctor catches it before apply, and the
failure prints as readable lines.
"""

from __future__ import annotations

import os

import pytest

from umbra import cli, doctor
from umbra.engine import ApplyReport
from umbra.modules.tunnel import TunnelModule, diagnose_unit_failure
from umbra.profiles import load_profile
from umbra.runner import RunResult

UNIT = "wg-quick@vpn.service"


# --- diagnosis -------------------------------------------------------------------

@pytest.mark.parametrize("journal, expect", [
    ("[#] ip link add vpn type wireguard\n[#] resolvconf -a vpn -m 0 -x\n"
     "/usr/bin/wg-quick: line 32: resolvconf: command not found",
     "sudo apt install openresolv"),
    ("wg-quick: `/etc/wireguard/vpn.conf' does not exist", "sudo umbra vpn"),
    ("Name or service not known: `vpn.example.com:51820'", "doesn't resolve"),
    ("wg-quick: `vpn' already exists", "sudo wg-quick down"),
    ("Key is not the correct length or format: `abc'", "malformed"),
])
def test_known_causes_become_a_fix(journal, expect):
    msg = diagnose_unit_failure(UNIT, journal)
    assert msg.startswith(f"{UNIT} failed to start")
    assert expect in msg


def test_dns_line_advice_warns_against_just_deleting_it():
    msg = diagnose_unit_failure(UNIT, "resolvconf: command not found")
    assert "outside the tunnel" in msg            # deleting DNS = would leak lookups


def test_unknown_cause_shows_the_actual_log_lines():
    msg = diagnose_unit_failure(UNIT, "line one\nsomething odd happened\n")
    assert "something odd happened" in msg and "Last log lines" in msg


# --- the start path ----------------------------------------------------------------

class _Runner:
    dry_run = False

    def __init__(self, journal: str):
        self.journal, self.calls = journal, []

    def run(self, argv, read_only=True, check=False, **_):
        self.calls.append(argv)
        if argv[:2] == ["systemctl", "start"] and check:
            raise RuntimeError(f"command failed (1): {' '.join(argv)}\nJob for {UNIT} failed "
                               "because the control process exited with error code.")
        if argv[:1] == ["journalctl"]:
            return RunResult(argv, 0, self.journal, "", True, True)
        return RunResult(argv, 0, "", "", True, True)


class _Snap:
    def record(self, *a):
        pass


def test_failed_tunnel_start_raises_the_diagnosis_not_see_journalctl():
    r = _Runner("/usr/bin/wg-quick: line 32: resolvconf: command not found\n")
    mod = TunnelModule(r)
    mod.configure({"enabled": True, "mode": "wireguard", "profile_ref": "vpn"})
    with pytest.raises(RuntimeError) as ei:
        mod._apply_route(_Snap())
    msg = str(ei.value)
    assert "openresolv" in msg
    assert "see \"systemctl status" not in msg.lower()
    assert ["journalctl", "-u", UNIT, "-n", "25", "--no-pager", "-o", "cat"] in r.calls


# --- doctor -------------------------------------------------------------------------

class _WhichRunner:
    def __init__(self, have: set[str]):
        self.have = have

    def which(self, binary):
        return binary in self.have


_BASE_TOOLS = {"nft", "systemctl", "sysctl", "rfkill", "nmcli", "wg-quick", "pkexec"}
_CONF = "[Interface]\nPrivateKey = x\nAddress = 10.66.0.2/32\n{dns}\n[Peer]\nPublicKey = y\nEndpoint = 1.2.3.4:51820\n"


def _wg(report):
    return {c.name: c for c in report.checks}


def test_doctor_flags_missing_resolvconf_when_config_has_a_dns_line(tmp_path, monkeypatch):
    (tmp_path / "vpn.conf").write_text(_CONF.format(dns="DNS = 10.64.0.1"))
    monkeypatch.setattr(doctor, "_WG_DIR", tmp_path)
    rep = doctor.run_doctor(_WhichRunner(_BASE_TOOLS), load_profile("travel"))
    checks = _wg(rep)
    assert checks["wireguard config (vpn)"].ok
    assert not checks["resolvconf"].ok and "openresolv" in checks["resolvconf"].detail
    assert not rep.ready                              # caught BEFORE apply


def test_doctor_is_happy_without_a_dns_line_or_with_resolvconf(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_WG_DIR", tmp_path)
    (tmp_path / "vpn.conf").write_text(_CONF.format(dns=""))
    assert "resolvconf" not in _wg(doctor.run_doctor(_WhichRunner(_BASE_TOOLS), load_profile("travel")))
    (tmp_path / "vpn.conf").write_text(_CONF.format(dns="DNS = 10.64.0.1"))
    rep = doctor.run_doctor(_WhichRunner(_BASE_TOOLS | {"resolvconf"}), load_profile("travel"))
    assert rep.ready


def test_doctor_missing_config_points_at_umbra_vpn(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_WG_DIR", tmp_path)
    c = _wg(doctor.run_doctor(_WhichRunner(_BASE_TOOLS), load_profile("travel")))["wireguard config (vpn)"]
    assert not c.ok and "sudo umbra vpn" in c.detail


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a non-root POSIX user")
def test_doctor_as_user_says_rerun_with_sudo_not_missing(tmp_path, monkeypatch):
    wg = tmp_path / "wireguard"
    wg.mkdir()
    (wg / "vpn.conf").write_text(_CONF.format(dns=""))
    wg.chmod(0o700)
    os.chmod(wg, 0o000)                               # like root-only /etc/wireguard
    try:
        monkeypatch.setattr(doctor, "_WG_DIR", wg)
        c = _wg(doctor.run_doctor(_WhichRunner(_BASE_TOOLS), load_profile("travel")))["wireguard config (vpn)"]
    finally:
        os.chmod(wg, 0o700)
    assert c.needs_root and "sudo umbra doctor travel" in c.detail


# --- readable output -------------------------------------------------------------------

def test_failures_print_as_lines_not_a_list_repr(capsys):
    rep = ApplyReport(profile="travel", transaction_id="tx")
    rep.failed.append(diagnose_unit_failure(UNIT, "resolvconf: command not found"))
    cli._print_apply(rep, dry_run=False)
    out = capsys.readouterr().out
    assert "['" not in out and "\\n" not in out
    assert f"    ! {UNIT} failed to start" in out
    assert "      Your WireGuard config has a `DNS =` line" in out


def test_doctor_does_not_claim_ready_when_part_of_it_was_unreadable(capsys, monkeypatch):
    rep = doctor.DoctorReport("travel", [
        doctor.DoctorCheck("wg-quick", True, "the WireGuard tunnel"),
        doctor.DoctorCheck("wireguard config (vpn)", False,
                           "/etc/wireguard is root-only; check it with:  sudo umbra doctor travel",
                           needs_root=True)])
    monkeypatch.setattr(doctor, "run_doctor", lambda r, p: rep)
    import argparse
    assert cli.cmd_doctor(argparse.Namespace(profile="travel", profiles_dir=None), None) == 0
    out = capsys.readouterr().out
    assert "READY SO FAR" in out and "sudo umbra doctor travel" in out
    assert "\n  READY\n" not in out
