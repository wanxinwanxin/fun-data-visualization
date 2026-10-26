"""Fetch raw data for the room "Ships at the Border".

Sources:
  1. NOAA Marine Cadastre AIS daily files (2023). Each day is a zip with one CSV.
     The script streams each CSV and keeps only the rows inside the bounding box
     of the Channel Islands region. It deletes each zip after the filter.
  2. NOAA Office of National Marine Sanctuaries: Channel Islands NMS boundary.
     The sanctuaries.noaa.gov link redirects to an Azure blob. The script uses
     the blob URL directly, because the redirect page refuses some clients.
  3. California Department of Fish and Wildlife: California MPAs (BIOS ds582).
     The CDFW zip holds a file geodatabase, which pyshp cannot read. The script
     queries the public ArcGIS feature service of the same data set as GeoJSON,
     limited to the bounding box.
  4. Natural Earth 10m land and minor islands (coastline).
  5. NOAA Office of Coast Survey chart data: traffic separation schemes, traffic
     lanes, precautionary areas and areas to be avoided, as GeoJSON for the box.

Run from the repository root:
  .venv/bin/python3 -I pipelines/ships-and-borders/fetch.py

Only the standard library and requests are used here.
"""
import csv
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ships-and-borders"
RAW.mkdir(parents=True, exist_ok=True)

# Bounding box of the Channel Islands region (lon_min, lon_max, lat_min, lat_max).
BBOX = (-121.2, -118.2, 33.3, 34.6)

# The 2024 daily files return 404 on the NOAA server at the time of writing.
# The 2023 files are present, so the room uses four days in June 2023.
AIS_BASE = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2023/"
AIS_DAYS = ["2023_06_15", "2023_06_16", "2023_06_17", "2023_06_18"]

STATIC = {
    "cinms_py2.zip": "https://nmssanctuaries.blob.core.windows.net/sanctuaries-prod/media/archive/library/imast/cinms_py2.zip",
    "ne_10m_land.zip": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip",
    "ne_10m_minor_islands.zip": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_minor_islands.zip",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) thirteen-rooms-fetch"}

MPA_URL = ("https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/"
           "FeatureServer/0/query?where=1%3D1&geometry=-121.2%2C33.3%2C-118.2%2C34.6"
           "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects"
           "&outFields=*&outSR=4326&f=geojson")

LANES_URL = ("https://gis.charttools.noaa.gov/arcgis/rest/services/NavigationChartData/"
             "MarineTransportation/MapServer/0/query?where=1%3D1"
             "&geometry=-121.2%2C33.3%2C-118.2%2C34.6&geometryType=esriGeometryEnvelope&inSR=4326"
             "&spatialRel=esriSpatialRelIntersects&outFields=*&outSR=4326&f=geojson")

KEEP_COLS = ["MMSI", "BaseDateTime", "LAT", "LON", "SOG", "COG", "VesselType", "Length"]


def download(url, dest, retries=4):
    """Stream a URL to a file. Retry on failure. Skip when the file exists."""
    if dest.exists() and dest.stat().st_size > 0:
        print("exists", dest.name)
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=120, headers=HEADERS) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                t0 = time.time()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if total and done % (64 << 20) < (1 << 20):
                            print(f"  {dest.name}: {done / 1e6:.0f}/{total / 1e6:.0f} MB "
                                  f"({time.time() - t0:.0f} s)", flush=True)
            tmp.rename(dest)
            print("saved", dest.name, dest.stat().st_size, "bytes")
            return
        except Exception as e:  # noqa: BLE001
            print(f"  retry {attempt + 1} for {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}")


def filter_day(day):
    """Download one AIS day, keep rows inside BBOX, write a small CSV, delete the zip."""
    out = RAW / f"ais_{day}.csv"
    if out.exists():
        print("exists", out.name)
        return
    zpath = RAW / f"AIS_{day}.zip"
    download(AIS_BASE + f"AIS_{day}.zip", zpath)
    lon0, lon1, lat0, lat1 = BBOX
    n_in = n_out = 0
    t0 = time.time()
    with zipfile.ZipFile(zpath) as z:
        member = [m for m in z.namelist() if m.lower().endswith(".csv")][0]
        with z.open(member) as raw, open(out, "w", newline="") as fo:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            header = next(reader)
            idx = [header.index(c) for c in KEEP_COLS]
            i_lat, i_lon = header.index("LAT"), header.index("LON")
            writer = csv.writer(fo)
            writer.writerow(KEEP_COLS)
            for row in reader:
                n_in += 1
                try:
                    lat = float(row[i_lat])
                    lon = float(row[i_lon])
                except ValueError:
                    continue
                if lon0 <= lon <= lon1 and lat0 <= lat <= lat1:
                    writer.writerow([row[i] for i in idx])
                    n_out += 1
    zpath.unlink()
    print(f"{day}: {n_in} rows read, {n_out} rows kept, {time.time() - t0:.0f} s", flush=True)
    with open(RAW / "counts.txt", "a") as f:
        f.write(f"{day},{n_in},{n_out}\n")


def main():
    for name, url in STATIC.items():
        download(url, RAW / name)
    download(MPA_URL, RAW / "ca_mpas_bbox.geojson")
    download(LANES_URL, RAW / "noaa_lanes_bbox.geojson")
    for day in AIS_DAYS:
        filter_day(day)
    print("done")


if __name__ == "__main__":
    main()
