"""Restore primitives — the ONLY ways Umbra puts prior state back.

Spec §4: *restore is data, not code.* A snapshot never stores a shell command to
run; it stores a `restore_method` naming one of the primitives below plus a
`prior` payload of plain data. This keeps "undo" small, auditable, and impossible
to weaponise via a crafted snapshot.

Each primitive takes (runner, prior) and reapplies the recorded prior state. They
must be idempotent: running a restore twice is a no-op.
"""

from __future__ import annotations

from umbra import fsutil
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
    """LEGACY undo for snapshots taken when netdark flushed the whole ruleset.

    New snapshots use nftables_table_delete; this stays because boxes still hold
    old transactions. It used to `nft flush ruleset` and reload the entire saved
    dump in one go -- any table nft couldn't parse back (an iptables-nft table,
    a chain bound to a device that's gone) failed the WHOLE restore, leaving the
    firewall empty and the posture stuck as restore-failed.

    Now: remove Umbra's own tables, then reload each saved table that is MISSING,
    one at a time (a table its owner already re-created is left alone). A table
    nft can't rebuild is reported loudly with nft's own message instead of
    sinking the rest -- Umbra's part is fully undone either way.
    """
    import logging
    log = logging.getLogger("umbra.restore")

    live = runner.run(["nft", "list", "tables"], read_only=True)
    live_tables = _nft_tables(live.stdout)
    for family, name in live_tables:
        if name.startswith("umbra"):
            runner.run(["nft", "delete", "table", family, name], read_only=False, check=True)

    unrestorable = []
    for (family, name), block in _nft_table_blocks(prior.get("ruleset", "")):
        if name.startswith("umbra") or (family, name) in live_tables:
            continue
        res = runner.run(["nft", "-f", "-"], read_only=False, input_text=block)
        if res.executed and res.returncode != 0:
            unrestorable.append(f"table {family} {name}: {res.stderr.strip() or 'nft refused it'}")
    for msg in unrestorable:
        log.warning("could not rebuild pre-existing firewall %s -- restart the program "
                    "that owns it (e.g. docker, libvirtd, ufw) to recreate it", msg)


def _nft_tables(listing: str) -> list[tuple[str, str]]:
    """`nft list tables` -> [(family, name)]."""
    out = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "table":
            out.append((parts[1], parts[2]))
    return out


def _nft_table_blocks(ruleset: str) -> list[tuple[tuple[str, str], str]]:
    """Split an `nft list ruleset` dump into its top-level `table ... { }` blocks.

    Braces inside double-quoted strings (comments, names) don't count.
    """
    blocks, current, key, depth = [], [], None, 0
    for line in ruleset.splitlines():
        if key is None:
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "table" and line.rstrip().endswith("{"):
                key, current, depth = (parts[1], parts[2]), [], 0
            else:
                continue                     # comments / blank lines between tables
        current.append(line)
        in_str = False
        for ch in line:
            if ch == '"':
                in_str = not in_str
            elif not in_str and ch == "{":
                depth += 1
            elif not in_str and ch == "}":
                depth -= 1
        if depth == 0:
            blocks.append((key, "\n".join(current) + "\n"))
            key = None
    return blocks


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
    """Restore a file's exact prior bytes + mode/owner, or delete it if absent.

    Dry-run safe, atomic, metadata-preserving (see fsutil.restore_path)."""
    fsutil.restore_path(prior, runner.dry_run)


# /etc/hosts is just a file; hosts_replace shares file_replace's mechanics but is
# named separately so audits can tell "we touched name resolution" from other
# file edits at a glance.
_hosts_replace = _file_replace


def _path_restore(runner: Runner, prior: dict) -> None:
    """Restore a path that may have been a symlink, a file, or absent (dry-run
    safe, atomic, preserves the symlink-vs-file kind and metadata)."""
    fsutil.restore_path(prior, runner.dry_run)


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
