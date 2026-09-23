"""The audit data model — core, platform-agnostic.

Status/Check/AuditReport describe the *shape* of a posture proof, independent of
how any platform gathers it. The Linux probes that fill these in live in
audit.py (the agent); the HTML renderer (report.py) and, in time, the mobile
adapters, consume this model without importing the Linux enforcement path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from umbra import capabilities


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
