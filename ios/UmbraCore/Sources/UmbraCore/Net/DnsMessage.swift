import Foundation

/// Minimal DNS: read the first question, and build a sinkholed response for a
/// blocked domain (A -> 0.0.0.0, AAAA -> ::, else NXDOMAIN). Mirrors the Android
/// DnsMessage; the algorithm is cross-checked against the Python mirror.
public struct DnsQuery {
    public static let typeA = 1
    public static let typeAAAA = 28
    private static let classIN = 1
    private static let rcodeNXDOMAIN = 3
    private static let questionStart = 12

    public let id: Int
    public let flags: Int
    public let qName: String
    public let qType: Int
    public let raw: [UInt8]
    public let questionEnd: Int

    public static func parse(_ payload: [UInt8]) -> DnsQuery? {
        if payload.count < 12 { return nil }
        let id = u16(payload, 0)
        let flags = u16(payload, 2)
        let qd = u16(payload, 4)
        if qd < 1 { return nil }

        var name = ""
        var i = questionStart
        while i < payload.count {
            let len = Int(payload[i])
            if len == 0 { i += 1; break }
            if (len & 0xC0) != 0 { return nil }
            if i + 1 + len > payload.count { return nil }
            if !name.isEmpty { name += "." }
            for j in 0..<len { name.append(Character(UnicodeScalar(payload[i + 1 + j]))) }
            i += 1 + len
        }
        if i + 4 > payload.count { return nil }
        let qType = u16(payload, i)
        i += 4
        return DnsQuery(id: id, flags: flags, qName: name.lowercased(),
                        qType: qType, raw: payload, questionEnd: i)
    }

    /// A response that sinkholes this query.
    public func buildBlockedResponse() -> [UInt8] {
        let questionLen = questionEnd - DnsQuery.questionStart
        let rdata: [UInt8]? = qType == DnsQuery.typeA ? [UInt8](repeating: 0, count: 4)
            : (qType == DnsQuery.typeAAAA ? [UInt8](repeating: 0, count: 16) : nil)
        let hasAnswer = rdata != nil
        let anc = hasAnswer ? 1 : 0
        let answerLen = hasAnswer ? 12 + rdata!.count : 0

        var out = [UInt8](repeating: 0, count: 12 + questionLen + answerLen)
        DnsQuery.put16(&out, 0, id)
        let rcode = hasAnswer ? 0 : DnsQuery.rcodeNXDOMAIN
        let rd = flags & 0x0100
        DnsQuery.put16(&out, 2, 0x8000 | rd | 0x0080 | rcode)
        DnsQuery.put16(&out, 4, 1)
        DnsQuery.put16(&out, 6, anc)
        DnsQuery.put16(&out, 8, 0); DnsQuery.put16(&out, 10, 0)

        for k in 0..<questionLen { out[12 + k] = raw[DnsQuery.questionStart + k] }

        if hasAnswer, let rdata = rdata {
            var o = 12 + questionLen
            DnsQuery.put16(&out, o, 0xC000 | DnsQuery.questionStart); o += 2
            DnsQuery.put16(&out, o, qType); o += 2
            DnsQuery.put16(&out, o, DnsQuery.classIN); o += 2
            DnsQuery.put16(&out, o, 0); DnsQuery.put16(&out, o + 2, 60); o += 4
            DnsQuery.put16(&out, o, rdata.count); o += 2
            for (k, b) in rdata.enumerated() { out[o + k] = b }
        }
        return out
    }

    private static func u16(_ b: [UInt8], _ o: Int) -> Int { (Int(b[o]) << 8) | Int(b[o + 1]) }
    private static func put16(_ b: inout [UInt8], _ o: Int, _ v: Int) {
        b[o] = UInt8((v >> 8) & 0xFF); b[o + 1] = UInt8(v & 0xFF)
    }
}
