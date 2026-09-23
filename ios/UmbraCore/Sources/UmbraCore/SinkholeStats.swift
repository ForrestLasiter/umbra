import Foundation

/// Live DNS-sinkhole counters shared between the Packet Tunnel extension (which
/// writes them) and the app (which reads them). The two run in separate
/// processes, so they share an App Group `UserDefaults` suite. The suite is
/// injected, which also makes this unit-testable.
public struct SinkholeStats {
    public static let appGroup = "group.com.forrestlasiter.umbra"

    public struct Snapshot: Equatable {
        public let active: Bool
        public let domains: Int
        public let blocked: Int
        public let forwarded: Int
    }

    private let defaults: UserDefaults

    public init(defaults: UserDefaults) { self.defaults = defaults }

    /// The app-group-backed store (nil if the entitlement isn't present).
    public static func shared() -> SinkholeStats? {
        UserDefaults(suiteName: appGroup).map(SinkholeStats.init)
    }

    public func started(domains: Int) {
        defaults.set(true, forKey: Key.active)
        defaults.set(domains, forKey: Key.domains)
        defaults.set(0, forKey: Key.blocked)
        defaults.set(0, forKey: Key.forwarded)
    }

    public func recordBlocked() { defaults.set(defaults.integer(forKey: Key.blocked) + 1, forKey: Key.blocked) }
    public func recordForwarded() { defaults.set(defaults.integer(forKey: Key.forwarded) + 1, forKey: Key.forwarded) }
    public func stopped() { defaults.set(false, forKey: Key.active) }

    public func snapshot() -> Snapshot {
        Snapshot(active: defaults.bool(forKey: Key.active),
                 domains: defaults.integer(forKey: Key.domains),
                 blocked: defaults.integer(forKey: Key.blocked),
                 forwarded: defaults.integer(forKey: Key.forwarded))
    }

    private enum Key {
        static let active = "umbra.sink.active"
        static let domains = "umbra.sink.domains"
        static let blocked = "umbra.sink.blocked"
        static let forwarded = "umbra.sink.forwarded"
    }
}
