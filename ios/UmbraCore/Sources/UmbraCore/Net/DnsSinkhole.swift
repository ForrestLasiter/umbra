import Foundation

/// The pure sinkhole decision, shared by the Packet Tunnel provider and the
/// tests. If a packet is a DNS query for a blocked domain, returns the full
/// IPv4/UDP reply to write back; otherwise nil (the caller forwards it).
public enum DnsSinkhole {

    public static func reply(for packet: [UInt8], length: Int,
                             blocklist: TelemetryBlocklist) -> [UInt8]? {
        guard let ip = IPv4Packet.parse(packet, length),
              let udp = UDPDatagram.parse(ip),
              udp.dstPort == UDPDatagram.dnsPort,
              let q = DnsQuery.parse(udp.payload),
              blocklist.isBlocked(q.qName) else { return nil }
        return IPv4Packet.buildUDP(src: ip.dstAddr, dst: ip.srcAddr,
                                   srcPort: udp.dstPort, dstPort: udp.srcPort,
                                   payload: q.buildBlockedResponse())
    }
}
