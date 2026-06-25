#!/usr/bin/env bash
set -euo pipefail

# One-command local dev: API + ingest worker + ingest watcher + frontend.
#
# Usage:
#   ./dev.sh
#
# Press Ctrl+C once to stop everything.
# Worker and ingest client auto-restart if they crash.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_VENV="$ROOT_DIR/backend/.venv"
BACKEND_REQ="$ROOT_DIR/backend/requirements.txt"
INGEST_CLIENT_REQ="$ROOT_DIR/ingest-client/requirements.txt"

SHUTTING_DOWN=0
SERVICE_PIDS=()

python_cmd() {
  if command -v python3.12 &>/dev/null; then
    python3.12 "$@"
  else
    python3 "$@"
  fi
}

info()  { echo "[dev] $*"; }
warn()  { echo "[dev] WARNING: $*" >&2; }

kill_tree() {
  local pid="$1"
  [[ -z "${pid:-}" ]] && return 0
  kill -0 "$pid" 2>/dev/null || return 0

  if command -v pgrep &>/dev/null; then
    local children
    children=$(pgrep -P "$pid" 2>/dev/null || true)
    if [[ -n "${children:-}" ]]; then
      local child
      for child in $children; do
        kill_tree "$child"
      done
    fi
  fi

  kill -TERM "$pid" 2>/dev/null || true
}

stop_all() {
  [[ "$SHUTTING_DOWN" == "1" ]] && return 0
  SHUTTING_DOWN=1
  info "Stopping..."
  trap - INT TERM EXIT

  for pid in "${SERVICE_PIDS[@]:-}"; do
    kill_tree "$pid"
  done

  sleep 1
  for pid in "${SERVICE_PIDS[@]:-}"; do
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
  done
}

ensure_python_venv() {
  if [[ ! -d "$PYTHON_VENV" ]]; then
    info "Creating Python venv at backend/.venv ($(python_cmd -c 'import sys; print(sys.version.split()[0])'))..."
    python_cmd -m venv "$PYTHON_VENV"
  fi
  "$PYTHON_VENV/bin/pip" install -q -r "$BACKEND_REQ" -r "$INGEST_CLIENT_REQ"
}

# Kill leftover processes from a previous dev.sh that was not stopped cleanly.
cleanup_stale_processes() {
  if ! command -v pkill &>/dev/null; then
    return 0
  fi
  local py="${PYTHON_VENV}/bin/python"
  pkill -f "${py} -m app.worker" 2>/dev/null || true
  pkill -f "${py} -m ingest_client.watcher" 2>/dev/null || true
  pkill -f "${py} -m uvicorn app.main:app" 2>/dev/null || true
}

free_port() {
  local port="$1"
  if ! command -v lsof &>/dev/null; then
    return 0
  fi
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null) || true
  if [[ -n "${pids:-}" ]]; then
    info "Freeing port $port (PID(s): $pids)"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
}

wait_for_api() {
  local url="http://127.0.0.1:8000/health"
  info "Waiting for API at $url ..."
  for _ in $(seq 1 30); do
    if curl -sf --connect-timeout 2 "$url" >/dev/null 2>&1; then
      info "API is up."
      return 0
    fi
    sleep 1
  done
  warn "API did not respond in 30s; frontend may show errors until it is ready."
}

# Run a command in a restart loop until SHUTTING_DOWN=1.
supervise() {
  local name="$1"
  shift
  while [[ "$SHUTTING_DOWN" != "1" ]]; do
    info "[$name] starting"
    "$@" || true
    [[ "$SHUTTING_DOWN" == "1" ]] && break
    warn "[$name] exited unexpectedly — restarting in 2s"
    sleep 2
  done
}

start_backend() {
  supervise api bash -c "
    cd '$ROOT_DIR/backend' &&
    export GMAIL_SYNC_PYTHON='$PYTHON_VENV/bin/python' &&
    exec '$PYTHON_VENV/bin/python' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
  "
}

start_worker() {
  supervise worker bash -c "
    cd '$ROOT_DIR/backend' &&
    exec '$PYTHON_VENV/bin/python' -m app.worker
  "
}

start_ingest_client() {
  supervise ingest bash -c "
    cd '$ROOT_DIR/ingest-client' &&
    exec '$PYTHON_VENV/bin/python' -m ingest_client.watcher
  "
}

start_frontend() {
  supervise frontend bash -c "
    cd '$ROOT_DIR/frontend' &&
    [[ -d node_modules ]] || npm install &&
    exec npm run dev
  "
}

launch() {
  local name="$1"
  local pid
  shift
  "$@" &
  pid=$!
  SERVICE_PIDS+=("$pid")
  info "[$name] supervisor PID $pid"
}

main() {
  info "Investing Agent — starting all services"
  info "Root: $ROOT_DIR"
  trap 'stop_all; exit 0' INT TERM EXIT

  cleanup_stale_processes
  free_port 8000
  free_port 3000
  ensure_python_venv

  launch api start_backend
  wait_for_api

  launch worker start_worker
  launch ingest start_ingest_client
  launch frontend start_frontend

  info ""
  info "Ready:"
  info "  Dashboard   http://localhost:3000"
  info "  API         http://127.0.0.1:8000"
  info "  Drop PDFs   watch_pdfs/  (or your WATCH_DIR)"
  info ""
  info "Worker + ingest client auto-restart on crash. Press Ctrl+C to stop all."

  wait
}

main "$@"
