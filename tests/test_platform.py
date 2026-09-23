"""Platform boundary tests — the honest enforcement matrix (pure, any OS)."""

from __future__ import annotations

from umbra.capabilities import ALL_CAPABILITIES
from umbra import platform as plat
from umbra.platform import Enforcement, Platform
from umbra.profiles import load_profile


def test_every_platform_covers_every_capability():
    # A gap in the matrix is a place the app could silently pretend. Forbid it.
    for p in Platform:
        covered = set(plat.CAPABILITY_SUPPORT[p])
        assert covered == set(ALL_CAPABILITIES), f"{p.value} missing {ALL_CAPABILITIES - covered}"


def test_matrix_has_one_row_per_capability():
    rows = plat.matrix(Platform.ANDROID)
    assert len(rows) == len(ALL_CAPABILITIES)
    assert {r.capability for r in rows} == set(ALL_CAPABILITIES)


def test_linux_reference_enforces_everything():
    # Linux is the reference implementation: it must claim ENFORCED across the
    # board (that's what makes it the yardstick the phones are measured against).
    assert all(r.level is Enforcement.ENFORCED for r in plat.matrix(Platform.LINUX))


def test_phones_do_not_pretend_full_enforcement():
    # The whole point: a phone must be honest about what it cannot do.
    for p in (Platform.ANDROID, Platform.IOS):
        levels = {r.level for r in plat.matrix(p)}
        assert levels != {Enforcement.ENFORCED}, f"{p.value} claims full enforcement"


def test_every_row_has_a_nonempty_reason():
    for p in Platform:
        for r in plat.matrix(p):
            assert r.reason.strip(), f"{p.value}/{r.capability} has no reason"


def test_profile_support_filters_to_required_capabilities():
    home = load_profile("home")
    rows = plat.profile_support(Platform.ANDROID, home.requires)
    assert [r.capability for r in rows] == home.requires


def test_unknown_capability_is_unavailable():
    s = plat.support(Platform.IOS, "teleportation")
    assert s.level is Enforcement.UNAVAILABLE


def test_actionable_excludes_only_advisory_and_unavailable():
    enf = plat.support(Platform.LINUX, "firewall")
    adv = plat.support(Platform.IOS, "mac")
    una = plat.support(Platform.IOS, "kernel")
    assert enf.actionable is True
    assert adv.actionable is False and una.actionable is False


def test_current_platform_is_a_platform():
    assert isinstance(plat.current_platform(), Platform)
