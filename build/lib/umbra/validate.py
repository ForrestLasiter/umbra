"""Input validators for anything that becomes a filesystem path or a unit name.

Umbra runs privileged, so a profile name / VPN name / tunnel ref that contained
``/`` or ``..`` could escape its intended directory. These reject that up front.
"""

from __future__ import annotations

import re

# Profile names, tunnel profile_ref, systemd instance names: a strict slug.
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
# VPN import names: a bit looser (allow underscores / caps) but still no path bits.
_VPN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ValidationError(ValueError):
    """Raised for an input that fails validation."""


def safe_name(name: str, kind: str = "name") -> str:
    """A profile / tunnel-ref / unit slug: lowercase letters, digits, dashes."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValidationError(
            f"invalid {kind}: {name!r} (allowed: a lowercase letter/digit start, "
            "then letters, digits or dashes; no slashes or dots)")
    return name


def safe_vpn_name(name: str) -> str:
    if not isinstance(name, str) or not _VPN_NAME_RE.match(name):
        raise ValidationError(
            f"invalid vpn name: {name!r} (letters, digits, dash, underscore only)")
    return name
