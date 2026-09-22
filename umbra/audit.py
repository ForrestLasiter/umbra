"""audit — profile-aware proof of posture.

The audit measures the SELECTED profile's controls (via the engine, so it covers
firewall, Tor/WireGuard, IPv6, every discovery protocol, telemetry, kernel
hardening, DHCP hostname, MAC, Bluetooth, webcam...) and adds a few independent
leak probes. The score grades ONLY the profile's REQUIRED capabilities, so it
never reports 100/100 while a promised capability (e.g. Tor routing) isn't
actually verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from umbra import capabilities
from umbra.modules.base import Compliance
from umbra.profiles import Profile
from umbra.runner import Runner


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"
    NA = "na"


@dataclass
class Check:
    id: str
    title: str
    category: str
    status: Status
    evidence: str = ""
    recommendation: str = ""


@dataclass
class AuditReport:
    profile: str
    generated_at: str
    checks: list[Check] = field(default_factory=list)
    required: list = field(default_factory=list)   # list[capabilities.CapResult]

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Status}
        for c in self.checks:
            out[c.status.value] += 1
        return out

    def score(self) -> int | None:
        """0-100 over the profile's REQUIRED capabilities (None if none gradeable)."""
        return capabilities.score(self.required)


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


def _probe_default_route(runner: Runner) -> Check:
    res = runner.run(["ip", "route", "show", "default"], read_only=True)
    if not res.available:
        return Check("route", "Default route", "tunnel", Status.NA, "ip unavailable")
    route = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""
    if any(dev in route for dev in ("wg", "tun", "tor")):
        return Check("route", "Default route", "tunnel", Status.OK, f"via tunnel: {route}")
    return Check("route", "Default route", "tunnel", Status.INFO,
                 f"default route: {route or 'none'}")


def _probe_dns_resolvers(runner: Runner) -> Check:
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        return Check("dns", "DNS resolvers", "dns", Status.NA, "/etc/resolv.conf not present")
    servers = [ln.split()[1] for ln in resolv.read_text().splitlines()
               if ln.strip().startswith("nameserver") and len(ln.split()) > 1]
    return Check("dns", "DNS resolvers", "dns", Status.INFO,
                 "resolvers: " + (", ".join(servers) or "none"))
