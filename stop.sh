#!/bin/bash
# stop.sh — Stop all Running Route Generator services (Backend, GraphHopper, Docker PostGIS)

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[stop.sh]${NC} $1"; }
warn()  { echo -e "${YELLOW}[stop.sh]${NC} $1"; }

# 1. Stop FastAPI backend
if pgrep -f "uvicorn app.main" > /dev/null; then
  info "Stopping FastAPI backend..."
  pkill -f "uvicorn app.main"
fi

# 2. Stop GraphHopper
if pgrep -f "graphhopper-web" > /dev/null; then
  info "Stopping GraphHopper..."
  pkill -f "graphhopper-web"
  # Optional: rm "$REPO_ROOT/graphhopper/graphhopper.pid" 2>/dev/null
fi

# 3. Stop PostGIS (Docker)
info "Stopping PostGIS (Docker Compose)..."
cd "$BACKEND_DIR" && docker compose down > /dev/null 2>&1 || warn "Docker components already stopped or not found."

info "All services stopped successfully! ✅"
