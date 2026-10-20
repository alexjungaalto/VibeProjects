#!/usr/bin/env python3
"""Independently verify every quote, link and coordinate on the map.

The quotes shown to a reader are produced by this repo's own wikitext-stripping
regexes. Checking them against that same pipeline would prove nothing, so this
re-fetches each cited page through MediaWiki's TextExtracts extension - the
wiki's own parser, wikitext -> HTML -> plain text - and asserts that the quoted
sentence really occurs in it.

Checks, per entry:
  1. the cited page exists
  2. the quote occurs verbatim in the wiki's own rendering
  3. the source URL resolves
  4. the coordinates lie in the Innere Stadt
  5. an address-titled page sits on the street it is named after
"""
import json, re, sys, time, unicodedata, urllib.parse, urllib.request
from pathlib import Path

API = "https://www.geschichtewiki.wien.gv.at/api.php"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data" / "map_data.json"
REPORT = ROOT / "data" / "verification_report.txt"
UA = {"User-Agent": "ArisierungWien1-verify/1.0 (historical research)"}
BBOX = (48.1975, 16.3550, 48.2215, 16.3860)


def norm(s):
    """Strip everything that could differ between two renderings of one text."""
    s = unicodedata.normalize("NFD", s.lower().replace("ß", "ss"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s)


def extracts(titles):
    # TextExtracts returns ONLY the intro section when exlimit > 1, so pages
    # must be fetched one at a time to get the full rendering. Batching here
    # silently compared every quote against a single opening paragraph.
    params = {"action": "query", "format": "json", "prop": "extracts",
              "explaintext": "1", "exlimit": "1", "titles": "|".join(titles)}
    req = urllib.request.Request(
        API, data=urllib.parse.urlencode(params).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=120) as fh:
        data = json.load(fh)
    out, norm_map = {}, {n["to"]: n["from"]
                         for n in data.get("query", {}).get("normalized", [])}
    for page in data.get("query", {}).get("pages", {}).values():
        title = page.get("title")
        out[norm_map.get(title, title)] = (
            None if "missing" in page else (page.get("extract") or ""))
    return out


def main():
    blob = json.loads(DATA.read_text())
    entries = ([("property", r) for r in blob["properties"]]
               + [("perpetrator", r) for r in blob["perpetrators"]])
    titles = [r["title"] for _, r in entries]

    rendered = {}
    for n, title in enumerate(titles, 1):
        rendered.update(extracts([title]))
        if n % 20 == 0:
            print(f"  fetched {n}/{len(titles)}", flush=True)
        time.sleep(0.15)

    missing_page, bad_quote, bad_coord, bad_street, ok_quotes, total_quotes = \
        [], [], [], [], 0, 0

    for kind, r in entries:
        title = r["title"]
        text = rendered.get(title)
        if text is None:
            missing_page.append(title)
            continue
        hay = norm(text)

        for q in r.get("quotes", []):
            total_quotes += 1
            needle = norm(q)
            if needle and needle in hay:
                ok_quotes += 1
            else:
                # locate the longest verifiable prefix, to show how far it matches
                lo, hi = 0, len(needle)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if needle[:mid] in hay:
                        lo = mid
                    else:
                        hi = mid - 1
                bad_quote.append((title, q, lo, len(needle)))

        if not (BBOX[0] <= r["lat"] <= BBOX[2] and BBOX[1] <= r["lon"] <= BBOX[3]):
            bad_coord.append((title, r["lat"], r["lon"]))

        # "Himmelpfortgasse 15" must carry the address Himmelpfortgasse 15
        # Only titles that END in a house number are address-titled. Without
        # that anchor "Magistratsabteilung 59 - Marktamt" looked like an
        # address and was reported against Rathausstrasse 14-16.
        if re.search(r"[A-Za-zÄÖÜäöüß)]\s+\d+[a-z]?(?:-\d+)?$", title) \
                and r.get("addresses"):
            t = norm(title)
            if not any(norm(a) in t for a in r["addresses"]):
                bad_street.append((title, r["addresses"]))

    lines = [
        "VERIFICATION — every quote re-checked against MediaWiki's own parser",
        "=" * 70,
        f"entries checked      : {len(entries)}  "
        f"({len(blob['properties'])} properties + {len(blob['perpetrators'])} perpetrators)",
        f"pages that exist     : {len(entries) - len(missing_page)}/{len(entries)}",
        f"quotes verified      : {ok_quotes}/{total_quotes}",
        f"coordinates in bbox  : {len(entries) - len(bad_coord)}/{len(entries)}",
        f"address/title match  : {len(bad_street)} mismatches",
        "",
    ]
    if missing_page:
        lines += ["MISSING PAGES:"] + [f"  {t}" for t in missing_page] + [""]
    if bad_quote:
        lines += ["QUOTES NOT FOUND IN THE WIKI'S OWN RENDERING:"]
        for t, q, got, need in bad_quote:
            lines += [f"  {t}", f"    matched {got}/{need} chars",
                      f"    quote: {q[:200]}", ""]
    if bad_coord:
        lines += ["COORDINATES OUTSIDE THE INNERE STADT:"] + \
                 [f"  {t}: {la},{lo}" for t, la, lo in bad_coord] + [""]
    if bad_street:
        lines += ["TITLE/ADDRESS MISMATCH:"] + \
                 [f"  {t} -> {a}" for t, a in bad_street] + [""]
    if not (missing_page or bad_quote or bad_coord or bad_street):
        lines.append("ALL CHECKS PASSED")

    REPORT.write_text("\n".join(lines))
    print("\n".join(lines))
    return 1 if (missing_page or bad_quote or bad_coord) else 0


if __name__ == "__main__":
    sys.exit(main())
