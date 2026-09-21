@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\launchers\run_hazard_observe.ps1"
echo Hazard observation finished.
endlocal
