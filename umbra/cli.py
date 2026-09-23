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
import shutil
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
        raise SystemExit(
            "umbra: this command changes system state. Re-run as root:\n"
            "         sudo umbra ...            (terminal)\n"
            "         umbra --pkexec ...        (desktop auth dialog, no root shell)"
        )


def _umbra_bin() -> str:
    """The installed umbra launcher to hand pkexec. Prefer /usr/bin/umbra so it
    matches the polkit action's exec.path; fall back sensibly."""
    for candidate in ("/usr/bin/umbra", "/usr/local/bin/umbra"):
        if os.path.exists(candidate):
            return candidate
    return shutil.which("umbra") or os.path.abspath(sys.argv[0])


# Commands a pkexec-elevated run may perform. Excludes anything that could be
# turned into arbitrary privileged action (tray/dashboard/vpn import).
_PKEXEC_SAFE_COMMANDS = frozenset({
    "apply", "normal", "restore", "panic", "status", "plan", "audit", "doctor", "list",
})


def _strip_reexec_args(raw_args: list[str]) -> list[str]:
    """Drop flags that must never cross the pkexec boundary: --pkexec (would loop)
    and --profiles-dir (would let a caller point a privileged run at their own
    profiles)."""
    out: list[str] = []
    skip_next = False
    for a in raw_args:
        if skip_next:
            skip_next = False
            continue
        if a == "--pkexec":
            continue
        if a == "--profiles-dir":
            skip_next = True                 # also drop its value
            continue
        if a.startswith("--profiles-dir="):
            continue
        out.append(a)
    return out


def _pkexec_command(raw_args: list[str], umbra_bin: str | None = None) -> list[str]:
    """Build the `pkexec <umbra> <args>` command, with unsafe flags stripped.

    Pure/testable: the actual re-exec lives in main()."""
    binary = umbra_bin or _umbra_bin()
    return ["pkexec", binary, *_strip_reexec_args(raw_args)]


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

    from umbra.banner import render_compact
    try:
        print(render_compact())
    except UnicodeEncodeError:
        print(render_compact(unicode=False))
    print(f"\nposture vs profile '{profile.name}':\n")
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
    score = report.score()
    score_str = f"score {score}/100  " if score is not None else ""
    print(f"audit vs '{profile.name}'  {score_str}"
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


def cmd_tray(args, runner: Runner) -> int:
    from umbra.tray import run
    return run()


def cmd_doctor(args, runner: Runner) -> int:
    from umbra.doctor import run_doctor
    profile = load_profile(args.profile or "home", args.profiles_dir)
    report = run_doctor(runner, profile)
    print(f"readiness for '{profile.name}':\n")
    for c in report.checks:
        mark = "OK " if c.ok else ("?? " if c.optional else "XX ")
        opt = " (optional)" if c.optional else ""
        print(f"  {mark} {c.name}{opt}")
        if not c.ok or c.detail:
            print(f"        {c.detail}")
    print(f"\n  {'READY' if report.ready else 'NOT READY — install the missing pieces above'}")
    return 0 if report.ready else 1


def cmd_panic(args, runner: Runner) -> int:
    """Slam straight to the paranoid posture (go dark now)."""
    print("PANIC — going dark (applying paranoid)...")
    ns = argparse.Namespace(profile="paranoid", profiles_dir=args.profiles_dir, confirm=True)
    return cmd_apply(ns, runner)


def cmd_vpn(args, runner: Runner) -> int:
    """Import a WireGuard config so tunnel(wireguard) profiles can use it."""
    from umbra import fsutil
    from umbra.validate import ValidationError, safe_vpn_name
    try:
        name = safe_vpn_name(args.name)
    except ValidationError as exc:
        print(f"umbra: {exc}", file=sys.stderr)
        return 2
    src = Path(args.config)
    if not src.is_file():
        print(f"umbra: no such file: {src}", file=sys.stderr)
        return 2
    _require_privilege(dry_run=False)
    dest = Path("/etc/wireguard") / f"{name}.conf"
    fsutil.atomic_write_text(dest, src.read_text(), mode=0o600)
    print(f"imported {src} -> {dest} (referenced as profile_ref: {name})")
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
    p.add_argument("--pkexec", action="store_true",
                   help="re-run this command as root via pkexec (desktop auth dialog) instead of sudo")

    sub = p.add_subparsers(dest="command")
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

    sp = sub.add_parser("doctor", help="check this machine is ready for a profile")
    sp.add_argument("profile", nargs="?", help="profile to check (default: home)")

    sub.add_parser("panic", help="go dark now (apply the paranoid profile)")
    sub.add_parser("tray", help="run the system-tray posture toggle (desktop)")

    sp = sub.add_parser("vpn", help="import a WireGuard config for tunnel(wireguard)")
    sp.add_argument("config", help="path to a .conf file to import")
    sp.add_argument("--name", default="vpn", help="profile_ref name to save it as (default: vpn)")
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
    "doctor": cmd_doctor,
    "panic": cmd_panic,
    "vpn": cmd_vpn,
    "tray": cmd_tray,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.command is None:
        # Bare `umbra`: show the banner and a nudge toward the common commands.
        from umbra.banner import print_banner
        print_banner()
        print("   commands: status · plan · apply · normal · audit · dashboard · list")
        print("   start with:  umbra status home     (see: umbra --help)\n")
        return 0

    # --pkexec: re-run ourselves as root through polkit (a desktop auth dialog),
    # so a non-root user can change posture without a root shell. Only elevate
    # when we actually need to (not already root, on Linux).
    if getattr(args, "pkexec", False) and _is_linux() and not _is_root():
        raw = list(sys.argv[1:] if argv is None else argv)
        cmd = _pkexec_command(raw)
        try:
            os.execvp(cmd[0], cmd)          # replaces this process
        except FileNotFoundError:
            print("umbra: pkexec not found; install polkit (policykit-1) or use: sudo umbra ...",
                  file=sys.stderr)
            return 2

    # When WE are the pkexec-elevated process, constrain what's allowed: only the
    # safe built-in operations, and never an attacker-chosen profiles directory.
    if os.environ.get("PKEXEC_UID") is not None:
        if args.command not in _PKEXEC_SAFE_COMMANDS:
            print(f"umbra: '{args.command}' is not permitted via pkexec; run it directly",
                  file=sys.stderr)
            return 2
        if getattr(args, "profiles_dir", None):
            print("umbra: --profiles-dir is not permitted via pkexec (uses built-in profiles)",
                  file=sys.stderr)
            return 2
        # `audit --html PATH` writes a file as root; an attacker-chosen PATH would
        # be an arbitrary root-owned write. The dashboard is a convenience you can
        # produce unprivileged, so forbid it on the elevated path entirely.
        if getattr(args, "html", None):
            print("umbra: --html is not permitted via pkexec; run 'umbra audit --html' directly",
                  file=sys.stderr)
            return 2

    runner = Runner(dry_run=args.dry_run)
    try:
        return _HANDLERS[args.command](args, runner)
    except ProfileError as exc:
        print(f"umbra: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
