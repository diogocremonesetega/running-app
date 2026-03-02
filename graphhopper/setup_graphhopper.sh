#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
GH_VERSION="10.0"  # Latest stable as of 2025
GH_JAR="graphhopper-web-${GH_VERSION}.jar"
GH_JAR_URL="https://repo1.maven.org/maven2/com/graphhopper/graphhopper-web/${GH_VERSION}/graphhopper-web-${GH_VERSION}.jar"

# OSM data — NorCal extract (smallest Geofabrik extract containing Berkeley)
OSM_URL="https://download.geofabrik.de/north-america/us/california/norcal-latest.osm.pbf"
OSM_FILE="norcal-latest.osm.pbf"

echo "=== GraphHopper Setup for Running Route Generator ==="
echo "Target area: Berkeley / UC Berkeley campus"
echo ""

# Create directories
mkdir -p "$DATA_DIR"
mkdir -p "$SCRIPT_DIR/elevation-cache"

# Download GraphHopper JAR
if [ ! -f "$SCRIPT_DIR/$GH_JAR" ]; then
    echo "📦 Downloading GraphHopper Web $GH_VERSION..."
    curl -L -o "$SCRIPT_DIR/$GH_JAR" "$GH_JAR_URL"
    echo "✅ GraphHopper JAR downloaded."
else
    echo "✅ GraphHopper JAR already exists."
fi

# Download OSM data
if [ ! -f "$DATA_DIR/$OSM_FILE" ]; then
    echo "🗺️  Downloading NorCal OSM PBF (~450 MB, may take a few minutes)..."
    curl -L -o "$DATA_DIR/$OSM_FILE" "$OSM_URL"
    echo "✅ OSM data downloaded."
else
    echo "✅ OSM data already exists."
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start GraphHopper, run:"
echo "  cd $SCRIPT_DIR && bash start_graphhopper.sh"
echo ""
echo "First launch builds the routing graph (~5-10 min for NorCal + elevation)."
echo "Subsequent launches reuse the cached graph (< 30 seconds)."
