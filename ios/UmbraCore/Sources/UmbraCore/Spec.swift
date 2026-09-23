import Foundation

/// The platform-agnostic Umbra core, decoded from `umbra-core.json` (emitted by
/// the Python reference via `umbra export-spec`). iOS consumes exactly this — it
/// does not re-derive the posture model — so the phone and the laptop agree on
/// what a profile means and what this platform can honestly enforce.
///
/// Keep in step with umbra/spec.py::build_spec() and the Android core/Spec.kt.

/// The six honest promise levels. Mirrors umbra.platform.Enforcement.
public enum Enforcement: String, Codable {
    case enforced
    case requiresEntitlement = "requires_entitlement"
    case requiresVpnProfile = "requires_vpn_profile"
    case requiresRootedOS = "requires_rooted_os"
    case advisory
    case unavailable

    /// True when the app can actually change the state (vs. only observe/report).
    public var actionable: Bool {
        switch self {
        case .enforced, .requiresEntitlement, .requiresVpnProfile, .requiresRootedOS:
            return true
        case .advisory, .unavailable:
            return false
        }
    }

    public static func fromWire(_ s: String) -> Enforcement {
        Enforcement(rawValue: s) ?? .unavailable
    }
}

public struct EnforcementLevel: Codable {
    public let name: String
    public let description: String
}

public struct Capability: Codable {
    public let description: String
    public let controls: [String]
}

public struct PlatformCapability: Codable {
    public let level: String
    public let reason: String

    public var enforcement: Enforcement { Enforcement.fromWire(level) }
}

public struct PlatformSpec: Codable {
    public let description: String
    public let capabilities: [String: PlatformCapability]
}

public struct ProfileSpec: Codable {
    public let description: String
    public let failMode: String
    public let requires: [String]

    enum CodingKeys: String, CodingKey {
        case description
        case failMode = "fail_mode"
        case requires
    }
}

public struct CoreSpec: Codable {
    public let specVersion: String
    public let engineVersion: String
    public let enforcementLevels: [EnforcementLevel]
    public let capabilities: [String: Capability]
    public let platforms: [String: PlatformSpec]
    public let profiles: [String: ProfileSpec]

    enum CodingKeys: String, CodingKey {
        case specVersion = "umbra_spec_version"
        case engineVersion = "engine_version"
        case enforcementLevels = "enforcement_levels"
        case capabilities, platforms, profiles
    }

    /// The enforcement level THIS platform (ios) can promise for a capability.
    public func support(_ capability: String, platform: String = "ios") -> PlatformCapability {
        platforms[platform]?.capabilities[capability]
            ?? PlatformCapability(level: "unavailable", reason: "capability not in spec")
    }

    public static func parse(_ data: Data) throws -> CoreSpec {
        try JSONDecoder().decode(CoreSpec.self, from: data)
    }

    /// Load the bundled copy shipped in the app/extension resources.
    public static func loadBundled(from bundle: Bundle = .main) throws -> CoreSpec {
        guard let url = bundle.url(forResource: "umbra-core", withExtension: "json") else {
            throw NSError(domain: "UmbraCore", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "umbra-core.json not in bundle"])
        }
        return try parse(Data(contentsOf: url))
    }
}
