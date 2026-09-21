@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\launchers\run_hazard_snapshots_neutral.ps1"
echo Neutral hazard snapshots finished.
endlocal
