#!/usr/bin/env python3
"""Merge classification + coordinates + Memento Wien into the map's data file."""
import json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLASSIFIED = ROOT / "data" / "classified.json"
COORDS = ROOT / "data" / "coordinates.json"
MEMENTO = ROOT / "data" / "memento_bezirk1.json"
DOCS = ROOT / "docs"
OUT = DOCS / "data" / "map_data.json"

# Bounding box of the Innere Stadt, used to drop coordinates the wiki resolved
# to the wrong place (a few pages carry a street centroid or a Vienna default).
BBOX = (48.1975, 16.3550, 48.2215, 16.3860)       # S, W, N, E


def in_bbox(lat, lon):
    return BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]


def main():
    cls = json.loads(CLASSIFIED.read_text())
    coords = json.loads(COORDS.read_text())
    memento = json.loads(MEMENTO.read_text())

    def place(rec):
        c = coords.get(rec["title"]) or {}
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or not in_bbox(lat, lon):
            return None
        rec = dict(rec)
        rec["lat"], rec["lon"] = lat, lon
        rec["addresses"] = c.get("addresses") or []
        rec["kind"] = c.get("kind")
        return rec

    properties = [r for r in (place(x) for x in cls["properties"]) if r]
    perpetrators = [r for r in (place(x) for x in cls["perpetrators"]) if r]

    dropped = len(cls["properties"]) - len(properties)
    counts, types = {}, {}
    for r in properties:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
        types[r["page_type"]] = types.get(r["page_type"], 0) + 1

    data = {
        "meta": {
            "properties": len(properties),
            "perpetrators": len(perpetrators),
            "dropped_no_coords": dropped,
            "by_category": counts,
            "by_type": types,
            "memento_addresses": len(memento["features"]),
            "memento_persons": sum(f["properties"]["persons_nr"]
                                   for f in memento["features"]),
        },
        "properties": properties,
        "perpetrators": perpetrators,
        "memento": memento["features"],
    }

    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    size = OUT.stat().st_size / 1e6
    print(json.dumps(data["meta"], ensure_ascii=False, indent=1))
    print(f"\n{OUT}  ({size:.1f} MB)")
    if dropped:
        print(f"note: {dropped} properties dropped for missing/implausible coordinates")


if __name__ == "__main__":
    main()
