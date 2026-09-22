"""Transaction / snapshot tests — run on any OS using a temp state dir.

These prove the safety machinery (snapshot-before-mutate, crash detection,
restore dispatch) without needing nftables or root. The restore primitives that
touch the system are exercised via file_replace, which works everywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from umbra import snapshots
from umbra.runner import Runner


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("UMBRA_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def test_transaction_commits_and_sets_current(state_dir):
    runner = Runner(dry_run=False)
    with snapshots.Transaction(runner, profile="home") as tx:
        tx.writer.record("telemetry.hosts_sinkhole", "file_replace",
                         {"path": "x", "existed": False})
    assert snapshots.current_transaction_id() == tx.id
    assert (tx.dir / "status").read_text().strip() == "committed"
    assert (tx.dir / "manifest.json").exists()


def test_incomplete_transaction_is_detected(state_dir):
    runner = Runner(dry_run=False)
    tx = snapshots.Transaction(runner, profile="home")
    tx.__enter__()                      # marks in-progress, never commits
    assert tx.id in snapshots.find_incomplete()


def test_file_replace_round_trip(state_dir, tmp_path):
    target = tmp_path / "hosts"
    target.write_text("original\n")
    runner = Runner(dry_run=False)

    with snapshots.Transaction(runner, profile="home") as tx:
        tx.writer.record("telemetry.hosts_sinkhole", "file_replace",
                         {"path": str(target), "existed": True, "content": "original\n"})
        target.write_text("MUTATED\n")   # simulate the module's mutation

    assert target.read_text() == "MUTATED\n"
    failed = snapshots.restore_transaction(runner, tx.id)
    assert failed == []
    assert target.read_text() == "original\n"


def test_dry_run_records_nothing(state_dir):
    runner = Runner(dry_run=True)
    with snapshots.Transaction(runner, profile="home") as tx:
        tx.writer.record("telemetry.hosts_sinkhole", "file_replace", {"path": "x"})
    assert tx.writer.recorded == []


def test_active_profile_marker_round_trip(state_dir):
    assert snapshots.active_profile() is None
    snapshots.set_active_profile("travel")
    assert snapshots.active_profile() == "travel"
    snapshots.clear_active_profile()
    assert snapshots.active_profile() is None


def test_restore_success_clears_current_and_marks_restored(state_dir, tmp_path):
    target = tmp_path / "hosts"
    target.write_text("original\n")
    runner = Runner(dry_run=False)
    with snapshots.Transaction(runner, "home") as tx:
        tx.writer.record("telemetry.hosts_sinkhole", "file_replace",
                         {"path": str(target), "existed": True, "content": "original\n"})
        target.write_text("MUTATED\n")
    snapshots.set_active_profile("home")
    assert snapshots.current_transaction_id() == tx.id

    failed = snapshots.restore_transaction(runner, tx.id)
    assert failed == []
    assert target.read_text() == "original\n"
    assert snapshots.current_transaction_id() is None          # pointer cleared
    assert snapshots.active_profile() is None                  # active cleared
    assert (tx.dir / "status").read_text().strip() == "restored"


def test_restore_failure_keeps_pointer_and_marks_restore_failed(state_dir, tmp_path, monkeypatch):
    runner = Runner(dry_run=False)
    with snapshots.Transaction(runner, "home") as tx:
        tx.writer.record("telemetry.hosts_sinkhole", "file_replace",
                         {"path": str(tmp_path / "h"), "existed": False})

    def boom(*a, **k):
        raise RuntimeError("restore blew up")
    monkeypatch.setattr(snapshots, "apply_restore", boom)

    failed = snapshots.restore_transaction(runner, tx.id)
    assert failed == ["telemetry.hosts_sinkhole"]
    assert snapshots.current_transaction_id() == tx.id         # kept for retry
    assert (tx.dir / "status").read_text().strip() == "restore-failed"


def test_malformed_transaction_id_is_rejected(state_dir):
    import pytest
    with pytest.raises(ValueError):
        snapshots.restore_transaction(Runner(dry_run=False), "../../etc/passwd")


def test_apply_lock_is_a_working_context_manager(state_dir):
    # No-op on non-Unix, real flock on Unix; either way it must enter/exit cleanly.
    from umbra import lock
    with lock.apply_lock():
        pass
