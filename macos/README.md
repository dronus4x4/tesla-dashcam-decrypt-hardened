# macOS GUI — first development version

SwiftUI interface for the hardened Python decryptor. macOS 13+, Xcode Command Line Tools (Swift 5.9+) and an installed Python 3.10+ are required. No Python package needs to be installed globally.

## Build on your Mac

From a checkout of this repository:

```bash
bash macos/scripts/build-app.sh
open "macos/dist/Tesla Dashcam Decryptor.app"
```

The script compiles the native interface and creates a private Python virtual environment inside the app with pinned dependencies. That environment links to Python installed on the building Mac. This is a **local development app**, not a standalone portable installer; retain that Python installation. Building it on a CI runner does not create a portable app for another Mac. It is locally ad hoc signed, not notarized, and not an App Store distribution.

Alternatively, for development:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd macos
TESLA_GUI_PYTHON="$PWD/../.venv/bin/python3" swift run
```

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
