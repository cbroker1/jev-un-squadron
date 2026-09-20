@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_health_dense.ps1"
echo Dense health observation finished.
endlocal
