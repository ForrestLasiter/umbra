import NetworkExtension
import UmbraCore

/// The iOS enforcement path. Like the Android VPNService, this delivers the
/// `telemetry` capability with a DNS-only tunnel: only the tunnel's DNS server is
/// routed in, so every lookup arrives here to be sinkholed or forwarded, while
/// all other traffic flows normally.
///
///   - blocked telemetry domain -> answered locally 0.0.0.0 / :: (like the Linux
///                                 /etc/hosts sinkhole);
///   - everything else          -> forwarded to a real upstream and relayed.
///
/// The pure parsing/sinkhole logic is UmbraCore (shared with the app, unit-tested
/// + Python-mirror verified). WireGuard/Tor (full capture) remain future work.
///
/// DEVICE-TEST PENDING: the tunnel plumbing needs a real iOS runtime; the datapath
/// logic it drives is verified.
class PacketTunnelProvider: NEPacketTunnelProvider {

    private let tunDNS = "10.111.0.1"
    private let forwarder = UDPForwarder()
    private var blocklist = TelemetryBlocklist([])

    override func startTunnel(options: [String: NSObject]?,
                              completionHandler: @escaping (Error?) -> Void) {
        let profile = (options?["profile"] as? String) ?? "home"
        if let spec = try? CoreSpec.loadBundled(from: Bundle(for: Self.self)) {
            blocklist = TelemetryBlocklist(spec: spec, profile: profile)
            NSLog("Umbra: DNS sinkhole up for '\(profile)' — \(blocklist.count) domains")
        }

        // DNS-only capture: route just our resolver, and make it the system DNS.
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: tunDNS)
        let ipv4 = NEIPv4Settings(addresses: ["10.111.0.2"], subnetMasks: ["255.255.255.255"])
        ipv4.includedRoutes = [NEIPv4Route(destinationAddress: tunDNS, subnetMask: "255.255.255.255")]
        settings.ipv4Settings = ipv4
        let dns = NEDNSSettings(servers: [tunDNS])
        dns.matchDomains = [""]                  // send all DNS through the tunnel resolver
        settings.dnsSettings = dns

        setTunnelNetworkSettings(settings) { [weak self] error in
            if let error { completionHandler(error); return }
            self?.readLoop()
            completionHandler(nil)
        }
    }

    private func readLoop() {
        packetFlow.readPackets { [weak self] packets, protocols in
            guard let self else { return }
            for (i, data) in packets.enumerated() where protocols[i].int32Value == AF_INET {
                self.handle(Array(data))
            }
            self.readLoop()
        }
    }

    private func handle(_ packet: [UInt8]) {
        guard let ip = IPv4Packet.parse(packet, packet.count),
              let udp = UDPDatagram.parse(ip),
              udp.dstPort == UDPDatagram.dnsPort else { return }

        if let q = DnsQuery.parse(udp.payload), blocklist.isBlocked(q.qName) {
            writeReply(ip, udp, q.buildBlockedResponse())
        } else {
            forwarder.forward(udp.payload) { [weak self] reply in
                if let reply { self?.writeReply(ip, udp, reply) }
            }
        }
    }

    private func writeReply(_ ip: IPv4Packet, _ udp: UDPDatagram, _ dns: [UInt8]) {
        let reply = IPv4Packet.buildUDP(src: ip.dstAddr, dst: ip.srcAddr,
                                        srcPort: udp.dstPort, dstPort: udp.srcPort, payload: dns)
        packetFlow.writePackets([Data(reply)], withProtocols: [NSNumber(value: AF_INET)])
    }

    override func stopTunnel(with reason: NEProviderStopReason,
                             completionHandler: @escaping () -> Void) {
        completionHandler()
    }
}
