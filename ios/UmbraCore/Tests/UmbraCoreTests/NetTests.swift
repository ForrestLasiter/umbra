import XCTest
@testable import UmbraCore

final class NetTests: XCTestCase {

    private let src: [UInt8] = [10, 111, 0, 1]
    private let dst: [UInt8] = [10, 111, 0, 2]

    // MARK: IPv4 / UDP

    func testBuildThenParseRoundTrips() {
        let payload = Array("hello-dns".utf8)
        let pkt = IPv4Packet.buildUDP(src: src, dst: dst, srcPort: 53, dstPort: 40000, payload: payload)
        let ip = IPv4Packet.parse(pkt, pkt.count)!
        XCTAssertEqual(ip.proto, IPv4Packet.protoUDP)
        XCTAssertEqual(ip.srcAddr, src)
        XCTAssertEqual(ip.dstAddr, dst)
        let udp = UDPDatagram.parse(ip)!
        XCTAssertEqual(udp.srcPort, 53)
        XCTAssertEqual(udp.dstPort, 40000)
        XCTAssertEqual(udp.payload, payload)
    }

    func testHeaderChecksumIsValid() {
        let pkt = IPv4Packet.buildUDP(src: src, dst: dst, srcPort: 1, dstPort: 2, payload: [0, 0, 0, 0])
        XCTAssertEqual(InternetChecksum.compute(pkt, 0, 20), 0)
    }

    // MARK: DNS

    private func encodeQuery(_ name: String, _ type: Int, id: Int = 0x1234) -> [UInt8] {
        var out = [UInt8]()
        func p16(_ v: Int) { out.append(UInt8((v >> 8) & 0xFF)); out.append(UInt8(v & 0xFF)) }
        p16(id); p16(0x0100); p16(1); p16(0); p16(0); p16(0)
        for label in name.split(separator: ".") {
            out.append(UInt8(label.count)); out.append(contentsOf: Array(label.utf8))
        }
        out.append(0); p16(type); p16(1)
        return out
    }

    func testParsesQuestion() {
        let q = DnsQuery.parse(encodeQuery("graph.facebook.com", DnsQuery.typeA))!
        XCTAssertEqual(q.qName, "graph.facebook.com")
        XCTAssertEqual(q.qType, DnsQuery.typeA)
        XCTAssertEqual(q.id, 0x1234)
    }

    func testBlockedAAnswersZeroAddress() {
        let q = DnsQuery.parse(encodeQuery("app-measurement.com", DnsQuery.typeA))!
        let r = q.buildBlockedResponse()
        XCTAssertNotEqual(r[2] & 0x80, 0)                        // QR set
        XCTAssertEqual((Int(r[6]) << 8) | Int(r[7]), 1)         // ancount
        XCTAssertEqual(Array(r.suffix(4)), [0, 0, 0, 0])       // 0.0.0.0
    }

    func testBlockedOtherTypeIsNXDOMAIN() {
        let q = DnsQuery.parse(encodeQuery("analytics.google.com", 15))!
        let r = q.buildBlockedResponse()
        XCTAssertEqual((Int(r[6]) << 8) | Int(r[7]), 0)         // no answer
        XCTAssertEqual(Int(r[3]) & 0x0F, 3)                     // NXDOMAIN
    }

    // MARK: Blocklist

    func testBlocklistMatchesSubdomainsFromSpec() throws {
        let spec = try CoreSpec.parse(Data(SPEC.utf8))
        let bl = TelemetryBlocklist(spec: spec, profile: "home")
        XCTAssertTrue(bl.isBlocked("edge.graph.facebook.com"))
        XCTAssertTrue(bl.isBlocked("metrics.mozilla.org"))
        XCTAssertFalse(bl.isBlocked("example.com"))
        XCTAssertEqual(TelemetryBlocklist(spec: spec, profile: "normal").count, 0)
    }

    // MARK: Sinkhole end-to-end

    private let client: [UInt8] = [10, 111, 0, 2]
    private let resolver: [UInt8] = [10, 111, 0, 1]

    private func queryPacket(_ name: String, _ type: Int = DnsQuery.typeA) -> [UInt8] {
        IPv4Packet.buildUDP(src: client, dst: resolver, srcPort: 33333, dstPort: 53,
                            payload: encodeQuery(name, type))
    }

    func testSinkholeRepliesToBlockedQuery() {
        let bl = TelemetryBlocklist(["graph.facebook.com"])
        let pkt = queryPacket("graph.facebook.com")
        let reply = DnsSinkhole.reply(for: pkt, length: pkt.count, blocklist: bl)!
        let ip = IPv4Packet.parse(reply, reply.count)!
        XCTAssertEqual(ip.srcAddr, resolver)
        XCTAssertEqual(ip.dstAddr, client)
        let udp = UDPDatagram.parse(ip)!
        XCTAssertEqual(udp.srcPort, 53)
        XCTAssertEqual(udp.dstPort, 33333)
        XCTAssertEqual(Array(udp.payload.suffix(4)), [0, 0, 0, 0])       // 0.0.0.0
    }

    func testSinkholePassesThroughUnblocked() {
        let bl = TelemetryBlocklist(["graph.facebook.com"])
        let pkt = queryPacket("example.com")
        XCTAssertNil(DnsSinkhole.reply(for: pkt, length: pkt.count, blocklist: bl))
    }

    private let SPEC = """
    {
      "umbra_spec_version": "1", "engine_version": "0.1.0",
      "enforcement_levels": [], "capabilities": {}, "platforms": {},
      "telemetry_blocklists": {
        "os": ["metrics.mozilla.org"],
        "common-trackers": ["graph.facebook.com"]
      },
      "profiles": {
        "home": {"description": "", "fail_mode": "open", "requires": [],
                 "telemetry_blocklists": ["os", "common-trackers"]},
        "normal": {"description": "", "fail_mode": "open", "requires": [],
                   "telemetry_blocklists": []}
      }
    }
    """
}
