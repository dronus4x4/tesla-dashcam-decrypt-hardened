# Sentry USB Unlock for iPhone and iPad

## TL;DR

This is **iOS beta source code**, not a published TestFlight download. Use full Xcode on a Mac to [open the project](#open-the-project-on-your-mac), select your Apple developer team, test on a device and [upload to your own TestFlight](#upload-to-your-testflight).

Once installed: while parked, connect the dashcam USB, select **TeslaCam**, scan, sign in or paste a temporary token, and save unlocked copies. Test copy mode first. USB replacement is optional and keeps no encrypted backup. Keep the app in the foreground and use **Cancel** before disconnecting; completed replacements are skipped after rescanning.

Phone sign-in and real USB operation still need live testing. The latest Python/Mac performance changes do not automatically apply to this native Swift app. For the working Mac workflow, see the [Mac guide](../macos/README.md).


**Version 0.1.0 · build 1 · iOS/iPadOS 17 or later**

Bundle ID: `com.dronusdrives.sentryusbunlock`

This is a native Swift beta, with no Python runtime on the phone. Source and unsigned build validation are provided. It has not yet been signed or uploaded to TestFlight, or tested against a real iPhone, external USB drive, Tesla sign-in or real Tesla clips. Test a copied USB before enabling replacement. Independent project, not affiliated with Tesla.

## What it does

- Selects a TeslaCam folder through the Files picker and holds its security-scoped access for the session.
- Scans locally, skipping hidden system folders and Mac `._` metadata files.
- Requests keys from Tesla's fixed HTTPS decryption endpoint; video bytes stay on the device.
- Decrypts native AES-CBC pages, validates the MP4 and publishes only complete outputs.
- Saves copies in the app's local Documents folder by default.
- Offers explicit USB replacement, off by default, with a confirmation showing the folder and clip count. No encrypted backup is kept.
- Checks free space for one temporary clip, validates before replacement, detects source changes and cleans temporary files after normal cancellation.
- Keeps the screen awake during work. Cancel is available during scan/unlock; moving the app into the background cancels work and clears the token. Completed clips remain, and rescanning skips them.

## Sign-in limitation — read this first

The temporary embedded Tesla website can capture the token from Tesla's normal key request after you select one encrypted clip there. Tesla may reject this browser, including with its “required security tools” message observed on the Mac. Mobile authentication is experimental; we do not bypass Tesla's security or promise it works.

A manual secure token field is included. For the initial beta, if mobile sign-in is blocked, obtain the temporary token using a normal browser on a Mac as described in the [Mac guide](../macos/README.md#use), then transfer it privately to the phone and paste it. Never post the token, log it or save it in the repository. This limitation means the beta is not yet a proven fully independent in-car unlock workflow. A reliable phone-only authentication route needs live testing and potentially Tesla support.

## Connect and use

1. While parked, unplug the dashcam USB from the car and connect it to your iPhone/iPad with the appropriate USB adapter or hub.
2. Open Apple's **Files** app → **Browse**. Confirm your USB appears under **Locations**. Do not reformat it. Some drives need a powered hub.
3. Open **Sentry USB Unlock** → **Select TeslaCam folder…** → choose **TeslaCam** on the USB.
4. Leave **Replace encrypted clips on USB** off for the first test. Copies go to **Files → On My iPhone/iPad → Sentry USB Unlock → Unlocked Clips**.
5. Tap **Scan drive**, then sign in or paste a temporary token.
6. Tap **Save unlocked copies**. Keep the app in the foreground and the drive connected. Check that saved videos play.
7. To replace originals later, first copy the USB if you want recovery. Turn replacement on, rescan, tap **Unlock clips on USB** and confirm.
8. To stop, tap **Cancel** and wait for **Cancelled**. Completed replacements remain. The beta cannot guarantee recovery from power loss, forced termination or drive removal during a filesystem operation.

The app does not rewrite Tesla event metadata. Playback of replaced files in the car's viewer remains unverified. This is an iPhone/iPad app, not a CarPlay app or an app installed in the Tesla touchscreen.

Apple's [external storage guide](https://support.apple.com/guide/iphone/external-storage-devices-iph95baac91f/ios) covers adapters, power and supported disk formats. A drive must be compatible with Files. Copy mode publishes to the app's local APFS container; arbitrary cloud-provider or exFAT copy destinations are not exposed in this beta.

## Open the project on your Mac

Install full **Xcode** from the Mac App Store. Command Line Tools alone cannot build iPhone apps. Use a current Xcode version accepted by App Store Connect when you upload.

Open Terminal and paste these lines **one at a time**:

```bash
cd ~/tesla-dashcam-decrypt-hardened
```

```bash
git pull --ff-only
```

```bash
open ios/SentryUSBUnlock.xcodeproj
```

If the repository is not yet on your Mac, first run:

```bash
cd ~
git clone https://github.com/dronus4x4/tesla-dashcam-decrypt-hardened.git
cd tesla-dashcam-decrypt-hardened
open ios/SentryUSBUnlock.xcodeproj
```

No project generator, Homebrew or Python is needed to open/build the iOS app in Xcode. Python is used only for generating synthetic test fixtures in CI.

## Set up your Apple signing

1. In Xcode, open **Xcode → Settings → Accounts** and add the Apple Account associated with your developer membership. Complete Apple's authentication locally; do not send credentials or codes in chat.
2. Click the blue project icon in Xcode's left sidebar, then select the **SentryUSBUnlock** target.
3. Open **Signing & Capabilities**. Leave **Automatically manage signing** enabled and select your developer **Team**.
4. Keep the bundle ID above, unless it is unavailable in your team. If you change it, use that same value in App Store Connect. The team is deliberately not committed to this public repository.
5. Connect an iPhone, select it as the run destination at the top of Xcode, and click the triangular **Run** button. Follow Apple's device trust/Developer Mode prompts if shown.
6. Test scanning and saving copies on a duplicate USB before testing replacement.

## Upload to your TestFlight

1. In [App Store Connect](https://appstoreconnect.apple.com), open **Apps**, click **+**, then **New App**.
2. Choose **iOS**, name **Sentry USB Unlock**, your preferred primary language, the matching bundle ID and SKU `sentry-usb-unlock`. Name availability is determined by Apple.
3. In Xcode choose **Any iOS Device (arm64)** as the build destination, then **Product → Archive**.
4. When Organizer opens, select the archive, click **Distribute App**, choose **App Store Connect** and follow the upload steps. Exact labels can vary by Xcode version.
5. Wait for Apple to process the build. Open the app's **TestFlight** tab in App Store Connect and complete the required test information and encryption questions. The app uses Apple's CommonCrypto/CryptoKit for AES and MD5 compatibility, and URLSession HTTPS; no export-compliance answer is preselected in the project.
6. Add the build to your internal testing group and install it through TestFlight. External testers/public invitations require Apple's applicable beta review.
7. Increment **Build** in the target's General tab before each later upload; retain version `0.1.0` during this initial beta unless making a new version.

Apple's [upload guide](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/) is the authority for supported Xcode versions and upload requirements. This repository does not contain an Apple certificate, signing key, provisioning profile or App Store Connect API key. Unsigned CI builds cannot be installed through TestFlight.

## Privacy and implementation

No analytics, advertising, custom server or persistent token/key cache. Tokens stay in memory for the job and are cleared from the UI when work starts; memory erasure cannot be guaranteed. Tesla receives clip ID, VIN, key ID, timestamp, wrapped key and public key to authorize decryption. Its sign-in website handles credentials/MFA, and its own privacy policy applies. Required-reason declarations cover local/selected-file timestamps and temporary-file disk space. Before distribution, accurately complete Apple's privacy answers, including relevant Tesla processing; an embedded website is not a claim that no data reaches Tesla.

The AES/MD5 paging format is ported from the upstream-derived Python implementation; MD5 is required for compatibility, not used as a new password-security design. Original upstream attribution and its MIT declaration are retained in the repository's existing documentation. Requests reject redirects, unexpected/duplicate response IDs and malformed AES keys. Retry count and batches are bounded. File coordination and security scopes support selected external folders; actual device/Files-provider behaviour remains to be verified.

## Validation

The **iOS native checks** GitHub Actions workflow generates fake clips with the Python implementation, compiles/runs Swift protocol tests on macOS, and builds the complete iOS target without signing. It checks golden AES output, copy/source retention, validated replacement, wrong-key retention, temporary cleanup, resume scans, changed headers, colliding IDs and hidden metadata. Compile/tests do not prove live authentication or real-drive compatibility.

To run these checks on a Mac with full Xcode and a Python environment containing the root requirements:

```bash
TESLA_TEST_PYTHON="$PWD/.venv/bin/python" bash ios/scripts/check.sh
```
