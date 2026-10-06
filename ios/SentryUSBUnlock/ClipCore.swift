import Foundation
import CryptoKit
import CommonCrypto
import Darwin

enum ClipError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case let .invalid(message) = self { return message }; return nil }
}

struct ClipHeader: Codable, Equatable {
    let id: String
    let vin: String
    let key_id: UInt64
    let timestamp: UInt64
    let wrapped_key: String
    let public_key: String
}
struct Clip: Identifiable {
    let source: URL
    let relative: String
    let header: ClipHeader
    let size: UInt64
    var id: String { source.path }
}
struct Inventory {
    var clips: [Clip] = []
    var plaintext = 0
    var failures: [String] = []
}

// Native port of the upstream-derived paging algorithm. All writes are staged.
enum ClipCore {
    static let pageSize = 4096
    static func integer(_ data: Data, _ range: Range<Int>) throws -> UInt64 {
        guard range.upperBound <= data.count else { throw ClipError.invalid("Truncated file header") }
        return data[range].reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
    }
    static func readHeader(_ source: URL) throws -> (ClipHeader, UInt64) {
        let file = try FileHandle(forReadingFrom: source)
        defer { try? file.close() }
        let data = try file.read(upToCount: 8192) ?? Data()
        guard data.count == 8192,
              try integer(data, 20..<24) == 4096,
              try integer(data, 4096..<4100) > 0,
              data[4100] == 4 else { throw ClipError.invalid("Unsupported encrypted clip header") }
        let size = try integer(data, 0..<8)
        let fileSize = try source.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= UInt64(max(0, fileSize - 8192)),
              size / 4096 + (size % 4096 == 0 ? 0 : 1) <= UInt64(max(0, fileSize - 8192) / 4096) else {
            throw ClipError.invalid("Truncated encrypted clip")
        }
        let hex = data[4..<20].map { String(format: "%02x", $0) }.joined()
        let chars = Array(hex)
        let id = [0..<8,8..<12,12..<16,16..<20,20..<32].map { String(chars[$0]) }.joined(separator: "-")
        guard let vin = String(data: data[4165..<4182], encoding: .ascii), vin.count == 17 else {
            throw ClipError.invalid("Invalid vehicle metadata")
        }
        return (ClipHeader(id: id, vin: vin, key_id: try integer(data, 4096..<4100),
                           timestamp: try integer(data, 4182..<4190),
                           wrapped_key: data[4190..<4234].base64EncodedString(),
                           public_key: data[4100..<4165].base64EncodedString()), size)
    }
    static func checkFirstBox(_ data: Data) throws {
        guard data.count >= 16, data[4..<8] == Data("ftyp".utf8) else {
            throw ClipError.invalid("Decryption did not produce an MP4")
        }
        let size = try integer(data, 0..<4)
        guard size >= 16, size <= UInt64(data.count), (size - 16) % 4 == 0 else {
            throw ClipError.invalid("Invalid MP4 header")
        }
    }
    static func validateMP4(_ source: URL) throws {
        let file = try FileHandle(forReadingFrom: source)
        defer { try? file.close() }
        let length = try file.seekToEnd()
        try file.seek(toOffset: 0)
        try checkFirstBox(file.read(upToCount: 4096) ?? Data())
        var offset: UInt64 = 0
        var boxes = Set<String>()
        while offset < length {
            try file.seek(toOffset: offset)
            let header = try file.read(upToCount: 8) ?? Data()
            guard header.count == 8 else { throw ClipError.invalid("Truncated MP4 box") }
            var size = try integer(header, 0..<4)
            var minimum: UInt64 = 8
            if size == 1 {
                size = try integer(file.read(upToCount: 8) ?? Data(), 0..<8)
                minimum = 16
            } else if size == 0 { size = length - offset }
            guard size >= minimum, size <= length - offset else { throw ClipError.invalid("Invalid MP4 box bounds") }
            boxes.insert(String(data: header[4..<8], encoding: .ascii) ?? "")
            offset += size
        }
        guard Set(["ftyp", "moov", "mdat"]).isSubset(of: boxes) else {
            throw ClipError.invalid("MP4 is missing required media boxes")
        }
    }
    static func scan(_ root: URL) throws -> Inventory {
        var inventory = Inventory()
        let keys: [URLResourceKey] = [.isRegularFileKey, .isSymbolicLinkKey, .isDirectoryKey]
        var scanError: Error?
        guard let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: keys,
                         options: [.skipsHiddenFiles], errorHandler: { _, error in scanError = error; return false }) else {
            throw ClipError.invalid("Cannot read the selected folder")
        }
        for case let url as URL in enumerator {
            try Task.checkCancellation()
            let values = try url.resourceValues(forKeys: Set(keys))
            if values.isSymbolicLink == true { enumerator.skipDescendants(); continue }
            guard values.isRegularFile == true, url.pathExtension.lowercased() == "mp4" else { continue }
            let relative = String(url.path.dropFirst(root.path.count + 1))
            do {
                let file = try FileHandle(forReadingFrom: url)
                let probe = try file.read(upToCount: 16) ?? Data()
                try file.close()
                if probe.count >= 8, probe[4..<8] == Data("ftyp".utf8) {
                    try validateMP4(url)
                    inventory.plaintext += 1
                } else {
                    let (header, size) = try readHeader(url)
                    inventory.clips.append(Clip(source: url, relative: relative, header: header, size: size))
                }
            } catch { inventory.failures.append("\(relative): unsupported or damaged clip") }
        }
        if scanError != nil { throw ClipError.invalid("Drive became unavailable while scanning") }
        inventory.clips.sort { $0.relative < $1.relative }
        return inventory
    }
    static func batches(_ clips: [Clip]) -> [[Clip]] {
        var result: [[Clip]] = [], current: [Clip] = [], ids = Set<String>()
        for clip in clips {
            if current.count == 20 || ids.contains(clip.header.id) {
                result.append(current); current = []; ids = []
            }
            current.append(clip); ids.insert(clip.header.id)
        }
        if !current.isEmpty { result.append(current) }
        return result
    }
    static func decryptPage(_ ciphertext: Data, key: Data, page: Int) throws -> Data {
        guard key.count == 16, ciphertext.count == 4096 else { throw ClipError.invalid("Invalid key or encrypted page") }
        var material = Data(Insecure.MD5.hash(data: key))
        material.append(contentsOf: String(page).utf8)
        guard material.count <= 32 else { throw ClipError.invalid("Page index out of bounds") }
        material.append(Data(repeating: 0, count: 32 - material.count))
        let iv = Data(Insecure.MD5.hash(data: material))
        var output = [UInt8](repeating: 0, count: ciphertext.count)
        var written = 0
        let status = key.withUnsafeBytes { keyBytes in
            iv.withUnsafeBytes { ivBytes in
                ciphertext.withUnsafeBytes { encrypted in
                    output.withUnsafeMutableBytes { plaintext in
                        CCCrypt(CCOperation(kCCDecrypt), CCAlgorithm(kCCAlgorithmAES), CCOptions(0),
                                keyBytes.baseAddress, 16, ivBytes.baseAddress, encrypted.baseAddress,
                                ciphertext.count, plaintext.baseAddress, plaintext.count, &written)
                    }
                }
            }
        }
        guard status == kCCSuccess, written == 4096 else { throw ClipError.invalid("AES decryption failed") }
        return Data(output)
    }
    static func identity(_ source: URL) throws -> String {
        let values = try FileManager.default.attributesOfItem(atPath: source.path)
        return [values[.systemNumber], values[.systemFileNumber], values[.size], values[.modificationDate]]
            .map { String(describing: $0) }.joined(separator: ":")
    }
    static func process(_ clip: Clip, key: Data, outputRoot: URL?, replace: Bool) throws -> Bool {
        // Coordinate external Files-provider access before opening or replacing.
        guard replace || outputRoot != nil else { throw ClipError.invalid("Choose an output folder") }
        let destination = replace ? clip.source : outputRoot!.appendingPathComponent(clip.relative)
        let coordinator = NSFileCoordinator(filePresenter: nil)
        var coordinationError: NSError?
        var result: Result<Bool, Error>?
        coordinator.coordinate(writingItemAt: destination, options: replace ? .forReplacing : [],
                               error: &coordinationError) { coordinatedURL in
            result = Result { try writeValidated(clip, key: key, destination: coordinatedURL, replace: replace) }
        }
        if let error = coordinationError { throw error }
        guard let result else { throw ClipError.invalid("Files access could not be coordinated") }
        return try result.get()
    }
    static func writeValidated(_ clip: Clip, key: Data, destination: URL, replace: Bool) throws -> Bool {
        try Task.checkCancellation()
        let fm = FileManager.default
        let before = try identity(clip.source)
        let (header, size) = try readHeader(clip.source)
        guard header == clip.header, size == clip.size else { throw ClipError.invalid("Clip changed; scan again") }
        let parent = destination.deletingLastPathComponent()
        if !replace {
            // Never write through a symlink, including a nested destination.
            var current = parent
            while current.path != "/" {
                if (try? current.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true {
                    // Apple's /var alias is used by file coordination on macOS/iOS.
                    guard current.path == "/var", current.resolvingSymlinksInPath().path == "/private/var" else {
                        throw ClipError.invalid("Destination contains a symlink")
                    }
                }
                current.deleteLastPathComponent()
            }
            try fm.createDirectory(at: parent, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            if fm.fileExists(atPath: destination.path) {
                guard (try destination.resourceValues(forKeys: [.isSymbolicLinkKey])).isSymbolicLink != true else {
                    throw ClipError.invalid("Existing output is a symlink")
                }
                try validateMP4(destination)
                let existing = try destination.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? -1
                guard existing >= 0, UInt64(existing) == size else { throw ClipError.invalid("Existing output has the wrong size") }
                return false
            }
        }
        let storage = try fm.attributesOfFileSystem(forPath: parent.path)
        guard let free = storage[.systemFreeSize] as? NSNumber, free.uint64Value >= size else {
            throw ClipError.invalid("Not enough space for one temporary decrypted clip")
        }
        let temp = parent.appendingPathComponent(".sentry-unlock-\(UUID().uuidString).mp4")
        guard fm.createFile(atPath: temp.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
            throw ClipError.invalid("Cannot write to the selected drive")
        }
        defer { try? fm.removeItem(at: temp) }
        let input = try FileHandle(forReadingFrom: clip.source)
        defer { try? input.close() }
        let output = try FileHandle(forWritingTo: temp)
        defer { try? output.close() }
        try input.seek(toOffset: 8192)
        var written: UInt64 = 0, page = 0
        while written < size {
            try Task.checkCancellation()
            let encrypted = try input.read(upToCount: 4096) ?? Data()
            var plaintext = try decryptPage(encrypted, key: key, page: page)
            if page == 0 { try checkFirstBox(plaintext) }
            let remaining = size - written
            if remaining < UInt64(plaintext.count) { plaintext = plaintext.prefix(Int(remaining)) }
            try output.write(contentsOf: plaintext)
            written += UInt64(plaintext.count); page += 1
        }
        try output.synchronize()
        try output.close()
        try validateMP4(temp)
        guard try identity(clip.source) == before else { throw ClipError.invalid("Source changed during decryption") }
        try Task.checkCancellation()
        if replace {
            if let modified = try? clip.source.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate {
                try fm.setAttributes([.modificationDate: modified], ofItemAtPath: temp.path)
            }
            guard Darwin.rename(temp.path, destination.path) == 0 else { throw ClipError.invalid("Could not replace the encrypted clip") }
        } else {
            // Exclusive same-volume publication. Fails safely without hardlinks.
            guard Darwin.link(temp.path, destination.path) == 0 else { throw ClipError.invalid("Cannot publish output; use the app's local folder or USB replacement mode") }
        }
        return true
    }
}

final class NoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
enum TeslaKeys {
    static func fetch(_ batch: [Clip], token: String) async throws -> [String: Data] {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil; config.urlCache = nil
        config.timeoutIntervalForRequest = 30
        let session = URLSession(configuration: config, delegate: NoRedirect(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: URL(string: "https://dashcam.tesla.com/api/1/decrypt/batch")!)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("https://dashcam.tesla.com", forHTTPHeaderField: "Origin")
        request.setValue("https://dashcam.tesla.com/", forHTTPHeaderField: "Referer")
        struct Payload: Encodable { let items: [ClipHeader] }
        request.httpBody = try JSONEncoder().encode(Payload(items: batch.map(\.header)))
        let requested = Set(batch.map { $0.header.id })
        guard requested.count == batch.count else { throw ClipError.invalid("Duplicate clip IDs in request") }
        for attempt in 0..<4 {
            try Task.checkCancellation()
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw ClipError.invalid("Invalid Tesla response") }
            if [429,502,503,504].contains(http.statusCode), attempt < 3 {
                try await Task.sleep(nanoseconds: UInt64(1 << attempt) * 1_000_000_000); continue
            }
            guard http.statusCode == 200 else { throw ClipError.invalid("Tesla key request failed (HTTP \(http.statusCode)). Sign in again if needed.") }
            guard let object = try JSONSerialization.jsonObject(with: data) as? [String:Any],
                  let results = object["results"] as? [[String:Any]] else { throw ClipError.invalid("Invalid key response") }
            var keys: [String:Data] = [:], seen = Set<String>()
            for result in results {
                guard let id = result["id"] as? String, requested.contains(id), !seen.contains(id) else {
                    throw ClipError.invalid("Unrequested or duplicate key response")
                }
                seen.insert(id)
                if let error = result["error"], !(error is NSNull) {
                    let noError = (error as? String) == "" || (error as? NSNumber)?.doubleValue == 0
                    if !noError { continue }
                }
                guard let value = result["key"] as? String, let key = Data(base64Encoded: value), key.count == 16 else {
                    throw ClipError.invalid("Invalid AES key")
                }
                keys[id] = key
            }
            return keys
        }
        throw ClipError.invalid("Tesla key request failed")
    }
}
