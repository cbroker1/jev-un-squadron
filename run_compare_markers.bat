@echo off
setlocal
cd /d "%~dp0"
echo Close any existing BizHawk window first.
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\run_compare_markers.ps1"
echo Candidate comparison finished.
endlocal
