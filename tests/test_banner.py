"""Banner tests — ensure it never crashes a terminal (ASCII-safe, opt-in colour)."""

from __future__ import annotations

from umbra import __version__
from umbra.banner import render_banner


def test_ascii_fallback_is_pure_ascii_and_has_version():
    b = render_banner(color=False, unicode=False)
    b.encode("ascii")                     # raises if any non-ASCII slips in
    assert f"v{__version__}" in b
    assert "shadow" in b


def test_color_wraps_in_ansi_and_resets():
    b = render_banner(color=True, unicode=True)
    assert "\x1b[" in b and "\x1b[0m" in b


def test_no_color_has_no_ansi_escapes():
    b = render_banner(color=False, unicode=True)
    assert "\x1b[" not in b
