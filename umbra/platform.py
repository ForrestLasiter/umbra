"""The platform boundary — what each OS can HONESTLY enforce.

Umbra's Linux build enforces every control directly (nftables, systemd, sysctl,
rfkill, Tor). A phone can't, and the whole project rests on not pretending it can
(a powered radio is detectable; an app that claims control it doesn't have is
worse than honest advice). So the *core* posture model is platform-agnostic, and
each platform declares, per capability, the strongest thing it can truthfully
promise.

This module is the contract. It is pure data + logic (no Linux imports), so the
Android/iOS adapters — and the exported language-neutral spec (see spec.py) —
consume exactly the same source of truth as the Linux reference.

    core (this file, capabilities.py, profiles, audit model)
      -> linux agent  : enforces everything (the reference implementation)
      -> android app  : VPNService — routes/DNS/tunnel enforced, kernel needs root
      -> android (system) : the same app built INTO a custom Android OS as a
                         privileged app — adds the system-only controls
      -> ios app       : Network Extension — DNS/tunnel via entitlement, most advisory
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

from umbra.capabilities import ALL_CAPABILITIES


class Platform(str, Enum):
    LINUX = "linux"      # the reference implementation; full control
    ANDROID = "android"  # VPNService + app permissions; no root assumed
    ANDROID_SYSTEM = "android_system"  # same app, shipped inside a custom Android OS as a privileged system app
    IOS = "ios"          # Network Extension; the most sandboxed


class Enforcement(str, Enum):
    """The strongest promise a platform can make about a capability.

    Ordered loosely from strongest to weakest, but treated as distinct states:
    a UI should show each differently, never collapse them into a fake "on".
    """
    ENFORCED = "enforced"                       # guaranteed with ordinary app perms
    REQUIRES_ENTITLEMENT = "requires_entitlement"  # enforced once the OS grants a special entitlement (VPN consent, Network Extension)
    REQUIRES_VPN_PROFILE = "requires_vpn_profile"  # enforced only while an Umbra tunnel/VPN profile is active
    REQUIRES_ROOTED_OS = "requires_rooted_os"      # only possible with root / a custom OS build
    ADVISORY = "advisory"                       # can measure and warn, cannot change it
    UNAVAILABLE = "unavailable"                 # not applicable / impossible on this platform


@dataclass(frozen=True)
class CapabilitySupport:
    capability: str
    level: Enforcement
    reason: str

    @property
    def actionable(self) -> bool:
        """True if the platform can actually move the needle (not just observe)."""
        return self.level in (
            Enforcement.ENFORCED,
            Enforcement.REQUIRES_ENTITLEMENT,
            Enforcement.REQUIRES_VPN_PROFILE,
            Enforcement.REQUIRES_ROOTED_OS,
        )


# The honest matrix. For every platform, every capability token in
# capabilities.CAPABILITY_CONTROLS gets exactly one (level, reason). Keep the
# reasons factual and hedged -- this is the project's honesty promise in data.
_E = Enforcement
CAPABILITY_SUPPORT: dict[Platform, dict[str, tuple[Enforcement, str]]] = {
    Platform.LINUX: {
        "firewall":     (_E.ENFORCED, "nftables default-DROP inbound"),
        "ipv6_privacy": (_E.ENFORCED, "sysctl use_tempaddr"),
        "discovery":    (_E.ENFORCED, "stop/av mDNS/LLMNR/NetBIOS/SSDP/WSD daemons"),
        "telemetry":    (_E.ENFORCED, "/etc/hosts sinkhole + disable phone-home units"),
        "kernel":       (_E.ENFORCED, "hardening sysctls"),
        "hostname":     (_E.ENFORCED, "NetworkManager dhcp-send-hostname=false"),
        "mac":          (_E.ENFORCED, "NetworkManager per-network MAC randomization"),
        "bluetooth_off":(_E.ENFORCED, "rfkill soft-block"),
        "webcam_off":   (_E.ENFORCED, "unload the uvcvideo kernel module"),
        "wireguard":    (_E.ENFORCED, "wg-quick + nftables killswitch"),
        "tor":          (_E.ENFORCED, "nftables transparent-proxy redirect to Tor"),
    },
    Platform.ANDROID: {
        # VPNService gives real control over egress/DNS/tunnel without root; the
        # kernel and the system firewall do not, and the OS already owns most of
        # the radio/identity surface.
        "firewall":     (_E.REQUIRES_ROOTED_OS, "a system inbound firewall needs root; unrooted Android already sandboxes inbound per-app"),
        "ipv6_privacy": (_E.ADVISORY, "Android enables IPv6 privacy addresses by default; not app-toggleable"),
        "discovery":    (_E.ADVISORY, "system owns mDNS/NSD; an app cannot silence it without root"),
        "telemetry":    (_E.REQUIRES_VPN_PROFILE, "sinkhole telemetry domains via a local VPNService DNS filter"),
        "kernel":       (_E.REQUIRES_ROOTED_OS, "sysctl hardening requires root / a custom ROM"),
        "hostname":     (_E.ADVISORY, "modern Android randomizes the DHCP hostname itself; app can only verify"),
        "mac":          (_E.ADVISORY, "Android 10+ randomizes MAC per-SSID by default; app verifies, cannot force"),
        "bluetooth_off":(_E.ADVISORY, "Android 13+ blocks apps from toggling the radio; guide the user to the toggle"),
        "webcam_off":   (_E.ADVISORY, "no module unload; guide to the OS camera kill-switch / permission revoke"),
        "wireguard":    (_E.REQUIRES_ENTITLEMENT, "native WireGuard over VPNService after a one-time VPN-consent grant"),
        "tor":          (_E.REQUIRES_VPN_PROFILE, "route all traffic through Tor via a VPNService packet tunnel"),
    },
    Platform.IOS: {
        # The most locked-down: Network Extension covers DNS and the tunnel (with
        # an Apple-granted entitlement); nearly everything else is advisory.
        "firewall":     (_E.UNAVAILABLE, "iOS exposes no app-level inbound firewall"),
        "ipv6_privacy": (_E.ADVISORY, "iOS uses private/temporary addresses by default; not app-toggleable"),
        "discovery":    (_E.ADVISORY, "system Bonjour is not app-controllable"),
        "telemetry":    (_E.REQUIRES_ENTITLEMENT, "block telemetry domains via a Network Extension DNS proxy / content filter"),
        "kernel":       (_E.UNAVAILABLE, "no sysctl / kernel access in the app sandbox"),
        "hostname":     (_E.ADVISORY, "iOS manages the DHCP hostname; app can only verify"),
        "mac":          (_E.ADVISORY, "'Private Wi-Fi Address' is on per-network by default; not app-controllable"),
        "bluetooth_off":(_E.ADVISORY, "no programmatic radio toggle; guide the user to Control Center"),
        "webcam_off":   (_E.UNAVAILABLE, "camera is permission-gated only; no disable primitive"),
        "wireguard":    (_E.REQUIRES_ENTITLEMENT, "WireGuard via NEVPNManager with the Network Extension entitlement"),
        "tor":          (_E.REQUIRES_VPN_PROFILE, "route through Tor via a Packet Tunnel Provider"),
    },
}

# The Android app can also be built into a custom Android OS and signed with that
# OS's platform key. Then it is no longer a sandboxed guest: it holds
# signature-level permissions an ordinary app can never get, so some promises the
# plain `android` row can only make as "advisory" become real.
#
# The rule that keeps this honest: a capability is listed here ONLY once the app
# has a working system control for it (android/.../system/). Everything not
# listed is inherited unchanged from the `android` row -- so this matrix never
# advertises a control that does not exist yet. It grows one slice at a time.
_ANDROID_SYSTEM_OVERRIDES: dict[str, tuple[Enforcement, str]] = {
    "kernel":       (_E.ENFORCED, "asks init to assert the pointer/ASLR/core-dump sysctls and set perf_event_paranoid=3; that one is read back as proof, the rest are readable only by init"),
    "firewall":     (_E.ENFORCED, "default-deny inbound packet filter, applied by the OS's umbra-net service and read back before it is reported"),
    "discovery":    (_E.ENFORCED, "drops outbound mDNS/LLMNR/SSDP/NetBIOS/WS-Discovery packets in the OS packet filter"),
    "telemetry":    (_E.ENFORCED, "the OS resolver answers blocklisted domains from a built-in hosts sinkhole, on any DNS transport and without the VPN slot"),
    "hostname":     (_E.ENFORCED, "sets the Wi-Fi restriction that stops the device name being sent over DHCP, on open and secured networks"),
    "mac":          (_E.ENFORCED, "forces a fresh random Wi-Fi MAC per connection on every network that randomizes (Android's default)"),
    "bluetooth_off":(_E.ENFORCED, "turns the Bluetooth radio off with the privileged adapter API"),
    "webcam_off":   (_E.ENFORCED, "sets the system 'no camera' user restriction, which blocks the camera for every app and survives a reboot"),
}
CAPABILITY_SUPPORT[Platform.ANDROID_SYSTEM] = {
    **CAPABILITY_SUPPORT[Platform.ANDROID],
    **_ANDROID_SYSTEM_OVERRIDES,
}


def current_platform() -> Platform:
    """Best-effort detection for the runtime we're executing in.

    The Linux reference runs here; ANDROID/IOS are targets the matrix describes
    for the mobile adapters, not runtimes this Python process runs under. Anything
    that isn't Linux falls back to LINUX for the local tooling's purposes.
    """
    return Platform.LINUX if sys.platform.startswith("linux") else Platform.LINUX


def support(platform: Platform, capability: str) -> CapabilitySupport:
    """The honest enforcement level for one capability on one platform."""
    table = CAPABILITY_SUPPORT[platform]
    if capability not in table:
        return CapabilitySupport(capability, Enforcement.UNAVAILABLE,
                                 f"unknown capability '{capability}'")
    level, reason = table[capability]
    return CapabilitySupport(capability, level, reason)


def matrix(platform: Platform) -> list[CapabilitySupport]:
    """Every capability's support on a platform, in a stable order."""
    return [support(platform, cap) for cap in sorted(ALL_CAPABILITIES)]


def profile_support(platform: Platform, required: list[str]) -> list[CapabilitySupport]:
    """What a platform can promise for the capabilities a profile REQUIRES.

    This is the phone app's core contract: given the profile the user picked,
    which of its promises can this device actually keep, and how.
    """
    return [support(platform, cap) for cap in required]
