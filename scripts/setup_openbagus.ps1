<#
.SYNOPSIS
    One-click setup for OpenBagus on Windows.
.DESCRIPTION
    Detects Python, sets up a local virtual environment (.venv), installs OpenBagus,
    ensures local .env configuration, runs openbagus doctor, and optionally configures
    or launches OpenBagus.
#>

[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$SkipWizard
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $repoRoot) {
    $repoRoot = (Get-Location).Path
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " OpenBagus Setup" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Detect compatible Python
Write-Host "[....] Detecting compatible Python"
$pythonCmd = $null
$pythonVersion = $null
$candidates = @("python", "py")

foreach ($cand in $candidates) {
    $cmdObj = Get-Command $cand -ErrorAction SilentlyContinue
    if (-not $cmdObj) { continue }
    try {
        $ver = & $cand -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}'); sys.exit(0 if v >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver) {
            $pythonCmd = $cand
            $pythonVersion = $ver.Trim()
            break
        }
    } catch {
        continue
    }
}

if (-not $pythonCmd) {
    Write-Host "[FAIL] Compatible Python (>= 3.11) not found." -ForegroundColor Red
    Write-Host "Please install Python 3.11 or newer from https://www.python.org/"
    exit 1
}

Write-Host "[PASS] Python $pythonVersion" -ForegroundColor Green

# 2. Virtual environment (.venv)
Write-Host ""
Write-Host "[....] Preparing virtual environment"
$venvDir = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

$running = Get-Process -Name "openbagus" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "OpenBagus is currently running." -ForegroundColor Yellow
    Write-Host "Close the OpenBagus CLI and run setup again." -ForegroundColor Yellow
    exit 1
}

$sitePackages = Join-Path $venvDir "Lib\site-packages"
if (Test-Path $sitePackages) {
    $stale = Get-ChildItem -Path $sitePackages -Filter "~penbagus*" -ErrorAction SilentlyContinue
    if ($stale) {
        $stale | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $venvPython)) {
    & $pythonCmd -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Write-Host "[FAIL] Failed to create virtual environment in .venv." -ForegroundColor Red
        exit 1
    }
}
Write-Host "[PASS] Virtual environment ready" -ForegroundColor Green

# 3. Install OpenBagus
Write-Host ""
Write-Host "[....] Installing OpenBagus"
& $venvPython -m pip install -e $repoRoot --quiet --disable-pip-version-check --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Failed to install OpenBagus." -ForegroundColor Red
    exit 1
}
& $venvPython -m pip check --quiet 2>$null
Write-Host "[PASS] OpenBagus installed" -ForegroundColor Green

# 4. Verify CLI Entrypoint
Write-Host ""
Write-Host "[....] Verifying CLI entrypoint"
$openbagusExe = Join-Path $venvDir "Scripts\openbagus.exe"
if (-not (Test-Path $openbagusExe)) {
    Write-Host "[FAIL] openbagus command entry point not found in .venv." -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] openbagus command ready" -ForegroundColor Green

# 5. Local configuration (.env)
$envFile = Join-Path $repoRoot ".env"
$envExample = Join-Path $repoRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Host ""
        Write-Host "[PASS] Local configuration created (.env)" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "[PASS] Existing local configuration preserved (.env)" -ForegroundColor Green
}

# 6. Run doctor
Write-Host ""
Write-Host "[....] Running doctor"
Write-Host ""
& $openbagusExe doctor
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[FAIL] Doctor detected an issue." -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "[PASS] Doctor completed" -ForegroundColor Green

# 7. Local Language Model status (Qwen3-0.6B-Q8_0.gguf)
$appDataOpenBagus = Join-Path $env:LOCALAPPDATA "OpenBagus"
$modelsDir = Join-Path $appDataOpenBagus "models"
$binDir = Join-Path $appDataOpenBagus "bin"
$modelFile = Join-Path $modelsDir "Qwen3-0.6B-Q8_0.gguf"
$llamaExe = Join-Path $binDir "llama-cli.exe"

$llmState = "UNAVAILABLE"
try {
    $llmState = (& $venvPython -c "from openbagus.intelligence.local_language import LocalLanguageEngine; print(LocalLanguageEngine().get_runtime_state())").Trim()
} catch {
    $llmState = "UNAVAILABLE"
}

if ($llmState -eq "ACTIVE") {
    Write-Host ""
    Write-Host "[PASS] Local Language Engine: ACTIVE (Qwen3-0.6B-Q8_0.gguf)" -ForegroundColor Green
} elseif ($llmState -eq "FALLBACK") {
    Write-Host ""
    Write-Host "[WARN] Local Language Engine: FALLBACK (deterministic engine active)" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "[INFO] Local Language Model: UNAVAILABLE (optional ~639MB; deterministic engine active)"
}

# 8. Non-interactive bypass
if ($NonInteractive -or $SkipWizard) {
    Write-Host ""
    Write-Host "Setup completed successfully." -ForegroundColor Green
    exit 0
}

# 9. Interactive configuration & launch
if ($llmState -ne "ACTIVE") {
    Write-Host ""
    $dlModel = Read-Host "Download local language model (Qwen 0.6B, ~639MB)? (Y/N):"
    $dlLower = if ($dlModel) { $dlModel.Trim().ToLower() } else { "n" }
    if ($dlLower -eq "y") {
        Write-Host ""
        Write-Host "[....] Provisioning Local Language Engine"
        & $venvPython -c "from openbagus.intelligence.local_language import provision_local_runtime; import sys; sys.exit(0 if provision_local_runtime() else 1)"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[PASS] Local Language Engine: ACTIVE" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Local Language Engine download incomplete. Continuing with deterministic fallback." -ForegroundColor Yellow
        }
    }
}

Write-Host ""
$configure = Read-Host "Configure optional settings? (Y/N):"
$confLower = if ($configure) { $configure.Trim().ToLower() } else { "n" }
if ($confLower -eq "y") {
    & $openbagusExe setup
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[FAIL] Setup wizard encountered an issue (exit code $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "Setup completed successfully." -ForegroundColor Green
Write-Host ""

$launch = Read-Host "Launch OpenBagus now? (Y/N):"
$launchLower = if ($launch) { $launch.Trim().ToLower() } else { "y" }
if ($launchLower -eq "y" -or $launchLower -eq "") {
    Write-Host "Starting OpenBagus..." -ForegroundColor Cyan
    & $openbagusExe
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} else {
    Write-Host "You can launch OpenBagus anytime by running:"
    Write-Host "  .\.venv\Scripts\openbagus" -ForegroundColor Cyan
}
