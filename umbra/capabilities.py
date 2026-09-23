"""Required capabilities: what a profile PROMISES, and whether it's verified.

A profile declares `meta.requires: [firewall, tor, ...]`. Each token maps to the
control(s) that must all measure COMPLIANT for that promise to hold. The audit
scores only these required capabilities, and apply/doctor fail when a required one
can't be verified — so a profile never silently under-delivers (e.g. "tor" when
Tor isn't actually routing).
"""

from __future__ import annotations

from dataclasses import dataclass

from umbra.model import Compliance

# capability token -> control-id patterns ('*' suffix = prefix match).
CAPABILITY_CONTROLS: dict[str, tuple[str, ...]] = {
    "firewall": ("netdark.inbound_policy",),
    "ipv6_privacy": ("netdark.ipv6_privacy",),
    "discovery": ("netdark.mdns", "netdark.netbios", "netdark.llmnr",
                  "netdark.ssdp_upnp", "netdark.wsd"),
    "telemetry": ("telemetry.hosts_sinkhole",),
    "kernel": ("kernel.sc_*",),
    "hostname": ("identity.dhcp_hostname",),
    "mac": ("rf.mac",),
    "bluetooth_off": ("rf.radio_bluetooth",),
    "webcam_off": ("kernel.disable_webcam",),
    "wireguard": ("tunnel.route", "tunnel.killswitch"),
    "tor": ("tunnel.tor_config", "tunnel.route", "tunnel.killswitch"),
}

ALL_CAPABILITIES = frozenset(CAPABILITY_CONTROLS)


@dataclass
class CapResult:
    token: str
    verified: bool          # all matching controls COMPLIANT
    gradeable: bool         # at least one matching control could be measured
    detail: str


def _match(cid: str, patterns: tuple[str, ...]) -> bool:
    for p in patterns:
        if p.endswith("*"):
            if cid.startswith(p[:-1]):
                return True
        elif cid == p:
            return True
    return False


def _flatten(status: dict) -> dict:
    flat: dict = {}
    for states in status.values():
        flat.update(states)
    return flat


def evaluate(profile, status: dict) -> list[CapResult]:
    """Assess each capability the profile requires against a measured status."""
    flat = _flatten(status)
    results: list[CapResult] = []
    for token in getattr(profile, "requires", []) or []:
        patterns = CAPABILITY_CONTROLS.get(token)
        if patterns is None:
            results.append(CapResult(token, False, True, f"unknown capability '{token}'"))
            continue
        matched = [(cid, cs) for cid, cs in flat.items() if _match(cid, patterns)]
        if not matched:
            results.append(CapResult(token, False, True,
                                     "no matching control present on this host"))
            continue
        all_ok = all(cs.compliance is Compliance.COMPLIANT for _, cs in matched)
        gradeable = any(cs.compliance is not Compliance.UNKNOWN for _, cs in matched)
        if all_ok:
            results.append(CapResult(token, True, True, "verified"))
        else:
            bad = [f"{cid}={cs.compliance.value}"
                   for cid, cs in matched if cs.compliance is not Compliance.COMPLIANT]
            results.append(CapResult(token, False, gradeable, "not verified: " + ", ".join(bad)))
    return results


def score(results: list[CapResult]) -> int | None:
    """0-100 over the gradeable required capabilities; None when none are gradeable
    (e.g. off-Linux, where nothing can be measured)."""
    gradeable = [r for r in results if r.gradeable]
    if not gradeable:
        return None
    return round(100 * sum(1 for r in gradeable if r.verified) / len(gradeable))


def unmet(results: list[CapResult]) -> list[str]:
    """Required capabilities that could be measured but did NOT verify."""
    return [r.token for r in results if r.gradeable and not r.verified]
