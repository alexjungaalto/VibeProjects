#!/usr/bin/env python3
"""Resolve coordinates for the shortlisted pages via Semantic MediaWiki.

`action=browsebysubject` returns one page's semantic properties, including the
`Koordinaten` the wiki derives from its address. Used only for the final
shortlist, so the per-page cost is irrelevant and we avoid the ask-API's
offset cap entirely.
"""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path

API = "https://www.geschichtewiki.wien.gv.at/api.php"
ROOT = Path(__file__).resolve().parent.parent
CAND = ROOT / "data" / "candidates.json"
OUT = ROOT / "data" / "coordinates.json"
UA = {"User-Agent": "ArisierungWien1/1.0 (historical research)"}


def browse(title):
    url = API + "?" + urllib.parse.urlencode({
        "action": "browsebysubject", "format": "json",
        "subject": title.replace(" ", "_")})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as fh:
        return json.load(fh)


def extract(blob):
    """Pick the 1st-district address of a page, with its own coordinates.

    browsebysubject returns one subobject per address under `sobj`, each
    carrying its own Bezirk / Strasse / Hausnummer / Koordinaten. Taking the
    first coordinate on the page was wrong: a person who lived at several
    addresses, or a firm that moved, then landed wherever its other address
    was - Peter Altenberg at Franzensbrueckenstrasse 3 in the 2nd district
    instead of Dorotheergasse 3 in the 1st. Selecting the subobject whose
    Bezirk is exactly "1" fixes it at the source.
    """
    def props(node):
        """property -> list of plain item values, for one subobject."""
        out = {}
        for entry in node.get("data", []) or []:
            prop = entry.get("property")
            items = [i.get("item") for i in (entry.get("dataitem") or [])]
            out[prop] = [str(i).split("#")[0].replace("_", " ")
                         for i in items if i is not None]
        return out

    query = blob.get("query", blob)
    here, other, kinds = [], [], []

    for sub in query.get("sobj", []) or []:
        pr = props(sub)
        coord = None
        for raw in pr.get("Koordinaten", []):
            if "," in raw:
                lat, lon = raw.split(",")[:2]
                try:
                    coord = (float(lat), float(lon))
                except ValueError:
                    coord = None
        street = (pr.get("Straße") or [""])[0].strip()
        nr = (pr.get("Hausnummer") or [""])[0].strip()
        bez = (pr.get("Bezirk") or [""])[0].strip()
        addr = f"{street} {nr}".strip()
        if not addr:
            continue
        (here if bez == "1" else other).append((addr, coord))

    for entry in query.get("data", []) or []:
        if entry.get("property") == "Art_des_Bauwerks":
            kinds = [str(i.get("item", "")).split("#")[0].replace("_", " ")
                     for i in (entry.get("dataitem") or [])]

    # Fall back to the page's own coordinate only if it is in the 1st district.
    page_coord = None
    for entry in query.get("data", []) or []:
        if entry.get("property") == "Koordinaten":
            for i in entry.get("dataitem") or []:
                raw = str(i.get("item", ""))
                if "," in raw:
                    try:
                        lat, lon = (float(x) for x in raw.split(",")[:2])
                        page_coord = (lat, lon)
                    except ValueError:
                        pass

    chosen = next((c for _, c in here if c), None)
    return {
        "lat": chosen[0] if chosen else None,
        "lon": chosen[1] if chosen else None,
        "addresses": [a for a, _ in here],
        "addresses_other": [a for a, _ in other],
        "page_coord": page_coord,
        "kind": kinds[0] if kinds else None,
    }


# Many subobjects carry an address but no coordinates of their own. The wiki
# also keeps a dedicated "Adresse:<Street> <Nr>" page per address, and those do
# carry exact coordinates - so a failed lookup is resolved there rather than
# falling back to whatever other district the page also touches.
ADDR_NOISE = re.compile(r"\s*\((Verkehrsfläche|Platz|Gasse|Straße)\)\s*")


def address_coord(addr):
    """Resolve one street address via its Adresse: page."""
    clean = ADDR_NOISE.sub(" ", addr).strip()
    clean = re.split(r"\s*[/(]", clean)[0].strip()       # "Graben 7/ Seilergasse 4"
    if not re.search(r"\d", clean):
        return None
    try:
        blob = browse("Adresse:" + clean)
    except Exception:
        return None
    query = blob.get("query", blob)
    if "error" in blob:
        return None
    bez, coord = None, None
    for entry in query.get("data", []) or []:
        prop = entry.get("property")
        items = [str(i.get("item", "")) for i in (entry.get("dataitem") or [])]
        if prop == "Bezirk" and items:
            bez = items[0].split("#")[0]
        elif prop == "Koordinaten":
            for raw in items:
                if "," in raw:
                    try:
                        coord = tuple(float(x) for x in raw.split(",")[:2])
                    except ValueError:
                        pass
    return coord if (coord and bez == "1") else None


def main():
    titles = json.loads(CAND.read_text())
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [t for t in titles if t not in cache]
    print(f"{len(titles)} candidates, {len(todo)} to resolve")

    for n, title in enumerate(todo, 1):
        try:
            rec = extract(browse(title))
        except Exception as exc:
            print(f"  ! {title}: {exc}")
            cache[title] = {}
            continue

        if rec["lat"] is None:                   # resolve via Adresse: pages
            for addr in rec["addresses"]:
                hit = address_coord(addr)
                if hit:
                    rec["lat"], rec["lon"] = hit
                    rec["coord_source"] = f"Adresse:{addr}"
                    break
                time.sleep(0.12)
        else:
            rec["coord_source"] = "subobject"

        if rec["lat"] is None and rec.get("page_coord"):
            lat, lon = rec["page_coord"]
            if 48.1975 <= lat <= 48.2215 and 16.3550 <= lon <= 16.3860:
                rec["lat"], rec["lon"] = lat, lon
                rec["coord_source"] = "page"

        cache[title] = rec
        if n % 25 == 0:
            OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
            print(f"  {n}/{len(todo)}", flush=True)
        time.sleep(0.2)

    OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    got = sum(1 for v in cache.values() if v.get("lat"))
    print(f"\n{got}/{len(cache)} with coordinates -> {OUT}")


if __name__ == "__main__":
    main()
