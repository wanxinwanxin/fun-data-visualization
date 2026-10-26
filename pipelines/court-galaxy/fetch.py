"""Fetch the raw data for the Citation Galaxy room.

Source: the Caselaw Access Project (CAP) static archive of the United States
Reports, hosted by the Free Law Project at https://static.case.law/us/.
Each volume has one CasesMetadata.json file. The file lists every case in the
volume with its name, decision date, citations, and a cites_to list. The
cites_to list holds the CAP case ids of the cited cases. That is enough to
build the Supreme Court citation network without the opinion texts.

The script also downloads d3 7.9.0 for the offline force layout.

Optional source: the Supreme Court Database (SCDB). The script tries to fetch
the legacy and modern case-centered files. They give the issue area of each
case. When the SCDB server does not answer, the script continues without it.

Run from the repository root:
  .venv/bin/python3 -I pipelines/court-galaxy/fetch.py
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "court-galaxy"
VOLS = RAW / "us"
BASE = "https://static.case.law/us/"
SCDB_FILES = [
    ("http://scdb.wustl.edu/_brickFiles/Legacy_07/SCDB_Legacy_07_caseCentered_Citation.csv.zip",
     "SCDB_Legacy_07_caseCentered_Citation.csv.zip"),
    ("http://scdb.wustl.edu/_brickFiles/2024_01/SCDB_2024_01_caseCentered_Citation.csv.zip",
     "SCDB_2024_01_caseCentered_Citation.csv.zip"),
]
D3_URL = "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"
HEADERS = {"User-Agent": "thirteen-rooms-gallery/1.0 (data visualization, contact via repository)"}


def get(url, tries=4, timeout=120):
    """Download one URL with retries. Return the response or None."""
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            print(f"  status {r.status_code} for {url}")
        except requests.RequestException as e:
            print(f"  error {e.__class__.__name__} for {url}")
        time.sleep(2 * (i + 1))
    return None


def fetch_volumes():
    VOLS.mkdir(parents=True, exist_ok=True)
    index = get(BASE)
    if index is None:
        print("The CAP index is not reachable.")
        sys.exit(1)
    vols = sorted({int(v) for v in re.findall(r"static\.case\.law/us/(\d+)/", index.text)})
    print(f"{len(vols)} volumes listed, {vols[0]} to {vols[-1]}")
    done = 0
    total_bytes = 0
    for v in vols:
        out = VOLS / f"{v}.json"
        if out.exists() and out.stat().st_size > 2:
            done += 1
            total_bytes += out.stat().st_size
            continue
        r = get(f"{BASE}{v}/CasesMetadata.json")
        if r is None:
            print(f"  volume {v} failed")
            continue
        try:
            cases = r.json()
        except ValueError:
            print(f"  volume {v} is not valid JSON")
            continue
        out.write_text(json.dumps(cases, separators=(",", ":")))
        done += 1
        total_bytes += out.stat().st_size
        if done % 25 == 0:
            print(f"  {done}/{len(vols)} volumes, {total_bytes / 1e6:.0f} MB")
        time.sleep(0.15)
    print(f"volumes on disk: {done}/{len(vols)}, {total_bytes / 1e6:.0f} MB")


def fetch_d3():
    """Download d3 7.9.0. layout.cjs uses its force simulation in Node."""
    out = RAW / "d3.min.js"
    if out.exists() and out.stat().st_size > 100000:
        print("d3.min.js present")
        return
    r = get(D3_URL)
    if r is None:
        print("d3.min.js not reachable")
        return
    out.write_bytes(r.content)
    print(f"d3.min.js saved ({len(r.content) / 1e3:.0f} kB)")


def fetch_scdb():
    for url, name in SCDB_FILES:
        out = RAW / name
        if out.exists() and out.stat().st_size > 1000:
            print(f"SCDB file present: {name}")
            continue
        r = get(url, tries=2, timeout=60)
        if r is None:
            print(f"SCDB file not reachable: {name}")
            continue
        out.write_bytes(r.content)
        print(f"SCDB file saved: {name} ({len(r.content) / 1e6:.1f} MB)")


if __name__ == "__main__":
    fetch_volumes()
    fetch_d3()
    fetch_scdb()
