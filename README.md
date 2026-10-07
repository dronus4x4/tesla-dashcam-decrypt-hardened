# Tesla Dashcam Decryptor — hardened local derivative

## TL;DR — start here

**Batch-unlock encrypted Tesla dashcam clips on your own computer. Video stays local; an internet connection and Tesla account authorization are needed to obtain keys.**

- **Mac users:** follow the [step-by-step Mac app guide](macos/README.md). Download the source, build the app, select **TeslaCam**, scan, sign in or paste a temporary token, then click **Decrypt all**.
- **Keep originals:** leave replacement off and choose a dedicated folder on your Mac for decrypted copies.
- **Unlock on the same USB:** enable **Replace encrypted clips on the USB**, scan and confirm. This replaces encrypted originals and keeps no encrypted backup.
- **Stop/resume:** click **Stop decrypting**, wait for cleanup, then quit or eject. On the next run, scan and sign in again; completed replacements are skipped.
- **Latest Mac improvements:** quicker scans, no second full scan when decrypting, bulk decryption, remaining counts, automatic results scrolling and timing information. Thousands of clips can still take hours; drive performance and clip sizes affect speed.
- **iPhone/iPad:** [Sentry USB Unlock 0.1.0 (build 1)](ios/README.md) is source code for a native beta. It is **not yet available through a public TestFlight link**; build/sign/upload instructions are included. Phone/USB/live authentication testing is still required.

No GitHub sign-in is needed to download this public repository. The Mac app currently needs to be built on the Mac where it will run; it is not a portable, notarized installer. Start with a copy of one clip and check playback before processing an archive.

Based on [XGxF3/tesla-dashcam-decrypt](https://github.com/XGxF3/tesla-dashcam-decrypt), upstream commit `aceb414dd1c54d558a921414bd8883fe97c8ba24`. Retains the upstream AES/eCryptfs page algorithm and ownership-metadata layout. Unofficial software, not affiliated with Tesla.

## macOS graphical app

The [Mac app guide](macos/README.md) covers first-time setup, updates, USB selection, browser token fallback, replacement, cancellation and interpreting progress. The GUI uses the hardened Python backend. Embedded Tesla sign-in can be rejected by Tesla; the manual browser-token route is included.

## Terminal alternative — Python command-line tool

If you prefer the graphical app, use the [Mac guide](macos/README.md) instead. For this Terminal workflow, install Python 3.10+ and download the repository first:

```bash
cd ~
git clone https://github.com/dronus4x4/tesla-dashcam-decrypt-hardened.git
cd tesla-dashcam-decrypt-hardened
```

If you already downloaded it, run `cd ~/tesla-dashcam-decrypt-hardened` instead of cloning again. All commands below run from that project folder.

Use an APFS output directory, such as a folder under your Mac's Movies directory. Input can remain on the Tesla USB. Output uses hardlinks to publish atomically; filesystems without that support fail safely. POSIX permissions do not protect plaintext on filesystems that ignore them.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -q test_hardening test_gui_bridge test_replacement test_scan_plan test_fast_decrypt
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

Obtain the temporary bearer token by signing into https://dashcam.tesla.com, loading one encrypted clip, and following the [browser-token steps in the Mac guide](macos/README.md#manual-token-fallback-firefox-or-chrome). Copy the value after `Bearer`. Treat it as a secret; do not send it in chat, save it in a command or commit it.

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
- Requests group distinct clip IDs into batches, preserving every discovered file even when IDs repeat.
- API result IDs and 16-byte keys validated; missing keys counted as failures.
- Bounded retries for 429/502/503/504; no API response bodies printed.
- Offline `--scan`/`--dry-run`: no authentication, requests or output writes.
- Rejects overlapping input/output trees and symlink output paths; discovery does not follow symlinks.
- Refuses malformed/truncated input and unsupported synthetic/unknown containers.
- Checks first decrypted page for `ftyp`, then validates top-level MP4 box boundaries and required `moov`/`mdat` boxes.
- Private temporary files; selected output directories restricted to `0700` and outputs to `0600`.
- Validates before publishing; separate-output mode never overwrites existing outputs. Optional `--replace-originals` replaces encrypted sources only after validation. Temporary files are cleaned on normal exceptions/interruption.
- Existing destination files skipped only after full MP4 checks (and expected length unless remuxing). Already-plain inputs get a quick ftyp header classification and remain untouched; scanning does not certify their playback or integrity.
- Reports processed/remaining/decrypted/replaced/failed counts; the GUI can follow the latest results. Exits nonzero on failures.
- The Mac GUI reuses a completed in-memory scan; independently launched CLI runs scan again.
- Bounded 1 MB I/O and bulk AES processing preserve Tesla's 4 KB CBC page format. No parallel writers are enabled.
- Cumulative stage timings every 20 processed clips help diagnose local throughput; HTTP 401/403 stops further key requests.
- ffmpeg receives MP4-suffixed private temporary paths and explicit MP4 output format; network protocols disabled.

## Privacy and limitations

Footage stays local. Tesla receives the clip ID, VIN, key ID, timestamp, wrapped key and public key, along with your bearer token. Decryption depends on Tesla's API and account authorization.

By default, original clips are opened for reading only and decrypted copies go to a separate destination. Optional `--replace-originals` replaces encrypted source files with validated plaintext at the same paths, with no encrypted backup. Keep a separate backup if originals must be retained. Already-plaintext input MP4s are counted and left in place, not copied.

MP4 structure checks detect many wrong-key/corruption cases but are not cryptographic authentication, video decoding or proof of ownership/source identity. Existing-output checks cannot prove that a file belongs to a particular input. Use a fresh dedicated destination per USB archive. The filesystem protections assume no hostile same-user process races changing directories or inputs during a run. Root and processes running as your user can read secrets/plaintext. A kill or power loss can leave `.tesla-*` temporary files; delete those only after stopping the process.

Automated tests use generated eCryptfs-style fixtures and mocked HTTP responses. CI builds the Mac GUI and unsigned iOS app. These checks do not establish live Tesla API compatibility, every real recording's playback, USB power-loss behaviour or actual ffmpeg execution. Test one real clip and check playback before trusting a full archive.

## Attribution and licence

Upstream README declares `MIT`. Upstream provides no separate LICENSE file or full copyright/permission notice at the pinned commit. The original README is retained as `README.upstream.md`, and `WRITEUP.md` is retained for attribution and provenance. No licence or copyright holder has been invented. Obtain the author's full MIT notice before a public release.

## iPhone and iPad beta

[Sentry USB Unlock 0.1.0 (build 1)](ios/README.md) provides a native Swift iOS project, USB folder selection, copy/replacement modes and TestFlight setup instructions. Device and live sign-in testing remain required.


The scan/decryption performance changes described above apply to the Python CLI and Mac app. The iOS app has its own native Swift implementation.
