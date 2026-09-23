import XCTest
@testable import UmbraCore

/// Pure tests over the same core contract the app ships. They prove the iOS
/// adapter reads the spec correctly and stays HONEST — an advisory capability
/// must never surface as enforced.
final class PostureEngineTests: XCTestCase {

    private let specJSON = """
    {
      "umbra_spec_version": "1",
      "engine_version": "0.1.0",
      "enforcement_levels": [],
      "capabilities": {
        "telemetry": {"description": "Block phone-home.", "controls": []},
        "mac": {"description": "Randomize MAC.", "controls": []},
        "kernel": {"description": "Kernel hardening.", "controls": []},
        "wireguard": {"description": "Tunnel.", "controls": []}
      },
      "platforms": {
        "ios": {"description": "Network Extension", "capabilities": {
          "telemetry": {"level": "requires_entitlement", "reason": "DNS proxy"},
          "mac": {"level": "advisory", "reason": "OS owns it"},
          "kernel": {"level": "unavailable", "reason": "no kernel access"},
          "wireguard": {"level": "requires_entitlement", "reason": "NEVPNManager"}
        }}
      },
      "profiles": {
        "travel": {"description": "", "fail_mode": "closed",
                   "requires": ["telemetry", "mac", "kernel", "wireguard"]}
      }
    }
    """

    private func spec() throws -> CoreSpec {
        try CoreSpec.parse(Data(specJSON.utf8))
    }

    func testPlanCoversEveryRequiredCapability() throws {
        let plan = PostureEngine.plan(spec: try spec(), profile: "travel")
        XCTAssertEqual(plan.items.map { $0.capability },
                       ["telemetry", "mac", "kernel", "wireguard"])
    }

    func testAdvisoryNeverReportedAsEnforced() throws {
        let mac = PostureEngine.plan(spec: try spec(), profile: "travel")
            .items.first { $0.capability == "mac" }!
        XCTAssertEqual(mac.action, .guideToSetting)
        XCTAssertFalse(mac.honestlyOn)
    }

    func testUnavailableCapabilityIsMarkedUnavailable() throws {
        let kernel = PostureEngine.plan(spec: try spec(), profile: "travel")
            .items.first { $0.capability == "kernel" }!
        XCTAssertEqual(kernel.action, .unavailable)
    }

    func testEntitlementCapabilitiesAreActionable() throws {
        XCTAssertTrue(Enforcement.enforced.actionable)
        XCTAssertTrue(Enforcement.requiresEntitlement.actionable)
        XCTAssertFalse(Enforcement.advisory.actionable)
        XCTAssertFalse(Enforcement.unavailable.actionable)
    }
}
