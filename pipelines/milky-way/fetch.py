"""Fetch the Gaia Catalogue of Nearby Stars (GCNS) from the VizieR TAP service.

The script pages through table "J/A+A/649/A6/table1c" (Gaia Collaboration,
Smart et al. 2021, A&A 649, A6) in blocks of 50000 rows, ordered by the
GaiaEDR3 source id. It writes one CSV file per page into data/raw/milky-way/.
The script keeps only the columns that the room needs.

Usage (from the repository root):
    .venv/bin/python3 -I pipelines/milky-way/fetch.py

Run process.py after this script.
"""
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "milky-way"
TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
TABLE = '"J/A+A/649/A6/table1c"'
COLS = ['"GaiaEDR3"', '"RA_ICRS"', '"DE_ICRS"', '"Plx"', '"pmRA"', '"pmDE"',
        '"Gmag"', '"BPmag"', '"RPmag"', '"RV"', '"Dist50"',
        '"xcoord50"', '"ycoord50"', '"zcoord50"',
        '"Uvel50"', '"Vvel50"', '"Wvel50"']
PAGE = 50000
RETRIES = 5

# Hipparcos identifiers of well-known nearby stars. The room uses them for
# labels. Some of these stars are too bright for Gaia, so the GCNS does not
# hold them. The Hipparcos new reduction (van Leeuwen 2007, VizieR I/311/hip2)
# gives a real position, parallax and proper motion for each of them.
HIP_IDS = [70890, 71683, 87937, 32349, 37279, 97649, 91262, 54035,
           16537, 8102, 104214, 24186]


def query(adql):
    """Run one synchronous ADQL query and return the CSV text."""
    params = urllib.parse.urlencode({
        "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql})
    url = TAP + "?" + params
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=600) as r:
                text = r.read().decode("utf-8")
            if text.startswith("<?xml"):
                raise RuntimeError("TAP error: " + text[:400])
            return text
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 10 * (attempt + 1)
            print(f"  attempt {attempt + 1} failed ({e}); retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"TAP query failed after {RETRIES} attempts: {last}")


def fetch_named():
    """Download the Hipparcos rows for the named stars."""
    out = RAW / "hip2_named.csv"
    if out.exists() and out.stat().st_size > 0:
        print("hipparcos: cached")
        return
    ids = ", ".join(str(i) for i in HIP_IDS)
    adql = ('SELECT "HIP", "RArad", "DErad", "Plx", "pmRA", "pmDE", "Hpmag", "B-V" '
            f'FROM "I/311/hip2" WHERE "HIP" IN ({ids})')
    out.write_text(query(adql))
    print(f"hipparcos: {len(HIP_IDS)} named stars")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    fetch_named()
    total = int(query(f"SELECT COUNT(*) AS n FROM {TABLE}").strip().splitlines()[1])
    print(f"GCNS rows on the server: {total}")
    last_id = -1
    page = 0
    fetched = 0
    while True:
        out = RAW / f"gcns_{page:03d}.csv"
        adql = (f"SELECT TOP {PAGE} {', '.join(COLS)} FROM {TABLE} "
                f"WHERE \"GaiaEDR3\" > {last_id} ORDER BY \"GaiaEDR3\"")
        if out.exists() and out.stat().st_size > 0:
            text = out.read_text()
            print(f"page {page}: cached")
        else:
            print(f"page {page}: query from id > {last_id}")
            text = query(adql)
            out.write_text(text)
        lines = text.strip().splitlines()
        n = len(lines) - 1
        fetched += n
        if n == 0:
            out.unlink()
            break
        last_id = int(lines[-1].split(",")[0])
        page += 1
        if n < PAGE:
            break
        time.sleep(1)
    print(f"fetched {fetched} rows into {RAW}")
    if fetched != total:
        print("warning: row count differs from the server count", file=sys.stderr)


if __name__ == "__main__":
    main()
