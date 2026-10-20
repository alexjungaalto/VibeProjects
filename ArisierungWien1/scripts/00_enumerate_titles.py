#!/usr/bin/env python3
"""Enumerate every main-namespace page title in the Wien Geschichte Wiki.

Why not Semantic MediaWiki: an `ask` query for [[Bezirk::1]] silently stops
yielding new subjects past roughly offset 10000 (address subobjects dominate
the result stream), so it returned 3567 subjects while demonstrably missing
house pages such as "Kaerntner Strasse 10". `list=allpages` paginates
exhaustively via apcontinue and is the only trustworthy enumeration.
"""
import json, time, urllib.parse, urllib.request
from pathlib import Path

API = "https://www.geschichtewiki.wien.gv.at/api.php"
OUT = Path(__file__).resolve().parent.parent / "data" / "all_titles.json"
UA = {"User-Agent": "ArisierungWien1/1.0 (historical research)"}


def main():
    titles, cont, page = [], None, 0
    while True:
        params = {"action": "query", "list": "allpages", "aplimit": "500",
                  "apnamespace": "0", "format": "json"}
        if cont:
            params["apcontinue"] = cont
        url = API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as fh:
            data = json.load(fh)
        titles.extend(p["title"] for p in data["query"]["allpages"])
        page += 1
        if page % 10 == 0:
            print(f"  {len(titles)} titles...", flush=True)
        cont = data.get("continue", {}).get("apcontinue")
        if not cont:
            break
        time.sleep(0.15)

    OUT.write_text(json.dumps(sorted(set(titles)), ensure_ascii=False))
    print(f"{len(set(titles))} main-namespace pages -> {OUT}")


if __name__ == "__main__":
    main()
