# 1. NutriLens-AI

NutriLens-AI is a college-project prototype that helps a user read a packaged
food label. The user uploads a photograph, and the application tries to extract
the nutrition table, ingredients, allergens, and additives that are visible in
the image. It can then show separate nutrition and ingredient analysis when the
extracted information is reliable enough.

The project was created to make dense food labels easier to inspect during a
local demonstration. It is **not** a medical diagnosis, clinical tool, or
guarantee that a food is safe. Important results should always be checked
against the original package label.

This guide explains how to install and run the complete project locally on a
Windows 10 or Windows 11 laptop.

## 2. What the project can do

The current application can:

- Upload JPEG, PNG, or WEBP food-label photographs and preview them in the
  browser.
- Read label text locally with Tesseract OCR.
- Extract available nutrition values, the nutrition basis, ingredients,
  allergens, and additives.
- Produce a deterministic M2 nutrition score when the label provides enough
  supported per-100-g nutrition information.
- Produce a separate M2 ingredient-risk prediction when a reliable ingredient
  list and the verified model files are available.
- Provide M5 knowledge-base explanations and careful recommendations when its
  verified dataset and reliable inputs are available.
- Show complete, partial, and unavailable component results in a React
  frontend backed by a FastAPI API.
- Provide tested backend registration, login, and current-user endpoints using
  a local SQLite database. The current image-analysis page does not require a
  user to sign in.

The application deliberately avoids guessing. A blurry photograph, incomplete
label, unsupported nutrition basis, or unreliable ingredient section can
produce a partial or unavailable result. Not every image will receive a
nutrition score or ingredient-risk prediction.

## 3. How it works

```text
Food-label image
        ↓
Tesseract OCR
        ↓
Nutrition and ingredient extraction (M1)
        ↓
Nutrition score and ingredient-risk prediction (M2)
        ↓
Knowledge-base explanations and recommendations (M5)
        ↓
Results shown in the React frontend
```

The **React frontend** runs in the browser. It lets the user select an image,
shows the preview, sends the image to the local API, and displays the response.

The **FastAPI backend** validates the upload, runs OCR and extraction, applies
the available analysis stages, and returns a structured result. Missing values
are not treated as zero. Ingredient-dependent analysis is withheld when the
ingredient text is not trustworthy.

## 4. What to install before starting

Install all four tools below before downloading the project. After each
installer finishes, close PowerShell, open a new PowerShell window, and run the
listed check.

### 4.1 Git for Windows

1. Download Git from [Git for Windows](https://git-scm.com/downloads/win).
2. Run the 64-bit installer on a normal Intel/AMD Windows laptop.
3. Keep the option that makes Git available from the command line. The default
   installer settings are suitable for this project.
4. Open a new PowerShell window and check it:

```powershell
git --version
```

### 4.2 Python 3.12

This project requires **Python 3.12**, not Python 3.11, 3.13, or 3.14.

1. Open the [official Python downloads page](https://www.python.org/downloads/).
2. Select a Python 3.12 release with a Windows 64-bit installer. If the main
   page promotes a newer Python series, the
   [Python 3.12.10 release page](https://www.python.org/downloads/release/python-31210/)
   provides the final full Python 3.12 maintenance installer for Windows.
3. Run the 64-bit installer.
4. Enable **Add python.exe to PATH** and install the Python launcher when those
   options are shown.
5. Open a new PowerShell window and check it:

```powershell
py -3.12 --version
```

The result must start with `Python 3.12`.

If `py -3.12` fails even though Python 3.12 is installed, list the Python
installations that Windows can find:

```powershell
py --list-paths
Get-Command python -All
```

Common Python 3.12 locations are:

```text
C:\Users\YOUR-NAME\AppData\Local\Programs\Python\Python312\python.exe
C:\Program Files\Python312\python.exe
```

Test the actual path with the call operator (`&`):

```powershell
& 'C:\path\to\Python312\python.exe' --version
```

If this works, use that full path instead of `py -3.12` in the virtual
environment command in section 6.

### 4.3 Node.js LTS and npm

1. Download the LTS version from the
   [official Node.js download page](https://nodejs.org/en/download).
2. Choose the Windows installer for the laptop's architecture. Most laptops
   use x64.
3. Keep the installer option that adds Node.js to `PATH`. npm is included with
   Node.js.
4. Open a new PowerShell window and check both commands:

```powershell
node --version
npm --version
```

Use the current Node.js LTS release. The committed frontend dependencies support
Node.js `20.19.0` or newer in the 20.x series, `22.12.0` or newer in the 22.x
series, or Node.js 24 and newer.

### 4.4 Tesseract OCR for Windows

Tesseract does not currently publish its own modern Windows installer. The
Tesseract documentation points Windows users to community builds such as the
[UB Mannheim Tesseract installers](https://github.com/UB-Mannheim/tesseract/wiki).

1. Download a current 64-bit Tesseract 5.x installer from that page.
2. Run the installer and keep the English language data (`eng`) selected.
3. Note the installation folder. A common location is:

```text
C:\Program Files\Tesseract-OCR
```

4. If the installer offers to add that folder to `PATH`, enable it. Otherwise,
   section 9 explains how to configure the executable directly.
5. Open a new PowerShell window and check it:

```powershell
tesseract --version
```

## 5. Download the project

The repository is private. Your GitHub account must have access, and Git may
ask you to sign in through Git Credential Manager.

Until the integration pull request is merged into `main`, clone the tested
`team-integration` branch:

```powershell
git clone --branch team-integration https://github.com/mitalipatelco23d2-pixel/NutriLens-AI.git
cd NutriLens-AI
```

All remaining commands assume PowerShell is in the new `NutriLens-AI` folder.
Confirm the branch before continuing:

```powershell
git branch --show-current
```

It should print `team-integration`.

After this branch is reviewed and safely merged, a normal clone of `main` will
become the correct setup:

```powershell
git clone https://github.com/mitalipatelco23d2-pixel/NutriLens-AI.git
```

Do not use the main-branch command before the integration is merged.

## 6. Install backend dependencies

Run this entire section from the repository root—the folder that contains
`README.md`, `backend`, `frontend`, and `data`.

1. Confirm Python 3.12:

```powershell
py -3.12 --version
```

2. Create an isolated virtual environment:

```powershell
py -3.12 -m venv .venv
```

If the Python launcher failed in section 4, use the verified full path instead:

```powershell
& 'C:\path\to\Python312\python.exe' -m venv .venv
```

3. Upgrade pip and install the pinned runtime and test dependencies:

```powershell
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

4. Confirm the important runtime versions:

```powershell
& .\.venv\Scripts\python.exe --version
& .\.venv\Scripts\python.exe -c "import fastapi, sklearn, cv2, pytesseract; print('FastAPI:', fastapi.__version__); print('scikit-learn:', sklearn.__version__); print('OpenCV:', cv2.__version__); print('pytesseract:', pytesseract.__version__)"
```

Python must be 3.12 and scikit-learn must be `1.9.1`. Do not install
`backend\requirements-shap.txt` for the basic demo.

## 7. Install frontend dependencies

The frontend's `package.json` and `package-lock.json` are inside the `frontend`
folder.

From the repository root, run:

```powershell
Set-Location frontend
npm ci
Set-Location ..
```

`npm ci` installs the exact versions recorded in the lockfile. You should now
be back in the repository root. Check with:

```powershell
Get-Location
Test-Path frontend\package.json
```

The final command should print `True`.

## 8. Required model and knowledge-base files

Cloning the repository is **not enough** for the complete demo. Three approved
files are deliberately excluded from Git and must be obtained privately from a
trusted project-team member:

| File | Exact destination | Expected SHA-256 |
| --- | --- | --- |
| `health_risk_model.pkl` | `data/processed/m2/health_risk_model.pkl` | `55397e61da7b9e6b22c88d2757c75dcd8b1b8b894f93a63ca59752bb159f50e8` |
| `tfidf_vectorizer.pkl` | `data/processed/m2/tfidf_vectorizer.pkl` | `ca053bfc80dca02de68e21294f675a2416aa62be3377f6c0ffb8eef9affda677` |
| `nutrilens_knowledge_base_final.csv` | `data/external/m5/nutrilens_knowledge_base_final.csv` | `667d2fe0950183d84fc2973f9164fd2b20892d12872bb7286ff5a2661c04a046` |

The repository does not grant permission to redistribute these files. Do not
upload them to GitHub or a public file-sharing service. Python pickle files can
execute code when loaded, so never use a model or vectorizer from an untrusted
source—even if it has the expected filename.

Ask a trusted team member for the approved files on an encrypted USB drive or
through another team-approved private transfer. Suppose the three files are in
`E:\NutriLens-demo-artifacts`. From the repository root, run:

```powershell
$artifactSource = 'E:\NutriLens-demo-artifacts'
New-Item -ItemType Directory -Force -Path data\processed\m2, data\external\m5 | Out-Null
Copy-Item -LiteralPath "$artifactSource\health_risk_model.pkl" -Destination data\processed\m2\health_risk_model.pkl
Copy-Item -LiteralPath "$artifactSource\tfidf_vectorizer.pkl" -Destination data\processed\m2\tfidf_vectorizer.pkl
Copy-Item -LiteralPath "$artifactSource\nutrilens_knowledge_base_final.csv" -Destination data\external\m5\nutrilens_knowledge_base_final.csv
```

Verify every copied file:

```powershell
Get-FileHash -Algorithm SHA256 data\processed\m2\health_risk_model.pkl
Get-FileHash -Algorithm SHA256 data\processed\m2\tfidf_vectorizer.pkl
Get-FileHash -Algorithm SHA256 data\external\m5\nutrilens_knowledge_base_final.csv
```

Compare every complete hash with the table. Stop if any value differs. The
backend also checks the model and vectorizer hashes before loading them.

These files are ignored by Git. Do not use `git add -f` to add them. The
optional generated RAG corpus under `data/processed/rag` is not required for
the basic demo.

## 9. Configure the project

### 9.1 Backend configuration

From the repository root, copy the safe example file:

```powershell
Copy-Item .env.example .env
```

Generate a new random JWT secret and replace the placeholder in `.env`:

```powershell
$jwtSecret = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
(Get-Content .env -Raw).Replace('replace-with-a-long-random-secret', $jwtSecret) | Set-Content .env -Encoding utf8
Remove-Variable jwtSecret
```

The JWT secret is used by the tested backend login endpoints. Keep `.env`
private; it is ignored by Git.

The required model/vectorizer paths and hashes already match section 8. The
knowledge-base path is optional for API readiness but is required for the full
M5 demo. SQLite automatically uses `data/nutrilens.db`, so no database server
is needed.

If `tesseract --version` did not work, open `.env` in Notepad:

```powershell
notepad .env
```

Find this commented line:

```dotenv
# NUTRILENS_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

Remove `# ` and change the path if Tesseract was installed elsewhere:

```dotenv
NUTRILENS_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

For the basic local demo, keep these settings unchanged:

```dotenv
NUTRILENS_M5_SHAP_ENABLED=false
NUTRILENS_M5_RAG_ENABLED=false
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
```

Cloudflare and Azure are not required.

### 9.2 Frontend configuration

Create the frontend's local environment file from the tracked example:

```powershell
Copy-Item frontend\.env.example frontend\web\.env.local
```

For local development, keep:

```dotenv
VITE_API_BASE_URL=
VITE_ANALYSIS_ENABLED=true
VITE_MAX_UPLOAD_BYTES=8388608
```

An empty API base makes the browser use Vite's local `/api` proxy. Never put a
password, token, JWT secret, or other credential in a `VITE_*` variable because
Vite includes those values in browser files.

## 10. Run the project

The backend and frontend are two separate programs. Open **two PowerShell
windows** and keep both windows open during the demo.

### Terminal 1 — backend

Open PowerShell in the repository root. The prompt should be inside the folder
that contains `backend` and `.venv`. Run:

```powershell
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Wait until the terminal says Uvicorn is running on `http://127.0.0.1:8000`.

### Terminal 2 — frontend

Open another PowerShell window in the repository root. Run:

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Wait until Vite shows its local address, then open:

<http://127.0.0.1:5173>

Leave both PowerShell windows open. To stop the project, click each terminal
window and press `Ctrl+C`. Confirm termination if PowerShell asks.

## 11. Check whether everything works

1. Open <http://127.0.0.1:5173>. The NutriLens upload page should appear.
2. Check that the backend process is alive:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
   ```

   A working backend returns a response containing `"status": "alive"`.

3. Check required dependencies:

   ```powershell
   curl.exe -i http://127.0.0.1:8000/api/v1/ready
   ```

   A complete local setup returns `HTTP/1.1 200 OK` and overall status
   `ready`. Disabled optional RAG or SHAP entries can report that they are not
   ready without making the core application unavailable.

   `HTTP 503` means a required dependency—such as Tesseract or the verified M2
   artifacts—is missing or invalid. Read the dependency details in the
   response and fix the problem; do not ignore the 503.

4. On the frontend, select a clear food-label photograph. Check its preview,
   then choose **Analyze nutrition label**.
5. Compare the extracted basis, nutrition values, and ingredients with the
   visible package label.

Result meanings:

- **Complete/success:** the main pipeline completed, but important extracted
  values should still be checked against the photograph.
- **Partial:** useful information was recovered, but one or more fields or
  downstream components were unavailable or withheld.
- **Unavailable:** the component did not have enough reliable input, a required
  local file was missing, or the label format was unsupported. The application
  does not invent a replacement value.

## 12. Common problems and solutions

### `python` or `py -3.12` is not found

Close and reopen PowerShell after installing Python. Run `py --list-paths` and
`Get-Command python -All`. If a Python 3.12 executable exists, use its full path
as shown in sections 4 and 6.

### Python 3.12 is not installed

Install the Windows 64-bit Python 3.12 installer from the official link in
section 4. Do not create this project's environment with another Python
version.

### PowerShell blocks virtual-environment activation

Activation is not required: every backend command in this guide calls
`.venv\Scripts\python.exe` directly. If you still want to activate it for the
current terminal only, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\.venv\Scripts\Activate.ps1
```

### `npm` is not recognized

Install Node.js LTS, keep the installer option that adds it to `PATH`, and open
a new PowerShell window. Then run `node --version` and `npm --version` again.

### `tesseract` is not found

Confirm the installation folder. Either add that folder to the Windows `PATH`
or set `NUTRILENS_TESSERACT_CMD` in `.env` to the full `tesseract.exe` path.
Restart the backend after changing `.env`.

### Model, vectorizer, or knowledge-base file is missing

Repeat section 8 from the repository root. Check the spelling and exact folder
structure. Do not substitute a similarly named file downloaded from the
internet.

### An artifact checksum is incorrect

Do not start the demo with that artifact. Delete only the incorrect copied file
and obtain the approved version again from a trusted team member. Never bypass
the application's hash checks.

### scikit-learn model compatibility error

Check the installed version:

```powershell
& .\.venv\Scripts\python.exe -c "import sklearn; print(sklearn.__version__)"
```

It must print `1.9.1`. If it does not, reinstall the pinned dependencies:

```powershell
& .\.venv\Scripts\python.exe -m pip install --force-reinstall -r backend\requirements-dev.txt
```

### Backend or frontend port is already in use

To move the backend to port 8001, start it with:

```powershell
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001
```

Before starting Vite in the second terminal, point its proxy to that port:

```powershell
Set-Location frontend
$env:VITE_BACKEND_ORIGIN='http://127.0.0.1:8001'
npm run dev -- --host 127.0.0.1 --port 5173
```

If port 5173 is busy, change the frontend command to `--port 5174` and open
<http://127.0.0.1:5174>.

### The frontend opens but API requests fail

Confirm the backend terminal is still running and `/api/v1/health` works.
Keep `VITE_API_BASE_URL` empty for local development. Restart Vite after
changing a frontend environment value or `VITE_BACKEND_ORIGIN`.

### The label image is blurry or unreadable

Retake the photograph in bright, diffuse light. Avoid glare, fill the frame
with the label, keep the camera parallel to the package, and flatten curved
packaging where possible. Photograph the nutrition table and ingredients
clearly. Some poor images cannot be fixed reliably by software.

### GitHub says the repository does not exist or access is denied

This is a private repository. Sign in to the GitHub account that the team has
authorized. Ask the repository owner for access if needed. Do not use another
person's credentials.

## 13. Project status and future improvements

NutriLens-AI is ready for a controlled local college demonstration. It is not
production-ready or clinically validated. OCR can still struggle with curved,
glossy, tilted, rotated, low-resolution, or mixed-language labels. Unusual
nutrition tables and separated ingredient panels can also reduce extraction
quality.

Planned improvements include:

- Evaluating OCR and extraction on a manually annotated set of previously
  unseen food labels.
- Improving orientation, perspective, glare, and nutrition-panel handling.
- Improving ingredient-section boundaries and mixed-language extraction.
- Adding clearer image-retake guidance and field-level confidence reporting.
- Reviewing artifact and dataset licensing before choosing any distribution
  method.

Future work must preserve the current safeguards: missing values must not be
invented, unreliable ingredient text must not drive confident predictions, and
analysis must not be presented as medical or food-safety advice.
