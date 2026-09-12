"""
Streamlit Web Application: Isochrone Map Maker & Spatial POI Analyzer
---------------------------------------------------------------------
Interactive dashboard to generate travel-time isochrones, overlay multi-modal
transit boundaries, query OpenStreetMap POIs, and analyze reachable amenities.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import List, Tuple
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

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

# ---------------------------------------------------------------------------
# Page Configuration & Styling
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Isochrone Map Maker",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 4px solid #3498db;
        margin-bottom: 10px;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: Controls & Settings
# ---------------------------------------------------------------------------
st.sidebar.title("🗺️ Isochrone Map Maker")
st.sidebar.caption("Analyze what is reachable within an X-minute commute")

# 1. API Key & Instructions Expander
with st.sidebar.expander("ℹ️ OpenRouteService API Key (Free)", expanded=False):
    st.markdown(
        """
        **How to get a free API key:**
        1. Go to [openrouteservice.org/sign-up](https://openrouteservice.org/sign-up)
        2. Create a free account (takes ~1 minute).
        3. Navigate to **Dashboard** -> **API Keys**.
        4. Select token type **Free** and copy your key.
        5. Paste it below or save it as `ORS_API_KEY` in a `.env` file.
        
        *ORS provides **2,000 free requests per day**.*
        """
    )

env_api_key = os.environ.get("ORS_API_KEY", "")
api_key_input = st.sidebar.text_input(
    "ORS API Key",
    value=env_api_key,
    type="password",
    help="Paste your free OpenRouteService API token here.",
)

demo_mode = st.sidebar.checkbox(
    "Use Simulated / Demo Mode (No API key needed)",
    value=(not bool(api_key_input)),
    help="Generates simulated realistic road-network travel isochrones without calling external routing APIs.",
)

effective_api_key = None if demo_mode else api_key_input

st.sidebar.divider()

# 2. Location Input
st.sidebar.subheader("📍 Target Center Location")
input_mode = st.sidebar.radio("Location Input Method", ["Address / Landmark", "Coordinates (Lat/Lon)"], horizontal=True)

target_lat, target_lon, target_name = 40.7484, -73.9857, "Empire State Building, NY"

if input_mode == "Address / Landmark":
    address_query = st.sidebar.text_input(
        "Street Address or Landmark",
        value="Empire State Building, New York",
        help="Enter any place, landmark, or full street address anywhere in the world.",
    )
else:
    col_lat, col_lon = st.sidebar.columns(2)
    with col_lat:
        target_lat = st.number_input("Latitude", value=40.7484, format="%.5f")
    with col_lon:
        target_lon = st.number_input("Longitude", value=-73.9857, format="%.5f")
    target_name = st.sidebar.text_input("Location Name", value="Custom Coordinates")

st.sidebar.divider()

# 3. Travel Time & Transit Modes (Multi-Mode Overlay)
st.sidebar.subheader("⏱️ Commute & Transit Modes")

travel_minutes = st.sidebar.slider(
    "Travel Time (Minutes)",
    min_value=3,
    max_value=60,
    value=15,
    step=1,
    help="Maximum travel time for the isochrone boundary.",
)

selected_mode_keys = st.sidebar.multiselect(
    "Overlay Transit Modes",
    options=list(TRANSIT_MODES.keys()),
    default=["driving-car", "cycling-regular", "foot-walking"],
    format_func=lambda k: TRANSIT_MODES[k]["label"],
    help="Select one or multiple transit modes to overlay on the map for side-by-side comparison.",
)

st.sidebar.divider()

# 4. Points of Interest (POIs) Categories
st.sidebar.subheader("🏢 Points of Interest to Check")

preset_categories = list(DEFAULT_CATEGORIES.keys())
selected_categories = st.sidebar.multiselect(
    "Select Amenities & Buildings",
    options=preset_categories,
    default=["Coffee & Cafes", "Apartment Buildings", "Gyms & Fitness"],
    help="OpenStreetMap amenities and buildings to query and verify within the travel border.",
)

with st.sidebar.expander("➕ Add Custom OSM Tag", expanded=False):
    custom_tag_key = st.text_input("Key (e.g. shop, amenity)", value="")
    custom_tag_val = st.text_input("Value (e.g. bakery, pharmacy)", value="")
    custom_tags: List[Tuple[str, str]] = []
    if custom_tag_key.strip() and custom_tag_val.strip():
        custom_tags.append((custom_tag_key.strip(), custom_tag_val.strip()))

cluster_option = st.sidebar.checkbox("Cluster Map Markers", value=True, help="Groups nearby markers to avoid visual clutter.")

# Action Button
run_search = st.sidebar.button("🚀 Generate Isochrone & Count Amenities", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Main Panel
# ---------------------------------------------------------------------------
st.title("🗺️ Isochrone Map & Spatial Amenity Checker")
st.markdown(
    "Determine reachable commute zones and accurately count coffee shops, apartments, gyms, "
    "and services within your specified travel time."
)

if run_search or "analysis_data" in st.session_state:
    if run_search:
        if not selected_mode_keys:
            st.error("Please select at least one transit mode (Driving, Cycling, or Walking).")
            st.stop()

        if not selected_categories and not custom_tags:
            st.error("Please select at least one POI category or provide a custom OSM tag.")
            st.stop()

        with st.spinner("Geocoding target location..."):
            try:
                if input_mode == "Address / Landmark":
                    geo = geocode_location(address_query)
                    target_lat, target_lon = geo["lat"], geo["lon"]
                    target_name = geo["display_name"]
            except Exception as e:
                st.error(f"Geocoding Error: {e}")
                st.stop()

        isochrone_results = []
        with st.spinner(f"Generating travel isochrones for {travel_minutes} minutes..."):
            for m_key in selected_mode_keys:
                try:
                    iso = get_isochrone(
                        lat=target_lat,
                        lon=target_lon,
                        mode_key=m_key,
                        minutes=travel_minutes,
                        api_key=effective_api_key,
                        force_simulated=demo_mode,
                    )
                    isochrone_results.append(iso)
                except Exception as e:
                    st.warning(f"Could not fetch {TRANSIT_MODES[m_key]['label']} isochrone: {e}")

        if not isochrone_results:
            st.error("Failed to generate any isochrone boundaries. Please check your API key or use Demo mode.")
            st.stop()

        with st.spinner("Querying OpenStreetMap Overpass database for POIs..."):
            bbox = compute_combined_bounding_box(isochrone_results)
            try:
                raw_pois = fetch_pois(bbox, selected_categories, custom_tags)
            except Exception as e:
                st.error(f"Overpass API error: {e}. Please try again in a few moments.")
                st.stop()

        with st.spinner("Performing spatial point-in-polygon filtering..."):
            filtered_pois, stats = filter_pois_in_polygons(
                isochrone_results, raw_pois, target_lat, target_lon
            )

        # Save to session state
        st.session_state["analysis_data"] = {
            "center_lat": target_lat,
            "center_lon": target_lon,
            "center_name": target_name,
            "isochrone_results": isochrone_results,
            "filtered_pois": filtered_pois,
            "stats": stats,
            "cluster_markers": cluster_option,
        }

    # Load from session state
    data = st.session_state["analysis_data"]
    center_lat = data["center_lat"]
    center_lon = data["center_lon"]
    center_name = data["center_name"]
    isochrone_results = data["isochrone_results"]
    filtered_pois = data["filtered_pois"]
    stats = data["stats"]
    cluster_markers = data.get("cluster_markers", True)

    # Status Banner
    is_any_sim = any(
        feat.get("properties", {}).get("is_simulated", False)
        for iso in isochrone_results
        for feat in iso.get("features", [])
    )
    if is_any_sim:
        st.info("ℹ️ Displaying **Simulated Isochrones** (ideal for testing without consuming API quota). Enter an ORS API key in the sidebar for real-world road network calculations.")

    # Location Info
    st.markdown(f"**📍 Center Location:** `{center_name}` *(Lat: {center_lat:.4f}, Lon: {center_lon:.4f})*")

    # Metrics Row
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric("Total Reachable POIs", stats["total_pois"])
    with m_col2:
        st.metric("Travel Time Limit", f"{travel_minutes} mins")
    with m_col3:
        modes_disp = ", ".join([TRANSIT_MODES[k]["label"].split()[0] for k in selected_mode_keys])
        st.metric("Modes Active", modes_disp)
    with m_col4:
        top_cat = max(stats["by_category"].items(), key=lambda x: x[1])[0] if stats["by_category"] else "N/A"
        st.metric("Top Amenity", top_cat)

    # Tabs for Map, Breakdown, Data Table, and Future Apartment Search Tool
    tab_map, tab_stats, tab_table, tab_apartments = st.tabs([
        "🗺️ Interactive Map",
        "📊 Category Breakdown",
        "📋 Filtered POI Directory",
        "🏢 Apartment Hunter & Insights",
    ])

    with tab_map:
        st.markdown(
            "Use the **Layer Control in the top-right corner** of the map to toggle transit modes and POI categories on/off."
        )
        folium_map = build_folium_map(
            center_lat=center_lat,
            center_lon=center_lon,
            center_name=center_name,
            isochrone_results=isochrone_results,
            filtered_pois=filtered_pois,
            cluster_markers=cluster_markers,
        )
        map_html = folium_map.get_root().render()
        components.html(map_html, height=640, scrolling=False)

        col_dl, _ = st.columns([2, 5])
        with col_dl:
            st.download_button(
                label="📥 Download Map as Standalone HTML",
                data=map_html,
                file_name=f"isochrone_map_{travel_minutes}min.html",
                mime="text/html",
                help="Save this interactive map to open in any web browser or share.",
            )

    with tab_stats:
        st.subheader("Amenity Counts Inside Isochrone Boundary")
        col_c1, col_c2 = st.columns(2)

        with col_c1:
            st.markdown("#### Count by Category")
            if stats["by_category"]:
                cat_df = pd.DataFrame(
                    list(stats["by_category"].items()),
                    columns=["Category", "Count"],
                ).sort_values(by="Count", ascending=False)
                st.dataframe(cat_df, use_container_width=True, hide_index=True)
                st.bar_chart(cat_df.set_index("Category"))
            else:
                st.write("No matching POIs found within this travel boundary.")

        with col_c2:
            st.markdown("#### Reachable by Transit Mode")
            mode_df = pd.DataFrame(
                list(stats["by_mode"].items()),
                columns=["Transit Mode", "Reachable Count"],
            )
            st.dataframe(mode_df, use_container_width=True, hide_index=True)

            st.markdown("#### Isochrone Coverage Areas")
            area_data = [
                {"Transit Mode": mode, "Area (sq km)": area}
                for mode, area in stats.get("areas_sq_km", {}).items()
            ]
            if area_data:
                st.dataframe(pd.DataFrame(area_data), use_container_width=True, hide_index=True)

    with tab_table:
        st.subheader("Reachable Amenities List")
        if filtered_pois:
            table_records = []
            for p in filtered_pois:
                clean_name = p["name"].replace('"', "").replace("'", "")
                gmaps_query = urllib.parse.quote(f"{clean_name} {p['lat']:.5f},{p['lon']:.5f}")
                gmaps_url = f"https://www.google.com/maps/search/?api=1&query={gmaps_query}"
                table_records.append({
                    "Name": p["name"],
                    "Category": p["category"],
                    "Distance (mi)": p.get("distance_mi"),
                    "Distance (km)": p.get("distance_km"),
                    "Reachable By": ", ".join(p.get("reaching_modes", [])),
                    "Google Maps": gmaps_url,
                    "Latitude": round(p["lat"], 5),
                    "Longitude": round(p["lon"], 5),
                })
            df = pd.DataFrame(table_records)

            search_filter = st.text_input("🔍 Search within results by name", "")
            if search_filter:
                df = df[df["Name"].str.contains(search_filter, case=False, na=False)]

            st.dataframe(
                df,
                column_config={
                    "Google Maps": st.column_config.LinkColumn("Google Maps", display_text="Open in Maps ↗"),
                },
                use_container_width=True,
                hide_index=True,
            )

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download POI Results as CSV",
                data=csv,
                file_name=f"isochrone_pois_{travel_minutes}min.csv",
                mime="text/csv",
            )
        else:
            st.info("No POIs found inside this travel boundary. Try expanding the travel time slider.")

    with tab_apartments:
        st.subheader("🏢 Apartment Hunter & Residential Trends")
        st.markdown(
            """
            Analyze apartment complexes and residential buildings reachable within your commute.
            *This module is designed for future extension with rental pricing, vacancy rates, and market trend tracking.*
            """
        )

        apts = ApartmentAnalyzer.extract_apartment_features(filtered_pois)
        apt_summary = ApartmentAnalyzer.summarize_apartments(apts)

        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            st.metric("Apartment Buildings Found", apt_summary["count"])
        with col_a2:
            st.metric("Avg Distance to Center", f"{apt_summary['avg_distance_mi']} mi")
        with col_a3:
            st.metric("Properties with Website", apt_summary["has_website_count"])

        if apts:
            st.markdown("#### Reachable Apartment Buildings")
            apt_df = pd.DataFrame(apts)
            display_cols = ["name", "distance_mi", "levels", "flats", "street", "housenumber", "operator", "google_maps", "website"]
            available_cols = [c for c in display_cols if c in apt_df.columns]
            st.dataframe(
                apt_df[available_cols].rename(columns={
                    "name": "Building Name",
                    "distance_mi": "Distance (mi)",
                    "levels": "Floors",
                    "flats": "Units",
                    "street": "Street",
                    "housenumber": "No.",
                    "operator": "Management",
                    "google_maps": "Google Maps",
                    "website": "Website",
                }),
                column_config={
                    "Google Maps": st.column_config.LinkColumn("Google Maps", display_text="Open in Maps ↗"),
                    "Website": st.column_config.LinkColumn("Website", display_text="Visit Site ↗"),
                },
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info(
                "No apartment buildings tagged in OpenStreetMap were found within the current travel boundary. "
                "Make sure 'Apartment Buildings' is checked in the sidebar or try increasing the travel time."
            )

        st.info(
            "💡 **Future Feature Roadmap:**\n"
            "- Integration with rental listing APIs / scrapers for median rent by transit time\n"
            "- Price per square foot heatmaps along transit corridors\n"
            "- Walk Score and Transit Score integration per apartment building"
        )

else:
    # Initial landing screen guidance
    st.info("👈 Configure your location, transit modes, and travel time in the sidebar, then click **'Generate Isochrone & Count Amenities'**.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            """
            ### 🚗 Multi-Modal Isochrones
            Compare driving, walking, and cycling reachable polygons on a single map to visualize trade-offs.
            """
        )
    with col2:
        st.markdown(
            """
            ### ☕ Accurate POI Counts
            Use OpenStreetMap's Overpass database and Shapely point-in-polygon math to verify what's strictly inside the commute boundary.
            """
        )
    with col3:
        st.markdown(
            """
            ### 🏢 Apartment Analytics
            Inspect residential buildings and explore potential housing options within your target commute time.
            """
        )

