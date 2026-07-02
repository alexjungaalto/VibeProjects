# 🏗️ Verbaut — Built-up Area Animation for Austria

> **Verbaut** (German for "built-up") animates the evolution of building footprint coverage in Austria using real OSM data. See how Vienna's built-up area grew over 70 years — from a YouTube Short to a full landscape animation.

---

## 📦 Project Structure

```
Verbaut/
├── verbaut_short.py          ← YouTube Short generator (9:16, 1955–2026, ~30s)
├── verbaut_boeheimkirchen.py ← Böheimkirchen rural-village Short (9:16, 1955–2026)
├── verbaut_animation.py      ← Landscape animation (16:9, 2008–2026)
├── austria_bauflaeche.py     ← Original sealed-surface estimator (static analysis)
├── README.md
├── .gitignore
├── LICENSE
├── data/                     ← Cached data (*.gpkg: DKM Nutzungsflächen,
│   │                            OSM roads/railways for cartography)
│   └── gwr/                  ← Statistik Austria GWR Bauperiode CSV
├── cache/                    ← Overpass API response cache
└── output/                   ← Generated videos, frames, reports
    ├── verbaut_vienna_10fps.mp4       ← Landscape animation
    ├── verbaut_growth.png             ← Growth chart
    ├── verbaut_report.json            ← Per-year statistics
    ├── frames/                        ← Individual frames
    └── shorts/                        ← YouTube Short output
        ├── verbaut_wien_70yrs.mp4     ← Vienna Short (9:16, 32s)
        ├── verbaut_boeheimkirchen_70yrs.mp4       ← full municipality
        ├── verbaut_boeheimkirchen_core_70yrs.mp4  ← village-core close-up
        ├── frames/  frames_bhmk/  frames_bhmk_core/
        └── short_report.json  bhmk_report.json  bhmk_core_report.json
```

---

## 🎬 YouTube Short — 70 Years of Vienna

```
python verbaut_short.py
```

Output: `output/shorts/verbaut_wien_70yrs.mp4`

- **32 seconds**, 9:16 vertical (YouTube Short / TikTok / Reels)
- **72 frames** (1955 → 2026)
- Shows Vienna's building footprint growing from **34.7 km² → 58.1 km²**
- Dark green background, red built-up overlay

---

## 🏡 Böheimkirchen Demo — 70 Years of a Rural Village

```
python verbaut_boeheimkirchen.py                      # full municipality (8 m grid)
python verbaut_boeheimkirchen.py --zoom-km 2.4 --grid 4   # village core close-up
```

Output: `output/shorts/verbaut_boeheimkirchen_70yrs.mp4` (full) and
`output/shorts/verbaut_boeheimkirchen_core_70yrs.mp4` (core close-up),
each **~9 seconds** (intro 1.5 s → one year per ~0.08 s → outro 2 s)

`--zoom-km` sets the view width in km around the village centre (the map
zooms; the km²/% stats still cover the whole municipality). Use a finer
`--grid` when zoomed so individual houses render crisply.

- **~9 seconds**, 9:16 vertical
- **72 frames** (1955 → 2026)
- Shows Böheimkirchen's building area growing from **0.20 km² → 0.73 km²** (0.44 % → 1.60 % of the 45.5 km² municipality)
- **Building geometry from the cadastre**: the animated buildings are the surveyed *Gebäude* Nutzungsflächen (NS 41) of the **Digitale Katastralmappe (DKM)** — the geometric counterpart of the Grundbuch — fetched per Katastralgemeinde (all 21 KGs of the municipality) from the BEV Niederösterreich snapshot via HTTP range requests (a few MB instead of the 3.3 GB state file). Kataster © BEV, CC BY 4.0, Stichtag 2026-04-01.
- Uses a **growth curve built from Statistik Austria's GWR (Gebäude- und Wohnungsregister)** — the federal building register — which counts buildings per **Bauperiode** (construction period) for Böheimkirchen. The 2025-01-01 extract is downloaded from statistik.at and cached in `data/gwr/`. The per-period counts are turned into a cumulative year-by-year curve by linear interpolation between period endpoints, so the animation follows the **documented construction history** of the municipality rather than an assumed sigmoid. The 27 buildings with unknown period are distributed proportionally.
- **White map background** with cartographic overlays (clipped to the municipal boundary):
  - 🛣️ **A1 Westautobahn** (blue) and **B1 Bundesstraße** (orange) with white casing
  - Secondary/tertiary roads in light grey
  - 🚂 **Westbahn / Neue Westbahn** railway (dark line on white casing)
  - 📍 Place-name labels: **Böheimkirchen**, **Mechters**, **Schildberg**, **Furth**
- Rendered on an **8 m grid**; each built cell is drawn with a 1-cell halo and a minimum opacity so single farmhouses stay visible at phone-screen scale
- **Sealed-surface layer** (grey, constant across frames), also from the DKM: the *measured* cadastral Nutzungsflächen for **Parkplätze (NS 42)**, **Gebäudenebenflächen/befestigt (NS 83)**, **Schienenverkehrsanlagen (NS 92)**, and **Straßenverkehrsanlagen (NS 95)** — no assumed road widths. *Betriebsflächen* (NS 63, 0.63 km²) are excluded as only partly sealed. The cadastre has no historical geometry, so the grey layer shows **today's extent in every frame**; only the buildings animate. Result: **5.9 % of the municipality is sealed today** (2.69 km² = 0.73 km² buildings + 1.96 km² roads/rail/parking/paved) vs. 1.6 % from buildings alone. For comparison, an earlier OSM-based estimate (road centerlines buffered by assumed pavement widths) gave only 2.9 % — the cadastral road parcels are nearly 3× the buffered estimate. Unpaved `track`/`path` ways are excluded unless tagged with a paved surface, and — unlike `austria_bauflaeche.py` — `landuse=residential` is not counted (at village scale it is mostly unsealed gardens; buildings are counted separately). OSM has no historical road data, so this layer shows **today's extent in every frame**; only the buildings animate. Result: **~2.9 % of the municipality is sealed today** (1.32 km² dissolved: 0.79 km² buildings + 0.65 km² roads/parking/landuse, minus overlaps) vs. 1.74 % from buildings alone.

| Year | Cumulative fraction | Building footprint | Built-up ratio |
|------|-------------------|-------------------|----------------|
| **1955** | 26 % | 0.20 km² | 0.44 % |
| **1975** | 44 % | 0.32 km² | 0.70 % |
| **1995** | 65 % | 0.47 km² | 1.04 % |
| **2015** | 90 % | 0.66 km² | 1.46 % |
| **2026** | 100 % | 0.73 km² | 1.60 % |

---

### How it works

| Step | What |
|------|------|
| **1. Load** | Building geometry: OSM footprints for Vienna (250 k), BEV DKM cadastral *Gebäude* areas for Böheimkirchen (~3.3 k); cached locally |
| **2. Date** | Assign each building a year via random sampling against the growth curve (GWR-based for Böheimkirchen, researched anchors for Vienna) |
| **3. Raster** | Rasterise all buildings onto a grid (12 m Vienna, 8 m Böheimkirchen) in a single pass (year + coverage arrays) |
| **4. Frame** | Each frame = `np.where(year_raster ≤ year, area_raster, 0)` → direct RGB compositing |
| **5. Video** | Compile 72 frames with pacing (intro 4s → middle → outro 5s) |

### Historical growth model

Vienna is a mature city — the Ringstraße was built 1860–1900, post-war reconstruction was done by the mid-1950s.

| Year | Cumulative fraction | Building footprint | Source |
|------|-------------------|-------------------|--------|
| **1955** | 60 % | 34.7 km² | Post-war city, mostly rebuilt |
| **1975** | 72 % | 41.9 km² | Suburban expansion |
| **1995** | 85 % | 49.3 km² | Infill development |
| **2015** | 95 % | 55.1 km² | Aspern Seestadt begins |
| **2026** | 100 % | 58.1 km² | Current state |

---

## 🖥️ Landscape Animation — 2008–2026

```
python verbaut_animation.py
python verbaut_animation.py --region "St. Pölten, Austria"
python verbaut_animation.py --region "Wien" --fps 12 --grid 15
```

Output: `output/verbaut_<region>_<fps>fps.mp4`

- **19 frames** (2008–2026), landscape 16:9
- Shows the rapid OSM mapping of Austrian buildings (BEV cadastre imports in 2015, 2018, 2021)

---

## 📊 Static Analysis

```
python austria_bauflaeche.py --state wien
python austria_bauflaeche.py --all-states
```

The original sealed-surface estimator analyzes **all sealed surfaces** (buildings + roads + parking + landuse). According to its analysis:

| State | Sealed area | Ratio |
|-------|-------------|-------|
| **Wien** | 194.1 km² | **46.8 %** |
| **Vorarlberg** | 146.2 km² | 5.6 % |
| **St. Pölten** | 25.4 km² | 23.4 % |

---

## 📋 Requirements

```bash
pip install osmnx geopandas matplotlib numpy shapely requests pillow
```

For video compilation: `ffmpeg` must be available on your PATH.

OSMnx downloads data from the OpenStreetMap Overpass API — an internet connection is required for the first run (data is then cached locally).

---

## 🧠 Data & Limitations

- **Building footprints only** (Vienna short & landscape animation): those animations show building coverage (14 % of Vienna), not total sealed surface (46.8 %, which includes roads, parking, etc.). The Böheimkirchen short additionally shows a grey sealed-surface layer, but as a **present-day constant** — road/parking growth over time is not animated because no historical geometry source exists for it.
- **Cadastral "sealed" is a use classification, not a pavement survey**: the DKM Nutzungsflächen classify parcels by *use*. Straßenverkehrsanlagen parcels include some gravel rural lanes (overstating sealing), while the excluded Betriebsflächen (0.63 km²) are partly paved (understating it). The 5.9 % is the cadastral *Bau- und Verkehrsfläche* share — the best available measured proxy for soil sealing at municipal scale, sitting between the OSM lower bound (2.9 %) and land-take totals.
- **Year assignment**: Individual building ages are unknown — years are statistically sampled to match the aggregate growth curve. The growth pattern looks realistic but individual buildings may be misdated.
- **OSM completeness**: OSM building coverage in Austria is excellent (>95 % for urban areas), but small structures (sheds, garden huts) may be over-represented.
- **Raster resolution**: grid cells (12 m Vienna, 8 m Böheimkirchen) mean very small buildings (<~50 m²) may not be individually visible; the Böheimkirchen renderer dilates built cells by one cell for visibility, so red pixels slightly overstate footprint extent (the km²/% numbers are computed from the true polygon areas, not the pixels).

---

## 📄 License

**MIT** — Free to use, modify, and share.

Data from OpenStreetMap is © OpenStreetMap contributors (ODbL).

---

*Made with ❤️ for the VibeProjects community.*
