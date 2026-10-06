import AppKit
import SwiftUI

@MainActor
struct TeslaDecryptApp: App {
    @StateObject private var model = DecryptModel()
    var body: some Scene {
        WindowGroup("Tesla Dashcam Decryptor") {
            ContentView(model: model)
                .frame(minWidth: 680, minHeight: 560)
        }
    }
}

@MainActor
struct ContentView: View {
    @ObservedObject var model: DecryptModel
    @State private var showSignIn = false
    @State private var confirmReplacement = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Image(systemName: "externaldrive.fill").font(.largeTitle)
                VStack(alignment: .leading) {
                    Text("Tesla Dashcam Decryptor").font(.title2.bold())
                    Text("Decrypt your USB footage on this Mac.").foregroundStyle(.secondary)
                }
                Spacer()
            }
            GroupBox("Folders") {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Button("Select Tesla drive…") { model.pickFolder(input: true) }
                        Text(model.input?.path ?? "Choose your drive or TeslaCam folder")
                            .lineLimit(1).truncationMode(.middle)
                    }
                    HStack {
                        Button("Select destination…") { model.pickFolder(input: false) }
                        Text(model.output?.path ?? "Choose a separate folder on your Mac")
                            .lineLimit(1).truncationMode(.middle)
                    }.disabled(model.replaceOriginals)
                    Toggle("Replace encrypted clips on the USB", isOn: $model.replaceOriginals)
                        .onChange(of: model.replaceOriginals) { _ in model.modeChanged() }
                    if model.replaceOriginals {
                        Text("Decrypted clips replace the encrypted originals. No encrypted backup is kept. The USB needs room for one temporary clip.")
                            .font(.caption).foregroundStyle(.orange)
                    }
                }.padding(8)
            }.disabled(model.busy)
            HStack {
                Button("Scan drive") { model.run(scan: true) }
                    .disabled(model.busy || !model.hasFolders)
                Text(model.scanDescription).font(.callout).foregroundStyle(.secondary)
            }
            GroupBox("Tesla sign-in") {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Button("Sign in with Tesla…") { showSignIn = true }
                        Label(model.token.isEmpty ? "Not connected" : "Token ready for this session",
                              systemImage: model.token.isEmpty ? "person.crop.circle" : "checkmark.shield")
                        Spacer()
                        if !model.token.isEmpty { Button("Forget token") { model.token = "" } }
                    }
                    DisclosureGroup("Paste a temporary token instead") {
                        SecureField("Tesla Dashcam bearer token", text: $model.token)
                            .textFieldStyle(.roundedBorder).padding(.top, 6)
                    }
                    Text("Video stays on your Mac. Tesla receives clip identifiers and ownership metadata to release keys.")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(8)
            }.disabled(model.busy)
            HStack {
                Button("Decrypt all") {
                    if model.replaceOriginals { confirmReplacement = true }
                    else { model.run(scan: false) }
                }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.busy || !model.hasFolders || model.token.isEmpty || model.pending == 0)
                if model.busy { Button("Cancel") { model.cancel() } }
                Spacer()
                if let output = model.resultFolder {
                    Button("Show destination") { NSWorkspace.shared.open(output) }
                }
            }
            if model.busy { ProgressView(value: model.fraction).progressViewStyle(.linear) }
            Text(model.status).font(.callout).textSelection(.enabled)
            ScrollView {
                Text(model.log.joined(separator: "\n")).font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
            }.frame(maxHeight: .infinity)
            Text(model.replaceOriginals
                 ? "Keep a separate backup if you need the encrypted originals. Safely eject the USB when finished."
                 : "Original clips are read only. Use an APFS destination. Keep originals until playback is checked.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(24)
        .onDisappear { model.cancel(); model.token = "" }
        .alert("Replace encrypted clips on this USB?", isPresented: $confirmReplacement) {
            Button("Replace encrypted clips", role: .destructive) { model.run(scan: false) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will replace \(model.pending) encrypted clips in \(model.input?.path ?? "the selected folder") with readable MP4s. Each clip is validated first. No encrypted backup is kept. Failed clips are not replaced.")
        }
        .sheet(isPresented: $showSignIn) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Sign in at Tesla’s Dashcam website").font(.headline)
                Text("After signing in, select one encrypted clip on the website. The app captures the token used for that key request. This temporary browser session is discarded when closed.")
                    .font(.callout)
                TeslaSignInView { token in
                    model.token = token
                    model.status = "Tesla token received. You can now decrypt the scanned clips."
                    showSignIn = false
                }
                HStack {
                    Text("If Tesla declines this embedded browser, use the manual token field.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Close") { showSignIn = false }
                }
            }.padding(18).frame(width: 850, height: 700)
        }
    }
}
