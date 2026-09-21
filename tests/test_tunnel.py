"""tunnel module — pure-logic tests for endpoint parsing + killswitch builder."""

from __future__ import annotations

from umbra.modules.tunnel import (
    _build_killswitch,
    _build_tor_filter,
    _build_tor_nat,
    _endpoint_from_conf,
    _strip_tor_block,
    _torrc_block,
)

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


# --- Tor transparent proxy --------------------------------------------------

def test_tor_nat_redirects_dns_and_tcp_and_excepts_tor_uid():
    nat = _build_tor_nat("115")
    assert "meta skuid 115 return" in nat                 # Tor's own traffic goes direct
    assert "udp dport 53 redirect to :9053" in nat        # DNS -> Tor DNSPort
    assert "tcp dport 53 redirect to :9053" in nat
    assert "meta l4proto tcp redirect to :9040" in nat    # all TCP -> Tor TransPort
    assert "ip daddr 127.0.0.0/8 return" in nat           # loopback untouched
    # DNS redirect must precede the loopback return, so a query to 127.0.0.1:53
    # is still sent to Tor's DNSPort.
    assert nat.index("udp dport 53 redirect") < nat.index("ip daddr 127.0.0.0/8 return")


def test_tor_filter_is_leak_tight():
    filt = _build_tor_filter("115")
    assert "policy drop" in filt                          # default-deny egress
    assert "meta skuid 115 accept" in filt                # only Tor's uid gets out
    assert 'oif "lo" accept' in filt
    assert "ip daddr 127.0.0.0/8 accept" in filt          # redirected-to-Tor traffic
    # crucially: no IPv6 accept rule at all -> all IPv6 is dropped (no leaks)
    assert "ip6" not in filt


def test_torrc_block_sets_transparent_ports():
    block = _torrc_block()
    assert "TransPort 127.0.0.1:9040" in block
    assert "DNSPort 127.0.0.1:9053" in block
    assert "AutomapHostsOnResolve 1" in block


def test_strip_tor_block_is_idempotent():
    original = "SocksPort 9050\n"
    with_block = original + _torrc_block()
    assert _strip_tor_block(with_block).strip() == original.strip()
    assert _strip_tor_block(original) == original         # nothing to strip
