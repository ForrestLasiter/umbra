import Foundation

/// WireGuard config import for iOS — the Swift port of the Android `wg/WgConfig`
/// (and the phone equivalent of `umbra vpn`). A lightweight validator + summary
/// over a wg-quick `.conf`; WireGuardKit parses the real thing when the tunnel
/// comes up. Pure, so it is `swift test`-able (the algorithm is Python-mirror
/// verified, shared with the Kotlin port).
public struct WgConfigError: Error {
    public let message: String
    public init(_ message: String) { self.message = message }
}

public struct WgConfigSummary: Equatable {
    public let address: String
    public let dns: String?
    public let endpoint: String
    public let allowedIps: String
    public let hasPresharedKey: Bool
}

public enum WgConfig {

    public static func validate(_ text: String) throws -> WgConfigSummary {
        var section = ""
        var iface: [String: String] = [:]
        var peer: [String: String] = [:]

        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine).components(separatedBy: "#").first!
                .trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            switch line.lowercased() {
            case "[interface]": section = "interface"
            case "[peer]": section = "peer"
            default:
                if line.hasPrefix("[") { section = "other"; continue }
                guard let eq = line.firstIndex(of: "=") else { continue }
                let k = String(line[..<eq]).trimmingCharacters(in: .whitespaces).lowercased()
                let v = String(line[line.index(after: eq)...]).trimmingCharacters(in: .whitespaces)
                if k.isEmpty { continue }
                if section == "interface" { iface[k] = v }
                else if section == "peer" { peer[k] = v }
            }
        }

        guard let privateKey = iface["privatekey"] else {
            throw WgConfigError("missing PrivateKey in [Interface]")
        }
        try requireKey(privateKey, "PrivateKey")
        guard let address = iface["address"] else {
            throw WgConfigError("missing Address in [Interface]")
        }
        guard let publicKey = peer["publickey"] else {
            throw WgConfigError("missing PublicKey in [Peer]")
        }
        try requireKey(publicKey, "PublicKey")
        guard let endpoint = peer["endpoint"] else {
            throw WgConfigError("missing Endpoint in [Peer]")
        }
        try requireEndpoint(endpoint)
        if let psk = peer["presharedkey"] { try requireKey(psk, "PresharedKey") }

        return WgConfigSummary(
            address: address,
            dns: iface["dns"],
            endpoint: endpoint,
            allowedIps: peer["allowedips"] ?? "0.0.0.0/0, ::/0",
            hasPresharedKey: peer["presharedkey"] != nil
        )
    }

    private static func requireKey(_ value: String, _ name: String) throws {
        let ok = value.count == 44 && value.hasSuffix("=")
            && value.allSatisfy { $0.isLetter || $0.isNumber || $0 == "+" || $0 == "/" || $0 == "=" }
        if !ok { throw WgConfigError("\(name) is not a valid WireGuard key") }
    }

    private static func requireEndpoint(_ value: String) throws {
        guard let colon = value.lastIndex(of: ":") else {
            throw WgConfigError("Endpoint must be host:port")
        }
        let host = String(value[..<colon])
        let port = Int(value[value.index(after: colon)...])
        if host.isEmpty || port == nil || !(1...65535).contains(port!) {
            throw WgConfigError("Endpoint must be host:port")
        }
    }
}
