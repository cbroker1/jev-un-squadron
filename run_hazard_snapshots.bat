@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_hazard_snapshots.ps1"
echo Hazard snapshots finished.
endlocal
