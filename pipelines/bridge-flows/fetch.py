"""Download bridge volume data from the DefiLlama dimensions API.

Stdlib only. Run from the repository root:

    .venv/bin/python3 -I pipelines/bridge-flows/fetch.py

The script writes raw JSON into data/raw/bridge-flows/. It caches every
response. When a file exists, the script does not download it again.

Endpoints:
  https://api.llama.fi/overview/bridges
      The list of bridge protocols with category, chains and totals.
  https://api.llama.fi/summary/bridges/<slug>?dataType=dailyOutgoingVolume
      Daily USD value that leaves each chain through the bridge.
  https://api.llama.fi/summary/bridges/<slug>?dataType=dailyIncomingVolume
      Daily USD value that arrives on each chain through the bridge.

Note: the older bridges.llama.fi endpoints now answer HTTP 402 (paid plan).
The dimensions API above is the open replacement and has the same data.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "bridge-flows"
RAW.mkdir(parents=True, exist_ok=True)

BASE = "https://api.llama.fi"
UA = "thirteen-rooms-gallery/1.0 (data visualization, contact: see README)"
# Categories that describe a bridge. Aggregators route through other bridges
# and would count the same transfer twice.
CATEGORIES = {"Bridge", "Canonical Bridge", "Cross Chain Bridge", "Decentralized BTC"}


def get(url, dest, tries=4):
    """Download url into dest with retries. Return the parsed JSON."""
    if dest.exists() and dest.stat().st_size > 0:
        with open(dest) as f:
            return json.load(f)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
            data = json.loads(body)
            with open(dest, "wb") as f:
                f.write(body)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  retry {i + 1} for {url}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"failed {url}: {last}")


def main():
    overview = get(f"{BASE}/overview/bridges", RAW / "overview.json")
    protos = overview["protocols"]
    print(f"{len(protos)} bridge protocols listed")
    wanted = []
    for p in protos:
        cat = p.get("category") or ""
        if cat not in CATEGORIES:
            continue
        vol = (p.get("total1y") or 0) + (p.get("total30d") or 0)
        if vol <= 0:
            continue
        wanted.append(p)
    print(f"{len(wanted)} bridges with volume in the last year")
    n = 0
    for p in wanted:
        slug = p["slug"]
        for dt in ("dailyOutgoingVolume", "dailyIncomingVolume"):
            dest = RAW / f"{slug}__{dt}.json"
            fresh = not dest.exists()
            get(f"{BASE}/summary/bridges/{slug}?dataType={dt}", dest)
            n += 1
            if fresh:
                time.sleep(0.4)
        print(f"  {slug} ok")
    print(f"done, {n} summary files in {RAW}")


if __name__ == "__main__":
    main()
