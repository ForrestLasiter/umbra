# Umbra for iOS

The iOS adapter from the Umbra platform boundary
([`docs/phases/PHASE-16.md`](../docs/phases/PHASE-16.md)). Like Android, it is a
**thin front-end over the platform-agnostic core**: it reads the same
[`spec/umbra-core.json`](../spec/umbra-core.json) and enforces only what a stock
iPhone honestly can — which, on iOS, is the least of the three platforms.

> Status: **DNS telemetry sinkhole implemented** (ported from the Android
> datapath, sharing the same algorithm). The core (a Swift Package with tests),
> the honest capability model, the SwiftUI front-end, and the Packet Tunnel
> provider are in place. WireGuard/Tor forwarding is still `TODO`. The tunnel
> plumbing is **device-test pending** (needs an iOS runtime); the datapath logic
> it drives is unit-tested and Python-mirror verified.

## What the phone can enforce (and what it can't)

iOS gives no app-level firewall and no kernel access. Its one lever is the
**Network Extension** (a Packet Tunnel / DNS proxy), behind an Apple-granted
entitlement:

| Capability | iOS | How the app treats it |
|---|---|---|
| telemetry sinkhole | `requires_entitlement` | **implemented** — DNS-only Packet Tunnel drops telemetry lookups (0.0.0.0), forwards the rest |
| wireguard / tor | `requires_entitlement` / `requires_vpn_profile` | Packet Tunnel Provider |
| firewall / kernel / webcam | `unavailable` | shown plainly as not possible |
| mac / hostname / ipv6 / bluetooth | `advisory` | iOS already does these; app verifies + deep-links |

Every row renders as text (`enforced` / `on grant` / `via tunnel` / `advisory` /
`unavailable`) — **never a fake "on"**.

## Layout

```
ios/
  UmbraCore/                     Swift Package — pure logic, `swift test`-able
    Sources/UmbraCore/           Spec.swift, PostureEngine.swift
    Sources/UmbraCore/Net/       InternetChecksum, IPv4Packet, DnsMessage, TelemetryBlocklist
    Tests/UmbraCoreTests/        PostureEngineTests.swift, NetTests.swift
  Umbra/
    App/                         UmbraApp.swift, ContentView.swift, Umbra.entitlements
    PacketTunnel/                PacketTunnelProvider.swift, UDPForwarder.swift (+ entitlements)
    Resources/umbra-core.json    copy of the core contract (bundled)
  project.yml                    XcodeGen spec (the .xcodeproj is generated, not committed)
```

## Build

Requires macOS + Xcode (the app/extension use UIKit/Network Extension). The pure
core compiles anywhere Swift does.

```bash
# Core logic + tests (no Xcode needed):
cd ios/UmbraCore && swift test

# Full app: generate the Xcode project, then open it.
cd ios && brew install xcodegen && xcodegen generate && open Umbra.xcodeproj
```

Shipping the tunnel to a device needs the **Network Extension** capability on your
Apple Developer account and the app group `group.com.forrestlasiter.umbra`.

## Keeping the spec in sync

`Umbra/Resources/umbra-core.json` is a verbatim copy of the core spec. After
changing profiles/capabilities/matrix, run from the repo root:

```bash
scripts/sync-spec.sh
```

## Next steps (the datapath)

1. ~~**DNS sinkhole**~~ — **done** (device-test pending). In-tunnel DNS filter
   sharing the Android datapath's algorithm.
2. **WireGuard** — `NEPacketTunnelProvider` + WireGuardKit for the `travel` tunnel
   (config import mirrors the Android `wg/` layer).
3. **Tor** — route the packet tunnel through Tor (Tor.framework) for `paranoid`.
4. **Advisory deep-links** — link each `advisory` row to the matching iOS Settings
   URL (Wi-Fi, Bluetooth, Private DNS).
