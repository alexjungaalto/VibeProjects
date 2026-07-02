#!/usr/bin/env python3
"""
Historical calibration — Wien 1829 & 1904 🗺
============================================
Assigns each present-day DKM building footprint two *measured* history
flags, replacing the population-interpolated timing of
``verbaut_wien.py`` with archival evidence:

existed_1829 — vector overlay against the **Franziszeischer Kataster**
    (City of Vienna OGD ``FRANZKATOGD``, WFS, EPSG:31256): the complete
    1829 cadastre vectorised by Stadtarchäologie Wien, incl. building
    classes Stein (masonry) / Holz (wood) / Kirche / Militaer / Oefftl.
    A footprint counts as standing in 1829 if ≥ ``FRAC_1829`` of its
    area intersects an 1829 building polygon (threshold absorbs the
    georeferencing tolerance of the historical sheets).

existed_1904 — raster test against the **Generalstadtplan 1904**
    (WMS layer ``GENLPLAN1904OGD``, same CRS): the GSP is B/W line art
    where built parcels are hatched or solid dark. For each footprint
    the interior dark-pixel fraction is measured on 1 m/px WMS tiles;
    above ``DARK_1904`` the building is taken as standing in 1904.
    Tiles whose overall content is near-blank (off the 1904 sheet
    edge, e.g. parts of trans-Danube Vienna) yield coverage=False and
    the building stays unclassified rather than "absent".

Output: ``data/calibration_flags.gpkg`` keyed by the positional index
of the NS-41 subset of ``data/dkm_nfl_wien.gpkg`` (column ``nfl_fid``),
plus a per-district summary comparing measured shares against the
population model. ``verbaut_wien.py`` picks the file up automatically.

Usage:
    python historical_calibration.py            # both anchors
    python historical_calibration.py --skip-1904

Data: Franziszeischer Kataster & Generalstadtplan © Stadt Wien
      (data.wien.gv.at, CC BY 4.0) · Kataster/DKM © BEV (CC BY 4.0)
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("calib")

EPSG_MGI = 31256           # MGI / Austria GK East — DKM, FRANZKAT, WMS
DKM_GPKG = Path("data/dkm_nfl_wien.gpkg")
FK_GPKG = Path("data/franzkat_1829.gpkg")
OUT_GPKG = Path("data/calibration_flags.gpkg")
TILE_DIR = Path("cache/gsp1904")

WFS_URL = ("https://data.wien.gv.at/daten/geo?service=WFS&version=1.1.0"
           "&request=GetFeature&typeName=ogdwien:FRANZKATOGD"
           "&outputFormat=json&srsName=EPSG:31256&sortBy=OBJECTID")
WMS_URL = ("https://data.wien.gv.at/daten/wms?service=WMS&version=1.1.1"
           "&request=GetMap&layers=GENLPLAN1904OGD&styles="
           "&srs=EPSG:31256&format=image/png")

# Franziszeischer Kataster TYP values that are buildings
BUILDING_TYPS = ["Stein", "Holz", "Kirche", "Militaer", "Oefftl"]

FRAC_1829 = 0.30    # min. area overlap with an 1829 building polygon
DARK_1904 = 0.12    # min. interior dark-pixel fraction on the 1904 plan
TILE_M = 1000       # WMS tile edge (m) at 1 m/px
BLANK_TILE = 0.002  # tile dark share below this = off-sheet (no coverage)


def load_franzkat() -> gpd.GeoDataFrame:
    """1829 Kataster polygons (cached; paged WFS download otherwise)."""
    if FK_GPKG.exists():
        log.info(f"Loading cached Franziszeischer Kataster from {FK_GPKG}…")
        return gpd.read_file(FK_GPKG)
    import requests, pandas as pd
    log.info("Downloading FRANZKATOGD via WFS (paged)…")
    parts, start = [], 0
    while True:
        r = requests.get(f"{WFS_URL}&maxFeatures=40000&startIndex={start}",
                         timeout=300)
        r.raise_for_status()
        g = gpd.read_file(io.BytesIO(r.content))
        if not len(g):
            break
        parts.append(g)
        start += len(g)
        log.info(f"  {start:,} features…")
        if len(g) < 40000:
            break
    fk = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True)
                          ).set_crs(EPSG_MGI, allow_override=True)
    fk[["TYP", "geometry"]].to_file(FK_GPKG, driver="GPKG")
    log.info(f"  {len(fk):,} features (cached -> {FK_GPKG})")
    return fk


def overlay_1829(bld: gpd.GeoDataFrame) -> np.ndarray:
    """Fraction of each footprint's area covered by 1829 buildings."""
    import shapely
    fk = load_franzkat()
    fkb = fk[fk["TYP"].isin(BUILDING_TYPS)].to_crs(EPSG_MGI)
    log.info(f"  1829 building polygons: {len(fkb):,} "
             f"({', '.join(BUILDING_TYPS)})")

    t0 = time.time()
    bgeo = bld.geometry.values
    fgeo = fkb.geometry.values
    il, jr = fkb.sindex.query(bgeo, predicate="intersects")
    log.info(f"  {len(il):,} intersecting pairs "
             f"({time.time()-t0:.0f}s, spatial index)")

    inter = shapely.area(shapely.intersection(bgeo[il], fgeo[jr]))
    overlap = np.zeros(len(bld))
    np.add.at(overlap, il, inter)
    frac = overlap / shapely.area(bgeo)
    log.info(f"  overlay done in {time.time()-t0:.0f}s")
    return frac


# ── Generalstadtplan 1904 raster test ───────────────────────────────────────

def _tile_key(tx: int, ty: int) -> Path:
    return TILE_DIR / f"{tx}_{ty}.npy"


def fetch_tile(tx: int, ty: int, session) -> np.ndarray:
    """1 m/px greyscale tile (TILE_M × TILE_M), cached as .npy."""
    p = _tile_key(tx, ty)
    if p.exists():
        return np.load(p)
    from PIL import Image
    x0, y0 = tx * TILE_M, ty * TILE_M
    url = (f"{WMS_URL}&bbox={x0},{y0},{x0+TILE_M},{y0+TILE_M}"
           f"&width={TILE_M}&height={TILE_M}")
    r = session.get(url, timeout=120)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("L")
    a = np.asarray(img, dtype=np.uint8)
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(p, a)
    return a


def classify_1904(bld: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Interior dark-pixel fraction on the 1904 plan + coverage flag."""
    import requests
    from matplotlib.path import Path as MplPath

    session = requests.Session()
    dark = np.full(len(bld), np.nan)
    cover = np.zeros(len(bld), dtype=bool)

    # group buildings by the tile containing their centroid; footprints
    # crossing a tile edge are sampled on the centroid tile only —
    # at 1 m/px a partial interior sample is plenty
    cents = bld.geometry.centroid
    txs = (cents.x.values // TILE_M).astype(int)
    tys = (cents.y.values // TILE_M).astype(int)
    tiles = {}
    for i, (tx, ty) in enumerate(zip(txs, tys)):
        tiles.setdefault((tx, ty), []).append(i)
    log.info(f"  {len(tiles):,} tiles to fetch/classify "
             f"({len(bld):,} buildings)")

    t0 = time.time()
    for k, ((tx, ty), idxs) in enumerate(sorted(tiles.items())):
        a = fetch_tile(tx, ty, session)
        tile_dark = float((a < 128).mean())
        if tile_dark < BLANK_TILE:      # off the 1904 sheet
            continue
        x0, y0 = tx * TILE_M, ty * TILE_M
        for i in idxs:
            g = bld.geometry.values[i]
            # shrink 1.5 m so parcel outlines don't count as "dark"
            gi = g.buffer(-1.5)
            if gi.is_empty:
                gi = g
            bx0, by0, bx1, by1 = gi.bounds
            c0 = max(int(bx0 - x0), 0); c1 = min(int(bx1 - x0) + 1, TILE_M)
            r0 = max(int(by0 - y0), 0); r1 = min(int(by1 - y0) + 1, TILE_M)
            if c1 <= c0 or r1 <= r0:
                continue
            xs, ys = np.meshgrid(np.arange(c0, c1) + x0 + 0.5,
                                 np.arange(r0, r1) + y0 + 0.5)
            pts = np.column_stack([xs.ravel(), ys.ravel()])
            polys = getattr(gi, "geoms", [gi])
            inside = np.zeros(len(pts), dtype=bool)
            for poly in polys:
                mp = MplPath(np.asarray(poly.exterior.coords))
                inside |= mp.contains_points(pts)
            if inside.sum() < 4:        # too small to judge
                continue
            # tile rows: row 0 is the *north* edge (image origin top-left)
            rows = (TILE_M - 1 - (pts[inside, 1] - y0)).astype(int)
            cols = (pts[inside, 0] - x0).astype(int)
            dark[i] = float((a[rows, cols] < 128).mean())
            cover[i] = True
        if (k + 1) % 50 == 0 or k == len(tiles) - 1:
            done = (~np.isnan(dark)).sum()
            log.info(f"  tile {k+1}/{len(tiles)} — {done:,} buildings "
                     f"classified [{(time.time()-t0)/60:.1f} min]")
    return dark, cover


def main():
    p = argparse.ArgumentParser(description="🗺 Wien 1829/1904 calibration")
    p.add_argument("--skip-1904", action="store_true",
                   help="only the 1829 vector overlay")
    args = p.parse_args()

    log.info("Loading DKM buildings (NS 41)…")
    nfl = gpd.read_file(DKM_GPKG)
    bld = nfl[nfl["NS"] == 41].to_crs(EPSG_MGI)
    nfl_fid = bld.index.to_numpy()          # key into the NFL gpkg
    bld = bld.reset_index(drop=True)
    log.info(f"  {len(bld):,} footprints")

    log.info("─" * 50)
    log.info("  [1/2] 1829 — Franziszeischer Kataster (vector overlay)")
    log.info("─" * 50)
    frac29 = overlay_1829(bld)
    ex29 = frac29 >= FRAC_1829
    log.info(f"  existed_1829: {ex29.sum():,} of {len(bld):,} "
             f"({ex29.mean():.1%}) at overlap ≥ {FRAC_1829}")

    dark04 = np.full(len(bld), np.nan)
    cov04 = np.zeros(len(bld), dtype=bool)
    if not args.skip_1904:
        log.info("─" * 50)
        log.info("  [2/2] 1904 — Generalstadtplan (raster dark-fraction)")
        log.info("─" * 50)
        dark04, cov04 = classify_1904(bld)
        v = dark04[cov04 & ~np.isnan(dark04)]
        log.info(f"  coverage: {cov04.sum():,} buildings on-sheet; "
                 f"dark-fraction quartiles "
                 f"{np.percentile(v, [25, 50, 75]).round(3)}")
        # QA: 1829 buildings should read dark in 1904
        m = cov04 & ex29
        if m.sum():
            log.info(f"  QA — median dark of 1829-confirmed buildings: "
                     f"{np.nanmedian(dark04[m]):.3f} (expect ≫ {DARK_1904})")
    ex04 = cov04 & (dark04 >= DARK_1904)

    out = gpd.GeoDataFrame({
        "nfl_fid": nfl_fid,
        "frac_1829": frac29.round(4),
        "existed_1829": ex29,
        "dark_1904": np.round(dark04, 4),
        "cover_1904": cov04,
        "existed_1904": ex04,
    }, geometry=bld.geometry, crs=bld.crs)
    out.to_file(OUT_GPKG, driver="GPKG")
    log.info(f"  -> {OUT_GPKG}")

    summary = {
        "n_buildings": int(len(bld)),
        "existed_1829": int(ex29.sum()),
        "cover_1904": int(cov04.sum()),
        "existed_1904": int(ex04.sum()),
        "thresholds": {"frac_1829": FRAC_1829, "dark_1904": DARK_1904},
        "sources": ("FRANZKATOGD + GENLPLAN1904OGD © Stadt Wien "
                    "(CC BY 4.0) · DKM © BEV (CC BY 4.0)"),
    }
    with open("data/calibration_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    log.info(f"  ✅ {json.dumps(summary['thresholds'])} — "
             f"1829: {ex29.sum():,} · 1904: {ex04.sum():,} "
             f"(coverage {cov04.sum():,})")


if __name__ == "__main__":
    main()
