#!/bin/bash
#
# posture-matrix: do Umbra's system controls work TOGETHER, and does the phone
# come back exactly as it was?
#
# Each control has its own focused test. This one is the cross-check: it applies
# every profile in turn with all controls active at once, switches between
# profiles in both directions, and compares a full snapshot of system state taken
# before anything was applied with one taken after `normal`. They must be
# IDENTICAL. It is the phone's version of the Linux build's kali-matrix.
#
# Needs a device or emulator running an OS build with Umbra built in, reachable
# over adb, with `adb root` available (userdebug or eng).
#
#   posture-matrix.sh                  # system controls only
#   posture-matrix.sh wg-client.conf   # also import that WireGuard config
#
# Exit status is 0 only if every check passed.

set -u
U=com.forrestlasiter.umbra
R="am broadcast -n $U/.system.PostureCommandReceiver"
CONF=${1:-}
fails=0

g() { timeout 90 adb shell "$@" < /dev/null 2>&1 | tr -d '\015'; }
ok()   { echo "  ok    $1"; }
bad()  { echo "  FAIL  $1"; fails=$((fails + 1)); }
skip() { echo "  skip  $1 (needs adb root)"; skipped=$((skipped + 1)); }
check() {
    if [ "$2" = "n/a" ]; then skip "$1"
    elif [ "$2" = "$3" ]; then ok "$1 = $2"
    else bad "$1: got [$2], expected [$3]"; fi
}
# Some state can only be read as root (umbra's own properties, the packet filter,
# init-only sysctls, the kernel log). Without root those read as "n/a" and their
# checks are skipped; Umbra's own audit and the functional checks still run.
ROOT=0
skipped=0
r() { if [ "$ROOT" = 1 ]; then g "$@"; else echo "n/a"; fi; }
# A name from Umbra's telemetry blocklist, to prove the sinkhole by resolving it.
CANARY=analytics.google.com

apply() {
    local out
    out=$(g "$R -a $U.action.APPLY_POSTURE --es profile $1" | sed -n 's/.*data="\(.*\)"/\1/p')
    echo "  -> $out"
    case "$out" in *"could not change"*) bad "applying $1 reported a failure" ;; esac
    sleep 4
}

# Ask Umbra to MEASURE the posture it is in. Every control it enforces must
# report as holding; "DRIFTED" or a short count is a failure.
audit() {
    local out
    out=$(g "$R -a $U.action.AUDIT" | sed -n 's/.*data="\(.*\)"/\1/p')
    echo "  audit: $out"
    case "$out" in
        *DRIFTED*) bad "audit reports drift" ;;
        *" of "*)
            local have total
            have=$(echo "$out" | sed -n 's/^[a-z]*: \([0-9]*\) of \([0-9]*\) .*/\1/p')
            total=$(echo "$out" | sed -n 's/^[a-z]*: \([0-9]*\) of \([0-9]*\) .*/\2/p')
            [ -n "$have" ] && [ "$have" = "$total" ] && ok "audit: all $total controls verified" || bad "audit: $have of $total verified"
            ;;
        *) bad "audit gave no result" ;;
    esac
}

# One line per piece of system state a control can change.
snapshot() {
    echo "perf_event_paranoid=$(g cat /proc/sys/kernel/perf_event_paranoid)"
    echo "kptr_restrict=$(r cat /proc/sys/kernel/kptr_restrict)"
    echo "telemetry_switch=$(r getprop persist.umbra.net.telemetry_sinkhole | sed 's/^$/0/')"
    echo "packet_filter=$(r getprop umbra.net.applied)"
    echo "inbound_rules=$(r "iptables -w -S oem_umbra_in 2>/dev/null | grep -c -- '-A '")"
    echo "discovery_rules=$(r "iptables -w -S oem_umbra_out 2>/dev/null | grep -c -- '-A '")"
    echo "always_on_vpn=$(g settings get secure always_on_vpn_app)"
    echo "vpn_lockdown=$(g settings get secure always_on_vpn_lockdown | sed 's/^null$/0/')"
    echo "tunnel_iface=$(g "ip -o -4 addr | grep -cE ' tun[0-9]'")"
    echo "mac_flag=$(g settings get global non_persistent_mac_randomization_force_enabled)"
    echo "bluetooth_on=$(g settings get global bluetooth_on)"
    echo "no_camera=$(g dumpsys user | grep -c 'no_camera')"
    echo "dhcp_hostname_restriction=$(g dumpsys wifi | sed -n 's/.*mSendDhcpHostnameRestriction=\([0-9]*\).*/\1/p' | head -1)"
}
value() { echo "$1" | sed -n "s/^$2=//p"; }

# What each profile must show, checked against the live system.
expect() {   # $1 = profile
    local s; s=$(snapshot)
    local hard=0 bt=1 cam=0 vpn=0
    case "$1" in
        home)     hard=1 ;;
        travel)   hard=1; bt=0; [ -n "$CONF" ] && vpn=1 ;;
        paranoid) hard=1; bt=0; cam=1 ;;
    esac
    if [ "$hard" = 1 ]; then
        check "perf_event_paranoid"        "$(value "$s" perf_event_paranoid)" 3
        check "telemetry_switch"           "$(value "$s" telemetry_switch)" 1
        check "packet_filter"              "$(value "$s" packet_filter)" "inbound=1 discovery=1"
        check "mac_flag"                   "$(value "$s" mac_flag)" 1
        check "dhcp_hostname_restriction"  "$(value "$s" dhcp_hostname_restriction)" 3
        local rules; rules=$(value "$s" inbound_rules)
        if [ "$rules" = "n/a" ]; then skip "inbound rules"
        elif [ "$rules" -gt 0 ]; then ok "inbound rules present"
        else bad "no inbound rules"; fi
        # Functional proof of the telemetry sinkhole, readable without root: a
        # blocklisted name must resolve to nowhere. (ping prints the unspecified
        # address as 127.0.0.1.)
        g "ping -c 1 -W 1 $CANARY 2>&1 | head -1" | grep -qE "\((127\.0\.0\.1|0\.0\.0\.0)\)" &&
            ok "blocklisted name resolves to nowhere" || bad "blocklisted name still resolves under $1"
    fi
    check "bluetooth_on" "$(value "$s" bluetooth_on)" "$bt"
    [ "$(value "$s" no_camera)" -gt 0 ] && c=1 || c=0
    check "camera blocked" "$c" "$cam"
    check "vpn_lockdown" "$(value "$s" vpn_lockdown)" "$vpn"
    check "tunnel_iface" "$(value "$s" tunnel_iface)" "$vpn"
    # The network must still work under every profile (through the tunnel, if any).
    g "ping -c 2 -W 3 9.9.9.9" | grep -q " 0% packet loss" && ok "internet reachable" || bad "internet NOT reachable under $1"
    # ...and name resolution too, since three controls touch DNS or the firewall.
    g "ping -c 1 -W 3 example.org" | grep -q "1 received" && ok "names resolve" || bad "names do NOT resolve under $1"
}

adb root > /dev/null 2>&1; sleep 3; adb wait-for-device
[ "$(g id -u)" = "0" ] && ROOT=1
echo "== device: $(g getprop ro.build.fingerprint)"
echo "   build type $(g getprop ro.build.type), SELinux $(g getenforce), adb root: $([ "$ROOT" = 1 ] && echo yes || echo "no (root-only checks will be skipped)")"
g svc bluetooth enable > /dev/null; sleep 6      # so bluetooth_off has something to turn off
apply normal > /dev/null

if [ -n "$CONF" ]; then
    adb push "$CONF" /data/local/tmp/wg.conf > /dev/null 2>&1
    echo "== import WireGuard config"
    echo "  -> $(g "$R -a $U.action.IMPORT_WIREGUARD --es config \"\$(cat /data/local/tmp/wg.conf)\"" | sed -n 's/.*data="\(.*\)"/\1/p')"
    g "rm -f /data/local/tmp/wg.conf"
fi

before=$(snapshot)
echo "== baseline"; echo "$before" | sed 's/^/  /'

# Up through the profiles, then back down and across, so every switch direction
# is exercised: lighter->heavier, heavier->lighter, and tunnel<->no tunnel.
for profile in home travel paranoid travel home paranoid; do
    echo "== apply $profile"
    apply "$profile"
    expect "$profile"
    audit
done

# Drift: change a setting behind Umbra's back. The audit must notice, and
# re-applying the same profile must put it right.
echo "== drift detection (under paranoid)"
g settings put global non_persistent_mac_randomization_force_enabled 0
out=$(g "$R -a $U.action.AUDIT" | sed -n 's/.*data="\(.*\)"/\1/p')
echo "  audit: $out"
case "$out" in *"DRIFTED: mac"*) ok "audit noticed the changed setting" ;; *) bad "audit did not notice drift" ;; esac
apply paranoid
audit

# Reboot with a posture active: it must come back by itself and audit clean.
echo "== reboot (under home)"
apply home
timeout 20 adb reboot; sleep 10
adb wait-for-device
for i in $(seq 1 300); do
    [ "$(timeout 5 adb shell getprop sys.boot_completed 2>/dev/null | tr -d '[:cntrl:]')" = "1" ] && break
    sleep 1
done
sleep 30
adb root > /dev/null 2>&1; sleep 3; adb wait-for-device
expect home
audit

echo "== apply normal"
apply normal
after=$(snapshot)
if [ "$before" = "$after" ]; then
    ok "state after normal is IDENTICAL to the baseline"
else
    bad "state after normal differs from the baseline:"
    diff <(echo "$before") <(echo "$after") | sed 's/^/        /'
fi

echo "== SELinux denials involving Umbra"
if [ "$ROOT" = 1 ]; then
    denials=$(g "dmesg | grep -i 'avc.*denied' | grep -iE 'umbra|netutils'" | sed 's/.*avc: *//; s/pid=[0-9]* //; s/ino=[0-9]* //' | sort -u)
    if [ -z "$denials" ]; then ok "none"; else bad "denials found:"; echo "$denials" | cut -c1-240 | sed 's/^/        /'; fi
else
    skip "kernel log"
fi

echo "== crashes"
crashes=$(g "logcat -d -b crash" | grep -cE "FATAL EXCEPTION|com.forrestlasiter.umbra")
[ "$crashes" = 0 ] && ok "none" || bad "$crashes crash log line(s) mention Umbra or a fatal exception"

echo
note=""
[ "$skipped" -gt 0 ] && note=" ($skipped check(s) skipped for lack of adb root)"
if [ "$fails" = 0 ]; then echo "RESULT: PASS$note"; else echo "RESULT: FAIL ($fails check(s))$note"; fi
exit $((fails > 0))
