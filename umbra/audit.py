"""audit — read-only checks that PROVE the posture rather than trusting it.

Phase 3 turns the audit into a structured set of independent probes, each a
`Check` with a status, the evidence it saw, and a recommendation. These feed both
`umbra audit` (terminal) and the HTML posture dashboard (umbra/report.py).

Every probe is read-only and degrades gracefully off-Linux (missing tool -> NA),
so the audit runs anywhere; it just has less to say on a non-Linux box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from umbra.profiles import Profile
from umbra.runner import Runner


class Status(str, Enum):
    OK = "ok"        # posture is as hardened as this check wants
    WARN = "warn"    # exposed / not hardened
    FAIL = "fail"    # actively leaking or wide open
    INFO = "info"    # neutral fact, no judgement
    NA = "na"        # could not determine (tool/permission missing)


@dataclass
class Check:
    id: str
    title: str
    category: str            # "firewall" | "exposure" | "tunnel" | "dns" | "rf" | "telemetry"
    status: Status
    evidence: str = ""
    recommendation: str = ""


@dataclass
class AuditReport:
    profile: str
    generated_at: str
    checks: list[Check] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Status}
        for c in self.checks:
            out[c.status.value] += 1
        return out


def run_audit(runner: Runner, profile: Profile) -> AuditReport:
    report = AuditReport(
        profile=profile.name,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    for probe in (
        _probe_firewall,
        _probe_listening,
        _probe_discovery,
        _probe_tunnel,
        _probe_dns,
        _probe_ipv6_privacy,
        _probe_mac,
        _probe_telemetry_sinkhole,
        _probe_kernel_hardening,
        _probe_hostname_leak,
    ):
        report.checks.append(probe(runner))
    return report


# --- probes ------------------------------------------------------------------

def _probe_firewall(runner: Runner) -> Check:
    res = runner.run(["nft", "list", "ruleset"], read_only=True)
    if not res.available:
        return Check("firewall", "Inbound firewall", "firewall", Status.NA,
                     "nft unavailable on this host")
    text = res.stdout
    has_drop = "policy drop" in text
    managed = "umbra:managed" in text
    if managed and has_drop:
        return Check("firewall", "Inbound firewall", "firewall", Status.OK,
                     "umbra stealth ruleset active (default DROP)")
    if has_drop:
        return Check("firewall", "Inbound firewall", "firewall", Status.OK,
                     "a default-DROP input policy is present")
    return Check("firewall", "Inbound firewall", "firewall", Status.WARN,
                 "no default-DROP input policy found",
                 "apply a profile with netdark enabled to go stealth")


def _probe_listening(runner: Runner) -> Check:
    res = runner.run(["ss", "-tlnH"], read_only=True)
    if not res.available:
        return Check("exposure", "Listening TCP sockets", "exposure", Status.NA,
                     "ss unavailable on this host")
    public = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            local = parts[3]
            # anything not bound to loopback is externally reachable
            if not (local.startswith("127.") or local.startswith("[::1]") or local.startswith("::1")):
                public.append(local)
    if not public:
        return Check("exposure", "Listening TCP sockets", "exposure", Status.OK,
                     "nothing listening beyond loopback")
    return Check("exposure", "Listening TCP sockets", "exposure", Status.WARN,
                 "reachable: " + ", ".join(sorted(set(public))),
                 "close these services or let netdark's DROP policy shield them")


def _probe_discovery(runner: Runner) -> Check:
    running = []
    for unit in ("avahi-daemon", "nmbd"):
        r = runner.run(["systemctl", "is-active", unit], read_only=True)
        if not r.available:
            return Check("discovery", "Local-discovery daemons", "exposure", Status.NA,
                         "systemctl unavailable on this host")
        if r.stdout.strip() == "active":
            running.append(unit)
    if not running:
        return Check("discovery", "Local-discovery daemons", "exposure", Status.OK,
                     "mDNS/NetBIOS announcers are not running")
    return Check("discovery", "Local-discovery daemons", "exposure", Status.WARN,
                 "announcing: " + ", ".join(running),
                 "enable netdark to silence mDNS/NetBIOS")


def _probe_tunnel(runner: Runner) -> Check:
    res = runner.run(["ip", "route", "show", "default"], read_only=True)
    if not res.available:
        return Check("tunnel", "Default route", "tunnel", Status.NA,
                     "ip unavailable on this host")
    route = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""
    if any(dev in route for dev in ("wg", "tun", "tor")):
        return Check("tunnel", "Default route", "tunnel", Status.OK,
                     f"default route via tunnel: {route}")
    return Check("tunnel", "Default route", "tunnel", Status.INFO,
                 f"default route: {route or 'none'}",
                 "traffic is going out the physical interface, not a tunnel")


def _probe_dns(runner: Runner) -> Check:
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        return Check("dns", "DNS resolvers", "dns", Status.NA, "/etc/resolv.conf not present")
    servers = [ln.split()[1] for ln in resolv.read_text().splitlines()
               if ln.strip().startswith("nameserver") and len(ln.split()) > 1]
    return Check("dns", "DNS resolvers", "dns", Status.INFO,
                 "resolvers: " + (", ".join(servers) or "none"),
                 "under a tunnel these should be the tunnel's resolver, not your ISP's")


def _probe_ipv6_privacy(runner: Runner) -> Check:
    res = runner.run(["sysctl", "-n", "net.ipv6.conf.all.use_tempaddr"], read_only=True)
    if not res.available:
        return Check("ipv6", "IPv6 privacy addresses", "rf", Status.NA, "sysctl unavailable")
    val = res.stdout.strip()
    if val == "2":
        return Check("ipv6", "IPv6 privacy addresses", "rf", Status.OK,
                     "temporary IPv6 addresses preferred (use_tempaddr=2)")
    return Check("ipv6", "IPv6 privacy addresses", "rf", Status.WARN,
                 f"use_tempaddr={val or 'unset'}",
                 "enable netdark's ipv6_privacy to avoid a stable, trackable IPv6")


def _probe_mac(runner: Runner) -> Check:
    net = Path("/sys/class/net")
    if not net.exists():
        return Check("mac", "WiFi MAC randomization", "rf", Status.NA, "no /sys/class/net")
    wifi = [p.name for p in net.iterdir() if (p / "wireless").exists()]
    if not wifi:
        return Check("mac", "WiFi MAC randomization", "rf", Status.NA, "no WiFi interface present")
    details = []
    randomized = False
    for iface in wifi:
        cur = (net / iface / "address").read_text().strip()
        perm = runner.run(["ethtool", "-P", iface], read_only=True)
        perm_mac = perm.stdout.split()[-1] if perm.available and perm.ok else "?"
        differs = perm_mac not in ("?", cur)
        randomized = randomized or differs
        details.append(f"{iface}: cur={cur} perm={perm_mac}")
    status = Status.OK if randomized else Status.WARN
    return Check("mac", "WiFi MAC randomization", "rf", status, "; ".join(details),
                 "" if randomized else "enable rf.mac to randomize the MAC")


def _probe_kernel_hardening(runner: Runner) -> Check:
    res = runner.run(["sysctl", "-n", "kernel.kptr_restrict"], read_only=True)
    if not res.available:
        return Check("kernel", "Kernel hardening", "hardening", Status.NA, "sysctl unavailable")
    val = res.stdout.strip()
    if val == "2":
        return Check("kernel", "Kernel hardening", "hardening", Status.OK,
                     "kptr_restrict=2 (kernel pointers hidden)")
    return Check("kernel", "Kernel hardening", "hardening", Status.WARN,
                 f"kptr_restrict={val or 'unset'}", "enable the kernel module")


def _probe_hostname_leak(runner: Runner) -> Check:
    nm = Path("/etc/NetworkManager")
    conf = nm / "conf.d" / "01-umbra-hostname.conf"
    if not nm.exists():
        return Check("hostname", "DHCP hostname leak", "identity", Status.NA,
                     "NetworkManager not present")
    if conf.exists() and "dhcp-send-hostname=false" in conf.read_text():
        return Check("hostname", "DHCP hostname leak", "identity", Status.OK,
                     "hostname is not broadcast over DHCP")
    return Check("hostname", "DHCP hostname leak", "identity", Status.INFO,
                 "the hostname may be sent in DHCP requests (a cross-network identifier)",
                 "enable the identity module to suppress it")


def _probe_telemetry_sinkhole(runner: Runner) -> Check:
    hosts = Path("/etc/hosts")
    if not hosts.exists():
        return Check("telemetry", "Telemetry DNS sinkhole", "telemetry", Status.NA,
                     "/etc/hosts not present")
    if "umbra telemetry sinkhole" in hosts.read_text():
        n = sum(1 for ln in hosts.read_text().splitlines() if ln.startswith("0.0.0.0"))
        return Check("telemetry", "Telemetry DNS sinkhole", "telemetry", Status.OK,
                     f"sinkhole active ({n} domains)")
    return Check("telemetry", "Telemetry DNS sinkhole", "telemetry", Status.INFO,
                 "no umbra sinkhole in /etc/hosts",
                 "enable telemetry to sinkhole known trackers")
