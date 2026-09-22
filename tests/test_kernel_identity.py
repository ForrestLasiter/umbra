"""Tests for the kernel + identity modules (cross-platform, no root)."""

from __future__ import annotations

from umbra.modules.identity import IdentityModule
from umbra.modules.kernel import _SYSCTLS, KernelModule, _cid
from umbra.profiles import load_profile
from umbra.runner import Runner


def test_kernel_excludes_one_way_sysctls():
    # kexec_load_disabled / unprivileged_bpf_disabled can't be reset until reboot,
    # which would break clean revert -- they must NOT be managed.
    assert "kernel.kexec_load_disabled" not in _SYSCTLS
    assert "kernel.unprivileged_bpf_disabled" not in _SYSCTLS


def test_kernel_control_ids_are_dot_safe_and_unique():
    ids = [_cid(k) for k in _SYSCTLS]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("kernel.sc_") and " " not in i for i in ids)


def test_kernel_module_measures_without_error():
    m = KernelModule(Runner(dry_run=False))
    m.configure({"enabled": True, "hardening_sysctls": True, "disable_webcam": True})
    states = m.measure()                      # off-Linux -> NA, must not raise
    assert len(states) == len(_SYSCTLS) + 1   # sysctls + webcam
    assert m.controls()                        # declares controls


def test_identity_enabled_via_home_profile():
    ident = load_profile("home").module_config("identity")
    assert ident["enabled"] is True
    assert ident["dhcp_hostname_suppress"] is True


def test_identity_disabled_module_plans_nothing():
    m = IdentityModule(Runner(dry_run=False))
    m.configure({"enabled": False})
    assert m.plan() == []
