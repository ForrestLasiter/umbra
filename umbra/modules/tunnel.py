"""tunnel — force traffic through a tunnel and cut everything that isn't.

Phase-2 controls (WireGuard mode, wired to the homevpn wg-hub):
  * route       -- bring up the WireGuard interface via its systemd unit
                   (wg-quick@<profile_ref>.service).
  * killswitch  -- an nftables `umbra_egress` table with a default-DROP OUTPUT
                   policy that permits only loopback, established traffic, the
                   tunnel interface, the WireGuard endpoint, DHCP, and DNS.

This layers ON TOP of netdark's ruleset (it does NOT flush), so the two firewalls
coexist: netdark guards inbound, tunnel guards outbound. Undo removes just our
egress table (nftables_table_delete).

Order matters: the engine applies route before killswitch (bring the tunnel up,
then seal egress) so a dynamic-hostname endpoint can still be resolved and
handshaked.

Honest limits (surfaced by measure()):
  * Tor mode routing/killswitch is Phase 2.1; only WireGuard is wired now.
  * DNS (port 53) is permitted so a dynamic-hostname endpoint (e.g. DuckDNS) can
    re-resolve on reconnect. A static-IP endpoint can tighten this later.
  * WebRTC leak protection is a browser-level concern, not an OS firewall one; it
    is reported as advisory, not enforced here.
"""

from __future__ import annotations

import re
from pathlib import Path

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

_WG_DIR = Path("/etc/wireguard")
_EGRESS_TABLE = "umbra_egress"


def _endpoint_from_conf(conf_text: str) -> tuple[str, str] | None:
    """Parse `Endpoint = host:port` from a WireGuard config. Pure/testable."""
    match = re.search(r"^\s*Endpoint\s*=\s*([^:\s]+):(\d+)", conf_text, re.MULTILINE)
    if not match:
        return None
    return match.group(1), match.group(2)


def _build_killswitch(wg_iface: str, endpoint_ip: str, port: str) -> str:
    """The egress ruleset. Pure function of its inputs so it is easy to test."""
    return (
        f"table inet {_EGRESS_TABLE} {{\n"
        f"\tchain output {{\n"
        f"\t\ttype filter hook output priority filter; policy drop;\n"
        f"\t\toifname \"lo\" accept\n"
        f"\t\tct state established,related accept\n"
        f"\t\toifname \"{wg_iface}\" accept\n"
        f"\t\tip daddr {endpoint_ip} udp dport {port} accept comment \"wg endpoint\"\n"
        f"\t\tudp dport 53 accept comment \"resolve dynamic endpoint\"\n"
        f"\t\ttcp dport 53 accept\n"
        f"\t\tudp sport 68 udp dport 67 accept comment \"dhcp\"\n"
        f"\t\tmeta l4proto ipv6-icmp accept\n"
        f"\t}}\n"
        f"}}\n"
    )


class TunnelModule(Module):
    name = "tunnel"

    def _ref(self) -> str:
        return self.config.get("profile_ref", "wg-hub")

    def _route_unit(self) -> str | None:
        mode = self.config.get("mode", "off")
        if mode == "wireguard":
            return f"wg-quick@{self._ref()}.service"
        if mode == "tor":
            return "tor.service"
        return None

    def controls(self) -> list[Control]:
        ctrls = [Control("tunnel.route", "Route traffic via the tunnel", "systemd_unit")]
        if self.config.get("killswitch"):
            ctrls.append(Control("tunnel.killswitch", "Drop all non-tunnel egress",
                                 "nftables_table_delete"))
        return ctrls

    # --- measure -------------------------------------------------------------

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states

        states["tunnel.route"] = self._measure_route()
        if self.config.get("killswitch"):
            states["tunnel.killswitch"] = self._measure_killswitch()
        if "webrtc" in self.config.get("leak_guard", []):
            states["tunnel.webrtc"] = ControlState(
                "tunnel.webrtc", Compliance.UNSUPPORTED,
                detail="WebRTC is a browser setting, not an OS firewall control (advisory)",
            )
        return states

    def _measure_route(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        if self.config.get("mode") == "tor":
            return ControlState("tunnel.route", Compliance.UNSUPPORTED, detail="Tor mode is Phase 2.1")
        unit = self._route_unit()
        res = self.runner.run(["systemctl", "is-active", unit], read_only=True)
        if not res.available:
            return ControlState("tunnel.route", Compliance.UNKNOWN)
        active = res.stdout.strip() == "active"
        return ControlState(
            "tunnel.route",
            Compliance.COMPLIANT if active else Compliance.DRIFT,
            observed={"unit": unit, "active": active},
        )

    def _measure_killswitch(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        if self.config.get("mode") == "tor":
            return ControlState("tunnel.killswitch", Compliance.UNSUPPORTED, detail="Tor mode is Phase 2.1")
        res = self.runner.run(["nft", "list", "ruleset"], read_only=True)
        if not res.available:
            return ControlState("tunnel.killswitch", Compliance.UNKNOWN)
        present = _EGRESS_TABLE in res.stdout
        return ControlState(
            "tunnel.killswitch",
            Compliance.COMPLIANT if present else Compliance.DRIFT,
        )

    # --- plan ----------------------------------------------------------------

    def plan(self) -> list[Action]:
        if not self.enabled:
            return []
        # Deterministic order: route first, then killswitch (bring the tunnel up,
        # then seal egress). measure() dict preserves insertion order.
        return [
            Action(control, self.config, reason=state.detail or "drift")
            for control, state in self.measure().items()
            if state.compliance is Compliance.DRIFT
        ]

    # --- apply ---------------------------------------------------------------

    def apply(self, action: Action, snap) -> None:
        if action.control == "tunnel.route":
            self._apply_route(snap)
        elif action.control == "tunnel.killswitch":
            self._apply_killswitch(snap)

    def _apply_route(self, snap) -> None:
        unit = self._route_unit()
        enabled = self.runner.run(["systemctl", "is-enabled", unit], read_only=True)
        active = self.runner.run(["systemctl", "is-active", unit], read_only=True)
        snap.record("tunnel.route", "systemd_unit", {
            "unit": unit,
            "was_enabled": enabled.stdout.strip() == "enabled",
            "was_active": active.stdout.strip() == "active",
        })
        self.runner.run(["systemctl", "enable", "--now", unit], read_only=False, check=True)

    def _apply_killswitch(self, snap) -> None:
        endpoint = self._resolve_endpoint()
        if endpoint is None:
            raise RuntimeError(f"could not determine WireGuard endpoint for {self._ref()!r}")
        endpoint_ip, port = endpoint
        # Undo = remove just our table (we layer on top, we never flush).
        snap.record("tunnel.killswitch", "nftables_table_delete",
                    {"family": "inet", "table": _EGRESS_TABLE})
        ruleset = _build_killswitch(self._ref(), endpoint_ip, port)
        self.runner.run(["nft", "-f", "-"], read_only=False, check=True, input_text=ruleset)

    def _resolve_endpoint(self) -> tuple[str, str] | None:
        """Read the endpoint from the wg config, resolving a hostname to an IP so
        the killswitch can allow it by address."""
        conf = _WG_DIR / f"{self._ref()}.conf"
        if not conf.exists():
            return None
        parsed = _endpoint_from_conf(conf.read_text())
        if parsed is None:
            return None
        host, port = parsed
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
            return host, port
        # Resolve a hostname (e.g. DuckDNS) to its current IPv4.
        res = self.runner.run(["getent", "ahostsv4", host], read_only=True)
        if res.available and res.ok and res.stdout.strip():
            return res.stdout.split()[0], port
        return None

    # --- verify / restore ----------------------------------------------------

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    def restore(self, snap) -> None:
        return None
