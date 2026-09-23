import XCTest
@testable import UmbraCore

final class WgConfigTests: XCTestCase {

    private let key = String(repeating: "A", count: 43) + "="

    private func config(privateKey: String? = nil, dns: String? = "1.1.1.1",
                        endpoint: String = "vpn.example.com:51820", psk: String? = nil) -> String {
        var s = "[Interface]\n# imported\n"
        s += "PrivateKey = \(privateKey ?? key)\n"
        s += "Address = 10.7.0.2/32\n"
        if let dns { s += "DNS = \(dns)\n" }
        s += "\n[Peer]\nPublicKey = \(key)\n"
        if let psk { s += "PresharedKey = \(psk)\n" }
        s += "Endpoint = \(endpoint)\nAllowedIPs = 0.0.0.0/0, ::/0\nPersistentKeepalive = 25\n"
        return s
    }

    func testParsesValidConfig() throws {
        let s = try WgConfig.validate(config())
        XCTAssertEqual(s.endpoint, "vpn.example.com:51820")
        XCTAssertEqual(s.address, "10.7.0.2/32")
        XCTAssertEqual(s.dns, "1.1.1.1")
        XCTAssertFalse(s.hasPresharedKey)
    }

    func testDetectsPresharedKey() throws {
        XCTAssertTrue(try WgConfig.validate(config(psk: key)).hasPresharedKey)
    }

    func testDnsOptional() throws {
        XCTAssertNil(try WgConfig.validate(config(dns: nil)).dns)
    }

    func testMissingPrivateKeyRejected() {
        let text = config().split(separator: "\n").filter { !$0.hasPrefix("PrivateKey") }.joined(separator: "\n")
        XCTAssertThrowsError(try WgConfig.validate(text))
    }

    func testMalformedKeyRejected() {
        XCTAssertThrowsError(try WgConfig.validate(config(privateKey: "too-short")))
    }

    func testEndpointWithoutPortRejected() {
        XCTAssertThrowsError(try WgConfig.validate(config(endpoint: "vpn.example.com")))
    }
}
