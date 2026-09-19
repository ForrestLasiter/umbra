# Umbra

**A one-toggle privacy, anonymity, and hardening posture engine for Linux.**
Pick a posture; Umbra reconciles the whole machine to it — and can put it back
exactly the way it was.

> **Honest scope.** Umbra does not make a device *invisible*. A powered radio is
> detectable, full stop. Umbra minimizes attack surface and observable signature
> on demand: MAC/RF signature, local-network discovery, ISP-level traffic, and
> OS/app telemetry — wired together, reversible, and *provably* on via a built-in
> audit. True invisibility = radios off, and Umbra says so in plain language
> rather than pretending otherwise.

## Status

Phase 0 — specification and scaffold. Nothing here changes system state yet.
Target platform: **Kali / Debian first**, architected to port later.

## What it does (by layer)

| Layer | Controls |
|---|---|
| **RF signature** | Per-network MAC randomization, probe-request suppression, Bluetooth off/non-discoverable, radio kill |
| **Local network dark** | `nftables` default-deny **DROP**, kill mDNS/LLMNR/NetBIOS/SSDP/WSD, IPv6 privacy, open-port audit |
| **Internet / ISP** | WireGuard or Tor routing, egress **killswitch**, encrypted DNS, leak prevention |
| **Telemetry** | Telemetry-domain blocklist, disable OS/app phone-home, egress allowlist |

## Posture profiles

Declarative YAML. The engine diffs current state against the target and applies
only what differs; every change is snapshotted first so it reverts cleanly.

- `normal` — restore to stock
- `home` — sane hardening, usable on a trusted LAN
- `travel` — hostile-network mode
- `paranoid` — go dark

## Design non-negotiables

1. **Reversibility first** — every module snapshots prior state before touching
   anything; a crash mid-apply must still restore.
2. **Idempotent modules** — re-applying a profile is a no-op.
3. **Audit proves it** — a posture scanner + leak tests show green/red per
   control; you see it, you don't trust a claim.
4. **CLI before GUI** — the engine and `umbra` CLI are the product; any UI is a
   thin client over them.

See [`docs/PHASE-0-SPEC.md`](docs/PHASE-0-SPEC.md) for the full specification.

## Layout

```
umbra/
  docs/            specs (start here)
  profiles/        posture definitions (YAML)
  schema/          JSON Schema for profiles + state snapshots
  umbra/           the Python package (installable, entrypoint `umbra`)
    engine.py      the reconciler
    profiles.py    load + validate + merge posture YAML
    snapshots.py   crash-safe transactions
    restore.py     the audited restore primitives
    runner.py      the one shim all external commands go through
    modules/       rf, netdark, tunnel, telemetry (idempotent)
    cli.py         `umbra` entrypoint
  engine/state/    runtime snapshots for clean revert (git-ignored)
  tests/           unit tests (run on any OS)
```

## Install (dev)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
umbra --help
```
