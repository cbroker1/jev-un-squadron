@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\launchers\run_health_batch.ps1"
echo Health batch finished.
endlocal
