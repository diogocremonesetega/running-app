#!/usr/bin/env python3
"""Verification test script for Phase 1 — Elevation Routing & Traffic Signal Detection.

Run this after starting both GraphHopper (:8989) and the FastAPI backend (:8000).

Usage:
    python3 tests/test_routes.py
"""

import json
import sys
import time
import urllib.request
import urllib.error

API_BASE = "http://localhost:8000"
GH_BASE = "http://localhost:8080"

# UC Berkeley campus — Sather Gate area
START_LAT = 37.8702
START_LNG = -122.2595

# Memorial Stadium (hilly area east of campus)
END_LAT = 37.8707
END_LNG = -122.2505

PASS = 0
FAIL = 0
TESTS = []


def test(name, condition, details=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        TESTS.append(("✅", name, details))
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        TESTS.append(("❌", name, details))
        print(f"  ❌ {name} — {details}")


def api_get(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def api_post(url, body):
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    print("\n" + "=" * 60)
    print("  Phase 1 Verification Tests")
    print("  Running Route Generator — Berkeley / UC Berkeley")
    print("=" * 60)

    # --- 1. GraphHopper Health ---
    print("\n📡 1. GraphHopper Connection")
    gh_health = api_get(f"{GH_BASE}/health")
    test("GraphHopper is reachable", "error" not in gh_health, gh_health.get("error", ""))

    # --- 2. Direct GraphHopper route with elevation ---
    print("\n🗺️  2. Direct GraphHopper Route with Elevation")
    gh_route = api_get(
        f"{GH_BASE}/route?point={START_LAT},{START_LNG}&point={END_LAT},{END_LNG}"
        f"&profile=foot_elevation&elevation=true&points_encoded=false"
        f"&details=average_slope&ch.disable=true"
    )

    has_paths = "paths" in gh_route and len(gh_route.get("paths", [])) > 0
    test("GraphHopper returns route", has_paths, gh_route.get("error", "No paths returned"))

    if has_paths:
        path = gh_route["paths"][0]
        coords = path.get("points", {}).get("coordinates", [])
        has_3d = len(coords) > 0 and len(coords[0]) >= 3
        test("Route has 3D coordinates (elevation)", has_3d,
             f"Coord dimensions: {len(coords[0]) if coords else 'N/A'}")

        has_ascend = "ascend" in path and path["ascend"] > 0
        test("Route has elevation gain (ascend > 0)", has_ascend,
             f"ascend={path.get('ascend', 'N/A')}")

        has_slope = "average_slope" in path.get("details", {})
        test("Route has slope details", has_slope)

        if has_slope:
            slopes = path["details"]["average_slope"]
            slope_values = [s[2] for s in slopes]
            has_varied_slopes = max(slope_values) - min(slope_values) > 0.5
            test("Slopes are varied (terrain changes)", has_varied_slopes,
                 f"range: {min(slope_values):.1f}% to {max(slope_values):.1f}%")

    # --- 3. Backend Health ---
    print("\n🖥️  3. FastAPI Backend Connection")
    be_health = api_get(f"{API_BASE}/api/v1/health")
    test("Backend is reachable", "error" not in be_health, be_health.get("error", ""))
    test("Backend reports GH connected",
         be_health.get("graphhopper", {}).get("status") == "ok",
         f"GH status: {be_health.get('graphhopper', {}).get('status', 'N/A')}")

    # --- 4. Loop Route Generation ---
    print("\n🔄 4. Loop Route Generation (5km, moderate)")
    loop_result = api_post(f"{API_BASE}/api/v1/generate-route", {
        "start": {"lat": START_LAT, "lng": START_LNG},
        "distance_km": 5.0,
        "elevation_preference": "moderate",
        "avoid_traffic_signals": False,
        "prioritize_well_lit_streets": False,
        "prioritize_soft_surfaces": False,
        "include_water": False,
        "include_restrooms": False,
    })

    has_route = "route" in loop_result and "geometry" in loop_result.get("route", {})
    test("Loop route generated", has_route, loop_result.get("error", ""))

    if has_route:
        props = loop_result["route"]["properties"]
        test("Distance is reasonable (2-15 km)",
             2 < props.get("distance_km", 0) < 15,
             f"distance={props.get('distance_km', 'N/A')} km")

        test("Has elevation data",
             props.get("ascend_m", 0) > 0,
             f"ascend={props.get('ascend_m')}m, descend={props.get('descend_m')}m")

        # Check it's a loop (start ≈ end)
        coords = loop_result["route"]["geometry"].get("coordinates", [])
        if coords:
            start_coord = coords[0]
            end_coord = coords[-1]
            dist_diff = ((start_coord[0] - end_coord[0])**2 + (start_coord[1] - end_coord[1])**2) ** 0.5
            test("Route is a loop (start ≈ end)",
                 dist_diff < 0.001,  # ~100m at Berkeley latitude
                 f"start/end gap: {dist_diff:.6f}°")

        # Elevation profile
        has_profile = len(loop_result.get("elevation_profile", [])) > 0
        test("Elevation profile data returned", has_profile,
             f"{len(loop_result.get('elevation_profile', []))} points")

        has_stats = "elevation_stats" in loop_result
        test("Elevation stats computed", has_stats)

        has_waypoints = len(loop_result.get("waypoints_generated", [])) >= 1
        test("Start waypoint metadata returned", has_waypoints)

    # --- 5. Profile Comparison ---
    print("\n📊 5. Elevation Profile Comparison (flat vs moderate vs hilly)")
    ascends = {}
    for pref in ["flat", "moderate", "hilly"]:
        result = api_post(f"{API_BASE}/api/v1/generate-route", {
            "start": {"lat": START_LAT, "lng": START_LNG},
            "distance_km": 5.0,
            "elevation_preference": pref,
            "avoid_traffic_signals": False,
            "prioritize_well_lit_streets": False,
            "prioritize_soft_surfaces": False,
            "include_water": False,
            "include_restrooms": False,
        })
        if "route" in result:
            a = result["route"]["properties"].get("ascend_m", 0)
            ascends[pref] = a
            print(f"    {pref:>10}: ↑{a}m  dist={result['route']['properties'].get('distance_km')}km")
        else:
            print(f"    {pref:>10}: ERROR — {result.get('error', 'unknown')}")

    if len(ascends) == 3:
        test("Flat has less ascent than hilly",
             ascends.get("flat", 999) < ascends.get("hilly", 0),
             f"flat={ascends.get('flat')}m vs hilly={ascends.get('hilly')}m")
        test("Hilly has most ascent",
             ascends.get("hilly", 0) >= ascends.get("moderate", 0),
             f"hilly={ascends.get('hilly')}m vs moderate={ascends.get('moderate')}m")

    # --- 6. Traffic Signal Avoidance ---
    print("\n🚦 6. Traffic Signal Avoidance")
    infra_off = {
        "prioritize_well_lit_streets": False,
        "prioritize_soft_surfaces": False,
        "include_water": False,
        "include_restrooms": False,
    }
    normal = api_post(f"{API_BASE}/api/v1/generate-route", {
        "start": {"lat": START_LAT, "lng": START_LNG},
        "distance_km": 5.0,
        "elevation_preference": "moderate",
        "avoid_traffic_signals": False,
        **infra_off,
    })
    avoid = api_post(f"{API_BASE}/api/v1/generate-route", {
        "start": {"lat": START_LAT, "lng": START_LNG},
        "distance_km": 5.0,
        "elevation_preference": "moderate",
        "avoid_traffic_signals": True,
        **infra_off,
    })

    if "route" in normal and "route" in avoid:
        normal_dist = normal["route"]["properties"]["distance_km"]
        avoid_dist = avoid["route"]["properties"]["distance_km"]
        normal_flags = normal["route"]["properties"].get("avoid_traffic_signals")
        avoid_flags = avoid["route"]["properties"].get("avoid_traffic_signals")

        test("Signal toggle reflected in response",
             normal_flags is False and avoid_flags is True,
             f"normal={normal_flags}, avoid={avoid_flags}")

        # The routes should differ somewhat (different distances or paths)
        routes_differ = abs(normal_dist - avoid_dist) > 0.05
        normal_coords = json.dumps(normal["route"]["geometry"]["coordinates"][:5])
        avoid_coords = json.dumps(avoid["route"]["geometry"]["coordinates"][:5])
        test("Routes differ (signal avoidance changes path)",
             routes_differ or normal_coords != avoid_coords,
             f"normal={normal_dist}km, avoid={avoid_dist}km")

        print(f"    Normal: {normal_dist}km")
        print(f"    Avoid:  {avoid_dist}km")

    # --- Summary ---
    print("\n" + "=" * 60)
    print(f"  Results: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    print("=" * 60)

    if FAIL > 0:
        print("\n  Failed tests:")
        for icon, name, details in TESTS:
            if icon == "❌":
                print(f"    • {name}: {details}")

    print()
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
