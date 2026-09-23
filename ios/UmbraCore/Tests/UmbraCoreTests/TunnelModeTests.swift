import XCTest
@testable import UmbraCore

final class TunnelModeTests: XCTestCase {

    private func mode(_ profile: String) throws -> TunnelMode {
        let spec = try CoreSpec.parse(Data(SPEC.utf8))
        return TunnelMode.forPlan(PostureEngine.plan(spec: spec, profile: profile))
    }

    func testParanoidRoutesThroughTor() throws { XCTAssertEqual(try mode("paranoid"), .tor) }
    func testTravelUsesWireGuard() throws { XCTAssertEqual(try mode("travel"), .wireGuard) }
    func testHomeUsesDnsSinkhole() throws { XCTAssertEqual(try mode("home"), .dnsSinkhole) }
    func testBareEnforcesNothing() throws { XCTAssertEqual(try mode("bare"), TunnelMode.none) }

    private let SPEC = """
    {
      "umbra_spec_version": "1", "engine_version": "0.1.0",
      "enforcement_levels": [], "capabilities": {},
      "platforms": { "ios": { "description": "", "capabilities": {
        "tor": {"level": "requires_vpn_profile", "reason": ""},
        "wireguard": {"level": "requires_entitlement", "reason": ""},
        "telemetry": {"level": "requires_entitlement", "reason": ""},
        "kernel": {"level": "unavailable", "reason": ""},
        "mac": {"level": "advisory", "reason": ""}
      }}},
      "telemetry_blocklists": {},
      "profiles": {
        "paranoid": {"description": "", "fail_mode": "closed", "requires": ["tor","wireguard","telemetry"]},
        "travel":   {"description": "", "fail_mode": "closed", "requires": ["wireguard","telemetry"]},
        "home":     {"description": "", "fail_mode": "open",   "requires": ["telemetry","mac"]},
        "bare":     {"description": "", "fail_mode": "open",   "requires": ["kernel","mac"]}
      }
    }
    """
}
