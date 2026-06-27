// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "RiskCalc",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "RiskCalc",
            path: "Sources/RiskCalc"
        ),
        .testTarget(
            name: "RiskCalcTests",
            dependencies: ["RiskCalc"],
            path: "Tests/RiskCalcTests",
            resources: [.copy("Fixtures")]
        ),
    ]
)
