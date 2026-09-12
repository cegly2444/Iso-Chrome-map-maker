"""
Command-Line Interface for Isochrone Map Maker
----------------------------------------------
Run headless spatial queries, print summary stats to the terminal,
and export an interactive Folium HTML map.

Usage:
  python cli.py --address "Times Square, New York" --time 15 --modes driving-car,cycling-regular
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

from isochrone_analyzer import (
    TRANSIT_MODES,
    DEFAULT_CATEGORIES,
    geocode_location,
    get_isochrone,
    compute_combined_bounding_box,
    fetch_pois,
    filter_pois_in_polygons,
    build_folium_map,
    ApartmentAnalyzer,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Isochrone Map Maker: Spatial reachability and POI analysis tool."
    )
    parser.add_argument(
        "--address",
        "-a",
        type=str,
        default="Empire State Building, New York",
        help="Center address or landmark name to geocode.",
    )
    parser.add_argument("--lat", type=float, default=None, help="Latitude override (skips geocoding).")
    parser.add_argument("--lon", type=float, default=None, help="Longitude override (skips geocoding).")
    parser.add_argument(
        "--time",
        "-t",
        type=int,
        default=15,
        help="Commute / travel time in minutes (default: 15).",
    )
    parser.add_argument(
        "--modes",
        "-m",
        type=str,
        default="driving-car,cycling-regular,foot-walking",
        help="Comma-separated transit modes: driving-car, cycling-regular, foot-walking.",
    )
    parser.add_argument(
        "--categories",
        "-c",
        type=str,
        default="Coffee & Cafes,Apartment Buildings,Gyms & Fitness",
        help="Comma-separated POI categories to query.",
    )
    parser.add_argument(
        "--api-key",
        "-k",
        type=str,
        default=os.environ.get("ORS_API_KEY", ""),
        help="OpenRouteService API key (optional, uses demo mode if omitted).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Force simulated / demo isochrones without calling external ORS API.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="isochrone_map.html",
        help="Output HTML path for the interactive Folium map (default: isochrone_map.html).",
    )
    parser.add_argument(
        "--no-cluster",
        action="store_true",
        help="Disable marker clustering on the output map.",
    )

    return parser.parse_args()


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    args = parse_args()

    print("=" * 65)
    print("           ISOCHRONE MAP MAKER & SPATIAL ANALYZER")
    print("=" * 65)

    # 1. Resolve Location
    if args.lat is not None and args.lon is not None:
        target_lat, target_lon = args.lat, args.lon
        target_name = f"Coordinates ({target_lat:.4f}, {target_lon:.4f})"
        print(f"[*] Target Location (Manual): {target_name}")
    else:
        print(f"[*] Geocoding address: '{args.address}'...")
        try:
            geo = geocode_location(args.address)
            target_lat, target_lon = geo["lat"], geo["lon"]
            target_name = geo["display_name"]
            print(f"    Found: {target_name}")
            print(f"    Lat: {target_lat:.5f}, Lon: {target_lon:.5f}")
        except Exception as e:
            print(f"[!] Geocoding error: {e}", file=sys.stderr)
            sys.exit(1)

    # 2. Parse Modes and Categories (support aliases like 'walking', 'driving', 'biking')
    mode_aliases = {
        "driving": "driving-car",
        "car": "driving-car",
        "driving-car": "driving-car",
        "walking": "foot-walking",
        "foot": "foot-walking",
        "walk": "foot-walking",
        "foot-walking": "foot-walking",
        "cycling": "cycling-regular",
        "biking": "cycling-regular",
        "bike": "cycling-regular",
        "cycling-regular": "cycling-regular",
    }
    modes_list = []
    for m in args.modes.split(","):
        clean_m = m.strip().lower()
        if clean_m in mode_aliases and mode_aliases[clean_m] not in modes_list:
            modes_list.append(mode_aliases[clean_m])

    if not modes_list:
        print(f"[!] No valid transit modes specified. Supported: driving, walking, cycling", file=sys.stderr)
        sys.exit(1)

    # Category matching (fuzzy case-insensitive match against DEFAULT_CATEGORIES keys)
    cat_keys_lower = {k.lower(): k for k in DEFAULT_CATEGORIES.keys()}
    selected_cats: List[str] = []
    for c_raw in args.categories.split(","):
        c_clean = c_raw.strip().lower()
        matched = False
        for k_low, k_orig in cat_keys_lower.items():
            if c_clean in k_low or k_low in c_clean:
                selected_cats.append(k_orig)
                matched = True
                break
        if not matched and c_raw.strip():
            selected_cats.append(c_raw.strip())

    print(f"[*] Commute Time: {args.time} minutes")
    print(f"[*] Transit Modes: {', '.join(modes_list)}")
    print(f"[*] POI Categories: {', '.join(selected_cats)}")

    # 3. Generate Isochrones
    isochrone_results = []
    use_sim = args.demo or not bool(args.api_key.strip())
    if use_sim:
        print("[i] Running in Simulated Isochrone Mode.")
    else:
        print("[*] Contacting OpenRouteService API...")

    for m_key in modes_list:
        try:
            iso = get_isochrone(
                lat=target_lat,
                lon=target_lon,
                mode_key=m_key,
                minutes=args.time,
                api_key=args.api_key,
                force_simulated=use_sim,
            )
            isochrone_results.append(iso)
            area = iso["features"][0]["properties"].get("area_sq_km", "N/A")
            print(f"    + {TRANSIT_MODES[m_key]['label']}: {area} sq km coverage")
        except Exception as e:
            print(f"[!] Error generating {m_key} isochrone: {e}", file=sys.stderr)

    if not isochrone_results:
        print("[!] No isochrones could be generated.", file=sys.stderr)
        sys.exit(1)

    # 4. Fetch POIs from Overpass
    bbox = compute_combined_bounding_box(isochrone_results)
    print(f"[*] Querying OpenStreetMap Overpass API within bounding box...")
    try:
        raw_pois = fetch_pois(bbox, selected_cats)
        print(f"    Retrieved {len(raw_pois)} total raw amenities in bounding region.")
    except Exception as e:
        print(f"[!] Overpass API query failed: {e}", file=sys.stderr)
        sys.exit(1)

    # 5. Spatial Intersection (Point in Polygon)
    print(f"[*] Running Point-in-Polygon check via Shapely...")
    filtered_pois, stats = filter_pois_in_polygons(
        isochrone_results, raw_pois, target_lat, target_lon
    )

    # 6. Display Statistics
    print("\n" + "=" * 65)
    print(f"  SPATIAL RESULTS SUMMARY ({args.time} MIN COMMUTE)")
    print("=" * 65)
    print(f"  Total Valid Amenities Reachable: {stats['total_pois']}")
    print("-" * 65)
    print("  Counts by Amenity Category:")
    for cat, count in stats["by_category"].items():
        print(f"    • {cat:<30}: {count:>4}")

    print("-" * 65)
    print("  Counts Reachable by Transit Mode:")
    for mode_label, count in stats["by_mode"].items():
        print(f"    • {mode_label:<30}: {count:>4}")

    # Apartment specific summary if present
    if "Apartment Buildings" in selected_cats:
        apts = ApartmentAnalyzer.extract_apartment_features(filtered_pois)
        apt_summary = ApartmentAnalyzer.summarize_apartments(apts)
        print("-" * 65)
        print("  🏢 Apartment & Residential Insights:")
        print(f"    • Total Apartments Found        : {apt_summary['count']}")
        print(f"    • Average Distance to Work/Site : {apt_summary['avg_distance_mi']} miles")
        print(f"    • Listings with Website/Contact : {apt_summary['has_website_count']}")

    print("=" * 65)

    # 7. Generate Folium Map
    print(f"[*] Building interactive Folium map...")
    m = build_folium_map(
        center_lat=target_lat,
        center_lon=target_lon,
        center_name=target_name,
        isochrone_results=isochrone_results,
        filtered_pois=filtered_pois,
        cluster_markers=not args.no_cluster,
    )
    m.save(args.output)
    print(f"[PASS] Interactive map saved successfully to: {os.path.abspath(args.output)}")
    print("       Open this file in any web browser to view your map!\n")


if __name__ == "__main__":
    main()
