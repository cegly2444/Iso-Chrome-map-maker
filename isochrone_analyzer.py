"""
Isochrone Spatial Analysis and POI Engine
-----------------------------------------
Handles geocoding, multi-modal travel-time isochrones, Overpass API queries for POIs,
point-in-polygon filtering via Shapely, and interactive Folium map visualization.
"""

from __future__ import annotations

import math
import random
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import requests
from shapely.geometry import Point, shape, Polygon, MultiPolygon
from shapely.prepared import prep
import folium
from folium.plugins import MarkerCluster
from branca.element import Element, MacroElement
from jinja2 import Template

# ---------------------------------------------------------------------------
# Google Maps Direct URL Generator
# ---------------------------------------------------------------------------

def create_google_maps_url(
    name: str, lat: float, lon: float, tags: Optional[Dict[str, Any]] = None
) -> str:
    """
    Constructs an accurate Google Maps search URL.
    Avoids passing generic 'Unnamed' placeholders which confuse Google Maps text search
    into showing irrelevant business matches (e.g. 'The Diplomat Apartments').
    """
    tags = tags or {}
    addr_parts = []
    if tags.get("addr:housenumber"):
        addr_parts.append(str(tags["addr:housenumber"]))
    if tags.get("addr:street"):
        addr_parts.append(str(tags["addr:street"]))
    if tags.get("addr:city"):
        addr_parts.append(str(tags["addr:city"]))
    addr_str = " ".join(addr_parts) if addr_parts else None

    clean_name = (name or "").replace('"', "").replace("'", "").strip()
    is_real_name = (
        clean_name
        and not clean_name.lower().startswith("unnamed")
        and clean_name.lower() != "other"
    )

    if is_real_name:
        query = f"{clean_name}, {lat:.6f},{lon:.6f}"
    elif addr_str:
        query = f"{addr_str}, {lat:.6f},{lon:.6f}"
    else:
        # Exact GPS pin prevents Google Maps from doing an ambiguous keyword search
        query = f"{lat:.6f},{lon:.6f}"

    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(query)}"


# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------

USER_AGENT = "IsochroneMapMaker/1.0 (https://github.com/cegly2444/Iso-Chrome-map-maker)"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ORS_API_URL = "https://api.openrouteservice.org/v2/isochrones/{profile}"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Supported transit profiles with UI display info and simulated speeds (km/h)
TRANSIT_MODES: Dict[str, Dict[str, Any]] = {
    "driving-car": {
        "label": "Driving 🚗",
        "profile": "driving-car",
        "color": "#1f77b4",
        "fill_color": "#3498db",
        "fill_opacity": 0.22,
        "simulated_speed_kmh": 38.0,
    },
    "cycling-regular": {
        "label": "Cycling 🚲",
        "profile": "cycling-regular",
        "color": "#2ca02c",
        "fill_color": "#2ecc71",
        "fill_opacity": 0.25,
        "simulated_speed_kmh": 16.0,
    },
    "foot-walking": {
        "label": "Walking 🚶",
        "profile": "foot-walking",
        "color": "#d35400",
        "fill_color": "#e67e22",
        "fill_opacity": 0.30,
        "simulated_speed_kmh": 4.8,
    },
}

# Pre-configured POI Categories with OSM Tags and Marker Styles
DEFAULT_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "Coffee & Cafes": {
        "tags": [("amenity", "cafe")],
        "icon": "coffee",
        "color": "darkred",
        "cluster_color": "#8B0000",
        "prefix": "fa",
    },
    "Apartment Buildings": {
        "tags": [
            ("building", "apartments"),
            ("building", "residential"),
            ("building", "flats"),
            ("building", "dormitory"),
            ("building", "condominium"),
            ("residential", "apartments"),
            ("residential", "flats"),
            ("residential", "condominium"),
            ("amenity", "student_accommodation"),
        ],
        "icon": "building",
        "color": "purple",
        "cluster_color": "#8e44ad",
        "prefix": "fa",
    },
    "Gyms & Fitness": {
        "tags": [
            ("leisure", "fitness_centre"),
            ("leisure", "sports_centre"),
        ],
        "icon": "heartbeat",
        "color": "green",
        "cluster_color": "#27ae60",
        "prefix": "fa",
    },
    "Supermarkets & Groceries": {
        "tags": [
            ("shop", "supermarket"),
            ("shop", "convenience"),
            ("shop", "grocery"),
        ],
        "icon": "shopping-cart",
        "color": "orange",
        "cluster_color": "#d35400",
        "prefix": "fa",
    },
    "Restaurants & Dining": {
        "tags": [
            ("amenity", "restaurant"),
            ("amenity", "fast_food"),
        ],
        "icon": "cutlery",
        "color": "red",
        "cluster_color": "#c0392b",
        "prefix": "fa",
    },
    "Bars & Pubs": {
        "tags": [
            ("amenity", "bar"),
            ("amenity", "pub"),
        ],
        "icon": "glass",
        "color": "darkpurple",
        "cluster_color": "#5c2d91",
        "prefix": "fa",
    },
    "Parks & Green Space": {
        "tags": [
            ("leisure", "park"),
            ("leisure", "garden"),
        ],
        "icon": "tree",
        "color": "darkgreen",
        "cluster_color": "#1e7e34",
        "prefix": "fa",
    },
    "Transit Stops & Stations": {
        "tags": [
            ("highway", "bus_stop"),
            ("railway", "station"),
            ("railway", "subway_entrance"),
        ],
        "icon": "bus",
        "color": "cadetblue",
        "cluster_color": "#2980b9",
        "prefix": "fa",
    },
    "Schools & Education": {
        "tags": [
            ("amenity", "school"),
            ("amenity", "college"),
            ("amenity", "university"),
        ],
        "icon": "graduation-cap",
        "color": "blue",
        "cluster_color": "#1a5276",
        "prefix": "fa",
    },
}


# ---------------------------------------------------------------------------
# Geocoding & Distance Utilities
# ---------------------------------------------------------------------------

def geocode_location(query: str) -> Dict[str, Any]:
    """
    Geocodes an address or landmark query to latitude/longitude using OSM Nominatim.
    """
    if not query or not query.strip():
        raise ValueError("Address query cannot be empty.")

    headers = {"User-Agent": USER_AGENT}
    params = {"q": query.strip(), "format": "json", "limit": 1}

    try:
        response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=12)
        response.raise_for_status()
        data = response.json()
        if not data:
            raise ValueError(f"Could not find coordinates for: '{query}'. Try a more specific address or landmark.")
        
        return {
            "lat": float(data[0]["lat"]),
            "lon": float(data[0]["lon"]),
            "display_name": data[0].get("display_name", query),
        }
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Geocoding request failed: {e}")


def haversine_distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points in miles."""
    r = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points in kilometers."""
    return haversine_distance_miles(lat1, lon1, lat2, lon2) * 1.60934


# ---------------------------------------------------------------------------
# Isochrone Generation (OpenRouteService + Realistic Simulated Fallback)
# ---------------------------------------------------------------------------

def generate_simulated_isochrone(
    lat: float, lon: float, mode_key: str, minutes: int
) -> Dict[str, Any]:
    """
    Generates a realistic organic travel-time polygon for offline testing or demo mode.
    Simulates non-uniform street grid expansion with radial variation.
    """
    mode_info = TRANSIT_MODES.get(mode_key, TRANSIT_MODES["driving-car"])
    speed_kmh = mode_info["simulated_speed_kmh"]
    travel_hours = minutes / 60.0
    base_radius_km = speed_kmh * travel_hours

    # 1 deg lat ~ 111 km; 1 deg lon ~ 111 * cos(lat) km
    lat_deg_per_km = 1.0 / 110.574
    lon_deg_per_km = 1.0 / (111.320 * math.cos(math.radians(lat)))

    num_points = 48
    coords = []
    # Seed deterministic variation from lat, lon, mode, minutes
    rng = random.Random(f"{round(lat, 4)}_{round(lon, 4)}_{mode_key}_{minutes}")

    for i in range(num_points):
        angle = 2.0 * math.pi * i / num_points
        # Add road corridor lobes (e.g. highways / main arteries in cardinal/intercardinal directions)
        arterial_factor = 1.0 + 0.20 * math.cos(4 * angle) + 0.12 * math.sin(2 * angle)
        noise_factor = rng.uniform(0.82, 1.18)
        radius = base_radius_km * arterial_factor * noise_factor

        d_lat = radius * math.cos(angle) * lat_deg_per_km
        d_lon = radius * math.sin(angle) * lon_deg_per_km
        coords.append([lon + d_lon, lat + d_lat])

    coords.append(coords[0])  # Close polygon ring

    area_sq_km = math.pi * (base_radius_km ** 2) * 0.95

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords],
                },
                "properties": {
                    "value": minutes * 60,
                    "center": [lon, lat],
                    "mode": mode_key,
                    "mode_label": mode_info["label"],
                    "minutes": minutes,
                    "area_sq_km": round(area_sq_km, 2),
                    "is_simulated": True,
                },
            }
        ],
    }


def get_isochrone(
    lat: float,
    lon: float,
    mode_key: str,
    minutes: int,
    api_key: Optional[str] = None,
    force_simulated: bool = False,
) -> Dict[str, Any]:
    """
    Fetches an isochrone polygon from OpenRouteService or falls back to simulation.
    Returns GeoJSON FeatureCollection.
    """
    mode_info = TRANSIT_MODES.get(mode_key)
    if not mode_info:
        raise ValueError(f"Unsupported transit mode: {mode_key}")

    clean_key = (api_key or "").strip()
    if force_simulated or not clean_key or clean_key.lower() == "demo":
        return generate_simulated_isochrone(lat, lon, mode_key, minutes)

    url = ORS_API_URL.format(profile=mode_info["profile"])
    headers = {
        "Authorization": clean_key,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": USER_AGENT,
    }
    payload = {
        "locations": [[lon, lat]],
        "range": [minutes * 60],
        "attributes": ["area", "reachfactor"],
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        if response.status_code == 401:
            raise ValueError("OpenRouteService API Key is invalid or unauthorized. Please verify your key.")
        if response.status_code == 429:
            raise ValueError("OpenRouteService rate limit / quota exceeded. Try again later or use Demo mode.")
        if response.status_code != 200:
            raise RuntimeError(f"OpenRouteService error {response.status_code}: {response.text}")

        data = response.json()
        if "features" in data and len(data["features"]) > 0:
            # Inject helper properties
            for feat in data["features"]:
                feat.setdefault("properties", {})
                feat["properties"]["mode"] = mode_key
                feat["properties"]["mode_label"] = mode_info["label"]
                feat["properties"]["minutes"] = minutes
                feat["properties"]["is_simulated"] = False
                if "area" in feat["properties"]:
                    feat["properties"]["area_sq_km"] = round(feat["properties"]["area"] / 1e6, 2)
        return data
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error querying OpenRouteService: {e}")


def compute_combined_bounding_box(isochrones: List[Dict[str, Any]]) -> Tuple[float, float, float, float]:
    """
    Computes (south, west, north, east) bounding box covering all isochrone features,
    with a 5% margin.
    """
    min_lat, max_lat = 90.0, -90.0
    min_lon, max_lon = 180.0, -180.0

    found_coords = False
    for iso_data in isochrones:
        for feat in iso_data.get("features", []):
            geom = feat.get("geometry", {})
            coords_list = []
            gtype = geom.get("type")
            if gtype == "Polygon":
                coords_list = geom.get("coordinates", [[]])[0]
            elif gtype == "MultiPolygon":
                for poly in geom.get("coordinates", []):
                    coords_list.extend(poly[0])

            for pt in coords_list:
                lon, lat = pt[0], pt[1]
                min_lon = min(min_lon, lon)
                max_lon = max(max_lon, lon)
                min_lat = min(min_lat, lat)
                max_lat = max(max_lat, lat)
                found_coords = True

    if not found_coords:
        return (0.0, 0.0, 0.0, 0.0)

    # Add 5% padding
    dlat = (max_lat - min_lat) * 0.05 or 0.01
    dlon = (max_lon - min_lon) * 0.05 or 0.01

    return (min_lat - dlat, min_lon - dlon, max_lat + dlat, max_lon + dlon)


# ---------------------------------------------------------------------------
# POI Retrieval via OpenStreetMap Overpass API
# ---------------------------------------------------------------------------

def build_overpass_query(
    bbox: Tuple[float, float, float, float],
    categories: List[str],
    custom_tags: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """
    Builds an optimized Overpass QL query string for the specified categories and bounding box.
    """
    south, west, north, east = bbox
    bbox_str = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"

    tag_filters = []
    for cat in categories:
        if cat in DEFAULT_CATEGORIES:
            for k, v in DEFAULT_CATEGORIES[cat]["tags"]:
                tag_filters.append((k, v, cat))

    if custom_tags:
        for k, v in custom_tags:
            tag_filters.append((k, v, f"Custom: {k}={v}"))

    statements = []
    for k, v, _ in tag_filters:
        statements.append(f'  node["{k}"="{v}"]({bbox_str});')
        statements.append(f'  way["{k}"="{v}"]({bbox_str});')
        statements.append(f'  relation["{k}"="{v}"]({bbox_str});')

    # If Apartment Buildings are selected, also query multi-family residential tags and named buildings
    if "Apartment Buildings" in categories:
        statements.append(f'  way["building"]["building:flats"]({bbox_str});')
        statements.append(f'  relation["building"]["building:flats"]({bbox_str});')
        statements.append(f'  node["building"]["name"~"Apartment|Apartments|Loft|Lofts|Flats|Residences|Condo|Condos|Suites",i]({bbox_str});')
        statements.append(f'  way["building"]["name"~"Apartment|Apartments|Loft|Lofts|Flats|Residences|Condo|Condos|Suites",i]({bbox_str});')
        statements.append(f'  relation["building"]["name"~"Apartment|Apartments|Loft|Lofts|Flats|Residences|Condo|Condos|Suites",i]({bbox_str});')

    combined_statements = "\n".join(statements)
    query = f"""[out:json][timeout:35];
(
{combined_statements}
);
out center tags;
"""
    return query


def fetch_pois(
    bbox: Tuple[float, float, float, float],
    categories: List[str],
    custom_tags: Optional[List[Tuple[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """
    Queries Overpass API endpoints with mirror failover to retrieve POIs within bounding box.
    """
    if not categories and not custom_tags:
        return []

    query = build_overpass_query(bbox, categories, custom_tags)

    # Build category lookup map for tag matching
    tag_to_category = {}
    for cat in categories:
        if cat in DEFAULT_CATEGORIES:
            for k, v in DEFAULT_CATEGORIES[cat]["tags"]:
                tag_to_category[(k, v)] = cat
    if custom_tags:
        for k, v in custom_tags:
            tag_to_category[(k, v)] = f"Custom: {k}={v}"

    last_error = None
    data = None

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(endpoint, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                break
            elif resp.status_code == 429:
                last_error = f"Overpass 429: Endpoint {endpoint} is busy."
                continue
            else:
                last_error = f"Overpass error {resp.status_code} from {endpoint}"
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            continue

    if data is None:
        raise RuntimeError(f"All Overpass API mirrors failed or timed out: {last_error}")

    elements = data.get("elements", [])
    pois = []
    seen_ids = set()

    for elem in elements:
        osm_id = f"{elem.get('type')}/{elem.get('id')}"
        if osm_id in seen_ids:
            continue
        seen_ids.add(osm_id)

        tags = elem.get("tags", {})
        # Extract coordinates (node has lat/lon; way/relation has center.lat/center.lon)
        lat = elem.get("lat") or elem.get("center", {}).get("lat")
        lon = elem.get("lon") or elem.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue

        # Match category from explicit tags
        matched_category = "Other"
        for (k, v), cat_name in tag_to_category.items():
            if tags.get(k) == v:
                matched_category = cat_name
                break

        # Secondary matching for apartments that might be tagged building=yes with apartment name
        if matched_category == "Other" and "Apartment Buildings" in categories and tags:
            bld = str(tags.get("building", "")).lower()
            res = str(tags.get("residential", "")).lower()
            amenity = str(tags.get("amenity", "")).lower()
            name_str = str(tags.get("name", "")).lower()

            apt_keywords = ("apartment", "apartments", "loft", "lofts", "flats", "residence", "residences", "condo", "condos", "suites")
            is_apt_name = any(kw in name_str for kw in apt_keywords)

            if (
                bld in ("apartments", "residential", "flats", "dormitory", "condominium", "yes") and (is_apt_name or "building:flats" in tags)
            ) or (
                res in ("apartments", "flats", "condominium")
            ) or (
                amenity == "student_accommodation"
            ):
                matched_category = "Apartment Buildings"

        # Discard untagged or non-matching features
        if matched_category == "Other":
            continue

        name = tags.get("name") or tags.get("brand") or f"Unnamed {matched_category}"

        pois.append({
            "osm_id": osm_id,
            "name": name,
            "category": matched_category,
            "lat": float(lat),
            "lon": float(lon),
            "tags": tags,
        })

    return pois


# ---------------------------------------------------------------------------
# Point-in-Polygon Spatial Filtering via Shapely
# ---------------------------------------------------------------------------

def filter_pois_in_polygons(
    isochrone_results: List[Dict[str, Any]],
    pois: List[Dict[str, Any]],
    center_lat: float,
    center_lon: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Performs Point-in-Polygon checks using Shapely.
    Associates each POI with all transit modes that can reach it.
    Returns:
      (filtered_pois, summary_statistics)
    """
    if not isochrone_results or not pois:
        return [], {"total": 0, "by_category": {}, "by_mode": {}}

    # Pre-parse and prepare Shapely polygons for high performance
    prepared_polygons = []
    for iso_data in isochrone_results:
        for feat in iso_data.get("features", []):
            mode_key = feat["properties"].get("mode", "unknown")
            mode_label = feat["properties"].get("mode_label", mode_key)
            geom_dict = feat.get("geometry")
            if geom_dict:
                shapely_geom = shape(geom_dict)
                prepared_polygons.append({
                    "mode_key": mode_key,
                    "mode_label": mode_label,
                    "shape": shapely_geom,
                    "prep": prep(shapely_geom),
                    "area_sq_km": feat["properties"].get("area_sq_km", 0),
                    "is_simulated": feat["properties"].get("is_simulated", False),
                })

    filtered_pois = []
    category_counts: Dict[str, int] = {}
    mode_counts: Dict[str, int] = {p["mode_label"]: 0 for p in prepared_polygons}

    for poi in pois:
        pt = Point(poi["lon"], poi["lat"])
        reaching_modes = []

        for p_item in prepared_polygons:
            if p_item["prep"].contains(pt):
                reaching_modes.append(p_item["mode_label"])
                mode_counts[p_item["mode_label"]] += 1

        if reaching_modes:
            dist_mi = haversine_distance_miles(center_lat, center_lon, poi["lat"], poi["lon"])
            dist_km = dist_mi * 1.60934

            poi_entry = dict(poi)
            poi_entry["reaching_modes"] = reaching_modes
            poi_entry["distance_mi"] = round(dist_mi, 2)
            poi_entry["distance_km"] = round(dist_km, 2)
            filtered_pois.append(poi_entry)

            cat = poi["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

    # Sort filtered POIs by proximity to center
    filtered_pois.sort(key=lambda p: p["distance_mi"])

    stats = {
        "total_pois": len(filtered_pois),
        "by_category": category_counts,
        "by_mode": mode_counts,
        "modes_analyzed": [p["mode_label"] for p in prepared_polygons],
        "areas_sq_km": {p["mode_label"]: p["area_sq_km"] for p in prepared_polygons},
    }

    return filtered_pois, stats


# ---------------------------------------------------------------------------
# Direct 1:1 Smooth Continuous Wheel Zoom Macro
# ---------------------------------------------------------------------------

class SmoothContinuousZoom(MacroElement):
    """
    Official Folium MacroElement injecting a direct 1:1 linear wheel zoom handler.
    Eliminates Leaflet's built-in debounced sigmoid acceleration which caused
    zooming to feel super slow at first then jump erratically ('bam it moves a lot').
    """
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function() {
            var map = {{ this._parent.get_name() }};
            if (!map) return;

            try {
                if (map.scrollWheelZoom && map.scrollWheelZoom.enabled()) {
                    map.scrollWheelZoom.disable();
                }
            } catch(e) {}

            var container = map.getContainer();
            if (!container || container._hasSmoothZoom) return;
            container._hasSmoothZoom = true;

            var pendingDelta = 0;
            var lastMousePoint = null;
            var ticking = false;

            function applyZoom() {
                ticking = false;
                if (pendingDelta === 0) return;

                var currentZoom = map.getZoom();
                var zoomChange = -pendingDelta * 0.0018;
                pendingDelta = 0;

                var minZ = map.getMinZoom();
                var maxZ = map.getMaxZoom();
                var newZoom = Math.max(minZ, Math.min(maxZ, currentZoom + zoomChange));

                if (Math.abs(newZoom - currentZoom) > 0.0001) {
                    var anchor = lastMousePoint || map.getSize().divideBy(2);
                    map.setZoomAround(anchor, newZoom, { animate: false });
                }
            }

            container.addEventListener('wheel', function(e) {
                e.preventDefault();
                e.stopPropagation();

                var delta = e.deltaY;
                if (e.deltaMode === 1) delta *= 33;
                else if (e.deltaMode === 2) delta *= 400;

                pendingDelta += delta;
                try {
                    lastMousePoint = map.mouseEventToContainerPoint(e);
                } catch(err) {
                    lastMousePoint = null;
                }

                if (!ticking) {
                    ticking = true;
                    requestAnimationFrame(applyZoom);
                }
            }, { passive: false, capture: true });
        })();
        {% endmacro %}
    """)


# ---------------------------------------------------------------------------
# Interactive Folium Map Builder
# ---------------------------------------------------------------------------

def build_folium_map(
    center_lat: float,
    center_lon: float,
    center_name: str,
    isochrone_results: List[Dict[str, Any]],
    filtered_pois: List[Dict[str, Any]],
    cluster_markers: bool = True,
) -> folium.Map:
    """
    Constructs an interactive Folium map with:
      - Center landmark pin
      - Multi-mode isochrone polygon layers
      - Categorized POI markers with custom icons & popups
      - LayerControl for toggling modes and POI categories
    """
    # Initialize Folium Map with hardware-accelerated canvas rendering
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=14,
        tiles=None,  # Custom tiles added below
        prefer_canvas=True,
        scroll_wheel_zoom=False,      # Disabled native debounced handler in favor of direct 1:1 linear zoom
        touch_zoom=True,              # Native pinch-to-zoom for touchscreens
        zoom_snap=0,                  # 0 completely disables discrete level snapping!
        zoom_delta=1.0,               # Clean 1-step zooming for + / - buttons
        control_scale=True,
    )

    # Base Layers: Fast, crisp CartoDB Voyager as default, plus standard OpenStreetMap
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        name="Voyager (Smooth & Fast)",
        subdomains="abcd",
        max_zoom=20,
        show=True,
        control=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap Standard",
        show=False,
        control=True,
    ).add_to(m)

    # 1. Add Center Pin
    center_html = f"""
    <div style="font-family:-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; min-width:200px;">
        <h4 style="margin:0 0 5px 0; color:#c0392b;">📍 Starting Location</h4>
        <p style="margin:0; font-size:13px;"><b>{center_name}</b></p>
        <p style="margin:4px 0 0 0; color:#7f8c8d; font-size:11px;">
            Lat: {center_lat:.5f}, Lon: {center_lon:.5f}
        </p>
    </div>
    """
    folium.Marker(
        [center_lat, center_lon],
        tooltip=f"Starting Point: {center_name}",
        popup=folium.Popup(center_html, max_width=300),
        icon=folium.Icon(color="red", icon="star", prefix="fa"),
    ).add_to(m)

    # 2. Add Isochrone Polygon Layers (sorted by mode speed/area so smaller polygons render on top)
    sorted_isochrones = sorted(
        isochrone_results,
        key=lambda iso: iso.get("features", [{}])[0].get("properties", {}).get("area_sq_km", 0),
        reverse=True,
    )

    for iso_data in sorted_isochrones:
        for feat in iso_data.get("features", []):
            mode_key = feat["properties"].get("mode", "driving-car")
            mode_info = TRANSIT_MODES.get(mode_key, TRANSIT_MODES["driving-car"])
            mode_label = feat["properties"].get("mode_label", mode_info["label"])
            minutes = feat["properties"].get("minutes", 10)
            area = feat["properties"].get("area_sq_km", "N/A")
            sim_badge = " (Simulated)" if feat["properties"].get("is_simulated") else ""

            layer_name = f"⏳ {mode_label} ({minutes}m, {area} km²){sim_badge}"
            fg_isochrone = folium.FeatureGroup(name=layer_name, show=True)

            def style_func(
                x,
                color=mode_info["color"],
                fill_color=mode_info["fill_color"],
                fill_opacity=mode_info["fill_opacity"],
            ):
                return {
                    "fillColor": fill_color,
                    "color": color,
                    "weight": 2.5,
                    "fillOpacity": fill_opacity,
                    "dashArray": "4, 4" if "Simulated" in layer_name else "1",
                }

            folium.GeoJson(
                feat,
                name=layer_name,
                style_function=style_func,
                tooltip=f"{mode_label}: {minutes} minutes travel time{sim_badge}",
            ).add_to(fg_isochrone)

            fg_isochrone.add_to(m)

    # 3. Add POI Markers grouped by Category with Color-Coded Building Clusters
    pois_by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for poi in filtered_pois:
        pois_by_cat.setdefault(poi["category"], []).append(poi)

    for cat_name, cat_items in pois_by_cat.items():
        cat_meta = DEFAULT_CATEGORIES.get(
            cat_name,
            {"icon": "map-marker", "color": "blue", "cluster_color": "#2980b9", "prefix": "fa"},
        )
        cluster_color = cat_meta.get("cluster_color", "#2980b9")
        layer_display_name = f"📌 {cat_name} ({len(cat_items)})"
        cat_group = folium.FeatureGroup(name=layer_display_name, show=True)

        if cluster_markers:
            # Custom cluster icon that color-codes by building type instead of count
            icon_create_func = f"""
            function(cluster) {{
                var count = cluster.getChildCount();
                var size = count < 10 ? 36 : (count < 100 ? 42 : 48);
                var fontSize = count < 100 ? '13px' : '11px';
                return new L.DivIcon({{
                    html: '<div style="' +
                          'background-color: {cluster_color}; ' +
                          'color: #ffffff; ' +
                          'width: ' + size + 'px; ' +
                          'height: ' + size + 'px; ' +
                          'line-height: ' + size + 'px; ' +
                          'border-radius: 50%; ' +
                          'text-align: center; ' +
                          'font-weight: 700; ' +
                          'font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; ' +
                          'font-size: ' + fontSize + '; ' +
                          'border: 3px solid rgba(255, 255, 255, 0.92); ' +
                          'box-shadow: 0 3px 10px rgba(0, 0, 0, 0.35); ' +
                          'display: flex; align-items: center; justify-content: center;' +
                          '">' + count + '</div>',
                    className: 'custom-building-cluster',
                    iconSize: new L.Point(size, size),
                    iconAnchor: new L.Point(size / 2, size / 2)
                }});
            }}
            """
            marker_container = MarkerCluster(icon_create_function=icon_create_func).add_to(cat_group)
        else:
            marker_container = cat_group

        for item in cat_items:
            modes_str = ", ".join(item.get("reaching_modes", []))
            osm_link = f"https://www.openstreetmap.org/{item['osm_id']}"

            # Accurate Google Maps URL (using coordinates to avoid keyword text-search mixups)
            gmaps_url = create_google_maps_url(item["name"], item["lat"], item["lon"], item.get("tags"))

            # Format optional street address from OSM tags
            tags = item.get("tags", {})
            addr_parts = []
            if tags.get("addr:housenumber"):
                addr_parts.append(str(tags["addr:housenumber"]))
            if tags.get("addr:street"):
                addr_parts.append(str(tags["addr:street"]))
            if tags.get("addr:city"):
                addr_parts.append(str(tags["addr:city"]))
            addr_html = ""
            if addr_parts:
                addr_html = f"""
                <tr>
                    <td style="color:#7f8c8d; padding:2px 0;">Address:</td>
                    <td style="text-align:right;">{' '.join(addr_parts)}</td>
                </tr>
                """

            # Rich popup card with Google Maps button
            popup_html = f"""
            <div style="font-family:-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; min-width:230px; font-size:12px;">
                <h4 style="margin:0 0 5px 0; color:#1a252f; font-size:14px; line-height:1.3;">{item['name']}</h4>
                <div style="margin-bottom:8px;">
                    <span style="background:{cluster_color}22; color:{cluster_color}; border:1px solid {cluster_color}55; padding:2px 8px; border-radius:4px; font-weight:700; font-size:11px;">
                        {item['category']}
                    </span>
                </div>
                <table style="width:100%; border-collapse:collapse; margin-bottom:8px; font-size:12px;">
                    <tr>
                        <td style="color:#7f8c8d; padding:2px 0;">Distance:</td>
                        <td style="text-align:right;"><b>{item.get('distance_mi', 'N/A')} mi</b> ({item.get('distance_km', 'N/A')} km)</td>
                    </tr>
                    <tr>
                        <td style="color:#7f8c8d; padding:2px 0;">Reachable by:</td>
                        <td style="text-align:right;"><b>{modes_str}</b></td>
                    </tr>
                    {addr_html}
                </table>
                <a href="{gmaps_url}" target="_blank" rel="noopener noreferrer" style="
                    display: block;
                    box-sizing: border-box;
                    text-align: center;
                    background-color: #1a73e8;
                    color: #ffffff !important;
                    padding: 8px 12px;
                    border-radius: 6px;
                    text-decoration: none;
                    font-weight: 600;
                    font-size: 12px;
                    margin-bottom: 6px;
                    box-shadow: 0 2px 4px rgba(26,115,232,0.3);
                ">
                    📍 Open in Google Maps ↗
                </a>
                <div style="text-align:center; font-size:11px;">
                    <a href="{osm_link}" target="_blank" rel="noopener noreferrer" style="color:#7f8c8d; text-decoration:underline;">
                        View on OpenStreetMap
                    </a>
                </div>
            </div>
            """

            folium.Marker(
                [item["lat"], item["lon"]],
                tooltip=f"{item['name']} ({item['category']})",
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.Icon(
                    color=cat_meta["color"],
                    icon=cat_meta["icon"],
                    prefix=cat_meta.get("prefix", "fa"),
                ),
            ).add_to(marker_container)

        cat_group.add_to(m)

    # 4. Add Folium Layer Control (allows toggling isochrones and POI categories)
    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    # 5. Automatically fit map bounds to the isochrone polygons
    bbox = compute_combined_bounding_box(isochrone_results)
    if bbox != (0.0, 0.0, 0.0, 0.0):
        m.fit_bounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]])

    # 6. Attach direct 1:1 linear wheel zoom handler
    SmoothContinuousZoom().add_to(m)

    return m


# ---------------------------------------------------------------------------
# Extensible Apartment Analytics Module (Future Integration Hook)
# ---------------------------------------------------------------------------

class ApartmentAnalyzer:
    """
    Extensible module for analyzing apartment buildings, unit counts, density,
    and housing trends within the reachable travel boundary.
    """

    @staticmethod
    def extract_apartment_features(pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extracts and enriches apartment-specific attributes from OSM tags."""
        apartments = []
        for poi in pois:
            if poi.get("category") == "Apartment Buildings":
                tags = poi.get("tags", {})
                gmaps_url = create_google_maps_url(poi["name"], poi["lat"], poi["lon"], tags)
                apartments.append({
                    "name": poi["name"],
                    "lat": poi["lat"],
                    "lon": poi["lon"],
                    "distance_mi": poi.get("distance_mi"),
                    "levels": tags.get("building:levels", "Unknown"),
                    "flats": tags.get("flats") or tags.get("building:flats") or "Unknown",
                    "operator": tags.get("operator", "Unknown"),
                    "street": tags.get("addr:street"),
                    "housenumber": tags.get("addr:housenumber"),
                    "postcode": tags.get("addr:postcode"),
                    "wheelchair": tags.get("wheelchair", "Unknown"),
                    "website": tags.get("website") or tags.get("contact:website"),
                    "google_maps": gmaps_url,
                })
        return apartments

    @staticmethod
    def summarize_apartments(apartments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculates housing density and proximity metrics."""
        if not apartments:
            return {"count": 0, "avg_distance_mi": 0.0, "has_website_count": 0}
        
        distances = [a["distance_mi"] for a in apartments if a.get("distance_mi") is not None]
        avg_dist = sum(distances) / len(distances) if distances else 0.0
        web_count = sum(1 for a in apartments if a.get("website"))

        return {
            "count": len(apartments),
            "avg_distance_mi": round(avg_dist, 2),
            "has_website_count": web_count,
        }
