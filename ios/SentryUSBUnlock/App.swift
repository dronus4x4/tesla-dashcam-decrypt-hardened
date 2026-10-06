import SwiftUI
import UniformTypeIdentifiers
import UIKit

@main
struct SentryUSBUnlockApp: App {
    @StateObject private var model = UnlockModel()
    @Environment(\.scenePhase) private var phase
    var body: some Scene {
        WindowGroup {
            UnlockView(model: model)
                .onChange(of: phase) { _, value in
                    if value == .background { model.cancel(); model.token = "" }
                }
        }
    }
}

@MainActor
final class UnlockModel: ObservableObject {
    @Published var input: URL?
    @Published var replace = false
    @Published var token = ""
    @Published var inventory: Inventory?
    @Published var busy = false
    @Published var status = "Select the TeslaCam folder on your USB drive."
    @Published var messages: [String] = []
    @Published var completed = 0
    @Published var total = 0
    private var scoped = false
    private var job: Task<Void, Never>?
    var output: URL { FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Unlocked Clips", isDirectory: true) }
    var normalizedToken: String {
        let value = token.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.hasPrefix("Bearer ") ? String(value.dropFirst(7)) : value
    }
    var canDecrypt: Bool { !busy && !(inventory?.clips.isEmpty ?? true) && !normalizedToken.isEmpty }
    func select(_ url: URL) {
        guard !busy else { return }
        if scoped, let input { input.stopAccessingSecurityScopedResource() }
        input = url; scoped = url.startAccessingSecurityScopedResource()
        reset()
    }
    func reset() { inventory = nil; status = "Folder or output mode changed — scan again."; messages = [] }
    func begin(_ message: String) {
        busy = true; status = message; messages = []; completed = 0; total = 0
        UIApplication.shared.isIdleTimerDisabled = true
    }
    func finish() { busy = false; UIApplication.shared.isIdleTimerDisabled = false; job = nil }
    func append(_ message: String) { messages.append(message); if messages.count > 500 { messages.removeFirst(messages.count - 500) } }
    func cancel() { job?.cancel() }
    func scan() {
        guard !busy, let root = input else { return }
        begin("Scanning…")
        job = Task.detached { [weak self] in
            do {
                let found = try ClipCore.scan(root)
                try Task.checkCancellation()
                await self?.scanned(found)
            } catch { await self?.failed(error, operation: "Scan") }
            await self?.finish()
        }
    }
    private func scanned(_ found: Inventory) {
        inventory = found
        status = "\(found.clips.count) encrypted · \(found.plaintext) readable · \(found.failures.count) unreadable"
        messages = Array(found.failures.prefix(500))
    }
    private func failed(_ error: Error, operation: String) {
        if error is CancellationError { status = "Cancelled. Scan again to resume." }
        else if let error = error as? ClipError { status = error.localizedDescription }
        else { status = "\(operation) failed. Check USB access and connection, then scan again." }
        inventory = nil
    }
    func decrypt() {
        guard canDecrypt, let found = inventory, let root = input else { return }
        let secret = normalizedToken
        guard secret.utf8.count <= 16000, secret.unicodeScalars.allSatisfy({ $0.value >= 33 && $0.value <= 126 }) else {
            status = "Paste only the temporary Tesla token."; return
        }
        let replacing = replace, destination = output
        if !replacing {
            let a = root.standardizedFileURL.path, b = destination.standardizedFileURL.path
            guard a != b, !a.hasPrefix(b + "/"), !b.hasPrefix(a + "/") else { status = "Input and output folders must be separate."; return }
        }
        token = ""; begin("Requesting keys from Tesla…"); total = found.clips.count
        job = Task.detached { [weak self] in
            var success = 0, skipped = 0, failures = 0
            do {
                for batch in ClipCore.batches(found.clips) {
                    try Task.checkCancellation()
                    let keys = try await TeslaKeys.fetch(batch, token: secret)
                    for clip in batch {
                        try Task.checkCancellation()
                        guard let key = keys[clip.header.id] else {
                            failures += 1
                            await self?.record("No key returned: \(clip.relative)")
                            continue
                        }
                        do {
                            let created = try ClipCore.process(clip, key: key, outputRoot: replacing ? nil : destination, replace: replacing)
                            if created { success += 1 } else { skipped += 1 }
                            await self?.record("\(created ? "Unlocked" : "Already saved"): \(clip.relative)")
                        } catch is CancellationError { throw CancellationError() }
                        catch {
                            failures += 1
                            let reason = (error as? ClipError)?.localizedDescription ?? "Check drive access, free space and connection"
                            await self?.record("Failed: \(clip.relative) — \(reason)")
                        }
                    }
                }
                await self?.done(success: success, skipped: skipped, failures: failures)
            } catch { await self?.failed(error, operation: "Unlock") }
            await self?.finish()
        }
    }
    private func record(_ message: String) { completed += 1; status = "Unlocking \(completed) of \(total)…"; append(message) }
    private func done(success: Int, skipped: Int, failures: Int) {
        status = "Finished: \(success) unlocked · \(skipped) already saved · \(failures) failed."
        inventory = nil
    }
}

struct UnlockView: View {
    @ObservedObject var model: UnlockModel
    @State private var selecting = false
    @State private var signingIn = false
    @State private var confirming = false
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Unlock your Tesla USB footage", systemImage: "externaldrive.fill")
                    Text("Connect the drive to your iPhone or iPad while parked. Keep this app open and the drive connected during processing.").font(.footnote).foregroundStyle(.secondary)
                }
                Section("1. Choose your USB folder") {
                    Button("Select TeslaCam folder…") { selecting = true }.disabled(model.busy)
                    if let root = model.input { Text(root.lastPathComponent).font(.footnote) }
                    Toggle("Replace encrypted clips on USB", isOn: $model.replace).disabled(model.busy)
                        .onChange(of: model.replace) { _, _ in model.reset() }
                    Text(model.replace ? "No encrypted backup is kept. The USB needs space for one temporary clip." : "Copies are saved to Files → On My iPhone/iPad → Sentry USB Unlock → Unlocked Clips.").font(.footnote).foregroundStyle(.secondary)
                    Button("Scan drive") { model.scan() }.disabled(model.busy || model.input == nil)
                }
                Section("2. Sign in to Tesla") {
                    Button("Sign in with Tesla…") { signingIn = true }.disabled(model.busy)
                    DisclosureGroup("Paste a temporary token instead") {
                        SecureField("Tesla Dashcam token", text: $model.token)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().disabled(model.busy)
                        Text("If Tesla blocks this app's browser, obtain a temporary token on your Mac using the repository guide. Mobile sign-in is experimental.").font(.footnote).foregroundStyle(.secondary)
                    }
                    if !model.normalizedToken.isEmpty { Label("Token ready for this session", systemImage: "checkmark.circle"); Button("Forget token") { model.token = "" }.disabled(model.busy) }
                }
                Section("3. Unlock") {
                    Button(model.replace ? "Unlock clips on USB" : "Save unlocked copies") {
                        if model.replace { confirming = true } else { model.decrypt() }
                    }.disabled(!model.canDecrypt)
                    if model.busy {
                        if model.total > 0 { ProgressView(value: Double(model.completed), total: Double(model.total)) }
                        else { ProgressView() }
                        Button("Cancel", role: .cancel) { model.cancel() }
                    }
                    Text(model.status).font(.callout)
                }
                if !model.messages.isEmpty {
                    Section("Results") { ForEach(Array(model.messages.enumerated()), id: \.offset) { _, message in Text(message).font(.caption).textSelection(.enabled) } }
                }
                Section {
                    Text("Footage stays on your device. Tesla receives clip identifiers and vehicle metadata to release keys. No analytics or saved tokens.").font(.footnote).foregroundStyle(.secondary)
                    Text("Sentry USB Unlock 0.1.0 (1) · Independent project, not affiliated with Tesla.").font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Sentry USB Unlock")
            .fileImporter(isPresented: $selecting, allowedContentTypes: [.folder]) { result in
                if case let .success(url) = result { model.select(url) }
            }
            .sheet(isPresented: $signingIn) {
                NavigationStack {
                    VStack(alignment: .leading) {
                        Text("Sign in, then select one encrypted clip on Tesla's website to capture its temporary token.").font(.footnote).padding()
                        TeslaSignInView { value in model.token = value; signingIn = false }
                        Text("Tesla may block this embedded browser. No login bypass is provided.").font(.footnote).padding()
                    }
                    .navigationTitle("Tesla sign-in").navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { signingIn = false } } }
                }
            }
            .alert("Replace encrypted originals?", isPresented: $confirming) {
                Button("Cancel", role: .cancel) {}
                Button("Replace \(model.inventory?.clips.count ?? 0) clips", role: .destructive) { model.decrypt() }
            } message: { Text("Selected folder: \(model.input?.lastPathComponent ?? "")\nNo encrypted backup is kept. Completed replacements remain if you cancel. Copy the USB first if you want a backup.") }
        }
    }
}
