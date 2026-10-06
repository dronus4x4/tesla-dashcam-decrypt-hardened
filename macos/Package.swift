// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TeslaDecryptGUI",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "TeslaDecryptGUI", targets: ["TeslaDecryptGUI"])],
    targets: [
        .executableTarget(name: "TeslaDecryptGUI", resources: [.copy("Resources")])
    ]
)
