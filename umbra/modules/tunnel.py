"""tunnel — route traffic through WireGuard or Tor with an egress killswitch.

Phase-1 stub. Declared so travel/paranoid profiles load and status lists it as
pending; it takes no action yet. Phase 2 wires this to the existing homevpn
wg-hub (via tunnel.profile_ref) and adds the nftables egress killswitch + DNS/
IPv6/WebRTC leak guards.
"""

from __future__ import annotations

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult


class TunnelModule(Module):
    name = "tunnel"

    def controls(self) -> list[Control]:
        return [
            Control("tunnel.route", "Route all traffic via tunnel", "nftables_replace"),
            Control("tunnel.killswitch", "Drop all non-tunnel egress", "nftables_replace"),
        ]

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        if not self.enabled:
            return {}
        return {
            c.id: ControlState(c.id, Compliance.UNSUPPORTED, detail="Phase 2")
            for c in self.controls()
        }

    def plan(self) -> list[Action]:
        return []

    def apply(self, action: Action, snap) -> None:
        raise NotImplementedError("tunnel module lands in Phase 2")

    def verify(self, action: Action) -> VerifyResult:
        return VerifyResult(action.control, False, "Phase 2")

    def restore(self, snap) -> None:
        return None
