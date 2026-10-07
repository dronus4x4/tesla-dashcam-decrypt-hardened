#!/usr/bin/env python3
"""
Tesla Dashcam Batch Decryptor
==============================
Decrypts Tesla 2026.20+ encrypted dashcam files locally.

Encryption scheme (reverse engineered from dashcam.tesla.com):
  - Each .mp4 is AES-128-CBC encrypted in 4096-byte pages
  - Each page IV is derived from MD5(MD5(file_key) + page_number)
  - The AES key is fetched from Tesla's API (tied to your account)
  - The file header contains the UUID and ownership metadata needed
    to request the per-file key

Usage:
  1. Get your Tesla auth token (see instructions below)
  2. Point the script at your TeslaCam USB folder
  3. Run it — decrypted MP4s land in the output folder

Getting your auth token:
  - Open dashcam.tesla.com in Chrome, log in
  - Open DevTools → Application → Cookies → dashcam.tesla.com
  - Copy the value of the cookie named "token" or "access_token"
  - Or: DevTools → Network → any /api/ request → Headers → Authorization: Bearer <TOKEN>
"""

import argparse
import base64
import hashlib
import getpass
import os
import shutil
import tempfile
import warnings
import subprocess
import struct
import sys
import time
from pathlib import Path

import requests
from Crypto.Cipher import AES

# ── Constants ──────────────────────────────────────────────────────────────────

TESLA_API_BASE    = "https://dashcam.tesla.com"
DECRYPT_BATCH_URL = f"{TESLA_API_BASE}/api/1/decrypt/batch"

CHUNK_SIZE        = 4096          # bytes of ciphertext per chunk
HEADER_SIZE       = 16            # IV prepended to synthetic fixture chunks
FULL_CHUNK        = CHUNK_SIZE + HEADER_SIZE  # 4112 bytes total

# UUID is stored as a 16-byte binary at this offset in the encrypted file header
# (first 36 bytes appear to be a magic + UUID in the custom Tesla container)
UUID_OFFSET       = 4            # bytes into the file where the 16-byte UUID lives

# Real Tesla 2026.20 files contain API ownership metadata in a 4096-byte header
# block, and encrypted media ciphertext starts at the next 4096-byte boundary.
EXTENDED_HEADER_OFFSET = 0x1000
REAL_CIPHERTEXT_OFFSET = 0x2000
KEY_ID_OFFSET          = EXTENDED_HEADER_OFFSET
PUBLIC_KEY_OFFSET      = KEY_ID_OFFSET + 4
PUBLIC_KEY_SIZE        = 65
VIN_OFFSET             = PUBLIC_KEY_OFFSET + PUBLIC_KEY_SIZE
VIN_SIZE               = 17
TIMESTAMP_SIZE         = 8
TIMESTAMP_OFFSET       = VIN_OFFSET + VIN_SIZE
WRAPPED_KEY_OFFSET     = TIMESTAMP_OFFSET + TIMESTAMP_SIZE
WRAPPED_KEY_SIZE       = 44


# ── Tesla API ──────────────────────────────────────────────────────────────────

def get_session(token: str) -> requests.Session:
    """Build an authenticated requests session."""
    s = requests.Session()
    s.trust_env = False  # Ignore environment proxies and .netrc credentials.
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Origin":        TESLA_API_BASE,
        "Referer":       f"{TESLA_API_BASE}/",
    })
    return s


def read_file_uuid(path: Path, *, probe: bytes | None = None) -> str:
    """
    Read the 16-byte UUID from the encrypted file header and return
    it formatted as a lowercase hyphenated UUID string.
    """
    if probe is None:
        with open(path, "rb") as f:
            f.seek(UUID_OFFSET)
            raw = f.read(16)
    else:
        raw = probe[UUID_OFFSET:UUID_OFFSET + 16]
    if len(raw) < 16:
        raise ValueError(f"File too short to contain UUID: {path}")
    # Interpret as UUID: 4-2-2-2-6 byte grouping (standard UUID layout)
    a = raw[0:4].hex()
    b = raw[4:6].hex()
    c = raw[6:8].hex()
    d = raw[8:10].hex()
    e = raw[10:16].hex()
    return f"{a}-{b}-{c}-{d}-{e}"


def _has_extended_header(path: Path, *, probe: bytes | None = None) -> bool:
    """Return True for real Tesla files with the 0x1000 metadata block."""
    if probe is None:
        with open(path, "rb") as f:
            probe = f.read(EXTENDED_HEADER_OFFSET + 4)

    if probe.startswith(b"TSLC"):
        return False
    if len(probe) < EXTENDED_HEADER_OFFSET + 4:
        return False

    metadata_offset = struct.unpack(">I", probe[0x14:0x18])[0]
    return metadata_offset == EXTENDED_HEADER_OFFSET and probe[KEY_ID_OFFSET:KEY_ID_OFFSET + 4] != b"\x00" * 4


def _read_real_plaintext_size(path: Path, *, probe: bytes | None = None) -> int:
    """Real Tesla files store the decrypted MP4 length as a big-endian uint64."""
    if probe is None:
        with open(path, "rb") as f:
            raw = f.read(8)
    else:
        raw = probe[:8]
    if len(raw) != 8:
        raise ValueError(f"File too short to contain plaintext size: {path}")
    size = struct.unpack(">Q", raw)[0]
    if size <= 0:
        raise ValueError(f"Invalid plaintext size in encrypted header: {path}")
    return size


def read_file_header(path: Path, *, probe: bytes | None = None) -> dict:
    """
    Read all fields needed for the decrypt API from the file header.
    Returns dict with keys: id, vin, key_id, timestamp, wrapped_key, public_key.
    Synthetic TSLC fixtures only contain the id, so they return that field alone.
    """
    if probe is None:
        with path.open("rb") as f:
            probe = f.read(WRAPPED_KEY_OFFSET + WRAPPED_KEY_SIZE)
    file_id = read_file_uuid(path, probe=probe)
    header = {"id": file_id}

    if not _has_extended_header(path, probe=probe):
        return header

    key_id_raw = probe[KEY_ID_OFFSET:KEY_ID_OFFSET + 4]
    public_key_raw = probe[PUBLIC_KEY_OFFSET:PUBLIC_KEY_OFFSET + PUBLIC_KEY_SIZE]
    vin_raw = probe[VIN_OFFSET:VIN_OFFSET + VIN_SIZE]
    timestamp_raw = probe[TIMESTAMP_OFFSET:TIMESTAMP_OFFSET + TIMESTAMP_SIZE]
    wrapped_key_raw = probe[WRAPPED_KEY_OFFSET:WRAPPED_KEY_OFFSET + WRAPPED_KEY_SIZE]

    if len(wrapped_key_raw) != WRAPPED_KEY_SIZE:
        raise ValueError(f"File too short to contain ownership metadata: {path}")

    vin = vin_raw.decode("ascii", errors="ignore").rstrip("\x00")
    if len(vin) != VIN_SIZE:
        raise ValueError(f"Invalid VIN in encrypted header: {path}")
    if not public_key_raw.startswith(b"\x04"):
        raise ValueError(f"Invalid public key in encrypted header: {path}")

    header.update({
        "vin": vin,
        "key_id": struct.unpack(">I", key_id_raw)[0],
        "timestamp": struct.unpack(">Q", timestamp_raw)[0],
        "wrapped_key": base64.b64encode(wrapped_key_raw).decode("ascii"),
        "public_key": base64.b64encode(public_key_raw).decode("ascii"),
    })
    return header


def _api_item_from_header(header: dict | str) -> dict:
    if isinstance(header, str):
        return {"id": header}

    required = ("id", "vin", "key_id", "timestamp", "wrapped_key", "public_key")
    if all(field in header for field in required):
        return {field: header[field] for field in required}
    return {"id": header["id"]}


def fetch_keys_batch(session: requests.Session, file_headers: list[dict] | list[str]) -> dict[str, bytes]:
    """
    POST to /api/1/decrypt/batch with file UUIDs and ownership metadata.
    Returns a dict mapping uuid -> raw AES key bytes.
    """
    payload = {"items": [_api_item_from_header(header) for header in file_headers]}
    requested = {item['id'] for item in payload['items']}
    if len(requested) != len(payload['items']):
        raise ValueError('Duplicate IDs in API batch')
    for attempt in range(4):
        resp = session.post(DECRYPT_BATCH_URL, json=payload, timeout=(10, 30),
                            allow_redirects=False)
        if resp.status_code in (429, 502, 503, 504) and attempt < 3:
            time.sleep(2 ** attempt)
            continue
        break
    if resp.status_code != 200:
        # Do not display response bodies, which may contain sensitive metadata.
        raise RuntimeError(f'Tesla API returned HTTP {resp.status_code}')

    data = resp.json()
    keys = {}
    if not isinstance(data, dict) or not isinstance(data.get('results'), list):
        raise ValueError('Invalid API response structure')
    seen = set()
    for result in data['results']:
        uid = result["id"]
        if uid not in requested or uid in seen:
            raise ValueError('Unrequested or duplicate ID in API response')
        seen.add(uid)
        if result.get("error"):
            continue
        raw_key = base64.b64decode(result["key"], validate=True)
        if len(raw_key) != 16:
            raise ValueError('Tesla key is not AES-128')
        keys[uid] = raw_key
    return keys


# ── Decryption ─────────────────────────────────────────────────────────────────

def _decrypt_real_file(src: Path, dst: Path, key_bytes: bytes) -> int:
    """
    Decrypt a real Tesla 2026.20 encrypted clip.

    Tesla's browser decrypts the payload as 4096-byte eCryptfs pages. Each page
    uses AES-CBC with IV = md5(md5(file_key) + ascii(page_number) + zero padding).
    """
    target_size = _read_real_plaintext_size(src)
    root_iv = hashlib.md5(key_bytes).digest()
    written = 0

    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fin.seek(REAL_CIPHERTEXT_OFFSET)
        page = 0
        while written < target_size:
            encrypted_page = fin.read(CHUNK_SIZE)
            if not encrypted_page:
                break
            if len(encrypted_page) != CHUNK_SIZE:
                raise ValueError(f"Encrypted page is not 4096 bytes: {src}")

            iv_material = bytearray(32)
            iv_material[:len(root_iv)] = root_iv
            page_bytes = str(page).encode("ascii")
            iv_material[len(root_iv):len(root_iv) + len(page_bytes)] = page_bytes
            derived_iv = hashlib.md5(iv_material).digest()

            plaintext = AES.new(key_bytes, AES.MODE_CBC, derived_iv).decrypt(encrypted_page)
            remaining = target_size - written
            if remaining < len(plaintext):
                plaintext = plaintext[:remaining]
            if page == 0:
                check_ftyp(plaintext)
            fout.write(plaintext)
            written += len(plaintext)
            page += 1

    if written != target_size:
        raise ValueError(f"Decrypted output shorter than expected: {src}")
    return written


def remux_mp4(src: Path, dst: Path) -> None:
    """Losslessly remux an MP4 through ffmpeg to rewrite container metadata."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-protocol_whitelist",
            "file",
            "-y",
            "-i",
            str(src),
            "-c",
            "copy",
            "-movflags",
            "faststart",
            "-f",
            "mp4",
            str(dst),
        ],
        check=True,
        timeout=300,
        capture_output=True,
        text=True,
    )


# Hardened local workflow; the paging algorithm above remains upstream-derived.

def check_ftyp(data: bytes) -> None:
    if len(data) < 16 or data[4:8] != b"ftyp":
        raise ValueError("Decrypted data does not start with an MP4 ftyp box")
    size = struct.unpack(">I", data[:4])[0]
    if size < 16 or size > len(data) or (size - 16) % 4:
        raise ValueError("Invalid MP4 ftyp box")


def validate_mp4(path: Path) -> None:
    """Check top-level MP4 box boundaries; not cryptographic authentication."""
    length = path.stat().st_size
    boxes = set()
    with path.open("rb") as f:
        check_ftyp(f.read(CHUNK_SIZE))
        offset = 0
        while offset < length:
            f.seek(offset)
            header = f.read(8)
            if len(header) != 8:
                raise ValueError("Truncated MP4 box")
            size, kind = struct.unpack(">I4s", header)
            minimum = 8
            if size == 1:
                extended = f.read(8)
                if len(extended) != 8:
                    raise ValueError("Truncated extended MP4 box")
                size = struct.unpack(">Q", extended)[0]
                minimum = 16
            elif size == 0:
                size = length - offset
            if size < minimum or offset + size > length:
                raise ValueError("MP4 box extends outside file")
            boxes.add(kind)
            offset += size
    if not {b"ftyp", b"moov", b"mdat"}.issubset(boxes):
        raise ValueError("MP4 is missing ftyp, moov or mdat")


def private_directory(path: Path) -> None:
    """Require real directories; restrict the selected output tree to its owner."""
    if path.is_symlink():
        raise ValueError("Output directories must not be symlinks")
    if not path.exists():
        private_directory(path.parent)
        path.mkdir(mode=0o700)
    if not path.is_dir():
        raise ValueError("Output path is not a directory")


def safe_output(src: Path, dst: Path, key: bytes, remux=False, output_root=None) -> int:
    """Publish validated plaintext atomically without overwriting existing files."""
    private_directory(dst.parent)
    current = dst.parent
    while True:
        os.chmod(current, 0o700)
        if output_root is None or current == output_root:
            break
        current = current.parent
    fd, name = tempfile.mkstemp(prefix=".tesla-", suffix=".mp4", dir=dst.parent)
    os.close(fd)
    tmp = Path(name)
    remux_tmp = None
    try:
        written = _decrypt_real_file(src, tmp, key)
        validate_mp4(tmp)
        if remux:
            fd, name = tempfile.mkstemp(prefix=".tesla-remux-", suffix=".mp4", dir=dst.parent)
            os.close(fd)
            remux_tmp = Path(name)
            remux_mp4(tmp, remux_tmp)
            validate_mp4(remux_tmp)
            tmp.unlink()
            tmp = remux_tmp
        os.chmod(tmp, 0o600)
        with tmp.open("rb") as f:
            os.fsync(f.fileno())
        # APFS/ext4 support atomic, no-clobber hardlinks. Unsupported output
        # filesystems fail safely; encrypted sources are always untouched.
        os.link(tmp, dst)
        return written
    finally:
        tmp.unlink(missing_ok=True)
        if remux_tmp is not None:
            remux_tmp.unlink(missing_ok=True)


def collision_safe_batches(items, size):
    batch, seen = [], set()
    for item in items:
        uid = item[0]["id"]
        if len(batch) == size or uid in seen:
            yield batch
            batch, seen = [], set()
        batch.append(item)
        seen.add(uid)
    if batch:
        yield batch


def safe_replace(src: Path, key: bytes, expected_header=None) -> int:
    """Validate a same-directory temporary MP4 before replacing its source.

    Does not require hardlinks (unlike separate-output publishing), and does
    not chmod source directories. Power-loss guarantees depend on the USB FS.
    """
    if src.is_symlink() or not src.is_file():
        raise ValueError("Source must be a regular file")
    before = src.stat()
    if expected_header is not None and read_file_header(src) != expected_header:
        raise ValueError("Source header changed after scanning; scan again")
    target_size = _read_real_plaintext_size(src)
    if shutil.disk_usage(src.parent).free < target_size:
        raise ValueError("USB needs enough free space for one decrypted clip")
    fd, name = tempfile.mkstemp(prefix=".tesla-", suffix=".mp4", dir=src.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        written = _decrypt_real_file(src, tmp, key)
        validate_mp4(tmp)
        with tmp.open("rb") as output:
            os.fsync(output.fileno())
        current = src.stat()
        identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
        if src.is_symlink() or identity(current) != identity(before):
            raise ValueError("Source changed during decryption; scan again")
        os.utime(tmp, ns=(before.st_atime_ns, before.st_mtime_ns))
        # Single same-filesystem replacement: originals are never unlinked first.
        os.replace(tmp, src)
        return written
    finally:
        tmp.unlink(missing_ok=True)


def find_encrypted_files(root: Path, progress=None) -> list[Path]:
    """Discover regular MP4s without following directory/file symlinks."""
    found = []
    reported = time.monotonic()
    def failed(exc):
        raise exc
    for parent, directories, files in os.walk(root, followlinks=False, onerror=failed):
        directories[:] = sorted(d for d in directories if not d.startswith(".") and not (Path(parent) / d).is_symlink())
        for name in sorted(files):
            if name.startswith("._"):
                continue
            path = Path(parent) / name
            if path.suffix.lower() == ".mp4" and not path.is_symlink() and path.is_file():
                found.append(path)
        if progress is not None and time.monotonic() - reported >= 0.5:
            progress(len(found))
            reported = time.monotonic()
    return sorted(found)


def prompt_token():
    if not sys.stdin.isatty():
        raise ValueError("Run in an interactive Terminal for secure token entry")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        token = getpass.getpass("Tesla Dashcam token (hidden): ").strip()
    if token.startswith("Bearer "):
        token = token[7:].strip()
    if not token or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Invalid token format")
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(description="Decrypt Tesla clips locally with safe outputs")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path, nargs="?")
    parser.add_argument("--replace-originals", action="store_true",
                        help="Replace validated encrypted clips in place; no encrypted backup kept")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--dry-run", "--scan", dest="dry_run", action="store_true",
                        help="Offline scan; no token prompt, API calls or output writes")
    parser.add_argument("--remux", action="store_true", help="Remux using installed ffmpeg")
    args = parser.parse_args(argv)
    if args.replace_originals and (args.output_dir is not None or args.remux):
        parser.error("--replace-originals takes no output directory and cannot be combined with --remux")
    if not args.replace_originals and args.output_dir is None:
        parser.error("provide an output directory, or explicitly select --replace-originals")
    if not 1 <= args.batch_size <= 100:
        parser.error("batch size must be between 1 and 100")
    root = args.input_dir.expanduser().resolve(strict=True)
    if not root.is_dir():
        parser.error("input must be a directory")
    # Inspect the lexical destination before resolve() can hide symlinks.
    output = None
    if not args.replace_originals:
        output = Path(os.path.abspath(args.output_dir.expanduser()))
        if any(p.is_symlink() for p in (output, *output.parents)):
            parser.error("output path must not contain symlinks")
        output = output.resolve()
        if output == root or output in root.parents or root in output.parents:
            parser.error("input and output directory trees must not overlap")
    counts = dict(examined=0, encrypted=0, plaintext=0, existing=0,
                  keys=0, decrypted=0, replaced=0, failed=0, pending=0)
    items = []
    print("Finding MP4 clips…")
    all_files = find_encrypted_files(root, progress=lambda n: print(f"Finding MP4 clips… {n} found"))
    total = len(all_files)
    reported = time.monotonic()
    print(f"Checking clips: 0 of {total}")
    for src in all_files:
        counts["examined"] += 1
        rel = src.relative_to(root)
        dst = src if args.replace_originals else output / rel
        try:
            with src.open("rb") as f:
                probe = f.read(WRAPPED_KEY_OFFSET + WRAPPED_KEY_SIZE)
            if probe[4:8] == b"ftyp":
                validate_mp4(src)
                counts["plaintext"] += 1
                continue
            if not _has_extended_header(src, probe=probe):
                raise ValueError("Unsupported or malformed encrypted container")
            size = _read_real_plaintext_size(src, probe=probe)
            needed = REAL_CIPHERTEXT_OFFSET + ((size + CHUNK_SIZE - 1) // CHUNK_SIZE) * CHUNK_SIZE
            if src.stat().st_size < needed:
                raise ValueError("Truncated encrypted payload")
            header = read_file_header(src, probe=probe)
            counts["encrypted"] += 1
            if args.replace_originals:
                items.append((header, src, src))
                continue
            if any(p.is_symlink() for p in (dst, *dst.parents)):
                raise ValueError("Destination contains a symlink")
            if dst.exists():
                if not dst.is_file():
                    raise ValueError("Destination is not a regular file")
                validate_mp4(dst)
                if not args.remux and dst.stat().st_size != size:
                    raise ValueError("Existing output has wrong size; move it aside to retry")
                counts["existing"] += 1
                continue
            items.append((header, src, dst))
        except (OSError, ValueError) as exc:
            print(f"Failed {str(rel)!r}: {exc}")
            counts["failed"] += 1
        finally:
            if counts["examined"] == total or time.monotonic() - reported >= 0.5:
                print(f"Checking clips: {counts['examined']} of {total}")
                reported = time.monotonic()
    counts["pending"] = len(items)
    print("Scan:", counts)
    if args.dry_run or not items:
        return 1 if counts["failed"] else 0
    if args.replace_originals:
        print("Replacement mode: validated plaintext will replace encrypted clips; no encrypted backup is kept.")
    print("Footage stays local. Tesla receives clip ID, VIN, key ID, timestamp, wrapped key and public key.")
    token = prompt_token()
    session = get_session(token)
    del token
    try:
        for batch in collision_safe_batches(items, args.batch_size):
            try:
                keys = fetch_keys_batch(session, [h for h, _, _ in batch])
            except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
                print("Key request failed; this batch was not decrypted. Check network/token and retry.")
                counts["failed"] += len(batch)
                counts["pending"] -= len(batch)
                continue
            for header, src, dst in batch:
                counts["pending"] -= 1
                key = keys.get(header["id"])
                if key is None:
                    counts["failed"] += 1
                    print(f"No key returned for {str(src.relative_to(root))!r}")
                    continue
                counts["keys"] += 1
                try:
                    # No persistent key cache. All outputs start as private temps.
                    if args.replace_originals:
                        safe_replace(src, key, expected_header=header)
                        counts["replaced"] += 1
                    else:
                        safe_output(src, dst, key, args.remux, output)
                    counts["decrypted"] += 1
                    print(f"Decrypted {str(src.relative_to(root))!r}")
                except (OSError, ValueError, subprocess.SubprocessError):
                    counts["failed"] += 1
                    print(f"Decryption/validation failed for {str(src.relative_to(root))!r}; no output published")
    finally:
        session.headers.pop("Authorization", None)
        session.close()
    print("Results:", counts)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted. Completed outputs retained; rerun to resume.", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError, getpass.GetPassWarning) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
