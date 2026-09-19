"""Profile loader tests — these run on any OS (no system calls involved)."""

from __future__ import annotations

import pytest

from umbra.profiles import ProfileError, load_profile, list_profiles


def test_all_shipped_profiles_are_valid():
    for name in list_profiles():
        profile = load_profile(name)
        assert profile.name == name


def test_normal_disables_every_module():
    profile = load_profile("normal")
    for module in ("rf", "netdark", "tunnel", "telemetry"):
        assert profile.module_config(module).get("enabled") is False


def test_extends_merges_parent_then_child_wins():
    # travel extends home; it must inherit home's netdark discovery block while
    # overriding the tunnel to be enabled.
    travel = load_profile("travel")
    assert travel.module_config("tunnel")["enabled"] is True
    assert travel.module_config("tunnel")["killswitch"] is True
    # inherited from home (not restated in travel.yaml):
    assert travel.module_config("netdark")["discovery"]["mdns"] is True


def test_paranoid_is_closed_and_requires_confirm():
    paranoid = load_profile("paranoid")
    assert paranoid.fail_mode == "closed"
    assert paranoid.require_confirm is True


def test_unknown_profile_raises():
    with pytest.raises(ProfileError):
        load_profile("does-not-exist")
