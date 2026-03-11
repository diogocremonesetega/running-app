# 🏃 Advanced Running Route Generator

An elevation-aware running route generator for the Berkeley area, featuring real-time 3D terrain routing, interactive map visualization, and customizable elevation profiles.

![Elevation Visualizer](https://img.shields.io/badge/Status-Phase_4_Complete-brightgreen) ![GraphHopper](https://img.shields.io/badge/Routing-GraphHopper%2010.0-blue) ![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)

## ✨ Features

- **Address Search** — Type any street name, park, or landmark to set your start/end location (powered by OpenStreetMap Nominatim geocoding)
- **Loop & Point-to-Point Modes** — Toggle between circular loop routes and A-to-B point-to-point routes
- **Elevation-Aware Routing** — 4 custom profiles that actively adjust routes based on terrain:
  - ⛰️ **Balanced** — Moderate hills for everyday runs
  - 🌊 **Flat Recovery** — Avoids hills for easy recovery days
  - 🔺 **Hill Training** — Seeks steep climbs for workouts
  - 🚦 **No Signals** — Prioritizes footways/paths over main roads
- **Interactive Map** — Leaflet.js with dark CartoDB tiles, route colored by elevation
- **Elevation Profile Chart** — Interactive chart with hover-to-map sync
- **Circle-Based Loop Routing** — Generates natural loop routes using waypoint circles
- **Compass Direction Selector** — Choose which direction your route heads (N/NE/E/SE/S/SW/W/NW)
- **km/miles Toggle** — Switch between metric and imperial units (distance + elevation)
- **SRTM 3D Elevation Data** — Real terrain data for accurate elevation profiles
- **Spatial Intelligence (Phase 2 & 3)** — PostGIS-backed storage for safety zones, construction zones, and route history
- **Dynamic Overlays** — Avoid unlit streets, crime zones, and construction in real-time. Visualize traffic signals and crime heatmaps.
- **Scenic Routing & Weather (Phase 4)** — Prefers parks and trails. Integrates real-time weather, AQI, wind, and comfort scores. Suggests optimal wind-based start bearing. Calculates Safety and Scenic route scores.

## 🏗️ Architecture

```text
                        ┌────────────────────────┐
                        │ Live External APIs     │
                        │ - Open-Meteo (Weather) │
                        │ - Nominatim (Geocoding)│
                        └──────────┬─────────────┘
                                   │
┌─────────────┐         ┌──────────▼─────────────┐       ┌──────────────────┐
│  Browser UI  │───────▶│  FastAPI Backend       │──────▶│  GraphHopper     │
│  (Leaflet)   │◀───────│  (Route Gen & APIs)    │◀──────│  Routing Engine  │
│  :8000       │        └──────────┬─────────────┘       │  :8989           │
└──────┬───────┘                   │                     └────────┬─────────┘
       │                           ▼                              ▼
       │                ┌────────────────────────┐       ┌──────────────────┐
       │                │    PostGIS Database    │       │   NorCal OSM     │
       │                │  (Spatial Intelligence)│       │   + SRTM DEM     │
       │                └──────────▲─────────────┘       └──────────────────┘
       │                           │
       │                ┌──────────┴─────────────┐
       │                │   Background Workers   │
       │                │    (Data Ingestors)    │
       │                └──────────┬─────────────┘
       │                           │
       ▼                           ▼
┌──────────────┐        ┌────────────────────────┐
│ Overpass API │        │ External Data Sources  │
│(Signals/POIs)│        │ - Socrata (Crime)      │
└──────────────┘        │ - SF Bay 511 (Const.)  │
                        │ - OSM/Overpass (Scenic)│
                        └────────────────────────┘
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

We use unified scripts to manage PostGIS (via Docker), GraphHopper (natively via Java), and the FastAPI backend.

```bash
# from the repository root
./start.sh    # Launch everything
./stop.sh     # Shut everything down
```

Wait until you see `[OK] All services running!` on start.

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
| GET    | `/api/v1/weather-advisory`| Get comfort score, wind, & AQI     |
| GET    | `/api/v1/safety-overlay`  | Get GeoJSON crime/safety zones     |
| GET    | `/api/v1/geocode?q=...`   | Address search (Nominatim)         |
| GET    | `/api/v1/reverse-geocode` | Coordinates → address              |
| GET    | `/api/v1/profiles`        | List available routing profiles    |
| GET    | `/api/v1/health`          | Health check + GH status           |

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

## 🛡️ Resilience & Background Workers

The application features self-healing background workers that:
- Refresh crime and construction data every 30 minutes.
- Refresh scenic/nature segments every 6 hours.
- **Fail-fast & Retry**: If the public Overpass API times out (504), workers will retry every 60 seconds until data is successfully synchronized.

## 🛠️ Tech Stack

- **Routing**: [GraphHopper 10.0](https://www.graphhopper.com/) with custom foot profiles
- **Elevation**: SRTM DEM 3-arc-second data
- **Geocoding**: [Nominatim](https://nominatim.openstreetmap.org/) (OpenStreetMap)
- **Backend**: Python FastAPI + httpx
- **Frontend**: Vanilla HTML/CSS/JS + Leaflet.js + CartoDB Dark Matter tiles
- **Map Data**: OpenStreetMap (NorCal region)

## 📝 License

MIT
