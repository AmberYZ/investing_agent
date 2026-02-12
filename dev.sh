#!/usr/bin/env bash
set -euo pipefail

# Simple "all-in-one" local dev runner for:
# - Postgres (optional, via Docker Compose)
# - Backend API (FastAPI)
# - Ingest worker
# - Ingest client (watcher)
# - Frontend (Next.js)
#
# Usage:
#   chmod +x dev.sh
#   ./dev.sh          # runs everything with defaults from .env
#
# Notes:
# - Requires: python3, node/npm, (optionally) docker + docker compose
# - By default this leaves Postgres to sqlite. To use Postgres, start it first:
#       docker compose up -d db
#   and set DATABASE_URL in .env accordingly, then run this script.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer Python 3.12+ (3.9 is EOL; google-auth and others recommend upgrading)
python_cmd() {
  if command -v python3.12 &>/dev/null; then
    python3.12 "$@"
  else
    python3 "$@"
  fi
}

info() {
  echo "[dev] $*"
}

run_backend() {
  info "Starting backend API..."
  cd "$ROOT_DIR/backend"

  if [[ ! -d .venv ]]; then
    info "Creating backend virtualenv (using $(python_cmd -c 'import sys; print(sys.version.split()[0])'))..."
    python_cmd -m venv .venv
  fi

  .venv/bin/pip install -r requirements.txt >/dev/null
  .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
}

run_worker() {
  info "Starting ingest worker..."
  cd "$ROOT_DIR/backend"

  if [[ ! -d .venv ]]; then
    python_cmd -m venv .venv
  fi

  .venv/bin/pip install -r requirements.txt >/dev/null
  .venv/bin/python -m app.worker
}

run_ingest_client() {
  info "Starting ingest client watcher..."
  cd "$ROOT_DIR/ingest-client"

  if [[ ! -d .venv ]]; then
    python_cmd -m venv .venv
  fi

  .venv/bin/pip install -r requirements.txt >/dev/null
  .venv/bin/python -m ingest_client.watcher
}

run_frontend() {
  info "Starting frontend (Next.js)..."
  cd "$ROOT_DIR/frontend"

  if [[ ! -d node_modules ]]; then
    npm install
  fi

  npm run dev
}

wait_for_api() {
  local url="http://127.0.0.1:8000/health"
  info "Waiting for backend at $url ..."
  for i in $(seq 1 30); do
    if curl -sf --connect-timeout 2 "$url" >/dev/null 2>&1; then
      info "Backend is up."
      return 0
    fi
    sleep 1
  done
  info "Warning: backend did not respond in 30s; frontend may show 'Could not reach backend' until it is ready."
  return 0
}

# Free port 8000 so the new backend can bind (avoids 'old code' 404s when a previous run is still on 8000)
free_port_8000() {
  if command -v lsof &>/dev/null; then
    local pids
    pids=$(lsof -ti:8000 2>/dev/null) || true
    if [[ -n "${pids:-}" ]]; then
      info "Freeing port 8000 (was in use by PID(s): $pids)"
      echo "$pids" | xargs kill -9 2>/dev/null || true
      sleep 1
    fi
  fi
}

main() {
  info "Root directory: $ROOT_DIR"
  info "Make sure .env is configured (see .env.example)."

  free_port_8000
  info "Launching services (API, worker, ingest client, frontend)..."

  # Start backend first, then wait for it so the frontend's first SSR request can reach it
  (run_backend) &
  API_PID=$!
  wait_for_api

  (run_worker) &
  WORKER_PID=$!

  (run_ingest_client) &
  INGEST_PID=$!

  (run_frontend) &
  FRONTEND_PID=$!

  info "PIDs: api=$API_PID worker=$WORKER_PID ingest=$INGEST_PID frontend=$FRONTEND_PID"
  info "Press Ctrl+C to stop everything."

  trap 'info "Stopping..."; kill $API_PID $WORKER_PID $INGEST_PID $FRONTEND_PID 2>/dev/null || true; exit 0' INT TERM

  # Wait on any process to exit; Ctrl+C also handled by trap.
  wait
}

main "$@"

