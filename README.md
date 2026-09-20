# NutriLens AI

NutriLens AI is a college team project that extracts structured nutrition and ingredient information from packaged-food labels. This repository currently contains Member 4's backend integration layer: safe image uploads, OpenCV/Pillow preprocessing, Tesseract OCR, conservative fallback parsing, stable team adapters, FastAPI endpoints, tests, Docker configuration, and a lightweight demo UI.

The integrated M2 path uses deterministic per-100-g nutrition rules and a
separate, verified ingredient-risk classifier. The older joblib scorer remains
available only through compatibility scoring routes; it is not part of core
readiness and is not the integrated NutriLens score.

## Runtime architecture

```text
Image upload
  -> size/type/decode/pixel validation
  -> EXIF orientation + Pillow/OpenCV preprocessing
  -> nutrition-panel candidates
  -> Tesseract spatial OCR
  -> nutrition/ingredient/allergen fallback parsing
  -> Member 1 analysis adapter
  -> Member 2 nutrition rules + verified ingredient-risk classifier
  -> Member 5 explanation/RAG adapters
  -> versioned API response for Member 3
```

`run_ocr(image_bytes, ...)`, `analyze_label_text(...)`, `predict_health(...)`, and `explain_analysis(...)` remain the stable integration seams. The OCR service itself remains abstracted even though Tesseract is the only supported MVP engine.

## Team ownership

- Member 1 owns final ingredient, additive, and allergen NLP. Member 4 supplies a conservative fallback and adapter.
- Member 2 owns the final health-risk/score model. Member 4 validates inputs, loads the existing artifact once, and exposes an adapter.
- Member 3 owns the final UI. Member 4 supplies stable API schemas and a small same-origin demo.
- Member 5 owns RAG/XAI explanations. Member 4 exposes optional adapters and never fabricates unavailable output.

## Main directories

```text
backend/app/api/          FastAPI routes
backend/app/core/         deterministic paths, settings, errors, logging
backend/app/ocr/          preprocessing, panel detection, Tesseract, spatial parser
backend/app/nlp/          Member 4 fallback ingredient/allergen parser
backend/app/scoring/      cached legacy joblib adapter
backend/app/services/     pipeline orchestration and team contracts
backend/app/schemas/      Pydantic request/response contracts
frontend/                 lightweight integration demo
tests/                    unit/API/pipeline tests
scripts/compare_ocr.py    development-only Tesseract benchmark diagnostics
```

## Prerequisites

- Python 3.12 (tested)
- Tesseract 5.x with English language data
- The approved M2 artifacts at `data/processed/m2/health_risk_model.pkl` and
  `data/processed/m2/tfidf_vectorizer.pkl`
- scikit-learn 1.9.1, pinned in `backend/requirements-base.txt` to match those
  verified artifacts

The optional legacy scorer at `data/processed/health_score_model.joblib` is
needed only for the manual and compatibility scoring routes.

On Windows, install Tesseract and either add it to `PATH` or set:

```cmd
set NUTRILENS_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

On Debian/Ubuntu, `sudo apt-get install tesseract-ocr` normally makes `tesseract` available on `PATH`.

## Local setup and run

From the repository root in Windows CMD:

```cmd
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000/` for the demo, `/docs` for OpenAPI, or run:

```cmd
.venv\Scripts\python.exe -m pytest -q
```

The application uses paths derived from the repository rather than the shell working directory, so it may also be started from `backend/` with an appropriate module path.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Lightweight liveness |
| `GET` | `/api/v1/ready` | Required core and optional-component readiness |
| `POST` | `/api/v1/ocr` | Tesseract OCR contract (`multipart` field `image`) |
| `POST` | `/api/v1/analyze-text` | Analyze supplied OCR text through team adapters |
| `POST` | `/api/v1/analyze` | Stable end-to-end team image endpoint |
| `POST` | `/api/v1/analyze/image` | Detailed Member 4 image-analysis response |
| `POST` | `/api/v1/score/manual` | Strict per-100-g legacy manual scoring |

The older `/health`, `/ready`, `/predict/health_score`, and `/predict/health_score_from_image` routes remain as compatibility aliases. An OCR request such as `/api/v1/ocr?engine=easyocr` is rejected with `422 invalid_ocr_engine`; it is not silently redirected.

Readiness requires the backend API, Tesseract, deterministic M2 nutrition
scoring, and the verified M2 ingredient-risk classifier. The response reports
the optional knowledge base, SHAP, RAG, and frontend independently. SHAP and
RAG being disabled by default do not make the core backend unavailable. The
readiness check never makes a hosted inference request.

Example:

```cmd
curl -F "image=@label.jpg" http://127.0.0.1:8000/api/v1/analyze
```

Responses explicitly include the detected basis. Per-100-ml observations are never converted to per-100-g without density data and are not sent to the current per-100-g scorer. Missing OCR values are omitted, not filled with zero.

## Environment variables

See `.env.example`. Common settings are `NUTRILENS_RISK_MODEL_PATH`,
`NUTRILENS_RISK_VECTORIZER_PATH`, `NUTRILENS_FRONTEND_DIR`,
`NUTRILENS_MAX_UPLOAD_BYTES`, `NUTRILENS_MAX_IMAGE_PIXELS`,
`NUTRILENS_OCR_LANGUAGE`, `NUTRILENS_TESSERACT_CMD`,
`NUTRILENS_CORS_ORIGINS`, and `NUTRILENS_LOG_LEVEL`.
`NUTRILENS_OCR_ENGINE` may remain `tesseract`; any other value fails clearly at
configuration load. `NUTRILENS_MODEL_PATH` configures only the optional legacy
development scorer.

## Docker Compose

The image is CPU-only and installs Tesseract, OpenCV, FastAPI, and the sklearn/joblib runtime. It contains no Torch or CUDA stack.

```cmd
docker compose config --quiet
docker compose up --build
```

The Compose file mounts `data/processed` read-only so the local model is not baked into the image.

## OCR decision note

During development, Tesseract and EasyOCR were evaluated internally on three real packaged-food labels. Tesseract was selected for the MVP based on overall structured accuracy, latency, dependency size, portability, and Docker/deployment simplicity. EasyOCR performed better on one difficult curved/dark label, but required a heavier PyTorch/CUDA stack and was slower on the tested hardware. This was a small engineering evaluation, not a scientific benchmark; product photos remain local and ignored by Git.

The retained `scripts/compare_ocr.py` command is a Tesseract-only development diagnostic. It reports raw text, normalized lines, nutrition evidence, candidate parse outcomes, runtime, and OCR-vs-parser failure classification without expanding the stable frontend API.

## Known limitations

- Glare, curved dark labels, low contrast, perspective, and multilingual surroundings can still prevent Tesseract recognition.
- Spatial parsing is conservative: ambiguous cells are omitted rather than guessed.
- Ingredient/allergen extraction is a basic explicit-text fallback until Member 1 integrates the final NLP module.
- Per-100-ml data is reported with its true basis but is not converted for the
  per-100-g M2 nutrition rules.
- The compatibility scorer requires all eight named features and must not be
  presented as the integrated M2 nutrition score.
- RAG and SHAP are optional and disabled by default; their disabled state does
  not affect core readiness.
