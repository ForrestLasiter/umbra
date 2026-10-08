#!/system/bin/sh
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
# netd (Android's network daemon) owns the filter table but leaves two empty
# chains for the OS builder, oem_in and oem_out, hooked first into INPUT and
# OUTPUT. We add ONE jump from each into chains of our own (umbra_in/umbra_out)
# and only ever flush our own, so anything else using the oem chains is left alone.

INBOUND_PROP=persist.umbra.net.inbound_drop
DISCOVERY_PROP=persist.umbra.net.discovery_drop
STATUS_PROP=umbra.net.applied

V4="iptables -w 5"
V6="ip6tables -w 5"
failed=0

run() { "$@" || failed=1; }

# netd creates its chains a moment after it starts; wait for them.
wait_for_netd() {
    tries=0
    until $V4 -S oem_in >/dev/null 2>&1 && $V6 -S oem_in >/dev/null 2>&1; do
        tries=$((tries + 1))
        [ "$tries" -gt 120 ] && return 1
        sleep 0.5
    done
}

# Make sure <chain> exists and is empty, and that <hook> jumps to it exactly once.
prepare() {   # $1 = "iptables ..." command, $2 = hook chain, $3 = our chain
    $1 -N "$3" 2>/dev/null
    run $1 -F "$3"
    $1 -C "$2" -j "$3" 2>/dev/null || run $1 -A "$2" -j "$3"
}

apply() {
    inbound=$1
    discovery=$2
    for cmd in "$V4" "$V6"; do
        prepare "$cmd" oem_in umbra_in
        prepare "$cmd" oem_out umbra_out
    done

    if [ "$inbound" = "1" ]; then
        for cmd in "$V4" "$V6"; do
            run $cmd -A umbra_in -i lo -j RETURN
            # Replies to connections the phone itself opened.
            run $cmd -A umbra_in -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
            # DNS for hotspot clients. Nothing listens here unless tethering is on.
            run $cmd -A umbra_in -p udp --dport 53 -j RETURN
            run $cmd -A umbra_in -p tcp --dport 53 -j RETURN
        done
        # DHCP: replies to the phone's client, and requests to its hotspot server.
        run $V4 -A umbra_in -p udp --dport 67:68 -j RETURN
        # IPv6 cannot work without neighbour discovery (133-137) and multicast
        # listener reports (130-132, 143). Echo requests (128) are NOT allowed.
        for type in 130 131 132 133 134 135 136 137 143; do
            run $V6 -A umbra_in -p ipv6-icmp --icmpv6-type "$type" -j RETURN
        done
        run $V6 -A umbra_in -p udp --dport 546 -j RETURN      # DHCPv6 client
        # Everything else unsolicited is dropped silently (no reject, no reply).
        run $V4 -A umbra_in -j DROP
        run $V6 -A umbra_in -j DROP
    fi

    if [ "$discovery" = "1" ]; then
        # mDNS, LLMNR, SSDP/UPnP, NetBIOS name + datagram, WS-Discovery.
        for port in 5353 5355 1900 137 138 3702; do
            run $V4 -A umbra_out -p udp --dport "$port" -j DROP
            run $V6 -A umbra_out -p udp --dport "$port" -j DROP
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
