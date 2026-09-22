"""Tray tests - the command builder is pure and importing the module needs no GUI."""

from __future__ import annotations

from umbra.tray import command_for


def test_profile_uses_pkexec_and_confirm():
    assert command_for("travel") == ["umbra", "--pkexec", "--confirm", "apply", "travel"]


def test_normal_and_panic_are_their_own_commands():
    assert command_for("normal") == ["umbra", "--pkexec", "normal"]
    assert command_for("panic") == ["umbra", "--pkexec", "panic"]


def test_importing_tray_does_not_require_a_gui_stack():
    # module import must not pull in gi/AppIndicator (that happens inside run()).
    import umbra.tray as tray
    assert hasattr(tray, "run")
