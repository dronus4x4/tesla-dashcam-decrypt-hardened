import Foundation

@main
struct CoreSmoke {
    static func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
        if try !condition() { throw ClipError.invalid("Test failed: \(message)") }
    }
    static func rejected(_ body: () throws -> Void) throws {
        do { try body() } catch { return }
        throw ClipError.invalid("Test failed: operation should reject")
    }
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1]).resolvingSymlinksInPath()
        let source = root.appendingPathComponent("input")
        let output = root.appendingPathComponent("output")
        let inventory = try ClipCore.scan(source)
        try require(inventory.clips.count == 2 && inventory.failures.isEmpty, "scan ignores AppleDouble")
        try require(ClipCore.batches(inventory.clips).map(\.count) == [1,1], "collision-safe batches")
        let clip = inventory.clips[0]
        let original = try Data(contentsOf: clip.source)
        let key = try Data(contentsOf: root.appendingPathComponent("key.bin"))
        let expected = try Data(contentsOf: root.appendingPathComponent("plain.bin"))
        let destination = output.appendingPathComponent(clip.relative)
        try require(ClipCore.process(clip, key: key, outputRoot: output, replace: false), "publish")
        try require(Data(contentsOf: destination) == expected, "native AES golden roundtrip")
        try require(Data(contentsOf: clip.source) == original, "copy retains source")
        try require(!ClipCore.process(clip, key: key, outputRoot: output, replace: false), "existing output skip")
        try rejected { _ = try ClipCore.process(clip, key: Data(repeating: 88, count: 16), outputRoot: nil, replace: true) }
        try require(Data(contentsOf: clip.source) == original, "wrong key retains encrypted source")
        try require(FileManager.default.contentsOfDirectory(atPath: source.path).allSatisfy { !$0.hasPrefix(".sentry-unlock-") }, "temporary cleanup")
        try require(ClipCore.process(clip, key: key, outputRoot: nil, replace: true), "replace")
        try require(Data(contentsOf: clip.source) == expected, "replacement contents")
        let rescan = try ClipCore.scan(source)
        try require(rescan.plaintext == 1 && rescan.clips.count == 1, "resume scan skips plain")
        let remaining = rescan.clips[0]
        var changed = try Data(contentsOf: remaining.source)
        changed[4200] ^= 1
        try changed.write(to: remaining.source)
        try rejected { _ = try ClipCore.process(remaining, key: key, outputRoot: nil, replace: true) }
        try require(Data(contentsOf: remaining.source) == changed, "changed header retained")
        print("Native checks passed: golden AES, copy, replacement, wrong key, cleanup, resume, changed source, ID collisions, hidden metadata.")
    }
}
