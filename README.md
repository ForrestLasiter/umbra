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

> **Standalone by design.** Umbra is a go-anywhere tool for a single device: you
> operate the laptop from anywhere and harden/anonymize it with **no dependency on
> and no connection back to any home network**. The tunnel is any endpoint *you*
> supply (a commercial VPN, a VPS you control) or Tor — never a home server, since
> phoning home would tie the device's traffic back to your identity.

> **Linux is the reference implementation.** The engine, profiles, and audit are
> the product; the CLI is the primary interface. A phone app is the eventual goal,
> with this Linux build as the setup and proving ground for the posture model. The
> mobile boundary is explicit: anything that needs root nftables, NetworkManager,
> or systemd here maps to the platform-native equivalent there, not a straight port.

## Status

**Working on Kali / Debian**, validated on a real Kali VM through Phase 15 plus a
full security/reliability hardening pass. The reconciler, all posture modules, the
crash-safe transaction store, the profile-aware audit, Tor transparent-proxy
routing, polkit elevation, the system tray, the boot service, and the `.deb` /
wheel packaging are all in place and tested. Architected to port to other
platforms later; radios-off honesty is a design rule, not a TODO.

## What it does (by layer)

| Layer | Controls |
|---|---|
| **RF signature** | Per-network MAC randomization, probe-request suppression, Bluetooth off, radio kill (rfkill) |
| **Local network dark** | `nftables` default-deny **DROP**, kill mDNS/LLMNR/NetBIOS/SSDP/WSD discovery, IPv6 privacy addresses, open-port audit |
| **Internet / ISP** | WireGuard or **Tor transparent proxy** routing, egress **killswitch**, encrypted DNS, IPv6/DNS leak prevention |
| **Telemetry** | Telemetry-domain sinkhole (hosts blocklist), disable OS/app phone-home services |
| **OS hardening** | Kernel hardening sysctls, webcam disable, DHCP hostname suppression |

Every control is *measured* before and *verified* after — the audit reports what
is actually true on the wire, not what a profile claims.

## Posture profiles

Declarative YAML. The engine diffs current state against the target and applies
only what differs; every change is snapshotted first so it reverts cleanly. Each
profile declares the capabilities it **requires**, and the audit only scores
against those — a profile can't report 100/100 while a required control is
unverified.

- `normal` — restore to stock
- `home` — sane hardening, usable on a trusted LAN (firewall, IPv6 privacy, discovery off, telemetry sinkhole, kernel hardening, hostname + MAC randomization; Bluetooth stays on)
- `travel` — hostile-network mode (home **+** Bluetooth off **+** WireGuard tunnel & killswitch)
- `paranoid` — go dark (travel **+** Tor transparent proxy **+** webcam off)

Profiles compose with `extends`, so `travel` and `paranoid` build on `home`
rather than repeating it.

## Commands

`umbra <command>` — read-only commands need no privilege; mutating ones elevate
via `sudo` or `--pkexec` (a desktop auth dialog).

| Command | What it does |
|---|---|
| `umbra list` | list available profiles |
| `umbra status [profile]` | measured posture vs a profile (default `home`); prints the compact banner |
| `umbra plan <profile>` | show the exact actions `apply` would take — no mutation |
| `umbra apply <profile>` | reconcile the machine to a profile (one crash-safe transaction) |
| `umbra normal` | restore to stock (undo the active posture) |
| `umbra restore [--tx ID]` | restore a specific transaction (default: the current one) |
| `umbra audit [profile] [--html PATH]` | read-only **proof** of posture; optional accessible HTML dashboard |
| `umbra dashboard [profile] [--port N]` | serve a live posture dashboard on `localhost` (default `:8799`) |
| `umbra doctor [profile]` | check this machine has what a profile needs (nftables, tor, wireguard, …) |
| `umbra panic` | go dark **now** — slam straight to the `paranoid` posture |
| `umbra vpn <config> [--name NAME]` | import a WireGuard `.conf` for `tunnel(wireguard)` |
| `umbra tray` | run the system-tray posture toggle (desktop) |
| `umbra capabilities [--platform P] [--profile]` | what a platform (`linux`/`android`/`ios`) can honestly enforce |
| `umbra export-spec [--out DIR]` | write the language-neutral core spec for the mobile adapters |
| `umbra conky [profile] [--field N] [--plain]` | emit posture as Conky-friendly text for a desktop widget |

**Global flags:** `--dry-run` (show mutations without doing them), `--json`
(machine-readable output where supported), `--confirm` (acknowledge a
`fail-mode=closed` apply), `--pkexec` (elevate through polkit), `--profiles-dir`
(override — refused on the pkexec path), `--verbose`, `--version`.

### Applying, undoing, and crash safety

```bash
umbra doctor travel          # is this machine ready?  (exit 1 if not)
umbra plan travel            # what would change?
sudo umbra apply travel      # do it — snapshots every change first
umbra audit travel           # prove it: green/red per control, scored
umbra normal                 # put everything back
```

Every `apply` is one transaction with a snapshot taken **before** each mutation.
If a run crashes mid-apply, the next invocation detects the incomplete
transaction and restores it before doing anything else. `open` profiles favour
connectivity (a failure rolls the whole transaction back); `closed` profiles
favour safety (the walls stay up, the transaction is marked failed, and `current`
points at it so `umbra normal` / `umbra restore` can undo it). A posture that
didn't verify is **never** recorded as active.

### Tor transparent proxy (`paranoid`)

`paranoid` routes all TCP through Tor via an nftables NAT redirect to `TransPort
9040`, with DNS forced to Tor's `DNSPort 9053` (9053, not 5353 — that collides
with mDNS) and a killswitch that drops anything that would bypass the tunnel.
It drives `tor@default.service` (the real Debian unit, not the `tor.service`
no-op wrapper) and forces a config reload so a Tor that was already running still
picks up the transparent-proxy settings. `umbra audit paranoid` confirms
`IsTor: true` end to end.

### VPN import

Bring your own endpoint — a commercial VPN or a VPS you control:

```bash
sudo umbra vpn ~/Downloads/mullvad-us.conf --name vpn
sudo umbra apply travel        # travel/paranoid reference profile_ref "vpn"
```

The config is written to `/etc/wireguard/<name>.conf` at mode `0600`. Names are
validated (no path traversal); `travel` and `paranoid` reference it by
`profile_ref`, never a home server.

## Elevation, tray, and boot

- **polkit** — install registers action `com.forrestlasiter.umbra.run`
  (`exec.path=/usr/bin/umbra`), so `umbra --pkexec apply travel` pops a desktop
  auth dialog instead of needing a root shell. The elevated process constrains
  itself to a safe set of built-in commands, refuses an attacker-chosen
  `--profiles-dir`, and refuses `audit --html` (arbitrary root-owned write).
- **system tray** — `umbra tray` gives a desktop toggle between postures over the
  same engine the CLI uses.
- **boot service** — `install.sh --with-boot-service` installs a `oneshot` systemd
  unit that applies your chosen boot profile at every boot and reverts to `normal`
  on stop.
- **NetworkManager dispatcher** — re-asserts the active posture (MAC, hostname
  suppression, firewall, killswitch) when a link comes up as you move between
  networks. It's `flock`-serialized (no concurrent transactions), debounced (15s,
  so an apply that nudges NetworkManager can't loop), and logs every reapply,
  success or failure.

## Design non-negotiables

1. **Reversibility first** — every module snapshots prior state before touching
   anything (mode, owner, group, and symlink metadata preserved; writes are
   atomic: temp file + `fsync` + `os.replace`); a crash mid-apply must still
   restore, and a `--dry-run` restore mutates nothing.
2. **Idempotent modules** — re-applying a profile is a no-op.
3. **Audit proves it** — a profile-aware posture scanner + live leak probes
   (listening ports, default route, DNS resolvers) show green/red per control;
   you see it, you don't trust a claim.
4. **CLI before GUI** — the engine and `umbra` CLI are the product; any UI (tray,
   dashboard, future mobile app) is a thin client over them.

## Layout

```
umbra/
  docs/            specs + per-phase writeups (start here)
  packaging/       polkit policy, systemd unit, NM dispatcher, .deb builder
  spec/            umbra-core.json (+ schema) — the language-neutral contract
  scripts/         sync-spec.sh (fan the core spec out to the adapters)
  android/         umbra-android — VPNService adapter (Kotlin, scaffold)
  ios/             umbra-ios — Network Extension adapter (Swift, scaffold)
  umbra/           the Python package (installable, entrypoint `umbra`)
    # --- core (platform-agnostic; provably no Linux imports, see tests/test_boundary.py) ---
    model.py       posture model types (Compliance, Control, Action, ...)
    profiles.py    load + validate + merge posture YAML
    profiles/      posture definitions (YAML, shipped as package data)
    schema/        JSON Schema for profiles (shipped as package data)
    capabilities.py  maps profile "requires" tokens -> the controls that satisfy them
    platform.py    the honest per-platform enforcement matrix
    auditmodel.py  the audit data model (Status/Check/AuditReport)
    report.py      the accessible HTML dashboard renderer
    spec.py        export the language-neutral core (umbra export-spec)
    # --- Linux agent (measures + mutates the machine) ---
    engine.py      the reconciler (measure→plan→apply→verify→restore)
    snapshots.py   crash-safe transactions
    restore.py     the audited restore primitives
    fsutil.py      snapshot / atomic-write / restore-path helpers
    runner.py      the one shim all external commands go through (timeouts, clean env)
    audit.py       the Linux posture probes (fills in the audit model)
    lock.py        flock apply-lock (one transaction at a time)
    modules/       kernel, telemetry, netdark, tunnel, rf, identity (idempotent)
    cli.py         `umbra` entrypoint
  tests/           unit tests (run on any OS)
```

## Install

**System (Kali/Debian):**

```bash
sudo ./install.sh                       # umbra on your PATH (uses apt for deps)
sudo ./install.sh --with-boot-service   # + apply a posture at every boot
sudo ./uninstall.sh                     # restores posture, then removes
```

**Debian package:**

```bash
packaging/build-deb.sh                  # builds umbra_<version>_all.deb
sudo apt install ./umbra_*.deb          # deps + wrapper + polkit; prerm restores posture
```

**Dev:**

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
umbra --help
pytest -q
```

## Desktop widget (Conky)

Umbra's audit is read-only and scored, which makes it a natural Conky panel:

```bash
cp contrib/umbra.conkyrc ~/.config/conky/umbra.conkyrc
conky -c ~/.config/conky/umbra.conkyrc
```

`umbra conky` prints the active posture, the audit score, and a tick/cross per
required capability as Conky-markup text — poll it with `${execpi 15 umbra
conky}`. For a hand-built layout, `umbra conky --field score` (or `active` /
`fail` / `tor` / …) prints one value for `${execi}`, and `--plain` drops the
colour markup. It needs no root (the audit degrades to N/A without it).

## Platform boundary (toward the phone app)

Linux is the reference *because* it can enforce everything; a phone can't, and
Umbra won't pretend otherwise. The core is platform-agnostic (profiles, the
posture model, capabilities, audit/scoring) and declares, per capability, the
strongest promise each platform can honestly make — six distinct levels:
`enforced`, `requires_entitlement`, `requires_vpn_profile`, `requires_rooted_os`,
`advisory`, `unavailable`.

```bash
umbra capabilities --platform android --profile travel   # what THIS device can keep
umbra export-spec                                         # spec/umbra-core.json for Kotlin/Swift
```

`spec/umbra-core.json` is the language-neutral contract the Android (VPNService)
and iOS (Network Extension) adapters consume, so all three platforms speak one
posture language. See [`docs/phases/PHASE-16.md`](docs/phases/PHASE-16.md) for the
full boundary and the enforcement matrix.

### Mobile apps (in progress)

Thin front-ends over the same core, each enforcing what its OS honestly can:

- [`android/`](android/) — Kotlin/VPNService. **DNS telemetry sinkhole** (no root,
  same blocklist as Linux), **WireGuard** (libwg-go), and **Tor via Orbot**;
  advisory rows deep-link to the OS setting; live blocked/forwarded counters.
- [`ios/`](ios/) — Swift/Network Extension. DNS sinkhole ported (shared datapath),
  WireGuard config import ported; the tunnel plumbing is WireGuardKit/next.

Every line of both apps **compiles in CI**: Android via `gradle
:app:testDebugUnitTest` (whole app + unit tests), iOS via `swift test` (the core)
and `xcodebuild` (the full app + Packet Tunnel extension). The no-root **DNS
sinkhole** is one algorithm ported to Kotlin and Swift, and **golden vectors
enforce byte-exact parity** with the Python reference across all three. Only the
live native runtime (VpnService `establish`, libwg-go handshake, Orbot launch, the
iOS Packet Tunnel) is **device-test pending** — it needs a real device, and the
apps say so rather than claiming what isn't verified. See
[`docs/phases/PHASE-17.md`](docs/phases/PHASE-17.md).

## Documentation

- [`docs/PHASE-0-SPEC.md`](docs/PHASE-0-SPEC.md) — the full specification and
  contracts every module implements.
- [`docs/phases/`](docs/phases/) — per-phase writeups with diagrams.
- [`docs/DEVELOPING.md`](docs/DEVELOPING.md) — how the pieces fit and how to work
  on them.
