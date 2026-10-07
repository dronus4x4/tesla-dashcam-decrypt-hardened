# Tesla Dashcam Decryptor — hardened local derivative

Based on [XGxF3/tesla-dashcam-decrypt](https://github.com/XGxF3/tesla-dashcam-decrypt), upstream commit `aceb414dd1c54d558a921414bd8883fe97c8ba24`. Retains the upstream AES/eCryptfs page algorithm and ownership-metadata layout. Unofficial software, not affiliated with Tesla.

## macOS graphical app

The first native Mac interface is in [macos/](macos/README.md): drive and destination pickers, offline scan, temporary Tesla sign-in, hidden token fallback, batch progress and cancellation. See its README to build the local development `.app`. Embedded Tesla sign-in and real recordings still require testing on your Mac; this is not a portable/notarized release or an iOS app.

## Mac setup

Python 3.10+ required. Use an APFS output directory, such as a folder under your Mac's Movies directory. Input can remain on the Tesla USB. Output uses hardlinks to publish atomically; filesystems without that support fail safely. POSIX permissions do not protect plaintext on filesystems that ignore them.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v test_hardening
```

Dependencies, including transitive packages, are pinned to the versions used in local testing. Pins are not an independent dependency security audit or a hash-verified lockfile. Review updates periodically.

First scan, entirely offline:

```bash
python tesla_dashcam_decrypt.py /Volumes/TESLA/TeslaCam ~/Movies/Tesla-Decrypted --scan
```

Then decrypt:

```bash
python tesla_dashcam_decrypt.py /Volumes/TESLA/TeslaCam ~/Movies/Tesla-Decrypted
```

Replace `/Volumes/TESLA` with your actual drive name. Paste the token only into the hidden interactive Terminal prompt. There is deliberately no `--token`, environment-token, or on-disk token option. Noninteractive input and terminals unable to hide entry are rejected. Python cannot guarantee erasure of secrets from process memory.

Obtain the temporary bearer token by signing into https://dashcam.tesla.com, loading one encrypted clip, and using browser developer tools → Network → the decryption API request → Authorization header. Copy the value after `Bearer`. Treat it as a secret; do not send it in chat, save it in a command or commit it.

`--batch-size N` defaults to 20 (range 1–100). `--remux` optionally uses your installed ffmpeg to losslessly remux after decryption. Remux output size can differ from the source's plaintext length, so resumed runs with `--remux` check structure rather than exact size.

## Optional: replace encrypted files on the USB

The GUI has a **Replace encrypted clips on the USB** checkbox, off by default. Select it, scan again, then confirm replacement when clicking **Decrypt all**. A separate output folder is not required in this mode.

From Terminal:

```bash
python tesla_dashcam_decrypt.py /Volumes/TESLA/TeslaCam --replace-originals --scan
python tesla_dashcam_decrypt.py /Volumes/TESLA/TeslaCam --replace-originals
```

Each clip decrypts into a temporary file beside its source. The temporary MP4 is validated and flushed before a same-filesystem replacement. Wrong keys, insufficient space and failures before replacement leave the encrypted source intact. Already-plaintext clips are skipped on subsequent scans. No hardlinks are required, so this mode supports writable exFAT USB drives. Keep the drive connected throughout and safely eject it afterwards.

This changes the USB and keeps no encrypted backup. It requires free space for one temporary plaintext clip at a time. It preserves filenames, folders and timestamps, but does not rewrite Tesla event metadata; compatibility with the car's viewer is unverified. Filesystem corruption or power loss during a rename cannot be eliminated by the program, especially on non-journaled USB filesystems. Make a backup if you need recovery beyond the app's normal failure handling. This option cannot be combined with a destination folder or `--remux`.

## Changes

- Hidden token prompt; no token logged or saved by the program.
- HTTPS requests to the fixed Tesla endpoint; no redirects; ignores environment proxies and `.netrc`.
- Clip ID collisions split into separate requests, preserving every discovered file.
- API result IDs and 16-byte keys validated; missing keys counted as failures.
- Bounded retries for 429/502/503/504; no API response bodies printed.
- Offline `--scan`/`--dry-run`: no authentication, requests or output writes.
- Rejects overlapping input/output trees and symlink output paths; discovery does not follow symlinks.
- Refuses malformed/truncated input and unsupported synthetic/unknown containers.
- Checks first decrypted page for `ftyp`, then validates top-level MP4 box boundaries and required `moov`/`mdat` boxes.
- Private temporary files; selected output directories restricted to `0700` and outputs to `0600`.
- Validates before publishing; separate-output mode never overwrites existing outputs. Optional `--replace-originals` replaces encrypted sources only after validation. Temporary files are cleaned on normal exceptions/interruption.
- Existing files skipped only after MP4 checks (and expected length unless remuxing).
- Reports examined/encrypted/plaintext/existing/keys/decrypted/failed/pending counts; exits nonzero on failures.
- ffmpeg receives MP4-suffixed private temporary paths and explicit MP4 output format; network protocols disabled.

## Privacy and limitations

Footage stays local. Tesla receives the clip ID, VIN, key ID, timestamp, wrapped key and public key, along with your bearer token. Decryption depends on Tesla's API and account authorization.

By default, original clips are opened for reading only and decrypted copies go to a separate destination. Optional `--replace-originals` replaces encrypted source files with validated plaintext at the same paths, with no encrypted backup. Keep a separate backup if originals must be retained. Already-plaintext input MP4s are counted and left in place, not copied.

MP4 structure checks detect many wrong-key/corruption cases but are not cryptographic authentication, video decoding or proof of ownership/source identity. Existing-output checks cannot prove that a file belongs to a particular input. Use a fresh dedicated destination per USB archive. The filesystem protections assume no hostile same-user process races changing directories or inputs during a run. Root and processes running as your user can read secrets/plaintext. A kill or power loss can leave `.tesla-*` temporary files; delete those only after stopping the process.

Automated tests use generated eCryptfs-style fixtures and mocked HTTP responses. They do not verify the live Tesla API, real vehicle recordings, macOS filesystem behaviour or actual ffmpeg execution. Test one real clip and check playback before trusting a full archive.

## Attribution and licence

Upstream README declares `MIT`. Upstream provides no separate LICENSE file or full copyright/permission notice at the pinned commit. The original README is retained as `README.upstream.md`, and `WRITEUP.md` is retained for attribution and provenance. No licence or copyright holder has been invented. Obtain the author's full MIT notice before a public release.

## iPhone and iPad beta

[Sentry USB Unlock 0.1.0 (build 1)](ios/README.md) provides a native Swift iOS project, USB folder selection, copy/replacement modes and TestFlight setup instructions. Device and live sign-in testing remain required.

The Mac GUI reuses its session-only completed scan for decryption, checks each pending source for changes before writing, reports processed/remaining counts and offers optional automatic results scrolling. Requests with duplicate clip IDs are filled from distinct-ID queues to avoid prematurely small batches. Authentication rejection stops further requests. The CLI continues to scan on each independent invocation; no disk inventory/token cache is introduced.
