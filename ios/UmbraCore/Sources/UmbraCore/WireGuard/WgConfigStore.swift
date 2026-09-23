import Foundation

/// Stores the imported WireGuard config on disk — the iOS analogue of the Android
/// WgConfigStore and the phone's `/etc/wireguard/vpn.conf`. The directory is
/// injected (the app passes its App Group container so the Packet Tunnel
/// extension can read it too), which also makes this unit-testable.
public struct WgConfigStore {
    public static let name = "vpn"

    private let fileURL: URL

    public init(directory: URL) {
        self.fileURL = directory.appendingPathComponent("\(Self.name).conf")
    }

    /// Validate then persist. Throws WgConfigError on a bad config.
    public func save(_ text: String) throws {
        _ = try WgConfig.validate(text)
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: fileURL, atomically: true, encoding: .utf8)
    }

    public func load() -> String? { try? String(contentsOf: fileURL, encoding: .utf8) }

    public func exists() -> Bool { FileManager.default.fileExists(atPath: fileURL.path) }

    public func summary() -> WgConfigSummary? {
        guard let text = load() else { return nil }
        return try? WgConfig.validate(text)
    }

    public func clear() { try? FileManager.default.removeItem(at: fileURL) }
}
