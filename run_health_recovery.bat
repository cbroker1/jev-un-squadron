@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_health_recovery.ps1"
echo Recovery probe finished.
endlocal
