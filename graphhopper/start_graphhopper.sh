#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GH_VERSION="10.0"
GH_JAR="$SCRIPT_DIR/graphhopper-web-${GH_VERSION}.jar"
CONFIG="$SCRIPT_DIR/config.yml"

if [ ! -f "$GH_JAR" ]; then
    echo "❌ GraphHopper JAR not found. Run setup_graphhopper.sh first."
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/data/norcal-latest.osm.pbf" ]; then
    echo "❌ OSM data not found. Run setup_graphhopper.sh first."
    exit 1
fi

echo "🚀 Starting GraphHopper server..."
echo "   Config: $CONFIG"
echo "   Server: http://localhost:8989"
echo "   Admin:  http://localhost:8990"
echo ""

if [ ! -d "$SCRIPT_DIR/data/graph-cache" ]; then
    echo "⏳ First launch — building routing graph with elevation data."
    echo "   This takes ~5-10 minutes for NorCal. Please wait..."
    echo ""
fi

# Run with 4GB heap. All config is in config.yml — no -D overrides needed.
cd "$SCRIPT_DIR"
java -Xmx4g -Xms1g -jar "$GH_JAR" server "$CONFIG"
