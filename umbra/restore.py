"""Restore primitives — the ONLY ways Umbra puts prior state back.

Spec §4: *restore is data, not code.* A snapshot never stores a shell command to
run; it stores a `restore_method` naming one of the primitives below plus a
`prior` payload of plain data. This keeps "undo" small, auditable, and impossible
to weaponise via a crafted snapshot.

Each primitive takes (runner, prior) and reapplies the recorded prior state. They
must be idempotent: running a restore twice is a no-op.
"""

from __future__ import annotations

import os
from pathlib import Path

from umbra.runner import Runner

# The closed set. A snapshot whose restore_method is not in here is refused.
RESTORE_PRIMITIVES: frozenset[str] = frozenset({
    "nftables_replace",
    "nmcli_set",
    "rfkill_set",
    "systemd_unit",
    "sysctl_set",
    "file_replace",
    "hosts_replace",
})


def _nftables_replace(runner: Runner, prior: dict) -> None:
    """Reload the complete prior nftables ruleset (full-state restore)."""
    ruleset = prior["ruleset"]
    # Flush everything we may have added, then load exactly what was there before.
    runner.run(["nft", "flush", "ruleset"], read_only=False, check=True)
    if ruleset.strip():
        runner.run(["nft", "-f", "-"], read_only=False, check=True, input_text=ruleset)


def _systemd_unit(runner: Runner, prior: dict) -> None:
    """Return a unit to its prior enabled/active state."""
    unit = prior["unit"]
    if prior.get("was_enabled"):
        runner.run(["systemctl", "enable", unit], read_only=False)
    else:
        runner.run(["systemctl", "disable", unit], read_only=False)
    if prior.get("was_active"):
        runner.run(["systemctl", "start", unit], read_only=False)
    else:
        runner.run(["systemctl", "stop", unit], read_only=False)


def _sysctl_set(runner: Runner, prior: dict) -> None:
    """Write a kernel parameter back to its prior runtime value."""
    key, value = prior["key"], prior["value"]
    runner.run(["sysctl", "-w", f"{key}={value}"], read_only=False, check=True)


def _file_replace(runner: Runner, prior: dict) -> None:
    """Restore a file's exact prior bytes, or delete it if it did not exist."""
    path = Path(prior["path"])
    if not prior.get("existed", False):
        path.unlink(missing_ok=True)
        return
    path.write_text(prior["content"])
    if "mode" in prior:
        os.chmod(path, prior["mode"])


# /etc/hosts is just a file; hosts_replace shares file_replace's mechanics but is
# named separately so audits can tell "we touched name resolution" from other
# file edits at a glance.
_hosts_replace = _file_replace


def _not_yet(name: str):
    def _stub(runner: Runner, prior: dict) -> None:
        raise NotImplementedError(f"restore primitive '{name}' arrives with the rf/tunnel modules")
    return _stub


_DISPATCH = {
    "nftables_replace": _nftables_replace,
    "systemd_unit": _systemd_unit,
    "sysctl_set": _sysctl_set,
    "file_replace": _file_replace,
    "hosts_replace": _hosts_replace,
    "nmcli_set": _not_yet("nmcli_set"),
    "rfkill_set": _not_yet("rfkill_set"),
}


def apply_restore(runner: Runner, method: str, prior: dict) -> None:
    """Dispatch one snapshot back onto the system."""
    if method not in RESTORE_PRIMITIVES:
        raise ValueError(f"unknown restore method: {method!r}")
    _DISPATCH[method](runner, prior)
