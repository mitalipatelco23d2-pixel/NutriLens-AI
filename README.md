# NutriLens AI

NutriLens AI is a college team project for local analysis of packaged-food
labels. A user uploads a JPEG, PNG, or WEBP photograph through the React
interface; the FastAPI backend runs Tesseract OCR, extracts nutrition and label
information, applies the integrated M2 scoring components, and returns M5
knowledge-base explanations and conservative recommendations where evidence is
available.

This repository is currently prepared for a **local Windows demonstration**.
It is not a clinical system, and difficult photographs can produce partial or
unavailable results. The ingredient-quality gate intentionally suppresses the
ingredient-risk classifier and ingredient-dependent explanations when OCR text
is missing, incomplete, or contaminated by other packaging text.

## What is integrated

- React 19 and Vite upload interface with image preview and explicit component
  availability states.
- FastAPI upload validation and stable `POST /api/v1/analyze` response.
- Pillow/OpenCV preprocessing, orientation selection, nutrition-region
  candidates, and Tesseract OCR.
- M1 nutrition, ingredient, allergen, additive, basis, and confidence-aware
  extraction.
- M2 deterministic per-100-g nutrition score plus a separate verified
  scikit-learn ingredient-risk classifier.
- M5 deterministic knowledge-base matching, nutrition explanations, and
  non-diagnostic label-reading recommendations.
- Optional SHAP and source-backed RAG integrations, both disabled by default.
- Local SQLite support for user accounts. Image analysis itself currently does
  not require authentication.

```text
React/Vite (http://127.0.0.1:5173)
        │  /api development proxy
        ▼
FastAPI (http://127.0.0.1:8000)
        ▼
OCR → M1 structured extraction → M2 scoring/risk → M5 explanations
```

## Important limitations

- Glare, blur, curvature, perspective, low resolution, mixed-language text,
  and incomplete label photographs can reduce OCR and extraction accuracy.
- Missing nutrients are never invented or treated as zero. Per-100-ml and
  per-serving values are not converted to per 100 g without sufficient data.
- Partial, untrusted, or absent ingredient extraction cannot produce an M2
  ingredient-risk prediction, ingredient-based KB match, or ingredient-based
  recommendation/RAG context.
- A successful HTTP response does not prove that every extracted value is
  correct. Compare important values with the visible label.
- The ingredient-risk model is a college-project classifier and is **not
  clinically validated**. Outputs are not medical or food-safety advice.
- SHAP and RAG are optional. The basic local demo needs neither a Cloudflare
  account nor a Cloudflare API token.

## Verified prerequisites

The reviewed development machine used the following versions:

| Tool | Verified version | Supported setup guidance |
| --- | --- | --- |
| Python | 3.12.14 | Use Python 3.12.x |
| scikit-learn | 1.9.1 | Installed from the pinned backend requirements |
| Node.js | 24.18.0 | Vite requires `^20.19.0` or `>=22.12.0` |
| npm | 11.16.0 | Installed with Node.js |
| Tesseract | 5.4.0 | Install Tesseract 5.x with English data |
| Git for Windows | 2.55.0 | A current Git for Windows release |

Install Python, Node.js, Git, and Tesseract before continuing. During the
Tesseract installer, include the English language data. Adding Tesseract to
`PATH` is convenient but not required because its executable can be configured
in `.env`.

## Clone and install on Windows

Run these commands in PowerShell. Choose any normal development directory;
do not clone into an existing NutriLens project.

```powershell
git clone https://github.com/mitalipatelco23d2-pixel/NutriLens-AI.git
Set-Location NutriLens-AI

py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

Set-Location frontend
npm ci
Set-Location ..
```

`backend/requirements-dev.txt` installs the complete core runtime and pytest.
Do not install `backend/requirements-shap.txt` for the basic demo.

## Required local artifacts

The model, vectorizer, and teammate knowledge-base CSV are intentionally not in
Git. There is no repository documentation granting redistribution permission,
and the CSV is treated by the application as an unverified teammate-provided
dataset. Do not upload these files to GitHub or a public file-sharing service.
A fresh clone alone is therefore **not sufficient** for the complete demo.

Obtain the three previously approved files from the team member who owns or is
authorized to share them. Transfer them directly with an encrypted USB drive or
another team-approved private method. Do not include `.env`, `nutrilens.db`,
test photographs, or credentials in the transfer.

Place the files at these exact relative paths:

| File | Destination | Expected SHA-256 |
| --- | --- | --- |
| `health_risk_model.pkl` | `data/processed/m2/health_risk_model.pkl` | `55397e61da7b9e6b22c88d2757c75dcd8b1b8b894f93a63ca59752bb159f50e8` |
| `tfidf_vectorizer.pkl` | `data/processed/m2/tfidf_vectorizer.pkl` | `ca053bfc80dca02de68e21294f675a2416aa62be3377f6c0ffb8eef9affda677` |
| `nutrilens_knowledge_base_final.csv` | `data/external/m5/nutrilens_knowledge_base_final.csv` | `667d2fe0950183d84fc2973f9164fd2b20892d12872bb7286ff5a2661c04a046` |

Example transfer on the demo laptop (change only `$artifactSource`):

```powershell
$artifactSource = 'E:\NutriLens-demo-artifacts'
New-Item -ItemType Directory -Force data\processed\m2, data\external\m5 | Out-Null
Copy-Item -LiteralPath "$artifactSource\health_risk_model.pkl" -Destination data\processed\m2\health_risk_model.pkl
Copy-Item -LiteralPath "$artifactSource\tfidf_vectorizer.pkl" -Destination data\processed\m2\tfidf_vectorizer.pkl
Copy-Item -LiteralPath "$artifactSource\nutrilens_knowledge_base_final.csv" -Destination data\external\m5\nutrilens_knowledge_base_final.csv
```

Verify all three files before starting the application:

```powershell
Get-FileHash -Algorithm SHA256 data\processed\m2\health_risk_model.pkl
Get-FileHash -Algorithm SHA256 data\processed\m2\tfidf_vectorizer.pkl
Get-FileHash -Algorithm SHA256 data\external\m5\nutrilens_knowledge_base_final.csv
```

Compare the complete hashes with the table above. Pickle files can execute code
when deserialized, so use only the approved files with matching hashes. The
backend also verifies the configured hashes before loading either M2 artifact.

The generated RAG corpus under `data/processed/rag` is not needed for the basic
demo and should not be transferred. The optional legacy
`data/processed/health_score_model.joblib` is also not part of integrated M2
readiness.

## Local configuration

Create a private backend `.env` from the tracked example and replace the JWT
placeholder with a random local value:

```powershell
Copy-Item .env.example .env
$jwtSecret = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
(Get-Content .env -Raw).Replace('replace-with-a-long-random-secret', $jwtSecret) | Set-Content .env
```

If `tesseract --version` fails, uncomment and adjust this line in `.env`:

```dotenv
NUTRILENS_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

The default artifact paths and reviewed hashes are already recorded in
`.env.example` and the backend. Only change them when the team has approved a
different artifact and corresponding SHA-256 digest.

For the React development server, create its local environment file:

```powershell
Copy-Item frontend\.env.example frontend\web\.env.local
```

Keep `VITE_API_BASE_URL` empty, keep `VITE_ANALYSIS_ENABLED=true`, and use the
default Vite proxy for the local demo. Never place backend credentials in a
`VITE_*` variable: those values are included in browser code.

## Start the local demo

Open two PowerShell terminals in the repository root.

Terminal 1 — backend:

```powershell
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — React frontend:

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open <http://127.0.0.1:5173>. Vite sends browser requests beginning with
`/api` to `http://127.0.0.1:8000`; `localhost` is never used as a public API.
The FastAPI OpenAPI page is available at <http://127.0.0.1:8000/docs>.

Check liveness and readiness before demonstrating an upload:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
curl.exe -i http://127.0.0.1:8000/api/v1/ready
```

`/health` confirms that the API process is running. `/ready` returns HTTP 200
only when the required API, Tesseract, nutrition-scoring, and verified M2
ingredient-risk components are ready. Knowledge-base, SHAP, RAG, and frontend
status are reported separately; disabled SHAP/RAG do not make core readiness
fail.

## Demonstrating an analysis

1. Use a clear, straight-on photograph showing the nutrition table and, when
   possible, a separate ingredients photograph or a frame containing both.
2. Select the image and confirm its preview before choosing **Analyze nutrition
   label**.
3. Check the detected basis and compare extracted values with the visible label.
4. Explain `partial` or `unavailable` sections honestly. For example, an
   unsupported per-100-ml basis may preserve nutrition values without producing
   the per-100-g score.
5. Check the ingredient extraction quality. `partial`, `untrusted`, and
   `absent` deliberately suppress ingredient-driven M2/M5 results.

The frontend never fabricates a result when the API or a component is
unavailable.

## Testing

From the repository root:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

From the frontend directory:

```powershell
Set-Location frontend
npm test
npm run lint
npm run build
```

The production build is written to `frontend/dist` and is ignored by Git. Local
development should use the Vite server at port 5173 so its `/api` proxy remains
active.

## Windows troubleshooting

### PowerShell blocks virtual-environment activation

Activation is optional because every documented backend command calls the
virtual-environment Python directly. If desired, enable activation only for the
current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\.venv\Scripts\Activate.ps1
```

### Tesseract is not found

Run `tesseract --version`. If it is not on `PATH`, set
`NUTRILENS_TESSERACT_CMD` in `.env` to the installed `tesseract.exe`. Restart
the backend after editing `.env`.

### Model unavailable or scikit-learn version mismatch

Confirm both M2 files exist at the documented paths and their complete hashes
match. Then run:

```powershell
& .\.venv\Scripts\python.exe -c "import sklearn; print(sklearn.__version__)"
```

It must print `1.9.1`. Reinstall `backend\requirements-dev.txt` if it does not.

### Knowledge base unavailable

The API remains usable, but M5 lookup will be unavailable. Verify the CSV path
and hash, then restart the backend. Do not replace it with an unreviewed CSV.

### Frontend cannot reach the backend

Confirm the backend is listening on port 8000, `VITE_API_BASE_URL` is blank,
and the React page was opened on port 5173. Restart Vite after changing any
frontend environment value.

If port 8000 is already in use, start the backend on 8001 and set the proxy
origin before starting Vite:

```powershell
$env:VITE_BACKEND_ORIGIN='http://127.0.0.1:8001'
npm run dev -- --host 127.0.0.1 --port 5173
```

### Image produces incomplete output

Retake the photograph with diffuse lighting, the package flattened where
possible, the label filling the frame, and the camera parallel to the label.
Partial output is safer than guessed nutrition or ingredients.

## Team responsibilities

The repository documents responsibilities by project member number only:

- Member 1: ingredient, additive, allergen, and nutrition NLP integration.
- Member 2: nutrition scoring and ingredient-risk classifier artifacts.
- Member 3: React frontend.
- Member 4: OCR, backend integration, stable API contracts, and fallbacks.
- Member 5: knowledge-base, explanation, optional SHAP, and optional RAG work.

No personal contributor names are asserted here because they are not confirmed
in the repository documentation.

## Development roadmap

- Evaluate OCR and extraction against a manually annotated independent test set.
- Improve ingredient-region confidence and multilingual label handling without
  product-specific rules.
- Review artifact and dataset licensing before selecting a team distribution
  mechanism.
- Keep RAG and SHAP optional until their runtime, evidence, privacy, and
  evaluation requirements are independently validated.
