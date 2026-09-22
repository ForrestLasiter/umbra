"""Module registry.

`build_modules()` returns the layer modules keyed by name. The engine walks them
in APPLY_ORDER (see base.py), not in the order here.
"""

from __future__ import annotations

from umbra.modules.base import Module
from umbra.modules.identity import IdentityModule
from umbra.modules.kernel import KernelModule
from umbra.modules.netdark import NetdarkModule
from umbra.modules.rf import RfModule
from umbra.modules.telemetry import TelemetryModule
from umbra.modules.tunnel import TunnelModule
from umbra.runner import Runner


def build_modules(runner: Runner) -> dict[str, Module]:
    modules = [
        KernelModule(runner),
        TelemetryModule(runner),
        NetdarkModule(runner),
        TunnelModule(runner),
        RfModule(runner),
        IdentityModule(runner),
    ]
    return {m.name: m for m in modules}
