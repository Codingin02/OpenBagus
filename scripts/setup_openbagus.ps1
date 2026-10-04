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

# 7. Non-interactive bypass
if ($NonInteractive -or $SkipWizard) {
    Write-Host ""
    Write-Host "Setup completed successfully." -ForegroundColor Green
    exit 0
}

# 8. Interactive configuration & launch
Write-Host ""
$configure = Read-Host "Configure optional settings now? [y/N]"
if ($configure -and ($configure.Trim().ToLower() -eq "y" -or $configure.Trim().ToLower() -eq "yes")) {
    & $openbagusExe setup
}

Write-Host ""
Write-Host "Setup completed successfully." -ForegroundColor Green
Write-Host ""

$launch = Read-Host "Launch OpenBagus now? [Y/n]"
if ([string]::IsNullOrWhiteSpace($launch) -or $launch.Trim().ToLower().StartsWith("y")) {
    Write-Host "Starting OpenBagus..." -ForegroundColor Cyan
    & $openbagusExe
} else {
    Write-Host "You can launch OpenBagus anytime by running:"
    Write-Host "  .\.venv\Scripts\openbagus" -ForegroundColor Cyan
}
