#!/usr/bin/env python3
"""Download the wikitext of the whole wiki, keeping only Bezirk-1 pages.

63,463 main-namespace pages are fetched in batches of 50 and discarded unless
their {{Adresse}} template says Bezirk=1. Scanning everything and filtering
locally is the only way to get a complete 1st-district universe (see
00_enumerate_titles.py for why Semantic MediaWiki cannot be trusted here).

Resumable: progress is checkpointed, so an interrupted run continues.
Serially this takes ~2 hours (each 50-page batch is a multi-MB response), so a
small thread pool is used - kept deliberately modest, this is a public wiki.
"""
import json, re, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://www.geschichtewiki.wien.gv.at/api.php"
ROOT = Path(__file__).resolve().parent.parent
TITLES = ROOT / "data" / "all_titles.json"
OUT = ROOT / "data" / "wikitext.json"
STATE = ROOT / "data" / "fetch_state.json"
UA = {"User-Agent": "ArisierungWien1/1.0 (historical research)"}
BATCH = 50
WORKERS = 6

# |Bezirk=1  but not  |Bezirk=10 .. |Bezirk=23
BEZIRK1 = re.compile(r"\|\s*Bezirk\s*=\s*1\s*(?=[\|\}\n\r]|$)")


def fetch(titles):
    params = {"action": "query", "format": "json", "prop": "revisions",
              "rvprop": "content", "rvslots": "main", "titles": "|".join(titles)}
    req = urllib.request.Request(
        API, data=urllib.parse.urlencode(params).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=180) as fh:
        return json.load(fh)


def scan(chunk):
    """Fetch one batch and return only its Bezirk-1 pages."""
    for attempt in range(3):
        try:
            data = fetch(chunk)
            break
        except Exception as exc:                     # transient API hiccup
            print(f"    retry {attempt + 1}: {exc}", flush=True)
            time.sleep(3 * (attempt + 1))
    else:
        return None                                  # leave chunk un-done
    out = {}
    for page in data.get("query", {}).get("pages", {}).values():
        revs = page.get("revisions") or []
        if not revs:
            continue
        text = revs[0]["slots"]["main"].get("*", "")
        if text and BEZIRK1.search(text):
            out[page["title"]] = text
    return out


def main():
    titles = json.loads(TITLES.read_text())
    kept = json.loads(OUT.read_text()) if OUT.exists() else {}
    done = set(json.loads(STATE.read_text())) if STATE.exists() else set()

    todo = [t for t in titles if t not in done]
    print(f"{len(titles)} pages total, {len(done)} already scanned, "
          f"{len(todo)} to go, {len(kept)} Bezirk-1 pages kept so far",
          flush=True)

    chunks = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    lock = threading.Lock()
    progress = {"n": 0}

    def work(chunk):
        result = scan(chunk)
        with lock:
            if result is not None:
                kept.update(result)
                done.update(chunk)
            progress["n"] += 1
            n = progress["n"]
            if n % 25 == 0:
                OUT.write_text(json.dumps(kept, ensure_ascii=False))
                STATE.write_text(json.dumps(sorted(done)))
                print(f"  batch {n}/{len(chunks)} "
                      f"({100 * n / len(chunks):4.1f}%)  "
                      f"Bezirk-1 pages: {len(kept)}", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, chunks))

    OUT.write_text(json.dumps(kept, ensure_ascii=False))
    STATE.write_text(json.dumps(sorted(done)))
    chars = sum(len(v) for v in kept.values())
    print(f"\nDONE: {len(kept)} Bezirk-1 pages, {chars:,} chars -> {OUT}",
          flush=True)


if __name__ == "__main__":
    main()
