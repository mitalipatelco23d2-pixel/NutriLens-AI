# Flutter mobile verification

Status date: 2026-08-27

## Implemented journey

The production entry point now requires a NutriLens session and uses Google Sign-In only to obtain an OIDC ID token. The ID token is exchanged at `/api/v1/auth/google`; only the resulting short-lived NutriLens access token is persisted in platform secure storage. A centralized authorized client supplies that token to scans and all account APIs.

Authenticated surfaces cover camera/gallery image acquisition, product/meal/OCR/barcode scan modes, R3 uncertainty, R4 ingredient/additive/allergen/processing evidence, private scan history, consent-gated recommendations, diary and recorded-meal comparison, pantry, pantry-coverage recipe comparison, functional substitutions, user-supplied per-serving recipe nutrition comparison, analytics with source-record drill-down, typed/push-to-talk/read-aloud evidence assistant, health profile including consented adult BMI context, household-profile CRUD and subscription status. Voice transcripts remain editable and are not sent until submission. BMI remains a formula-only self-reported context without categories or recommendations. Household consent is independent and a member context is never selected automatically. Backend entitlements and ownership checks remain authoritative.

## Verified locally

Executed with Flutter 3.44.4 and Dart 3.12.2:

```powershell
flutter pub get
dart format lib test
flutter analyze
flutter test
```

Result: analyzer clean; 13 tests passed and one opt-in live connectivity test skipped because `LIVE_API_BASE_URL` was not supplied. Coverage includes bearer propagation, structured error handling, Google credential exchange/session persistence, product/search/favorites/recipe/recipe-nutrition/meal-comparison/drill-down/household-profile/BMI contract parsing, voice-gateway assistant interaction, R4/recommendation parsing, scanner uncertainty UI, user-scoped minimized offline fallback and backend health UI.

## External checks still required

- Android SDK installation, configured emulator or physical device, camera/gallery permission checks and release APK/AAB build.
- Owner-created Google Android/iOS OAuth clients and an audience-compatible server client ID.
- iOS URL scheme, Apple signing/provisioning and archive on macOS/Xcode.
- Real Google account exchange against the public FastAPI origin.
- Physical accessibility review with TalkBack and VoiceOver, large text, reduced motion and keyboard/switch navigation where applicable.
- Razorpay Test Mode lifecycle verification through the web checkout; mobile intentionally displays authoritative account state and does not collect payment details.

No client secrets, signing keys or provider credentials belong in Dart defines or source control.
