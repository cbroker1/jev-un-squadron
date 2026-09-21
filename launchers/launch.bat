@echo off
setlocal
cd /d "%~dp0.."
echo.
echo Use your already-running BizHawk game at the gameplay save state.
echo.
echo RUN CHECKLIST:
echo   1. BizHawk must show the aircraft in active gameplay.
echo   2. Lua Console must show lua\main.lua as active.
echo   3. Keep BizHawk unpaused while the bridge runs.
echo   4. Press Ctrl+C in this bridge window to stop early; controls release safely.
echo   5. The default maximum is 60 calls.
echo.
echo Press D for dry-run, L for live Jev, or Q to quit.
choice /c DLQ /n /m "Start mode: "
if errorlevel 3 goto :quit
if errorlevel 2 goto :live_selected
goto :dry_selected
:live_selected
set "MODE=L"
goto :countdown
:dry_selected
set "MODE=D"
:countdown
echo.
echo Click BizHawk Play/Run now. The bridge starts after this countdown:
for /l %%N in (5,-1,1) do (
  echo %%N...
  timeout /t 1 /nobreak >nul
)
echo GO - bridge is starting.
if "%MODE%"=="L" powershell -ExecutionPolicy Bypass -File "%CD%\launchers\launch_live.ps1"
if "%MODE%"=="D" start "Jev bridge" /wait python src\bridge.py --dry-run
echo Bridge stopped; controls were released.
:quit
