"""rf — reduce the machine's radio-frequency signature.

Phase-2 controls:
  * mac            -- a NetworkManager drop-in that randomizes the MAC address
                      and randomizes MACs during scanning (which suppresses a
                      stable, trackable probe-request fingerprint).
  * radio_<type>   -- hard rfkill soft-block for any radio the profile does NOT
                      permit (radios: [wifi] blocks bluetooth/wwan/nfc; [] = all).

Bluetooth is on|off (a hard rfkill block); there is no half-measure
"non-discoverable" mode, because it can't be enforced reliably without a live
adapter -- `bluetooth: off` is the honest privacy setting.

Honest limits (surfaced by measure()):
  * The MAC drop-in takes effect on the next NetworkManager reload / reconnect;
    apply triggers a reload, but a restore removes the file and the old value
    returns on the following reload.
"""

from __future__ import annotations

from pathlib import Path

from umbra import fsutil
from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

_MAC_CONF = Path("/etc/NetworkManager/conf.d/00-umbra-mac.conf")

# Every radio Umbra knows how to reason about. `radios` in a profile lists the
# ones PERMITTED to stay powered; the rest get blocked.
_ALL_RADIOS = ("wifi", "bluetooth", "wwan", "nfc")


def _radios_to_block(permitted: list[str], bluetooth_off: bool) -> list[str]:
    """Which radios should be soft-blocked, given what the profile permits.

    Pure function (no I/O) so it is easy to unit-test.
    """
    blocked = [r for r in _ALL_RADIOS if r not in set(permitted)]
    if bluetooth_off and "bluetooth" not in blocked:
        blocked.append("bluetooth")     # explicit `bluetooth: off` overrides
    return blocked


def _mac_conf_text(mode: str) -> str:
    """The NetworkManager drop-in for a given randomization mode.

    per-network -> 'stable'  (same MAC per SSID, different across networks)
    others      -> 'random'  (fresh MAC every activation)
    scan randomization is always on -> no stable probe-request fingerprint.
    """
    cloned = "stable" if mode == "per-network" else "random"
    return (
        "# Managed by umbra (rf module). Remove to restore stock behaviour.\n"
        "[device]\n"
        "wifi.scan-rand-mac-address=yes\n\n"
        "[connection]\n"
        f"wifi.cloned-mac-address={cloned}\n"
        f"ethernet.cloned-mac-address={cloned}\n"
    )


class RfModule(Module):
    name = "rf"

    # --- controls ------------------------------------------------------------

    def _wants_mac(self) -> bool:
        return self.config.get("mac_randomization", "off") != "off"

    def _blocked_radios(self) -> list[str]:
        permitted = self.config.get("radios", list(_ALL_RADIOS))
        return _radios_to_block(permitted, self.config.get("bluetooth") == "off")

    def controls(self) -> list[Control]:
        ctrls: list[Control] = []
        if self._wants_mac():
            ctrls.append(Control("rf.mac", "MAC randomization + scan privacy", "file_replace"))
        for radio in self._blocked_radios():
            ctrls.append(Control(f"rf.radio_{radio}", f"Block {radio} radio", "rfkill_set"))
        return ctrls

    # --- measure -------------------------------------------------------------

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states

        if self._wants_mac():
            states["rf.mac"] = self._measure_mac()
        for radio in self._blocked_radios():
            states[f"rf.radio_{radio}"] = self._measure_radio(radio)
        return states

    def _measure_mac(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        want = _mac_conf_text(self.config.get("mac_randomization", "random"))
        if not _MAC_CONF.parent.exists():
            return ControlState("rf.mac", Compliance.UNKNOWN,
                                detail="NetworkManager not present on this host")
        current = _MAC_CONF.read_text() if _MAC_CONF.exists() else ""
        return ControlState(
            "rf.mac",
            Compliance.COMPLIANT if current == want else Compliance.DRIFT,
        )

    def _measure_radio(self, radio: str) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        res = self.runner.run(["rfkill", "list", radio], read_only=True)
        if not res.available:
            return ControlState(f"rf.radio_{radio}", Compliance.UNKNOWN)
        if not res.stdout.strip():
            # No such radio on this host -> already "silent".
            return ControlState(f"rf.radio_{radio}", Compliance.UNSUPPORTED,
                                detail="no such radio")
        blocked = "Soft blocked: yes" in res.stdout
        return ControlState(
            f"rf.radio_{radio}",
            Compliance.COMPLIANT if blocked else Compliance.DRIFT,
            observed={"soft_blocked": blocked},
        )

    # --- plan ----------------------------------------------------------------

    def plan(self) -> list[Action]:
        if not self.enabled:
            return []
        return [
            Action(control, self.config, reason=state.detail or "drift")
            for control, state in self.measure().items()
            if state.compliance is Compliance.DRIFT
        ]

    # --- apply ---------------------------------------------------------------

    def apply(self, action: Action, snap) -> None:
        if action.control == "rf.mac":
            self._apply_mac(snap)
        elif action.control.startswith("rf.radio_"):
            self._apply_radio(action.control.removeprefix("rf.radio_"), snap)

    def _apply_mac(self, snap) -> None:
        snap.record("rf.mac", "file_replace", fsutil.snapshot_path(_MAC_CONF))
        fsutil.atomic_write_text(
            _MAC_CONF, _mac_conf_text(self.config.get("mac_randomization", "random")),
            mode=0o644)
        # Ask NetworkManager to pick up the drop-in now.
        self.runner.run(["nmcli", "general", "reload"], read_only=False, check=True)

    def _apply_radio(self, radio: str, snap) -> None:
        state = self.runner.run(["rfkill", "list", radio], read_only=True)
        was_blocked = "Soft blocked: yes" in state.stdout
        snap.record(f"rf.radio_{radio}", "rfkill_set", {
            "identifier": radio,
            "was_blocked": was_blocked,
        })
        self.runner.run(["rfkill", "block", radio], read_only=False, check=True)

    # --- verify / restore ----------------------------------------------------

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    def restore(self, snap) -> None:
        return None
