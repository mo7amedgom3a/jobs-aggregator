#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_ROOT/.running_pids"
BACKEND_PORT="${BACKEND_PORT:-8001}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# Stop a process and its children, escalating to SIGKILL if needed.
terminate() {
  local pid="$1"
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  pkill -TERM -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  pkill -KILL -P "$pid" 2>/dev/null || true
  kill -9 "$pid" 2>/dev/null || true
  return 0
}

# ── 1. Stop backend & frontend processes ───────────────────────────────
if [ -f "$PID_FILE" ]; then
  info "Stopping backend/frontend processes..."
  while IFS= read -r pid; do
    if [ -n "$pid" ]; then
      if kill -0 "$pid" 2>/dev/null; then
        terminate "$pid"
        info "Stopped PID $pid"
      fi
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
else
  warn "No PID file found; skipping process cleanup."
fi

# Fallback: kill any lingering uvicorn / vite dev processes for this repo
pkill -f "uvicorn app:app .*--port ${BACKEND_PORT}" 2>/dev/null && \
  info "Stopped lingering uvicorn process" || true
pkill -f "vite dev" 2>/dev/null && \
  info "Stopped lingering vite process" || true

# ── 2. Stop Docker containers ──────────────────────────────────────────
info "Stopping Docker containers..."
docker compose down

info "Cleanup complete. All services stopped."
