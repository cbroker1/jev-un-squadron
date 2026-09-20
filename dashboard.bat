@echo off
REM Jev Squadron dashboard: leave it open, it follows runs by itself.
start "" http://127.0.0.1:8770/
python "%~dp0dashboard.py" --port 8770
