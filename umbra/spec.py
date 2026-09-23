"""Export the platform-agnostic core as a language-neutral spec.

The Linux agent is Python, but the Android app is Kotlin and the iOS app is
Swift. They must all speak the *same* posture language: the same profiles, the
same capability tokens, the same honest per-platform enforcement matrix, and the
same audit shape. Rather than re-encode that three times (and drift), the Python
core is the single source of truth and emits it as JSON here.

`umbra export-spec` writes:
  * spec/umbra-core.json         -- the data every platform consumes
  * spec/umbra-core.schema.json  -- a JSON Schema that validates it

Nothing in this module is Linux-specific; it is pure core.
"""

from __future__ import annotations

import json
from pathlib import Path

from umbra import __version__
from umbra.blocklists import TELEMETRY_BLOCKLISTS
from umbra.capabilities import CAPABILITY_CONTROLS
from umbra.platform import CAPABILITY_SUPPORT, Enforcement, Platform
from umbra.profiles import list_profiles, load_profile

SPEC_VERSION = "1"

# One line per capability: what the token PROMISES, independent of how any
# platform delivers it. (The controls that satisfy it live in capabilities.py.)
CAPABILITY_DESCRIPTIONS: dict[str, str] = {
    "firewall": "Do not be reachable from the local network (default-deny inbound).",
    "ipv6_privacy": "Use rotating IPv6 privacy addresses, not a stable EUI-64.",
    "discovery": "Emit no local-network discovery chatter (mDNS/LLMNR/NetBIOS/SSDP/WSD).",
    "telemetry": "Block OS/app phone-home and telemetry destinations.",
    "kernel": "Apply kernel hardening (restricted pointers/dmesg/ptrace, full ASLR).",
    "hostname": "Do not broadcast a stable hostname over DHCP.",
    "mac": "Randomize the Wi-Fi MAC so the hardware address is not a tracker.",
    "bluetooth_off": "Keep the Bluetooth radio off.",
    "webcam_off": "Disable the camera at the device level.",
    "wireguard": "Route all traffic through a WireGuard tunnel with an egress killswitch.",
    "tor": "Route all traffic through Tor with an egress killswitch.",
}

_ENFORCEMENT_DESCRIPTIONS: dict[Enforcement, str] = {
    Enforcement.ENFORCED: "Guaranteed with ordinary app permissions.",
    Enforcement.REQUIRES_ENTITLEMENT: "Enforced after the OS grants a special entitlement (e.g. VPN consent, Network Extension).",
    Enforcement.REQUIRES_VPN_PROFILE: "Enforced only while an Umbra tunnel/VPN profile is active.",
    Enforcement.REQUIRES_ROOTED_OS: "Only possible with root or a custom OS build.",
    Enforcement.ADVISORY: "The app can measure and warn, but cannot change it.",
    Enforcement.UNAVAILABLE: "Not applicable or impossible on this platform.",
}

_PLATFORM_DESCRIPTIONS: dict[Platform, str] = {
    Platform.LINUX: "Reference implementation. Enforces every control directly (nftables, systemd, sysctl, rfkill, Tor).",
    Platform.ANDROID: "VPNService-based. Real egress/DNS/tunnel control without root; kernel and system firewall need root.",
    Platform.IOS: "Network Extension-based. DNS and the tunnel via an entitlement; nearly everything else is advisory.",
}


def build_spec() -> dict:
    """Assemble the full core spec as a JSON-serializable dict."""
    capabilities = {
        token: {
            "description": CAPABILITY_DESCRIPTIONS.get(token, ""),
            "controls": list(controls),
        }
        for token, controls in sorted(CAPABILITY_CONTROLS.items())
    }

    platforms = {}
    for platform in Platform:
        caps = {
            token: {"level": level.value, "reason": reason}
            for token, (level, reason) in sorted(CAPABILITY_SUPPORT[platform].items())
        }
        platforms[platform.value] = {
            "description": _PLATFORM_DESCRIPTIONS[platform],
            "capabilities": caps,
        }

    profiles = {}
    for name in list_profiles():
        prof = load_profile(name)
        # Which telemetry blocklists this profile sinkholes (the adapters union
        # these into a DNS filter; the Linux agent writes them to /etc/hosts).
        tele = prof.data.get("modules", {}).get("telemetry", {})
        tele_lists = tele.get("blocklists", []) if tele.get("enabled") else []
        profiles[name] = {
            "description": prof.data.get("description", ""),
            "fail_mode": prof.fail_mode,
            "requires": prof.requires,
            "telemetry_blocklists": list(tele_lists),
            "modules": prof.data.get("modules", {}),
        }

    return {
        "umbra_spec_version": SPEC_VERSION,
        "engine_version": __version__,
        "enforcement_levels": [
            {"name": level.value, "description": _ENFORCEMENT_DESCRIPTIONS[level]}
            for level in Enforcement
        ],
        "capabilities": capabilities,
        "platforms": platforms,
        "telemetry_blocklists": {name: list(domains)
                                 for name, domains in sorted(TELEMETRY_BLOCKLISTS.items())},
        "profiles": profiles,
        "audit": {
            "status_values": ["ok", "warn", "fail", "info", "na"],
            "check_fields": ["id", "title", "category", "status", "evidence", "recommendation"],
            "score": "0-100 over the profile's REQUIRED, gradeable capabilities; null when none are gradeable. Never a fake 100.",
        },
    }


def build_schema() -> dict:
    """A JSON Schema that the emitted spec must satisfy (guards drift)."""
    levels = [e.value for e in Enforcement]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Umbra core spec",
        "type": "object",
        "required": ["umbra_spec_version", "engine_version", "enforcement_levels",
                     "capabilities", "platforms", "telemetry_blocklists", "profiles", "audit"],
        "properties": {
            "umbra_spec_version": {"type": "string"},
            "engine_version": {"type": "string"},
            "enforcement_levels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "description"],
                    "properties": {
                        "name": {"enum": levels},
                        "description": {"type": "string"},
                    },
                },
            },
            "capabilities": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["description", "controls"],
                    "properties": {
                        "description": {"type": "string"},
                        "controls": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "platforms": {
                "type": "object",
                "required": ["linux", "android", "ios"],
                "additionalProperties": {
                    "type": "object",
                    "required": ["description", "capabilities"],
                    "properties": {
                        "description": {"type": "string"},
                        "capabilities": {
                            "type": "object",
                            "additionalProperties": {
                                "type": "object",
                                "required": ["level", "reason"],
                                "properties": {
                                    "level": {"enum": levels},
                                    "reason": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "telemetry_blocklists": {
                "type": "object",
                "additionalProperties": {"type": "array", "items": {"type": "string"}},
            },
            "profiles": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["requires", "fail_mode"],
                    "properties": {
                        "description": {"type": "string"},
                        "fail_mode": {"type": "string"},
                        "requires": {"type": "array", "items": {"type": "string"}},
                        "telemetry_blocklists": {"type": "array", "items": {"type": "string"}},
                        "modules": {"type": "object"},
                    },
                },
            },
            "audit": {"type": "object"},
        },
    }


def write_spec(out_dir: Path) -> tuple[Path, Path]:
    """Write the spec + its schema to out_dir. Returns (spec_path, schema_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / "umbra-core.json"
    schema_path = out_dir / "umbra-core.schema.json"
    spec_path.write_text(json.dumps(build_spec(), indent=2) + "\n", encoding="utf-8")
    schema_path.write_text(json.dumps(build_schema(), indent=2) + "\n", encoding="utf-8")
    return spec_path, schema_path
