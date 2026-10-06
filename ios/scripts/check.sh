#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
TASK_NATIVE_TEMP=$(mktemp -d)
trap 'rm -rf "$TASK_NATIVE_TEMP"' EXIT
"${TESLA_TEST_PYTHON:-python3}" ios/tests/generate_fixtures.py "$TASK_NATIVE_TEMP/fixtures"
swiftc ios/SentryUSBUnlock/ClipCore.swift ios/tests/CoreSmoke.swift -o "$TASK_NATIVE_TEMP/core-tests"
"$TASK_NATIVE_TEMP/core-tests" "$TASK_NATIVE_TEMP/fixtures"
xcodebuild -project ios/SentryUSBUnlock.xcodeproj -scheme SentryUSBUnlock -sdk iphoneos -destination 'generic/platform=iOS' -derivedDataPath "$TASK_NATIVE_TEMP/build" CODE_SIGNING_ALLOWED=NO build
