"""tunnel module — pure-logic tests for endpoint parsing + killswitch builder."""

from __future__ import annotations

from umbra.modules.tunnel import _build_killswitch, _endpoint_from_conf

_SAMPLE_CONF = """\
[Interface]
PrivateKey = abc123=
Address = 10.7.0.2/24
DNS = 10.7.0.1

[Peer]
PublicKey = def456=
Endpoint = vpn.example.net:51820
AllowedIPs = 0.0.0.0/0
"""


def test_endpoint_is_parsed_from_conf():
    assert _endpoint_from_conf(_SAMPLE_CONF) == ("vpn.example.net", "51820")


def test_endpoint_missing_returns_none():
    assert _endpoint_from_conf("[Interface]\nAddress = 10.0.0.1/24\n") is None


def test_killswitch_allows_tunnel_and_endpoint_only():
    rules = _build_killswitch("vpn", "203.0.113.5", "51820")
    assert "policy drop" in rules                 # default-deny egress
    assert 'oifname "vpn" accept' in rules         # the tunnel is allowed
    assert "ip daddr 203.0.113.5 udp dport 51820 accept" in rules  # endpoint reachable
    assert 'oifname "lo" accept' in rules          # loopback survives
