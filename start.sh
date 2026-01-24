#!/usr/bin/env sh
set -eu

PORT="${WEBSITES_PORT:-${PORT:-8000}}"
export FRONTEND_DIST_DIR="${FRONTEND_DIST_DIR:-/app/frontend_dist}"

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --timeout-keep-alive 75
