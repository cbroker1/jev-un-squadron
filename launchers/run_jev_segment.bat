@echo off
setlocal
cd /d "%~dp0.."
echo Experimental combat, NOT a level-clear agent. Maximum 300 paid Jev requests (a decision every 6 game frames).
echo Pause-and-step: the game pauses while Jev decides. Gun fires from the start.
echo Uses the existing local key. Ctrl+C or stop_segment.bat stops.
python src\run_segment.py --mode live --stepped --prelude-fire --interval 6 --max-calls 300 --frames 1800
exit /b %errorlevel%
