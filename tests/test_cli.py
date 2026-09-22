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


def test_pkexec_command_strips_flag_and_prepends_pkexec():
    cmd = cli._pkexec_command(["--pkexec", "apply", "travel", "--confirm"],
                              umbra_bin="/usr/bin/umbra")
    assert cmd == ["pkexec", "/usr/bin/umbra", "apply", "travel", "--confirm"]
    # --pkexec never leaks into the elevated invocation (would loop otherwise)
    assert "--pkexec" not in cmd


def test_pkexec_command_strips_profiles_dir():
    # a caller must not be able to point a privileged run at their own profiles
    cmd = cli._pkexec_command(["--pkexec", "--profiles-dir", "/tmp/evil", "apply", "home"],
                              umbra_bin="/usr/bin/umbra")
    assert cmd == ["pkexec", "/usr/bin/umbra", "apply", "home"]
    assert "--profiles-dir" not in cmd and "/tmp/evil" not in cmd
    # also the = form
    cmd2 = cli._pkexec_command(["--profiles-dir=/tmp/evil", "normal"], umbra_bin="/usr/bin/umbra")
    assert cmd2 == ["pkexec", "/usr/bin/umbra", "normal"]


def test_audit_html_writes_a_file(tmp_path):
    out = tmp_path / "posture.html"
    args = argparse.Namespace(profile="home", profiles_dir=None,
                              json=False, html=str(out))
    rc = cli.cmd_audit(args, Runner(dry_run=False))
    assert rc == 0
    assert out.exists()
    assert '<html lang="en">' in out.read_text(encoding="utf-8")
