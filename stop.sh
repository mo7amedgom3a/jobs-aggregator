#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_ROOT/.running_pids"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# ── 1. Stop backend & frontend processes ───────────────────────────────
if [ -f "$PID_FILE" ]; then
  info "Stopping backend/frontend processes..."
  while IFS= read -r pid; do
    # shellcheck disable=SC2086
    if [ -n "$pid" ] && kill $pid 2>/dev/null; then
      info "Stopped PID $pid"
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
else
  warn "No PID file found; skipping process cleanup."
fi

# Fallback: kill any lingering uvicorn / vite dev processes for this repo
pkill -f "uvicorn app:app --host 0.0.0.0 --port 8000" 2>/dev/null && \
  info "Stopped lingering uvicorn process" || true
pkill -f "vite dev" 2>/dev/null && \
  info "Stopped lingering vite process" || true

# ── 2. Stop Docker containers ──────────────────────────────────────────
info "Stopping Docker containers..."
docker compose down

info "Cleanup complete. All services stopped."