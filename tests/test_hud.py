"""Ops HUD rendering tests (pure, run on any OS — no GTK needed)."""

from __future__ import annotations

import json

from umbra import hud
from umbra.auditmodel import AuditReport, Check, Status
from umbra.capabilities import CapResult
from umbra.hud import Segment


def _report(**over) -> AuditReport:
    checks = [
        Check("require:firewall", "Required: firewall", "required", Status.OK, "verified"),
        Check("require:tor", "Required: tor", "required", Status.FAIL, "not verified"),
        Check("route", "Default route", "tunnel", Status.OK, "via tunnel: default dev wg0"),
        Check("exposure", "Listening TCP sockets", "exposure", Status.OK,
              "nothing listening beyond loopback"),
    ]
    required = [CapResult("firewall", True, True, "verified"),
                CapResult("tor", False, True, "drift")]
    r = AuditReport("travel", "2026-01-01T00:00:00+00:00", checks=checks, required=required)
    for k, v in over.items():
        setattr(r, k, v)
    return r


def _by_label(segs, label) -> Segment:
    return next(s for s in segs if s.label == label)


def test_segments_cover_the_pitched_fields():
    segs = hud.build_segments(_report(), active="travel")
    labels = [s.label for s in segs]
    assert labels == ["umbra", "score", "fw", "vpn", "tor", "net"]


def test_active_profile_and_score_status():
    segs = hud.build_segments(_report(), active="travel")
    assert _by_label(segs, "umbra").value == "travel"
    score = _by_label(segs, "score")
    assert score.value == "50"                     # 1 of 2 required verified
    assert score.status is Status.FAIL             # <60 -> red


def test_firewall_up_vpn_up_from_route_probe():
    segs = hud.build_segments(_report(), active="travel")
    assert _by_label(segs, "fw").value == "on" and _by_label(segs, "fw").status is Status.OK
    # route probe is OK (dev wg0) -> tunnel up
    assert _by_label(segs, "vpn").value == "up" and _by_label(segs, "vpn").status is Status.OK


def test_tor_off_when_required_but_failing():
    tor = _by_label(hud.build_segments(_report(), active="travel"), "tor")
    assert tor.value == "off" and tor.status is Status.FAIL


def test_vpn_down_when_required_wireguard_fails():
    checks = [Check("require:wireguard", "Required: wireguard", "required", Status.FAIL, "x"),
              Check("route", "Default route", "tunnel", Status.INFO, "default dev eth0")]
    r = AuditReport("travel", "t", checks=checks, required=[])
    assert _by_label(hud.build_segments(r, "travel"), "vpn").value == "down"


def test_absent_capabilities_read_as_neutral_not_failed():
    # A stock machine: no require:* checks, plain default route, quiet sockets.
    checks = [Check("route", "Default route", "tunnel", Status.INFO, "default dev eth0"),
              Check("exposure", "Listening TCP sockets", "exposure", Status.OK, "quiet")]
    segs = hud.build_segments(AuditReport("home", "t", checks=checks, required=[]), active=None)
    assert _by_label(segs, "umbra").value == "stock"
    assert _by_label(segs, "fw").value == "n/a" and _by_label(segs, "fw").status is Status.INFO
    assert _by_label(segs, "tor").value == "off" and _by_label(segs, "tor").status is Status.INFO
    assert _by_label(segs, "vpn").value == "off"


def test_exposure_counts_open_sockets():
    checks = [Check("exposure", "Listening TCP sockets", "exposure", Status.WARN,
                    "reachable: 0.0.0.0:22, [::]:631")]
    net = _by_label(hud.build_segments(AuditReport("home", "t", checks=checks), "home"), "net")
    assert net.value == "2 open" and net.status is Status.WARN


def test_public_ip_segment_is_opt_in():
    assert not any(s.label == "ip" for s in hud.build_segments(_report(), "travel"))
    segs = hud.build_segments(_report(), "travel", public_ip="203.0.113.7")
    assert _by_label(segs, "ip").value == "203.0.113.7"


def test_render_line_color_is_ansi_and_toggleable():
    segs = hud.build_segments(_report(), "travel")
    colored = hud.render_line(segs, color=True)
    plain = hud.render_line(segs, color=False)
    assert "\x1b[" in colored and "\x1b[" not in plain
    assert "umbra" in plain and "travel" in plain and "tor" in plain


def test_render_json_is_structured():
    segs = hud.build_segments(_report(), "travel")
    data = json.loads(hud.render_json(segs, "travel", 50))
    assert data["active"] == "travel" and data["score"] == 50
    fw = next(s for s in data["segments"] if s["label"] == "fw")
    assert fw["value"] == "on" and fw["status"] == "ok"


def test_render_markup_is_pango_and_escapes():
    markup = hud.render_markup(hud.build_segments(_report(), "travel"))
    assert "<span" in markup and "foreground=" in markup
    # a WARN exposure value with an ampersand would need escaping; ensure no bare &
    hostile = [Segment("x", "a & b", Status.OK)]
    assert "&amp;" in hud.render_markup(hostile)
