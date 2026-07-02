#!/usr/bin/env python3
"""
Verbaut — Böheimkirchen 🏡
==========================
70 years of built-up area evolution (1955–2026) for the village of
Böheimkirchen (Lower Austria). Vertical 9:16 short using real OSM
building footprints, a documented rural-growth model, and a
present-day sealed-surface layer (roads, parking, sealed landuse).

Böheimkirchen is a small rural municipality (~45.5 km², ~2 950 buildings
in OSM). Unlike Vienna — a mature city already ~60 % built by 1955 —
the village grew more gradually, with the bulk of post-war expansion
happening in the 1960s–1980s (Siedlungen, Einfamilienhäuser).

Year assignment model (authoritative)
-------------------------------------
OSM does NOT store construction years. The ``at_bev:addr_date`` tag
reflects BEV cadastre *import* dates (2017–2023), not building ages.

Instead of a synthetic curve, this script uses the **Gebäude- und
Wohnungsregister (GWR)** of Statistik Austria — the federal building
register — which counts buildings per **Bauperiode** (construction
period) for every municipality. The 2025-01-01 extract is downloaded
from https://www.statistik.at/ and cached in ``data/gwr/``.

The per-period counts for Böheimkirchen are turned into a cumulative
year-by-year growth curve by linearly interpolating between the period
endpoints. Each OSM building footprint is then assigned a year by
sampling against this *real* distribution. This makes the animation
follow the documented construction history of the municipality rather
than an assumed sigmoid.

Sealed-surface layer (present-day, constant)
--------------------------------------------
Buildings are only part of the sealed ground. A grey layer shows all
other sealed surfaces as of today: roads and railways buffered to their
estimated pavement width (width assumptions shared with
``austria_bauflaeche.py``), parking areas, and sealed landuse. Unpaved
``track``/``path`` ways and ``landuse=residential`` (mostly gardens at
village scale) are excluded. OSM has no historical road data, so this
layer is constant across frames — only the buildings animate. Result:
~2.9 % of the municipality is sealed today vs. 1.74 % from buildings
alone.

Usage:
    python verbaut_boeheimkirchen.py                        # full municipality
    python verbaut_boeheimkirchen.py --zoom-km 2.4 --grid 4 # village core
    python verbaut_boeheimkirchen.py --fps 24 --grid 8

Output (``_core`` suffix when zoomed):
    output/shorts/verbaut_boeheimkirchen[_core]_70yrs.mp4
    output/shorts/frames_bhmk[_core]/
    output/shorts/bhmk[_core]_report.json

Data: © OpenStreetMap contributors (ODbL) · GWR © Statistik Austria
Author: VibeProjects · License: MIT
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
import warnings
from collections import Counter
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FFMpegWriter

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("verbaut_bhmk")

# ── Projections ──────────────────────────────────────────────────────────────
EPSG_LAEA = 3035
EPSG_WGS84 = 4326

# ── Colours (light theme) ───────────────────────────────────────────────────
BG = "#ffffff"          # page background (white)
MAP_BG = "#f7f7f2"       # map panel background (off-white)
BLD = "#c0392b"         # built-up red (darker for contrast on white)
GRN = "#27ae60"
ACC = "#e67e22"
TXT_L = "#1c1c28"        # dark text on white
TXT_M = "#5d6d7e"
TXT_D = "#aab2bd"
BND = "#7f8c8d"          # boundary grey
# Road / railway colours
C_MOTORWAY = "#2e86c1"   # A1 Westautobahn — blue
C_BUND = "#e67e22"        # B1 Bundesstraße — orange
C_SEC = "#bdc3c7"         # secondary/tertiary — light grey
C_RAIL = "#2c3e50"        # railway — dark
C_PLACE = "#34495e"       # place labels


REGION = "Böheimkirchen"
START_YEAR = 1955
END_YEAR = 2026
# GWR (Statistik Austria) building-per-construction-period data cache
GWR_CSV = Path("data/gwr/daten_gwr.v_geb_gem_de.csv")
GWR_ZIP_URL = ("https://www.statistik.at/fileadmin/pages/490/"
               "GWRPakete2025DE.zip")


# ════════════════════════════════════════════════════════════════════════════
#  1. DATA
# ════════════════════════════════════════════════════════════════════════════

def load_buildings(force: bool = False) -> gpd.GeoDataFrame:
    cache = Path("data/buildings_boeheimkirchen.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached buildings from {cache}…")
        return gpd.read_file(cache)

    log.info("Downloading buildings for Böheimkirchen from Overpass…")
    import osmnx as ox
    ox.settings.timeout = 600
    ox.settings.log_console = False
    t0 = time.time()
    gdf = ox.features_from_place("Böheimkirchen, Austria", tags={"building": True})
    bld = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    log.info(f"  {len(bld):,} buildings in {time.time() - t0:.0f}s")
    cache.parent.mkdir(exist_ok=True)
    bld.to_file(cache, driver="GPKG")
    return bld


def get_boundary() -> gpd.GeoDataFrame:
    import osmnx as ox
    return ox.geocode_to_gdf("Böheimkirchen, Austria").to_crs(EPSG_WGS84)


def _road_class(row) -> str:
    """Classify a road segment: motorway / bund / sec / other."""
    ref = str(row.get("ref", "") or "")
    hw = str(row.get("highway", "") or "")
    if "motorway" in hw or ref.startswith("A"):
        return "motorway"
    if ref.startswith("B") or hw == "primary":
        return "bund"
    if hw in ("secondary", "tertiary"):
        return "sec"
    return "other"


def load_roads(force: bool = False) -> gpd.GeoDataFrame:
    """Load main roads (motorway, primary, secondary, tertiary) from OSM."""
    cache = Path("data/roads_boeheimkirchen.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached roads from {cache}…")
        r = gpd.read_file(cache)
    else:
        log.info("Downloading main roads for Böheimkirchen from Overpass…")
        import osmnx as ox
        ox.settings.timeout = 600
        ox.settings.log_console = False
        r = ox.features_from_place(
            "Böheimkirchen, Austria",
            tags={"highway": ["motorway", "primary", "secondary",
                              "tertiary", "trunk"]},
        )
        r = r[r.geometry.type.isin(["LineString", "MultiLineString"])].copy()
        cache.parent.mkdir(exist_ok=True)
        r.to_file(cache, driver="GPKG")
    r["_class"] = r.apply(_road_class, axis=1)
    log.info(f"  {len(r):,} road segments "
             f"(motorway/B={int((r['_class']=='motorway').sum())}/"
             f"{int((r['_class']=='bund').sum())})")
    return r


def load_railways(force: bool = False) -> gpd.GeoDataFrame:
    """Load railway lines from OSM."""
    cache = Path("data/railways_boeheimkirchen.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached railways from {cache}…")
        return gpd.read_file(cache)
    log.info("Downloading railways for Böheimkirchen from Overpass…")
    import osmnx as ox
    ox.settings.timeout = 600
    ox.settings.log_console = False
    r = ox.features_from_place("Böheimkirchen, Austria",
                               tags={"railway": "rail"})
    r = r[r.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    cache.parent.mkdir(exist_ok=True)
    r.to_file(cache, driver="GPKG")
    log.info(f"  {len(r):,} railway segments")
    return r


# ── Sealed surfaces beyond buildings (present-day, constant layer) ──────────
# OSM has no historical road/parking data, so this layer shows TODAY's
# extent in every frame — the animation only moves the buildings.
# Width assumptions are shared with austria_bauflaeche.py.
# Unlike austria_bauflaeche.py we deliberately EXCLUDE landuse=residential
# and cemetery here: at village scale those polygons are mostly unsealed
# gardens, and buildings are already counted separately.
SEALED_LANDUSE = ["commercial", "industrial", "retail", "garages",
                  "depot", "parking", "road", "construction"]
# track/path are mostly unpaved field ways — only count them when the
# surface tag says otherwise (austria_bauflaeche.py counts them all)
UNPAVED_DEFAULT = {"track", "path"}
PAVED_SURFACES = {"asphalt", "concrete", "paved", "paving_stones",
                  "sett", "cobblestone"}
C_SEALED = "#b9c0c5"     # other sealed surfaces — grey


def _width_m(row, width_map: dict, key: str) -> float:
    """Pavement width for a line feature: explicit width tag, else class default."""
    w = row.get("width")
    if w:
        try:
            return float(str(w).replace("m", "").strip())
        except ValueError:
            pass
    return width_map.get(str(row.get(key, "")), 0.0)


def _sealed_parts(gdf, width_map: dict, key: str) -> list:
    """LAEA geometries for a feature set: lines buffered to half their
    pavement width, polygons taken as-is."""
    g = gdf.to_crs(EPSG_LAEA)
    lines = g[g.geometry.type.isin(["LineString", "MultiLineString"])]
    polys = g[g.geometry.type.isin(["Polygon", "MultiPolygon"])]
    parts = list(polys.geometry)
    if len(lines):
        widths = lines.apply(lambda r: _width_m(r, width_map, key), axis=1)
        parts += list(lines.geometry.buffer(widths.values / 2.0))
    return parts


def load_sealed(boundary: gpd.GeoDataFrame,
                force: bool = False) -> gpd.GeoDataFrame:
    """
    Present-day sealed surfaces other than buildings, dissolved, in LAEA:
    all roads and railways buffered to their estimated pavement width
    (same assumptions as austria_bauflaeche.py), parking areas, and
    sealed landuse polygons — clipped to the municipality.
    """
    cache = Path("data/sealed_boeheimkirchen.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached sealed surfaces from {cache}…")
        return gpd.read_file(cache)

    log.info("Downloading sealed surfaces (roads/parking/landuse) from Overpass…")
    import osmnx as ox
    from shapely.ops import unary_union
    from austria_bauflaeche import ROAD_WIDTH, RAIL_WIDTH
    ox.settings.timeout = 600
    ox.settings.log_console = False

    parts = []
    for tags, wmap, key, what in [
        ({"highway": list(ROAD_WIDTH)}, ROAD_WIDTH, "highway", "roads"),
        ({"railway": list(RAIL_WIDTH)}, RAIL_WIDTH, "railway", "railways"),
        ({"amenity": "parking"}, {}, "amenity", "parking"),
        ({"landuse": SEALED_LANDUSE}, {}, "landuse", "sealed landuse"),
    ]:
        try:
            g = ox.features_from_place("Böheimkirchen, Austria", tags=tags)
        except Exception as e:
            log.info(f"    {what}: none found ({type(e).__name__})")
            continue
        if key == "highway":
            unpaved = g["highway"].isin(UNPAVED_DEFAULT)
            if "surface" in g.columns:
                unpaved &= ~g["surface"].isin(PAVED_SURFACES)
            log.info(f"    ({int(unpaved.sum()):,} unpaved tracks/paths excluded)")
            g = g[~unpaved]
        p = _sealed_parts(g, wmap, key)
        log.info(f"    {what}: {len(p):,} geometries")
        parts += p

    merged = unary_union(parts)
    clip_poly = boundary.to_crs(EPSG_LAEA).union_all()
    merged = merged.intersection(clip_poly)
    sealed = gpd.GeoDataFrame(geometry=[merged], crs=EPSG_LAEA)
    cache.parent.mkdir(exist_ok=True)
    sealed.to_file(cache, driver="GPKG")
    log.info(f"  Other sealed surfaces: {merged.area / 1e6:.2f} km² (cached -> {cache})")
    return sealed


# Place names to label (villages / cadastral centres within the municipality)
PLACE_NAMES = {
    "Böheimkirchen": (48.1961, 15.7619),   # main village centre
    "Mechters":       (48.1954, 15.7123),
    "Schildberg":    (48.2187, 15.7426),
    "Furth":         (48.1676, 15.7528),
}


def geocode_places() -> gpd.GeoDataFrame:
    """Return a GeoDataFrame of place-name points in LAEA projection."""
    from shapely.geometry import Point
    pts = [(name, lon, lat) for name, (lat, lon) in PLACE_NAMES.items()]
    g = gpd.GeoDataFrame(
        {"name": [p[0] for p in pts]},
        geometry=[Point(p[1], p[2]) for p in pts],
        crs=EPSG_WGS84,
    ).to_crs(EPSG_LAEA)
    log.info(f"  {len(g)} place labels: {', '.join(g['name'])}")
    return g


# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
#  2. GROWTH MODEL FROM STATISTIK AUSTRIA GWR  (authoritative)
# ════════════════════════════════════════════════════════════════════════════

# GWR Bauperiode column -> (period start year, period end year)
GWR_PERIODS = [
    ("bp_vor1919",   1800, 1918),
    ("bp_1919b1944", 1919, 1944),
    ("bp_1945b1960", 1945, 1960),
    ("bp_1961b1970", 1961, 1970),
    ("bp_1971b1980", 1971, 1980),
    ("bp_1981b1990", 1981, 1990),
    ("bp_1991b2000", 1991, 2000),
    ("bp_2001b2005", 2001, 2005),
    ("bp_2006b2010", 2006, 2010),
    ("bp_2011b2015", 2011, 2015),
    ("bp_2016b2020", 2016, 2020),
    ("bp_2021b2025", 2021, 2025),
]


def load_gwr_periods(place: str = REGION):
    """
    Download (if needed) and parse the Statistik Austria GWR
    buildings-by-construction-period CSV for the given municipality.

    Returns (anchors, total) where anchors is a list of
    (end_year, cumulative_count) and total is the scaled total
    (unknown periods distributed proportionally).
    """
    import csv, io, zipfile, requests

    if not GWR_CSV.exists():
        log.info("Downloading Statistik Austria GWR 2025 package...")
        GWR_CSV.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(GWR_ZIP_URL, timeout=120,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        outer = zipfile.ZipFile(io.BytesIO(r.content))
        inner_name = next(n for n in outer.namelist()
                          if n.endswith("_gem_de.zip"))
        inner = zipfile.ZipFile(io.BytesIO(outer.read(inner_name)))
        geb_csv_name = next(n for n in inner.namelist()
                           if n.startswith("daten_gwr.v_geb_gem"))
        GWR_CSV.write_bytes(inner.read(geb_csv_name))
        log.info(f"  Cached GWR data -> {GWR_CSV}")

    with open(GWR_CSV, encoding="utf-8") as f:
        rd = csv.DictReader(f, delimiter=";")
        row = next((r for r in rd if r["name"] == place), None)
    if row is None:
        raise RuntimeError(f"Gemeinde '{place}' not found in GWR CSV")

    log.info(f"  GWR total buildings for {place}: {row['geb']}")
    counts = {col: int(row[col]) for col, _, _ in GWR_PERIODS}
    unknown = int(row["bp_unbekannt"])
    known_total = sum(counts.values())
    # Distribute the 'unbekannt' (unknown period) proportionally so the
    # curve reaches 100 % of the documented stock at 2025.
    scale = (known_total + unknown) / known_total if known_total else 1.0

    anchors = []  # (end_year, cumulative_count)
    cum = 0.0
    for col, y0, y1 in GWR_PERIODS:
        cum += counts[col] * scale
        anchors.append((y1, cum))
    total = anchors[-1][1]
    log.info("  Bauperiode cumulative anchors (year -> share of stock):")
    for y, c in anchors:
        log.info(f"    {y}: {c/total:.1%} ({c:.0f} of {total:.0f})")
    return anchors, total


def growth_curve() -> dict[int, float]:
    """
    Build a year-by-year cumulative growth curve from the real Statistik
    Austria GWR Bauperiode counts, by linearly interpolating between the
    period endpoints. Returns a dict year -> cumulative fraction (0..1).
    """
    anchors, total = load_gwr_periods(REGION)
    yrs = [a[0] for a in anchors]
    fr = [a[1] / total for a in anchors]
    # prepend a zero anchor before the first period so early years -> 0
    yrs = [yrs[0] - 1] + yrs
    fr = [0.0] + fr

    curve = {}
    for y in range(START_YEAR, END_YEAR + 1):
        if y <= yrs[0]:
            f = fr[0]
        elif y >= yrs[-1]:
            f = 1.0
        else:
            lo = max(i for i, yy in enumerate(yrs) if yy <= y)
            hi = min(i for i, yy in enumerate(yrs) if yy >= y)
            if lo == hi:
                f = fr[lo]
            else:
                t = (y - yrs[lo]) / (yrs[hi] - yrs[lo])
                f = fr[lo] + (fr[hi] - fr[lo]) * t
        curve[y] = round(min(max(f, 0.0), 1.0), 4)
    return curve


def assign_years(bld: gpd.GeoDataFrame, gc: dict[int, float],
                seed: int = 42) -> gpd.GeoDataFrame:
    rng = np.random.default_rng(seed)
    n = len(bld)
    scores = rng.uniform(0, 1, n)
    years_sorted = sorted(gc.keys())
    thresholds = [gc[y] for y in years_sorted]
    bld["_year"] = [
        years_sorted[next(i for i, t in enumerate(thresholds) if s <= t)]
        for s in scores
    ]
    yc = Counter(bld["_year"])
    total = sum(yc.values())
    log.info("Year distribution (sampled against growth curve):")
    for d in range(1950, 2030, 10):
        c = sum(v for k, v in yc.items() if d <= k < d + 10)
        if c:
            log.info(f"  {d}s: {c:>5,} ({c / total * 100:.0f}%)")
    return bld


# ════════════════════════════════════════════════════════════════════════════
#  3. SINGLE-PASS RASTERISATION
# ════════════════════════════════════════════════════════════════════════════

def rasterise_once(bld, boundary, cell_size=8):
    bnd = boundary.to_crs(EPSG_LAEA)
    xmin, ymin, xmax, ymax = bnd.total_bounds
    w = int(np.ceil((xmax - xmin) / cell_size))
    h = int(np.ceil((ymax - ymin) / cell_size))

    bl = bld.to_crs(EPSG_LAEA)
    cents = bl.geometry.centroid
    cx = np.array([c.x for c in cents])
    cy = np.array([c.y for c in cents])
    col = np.floor((cx - xmin) / cell_size).astype(int)
    row = np.floor((cy - ymin) / cell_size).astype(int)
    valid = (col >= 0) & (col < w) & (row >= 0) & (row < h)
    col, row = col[valid], row[valid]

    cov = bl.area.values[valid] / (cell_size ** 2)
    yrs = bld["_year"].values[valid]

    yr = np.full((h, w), 9999, dtype=np.uint16)
    ar = np.zeros((h, w), dtype=np.float32)
    for r, c, y, a in zip(row, col, yrs, cov):
        if y < yr[r, c]:
            yr[r, c] = y
        ar[r, c] += a
    ar = np.clip(ar * 255, 0, 255).astype(np.uint8)
    log.info(f"  Raster {w}×{h} × {cell_size}m = {w * h:,} cells")
    return yr, ar, (xmin, ymin, cell_size)


# ════════════════════════════════════════════════════════════════════════════
#  4. FRAME RENDERER (9:16 vertical)
# ════════════════════════════════════════════════════════════════════════════

def _dilate(mask: np.ndarray) -> np.ndarray:
    """3×3 binary dilation without scipy (no wrap-around at edges)."""
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    out[1:, 1:] |= mask[:-1, :-1]
    out[1:, :-1] |= mask[:-1, 1:]
    out[:-1, 1:] |= mask[1:, :-1]
    out[:-1, :-1] |= mask[1:, 1:]
    return out


# map panel geometry (fig fractions) — height/width aspect of the axes in
# inches, used to shape the zoom window so it fills the panel
MAP_AXES = [0.02, 0.28, 0.96, 0.70]
MAP_ASPECT = (9.6 * MAP_AXES[3]) / (5.4 * MAP_AXES[2])   # ≈ 1.30


def render_frame(year_raster, area_raster, extent_info, boundary, total_km2,
                 current_year, bu_km2, n_buildings, output_path,
                 roads=None, railways=None, places=None, sealed=None,
                 sealed_pct=None, view=None, dpi=150):
    xmin, ymin, cs = extent_info

    fig = plt.figure(figsize=(5.4, 9.6), facecolor=BG)
    ax_map = fig.add_axes(MAP_AXES, facecolor=MAP_BG)
    ax_info = fig.add_axes([0, 0, 1, 0.30])
    ax_info.set_xlim(0, 1); ax_info.set_ylim(0, 1); ax_info.axis("off")
    # axis("off") hides the axes patch, so paint the dark panel explicitly
    ax_info.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor="#16161e",
                                    zorder=0))

    # ── Other sealed surfaces (today, constant): grey under the buildings ──
    if sealed is not None and len(sealed):
        # stroke with the fill colour so narrow road buffers (<1 px at this
        # scale) keep a minimum visible width
        sealed.plot(ax=ax_map, color=C_SEALED, edgecolor=C_SEALED,
                    linewidth=0.6, zorder=2)

    # ── RGBA overlay: red built-up on transparent background ───────────
    mask = (year_raster <= current_year) & (year_raster < 9999)
    frame = np.where(mask, area_raster, 0)

    bu_c = np.array([192, 57, 43], dtype=np.uint8)     # built-up red
    # A single 8 m cell is ~1 screen pixel at this scale — dilate each
    # built cell one cell outward and give it a solid minimum opacity so
    # individual houses stay visible on a phone screen.
    halo = _dilate(mask)
    alpha = np.clip(frame.astype(float) / 255.0, 0, 1)
    alpha = np.where(halo, np.maximum(alpha, 0.65), 0.0)
    rgba = np.zeros((*frame.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = bu_c
    rgba[:, :, 3] = (alpha * 255).astype(np.uint8)

    extent = [xmin, xmin + year_raster.shape[1] * cs,
              ymin, ymin + year_raster.shape[0] * cs]
    ax_map.imshow(rgba, extent=extent, origin="lower",
                  interpolation="nearest", zorder=2.5)

    # ── Legend (top-left) ───────────────────────────────────────────────
    lg_box = dict(boxstyle="round,pad=0.25", facecolor="white",
                  edgecolor="none", alpha=0.85)
    ax_map.text(0.02, 0.995, f"■ Gebäude (bis {current_year})",
                transform=ax_map.transAxes, fontsize=7.5, color=BLD,
                ha="left", va="top", fontweight="bold", zorder=9, bbox=lg_box)
    if sealed is not None:
        ax_map.text(0.02, 0.968, "■ Straßen, Park- u. a. versiegelte "
                    "Flächen (Stand heute)",
                    transform=ax_map.transAxes, fontsize=7.5, color="#7d868c",
                    ha="left", va="top", fontweight="bold", zorder=9,
                    bbox=lg_box)

    # ── Roads: secondary (grey) → motorway (blue) → B-roads (orange) ─────
    if roads is not None and len(roads):
        rl = roads.to_crs(EPSG_LAEA)
        # white casing under main roads for readability
        for cls in ("motorway", "bund"):
            sub = rl[rl["_class"] == cls]
            if len(sub):
                sub.plot(ax=ax_map, color="#ffffff", lw=3.6, zorder=3)
        for cls, col, lw, z in [
            ("sec", C_SEC, 1.2, 3),
            ("motorway", C_MOTORWAY, 2.6, 5),
            ("bund", C_BUND, 2.4, 5),
        ]:
            sub = rl[rl["_class"] == cls]
            if len(sub):
                sub.plot(ax=ax_map, color=col, lw=lw, zorder=z)

    # ── Railways: dark line + white hatching (classic railway style) ──
    if railways is not None and len(railways):
        rwy = railways.to_crs(EPSG_LAEA)
        rwy.plot(ax=ax_map, color="#ffffff", lw=2.4, zorder=4)
        rwy.plot(ax=ax_map, color=C_RAIL, lw=1.0, zorder=5)

    # ── Boundary ───────────────────────────────────────────────────────
    boundary.to_crs(EPSG_LAEA).boundary.plot(ax=ax_map, color=BND, lw=0.8,
                                             alpha=0.7, zorder=6)

    # ── Place-name labels ─────────────────────────────────────────────
    if places is not None and len(places):
        for _, row in places.iterrows():
            x, y = row.geometry.x, row.geometry.y
            ax_map.plot(x, y, "o", color=C_PLACE, ms=3.5, mec="white",
                        mew=0.8, zorder=7)
            ax_map.annotate(
                row["name"], xy=(x, y), xytext=(4, 3), textcoords="offset points",
                fontsize=8, fontweight="bold", color="#1c1c28", zorder=8,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                          edgecolor="none", alpha=0.8),
            )

    if view is not None:
        ax_map.set_xlim(view[0], view[1])
        ax_map.set_ylim(view[2], view[3])
    else:
        ax_map.set_xlim(extent[0], extent[1])
        ax_map.set_ylim(extent[2], extent[3])
    ax_map.axis("off")

    # ── Info panel (dark, for contrast) ───────────────────────────────
    ratio = bu_km2 / total_km2 * 100 if total_km2 else 0
    rc = GRN if ratio < 1 else ACC if ratio < 1.5 else BLD
    TXT_LI = "#ecf0f1"
    TXT_MI = "#95a5a6"

    ax_info.text(0.5, 0.75, "VERBAUT", fontsize=22, fontweight="bold",
                 color=BLD, ha="center", va="center",
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e",
                           edgecolor="none", alpha=0.8))
    ax_info.text(0.5, 0.52, f"{current_year}", fontsize=48, fontweight="bold",
                 color=TXT_LI, ha="center", va="center")

    chips = [
        (0.2, f"Gebäude {bu_km2:.2f} km²", BLD),
        (0.5, f"{ratio:.1f} % verbaut", rc),
    ]
    if sealed_pct is not None:
        chips.append((0.8, f"~{sealed_pct:.1f} % versiegelt", C_SEALED))
    else:
        chips.append((0.8, f"{n_buildings:,} Geb.", TXT_LI))
    for xp, label, col in chips:
        ax_info.text(xp, 0.30, label, fontsize=8,
                     color=col, ha="center", va="center",
                     bbox=dict(boxstyle="round,pad=0.4", facecolor="#1a1a2e",
                               edgecolor=col, lw=0.5))
    ax_info.text(0.5, 0.10,
                 f"Böheimkirchen · Niederösterreich · {total_km2:.0f} km²",
                 fontsize=9, color=TXT_MI, ha="center", va="center")
    ax_info.text(0.5, 0.04,
                 "versiegelt = Gebäude + Straßen/Parkflächen (Stand heute) | "
                 "© OpenStreetMap (ODbL)",
                 fontsize=6, color=TXT_D, ha="center", va="center")

    # no bbox_inches="tight" — keep the exact 5.4×9.6 in (9:16) canvas
    fig.savefig(str(output_path), dpi=dpi, facecolor=BG, edgecolor="none")
    plt.close(fig)


# ════════════════════════════════════════════════════════════════════════════
#  5. MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="🏗️ Verbaut — Böheimkirchen")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--grid", type=int, default=8, help="raster cell size (m)")
    p.add_argument("--zoom-km", type=float, default=None,
                   help="zoom to the village core: view width in km "
                        "(e.g. 2.4); default = full municipality")
    p.add_argument("--output-dir", "-o", default="./output/shorts")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    suffix = "_core" if args.zoom_km else ""
    log.info(f"🎬 Verbaut — Böheimkirchen | fps={args.fps} grid={args.grid}m"
             + (f" zoom={args.zoom_km}km" if args.zoom_km else ""))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fd = out / f"frames_bhmk{suffix}"
    fd.mkdir(exist_ok=True)
    t0 = time.time()

    # 1. Load
    log.info("─" * 52)
    log.info("  [1/6] Load building footprints from OSM")
    log.info("─" * 52)
    bld = load_buildings(args.force)
    boundary = get_boundary()
    total_km2 = float(boundary.to_crs(EPSG_LAEA).area.sum()) / 1e6
    log.info(f"  Böheimkirchen: {total_km2:.2f} km², {len(bld):,} buildings")
    # clip line features to the municipality so they don't spill into the
    # empty margins of the map panel
    roads = gpd.clip(load_roads(args.force), boundary)
    railways = gpd.clip(load_railways(args.force), boundary)
    places = geocode_places()
    sealed = load_sealed(boundary, args.force)   # LAEA, dissolved, clipped

    # Optional zoom window around the village core, shaped to fill the
    # map panel (view height = width × panel aspect)
    view = None
    if args.zoom_km:
        from shapely.geometry import Point
        lat, lon = PLACE_NAMES[REGION]
        c = gpd.GeoSeries([Point(lon, lat)], crs=EPSG_WGS84).to_crs(EPSG_LAEA)[0]
        half_w = args.zoom_km * 1000 / 2
        half_h = half_w * MAP_ASPECT
        view = (c.x - half_w, c.x + half_w, c.y - half_h, c.y + half_h)
        log.info(f"  Zoom: {args.zoom_km} km × {2*half_h/1000:.1f} km "
                 f"around the village core")

    # 2. Growth curve (from Statistik Austria GWR)
    log.info("\n" + "─" * 52)
    log.info("  [2/6] Build growth curve from Statistik Austria GWR (1955→2026)")
    log.info("─" * 52)
    gc = growth_curve()
    log.info(f"  Source: GWR 2025-01-01 (Statistik Austria), Bauperiode counts")
    for yr in [1955, 1965, 1975, 1985, 1995, 2005, 2015, 2025]:
        log.info(f"    {yr}: {gc[yr]:.0%}")

    # 3. Assign years
    log.info("\n" + "─" * 52)
    log.info("  [3/6] Assign years to buildings")
    log.info("─" * 52)
    bld = assign_years(bld, gc)
    years = sorted(gc.keys())
    log.info(f"  Frames: {years[0]}–{years[-1]} ({len(years)})")

    # 4. Rasterise
    log.info("\n" + "─" * 52)
    log.info("  [4/6] Rasterise (single pass)")
    log.info("─" * 52)
    yr, ar, ext = rasterise_once(bld, boundary, args.grid)

    # 5. Pre-compute yearly built-up area
    log.info("\n" + "─" * 52)
    log.info("  [5/6] Compute yearly built-up area")
    log.info("─" * 52)
    laea = bld.to_crs(EPSG_LAEA)
    vals = laea.area.values

    # Present-day sealed total: buildings ∪ other sealed, dissolved so
    # overlaps (e.g. a garage on a parking polygon) aren't double-counted.
    from shapely.ops import unary_union
    other_sealed_km2 = float(sealed.area.sum()) / 1e6
    sealed_union = unary_union(list(sealed.geometry) + list(laea.geometry))
    total_sealed_km2 = float(sealed_union.area) / 1e6
    sealed_pct = total_sealed_km2 / total_km2 * 100
    log.info(f"  Other sealed surfaces (today): {other_sealed_km2:.2f} km²")
    log.info(f"  Total sealed today (dissolved): {total_sealed_km2:.2f} km² "
             f"= {sealed_pct:.1f}% of municipality")

    yearly = {}
    for y in years:
        m = bld["_year"] <= y
        bu_km2 = float(vals[m].sum()) / 1e6
        yearly[y] = {"km2": bu_km2, "n": int(m.sum())}
    for y in [1955, 1965, 1975, 1985, 1995, 2005, 2015, 2025, 2026]:
        s = yearly[y]
        log.info(f"  {y}: {s['km2']:.3f} km² "
                 f"({s['km2']/total_km2*100:.2f}%) — {s['n']:,} blds")

    # 6. Render frames + compile video
    log.info("\n" + "─" * 52)
    log.info("  [6/6] Render frames → compile video")
    log.info("─" * 52)
    for i, y in enumerate(years):
        fp = fd / f"frame_{y:04d}.png"
        render_frame(yr, ar, ext, boundary, total_km2, y, yearly[y]["km2"],
                     yearly[y]["n"], fp, roads, railways, places,
                     sealed, sealed_pct, view, args.dpi)
        if (i + 1) % 14 == 0 or i == len(years) - 1:
            log.info(f"  Frame {i+1}/{len(years)} ({y}): {yearly[y]['km2']:.3f} km²")

    vp = out / f"verbaut_boeheimkirchen{suffix}_70yrs.mp4"
    try:
        frames = sorted(fd.glob("frame_*.png"))
        import matplotlib.image as mpimg
        fig, ax = plt.subplots(figsize=(5.4, 9.6), facecolor=BG)
        ax.axis("off"); fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        im = ax.imshow(mpimg.imread(frames[0]))
        writer = FFMpegWriter(fps=args.fps, bitrate=20000, codec="libx264")
        tf = 0
        with writer.saving(fig, str(vp), dpi=args.dpi):
            for fi in range(len(frames)):
                if fi > 0:
                    im.set_data(mpimg.imread(frames[fi]))
                # pacing: hold first frame 4s, last 5s, others ~0.3s
                reps = (args.fps * 4 if fi == 0
                        else args.fps * 5 if fi == len(frames) - 1
                        else max(1, args.fps // 3))
                for _ in range(reps):
                    writer.grab_frame(); tf += 1
                if (fi + 1) % 20 == 0 or fi == len(frames) - 1:
                    log.info(f"    {tf//args.fps}s ({fi+1}/{len(frames)})")
        plt.close(fig)
        log.info(f"  ✓ {vp} ({os.path.getsize(vp)/1e6:.1f} MB, "
                 f"{tf/args.fps:.0f}s)")
    except Exception as e:
        log.warning(f"  Video failed: {e}")

    report = {
        "region": "Böheimkirchen",
        "total_km2": total_km2,
        "n_buildings": len(bld),
        "model": ("cumulative growth curve from Statistik Austria GWR "
                  "2025-01-01 Bauperiode counts (Böheimkirchen), "
                  "linear interpolation between period endpoints"),
        "growth_source": "Statistik Austria GWR (Gebäude- und Wohnungsregister) 2025-01-01",
        "gwr_total_buildings": "see data/gwr/daten_gwr.v_geb_gem_de.csv",
        "sealed_layer": {
            "other_sealed_km2_today": round(other_sealed_km2, 3),
            "total_sealed_km2_today": round(total_sealed_km2, 3),
            "total_sealed_pct_today": round(sealed_pct, 2),
            "note": ("roads/railways buffered to estimated pavement width "
                     "(austria_bauflaeche.py assumptions) + parking areas + "
                     "sealed landuse (excl. residential/cemetery); "
                     "present-day extent, constant across frames — OSM has "
                     "no historical road data"),
        },
        "years": years,
        "frames": {str(y): {"bu_km2": yearly[y]["km2"],
                            "ratio": round(yearly[y]["km2"]/total_km2*100, 3),
                            "n": yearly[y]["n"]} for y in years},
        "data_source": "© OpenStreetMap contributors (ODbL) · GWR © Statistik Austria",
    }
    if args.zoom_km:
        report["view"] = {"center": "Böheimkirchen village core",
                          "width_km": args.zoom_km,
                          "note": "map view only — stats cover the whole "
                                  "municipality"}
    with open(out / f"bhmk{suffix}_report.json", "w") as f:
        json.dump(report, f, indent=2)

    log.info(f"\n{'─' * 52}")
    log.info(f"  ✅ Done in {time.time()-t0:.0f}s")
    log.info(f"  🎬 {vp}")
    log.info(f"  📊 {out / f'bhmk{suffix}_report.json'}")
    log.info(f"{'─' * 52}")


if __name__ == "__main__":
    main()
