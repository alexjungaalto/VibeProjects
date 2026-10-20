#!/usr/bin/env python3
"""Fetch DÖW Memento Wien addresses and keep the 1st-district subset.

Memento Wien (memento.wien, Dokumentationsarchiv des oesterreichischen
Widerstandes) maps the LAST KNOWN RESIDENTIAL ADDRESS of victims of Nazi
persecution. That is NOT the same as property ownership - most of these people
were tenants. The endpoint below is the one its AngularJS front-end uses.
"""
import json, urllib.request
from pathlib import Path

URL = "https://www.memento.wien/geojson?v=3.2"
OUT = Path(__file__).resolve().parent.parent / "data" / "memento_bezirk1.json"
UA = {"User-Agent": "ArisierungWien1/1.0 (historical research)"}


def main():
    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as fh:
        raw = json.load(fh)

    print(f"Memento Wien: {raw['iTotalRecords']} addresses, "
          f"{raw['iTotalRecordsPersons']} persons (all of Vienna)")

    features = []
    for item in raw["aaData"]:
        props = item["properties"]
        label = props.get("street_with_nr") or ""
        if not label.startswith("Wien 1,"):
            continue
        geom = item.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "id": item["id"],
                # strip the redundant "Wien 1, " prefix
                "address": label.replace("Wien 1, ", "", 1),
                "persons_nr": props.get("persons_nr") or 0,
                "persons": [p["fullname"] for p in (props.get("persons") or [])],
                "url": f"https://www.memento.wien/address/{item['id']}/",
            },
        })

    features.sort(key=lambda f: -f["properties"]["persons_nr"])
    total = sum(f["properties"]["persons_nr"] for f in features)
    out = {"type": "FeatureCollection", "features": features}
    OUT.write_text(json.dumps(out, ensure_ascii=False))
    print(f"Bezirk 1: {len(features)} addresses, {total} persons")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
