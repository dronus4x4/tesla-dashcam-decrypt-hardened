import Darwin
import Foundation

@main
enum Launcher {
    @MainActor
    static func main() {
        if CommandLine.arguments.contains("--check-installation") {
            do {
                try checkInstallation()
                print("Native app resource and Python worker checks passed.")
            } catch {
                print("App installation check failed: \(error)")
                exit(1)
            }
        } else {
            TeslaDecryptApp.main()
        }
    }

    private static func checkInstallation() throws {
        let manager = FileManager.default
        let temp = manager.temporaryDirectory.resolvingSymlinksInPath()
            .appendingPathComponent("tesla-install-check-" + UUID().uuidString)
        let input = temp.appendingPathComponent("input")
        let output = temp.appendingPathComponent("output")
        try manager.createDirectory(at: input, withIntermediateDirectories: true)
        defer { try? manager.removeItem(at: temp) }
        let worker = Bundle.module.resourceURL!.appendingPathComponent("Resources/gui_bridge.py")
        let python = Bundle.main.resourceURL!.appendingPathComponent("python-runtime/bin/python3")
        guard manager.fileExists(atPath: worker.path), manager.isExecutableFile(atPath: python.path) else {
            print("Worker resource: \(worker.path), exists: \(manager.fileExists(atPath: worker.path))")
            print("Python runtime: \(python.path), executable: \(manager.isExecutableFile(atPath: python.path))")
            throw NSError(domain: "TeslaInstallCheck", code: 1)
        }
        let process = Process(), stdout = Pipe(), stderr = Pipe()
        process.executableURL = python
        process.arguments = [worker.path, input.path, output.path, "--scan"]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        let data = stdout.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0,
              let result = String(data: data, encoding: .utf8),
              result.contains("\"kind\": \"scan\""),
              !manager.fileExists(atPath: output.path) else {
            print("Offline worker exit: \(process.terminationStatus)")
            print(String(data: data, encoding: .utf8) ?? "No output")
            print(String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "")
            throw NSError(domain: "TeslaInstallCheck", code: 2)
        }
    }
}
