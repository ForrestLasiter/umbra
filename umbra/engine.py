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

from umbra import capabilities, lock, snapshots
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
    switched_from: str | None = None   # a different posture was unwound first

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
        # Serialize with any other apply/restore (terminal, tray, NM dispatcher).
        with lock.apply_lock():
            return self._apply_locked(profile)

    def _apply_locked(self, profile: Profile) -> ApplyReport:
        report = ApplyReport(profile=profile.name, transaction_id=None)

        # 1) Crash recovery: never build on top of a half-applied prior run.
        report.recovered = self._recover_incomplete()

        # 1b) Switching to a DIFFERENT posture: unwind the current one to stock
        #     first. A profile only measures the modules it enables, so applying
        #     home on top of paranoid left the Tor killswitch, the blocked
        #     Bluetooth radio and the unloaded webcam in place while the marker
        #     said "home". Re-applying the SAME profile (the NetworkManager
        #     dispatcher on link-up) stacks instead -- restore_chain unwinds those
        #     layers together later.
        live = snapshots.current_transaction_id()
        active = snapshots.active_profile()
        if live is not None and active != profile.name:
            report.switched_from = active or "a failed posture"
            log.info("switching from %s to %s: restoring to normal first",
                     report.switched_from, profile.name)
            if not self.runner.dry_run:
                failed = snapshots.restore_chain(self.runner)
                if failed:
                    # Never layer a new posture over a half-restored one.
                    report.failed.extend(f"restore:{c}" for c in failed)
                    raise SystemExitSafe(report)

        # 2) Already compliant? Still verify REQUIRED capabilities and record the
        #    active posture -- there is just nothing to change.
        actions = self.plan(profile)
        if not actions:
            log.info("already compliant with profile %s; nothing to do", profile.name)
            unmet = capabilities.unmet(capabilities.evaluate(profile, self.status(profile)))
            if unmet:
                report.failed.extend(f"require:{t}" for t in unmet)
                raise SystemExitSafe(report)   # no transaction was created
            if not self.runner.dry_run:
                self._record_active(profile)
            return report

        # 3) One transaction for the whole reconcile.
        tx = snapshots.Transaction(self.runner, profile.name)
        tx.__enter__()
        report.transaction_id = tx.id
        try:
            for name in APPLY_ORDER:
                module = self.modules[name]
                module.configure(profile.module_config(name))
                for action in module.plan():
                    module.apply(action, tx.writer)
                    report.applied.append(action.control)
                    if module.verify(action).ok:
                        report.verified.append(action.control)
                    else:
                        report.failed.append(action.control)
            # A required capability that didn't verify (drifted, unknown, or
            # unsupported) fails the transaction too -- the profile's promise
            # wasn't met.
            unmet = capabilities.unmet(capabilities.evaluate(profile, self.status(profile)))
            report.failed.extend(f"require:{t}" for t in unmet)
            # A failed verification MUST fail the transaction, same as an
            # exception -- a posture that didn't take is not "applied".
            if report.failed:
                raise _ApplyFailed("not verified: " + ", ".join(report.failed))
            tx.commit()
        except Exception as exc:  # noqa: BLE001
            tx.mark_failed()
            if not isinstance(exc, _ApplyFailed):
                log.error("apply failed: %s", exc)
                report.failed.append(f"<exception: {exc}>")
            if profile.fail_mode == "open":
                # Favour connectivity: undo this transaction entirely.
                snapshots.restore_transaction(self.runner, tx.id)
                report.restored = True
            # `closed`: leave applied controls in place; tx stays failed and
            # `current` points at it so the user can `umbra normal` to undo.
            # Never record active-profile for a failed/unverified posture.
            raise SystemExitSafe(report) from exc

        # Success: record which posture is now active.
        if not self.runner.dry_run:
            self._record_active(profile)
        return report

    def restore(self, tx_id: str | None = None) -> list[str]:
        """Undo a posture. No id: unwind EVERY applied layer back to stock (what
        `umbra normal` means). An id: restore just that one transaction."""
        with lock.apply_lock():
            if tx_id is None:
                return snapshots.restore_chain(self.runner)
            return snapshots.restore_transaction(self.runner, tx_id)

    # --- internals -----------------------------------------------------------

    @staticmethod
    def _record_active(profile: Profile) -> None:
        # `normal` is the absence of a posture: no marker, so the HUD reads
        # "normal" and the dispatcher has nothing to re-apply.
        if profile.name == "normal":
            snapshots.clear_active_profile()
        else:
            snapshots.set_active_profile(profile.name)

    def _recover_incomplete(self) -> list[str]:
        recovered = []
        for tx_id in snapshots.find_incomplete():
            log.warning("recovering crashed transaction %s", tx_id)
            snapshots.restore_transaction(self.runner, tx_id)
            recovered.append(tx_id)
        return recovered


class _ApplyFailed(Exception):
    """Internal: a verification failed, so the transaction must fail."""


class SystemExitSafe(Exception):
    """Carries an ApplyReport out of a failed apply so the CLI can print a useful
    summary instead of a bare traceback."""

    def __init__(self, report: ApplyReport) -> None:
        super().__init__("apply aborted; see report")
        self.report = report
