#!/usr/bin/env bash
# Mini Coding Agent launcher (Linux / macOS)
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 not found. Install Python 3.10+ first."
  exit 1
fi

echo "[1/2] Installing dependencies ..."
python3 -m pip install -r requirements.txt --quiet

echo "[2/2] Starting Mini Coding Agent at http://127.0.0.1:8000"
echo "Press Ctrl+C to stop."
exec python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
