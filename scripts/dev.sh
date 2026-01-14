#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT_DIR/backend/.venv/bin/uvicorn" ]; then
  echo "backend/.venv is missing. Run the backend setup first."
  exit 1
fi

if ! command -v bun >/dev/null 2>&1; then
  echo "bun is not installed. Install bun before running dev."
  exit 1
fi

if [ ! -f "$ROOT_DIR/backend/.env" ]; then
  echo "backend/.env not found. Copy backend/.env.example and set OPENAI_API_KEY."
fi

cleanup() {
  local pids
  pids=$(jobs -p) || true
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/backend"
  source .venv/bin/activate
  uvicorn app.main:app --reload --port 8000
) &

(
  cd "$ROOT_DIR/frontend"
  bun run dev
) &

wait
