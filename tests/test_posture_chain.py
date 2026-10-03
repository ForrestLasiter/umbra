"""Posture layering: re-applies, switches, and `umbra normal` back to TRUE stock.

Real file_replace restores on temp files, so these prove the machine's actual
state after undo -- not just the pointer bookkeeping. Each guards a bug found by
reading the restore path:

  * `normal` restored only the NEWEST transaction. After the NetworkManager
    dispatcher re-applied on a Wi-Fi reconnect (a second, smaller transaction),
    `normal` undid that layer and left the first one in place -- while clearing
    the marker, so the HUD said "normal".
  * Switching profiles layered the new one on top. A profile only manages the
    modules it enables, so paranoid -> home left the Tor killswitch, the blocked
    radio and the unloaded webcam in place under a "home" label.
  * A failed re-apply in open fail-mode rolled back its own transaction and then
    CLEARED the pointer, orphaning the posture underneath.
"""

from __future__ import annotations

import pytest

from umbra import capabilities, snapshots
from umbra.engine import Engine, SystemExitSafe
from umbra.modules.base import Action, VerifyResult
from umbra.profiles import load_profile
from umbra.runner import Runner


@pytest.fixture()
def box(tmp_path, monkeypatch):
    """A 'machine': two config files at their stock values, empty state dir."""
    monkeypatch.setenv("UMBRA_STATE_DIR", str(tmp_path / "state"))
    f, g = tmp_path / "F", tmp_path / "G"
    f.write_text("stock-F")
    g.write_text("stock-G")
    return f, g


def _apply_layer(profile: str, changes: dict) -> str:
    """One committed transaction: snapshot each file, then mutate it."""
    with snapshots.Transaction(Runner(dry_run=False), profile) as tx:
        for i, (path, new) in enumerate(changes.items()):
            tx.writer.record(f"telemetry.f{i}", "file_replace",
                             {"path": str(path), "existed": True, "content": path.read_text()})
            path.write_text(new)
    snapshots.set_active_profile(profile)
    return tx.id


def test_normal_after_a_dispatcher_reapply_returns_to_true_stock(box):
    f, g = box
    _apply_layer("home", {f: "home-F", g: "home-G"})       # the posture
    _apply_layer("home", {f: "home-F-again"})               # re-apply fixed drift on F

    assert snapshots.restore_chain(Runner(dry_run=False)) == []
    assert f.read_text() == "stock-F"
    assert g.read_text() == "stock-G"                       # was left at home-G
    assert snapshots.current_transaction_id() is None
    assert snapshots.active_profile() is None


def test_engine_restore_without_an_id_unwinds_every_layer(box):
    f, g = box
    _apply_layer("home", {g: "home-G"})
    _apply_layer("home", {f: "home-F"})
    assert Engine(Runner(dry_run=False)).restore() == []
    assert (f.read_text(), g.read_text()) == ("stock-F", "stock-G")


def test_unwind_stops_at_a_failure_and_keeps_the_pointer_for_retry(box, monkeypatch):
    f, g = box
    first = _apply_layer("home", {g: "home-G"})
    second = _apply_layer("home", {f: "home-F"})

    real = snapshots.apply_restore
    def flaky(runner, method, prior):
        if prior["path"] == str(f):
            raise RuntimeError("nft -f - refused the ruleset")
        return real(runner, method, prior)
    monkeypatch.setattr(snapshots, "apply_restore", flaky)

    assert snapshots.restore_chain(Runner(dry_run=False)) == ["telemetry.f0"]
    assert snapshots.current_transaction_id() == second     # retry resumes here
    assert snapshots.active_profile() == "home"
    assert g.read_text() == "home-G"                         # first layer untouched
    assert first != second


def test_restoring_one_layer_steps_back_to_the_layer_beneath(box):
    f, _ = box
    first = _apply_layer("home", {f: "home-F"})
    second = _apply_layer("home", {f: "home-F-again"})
    assert snapshots.restore_transaction(Runner(dry_run=False), second) == []
    assert snapshots.current_transaction_id() == first       # not cleared
    assert snapshots.active_profile() == "home"
    assert f.read_text() == "home-F"


def _quiet_engine(monkeypatch) -> Engine:
    """An engine whose modules have nothing left to do and whose promises hold."""
    monkeypatch.setattr(Engine, "plan", lambda self, profile: [])
    monkeypatch.setattr(capabilities, "unmet", lambda results: [])
    return Engine(Runner(dry_run=False))


def test_switching_profiles_unwinds_the_old_posture_first(box, monkeypatch):
    f, g = box
    _apply_layer("paranoid", {f: "tor-killswitch", g: "bt-blocked"})
    report = _quiet_engine(monkeypatch).apply(load_profile("home"))

    assert report.switched_from == "paranoid"
    assert (f.read_text(), g.read_text()) == ("stock-F", "stock-G")   # no leftovers
    assert snapshots.active_profile() == "home"


def test_reapplying_the_same_profile_stacks_instead_of_unwinding(box, monkeypatch):
    f, _ = box
    first = _apply_layer("home", {f: "home-F"})
    report = _quiet_engine(monkeypatch).apply(load_profile("home"))
    assert report.switched_from is None
    assert f.read_text() == "home-F"
    assert snapshots.current_transaction_id() == first


def test_a_failed_unwind_blocks_the_switch(box, monkeypatch):
    f, _ = box
    _apply_layer("paranoid", {f: "tor-killswitch"})
    monkeypatch.setattr(snapshots, "apply_restore",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(SystemExitSafe) as ei:
        _quiet_engine(monkeypatch).apply(load_profile("home"))
    assert ei.value.report.failed == ["restore:telemetry.f0"]
    assert snapshots.active_profile() == "paranoid"          # never layered over it


def test_applying_normal_leaves_no_marker(box, monkeypatch):
    f, _ = box
    _apply_layer("home", {f: "home-F"})
    _quiet_engine(monkeypatch).apply(load_profile("normal"))
    assert f.read_text() == "stock-F"
    assert snapshots.active_profile() is None                # HUD reads "normal"


class _FailingTelemetry:
    """Plans one action, records a snapshot, never verifies."""
    name = "telemetry"

    def __init__(self, target):
        self.target, self.config = target, {}

    def configure(self, cfg):
        self.config = cfg or {}

    def measure(self):
        return {}

    def plan(self):
        return [Action("telemetry.x", {})] if self.config.get("enabled") else []

    def apply(self, action, snap):
        snap.record("telemetry.x", "file_replace",
                    {"path": str(self.target), "existed": True, "content": self.target.read_text()})
        self.target.write_text("half-applied")

    def verify(self, action):
        return VerifyResult("telemetry.x", False, "forced")

    def restore(self, snap):
        return None


def test_failed_open_reapply_keeps_the_posture_underneath(box, monkeypatch):
    f, g = box
    first = _apply_layer("home", {g: "home-G"})
    engine = Engine(Runner(dry_run=False))
    engine.modules["telemetry"] = _FailingTelemetry(f)
    with pytest.raises(SystemExitSafe) as ei:
        engine.apply(load_profile("home"))                   # home = fail_mode open
    assert ei.value.report.restored is True
    assert f.read_text() == "stock-F"                         # its own layer undone
    assert snapshots.current_transaction_id() == first       # ...not the one beneath
    assert snapshots.active_profile() == "home"
