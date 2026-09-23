# Umbra for Android

The Android adapter from the Umbra platform boundary
([`docs/phases/PHASE-16.md`](../docs/phases/PHASE-16.md)). It is a **thin
front-end over the platform-agnostic core**: it reads the same
[`spec/umbra-core.json`](../spec/umbra-core.json) the Linux build emits, and
enforces what an unrooted phone honestly can — never pretending to match the
Linux reference.

> Status: **DNS telemetry sinkhole + WireGuard tunnel implemented**; Tor is still
> a `TODO` seam. The honest capability model, the VPN lifecycle, the spec-driven
> UI, the DNS datapath, and the WireGuard config import are unit-tested. The
> WireGuard tunnel bring-up (native libwg-go) is written against the library's
> public API and is **device-test pending** — it can't run on the build host.

## What the phone can enforce (and what it can't)

Android's one real lever without root is **VPNService**. The app maps each
capability a profile requires to its honest level from the core matrix:

| Capability | Android | How the app treats it |
|---|---|---|
| telemetry sinkhole | `requires_vpn_profile` | **enforced** — DNS-only tunnel drops telemetry lookups (0.0.0.0), forwards the rest |
| wireguard | `requires_entitlement` | **enforced** — import a `.conf`, one-time VPN consent, then libwg-go tunnels all traffic |
| tor | `requires_vpn_profile` | **via Orbot** — Umbra detects/launches it; Orbot's VPN mode carries all traffic over Tor |
| firewall / kernel | `requires_rooted_os` | **not** enforced — shown as "needs root" |
| mac / hostname / ipv6 / bluetooth | `advisory` | the OS owns these; the app verifies and links to the setting |

The UI renders every capability with a text badge (`enforced` / `via tunnel` /
`on consent` / `needs root` / `advisory` / `unavailable`) — **never a fake "on"**.

## Layout

```
android/
  app/src/main/java/com/forrestlasiter/umbra/
    core/      Spec.kt, PostureEngine.kt, SpecRepository.kt   (pure, reads the core spec)
    net/       InternetChecksum, Ipv4Packet, UdpDatagram     (packet parse/build)
      dns/     DnsMessage, TelemetryBlocklist, DnsSinkhole    (the DNS datapath)
    wg/        WgConfig, WgConfigStore, WireGuardBackend      (WireGuard: import + tunnel)
    tor/       OrbotHelper                                    (Tor via Orbot)
    vpn/       UmbraVpnService, TunnelController, TunnelMode   (sinkhole svc + datapath select)
    ui/        MainActivity.kt, PostureViewModel.kt           (Compose front-end)
  app/src/main/assets/umbra-core.json                        (copy of the core contract)
  app/src/test/...  PostureEngineTest, DnsMessageTest,        (pure-JVM tests)
                    TelemetryBlocklistTest, Ipv4UdpTest
```

## How the DNS sinkhole works

VPNService captures traffic by IP route, not by port — so instead of grabbing all
traffic (which would need a full userspace network stack), Umbra routes **only its
own DNS server** (`10.111.0.1/32`) into the tunnel and sets it as the system
resolver. Every DNS lookup then arrives as an IP packet on the `tun` fd:

- **blocked domain** → answered locally with `0.0.0.0` (A) / `::` (AAAA), exactly
  like the Linux `/etc/hosts` sinkhole;
- **anything else** → forwarded to a real upstream over a `protect()`ed socket
  (which bypasses the VPN) and relayed back.

All other traffic (web, apps) never enters the tunnel — this is a DNS filter, not
a full VPN.

**Honest limits** (the same ceiling the Linux hosts file has): it catches
plaintext DNS via the system resolver. Apps using DNS-over-HTTPS/TLS or a
hardcoded resolver IP bypass it. The domain lists come from the shared core spec
(`telemetry_blocklists`), so the phone and the laptop block the same set.

## WireGuard (the tunnel postures)

`travel` and `paranoid` route **all** traffic through a WireGuard tunnel to an
endpoint you supply — the phone's equivalent of `umbra vpn` + `wg-quick` on Linux.

- **Import** a `.conf` in the app (a commercial VPN or a VPS you control — never a
  home server). `WgConfig` validates it and `WgConfigStore` keeps it app-private
  (the phone's `/etc/wireguard/vpn.conf`).
- On activate, `TunnelController` sees the posture needs `wireguard` and brings up
  `WireGuardBackend`, which hands the config to the official **libwg-go** backend
  (`com.wireguard.android:tunnel`). One VPN consent covers this and the sinkhole.

`TunnelController` picks the datapath per posture (`TunnelMode`, pure + tested):
**Tor** > **WireGuard** > **DNS sinkhole** > nothing. So `paranoid` (which needs
both tor and wireguard) routes through Tor — going dark.

## Tor (the paranoid posture)

Tor on an unrooted phone is provided by **Orbot** (Guardian Project). Umbra
doesn't re-implement Tor — it detects Orbot, sends you to install it if missing,
and requests it to start; Orbot's VPN mode then carries all traffic over Tor.
That's the honest no-root way to route everything through Tor (a self-contained
tun2socks→Orbot SOCKS `127.0.0.1:9050` path is a future option).

**Honest notes:** the WireGuard bring-up is native (libwg-go) and **device-test
pending** — it's written to the library's public API but can't run on the build
host; the config import/validation is unit-tested. In WireGuard mode all DNS goes
through the tunnel endpoint (telemetry is handled there, not by the local
sinkhole); running the sinkhole *over* WireGuard is a future refinement.

## Build

Needs Android Studio (Koala+) or a command-line Android SDK with JDK 17.

```bash
cd android
./gradlew :app:testDebugUnitTest     # run the pure-JVM core tests
./gradlew :app:assembleDebug         # build the APK
```

(The Gradle wrapper jar is not committed; run `gradle wrapper` once, or open the
project in Android Studio which provisions it.)

## Keeping the spec in sync

The bundled `assets/umbra-core.json` is a verbatim copy of the repo's core spec.
After changing profiles, capabilities, or the platform matrix, refresh every
adapter from the Python core:

```bash
scripts/sync-spec.sh
```

## Next steps (the datapath)

1. ~~**DNS sinkhole**~~ — **done.** Telemetry lookups are dropped in the tun loop.
2. ~~**WireGuard**~~ — **done** (device-test pending). Config import + libwg-go tunnel.
3. ~~**Tor**~~ — **done.** Orbot detection/launch for `paranoid` (device-test pending).
4. ~~**Advisory deep-links**~~ — **done.** Advisory rows open the matching OS setting.
5. ~~**Live counters**~~ — **done.** The UI shows blocked/forwarded while the sinkhole runs.
6. **Sinkhole over WireGuard** — run the telemetry filter in front of the tunnel so
   tunnel postures also block by the shared list (not just the endpoint's DNS).
