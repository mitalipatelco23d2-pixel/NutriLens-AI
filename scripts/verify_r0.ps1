$ErrorActionPreference = "Stop"

Write-Host "Validating Docker Compose"
docker compose config --quiet

Write-Host "Validating live foundation health"
$health = Invoke-RestMethod "http://localhost:8000/api/v1/health"
if ($health.status -ne "healthy") {
    throw "Foundation health is '$($health.status)', expected 'healthy'."
}

Write-Host "Validating capability register"
& ".\.venv\Scripts\python.exe" scripts\validate_capability_register.py

Write-Host "Validating backend"
& ".\.venv\Scripts\ruff.exe" check backend tests scripts
& ".\.venv\Scripts\ruff.exe" format --check backend tests scripts
& ".\.venv\Scripts\mypy.exe" backend
& ".\.venv\Scripts\pytest.exe"

Write-Host "Validating web"
npm run verify:web
npm audit --omit=dev

$flutterCommand = Get-Command flutter -ErrorAction SilentlyContinue
$flutterExecutable = if ($flutterCommand) {
    $flutterCommand.Source
} elseif ($env:NUTRILENS_FLUTTER_BIN) {
    $env:NUTRILENS_FLUTTER_BIN
} else {
    throw "Flutter is not on PATH. Set NUTRILENS_FLUTTER_BIN to flutter.bat."
}

$dartExecutable = Join-Path (Split-Path $flutterExecutable) "dart.bat"
Write-Host "Validating Flutter"
Push-Location apps\mobile
& $dartExecutable format --output=none --set-exit-if-changed lib test
& $flutterExecutable analyze
& $flutterExecutable test
& $flutterExecutable test --dart-define=LIVE_API_BASE_URL=http://localhost:8000 test\live_health_test.dart
& $flutterExecutable build bundle --debug
Pop-Location

Write-Host "R0 static acceptance checks passed."
