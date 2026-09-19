"""CLI wiring tests.

Regression guard for the bug the Kali VM caught: `umbra normal` must UNDO by
replaying the active transaction's snapshots (engine.restore), not by applying an
all-off profile (which reverts nothing). Uses a dry-run runner so it needs no
root and runs on any OS.
"""

from __future__ import annotations

import argparse

from umbra import cli
from umbra.runner import Runner


def test_normal_restores_the_current_transaction(monkeypatch):
    calls = {}

    monkeypatch.setattr(cli.snapshots, "current_transaction_id", lambda: "tx-123")

    def fake_restore(self, tx_id=None):
        calls["restored"] = tx_id
        return []                      # no failures

    monkeypatch.setattr(cli.Engine, "restore", fake_restore)
    # Guard: if `normal` ever regressed to applying a profile, this would fire.
    monkeypatch.setattr(cli.Engine, "apply",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("normal must not apply")))

    rc = cli.cmd_normal(argparse.Namespace(), Runner(dry_run=True))
    assert rc == 0
    assert calls["restored"] == "tx-123"


def test_normal_with_no_active_posture_is_a_noop(monkeypatch):
    monkeypatch.setattr(cli.snapshots, "current_transaction_id", lambda: None)
    rc = cli.cmd_normal(argparse.Namespace(), Runner(dry_run=True))
    assert rc == 0
