#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
PID_FILE="$PROJECT_ROOT/.running_pids"

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

# ── 1. Docker: Postgres & Redis ────────────────────────────────────────
info "Starting PostgreSQL and Redis via Docker Compose..."
docker compose up -d

info "Waiting for services to be healthy..."
sleep 3

for container in job_automation_postgres job_automation_redis; do
  for i in $(seq 1 30); do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "missing")
    if [ "$status" = "healthy" ]; then
      info "$container is healthy"
      break
    fi
    if [ "$i" -eq 30 ]; then
      error "$container did not become healthy in time"
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
playwright install chromium --with-deps 2>/dev/null || playwright install chromium

# ── 3. Backend: Start uvicorn ──────────────────────────────────────────
info "Starting backend on http://0.0.0.0:8000 ..."
source .venv/bin/activate && uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2 &
echo $! >> "$PID_FILE"

# Give uvicorn a moment to start
sleep 2

# ── 4. Frontend: npm install + dev ─────────────────────────────────────
info "Installing frontend dependencies..."
cd "$FRONTEND_DIR"
npm install --silent

info "Starting frontend dev server..."
npm run dev &
echo $! >> "$PID_FILE"

sleep 2

# ── Done ────────────────────────────────────────────────────────────────
echo ""
info "All services are running!"
echo -e "  Backend  : http://localhost:8000"
echo -e "  Frontend : http://localhost:5173"
echo ""
info "PIDs saved to $PID_FILE — use ./stop.sh to shut everything down."
