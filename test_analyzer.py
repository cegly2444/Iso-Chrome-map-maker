"""
Test suite for Isochrone Analyzer Core Functions
"""

import os
from isochrone_analyzer import (
    geocode_location,
    generate_simulated_isochrone,
    filter_pois_in_polygons,
    build_folium_map,
    build_overpass_query,
    ApartmentAnalyzer,
    haversine_distance_miles,
)

def test_haversine():
    # NYC Empire State to Flatiron ~ 0.5 miles
    d = haversine_distance_miles(40.7484, -73.9857, 40.7411, -73.9897)
    assert 0.4 < d < 0.7, f"Expected ~0.5 mi, got {d}"
    print("[PASS] Haversine distance test passed")

def test_geocoding():
    res = geocode_location("Empire State Building")
    assert "lat" in res and "lon" in res
    assert 40.7 < res["lat"] < 40.8
    assert -74.1 < res["lon"] < -73.8
    print("[PASS] Geocoding test passed:", res["display_name"][:40])

def test_simulated_isochrone():
    lat, lon = 40.7484, -73.9857
    iso = generate_simulated_isochrone(lat, lon, "driving-car", 15)
    assert iso["type"] == "FeatureCollection"
    feat = iso["features"][0]
    assert feat["geometry"]["type"] == "Polygon"
    assert len(feat["geometry"]["coordinates"][0]) == 49  # 48 + 1 closing
    print("[PASS] Simulated isochrone test passed, area:", feat["properties"]["area_sq_km"], "sq km")

def test_overpass_query():
    bbox = (40.74, -73.99, 40.75, -73.98)
    q = build_overpass_query(bbox, ["Coffee & Cafes", "Gyms & Fitness"])
    assert "amenity" in q and "cafe" in q
    assert "fitness_centre" in q
    print("[PASS] Overpass query builder test passed")

def test_spatial_filtering_and_map():
    lat, lon = 40.7484, -73.9857
    # 15 min driving polygon
    iso_drive = generate_simulated_isochrone(lat, lon, "driving-car", 15)
    # 10 min walking polygon
    iso_walk = generate_simulated_isochrone(lat, lon, "foot-walking", 10)

    # Test POIs (one very close, one within drive, one in Tokyo)
    mock_pois = [
        {
            "osm_id": "node/1",
            "name": "Local Coffee Shop",
            "category": "Coffee & Cafes",
            "lat": 40.7485,
            "lon": -73.9858,
            "tags": {"amenity": "cafe"},
        },
        {
            "osm_id": "node/2",
            "name": "Midtown Gym",
            "category": "Gyms & Fitness",
            "lat": 40.7600,
            "lon": -73.9800,
            "tags": {"leisure": "fitness_centre"},
        },
        {
            "osm_id": "node/3",
            "name": "Far Away Place",
            "category": "Coffee & Cafes",
            "lat": 35.6762,
            "lon": 139.6503,
            "tags": {"amenity": "cafe"},
        },
        {
            "osm_id": "way/4",
            "name": "Sunset Luxury Apartments",
            "category": "Apartment Buildings",
            "lat": 40.7490,
            "lon": -73.9860,
            "tags": {
                "building": "apartments",
                "building:levels": "12",
                "flats": "84",
                "addr:street": "5th Ave",
                "website": "https://example.com/apartments",
            },
        },
    ]

    filtered, stats = filter_pois_in_polygons([iso_drive, iso_walk], mock_pois, lat, lon)
    assert len(filtered) >= 2, f"Expected at least 2 filtered POIs, got {len(filtered)}"
    # Tokyo should be filtered out
    assert not any(p["osm_id"] == "node/3" for p in filtered)
    print("[PASS] Spatial filtering test passed! Stats:", stats["by_category"])

    # Test Apartment analyzer
    apts = ApartmentAnalyzer.extract_apartment_features(filtered)
    assert len(apts) >= 1
    apt_summary = ApartmentAnalyzer.summarize_apartments(apts)
    assert apt_summary["count"] >= 1
    assert apt_summary["has_website_count"] >= 1
    print("[PASS] Apartment analyzer test passed:", apt_summary)

    # Test Folium Map generation
    m = build_folium_map(lat, lon, "Empire State", [iso_drive, iso_walk], filtered)
    html_out = "test_map_output.html"
    m.save(html_out)
    assert os.path.exists(html_out)
    assert os.path.getsize(html_out) > 1000
    os.remove(html_out)
    print("[PASS] Folium interactive map generation passed!")

if __name__ == "__main__":
    test_haversine()
    test_geocoding()
    test_simulated_isochrone()
    test_overpass_query()
    test_spatial_filtering_and_map()
    print("\nALL TESTS PASSED!")

