"""Crash-safe transactions and snapshots (spec §4).

The safety promise: Umbra can restore the machine to its pre-Umbra state even if
apply crashes halfway, the power drops, or a module throws.

How that promise is kept:

  * snapshot-before-mutate  -- a control's prior state is written AND fsync'd to
                               disk before the mutation runs (see modules).
  * one reconcile = one tx  -- all snapshots for a run live under one directory.
  * atomic commit           -- the run becomes "durable" only when manifest.json
                               is written and status flips to `committed`. A tx
                               left `in-progress` is a crash and is offered for
                               restore on next start.
  * full-state snapshots     -- we store the whole prior value, not a reverse
                               delta, so restore is just "write the old value back".
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from umbra import fsutil, paths
from umbra.restore import RESTORE_PRIMITIVES, apply_restore
from umbra.runner import Runner

# A transaction id is a timestamp + short hex. Anything else (e.g. a path with
# "/" or "..") is rejected before it can be used to build a filesystem path.
_TX_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z_[0-9a-f]{4,}$")


def _now_id() -> str:
    """A sortable, unique transaction id: ISO-ish timestamp + short random."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{stamp}_{secrets.token_hex(2)}"


def _valid_tx_id(tx_id: str) -> bool:
    return bool(_TX_ID_RE.match(tx_id))


class SnapshotWriter:
    """Records prior state for controls during one transaction."""

    def __init__(self, tx_dir: Path, dry_run: bool) -> None:
        self._tx_dir = tx_dir
        self._dry_run = dry_run
        self._recorded: list[str] = []

    def record(self, control: str, restore_method: str, prior: dict) -> None:
        """Persist a control's prior state. Called by a module BEFORE it mutates.

        control is dotted ("netdark.inbound_policy"); the part before the dot is
        the module, which becomes the sub-directory.
        """
        if restore_method not in RESTORE_PRIMITIVES:
            raise ValueError(f"refusing snapshot with unknown restore method {restore_method!r}")
        module = control.split(".", 1)[0]
        payload = {
            "control": control,
            "module": module,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "restore_method": restore_method,
            "prior": prior,
        }
        if self._dry_run:
            # In dry-run we never mutate, so there is nothing to snapshot.
            return
        mod_dir = self._tx_dir / module
        mod_dir.mkdir(parents=True, exist_ok=True)
        snap_path = mod_dir / f"{control.split('.', 1)[1]}.snap"
        # Atomic + fsync'd, so the snapshot is durable before the caller mutates.
        fsutil.atomic_write_text(snap_path, json.dumps(payload, indent=2))
        if control not in self._recorded:
            self._recorded.append(control)

    @property
    def recorded(self) -> list[str]:
        return list(self._recorded)


class SnapshotReader:
    """Reads back the snapshots of a committed (or crashed) transaction."""

    def __init__(self, tx_dir: Path) -> None:
        self._tx_dir = tx_dir

    def controls(self) -> list[str]:
        found: list[str] = []
        for snap in self._tx_dir.rglob("*.snap"):
            found.append(json.loads(snap.read_text())["control"])
        return found

    def read(self, control: str) -> dict | None:
        module, name = control.split(".", 1)
        snap = self._tx_dir / module / f"{name}.snap"
        if not snap.exists():
            return None
        return json.loads(snap.read_text())


class Transaction:
    """A single reconcile run. Use as a context manager.

        with Transaction(runner, profile="travel") as tx:
            module.apply(action, tx.writer)
        # leaving the block cleanly commits; an exception marks it failed.
    """

    def __init__(self, runner: Runner, profile: str) -> None:
        self.runner = runner
        self.profile = profile
        self.id = _now_id()
        self.dir = paths.transactions_dir() / self.id
        self.writer = SnapshotWriter(self.dir, dry_run=runner.dry_run)
        self._committed = False

    def __enter__(self) -> "Transaction":
        if not self.runner.dry_run:
            _ensure_state_dirs()
            self.dir.mkdir(parents=True, exist_ok=True)
            # Link to the posture that was live when we started. Undoing this
            # transaction returns the machine to THAT state -- not to stock -- so
            # `umbra normal` must walk the whole chain (see restore_chain).
            parent = current_transaction_id()
            if parent:
                fsutil.atomic_write_text(self.dir / "parent", parent + "\n")
            self._write_status("in-progress")
        return self

    def commit(self) -> None:
        """Make the transaction durable: write the manifest, flip status, point
        `current` at us."""
        if self.runner.dry_run:
            return
        manifest = {
            "id": self.id,
            "profile": self.profile,
            "committed_at": datetime.now(timezone.utc).isoformat(),
            "controls": self.writer.recorded,
        }
        manifest_path = self.dir / "manifest.json"
        fsutil.atomic_write_text(manifest_path, json.dumps(manifest, indent=2))
        self._write_status("committed")
        _set_current(self.id)
        self._committed = True

    def mark_failed(self) -> None:
        """Record an explicit failed transaction and point `current` at it, so the
        partial posture is undoable via `umbra normal` / `umbra restore`."""
        if self.runner.dry_run:
            return
        self._write_status("failed")
        _set_current(self.id)

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Convenience for `with Transaction(...)` users: clean exit commits, an
        # exception marks failed. The engine instead drives commit/mark_failed
        # explicitly (so it never relies on this), which leaves _committed set and
        # makes the branches below no-ops.
        if self.runner.dry_run:
            return False
        if exc_type is not None:
            if not self._committed:
                self._write_status("failed")
        elif not self._committed:
            self.commit()
        return False  # never suppress

    def _write_status(self, value: str) -> None:
        fsutil.atomic_write_text(self.dir / "status", value + "\n")


# --- module-level helpers ----------------------------------------------------

# Who may read what. The two small marker files are PUBLIC on purpose: the HUD,
# conky, the tray, and a plain `umbra status` run as the normal user and must see
# which posture is active. The transaction snapshots are PRIVATE: they hold copies
# of prior /etc files (hosts, resolv.conf, NetworkManager config, the firewall).
# Set explicitly rather than trusting the umask -- Kali's root umask is 027, and
# mkstemp creates files 0600, which is how the marker became root-only and the
# HUD fell back to "stock".
_STATE_DIR_MODE = 0o755
_MARKER_MODE = 0o644
_TX_DIR_MODE = 0o700


def _ensure_state_dirs() -> None:
    """Create the state dir (readable) and the transactions dir (root-only)."""
    sd = paths.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    tx = paths.transactions_dir()
    tx.mkdir(parents=True, exist_ok=True)
    for d, mode in ((sd, _STATE_DIR_MODE), (tx, _TX_DIR_MODE)):
        try:
            os.chmod(d, mode)
        except OSError:
            pass                        # not ours to change (dev dir, tests): fine


def _write_marker(name: str, text: str) -> None:
    _ensure_state_dirs()
    fsutil.atomic_write_text(paths.state_dir() / name, text, mode=_MARKER_MODE)


def _set_current(tx_id: str) -> None:
    """Point `state/current` at a transaction (a plain pointer file, portable)."""
    _write_marker("current", tx_id + "\n")


def _clear_current() -> None:
    (paths.state_dir() / "current").unlink(missing_ok=True)


def current_transaction_id() -> str | None:
    ptr = paths.state_dir() / "current"
    return ptr.read_text().strip() if ptr.exists() else None


# --- active-profile marker (for the NetworkManager dispatcher to re-apply) ----

def set_active_profile(name: str) -> None:
    _write_marker("active-profile", name + "\n")


def active_profile() -> str | None:
    """The applied posture, or None when nothing is applied (= `normal`).

    An unreadable marker (an install from before the permission fix) also reads
    as None; `sudo ./install.sh` repairs the modes on an existing box.
    """
    p = paths.state_dir() / "active-profile"
    try:
        return p.read_text().strip() or None
    except (FileNotFoundError, PermissionError):
        return None


def clear_active_profile() -> None:
    (paths.state_dir() / "active-profile").unlink(missing_ok=True)


def find_incomplete() -> list[str]:
    """Transaction ids whose status is still `in-progress` -- i.e. a prior run
    crashed. The engine restores these before doing anything else."""
    tx_root = paths.transactions_dir()
    if not tx_root.exists():
        return []
    incomplete = []
    for tx in sorted(tx_root.iterdir()):
        status_file = tx / "status"
        if status_file.exists() and status_file.read_text().strip() == "in-progress":
            incomplete.append(tx.name)
    return incomplete


def restore_transaction(runner: Runner, tx_id: str | None = None) -> list[str]:
    """Replay a transaction's snapshots in reverse apply order.

    Returns the list of controls that FAILED to restore (empty == full success).
    Best-effort: a failing primitive is logged and the rest still run (spec §4).
    """
    from umbra.modules.base import RESTORE_ORDER

    tx_id = tx_id or current_transaction_id()
    if tx_id is None:
        return []
    if not _valid_tx_id(tx_id):
        raise ValueError(f"refusing malformed transaction id: {tx_id!r}")
    tx_dir = paths.transactions_dir() / tx_id
    reader = SnapshotReader(tx_dir)

    # Group snapshotted controls by module, then walk modules in restore order.
    by_module: dict[str, list[str]] = {}
    for control in reader.controls():
        by_module.setdefault(control.split(".", 1)[0], []).append(control)

    failed: list[str] = []
    for module in RESTORE_ORDER:
        for control in by_module.get(module, []):
            snap = reader.read(control)
            if snap is None:
                continue
            try:
                apply_restore(runner, snap["restore_method"], snap["prior"])
            except Exception:  # noqa: BLE001 -- best-effort, keep going
                failed.append(control)

    if not runner.dry_run:
        if failed:
            # Partial restore: keep the pointer + active-profile so it can be
            # retried; mark it distinctly, not "restored".
            fsutil.atomic_write_text(tx_dir / "status", "restore-failed\n")
        else:
            fsutil.atomic_write_text(tx_dir / "status", "restored\n")
            if current_transaction_id() == tx_id:
                # Step the pointer back to the posture this one was layered on.
                # Only when nothing is left is the machine back at stock. (This
                # used to clear unconditionally, orphaning the earlier posture:
                # `normal` after a re-apply left most of the first one in place.)
                parent = _live_parent(tx_id)
                if parent:
                    _set_current(parent)
                else:
                    _clear_current()
                    clear_active_profile()
    return failed


def _parent_of(tx_id: str) -> str | None:
    p = paths.transactions_dir() / tx_id / "parent"
    try:
        parent = p.read_text().strip()
    except FileNotFoundError:
        return None
    return parent if parent and _valid_tx_id(parent) else None


def _live_parent(tx_id: str) -> str | None:
    """The nearest ancestor still applied (skip any already restored by hand)."""
    seen = {tx_id}
    parent = _parent_of(tx_id)
    while parent and parent not in seen:
        seen.add(parent)
        status_f = paths.transactions_dir() / parent / "status"
        status = status_f.read_text().strip() if status_f.exists() else ""
        if status != "restored":
            return parent
        parent = _parent_of(parent)
    return None


def restore_chain(runner: Runner) -> list[str]:
    """Undo EVERY applied transaction, newest first, back to stock.

    A posture can be several transactions deep: the NetworkManager dispatcher
    re-applies on each link-up, and each re-apply that fixed drift is its own
    transaction layered on the last. Undoing only the newest left the rest of the
    posture in place while the marker said "normal". Stops at the first failure
    (pointer left on it, so a retry resumes exactly there).
    """
    if runner.dry_run:
        # Nothing moves in a dry run; walk the links to preview every layer.
        failed: list[str] = []
        tx = current_transaction_id()
        seen: set[str] = set()
        while tx and tx not in seen:
            seen.add(tx)
            failed += restore_transaction(runner, tx)
            tx = _live_parent(tx)
        return failed

    seen = set()
    while (tx := current_transaction_id()) is not None and tx not in seen:
        seen.add(tx)
        failed = restore_transaction(runner, tx)
        if failed:
            return failed
    return []
