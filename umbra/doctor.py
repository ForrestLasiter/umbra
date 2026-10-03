"""doctor - is this machine ready to apply a given profile?

`umbra doctor [profile]` checks that the tools and configs a profile needs are
present, so a profile fails up front with a clear "install X" instead of
mid-apply. Read-only; safe to run anytime, anywhere.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from umbra.profiles import Profile
from umbra.runner import Runner

# Where wg-quick reads configs (root-only, 0700 -- a plain `umbra doctor` can't
# look inside). Module-level so tests can point it at a temp dir.
_WG_DIR = Path("/etc/wireguard")
_DNS_LINE = re.compile(r"^\s*DNS\s*=", re.MULTILINE | re.IGNORECASE)


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str = ""
    optional: bool = False
    needs_root: bool = False    # couldn't check as this user -- neither pass nor fail


@dataclass
class DoctorReport:
    profile: str
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks if not c.optional and not c.needs_root)

    @property
    def unverified(self) -> list[str]:
        """Checks that need `sudo umbra doctor` to see (e.g. root-only /etc/wireguard)."""
        return [c.name for c in self.checks if c.needs_root]


def run_doctor(runner: Runner, profile: Profile) -> DoctorReport:
    report = DoctorReport(profile=profile.name)
    modules = profile.data.get("modules", {})

    def tool(binary: str, why: str, optional: bool = False) -> None:
        present = runner.which(binary)
        report.checks.append(DoctorCheck(
            binary, present,
            why if present else f"missing - needed for {why}", optional))

    # core tools (used by most profiles)
    tool("nft", "the stealth firewall and killswitch")
    tool("systemctl", "service control")
    tool("sysctl", "kernel hardening and IPv6 privacy")

    if modules.get("kernel", {}).get("enabled"):
        tool("sysctl", "kernel hardening sysctls")
    if modules.get("rf", {}).get("enabled"):
        tool("rfkill", "radio control")
        tool("nmcli", "MAC randomization")
    if modules.get("identity", {}).get("enabled"):
        tool("nmcli", "DHCP hostname suppression")

    tun = modules.get("tunnel", {})
    if tun.get("enabled"):
        mode = tun.get("mode", "off")
        if mode == "wireguard":
            tool("wg-quick", "the WireGuard tunnel")
            ref = tun.get("profile_ref", "vpn")
            conf = _WG_DIR / f"{ref}.conf"
            name = f"wireguard config ({ref})"
            if _WG_DIR.exists() and not os.access(_WG_DIR, os.R_OK | os.X_OK):
                # Can't look as a normal user -- say so, never a false "missing".
                report.checks.append(DoctorCheck(
                    name, False, f"{_WG_DIR} is root-only; check it with:  "
                    f"sudo umbra doctor {profile.name}", needs_root=True))
            elif not conf.exists():
                report.checks.append(DoctorCheck(
                    name, False, f"missing {conf} - import yours:  sudo umbra vpn <file.conf>"))
            else:
                report.checks.append(DoctorCheck(name, True, str(conf)))
                # Every commercial VPN config carries a DNS line; wg-quick needs
                # resolvconf to apply it, and Kali doesn't ship one. Without this
                # check, `apply travel` failed with only "see journalctl".
                if _DNS_LINE.search(conf.read_text(errors="replace")):
                    tool("resolvconf", "the `DNS =` line in your WireGuard config "
                         "(install:  sudo apt install openresolv)")
        elif mode == "tor":
            tool("tor", "the Tor transparent proxy")

    tool("pkexec", "desktop authorization (umbra --pkexec)", optional=True)
    return report
