"""The egress-route probe behind the HUD's `vpn` segment.

Found on real Kali (travel posture): WireGuard was carrying every packet but the
HUD said vpn=off, because the probe read the MAIN table's default route (wg-quick
uses its own policy table, so main still says eth0) and matched "wg" in the
interface name (ours is `vpn`). These pin the corrected behaviour.
"""

from __future__ import annotations

from umbra.audit import _probe_default_route
from umbra.auditmodel import Status
from umbra.runner import RunResult


class _Runner:
    dry_run = False

    def __init__(self, route_get: str | None, links: dict[str, str] | None = None):
        self.route_get, self.links = route_get, links or {}

    def run(self, argv, read_only=True, **_):
        if argv[:3] == ["ip", "route", "get"]:
            if self.route_get is None:
                return RunResult(argv, 127, "", "", False, False)        # no `ip`
            rc = 0 if self.route_get else 2                              # "" = unreachable
            return RunResult(argv, rc, self.route_get, "", True, True)
        if argv[:2] == ["ip", "-d"]:
            return RunResult(argv, 0, self.links.get(argv[-1], ""), "", True, True)
        return RunResult(argv, 127, "", "", False, False)


_WG = "5: vpn: <POINTOPOINT,NOARP,UP> mtu 1420 link/none promiscuity 0 wireguard addrgenmode none"
_ETH = "2: eth0: <BROADCAST,MULTICAST,UP> mtu 1500 link/ether 08:00:27:aa:bb:cc promiscuity 0"
_TUN = "6: tun0: <POINTOPOINT,UP> mtu 1500 link/none promiscuity 0 tun type tun pi off"


def test_wg_quick_policy_route_through_a_tunnel_named_vpn_is_up():
    r = _Runner("1.1.1.1 dev vpn table 51820 src 10.66.0.2 uid 1000\n    cache", {"vpn": _WG})
    c = _probe_default_route(r)
    assert c.status is Status.OK
    assert "vpn" in c.evidence and "wireguard" in c.evidence


def test_physical_interface_is_not_a_tunnel_even_if_named_like_one():
    # Name means nothing: a plain NIC called "wgx" is still not a tunnel.
    r = _Runner("1.1.1.1 via 10.0.2.2 dev wgx src 10.0.2.15", {"wgx": _ETH})
    assert _probe_default_route(r).status is Status.INFO


def test_openvpn_style_tun_device_counts_as_a_tunnel():
    r = _Runner("1.1.1.1 dev tun0 src 10.8.0.2", {"tun0": _TUN})
    assert _probe_default_route(r).status is Status.OK


def test_plain_egress_is_info_not_failure():
    r = _Runner("1.1.1.1 via 10.0.2.2 dev eth0 src 10.0.2.15 uid 1000", {"eth0": _ETH})
    c = _probe_default_route(r)
    assert c.status is Status.INFO and "eth0" in c.evidence


def test_no_route_and_no_ip_tool():
    assert _probe_default_route(_Runner("")).status is Status.INFO        # unreachable
    assert _probe_default_route(_Runner(None)).status is Status.NA        # ip missing
