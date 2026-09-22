"""A process-wide apply lock, so two posture transactions never run at once.

An `umbra apply` from the terminal, the tray, and the NetworkManager dispatcher
could otherwise all reconcile the same machine concurrently and corrupt the
snapshot/transaction state. `apply_lock()` serializes them with an exclusive
flock. On a non-Unix host (dev/test) it is a no-op.
"""

from __future__ import annotations

from contextlib import contextmanager

from umbra import paths


@contextmanager
def apply_lock():
    try:
        import fcntl
    except ImportError:
        # Windows / no fcntl: locking isn't available (and isn't needed in the
        # dev/test environment, which is single-process).
        yield
        return

    d = paths.state_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = open(d / "umbra.lock", "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()
