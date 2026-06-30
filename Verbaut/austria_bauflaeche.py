#!/usr/bin/env python3
"""
Austrian Built-Up / Sealed Surface Area Estimator 🇦🇹
======================================================

Gathers publicly available construction/land-use maps across Austria and
estimates the area consumed by buildings, streets, parking lots, and any
surface different from nature ("versiegelte Fläche" / sealed surface).

Data Sources:
  1. OpenStreetMap (via osmnx/Overpass) — primary; excellent Austria coverage
  2. BEV Open Data (GeoNetwork / OGD)  — Austrian cadastre, if available

Output:
  • Built-up polygons (GeoPackage)
  • Per-region statistics (CSV, JSON)
  • Interactive leaflet map (HTML)
  • Sealing-ratio pie chart (PNG)

Usage:
  python austria_bauflaeche.py                              # whole Austria
  python austria_bauflaeche.py --state wien                  # single state
  python austria_bauflaeche.py --municipality 90101          # single municipality
  python austria_bauflaeche.py --state tirol --output-dir ./tirol

Dependencies:
  pip install osmnx geopandas matplotlib folium requests shapely

Author: pi-coding-agent | License: MIT
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from shapely.geometry import MultiPolygon, Polygon, box

warnings.filterwarnings("ignore", category=UserWarning, module="shapely")

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bauflaeche")

# ── Constants ─────────────────────────────────────────────────────────────────
EPSG_LAEA = 3035   # ETRS89 Lambert Azimuthal Equal-Area — accurate area calc
EPSG_WGS84 = 4326

# OSM landuse tags that indicate sealed / built-up ground
SEALED_LANDUSE = [
    "residential",
    "commercial",
    "industrial",
    "retail",
    "construction",
    "brownfield",
    "landfill",
    "quarry",
    "railway",
    "port",
    "harbour",
    "military",
    "depot",
    "garages",
    "parking",
    "road",
    "cemetery",  # often sealed walkways
]

# Estimated road widths (m) per highway tag — used when OSM lacks explicit width
ROAD_WIDTH: dict[str, float] = {
    "motorway": 26.0,
    "motorway_link": 18.0,
    "trunk": 22.0,
    "trunk_link": 16.0,
    "primary": 14.0,
    "primary_link": 12.0,
    "secondary": 10.0,
    "secondary_link": 8.0,
    "tertiary": 8.0,
    "tertiary_link": 6.0,
    "residential": 6.0,
    "living_street": 5.0,
    "service": 5.0,
    "track": 4.0,
    "unclassified": 6.0,
    "road": 6.0,
    "pedestrian": 4.0,
    "footway": 2.0,
    "cycleway": 2.0,
    "path": 2.0,
    "corridor": 2.0,
    "steps": 2.0,
}

RAIL_WIDTH: dict[str, float] = {
    "rail": 5.0,
    "light_rail": 4.0,
    "subway": 5.0,
    "tram": 3.0,
    "narrow_gauge": 3.0,
}

AEROWAY_WIDTH: dict[str, float] = {
    "runway": 45.0,
    "taxiway": 20.0,
    "apron": 0.0,  # polygon, not line
}

# Austrian states (Bundesländer) with their admin_level
AUSTRIAN_STATES: dict = {
    "burgenland": {"id": 1, "name": "Burgenland", "query": "Burgenland, Austria", "area_km2": 3962},
    "kaernten": {"id": 2, "name": "Kärnten", "query": "Kärnten, Austria", "area_km2": 9536},
    "niederoesterreich": {"id": 3, "name": "Niederösterreich", "query": "Niederösterreich, Austria", "area_km2": 19186},
    "oberoesterreich": {"id": 4, "name": "Oberösterreich", "query": "Oberösterreich, Austria", "area_km2": 11982},
    "salzburg": {"id": 5, "name": "Salzburg", "query": "AT-5", "area_km2": 7156},
    "steiermark": {"id": 6, "name": "Steiermark", "query": "Steiermark, Austria", "area_km2": 16401},
    "tirol": {"id": 7, "name": "Tirol", "query": "Tirol, Austria", "area_km2": 12648},
    "vorarlberg": {"id": 8, "name": "Vorarlberg", "query": "Vorarlberg, Austria", "area_km2": 2601},
    "wien": {"id": 9, "name": "Wien", "query": "Wien, Österreich", "area_km2": 414},
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def fmt_area(m2: float) -> str:
    """Format square-metres into a human-friendly string."""
    if m2 < 10_000:
        return f"{m2:,.0f} m²"
    ha = m2 / 10_000
    if ha < 100:
        return f"{ha:,.1f} ha"
    km2 = m2 / 1_000_000
    return f"{km2:,.2f} km²"


def fmt_pct(part: float, total: float) -> str:
    return f"{part / total * 100:.2f}%" if total else "0.0%"


def _to_laea(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject to LAEA for area computation."""
    if gdf.crs is None:
        gdf = gdf.set_crs(EPSG_WGS84)
    if gdf.crs.to_epsg() != EPSG_LAEA:
        return gdf.to_crs(EPSG_LAEA)
    return gdf


def area_m2(gdf: gpd.GeoDataFrame) -> float:
    """Total planar area in square metres (reprojects to LAEA)."""
    if gdf.empty:
        return 0.0
    return float(_to_laea(gdf).area.sum())


def admin_level_for_place(place: str) -> int | None:
    """Determine OSM admin_level for common place names."""
    place_lower = place.strip().lower()
    if place_lower in ("austria", "österreich"):
        return 2
    for key, info in AUSTRIAN_STATES.items():
        if info["name"].lower() == place_lower:
            return 4
    # Default to municipality level
    return 8


# ── 1. Region Boundary ───────────────────────────────────────────────────────


def get_boundary(place: str) -> gpd.GeoDataFrame:
    """
    Fetch the administrative boundary for a place via OSM / osmnx.
    Accepts: country ("Austria"), state name, or municipality GKZ.
    """
    import osmnx as ox

    ox.settings.timeout = 180
    ox.settings.max_query_area_size = 1_000_000_000_000
    ox.settings.log_console = False

    # ── Numeric GKZ ────────────────────────────────────────────────
    if place.isdigit():
        log.info(f"Looking up municipality GKZ {place}…")
        # Only search within Austria by using the Austria boundary
        austria_boundary = ox.geocode_to_gdf("Austria").geometry.iloc[0]
        try:
            gdf = ox.features_from_polygon(
                austria_boundary,
                tags={"ref:at:gkz": place, "boundary": "administrative"},
            )
            if not gdf.empty:
                gdf = gdf.to_crs(EPSG_WGS84)
                # Pick only the one matching the GKZ exactly
                gdf = gdf[gdf.get("ref:at:gkz", "") == place].copy()
                if len(gdf) > 0:
                    log.info(f"  Found: {gdf.iloc[0].get('name', 'GKZ ' + place)}")
                    return gdf
        except Exception as e:
            log.debug(f"  GKZ query via polygon failed: {e}")
        log.warning(f"GKZ {place} not found. Trying as place name…")
        # Fall through to try as place name

    # ── Austrian states ─────────────────────────────────────────────
    place_lower = place.strip().lower()
    resolved_state = None
    resolved_state = None
    resolved_info = None
    for key, info in AUSTRIAN_STATES.items():
        key_lower = key
        name_lower = info["name"].lower()
        if (place_lower == key_lower or place_lower == name_lower or
            place_lower.startswith(key_lower) or place_lower.startswith(name_lower)):
            resolved_state = info["name"]
            resolved_info = info
            break

    if resolved_state:
        log.info(f"Resolving state boundary: {resolved_state}")

        # Use pre-configured Nominatim-safe query for each state
        # (Salzburg needs "AT-5" to get the state, not the city)
        queries = [resolved_info["query"]] if resolved_info else [resolved_state]

        for q in queries:
            try:
                gdf = ox.geocode_to_gdf(q)
                if not gdf.empty:
                    gdf = gdf.to_crs(EPSG_WGS84)
                    area_val = area_m2(gdf)
                    log.info(f"  Found: {resolved_state}  ({fmt_area(area_val)})")
                    return gdf
            except Exception:
                continue

        log.warning(f"Could not resolve state boundary for '{resolved_state}'.")
        return gpd.GeoDataFrame()

    # ── Generic geocode ─────────────────────────────────────────────
    log.info(f"Geocoding '{place}' via nominatim…")
    try:
        gdf = ox.geocode_to_gdf(place)
        if not gdf.empty:
            gdf = gdf.to_crs(EPSG_WGS84)
            name = gdf.iloc[0].get("name", place)
            log.info(f"  Found: {name}  ({fmt_area(area_m2(gdf))})")
            return gdf
    except Exception as e:
        log.debug(f"  Nominatim error: {e}")

    # ── Last resort ────────────────────────────────────────────────
    log.warning(f"Could not resolve '{place}'. Falling back to all of Austria.")
    austria = ox.geocode_to_gdf("Austria").to_crs(EPSG_WGS84)
    log.info(f"  Austria: {fmt_area(area_m2(austria))}")
    return austria


# ── 2. OSM Feature Extraction (via osmnx) ───────────────────────────────────


def fetch_osm_features(
    place_or_polygon: str | Polygon | MultiPolygon,
) -> dict[str, gpd.GeoDataFrame]:
    """
    Fetch all OSM features relevant to built-up area estimation.

    Parameters
    ----------
    place_or_polygon : str | Polygon | MultiPolygon
        Place name (e.g. "Wien") OR a shapely geometry (Polygon/MultiPolygon).
        When a geometry is given, osmnx queries within that polygon directly.
    """
    import osmnx as ox

    ox.settings.timeout = 600
    ox.settings.max_query_area_size = 1_000_000_000_000
    ox.settings.log_console = False

    is_polygon = isinstance(place_or_polygon, (Polygon, MultiPolygon))
    label = "polygon" if is_polygon else str(place_or_polygon)
    log.info(f"Fetching OSM data for '{label}' — this may take a while…")

    # Build the query function: use polygon directly or place name
    def _query(tags) -> gpd.GeoDataFrame:
        if is_polygon:
            return ox.features_from_polygon(place_or_polygon, tags=tags)
        return ox.features_from_place(place_or_polygon, tags=tags)

    results: dict[str, gpd.GeoDataFrame] = {}
    t0 = time.time()

    # 2a. Buildings
    log.info("  (1/4) Buildings…")
    try:
        bld = _query({"building": True})
        if not bld.empty:
            bld = bld.to_crs(EPSG_WGS84)
            bld = bld[bld.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
            results["buildings"] = bld
            log.info(f"         {len(bld):,} footprints  →  {fmt_area(area_m2(bld))}")
    except Exception as e:
        log.warning(f"    Buildings query failed: {e}")

    # 2b. Landuse
    log.info("  (2/4) Sealed landuse areas…")
    try:
        lu = _query({"landuse": SEALED_LANDUSE})
        if not lu.empty:
            lu = lu.to_crs(EPSG_WGS84)
            lu = lu[lu.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
            results["landuse"] = lu
            log.info(f"         {len(lu):,} polygons  →  {fmt_area(area_m2(lu))}")
    except Exception as e:
        log.warning(f"    Landuse query failed: {e}")

    # 2c. Parking
    log.info("  (3/4) Parking lots…")
    try:
        pk = _query({"amenity": "parking"})
        if not pk.empty:
            pk = pk.to_crs(EPSG_WGS84)
            pk = pk[pk.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
            results["parking"] = pk
            log.info(f"         {len(pk):,} lots      →  {fmt_area(area_m2(pk))}")

        pk2 = _query({"parking": True})
        if not pk2.empty:
            pk2 = pk2.to_crs(EPSG_WGS84)
            pk2 = pk2[pk2.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
            if not pk2.empty:
                if "parking" in results:
                    results["parking"] = pd.concat(
                        [results["parking"], pk2], ignore_index=True
                    )
                else:
                    results["parking"] = pk2
                log.info(f"         (parking=* adds {len(pk2):,} more)")
    except Exception as e:
        log.warning(f"    Parking query failed: {e}")

    # 2d. Roads (lines → buffered)
    log.info("  (4/4) Roads & railways (buffered)…")
    try:
        roads = _query({"highway": list(ROAD_WIDTH.keys())})
        if not roads.empty:
            roads = roads.to_crs(EPSG_WGS84)
            results["roads_buffer"] = _buffer_linear_features(roads)
            log.info(
                f"         {len(roads):,} road segments →  "
                f"{fmt_area(area_m2(results['roads_buffer']))}"
            )
    except Exception as e:
        log.warning(f"    Roads query failed: {e}")

    # 2e. Railways
    try:
        rails = _query({"railway": list(RAIL_WIDTH.keys())})
        if not rails.empty:
            rails = rails.to_crs(EPSG_WGS84)
            rails_buf = _buffer_linear_features(rails, width_map=RAIL_WIDTH)
            results["rail_buffer"] = rails_buf
            log.info(
                f"         {len(rails):,} rail segments →  "
                f"{fmt_area(area_m2(rails_buf))}"
            )
    except Exception as e:
        log.debug(f"    Rail query note: {e}")

    # 2f. Aeroways
    try:
        aero = _query({"aeroway": list(AEROWAY_WIDTH.keys())})
        if not aero.empty:
            aero = aero.to_crs(EPSG_WGS84)
            aero_buf = _buffer_linear_features(aero, width_map=AEROWAY_WIDTH)
            results["aero_buffer"] = aero_buf
            log.info(
                f"         {len(aero):,} runway/taxiway →  "
                f"{fmt_area(area_m2(aero_buf))}"
            )
    except Exception as e:
        log.debug(f"    Aeroway query note: {e}")

    elapsed = time.time() - t0
    log.info(f"  OSM fetching completed in {elapsed:.0f}s")
    return results


def _buffer_linear_features(
    gdf: gpd.GeoDataFrame,
    width_map: dict[str, float] | None = None,
) -> gpd.GeoDataFrame:
    """
    Buffer linear OSM features (roads, rails) into polygons representing
    their sealed surface extent. Respects explicit 'width' tags.
    """
    if width_map is None:
        width_map = ROAD_WIDTH

    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=EPSG_WGS84)

    # Keep only lines
    lines = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    polys = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()

    if lines.empty:
        return polys

    lines = _to_laea(lines)

    def _get_buffer_m(row: pd.Series) -> float:
        """Determine buffer radius in metres for a given feature."""
        # Explicit width tag takes precedence
        if "width" in row and row["width"]:
            try:
                return float(row["width"]) / 2.0
            except (ValueError, TypeError):
                pass

        # Highway type
        hw = row.get("highway", "")
        if hw in width_map:
            return width_map[hw] / 2.0

        # Railway type
        rw = row.get("railway", "")
        if rw in RAIL_WIDTH:
            return RAIL_WIDTH[rw] / 2.0

        # Aeroway type
        aw = row.get("aeroway", "")
        if aw in AEROWAY_WIDTH:
            w = AEROWAY_WIDTH[aw]
            return w / 2.0 if w > 0 else 0.0  # apron → polygon already

        # Fallback
        return 3.0  # 6 m wide

    lines["_buf_m"] = lines.apply(_get_buffer_m, axis=1)
    lines["geometry"] = lines.apply(
        lambda r: r.geometry.buffer(r["_buf_m"]) if r["_buf_m"] > 0 else r.geometry,
        axis=1,
    )
    lines = lines[lines.geometry.notna()].copy()
    lines = lines.to_crs(EPSG_WGS84)

    # Merge with existing polygons
    if not polys.empty:
        combined = pd.concat([lines, polys], ignore_index=True)
    else:
        combined = lines

    return combined


def _dissolve_builtup(
    results: dict[str, gpd.GeoDataFrame],
    clip_boundary: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Merge all built-up categories into a single dissolved layer."""
    parts: list[gpd.GeoDataFrame] = []
    for key in ("buildings", "landuse", "parking", "roads_buffer",
                "rail_buffer", "aero_buffer"):
        if key in results and not results[key].empty:
            # Ensure valid geometries
            g = results[key].copy()
            g = g[g.geometry.notna() & g.geometry.is_valid].copy()
            if not g.empty:
                parts.append(_to_laea(g))

    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs=EPSG_LAEA)

    merged = pd.concat(parts, ignore_index=True)

    # Dissolve overlapping polygons
    if len(merged) == 1:
        dissolved = merged.geometry.iloc[0]
    else:
        dissolved = merged.geometry.union_all()

    if dissolved is None or dissolved.is_empty:
        log.warning("  Dissolve produced empty geometry")
        return gpd.GeoDataFrame(geometry=[], crs=EPSG_LAEA)

    if isinstance(dissolved, Polygon):
        dissolved = MultiPolygon([dissolved])

    result = gpd.GeoDataFrame(geometry=[dissolved], crs=EPSG_LAEA)
    log.info(f"  Dissolved: {fmt_area(area_m2(result))} "
             f"({len(parts)} categories, {len(merged):,} features)")

    if clip_boundary is not None and not clip_boundary.empty:
        clip_laea = clip_boundary.to_crs(EPSG_LAEA)
        result = gpd.clip(result, clip_laea)
        log.info(f"  After clip: {fmt_area(area_m2(result))}")

    return result


# ── 3. BEV / OGD Fallback ────────────────────────────────────────────────────


def try_bev_data(output_dir: Path) -> gpd.GeoDataFrame | None:
    """Attempt to fetch Austrian cadastral data from BEV open data / OGD."""
    log.info("Trying BEV open data discovery…")

    urls_attempted: list[str] = []
    datasets: list[dict[str, Any]] = []

    # Try CKAN
    try:
        resp = requests.get(
            "https://www.data.gv.at/katalog/api/3/action/package_search",
            params={"q": "kataster nutzungsart", "rows": 10},
            timeout=15,
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 200:
            data = resp.json()
            for r in data.get("result", {}).get("results", []):
                resources = []
                for res in r.get("resources", []):
                    resources.append(res)
                datasets.append({"title": r.get("title", ""), "resources": resources})
    except Exception as e:
        log.debug(f"CKAN error: {e}")

    # Try GeoNetwork CSW
    try:
        params = {
            "SERVICE": "CSW",
            "VERSION": "2.0.2",
            "REQUEST": "GetRecords",
            "typeNames": "csw:Record",
            "elementSetName": "full",
            "CONSTRAINTLANGUAGE": "CQL_TEXT",
            "CONSTRAINT": "anytext LIKE '%Nutzungsart%'",
            "MAXRECORDS": "10",
        }
        resp = requests.get(
            "https://data.bev.gv.at/geonetwork/srv/eng/csw",
            params=params,
            timeout=15,
        )
        if resp.status_code == 200:
            log.info(f"  CSW response received ({len(resp.content)} bytes)")
    except Exception as e:
        log.debug(f"CSW error: {e}")

    # Try several known download locations
    known_downloads = [
        "https://data.bev.gv.at/opendata/Kataster/Katastralflaechen.gpkg",
        "https://data.bev.gv.at/download/Kataster/Katastralflaechen.gpkg",
        "https://data.bev.gv.at/opendata/Kataster/Nutzungsarten.gpkg",
        "https://data.bev.gv.at/download/Kataster/Nutzungsarten.shp.zip",
    ]

    for url in known_downloads:
        try:
            log.info(f"  Checking {url}…")
            h = requests.head(url, timeout=10, allow_redirects=True)
            if h.status_code == 200:
                log.info(f"  ✓ Found: {url}")
                local = output_dir / "bev_cadastre.gpkg"
                r = requests.get(url, timeout=300, stream=True)
                if r.status_code == 200:
                    with open(local, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    log.info(f"  Downloaded to {local}")
                    gdf = gpd.read_file(local)
                    return gdf
        except Exception as e:
            log.debug(f"  {url}: {e}")
            urls_attempted.append(url)

    log.info("  No BEV data available at this time.")
    return None


def classify_bev_builtup(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame | None:
    """
    Classify BEV cadastral features by land-use code (Nutzungsart).
    Returns only built-up/sealed features.
    """
    if gdf.empty:
        return None

    # Known built-up Nutzungsarten codes (first 3 chars)
    BUILTUP_CODES = {
        "BB",  # Bebaute Grundstücke
        "GB",  # Gebäude
        "HF",  # Hofraum
        "STR",  # Straßenanlagen
        "WEG",  # Wege
        "PKP",  # Parkplätze
        "ABW",  # Abwasseranlagen
        "BGS",  # Bahnanlagen
        "FLH",  # Flughafen
        "IND",  # Industrie (versiegelt)
    }

    # Find the Nutzungsart column
    nutz_col = None
    for col in gdf.columns:
        if col.lower() in ("nutzungsart", "nutzung", "use_type",
                           "land_use", "kataster_nutzung", "beschreibung"):
            nutz_col = col
            break

    if nutz_col is None:
        # Heuristic: try string columns starting the values
        for col in gdf.select_dtypes(include="object").columns:
            sample = gdf[col].dropna().astype(str).str[:3].unique()
            if any(v in BUILTUP_CODES for v in sample):
                nutz_col = col
                break

    if nutz_col:
        log.info(f"  BEV land-use column: '{nutz_col}'")
        mask = gdf[nutz_col].astype(str).str[:3].isin(BUILTUP_CODES)
        built = gdf[mask].copy()
        log.info(f"  Built-up features: {len(built)} / {len(gdf)}")
        return built

    log.warning("  Could not identify land-use column.")
    return None


# ── 4. Statistics ────────────────────────────────────────────────────────────


def compute_statistics(
    builtup_gdf: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    region_name: str,
    breakdown: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute all statistics for the region."""
    stats: dict[str, Any] = {
        "region": region_name,
        "timestamp": datetime.now().isoformat(),
    }

    bu_area = area_m2(builtup_gdf)
    total_area = area_m2(boundary)

    stats["total_builtup_m2"] = bu_area
    stats["total_builtup_ha"] = bu_area / 10_000
    stats["total_builtup_km2"] = bu_area / 1_000_000
    stats["total_area_m2"] = total_area
    stats["total_area_km2"] = total_area / 1_000_000
    stats["sealing_ratio_pct"] = (bu_area / total_area * 100) if total_area else 0.0
    stats["n_polygons"] = len(builtup_gdf)

    if breakdown:
        stats["breakdown"] = breakdown
        total_breakdown = sum(breakdown.values())
        if total_breakdown:
            stats["breakdown_pct"] = {
                k: v / total_breakdown * 100 for k, v in breakdown.items()
            }

    # Estimate population (from Statistik Austria 2024 approximate)
    population_estimates = {
        "Burgenland": 301_000,
        "Kärnten": 568_000,
        "Niederösterreich": 1_698_000,
        "Oberösterreich": 1_532_000,
        "Salzburg": 562_000,
        "Steiermark": 1_265_000,
        "Tirol": 764_000,
        "Vorarlberg": 404_000,
        "Wien": 1_982_000,
        "Austria": 9_106_000,
    }

    for key, pop in population_estimates.items():
        if key.lower() in region_name.lower():
            stats["population"] = pop
            stats["builtup_per_capita_m2"] = bu_area / pop
            stats["builtup_per_capita_ha"] = bu_area / 10_000 / pop
            break

    return stats


# ── 5. Export ────────────────────────────────────────────────────────────────


def export_results(
    builtup_gdf: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    stats: dict[str, Any],
    output_dir: Path,
):
    """Write results to files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Exporting results to {output_dir}…")

    # GeoPackage (simplify geometries to reduce size)
    gpkg = output_dir / "builtup.gpkg"
    if not builtup_gdf.empty:
        export = builtup_gdf.to_crs(EPSG_WGS84).copy()
        export["area_m2"] = _to_laea(export).area.values
        export["area_ha"] = export["area_m2"] / 10_000
        # Simplify for storage (tolerance=1m in LAEA ≈ 0.000009° at 48°N)
        export["geometry"] = export.simplify(tolerance=0.00005, preserve_topology=True)
        export.to_file(gpkg, layer="builtup", driver="GPKG")
        log.info(f"  Built-up polygons → {gpkg}")

    if not boundary.empty:
        bnd = boundary.to_crs(EPSG_WGS84).copy()
        bnd["geometry"] = bnd.simplify(tolerance=0.00005, preserve_topology=True)
        bnd.to_file(gpkg, layer="boundary", driver="GPKG")
        log.info(f"  Boundary          → {gpkg}")

    # CSV
    csv_path = output_dir / "statistics.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value", "unit"])
        for k, v in stats.items():
            if isinstance(v, dict):
                for sk, sv in v.items():
                    if isinstance(sv, (int, float)):
                        w.writerow([f"{k}.{sk}", f"{sv:,.2f}", ""])
                    else:
                        w.writerow([f"{k}.{sk}", sv, ""])
            elif isinstance(v, (int, float)):
                w.writerow([k, f"{v:,.2f}", ""])
            else:
                w.writerow([k, str(v), ""])
    log.info(f"  Statistics        → {csv_path}")

    # JSON
    def convert(val):
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return round(float(val), 4)
        if isinstance(val, dict):
            return {k: convert(v) for k, v in val.items()}
        return val

    clean = {k: convert(v) for k, v in stats.items()}
    json_path = output_dir / "report.json"
    with open(json_path, "w") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
    log.info(f"  Report            → {json_path}")

    # Interactive HTML map
    _make_map(builtup_gdf, boundary, stats, output_dir)

    # Chart
    _make_chart(stats, output_dir)


def _make_map(
    builtup_gdf: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    stats: dict[str, Any],
    output_dir: Path,
):
    """Create a folium interactive map."""
    try:
        import folium

        map_path = output_dir / "builtup_map.html"

        center_lat, center_lon = 47.5, 13.5
        if not boundary.empty:
            bnd_wgs = boundary.to_crs(EPSG_WGS84)
            centroid = bnd_wgs.geometry.centroid.iloc[0]
            center_lat, center_lon = centroid.y, centroid.x

        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=8 if "Wien" not in str(stats.get("region", "")) else 10,
            control_scale=True,
            tiles="CartoDB positron",
        )

        # Built-up layer
        if not builtup_gdf.empty:
            fg = folium.FeatureGroup(name="Built-up / Sealed", show=True)
            simple = builtup_gdf.to_crs(EPSG_WGS84).copy()
            simple["geometry"] = simple.simplify(0.0005, preserve_topology=True)

            style = {
                "fillColor": "#e74c3c",
                "color": "#c0392b",
                "weight": 0.3,
                "fillOpacity": 0.55,
            }
            tooltip = None
            if "area_ha" in simple.columns:
                tooltip = folium.GeoJsonTooltip(
                    fields=["area_ha"],
                    aliases=["Area [ha]"],
                    localize=True,
                )
            gi = folium.GeoJson(
                simple.__geo_interface__,
                style_function=lambda x: style,
                tooltip=tooltip,
            )
            fg.add_child(gi)
            m.add_child(fg)

        # Boundary
        if not boundary.empty:
            fb = folium.FeatureGroup(name="Boundary", show=True)
            folium.GeoJson(
                boundary.to_crs(EPSG_WGS84).__geo_interface__,
                style_function=lambda x: {
                    "fillColor": "none",
                    "color": "#2c3e50",
                    "weight": 2,
                    "dashArray": "5,5",
                },
            ).add_to(fb)
            m.add_child(fb)

        # Statistics info box
        html = f"""
        <div style="font-family: sans-serif; padding: 8px 12px; min-width: 220px;
                    background: white; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.15);">
            <b>🏗️ {stats.get('region', 'Region')}</b><br>
            Sealed: <b>{fmt_area(stats.get('total_builtup_m2', 0))}</b><br>
            Ratio: <b>{stats.get('sealing_ratio_pct', 0):.1f}%</b>
        </div>"""
        folium.Marker(
            location=[center_lat, center_lon],
            icon=folium.DivIcon(html=html, icon_size=(220, 80)),
        ).add_to(m)

        folium.LayerControl().add_to(m)
        m.save(str(map_path))
        log.info(f"  Interactive map   → {map_path}")
    except ImportError:
        log.info("  (folium not installed, skipping map)")


def _make_chart(stats: dict[str, Any], output_dir: Path):
    """Pie chart of sealing ratio."""
    try:
        chart_path = output_dir / "sealing_chart.png"
        fig, ax = plt.subplots(figsize=(8, 6))

        bu = stats.get("total_builtup_m2", 0)
        total = stats.get("total_area_m2", bu)
        nat = max(0, total - bu)
        ratio = stats.get("sealing_ratio_pct", 0)

        if total:
            wedges, texts, autos = ax.pie(
                [bu, nat],
                labels=["Built-up / sealed", "Natural / other"],
                autopct="%1.1f%%",
                startangle=90,
                colors=["#e74c3c", "#27ae60"],
                explode=(0.03, 0),
                textprops={"fontsize": 11},
            )
            for a in autos:
                a.set_fontweight("bold")
            ax.set_title(
                f"Land Sealing Ratio — {stats.get('region', 'Austria')}\n"
                f"Sealed: {fmt_area(bu)}  |  Natural: {fmt_area(nat)}  |  "
                f"Total: {fmt_area(total)}",
                fontsize=13,
                fontweight="bold",
                pad=20,
            )
            plt.tight_layout()
            plt.savefig(str(chart_path), dpi=150, bbox_inches="tight")
            log.info(f"  Sealing chart     → {chart_path}")
        else:
            log.info("  (no area data for chart)")
        plt.close()
    except Exception as e:
        log.debug(f"Chart error: {e}")


# ── Terminal Report ──────────────────────────────────────────────────────────


def print_report(stats: dict[str, Any]):
    """Print a formatted report to the terminal."""
    r = stats.get("region", "Unknown")
    bu = stats.get("total_builtup_m2", 0)
    ta = stats.get("total_area_m2", 0)
    sr = stats.get("sealing_ratio_pct", 0)

    print()
    print("╔" + "═" * 58 + "╗")
    print(f"║  📊  BUILT-UP AREA REPORT  —  {r:<29s} ║")
    print("╠" + "═" * 58 + "╣")
    print(f"║  Total built-up / sealed:  {fmt_area(bu):>30s}  ║")
    if ta:
        print(f"║  Total area:               {fmt_area(ta):>30s}  ║")
        print(f"║  Sealing ratio:            {sr:>9.2f} %              ║")
    if "population" in stats:
        print(f"║  Population:               {stats['population']:>12,}           ║")
        if "builtup_per_capita_m2" in stats:
            print(f"║  Built-up per capita:      {stats['builtup_per_capita_m2']:>8.1f} m²           ║")

    if "breakdown" in stats and stats["breakdown"]:
        print("║  ───────────────────────────────────────────  ║")
        for cat, area in sorted(
            stats["breakdown"].items(), key=lambda x: -x[1]
        ):
            print(f"║  • {cat:<18s}  {fmt_area(area):>28s}  ║")

    print("║  ───────────────────────────────────────────  ║")
    print(f"║  Polygons: {stats.get('n_polygons', 0):>12,}                       ║")
    print(f"║  Timestamp: {stats.get('timestamp', 'N/A')}          ║")
    print("╚" + "═" * 58 + "╝")
    print()


# ── 6. Main Pipeline ─────────────────────────────────────────────────────────


def run_pipeline(
    place: str = "Austria",
    output_dir: str | Path = "./austria_bauflaeche_output",
    skip_bev: bool = False,
) -> dict[str, Any]:
    """Run the full built-up area estimation pipeline."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Step 1 — Boundary
    log.info("─" * 50)
    log.info("STEP 1: Region boundary")
    log.info("─" * 50)
    boundary = get_boundary(place)
    if boundary.empty:
        log.error(f"Could not resolve region: {place}")
        return {}

    # Collapse multi-row boundaries (e.g. multiple matching OSM relations)
    # into a single homogeneous polygon
    if len(boundary) > 1:
        log.info(f"  Collapsing {len(boundary)} boundary features into one…")
        laea = boundary.to_crs(EPSG_LAEA)
        dissolved = laea.geometry.union_all()
        if dissolved is not None and not dissolved.is_empty:
            if isinstance(dissolved, Polygon):
                dissolved = MultiPolygon([dissolved])
            boundary = gpd.GeoDataFrame(geometry=[dissolved], crs=EPSG_LAEA).to_crs(EPSG_WGS84)

    region_name = place.title()
    if "name" in boundary.columns and len(boundary) == 1:
        region_name = boundary["name"].iloc[0]
    # Prefer ISO/GKZ name over English names like "Vienna"
    if "name:de" in boundary.columns:
        de_name = boundary["name:de"].iloc[0]
        if de_name:
            region_name = de_name
    log.info(f"  Region: {region_name}  ({fmt_area(area_m2(boundary))})")

    # Step 2 — OSM extraction
    log.info("")
    log.info("─" * 50)
    log.info("STEP 2: OSM feature extraction")
    log.info("─" * 50)
    # Use the boundary polygon for all OSM queries.
    # This avoids Nominatim ambiguity (e.g. "Salzburg" = city vs state).
    # For place name strings, osmnx geocodes them anyway; by passing
    # the polygon we get the exact area we want.
    osm_query_geom = boundary.geometry.iloc[0]
    osm_features = fetch_osm_features(osm_query_geom)

    # Build breakdown
    breakdown = {}
    for key in ("buildings", "landuse", "parking",
                "roads_buffer", "rail_buffer", "aero_buffer"):
        if key in osm_features:
            label = key.replace("_buffer", "").replace("_", " ").title()
            breakdown[label] = area_m2(osm_features[key])

    # Step 3 — Dissolve
    log.info("")
    log.info("─" * 50)
    log.info("STEP 3: Dissolve into single built-up layer")
    log.info("─" * 50)
    builtup = _dissolve_builtup(osm_features, clip_boundary=boundary)
    log.info(f"  Dissolved area: {fmt_area(area_m2(builtup))}")

    # Step 4 — BEV fallback (optional)
    if not skip_bev and builtup.empty:
        log.info("")
        log.info("─" * 50)
        log.info("STEP 4 (fallback): BEV open data")
        log.info("─" * 50)
        bev_gdf = try_bev_data(out)
        if bev_gdf is not None:
            bev_built = classify_bev_builtup(bev_gdf)
            if bev_built is not None and not bev_built.empty:
                builtup = _dissolve_builtup(
                    {"bev": bev_built}, clip_boundary=boundary
                )
                log.info(f"  BEV built-up area: {fmt_area(area_m2(builtup))}")

    if builtup.empty:
        log.error("No built-up data could be obtained. Exiting.")
        return {}

    # Step 5 — Statistics
    log.info("")
    log.info("─" * 50)
    log.info("STEP 5: Statistics & export")
    log.info("─" * 50)
    stats = compute_statistics(builtup, boundary, region_name, breakdown)
    stats["place"] = place

    # Step 6 — Export
    export_results(builtup, boundary, stats, out)

    # Step 7 — Report
    print_report(stats)

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────


def run_all_states(output_dir: str, skip_bev: bool) -> dict[str, dict]:
    """Run the analysis for all 9 Austrian states and aggregate."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_stats: dict[str, dict] = {}
    total_builtup = 0.0
    total_area = 0.0
    t_start = time.time()

    for key, info in AUSTRIAN_STATES.items():
        name = info["name"]
        log.info("")
        log.info("═" * 60)
        log.info(f"  STATE: {name}")
        log.info("═" * 60)

        state_out = out / key
        t0 = time.time()
        try:
            stats = run_pipeline(
                place=name,
                output_dir=str(state_out),
                skip_bev=skip_bev,
            )
            if stats:
                all_stats[name] = stats
                total_builtup += stats.get("total_builtup_m2", 0)
                total_area += stats.get("total_area_m2", 0)
            elapsed = time.time() - t0
            log.info(f"  ⏱️  {name}: {elapsed:.0f}s")
        except Exception as e:
            log.error(f"  ❌ {name}: {e}")
            all_stats[name] = {"error": str(e)}

    # National summary
    log.info("")
    log.info("═" * 60)
    log.info("  NATIONAL SUMMARY — All 9 States")
    log.info("═" * 60)

    print()
    print("╔" + "═" * 58 + "╗")
    print("║  🏗️  AUSTRIA — BUILT-UP AREA SUMMARY             ║")
    print("╠" + "═" * 58 + "╣")
    print(f"║  {'State':<22s} {'Built-up':>16s} {'Ratio':>8s}   ║")
    print("║" + "─" * 58 + "║")

    for key, info in AUSTRIAN_STATES.items():
        name = info["name"]
        s = all_stats.get(name, {})
        bu = s.get("total_builtup_m2", 0)
        ta = s.get("total_area_m2", 0)
        ratio = bu / ta * 100 if ta else 0
        bu_str = fmt_area(bu)
        print(f"║  {name:<22s} {bu_str:>16s} {ratio:>6.2f}%   ║")

    print("║" + "─" * 58 + "║")
    total_builtup_str = fmt_area(total_builtup)
    total_area_str = fmt_area(total_area)
    print(f"║  {'ÖSTERREICH':<22s} {total_builtup_str:>16s}"
          f" {total_builtup/total_area*100 if total_area else 0:>5.2f}%   ║")
    print("╚" + "═" * 58 + "╝")
    print()

    # Save national summary
    summary = {
        "states": all_stats,
        "national": {
            "total_builtup_m2": total_builtup,
            "total_builtup_km2": total_builtup / 1e6,
            "total_area_m2": total_area,
            "total_area_km2": total_area / 1e6,
            "sealing_ratio_pct": total_builtup / total_area * 100 if total_area else 0,
            "time_seconds": time.time() - t_start,
        },
    }

    def convert(val):
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return round(float(val), 4)
        if isinstance(val, dict):
            return {k: convert(v) for k, v in val.items()}
        return val

    summary_path = out / "national_summary.json"
    with open(summary_path, "w") as f:
        json.dump(convert(summary), f, indent=2, ensure_ascii=False)
    log.info(f"National summary → {summary_path}")

    # CSV
    csv_path = out / "national_summary.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state", "total_area_km2", "builtup_km2", "sealing_pct"])
        for key, info in AUSTRIAN_STATES.items():
            name = info["name"]
            s = all_stats.get(name, {})
            w.writerow([
                name,
                round(s.get("total_area_m2", 0) / 1e6, 2),
                round(s.get("total_builtup_m2", 0) / 1e6, 2),
                round(s.get("sealing_ratio_pct", 0), 2),
            ])
        w.writerow([
            "ÖSTERREICH",
            round(total_area / 1e6, 2),
            round(total_builtup / 1e6, 2),
            round(total_builtup / total_area * 100 if total_area else 0, 2),
        ])
    log.info(f"National CSV → {csv_path}")

    return all_stats


def main():
    parser = argparse.ArgumentParser(
        description="🏗️  Austrian Built-Up / Sealed Surface Area Estimator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python austria_bauflaeche.py --all-states        # All 9 states
  python austria_bauflaeche.py --state wien         # Single state
  python austria_bauflaeche.py --municipality 90101 # Single municipality
  python austria_bauflaeche.py --all-states --skip-bev -v
        """,
    )
    parser.add_argument(
        "--state", "-s",
        type=str,
        default=None,
        choices=list(AUSTRIAN_STATES.keys()),
        help="Analyse a single Bundesland",
    )
    parser.add_argument(
        "--all-states", "-a",
        action="store_true",
        help="Analyse all 9 Bundesländer (batch mode)",
    )
    parser.add_argument(
        "--municipality", "-m",
        type=str,
        default=None,
        help="Municipality GKZ (e.g., 90101 = Wien)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="./austria_bauflaeche_output",
        help="Output directory",
    )
    parser.add_argument(
        "--skip-bev",
        action="store_true",
        help="Skip BEV / OGD fallback (OSM only)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose (debug) logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        log.setLevel(logging.DEBUG)

    log.info("🏗️  Austrian Built-Up Area Estimator")
    log.info(f"  Output: {args.output_dir}")

    t0 = time.time()

    if args.all_states:
        log.info("  Mode: ALL 9 STATES (batch)")
        run_all_states(args.output_dir, args.skip_bev)
    elif args.municipality:
        place = args.municipality
        log.info(f"  Mode: Municipality GKZ {place}")
        stats = run_pipeline(
            place=place,
            output_dir=args.output_dir,
            skip_bev=args.skip_bev,
        )
    elif args.state:
        place = AUSTRIAN_STATES[args.state]["name"]
        log.info(f"  Mode: State '{place}'")
        stats = run_pipeline(
            place=place,
            output_dir=args.output_dir,
            skip_bev=args.skip_bev,
        )
    else:
        log.info("  Mode: Single run (use --all-states for nationwide analysis)")
        stats = run_pipeline(
            place="Austria",
            output_dir=args.output_dir,
            skip_bev=args.skip_bev,
        )

    elapsed = time.time() - t0
    log.info(f"⏱️  Total time: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
