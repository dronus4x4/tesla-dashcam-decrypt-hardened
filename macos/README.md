# macOS GUI — first development version

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

First open Terminal and go to the project folder:

```bash
cd ~/tesla-dashcam-decrypt-hardened
git pull --ff-only
```

If the update succeeds, rebuild and then open the app using steps 4 and 5. If Git reports local changes or a merge problem, stop and resolve that before rebuilding.

## About this build

This is a local development app. The build script creates a Python virtual environment inside the app and links it to Python installed on the building Mac. Retain that Python installation. The app is locally ad hoc signed, not notarized. A build from a CI runner is not a portable installer for another Mac.

## Use

1. Plug in your Tesla USB/SSD.
2. **Select Tesla drive**: choose the drive or its TeslaCam folder.
3. **Select destination**: choose a new separate folder on your Mac's APFS disk.
4. **Scan drive**: offline inventory; no token or network request.
5. **Sign in with Tesla**: sign into Tesla's real Dashcam website in a temporary WebKit window. Select one encrypted clip there so the website makes its normal key request. The app observes the Bearer header on that exact decryption endpoint and keeps the token in memory.
6. **Decrypt all**: batch processing, progress and results.
7. Play one result before trusting a large archive. **Show destination** opens Finder.

The app does not generate a Tesla credential independently. Tesla issues the token when you authenticate. Embedded sign-in, MFA/passkeys, the web file picker and automatic token capture require real-Mac/live-Tesla testing; website changes or Tesla restrictions can break them. No endpoint or login bypass is implemented.

If embedded sign-in fails, use the official dashcam site in your normal browser and paste its temporary token into the app's **Paste a temporary token instead** secure field. This fallback still requires extracting a token from browser developer tools as described in the root README.

## Security and implementation

- Local worker is the existing hardened decryptor; a JSON-lines bridge conveys progress.
- Token crosses an anonymous stdin pipe, never command arguments, environment variables or logs.
- Token removed from the GUI after it is passed to a decryption job. A new sign-in/token is needed for another job. Python/Swift cannot guarantee erasure from memory.
- Temporary WebKit cookie storage; no persistent login or token cache. The page's token is observed only from the exact HTTPS Tesla Dashcam batch endpoint and main frame. No form/password/MFA-field inspection.
- Navigation allowed only to HTTPS Tesla domains. Third-party identity/verification pages may therefore fail; use the browser fallback instead of relaxing this silently.
- Source files opened for reading. Output ownership, validation and atomic publishing follow the engine's safeguards.
- Cancel signals the worker to clean up active temporary files; completed outputs remain.
- Last 500 progress messages remain in the UI only and can include local filenames. No analytics or remote server.
- The app is not sandboxed in this initial build. Folder pickers and scope lifetimes prepare for later sandboxing, but do not enforce least-privilege filesystem access in this build.
- iOS is not included yet. This Mac version uses a Python subprocess; an iOS version needs a native Swift decryption engine plus Files/document-picker integration and mobile lifecycle work.

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
