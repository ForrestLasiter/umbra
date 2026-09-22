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
    "nftables_table_delete",
    "nmcli_set",
    "rfkill_set",
    "systemd_unit",
    "sysctl_set",
    "file_replace",
    "hosts_replace",
    "path_restore",
    "module_load",
})


def _nftables_replace(runner: Runner, prior: dict) -> None:
    """Reload the complete prior nftables ruleset (full-state restore)."""
    ruleset = prior["ruleset"]
    # Flush everything we may have added, then load exactly what was there before.
    runner.run(["nft", "flush", "ruleset"], read_only=False, check=True)
    if ruleset.strip():
        runner.run(["nft", "-f", "-"], read_only=False, check=True, input_text=ruleset)


def _nftables_table_delete(runner: Runner, prior: dict) -> None:
    """Delete one table a module ADDED without flushing the whole ruleset.

    Used by the tunnel killswitch, which layers its own `umbra_egress` table on
    top of whatever netdark left, instead of replacing the entire ruleset. Undo
    is just "remove our table"; missing is fine (idempotent), so check=False.
    """
    family, table = prior["family"], prior["table"]
    runner.run(["nft", "delete", "table", family, table], read_only=False, check=False)


def _rfkill_set(runner: Runner, prior: dict) -> None:
    """Return a radio to its prior soft-block state."""
    identifier = prior["identifier"]        # e.g. "bluetooth", "wifi", "wwan"
    action = "block" if prior.get("was_blocked") else "unblock"
    runner.run(["rfkill", action, identifier], read_only=False, check=False)


def _module_load(runner: Runner, prior: dict) -> None:
    """Reload or unload a kernel module back to its prior loaded state."""
    module = prior["module"]
    if prior.get("was_loaded"):
        runner.run(["modprobe", module], read_only=False, check=False)
    else:
        runner.run(["modprobe", "-r", module], read_only=False, check=False)


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


def _path_restore(runner: Runner, prior: dict) -> None:
    """Restore a path that may have been a symlink, a file, or absent.

    Used for /etc/resolv.conf, which is often a symlink (NetworkManager /
    systemd-resolved). file_replace would turn a restored symlink into a plain
    file; this preserves the original kind exactly.
    """
    path = Path(prior["path"])
    if path.is_symlink() or path.exists():
        try:
            path.unlink()
        except (OSError, IsADirectoryError):
            pass
    if prior.get("was_symlink"):
        path.symlink_to(prior["link_target"])
    elif prior.get("existed"):
        path.write_text(prior.get("content") or "")


def _not_yet(name: str):
    def _stub(runner: Runner, prior: dict) -> None:
        raise NotImplementedError(f"restore primitive '{name}' arrives with the rf/tunnel modules")
    return _stub


_DISPATCH = {
    "nftables_replace": _nftables_replace,
    "nftables_table_delete": _nftables_table_delete,
    "systemd_unit": _systemd_unit,
    "sysctl_set": _sysctl_set,
    "file_replace": _file_replace,
    "hosts_replace": _hosts_replace,
    "path_restore": _path_restore,
    "rfkill_set": _rfkill_set,
    "module_load": _module_load,
    # nmcli MAC changes restore via file_replace of the NetworkManager drop-in,
    # so no dedicated nmcli_set primitive is needed yet.
    "nmcli_set": _not_yet("nmcli_set"),
}


def apply_restore(runner: Runner, method: str, prior: dict) -> None:
    """Dispatch one snapshot back onto the system."""
    if method not in RESTORE_PRIMITIVES:
        raise ValueError(f"unknown restore method: {method!r}")
    _DISPATCH[method](runner, prior)
