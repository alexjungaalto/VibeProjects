# 🏗️ Verbaut — Built-up Area Animation for Austria

> **Verbaut** (German for "built-up") animates the evolution of building footprint coverage in Austria using real OSM data. See how Vienna's built-up area grew over 70 years — from a YouTube Short to a full landscape animation.

---

## 📦 Project Structure

```
Verbaut/
├── verbaut_short.py          ← YouTube Short generator (9:16, 1955–2026, ~30s)
├── verbaut_animation.py      ← Landscape animation (16:9, 2008–2026)
├── austria_bauflaeche.py     ← Original sealed-surface estimator (static analysis)
├── README.md
├── .gitignore
├── LICENSE
├── data/                     ← Cached OSM building footprints (*.gpkg)
├── cache/                    ← Overpass API response cache
└── output/                   ← Generated videos, frames, reports
    ├── verbaut_vienna_10fps.mp4       ← Landscape animation
    ├── verbaut_vienna_<fps>fps.mp4
    ├── verbaut_growth.png             ← Growth chart
    ├── verbaut_report.json            ← Per-year statistics
    ├── frames/                        ← Individual frames
    └── shorts/                        ← YouTube Short output
        ├── verbaut_wien_70yrs.mp4     ← Short (9:16, 32s)
        ├── frames/
        └── short_report.json
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

### How it works

| Step | What |
|------|------|
| **1. Load** | Download 250 k building footprints from OSM (cached locally) |
| **2. Date** | Assign each building a year via random sampling against a researched growth curve |
| **3. Raster** | Rasterise all buildings ONTO a 12 m grid in a single pass (year + coverage arrays) |
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

- **Building footprints only**: The animations show building coverage (14 % of Vienna), not total sealed surface (46.8 %, which includes roads, parking, etc.).
- **Year assignment**: Individual building ages are unknown — years are statistically sampled to match the aggregate growth curve. The growth pattern looks realistic but individual buildings may be misdated.
- **OSM completeness**: OSM building coverage in Austria is excellent (>95 % for urban areas), but small structures (sheds, garden huts) may be over-represented.
- **Raster resolution**: 12 m grid cells mean very small buildings (<~50 m²) may not be individually visible.

---

## 📄 License

**MIT** — Free to use, modify, and share.

Data from OpenStreetMap is © OpenStreetMap contributors (ODbL).

---

*Made with ❤️ for the VibeProjects community.*
