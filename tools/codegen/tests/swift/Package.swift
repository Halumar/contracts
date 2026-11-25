// swift-tools-version: 6.0
// Test harness for the generated Swift models. tools/codegen/tests/test_codegen.py copies this
// package to a temporary directory and puts the generated sources into Sources/HubModels.
import PackageDescription

let package = Package(
    name: "ContractModelsHarness",
    platforms: [.iOS(.v17), .tvOS(.v17), .macOS(.v14)],
    targets: [
        .target(name: "HubModels"),
        .testTarget(name: "ContractModelsTests", dependencies: ["HubModels"]),
    ],
    swiftLanguageModes: [.v6]
)
