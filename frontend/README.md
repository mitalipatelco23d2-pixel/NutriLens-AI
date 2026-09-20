# NutriLens React frontend

This Vite/React client uses the stable multipart `POST /api/v1/analyze` API. It
does not call Cloudflare directly and never places provider credentials in the
browser bundle.

## Local development

Start the backend from the repository root, then run:

```powershell
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`. To use another backend during
development, set `VITE_BACKEND_ORIGIN` for the Vite process. For a separately
hosted production frontend, set `VITE_API_BASE_URL` at build time and configure
the backend CORS origin explicitly.

## Validation

```powershell
npm run lint
npm test
npm run build
```

The production build is written to `frontend/dist` and is intentionally ignored
by Git. The existing backend demo at `frontend/index.html` remains unchanged so
the current backend-only deployment does not break. To deploy the React client,
the deployment pipeline must run `npm ci && npm run build` and point
`NUTRILENS_FRONTEND_DIR` at `frontend/dist` (or copy that directory into the
runtime image). Do not point the backend at the Vite source directory.

## Contract and privacy notes

- Accepted uploads: JPEG, PNG, and WEBP; client preflight limit is 8 MiB.
- Analysis does not require authentication, so this client does not gate the
  stable endpoint behind a login or persist an access token.
- Raw OCR text is not present in the stable response. The client displays OCR
  metadata and parsed label fields without changing that privacy boundary.
- RAG, SHAP, the local knowledge base, and M2 components may independently be
  disabled or unavailable. The UI shows those states without substituting data.
