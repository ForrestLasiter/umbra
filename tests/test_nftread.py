"""Firewall reads without root: never report "off" just because we couldn't look.

Regression for: the HUD (running as the user, never root) showed firewall=off
while `sudo umbra audit` showed it verified. An unprivileged `nft list ruleset`
is refused by the kernel; the probe saw empty output and called it DRIFT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from umbra import nftread
from umbra.modules.base import Compliance
from umbra.modules.netdark import NetdarkModule
from umbra.modules.tunnel import TunnelModule
from umbra.runner import RunResult

ROOT = Path(__file__).resolve().parent.parent

_UMBRA_RULESET = (
    "table inet umbra {\n\tchain input {\n"
    '\t\tmeta l4proto ipv6-icmp accept comment "umbra:managed neighbour discovery"\n'
    "\t}\n}\n"
)


class FakeRunner:
    """Answers every command with one canned result and records the argv."""

    dry_run = False

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def run(self, argv, *, read_only, check=False, input_text=None):
        self.calls.append(argv)
        return self.result


def _res(rc: int, out: str = "", err: str = "", available: bool = True) -> RunResult:
    return RunResult(["nft"], rc, out, err, executed=available, available=available)


def _netdark(runner) -> NetdarkModule:
    m = NetdarkModule(runner)
    m.config = {"enabled": True, "inbound_policy": "drop"}
    return m


@pytest.fixture
def as_user(monkeypatch):
    monkeypatch.setattr(nftread, "_is_root", lambda: False)


@pytest.fixture
def as_root(monkeypatch):
    monkeypatch.setattr(nftread, "_is_root", lambda: True)


# --- which command gets run --------------------------------------------------

def test_root_runs_nft_directly(as_root):
    r = FakeRunner(_res(0, _UMBRA_RULESET))
    nftread.list_ruleset(r)
    assert r.calls == [["nft", "list", "ruleset"]]


def test_user_asks_sudo_non_interactively_for_exactly_the_whitelisted_command(as_user):
    r = FakeRunner(_res(0, _UMBRA_RULESET))
    nftread.list_ruleset(r)
    # -n: never prompt (a prompt would hang the HUD). The path + args must match
    # the sudoers rule exactly, or sudo refuses.
    assert r.calls == [["sudo", "-n", "/usr/sbin/nft", "list", "ruleset"]]


def test_sudoers_rule_and_code_agree_on_the_command():
    rule = (ROOT / "packaging" / "umbra-hud.sudoers").read_text()
    assert f"Cmnd_Alias UMBRA_NFT_READ = {nftread.NFT_PATH} list ruleset" in rule


# --- what the firewall probe concludes ---------------------------------------

def test_refused_read_is_unknown_not_drift(as_user):
    # sudo -n without the rule: exit 1, "a password is required", empty stdout.
    r = FakeRunner(_res(1, "", "sudo: a password is required"))
    cs = _netdark(r)._measure_firewall()
    assert cs.compliance is Compliance.UNKNOWN
    assert "umbra-hud-access" in cs.detail       # tells the user how to fix it


def test_readable_ruleset_with_marker_is_compliant(as_user):
    cs = _netdark(FakeRunner(_res(0, _UMBRA_RULESET)))._measure_firewall()
    assert cs.compliance is Compliance.COMPLIANT


def test_readable_ruleset_without_marker_is_still_real_drift(as_user):
    # The fix must not hide a firewall that is genuinely gone.
    cs = _netdark(FakeRunner(_res(0, "table inet filter {}\n")))._measure_firewall()
    assert cs.compliance is Compliance.DRIFT


def test_empty_but_successful_read_is_drift(as_root):
    # An empty ruleset read successfully as root means: no firewall at all.
    cs = _netdark(FakeRunner(_res(0, "")))._measure_firewall()
    assert cs.compliance is Compliance.DRIFT


def test_missing_nft_is_unknown(as_root):
    cs = _netdark(FakeRunner(_res(127, available=False)))._measure_firewall()
    assert cs.compliance is Compliance.UNKNOWN


def test_killswitch_refused_read_is_unknown_not_drift(as_user):
    t = TunnelModule(FakeRunner(_res(1, "", "sudo: a password is required")))
    t.config = {"enabled": True, "mode": "wireguard"}
    cs = t._measure_killswitch()
    assert cs.compliance is Compliance.UNKNOWN


def test_is_root_does_not_crash_without_geteuid(monkeypatch):
    # Windows has no os.geteuid; the dev box runs these tests there.
    monkeypatch.delattr(nftread.os, "geteuid", raising=False)
    assert nftread._is_root() is False


# --- packaging ---------------------------------------------------------------

def test_hud_access_validates_before_installing():
    script = (ROOT / "packaging" / "hud-access.sh").read_text()
    # A broken sudoers file can break sudo machine-wide: check first, then move.
    assert script.index("visudo -cf") < script.index('install -o root -g root -m 0440')
    assert "0440" in script


def test_installers_ship_and_remove_hud_access():
    install = (ROOT / "install.sh").read_text()
    uninstall = (ROOT / "uninstall.sh").read_text()
    deb = (ROOT / "packaging" / "build-deb.sh").read_text()
    assert "--with-hud-access" in install
    assert "/usr/sbin/umbra-hud-access" in install
    assert "rm -f /etc/sudoers.d/umbra-hud" in uninstall
    assert "umbra-hud-access" in deb
    assert "rm -f /etc/sudoers.d/umbra-hud" in deb
