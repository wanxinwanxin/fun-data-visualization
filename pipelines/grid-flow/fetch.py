"""Download the raw data for the room "The Grid Breathes".

Sources:
  1. EIA-930 six-month bulk files for 2024 (interchange and balance).
  2. EIA-860 annual zip for 2024. The zip holds the plant file with
     balancing authority codes and plant coordinates.

The script streams each file to data/raw/grid-flow/. It skips a file that
already exists. Delete a file to download it again. Each download gets
three tries.
Run from the repository root:
  .venv/bin/python3 -I pipelines/grid-flow/fetch.py
"""
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "grid-flow"
RAW.mkdir(parents=True, exist_ok=True)

BASE_930 = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/"
FILES = [
    (BASE_930 + "EIA930_INTERCHANGE_2024_Jan_Jun.csv", "EIA930_INTERCHANGE_2024_Jan_Jun.csv"),
    (BASE_930 + "EIA930_INTERCHANGE_2024_Jul_Dec.csv", "EIA930_INTERCHANGE_2024_Jul_Dec.csv"),
    (BASE_930 + "EIA930_BALANCE_2024_Jan_Jun.csv", "EIA930_BALANCE_2024_Jan_Jun.csv"),
    (BASE_930 + "EIA930_BALANCE_2024_Jul_Dec.csv", "EIA930_BALANCE_2024_Jul_Dec.csv"),
    ("https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602024.zip", "eia8602024.zip"),
    # State outlines. process.py uses them only for the static preview image.
    ("https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json", "states-10m.json"),
]
# Fallback for plant locations. EIA-860M also lists BA code and coordinates.
FALLBACK_860M = (
    "https://www.eia.gov/electricity/data/eia860m/archive/xls/december_generator2024.xlsx",
    "december_generator2024.xlsx",
)
HEADERS = {"User-Agent": "Mozilla/5.0 (thirteen-rooms data pipeline)"}


def download(url, dest, tries=3):
    """Stream one file to disk. Return True on success."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"skip  {dest.name} (already present)")
        return True
    for attempt in range(1, tries + 1):
        try:
            with requests.get(url, headers=HEADERS, stream=True, timeout=120) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                done = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                tmp.replace(dest)
                print(f"saved {dest.name} ({done} bytes)")
                return True
        except Exception as exc:  # noqa: BLE001
            print(f"try {attempt} failed for {url}: {exc}")
            time.sleep(5 * attempt)
    return False


def main():
    ok = True
    for url, name in FILES:
        if name == "eia8602024.zip" and (RAW / "2___Plant_Y2024.xlsx").exists():
            print("skip  eia8602024.zip (plant file already extracted)")
            continue
        if not download(url, RAW / name):
            ok = False
            print(f"FAILED {name}")
    zip_path = RAW / "eia8602024.zip"
    plant_ok = (RAW / "2___Plant_Y2024.xlsx").exists()
    if zip_path.exists() and not plant_ok:
        # Extract only the plant sheet. The rest of the zip is not needed.
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                if "Plant" in member and member.endswith(".xlsx"):
                    out = RAW / Path(member).name
                    with z.open(member) as src, open(out, "wb") as dst:
                        dst.write(src.read())
                    print(f"extracted {out.name}")
                    plant_ok = True
        zip_path.unlink()
    if not plant_ok:
        print("plant file missing, use the EIA-860M fallback")
        if not download(FALLBACK_860M[0], RAW / FALLBACK_860M[1]):
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
