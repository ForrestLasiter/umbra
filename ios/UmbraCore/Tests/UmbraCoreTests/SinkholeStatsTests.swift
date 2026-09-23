import XCTest
@testable import UmbraCore

final class SinkholeStatsTests: XCTestCase {

    private func freshStore() -> SinkholeStats {
        let suite = "test-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return SinkholeStats(defaults: defaults)
    }

    func testStartResetsAndSetsDomains() {
        let s = freshStore()
        s.started(domains: 6)
        let snap = s.snapshot()
        XCTAssertTrue(snap.active)
        XCTAssertEqual(snap.domains, 6)
        XCTAssertEqual(snap.blocked, 0)
        XCTAssertEqual(snap.forwarded, 0)
    }

    func testCountersIncrement() {
        let s = freshStore()
        s.started(domains: 2)
        s.recordBlocked(); s.recordBlocked(); s.recordForwarded()
        let snap = s.snapshot()
        XCTAssertEqual(snap.blocked, 2)
        XCTAssertEqual(snap.forwarded, 1)
    }

    func testStoppedClearsActive() {
        let s = freshStore()
        s.started(domains: 1)
        s.stopped()
        XCTAssertFalse(s.snapshot().active)
    }
}
