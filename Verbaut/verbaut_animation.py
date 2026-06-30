#!/usr/bin/env python3
"""
Verbaut — Landscape Animation 🖥️
====================================
Animate the evolution of building footprint coverage for any Austrian
region. Renders 19 frames (2008–2026) into an MP4 video with stats.

Uses real OSM building footprints rasterised onto a regular grid
for fast frame generation (~2 s / frame for 250 k buildings).

Usage:
    python verbaut_animation.py
    python verbaut_animation.py --region Niederösterreich --fps 10
    python verbaut_animation.py --region "St. Pölten, Austria" --grid 15

Output:
    output/verbaut_<region>_<fps>fps.mp4     ← landscape animation
    output/frames/                            ← individual PNG frames
    output/verbaut_report.json                ← per-year stats
    output/verbaut_growth.png                 ← growth chart

Data source:
    © OpenStreetMap contributors (ODbL) — building footprints

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
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FFMpegWriter
from matplotlib.lines import Line2D
from shapely.geometry import box

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("verbaut")

# ── Projections ─────────────────────────────────────────────────────────────
EPSG_LAEA = 3035
EPSG_WGS84 = 4326

# ── Colours (dark theme) ────────────────────────────────────────────────────
BG = "#0f0f1a"
BLD = "#e74c3c"       # built-up red
GRN = "#2ecc71"       # green
ACC = "#f39c12"       # amber
TXT_L = "#ecf0f1"     # light text
TXT_M = "#95a5a6"     # muted text
TXT_D = "#555555"     # dim text
BND = "#4ecdc4"       # boundary teal

# ── Year distribution model (filled at runtime from OSM metadata) ────────
DIST = None  # populated by query_growth_curve_from_osm()

GRID_SIZE = 12  # raster cell size in metres


# ═════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def area_km2(gdf: gpd.GeoDataFrame) -> float:
    """Area of a GeoDataFrame in km² using equal-area projection."""
    return float(gdf.to_crs(EPSG_LAEA).area.sum()) / 1e6


def load_data(region: str, force: bool = False) -> tuple[str, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Download or load cached building footprints + boundary."""
    import osmnx as ox
    ox.settings.timeout = 600
    ox.settings.log_console = False

    cache = Path(f"data/buildings_{region.lower().replace(' ','_')}.gpkg")
    if cache.exists() and not force:
        log.info(f"Loading cached buildings from {cache}…")
        bld = gpd.read_file(cache)
    else:
        log.info(f"Downloading buildings for '{region}'…")
        t0 = time.time()
        gdf = ox.features_from_place(region, tags={"building": True})
        bld = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
        log.info(f"  {len(bld):,} in {time.time() - t0:.0f}s")
        cache.parent.mkdir(exist_ok=True)
        bld.to_file(cache, driver="GPKG")

    boundary = ox.geocode_to_gdf(region).to_crs(EPSG_WGS84)
    name = (
        boundary.get("name:de", boundary.get("name", region)).iloc[0]
        if len(boundary) else str(region)
    )
    return name, bld, boundary


def query_growth_curve_from_osm(region):
    """Query OSM @timestamp data to build a growth curve."""
    import requests
    from collections import Counter
    url = 'https://overpass-api.de/api/interpreter'
    headers = {'User-Agent': 'Verbaut/1.0', 'Accept': '*/*'}

    # Try at_bev:addr_date first
    q = f'''
    [out:json];
    area["name:de"="{region}"]["admin_level"="4"]->.a;
    (
      way["building"]["at_bev:addr_date"](area.a);
    );
    out meta 5000;
    '''
    try:
        resp = requests.post(url, data={'data': q}, headers=headers, timeout=300)
        data = resp.json()
    except Exception:
        data = {'elements': []}

    years = Counter()
    for e in data.get('elements', []):
        d = e.get('tags', {}).get('at_bev:addr_date', '')
        if len(d) >= 4 and d[:4].isdigit():
            y = int(d[:4])
            if 2000 <= y <= 2030:
                years[y] += 1

    # Fallback to @timestamp
    if not years:
        q2 = f'''
        [out:json];
        area["name:de"="{region}"]["admin_level"="4"]->.a;
        (
          way["building"](area.a);
        );
        out meta 5000;
        '''
        try:
            resp2 = requests.post(url, data={'data': q2}, headers=headers, timeout=300)
            d2 = resp2.json()
            for e in d2.get('elements', []):
                ts = e.get('timestamp', '')
                if len(ts) >= 4 and ts[:4].isdigit():
                    y = int(ts[:4])
                    if 2000 <= y <= 2030:
                        years[y] += 1
        except Exception:
            pass

    log.info(f"  Queried {sum(years.values()):,} dated buildings from OSM")
    if not years:
        log.warning("  No OSM date data — cannot build growth curve")
        return None

    total = sum(years.values())
    sorted_ys = sorted(years.keys())
    start_y = max(1955, min(sorted_ys) - 10)
    end_y = 2026
    all_y = list(range(start_y, end_y + 1))

    cum = 0.0
    cum_y = {}
    for y in sorted_ys:
        cum += years[y] / total
        cum_y[y] = cum

    result = {}
    for y in all_y:
        if y <= sorted_ys[0]:
            frac = (y - start_y) / max(1, sorted_ys[0] - start_y)
            result[y] = round(0.0 + frac * cum_y[sorted_ys[0]], 4)
        elif y in cum_y:
            result[y] = round(cum_y[y], 4)
        elif y > sorted_ys[-1]:
            frac = (y - sorted_ys[-1]) / max(1, end_y - sorted_ys[-1])
            result[y] = round(cum_y[sorted_ys[-1]] + frac * (1.0 - cum_y[sorted_ys[-1]]), 4)
        else:
            lo = max(vy for vy in sorted_ys if vy <= y)
            hi = min(vy for vy in sorted_ys if vy >= y)
            if lo == hi:
                result[y] = round(cum_y[lo], 4)
            else:
                f = (y - lo) / (hi - lo)
                result[y] = round(cum_y[lo] + f * (cum_y[hi] - cum_y[lo]), 4)
    return result


def assign_years(bld: gpd.GeoDataFrame, growth_curve: dict, seed: int = 42) -> gpd.GeoDataFrame:
    """Assign year to each building via random sampling against growth curve from OSM."""
    rng = np.random.default_rng(seed)
    n = len(bld)
    scores = rng.uniform(0, 1, n)
    yl, th = sorted(growth_curve.keys()), sorted(growth_curve.values())
    bld["_year"] = [yl[next(i for i, t in enumerate(th) if s <= t)] for s in scores]
    return bld


def rasterise_once(bld, boundary, cell_size=GRID_SIZE):
    """Single-pass raster: returns (year_raster, area_raster, extent_info)."""
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


# ═════════════════════════════════════════════════════════════════════════════
#  LANDSCAPE FRAME RENDERER
# ═════════════════════════════════════════════════════════════════════════════

def render_frame(raster, extent_info, boundary_wgs, total_km2, bu_km2,
                 year, region_name, years_list, n_buildings, output_path, dpi=150):
    """Render one landscape frame with map panel (left) and info panel (right)."""
    xmin, ymin, cs = extent_info

    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    # Map panel — left 72 %
    ax_map = fig.add_axes([0.01, 0.03, 0.73, 0.94], facecolor="#0d2818")
    # Info panel — right 27 %
    ax_info = fig.add_axes([0.76, 0.03, 0.23, 0.94], facecolor=BG)
    ax_info.set_xlim(0, 1); ax_info.set_ylim(0, 1); ax_info.axis("off")

    # ── Direct RGB compositing ───────────────────────────────────────
    bg = np.array([13, 40, 24], dtype=np.uint8)
    bu = np.array([231, 76, 60], dtype=np.uint8)
    alph = np.clip(raster.astype(float) / 255.0, 0, 1)
    rgb = np.zeros((*raster.shape, 3), dtype=np.uint8)
    for c in range(3):
        rgb[:, :, c] = (bg[c] * (1 - alph) + bu[c] * alph).astype(np.uint8)

    extent = [xmin, xmin + raster.shape[1] * cs, ymin, ymin + raster.shape[0] * cs]
    ax_map.imshow(rgb, extent=extent, origin="lower", interpolation="nearest")
    boundary_wgs.to_crs(EPSG_LAEA).boundary.plot(ax=ax_map, color=BND, lw=1.0, alpha=0.6)
    ax_map.set_xlim(extent[0], extent[1])
    ax_map.set_ylim(extent[2], extent[3])
    ax_map.axis("off")

    # ── Stats ────────────────────────────────────────────────────────
    nat_km2 = max(0, total_km2 - bu_km2)
    ratio = bu_km2 / total_km2 * 100 if total_km2 else 0
    rcol = GRN if ratio < 25 else ACC if ratio < 40 else BLD

    ax_info.text(0.5, 0.94, "🏗️ VERBAUT", fontsize=28, fontweight="bold",
                 color=BLD, ha="center", va="center")
    ax_info.text(0.5, 0.88, "Versiegelungsflächen-Zeitraffer",
                 fontsize=10, color=TXT_M, ha="center", va="center")
    ax_info.text(0.5, 0.82, f"📍 {region_name}", fontsize=14,
                 color=TXT_L, ha="center", va="center")
    ax_info.text(0.5, 0.66, f"{year}", fontsize=76, fontweight="bold",
                 color=TXT_L, ha="center", va="center")

    y = 0.55
    for icon, label, value, vc, vs in [
        ("🏗️", "Versiegelt", f"{bu_km2:.2f} km²", BLD, 14),
        ("🌿", "Natur / Grün", f"{nat_km2:.2f} km²", GRN, 14),
        ("📐", "Gesamtfläche", f"{total_km2:.2f} km²", TXT_M, 14),
    ]:
        ax_info.text(0.08, y, icon, fontsize=11, ha="center", va="center")
        ax_info.text(0.17, y, label, fontsize=9, color=TXT_M, ha="left", va="center")
        ax_info.text(0.95, y, value, fontsize=vs, fontweight="bold",
                     color=vc, ha="right", va="center")
        y -= 0.05

    y -= 0.03
    ax_info.text(0.08, y, "📊", fontsize=11, ha="center", va="center")
    ax_info.text(0.17, y, "Versiegelungsgrad", fontsize=9, color=TXT_M,
                 ha="left", va="center")
    ax_info.text(0.95, y, f"{ratio:.1f}%", fontsize=28, fontweight="bold",
                 color=rcol, ha="right", va="center")
    y -= 0.08
    ax_info.text(0.95, y, f"{n_buildings:,} Gebäude", fontsize=9,
                 color=TXT_M, ha="right", va="center")

    # Timeline bar
    if len(years_list) >= 2:
        y_min, y_max = years_list[0], years_list[-1]
        by, bl, br = 0.13, 0.06, 0.94
        frac = (year - y_min) / max(y_max - y_min, 1)
        ax_info.plot([bl, br], [by, by], color="#2c3e50", lw=8,
                     solid_capstyle="round", zorder=1)
        ax_info.plot([bl, bl + (br - bl) * min(frac, 1)], [by, by],
                     color=BLD, lw=8, solid_capstyle="round", zorder=2)
        for yd in range(y_min, y_max + 1, 4):
            dx = bl + (br - bl) * (yd - y_min) / max(y_max - y_min, 1)
            ax_info.plot(dx, by, "o", color=BLD if yd <= year else "#2c3e50",
                         ms=5, mec=BG, mew=1.5, zorder=3)
        ax_info.text(bl, by - 0.04, str(y_min), fontsize=7, color=TXT_M,
                     ha="center", va="top")
        ax_info.text(br, by - 0.04, str(y_max), fontsize=7, color=TXT_M,
                     ha="center", va="top")

    ax_info.legend(
        handles=[
            Line2D([0], [0], marker='s', color='w', markerfacecolor=BLD,
                   ms=10, label='Versiegelt'),
            Line2D([0], [0], marker='s', color='w', markerfacecolor="#0d2818",
                   ms=10, label='Natur / Grün'),
        ],
        loc="lower center", bbox_to_anchor=(0.5, -0.01),
        ncol=1, fontsize=7.5, framealpha=0, labelcolor=TXT_M,
    )
    ax_info.text(0.5, -0.05, "© OpenStreetMap Mitwirkende · ODbL",
                 fontsize=5.5, color=TXT_D, ha="center", va="bottom")

    fig.savefig(str(output_path), dpi=dpi, bbox_inches="tight",
                facecolor=BG, edgecolor="none", pad_inches=0.05)
    plt.close(fig)


def save_chart(stats, region_name, fp):
    """Save a static growth chart (built-up area + ratio over time)."""
    years = sorted(stats.keys())
    bu = [stats[y]["bu_km2"] for y in years]
    ratios = [stats[y]["ratio"] for y in years]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5), facecolor=BG)
    for ax, d, c, yl, t in [
        (a1, bu, BLD, "km²", f"🏗️ Versiegelung: {region_name}"),
        (a2, ratios, ACC, "%", f"📊 Versiegelungsgrad: {region_name}"),
    ]:
        ax.set_facecolor("#1a1a2e")
        ax.fill_between(years, d, alpha=0.3, color=c)
        ax.plot(years, d, color=c, lw=2.5, marker="o", ms=6)
        ax.set_xlabel("Jahr", color=TXT_M, fontsize=11)
        ax.set_ylabel(yl, color=c, fontsize=11)
        ax.set_title(t, color=TXT_L, fontsize=13, fontweight="bold")
        ax.grid(True, alpha=0.1)
        ax.tick_params(colors=TXT_M, labelsize=9)
        ax.set_xlim(min(years), max(years))
    a2.axhline(y=30, color=GRN, lw=1, ls="--", alpha=0.4, label="30 %")
    a2.axhline(y=45, color=BLD, lw=1, ls="--", alpha=0.4, label="45 %")
    a2.legend(fontsize=8, labelcolor=TXT_M, framealpha=0)
    plt.tight_layout()
    fig.savefig(str(fp), dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

def run_animation(region="Wien", fps=10, dpi=150, grid_size=GRID_SIZE,
                  output_dir="./output", force=False):
    """Run the full animation pipeline."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fd = out / "frames"
    fd.mkdir(exist_ok=True)
    t0 = time.time()

    # 1. Load
    log.info("─" * 52)
    log.info("  Step 1: Load data")
    log.info("─" * 52)
    region_name, bld, boundary = load_data(region, force)
    total_km2 = area_km2(boundary)
    log.info(f"  {region_name}: {total_km2:.2f} km², {len(bld):,} buildings")

    # 2. Years
    log.info("\n" + "─" * 52)
    log.info("  Step 2: Query growth curve from OSM data")
    log.info("─" * 52)
    growth_curve = query_growth_curve_from_osm(region)
    if growth_curve is None:
        log.error("  Could not obtain growth curve — aborting")
        return
    log.info(f"  Growth curve: {len(growth_curve)} years")

    log.info("\n" + "─" * 52)
    log.info("  Step 3: Assign years from OSM data")
    log.info("─" * 52)
    bld = assign_years(bld, growth_curve)
    years = sorted(bld["_year"].unique())
    anim_years = list(range(min(years), max(years) + 1))
    log.info(f"  Frames: {anim_years[0]}–{anim_years[-1]} ({len(anim_years)})")

    # 3. Single-pass raster
    log.info("\n" + "─" * 52)
    log.info("  Step 4: Rasterise")
    log.info("─" * 52)
    yr, ar, ext = rasterise_once(bld, boundary, grid_size)

    # 4. Pre-compute areas
    log.info("\n" + "─" * 52)
    log.info("  Step 5: Compute areas")
    log.info("─" * 52)
    laea = bld.to_crs(EPSG_LAEA)
    vals = laea.area.values
    yearly = {}
    for y in anim_years:
        m = bld["_year"] <= y
        bu_km2 = float(vals[m].sum()) / 1e6
        yearly[y] = {"bu_km2": bu_km2, "ratio": round(bu_km2 / total_km2 * 100, 2),
                     "n": int(m.sum())}
        if y % 4 == 0:
            log.info(f"  {y}: {bu_km2:.2f} km² ({yearly[y]['ratio']:.1f}%) — {yearly[y]['n']:,} blds")

    # 5. Render frames
    log.info("\n" + "─" * 52)
    log.info("  Step 6: Render frames")
    log.info("─" * 52)
    bld_wgs = bld.to_crs(EPSG_WGS84)
    for i, y in enumerate(anim_years):
        s = yearly[y]
        # Build this year's raster via masking
        mask = (yr <= y) & (yr < 9999)
        frame = np.where(mask, ar, 0)

        fp = fd / f"frame_{y:04d}.png"
        render_frame(frame, ext, boundary, total_km2, s["bu_km2"], y,
                     region_name, anim_years, s["n"], fp, dpi)
        if (i + 1) % 5 == 0:
            log.info(f"  Frame {i+1}/{len(anim_years)} ({y}): {s['bu_km2']:.2f} km²")
    log.info(f"  ✓ {len(anim_years)} frames")

    # 6. Compile video
    log.info("\n" + "─" * 52)
    log.info("  Step 7: Compile video")
    log.info("─" * 52)
    vn = f"verbaut_{region_name.lower().replace(' ','_')}_{fps}fps.mp4"
    vp = out / vn
    try:
        frames = sorted(fd.glob("frame_*.png"))
        dur = len(frames) / fps
        log.info(f"  {len(frames)} frames → {vn} ({dur:.1f}s @ {fps}fps)")

        import matplotlib.image as mpimg
        fig, ax = plt.subplots(figsize=(16, 9), facecolor=BG)
        ax.axis("off")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        im = ax.imshow(mpimg.imread(frames[0]))

        writer = FFMpegWriter(fps=fps, bitrate=15000, codec="libx264")
        with writer.saving(fig, str(vp), dpi=dpi):
            for i in range(len(frames)):
                if i > 0:
                    im.set_data(mpimg.imread(frames[i]))
                writer.grab_frame()
                if (i + 1) % 10 == 0:
                    log.info(f"    Frame {i+1}/{len(frames)}")
        plt.close(fig)
        log.info(f"  ✓ {vp} ({os.path.getsize(vp)/1e6:.1f} MB)")
    except Exception as e:
        log.warning(f"  Video failed: {e}")

    # 7. Report + chart
    report = {
        "region": region_name, "total_km2": total_km2,
        "n_buildings": len(bld), "grid_size_m": grid_size,
        "years": anim_years,
        "frames": {str(y): {"bu_km2": yearly[y]["bu_km2"],
                            "ratio": yearly[y]["ratio"],
                            "n_buildings": yearly[y]["n"]} for y in anim_years},
        "generated": datetime.now().isoformat(),
    }
    with open(out / "verbaut_report.json", "w") as f:
        json.dump(report, f, indent=2)
    save_chart(yearly, region_name, out / "verbaut_growth.png")

    log.info(f"\n{'─' * 52}")
    log.info(f"  ✅ Done in {time.time() - t0:.0f}s")
    log.info(f"  🎬 {vp}")
    log.info(f"  📊 {out/'verbaut_report.json'}")
    log.info(f"  📈 {out/'verbaut_growth.png'}")
    log.info(f"  🖼️  {fd}/ ({len(anim_years)} frames)")
    log.info(f"{'─' * 52}")


def main():
    p = argparse.ArgumentParser(description="🏗️ Verbaut — Landscape animation")
    p.add_argument("--region", "-r", default="Wien")
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--grid", type=int, default=GRID_SIZE, help="Raster cell size (m)")
    p.add_argument("--output-dir", "-o", default="./output")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    log.info(f"🏗️  Verbaut — {args.region} | grid={args.grid}m | fps={args.fps}")
    run_animation(args.region, args.fps, args.dpi, args.grid, args.output_dir, args.force)


if __name__ == "__main__":
    main()
