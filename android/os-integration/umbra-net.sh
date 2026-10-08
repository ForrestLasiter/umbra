#!/vendor/bin/sh
#
# umbra-net: the OS half of Umbra's `firewall` and `discovery` capabilities.
#
# An Android app, even a platform-signed one, cannot touch the packet filter:
# only root can. So the app does not try. It states what it wants in two system
# properties, and this small root service (started by init, see umbra-net.rc)
# turns that into iptables rules and reports back what is actually in place:
#
#   persist.umbra.net.inbound_drop=1    default-deny inbound       (firewall)
#   persist.umbra.net.discovery_drop=1  drop discovery chatter out (discovery)
#   umbra.net.applied="inbound=1 discovery=0"   <- written here, read by the app
#
# The app only reports a capability as enforced after it reads the matching
# value back from umbra.net.applied. If this service is missing or fails, that
# never happens, and the app says so instead of pretending.
#
# Why it lives in /vendor and calls a "wrapper": on Android, changing ANY rule
# rewrites the whole filter table, including netd's own rules that reference
# kernel BPF programs. SELinux lets only two things do that: netd itself, and
# netutils-wrapper, the door Android leaves open for OS builders. The wrapper
# accepts commands from vendor code only, and only for chains named oem_*. So
# this service is vendor code, and its chains are oem_umbra_in / oem_umbra_out,
# hooked from netd's empty oem_in / oem_out. Stock SELinux policy is untouched.

INBOUND_PROP=persist.umbra.net.inbound_drop
DISCOVERY_PROP=persist.umbra.net.discovery_drop
STATUS_PROP=umbra.net.applied

V4="/system/bin/iptables-wrapper-1.0 -w 5"
V6="/system/bin/ip6tables-wrapper-1.0 -w 5"
IN=oem_umbra_in
OUT=oem_umbra_out
failed=0

run() { "$@" || failed=1; }

# Make sure our chain exists and that the hook chain jumps to it exactly once.
# Fails (quietly) until netd has created the hook chain.
hook() {   # $1 = wrapper command, $2 = netd's hook chain, $3 = our chain
    $1 -N "$3" 2>/dev/null
    $1 -C "$2" -j "$3" 2>/dev/null || $1 -A "$2" -j "$3" 2>/dev/null
}

hook_all() {
    hook "$V4" oem_in $IN && hook "$V4" oem_out $OUT &&
        hook "$V6" oem_in $IN && hook "$V6" oem_out $OUT
}

# netd creates its chains a moment after it starts; keep trying for a minute.
wait_for_netd() {
    tries=0
    until hook_all; do
        tries=$((tries + 1))
        [ "$tries" -gt 120 ] && return 1
        sleep 0.5
    done
}

apply() {
    inbound=$1
    discovery=$2
    hook_all || failed=1
    for cmd in "$V4" "$V6"; do
        run $cmd -F $IN
        run $cmd -F $OUT
    done

    if [ "$inbound" = "1" ]; then
        for cmd in "$V4" "$V6"; do
            run $cmd -A $IN -i lo -j RETURN
            # Replies to connections the phone itself opened.
            run $cmd -A $IN -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
            # DNS for hotspot clients. Nothing listens here unless tethering is on.
            run $cmd -A $IN -p udp --dport 53 -j RETURN
            run $cmd -A $IN -p tcp --dport 53 -j RETURN
        done
        # DHCP: replies to the phone's client, and requests to its hotspot server.
        run $V4 -A $IN -p udp --dport 67:68 -j RETURN
        # IPv6 cannot work without neighbour discovery (133-137) and multicast
        # listener reports (130-132, 143). Echo requests (128) are NOT allowed.
        for type in 130 131 132 133 134 135 136 137 143; do
            run $V6 -A $IN -p ipv6-icmp --icmpv6-type "$type" -j RETURN
        done
        run $V6 -A $IN -p udp --dport 546 -j RETURN      # DHCPv6 client
        # Everything else unsolicited is dropped silently (no reject, no reply).
        run $V4 -A $IN -j DROP
        run $V6 -A $IN -j DROP
    fi

    if [ "$discovery" = "1" ]; then
        # mDNS, LLMNR, SSDP/UPnP, NetBIOS name + datagram, WS-Discovery.
        for port in 5353 5355 1900 137 138 3702; do
            run $V4 -A $OUT -p udp --dport "$port" -j DROP
            run $V6 -A $OUT -p udp --dport "$port" -j DROP
        done
    fi
}

if ! wait_for_netd; then
    setprop "$STATUS_PROP" error
    exit 1
fi

# init will not start this service again while it is still running, so a request
# that arrives mid-run would be lost. Loop until what we applied is still what is
# being asked for.
while :; do
    inbound=$(getprop "$INBOUND_PROP")
    discovery=$(getprop "$DISCOVERY_PROP")
    [ "$inbound" = "1" ] || inbound=0
    [ "$discovery" = "1" ] || discovery=0

    failed=0
    apply "$inbound" "$discovery"
    if [ "$failed" = "1" ]; then
        setprop "$STATUS_PROP" error
        exit 1
    fi
    setprop "$STATUS_PROP" "inbound=$inbound discovery=$discovery"

    now_in=$(getprop "$INBOUND_PROP")
    now_disc=$(getprop "$DISCOVERY_PROP")
    [ "$now_in" = "1" ] || now_in=0
    [ "$now_disc" = "1" ] || now_disc=0
    [ "$now_in" = "$inbound" ] && [ "$now_disc" = "$discovery" ] && break
done
