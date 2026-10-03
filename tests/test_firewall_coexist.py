"""The stealth firewall coexists with other programs' rules.

Found on real Kali: every posture ran `nft flush ruleset`, so Docker's NAT/filter
tables (and any ufw/libvirt/Tailscale rules) were wiped for as long as you were
dark -- containers lost networking -- and undo had to rebuild them from a text
dump in one `nft -f`, which failed on Forrest's box (`! netdark.inbound_policy`)
and left the posture stuck. These pin the replacement: own-table only, atomic,
undo = delete our table, and a robust per-table legacy restore for old snapshots.
"""

from __future__ import annotations

import logging

from umbra import restore, snapshots
from umbra.modules.netdark import NetdarkModule
from umbra.runner import RunResult, Runner


class _Rec:
    """Records every command; answers `nft list tables` and can fail some loads."""
    dry_run = False

    def __init__(self, live_tables: str = "", refuse: str | None = None):
        self.calls: list[tuple[list[str], str | None]] = []
        self.live_tables, self.refuse = live_tables, refuse

    def run(self, argv, read_only=True, check=False, input_text=None, **_):
        self.calls.append((list(argv), input_text))
        if argv[:3] == ["nft", "list", "tables"]:
            return RunResult(argv, 0, self.live_tables, "", True, True)
        if argv[:2] == ["nft", "-f"] and self.refuse and self.refuse in (input_text or ""):
            return RunResult(argv, 1, "", "Error: syntax error, unexpected xt", True, True)
        return RunResult(argv, 0, "", "", True, True)

    def loads(self) -> list[str]:
        return [text for argv, text in self.calls if argv[:2] == ["nft", "-f"]]

    def flushed(self) -> bool:
        return any(argv[:3] == ["nft", "flush", "ruleset"] for argv, _ in self.calls)


class _Snap:
    def __init__(self):
        self.recorded = []

    def record(self, control, method, prior):
        self.recorded.append((control, method, prior))


# --- apply ---------------------------------------------------------------------

def test_apply_replaces_only_umbras_table_atomically():
    r = _Rec()
    mod = NetdarkModule(r)
    snap = _Snap()
    mod._apply_firewall(snap)

    assert not r.flushed()                                  # never wipes other rules
    (load,) = r.loads()                                     # ONE atomic transaction
    assert "delete table inet umbra" in load
    assert "policy drop" in load                            # stealth inbound
    assert "ct status dnat drop" in load                    # no published ports while dark
    assert snap.recorded == [("netdark.inbound_policy", "nftables_table_delete",
                              {"family": "inet", "table": "umbra"})]


def test_undo_of_a_new_snapshot_deletes_just_our_table():
    r = _Rec()
    restore.apply_restore(r, "nftables_table_delete", {"family": "inet", "table": "umbra"})
    assert r.calls == [(["nft", "delete", "table", "inet", "umbra"], None)]


# --- legacy snapshots (taken when apply flushed everything) --------------------

_DUMP = """\
# Warning: table ip nat is managed by iptables-nft, do not touch!
table ip nat {
	chain PREROUTING {
		type nat hook prerouting priority dstnat; policy accept;
		fib daddr type local counter packets 0 bytes 0 jump DOCKER
	}
	chain DOCKER {
	}
}
table ip filter {
	chain FORWARD {
		type filter hook forward priority filter; policy accept;
		counter jump DOCKER-USER comment "brace { in a comment"
	}
	chain DOCKER-USER {
	}
}
table inet umbra {
	chain input {
		type filter hook input priority filter; policy drop;
	}
}
"""


def test_table_blocks_split_on_top_level_tables_ignoring_quoted_braces():
    blocks = restore._nft_table_blocks(_DUMP)
    assert [k for k, _ in blocks] == [("ip", "nat"), ("ip", "filter"), ("inet", "umbra")]
    assert blocks[1][1].rstrip().endswith("}") and "DOCKER-USER {" in blocks[1][1]


def test_legacy_restore_removes_umbra_and_rebuilds_each_missing_table():
    r = _Rec(live_tables="table inet umbra\ntable ip umbra_tor_nat\n")
    restore.apply_restore(r, "nftables_replace", {"ruleset": _DUMP})

    assert not r.flushed()
    deletes = [a for a, _ in r.calls if a[:3] == ["nft", "delete", "table"]]
    assert deletes == [["nft", "delete", "table", "inet", "umbra"],
                       ["nft", "delete", "table", "ip", "umbra_tor_nat"]]
    loads = r.loads()
    assert len(loads) == 2                                  # one per foreign table
    assert loads[0].startswith("table ip nat") and loads[1].startswith("table ip filter")
    assert not any("table inet umbra" in l for l in loads)  # never reload our own


def test_legacy_restore_leaves_a_table_its_owner_already_recreated():
    r = _Rec(live_tables="table inet umbra\ntable ip nat\n")      # docker restarted
    restore.apply_restore(r, "nftables_replace", {"ruleset": _DUMP})
    assert [l.split("{")[0].strip() for l in r.loads()] == ["table ip filter"]


def test_one_unloadable_table_warns_instead_of_sinking_the_restore(caplog):
    r = _Rec(live_tables="table inet umbra\n", refuse="table ip nat")
    with caplog.at_level(logging.WARNING, logger="umbra.restore"):
        restore.apply_restore(r, "nftables_replace", {"ruleset": _DUMP})  # no raise
    assert len(r.loads()) == 2                              # filter still rebuilt
    assert "table ip nat" in caplog.text and "syntax error" in caplog.text


# --- failures are never silent ---------------------------------------------------

def test_restore_failures_are_logged_with_the_real_error(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("UMBRA_STATE_DIR", str(tmp_path / "state"))
    with snapshots.Transaction(Runner(dry_run=False), "home") as tx:
        tx.writer.record("netdark.inbound_policy", "nftables_table_delete",
                         {"family": "inet", "table": "umbra"})

    def boom(*a, **k):
        raise RuntimeError("command failed (1): nft -f -\nError: Could not process rule")
    monkeypatch.setattr(snapshots, "apply_restore", boom)

    with caplog.at_level(logging.ERROR, logger="umbra.snapshots"):
        assert snapshots.restore_transaction(Runner(dry_run=False), tx.id) == \
            ["netdark.inbound_policy"]
    assert "netdark.inbound_policy" in caplog.text
    assert "Could not process rule" in caplog.text          # used to vanish
