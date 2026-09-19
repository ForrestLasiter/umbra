"""audit — read-only checks that PROVE the posture, rather than trusting it.

Phase 1 keeps this deliberately small: it reuses the modules' own measure() for
per-control green/red, and adds a couple of independent leak probes (listening
TCP sockets, the default route) that don't rely on the modules being honest.
Real leak tests (DNS leak, MAC readback, broadcast sniff) grow here in later
phases alongside the rf/tunnel modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from umbra.engine import Engine
from umbra.modules.base import Compliance
from umbra.profiles import Profile
from umbra.runner import Runner


@dataclass
class AuditReport:
    per_control: dict[str, str] = field(default_factory=dict)   # control -> compliance
    listening_tcp: list[str] = field(default_factory=list)
    default_route: str = ""
    notes: list[str] = field(default_factory=list)


def run_audit(runner: Runner, profile: Profile) -> AuditReport:
    report = AuditReport()

    engine = Engine(runner)
    for module_states in engine.status(profile).values():
        for control, state in module_states.items():
            report.per_control[control] = state.compliance.value

    # Independent probe 1: what is still listening for inbound connections?
    ss = runner.run(["ss", "-tlnH"], read_only=True)
    if ss.available and ss.ok:
        for line in ss.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                report.listening_tcp.append(parts[3])   # local address:port
    else:
        report.notes.append("could not enumerate listening sockets (ss unavailable)")

    # Independent probe 2: default route (is traffic going where you think?).
    route = runner.run(["ip", "route", "show", "default"], read_only=True)
    if route.available and route.ok:
        report.default_route = route.stdout.strip().splitlines()[0] if route.stdout.strip() else ""
    else:
        report.notes.append("could not read default route (ip unavailable)")

    return report
