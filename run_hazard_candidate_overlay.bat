@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_hazard_candidate_overlay.ps1"
echo Hazard candidate overlay finished.
endlocal
