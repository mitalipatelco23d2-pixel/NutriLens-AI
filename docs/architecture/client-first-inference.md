# Client-first inference rollout

NutriLens is moving paid image inference off the default request path without
weakening evidence quality. The rollout is deliberately phased; the current
production server result remains authoritative until shadow metrics pass.

> **OCI-only migration update (2026-09-27):** Azure is no longer an accepted
> fallback target. The dedicated Azure worker runtime has been deleted while the
> private OCI ARM64 worker is gated on tenancy activation, native model equivalence and
> the real milk fixture. Historical Azure measurements below are retained only
> as baseline evidence. Until OCI acceptance passes, a scan that cannot use
> accepted client evidence is degraded and must fail truthfully rather than
> silently claim OCI readiness.

## Phase 1: Android OCR shadow

- Android runs the bundled ML Kit Text Recognition v2 Latin model locally.
- The native bridge returns text blocks, lines, pixel bounds, language tags,
  image dimensions, image SHA-256, runtime/model version, and cold/warm timing.
- ML Kit does not expose numeric OCR confidence through this API, so confidence
  remains null.
- The authenticated backend receives both the original image and JSON evidence
  at `POST /api/v1/scan/client-evidence/classify`. It safely decodes the image,
  recomputes its digest/dimensions, allowlists the exact runtime, bounds
  coordinates and payload size, and returns one explicit decision:
  `CLIENT_EVIDENCE_ACCEPTED`, `SERVER_FALLBACK_REQUIRED`,
  `CLIENT_EVIDENCE_INVALID`, or `CLIENT_CONTRACT_UNSUPPORTED`. The older JSON
  validation endpoint remains only for contract compatibility.
- Validation does not consume scan quota, persist raw OCR, or make the client
  result authoritative. The existing server scan proceeds in parallel.
- In `shadow`, even `CLIENT_EVIDENCE_ACCEPTED` means only “eligible for a future
  preferred path.” Server fallback remains mandatory. The gate requires image
  binding, coherent positioned lines, a recognized nutrition region/basis,
  conservative minimum structured rows/major nutrients, plausible units and
  values, preserved explicit allergen evidence, and a governed parser-confidence
  floor. Thresholds are backend environment settings, not APK constants.
- Classification logs only bounded stage counts, decision/reason codes, basis,
  rollout mode, and client OCR time. It does not log raw OCR text, image bytes,
  account identity, or package evidence. These events support measured acceptance
  and fallback rates after production shadow deployment without inventing data.
- Authenticated server fallback uses the durable scan-job API (`202 Accepted`)
  and polls the owner-scoped job instead of relying on the old 35-second
  synchronous mobile request.
- Before local OCR, the app reads the authenticated server capability at
  `GET /api/v1/scan/client-inference/capabilities`. The server-owned
  `ANDROID_CLIENT_INFERENCE_MODE` supports `disabled`, `shadow`, and the future
  `preferred` rollout. An invalid value fails closed to `disabled`; the APK
  does not own the rollout decision.
- The evidence protocol is explicitly versioned as
  `client_inference_contract_version: 1.0.0` and includes platform, app
  version, OCR provider/version, optional detector provenance, source-image
  SHA-256, dimensions, orientation, boxes, and raw OCR evidence. Unknown fields
  and obsolete versions are rejected.

## Phase 2: nutrition-table detector beta

The custom YOLO11n checkpoint has been exported to static ONNX opset 17. The
unquantized export preserves the operating-threshold metrics on the complete
151-image held-out test: precision 0.8774, recall 0.8553, and F1 0.8662. The real
milk fixture produced one matching detection with 0.989 PyTorch/ONNX box IoU.

The ONNX file is not bundled or publicly downloadable. Its model registry entry
is `BLOCKED_PENDING_LICENSE_AND_IP_REVIEW`; the current Ultralytics/OFF training
chain is not cleared for proprietary APK or public-web distribution. Android
OCR shadow validation therefore uses only the bundled ML Kit runtime and keeps
the detector null. Custom-model distribution remains blocked until an explicit
license and model-IP decision is recorded.

## Android emulator checkpoint (2026-09-01)

The official Android SDK, platform tools, API 36 system image, and required
build toolchain are installed. The debug app and an instrumentation-only test
APK build successfully. A headless Pixel 6/API 36 AOSP emulator ran the real
bundled ML Kit v2 engine over eight fixtures, with the Country Delight milk
image first and repeated warm in the same process.

The milk fixture produced 64 positioned OCR lines. The governed offline shadow
adapter recovered `Low Fat Cow Milk`, `Country Delight`, `Pasteurized Cow Milk`,
the explicit Milk package allergen, a 250 ml serving, `PER_100_ML`, and ten
nutrition rows. The first pass took 16.273 seconds of OCR and the immediate warm
repeat took 6.793 seconds on this software-rendered emulator. Across the eight
first passes, OCR p50 was 10.290 seconds and nearest-rank p95 was 16.273 seconds.
These are emulator measurements, not physical-phone latency or thermal proof.

The matrix still intentionally fails closed on a severely blurry snack (no
structured nutrition rows), while beverage, cereal, ingredient-heavy, rotated,
and tea fixtures recover partial-to-strong evidence. Consequently the rollout
switch remains `shadow`: Android client OCR is technically functional, but it
is not yet authoritative. The subsequent OCI-only pivot independently reduced
the legacy worker to zero warm replicas.

## Trust and fallback rules

1. Client evidence is untrusted input even for an authenticated owner.
2. Evidence must be tied to the original image SHA-256 and a governed runtime.
3. R3 normalization and R4 allergen/safety logic stay server-governed.
4. Low-quality, missing, malformed, or unsupported client evidence may use only
   the authenticated OCI worker after its acceptance gates pass; it never
   silently becomes a successful scan.
5. If OCI is unavailable or unvalidated, the result is a bounded retryable
   enhanced-scan failure. Azure is not restored as a backup.
6. `preferred` capability is reserved but does not yet bypass the durable server
   scan; production cannot silently become client-authoritative through config
   alone.

## Historical owner-controlled Azure worker measurement

The accepted Azure worker image was run locally over loopback with the same
1-vCPU/2-GiB CPU limit. The milk fixture remained structurally correct on three
runs (11 nutrition rows, `PER_100_ML`, Milk allergen), and sampled peak memory
was about 951 MiB with no OOM. However, cold request latency was 139–156 seconds
and warm p50 was about 123 seconds. Warm YOLO detection fell below 1.2 seconds,
while PaddleOCR remained about 120 seconds. The measured bottleneck is OCR, so
an owner-local copy of the unchanged worker is not a consumer default; Android
ML Kit shadow validation is the next optimization gate.
