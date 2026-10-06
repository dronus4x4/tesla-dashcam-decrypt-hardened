#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
MAC_PROJECT_DIR="$PWD"
APP_PATH="$MAC_PROJECT_DIR/dist/Tesla Dashcam Decryptor.app"
MAC_PYTHON="${TESLA_BUILD_PYTHON:-python3}"
"$MAC_PYTHON" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
cmp ../tesla_dashcam_decrypt.py Sources/TeslaDecryptGUI/Resources/tesla_dashcam_decrypt.py
swift build -c release
MAC_BIN_DIR="$(swift build -c release --show-bin-path)"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"
mkdir -p "$APP_PATH/Contents/Resources/decrypt-worker"
cp Sources/TeslaDecryptGUI/Resources/*.py "$APP_PATH/Contents/Resources/decrypt-worker/"
cp "$MAC_BIN_DIR/TeslaDecryptGUI" "$APP_PATH/Contents/MacOS/"
for MAC_RESOURCE_BUNDLE in "$MAC_BIN_DIR"/*.bundle; do
    if [ -d "$MAC_RESOURCE_BUNDLE" ]; then
        cp -R "$MAC_RESOURCE_BUNDLE" "$APP_PATH/Contents/Resources/"
    fi
done
"$MAC_PYTHON" -m venv "$APP_PATH/Contents/Resources/python-runtime"
"$APP_PATH/Contents/Resources/python-runtime/bin/python3" -m pip install -r ../requirements.txt
cat > "$APP_PATH/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>TeslaDecryptGUI</string>
<key>CFBundleIdentifier</key><string>com.dronusdrives.tesladecrypt</string>
<key>CFBundleName</key><string>Tesla Dashcam Decryptor</string>
<key>CFBundleDisplayName</key><string>Tesla Dashcam Decryptor</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
# Local development signing; not a Developer ID signature or notarization.
codesign --force --sign - "$APP_PATH"
printf 'Built: %s\n' "$APP_PATH"
