import Foundation

/// Minimal IPv4: parse the header to find UDP, and build a reply packet with
/// correct header + UDP checksums. Mirrors the Android Ipv4Packet.
public struct IPv4Packet {
    public static let protoUDP = 17

    public let raw: [UInt8]
    public let length: Int
    public let ihl: Int
    public let proto: Int
    public let srcAddr: [UInt8]
    public let dstAddr: [UInt8]

    public var payloadOffset: Int { ihl }
    public var payloadLength: Int { length - ihl }

    public static func parse(_ buf: [UInt8], _ length: Int) -> IPv4Packet? {
        if length < 20 { return nil }
        let version = (Int(buf[0]) & 0xF0) >> 4
        if version != 4 { return nil }
        let ihl = (Int(buf[0]) & 0x0F) * 4
        if ihl < 20 || ihl > length { return nil }
        let proto = Int(buf[9])
        return IPv4Packet(raw: buf, length: length, ihl: ihl, proto: proto,
                          srcAddr: Array(buf[12..<16]), dstAddr: Array(buf[16..<20]))
    }

    /// Assemble a full IPv4 + UDP packet with recomputed checksums.
    public static func buildUDP(src: [UInt8], dst: [UInt8],
                                srcPort: Int, dstPort: Int, payload: [UInt8]) -> [UInt8] {
        let udpLen = 8 + payload.count
        let total = 20 + udpLen
        var p = [UInt8](repeating: 0, count: total)

        p[0] = 0x45
        p[2] = UInt8((total >> 8) & 0xFF)
        p[3] = UInt8(total & 0xFF)
        p[8] = 64
        p[9] = UInt8(protoUDP)
        p[12] = src[0]; p[13] = src[1]; p[14] = src[2]; p[15] = src[3]
        p[16] = dst[0]; p[17] = dst[1]; p[18] = dst[2]; p[19] = dst[3]
        let ipChk = InternetChecksum.compute(p, 0, 20)
        p[10] = UInt8((ipChk >> 8) & 0xFF)
        p[11] = UInt8(ipChk & 0xFF)

        let u = 20
        p[u] = UInt8((srcPort >> 8) & 0xFF); p[u + 1] = UInt8(srcPort & 0xFF)
        p[u + 2] = UInt8((dstPort >> 8) & 0xFF); p[u + 3] = UInt8(dstPort & 0xFF)
        p[u + 4] = UInt8((udpLen >> 8) & 0xFF); p[u + 5] = UInt8(udpLen & 0xFF)
        for (k, b) in payload.enumerated() { p[u + 8 + k] = b }

        let seed = InternetChecksum.partialSum(src, 0, 4)
            + InternetChecksum.partialSum(dst, 0, 4)
            + UInt64(protoUDP) + UInt64(udpLen)
        var udpChk = InternetChecksum.compute(p, u, udpLen, seed: seed)
        if udpChk == 0 { udpChk = 0xFFFF }
        p[u + 6] = UInt8((udpChk >> 8) & 0xFF)
        p[u + 7] = UInt8(udpChk & 0xFF)
        return p
    }
}

/// A parsed UDP datagram inside an IPv4 payload.
public struct UDPDatagram {
    public static let dnsPort = 53
    public let srcPort: Int
    public let dstPort: Int
    public let payload: [UInt8]

    public static func parse(_ ip: IPv4Packet) -> UDPDatagram? {
        if ip.proto != IPv4Packet.protoUDP { return nil }
        let off = ip.payloadOffset
        if ip.payloadLength < 8 { return nil }
        let buf = ip.raw
        let srcPort = (Int(buf[off]) << 8) | Int(buf[off + 1])
        let dstPort = (Int(buf[off + 2]) << 8) | Int(buf[off + 3])
        let udpLen = (Int(buf[off + 4]) << 8) | Int(buf[off + 5])
        let dataLen = max(0, min(udpLen - 8, ip.length - (off + 8)))
        return UDPDatagram(srcPort: srcPort, dstPort: dstPort,
                           payload: Array(buf[(off + 8)..<(off + 8 + dataLen)]))
    }
}
