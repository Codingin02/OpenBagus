# OpenBagus Dashboard Local Web Server
# Serves the static PWA dashboard from reports/runtime/app

$Port = 8080
$AppDir = Join-Path $PSScriptRoot "..\reports\runtime\app"

if (-not (Test-Path $AppDir)) {
    Write-Host "[OpenBagus] Error: Dashboard directory not found at $AppDir" -ForegroundColor Red
    Write-Host "[OpenBagus] Please run scripts\build_openbagus_static_app.py first." -ForegroundColor Yellow
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " OpenBagus PWA Dashboard Server" -ForegroundColor Cyan
Write-Host " Listening on: http://localhost:$Port" -ForegroundColor Green
Write-Host " Press Ctrl+C to terminate." -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Cyan

python -m http.server $Port --directory $AppDir
