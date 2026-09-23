import Foundation

/// Which enforcement datapath a posture uses on iOS. Pure selection logic
/// (mirrors the Android `TunnelMode`), so it is unit-tested. Precedence reflects
/// "go dark": tor > wireguard > telemetry-only > nothing. `paranoid` (which needs
/// both tor and wireguard) therefore routes through Tor.
public enum TunnelMode {
    case tor, wireGuard, dnsSinkhole, none

    private static let enforcedByTunnel: Set<PlannedAction> = [
        .enforce, .requestEntitlement, .needsTunnel,
    ]

    public static func forPlan(_ plan: PosturePlan) -> TunnelMode {
        func tunnels(_ capability: String) -> Bool {
            plan.items.contains { $0.capability == capability && enforcedByTunnel.contains($0.action) }
        }
        if tunnels("tor") { return .tor }
        if tunnels("wireguard") { return .wireGuard }
        if tunnels("telemetry") { return .dnsSinkhole }
        return .none
    }
}
