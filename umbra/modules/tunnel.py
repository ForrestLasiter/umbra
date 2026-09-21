"""tunnel — force traffic through a tunnel and cut everything that isn't.

Umbra is a standalone, go-anywhere tool. The tunnel is either:

  * WireGuard — ANY endpoint YOU supply (a commercial VPN, a VPS you control;
    never a home server, since phoning home ties the device to your identity), or
  * Tor — a transparent proxy that connects to nothing of yours. This is the
    anonymity path for operating a device anywhere with no fixed endpoint.

Controls (WireGuard mode):
  * route       -- bring up wg-quick@<profile_ref>.service.
  * killswitch  -- an `umbra_egress` filter table (default-DROP OUTPUT) allowing
                   only loopback, established, the tunnel interface, the endpoint,
                   DHCP, and DNS.

Controls (Tor mode):
  * tor_config  -- add TransPort/DNSPort to torrc (a marked block).
  * route       -- enable + (re)start tor.service so it loads that config.
  * killswitch  -- two nftables tables that make Tor transparent AND leak-tight:
        `umbra_tor_nat` (ip)   redirects all DNS -> Tor DNSPort and all TCP ->
                               Tor TransPort (Tor's own uid and loopback excepted);
        `umbra_tor` (inet)     default-DROP OUTPUT that permits only Tor's uid,
                               loopback, established, and DHCP -- so ALL IPv6 and
                               any non-Tor egress is dropped. No leaks by
                               construction. (Local-network access is disabled in
                               Tor mode; that is the point.)

All tables layer ON TOP of netdark (no flush); undo removes only our tables.

Honest limits (surfaced by measure()):
  * WebRTC leak protection is a browser-level concern, not an OS firewall one; it
    is reported as advisory, not enforced here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

_WG_DIR = Path("/etc/wireguard")
_EGRESS_TABLE = "umbra_egress"

# --- Tor transparent proxy ---------------------------------------------------
# On Debian/Kali, tor.service is a do-nothing wrapper (RemainAfterExit oneshot);
# the actual daemon is the instanced unit tor@default.service. Managing plain
# tor.service reports "active" but runs no daemon and opens no TransPort.
_TOR_UNIT = "tor@default.service"
_TORRC = Path("/etc/tor/torrc")
_TOR_BEGIN = "# >>> umbra tor transparent proxy >>>"
_TOR_END = "# <<< umbra tor transparent proxy <<<"
_TOR_TRANS_PORT = "9040"
# NOT 5353: that's the mDNS port (avahi owns it), so Tor's DNSPort can't bind
# there. 9053 is conflict-free.
_TOR_DNS_PORT = "9053"
_TOR_NAT_TABLE = "umbra_tor_nat"
_TOR_FILTER_TABLE = "umbra_tor"
_RESOLV = Path("/etc/resolv.conf")
# Point the system resolver straight at loopback. DNS to 127.0.0.1:53 is then
# redirected (a pure loopback hop) to Tor's DNSPort. This also drops the box's
# IPv4/IPv6 LAN resolvers, so no DNS query ever leaves un-Tor'd.
_RESOLV_CONTENT = "# Managed by umbra (tor mode). Restored by `umbra normal`.\nnameserver 127.0.0.1\noptions edns0 trust-ad\n"


def _endpoint_from_conf(conf_text: str) -> tuple[str, str] | None:
    """Parse `Endpoint = host:port` from a WireGuard config. Pure/testable."""
    match = re.search(r"^\s*Endpoint\s*=\s*([^:\s]+):(\d+)", conf_text, re.MULTILINE)
    if not match:
        return None
    return match.group(1), match.group(2)


def _build_killswitch(wg_iface: str, endpoint_ip: str, port: str) -> str:
    """The WireGuard egress ruleset. Pure function so it is easy to test."""
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


def _torrc_block() -> str:
    return (
        f"{_TOR_BEGIN}\n"
        "VirtualAddrNetworkIPv4 10.192.0.0/10\n"
        "AutomapHostsOnResolve 1\n"
        f"TransPort 127.0.0.1:{_TOR_TRANS_PORT}\n"
        f"DNSPort 127.0.0.1:{_TOR_DNS_PORT}\n"
        f"{_TOR_END}\n"
    )


def _build_tor_nat(tor_uid: str) -> str:
    """NAT redirect: DNS -> Tor DNSPort, all TCP -> Tor TransPort. Pure/testable.

    Tor's own traffic (its uid) and loopback are returned unchanged so Tor can
    actually reach the network and the redirected packets land locally.
    """
    return (
        f"table ip {_TOR_NAT_TABLE} {{\n"
        f"\tchain output {{\n"
        f"\t\ttype nat hook output priority -100; policy accept;\n"
        f"\t\tmeta skuid {tor_uid} return\n"
        # DNS first (before the loopback return) so even a query aimed at
        # 127.0.0.1:53 is redirected to Tor's DNSPort.
        f"\t\tudp dport 53 redirect to :{_TOR_DNS_PORT}\n"
        f"\t\ttcp dport 53 redirect to :{_TOR_DNS_PORT}\n"
        f"\t\tip daddr 127.0.0.0/8 return\n"
        # All remaining TCP -> Tor's TransPort. This also covers the
        # AutomapHostsOnResolve virtual range (10.192.0.0/10) for .onion, so no
        # separate rule is needed (and `redirect to :port` needs an l4proto match).
        f"\t\tmeta l4proto tcp redirect to :{_TOR_TRANS_PORT}\n"
        f"\t}}\n"
        f"}}\n"
    )


def _build_tor_filter(tor_uid: str) -> str:
    """Leak-tight killswitch: only Tor's uid, loopback, established, and DHCP get
    out. Everything else -- all IPv6, all non-Tor egress -- is dropped."""
    return (
        f"table inet {_TOR_FILTER_TABLE} {{\n"
        f"\tchain output {{\n"
        f"\t\ttype filter hook output priority filter; policy drop;\n"
        f"\t\tmeta skuid {tor_uid} accept\n"
        f"\t\toif \"lo\" accept\n"
        # Traffic the NAT table redirected to Tor's Trans/DNSPort now has a
        # loopback destination but its oif is still the original interface, so
        # match on the (rewritten) destination, not oif -- otherwise the
        # redirected SYN is dropped and every connection times out.
        f"\t\tip daddr 127.0.0.0/8 accept comment \"redirected-to-Tor\"\n"
        f"\t\tct state established,related accept\n"
        f"\t\tudp sport 68 udp dport 67 accept comment \"dhcp\"\n"
        f"\t}}\n"
        f"}}\n"
    )


def _strip_tor_block(text: str) -> str:
    start, end = text.find(_TOR_BEGIN), text.find(_TOR_END)
    if start == -1 or end == -1:
        return text
    return text[:start] + text[end + len(_TOR_END):].lstrip("\n")


class TunnelModule(Module):
    name = "tunnel"

    def _mode(self) -> str:
        return self.config.get("mode", "off")

    def _ref(self) -> str:
        # A generic name; the user drops ANY WireGuard config at
        # /etc/wireguard/<ref>.conf. No home-network default.
        return self.config.get("profile_ref", "vpn")

    def _route_unit(self) -> str | None:
        if self._mode() == "wireguard":
            return f"wg-quick@{self._ref()}.service"
        if self._mode() == "tor":
            return _TOR_UNIT
        return None

    def controls(self) -> list[Control]:
        ctrls: list[Control] = []
        if self._mode() == "tor":
            ctrls.append(Control("tunnel.tor_config", "Configure Tor transparent proxy", "file_replace"))
        ctrls.append(Control("tunnel.route", "Route traffic via the tunnel", "systemd_unit"))
        if self.config.get("killswitch"):
            ctrls.append(Control("tunnel.killswitch", "Force all traffic through the tunnel",
                                 "nftables_table_delete"))
        return ctrls

    # --- measure -------------------------------------------------------------

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states

        if self._mode() == "tor":
            states["tunnel.tor_config"] = self._measure_tor_config()
        states["tunnel.route"] = self._measure_route()
        if self.config.get("killswitch"):
            states["tunnel.killswitch"] = self._measure_killswitch()
        if "webrtc" in self.config.get("leak_guard", []):
            states["tunnel.webrtc"] = ControlState(
                "tunnel.webrtc", Compliance.UNSUPPORTED,
                detail="WebRTC is a browser setting, not an OS firewall control (advisory)",
            )
        return states

    def _measure_tor_config(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        if not _TORRC.exists():
            return ControlState("tunnel.tor_config", Compliance.UNKNOWN,
                                detail="tor not installed (/etc/tor/torrc missing)")
        present = _TOR_BEGIN in _TORRC.read_text()
        return ControlState("tunnel.tor_config",
                            Compliance.COMPLIANT if present else Compliance.DRIFT)

    def _measure_route(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        unit = self._route_unit()
        if unit is None:
            return ControlState("tunnel.route", Compliance.UNKNOWN, detail="tunnel mode is off")
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

        res = self.runner.run(["nft", "list", "ruleset"], read_only=True)
        if not res.available:
            return ControlState("tunnel.killswitch", Compliance.UNKNOWN)
        marker = _TOR_FILTER_TABLE if self._mode() == "tor" else _EGRESS_TABLE
        present = marker in res.stdout
        return ControlState("tunnel.killswitch",
                            Compliance.COMPLIANT if present else Compliance.DRIFT)

    # --- plan ----------------------------------------------------------------

    def plan(self) -> list[Action]:
        if not self.enabled:
            return []
        # Deterministic order: (tor_config ->) route -> killswitch. measure()'s
        # dict preserves insertion order, which matches this.
        return [
            Action(control, self.config, reason=state.detail or "drift")
            for control, state in self.measure().items()
            if state.compliance is Compliance.DRIFT
        ]

    # --- apply ---------------------------------------------------------------

    def apply(self, action: Action, snap) -> None:
        if action.control == "tunnel.tor_config":
            self._apply_tor_config(snap)
        elif action.control == "tunnel.route":
            self._apply_route(snap)
        elif action.control == "tunnel.killswitch":
            if self._mode() == "tor":
                self._apply_tor_killswitch(snap)
            else:
                self._apply_wg_killswitch(snap)

    def _apply_tor_config(self, snap) -> None:
        existed = _TORRC.exists()
        content = _TORRC.read_text() if existed else ""
        snap.record("tunnel.tor_config", "file_replace",
                    {"path": str(_TORRC), "existed": existed, "content": content})
        cleaned = _strip_tor_block(content)
        if cleaned and not cleaned.endswith("\n"):
            cleaned += "\n"
        _TORRC.write_text(cleaned + _torrc_block())

        # Point the system resolver at loopback so DNS goes through Tor reliably
        # (a loopback->loopback redirect), and no LAN/IPv6 resolver leaks.
        was_symlink = _RESOLV.is_symlink()
        link_target = os.readlink(_RESOLV) if was_symlink else None
        r_existed = was_symlink or _RESOLV.exists()
        r_content = _RESOLV.read_text() if (r_existed and not was_symlink) else None
        snap.record("tunnel.tor_resolv", "path_restore", {
            "path": str(_RESOLV),
            "was_symlink": was_symlink,
            "link_target": link_target,
            "existed": r_existed,
            "content": r_content,
        })
        if _RESOLV.is_symlink() or _RESOLV.exists():
            _RESOLV.unlink()
        _RESOLV.write_text(_RESOLV_CONTENT)

        # Force the daemon to load the new TransPort/DNSPort. The route control
        # only *starts* Tor if it's stopped, so if Tor was already running it
        # would otherwise never pick up this config change.
        self.runner.run(["systemctl", "restart", _TOR_UNIT], read_only=False)

    def _apply_route(self, snap) -> None:
        unit = self._route_unit()
        enabled = self.runner.run(["systemctl", "is-enabled", unit], read_only=True)
        active = self.runner.run(["systemctl", "is-active", unit], read_only=True)
        snap.record("tunnel.route", "systemd_unit", {
            "unit": unit,
            "was_enabled": enabled.stdout.strip() == "enabled",
            "was_active": active.stdout.strip() == "active",
        })
        self.runner.run(["systemctl", "enable", unit], read_only=False)
        if self._mode() == "tor":
            # restart so tor loads the TransPort/DNSPort we just wrote to torrc
            self.runner.run(["systemctl", "restart", unit], read_only=False, check=True)
        else:
            self.runner.run(["systemctl", "start", unit], read_only=False, check=True)

    def _apply_wg_killswitch(self, snap) -> None:
        endpoint = self._resolve_endpoint()
        if endpoint is None:
            raise RuntimeError(f"could not determine WireGuard endpoint for {self._ref()!r}")
        endpoint_ip, port = endpoint
        snap.record("tunnel.killswitch", "nftables_table_delete",
                    {"family": "inet", "table": _EGRESS_TABLE})
        ruleset = _build_killswitch(self._ref(), endpoint_ip, port)
        self.runner.run(["nft", "-f", "-"], read_only=False, check=True, input_text=ruleset)

    def _apply_tor_killswitch(self, snap) -> None:
        tor_uid = self._tor_uid()
        if tor_uid is None:
            raise RuntimeError("tor user (debian-tor) not found; is tor installed?")
        # Two tables -> two snapshots under distinct ids so each undoes on its own.
        snap.record("tunnel.killswitch_nat", "nftables_table_delete",
                    {"family": "ip", "table": _TOR_NAT_TABLE})
        snap.record("tunnel.killswitch_filter", "nftables_table_delete",
                    {"family": "inet", "table": _TOR_FILTER_TABLE})
        ruleset = _build_tor_nat(tor_uid) + _build_tor_filter(tor_uid)
        self.runner.run(["nft", "-f", "-"], read_only=False, check=True, input_text=ruleset)

    def _resolve_endpoint(self) -> tuple[str, str] | None:
        conf = _WG_DIR / f"{self._ref()}.conf"
        if not conf.exists():
            return None
        parsed = _endpoint_from_conf(conf.read_text())
        if parsed is None:
            return None
        host, port = parsed
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
            return host, port
        res = self.runner.run(["getent", "ahostsv4", host], read_only=True)
        if res.available and res.ok and res.stdout.strip():
            return res.stdout.split()[0], port
        return None

    def _tor_uid(self) -> str | None:
        res = self.runner.run(["id", "-u", "debian-tor"], read_only=True)
        if res.available and res.ok and res.stdout.strip().isdigit():
            return res.stdout.strip()
        return None

    # --- verify / restore ----------------------------------------------------

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    def restore(self, snap) -> None:
        return None
