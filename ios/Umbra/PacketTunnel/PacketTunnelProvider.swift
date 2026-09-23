import NetworkExtension
import UmbraCore

/// The iOS enforcement path. A Packet Tunnel Provider is how a sandboxed iPhone
/// enforces anything on the wire: it captures egress and can filter DNS (telemetry
/// sinkhole) or forward through WireGuard / Tor. It runs in its own process with
/// the Network Extension entitlement, started by the app via NETunnelProviderManager.
///
/// Like the Android VPNService, capabilities the matrix marks advisory/unavailable
/// are NOT touched here — the UI reports them honestly instead.
///
/// The datapath below is a scaffold: it establishes the tunnel settings and owns
/// the lifecycle. Wiring the real DNS/packet processing (and a WireGuard/Tor
/// backend) is the next implementation step, marked TODO.
class PacketTunnelProvider: NEPacketTunnelProvider {

    override func startTunnel(options: [String: NSObject]?,
                              completionHandler: @escaping (Error?) -> Void) {
        let profile = (options?["profile"] as? String) ?? "travel"

        // Decide, from the shared core, what this posture enforces on iOS.
        if let spec = try? CoreSpec.loadBundled(from: Bundle(for: Self.self)) {
            let plan = PostureEngine.plan(spec: spec, profile: profile)
            NSLog("Umbra: tunnel up for '\(profile)'; enforceable=\(plan.enforceable.map { $0.capability })")
        }

        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: "127.0.0.1")
        let ipv4 = NEIPv4Settings(addresses: ["10.111.0.2"], subnetMasks: ["255.255.255.255"])
        ipv4.includedRoutes = [NEIPv4Route.default()]   // capture all IPv4
        settings.ipv4Settings = ipv4
        let ipv6 = NEIPv6Settings(addresses: ["fd00:1111::2"], networkPrefixLengths: [64])
        ipv6.includedRoutes = [NEIPv6Route.default()]   // ...and IPv6, no leak-around
        settings.ipv6Settings = ipv6
        // DNS handled inside the tunnel so telemetry lookups can be sinkholed.
        settings.dnsSettings = NEDNSSettings(servers: ["10.111.0.1"])

        setTunnelNetworkSettings(settings) { [weak self] error in
            if let error { completionHandler(error); return }
            self?.readPackets()
            completionHandler(nil)
        }
    }

    private func readPackets() {
        packetFlow.readPackets { [weak self] packets, protocols in
            // TODO(datapath): process/forward via the selected stack:
            //   telemetry -> drop DNS answers for telemetry domains
            //   wireguard -> encrypt + forward to the endpoint
            //   tor       -> forward through a Tor packet tunnel
            // Scaffold: keep the loop alive so the interface stays established.
            _ = packets; _ = protocols
            self?.readPackets()
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason,
                             completionHandler: @escaping () -> Void) {
        completionHandler()
    }
}
