"""The umbra terminal banner.

Shown when `umbra` is run with no command. Two safeties keep it from ever
breaking a terminal:
  * colour only on a real TTY that isn't NO_COLOR / dumb;
  * a pure-ASCII fallback when the output encoding can't do Unicode block glyphs
    (e.g. a cp1252 Windows console), so it never raises UnicodeEncodeError.
"""

from __future__ import annotations

import os
import sys

from umbra import __version__

# ANSI Shadow lettering (Unicode block glyphs) for UTF-8 terminals, e.g. Kali.
_ART_UNICODE = r"""
 ██╗   ██╗███╗   ███╗██████╗ ██████╗  █████╗
 ██║   ██║████╗ ████║██╔══██╗██╔══██╗██╔══██╗
 ██║   ██║██╔████╔██║██████╔╝██████╔╝███████║
 ██║   ██║██║╚██╔╝██║██╔══██╗██╔══██╗██╔══██║
 ╚██████╔╝██║ ╚═╝ ██║██████╔╝██║  ██║██║  ██║
  ╚═════╝ ╚═╝     ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝"""

# Pure-ASCII fallback (standard figlet).
_ART_ASCII = r"""
  _   _ __  __ ____  ____      _
 | | | |  \/  | __ )|  _ \    / \
 | | | | |\/| |  _ \| |_) |  / _ \
 | |_| | |  | | |_) |  _ <  / ___ \
  \___/|_|  |_|____/|_| \_\/_/   \_\ """

_TAGLINE = "the darkest part of a shadow"
_SUB = f"go dark on demand * privacy * anonymity * hardening * v{__version__}"

_VIOLET = "\x1b[38;5;141m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_RESET = "\x1b[0m"


def _supports_color(stream) -> bool:
    try:
        if not stream.isatty():
            return False
    except Exception:
        return False
    return os.environ.get("NO_COLOR") is None and os.environ.get("TERM") != "dumb"


def _supports_unicode(stream) -> bool:
    enc = (getattr(stream, "encoding", "") or "").lower()
    return "utf" in enc


def render_banner(color: bool | None = None, unicode: bool | None = None, stream=None) -> str:
    stream = stream or sys.stdout
    if color is None:
        color = _supports_color(stream)
    if unicode is None:
        unicode = _supports_unicode(stream)
    art = _ART_UNICODE if unicode else _ART_ASCII
    eye = "◐ " if unicode else "> "        # ◐ eclipse, or '>' in ASCII
    if color:
        art = f"{_BOLD}{_VIOLET}{art}{_RESET}"
        tag = f"   {_DIM}{eye}{_TAGLINE}{_RESET}"
        sub = f"   {_VIOLET}{_SUB}{_RESET}"
    else:
        tag, sub = f"   {eye}{_TAGLINE}", f"   {_SUB}"
    return f"{art}\n\n{tag}\n{sub}\n"


def print_banner(stream=None) -> None:
    stream = stream or sys.stdout
    try:
        stream.write(render_banner(stream=stream))
    except UnicodeEncodeError:
        # Belt and suspenders: force the ASCII form if the terminal still balks.
        stream.write(render_banner(unicode=False, stream=stream))
