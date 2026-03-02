# 🏃 Advanced Running Route Generator

An elevation-aware running route generator for the Berkeley area, featuring real-time 3D terrain routing, interactive map visualization, and customizable elevation profiles.

![Elevation Visualizer](https://img.shields.io/badge/Status-MVP-brightgreen) ![GraphHopper](https://img.shields.io/badge/Routing-GraphHopper%2010.0-blue) ![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)

## ✨ Features

- **Elevation-Aware Routing** — 4 custom profiles that actively adjust routes based on terrain:
  - ⛰️ **Balanced** — Moderate hills for everyday runs
  - 🌊 **Flat Recovery** — Avoids hills for easy recovery days
  - 🔺 **Hill Training** — Seeks steep climbs for workouts
  - 🚦 **No Signals** — Prioritizes footways/paths over main roads
- **Interactive Map** — Leaflet.js with dark CartoDB tiles, route colored by elevation
- **Elevation Profile Chart** — Interactive chart with hover-to-map sync
- **Circle-Based Loop Routing** — Generates natural loop routes using waypoint circles
- **Compass Direction Selector** — Choose which direction your route heads (N/NE/E/SE/S/SW/W/NW)
- **km/miles Toggle** — Switch between metric and imperial units
- **SRTM 3D Elevation Data** — Real terrain data for accurate elevation profiles

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Browser UI  │────▶│  FastAPI      │────▶│  GraphHopper     │
│  (Leaflet)   │◀────│  Backend      │◀────│  Routing Engine  │
│  :8000       │     │  :8000        │     │  :8080           │
└─────────────┘     └──────────────┘     └──────────────────┘
                                               │
                                          ┌────┴─────┐
                                          │ NorCal   │
                                          │ OSM Data │
                                          │ + SRTM   │
                                          └──────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Java 11+** (for GraphHopper)
- **Python 3.10+** (for FastAPI backend)

### 1. Download Data & GraphHopper

```bash
cd graphhopper
bash setup_graphhopper.sh
```

This downloads:
- GraphHopper 10.0 JAR (~50 MB)
- NorCal OSM data (~600 MB)

### 2. Start GraphHopper

```bash
cd graphhopper
bash start_graphhopper.sh
```

First run builds the routing graph (~3 min). Subsequent starts use the cache (~30 sec).

### 3. Start the Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env
echo "GRAPHHOPPER_URL=http://localhost:8080" > .env

# Start server
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

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

| Method | Endpoint                  | Description                    |
|--------|---------------------------|--------------------------------|
| POST   | `/api/v1/generate-route`  | Generate a loop route          |
| POST   | `/api/v1/point-to-point`  | Route between two points       |
| GET    | `/api/v1/profiles`        | List available routing profiles|
| GET    | `/api/v1/health`          | Health check + GH status       |

### Generate Route Example

```bash
curl -X POST http://localhost:8000/api/v1/generate-route \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"lat": 37.8719, "lng": -122.2585},
    "distance_km": 5.0,
    "elevation_preference": "moderate",
    "avoid_traffic_signals": false,
    "num_waypoints": 5,
    "start_bearing": 0
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
- **Backend**: Python FastAPI + httpx
- **Frontend**: Vanilla HTML/CSS/JS + Leaflet.js + CartoDB Dark Matter tiles
- **Map Data**: OpenStreetMap (NorCal region)

## 📝 License

MIT
