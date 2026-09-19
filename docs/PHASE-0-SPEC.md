# Umbra — Phase 0 Specification

Status: **draft** · Date: 2026-09-18 · Target: Kali / Debian (systemd, NetworkManager, nftables)

This document defines the contracts everything else is built against: the
**profile schema**, the **module interface**, and the **snapshot/restore
contract**. Phase 0 ships no behavior — only the shapes that guarantee Umbra can
harden a machine *and put it back*.

---

## 1. Concepts

- **Control** — one atomic, reversible change to the system (e.g. "randomize the
  WiFi MAC", "DROP inbound by default"). A control is owned by exactly one module.
- **Module** — a cohesive group of controls for one layer (`rf`, `netdark`,
  `tunnel`, `telemetry`). Modules are idempotent and self-contained.
- **Profile** — a declarative posture: which controls are on/off and their
  parameters. The user picks a profile; the engine reconciles to it.
- **Posture** — the machine's *actual* current state, as measured by the audit
  subsystem. A profile is the intent; the posture is the reality. Green = they match.
- **Snapshot** — the captured prior state of a control, written before the
  control is applied, used to restore.

### Reconciliation model

```
target profile ─┐
                ├─► engine.reconcile() ─► for each control:
current posture ┘        measure() → if drift → snapshot() → apply() → verify()
```

The engine never blindly applies. It measures, acts only on drift, verifies the
result, and records enough to undo. `umbra normal` restores the machine to stock
by **replaying the active transaction's snapshots** (the reverse path), not by
applying an all-off profile — a disabled module measures and plans nothing, so it
cannot revert anything. Prior values live only in the snapshots, so undo is
restore, not reconcile. (The `normal` profile still exists as a status/plan
target.)

---

## 2. Profile schema

Profiles are YAML, validated against [`schema/profile.schema.json`](../schema/profile.schema.json).

```yaml
# profiles/travel.yaml
apiVersion: umbra/v1
kind: Profile
name: travel
description: Hostile-network mode — assume the LAN and ISP are adversarial.
extends: home          # optional: inherit + override another profile

# Global knobs available to all modules.
meta:
  fail_mode: closed     # closed | open  — on apply error, prefer safety (closed)
                        # or connectivity (open). Travel/paranoid = closed.
  require_confirm: false # if true, CLI must be run with --confirm

modules:
  rf:
    enabled: true
    mac_randomization: per-network   # off | per-network | per-boot | full
    suppress_probe_requests: true
    bluetooth: off                   # on | off | non-discoverable
    radios: [wifi]                   # radios permitted to remain powered; [] = all off

  netdark:
    enabled: true
    inbound_policy: drop             # drop | reject | allow
    discovery:                       # each: true = kill the broadcaster/responder
      mdns: true
      llmnr: true
      netbios: true
      ssdp_upnp: true
      wsd: true
    ipv6_privacy: true
    block_listening_services: true

  tunnel:
    enabled: true
    mode: wireguard                  # off | wireguard | tor
    profile_ref: wg-hub              # named tunnel config (never inline secrets)
    killswitch: true                 # drop all non-tunnel egress
    dns: tunnel                      # tunnel | doh | dot
    leak_guard: [dns, ipv6, webrtc]

  telemetry:
    enabled: true
    blocklists: [os, common-trackers]
    egress: allowlist                # off | blocklist | allowlist
    disable_os_telemetry: true
```

### Field rules

- `name` is unique and matches the filename stem.
- `extends` performs a deep merge (child overrides parent); cycles are rejected
  at load.
- Unknown top-level or module keys are a **hard error** (fail loud — a typo in a
  security posture must never silently no-op).
- Every module has `enabled`. `enabled: false` means "this module makes no
  changes and asserts nothing" — distinct from setting each control off (which
  actively enforces the off state).
- Secrets are **never** in a profile. `tunnel.profile_ref` names a config Umbra
  looks up elsewhere (e.g. an existing WireGuard peer).

### The four shipped profiles

| Profile | rf | netdark | tunnel | telemetry | fail_mode |
|---|---|---|---|---|---|
| `normal` | off | off | off | off | open |
| `home` | per-network MAC, BT non-disc. | drop, discovery off | off (or wg, no killswitch) | blocklist | open |
| `travel` | per-network MAC, BT off | drop, all discovery off | wireguard + killswitch | allowlist | closed |
| `paranoid` | full MAC or radios off | drop, all off, no services | tor **or** radios off | allowlist | closed |

---

## 3. Module interface

Every module implements one interface. Controls are enumerated so the engine can
reason about them individually.

```python
# umbra/modules/base.py  (contract — see file for the runnable stub)

class Module(Protocol):
    name: str                       # "rf" | "netdark" | "tunnel" | "telemetry"

    def controls(self) -> list[Control]: ...
        # Declare the controls this module owns.

    def measure(self) -> dict[str, ControlState]: ...
        # Read CURRENT system state per control. No mutation. Safe to call anytime.

    def plan(self, target: dict) -> list[Action]: ...
        # Diff measure() against the target profile fragment; return only the
        # actions needed to close the gap. Empty list = already compliant.

    def apply(self, action: Action, snap: SnapshotWriter) -> None: ...
        # 1. snap.record(action.control, current_state)  ← BEFORE any change
        # 2. perform the change
        # Must be idempotent and re-entrant.

    def verify(self, action: Action) -> VerifyResult: ...
        # Re-measure and confirm the change took. Feeds the audit.

    def restore(self, snap: SnapshotReader) -> None: ...
        # Reapply recorded prior state for every control this module snapshotted.
```

Rules:
- **`apply` must snapshot before it mutates.** No snapshot recorded ⇒ engine
  refuses to apply the control (fail closed).
- Modules never call each other. Ordering/coordination is the engine's job.
- Modules must tolerate partial prior state (a half-applied previous run).
- Every external command a module runs is captured behind a thin `run()` shim so
  it can be dry-run and logged.

### Apply ordering (engine-owned)

Chosen so the machine is never briefly *more* exposed than either the start or
end state:

```
apply:    telemetry → netdark → tunnel → rf
restore:  rf → tunnel → netdark → telemetry   (reverse)
```

Rationale: raise the firewall/telemetry walls before bringing the tunnel up, and
touch radios (which can drop connectivity) last. `tunnel` killswitch is armed
*before* the old route is torn down, never after.

---

## 4. Snapshot / restore contract

The core safety guarantee. **Umbra must be able to restore the machine to its
pre-Umbra state even if apply crashes halfway, the power drops, or a module
throws.**

### Guarantees

1. **Snapshot-before-mutate.** A control is captured before it is changed; the
   snapshot is `fsync`'d to disk before the mutation runs.
2. **Atomic transactions.** One `reconcile()` = one transaction with a unique id.
   All snapshots for that transaction live under one directory and are committed
   by an atomic rename of a `manifest.json`.
3. **Crash safety.** On startup, if a transaction is `in-progress` (manifest not
   committed), the engine offers/performs `restore` of the partial transaction
   before doing anything else.
4. **Layered restore.** Restore replays snapshots in reverse apply order.
5. **Full-state, not diff.** A snapshot stores the *complete prior value* of what
   it touches (e.g. the entire prior nftables ruleset, the NM connection's prior
   `cloned-mac-address`), not a computed reverse-delta. Restoring is "write the
   old value back", which is robust even if intermediate state is unexpected.
6. **Idempotent restore.** Restoring twice is a no-op.

### On-disk layout

```
engine/state/
  transactions/
    2026-09-18T14-03-11Z_ab12/          # transaction id = ISO time + rand
      manifest.json                      # committed LAST = transaction is durable
      status                             # in-progress | committed | restored
      rf/
        wifi_mac.snap                    # prior NM cloned-mac-address value + conn uuid
        bluetooth.snap                   # prior rfkill soft-block state
      netdark/
        nftables.snap                    # full `nft list ruleset` output
        avahi_service.snap               # prior systemd unit state (enabled/active)
      tunnel/ ...
      telemetry/ ...
  current -> transactions/<id>           # symlink to the active posture's tx
  restore.log
```

### Snapshot file shape

```json
{
  "control": "rf.wifi_mac",
  "module": "rf",
  "captured_at": "2026-09-18T14:03:11Z",
  "restore": {
    "method": "nmcli_set",
    "target": "connection.uuid=…",
    "key": "802-11-wireless.cloned-mac-address",
    "prior_value": "preserve",
    "was_absent": false
  }
}
```

`restore.method` names a small, audited set of restore primitives
(`nftables_replace`, `nmcli_set`, `rfkill_set`, `systemd_unit`, `sysctl_set`,
`file_replace`, `hosts_replace`). No snapshot ever restores by running an
arbitrary shell string — restore is data, not code.

### Failure semantics

| Situation | Behavior |
|---|---|
| Module `apply` throws | Stop the transaction; if `fail_mode: closed`, leave applied controls in place (safe); if `open`, auto-restore the transaction. Always report. |
| Power loss mid-apply | On next start, `status=in-progress` ⇒ prompt/auto restore. |
| Snapshot write fails | Abort that control before mutating; never mutate un-snapshotted state. |
| Restore primitive fails | Log, continue remaining controls (best-effort full restore), exit non-zero, list what did not restore. |

---

## 5. CLI surface (Phase 1 target, defined now)

```
umbra status                 # current posture vs. active profile, green/red per control
umbra apply <profile>        # reconcile to a profile  (alias: umbra <profile>)
umbra normal                 # restore to stock (replay the active tx's snapshots)
umbra restore [--tx <id>]    # explicit restore of a transaction (default: current)
umbra audit                  # run leak tests + posture scan (read-only)
umbra plan <profile>         # dry-run: print the actions without applying
umbra diff <profile>         # show profile-vs-posture drift
```

Global flags: `--dry-run`, `--confirm`, `--json`, `--verbose`, `--fail-mode`.

Every mutating command:
- refuses without root (or a defined polkit action later),
- prints the plan and, for `closed` profiles or `require_confirm`, waits for
  `--confirm`,
- writes a transaction, and prints the tx id for later `restore`.

---

## 6. Explicit non-goals for Phase 0

- No system changes of any kind (spec + scaffold only).
- No GUI (Phase 3; will pass through the `ada-compliance` filter).
- No phone support (later; a phone build is an *auditor/advisor*, honest about
  the sandbox — it cannot silence radios the way desktop can).
- No cryptographic attestation of posture (a later hardening item).

## 7. Open questions to resolve entering Phase 1

1. Engine language: **Python** (fast to build, matches reconlens/homevpn) vs.
   **Rust** (hardened daemon). Leaning Python for the engine now, Rust for a
   privileged helper later.
2. Privilege model: run-as-root CLI first; polkit action + unprivileged client
   later.
3. Tunnel reuse: bind `tunnel.profile_ref: wg-hub` directly to the existing
   `homevpn` WireGuard peer config, or wrap it.
4. Blocklist source: ship curated lists vs. reuse the Pi-hole lists already on
   `wg-hub`.
