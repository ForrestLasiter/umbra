# OS integration

Three of Umbra's capabilities need something from the OS that no app can do for
itself. `firewall` and `discovery` are packet-filter rules, which only root can
write, so the OS ships the small service in this directory. `telemetry` needs
the resolver to read a blocklist; see "The telemetry sinkhole" below. Everything
else in the `android_system` platform works without any of this.

## The packet-filter service

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
`oem_in` and `oem_out`. The service adds one jump from each into its own chains,
`oem_umbra_in` and `oem_umbra_out`, and only ever flushes those.

**`oem_umbra_in` (when inbound_drop=1)** accepts, in order: loopback; replies to
connections the phone opened; DNS and DHCP (so a hotspot still serves its
clients); and, on IPv6, neighbour discovery, multicast listener reports and
DHCPv6. Everything else unsolicited is dropped silently, including ping.

**`oem_umbra_out` (when discovery_drop=1)** drops outbound UDP to ports 5353 (mDNS),
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
UMBRA_SEPOLICY := packages/apps/Umbra/android/os-integration/sepolicy
SYSTEM_EXT_PUBLIC_SEPOLICY_DIRS  += $(UMBRA_SEPOLICY)/public
SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += $(UMBRA_SEPOLICY)/private
BOARD_VENDOR_SEPOLICY_DIRS       += $(UMBRA_SEPOLICY)/vendor
```

(adjust the path to wherever this repository is checked out).

| Directory | What it adds |
|---|---|
| `public/` | The two property types, visible to both system and vendor policy |
| `private/` | Property labels, and permission for `platform_app` (the domain a platform-signed app runs in) to write the requests and read the status |
| `vendor/` | The service's own domain, `umbra_net` |

### Why the service is vendor code

On Android, changing any rule rewrites the whole filter table, including
`netd`'s own rules that reference kernel BPF programs. Stock SELinux policy lets
exactly two things do that: `netd`, and `netutils-wrapper`, the door Android
leaves open for OS builders. The wrapper only takes commands from vendor
domains, and only for chains named `oem_*`.

So `umbra-net` is a vendor service that calls
`/system/bin/ip[6]tables-wrapper-1.0`. Its domain needs no iptables, capability
or BPF rules of its own: it may run a vendor shell script and read/write its two
properties, and nothing else. No stock policy or neverallow rule is changed.

This needs the vendor image to be built from source. A device that ships a
prebuilt vendor image cannot add the vendor policy this way.

## The telemetry sinkhole

The `telemetry` capability on an OS build does not use the VPN slot. Android's
resolver looks a name up in the hosts file before it sends any DNS query, so a
hosts file that maps telemetry domains to the unspecified address stops them
resolving, whichever DNS transport is in use.

| Piece | What it is |
|---|---|
| `telemetry.hosts` | Generated from `umbra/blocklists.py` by `scripts/sync-spec.sh`; installed as `/system_ext/etc/umbra/hosts`. Includes the stock localhost lines, because it replaces the stock hosts file while active. |
| `patches/packages/modules/DnsResolver/` | A patch to the resolver: while `persist.umbra.net.telemetry_sinkhole` is `1`, read that file instead of `/system/etc/hosts`. |
| `ro.umbra.dns_sinkhole=1` | A build property by which the OS states that it carries the patch. |

The hosts file is installed with the app automatically. An OS build must do the
other two itself: apply the patch to `packages/modules/DnsResolver` (the
resolver must be built from source), and set the property, for example:

```make
PRODUCT_SYSTEM_EXT_PROPERTIES += ro.umbra.dns_sinkhole=1
```

The property is a claim, not proof. When the app turns the sinkhole on it
resolves a blocklisted domain and reports the capability as enforced only if the
answer is the unspecified address, so an OS that sets the property without the
patch is caught.

The limit is the same as a hosts file on Linux: an app with its own
DNS-over-HTTPS client, or with hardcoded addresses, does not ask the system
resolver and is not affected. Subdomains are not matched unless listed.

## Kernel hardening

On Android only init may read or write the security-sensitive sysctls. So the
`kernel` capability is an init `.rc` file, `umbra-kernel.rc`, installed with the
app. It reacts to `persist.umbra.kernel.harden`:

| Request | What init does |
|---|---|
| `1` | Re-asserts `kptr_restrict=2`, `randomize_va_space=2` and `suid_dumpable=0` (the values Android's own init sets at boot, in case something lowered one), and sets `perf_event_paranoid=3` |
| `0` | Sets `perf_event_paranoid` back to the value the app recorded in `persist.umbra.kernel.prior_perf_paranoid` |

Modern Android leaves `perf_event_paranoid` at -1 and controls `perf_event_open`
with SELinux alone; 3 adds the sysctl back as a second lock. Profilers such as
simpleperf stop working while it is set.

The app cannot read three of those four sysctls back. It can read
`perf_event_paranoid`, which init sets in the same action, so it reads that as
proof the action ran and reports the capability as enforced only when it is 3.

During boot, Android's own init writes `perf_event_paranoid=-1` after persistent
properties have loaded. The file has a second action on that same boot trigger,
which runs afterwards, so a posture that was active before a reboot comes back
hardened.

Three parts of the Linux build's list are not applied on Android, on purpose:
`dmesg_restrict` and the ptrace scope, because SELinux already denies every app
both; and reverse-path filtering, because Android's multi-network routing
depends on it being off.

The file needs no extra SELinux policy beyond the property labels in
`sepolicy/private/`, which it shares with the packet-filter service.

## WireGuard

The ordinary app tunnels with the WireGuard project's Android library, which
Gradle fetches from Maven. An OS source tree does not contain it, so by default
the OS build compiles a stand-in that reports "no tunnel in this OS build".

To get a real tunnel, the OS provides the library and says so:

1. Define a module named `umbra-wireguard-tunnel` that imports the published
   `com.wireguard.android:tunnel` archive, for example:

   ```
   android_library_import {
       name: "umbra-wireguard-tunnel",
       aars: ["tunnel-1.0.20230706.aar"],
       sdk_version: "current",
       min_sdk_version: "21",
       extract_jni: true,
       static_libs: ["androidx.annotation_annotation", "androidx.collection_collection"],
   }
   ```

   Use the version `build.gradle.kts` pins, so both builds run the same tunnel.

2. Set the Soong variable in the product configuration:

   ```make
   $(call soong_config_set,umbra,wireguard_tunnel,true)
   ```

With that, the `wireguard` capability does three things an ordinary app cannot:
it authorizes itself as the VPN app with no consent dialog, brings the tunnel
up, and pins itself as Android's always-on VPN with lockdown. Lockdown is the
killswitch, and it is Android's own: the OS drops anything that would leave
outside the VPN, including while the tunnel is down or reconnecting and after a
reboot before it is back. On leaving the posture, lockdown is lifted first and
the previous always-on setting, if there was one, is put back.

After a reboot Android starts the always-on VPN by itself; the app answers by
re-asserting the posture the phone is in, which brings the tunnel back.

`umbra-sysconfig.xml`, installed with the app, exempts it from Android's
background restrictions. Without that, Android refuses to start the tunnel's VPN
service whenever a posture is applied while the app is in the background, which
is the normal case (the tile, or a re-assert after reboot).

A WireGuard config still has to be imported (in the app, or over `adb` with the
`IMPORT_WIREGUARD` action; see `PostureCommandReceiver`). Until one is, the
capability shows as unavailable with that reason.

## Testing an OS build

`tests/posture-matrix.sh` is the cross-check for all of the above. Against a
device or emulator running an OS build (reachable over `adb`, with `adb root`),
it applies every profile in turn with all controls active at once, switches
between them in both directions, and checks the live system state after each:
sysctls, properties, packet-filter rules, the always-on VPN setting, radios, the
camera restriction, plus that the internet is reachable and names still resolve.
Finally it applies `normal` and compares a full snapshot of that state with the
one taken before anything was applied. They must be identical.

```bash
android/os-integration/tests/posture-matrix.sh                 # system controls only
android/os-integration/tests/posture-matrix.sh wg-client.conf  # with a WireGuard tunnel
```

It also fails on any SELinux denial that mentions Umbra and on any crash.

## Files

| File | Purpose |
|---|---|
| `umbra-net.sh` | The service: reads the requests, writes the rules, reports the result |
| `umbra-net.rc` | Defines the service (vendor side) |
| `umbra-net-triggers.rc` | When init starts it: on `netd` start and whenever a request changes (system side, because vendor `.rc` files may not trigger on these properties) |
| `umbra-kernel.rc` | The init actions behind the `kernel` capability |
| `umbra-sysconfig.xml` | Exempts the app from background restrictions |
| `telemetry.hosts` | The generated blocklist hosts file |
| `patches/` | Patches to other projects (the DNS resolver) |
| `sepolicy/` | The SELinux policy, in the three directories described above |
