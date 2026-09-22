"""identity - stop the device from broadcasting who it is.

MAC randomization hides the hardware address, but a device still leaks its
*name*: NetworkManager sends the system hostname in every DHCP request, so
"forrests-laptop" (or "kali") follows you across every network you join. That is
a stable identifier that survives MAC randomization.

Phase-10 control:
  * dhcp_hostname -- a NetworkManager drop-in that stops sending the hostname in
                    DHCP (and the FQDN), closing that cross-network tracking leak.

(mDNS hostname advertisement is already handled by netdark silencing avahi.)
"""

from __future__ import annotations

from pathlib import Path

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

_NM_CONF = Path("/etc/NetworkManager/conf.d/01-umbra-hostname.conf")
_NM_CONTENT = (
    "# Managed by umbra (identity). Stops leaking the hostname via DHCP.\n"
    "[connection]\n"
    "dhcp-send-hostname=false\n"
    "dhcp-fqdn=\n"
)


class IdentityModule(Module):
    name = "identity"

    def controls(self) -> list[Control]:
        ctrls: list[Control] = []
        if self.config.get("dhcp_hostname_suppress", False):
            ctrls.append(Control("identity.dhcp_hostname",
                                 "Stop leaking the hostname over DHCP", "file_replace"))
        return ctrls

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states
        if self.config.get("dhcp_hostname_suppress", False):
            states["identity.dhcp_hostname"] = self._measure_conf()
        return states

    def _measure_conf(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        if not _NM_CONF.parent.exists():
            return ControlState("identity.dhcp_hostname", Compliance.UNKNOWN,
                                detail="NetworkManager not present on this host")
        current = _NM_CONF.read_text() if _NM_CONF.exists() else ""
        return ControlState(
            "identity.dhcp_hostname",
            Compliance.COMPLIANT if current == _NM_CONTENT else Compliance.DRIFT,
        )

    def plan(self) -> list[Action]:
        if not self.enabled:
            return []
        return [
            Action(control, self.config, reason=state.detail or "drift")
            for control, state in self.measure().items()
            if state.compliance is Compliance.DRIFT
        ]

    def apply(self, action: Action, snap) -> None:
        if action.control == "identity.dhcp_hostname":
            existed = _NM_CONF.exists()
            snap.record("identity.dhcp_hostname", "file_replace", {
                "path": str(_NM_CONF),
                "existed": existed,
                "content": _NM_CONF.read_text() if existed else "",
            })
            _NM_CONF.parent.mkdir(parents=True, exist_ok=True)
            _NM_CONF.write_text(_NM_CONTENT)
            self.runner.run(["nmcli", "general", "reload"], read_only=False)

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    def restore(self, snap) -> None:
        return None
