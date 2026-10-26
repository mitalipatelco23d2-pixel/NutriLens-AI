# Android production release runbook

Status: engineering preparation complete; signed artifacts not yet produced.

## Frozen release configuration

| Item | Value / enforcement |
| --- | --- |
| Application ID | `ai.nutrilens.nutrilens_x` |
| Product name | NutriLens X |
| Version | `1.0.0` (`versionCode` 1) |
| Minimum Android SDK | Flutter 3.44 default API 24 |
| Target/compile SDK | Flutter 3.44 resolved SDK (verified by the release build) |
| API origin | `https://api.nutrilensx.tech` only in release mode |
| Authentication | Google plus verified email/password; phone OTP omitted |
| Signing | Owner-controlled release keystore; debug signing is forbidden |
| Custom YOLO | Not bundled in APK/AAB and not publicly downloadable |

The Dart runtime fails closed when a release build is missing the production API
or Google backend-audience client ID. Gradle fails release tasks when any signing
environment variable is missing. The build script also inspects the resulting ZIP
entries and rejects ONNX, PyTorch, or TensorFlow Lite model files.

## Owner-controlled inputs

Set these outside the repository and outside shell history where practical:

- `NUTRILENS_ANDROID_KEYSTORE`
- `NUTRILENS_ANDROID_STORE_PASSWORD`
- `NUTRILENS_ANDROID_KEY_ALIAS`
- `NUTRILENS_ANDROID_KEY_PASSWORD`
- `NUTRILENS_GOOGLE_SERVER_CLIENT_ID`
- optional `NUTRILENS_GOOGLE_ANDROID_CLIENT_ID`

The Android OAuth client must use package `ai.nutrilens.nutrilens_x` and the
SHA-1/SHA-256 fingerprints of the actual release/Play App Signing certificate.
The server-client ID must match the FastAPI `GOOGLE_CLIENT_ID` audience.

## Reproducible build

From the repository root:

```powershell
& .\scripts\mobile\build_android_release.ps1 -Artifact both
```

The script runs analysis and tests, builds the signed AAB and optional release
APK, rejects blocked model artifacts, and prints only artifact paths, sizes and
SHA-256 digests. It never prints passwords.

## Required post-build checks

1. Inspect the merged release manifest and dependency report.
2. Install the release APK on a physical Android device and exercise Google and
   email login against the same canonical web account.
3. Run the bounded client-evidence shadow fixture matrix and record physical
   latency, acceptance, fallback, and structured parity separately from emulator
   evidence.
4. Upload the AAB to an internal Play track, enable Play App Signing, and record
   the app-signing certificate fingerprints in the Android OAuth client.
5. Reconcile the Data Safety form with the final SDK/permission inventory.

No physical-device pass, signed AAB, or Play Console submission is claimed yet.
