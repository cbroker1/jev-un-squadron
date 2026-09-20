@echo off
setlocal
cd /d "%~dp0"
echo Close any existing BizHawk window first.
echo Starting BizHawk with ROM, quicksave slot 1, and API calibration...
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_calibration.ps1"
echo BizHawk calibration finished and closed.
endlocal
