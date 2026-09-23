# Umbra for Android

The Android adapter from the Umbra platform boundary
([`docs/phases/PHASE-16.md`](../docs/phases/PHASE-16.md)). It is a **thin
front-end over the platform-agnostic core**: it reads the same
[`spec/umbra-core.json`](../spec/umbra-core.json) the Linux build emits, and
enforces what an unrooted phone honestly can — never pretending to match the
Linux reference.

> Status: **scaffold.** The architecture, the honest capability model, the VPN
> lifecycle, and the spec-driven UI are in place and unit-tested. The packet
> datapath (DNS sinkhole, WireGuard, Tor) is stubbed at clearly marked `TODO`
> seams — that's the next implementation step.

## What the phone can enforce (and what it can't)

Android's one real lever without root is **VPNService**. The app maps each
capability a profile requires to its honest level from the core matrix:

| Capability | Android | How the app treats it |
|---|---|---|
| telemetry sinkhole | `requires_vpn_profile` | enforced by dropping telemetry DNS inside the tunnel |
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
    vpn/       UmbraVpnService.kt                             (the enforcement tunnel)
    ui/        MainActivity.kt, PostureViewModel.kt           (Compose front-end)
  app/src/main/assets/umbra-core.json                        (copy of the core contract)
  app/src/test/...  PostureEngineTest.kt                     (pure-JVM honesty tests)
```

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

1. **DNS sinkhole** — parse DNS in the tun loop, answer telemetry domains with
   NXDOMAIN (delivers `telemetry` on Android without root).
2. **WireGuard** — integrate `wireguard-android`'s Go backend; feed it the
   imported profile (mirrors `umbra vpn` on Linux).
3. **Tor** — route the tunnel through Orbot / arti for the `paranoid` posture.
4. **Advisory deep-links** — wire each `advisory` capability to its OS settings
   screen (Wi-Fi MAC, Bluetooth, private DNS).
