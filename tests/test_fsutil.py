"""fsutil tests: dry-run safety, atomic writes, metadata, symlinks, absent paths."""

from __future__ import annotations

import os

import pytest

from umbra import fsutil


def test_file_snapshot_and_restore_roundtrip(tmp_path):
    f = tmp_path / "a"
    f.write_text("orig")
    snap = fsutil.snapshot_path(f)
    assert snap["existed"] and snap["content"] == "orig" and not snap["is_symlink"]
    f.write_text("MUTATED")
    fsutil.restore_path(snap, dry_run=False)
    assert f.read_text() == "orig"


def test_restore_removes_a_path_that_did_not_exist(tmp_path):
    f = tmp_path / "a"
    snap = fsutil.snapshot_path(f)          # absent
    assert not snap["existed"]
    f.write_text("created after snapshot")
    fsutil.restore_path(snap, dry_run=False)
    assert not f.exists()


def test_restore_is_a_noop_in_dry_run(tmp_path):
    f = tmp_path / "a"
    f.write_text("orig")
    snap = fsutil.snapshot_path(f)
    f.write_text("MUTATED")
    fsutil.restore_path(snap, dry_run=True)  # MUST NOT touch the file
    assert f.read_text() == "MUTATED"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_atomic_write_and_restore_preserve_mode(tmp_path):
    f = tmp_path / "a"
    fsutil.atomic_write_text(f, "x", mode=0o600)
    assert (f.stat().st_mode & 0o777) == 0o600
    snap = fsutil.snapshot_path(f)
    assert snap["mode"] == 0o600
    os.chmod(f, 0o644)
    fsutil.restore_path(snap, dry_run=False)
    assert (f.stat().st_mode & 0o777) == 0o600     # mode restored


def test_symlink_kind_is_preserved(tmp_path):
    target = tmp_path / "target"
    target.write_text("t")
    link = tmp_path / "link"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this host")
    snap = fsutil.snapshot_path(link)
    assert snap["is_symlink"] and snap["link_target"]
    # replace the symlink with a plain file, then restore
    link.unlink()
    link.write_text("now a regular file")
    fsutil.restore_path(snap, dry_run=False)
    assert link.is_symlink()                        # kind restored, not flattened
