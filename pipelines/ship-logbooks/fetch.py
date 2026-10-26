"""Fetch a sample of ICOADS Release 3.1 marine reports for the ship-logbooks room.

Source: NOAA NCEI, ICOADS R3.0 archive, final-untrim monthly IMMA1 files.
  https://www.ncei.noaa.gov/data/international-comprehensive-ocean-atmosphere/v3/archive/final-untrim/

Sampling rule:
  * Before 1750 the archive holds only a few small months. The script takes every month.
  * From 1750 to 2010 the script takes one month every 5 years. It prefers July.
    When July is absent, it takes the available month that is closest to July.
  * The script also takes July 2014, the last month of Release 3.1.
  * The script streams each gzip file. It never stores the gzip file on disk.
  * It keeps main records only. Subsidiary records of a linked report do not start
    with the year, and the script skips them.
  * It counts every main record. It keeps at most 20,000 records per month with
    reservoir sampling. The random seed is year * 100 + month, so the sample is stable.

Second source: CLIWOC 2.1 core records (1662-1855) from PANGAEA, CC-BY-3.0.
  https://doi.org/10.1594/PANGAEA.743343  file CLIWOC21CORE.zip (3.8 MB)
  The script downloads the zip once and keeps it in data/raw/ship-logbooks/.

Output in data/raw/ship-logbooks/:
  * sample_YYYY-MM.tsv  one line per kept record: year, month, day, lat, lon, pt, c1, dck, id
  * months.json         per month: total main records, records by platform class, kept count

Fields come from the IMMA1 core record and the first (ICOADS) attachment:
  YR 1-4, MO 5-6, DY 7-8, LAT 13-17 (hundredths), LON 18-23 (hundredths, 0 to 360 east),
  ID 35-43, C1 44-45, DCK 119-121, PT 125-126.
"""
import gzip
import io
import json
import os
import random
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, "data", "raw", "ship-logbooks")
BASE = "https://www.ncei.noaa.gov/data/international-comprehensive-ocean-atmosphere/v3/archive/final-untrim/"
KEEP = 20000
UA = {"User-Agent": "thirteen-rooms-ship-logbooks/1.0 (data visualization gallery)"}


def listing():
    """Return the list of (year, month) pairs that the archive offers."""
    req = urllib.request.Request(BASE, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        html = r.read().decode("utf-8", "replace")
    pairs = sorted(set((int(y), int(m)) for y, m in re.findall(r'IMMA1_R3\.1\.0_(\d{4})-(\d{2})\.gz', html)))
    return pairs


def choose(pairs):
    """Apply the sampling rule and return the ordered list of months to fetch."""
    by_year = {}
    for y, m in pairs:
        by_year.setdefault(y, []).append(m)
    wanted = []
    for y in sorted(by_year):
        if y < 1750:
            wanted.extend((y, m) for m in by_year[y])
    targets = list(range(1750, 2011, 5)) + [2014]
    for y in targets:
        if y not in by_year:
            continue
        months = by_year[y]
        m = min(months, key=lambda mm: (abs(mm - 7), mm))
        wanted.append((y, m))
    return wanted


def platform_class(pt):
    """Map the IMMA platform type to ship, buoy, or other."""
    pt = pt.strip()
    if pt == "" or pt in ("0", "1", "2", "3", "4", "5"):
        return "ship"
    if pt in ("6", "7", "8"):
        return "buoy"
    return "other"


def fetch_month(y, m):
    """Stream one month, count main records, and keep a reservoir sample."""
    name = f"IMMA1_R3.1.0_{y:04d}-{m:02d}.gz"
    url = BASE + name
    rng = random.Random(y * 100 + m)
    ytag = f"{y:04d}".encode()
    mtag = f"{m:2d}".encode()
    total = 0
    classes = {"ship": 0, "buoy": 0, "other": 0}
    bad = 0
    kept = []
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as resp:
        gz = gzip.GzipFile(fileobj=io.BufferedReader(resp, buffer_size=1 << 20))
        for line in gz:
            if line[:4] != ytag or line[4:6] != mtag:
                continue
            try:
                lat = int(line[12:17])
                lon = int(line[17:23])
            except ValueError:
                bad += 1
                continue
            if lat < -9000 or lat > 9000 or lon < 0 or lon > 36000:
                bad += 1
                continue
            pt = line[124:126].decode("ascii", "replace") if len(line) > 126 else ""
            cls = platform_class(pt)
            classes[cls] += 1
            total += 1
            rec = (line[6:8], lat, lon, pt.strip(), line[43:45].decode("ascii", "replace").strip(),
                   line[118:121].decode("ascii", "replace").strip(),
                   line[34:43].decode("ascii", "replace").strip())
            if len(kept) < KEEP:
                kept.append(rec)
            else:
                j = rng.randrange(total)
                if j < KEEP:
                    kept[j] = rec
    out = os.path.join(RAW, f"sample_{y:04d}-{m:02d}.tsv")
    with open(out, "w") as f:
        for day, lat, lon, pt, c1, dck, sid in kept:
            d = day.decode("ascii", "replace").strip() or "0"
            f.write(f"{y}\t{m}\t{d}\t{lat}\t{lon}\t{pt}\t{c1}\t{dck}\t{sid}\n")
    return {"year": y, "month": m, "file": name, "total": total, "bad": bad,
            "classes": classes, "kept": len(kept)}


CLIWOC_URL = "https://hs.pangaea.de/Projects/CLIWOC/CLIWOC21CORE.zip"


def fetch_cliwoc():
    """Download the CLIWOC 2.1 core zip when it is not present."""
    out = os.path.join(RAW, "CLIWOC21CORE.zip")
    if os.path.exists(out) and os.path.getsize(out) > 1_000_000:
        return
    for attempt in range(4):
        try:
            req = urllib.request.Request(CLIWOC_URL, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r, open(out + ".part", "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(out + ".part", out)
            print(f"CLIWOC core zip: {os.path.getsize(out)} bytes", flush=True)
            return
        except Exception as e:
            print(f"CLIWOC attempt {attempt + 1} failed: {e}", flush=True)
            time.sleep(10 * (attempt + 1))
    print("CLIWOC: gave up", flush=True)


def main():
    os.makedirs(RAW, exist_ok=True)
    fetch_cliwoc()
    meta_path = os.path.join(RAW, "months.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    pairs = listing()
    wanted = choose(pairs)
    print(f"archive months: {len(pairs)}, chosen: {len(wanted)}", flush=True)
    for y, m in wanted:
        key = f"{y:04d}-{m:02d}"
        if key in meta and os.path.exists(os.path.join(RAW, f"sample_{key}.tsv")):
            continue
        for attempt in range(4):
            try:
                t0 = time.time()
                info = fetch_month(y, m)
                meta[key] = info
                with open(meta_path, "w") as f:
                    json.dump(meta, f, indent=1, sort_keys=True)
                print(f"{key}: total {info['total']} kept {info['kept']} "
                      f"ship {info['classes']['ship']} buoy {info['classes']['buoy']} "
                      f"other {info['classes']['other']} in {time.time() - t0:.0f}s", flush=True)
                break
            except Exception as e:
                print(f"{key}: attempt {attempt + 1} failed: {e}", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            print(f"{key}: gave up", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
