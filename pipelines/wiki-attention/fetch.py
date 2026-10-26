"""Download the Wikimedia clickstream file for English Wikipedia.

Stdlib only. Run from the repository root:
  .venv/bin/python3 -I pipelines/wiki-attention/fetch.py [YYYY-MM]

The script reads the directory listing at
https://dumps.wikimedia.org/other/clickstream/ and picks the latest month
that has an enwiki file. It streams the gz file to data/raw/wiki-attention/.
If the latest month fails, it tries the month before. The download resumes
when a partial file exists.
"""
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "wiki-attention"
BASE = "https://dumps.wikimedia.org/other/clickstream/"
UA = {"User-Agent": "thirteen-rooms-gallery/1.0 (data visualization; contact via repo)"}


def list_months():
    """Return the month folders in the listing, oldest first."""
    req = urllib.request.Request(BASE, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    return sorted(set(re.findall(r'href="(\d{4}-\d{2})/"', html)))


def download(month):
    """Stream one month's enwiki file to RAW. Return the local path or None."""
    name = f"clickstream-enwiki-{month}.tsv.gz"
    url = f"{BASE}{month}/{name}"
    dest = RAW / name
    part = RAW / (name + ".part")
    if dest.exists():
        print("already present", dest)
        return dest
    have = part.stat().st_size if part.exists() else 0
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=120)
    except Exception as e:  # 404 for a month without enwiki, or a network error
        print("cannot open", url, e)
        return None
    total = r.headers.get("Content-Length")
    mode = "ab" if have and r.status == 206 else "wb"
    if mode == "wb":
        have = 0
    done = have
    last = time.time()
    with open(part, mode) as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if time.time() - last > 10:
                print(f"{done / 1e6:.0f} MB", flush=True)
                last = time.time()
    part.rename(dest)
    print("saved", dest, done, "bytes", "of", total)
    return dest


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        months = [sys.argv[1]]
    else:
        months = list_months()[-2:][::-1]  # latest first, then the fallback month
    for month in months:
        for attempt in range(3):
            path = download(month)
            if path:
                (RAW / "MONTH").write_text(month + "\n")
                return
            time.sleep(5 * (attempt + 1))
    print("no file downloaded")
    sys.exit(1)


if __name__ == "__main__":
    main()
