import AppKit
import Foundation
import SwiftUI

@MainActor
final class DecryptModel: ObservableObject {
    @Published var input: URL?
    @Published var output: URL?
    @Published var token = ""
    @Published var status = "Select your Tesla drive and a destination, then scan."
    @Published var log: [String] = []
    @Published var scanDescription = "Scan is offline."
    @Published var busy = false
    @Published var pending = 0
    @Published var fraction = 0.0
    private var process: Process?
    private var reader: EventReader?
    private var initialPending = 0
    private var handled = 0
    private var inputScope = false
    private var outputScope = false
    var hasFolders: Bool { input != nil && output != nil }

    func pickFolder(input choosingInput: Bool) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = !choosingInput
        panel.message = choosingInput ? "Choose the Tesla USB drive or TeslaCam folder." : "Choose a separate APFS folder on your Mac."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        if choosingInput {
            if inputScope { input?.stopAccessingSecurityScopedResource() }
            input = url
            inputScope = url.startAccessingSecurityScopedResource()
        } else {
            if outputScope { output?.stopAccessingSecurityScopedResource() }
            output = url
            outputScope = url.startAccessingSecurityScopedResource()
        }
        pending = 0
        scanDescription = "Folders changed — scan again."
    }

    func run(scan: Bool) {
        guard !busy, let input, let output else { return }
        let resources = Bundle.module.resourceURL!.appendingPathComponent("Resources")
        let python = Bundle.main.resourceURL?.appendingPathComponent("python-runtime/bin/python3")
        let job = Process()
        if let python, FileManager.default.isExecutableFile(atPath: python.path) {
            job.executableURL = python
            job.arguments = [resources.appendingPathComponent("gui_bridge.py").path, input.path, output.path]
        } else {
            // Development with swift run: supply the tested virtual environment.
            guard let path = ProcessInfo.processInfo.environment["TESLA_GUI_PYTHON"],
                  FileManager.default.isExecutableFile(atPath: path) else {
                status = "Build the .app using scripts/build-app.sh, or set TESLA_GUI_PYTHON for development."
                return
            }
            job.executableURL = URL(fileURLWithPath: path)
            job.arguments = [resources.appendingPathComponent("gui_bridge.py").path, input.path, output.path]
        }
        if scan { job.arguments!.append("--scan") }
        var environment = ProcessInfo.processInfo.environment
        // Do not forward Python injection/search-path environment overrides.
        for key in environment.keys.filter({ $0.hasPrefix("PYTHON") || $0 == "TESLA_GUI_PYTHON" }) {
            environment.removeValue(forKey: key)
        }
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        job.environment = environment
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        job.standardInput = stdin
        job.standardOutput = stdout
        job.standardError = stderr
        // Never display raw stderr; the bridge sends sanitized errors as JSON.
        stderr.fileHandleForReading.readabilityHandler = { handle in
            if handle.availableData.isEmpty { handle.readabilityHandler = nil }
        }
        let eventReader = EventReader { [weak self] event in
            Task { @MainActor in self?.receive(event) }
        }
        reader = eventReader
        stdout.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            else { eventReader.append(data) }
        }
        job.terminationHandler = { [weak self] task in
            Task { @MainActor in
                self?.busy = false
                self?.process = nil
                if task.terminationStatus != 0 && task.terminationStatus != 130 {
                    self?.status = "Finished with errors. Review the results below and scan again before retrying."
                }
            }
        }
        log = []
        status = scan ? "Scanning drive…" : "Decrypting clips…"
        fraction = 0
        handled = 0
        initialPending = pending
        busy = true
        process = job
        do {
            try job.run()
            if !scan {
                let payload = try JSONSerialization.data(withJSONObject: ["token": token])
                try stdin.fileHandleForWriting.write(contentsOf: payload + Data([10]))
                // Token stays only in the worker for this run.
                token = ""
            }
            try stdin.fileHandleForWriting.close()
        } catch {
            if job.isRunning { job.terminate() }
            busy = false
            process = nil
            status = "Could not start the local worker. Check the Python installation and app setup."
        }
    }

    func cancel() {
        process?.terminate() // Bridge turns SIGTERM into cleanup-aware interruption.
        status = "Stopping after cleanup…"
    }

    private func receive(_ event: [String: Any]) {
        guard let kind = event["kind"] as? String else { return }
        if let counts = event["counts"] as? [String: Int] {
            pending = counts["pending", default: 0]
            if kind == "scan" {
                scanDescription = "\(counts["encrypted", default: 0]) encrypted · \(counts["existing", default: 0]) existing · \(counts["plaintext", default: 0]) plain · \(counts["failed", default: 0]) failed"
                initialPending = pending
                status = "Scan complete: \(pending) clips ready."
            } else {
                fraction = 1
                status = "\(counts["decrypted", default: 0]) decrypted · \(counts["keys", default: 0]) keys obtained · \(counts["failed", default: 0]) failed · \(counts["existing", default: 0]) skipped"
                log.append(status)
            }
        }
        if let message = event["message"] as? String {
            log.append(message)
            if log.count > 500 { log.removeFirst(log.count - 500) }
            if message.hasPrefix("Decrypted ") || message.hasPrefix("No key ") || message.hasPrefix("Decryption/validation failed ") {
                handled += 1
                fraction = min(1, Double(handled) / Double(max(1, initialPending)))
            }
            if kind == "cancelled" || kind == "error" { status = message }
        }
    }
}

private final class EventReader {
    private var buffer = Data()
    private let lock = NSLock()
    private let deliver: ([String: Any]) -> Void
    init(deliver: @escaping ([String: Any]) -> Void) { self.deliver = deliver }
    func append(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        buffer.append(data)
        while let newline = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<newline])
            buffer.removeSubrange(...newline)
            if let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                deliver(object)
            }
        }
    }
}
