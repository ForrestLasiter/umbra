# OS integration: the packet-filter service

Two of Umbra's capabilities, `firewall` and `discovery`, are packet-filter rules.
On Android only root can write those, so an OS build that wants them ships the
small service in this directory. Everything else in the `android_system`
platform works without it.

## The contract

The app and the service talk through three system properties:

| Property | Written by | Meaning |
|---|---|---|
| `persist.umbra.net.inbound_drop` | app | `1` = default-deny inbound |
| `persist.umbra.net.discovery_drop` | app | `1` = drop outbound discovery packets |
| `umbra.net.applied` | service | what is in place now, e.g. `inbound=1 discovery=0`, or `error` |

Writing a `persist.*` property is only a request. The app reports a capability as
enforced only after it reads the matching value back from `umbra.net.applied`.
With no service there is no status, the controls report themselves unavailable,
and the app shows them that way.

The requests are `persist.*` properties, so a posture survives a reboot: init
loads them before `netd` starts, and the service runs as soon as `netd`'s chains
exist.

## What the rules are

`netd` owns the filter table but leaves empty chains for the OS builder,
`oem_in` and `oem_out`. The service adds one jump from each into its own chains
and only ever flushes those.

**`umbra_in` (when inbound_drop=1)** accepts, in order: loopback; replies to
connections the phone opened; DNS and DHCP (so a hotspot still serves its
clients); and, on IPv6, neighbour discovery, multicast listener reports and
DHCPv6. Everything else unsolicited is dropped silently, including ping.

**`umbra_out` (when discovery_drop=1)** drops outbound UDP to ports 5353 (mDNS),
5355 (LLMNR), 1900 (SSDP/UPnP), 137-138 (NetBIOS) and 3702 (WS-Discovery).

Consequences worth knowing: wireless ADB and anything else that listens on the
phone stops being reachable while the firewall is on, and casting or printer
discovery stops while discovery is dropped. Both are the point.

## Adding it to an OS build

`android/Android.bp` already defines the `umbra-net` module and makes the `Umbra`
app require it, so it is installed with the app. The one thing an Android.bp
cannot do is add SELinux policy. Add this directory's policy to the board or
product configuration:

```make
SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += packages/apps/Umbra/android/os-integration/sepolicy/private
```

(adjust the path to wherever this repository is checked out).

The policy gives the service its own domain, `umbra_net`, with exactly what the
script needs: run a shell script, run `iptables`, hold `NET_ADMIN`/`NET_RAW`,
and read/write its properties. It also lets `platform_app`, the domain a
platform-signed app runs in, write the two request properties and read the status.

## Files

| File | Purpose |
|---|---|
| `umbra-net.sh` | The service: reads the requests, writes the rules, reports the result |
| `umbra-net.rc` | When init starts it: on `netd` start and whenever a request changes |
| `sepolicy/private/` | The SELinux domain, property types and labels |
