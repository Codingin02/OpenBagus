@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_openbagus.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% NEQ 0 (
    echo OpenBagus setup or launcher returned exit code %EXIT_CODE%. See the preceding SETUP/RUNTIME status.
    if "%~1"=="" pause
)

exit /b %EXIT_CODE%
