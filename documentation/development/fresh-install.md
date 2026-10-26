# Fresh Installation

## Prerequisites

- Git
- Node.js 22+
- Python 3.12+
- Docker Desktop with Linux containers
- Flutter stable with Android or iOS tooling for device execution

## Setup

```powershell
git clone <repository-url> nutrilens-x
cd nutrilens-x
Copy-Item .env.example .env
npm ci
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r backend\requirements-dev.txt
docker compose config --quiet
docker compose up --build
```

Open the web app at `http://localhost:3000`, the API documentation at `http://localhost:8000/docs`, and Neo4j Browser at `http://localhost:7474`.

## Mobile

```powershell
Set-Location apps\mobile
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

Use `http://10.0.2.2:8000` for an Android emulator and `http://localhost:8000` for iOS simulator/desktop. A physical device must use the development machine's reachable LAN address.
Android packaging requires the Android SDK. iOS packaging requires macOS with Xcode. Static analysis, tests and the platform-neutral debug bundle can run without either device toolchain.

## Verification

```powershell
npm run verify:web
& '.\.venv\Scripts\ruff.exe' check backend tests
& '.\.venv\Scripts\ruff.exe' format --check backend tests
& '.\.venv\Scripts\mypy.exe' backend
& '.\.venv\Scripts\pytest.exe'
Set-Location apps\mobile
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter test --dart-define=LIVE_API_BASE_URL=http://localhost:8000 test\live_health_test.dart
flutter build bundle --debug
```

Install pre-commit with `pip install pre-commit`, run `pre-commit install`, and execute all hooks manually with `pre-commit run --all-files`.
