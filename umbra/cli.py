"""The `umbra` command-line interface.

Commands:
  umbra list                 list available profiles
  umbra status [profile]     measured posture vs. a profile (default: home)
  umbra plan  <profile>      dry-run: show the actions apply would take
  umbra apply <profile>      reconcile the machine to a profile
  umbra normal               restore to stock (apply the `normal` profile)
  umbra restore [--tx ID]    restore a transaction (default: current)
  umbra audit [profile]      read-only proof of posture

Global flags: --dry-run, --json, --verbose, --confirm, --profiles-dir
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from umbra import __version__, snapshots
from umbra.audit import run_audit
from umbra.engine import Engine, SystemExitSafe
from umbra.modules.base import Compliance
from umbra.profiles import ProfileError, list_profiles, load_profile
from umbra.runner import Runner

# Terminal glyphs for compliance, kept ASCII-friendly.
_GLYPH = {
    Compliance.COMPLIANT.value: "OK ",
    Compliance.DRIFT.value: "-> ",
    Compliance.UNKNOWN.value: "? ",
    Compliance.UNSUPPORTED.value: ".. ",
}


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _is_root() -> bool:
    # geteuid only exists on Unix; on Windows we treat "root" as N/A.
    return getattr(os, "geteuid", lambda: 0)() == 0


def _require_privilege(dry_run: bool) -> None:
    """A real mutation needs Linux + root. A dry-run needs neither."""
    if dry_run:
        return
    if not _is_linux():
        raise SystemExit("umbra: mutations only run on Linux (use --dry-run to preview here)")
    if not _is_root():
        raise SystemExit("umbra: this command changes system state; run as root (or via sudo)")


# --- command handlers --------------------------------------------------------

def cmd_list(args, runner: Runner) -> int:
    for name in list_profiles(args.profiles_dir):
        print(name)
    return 0


def cmd_status(args, runner: Runner) -> int:
    profile = load_profile(args.profile or "home", args.profiles_dir)
    report = Engine(runner).status(profile)
    if args.json:
        out = {
            module: {c: s.compliance.value for c, s in states.items()}
            for module, states in report.items()
        }
        print(json.dumps(out, indent=2))
        return 0

    print(f"posture vs profile '{profile.name}':\n")
    any_control = False
    for module, states in report.items():
        if not states:
            continue
        print(f"  [{module}]")
        for control, state in states.items():
            any_control = True
            glyph = _GLYPH.get(state.compliance.value, "?")
            note = f"  ({state.detail})" if state.detail else ""
            print(f"    {glyph} {control}{note}")
        print()
    if not any_control:
        print("  (no controls active for this profile)")
    return 0


def cmd_plan(args, runner: Runner) -> int:
    profile = load_profile(args.profile, args.profiles_dir)
    actions = Engine(runner).plan(profile)
    if not actions:
        print(f"already compliant with '{profile.name}'; nothing to do.")
        return 0
    print(f"plan for '{profile.name}' ({len(actions)} action(s), apply order):\n")
    for action in actions:
        reason = f"  [{action.reason}]" if action.reason else ""
        print(f"  * {action.control}{reason}")
    return 0


def cmd_apply(args, runner: Runner) -> int:
    profile = load_profile(args.profile, args.profiles_dir)
    _require_privilege(runner.dry_run)

    if (profile.require_confirm or profile.fail_mode == "closed") and not args.confirm and not runner.dry_run:
        print(f"profile '{profile.name}' is fail-mode={profile.fail_mode} and needs --confirm.")
        print("preview with:  umbra plan", profile.name)
        return 2

    try:
        report = Engine(runner).apply(profile)
    except SystemExitSafe as safe:
        report = safe.report
        _print_apply(report, runner.dry_run)
        return 1
    _print_apply(report, runner.dry_run)
    return 0 if report.ok else 1


def cmd_normal(args, runner: Runner) -> int:
    """Return the machine to stock by REPLAYING the active transaction's
    snapshots -- not by applying an all-off profile.

    Prior state (the exact old firewall ruleset, the old /etc/hosts, the old
    sysctl value) only exists in the snapshots, so undo means restore, not
    reconcile. A disabled module measures/plans nothing, which is why applying
    the `normal` profile is a no-op and cannot revert anything.
    """
    _require_privilege(runner.dry_run)
    tx = snapshots.current_transaction_id()
    if tx is None:
        print("nothing to restore; no active umbra posture.")
        return 0
    failed = Engine(runner).restore(tx)
    if failed:
        print("restore completed with failures:")
        for control in failed:
            print("  !", control)
        return 1
    print(f"restored to stock (undid tx {tx}).")
    return 0


def cmd_restore(args, runner: Runner) -> int:
    _require_privilege(runner.dry_run)
    failed = Engine(runner).restore(args.tx)
    if failed:
        print("restore completed with failures:")
        for control in failed:
            print("  !", control)
        return 1
    print("restore complete.")
    return 0


_AUDIT_GLYPH = {
    "ok": "OK ", "warn": "!! ", "fail": "XX ", "info": ".. ", "na": "?? ",
}


def cmd_audit(args, runner: Runner) -> int:
    from dataclasses import asdict
    from umbra.report import render_html

    profile = load_profile(args.profile or "home", args.profiles_dir)
    report = run_audit(runner, profile)

    if args.html:
        Path(args.html).write_text(render_html(report), encoding="utf-8")
        print(f"wrote HTML posture dashboard -> {args.html}")

    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
        return 0

    counts = report.counts()
    print(f"audit vs '{profile.name}'  "
          f"[ok {counts['ok']} · warn {counts['warn']} · fail {counts['fail']} · "
          f"info {counts['info']} · na {counts['na']}]\n")
    for c in report.checks:
        print(f"  {_AUDIT_GLYPH.get(c.status.value, '?')} {c.title}")
        if c.evidence:
            print(f"        {c.evidence}")
        if c.recommendation and c.status.value in ("warn", "fail"):
            print(f"        -> {c.recommendation}")
    return 0


def cmd_dashboard(args, runner: Runner) -> int:
    from umbra.server import serve
    # Read-only; degrades to N/A without root, so no privilege gate. Blocks until
    # Ctrl-C.
    serve(args.profile or "home", args.port, runner)
    return 0


def _print_apply(report, dry_run: bool) -> None:
    tag = "DRY-RUN " if dry_run else ""
    print(f"{tag}apply '{report.profile}' (tx {report.transaction_id or '-'}):")
    if report.recovered:
        print(f"  recovered crashed transactions: {', '.join(report.recovered)}")
    print(f"  applied:  {len(report.applied)}")
    print(f"  verified: {len(report.verified)}")
    if report.failed:
        print(f"  FAILED:   {report.failed}")
    if report.restored:
        print("  rolled back (fail-mode=open).")
    if not dry_run and report.transaction_id:
        print(f"  undo with:  umbra restore --tx {report.transaction_id}")


# --- argument parsing --------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="umbra", description="privacy/anonymity/hardening posture engine")
    p.add_argument("--version", action="version", version=f"umbra {__version__}")
    p.add_argument("--dry-run", action="store_true", help="show mutations without performing them")
    p.add_argument("--json", action="store_true", help="machine-readable output where supported")
    p.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    p.add_argument("--confirm", action="store_true", help="acknowledge a fail-mode=closed apply")
    p.add_argument("--profiles-dir", default=None, help="override the profiles directory")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list available profiles")

    sp = sub.add_parser("status", help="measured posture vs a profile")
    sp.add_argument("profile", nargs="?", help="profile to compare against (default: home)")

    sp = sub.add_parser("plan", help="show actions apply would take")
    sp.add_argument("profile")

    sp = sub.add_parser("apply", help="reconcile the machine to a profile")
    sp.add_argument("profile")

    sub.add_parser("normal", help="restore to stock")

    sp = sub.add_parser("restore", help="restore a transaction")
    sp.add_argument("--tx", default=None, help="transaction id (default: current)")

    sp = sub.add_parser("audit", help="read-only proof of posture")
    sp.add_argument("profile", nargs="?", help="profile to audit against (default: home)")
    sp.add_argument("--html", metavar="PATH", default=None,
                    help="also write an accessible HTML posture dashboard to PATH")

    sp = sub.add_parser("dashboard", help="serve a live posture dashboard on localhost")
    sp.add_argument("profile", nargs="?", help="profile to audit against (default: home)")
    sp.add_argument("--port", type=int, default=8799, help="port to bind (default: 8799)")
    return p


_HANDLERS = {
    "list": cmd_list,
    "status": cmd_status,
    "plan": cmd_plan,
    "apply": cmd_apply,
    "normal": cmd_normal,
    "restore": cmd_restore,
    "audit": cmd_audit,
    "dashboard": cmd_dashboard,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    runner = Runner(dry_run=args.dry_run)
    try:
        return _HANDLERS[args.command](args, runner)
    except ProfileError as exc:
        print(f"umbra: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
