@echo off
setlocal
cd /d "%~dp0"
echo Passive brain preview: 50%% speed, 900 game frames, ZERO Jev calls.
echo No movement or firing will be injected. Ctrl+C stops the runner.
echo This opens and closes its own emulator; an existing emulator is preserved.
python check_bridge.py --mode brain-preview
exit /b %errorlevel%
