# 🗺️ Isochrone Map Maker & Spatial Amenity Checker

An interactive geospatial application that generates travel-time **isochrones** (driving, walking, biking) around any location, queries OpenStreetMap's Overpass database for points of interest (coffee shops, apartments, gyms, restaurants, supermarkets, etc.), filters them using spatial point-in-polygon geometry checks, and displays an interactive map with breakdown statistics.

---

## ✨ Features

- **Multi-Modal Travel Isochrones**:
  - Compare **Driving** 🚗, **Cycling** 🚲, and **Walking** 🚶 boundaries on the exact same map with customizable commute times (5–60 minutes).
  - Toggle layers individually via Leaflet/Folium layer controls.
- **Accurate Point-in-Polygon (PIP) Intersection**:
  - Leverages `shapely` prepared geometries to accurately filter points strictly inside the polygon boundary.
- **Rich Point of Interest (POI) Database**:
  - Direct integration with OpenStreetMap via the **Overpass API** (no API key required).
  - Pre-configured categories: Coffee & Cafes, Apartment Buildings, Gyms & Fitness Centers, Supermarkets & Groceries, Restaurants, Bars & Pubs, Parks, Transit Stops, and Schools.
  - Support for **custom OSM key/value tags** (e.g., `shop=bakery`).
- **Interactive Web App & Headless CLI**:
  - **Streamlit Web UI** (`app.py`): Search locations by name or coordinates, adjust sliders, view live interactive maps with marker clustering, and export results to CSV.
  - **Command-Line Interface** (`cli.py`): Run automated queries from your terminal and export standalone HTML maps.
- **OpenRouteService + Simulated Demo Mode**:
  - Uses OpenRouteService (ORS) API for real-world road network isochrones (2,000 free requests/day).
  - Includes a built-in **Simulated/Demo mode** that works immediately without requiring an API key.
- **Extensible Apartment Analytics Architecture**:
  - Dedicated module (`ApartmentAnalyzer`) extracting building levels, unit counts, street addresses, and website links for reachable residential buildings, architected for future rental price trends integration.

---

## 🏗️ Architecture & Pipeline

The system executes in four distinct stages:

```
┌────────────────────────┐
│ 1. Geocoding & Input   │ ──> OSM Nominatim converts address into (Lat, Lon)
└───────────┬────────────┘
            │
┌───────────▼────────────┐
│ 2. Isochrone Polygons  │ ──> ORS API (or simulated road expansion) computes 
└───────────┬────────────┘     travel boundaries for Driving, Biking, Walking
            │
┌───────────▼────────────┐
│ 3. Overpass POI Fetch  │ ──> OSM Overpass API fetches raw amenities within the 
└───────────┬────────────┘     combined bounding box
            │
┌───────────▼────────────┐
│ 4. Spatial PIP Check   │ ──> Shapely filters points strictly inside each isochrone 
└───────────┬────────────┘     and calculates distance & reachable modes
            │
┌───────────▼────────────┐
│ 5. Map & Analytics     │ ──> Folium renders interactive Leaflet map with custom icons,
└────────────────────────┘     clustering, layers, and Streamlit summary stats
```

---

## 🚀 Quick Start

### 1. Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/cegly2444/Iso-Chrome-map-maker.git
cd "Iso-Chrome map maker"
pip install -r requirements.txt
```

### 2. Optional: OpenRouteService API Key

OpenRouteService provides a generous **free tier (2,000 requests/day)**.
1. Sign up for free at [openrouteservice.org/sign-up](https://openrouteservice.org/sign-up).
2. Go to **Dashboard** -> **API Keys** -> Request a **Free** key.
3. You can:
   - Paste it directly into the web UI sidebar, OR
   - Create a `.env` file from `.env.example`:
     ```bash
     cp .env.example .env
     ```
     And add your key:
     ```env
     ORS_API_KEY=your_actual_key_here
     ```

*(If you don't have an API key, the app runs out-of-the-box using built-in Simulated Isochrone Mode!)*

---

## 💻 Usage

### Option A: Interactive Web UI (Recommended)

Launch the Streamlit app:

```bash
streamlit run app.py
```

1. Enter a street address or landmark (e.g., `Empire State Building, New York` or `Pike Place Market, Seattle`).
2. Adjust the commute time slider (e.g., `15 minutes`).
3. Select transit modes to overlay (`Driving`, `Cycling`, `Walking`).
4. Select amenity categories to query (`Coffee & Cafes`, `Apartments`, `Gyms`, etc.).
5. Click **"🚀 Generate Isochrone & Count Amenities"**.
6. Explore the interactive map, inspect the category breakdown, download the CSV report, or check the **Apartment Hunter** tab!

### Option B: Command-Line Interface (CLI)

Run a headless spatial search and save an interactive HTML map:

```bash
# Basic 15-minute commute check in Seattle
python cli.py --address "Space Needle, Seattle" --time 15 --modes driving,cycling --categories cafe,gym

# Output will save to isochrone_map.html
```

#### CLI Options:
| Flag | Description | Default |
|---|---|---|
| `--address`, `-a` | Target address or landmark | `"Empire State Building, New York"` |
| `--lat`, `--lon` | Manual latitude & longitude override | `None` |
| `--time`, `-t` | Travel time in minutes | `15` |
| `--modes`, `-m` | Comma-separated transit modes | `driving,cycling,walking` |
| `--categories`, `-c` | Comma-separated POI categories | `Coffee & Cafes,Apartment Buildings,Gyms & Fitness` |
| `--demo` | Force simulated isochrone mode | `False` |
| `--output`, `-o` | Output HTML map filename | `isochrone_map.html` |
| `--no-cluster` | Disable map marker clustering | `False` |

---

## 🧪 Running Tests

Run the built-in test suite to verify geocoding, isochrone calculations, and spatial intersection:

```bash
python test_analyzer.py
```

---

## 🔮 Future Roadmap (Apartment Hunter Tool)

The project includes an extensible `ApartmentAnalyzer` engine designed to support:
- [ ] Integration with rental listing APIs and scrapers to track median rent by commute time.
- [ ] Price per square foot heatmaps across transit corridors.
- [ ] Walk Score, Transit Score, and Bike Score overlays per apartment complex.
- [ ] Multi-center comparisons (e.g., find apartments reachable within 20 mins of *both* Partner A's office and Partner B's office).

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
