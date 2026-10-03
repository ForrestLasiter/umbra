"""Every profile x every face, the way Forrest actually runs them.

The bugs this file exists to catch were all "simple but unchecked": the HUD said
"umbra stock" while the box was in paranoid, Tor never showed as on, and `umbra
audit` with no argument audited `home`. Each face (HUD line, waybar JSON, conky,
audit) is driven through the REAL pipeline -- profile -> module controls -> audit
-> capability grading -> rendering -- for every shipped profile, twice:

  * as root            (sudo umbra audit / the engine): everything readable;
  * as the desktop user (the HUD, conky, the tray) WITHOUT `umbra-hud-access`:
    the nft-backed controls (firewall, killswitch) can't be read -> UNKNOWN.

Only the system itself is faked (the controls a profile owns are reported in the
state that profile leaves them in), so a profile whose controls don't cover what it
promises, a label that drifts from the profile, or a grader that turns "can't read"
into "failed" all fail here -- on Windows, in CI, before a Kali box ever sees it.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from umbra import audit, cli, conky, hud, paths, snapshots
from umbra.auditmodel import Status
from umbra.engine import Engine
from umbra.model import Compliance, ControlState
from umbra.modules import build_modules
from umbra.profiles import load_profile
from umbra.runner import RunResult, Runner

PROFILES = ["normal", "home", "travel", "paranoid"]

# Controls whose state is read from nftables -- unreadable to a non-root user
# unless `sudo umbra-hud-access enable` installed the read-only sudo rule.
_NFT_CONTROLS = {"netdark.inbound_policy", "tunnel.killswitch"}


class _ProbeRunner:
    """Answers the audit's independent probes (ss / ip route get / ip link) the
    way real Kali does in that posture -- including wg-quick's policy routing,
    where the main table's default route still says wlan0 and the tunnel
    interface is named after the config (`vpn`), not `wg*`."""
    dry_run = False

    def __init__(self, egress: str):
        self.egress = egress

    def run(self, argv, read_only=True, **_):
        if argv[:1] == ["ss"]:
            return RunResult(argv, 0, "", "", True, True)                # nothing listening
        if argv[:3] == ["ip", "route", "get"]:
            return RunResult(argv, 0, self.egress + "\n    cache\n", "", True, True)
        if argv[:2] == ["ip", "-d"] and argv[-1] == "vpn":
            return RunResult(argv, 0, "5: vpn: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1420 "
                             "link/none  promiscuity 0 wireguard addrgenmode none", "", True, True)
        if argv[:2] == ["ip", "-d"]:
            return RunResult(argv, 0, "2: wlan0: <BROADCAST,UP> mtu 1500 link/ether "
                             "aa:bb:cc:dd:ee:ff promiscuity 0", "", True, True)
        if argv[:3] == ["ip", "route", "show"]:                   # the old probe's view
            return RunResult(argv, 0, "default via 192.168.1.1 dev wlan0\n", "", True, True)
        return RunResult(argv, 127, "", "", False, False)


def _route_for(profile: str) -> str:
    # WireGuard is a real (policy) route; Tor's transparent proxy is NAT, not a route.
    if profile == "travel":
        return "1.1.1.1 dev vpn table 51820 src 10.66.0.2 uid 1000"
    return "1.1.1.1 via 192.168.1.1 dev wlan0 src 192.168.1.50 uid 1000"


def _applied_status(profile, nft_readable: bool) -> dict:
    """Each module's controls, in the state `profile` leaves them in."""
    status: dict = {}
    for name, mod in build_modules(Runner(dry_run=True)).items():
        mod.configure(profile.module_config(name))
        states = {}
        if mod.enabled:
            for ctrl in mod.controls():
                comp = Compliance.COMPLIANT
                if not nft_readable and ctrl.id in _NFT_CONTROLS:
                    comp = Compliance.UNKNOWN
                states[ctrl.id] = ControlState(ctrl.id, comp)
        status[name] = states
    return status


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    """A machine in posture P: marker written, controls in P's state."""
    monkeypatch.setenv("UMBRA_STATE_DIR", str(tmp_path / "state"))

    def put_in(profile_name: str, nft_readable: bool = True):
        prof = load_profile(profile_name)
        # `umbra normal` clears the marker; every other apply records itself.
        if profile_name == "normal":
            snapshots.clear_active_profile()
        else:
            snapshots.set_active_profile(profile_name)
        st = _applied_status(prof, nft_readable)
        monkeypatch.setattr(Engine, "status", lambda self, p: st)
        return _ProbeRunner(_route_for(profile_name))

    return put_in


def _hud(runner):
    """Exactly what the HUD does each tick."""
    active = snapshots.active_profile()
    report = audit.run_audit(runner, load_profile(active or "normal"))
    return active, report, {s.label: s for s in hud.build_segments(report, active)}


# --- what every face must say, per profile -----------------------------------

# label, fw, vpn, tor  (score 100 for every profile that promises anything)
_EXPECT = {
    "normal":   ("normal",   "n/a", "off", "off"),
    "home":     ("home",     "on",  "off", "off"),
    "travel":   ("travel",   "on",  "up",  "off"),
    "paranoid": ("paranoid", "on",  "off", "on"),
}


@pytest.mark.parametrize("name", PROFILES)
def test_hud_as_root_shows_the_profile_and_its_promises(machine, name):
    runner = machine(name)
    active, report, seg = _hud(runner)
    label, fw, vpn, tor = _EXPECT[name]

    assert seg["umbra"].value == label                  # never "stock" / "none"
    assert seg["fw"].value == fw
    assert seg["vpn"].value == vpn
    assert seg["tor"].value == tor
    if load_profile(name).requires:
        assert report.score() == 100, [c.evidence for c in report.checks if c.status is Status.FAIL]
        assert seg["score"].value == "100"
    else:
        assert seg["score"].value == "n/a"              # normal promises nothing
    assert not [s for s in seg.values() if s.status is Status.FAIL]


@pytest.mark.parametrize("name", PROFILES)
def test_hud_as_desktop_user_never_reports_unreadable_as_off(machine, name):
    # No HUD access: firewall + killswitch read UNKNOWN. That must surface as n/a,
    # never as "off" or a failure -- and the label/score must still be right.
    runner = machine(name, nft_readable=False)
    active, report, seg = _hud(runner)
    label, _fw, vpn, tor = _EXPECT[name]

    assert seg["umbra"].value == label
    assert seg["fw"].value == "n/a"
    assert seg["vpn"].value == vpn
    assert seg["tor"].value == ("n/a" if tor == "on" else tor)   # can't verify != off
    assert not [s for s in seg.values() if s.status is Status.FAIL]
    if load_profile(name).requires:
        assert report.score() == 100                    # graded over what's verifiable


@pytest.mark.parametrize("name", PROFILES)
def test_every_promise_has_a_control_behind_it(machine, name):
    # A required capability with no matching control is a profile bug (it would
    # read "no matching control present on this host" and fail on every box).
    runner = machine(name)
    report = audit.run_audit(runner, load_profile(name))
    for r in report.required:
        assert "no matching control" not in r.detail, (name, r.token)


@pytest.mark.parametrize("name", PROFILES)
def test_conky_and_waybar_agree_with_the_hud(machine, name):
    runner = machine(name)
    active, report, seg = _hud(runner)
    label = _EXPECT[name][0]

    block = conky.render_block(report, active, color=False)
    assert f"posture {label}" in block
    assert "✗" not in block                         # no ✗ on an applied profile
    assert conky.field(report, active, "active") == label

    wb = json.loads(hud.render_waybar(list(seg.values()), active, report.score()))
    assert wb["class"] != "fail"
    assert f"umbra posture: {label}" in wb["tooltip"]


@pytest.mark.parametrize("name", PROFILES)
def test_bare_commands_target_the_active_profile(machine, name, capsys):
    runner = machine(name)
    # `umbra hud --once --plain` / `umbra conky --field active`, as typed.
    monkeypatch_runner = lambda *a, **k: runner                 # noqa: E731
    cli_runner = cli.Runner
    try:
        cli.Runner = monkeypatch_runner
        assert cli.main(["hud", "--once", "--plain"]) == 0
        line = capsys.readouterr().out
        assert f"umbra {_EXPECT[name][0]}" in line
        assert cli.main(["conky", "--field", "profile"]) == 0
        audited = capsys.readouterr().out.strip()
        # a bare `umbra audit` must audit the posture you're IN, not `home`
        assert cli.main(["--json", "audit"]) == 0
        audit_profile = json.loads(capsys.readouterr().out)["profile"]
    finally:
        cli.Runner = cli_runner
    # always-on faces: nothing applied -> normal
    assert audited == (name if name != "normal" else "normal")
    # interactive commands: the active profile; nothing applied -> home ("what
    # would home fix?") -- the header names it, so it's never ambiguous
    assert audit_profile == (name if name != "normal" else "home")


# --- the state dir: root writes it, the desktop user must read it ------------

def test_reader_uses_the_system_state_dir_even_when_it_cannot_write(monkeypatch):
    # The root cause of "umbra stock": state_dir() only chose /var/lib/umbra when
    # /var/lib was WRITABLE, so every non-root reader read an empty dev folder.
    monkeypatch.delenv("UMBRA_STATE_DIR", raising=False)
    real_is_dir = paths.Path.is_dir
    monkeypatch.setattr(paths.Path, "is_dir",
                        lambda self: self.as_posix() == "/var/lib/umbra" or real_is_dir(self))
    monkeypatch.setattr(paths.os, "access", lambda *a, **k: False)   # not root
    assert paths.state_dir().as_posix() == "/var/lib/umbra"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_marker_is_world_readable_and_snapshots_stay_private(tmp_path, monkeypatch):
    # Kali's root umask is 027 and mkstemp makes 0600 files: without explicit
    # modes the marker was root-only and the HUD couldn't see the posture.
    monkeypatch.setenv("UMBRA_STATE_DIR", str(tmp_path / "state"))
    old = os.umask(0o027)
    try:
        with snapshots.Transaction(Runner(dry_run=False), "paranoid"):
            pass
        snapshots.set_active_profile("paranoid")
    finally:
        os.umask(old)
    sd = paths.state_dir()
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)          # noqa: E731
    assert mode(sd) == 0o755
    assert mode(sd / "active-profile") == 0o644
    assert mode(sd / "current") == 0o644
    assert mode(paths.transactions_dir()) == 0o700          # prior /etc copies: root only


def test_installers_repair_state_permissions_on_existing_boxes():
    root = paths._REPO_ROOT
    for f in ("install.sh", "packaging/build-deb.sh"):
        text = (root / f).read_text()
        assert "chmod 0755 /var/lib/umbra" in text, f
        assert "chmod 0700 /var/lib/umbra/transactions" in text, f
        assert 'chmod 0644 "/var/lib/umbra/$f"' in text, f
