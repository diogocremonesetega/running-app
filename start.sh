#!/bin/bash
# start.sh — Start all Running Route Generator services
# Usage: ./start.sh [--no-backend]
#
# Services:
#   1. PostGIS (Docker)      — port 5432
#   2. GraphHopper (native)  — port 8989 (first run ~5-10 min to index NorCal OSM)
#   3. FastAPI backend        — port 8000

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
GH_DIR="$REPO_ROOT/graphhopper"

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[start.sh]${NC} $1"; }
warn()  { echo -e "${YELLOW}[start.sh]${NC} $1"; }
error() { echo -e "${RED}[start.sh]${NC} $1"; }

# ── 1. PostGIS ────────────────────────────────────────────────────────────────
info "Starting PostGIS (Docker)..."
docker compose -f "$BACKEND_DIR/docker-compose.yml" up -d db
info "Waiting for PostGIS to be ready..."
until docker exec routegen-db pg_isready -U routegen -d routegen_db -q 2>/dev/null; do
  sleep 1
done
info "PostGIS is ready ✅"

# ── 2. GraphHopper (native Java) ──────────────────────────────────────────────
if ! pgrep -f "graphhopper-web" > /dev/null 2>&1; then
  info "Starting GraphHopper on port 8989..."
  if [ ! -d "$GH_DIR/data/graph-cache" ]; then
    warn "First launch — building OSM graph with elevation. This takes ~5-10 minutes..."
  fi
  nohup bash "$GH_DIR/start_graphhopper.sh" > "$GH_DIR/graphhopper.log" 2>&1 &
  echo "$!" > "$GH_DIR/graphhopper.pid"
  info "GraphHopper starting (PID $!). Logs: graphhopper/graphhopper.log"
  info "Waiting for GraphHopper to become healthy (may take a few minutes)..."
  for i in {1..60}; do
    if curl -sf http://localhost:8989/health > /dev/null 2>&1; then
      info "GraphHopper is ready ✅"
      break
    fi
    if [ "$i" -eq 60 ]; then
      warn "GraphHopper not yet ready after 5 min — still indexing OSM. Backend will start regardless."
    fi
    sleep 5
  done
else
  info "GraphHopper already running ✅"
fi

# ── 3. FastAPI backend ────────────────────────────────────────────────────────
if [[ "$1" != "--no-backend" ]]; then
  info "Running Alembic migrations..."
  cd "$BACKEND_DIR"
  export PYTHONPATH=.
  # Ensure the virtual environment is used if it exists
  if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
  fi
  python3 -m alembic upgrade head

  info "Starting FastAPI backend on http://localhost:8000"
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
