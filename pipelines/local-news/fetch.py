"""Fetch per-state page counts from the Library of Congress search API.

Source: the Chronicling America collection on loc.gov. For each topic
keyword and each decade, the script requests the "location_state" facet
index. That one small response lists every state with the number of
newspaper pages whose OCR text contains the keyword. A request with no
keyword and "dl=page" gives the total number of pages per state, which
is the denominator for the share.

The script is polite. It waits 3 seconds between requests, it retries
on 429 and 5xx with backoff, and it caches every response as JSON in
data/raw/local-news/. A rerun only downloads the files that are missing.

Run from the repository root:
    .venv/bin/python3 -I pipelines/local-news/fetch.py
"""
import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "local-news"
RAW.mkdir(parents=True, exist_ok=True)

API = "https://www.loc.gov/collections/chronicling-america/index/location_state/"
USER_AGENT = "thirteen-rooms-gallery/0.1 (data visualization research)"
THROTTLE_SECONDS = 3.0
TIMEOUT_SECONDS = 240

# One OCR-robust keyword for each topic. The search API treats "OR" as a
# word, so each topic is a single term. The label is the headline word.
TOPICS = [
    ("war", "war"),
    ("slavery", "slavery"),
    ("cholera", "cholera"),
    ("influenza", "influenza"),
    ("railroad", "railroad"),
    ("telegraph", "telegraph"),
    ("gold", "gold"),
    ("cotton", "cotton"),
    ("drought", "drought"),
    ("flood", "flood"),
    ("strike", "strike"),
    ("tariff", "tariff"),
    ("election", "election"),
    ("prohibition", "prohibition"),
    ("suffrage", "suffrage"),
    ("lynching", "lynching"),
    ("automobile", "automobile"),
    ("radio", "radio"),
    ("atomic", "atomic"),
]

# The collection runs from 1777 to 1963. The room covers 1800 to 1963.
DECADES = list(range(1800, 1970, 10))

# The us-atlas TopoJSON file gives the state shapes for the map.
ATLAS_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json"


def get_json(url, session):
    """Download one URL with retries. Return the parsed JSON."""
    delay = 10
    for attempt in range(10):
        try:
            r = session.get(url, timeout=TIMEOUT_SECONDS,
                            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        except requests.RequestException as e:
            print(f"  network error {e}, retry in {delay}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 300)
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                print("  bad JSON, retry", flush=True)
        elif r.status_code == 429 or r.status_code >= 500:
            # 429 is the rate limit. 5xx includes the Cloudflare 520 to 530 codes.
            print(f"  status {r.status_code}, retry in {delay}s", flush=True)
        else:
            raise RuntimeError(f"status {r.status_code} for {url}")
        time.sleep(delay)
        delay = min(delay * 2, 300)
    raise RuntimeError(f"gave up on {url}")


def fetch_facets(session, decade, term):
    """Return the cached or downloaded facet file for one decade and term."""
    name = f"{decade}_{term or 'TOTAL'}.json"
    path = RAW / name
    if path.exists():
        return json.loads(path.read_text())
    params = {"dates": f"{decade}/{decade + 9}", "fo": "json", "c": "1", "dl": "page"}
    if term:
        params["q"] = term
    url = API + "?" + urllib.parse.urlencode(params)
    t0 = time.time()
    data = get_json(url, session)
    states = {}
    for facet in data.get("facets", []):
        for f in facet.get("filters", []):
            states[f["title"]] = int(f["count"])
    out = {
        "decade": decade,
        "term": term,
        "url": url,
        "hits": data.get("search", {}).get("hits"),
        "states": states,
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(out, indent=0, sort_keys=True))
    print(f"  {name}: hits={out['hits']} states={len(states)} in {time.time() - t0:.1f}s", flush=True)
    time.sleep(THROTTLE_SECONDS)
    return out


def main():
    session = requests.Session()
    atlas = RAW / "states-10m.json"
    if not atlas.exists():
        print("download us-atlas states-10m.json", flush=True)
        r = session.get(ATLAS_URL, timeout=120, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        atlas.write_bytes(r.content)
    jobs = [(d, None) for d in DECADES] + [(d, t) for _, t in TOPICS for d in DECADES]
    done = 0
    for decade, term in jobs:
        print(f"{decade}s {term or 'TOTAL'}", flush=True)
        fetch_facets(session, decade, term)
        done += 1
    print(f"done, {done} facet files in {RAW}")


if __name__ == "__main__":
    sys.exit(main())
