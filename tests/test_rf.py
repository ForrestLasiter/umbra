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


# --- radio measurement -------------------------------------------------------

from umbra import capabilities  # noqa: E402
from umbra.model import Compliance, ControlState  # noqa: E402
from umbra.modules.rf import RfModule  # noqa: E402
from umbra.profiles import load_profile  # noqa: E402
from umbra.runner import RunResult  # noqa: E402


class _RfkillRunner:
    """Answers `rfkill list <radio>` with canned output (None = rfkill missing)."""
    dry_run = False

    def __init__(self, outputs: dict[str, str | None]):
        self.outputs = outputs

    def run(self, argv, read_only=True, **_):
        out = self.outputs.get(argv[-1], "")
        if out is None:
            return RunResult(argv, 127, "", "", executed=False, available=False)
        return RunResult(argv, 0, out, "", executed=True, available=True)


def _measure_bt(rfkill_out):
    mod = RfModule(_RfkillRunner({"bluetooth": rfkill_out}))
    mod.configure({"enabled": True, "bluetooth": "off", "radios": ["wifi"]})
    return mod._measure_radio("bluetooth")


def test_absent_radio_is_already_silent_not_unsupported():
    # Regression: no Bluetooth hardware used to read UNSUPPORTED, which the
    # grader counts as an unkept promise (paranoid scored 90, apply failed).
    st = _measure_bt("")
    assert st.compliance is Compliance.COMPLIANT
    assert "no such radio" in st.detail


def test_soft_blocked_radio_is_compliant():
    st = _measure_bt("0: hci0: Bluetooth\n\tSoft blocked: yes\n\tHard blocked: no\n")
    assert st.compliance is Compliance.COMPLIANT


def test_live_radio_is_drift():
    st = _measure_bt("0: hci0: Bluetooth\n\tSoft blocked: no\n\tHard blocked: no\n")
    assert st.compliance is Compliance.DRIFT


def test_missing_rfkill_is_unknown():
    assert _measure_bt(None).compliance is Compliance.UNKNOWN


def test_paranoid_on_a_bluetooth_less_box_scores_100():
    flat: dict = {}
    for pats in capabilities.CAPABILITY_CONTROLS.values():
        for pat in pats:
            cid = pat[:-1] + "kernel_kptr_restrict" if pat.endswith("*") else pat
            flat[cid] = ControlState(cid, Compliance.COMPLIANT)
    flat["rf.radio_bluetooth"] = _measure_bt("")            # no BT hardware
    res = capabilities.evaluate(load_profile("paranoid"), {"all": flat})
    assert capabilities.unmet(res) == []                    # apply won't fail on it
    assert capabilities.score(res) == 100
