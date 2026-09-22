"""Engine transaction-semantics tests (cross-platform).

On a non-Linux host every real module measures UNKNOWN -> plans nothing, which is
perfect for testing the "already compliant" path. For the failure paths we inject
a module that plans one action and always fails verification.
"""

from __future__ import annotations

import pytest

from umbra import snapshots
from umbra.engine import Engine, SystemExitSafe
from umbra.modules.base import Action, VerifyResult
from umbra.profiles import load_profile
from umbra.runner import Runner


class _FailModule:
    """Stands in for telemetry: plans one action, always fails verify."""
    name = "telemetry"

    def __init__(self, runner):
        self.runner = runner
        self.config = {}

    def configure(self, cfg):
        self.config = cfg or {}

    @property
    def enabled(self):
        return bool(self.config.get("enabled"))

    def controls(self):
        return []

    def measure(self):
        return {}

    def plan(self):
        return [Action("telemetry.x", {})] if self.enabled else []

    def apply(self, action, snap):
        snap.record("telemetry.x", "file_replace",
                    {"path": str(self.runner and "/nonexistent/umbra-test"), "existed": False})

    def verify(self, action):
        return VerifyResult("telemetry.x", False, "forced failure")

    def restore(self, snap):
        return None


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("UMBRA_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def test_already_compliant_still_records_active(state):
    report = Engine(Runner(dry_run=False)).apply(load_profile("home"))
    assert report.applied == []                       # nothing to do off-Linux
    assert snapshots.active_profile() == "home"       # ...but posture is recorded


def test_verify_failure_open_profile_rolls_back(state):
    runner = Runner(dry_run=False)
    engine = Engine(runner)
    engine.modules["telemetry"] = _FailModule(runner)
    with pytest.raises(SystemExitSafe) as ei:
        engine.apply(load_profile("home"))            # home = fail_mode open
    report = ei.value.report
    assert report.failed and report.restored is True
    assert snapshots.active_profile() is None          # never active on failure


def test_verify_failure_closed_profile_is_explicit_failed_tx(state):
    runner = Runner(dry_run=False)
    engine = Engine(runner)
    engine.modules["telemetry"] = _FailModule(runner)
    with pytest.raises(SystemExitSafe) as ei:
        engine.apply(load_profile("paranoid"))        # closed
    report = ei.value.report
    assert report.failed and report.restored is False
    assert snapshots.active_profile() is None
    # failed tx is pointed at by `current`, so it can be undone with `umbra normal`
    assert snapshots.current_transaction_id() == report.transaction_id
    tx_dir = snapshots.paths.transactions_dir() / report.transaction_id
    assert (tx_dir / "status").read_text().strip() == "failed"
