"""netdark — make the machine silent and unresponsive on the local network.

Phase-1 controls:
  * inbound_policy  -- replace the nftables ruleset with a default-DROP stealth
                       firewall (no ping reply, no RST: you don't answer at all).
  * mdns / netbios  -- stop+disable the daemons that announce you (avahi, nmbd).
  * ipv6_privacy    -- use temporary IPv6 addresses instead of a stable, trackable one.

Requested-but-not-yet-implemented discovery keys (llmnr, ssdp_upnp, wsd) and
block_listening_services are surfaced by measure() as UNSUPPORTED with a note,
so `umbra status` tells the truth about what is and isn't enforced yet.

Honest caveat baked into measure(): the DROP firewall replaces the *entire*
nftables ruleset. If another tool (e.g. Docker) has rules loaded, they are
suspended while dark and restored on `umbra normal`. plan()/status warn when
foreign tables are present.
"""

from __future__ import annotations

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

# The stealth ruleset. `umbra:managed` is our marker so measure() can recognise
# its own work. Default policy DROP; allow only established/related, loopback,
# and IPv6 neighbour discovery (so IPv6 keeps functioning). Nothing else is
# answered -- pings included.
_NFT_RULESET = """\
table inet umbra {
	chain input {
		type filter hook input priority filter; policy drop;
		ct state established,related accept
		ct state invalid drop
		iif "lo" accept
		meta l4proto ipv6-icmp accept comment "umbra:managed neighbour discovery"
	}
}
"""
_MARKER = "umbra:managed"

# discovery config key -> systemd unit that announces on that protocol.
_DISCOVERY_UNITS = {
    "mdns": "avahi-daemon.service",
    "netbios": "nmbd.service",
}
# Recognised but not yet enforced in Phase 1.
_DISCOVERY_DEFERRED = {"llmnr", "ssdp_upnp", "wsd"}

_IPV6_TEMPADDR_KEY = "net.ipv6.conf.all.use_tempaddr"


class NetdarkModule(Module):
    name = "netdark"

    def controls(self) -> list[Control]:
        ctrls = [
            Control("netdark.inbound_policy", "Stealth firewall (default DROP)", "nftables_replace"),
            Control("netdark.ipv6_privacy", "IPv6 temporary addresses", "sysctl_set"),
        ]
        for key, unit in _DISCOVERY_UNITS.items():
            ctrls.append(Control(f"netdark.{key}", f"Silence {key} ({unit})", "systemd_unit"))
        return ctrls

    # --- measure -------------------------------------------------------------

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states

        states["netdark.inbound_policy"] = self._measure_firewall()
        states["netdark.ipv6_privacy"] = self._measure_sysctl()
        for key, unit in _DISCOVERY_UNITS.items():
            if self.config.get("discovery", {}).get(key):
                states[f"netdark.{key}"] = self._measure_unit(key, unit)
        # Surface the deferred ones honestly.
        for key in _DISCOVERY_DEFERRED:
            if self.config.get("discovery", {}).get(key):
                states[f"netdark.{key}"] = ControlState(
                    f"netdark.{key}", Compliance.UNSUPPORTED,
                    detail="requested; enforcement lands in Phase 1.5",
                )
        return states

    def _measure_firewall(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        want_drop = self.config.get("inbound_policy", "drop") == "drop"
        res = self.runner.run(["nft", "list", "ruleset"], read_only=True)
        if not res.available:
            return ControlState("netdark.inbound_policy", Compliance.UNKNOWN,
                                detail="nft not available on this host")
        managed = _MARKER in res.stdout
        foreign = _has_foreign_tables(res.stdout)
        detail = "foreign nftables rules present; suspended while dark" if foreign else ""
        compliant = managed if want_drop else not managed
        return ControlState(
            "netdark.inbound_policy",
            Compliance.COMPLIANT if compliant else Compliance.DRIFT,
            observed={"managed": managed, "foreign_tables": foreign},
            detail=detail,
        )

    def _measure_sysctl(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        if not self.config.get("ipv6_privacy", False):
            return ControlState("netdark.ipv6_privacy", Compliance.COMPLIANT)
        res = self.runner.run(["sysctl", "-n", _IPV6_TEMPADDR_KEY], read_only=True)
        if not res.available:
            return ControlState("netdark.ipv6_privacy", Compliance.UNKNOWN)
        value = res.stdout.strip()
        return ControlState(
            "netdark.ipv6_privacy",
            Compliance.COMPLIANT if value == "2" else Compliance.DRIFT,
            observed={"use_tempaddr": value},
        )

    def _measure_unit(self, key: str, unit: str) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        active = self.runner.run(["systemctl", "is-active", unit], read_only=True)
        if not active.available:
            return ControlState(f"netdark.{key}", Compliance.UNKNOWN)
        # A unit that doesn't exist on this host is already "silent" -> compliant.
        if "could not be found" in (active.stderr + active.stdout).lower():
            return ControlState(f"netdark.{key}", Compliance.UNSUPPORTED,
                                detail=f"{unit} not installed")
        is_running = active.stdout.strip() == "active"
        return ControlState(
            f"netdark.{key}",
            Compliance.DRIFT if is_running else Compliance.COMPLIANT,
            observed={"active": is_running},
        )

    # --- plan ----------------------------------------------------------------

    def plan(self) -> list[Action]:
        if not self.enabled:
            return []
        actions: list[Action] = []
        states = self.measure()
        for control, state in states.items():
            if state.compliance is Compliance.DRIFT:
                actions.append(Action(control, self.config, reason=state.detail or "drift"))
        return actions

    # --- apply ---------------------------------------------------------------

    def apply(self, action: Action, snap) -> None:
        if action.control == "netdark.inbound_policy":
            self._apply_firewall(snap)
        elif action.control == "netdark.ipv6_privacy":
            self._apply_sysctl(snap)
        elif action.control in {f"netdark.{k}" for k in _DISCOVERY_UNITS}:
            key = action.control.split(".", 1)[1]
            self._apply_unit(key, _DISCOVERY_UNITS[key], snap)

    def _apply_firewall(self, snap) -> None:
        # 1) snapshot the COMPLETE prior ruleset (full-state restore, spec §4).
        prior = self.runner.run(["nft", "list", "ruleset"], read_only=True)
        snap.record("netdark.inbound_policy", "nftables_replace",
                    {"ruleset": prior.stdout if prior.available else ""})
        # 2) replace it with our stealth ruleset.
        self.runner.run(["nft", "flush", "ruleset"], read_only=False, check=True)
        self.runner.run(["nft", "-f", "-"], read_only=False, check=True, input_text=_NFT_RULESET)

    def _apply_sysctl(self, snap) -> None:
        prior = self.runner.run(["sysctl", "-n", _IPV6_TEMPADDR_KEY], read_only=True)
        snap.record("netdark.ipv6_privacy", "sysctl_set",
                    {"key": _IPV6_TEMPADDR_KEY, "value": prior.stdout.strip() or "0"})
        self.runner.run(["sysctl", "-w", f"{_IPV6_TEMPADDR_KEY}=2"], read_only=False, check=True)

    def _apply_unit(self, key: str, unit: str, snap) -> None:
        enabled = self.runner.run(["systemctl", "is-enabled", unit], read_only=True)
        active = self.runner.run(["systemctl", "is-active", unit], read_only=True)
        snap.record(f"netdark.{key}", "systemd_unit", {
            "unit": unit,
            "was_enabled": enabled.stdout.strip() == "enabled",
            "was_active": active.stdout.strip() == "active",
        })
        self.runner.run(["systemctl", "disable", "--now", unit], read_only=False)

    # --- verify --------------------------------------------------------------

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    # --- restore -------------------------------------------------------------

    def restore(self, snap) -> None:
        # The engine drives restore via the snapshot primitives; nothing extra
        # is needed here for Phase-1 controls (firewall/sysctl/units all restore
        # from their recorded prior state alone).
        return None


def _has_foreign_tables(ruleset: str) -> bool:
    """True if the live ruleset contains a table other than ours."""
    for line in ruleset.splitlines():
        line = line.strip()
        if line.startswith("table ") and "umbra" not in line:
            return True
    return False
