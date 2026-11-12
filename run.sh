#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
PID_FILE="$PROJECT_ROOT/.running_pids"
LOG_DIR="$PROJECT_ROOT/logs"
BACKEND_PORT="${BACKEND_PORT:-8001}"

# ── Colors ──────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Cleanup old PIDs ────────────────────────────────────────────────────
> "$PID_FILE"
mkdir -p "$LOG_DIR"

# ── 0. Local environment file ───────────────────────────────────────────
if [ ! -f "$BACKEND_DIR/.env" ]; then
  if [ -f "$BACKEND_DIR/.env.example" ]; then
    warn "backend/.env is missing; creating it from .env.example"
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  else
    error "backend/.env is missing. Create it with DATABASE_URL and REDIS_URL set."
  fi
fi

# ── 1. Docker: Postgres & Redis ────────────────────────────────────────
info "Starting PostgreSQL and Redis via Docker Compose..."
docker compose up -d postgres redis

info "Waiting for services to be healthy..."
for container in job_automation_postgres job_automation_redis; do
  for i in $(seq 1 30); do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "missing")
    if [ "$status" = "healthy" ]; then
      info "$container is healthy"
      break
    fi
    if [ "$i" -eq 30 ]; then
      error "$container did not become healthy in time. Check 'docker compose logs $container'."
    fi
    sleep 2
  done
done

# ── 2. Backend: venv + pip install ─────────────────────────────────────
info "Setting up backend virtual environment..."
cd "$BACKEND_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  info "Created .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

info "Installing Python dependencies..."
pip install -r requirements.txt -q

info "Installing Playwright browsers..."
if [[ "$(uname -s)" == "Darwin" ]]; then
  # --with-deps is Linux-only; on macOS Playwright fetches the browser alone.
  playwright install chromium
else
  playwright install chromium --with-deps
fi

# ── 3. Backend: Start uvicorn ──────────────────────────────────────────
info "Starting backend on http://127.0.0.1:$BACKEND_PORT (log: $LOG_DIR/backend.log) ..."
(
  cd "$BACKEND_DIR"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  # Single worker for local dev: avoids duplicated startup/schema init.
  exec uvicorn app:app --host 0.0.0.0 --port "$BACKEND_PORT" --workers 1
) > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" >> "$PID_FILE"

info "Waiting for backend health check..."
backend_ready=false
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
    backend_ready=true
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    error "Backend exited during startup. Last log lines:\n$(tail -n 30 "$LOG_DIR/backend.log" 2>/dev/null || true)"
  fi
  sleep 1
done

if [ "$backend_ready" != "true" ]; then
  error "Backend did not become healthy at http://127.0.0.1:$BACKEND_PORT. Last log lines:\n$(tail -n 30 "$LOG_DIR/backend.log" 2>/dev/null || true)"
fi
info "Backend is healthy (PID $BACKEND_PID)"

# ── 4. Frontend: npm install + dev ─────────────────────────────────────
info "Installing frontend dependencies..."
cd "$FRONTEND_DIR"
npm install --silent

info "Starting frontend dev server (log: $LOG_DIR/frontend.log) ..."
VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:$BACKEND_PORT}" \
  npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" >> "$PID_FILE"

info "Waiting for frontend dev server..."
FRONTEND_URL=""
for _ in $(seq 1 60); do
  FRONTEND_URL="$(grep -Eo 'http://localhost:[0-9]+' "$LOG_DIR/frontend.log" | head -n 1 || true)"
  if [ -n "$FRONTEND_URL" ]; then
    break
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    error "Frontend exited during startup. Last log lines:\n$(tail -n 30 "$LOG_DIR/frontend.log" 2>/dev/null || true)"
  fi
  sleep 1
done

if [ -z "$FRONTEND_URL" ]; then
  warn "Could not detect the frontend URL; check $LOG_DIR/frontend.log"
  FRONTEND_URL="http://localhost:5173"
fi

# ── Done ────────────────────────────────────────────────────────────────
echo ""
info "All services are running!"
echo -e "  Backend  : http://127.0.0.1:$BACKEND_PORT"
echo -e "  Frontend : $FRONTEND_URL"
echo -e "  Logs     : $LOG_DIR/backend.log, $LOG_DIR/frontend.log"
echo ""
info "PIDs saved to $PID_FILE — use ./stop.sh to shut everything down."
