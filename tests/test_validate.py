"""Input-validation tests (path-traversal / injection guards)."""

from __future__ import annotations

import pytest

from umbra.profiles import ProfileError, load_profile
from umbra.validate import ValidationError, safe_name, safe_vpn_name


@pytest.mark.parametrize("bad", [
    "../etc", "a/b", "..", "/abs", "Foo", "1abc", "", "a" * 70, "a.b", "wg hub",
])
def test_safe_name_rejects_traversal_and_junk(bad):
    with pytest.raises(ValidationError):
        safe_name(bad)


def test_safe_name_accepts_slugs():
    assert safe_name("home") == "home"
    assert safe_name("wg-hub") == "wg-hub"


def test_safe_vpn_name():
    assert safe_vpn_name("Mullvad_1") == "Mullvad_1"
    for bad in ["../x", "a/b", "", "a b"]:
        with pytest.raises(ValidationError):
            safe_vpn_name(bad)


def test_load_profile_rejects_traversal_name():
    with pytest.raises(ProfileError):
        load_profile("../../etc/passwd")
