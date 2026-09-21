@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\launchers\run_first_damage.ps1"
echo First-damage observation finished.
endlocal
