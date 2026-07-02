#!/usr/bin/env python3
"""
Verbaut — Wien 🏙
=================
226 years of built-up area evolution (1800–2026) for Vienna, as a
vertical 9:16 short. Same architecture as ``verbaut_boeheimkirchen.py``
(surveyed BEV DKM cadastral geometry + Statistik Austria GWR growth
model), with two Vienna-specific extensions:

1. Per-district growth curves
   ---------------------------
   The GWR municipality CSV lists Vienna as its 23 districts
   (``Wien-Innere Stadt`` … ``Wien-Liesing``), each with its own
   Bauperiode distribution. Buildings are spatially joined to their
   district (OSM admin_level 9) and year-sampled against *that
   district's* curve — so the historic core fills in first and the
   trans-Danube districts last, as actually happened.

2. Pre-1919 subdivision via historical population (start 1800)
   ------------------------------------------------------------
   The earliest GWR period is only "vor 1919". To start the clock in
   1800, the pre-1919 stock of every district is distributed across
   1800–1918 proportionally to Vienna's documented population curve
   (Statistik Austria, heutiger Gebietsstand): ~272 000 in 1800 →
   2 083 630 at the 1910 census. This concentrates pre-1919 growth in
   the Gründerzeit (1850–1914) instead of spreading it linearly.
   Modelling caveat: the citywide population curve is applied within
   every district; only the *share* of pre-1919 stock varies by
   district. Also, the GWR counts *surviving* stock — buildings
   demolished since (e.g. Glacis, Stadterweiterung) are invisible.

Building & sealed-surface geometry: BEV Kataster (DKM)
------------------------------------------------------
DKM Nutzungsflächen (Kataster © BEV, CC BY 4.0, Stichtag 2026-04-01)
for all 89 Wiener Katastralgemeinden, pulled from the BEV Wien snapshot
zip (661 MB) via HTTP range requests — the KG list is read from the zip
index, nothing hardcoded. NS classes as in the Böheimkirchen demo:

    NS 41  Gebäude                       → red, animated via GWR curves
    NS 42  Parkplätze                    → grey, constant
    NS 83  Gebäudenebenflächen/befestigt → grey, constant
    NS 92  Schienenverkehrsanlagen       → grey, constant
    NS 95  Straßenverkehrsanlagen        → grey, constant

The cadastre has no historical geometry, so the grey sealed layer is
constant across frames — only the buildings animate. For rendering
speed (227 frames, ~10⁵ sealed polygons) the sealed layer is dissolved
once and cached.

Usage:
    python verbaut_wien.py                          # full city, 10 m grid
    python verbaut_wien.py --zoom-km 6 --grid 6     # inside the Gürtel
    python verbaut_wien.py --fps 24 --grid 12

Output (``_core`` suffix when zoomed):
    output/shorts/verbaut_wien[_core]_226yrs.mp4
    output/shorts/frames_wien[_core]/
    output/shorts/wien[_core]_report.json

Data: Kataster/DKM © BEV (CC BY 4.0) · GWR © Statistik Austria ·
      districts/roads/water © OpenStreetMap contributors (ODbL)
Author: VibeProjects · License: MIT
"""
from __future__ import annotations

import argparse
import io
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
log = logging.getLogger("verbaut_wien")

# ── Projections ──────────────────────────────────────────────────────────────
EPSG_LAEA = 3035
EPSG_WGS84 = 4326

# ── Colours (light theme, as in the Böheimkirchen demo) ─────────────────────
BG = "#ffffff"
MAP_BG = "#f7f7f2"
BLD = "#c0392b"
GRN = "#27ae60"
ACC = "#e67e22"
TXT_L = "#1c1c28"
TXT_M = "#5d6d7e"
TXT_D = "#aab2bd"
BND = "#7f8c8d"
C_MOTORWAY = "#2e86c1"
C_BUND = "#e67e22"
C_SEC = "#bdc3c7"
C_RAIL = "#2c3e50"
C_PLACE = "#34495e"
C_SEALED = "#b9c0c5"
C_WATER = "#aed6f1"

REGION = "Wien"
START_YEAR = 1800
END_YEAR = 2026

# GWR (Statistik Austria) building-per-construction-period data cache
GWR_CSV = Path("data/gwr/daten_gwr.v_geb_gem_de.csv")
GWR_ZIP_URL = ("https://www.statistik.at/fileadmin/pages/490/"
               "GWRPakete2025DE.zip")

# ── BEV Kataster / DKM (Wien snapshot) ──────────────────────────────────────
DKM_STICHTAG = "20260401"
DKM_ZIP_URL = (f"https://data.bev.gv.at/download/Kataster/shp/{DKM_STICHTAG}/"
               f"KAT_DKM_Wien_SHP_{DKM_STICHTAG}.zip")
DKM_GPKG = Path("data/dkm_nfl_wien.gpkg")
NS_GEBAEUDE = 41
NS_SEALED = [42, 83, 92, 95]

# ── Vienna population, today's boundaries (heutiger Gebietsstand) ───────────
# Statistik Austria census series; 1800/1830/1850 are pre-census estimates.
# Used only to distribute the GWR "vor 1919" stock across 1800–1918.
POP_ANCHORS_1800_1918 = [
    (1800, 271_800),
    (1830, 401_200),
    (1850, 551_300),
    (1869, 900_998),
    (1880, 1_162_591),
    (1890, 1_430_213),
    (1900, 1_769_137),
    (1910, 2_083_630),
    (1918, 2_100_000),   # estimate; WWI plateau after the 1910 census
]

# GWR Bauperiode column -> (period start year, period end year).
# bp_vor1919 is handled separately via POP_ANCHORS_1800_1918.
GWR_PERIODS_POST1918 = [
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


# ════════════════════════════════════════════════════════════════════════════
#  1. DATA
# ════════════════════════════════════════════════════════════════════════════

class _HttpFile(io.RawIOBase):
    """Read-only seekable file over HTTP range requests, so ``zipfile``
    can pull single members out of the 661 MB BEV Wien zip."""

    def __init__(self, url: str):
        import requests
        self._requests = requests
        self.url = url
        self.pos = 0
        self.size = int(requests.head(url, timeout=30).headers["Content-Length"])

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True

    def read(self, n=-1):
        if n == -1:
            n = self.size - self.pos
        if n <= 0:
            return b""
        end = min(self.pos + n - 1, self.size - 1)
        r = self._requests.get(self.url, timeout=120,
                               headers={"Range": f"bytes={self.pos}-{end}"})
        r.raise_for_status()
        self.pos += len(r.content)
        return r.content


def load_dkm(force: bool = False) -> gpd.GeoDataFrame:
    """
    DKM Nutzungsflächen for all Wiener Katastralgemeinden. The KG list is
    enumerated from the zip index (89 KGs as of Stichtag 2026-04-01),
    fetched via HTTP range requests and cached as one GeoPackage.
    """
    if DKM_GPKG.exists() and not force:
        log.info(f"Loading cached DKM Nutzungsflächen from {DKM_GPKG}…")
        return gpd.read_file(DKM_GPKG)

    import zipfile
    import pandas as pd
    log.info(f"Opening BEV Wien snapshot zip (Stichtag {DKM_STICHTAG})…")
    t0 = time.time()
    z = zipfile.ZipFile(_HttpFile(DKM_ZIP_URL))
    kgs = sorted({n.split("/")[0] for n in z.namelist()
                  if n.endswith("NFL_V2.shp")})
    log.info(f"  {len(kgs)} Katastralgemeinden found in zip index")
    tmp = Path("data/dkm_tmp_wien")
    tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    for kg in kgs:
        for ext in ("shp", "shx", "dbf", "prj"):
            (tmp / f"{kg}NFL_V2.{ext}").write_bytes(
                z.read(f"{kg}/{kg}NFL_V2.{ext}"))
        parts.append(gpd.read_file(tmp / f"{kg}NFL_V2.shp"))
        log.info(f"    KG {kg}: {len(parts[-1]):,} Nutzungsflächen")
    nfl = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True),
                           crs=parts[0].crs)
    nfl.to_file(DKM_GPKG, driver="GPKG")
    log.info(f"  {len(nfl):,} Nutzungsflächen in {time.time()-t0:.0f}s "
             f"(cached -> {DKM_GPKG})")
    return nfl


def get_boundary() -> gpd.GeoDataFrame:
    import osmnx as ox
    return ox.geocode_to_gdf("Wien, Österreich").to_crs(EPSG_WGS84)


def load_districts(force: bool = False) -> gpd.GeoDataFrame:
    """The 23 Wiener Gemeindebezirke (OSM admin_level 9), cached."""
    cache = Path("data/bezirke_wien.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached Bezirke from {cache}…")
        return gpd.read_file(cache)
    log.info("Downloading Wiener Gemeindebezirke from Overpass…")
    import osmnx as ox
    ox.settings.timeout = 600
    d = ox.features_from_place(
        "Wien, Österreich",
        tags={"boundary": "administrative", "admin_level": "9"},
    )
    d = d[d.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    d = d[d["admin_level"] == "9"][["name", "geometry"]].reset_index(drop=True)
    if len(d) != 23:
        log.warning(f"  Expected 23 Bezirke, got {len(d)} — check OSM tags")
    cache.parent.mkdir(exist_ok=True)
    d.to_file(cache, driver="GPKG")
    log.info(f"  {len(d)} Bezirke: {', '.join(sorted(d['name'])[:5])}…")
    return d


def _road_class(row) -> str:
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
    """Main roads (motorway/trunk/primary/secondary) from OSM. Tertiary is
    omitted — at full-city scale it is visual noise."""
    cache = Path("data/roads_wien.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached roads from {cache}…")
        r = gpd.read_file(cache)
    else:
        log.info("Downloading main roads for Wien from Overpass…")
        import osmnx as ox
        ox.settings.timeout = 600
        r = ox.features_from_place(
            "Wien, Österreich",
            tags={"highway": ["motorway", "trunk", "primary", "secondary"]},
        )
        r = r[r.geometry.type.isin(["LineString", "MultiLineString"])].copy()
        r = r[[c for c in ("highway", "ref", "geometry") if c in r.columns]]
        cache.parent.mkdir(exist_ok=True)
        r.to_file(cache, driver="GPKG")
    r["_class"] = r.apply(_road_class, axis=1)
    log.info(f"  {len(r):,} road segments "
             f"(motorway/B={int((r['_class']=='motorway').sum())}/"
             f"{int((r['_class']=='bund').sum())})")
    return r


def load_railways(force: bool = False) -> gpd.GeoDataFrame:
    cache = Path("data/railways_wien.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached railways from {cache}…")
        return gpd.read_file(cache)
    log.info("Downloading railways for Wien from Overpass…")
    import osmnx as ox
    ox.settings.timeout = 600
    r = ox.features_from_place("Wien, Österreich",
                               tags={"railway": "rail"})
    r = r[r.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    r = r[[c for c in ("railway", "geometry") if c in r.columns]]
    cache.parent.mkdir(exist_ok=True)
    r.to_file(cache, driver="GPKG")
    log.info(f"  {len(r):,} railway segments")
    return r


def load_water(force: bool = False) -> gpd.GeoDataFrame:
    """Donau, Donaukanal, Alte/Neue Donau — static orientation layer."""
    cache = Path("data/water_wien.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached water from {cache}…")
        return gpd.read_file(cache)
    log.info("Downloading water bodies for Wien from Overpass…")
    import osmnx as ox
    ox.settings.timeout = 600
    w = ox.features_from_place("Wien, Österreich",
                               tags={"natural": "water"})
    w = w[w.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    # keep only sizeable bodies (> 1 ha) — ponds clutter the map
    w = w[w.to_crs(EPSG_LAEA).area > 10_000][["geometry"]]
    cache.parent.mkdir(exist_ok=True)
    w.to_file(cache, driver="GPKG")
    log.info(f"  {len(w):,} water polygons (> 1 ha)")
    return w


# District centres to label (lat, lon) — full-city view
PLACE_NAMES = {
    "Innere Stadt": (48.2085, 16.3721),
    "Favoriten":    (48.1600, 16.3800),
    "Simmering":    (48.1650, 16.4380),
    "Ottakring":    (48.2130, 16.3070),
    "Döbling":      (48.2470, 16.3480),
    "Floridsdorf":  (48.2570, 16.4000),
    "Donaustadt":   (48.2330, 16.5000),
    "Liesing":      (48.1380, 16.2890),
}

# Inner districts — used for the zoomed core cut, where the full-city
# labels (except Innere Stadt) fall outside the view
PLACE_NAMES_CORE = {
    "Innere Stadt": (48.2085, 16.3721),
    "Leopoldstadt": (48.2130, 16.3980),
    "Landstraße":   (48.1980, 16.3920),
    "Wieden":       (48.1920, 16.3670),
    "Margareten":   (48.1880, 16.3540),
    "Mariahilf":    (48.1950, 16.3480),
    "Neubau":       (48.2020, 16.3450),
    "Josefstadt":   (48.2110, 16.3470),
    "Alsergrund":   (48.2220, 16.3580),
    "Favoriten":    (48.1780, 16.3770),
    "Brigittenau":  (48.2390, 16.3730),
}


def geocode_places(core: bool = False) -> gpd.GeoDataFrame:
    from shapely.geometry import Point
    names = PLACE_NAMES_CORE if core else PLACE_NAMES
    pts = [(name, lon, lat) for name, (lat, lon) in names.items()]
    g = gpd.GeoDataFrame(
        {"name": [p[0] for p in pts]},
        geometry=[Point(p[1], p[2]) for p in pts],
        crs=EPSG_WGS84,
    ).to_crs(EPSG_LAEA)
    log.info(f"  {len(g)} place labels: {', '.join(g['name'])}")
    return g


# ════════════════════════════════════════════════════════════════════════════
#  2. GROWTH MODEL — PER-DISTRICT GWR CURVES, PRE-1919 VIA POPULATION
# ════════════════════════════════════════════════════════════════════════════

def load_gwr_rows() -> dict[str, dict]:
    """All 23 ``Wien-*`` district rows from the GWR municipality CSV,
    keyed by district name (without the ``Wien-`` prefix)."""
    import csv, zipfile, requests

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

    rows = {}
    with open(GWR_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["name"].startswith("Wien-"):
                rows[r["name"][len("Wien-"):]] = r
    if len(rows) != 23:
        raise RuntimeError(f"Expected 23 Wien district rows in GWR CSV, "
                           f"got {len(rows)}")
    total = sum(int(r["geb"]) for r in rows.values())
    log.info(f"  GWR: 23 Wiener Bezirke, {total:,} buildings total")
    return rows


def _pop_fraction(year: int) -> float:
    """Cumulative fraction of the pre-1919 stock existing by ``year``,
    modelled as pop(year)/pop(1918) with linear interpolation between
    the census anchors."""
    ys = [a[0] for a in POP_ANCHORS_1800_1918]
    ps = [a[1] for a in POP_ANCHORS_1800_1918]
    p1918 = ps[-1]
    if year <= ys[0]:
        return ps[0] / p1918
    if year >= ys[-1]:
        return 1.0
    return float(np.interp(year, ys, ps)) / p1918


def district_anchors(row: dict) -> list[tuple[int, float]]:
    """
    Cumulative (year, count) anchors for one district row:
    pre-1919 stock spread over 1800–1918 via the population curve,
    then the regular GWR periods. 'bp_unbekannt' is distributed
    proportionally so the curve reaches the full documented stock.
    """
    vor1919 = int(row["bp_vor1919"])
    counts = {col: int(row[col]) for col, _, _ in GWR_PERIODS_POST1918}
    unknown = int(row["bp_unbekannt"])
    known_total = vor1919 + sum(counts.values())
    scale = (known_total + unknown) / known_total if known_total else 1.0

    anchors: list[tuple[int, float]] = []
    for y, _ in POP_ANCHORS_1800_1918:
        anchors.append((y, vor1919 * scale * _pop_fraction(y)))
    cum = vor1919 * scale
    for col, y0, y1 in GWR_PERIODS_POST1918:
        cum += counts[col] * scale
        anchors.append((y1, cum))
    return anchors


def growth_curve_from_anchors(anchors: list[tuple[int, float]]
                              ) -> dict[int, float]:
    """Year -> cumulative fraction (0..1), linear between anchors.
    The 1800 anchor is the stock already standing at the start —
    the curve starts there, not at zero."""
    total = anchors[-1][1]
    if total <= 0:
        return {y: 1.0 for y in range(START_YEAR, END_YEAR + 1)}
    ys = [a[0] for a in anchors]
    fs = [a[1] / total for a in anchors]
    curve = {}
    for y in range(START_YEAR, END_YEAR + 1):
        f = float(np.interp(y, ys, fs))
        curve[y] = round(min(max(f, 0.0), 1.0), 5)
    return curve


def build_district_curves() -> dict[str, dict[int, float]]:
    rows = load_gwr_rows()
    curves = {}
    log.info("  Per-district share of stock standing in 1850 / 1918 / 1960:")
    for name, row in sorted(rows.items()):
        c = growth_curve_from_anchors(district_anchors(row))
        curves[name] = c
        log.info(f"    {name:<24} {c[1850]:>5.0%} {c[1918]:>5.0%} "
                 f"{c[1960]:>5.0%}")
    return curves


CALIB_GPKG = Path("data/calibration_flags.gpkg")


def load_calibration(bld: gpd.GeoDataFrame):
    """
    Measured year brackets from ``historical_calibration.py`` (overlay of
    each DKM footprint on the 1829 Franziszeischer Kataster vectors and
    the 1904 Generalstadtplan raster). Returns (lo, hi) year arrays
    aligned to ``bld`` — or None when no calibration file exists.

    Semantics: for the measured brackets, red means "this *site* was
    built by then" — a Gründerzeit replacement of an 1829 house counts
    as 1829, which is the right reading for a built-up-*area* animation.
    """
    if not CALIB_GPKG.exists():
        return None
    import pandas as pd
    cal = gpd.read_file(CALIB_GPKG, ignore_geometry=True)
    cal = cal.set_index("nfl_fid").reindex(bld.index)
    ex29 = cal["existed_1829"].fillna(False).astype(bool).values
    ex04 = cal["existed_1904"].fillna(False).astype(bool).values
    cov04 = cal["cover_1904"].fillna(False).astype(bool).values

    lo = np.full(len(bld), START_YEAR)
    hi = np.full(len(bld), END_YEAR)
    hi[ex29] = 1829
    lo[ex04 & ~ex29] = 1830
    hi[ex04 & ~ex29] = 1904
    lo[cov04 & ~ex04 & ~ex29] = 1905
    n_open = int((~cov04 & ~ex29).sum())
    log.info(f"  Calibration: {ex29.sum():,} sites standing 1829 · "
             f"{(ex04 & ~ex29).sum():,} appeared 1830–1904 · "
             f"{(cov04 & ~ex04 & ~ex29).sum():,} absent 1904 · "
             f"{n_open:,} off-sheet (unconstrained)")
    return lo, hi


def assign_years(bld: gpd.GeoDataFrame, districts: gpd.GeoDataFrame,
                 curves: dict[str, dict[int, float]],
                 seed: int = 42) -> gpd.GeoDataFrame:
    """Spatially join buildings to their Bezirk, then sample construction
    years against that district's growth curve — restricted to the
    measured 1829/1904 bracket when a calibration file is present."""
    rng = np.random.default_rng(seed)

    # centroid-in-polygon join (fast, unambiguous for building footprints)
    cent = bld.copy()
    cent["geometry"] = bld.geometry.centroid
    joined = gpd.sjoin(cent, districts.to_crs(bld.crs)[["name", "geometry"]],
                       how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    bld["_bezirk"] = joined["name"].reindex(bld.index).fillna("__city__")
    n_miss = int((bld["_bezirk"] == "__city__").sum())
    if n_miss:
        log.info(f"  {n_miss:,} buildings outside any Bezirk polygon "
                 f"-> citywide fallback curve")

    calib = load_calibration(bld)
    if calib is not None:
        bld["_lo"], bld["_hi"] = calib
    else:
        bld["_lo"], bld["_hi"] = START_YEAR, END_YEAR

    # citywide fallback: mean of district curves
    years_sorted = list(range(START_YEAR, END_YEAR + 1))
    city = {y: float(np.mean([c[y] for c in curves.values()]))
            for y in years_sorted}

    bld["_year"] = 0
    for (name, ylo, yhi), grp in bld.groupby(["_bezirk", "_lo", "_hi"]):
        c = curves.get(name, city)
        f = np.array([c[y] for y in years_sorted])
        i0, i1 = ylo - START_YEAR, yhi - START_YEAR
        base = f[i0 - 1] if i0 > 0 else 0.0
        mass = f[i1] - base
        if mass > 1e-9:
            thr = (f[i0:i1 + 1] - base) / mass
        else:
            # curve has no mass in the measured bracket (e.g. an 1829
            # site in Donaustadt) — fall back to uniform within it
            thr = np.linspace(1 / (i1 - i0 + 1), 1.0, i1 - i0 + 1)
        scores = rng.uniform(0, 1, len(grp))
        idx = np.clip(np.searchsorted(thr, scores, side="left"), 0, i1 - i0)
        bld.loc[grp.index, "_year"] = [years_sorted[i0 + i] for i in idx]

    yc = Counter(bld["_year"])
    total = sum(yc.values())
    log.info("Year distribution"
             + (" (1829/1904-calibrated)" if calib is not None else "")
             + ":")
    for d in range(1800, 2030, 20):
        c = sum(v for k, v in yc.items() if d <= k < d + 20)
        if c:
            log.info(f"  {d}–{d+19}: {c:>7,} ({c / total * 100:.0f}%)")
    return bld


# ════════════════════════════════════════════════════════════════════════════
#  3. SINGLE-PASS RASTERISATION
# ════════════════════════════════════════════════════════════════════════════

def rasterise_once(bld, boundary, cell_size=10):
    """Burn true footprint polygons (not centroids — a Gründerzeit block
    is hundreds of cells) with the *earliest* year winning per cell."""
    from rasterio import features as rfeatures
    from rasterio.transform import from_origin

    bnd = boundary.to_crs(EPSG_LAEA)
    xmin, ymin, xmax, ymax = bnd.total_bounds
    w = int(np.ceil((xmax - xmin) / cell_size))
    h = int(np.ceil((ymax - ymin) / cell_size))
    # row 0 = north edge; flipped to origin="lower" for imshow below
    transform = from_origin(xmin, ymax, cell_size, cell_size)

    bl = bld.to_crs(EPSG_LAEA)
    # later shapes overwrite earlier ones -> burn years descending so the
    # earliest year lands last and wins overlapping cells
    order = np.argsort(-bld["_year"].values)
    shapes = zip(bl.geometry.values[order], bld["_year"].values[order])
    yr = rfeatures.rasterize(
        shapes, out_shape=(h, w), transform=transform,
        fill=9999, all_touched=False, dtype="uint16")
    yr = np.flipud(yr)
    ar = np.where(yr < 9999, 255, 0).astype(np.uint8)
    log.info(f"  Raster {w}×{h} × {cell_size}m = {w * h:,} cells, "
             f"{(yr < 9999).sum():,} built")
    return yr, ar, (xmin, ymin, cell_size)


def dissolve_sealed(sealed: gpd.GeoDataFrame,
                    force: bool = False) -> gpd.GeoDataFrame:
    """Union the ~10⁵ sealed polygons once and cache — plotting one
    (multi)polygon per frame instead of the raw layer keeps 227-frame
    rendering tractable."""
    cache = Path("data/sealed_union_wien.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached sealed-surface union from {cache}…")
        return gpd.read_file(cache)
    log.info(f"Dissolving {len(sealed):,} sealed polygons (one-off)…")
    t0 = time.time()
    u = gpd.GeoDataFrame(geometry=[sealed.union_all()], crs=sealed.crs)
    u["geometry"] = u.simplify(2)
    u.to_file(cache, driver="GPKG")
    log.info(f"  done in {time.time()-t0:.0f}s (cached -> {cache})")
    return u


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


MAP_AXES = [0.02, 0.28, 0.96, 0.70]
MAP_ASPECT = (9.6 * MAP_AXES[3]) / (5.4 * MAP_AXES[2])   # ≈ 1.30


def render_frame(year_raster, area_raster, extent_info, boundary, total_km2,
                 current_year, bu_km2, n_buildings, output_path,
                 roads=None, railways=None, places=None, sealed=None,
                 water=None, sealed_pct=None, view=None, dpi=150,
                 dilate=True, model_note=None):
    xmin, ymin, cs = extent_info

    fig = plt.figure(figsize=(5.4, 9.6), facecolor=BG)
    ax_map = fig.add_axes(MAP_AXES, facecolor=MAP_BG)
    ax_info = fig.add_axes([0, 0, 1, 0.30])
    ax_info.set_xlim(0, 1); ax_info.set_ylim(0, 1); ax_info.axis("off")
    ax_info.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor="#16161e",
                                    zorder=0))

    # ── Water (static): Donau, Donaukanal, Alte/Neue Donau ─────────────
    if water is not None and len(water):
        water.plot(ax=ax_map, color=C_WATER, edgecolor=C_WATER,
                   linewidth=0.3, zorder=1.5)

    # ── Other sealed surfaces (today, constant): grey under buildings ──
    # keep it light — inside the Gürtel this layer covers nearly every
    # non-building surface and must not drown out the red
    if sealed is not None and len(sealed):
        sealed.plot(ax=ax_map, color=C_SEALED, edgecolor=C_SEALED,
                    linewidth=0.4, alpha=0.45, zorder=2)

    # ── RGBA overlay: red built-up on transparent background ───────────
    mask = (year_raster <= current_year) & (year_raster < 9999)
    frame = np.where(mask, area_raster, 0)

    bu_c = np.array([192, 57, 43], dtype=np.uint8)
    alpha = np.clip(frame.astype(float) / 255.0, 0, 1)
    if dilate:
        halo = _dilate(mask)
        alpha = np.where(halo, np.maximum(alpha, 0.65), 0.0)
    else:
        # zoomed view: no halo, but a solid floor so edge cells with
        # partial coverage don't fade the buildings out
        alpha = np.where(mask, np.maximum(alpha, 0.75), 0.0)
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
        ax_map.text(0.02, 0.968, "■ Straßen, Parkplätze u. befestigte "
                    "Flächen (Kataster, heute)",
                    transform=ax_map.transAxes, fontsize=7.5, color="#7d868c",
                    ha="left", va="top", fontweight="bold", zorder=9,
                    bbox=lg_box)

    # ── Roads ───────────────────────────────────────────────────────────
    if roads is not None and len(roads):
        rl = roads.to_crs(EPSG_LAEA)
        for cls in ("motorway", "bund"):
            sub = rl[rl["_class"] == cls]
            if len(sub):
                sub.plot(ax=ax_map, color="#ffffff", lw=2.6, zorder=3)
        for cls, col, lw, z in [
            ("sec", C_SEC, 0.7, 3),
            ("motorway", C_MOTORWAY, 1.8, 5),
            ("bund", C_BUND, 1.5, 5),
        ]:
            sub = rl[rl["_class"] == cls]
            if len(sub):
                sub.plot(ax=ax_map, color=col, lw=lw, zorder=z)

    # ── Railways ────────────────────────────────────────────────────────
    if railways is not None and len(railways):
        rwy = railways.to_crs(EPSG_LAEA)
        rwy.plot(ax=ax_map, color="#ffffff", lw=1.6, zorder=4)
        rwy.plot(ax=ax_map, color=C_RAIL, lw=0.6, zorder=5)

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
                row["name"], xy=(x, y), xytext=(4, 3),
                textcoords="offset points",
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

    # ── Info panel ──────────────────────────────────────────────────────
    ratio = bu_km2 / total_km2 * 100 if total_km2 else 0
    rc = GRN if ratio < 10 else ACC if ratio < 15 else BLD
    TXT_LI = "#ecf0f1"
    TXT_MI = "#95a5a6"

    ax_info.text(0.5, 0.75, "VERBAUT", fontsize=22, fontweight="bold",
                 color=BLD, ha="center", va="center",
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e",
                           edgecolor="none", alpha=0.8))
    ax_info.text(0.5, 0.52, f"{current_year}", fontsize=48, fontweight="bold",
                 color=TXT_LI, ha="center", va="center")

    chips = [
        (0.2, f"Gebäude {bu_km2:.1f} km²", BLD),
        (0.5, f"{ratio:.1f} % verbaut", rc),
    ]
    if sealed_pct is not None:
        chips.append((0.8, f"{sealed_pct:.1f} % versiegelt", C_SEALED))
    else:
        chips.append((0.8, f"{n_buildings:,} Geb.", TXT_LI))
    for xp, label, col in chips:
        ax_info.text(xp, 0.30, label, fontsize=8,
                     color=col, ha="center", va="center",
                     bbox=dict(boxstyle="round,pad=0.4", facecolor="#1a1a2e",
                               edgecolor=col, lw=0.5))
    ax_info.text(0.5, 0.12,
                 f"Wien · {total_km2:.0f} km² · 23 Bezirke",
                 fontsize=9, color=TXT_MI, ha="center", va="center")
    ax_info.text(0.5, 0.065,
                 model_note or
                 "vor 1919: Verteilung nach historischer Bevölkerung · "
                 "versiegelt = Gebäude + Straßen/Schienen/Parkplätze (heute)",
                 fontsize=6, color=TXT_D, ha="center", va="center")
    ax_info.text(0.5, 0.025,
                 "Kataster/DKM © BEV (CC BY 4.0) · Gebäudealter: GWR "
                 "Statistik Austria · © OpenStreetMap (ODbL)",
                 fontsize=6, color=TXT_D, ha="center", va="center")

    fig.savefig(str(output_path), dpi=dpi, facecolor=BG, edgecolor="none")
    plt.close(fig)


# ════════════════════════════════════════════════════════════════════════════
#  5. MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="🏗️ Verbaut — Wien 1800–2026")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--grid", type=int, default=10, help="raster cell size (m)")
    p.add_argument("--zoom-km", type=float, default=None,
                   help="zoom to the centre: view width in km (e.g. 6 = "
                        "inside the Gürtel); default = full city")
    p.add_argument("--year-step", type=int, default=1,
                   help="render every Nth year (1 = all 227 frames)")
    p.add_argument("--output-dir", "-o", default="./output/shorts")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    suffix = "_core" if args.zoom_km else ""
    log.info(f"🎬 Verbaut — Wien {START_YEAR}–{END_YEAR} | fps={args.fps} "
             f"grid={args.grid}m"
             + (f" zoom={args.zoom_km}km" if args.zoom_km else ""))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fd = out / f"frames_wien{suffix}"
    fd.mkdir(exist_ok=True)
    t0 = time.time()

    # 1. Load
    log.info("─" * 52)
    log.info("  [1/6] Load DKM Nutzungsflächen (BEV Kataster)")
    log.info("─" * 52)
    nfl = load_dkm(args.force)
    bld = nfl[nfl["NS"] == NS_GEBAEUDE].copy()
    sealed_raw = nfl[nfl["NS"].isin(NS_SEALED)].to_crs(EPSG_LAEA)
    boundary = get_boundary()
    total_km2 = float(boundary.to_crs(EPSG_LAEA).area.sum()) / 1e6
    log.info(f"  Wien: {total_km2:.1f} km², "
             f"{len(bld):,} Gebäudeflächen (NS 41), "
             f"{len(sealed_raw):,} sonst. versiegelte Flächen (NS {NS_SEALED})")
    sealed = dissolve_sealed(sealed_raw, args.force).to_crs(EPSG_LAEA)
    districts = load_districts(args.force)
    roads = gpd.clip(load_roads(args.force), boundary)
    railways = gpd.clip(load_railways(args.force), boundary)
    water = gpd.clip(load_water(args.force), boundary).to_crs(EPSG_LAEA)
    places = geocode_places(core=bool(args.zoom_km))

    view = None
    if args.zoom_km:
        from shapely.geometry import Point
        lat, lon = PLACE_NAMES["Innere Stadt"]     # Stephansdom
        c = gpd.GeoSeries([Point(lon, lat)], crs=EPSG_WGS84).to_crs(EPSG_LAEA)[0]
        half_w = args.zoom_km * 1000 / 2
        half_h = half_w * MAP_ASPECT
        view = (c.x - half_w, c.x + half_w, c.y - half_h, c.y + half_h)
        log.info(f"  Zoom: {args.zoom_km} km × {2*half_h/1000:.1f} km "
                 f"around Stephansdom")

    # 2. Growth curves (per district, from Statistik Austria GWR)
    log.info("\n" + "─" * 52)
    log.info(f"  [2/6] Build 23 district growth curves "
             f"({START_YEAR}→{END_YEAR})")
    log.info("─" * 52)
    curves = build_district_curves()

    # 3. Assign years (spatial join to Bezirk, sample district curve)
    log.info("\n" + "─" * 52)
    log.info("  [3/6] Assign years to buildings (per Bezirk)")
    log.info("─" * 52)
    bld = assign_years(bld, districts, curves)
    years = list(range(START_YEAR, END_YEAR + 1, args.year_step))
    if years[-1] != END_YEAR:
        years.append(END_YEAR)
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

    other_sealed_km2 = float(sealed.area.sum()) / 1e6
    total_sealed_km2 = other_sealed_km2 + float(vals.sum()) / 1e6
    sealed_pct = total_sealed_km2 / total_km2 * 100
    log.info(f"  Other sealed surfaces (Kataster, today): "
             f"{other_sealed_km2:.1f} km²")
    log.info(f"  Total sealed today: {total_sealed_km2:.1f} km² "
             f"= {sealed_pct:.1f}% of the city")

    yearly = {}
    byear = bld["_year"].values
    for y in years:
        m = byear <= y
        yearly[y] = {"km2": float(vals[m].sum()) / 1e6, "n": int(m.sum())}
    for y in [1800, 1850, 1880, 1910, 1930, 1960, 1990, 2010, 2026]:
        yy = min(years, key=lambda v: abs(v - y))
        s = yearly[yy]
        log.info(f"  {yy}: {s['km2']:.2f} km² "
                 f"({s['km2']/total_km2*100:.1f}%) — {s['n']:,} blds")

    # 6. Render frames + compile video
    log.info("\n" + "─" * 52)
    log.info("  [6/6] Render frames → compile video")
    log.info("─" * 52)
    calibrated = CALIB_GPKG.exists()
    model_note = (
        "verankert am Franziszeischen Kataster 1829 u. Generalstadtplan "
        "1904 (Stadt Wien) · versiegelt: Stand heute"
        if calibrated else None)
    for i, y in enumerate(years):
        fp = fd / f"frame_{y:04d}.png"
        render_frame(yr, ar, ext, boundary, total_km2, y, yearly[y]["km2"],
                     yearly[y]["n"], fp, roads, railways, places,
                     sealed, water, sealed_pct, view, args.dpi,
                     dilate=not args.zoom_km, model_note=model_note)
        if (i + 1) % 25 == 0 or i == len(years) - 1:
            log.info(f"  Frame {i+1}/{len(years)} ({y}): "
                     f"{yearly[y]['km2']:.2f} km² "
                     f"[{(time.time()-t0)/60:.1f} min]")

    vp = out / f"verbaut_wien{suffix}_226yrs.mp4"
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
                # pacing: hold first frame 1.5s, last 2s, others 1 tick
                # (227 frames at 24 fps ≈ 9.5s + 3.5s holds ≈ 13s)
                reps = (int(args.fps * 1.5) if fi == 0
                        else args.fps * 2 if fi == len(frames) - 1
                        else 1)
                for _ in range(reps):
                    writer.grab_frame(); tf += 1
                if (fi + 1) % 50 == 0 or fi == len(frames) - 1:
                    log.info(f"    {tf//args.fps}s ({fi+1}/{len(frames)})")
        plt.close(fig)
        log.info(f"  ✓ {vp} ({os.path.getsize(vp)/1e6:.1f} MB, "
                 f"{tf/args.fps:.0f}s)")
    except Exception as e:
        log.warning(f"  Video failed: {e}")

    report = {
        "region": "Wien",
        "total_km2": total_km2,
        "n_buildings": len(bld),
        "model": ("per-district cumulative growth curves from Statistik "
                  "Austria GWR 2025-01-01 Bauperiode counts (23 Wiener "
                  "Bezirke); pre-1919 stock distributed across 1800–1918 "
                  "proportionally to Vienna's historical population "
                  "(heutiger Gebietsstand); linear interpolation between "
                  "anchors; buildings joined to Bezirke via centroid"),
        "growth_source": ("Statistik Austria GWR (Gebäude- und "
                          "Wohnungsregister) 2025-01-01, per district"),
        "pre1919_model": {
            "population_anchors": POP_ANCHORS_1800_1918,
            "note": ("cumulative pre-1919 share at year y = pop(y)/pop(1918); "
                     "1800/1830/1850 are pre-census estimates; citywide curve "
                     "applied within every district. GWR counts surviving "
                     "stock only — demolished buildings are invisible."),
        },
        "calibration": ({
            "file": str(CALIB_GPKG),
            "anchors": ["Franziszeischer Kataster 1829 (FRANZKATOGD, "
                        "vector overlay)",
                        "Generalstadtplan 1904 (GENLPLAN1904OGD, "
                        "dark-fraction raster test)"],
            "method": ("per-building year bracket: standing-1829 -> "
                       "[1800,1829]; appeared -> [1830,1904]; absent 1904 "
                       "-> [1905,2026]; off-sheet -> unconstrained; GWR "
                       "district curve sampled within the bracket"),
            "semantics": ("for measured brackets red = site built by that "
                          "year (a Gründerzeit replacement of an 1829 "
                          "house counts as 1829)"),
            "source": "© Stadt Wien (data.wien.gv.at, CC BY 4.0)",
        } if calibrated else None),
        "sealed_layer": {
            "other_sealed_km2_today": round(other_sealed_km2, 2),
            "total_sealed_km2_today": round(total_sealed_km2, 2),
            "total_sealed_pct_today": round(sealed_pct, 2),
            "source": (f"BEV DKM Nutzungsflächen (Kataster © BEV, CC BY 4.0, "
                       f"Stichtag {DKM_STICHTAG}), NS classes: Gebäude 41; "
                       f"sealed {NS_SEALED} = Parkplätze, Gebäudenebenflächen "
                       f"(befestigt), Schienen- u. Straßenverkehrsanlagen"),
            "note": ("measured cadastral areas; present-day extent, constant "
                     "across frames — the cadastre has no historical "
                     "geometry. Betriebsflächen (NS 63) excluded"),
        },
        "years": years,
        "frames": {str(y): {"bu_km2": round(yearly[y]["km2"], 3),
                            "ratio": round(yearly[y]["km2"]/total_km2*100, 3),
                            "n": yearly[y]["n"]} for y in years},
        "data_source": ("Kataster/DKM © BEV (CC BY 4.0) · GWR © Statistik "
                        "Austria · districts/roads/water © OpenStreetMap "
                        "contributors (ODbL)"),
    }
    if args.zoom_km:
        report["view"] = {"center": "Stephansdom",
                          "width_km": args.zoom_km,
                          "note": "map view only — stats cover the whole city"}
    with open(out / f"wien{suffix}_report.json", "w") as f:
        json.dump(report, f, indent=2)

    log.info(f"\n{'─' * 52}")
    log.info(f"  ✅ Done in {(time.time()-t0)/60:.1f} min")
    log.info(f"  🎬 {vp}")
    log.info(f"  📊 {out / f'wien{suffix}_report.json'}")
    log.info(f"{'─' * 52}")


if __name__ == "__main__":
    main()
