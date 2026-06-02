# 🏃 Advanced Running Route Generator

An elevation-aware running route generator for the Berkeley area, featuring real-time 3D terrain routing, interactive map visualization, and customizable elevation profiles.

![Elevation Visualizer](https://img.shields.io/badge/Status-v2-brightgreen) ![GraphHopper](https://img.shields.io/badge/Routing-GraphHopper%2010.0-blue) ![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)

## ✨ Features

- **Address Search** — Type any street name, park, or landmark to set your start/end location (powered by OpenStreetMap Nominatim geocoding)
- **Loop & Point-to-Point Modes** — Toggle between circular loop routes and A-to-B point-to-point routes
- **Elevation-Aware Routing** — Three profiles that adjust routes based on terrain:
  - ⛰️ **Balanced** — Moderate hills for everyday runs
  - 🌊 **Flat Recovery** — Avoids hills for easy recovery days
  - 🔺 **Hill Training** — Seeks steep climbs for workouts
- **Infrastructure Toggles** — Optional routing preferences per request:
  - Avoid traffic signals
  - Prioritize well-lit streets (night runs)
  - Prioritize soft surfaces (track/trail)
  - Include water (hydration) and restrooms (separate toggles)
- **Interactive Map** — Leaflet.js with dark CartoDB tiles, route colored by elevation
- **Elevation Profile Chart** — Interactive chart with hover-to-map sync
- **GraphHopper round_trip** — Organic loop routes from a single start point
- **km/miles Toggle** — Switch between metric and imperial units (distance + elevation)
- **SRTM 3D Elevation Data** — Real terrain data for accurate elevation profiles
- **Live Run Tracking** — GPS breadcrumb recording with optional save to PostGIS `route_history`

## 🏗️ Architecture

```text
┌─────────────┐     ┌────────────────────┐     ┌──────────────────┐
│  Browser UI │────▶│  FastAPI Backend   │────▶│  GraphHopper     │
│  (Leaflet)  │◀────│  Route generation  │◀────│  :8989 + OSM    │
└──────┬──────┘     └─────────┬──────────┘     └──────────────────┘
       │                      │
       │                      ▼
       │            ┌────────────────────┐
       ▼            │ PostGIS (optional) │
┌──────────────┐    │ route_history      │
│ Overpass API │    └────────────────────┘
│ Nominatim    │
└──────────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Java 11+** (for GraphHopper native execution)
- **Python 3.10+** (for FastAPI backend)
- **Docker** (for PostGIS database)

### 1. Download Data & GraphHopper

```bash
cd graphhopper
bash setup_graphhopper.sh
cd ..
```

This downloads:
- GraphHopper 10.0 JAR (~50 MB)
- NorCal OSM data (~600 MB)

### 2. Setup Python Environment

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

### 3. Start & Stop (Unified Scripts)

**Windows (PowerShell):**

```powershell
# Full stack: PostGIS + GraphHopper + FastAPI (keep the terminal open)
.\start.ps1

# UI/API only — fastest fix if http://localhost:8000 refuses connection
.\start-backend.ps1

# Stop Docker, GraphHopper, and anything on port 8000
.\stop.ps1
```

**Linux/macOS:**

```bash
./start.sh
./stop.sh
```

Wait until you see `Uvicorn running on http://0.0.0.0:8000` (or `[OK] Backend starting` on Windows). **Leave that terminal open** — closing it stops the server and the browser will show `ERR_CONNECTION_REFUSED`.

### 4. Open the Visualizer

Navigate to **http://localhost:8000** in your browser.

## 📁 Project Structure

```
running-route-generator/
├── graphhopper/
│   ├── config.yml                 # GraphHopper v10 configuration
│   ├── setup_graphhopper.sh       # Download JAR + OSM data
│   ├── start_graphhopper.sh       # Launch GraphHopper server
│   └── custom_models/
│       ├── run_balanced.json      # Balanced elevation model
│       ├── run_flat.json          # Flat recovery model
│       ├── run_hilly.json         # Hill training model
│       └── run_no_signals.json    # Traffic signal avoidance
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI application
│   │   ├── config.py              # Settings & env vars
│   │   ├── routers/
│   │   │   └── routes.py          # API endpoints
│   │   └── services/
│   │       ├── graphhopper.py     # GraphHopper HTTP client
│   │       └── route_generator.py # Loop route generation logic
│   ├── static/
│   │   └── index.html             # Elevation visualizer UI
│   └── requirements.txt
└── tests/
    └── test_routes.py             # Verification test suite
```

## 🔌 API Endpoints

| Method | Endpoint                  | Description                        |
|--------|---------------------------|------------------------------------|
| POST   | `/api/v1/generate-route`  | Generate a loop route              |
| POST   | `/api/v1/point-to-point`  | Route between two points           |
| POST   | `/api/v1/runs`            | Save completed live run            |
| GET    | `/api/v1/geocode?q=...`   | Address search (Nominatim)         |
| GET    | `/api/v1/reverse-geocode` | Coordinates → address              |
| GET    | `/api/v1/profiles`        | List elevation profiles            |
| GET    | `/api/v1/health`          | Health check + GH status           |
| GET    | `/api/v1/diagnostics`     | GraphHopper + database checks      |

### Generate Route Example

```bash
curl -X POST http://localhost:8000/api/v1/generate-route \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"lat": 37.8719, "lng": -122.2585},
    "distance_km": 5.0,
    "elevation_preference": "moderate",
    "avoid_traffic_signals": false,
    "prioritize_well_lit_streets": false,
    "prioritize_soft_surfaces": false,
    "include_water": false,
    "include_restrooms": false
  }'
```

## 🧪 Running Tests

```bash
python3 tests/test_routes.py
```

Tests verify: GraphHopper connection, 3D elevation data, loop route closure, elevation profile comparison (flat < moderate < hilly), and traffic signal avoidance.

## 📊 Elevation Profile Comparison

| Profile       | Ascent ↑  | Distance |
|---------------|-----------|----------|
| Flat Recovery | 206.5 m   | 7.35 km  |
| Balanced      | 219.5 m   | 7.24 km  |
| Hill Training | 242.0 m   | 7.05 km  |

> The flat profile produces **17% less elevation gain** than the hilly profile for the same loop.

## 🛠️ Tech Stack

- **Routing**: [GraphHopper 10.0](https://www.graphhopper.com/) with custom foot profiles
- **Elevation**: SRTM DEM 3-arc-second data
- **Geocoding**: [Nominatim](https://nominatim.openstreetmap.org/) (OpenStreetMap)
- **Backend**: Python FastAPI + httpx
- **Frontend**: Vanilla HTML/CSS/JS + Leaflet.js + CartoDB Dark Matter tiles
- **Map Data**: OpenStreetMap (NorCal region)

## 📝 License

MIT
