"""Fetch raw data for the room "The Commute Bloodstream".

The script downloads four public files into data/raw/commute-bloodstream/:
  1. LODES8 origin-destination main file for Illinois (jobs 2022).
  2. Census Gazetteer 2023 national tract centroids (zip).
  3. ACS 2022 5-year table B08302 (time leaving home). The script tries the
     Census API first. The API now redirects keyless requests to a "Missing Key"
     page. When that happens, the script downloads the official table-based
     summary file for B08302 (72 MB), keeps only the Illinois county and tract
     rows, and deletes the large file.
  4. us-atlas counties-10m.json (county outlines for context).

Run from the repository root:
  .venv/bin/python3 -I pipelines/commute-bloodstream/fetch.py

The script streams each download to disk. It skips files that already exist.
"""
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "commute-bloodstream"
RAW.mkdir(parents=True, exist_ok=True)

STATE = "il"
LODES_URL = f"https://lehd.ces.census.gov/data/lodes/LODES8/{STATE}/od/{STATE}_od_main_JT00_2022.csv.gz"
GAZ_URLS = [
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_tracts_national.zip",
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2022_Gazetteer/2022_Gaz_tracts_national.zip",
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2021_Gazetteer/2021_Gaz_tracts_national.zip",
]
ACS_VARS = ",".join(["NAME"] + [f"B08302_{i:03d}E" for i in range(1, 16)])
ACS_URL = f"https://api.census.gov/data/2022/acs/acs5?get={ACS_VARS}&for=county:*&in=state:17"
ACS_SF_URL = "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/data/5YRData/acsdt5y2022-b08302.dat"
ATLAS_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/counties-10m.json"

HEADERS = {"User-Agent": "thirteen-rooms-gallery/1.0 (data visualization, contact via repo)"}


def download(url, dest, tries=4):
    """Stream one URL to dest. Retry with a short pause when the request fails."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"skip  {dest.name} (exists, {dest.stat().st_size} bytes)")
        return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, tries + 1):
        try:
            print(f"fetch {url} (attempt {attempt})")
            with requests.get(url, stream=True, timeout=120, headers=HEADERS) as r:
                r.raise_for_status()
                n = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        n += len(chunk)
            tmp.rename(dest)
            print(f"saved {dest.name} ({n} bytes)")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"error {exc}")
            if tmp.exists():
                tmp.unlink()
            time.sleep(5 * attempt)
    return False


def fetch_acs():
    """Get B08302 for Illinois. Try the API, then the summary file."""
    api_dest = RAW / "acs_b08302_il_counties.json"
    sf_dest = RAW / "acs_b08302_il.psv"
    if sf_dest.exists():
        print(f"skip  {sf_dest.name} (exists)")
        return
    if download(ACS_URL, api_dest):
        head = api_dest.read_bytes()[:200].lower()
        if head.startswith(b"[["):
            return
        print("the API answered with an HTML page instead of JSON (missing key). Use the summary file.")
        api_dest.unlink()
    big = RAW / "acsdt5y2022-b08302.dat"
    if not download(ACS_SF_URL, big):
        print("WARNING: the ACS summary file failed. process.py will use the fallback bell curve.")
        return
    kept = 0
    with open(big, "r", encoding="utf-8") as src, open(sf_dest, "w", encoding="utf-8") as out:
        for i, line in enumerate(src):
            if i == 0 or line.startswith("0500000US17") or line.startswith("1400000US17"):
                out.write(line)
                kept += 1
    big.unlink()
    print(f"saved {sf_dest.name} ({kept} rows, Illinois counties and tracts)")


def main():
    ok = True
    ok &= download(LODES_URL, RAW / "il_od_main_JT00_2022.csv.gz")
    got_gaz = False
    for url in GAZ_URLS:
        if download(url, RAW / "gaz_tracts_national.zip"):
            got_gaz = True
            break
    ok &= got_gaz
    fetch_acs()
    if not download(ATLAS_URL, RAW / "counties-10m.json"):
        print("WARNING: us-atlas failed. process.py will skip the county outlines.")
    if not ok:
        print("FAILED: a required file is missing")
        sys.exit(1)
    print("done")


if __name__ == "__main__":
    main()
