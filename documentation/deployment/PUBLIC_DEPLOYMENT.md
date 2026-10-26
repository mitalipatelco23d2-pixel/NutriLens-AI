# Public deployment runbook

## Proposed free-first topology

- Web: Cloudflare Workers using `@opennextjs/cloudflare`. Static assets are served at the edge; the Google session exchange remains a Next.js route handler.
- API: Render free web service from `render.yaml` and `infrastructure/docker/api.Dockerfile`.
- Transactional database: Neon Postgres free plan, replacing every process-local application store before billing is enabled.
- Cache/rate limiting: Upstash Redis free plan. Public mode uses an atomic Redis fixed-window limiter and fails closed if Redis is unavailable.
- Heavy R3 inference: local/hybrid. The public API exposes deterministic intelligence and can return explicit unavailable/unknown states rather than pretending free compute can sustain OCR/YOLO workloads.

This is an academic/startup preview topology, not an enterprise SLA. Render free services spin down after inactivity and use ephemeral filesystems. The official Render documentation explicitly says free instances should not be used for production applications.

## Background commands

```powershell
npm run verify:web
npm run cf:build
docker build -f infrastructure/docker/api.Dockerfile -t nutrilens-api:test .
docker compose config --quiet
```

## Required organization-owned configuration

Cloudflare web variables:

- `PUBLIC_WEBSITE_URL` — final HTTPS `.tech` website origin.
- `PUBLIC_API_URL` — final HTTPS `api.<website-host>` origin.
- `ANDROID_APP_LINK` — final HTTPS distribution or store URL; never a placeholder.
- `BACKEND_INTERNAL_URL` — public FastAPI origin.
- `NEXT_PUBLIC_API_URL` — public FastAPI origin baked into the web build.
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID` — web OAuth client ID.
- `NEXT_PUBLIC_SUPPORT_EMAIL` — published organization-owned support address.
- `LEGAL_POLICIES_APPROVED=true` — explicit owner/legal review gate before Live Mode.

FastAPI secrets/variables:

- `APP_ENVIRONMENT=production`
- `CORS_ORIGINS=https://DOMAIN.tech`
- `POSTGRES_URL`
- `RATE_LIMIT_BACKEND=redis`
- `REDIS_URL` — TLS Redis connection URL for the public limiter
- `JWT_SECRET`
- `GOOGLE_CLIENT_ID`
- Razorpay Test Mode keys, webhook secret, and all six plan IDs.

After owner-controlled values are present, run the fail-closed preflight. It reports field names
and reasons but never prints secret values:

```powershell
& '.\.venv\Scripts\python.exe' scripts\validate_public_config.py
```

CI separately checks that `.env.example` declares every required field. The live preflight also
verifies HTTPS `.tech`/`api.*.tech` topology, explicit CORS, TLS database/cache URLs, durable public
backends, a 32-byte session secret, Google audience agreement, Razorpay Test Mode, and six distinct
provider plan IDs.

## Human checkpoints

1. Sign in to selected providers with the Yash AI Technologies Google account.
2. Create/configure Google OAuth web credentials and approved origins.
3. Provide the actual `.tech` domain before any DNS change.
4. After stable web/API URLs exist, enter them in Razorpay onboarding.
5. Complete Razorpay KYC, OTP/2FA and live approval personally.
6. Do not configure live keys or perform a real charge without explicit approval.

## Intended DNS shape

Exact records depend on the registrar and Cloudflare project generated during deployment:

- `DOMAIN.tech` → Cloudflare web custom domain.
- `api.DOMAIN.tech` → Render API custom domain.

Provider-managed TLS should be preferred to manual certificate private-key handling.

## Android status

The official Android SDK/toolchain is installed and the authenticated Flutter
client builds successfully. Flutter analysis and automated contract/widget
tests pass, and a headless API 36 emulator has run the real bundled ML Kit OCR
path over the governed fixture matrix. This is not physical-device, release
signing, or Play review proof. No Play Store listing, public APK URL, or
Razorpay-acceptable Android proof exists yet. Do not fabricate
`ANDROID_APP_LINK` or incur Play Store fees without owner approval.

Client OCR remains centrally restricted to shadow comparison. The custom YOLO
ONNX artifact is not bundled and is blocked from APK/web distribution pending
license and model-IP review. Azure remains the authoritative fallback.

Owner-controlled mobile configuration is required before device sign-in:

- Create the Android OAuth client for package `ai.nutrilens.nutrilens_x` and register the owner-controlled signing certificate fingerprints.
- Create the iOS OAuth client for the final bundle identifier and add its reversed client-ID URL scheme to `ios/Runner/Info.plist`.
- Build with `--dart-define=GOOGLE_SERVER_CLIENT_ID=<backend-audience-client-id>` and, where required, `--dart-define=GOOGLE_CLIENT_ID=<platform-client-id>`. The server client ID must match FastAPI `GOOGLE_CLIENT_ID` because the backend validates the ID-token audience.
- Build public clients with `--dart-define=API_BASE_URL=https://api.DOMAIN.tech --dart-define=APP_ENVIRONMENT=production`; do not ship the emulator-only default URL.
- Provide the existing release-signing environment variables documented by the Android Gradle configuration. Release builds deliberately fail when those credentials are absent.

After configuration, run:

```powershell
flutter analyze
flutter test
flutter build apk --release `
  --dart-define=API_BASE_URL=https://api.DOMAIN.tech `
  --dart-define=APP_ENVIRONMENT=production `
  --dart-define=GOOGLE_SERVER_CLIENT_ID=<backend-audience-client-id>
```

The iOS archive requires an owner-controlled Apple development team, provisioning profile and macOS/Xcode environment.

## Razorpay website/app evidence checked on 2026-08-27

Razorpay's current official [Business Website Details](https://razorpay.com/docs/payments/dashboard/account-settings/business-website-details/?preferred-country=IN)
guidance requires live website or mobile-app details for Live Mode and lists Terms, Privacy,
Shipping, Contact, Pricing, and Cancellation/Refund policy surfaces. NutriLens now provides those
public routes. The same guidance asks the merchant to select whether payments are collected on a
website or app and may request review credentials.

The official [account setup guide](https://razorpay.com/docs/payments/set-up/?preferred-country=IN)
allows website or application links to be added later during initial setup. Neither source says a
Play Store listing is universally mandatory, nor does either promise that a sideloaded APK URL is
sufficient. Therefore the owner should submit the deployed `.tech` website as the primary payment
surface. If the live Dashboard still requests an app because App was selected, submit only the real
HTTPS Android distribution/store URL produced after signing and device validation; the Dashboard's
review result is authoritative. Do not fabricate a listing or assume an APK will be accepted.

## Container evidence

The web Docker build uses Next.js 16 standalone output and copies only traced runtime dependencies,
public assets and static build assets into the non-root runtime image. The traced standalone files
were approximately 19 MB compared with approximately 949 MB for the development dependency tree;
the final web image was approximately 74 MB and the API image approximately 176 MB. Both images run
as the non-root `nutrilens` user (UID 10001).

An isolated `docker compose up --build --wait` run verified PostgreSQL, MongoDB, Neo4j, Redis, API
and web all healthy. Direct API health and public web routes returned HTTP 200. A request carrying
an invalid session reached FastAPI through the Next same-origin bridge and returned the expected API
401, proving the server-side `http://api:8000` route rather than a localhost-only path. The isolated
containers, network and volumes were removed after verification. The Google requests transport and
Redis authenticated healthcheck are covered by repository regression checks.
