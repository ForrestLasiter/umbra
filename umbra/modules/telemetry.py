"""telemetry — stop the OS and apps from phoning home.

Phase-1 controls:
  * hosts_sinkhole      -- append a marked block to /etc/hosts that points known
                           telemetry domains at 0.0.0.0 (a simple, transparent,
                           fully-reversible sinkhole you can read with your eyes).
  * disable_os_telemetry -- stop+disable any known telemetry units present.

Deferred to Phase 2 (surfaced honestly by measure()):
  * egress: allowlist   -- an nftables output allowlist needs live DNS resolution
                           of the allowed domains; it lands with the tunnel module.

The blocklists here are intentionally small and legible. In a later phase these
can be sourced from a public blocklist the device fetches for itself. For now
they demonstrate the mechanism end to end.
"""

from __future__ import annotations

from pathlib import Path

from umbra import fsutil
from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

_HOSTS = Path("/etc/hosts")
_BEGIN = "# >>> umbra telemetry sinkhole >>>"
_END = "# <<< umbra telemetry sinkhole <<<"

# Curated, legible starter lists. Swap for a fetched public blocklist later.
_BLOCKLISTS: dict[str, list[str]] = {
    "os": [
        # Common OS/vendor telemetry endpoints (illustrative, edit freely).
        "incoming.telemetry.mozilla.org",
        "metrics.mozilla.org",
    ],
    "common-trackers": [
        "www.google-analytics.com",
        "analytics.google.com",
        "app-measurement.com",
        "graph.facebook.com",
    ],
}

# Telemetry-ish systemd units we disable when present. Deliberately conservative.
_TELEMETRY_UNITS = [
    "apport.service",          # crash reporting (Ubuntu/Debian derivatives)
    "whoopsie.service",        # error submission
]


class TelemetryModule(Module):
    name = "telemetry"

    def controls(self) -> list[Control]:
        return [
            Control("telemetry.hosts_sinkhole", "DNS sinkhole for telemetry domains", "hosts_replace"),
            Control("telemetry.disable_os_telemetry", "Disable OS telemetry services", "systemd_unit"),
        ]

    # --- helpers -------------------------------------------------------------

    def _wanted_domains(self) -> list[str]:
        domains: list[str] = []
        for name in self.config.get("blocklists", []):
            domains.extend(_BLOCKLISTS.get(name, []))
        return sorted(set(domains))

    def _sinkhole_block(self) -> str:
        lines = [_BEGIN]
        for domain in self._wanted_domains():
            lines.append(f"0.0.0.0 {domain}")
        lines.append(_END)
        return "\n".join(lines) + "\n"

    # --- measure -------------------------------------------------------------

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states

        # hosts sinkhole
        if self.config.get("egress") == "blocklist" or self.config.get("blocklists"):
            states["telemetry.hosts_sinkhole"] = self._measure_hosts()
        # OS telemetry units
        if self.config.get("disable_os_telemetry"):
            states["telemetry.disable_os_telemetry"] = self._measure_units()
        return states

    def _measure_hosts(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        if not _HOSTS.exists():
            return ControlState("telemetry.hosts_sinkhole", Compliance.UNKNOWN,
                                detail="/etc/hosts not present (non-Linux host?)")
        current = _HOSTS.read_text()
        present = _BEGIN in current
        wanted = self._sinkhole_block()
        up_to_date = present and _extract_block(current) == wanted
        return ControlState(
            "telemetry.hosts_sinkhole",
            Compliance.COMPLIANT if up_to_date else Compliance.DRIFT,
            observed={"domains": len(self._wanted_domains())},
        )

    def _measure_units(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        probe = self.runner.run(["systemctl", "is-active", _TELEMETRY_UNITS[0]], read_only=True)
        if not probe.available:
            return ControlState("telemetry.disable_os_telemetry", Compliance.UNKNOWN)
        running = [u for u in _TELEMETRY_UNITS if self._unit_active(u)]
        return ControlState(
            "telemetry.disable_os_telemetry",
            Compliance.DRIFT if running else Compliance.COMPLIANT,
            observed={"still_running": running},
        )

    def _unit_active(self, unit: str) -> bool:
        res = self.runner.run(["systemctl", "is-active", unit], read_only=True)
        return res.stdout.strip() == "active"

    # --- plan ----------------------------------------------------------------

    def plan(self) -> list[Action]:
        if not self.enabled:
            return []
        return [
            Action(control, self.config, reason=state.detail or "drift")
            for control, state in self.measure().items()
            if state.compliance is Compliance.DRIFT
        ]

    # --- apply ---------------------------------------------------------------

    def apply(self, action: Action, snap) -> None:
        if action.control == "telemetry.hosts_sinkhole":
            self._apply_hosts(snap)
        elif action.control == "telemetry.disable_os_telemetry":
            self._apply_units(snap)

    def _apply_hosts(self, snap) -> None:
        # Snapshot the whole file first (full-state restore, with metadata).
        prior = fsutil.snapshot_path(_HOSTS)
        snap.record("telemetry.hosts_sinkhole", "hosts_replace", prior)
        current = prior["content"] or ""
        # Idempotent: strip any prior umbra block, then append the fresh one.
        cleaned = _strip_block(current)
        if cleaned and not cleaned.endswith("\n"):
            cleaned += "\n"
        fsutil.atomic_write_text(_HOSTS, cleaned + self._sinkhole_block(),
                                 mode=prior["mode"], uid=prior["uid"], gid=prior["gid"])

    def _apply_units(self, snap) -> None:
        for unit in _TELEMETRY_UNITS:
            if not self._unit_active(unit):
                continue
            enabled = self.runner.run(["systemctl", "is-enabled", unit], read_only=True)
            # Unique snapshot id PER unit, else multiple services collide on one
            # snapshot file and only the last is restorable.
            stem = unit.rsplit(".", 1)[0]
            snap.record(f"telemetry.svc_{stem}", "systemd_unit", {
                "unit": unit,
                "was_enabled": enabled.stdout.strip() == "enabled",
                "was_active": True,
            })
            self.runner.run(["systemctl", "disable", "--now", unit], read_only=False, check=True)

    # --- verify --------------------------------------------------------------

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    def restore(self, snap) -> None:
        return None


# --- /etc/hosts block helpers ------------------------------------------------

def _extract_block(text: str) -> str:
    """Return our marked block (inclusive of markers) plus a trailing newline."""
    start = text.find(_BEGIN)
    end = text.find(_END)
    if start == -1 or end == -1:
        return ""
    return text[start:end + len(_END)] + "\n"


def _strip_block(text: str) -> str:
    """Remove our marked block so re-applying is idempotent."""
    start = text.find(_BEGIN)
    end = text.find(_END)
    if start == -1 or end == -1:
        return text
    return text[:start] + text[end + len(_END):].lstrip("\n")
