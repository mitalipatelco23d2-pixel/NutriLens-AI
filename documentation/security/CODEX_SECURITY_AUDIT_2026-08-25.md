# Codex Security Audit — 2026-08-25

Scan `659bafbc-21a9-44e3-9070-28473ed4601e` completed a repository-wide Standard audit of application, AI, pipeline, client, CI and deployment source. The offline canonical scan reported 20 validated findings: 9 medium and 11 low, with no high or critical findings. Threat-advisory connector verification was unavailable, so advisory coverage remains an explicit external follow-up.

## Dependency and delivery follow-up — 2026-08-27

A live `pip-audit` check subsequently found current advisories against the previously pinned
FastAPI/Starlette, PyJWT and pytest dependency chain. The repository now pins FastAPI 0.141.1,
Starlette 1.6.0, PyJWT 2.13.0 and pytest 9.1.1. Separate production and development requirement
audits both report no known vulnerabilities; `npm audit` also reports none. Development-only test,
lint and audit packages were removed from the API runtime requirements.

GitHub Actions references are commit-SHA pinned, CI audits both Python sets and builds both
container images, and regression tests enforce these invariants. The Next.js runtime container now
uses standalone output rather than copying the full development dependency tree. Isolated runtime
verification confirmed both images use UID 10001 and all six Compose services become healthy. The
Google authentication requests transport is an explicit production dependency, and Redis health
authentication no longer places its password in the CLI argument list. These checks do not replace
a deployed advisory scan or provider/infrastructure review.

## Remediation status

All 20 reported source findings received code-level remediation in this workspace:

- verified-subject rate limiting, constant liveness, cached/rate-limited readiness;
- quota reservation before uploads/inference, bounded cancellation-safe scan capacity, bounded webhook and BFF bodies;
- pre-decode per-image and aggregate pixel limits, bounded TTL/LRU local scan storage, PostgreSQL-only public persistence;
- loopback-only authenticated development stores, coarse fixed-window research cohort bands with sensitive totals withheld, payload-bound webhook identity and signed provider-event chronology;
- HTTPS-only Android release traffic, owner-keystore release signing gate, immutable Flutter CI action and non-root containers;
- model digest verification before deserialization, ingredient structural budgets, pinned dataset digests, tar/OFF/XLSX expansion and byte budgets, and safe embedded image identifiers.

Focused regression tests, Ruff and mypy validate the remediated paths. The post-patch bypass review found one canceled-queue semaphore leak; it was corrected by using cancellation-safe async acquisition while retaining worker slots through timed-out execution.

## External verification still required

- Connect the threat-advisory source and rerun advisory correlation.
- Validate deployed TLS, network ACLs, secret rotation, managed PostgreSQL/Redis and provider-console settings.
- Supply and safeguard the Android production keystore credentials.
- Run live Google OAuth, Razorpay Test Mode webhook and public deployment end-to-end checks.

The canonical generated scan artifacts remain in the local Codex Security scan workspace referenced by the release handoff; this durable summary records the repository disposition without claiming external controls were verified.
