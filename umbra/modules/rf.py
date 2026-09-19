"""rf — RF signature reduction (MAC randomization, probe suppression, radios).

Phase-1 stub. The module is declared so profiles that reference it load and
`umbra status` lists it as pending, but it takes no action yet. Real controls
(nmcli cloned-mac-address, rfkill) arrive in Phase 2 along with their restore
primitives (nmcli_set, rfkill_set).
"""

from __future__ import annotations

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult


class RfModule(Module):
    name = "rf"

    def controls(self) -> list[Control]:
        return [
            Control("rf.wifi_mac", "Per-network MAC randomization", "nmcli_set"),
            Control("rf.bluetooth", "Bluetooth off / non-discoverable", "rfkill_set"),
            Control("rf.radios", "Radio kill switch", "rfkill_set"),
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
        return []  # never acts in Phase 1

    def apply(self, action: Action, snap) -> None:
        raise NotImplementedError("rf module lands in Phase 2")

    def verify(self, action: Action) -> VerifyResult:
        return VerifyResult(action.control, False, "Phase 2")

    def restore(self, snap) -> None:
        return None
