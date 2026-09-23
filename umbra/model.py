"""The posture model types — core, platform-agnostic.

These are the vocabulary the whole system speaks: how a control's reality relates
to its target (Compliance), what a control is, what measure()/plan()/verify()
produce. They carry no behaviour and import nothing platform-specific, so the
core (capabilities, audit model, the mobile adapters' shared contract) can use
them without dragging in the Linux agent.

The Module ABC that USES these lives in modules/base.py (it needs the Runner);
base.py re-exports these names so existing `from umbra.modules.base import ...`
imports keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
