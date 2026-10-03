"""audit — profile-aware proof of posture.

The audit measures the SELECTED profile's controls (via the engine, so it covers
firewall, Tor/WireGuard, IPv6, every discovery protocol, telemetry, kernel
hardening, DHCP hostname, MAC, Bluetooth, webcam...) and adds a few independent
leak probes. The score grades ONLY the profile's REQUIRED capabilities, so it
never reports 100/100 while a promised capability (e.g. Tor routing) isn't
actually verified.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from umbra import capabilities
# The audit MODEL is core (auditmodel.py); this file adds the Linux PROBES.
from umbra.auditmodel import AuditReport, Check, Status
from umbra.modules.base import Compliance
from umbra.profiles import Profile
from umbra.runner import Runner

__all__ = ["AuditReport", "Check", "Status", "run_audit"]


_COMPLIANCE_TO_STATUS = {
    Compliance.COMPLIANT: Status.OK,
    Compliance.DRIFT: Status.WARN,
    Compliance.UNKNOWN: Status.NA,
    Compliance.UNSUPPORTED: Status.INFO,
}


def run_audit(runner: Runner, profile: Profile) -> AuditReport:
    from umbra.engine import Engine

    report = AuditReport(
        profile=profile.name,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    # 1) Per-control checks, measured against the SELECTED profile.
    status = Engine(runner).status(profile)
    for module, states in status.items():
        for cid, cs in states.items():
            report.checks.append(Check(
                cid, cid, module, _COMPLIANCE_TO_STATUS[cs.compliance], cs.detail))

    # 2) Required-capability checks (these drive the score).
    report.required = capabilities.evaluate(profile, status)
    for r in report.required:
        st = Status.OK if r.verified else (Status.NA if not r.gradeable else Status.FAIL)
        report.checks.append(Check(f"require:{r.token}", f"Required: {r.token}",
                                   "required", st, r.detail))

    # 3) Independent leak probes (profile-independent, informative).
    report.checks.append(_probe_listening(runner))
    report.checks.append(_probe_default_route(runner))
    report.checks.append(_probe_dns_resolvers(runner))
    return report


# --- independent probes ------------------------------------------------------

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
            if not (local.startswith("127.") or local.startswith("[::1]") or local.startswith("::1")):
                public.append(local)
    if not public:
        return Check("exposure", "Listening TCP sockets", "exposure", Status.OK,
                     "nothing listening beyond loopback")
    return Check("exposure", "Listening TCP sockets", "exposure", Status.WARN,
                 "reachable: " + ", ".join(sorted(set(public))))


# Where the kernel would actually send a packet to the internet. `ip route get`
# follows policy-routing rules -- which is how wg-quick routes everything through
# the tunnel (its own table + an ip rule) while the MAIN table's default route
# still says eth0. Reading `ip route show default` (and matching "wg" in the
# interface name -- ours is called `vpn`) made the HUD say vpn=off while
# WireGuard was carrying every packet. Both commands work unprivileged.
_PROBE_DST = "1.1.1.1"


def _route_dev(stdout: str) -> str | None:
    toks = stdout.split()
    return toks[toks.index("dev") + 1] if "dev" in toks[:-1] else None


def _tunnel_kind(runner: Runner, dev: str) -> str | None:
    """'wireguard' / 'tun' when `dev` is a tunnel device (by link type, not name)."""
    res = runner.run(["ip", "-d", "-o", "link", "show", "dev", dev], read_only=True)
    out = res.stdout if res.ok else ""
    if " wireguard " in f" {out} ":
        return "wireguard"
    if " tun " in f" {out} " or "link/none" in out:
        return "tun"
    return None


def _probe_default_route(runner: Runner) -> Check:
    title = "Egress route"
    res = runner.run(["ip", "route", "get", _PROBE_DST], read_only=True)
    if not res.available:
        return Check("route", title, "tunnel", Status.NA, "ip unavailable")
    dev = _route_dev(res.stdout) if res.ok else None
    if dev is None:
        return Check("route", title, "tunnel", Status.INFO, "no route to the internet")
    kind = _tunnel_kind(runner, dev)
    if kind:
        return Check("route", title, "tunnel", Status.OK, f"egress via {dev} ({kind} tunnel)")
    # Tor's transparent proxy is NAT, not a route: paranoid egresses the physical
    # interface and the Tor capability check (not this probe) proves the redirect.
    return Check("route", title, "tunnel", Status.INFO, f"egress via {dev} (no tunnel)")


def _probe_dns_resolvers(runner: Runner) -> Check:
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        return Check("dns", "DNS resolvers", "dns", Status.NA, "/etc/resolv.conf not present")
    servers = [ln.split()[1] for ln in resolv.read_text().splitlines()
               if ln.strip().startswith("nameserver") and len(ln.split()) > 1]
    return Check("dns", "DNS resolvers", "dns", Status.INFO,
                 "resolvers: " + (", ".join(servers) or "none"))
