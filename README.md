# NutriLens X

**Android-first nutrition intelligence for packaged food labels.**

NutriLens X helps users scan packaged-food nutrition labels, understand ingredients and allergens, evaluate food against their selected profile, and ask grounded nutrition questions using evidence extracted from the product label.

> **Project status:** College-demo / pre-release build.  
> NutriLens X is not a medical diagnosis or treatment product.

## What NutriLens X Does

The current college-demo experience focuses on **packaged food label scanning**.

Core capabilities include:

- Email and Google authentication
- Nutrition-label and ingredient OCR
- Ingredient and allergen extraction
- Nutrition normalization
- Personal Fit scoring
- Scan-grounded Ask Nutri
- Today / diary tracking
- Pantry and shopping workflows
- Hydration and weight tracking
- Account and session controls
- Optional Health Connect integration
- Curated recipe workflows with estimated nutrition per serving

Barcode, QR and prepared-meal scanning are not part of the current college-demo surface.

## Personal Fit

Personal Fit is a **deterministic, evidence-based rules system**.

It is not presented as a trained medical-risk model.

The system uses available label evidence and the user's selected profile to produce:

- a fit score
- a fit classification
- grounded reasons
- explicit uncertainty when evidence is insufficient

A scan does **not** automatically imply consumption.

## Architecture

```text
Flutter Android App
        |
        | HTTPS
        v
https://api.nutrilensx.tech
        |
        v
Render API
        |
        +---- PostgreSQL
        |
        +---- Redis
        |
        +---- client-side/on-device evidence when available
        |
        +---- server inference fallback
                 |
                 v
        Azure Container Apps AI Worker
        min replicas: 0
        max replicas: 1
```

The AI worker is used only when server-side inference is required and can scale back to zero when idle.

The supporting web surface at:

`https://nutrilensx.tech`

is used for web/support flows such as password reset. The Flutter Android application is the primary consumer frontend.

## Repository Structure

```text
.
├── apps/
│   ├── mobile/          # Flutter Android/iOS client
│   └── web/             # Supporting web workspace
│
├── backend/             # FastAPI API, auth, scan jobs and application services
├── ai/                  # OCR, food understanding and nutrition intelligence
├── app/                 # Next.js routes/pages
├── components/          # Web UI components
├── data/                # Governed datasets and runtime knowledge artifacts
├── infrastructure/      # API/worker container definitions and deployment assets
├── scripts/             # Data, validation, deployment and utility scripts
├── tests/               # Backend/web tests
├── docs/                # Product/release/integration documentation
├── documentation/       # Engineering architecture, datasets and historical records
└── reports/             # Sanitized QA and release reports
```

Local recovery workspaces, credentials, runtime caches and private QA evidence are intentionally excluded from version control.

## Android App

Flutter application:

```text
apps/mobile/
```

Android package:

```text
ai.nutrilens.nutrilens_x
```

Public API:

```text
https://api.nutrilensx.tech
```

### Run Locally

Install Flutter and Android tooling, then:

```bash
cd apps/mobile
flutter pub get
flutter doctor
flutter devices
flutter run
```

## Backend

The public API is implemented in Python/FastAPI.

For local development, create your own environment configuration from:

```text
.env.example
```

Never commit `.env` or real credentials.

Install the backend dependencies according to the repository development documentation, then start the API using the configured local environment.

Health endpoint:

```text
GET /health
```

## AI Worker

Server-side OCR/inference fallback is implemented separately from the public API.

Relevant deployment files are under:

```text
infrastructure/docker/
```

The college-demo deployment uses:

- GitHub Container Registry for the worker image
- Azure Container Apps Consumption
- authenticated API-to-worker communication
- scale-to-zero when idle

No worker credentials belong in source control.

## Current Demo Deployment

| Component | Deployment |
|---|---|
| Android frontend | Flutter APK |
| Public API | Render |
| Canonical API domain | `api.nutrilensx.tech` |
| AI fallback worker | Azure Container Apps |
| Worker image | GitHub Container Registry |
| Supporting web | `nutrilensx.tech` |
| Database | PostgreSQL |
| Cache | Redis |

## Verified Demo Paths

The current college-demo deployment has verified:

- email authentication
- Google authentication
- password reset
- packaged-food label scanning
- on-device/client evidence path
- Render → Azure server-inference fallback
- Personal Fit
- scan-grounded Ask Nutri
- authenticated worker access
- worker scale-to-zero

Exact QA evidence and historical engineering reports are retained only where appropriate and sanitized for source control.

## Security and Privacy

Do not commit:

- `.env`
- API keys
- JWT secrets
- database credentials
- Redis credentials
- worker tokens
- session exports
- private QA accounts
- keystores or signing credentials

Identifiable user data is not intended for sale.

Health Connect is optional.

Nutrition information provided by NutriLens X is informational and should not be treated as medical diagnosis or treatment advice.

## Development

Common quality checks include:

```bash
ruff check .
mypy backend
pytest
```

For Flutter:

```bash
cd apps/mobile
flutter analyze
flutter test
```

Run only the checks relevant to your change when working on the demo/release branch.

## Release

Android demo builds are distributed through **GitHub Releases**.

GitHub Releases are preferred over committing APK binaries directly into the source tree.

The current college-demo APK is a pre-release/testing artifact and is not presented as a Google Play production release.

## Contributors

**Yash Baid**  
Product development, architecture, Android, backend, AI integration and deployment.

**Prakruti Rathod — @Prakruti275**  
Repository collaboration, migration and release support.

GitHub's automatic contributor graph is generated from actual commit authorship. Contributor history is not rewritten solely for attribution.

## License

Add the final project license before treating this repository as a general open-source distribution.

Until then, repository availability should not be interpreted as granting unrestricted reuse rights.

---

**NutriLens X**  
Understand the label. Make a more informed choice.
