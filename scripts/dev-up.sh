#!/usr/bin/env bash
# Local dev orchestration: brings up Postgres+pgvector via Docker, then runs
# the FastAPI backend and Vite frontend dev servers in the foreground.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found -- copying from .env.example. Fill in QWEN_API_KEY before continuing." >&2
  cp .env.example .env
  exit 1
fi

echo "==> Starting Postgres+pgvector..."
docker compose up -d postgres

echo "==> Installing backend deps (if needed)..."
cd backend
if [ ! -d .venv ]; then
  python -m venv .venv
fi
./.venv/Scripts/python.exe -m pip install --disable-pip-version-check -q -r requirements.txt 2>/dev/null \
  || .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

echo "==> Installing frontend deps (if needed)..."
cd ../frontend
if [ ! -d node_modules ]; then
  npm install
fi
cd ..

echo "==> Starting backend (http://localhost:8000) and frontend (http://localhost:5173)..."
( cd backend && ( .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000 \
    || .venv/bin/python -m uvicorn app.main:app --reload --port 8000 ) ) &
BACKEND_PID=$!
( cd frontend && npm run dev ) &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
