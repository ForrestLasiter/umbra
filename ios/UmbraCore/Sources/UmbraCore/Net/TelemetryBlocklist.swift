import Foundation

/// Domain matcher for the DNS sinkhole, built from the shared core spec — the
/// same lists the Linux /etc/hosts sinkhole and the Android app use.
public struct TelemetryBlocklist {
    private let blocked: Set<String>
    public var count: Int { blocked.count }

    public init(_ domains: Set<String>) {
        blocked = Set(domains.map { $0.lowercased().trimmingTrailingDots() })
    }

    public init(spec: CoreSpec, profile: String) {
        self.init(spec.telemetryDomains(profile))
    }

    /// True if `qName` is a blocked domain or a subdomain of one.
    public func isBlocked(_ qName: String) -> Bool {
        let name = qName.lowercased().trimmingTrailingDots()
        if blocked.contains(name) { return true }
        var rest = name
        while let dot = rest.firstIndex(of: ".") {
            rest = String(rest[rest.index(after: dot)...])
            if blocked.contains(rest) { return true }
        }
        return false
    }
}

private extension String {
    func trimmingTrailingDots() -> String {
        var s = self
        while s.hasSuffix(".") { s.removeLast() }
        return s
    }
}
