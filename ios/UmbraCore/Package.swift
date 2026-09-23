// swift-tools-version:5.9
import PackageDescription

// The platform-agnostic Umbra core for Apple platforms: pure Swift, no UIKit /
// Network Extension imports, so it compiles and unit-tests with `swift test` and
// is shared by the app and the packet-tunnel extension.
let package = Package(
    name: "UmbraCore",
    products: [
        .library(name: "UmbraCore", targets: ["UmbraCore"]),
    ],
    targets: [
        .target(name: "UmbraCore"),
        .testTarget(name: "UmbraCoreTests", dependencies: ["UmbraCore"]),
    ]
)
