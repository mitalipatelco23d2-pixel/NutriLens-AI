[CmdletBinding()]
param(
    [ValidateSet("aab", "apk", "both")]
    [string]$Artifact = "aab",
    [string]$ApiBaseUrl = "https://api.nutrilensx.tech",
    [string]$GoogleServerClientId = $env:NUTRILENS_GOOGLE_SERVER_CLIENT_ID,
    [string]$GoogleClientId = $env:NUTRILENS_GOOGLE_ANDROID_CLIENT_ID,
    [string]$FlutterBin = $env:NUTRILENS_FLUTTER_BIN
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$mobileRoot = Join-Path $repositoryRoot "apps\mobile"

if ([string]::IsNullOrWhiteSpace($FlutterBin)) {
    $flutterCommand = Get-Command flutter -ErrorAction SilentlyContinue
    if ($flutterCommand) {
        $FlutterBin = $flutterCommand.Source
    } else {
        $configuredSdk = "C:\Users\yash0\.cache\flutter-sdk-3.44.4\flutter\bin\flutter.bat"
        if (Test-Path -LiteralPath $configuredSdk) {
            $FlutterBin = $configuredSdk
        }
    }
}
if ([string]::IsNullOrWhiteSpace($FlutterBin) -or !(Test-Path -LiteralPath $FlutterBin)) {
    throw "Set NUTRILENS_FLUTTER_BIN to the trusted Flutter executable."
}

$apiUri = $null
if (
    ![Uri]::TryCreate($ApiBaseUrl, [UriKind]::Absolute, [ref]$apiUri) -or
    $apiUri.Scheme -ne "https" -or
    $apiUri.Host -ne "api.nutrilensx.tech"
) {
    throw "Release builds require https://api.nutrilensx.tech."
}
if ([string]::IsNullOrWhiteSpace($GoogleServerClientId)) {
    throw "Set NUTRILENS_GOOGLE_SERVER_CLIENT_ID to the backend-audience OAuth client ID."
}

$signingVariables = @(
    "NUTRILENS_ANDROID_KEYSTORE",
    "NUTRILENS_ANDROID_STORE_PASSWORD",
    "NUTRILENS_ANDROID_KEY_ALIAS",
    "NUTRILENS_ANDROID_KEY_PASSWORD"
)
foreach ($variableName in $signingVariables) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($variableName))) {
        throw "Release signing is incomplete: set $variableName in the local environment."
    }
}
$keystorePath = [Environment]::GetEnvironmentVariable("NUTRILENS_ANDROID_KEYSTORE")
if (!(Test-Path -LiteralPath $keystorePath -PathType Leaf)) {
    throw "NUTRILENS_ANDROID_KEYSTORE must reference an existing owner-controlled keystore."
}

$dartDefines = @(
    "--dart-define=API_BASE_URL=$ApiBaseUrl",
    "--dart-define=APP_ENVIRONMENT=production",
    "--dart-define=GOOGLE_SERVER_CLIENT_ID=$GoogleServerClientId"
)
if (![string]::IsNullOrWhiteSpace($GoogleClientId)) {
    $dartDefines += "--dart-define=GOOGLE_CLIENT_ID=$GoogleClientId"
}

Push-Location $mobileRoot
try {
    & $FlutterBin analyze
    if ($LASTEXITCODE -ne 0) { throw "Flutter analysis failed." }
    & $FlutterBin test
    if ($LASTEXITCODE -ne 0) { throw "Flutter tests failed." }

    $artifacts = @()
    if ($Artifact -in @("aab", "both")) {
        & $FlutterBin build appbundle --release @dartDefines
        if ($LASTEXITCODE -ne 0) { throw "Release AAB compilation failed." }
        $artifacts += Join-Path $mobileRoot "build\app\outputs\bundle\release\app-release.aab"
    }
    if ($Artifact -in @("apk", "both")) {
        & $FlutterBin build apk --release @dartDefines
        if ($LASTEXITCODE -ne 0) { throw "Release APK compilation failed." }
        $artifacts += Join-Path $mobileRoot "build\app\outputs\flutter-apk\app-release.apk"
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($artifactPath in $artifacts) {
        if (!(Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
            throw "Expected release artifact was not produced."
        }
        $archive = [System.IO.Compression.ZipFile]::OpenRead($artifactPath)
        try {
            $forbiddenModels = @(
                $archive.Entries | Where-Object {
                    $_.FullName -match "(?i)\.(onnx|pt|pth|tflite)$"
                }
            )
            if ($forbiddenModels.Count -gt 0) {
                throw "Release artifact contains a blocked model file."
            }
        } finally {
            $archive.Dispose()
        }
        $hash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        [pscustomobject]@{
            Artifact = $artifactPath
            Bytes = (Get-Item -LiteralPath $artifactPath).Length
            Sha256 = $hash
            BlockedModels = 0
        }
    }
} finally {
    Pop-Location
}
