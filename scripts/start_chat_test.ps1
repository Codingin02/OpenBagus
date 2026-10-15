param([string]$Python = 'E:\Projects\OpenBagus\.venv\Scripts\python.exe')

$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & $Python -B -m openbagus.bootstrap
} finally {
    Pop-Location
}
