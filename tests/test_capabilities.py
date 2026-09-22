"""Capability evaluation + scoring tests (pure)."""

from __future__ import annotations

from umbra import capabilities
from umbra.modules.base import Compliance, ControlState
from umbra.profiles import load_profile


class _Prof:
    def __init__(self, requires):
        self.requires = requires


def _status(**controls):
    """Build a {module: {cid: ControlState}} status from cid=Compliance kwargs."""
    out: dict = {}
    for cid, comp in controls.items():
        cid = cid.replace("__", ".")
        out.setdefault(cid.split(".")[0], {})[cid] = ControlState(cid, comp)
    return out


def test_capability_verified_when_all_controls_compliant():
    st = _status(netdark__inbound_policy=Compliance.COMPLIANT)
    res = capabilities.evaluate(_Prof(["firewall"]), st)
    assert res[0].verified and res[0].gradeable
    assert capabilities.score(res) == 100
    assert capabilities.unmet(res) == []


def test_drifted_required_capability_fails_and_lowers_score():
    st = _status(netdark__inbound_policy=Compliance.DRIFT)
    res = capabilities.evaluate(_Prof(["firewall"]), st)
    assert not res[0].verified and res[0].gradeable
    assert capabilities.score(res) == 0
    assert capabilities.unmet(res) == ["firewall"]


def test_unknown_only_capability_is_not_gradeable():
    st = _status(netdark__inbound_policy=Compliance.UNKNOWN)
    res = capabilities.evaluate(_Prof(["firewall"]), st)
    assert not res[0].gradeable
    assert capabilities.score(res) is None        # can't grade -> not a fake 0/100
    assert capabilities.unmet(res) == []          # unknown != a measured failure


def test_unsupported_required_capability_is_a_failure():
    # e.g. profile requires tor but tor isn't routing
    st = _status(tunnel__tor_config=Compliance.UNSUPPORTED)
    res = capabilities.evaluate(_Prof(["tor"]), st)
    assert res[0].gradeable and not res[0].verified
    assert capabilities.unmet(res) == ["tor"]


def test_shipped_profile_requires_are_known_tokens():
    for name in ("home", "travel", "paranoid"):
        for tok in load_profile(name).requires:
            assert tok in capabilities.ALL_CAPABILITIES
