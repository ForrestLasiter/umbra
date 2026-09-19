"""netdark - make the machine silent and unresponsive on the local network.

Controls:
  * inbound_policy  -- replace the nftables ruleset with a default-DROP stealth
                       firewall (no ping reply, no RST: you don't answer at all).
  * ipv6_privacy    -- prefer temporary IPv6 addresses over a stable, trackable one.
  * discovery.<p>   -- silence each local-discovery protocol the profile requests:
        mdns (avahi), netbios (nmbd), ssdp_upnp (miniupnpd/minissdpd),
        wsd (wsdd)   -> stop+disable the announcing daemon if it is running;
        llmnr        -> a systemd-resolved drop-in (LLMNR=no) when resolved is
                        the active resolver.

Honest "already silent" semantics: a protocol whose announcer isn't installed (or
isn't running) reports COMPLIANT with a note, not a deferred placeholder - there
is simply nothing announcing it.

Caveat baked into measure(): the DROP firewall replaces the entire nftables
ruleset. Foreign rules (e.g. Docker) are suspended while dark and restored on
`umbra normal`; measure()/status warn when foreign tables are present.
"""

from __future__ import annotations

from pathlib import Path

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

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
_IPV6_TEMPADDR_KEY = "net.ipv6.conf.all.use_tempaddr"
_RESOLVED_DROPIN = Path("/etc/systemd/resolved.conf.d/umbra-llmnr.conf")
_RESOLVED_CONTENT = "# Managed by umbra (netdark).\n[Resolve]\nLLMNR=no\nMulticastDNS=no\n"

# Each discovery protocol -> the daemon(s) that announce it. llmnr is special:
# it is emitted by systemd-resolved itself, handled via a config drop-in.
_DISCOVERY_UNITS = {
    "mdns": ["avahi-daemon.service"],
    "netbios": ["nmbd.service"],
    "ssdp_upnp": ["miniupnpd.service", "minissdpd.service"],
    "wsd": ["wsdd.service"],
}


class NetdarkModule(Module):
    name = "netdark"

    def _requested_discovery(self) -> list[str]:
        disc = self.config.get("discovery", {}) or {}
        return [k for k, v in disc.items() if v]

    def controls(self) -> list[Control]:
        ctrls = [
            Control("netdark.inbound_policy", "Stealth firewall (default DROP)", "nftables_replace"),
            Control("netdark.ipv6_privacy", "IPv6 temporary addresses", "sysctl_set"),
        ]
        for proto in self._requested_discovery():
            method = "file_replace" if proto == "llmnr" else "systemd_unit"
            ctrls.append(Control(f"netdark.{proto}", f"Silence {proto}", method))
        return ctrls

    # --- measure -------------------------------------------------------------

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states
        states["netdark.inbound_policy"] = self._measure_firewall()
        states["netdark.ipv6_privacy"] = self._measure_sysctl()
        for proto in self._requested_discovery():
            states[f"netdark.{proto}"] = (
                self._measure_llmnr() if proto == "llmnr" else self._measure_units(proto)
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
        compliant = managed if want_drop else not managed
        return ControlState(
            "netdark.inbound_policy",
            Compliance.COMPLIANT if compliant else Compliance.DRIFT,
            observed={"managed": managed, "foreign_tables": foreign},
            detail="foreign nftables rules present; suspended while dark" if foreign else "",
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

    def _measure_units(self, proto: str) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        cid = f"netdark.{proto}"
        active, exists_any, unavailable = [], False, False
        for unit in _DISCOVERY_UNITS[proto]:
            state = self._unit_state(unit)
            if state is None:
                unavailable = True
                continue
            exists, is_active, _ = state
            exists_any = exists_any or exists
            if is_active:
                active.append(unit)
        if unavailable and not active:
            return ControlState(cid, Compliance.UNKNOWN, detail="systemctl unavailable")
        if active:
            return ControlState(cid, Compliance.DRIFT, observed={"active": active},
                                detail="announcing: " + ", ".join(active))
        detail = "no announcer installed (already silent)" if not exists_any else "installed but inactive"
        return ControlState(cid, Compliance.COMPLIANT, detail=detail)

    def _measure_llmnr(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        state = self._unit_state("systemd-resolved.service")
        if state is None:
            return ControlState("netdark.llmnr", Compliance.UNKNOWN, detail="systemctl unavailable")
        _, active, _ = state
        if not active:
            return ControlState("netdark.llmnr", Compliance.COMPLIANT,
                                detail="systemd-resolved inactive; LLMNR not emitted")
        silenced = _RESOLVED_DROPIN.exists() and "LLMNR=no" in _RESOLVED_DROPIN.read_text()
        return ControlState("netdark.llmnr",
                            Compliance.COMPLIANT if silenced else Compliance.DRIFT,
                            detail="resolved drop-in disables LLMNR" if silenced else "")

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
        control = action.control
        if control == "netdark.inbound_policy":
            self._apply_firewall(snap)
        elif control == "netdark.ipv6_privacy":
            self._apply_sysctl(snap)
        elif control == "netdark.llmnr":
            self._apply_llmnr(snap)
        elif control.startswith("netdark."):
            self._apply_units(control.split(".", 1)[1], snap)

    def _apply_firewall(self, snap) -> None:
        prior = self.runner.run(["nft", "list", "ruleset"], read_only=True)
        snap.record("netdark.inbound_policy", "nftables_replace",
                    {"ruleset": prior.stdout if prior.available else ""})
        self.runner.run(["nft", "flush", "ruleset"], read_only=False, check=True)
        self.runner.run(["nft", "-f", "-"], read_only=False, check=True, input_text=_NFT_RULESET)

    def _apply_sysctl(self, snap) -> None:
        prior = self.runner.run(["sysctl", "-n", _IPV6_TEMPADDR_KEY], read_only=True)
        snap.record("netdark.ipv6_privacy", "sysctl_set",
                    {"key": _IPV6_TEMPADDR_KEY, "value": prior.stdout.strip() or "0"})
        self.runner.run(["sysctl", "-w", f"{_IPV6_TEMPADDR_KEY}=2"], read_only=False, check=True)

    def _apply_units(self, proto: str, snap) -> None:
        for unit in _DISCOVERY_UNITS.get(proto, []):
            state = self._unit_state(unit)
            if state is None:
                continue
            exists, is_active, enabled = state
            if not is_active:
                continue
            stem = unit.rsplit(".", 1)[0]
            # Distinct control id per unit so each gets its own snapshot file.
            snap.record(f"netdark.{proto}_{stem}", "systemd_unit",
                        {"unit": unit, "was_enabled": enabled, "was_active": True})
            self.runner.run(["systemctl", "disable", "--now", unit], read_only=False)

    def _apply_llmnr(self, snap) -> None:
        existed = _RESOLVED_DROPIN.exists()
        snap.record("netdark.llmnr", "file_replace", {
            "path": str(_RESOLVED_DROPIN),
            "existed": existed,
            "content": _RESOLVED_DROPIN.read_text() if existed else "",
        })
        _RESOLVED_DROPIN.parent.mkdir(parents=True, exist_ok=True)
        _RESOLVED_DROPIN.write_text(_RESOLVED_CONTENT)
        # Pick up the drop-in now. (Restore removes the file; LLMNR fully reverts
        # on the next resolved restart / reboot.)
        self.runner.run(["systemctl", "restart", "systemd-resolved"], read_only=False)

    # --- verify / restore ----------------------------------------------------

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    def restore(self, snap) -> None:
        return None

    # --- helpers -------------------------------------------------------------

    def _unit_state(self, unit: str) -> tuple[bool, bool, bool] | None:
        """Return (exists, active, enabled) for a unit, or None if systemctl is
        unavailable on this host."""
        a = self.runner.run(["systemctl", "is-active", unit], read_only=True)
        if not a.available:
            return None
        text = (a.stdout + a.stderr).lower()
        exists = "could not be found" not in text and "not-found" not in text
        active = a.stdout.strip() == "active"
        e = self.runner.run(["systemctl", "is-enabled", unit], read_only=True)
        enabled = e.stdout.strip() == "enabled"
        return exists, active, enabled


def _has_foreign_tables(ruleset: str) -> bool:
    for line in ruleset.splitlines():
        line = line.strip()
        if line.startswith("table ") and "umbra" not in line:
            return True
    return False
