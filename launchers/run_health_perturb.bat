@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\launchers\run_health_perturb.ps1"
echo Perturbed health observation finished.
endlocal
