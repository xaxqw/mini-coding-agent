@echo off
REM ============================================
REM  Mini Coding Agent launcher (Windows)
REM ============================================
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH. Install Python 3.10+ first.
  pause
  exit /b 1
)

echo [1/2] Installing dependencies ...
python -m pip install -r requirements.txt --quiet

echo [2/2] Starting Mini Coding Agent at http://127.0.0.1:8000
echo Press Ctrl+C to stop.
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

pause
