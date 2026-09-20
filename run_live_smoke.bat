@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_live_smoke.ps1"
echo Five-call live Jev smoke test finished.
endlocal
