@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_health_perturb_down.ps1"
echo Down perturbation finished.
endlocal
