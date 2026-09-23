import Foundation

/// The iOS adapter's brain: given the profile the user picked, decide — per
/// required capability — what this device will ACTUALLY do, and say so honestly.
/// iOS is the most sandboxed platform, so most rows are advisory; DNS and the
/// tunnel work through a Network Extension entitlement.

public enum PlannedAction: String {
    case enforce            // the extension does it now
    case requestEntitlement // needs the Network Extension entitlement + profile install
    case needsTunnel        // enforced only while the Umbra tunnel is running
    case needsRoot          // impossible on stock iOS
    case guideToSetting     // advisory: deep-link the user to the OS toggle
    case unavailable        // not possible on this platform
}

public struct PostureItem: Identifiable {
    public var id: String { capability }
    public let capability: String
    public let summary: String
    public let enforcement: Enforcement
    public let reason: String
    public let action: PlannedAction

    public var honestlyOn: Bool { action == .enforce }
}

public struct PosturePlan {
    public let profile: String
    public let items: [PostureItem]

    public var enforceable: [PostureItem] {
        items.filter { $0.action == .enforce || $0.action == .needsTunnel || $0.action == .requestEntitlement }
    }
    public var advisory: [PostureItem] {
        items.filter { $0.action == .guideToSetting }
    }
}

public enum PostureEngine {

    public static func plan(spec: CoreSpec, profile profileName: String) -> PosturePlan {
        guard let profile = spec.profiles[profileName] else {
            return PosturePlan(profile: profileName, items: [])
        }
        let items = profile.requires.map { cap -> PostureItem in
            let support = spec.support(cap)
            let level = support.enforcement
            return PostureItem(
                capability: cap,
                summary: spec.capabilities[cap]?.description ?? cap,
                enforcement: level,
                reason: support.reason,
                action: actionFor(level)
            )
        }
        return PosturePlan(profile: profileName, items: items)
    }

    private static func actionFor(_ level: Enforcement) -> PlannedAction {
        switch level {
        case .enforced:            return .enforce
        case .requiresEntitlement: return .requestEntitlement
        case .requiresVpnProfile:  return .needsTunnel
        case .requiresRootedOS:    return .needsRoot
        case .advisory:            return .guideToSetting
        case .unavailable:         return .unavailable
        }
    }
}
