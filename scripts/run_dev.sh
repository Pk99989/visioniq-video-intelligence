#!/usr/bin/env bash
# Local dev (no Docker): backend on :8000, frontend on :3000.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv backend/.venv 2>/dev/null || true
backend/.venv/bin/pip install -q -r backend/requirements.txt
( cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000 ) &
( cd frontend && npm install && npm run dev ) &
wait
