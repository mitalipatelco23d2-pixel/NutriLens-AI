# Google Play Data Safety and health declaration draft

Status: owner-review draft; not submitted to Play Console.

Package: `ai.nutrilens.nutrilens_x`

This draft reflects the current ML Kit OCR shadow, local-reminder, and
read-only Health Connect debug build. It must be reconciled
against the final release AAB, every included SDK's current disclosure, and the
actual production configuration immediately before submission.

## Processing model

- The user selects or captures a food-label image.
- Android may process the image locally with bundled ML Kit OCR.
- Current shadow mode transmits the selected image and bounded OCR evidence over
  HTTPS for authenticated image binding and an owner-scoped authoritative server
  scan. A future preferred mode may avoid routine cloud OCR only after measured
  acceptance; that behavior is not claimed by this draft.
- Raw scan images are processing inputs and are not retained after processing.
  Structured scan evidence and user corrections may be saved to private scan
  history.
- The custom YOLO ONNX model is not in the APK.
- Optional reminder choices and times are stored on-device under an owner-scoped
  preference key. They are not transmitted by the reminder implementation.
- Optional Health Connect sync reads only hydration and weight for at most the
  preceding 30 days. The preview is held in memory and is not uploaded or merged
  into the NutriLens account/diary by the current implementation. Its owner-scoped
  opt-in flag is stored on-device.
- Android account export is user initiated and sends the authenticated JSON to
  a destination the user selects in the operating-system share sheet. NutriLens
  does not request broad storage access for this action. The selected receiving
  app/provider controls its copy and must be considered during final disclosure
  review.
- Private account profile fields include DOB, optional country/region and an
  optional E.164 phone. Phone is masked in normal reads, remains unverified while
  SMS delivery is disabled, and is included in the owner's explicit data export.
- The current release is restricted to users aged 18 or older. Terms and Privacy
  acceptance timestamps are stored on the account; this policy and wording still
  require owner/legal review before submission.
- Active-session identifiers and timestamps support owner-visible revocation.
  They are not presented as device names or location because those attributes
  are not collected by this implementation.
- The separate research/insights choice is off by default and withdrawable.
  Aggregate diary research excludes owners who have not opted in; identifiable
  account fields and Health Connect data are not part of that aggregate source.

Google's form guidance says data used solely on-device and never transmitted is
not collected for Data Safety purposes. That exception does not describe the
current shadow/fallback path, so the draft conservatively declares the relevant
off-device scan data.

## Proposed Data Safety answers

| Data category | Collected | Shared | Required/optional | Purpose and retention |
|---|---|---|---|---|
| Name, email, user ID, DOB, optional phone/region/avatar, legal-acceptance and session metadata | Yes | Review provider definitions | Identity/DOB/legal acceptance required for current 18+ account; phone/region optional | Account management, onboarding, security, owner scoping, chosen units and session revocation; retained until deletion/required retention |
| User-provided food-label photos | Yes | No sale; processor status to verify | Optional, user initiated | App functionality; raw image not retained after processing |
| Scan text, nutrition/ingredient evidence and corrections | Yes | No sale; processor status to verify | Optional, user initiated | App functionality and private history; user can delete scans/account |
| Nutrition, diary, goals and other wellness data | Yes | No sale; processor status to verify | Optional except where a feature requires it | Personalization, diary/analytics, app functionality |
| Purchase history/provider transaction references | Yes | Razorpay role to verify in final form | Required only for paid plans | Payment status, entitlement, reconciliation; no card/bank credentials stored by NutriLens |
| Voice input/audio | Transcription behavior must be verified in final AAB | Verify speech provider | Optional, user initiated | Voice input; do not claim on-device-only until provider behavior is confirmed |
| Local reminder preferences | No known off-device collection by this feature | No | Optional, user initiated | Stored on-device to schedule hydration, meal, summary, weight, scan and pantry reminders |
| Health Connect hydration and weight preview | No known off-device collection by this feature | No | Optional, user initiated | Read-only, manual 30-day device preview; values are not persisted or uploaded by this implementation |
| App diagnostics/analytics | Verify final SDKs and hosting logs | Verify | Automatic if present | Security, reliability, fraud/abuse prevention |
| Precise/approximate location | No known collection | No | Not requested | Not used |
| Contacts, SMS, call logs | No | No | Not requested | Not used |

`Shared` must be answered using Google Play's formal definition, including its
service-provider exceptions—not ordinary-language assumptions. Recheck Google,
Razorpay, hosting, crash/analytics, and speech SDK documentation for the exact
release.

## Security and deletion answers

- Production network traffic is HTTPS; debug-only cleartext configuration is
  not part of the release manifest.
- Authenticated data is owner scoped; client OCR is untrusted and cannot choose
  an owner, plan, entitlement, quota, or server inference provenance.
- The product provides scan deletion and account deletion flows.
- Android now exposes account export and exact-confirmation permanent deletion;
  the final signed-device flow and selected export destinations still require
  verification.
- No claim of independent security certification should be selected without
  the required audit/certification evidence.

## Health apps declaration

Declare `Nutrition and weight management`. NutriLens provides nutrition and
wellness information and tracking, but is not a medical device and does not
diagnose, treat, cure, or prevent a medical condition. Keep that disclaimer in
the store description and in-app legal/product surfaces. If this Health Connect
implementation remains in the final AAB, declare the read-only hydration and
weight access in every applicable Health Connect/Health apps console form. Do
not select write, background, extended-history, activity, location, or
medical-device capabilities.

## Permissions justification

- `INTERNET`: authentication, owner-scoped API, durable fallback jobs, account
  data, and payment status.
- `CAMERA`: optional user-initiated food-label capture; camera hardware remains
  optional.
- `RECORD_AUDIO`: optional user-initiated voice input. Verify the final speech
  implementation and retain the permission only while the feature ships.
- `POST_NOTIFICATIONS`: optional local reminders. Requested only after the user
  taps **Allow** in reminder settings.
- `RECEIVE_BOOT_COMPLETED`: restores the user's opted-in local schedules after a
  reboot. It does not start scan inference or collect data.
- `android.permission.health.READ_HYDRATION`: reads hydration only after the user
  enables manual sync and grants Health Connect access.
- `android.permission.health.READ_WEIGHT`: reads weight only after the user
  enables manual sync and grants Health Connect access.
- No Health Connect write, background-read, or extended-history permission is
  requested. The current read window is bounded to 30 days.
- No exact-alarm permission is requested; reminder delivery is inexact and
  subject to operating-system battery controls.
- No SMS, call-log, contacts, location, storage-wide, or package-wide query
  permission is requested by the main manifest.

## Required pre-submission checks

1. Build the signed release AAB and inspect the merged release manifest and SDK
   dependency report.
2. Re-run Data Safety against every production region/configuration because one
   package-level form covers all active distributed versions.
3. Verify the public, non-geofenced HTML privacy URL and in-app privacy link.
4. Verify deletion URL/flow and any legally required transaction retention.
5. Complete the Health apps declaration, use the nutrition/weight-management
   category, and declare only hydration/weight read access if Health Connect is
   present in the final AAB.
6. Keep ONNX/custom model disclosure absent unless the distribution gate is
   later cleared and the release actually bundles it.

## Official references

- [Google Play Data Safety guidance](https://support.google.com/googleplay/android-developer/answer/10787469)
- [Health Content and Services policy](https://support.google.com/googleplay/android-developer/answer/16679511)
- [Health apps declaration guidance](https://support.google.com/googleplay/android-developer/answer/14738291)
- [Permissions declaration guidance](https://support.google.com/googleplay/android-developer/answer/9214102)
