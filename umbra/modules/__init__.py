"""Module registry.

`build_modules()` returns the layer modules keyed by name. The engine walks them
in APPLY_ORDER (telemetry -> netdark -> tunnel -> rf), not in the order here.
"""

from __future__ import annotations

from umbra.modules.base import Module
from umbra.modules.netdark import NetdarkModule
from umbra.modules.rf import RfModule
from umbra.modules.telemetry import TelemetryModule
from umbra.modules.tunnel import TunnelModule
from umbra.runner import Runner


def build_modules(runner: Runner) -> dict[str, Module]:
    modules = [
        TelemetryModule(runner),
        NetdarkModule(runner),
        TunnelModule(runner),
        RfModule(runner),
    ]
    return {m.name: m for m in modules}
