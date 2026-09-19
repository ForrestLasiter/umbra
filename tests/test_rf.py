"""rf module — pure-logic tests (no radios required, run on any OS)."""

from __future__ import annotations

from umbra.modules.rf import _mac_conf_text, _radios_to_block


def test_permitted_wifi_blocks_the_other_radios():
    blocked = _radios_to_block(["wifi"], bluetooth_off=False)
    assert set(blocked) == {"bluetooth", "wwan", "nfc"}
    assert "wifi" not in blocked


def test_empty_permit_list_blocks_everything():
    assert set(_radios_to_block([], bluetooth_off=False)) == {"wifi", "bluetooth", "wwan", "nfc"}


def test_bluetooth_off_forces_block_even_if_permitted():
    # bluetooth is in the permitted list, but bluetooth: off overrides.
    blocked = _radios_to_block(["wifi", "bluetooth"], bluetooth_off=True)
    assert "bluetooth" in blocked
    assert "wifi" not in blocked


def test_mac_mode_per_network_is_stable_others_random():
    assert "cloned-mac-address=stable" in _mac_conf_text("per-network")
    assert "cloned-mac-address=random" in _mac_conf_text("full")
    # scan randomization is always on (probe-request privacy)
    assert "wifi.scan-rand-mac-address=yes" in _mac_conf_text("per-network")
