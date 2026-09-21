@echo off
setlocal
cd /d "%~dp0.."
echo Close any existing BizHawk window first.
echo Starting passive continuous marker check from quicksave slot 1...
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\launchers\run_marker_check.ps1"
echo Marker check finished and BizHawk closed.
endlocal
