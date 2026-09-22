"""The reconciler — drives modules through the lifecycle for a chosen profile.

Responsibilities the engine keeps so modules stay simple:
  * ordering        -- apply in APPLY_ORDER, restore in reverse (spec §3).
  * transactions    -- wrap a whole apply in one crash-safe transaction (spec §4).
  * crash recovery  -- restore any transaction a previous run left in-progress
                       BEFORE starting a new one.
  * fail modes      -- on error, `open` profiles auto-restore (favour
                       connectivity); `closed` profiles keep the walls up
                       (favour safety) and report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from umbra import snapshots
from umbra.modules import build_modules
from umbra.modules.base import APPLY_ORDER, Action, Compliance, ControlState
from umbra.profiles import Profile
from umbra.runner import Runner

log = logging.getLogger("umbra.engine")


@dataclass
class ApplyReport:
    profile: str
    transaction_id: str | None
    applied: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    restored: bool = False
    recovered: list[str] = field(default_factory=list)  # crashed txns cleaned up first

    @property
    def ok(self) -> bool:
        return not self.failed


class Engine:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.modules = build_modules(runner)

    # --- read-only views -----------------------------------------------------

    def status(self, profile: Profile) -> dict[str, dict[str, ControlState]]:
        """Per-module measured state vs. the profile. No mutation."""
        report: dict[str, dict[str, ControlState]] = {}
        for name in APPLY_ORDER:
            module = self.modules[name]
            module.configure(profile.module_config(name))
            report[name] = module.measure()
        return report

    def plan(self, profile: Profile) -> list[Action]:
        """The actions apply() would take, in apply order. No mutation."""
        actions: list[Action] = []
        for name in APPLY_ORDER:
            module = self.modules[name]
            module.configure(profile.module_config(name))
            actions.extend(module.plan())
        return actions

    # --- the mutating path ---------------------------------------------------

    def apply(self, profile: Profile) -> ApplyReport:
        report = ApplyReport(profile=profile.name, transaction_id=None)

        # 1) Crash recovery: never build on top of a half-applied prior run.
        report.recovered = self._recover_incomplete()

        # 2) One transaction for the whole reconcile.
        actions = self.plan(profile)
        if not actions:
            log.info("already compliant with profile %s; nothing to do", profile.name)
            return report

        with snapshots.Transaction(self.runner, profile.name) as tx:
            report.transaction_id = tx.id
            try:
                for name in APPLY_ORDER:
                    module = self.modules[name]
                    module.configure(profile.module_config(name))
                    for action in module.plan():
                        module.apply(action, tx.writer)
                        report.applied.append(action.control)
                        result = module.verify(action)
                        if result.ok:
                            report.verified.append(action.control)
                        else:
                            report.failed.append(action.control)
            except Exception as exc:  # noqa: BLE001
                log.error("apply failed: %s", exc)
                report.failed.append(f"<exception: {exc}>")
                if profile.fail_mode == "open":
                    # Favour connectivity: undo this transaction entirely.
                    snapshots.restore_transaction(self.runner, tx.id)
                    report.restored = True
                # `closed`: leave applied controls in place (safer) and report.
                raise SystemExitSafe(report) from exc

        # Record which posture is now active, so the NetworkManager dispatcher
        # can re-assert it when the link changes.
        if not self.runner.dry_run and report.ok:
            snapshots.set_active_profile(profile.name)
        return report

    def restore(self, tx_id: str | None = None) -> list[str]:
        """Restore a transaction (default: the current one). Returns failures."""
        return snapshots.restore_transaction(self.runner, tx_id)

    # --- internals -----------------------------------------------------------

    def _recover_incomplete(self) -> list[str]:
        recovered = []
        for tx_id in snapshots.find_incomplete():
            log.warning("recovering crashed transaction %s", tx_id)
            snapshots.restore_transaction(self.runner, tx_id)
            recovered.append(tx_id)
        return recovered


class SystemExitSafe(Exception):
    """Carries an ApplyReport out of a failed `closed`-mode apply so the CLI can
    print a useful summary instead of a bare traceback."""

    def __init__(self, report: ApplyReport) -> None:
        super().__init__("apply aborted; see report")
        self.report = report
