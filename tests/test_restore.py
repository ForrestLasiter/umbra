"""Restore-primitive tests using a fake Runner (no real system calls).

These prove the NEW Phase-2 primitives issue the right commands, cross-platform.
A FakeRunner records the argv it is asked to run instead of executing anything.
"""

from __future__ import annotations

import pytest

from umbra.restore import RESTORE_PRIMITIVES, apply_restore


class FakeRunner:
    """Stand-in for Runner that records commands instead of running them."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv, *, read_only, check=False, input_text=None):
        self.calls.append(argv)

        class _R:  # minimal RunResult-ish
            ok = True
            available = True
            stdout = ""
        return _R()


def test_new_primitives_are_registered():
    assert "rfkill_set" in RESTORE_PRIMITIVES
    assert "nftables_table_delete" in RESTORE_PRIMITIVES


def test_rfkill_set_blocks_when_prior_was_blocked():
    r = FakeRunner()
    apply_restore(r, "rfkill_set", {"identifier": "bluetooth", "was_blocked": True})
    assert r.calls == [["rfkill", "block", "bluetooth"]]


def test_rfkill_set_unblocks_when_prior_was_unblocked():
    r = FakeRunner()
    apply_restore(r, "rfkill_set", {"identifier": "wwan", "was_blocked": False})
    assert r.calls == [["rfkill", "unblock", "wwan"]]


def test_table_delete_removes_only_our_table():
    r = FakeRunner()
    apply_restore(r, "nftables_table_delete", {"family": "inet", "table": "umbra_egress"})
    assert r.calls == [["nft", "delete", "table", "inet", "umbra_egress"]]


def test_unknown_method_is_refused():
    with pytest.raises(ValueError):
        apply_restore(FakeRunner(), "rm_rf_everything", {})
