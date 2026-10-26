# R0 Security, Privacy and AI Safety Foundation

## Secrets and environment

Commit variable names and development-only placeholders, never active secrets. Use `.env` locally, repository/organization secrets in CI, and rotate credentials before any non-local environment.

## Dependencies

Pin backend packages, commit the npm lockfile, audit production and development dependencies, review updates, and never silence a critical advisory without documented acceptance. CI runs `npm audit` and pinned `pip-audit` checks; test/lint/audit tools live in `backend/requirements-dev.txt` and are excluded from the API runtime image.

## Authentication, authorization and abuse controls

The current R14/R16 boundary verifies Google identity before issuing short-lived signed NutriLens tokens. Server-side authorization enforces roles, plans and resource ownership. Public mode requires PostgreSQL persistence and an atomic Redis rate limiter; limiter identities use only verified token subjects and invalid bearer values share the client-host bucket. Unsafe identity, persistence or limiter configuration fails at startup, and a Redis outage fails protected traffic closed while constant-time liveness remains available. Readiness checks are rate-limited, cached and coalesced. Local development may use explicit bounded in-memory adapters.

Uploads and webhooks enforce byte, decoded-pixel, aggregate-view, concurrency and retention budgets before expensive work. Timed-out inference remains charged and retains its worker slot until the underlying job exits. Dataset/model inputs require trusted digests before parsing or model loading; archive and structured-document ingestion use expansion budgets.

## Privacy and development data

Minimize collection, use synthetic profiles in development, keep health/allergy data separate from public product data, and never put sensitive values in logs. Profile-aware recommendations and comparisons must read saved goals, allergens, and dietary preferences only when `consent_personalization` is true. Account export and confirmation-gated deletion are part of the authenticated boundary; raw scan images are not retained.

Research aggregates use fixed hourly snapshots and expose only coarse 20-user cohort bands; entry counts and nutrient totals are withheld to prevent nutrition differencing. Razorpay event identity is bound to the signed payload digest, and signed provider timestamps reject stale lifecycle reversal while permitting fresh recovery events.

## Deployment boundary

Release Android traffic is HTTPS-only and release builds fail without owner-managed signing credentials. Development service ports bind to loopback. Runtime containers drop root privileges, and third-party CI actions are pinned to reviewed commits. Live provider settings, credentials, TLS, domain configuration and Android keystore custody remain owner-controlled external verification items.

## Logging

The API emits a minimal completion event containing only event type, validated/generated request identifier, HTTP method, response status and duration. The same identifier is returned in `X-Request-ID` for support correlation. Do not log tokens, credentials, query strings, paths containing resource identifiers, images, raw OCR, health profiles, allergies, chat contents or full database URLs.

## AI safety and medical boundary

NutriLens X supports nutrition and wellness decisions. It does not diagnose, prescribe, predict disease from one food, certify medical safety or replace a professional. Use probabilistic, evidence-aware language and surface uncertainty. Hardcoded demonstrations must be labelled as scaffolds.
