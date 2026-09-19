"""Umbra module interface — the contract every layer module implements.

A *module* owns one layer (rf / netdark / tunnel / telemetry) and a set of
*controls*. The engine drives every module through the same five-step lifecycle:

    measure() -> plan(target) -> apply(action) -> verify(action)     (going dark)
    restore(snapshot)                                                (coming back)

See docs/PHASE-0-SPEC.md §3 (interface) and §4 (snapshot/restore).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from umbra.runner import Runner


class Compliance(str, Enum):
    """How a control's measured reality relates to the desired target."""
    COMPLIANT = "compliant"      # already matches the target
    DRIFT = "drift"             # differs; an action is needed
    UNKNOWN = "unknown"         # could not measure (missing tool / no permission)
    UNSUPPORTED = "unsupported"  # not applicable on this host


@dataclass(frozen=True)
class Control:
    """One atomic, reversible change owned by a module."""
    id: str                      # e.g. "netdark.inbound_policy"
    summary: str                 # shown in `umbra status`
    restore_method: str          # one of restore.RESTORE_PRIMITIVES


@dataclass
class ControlState:
    """What measure() found for one control right now."""
    control: str
    compliance: Compliance
    observed: dict = field(default_factory=dict)
    detail: str = ""


@dataclass
class Action:
    """A single planned change: bring `control` to `target`."""
    control: str
    target: dict
    reason: str = ""


@dataclass
class VerifyResult:
    control: str
    ok: bool
    detail: str = ""


class Module(ABC):
    """Base class for every layer module.

    Subclasses set `name` and implement the five lifecycle methods. They receive
    a shared `Runner` (so dry-run is uniform) and the module's slice of the
    active profile via `configure()`.
    """

    name: str = "base"

    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.config: dict = {}

    def configure(self, module_config: dict) -> None:
        """Hand the module its fragment of the profile (e.g. profile['modules']['netdark'])."""
        self.config = module_config or {}

    @property
    def enabled(self) -> bool:
        """A module with enabled=false makes no changes and asserts nothing."""
        return bool(self.config.get("enabled", False))

    # --- lifecycle -----------------------------------------------------------

    @abstractmethod
    def controls(self) -> list[Control]:
        """Declare the controls this module owns."""

    @abstractmethod
    def measure(self) -> dict[str, ControlState]:
        """Read current system state per control. No mutation; safe anytime."""

    @abstractmethod
    def plan(self) -> list[Action]:
        """Diff measure() against self.config; return only the needed actions.

        An empty list means the module is already compliant (or disabled).
        """

    @abstractmethod
    def apply(self, action: Action, snap: "SnapshotWriter") -> None:
        """Apply one action. MUST snapshot prior state BEFORE mutating. Idempotent."""

    @abstractmethod
    def verify(self, action: Action) -> VerifyResult:
        """Re-measure and confirm the change took. Feeds the audit."""

    @abstractmethod
    def restore(self, snap: "SnapshotReader") -> None:
        """Reapply recorded prior state for every control this module snapshotted."""


# Imported lazily for the type hints above without creating an import cycle at
# module load time. snapshots.py imports base.py, not the other way around.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from umbra.snapshots import SnapshotReader, SnapshotWriter


# --- Engine-owned ordering (spec §3) -----------------------------------------
# Raise the firewall/telemetry walls before opening the tunnel; touch radios
# (which can drop connectivity) last. Restore reverses this.
APPLY_ORDER: tuple[str, ...] = ("telemetry", "netdark", "tunnel", "rf")
RESTORE_ORDER: tuple[str, ...] = tuple(reversed(APPLY_ORDER))
