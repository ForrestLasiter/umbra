"""Umbra module interface — the contract every layer module implements.

Phase 0: shapes only. Nothing here touches the system. See docs/PHASE-0-SPEC.md
sections 3 (module interface) and 4 (snapshot/restore contract).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class Compliance(str, Enum):
    COMPLIANT = "compliant"      # measured state already matches the target
    DRIFT = "drift"             # differs from target; action needed
    UNKNOWN = "unknown"         # could not measure (missing tool, no permission)
    UNSUPPORTED = "unsupported"  # not applicable on this host


@dataclass(frozen=True)
class Control:
    """One atomic, reversible change owned by a module."""
    id: str                      # e.g. "rf.wifi_mac"
    summary: str                 # human-readable, shown in `umbra status`
    restore_method: str          # one of the audited restore primitives (spec §4)


@dataclass
class ControlState:
    control: str
    compliance: Compliance
    observed: dict = field(default_factory=dict)   # what measure() actually read
    detail: str = ""


@dataclass
class Action:
    """A single planned change: bring `control` to `target`."""
    control: str
    target: dict
    reason: str = ""             # why the planner emitted it (for --plan output)


@dataclass
class VerifyResult:
    control: str
    ok: bool
    detail: str = ""


class SnapshotWriter(Protocol):
    """Records prior state BEFORE a mutation. Writes are fsync'd (spec §4)."""
    def record(self, control: str, restore_method: str, prior: dict) -> None: ...


class SnapshotReader(Protocol):
    def read(self, control: str) -> dict | None: ...
    def controls(self) -> list[str]: ...


@runtime_checkable
class Module(Protocol):
    name: str

    def controls(self) -> list[Control]:
        """Declare the controls this module owns."""
        ...

    def measure(self) -> dict[str, ControlState]:
        """Read current system state per control. No mutation; safe anytime."""
        ...

    def plan(self, target: dict) -> list[Action]:
        """Diff measure() against the target fragment. Empty == compliant."""
        ...

    def apply(self, action: Action, snap: SnapshotWriter) -> None:
        """Apply one action. MUST snapshot before mutating; idempotent."""
        ...

    def verify(self, action: Action) -> VerifyResult:
        """Re-measure and confirm the change took. Feeds the audit."""
        ...

    def restore(self, snap: SnapshotReader) -> None:
        """Reapply recorded prior state for every snapshotted control."""
        ...


# ---------------------------------------------------------------------------
# Engine-owned apply ordering (spec §3). Modules never coordinate themselves.
# Raise walls before opening the tunnel; touch radios last.
APPLY_ORDER: tuple[str, ...] = ("telemetry", "netdark", "tunnel", "rf")
RESTORE_ORDER: tuple[str, ...] = tuple(reversed(APPLY_ORDER))

# The only restore primitives a snapshot may name. Restore is data, not code:
# no snapshot ever executes an arbitrary shell string (spec §4).
RESTORE_PRIMITIVES: frozenset[str] = frozenset({
    "nftables_replace",
    "nmcli_set",
    "rfkill_set",
    "systemd_unit",
    "sysctl_set",
    "file_replace",
    "hosts_replace",
})
