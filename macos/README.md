# Tesla Dashcam Decryptor for macOS

## TL;DR

1. **First time:** install Python 3.10+ and Swift 5.9+ tools, then follow [First-time setup](#first-time-setup) below. Build the app on the Mac where you will use it.
2. Plug in the drive. Open the app and choose its **TeslaCam** folder.
3. Choose **copies on your Mac** or **Replace encrypted clips on the USB**. Replacement keeps no encrypted backup.
4. Click **Scan drive**. Sign in with Tesla, or use the [manual token fallback](#manual-token-fallback-firefox-or-chrome) if the embedded sign-in is blocked.
5. Click **Decrypt all**. Watch **processed / remaining / failed**. The completed scan is reused; already-plain clips are skipped.
6. To stop, click **Stop decrypting** and wait for cleanup. To resume later, scan and sign in again. Completed replacements stay completed.

**Updating an existing checkout:** stop any active job, wait for cleanup, quit the app, then paste this into a normal Terminal window:

```bash
cd ~/tesla-dashcam-decrypt-hardened
git pull --ff-only
bash macos/scripts/build-app.sh
open "macos/dist/Tesla Dashcam Decryptor.app"
```

Run each line after the previous one succeeds. No `sudo` or GitHub login is needed. These commands assume you originally cloned into your home folder. If you used another location, change the `cd` line. Scan and sign in again after reopening. You do not have to stop a successful run merely because an update exists; you can let it finish and update afterwards.


SwiftUI interface for the hardened Python decryptor. macOS 13+, Xcode Command Line Tools (Swift 5.9+) and an installed Python 3.10+ are required. No Python package needs to be installed globally.

## First-time setup

These steps start from a normal Terminal window. You do not need to have downloaded the project already.

### 1. Open Terminal

Open **Finder → Applications → Utilities → Terminal**, or search for **Terminal** with Spotlight.

Copy only the commands inside the code blocks below. Do not copy the Terminal prompt.

### 2. Check the two requirements

Run these commands:

```bash
python3 --version
swift --version
```

You need **Python 3.10 or newer** and **Swift 5.9 or newer**.

- If Python is missing or older than 3.10, install a current Python 3 release from [Python's official macOS downloads page](https://www.python.org/downloads/macos/). Close Terminal, reopen it, and check the version again.
- If Swift is missing, run `xcode-select --install` and complete the Command Line Tools installation. If the command reports that the tools are already installed but Swift is too old, update the tools through Software Update or install a suitable Xcode version.
- Wait for installations to finish before continuing.

### 3. Download the project

Copy and paste this block into Terminal:

```bash
cd ~
git clone https://github.com/dronus4x4/tesla-dashcam-decrypt-hardened.git
```

This creates a folder named **tesla-dashcam-decrypt-hardened** in your home folder. No GitHub sign-in is needed to download this public repository.

If Terminal says that the destination folder already exists, do not delete it. Continue to the next step if it is an existing checkout of this project; use the update instructions below when needed.

### 4. Build the app

Copy and paste this block:

```bash
cd ~/tesla-dashcam-decrypt-hardened
bash macos/scripts/build-app.sh
```

Wait for it to finish. It downloads the required Python packages and builds the app. Success ends with a line beginning **Built:**.

If an error appears, stop here. The app may not have been created, so running the next command will not fix the error.

### 5. Open the app

After the build succeeds, run:

```bash
open ~/tesla-dashcam-decrypt-hardened/macos/dist/"Tesla Dashcam Decryptor.app"
```

For future launches, use Finder to open your home folder, then **tesla-dashcam-decrypt-hardened → macos → dist**, and double-click **Tesla Dashcam Decryptor.app**. You can drag the app to the Dock for convenient access.

You only need to build again when updating the app. Keep the Python installation used to build it.

### Common setup errors

| Message | What it means | What to do |
| --- | --- | --- |
| `macos/scripts/build-app.sh: No such file or directory` | The project is missing or Terminal is in the wrong folder. | Complete steps 3 and 4, including the `cd` command. |
| `requirements.txt: No such file or directory` | Terminal is outside the project folder. | Run `cd ~/tesla-dashcam-decrypt-hardened` first. |
| `Could not find Package.swift` | A development command was run outside the Mac project folder. | Use step 4 to build the app. The development commands further below are optional. |
| `destination path ... already exists` | The download folder is already present. | Use the existing checkout; do not repeat the clone or delete the folder. |
| The app does not exist | The build did not finish successfully. | Check the build error before attempting to open the app. |

When requesting help, share the build error, but remove personal usernames, computer names and private paths. Never share a Tesla token.

## Updating an existing installation

Stop an active scan/decryption with **Stop decrypting**, wait for the worker to exit, and quit the app before rebuilding. Completed files remain. Then open Terminal and go to the project folder:

```bash
cd ~/tesla-dashcam-decrypt-hardened
git pull --ff-only
```

If the update succeeds, rebuild and then open the app using steps 4 and 5. If Git reports local changes or a merge problem, stop and resolve that before rebuilding.

## About this build

This is a local development app. The build script creates a Python virtual environment inside the app and links it to Python installed on the building Mac. Retain that Python installation. The app is locally ad hoc signed, not notarized. A build from a CI runner is not a portable installer for another Mac.

## Use

1. Plug in your Tesla USB/SSD.
2. **Select Tesla drive…**: choose **TeslaCam** inside the drive. Selecting this folder avoids protected system folders at the drive root. You can also select a specific clip subfolder to process a smaller batch.
3. Choose the output mode: leave **Replace encrypted clips on the USB** off and select a destination on your Mac, or turn it on to replace files on the selected drive.
4. **Scan drive**: offline inventory; no token or network request. The status first shows files being found, then **Checking clips: X of Y**. Encrypted ownership metadata is read once per file. Already-plain inputs are classified by their MP4 ftyp header and left untouched; this is not a full playback/integrity check. New decrypted outputs and existing destination files still undergo full MP4 structure checks. Large folders and slow USB devices can take time.
5. **Sign in with Tesla**: sign into Tesla's real Dashcam website in a temporary WebKit window. Select one encrypted clip there so the website makes its normal key request. The app observes the Bearer header on that exact decryption endpoint and keeps the token in memory.
6. **Decrypt all**: reuses the completed scan; readable clips are not rescanned. Each pending encrypted source is checked against its scanned identity and header immediately before writing, and validated before publication. New files added since scanning wait for the next scan. The main status shows processed and remaining counts, with decrypted/replaced/failed totals below it. Results follow new entries automatically; turn off **Follow latest results** to read older entries. **Stop decrypting** or **Command + .** requests cleanup; wait for the worker to exit before ejecting. Quitting waits for worker cleanup. USB replacement mode asks you to confirm the selected folder and clip count first.
7. **Show destination** opens the output folder or selected drive. Safely eject the drive when finished.

The app does not generate a Tesla credential independently. Tesla issues the token when you authenticate. Embedded sign-in, MFA/passkeys, the web file picker and automatic token capture require real-Mac/live-Tesla testing; website changes or Tesla restrictions can break them. No endpoint or login bypass is implemented.

### Manual token fallback (Firefox or Chrome)

Use this if Tesla reports that the embedded browser is blocking required security tools.

1. Open [dashcam.tesla.com](https://dashcam.tesla.com) in Firefox or Chrome and sign in.
2. Open developer tools: **Firefox → Tools → Browser Tools → Web Developer Tools**, or **Chrome → View → Developer → Developer Tools**.
3. In the panel that opens, click **Network**. Do this before choosing a clip so the key request is recorded.
4. On the Tesla webpage, click **Browse Files** and select one encrypted `.mp4` from the USB. Wait until the webpage decrypts it.
5. In the **Network** panel, find the request whose address ends in **`/api/1/decrypt/batch`**. If there are many entries, type **`decrypt`** into the Network filter. If no request appears, leave Network open and select a different encrypted clip.
6. Click that request, click **Headers**, and look under **Request Headers** for **Authorization**. Its value begins with **`Bearer `**.
7. Copy only the long value **after** `Bearer `, without quotes or extra spaces.
8. Return to the app. Expand **Paste a temporary token instead** and paste into the hidden token field, then click **Decrypt all**.

The token is a temporary account credential. Never post it in screenshots/chat/issues, put it in a shell command or save it in this repository. The app clears the visible token after starting a job; **Not connected** during an active job therefore does not mean that decryption has lost authorization. A new token is needed for another job. If Tesla rejects authorization, sign in again and rescan before retrying.

### Stop, resume and read the results

- **Stop decrypting** also stops a scan. Wait until the app says the worker has exited before closing it or ejecting the USB.
- For replacement mode, resume by scanning the same folder and signing in again. Completed clips are now plain, so they are skipped. A clip interrupted before replacement remains encrypted and can be retried.
- For copy mode, select the same source and destination again; valid existing outputs are skipped.
- **Follow latest results** scrolls to new entries. Turn it off to read older messages. The UI keeps the most recent 500 messages.
- **Plain** means an input has a recognised MP4 header, not that the app decoded and verified its video. **Existing** means a destination output passed the skip checks. **Failed** means a clip/request could not be processed; read its message before retrying.
- When finished, check some output clips in a video player, then safely eject through Finder.


## Replacing encrypted clips on the USB

The checkbox is **off by default**. Changing output mode resets the scan, so scan again before decrypting.

Each encrypted clip is decrypted into a temporary file in the same folder. The app validates the MP4, flushes it and replaces the encrypted file at its original path. Filenames, folder placement and timestamps are preserved. Failures before replacement leave the original encrypted clip intact. Completed replacements remain readable if a later clip fails or you cancel; already-readable MP4s are skipped when you run again.

No separate destination or hardlinks are needed, so a writable exFAT Tesla drive can be used. The drive needs free space for one temporary decrypted clip at a time.

**No encrypted backup is kept.** Copy the drive first if you want one. Keep the USB connected while processing and safely eject it afterwards. Power loss or unexpected removal can still corrupt a USB filesystem; normal error handling cannot provide a power-loss guarantee.

The app does not rewrite Tesla's event metadata or move clips between folders. Playback in the car's viewer after replacement is unverified; this does not promise to reproduce every part of Tesla's in-car unlock operation.

## Security and implementation

- Local worker is the existing hardened decryptor; a JSON-lines bridge conveys progress.
- Token crosses an anonymous stdin pipe, never command arguments, environment variables or logs.
- Token removed from the GUI after it is passed to a decryption job. A new sign-in/token is needed for another job. Python/Swift cannot guarantee erasure from memory.
- Temporary WebKit cookie storage; no persistent login or token cache. The page's token is observed only from the exact HTTPS Tesla Dashcam batch endpoint and main frame. No form/password/MFA-field inspection.
- Navigation allowed only to HTTPS Tesla domains. Third-party identity/verification pages may therefore fail; use the browser fallback instead of relaxing this silently.
- Sources remain read-only in separate-output mode. Optional replacement mode validates a same-directory temporary MP4 before replacing the original. Output permissions on exFAT depend on the filesystem and mount settings.
- Stop decrypting (also File menu / Command + .) signals the worker to clean up active temporary files; completed outputs remain. The button stays visible and is disabled when idle. Quitting waits for the worker to exit. Scans skip hidden system directories and Mac `._` metadata files.
- Last 500 progress messages remain in the UI only and can include local filenames. No analytics or remote server.
- The app is not sandboxed in this initial build. Folder pickers and scope lifetimes prepare for later sandboxing, but do not enforce least-privilege filesystem access in this build.
- The [native iOS beta](../ios/README.md) uses Swift decryption and Files access. Device/USB and live Tesla authentication testing remain required.

## Checks

The root Python tests exercise encryption/file handling. `test_gui_bridge.py` checks offline bridge behaviour, token transport, sanitized errors and interruption. A macOS CI workflow checks the Swift build and app assembly. Compile success does not prove that live sign-in or real Tesla clips work.

The bundled engine copy must exactly match the root script. Both the build script and bridge tests check that. After changing the core, copy it to `macos/Sources/TeslaDecryptGUI/Resources/tesla_dashcam_decrypt.py`.

Upstream attribution and licence declaration are in the root README and `README.upstream.md`.


## Optional: development mode

Most users should use the setup steps above. Developers can instead run the interface directly from the source folder:

```bash
cd ~/tesla-dashcam-decrypt-hardened
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd macos
TESLA_GUI_PYTHON="$PWD/../.venv/bin/python3" swift run
```

## Scan reuse and efficiency

The completed scan is held only in app memory and passed to the next worker through stdin, separately from the token. No scan inventory or token cache is saved to disk. Selecting different folders, changing output mode, starting a new scan, starting a decryption job or cancelling invalidates the inventory. A fresh scan is required after a job, including a partial/cancelled job. The backend rejects plans for another root, destination, mode or drive identity and unsafe relative paths.

Decryption reads the pending source metadata once for the safety check and passes the validated plaintext length to the paging routine. Existing readable clips are not revisited. Request batches fill from distinct clip-ID queues while retaining the unique-ID constraint; the batch limit is unchanged. HTTP 401/403 stops further requests instead of repeating a rejected token across the whole inventory. Large stdin inventories are written off the main thread, so the Stop button remains responsive.

### Decryption throughput and timings

The worker uses bounded 1 MB sequential reads and writes, with bulk AES processing that preserves the original 4 KB CBC page boundaries. Original files are still replaced only after validation and a successful disk flush. No parallel writers are enabled.

The token authorizes key requests; it does not decrypt the video bytes. The worker fetches keys in batches and decrypts locally, one file at a time. A large archive can still take hours. USB-C describes the connector and does not by itself establish transfer speed.

Every 20 processed clips, the results show cumulative timings for key requests (`keys`), decryption plus file reads/writes (`decrypt_io`), MP4 checks (`validation`), and disk flushes (`flush`). These counters use a monotonic clock; they do not sample the drive, write telemetry files, or disclose keys. Elapsed time also includes other file operations. They help identify the bottleneck on a particular Mac and USB drive.

An offline 32 MB synthetic benchmark on the development machine measured roughly four times faster decryption and buffered I/O than the previous loop. This is not a measured T7 or M4 Max speedup; overall gains depend on disk and flush latency.

Scanning uses directory-entry metadata to avoid repeated filesystem queries and reads only the ftyp box for plain input clips. It does not reopen and seek through every already-plain clip. Encrypted metadata and payload lengths are still checked, and full output validation remains mandatory before replacement.

For example:

```text
Timing (cumulative): elapsed 49.7s · keys 1.3s · decrypt_io 47.8s · validation 0.0s · flush 0.0s
```

| Field | What it measures |
| --- | --- |
| `elapsed` | Wall-clock time since this decryption job started, including other file operations. |
| `keys` | Time waiting for Tesla's key requests, including retries. |
| `decrypt_io` | Combined file reads, AES decryption, buffered writes and closing the temporary output. It does not isolate CPU from disk waiting. |
| `validation` | Checking the new MP4's container structure. |
| `flush` | The explicit disk-flush call before publishing. Some write waiting may already have occurred inside `decrypt_io`. |

Values accumulate across the job and are rounded to tenths of a second; `0.0s` is not proof that an operation took zero time. The synthetic benchmark above is not a guarantee of four-times-faster archive processing. To compare actual runs, use similar clips and compare timing lines over many files. No throughput test or extra drive scan is run while decrypting.
