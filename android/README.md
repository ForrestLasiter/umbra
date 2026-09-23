# Umbra for Android

The Android adapter from the Umbra platform boundary
([`docs/phases/PHASE-16.md`](../docs/phases/PHASE-16.md)). It is a **thin
front-end over the platform-agnostic core**: it reads the same
[`spec/umbra-core.json`](../spec/umbra-core.json) the Linux build emits, and
enforces what an unrooted phone honestly can — never pretending to match the
Linux reference.

> Status: **DNS telemetry sinkhole implemented** (the first real no-root
> enforcement); WireGuard and Tor are still `TODO` seams. The architecture, the
> honest capability model, the VPN lifecycle, the spec-driven UI, and the DNS
> datapath (IPv4/UDP/DNS parsing + blocklist) are unit-tested.

## What the phone can enforce (and what it can't)

Android's one real lever without root is **VPNService**. The app maps each
capability a profile requires to its honest level from the core matrix:

| Capability | Android | How the app treats it |
|---|---|---|
| telemetry sinkhole | `requires_vpn_profile` | **enforced** — DNS-only tunnel drops telemetry lookups (0.0.0.0), forwards the rest |
| wireguard | `requires_entitlement` | enforced after the one-time VPN-consent grant |
| tor | `requires_vpn_profile` | routed through a Tor packet tunnel |
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
    vpn/       UmbraVpnService.kt                             (DNS-only tunnel + sinkhole)
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
2. **WireGuard** — integrate `wireguard-android`'s Go backend; switch to full
   capture and forward through it (mirrors `umbra vpn` on Linux).
3. **Tor** — route the tunnel through Orbot / arti for the `paranoid` posture.
4. **Advisory deep-links** — wire each `advisory` capability to its OS settings
   screen (Wi-Fi MAC, Bluetooth, private DNS).
5. **Live counters** — surface DnsSinkhole's blocked/forwarded counts in the UI.
