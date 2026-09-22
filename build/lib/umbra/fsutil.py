"""Filesystem helpers: atomic writes and metadata-preserving path snapshot/restore.

Every file Umbra touches is snapshotted with `snapshot_path` (which records the
kind — regular file / symlink / absent — plus content and mode/uid/gid) and
restored with `restore_path`, which:
  * is a NO-OP under dry-run,
  * writes atomically (temp file + fsync + os.replace, then fsync the dir),
  * puts back the original mode/owner/group and symlink-vs-file kind.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def snapshot_path(path: str | os.PathLike) -> dict:
    """Capture a path's full prior state for later restore."""
    p = Path(path)
    info: dict = {
        "path": str(p), "existed": False, "is_symlink": False,
        "link_target": None, "content": None,
        "mode": None, "uid": None, "gid": None,
    }
    if p.is_symlink():
        info.update(existed=True, is_symlink=True, link_target=os.readlink(p))
        return info
    if p.exists():
        st = p.lstat()
        info.update(
            existed=True,
            content=p.read_text(),
            mode=st.st_mode & 0o7777,
            uid=st.st_uid,
            gid=st.st_gid,
        )
    return info


def atomic_write_text(path: str | os.PathLike, text: str,
                      mode: int | None = None,
                      uid: int | None = None, gid: int | None = None) -> None:
    """Write text atomically: temp file in the same dir, fsync, os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".umbra-tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        if uid is not None and gid is not None:
            try:
                os.chown(tmp, uid, gid)
            except (OSError, AttributeError):
                pass
        os.replace(tmp, p)
        tmp = None                      # replaced; nothing to clean up
        _fsync_dir(p.parent)
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def restore_path(prior: dict, dry_run: bool) -> None:
    """Restore a path to its snapshotted state. No-op under dry-run."""
    if dry_run:
        return
    p = Path(prior["path"])
    # Clear whatever is there now.
    if p.is_symlink() or p.exists():
        try:
            p.unlink()
        except (OSError, IsADirectoryError):
            pass
    if prior.get("is_symlink"):
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(prior["link_target"], p)
    elif prior.get("existed"):
        atomic_write_text(
            p, prior.get("content") or "",
            mode=prior.get("mode"), uid=prior.get("uid"), gid=prior.get("gid"))
    # else: did not exist before -> leave it removed.


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
