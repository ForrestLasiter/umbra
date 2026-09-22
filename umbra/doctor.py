"""doctor - is this machine ready to apply a given profile?

`umbra doctor [profile]` checks that the tools and configs a profile needs are
present, so a profile fails up front with a clear "install X" instead of
mid-apply. Read-only; safe to run anytime, anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from umbra.profiles import Profile
from umbra.runner import Runner


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str = ""
    optional: bool = False


@dataclass
class DoctorReport:
    profile: str
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks if not c.optional)


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
            conf = Path(f"/etc/wireguard/{ref}.conf")
            report.checks.append(DoctorCheck(
                f"wireguard config ({ref})", conf.exists(),
                str(conf) if conf.exists() else
                f"missing {conf} - drop your WireGuard config there"))
        elif mode == "tor":
            tool("tor", "the Tor transparent proxy")

    tool("pkexec", "desktop authorization (umbra --pkexec)", optional=True)
    return report
