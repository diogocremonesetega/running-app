# Advanced Automated Running Route Generator — Implementation Guide

> A comprehensive, phased guide for building a production-grade automated running route generator with elevation-aware routing, real-time safety overlays, experiential waypoints, and intelligent audio navigation.

---

## Table of Contents

1. [Service & API Key Registration Checklist](#1-service--api-key-registration-checklist)
2. [Phase 1 — Map Rendering & Elevation-Based Routing (Priority)](#2-phase-1--map-rendering--elevation-based-routing-priority)
3. [Phase 2 — FastAPI Backend & PostGIS Spatial Warehouse](#3-phase-2--fastapi-backend--postgis-spatial-warehouse)
4. [Phase 3 — Dynamic Safety, Construction & Traffic-Signal Avoidance](#4-phase-3--dynamic-safety-construction--traffic-signal-avoidance)
5. [Phase 4 — Experiential Routing, Scenic Beauty & Weather](#5-phase-4--experiential-routing-scenic-beauty--weather)
6. [Phase 5 — Audio Subsystem, Pace Tracking & Wearable Integration](#6-phase-5--audio-subsystem-pace-tracking--wearable-integration)
7. [Phase 6 — Background Geolocation & Battery Optimization](#7-phase-6--background-geolocation--battery-optimization)
8. [Project Directory Structure](#8-project-directory-structure)
9. [Verification & Testing Strategy](#9-verification--testing-strategy)
10. [Open Questions & Design Decisions](#10-open-questions--design-decisions)

---

## 1. Service & API Key Registration Checklist

Before writing any code, register for the following services and store all keys in environment variables (never hard-code).

| Service | Purpose | Free Tier | Registration URL |
|---|---|---|---|
| **Mapbox** | Map tiles (Streets v8), Directions API | 50 000 map loads/mo, 100 000 direction reqs/mo | <https://account.mapbox.com/auth/signup/> |
| **GraphHopper** | Self-hosted routing engine (no key needed for self-hosted) | Unlimited (self-hosted) | <https://github.com/graphhopper/graphhopper> |
| **CrimeOMeter** | Crime data & Safety Quality Index (SQI) | ~1 000 reqs/mo | <https://www.crimeometer.com/crime-data-api> |
| **OpenWeatherMap** | One-Call API for hyper-local weather | 1 000 calls/day | <https://openweathermap.org/api/one-call-3> |
| **Mapillary** | Street-level imagery for Green View Index | Public access | <https://www.mapillary.com/developer> |
| **ParkServe (TPL)** | Park coverage GeoJSON | Public / free | <https://www.tpl.org/parkserve/downloads> |
| **USDA Farmers Market** | National Farmers Market Directory | Free, no key | <https://www.usdalocalfoodportal.com/fe/fdirectory_farmersmarket/> |
| **Waze CIFS** | Construction / closure feed | Partner program | <https://www.waze.com/ccp> |
| **WZDx (DOT)** | Regional work-zone data exchange | Public | <https://www.transportation.gov/av/data/wzdx> |
| **Apple HealthKit** | iOS fitness sync | Native iOS API | Xcode entitlements |
| **Google Fit / Health Connect** | Android fitness sync | Native Android API | Google Cloud Console |

> [!IMPORTANT]
> Store all keys in a single `.env` file at the project root. The backend reads them via `python-dotenv`; the mobile client reads them via `react-native-config`.

---

## 2. Phase 1 — Map Rendering & Elevation-Based Routing (Priority)

This is the **highest-priority phase** and forms the foundational layer on which everything else is built.

### 2.1 React Native Project Initialization

```bash
# Create a new React Native project with the New Architecture enabled
npx -y @react-native-community/cli init RunRouteGen --pm npm
cd RunRouteGen

# Ensure New Architecture is ON (default in RN ≥ 0.76)
# iOS: ios/Podfile should contain  :fabric_enabled => true
# Android: android/gradle.properties should contain  newArchEnabled=true
```

#### Key Dependencies (install early)

```bash
npm install @rnmapbox/maps                # Mapbox SDK wrapper
npm install react-native-config           # .env access
npm install @react-navigation/native @react-navigation/native-stack  # navigation
npm install react-native-permissions      # location perms
npx pod-install                           # iOS pods
```

### 2.2 Mapbox Map Rendering (Streets v8)

#### 2.2.1 Access Token Configuration

| Platform | Location | Action |
|---|---|---|
| JS | `App.tsx` top-level | `Mapbox.setAccessToken(Config.MAPBOX_TOKEN)` |
| iOS | `ios/RunRouteGen/Info.plist` | Add `MBXAccessToken` key |
| Android | `android/app/src/main/res/values/mapbox_access_token.xml` | `<string name="mapbox_access_token">pk.xxx</string>` |
| Android | `android/build.gradle` (allprojects → repositories) | Add Mapbox Maven repo with secret download token |

#### 2.2.2 Basic Map Component

Create `src/components/MapScreen.tsx`:

- Use `<MapView>` with `styleURL={Mapbox.StyleURL.Street}` (this is Streets v8 by default).
- Add `<Camera>` for initial zoom (≈ 14) centered on user location.
- Use `<UserLocation>` component with `visible={true}`.
- **Pedestrian emphasis**: Use Mapbox Studio to create a custom style based on *Mapbox Streets* that:
  - Increases prominence of `highway=footway`, `highway=path`, `highway=pedestrian` layers.
  - Dims or reduces `highway=motorway`, `highway=trunk` layers.
  - Highlights parks and green areas with more saturated fills.

#### 2.2.3 Drawing Route Lines

After receiving a route from GraphHopper, render it on the map:

- Use `<ShapeSource>` with GeoJSON `LineString` geometry from the decoded route.
- Use `<LineLayer>` with styling: a thick semi-transparent line (e.g., `lineWidth: 5`, `lineColor: '#4A90D9'`, `lineOpacity: 0.8`), and optionally apply a glow effect using a wider, more transparent line beneath.
- Show elevation-profile color gradient along the route by splitting the line into elevation buckets and using separate `<LineLayer>` components per bucket (green=flat, yellow=moderate, red=steep).

### 2.3 GraphHopper Self-Hosted Server Setup

GraphHopper is deployed as your own server — you are NOT using GraphHopper's hosted API. This gives you unlimited requests and full Custom Model control.

#### 2.3.1 Prerequisites

- **Java SE 21+** (LTS recommended)
- **≥ 4 GB RAM** allocated to the JVM for metro-area PBFs; ≥ 16 GB for state/country.

#### 2.3.2 Installation Steps

```bash
# 1. Clone GraphHopper
git clone https://github.com/graphhopper/graphhopper.git
cd graphhopper

# 2. Download an OSM PBF for your target region from Geofabrik
#    Example: Northern California
wget https://download.geofabrik.de/north-america/us/california/norcal-latest.osm.pbf \
     -O data/region.osm.pbf

# 3. Build and run (builds the routing graph on first launch)
./graphhopper.sh build
java -Xmx4g -jar web/target/graphhopper-web-*.jar server config/config.yml
```

The server starts at `http://localhost:8989`. The GraphHopper Maps UI is available for manual testing.

#### 2.3.3 `config.yml` — Elevation + Custom Foot Profile

This is the **critical** configuration. Key sections:

```yaml
graphhopper:
  # --- Data source ---
  datareader.file: data/region.osm.pbf
  graph.location: data/graph-cache

  # --- ELEVATION (DEM) ---
  graph.elevation.provider: srtm        # SRTM 90m resolution (free)
  # Alternatives:
  #   cgiar   – CGIAR-CSI SRTM (gap-filled, recommended for production)
  #   multi   – tries SRTM, then CGIAR, then GMTED
  #   hgt     – uses local .hgt files you provide
  graph.elevation.cache_dir: data/elevation-cache
  graph.elevation.dataaccess: MMAP       # memory-mapped for speed

  # --- PROFILES ---
  profiles:
    - name: foot_elevation
      vehicle: foot
      weighting: custom
      custom_model:
        # === Speed adjustments based on slope ===
        speed:
          - if: average_slope > 15
            multiply_by: 0.4            # Steep uphills = very slow
          - if: average_slope > 8
            multiply_by: 0.6            # Moderate uphills
          - if: average_slope > 3
            multiply_by: 0.85           # Mild uphills
          - if: average_slope < -15
            multiply_by: 0.7            # Steep downhills (slower, careful)
          - if: average_slope < -8
            multiply_by: 0.9            # Moderate downhills

        # === Priority adjustments ===
        priority:
          - if: road_class == MOTORWAY
            multiply_by: 0              # Never route on motorways
          - if: road_environment == FERRY
            multiply_by: 0
          - if: road_class == FOOTWAY || road_class == PATH
            multiply_by: 1.5            # Prefer footpaths
          - if: road_class == LIVING_STREET || road_class == RESIDENTIAL
            multiply_by: 1.2            # Prefer quiet streets

        distance_influence: 70           # Higher = prefer shorter overall

    - name: foot_flat_recovery
      vehicle: foot
      weighting: custom
      custom_model:
        speed:
          - if: average_slope > 5
            multiply_by: 0.3            # Heavily penalize any incline
          - if: average_slope < -5
            multiply_by: 0.5            # Also penalize steep descents
        priority:
          - if: road_class == MOTORWAY
            multiply_by: 0
          - if: road_class == FOOTWAY || road_class == PATH
            multiply_by: 1.5
        distance_influence: 50

    - name: foot_hill_training
      vehicle: foot
      weighting: custom
      custom_model:
        priority:
          - if: average_slope > 10
            multiply_by: 2.0            # BOOST steep uphills
          - if: average_slope > 5
            multiply_by: 1.5            # Boost moderate uphills
          - if: average_slope < -3
            multiply_by: 0.8            # Penalize flat/downhill
          - if: road_class == MOTORWAY
            multiply_by: 0
        distance_influence: 90

  # --- SERVER ---
  server:
    application_connectors:
      - type: http
        port: 8989
    admin_connectors:
      - type: http
        port: 8990
```

> [!TIP]
> **`average_slope`** is computed as `100 × (elevation_change / edge_distance)`. A value of `10` means a 10% grade. Its sign flips for reverse traversal, so you can differentiate uphill vs. downhill by checking positive vs. negative values.

#### 2.3.4 GraphHopper API Usage from the Backend

The FastAPI backend calls GraphHopper's API locally:

```
GET http://localhost:8989/route
  ?point=37.7749,-122.4194       # Start (lat,lng)
  &point=37.7849,-122.4094       # End
  &profile=foot_elevation        # OR foot_flat_recovery / foot_hill_training
  &elevation=true                # Include 3D coordinates in response
  &points_encoded=false          # Return GeoJSON (not encoded polyline)
  &details=average_slope         # Include per-edge slope details
  &ch.disable=true               # REQUIRED for custom models
  &algorithm=alternative_route   # Optional: get 2-3 alternative routes
  &alternative_route.max_paths=3
```

The response includes:
- `paths[].points` — GeoJSON with `[lng, lat, elevation]` triples.
- `paths[].details.average_slope` — array of `[fromIndex, toIndex, slopeValue]` for coloring the route.
- `paths[].ascend` / `paths[].descend` — total elevation gain/loss in meters.
- `paths[].distance` — total distance in meters.
- `paths[].time` — estimated time in milliseconds.

#### 2.3.5 Dynamic Custom Model Override (Per-Request)

Instead of relying only on pre-defined profiles, you can send a **custom model JSON body** with each routing request. This is how you inject real-time safety/construction penalties dynamically:

```
POST http://localhost:8989/route
Content-Type: application/json

{
  "points": [[lng1, lat1], [lng2, lat2]],
  "profile": "foot_elevation",
  "elevation": true,
  "ch.disable": true,
  "custom_model": {
    "speed": [
      { "if": "average_slope > 12", "multiply_by": 0.5 }
    ],
    "priority": [
      { "if": "road_class == FOOTWAY", "multiply_by": 1.8 }
    ],
    "areas": {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "id": "crime_zone_1",
          "properties": {},
          "geometry": {
            "type": "Polygon",
            "coordinates": [[[lng, lat], [lng, lat], ...]]
          }
        }
      ]
    }
  }
}
```

The `areas` payload is how you dynamically block or penalize geographic zones (crime, construction, etc.) without rebuilding the graph. Add corresponding priority rules:

```json
{ "if": "in_crime_zone_1", "multiply_by": 0 }
```

### 2.4 Elevation Profile UI Component

Build a dedicated elevation visualization component (`src/components/ElevationProfile.tsx`):

- **Input**: The `paths[].points` array (with elevation as the 3rd coordinate) and `paths[].details.average_slope`.
- **Rendering**: Use a React Native charting library (e.g., `react-native-gifted-charts` or `victory-native`) to draw:
  - X-axis: cumulative distance (km/mi).
  - Y-axis: elevation (m/ft).
  - Fill area under the curve color-coded by slope intensity.
- **Interactive**: Tapping on the chart highlights the corresponding segment on the map (and vice-versa).
- **Summary stats**: Display total ascent ↑, total descent ↓, max elevation, min elevation, and average gradient.

### 2.5 Phase 1 Milestone Checklist

- [ ] React Native project created with New Architecture enabled
- [ ] Mapbox map renders with Streets v8 style on both iOS and Android
- [ ] Custom style emphasizes pedestrian paths and parks
- [ ] User location shows on map with heading indicator
- [ ] GraphHopper server runs locally with SRTM elevation data
- [ ] Three profiles configured: `foot_elevation`, `foot_flat_recovery`, `foot_hill_training`
- [ ] Backend can request routes and receive 3D coordinates + slope details
- [ ] Route line draws on map with elevation-based color gradient
- [ ] Elevation profile chart displays correctly with interactive tapping
- [ ] Round-trip / loop route generation works (start == end with intermediate waypoints)

---

## 3. Phase 2 — FastAPI Backend & PostGIS Spatial Warehouse

### 3.1 FastAPI Project Setup

```bash
mkdir route-backend && cd route-backend
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn[standard] httpx sqlalchemy asyncpg \
            geoalchemy2 shapely geojson python-dotenv pydantic-settings
```

#### Directory Structure

```
route-backend/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app entry, CORS, lifespan
│   ├── config.py             # Pydantic Settings (reads .env)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── spatial.py         # SQLAlchemy + GeoAlchemy2 models
│   │   └── user.py            # User preferences model
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── routes.py          # /generate-route endpoint
│   │   ├── safety.py          # /safety-overlay endpoint
│   │   └── weather.py         # /weather endpoint
│   ├── services/
│   │   ├── __init__.py
│   │   ├── graphhopper.py     # GraphHopper HTTP client
│   │   ├── crime.py           # CrimeOMeter integration
│   │   ├── weather.py         # OpenWeatherMap integration
│   │   ├── construction.py    # Waze CIFS / WZDx parser
│   │   ├── scenic.py          # Mapillary GVI + ParkServe
│   │   └── events.py          # USDA Farmers Market
│   ├── workers/
│   │   ├── __init__.py
│   │   └── data_ingest.py     # Background tasks for data polling
│   └── utils/
│       ├── __init__.py
│       ├── geo.py             # Haversine, GeoJSON helpers
│       └── cache.py           # Redis / in-memory caching
├── alembic/                   # Database migrations
├── alembic.ini
├── requirements.txt
├── .env
└── Dockerfile
```

### 3.2 PostgreSQL + PostGIS Setup

```bash
# Using Docker (recommended for development)
docker run -d --name routegen-db \
  -e POSTGRES_USER=routegen \
  -e POSTGRES_PASSWORD=securepassword \
  -e POSTGRES_DB=routegen_db \
  -p 5432:5432 \
  postgis/postgis:16-3.4

# Inside the database, ensure PostGIS is enabled:
# CREATE EXTENSION IF NOT EXISTS postgis;
```

#### 3.2.1 Core Spatial Tables

```sql
-- Crime safety zones (refreshed periodically)
CREATE TABLE safety_zones (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,           -- 'crimeometer', 'user_report'
    safety_score FLOAT NOT NULL,            -- 0-100 (0 = dangerous, 100 = safe)
    geom GEOMETRY(Polygon, 4326) NOT NULL,  -- WGS84 polygon
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_safety_zones_geom ON safety_zones USING GIST (geom);

-- Construction / road closure zones
CREATE TABLE closure_zones (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,            -- 'waze_cifs', 'wzdx', 'manual'
    closure_type VARCHAR(100),              -- 'road_closure', 'construction', 'event'
    description TEXT,
    geom GEOMETRY(Polygon, 4326) NOT NULL,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_closure_zones_geom ON closure_zones USING GIST (geom);

-- Scenic / green segments
CREATE TABLE scenic_segments (
    id SERIAL PRIMARY KEY,
    gvi_score FLOAT,                        -- Green View Index 0.0-1.0
    park_coverage FLOAT,                    -- % of segment near park
    geom GEOMETRY(LineString, 4326) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_scenic_segments_geom ON scenic_segments USING GIST (geom);

-- User route history
CREATE TABLE route_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    route_geom GEOMETRY(LineString, 4326),
    distance_m FLOAT,
    elevation_gain_m FLOAT,
    duration_s INTEGER,
    profile_used VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### 3.2.2 Key Spatial Queries

```sql
-- Find all unsafe zones that intersect a candidate route's bounding box
SELECT id, safety_score, ST_AsGeoJSON(geom) as geojson
FROM safety_zones
WHERE ST_Intersects(
    geom,
    ST_Buffer(
        ST_GeomFromGeoJSON($route_geojson)::geography,
        500  -- 500m buffer around the route
    )::geometry
)
AND safety_score < 40   -- threshold for "unsafe"
AND expires_at > NOW();

-- Find active construction in radius
SELECT id, description, ST_AsGeoJSON(geom)
FROM closure_zones
WHERE ST_DWithin(
    geom::geography,
    ST_SetSRID(ST_MakePoint($lng, $lat), 4326)::geography,
    5000  -- 5km radius
)
AND (end_time IS NULL OR end_time > NOW());
```

### 3.3 Core Route Generation Endpoint

The main endpoint orchestrates all data sources:

```
POST /api/v1/generate-route
```

**Request body**:
```json
{
  "start": { "lat": 37.7749, "lng": -122.4194 },
  "distance_km": 8.0,
  "elevation_preference": "moderate",   // "flat" | "moderate" | "hilly"
  "avoid_traffic_signals": true,
  "avoid_unsafe_areas": true,
  "prefer_scenic": true,
  "include_events": false,
  "loop": true,                         // return to start
  "weather_aware": true
}
```

**Orchestration flow** (all async, concurrent where possible):
1. Fetch crime data → convert to `areas` GeoJSON polygons.
2. Fetch construction data → merge into `areas`.
3. Fetch weather → determine headwind, shade preference.
4. Select GraphHopper profile based on `elevation_preference`.
5. Build dynamic custom model JSON merging all penalty/boost rules.
6. Generate intermediate waypoints for loop routes (if `loop: true`) using compass-bearing spread.
7. POST to GraphHopper with the full custom model.
8. Get 2-3 alternatives, score them, return the best + alternatives.

---

## 4. Phase 3 — Dynamic Safety, Construction & Traffic-Signal Avoidance

### 4.1 CrimeOMeter Integration

#### 4.1.1 API Call Pattern

```
GET https://api.crimeometer.com/v1/incidents/raw-data
  ?lat=37.7749&lon=-122.4194
  &distance=5mi
  &datetime_ini=2025-10-01T00:00:00.000Z
  &datetime_end=2026-03-01T00:00:00.000Z
  &page=1
```

#### 4.1.2 Processing Pipeline

1. **Fetch** raw incidents for the user's area (5-mile radius).
2. **Grid** the area into ~500m × 500m cells.
3. **Aggregate** incident counts per cell, normalized by cell area.
4. **Compute** Safety Quality Index (SQI) per cell: `SQI = 100 - (normalized_crime_count / max_count × 100)`.
5. **Filter** cells where SQI < configurable threshold (e.g., 40).
6. **Convert** each unsafe cell into a GeoJSON polygon.
7. **Cache** in PostGIS (`safety_zones` table) with a TTL of 24 hours.
8. **Inject** into GraphHopper's `areas` payload with `multiply_by: 0` (total avoidance) or `multiply_by: 0.1` (heavy penalty, allows if no other option).

### 4.2 Construction & Closure Ingestion

#### 4.2.1 Waze CIFS Feed

- Waze provides a GeoRSS/JSON feed of closures and incidents.
- Set up an **async background worker** (`workers/data_ingest.py`) using `asyncio` to poll every 15 minutes.
- Parse closure coordinates → create buffered polygons (50m buffer around linestring closures).
- Upsert into `closure_zones`.

#### 4.2.2 WZDx (Work Zone Data Exchange)

- WZDx provides GeoJSON feeds from regional DOTs.
- Same ingestion pattern: poll, parse, upsert to PostGIS.
- Map WZDx `road_event_status` to penalty severity.

### 4.3 Traffic Signal Avoidance

GraphHopper already encodes OSM node metadata. The approach:

1. In `config.yml`, ensure the foot profile considers traffic signal data. GraphHopper recognizes `highway=traffic_signals` from OSM.
2. In the custom model, add:

```json
{
  "priority": [
    { "if": "max_speed < 1", "multiply_by": 0.7 }
  ]
}
```

> [!NOTE]
> As of GraphHopper 9.x, direct traffic-signal penalization requires either a custom `EncodedValue` via a Java plugin or pre-processing the OSM data to tag edges near signals. The most practical approach for the MVP is:
> - **Option A (Recommended)**: Write a small GraphHopper Java extension that creates a custom `BooleanEncodedValue` called `has_traffic_signal` by checking if an edge touches a node tagged `highway=traffic_signals`. Then use this in the custom model: `{ "if": "has_traffic_signal", "multiply_by": 0.6 }`.
> - **Option B (Simpler MVP)**: Rely on the heuristic that `road_class == RESIDENTIAL` and `road_class == FOOTWAY` segments have fewer signals. Boost their priority when the user selects "minimize stops."

---

## 5. Phase 4 — Experiential Routing, Scenic Beauty & Weather

### 5.1 USDA Farmers Market Integration

```
GET https://www.usdalocalfoodportal.com/api/farmersmarket/
  ?apikey=YOUR_KEY   (or no key for public endpoint)
  &lat=37.7749&lng=-122.4194
  &radius=5
```

- Filter results by today's operating schedule (`Schedule` field).
- If `include_events: true` in the route request, inject active market coordinates as **mid-route waypoints** in the GraphHopper request.
- Use `point` parameter multiple times to force the route through these waypoints.

### 5.2 Green View Index (Scenic Routing)

#### 5.2.1 Mapillary GVI Pipeline

1. Query Mapillary's API for street-level images along candidate route segments.
2. Use Mapillary's built-in semantic segmentation data (object detections) to extract vegetation coverage per image.
3. Compute GVI per road segment: `GVI = pixels_vegetation / pixels_total` (averaged across images on that segment).
4. Store in `scenic_segments` table.

#### 5.2.2 ParkServe Dataset

1. Download ParkServe GeoJSON (park boundaries) for target metro areas.
2. Import into PostGIS as a `parks` table.
3. For route scoring, check `ST_DWithin(route_segment, park_geom, 100)` — segments within 100m of parks get a scenic boost.

#### 5.2.3 Combined Scenic Scoring

For each candidate route returned by GraphHopper:

```
scenic_score = 0.6 × avg_gvi + 0.4 × park_proximity_factor
```

The route with the highest `scenic_score` is ranked higher when `prefer_scenic: true`.

### 5.3 Weather-Aware Routing

#### 5.3.1 OpenWeatherMap One-Call API

```
GET https://api.openweathermap.org/data/3.0/onecall
  ?lat=37.7749&lon=-122.4194
  &exclude=minutely,daily
  &appid=YOUR_KEY
  &units=metric
```

Key fields to use:
- `current.wind_speed`, `current.wind_deg` — headwind analysis.
- `current.temp`, `current.uvi` — heat/shade preference.
- `hourly[0..2]` — look-ahead for route duration.

#### 5.3.2 Wind-Aware Routing Logic

1. Calculate the user's **outbound bearing** (start → farthest waypoint).
2. Compare to `wind_deg`. If headwind component > 15 km/h:
   - Rotate the route generation to favor a different outbound bearing.
   - On loop routes, aim for **tailwind on the return leg** (when the runner is most fatigued).

#### 5.3.3 Heat-Aware Shade Seeking

When `temp > 30°C` or `uvi > 7`:
- Boost `priority` for segments with high GVI (tree canopy = shade).
- Reduce priority for wide, exposed roads.
- Suggest shorter routes or time-shift recommendations.

---

## 6. Phase 5 — Audio Subsystem, Pace Tracking & Wearable Integration

### 6.1 TTS + Audio Ducking

#### 6.1.1 Library Setup

```bash
npm install @mhpdev/react-native-speech
```

This Turbo Module requires RN ≥ 0.68 with New Architecture enabled (which we have from Phase 1).

#### 6.1.2 Audio Ducking Configuration

```typescript
import Speech from '@mhpdev/react-native-speech';

// Enable audio ducking so the user's music volume drops during TTS
Speech.setDuckingEnabled(true);

// Speak a turn-by-turn prompt
await Speech.speak('In 50 meters, turn left onto Elm Street', {
  language: 'en-US',
  rate: 1.0,
  pitch: 1.0,
});
```

**Platform behavior:**
- **iOS**: Uses `AVAudioSession` with `duckOthers` option. Music volume dips, TTS plays, music restores.
- **Android**: Uses `AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK`. Same ducking behavior.

#### 6.1.3 Turn-by-Turn Prompt Generation

Build a service (`src/services/NavigationPromptService.ts`) that:

1. Monitors the user's position against the route waypoints.
2. Uses a proximity threshold (e.g., 50m before a turn) to trigger a TTS prompt.
3. Generates human-readable directions from GraphHopper's `instructions[]` response:
   - `"Turn left onto Oak Avenue"`, `"Continue straight for 400 meters"`, `"You have arrived"`.
4. Queues prompts to avoid overlapping speech.

### 6.2 Real-Time Pace Tracking

#### 6.2.1 Haversine Distance Calculation

Implement in `src/utils/geo.ts`:

```typescript
function haversineDistance(
  lat1: number, lon1: number,
  lat2: number, lon2: number
): number {
  const R = 6371000; // Earth's radius in meters
  const φ1 = lat1 * Math.PI / 180;
  const φ2 = lat2 * Math.PI / 180;
  const Δφ = (lat2 - lat1) * Math.PI / 180;
  const Δλ = (lon2 - lon1) * Math.PI / 180;

  const a = Math.sin(Δφ / 2) ** 2 +
            Math.cos(φ1) * Math.cos(φ2) *
            Math.sin(Δλ / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

  return R * c; // meters
}
```

#### 6.2.2 Rolling Pace Algorithm

- Maintain a **circular buffer** of the last N GPS readings (e.g., N=10).
- For each new reading, compute distance from the previous reading via Haversine.
- Compute instantaneous pace: `pace = timeDelta / distance` (min/km).
- Apply a **weighted moving average** to smooth GPS jitter.
- Filter out readings where `accuracy > 20m` (unreliable GPS).
- Display: current pace, average pace, split times per km/mile.

### 6.3 Wearable Ecosystem (HealthKit + Google Fit)

#### 6.3.1 Apple HealthKit (iOS)

```bash
npm install react-native-health
```

- Request permissions for: `HKQuantityTypeIdentifier.distanceWalkingRunning`, `.activeEnergyBurned`, `.heartRate`, `.stepCount`.
- After a run, write a **workout session** (`HKWorkoutActivityType.running`) with distance, duration, energy, and route GPS data.
- Read historical data for training insights.

#### 6.3.2 Google Fit / Health Connect (Android)

```bash
npm install react-native-health-connect
```

- Use Health Connect (the replacement for Google Fit APIs) on Android 14+.
- Permission scopes: `ExerciseSessionRecord`, `DistanceRecord`, `HeartRateRecord`, `StepsRecord`.
- Write a running session with the same data as HealthKit.

#### 6.3.3 GPX Export for Garmin/Smartwatches

Build a GPX serializer (`src/utils/gpxExporter.ts`):
- Input: route coordinates `[lat, lng, elevation]` + timestamps.
- Output: XML string conforming to GPX 1.1 schema.
- Allow sharing via the OS share sheet → users import into Garmin Connect, Strava, etc.

---

## 7. Phase 6 — Background Geolocation & Battery Optimization

### 7.1 Library

```bash
npm install react-native-background-geolocation
```

This library provides direct access to `CLLocationManager` (iOS) and `FusedLocationProviderClient` (Android).

### 7.2 Dynamic Polling Strategy

| User State | Polling Interval | Accuracy | Distance Filter |
|---|---|---|---|
| **Running, near turn (< 200m)** | 3s | `BestForNavigation` | 5m |
| **Running, straight segment** | 8s | `NearestTenMeters` | 15m |
| **Walking / paused** | 15s | `HundredMeters` | 30m |
| **Stationary (auto-detected)** | 60s | `Kilometer` | 100m |
| **App backgrounded** | 30s | `NearestTenMeters` | 25m |

**Logic**: After each GPS fix, calculate:
1. Distance to the next turn from GraphHopper's `instructions[]`.
2. Current velocity (from GPS or calculated).
3. Adjust the polling configuration accordingly.

### 7.3 Battery Preservation

- Use `stopOnTerminate: false` and `startOnBoot: true` for active run tracking.
- Implement a **geofence** at the destination point. Once reached, switch to coarse tracking.
- On iOS, leverage `significantLocationChange` monitoring as a fallback when high-accuracy tracking has been running > 2 hours.

---

## 8. Project Directory Structure

```
running-route-generator/
├── IMPLEMENTATION_GUIDE.md        ← You are here
│
├── mobile/                        ← React Native app
│   ├── src/
│   │   ├── components/
│   │   │   ├── MapScreen.tsx
│   │   │   ├── ElevationProfile.tsx
│   │   │   ├── RouteOptions.tsx
│   │   │   └── PaceOverlay.tsx
│   │   ├── screens/
│   │   │   ├── HomeScreen.tsx
│   │   │   ├── RunActiveScreen.tsx
│   │   │   └── HistoryScreen.tsx
│   │   ├── services/
│   │   │   ├── NavigationPromptService.ts
│   │   │   ├── PaceTracker.ts
│   │   │   ├── LocationService.ts
│   │   │   └── HealthService.ts
│   │   ├── utils/
│   │   │   ├── geo.ts             # Haversine, bearing calculations
│   │   │   └── gpxExporter.ts
│   │   ├── hooks/
│   │   │   ├── useLocation.ts
│   │   │   ├── useRoute.ts
│   │   │   └── usePace.ts
│   │   ├── api/
│   │   │   └── backendClient.ts   # Axios/fetch wrapper for FastAPI
│   │   ├── store/                 # Zustand or Redux state
│   │   └── App.tsx
│   ├── ios/
│   ├── android/
│   ├── package.json
│   └── .env
│
├── backend/                       ← FastAPI microservice
│   ├── app/                       (see Phase 2 structure)
│   ├── alembic/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env
│
├── graphhopper/                   ← Self-hosted routing engine
│   ├── config/
│   │   └── config.yml
│   ├── data/
│   │   ├── region.osm.pbf
│   │   ├── graph-cache/
│   │   └── elevation-cache/
│   └── docker-compose.yml         (optional containerized GH)
│
├── docker-compose.yml             ← Orchestrates all services
├── .env                           ← Shared secrets
└── README.md
```

---

## 9. Verification & Testing Strategy

### 9.1 Phase 1 Tests (Map + Elevation)

| Test | Method | Pass Criteria |
|---|---|---|
| Map loads on iOS simulator | `npx react-native run-ios` | Map tiles visible, no red screen |
| Map loads on Android emulator | `npx react-native run-android` | Map tiles visible |
| User location dot appears | Grant location permission in sim settings | Blue dot at simulated coords |
| GraphHopper returns 3D route | `curl 'http://localhost:8989/route?point=37.7749,-122.4194&point=37.7849,-122.4094&profile=foot_elevation&elevation=true&points_encoded=false&ch.disable=true'` | Response has `[lng, lat, elevation]` triples |
| Slope details included | Same curl, add `&details=average_slope` | `details.average_slope` array present |
| Flat profile avoids hills | Compare `ascend` values between `foot_elevation` and `foot_flat_recovery` for the same points | `foot_flat_recovery` has significantly lower ascend |
| Hill profile seeks hills | Compare `ascend` values for `foot_hill_training` | Higher total ascend |
| Route draws on map | Trigger route in app | Colored line appears on map |
| Elevation chart renders | Navigate to elevation view | SVG/Canvas chart with distance × elevation |

### 9.2 Backend Tests

```bash
# Run all backend tests
cd backend
pytest tests/ -v --cov=app

# Key test files to create:
# tests/test_graphhopper_service.py  – mock GraphHopper responses
# tests/test_crime_service.py        – mock CrimeOMeter → verify GeoJSON polygon generation
# tests/test_route_endpoint.py       – integration test for /generate-route
# tests/test_spatial_queries.py      – PostGIS query correctness (use testcontainers-python)
```

### 9.3 End-to-End Smoke Test

1. Start all services: `docker-compose up`
2. Open the mobile app on a simulator.
3. Set a starting location and request an 8km loop route with "scenic" and "flat" preferences.
4. Verify: route draws, elevation profile shows, total ascent is low, route prioritizes green areas.
5. Toggle "avoid unsafe areas" → verify route adjusts (may need mock crime data).

---

## 10. Open Questions & Design Decisions

> [!CAUTION]
> The following items require your input before implementation begins.

### Questions for You

1. **Target Geography**: Which metro area(s) should the initial OSM PBF cover? This determines the GraphHopper graph size and download. (e.g., San Francisco Bay Area = ~300 MB PBF, all of California = ~1.2 GB).

2. **Loop Route Algorithm**: For generating running loops (start == end), do you prefer:
   - **Option A**: Generate N waypoints on a circle of radius `distance / (2π)` around the start, then route through them.
   - **Option B**: Use GraphHopper's `round_trip` algorithm (simpler, but less control over shape).
   - **Option C**: Custom algorithm that picks waypoints biased toward scenic/safe areas.

3. **CrimeOMeter Budget**: The free tier is ~1 000 requests/month. For an MVP demo, should we:
   - Pre-fetch and cache data for a fixed metro area nightly (fewer API calls)?
   - Use mock/synthetic crime data initially and integrate the real API later?

4. **Deployment Target**: For the backend + GraphHopper + PostGIS stack, do you plan to:
   - Run everything locally via Docker Compose during development?
   - Deploy to a cloud provider (AWS, GCP, etc.)? If so, which one?

5. **Authentication**: The spec doesn't mention user auth. Should we add JWT-based auth (e.g., via Firebase Auth or Supabase) for user accounts and route history?

6. **Offline Support**: Should the app support pre-downloading routes/map tiles for offline use during runs (important for trails with poor cell coverage)?

7. **Units**: Default to metric (km, m elevation) with an imperial toggle, or auto-detect from user locale?

---

> **Next Step**: Once these questions are answered, implementation begins with Phase 1 (Map + Elevation Routing). The estimated timeline for Phase 1 is 2-3 weeks for a single developer.
