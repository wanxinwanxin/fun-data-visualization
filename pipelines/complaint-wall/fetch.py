"""Download the two raw complaint data sets for The Complaint Wall.

Sources:
  1. CFPB Consumer Complaint Database (zipped CSV, about 360 MB).
  2. NHTSA vehicle complaints flat file (zipped tab-delimited text).

Run from the repository root:
  .venv/bin/python3 -I pipelines/complaint-wall/fetch.py

The script writes into data/raw/complaint-wall/. It skips a file that is
already complete. It retries each download up to four times.
"""
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "complaint-wall"
RAW.mkdir(parents=True, exist_ok=True)

SOURCES = {
    "cfpb_complaints.csv.zip": "https://files.consumerfinance.gov/ccdb/complaints.csv.zip",
    "nhtsa_FLAT_CMPL.zip": "https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip",
    "nhtsa_CMPL.txt": "https://static.nhtsa.gov/odi/ffdd/cmpl/CMPL.txt",
}

HEADERS = {"User-Agent": "thirteen-rooms-gallery/1.0 (data visualization, contact: see README)"}


def looks_complete(dest):
    """Return True when the file on disk is a readable archive or a non-empty text file."""
    if not dest.exists() or dest.stat().st_size == 0:
        return False
    if dest.suffix != ".zip":
        return True
    try:
        with zipfile.ZipFile(dest) as z:
            return len(z.infolist()) > 0
    except zipfile.BadZipFile:
        return False


def download(name, url):
    """Stream one file to disk, then check that the archive opens.

    The NHTSA server sends the zip with gzip transfer encoding, so the
    Content-Length header does not match the bytes on disk. The script
    therefore does not compare sizes. It opens the archive instead.
    """
    dest = RAW / name
    part = RAW / (name + ".part")
    if looks_complete(dest):
        print(f"skip {name}: already complete ({dest.stat().st_size} bytes)")
        return
    for attempt in range(1, 5):
        try:
            with requests.get(url, headers=HEADERS, stream=True, timeout=120) as r:
                r.raise_for_status()
                done = 0
                t0 = time.time()
                with open(part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if time.time() - t0 > 15:
                            t0 = time.time()
                            print(f"  {name}: {done / 1e6:.0f} MB", flush=True)
            if not looks_complete(part):
                raise IOError("downloaded file is not a readable archive")
            part.rename(dest)
            print(f"done {name}: {dest.stat().st_size} bytes")
            return
        except (requests.RequestException, IOError) as e:
            print(f"  attempt {attempt} for {name} failed: {e}", file=sys.stderr)
            time.sleep(10 * attempt)
    raise SystemExit(f"could not download {name}")


if __name__ == "__main__":
    for name, url in SOURCES.items():
        download(name, url)
