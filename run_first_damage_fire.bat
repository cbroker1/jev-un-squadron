@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_first_damage_fire.ps1"
echo First-damage firing observation finished.
endlocal
