import AppKit
import Foundation
import SwiftUI

@MainActor
final class DecryptModel: ObservableObject {
    @Published var input: URL?
    @Published var output: URL?
    @Published var token = ""
    @Published var replaceOriginals = false
    @Published var status = "Select your Tesla drive and a destination, then scan."
    @Published var log: [String] = []
    @Published var scanDescription = "Scan is offline."
    @Published var busy = false
    @Published var pending = 0
    @Published var fraction = 0.0
    @Published var workSummary = ""
    private var scanPlan: Data?
    private var scanRun = false
    private var activeRun = UUID()
    private var process: Process?
    private var reader: EventReader?
    private var initialPending = 0
    private var handled = 0
    private var quitCompletion: (() -> Void)?
    private var stopping = false
    private var inputScope = false
    private var outputScope = false
    var hasFolders: Bool { input != nil && (replaceOriginals || output != nil) }
    var resultFolder: URL? { replaceOriginals ? input : output }

    func modeChanged() {
        pending = 0
        scanPlan = nil
        scanDescription = "Output mode changed — scan again."
    }

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
        scanPlan = nil
        scanDescription = "Folders changed — scan again."
    }

    func run(scan: Bool) {
        guard !busy, hasFolders, let input else { return }
        var command: Data?
        if !scan {
            guard let scanPlan else { status = "Scan the selected folder before decrypting."; return }
            do {
                var data = try JSONSerialization.data(withJSONObject: ["token": token])
                data.append(10)
                data.append(scanPlan)
                data.append(10)
                command = data
            } catch { status = "Could not prepare the job. Scan again."; return }
        } else { scanPlan = nil }
        let runID = UUID()
        activeRun = runID
        scanRun = scan
        var workerArguments = [WorkerResources.directory.appendingPathComponent("gui_bridge.py").path, input.path]
        if replaceOriginals { workerArguments.append("--replace-originals") }
        else if let output { workerArguments.append(output.path) }
        let python = Bundle.main.resourceURL?.appendingPathComponent("python-runtime/bin/python3")
        let job = Process()
        if let python, FileManager.default.isExecutableFile(atPath: python.path) {
            job.executableURL = python
            job.arguments = workerArguments
        } else {
            // Development with swift run: supply the tested virtual environment.
            guard let path = ProcessInfo.processInfo.environment["TESLA_GUI_PYTHON"],
                  FileManager.default.isExecutableFile(atPath: path) else {
                status = "Build the .app using scripts/build-app.sh, or set TESLA_GUI_PYTHON for development."
                return
            }
            job.executableURL = URL(fileURLWithPath: path)
            job.arguments = workerArguments
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
            Task { @MainActor in
                guard self?.activeRun == runID else { return }
                self?.receive(event)
            }
        }
        reader = eventReader
        stdout.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            else { eventReader.append(data) }
        }
        job.terminationHandler = { [weak self] task in
            guard let model = self else { return }
            let code = task.terminationStatus
            Task { @MainActor in
                guard model.activeRun == runID else { return }
                model.busy = false
                model.process = nil
                if model.stopping {
                    model.pending = 0
                    model.scanPlan = nil
                    model.scanDescription = "Stopped — scan again to resume."
                    model.status = "Stopped. The worker has exited; you can now eject the USB in Finder."
                    model.stopping = false
                }
                if let completion = model.quitCompletion {
                    model.quitCompletion = nil
                    completion()
                }
                if !scan { model.pending = 0; model.scanPlan = nil }
                if code != 0 && code != 130 {
                    model.status = "Finished with errors. Review the results below and scan again before retrying."
                }
            }
        }
        log = []
        status = scan ? "Scanning drive…" : "Decrypting clips…"
        fraction = 0
        workSummary = ""
        handled = 0
        initialPending = pending
        busy = true
        process = job
        do {
            try job.run()
            if let command {
                token = ""
                scanPlan = nil // Single-use session inventory; never written to disk.
                let writer = stdin.fileHandleForWriting
                // Large inventories must not block the main thread or Stop button.
                DispatchQueue.global(qos: .userInitiated).async {
                    defer { try? writer.close() }
                    do { try writer.write(contentsOf: command) }
                    catch { if job.isRunning { job.terminate() } }
                }
            } else { try stdin.fileHandleForWriting.close() }

        } catch {
            if job.isRunning { job.terminate() }
            busy = false
            process = nil
            status = "Could not start the local worker. Check the Python installation and app setup."
        }
    }

    func stopBeforeQuit(_ completion: @escaping () -> Void) {
        quitCompletion = completion
        cancel()
    }

    func cancel() {
        guard busy, let process, process.isRunning else { return }
        guard !stopping else { return }
        stopping = true
        process.terminate() // Bridge turns SIGTERM into cleanup-aware interruption.
        status = "Stopping after cleanup…"
    }

    private func receive(_ event: [String: Any]) {
        guard let kind = event["kind"] as? String else { return }
        if kind == "plan", scanRun, let plan = event["plan"] as? [String: Any] {
            scanPlan = try? JSONSerialization.data(withJSONObject: plan)
            return
        }
        if kind == "scan_progress", let done = event["completed"] as? Int, let total = event["total"] as? Int {
            fraction = total > 0 ? Double(done) / Double(total) : 0
            status = "Checking clips: \(done) of \(total) — \(max(0, total - done)) remaining"
            return
        }
        if let counts = event["counts"] as? [String: Int] {
            if kind == "scan" {
                pending = counts["pending", default: 0]
                scanDescription = "\(counts["encrypted", default: 0]) encrypted · \(counts["existing", default: 0]) existing · \(counts["plaintext", default: 0]) unencrypted · \(counts["failed", default: 0]) failed"
                initialPending = pending
                fraction = scanRun ? 1 : 0
                status = scanRun ? "Scan complete: \(pending) clips ready." : "Requesting keys for \(pending) clips…"
            } else if kind == "work" {
                handled = counts["processed", default: 0]
                let total = counts["total", default: initialPending]
                pending = counts["pending", default: 0]
                fraction = Double(handled) / Double(max(1, total))
                status = "Decrypting: \(handled) of \(total) processed — \(pending) remaining"
                workSummary = "\(counts["decrypted", default: 0]) decrypted · \(counts["replaced", default: 0]) replaced · \(counts["failed", default: 0]) failed"
            } else if kind == "summary" {
                pending = 0
                scanPlan = nil
                fraction = 1
                status = "Finished: \(counts["decrypted", default: 0]) decrypted · \(counts["replaced", default: 0]) replaced · \(counts["failed", default: 0]) failed · \(counts["existing", default: 0]) skipped"
                workSummary = "0 remaining"
                log.append(status)
            }
        }
        if let message = event["message"] as? String {
            log.append(message)
            if log.count > 500 { log.removeFirst(log.count - 500) }

            if kind == "cancelled" || kind == "error" || message.hasPrefix("Finding MP4 clips") || message.hasPrefix("Using completed scan:") || message.hasPrefix("Decrypting ") { status = message }
        }
    }
}

private final class EventReader {
    private var buffer = Data()
    private var searchOffset = 0
    private let lock = NSLock()
    private let deliver: ([String: Any]) -> Void
    init(deliver: @escaping ([String: Any]) -> Void) { self.deliver = deliver }
    func append(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        buffer.append(data)
        while let newline = buffer[buffer.index(buffer.startIndex, offsetBy: searchOffset)...].firstIndex(of: 10) {
            let line = Data(buffer[..<newline])
            buffer.removeSubrange(...newline)
            searchOffset = 0
            if let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                deliver(object)
            }
        }
        searchOffset = buffer.count // Scan only newly received bytes next time.
    }
}
