"""Download the raw inputs for the Treasury Machine room into data/raw/treasury-machine/.

Run with the venv: .venv/bin/python3 -I pipelines/treasury-machine/fetch.py
Then: parse_omb.py, the OCR steps (see the room README), process.py.
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "treasury-machine"
RAW.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (data-art-galleries; research use)"}


def get(url, dest, binary=True):
    dest = RAW / dest
    if dest.exists() and dest.stat().st_size > 0:
        print("have", dest.name); return dest
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    dest.write_bytes(data); print("got", dest.name, len(data), "bytes"); return dest


# 1. OMB Historical Tables. The page lists the current edition's xlsx links.
page = get("https://www.whitehouse.gov/omb/information-resources/budget/historical-tables/", "hist_page.html").read_text(errors="ignore")
for t in ["01z1", "01z2", "02z1", "02z4", "02z5", "03z1", "03z2", "07z1", "10z1", "11z3"]:
    m = re.search(r'https://[^"]+hist' + t + r'_fy\d+\.xlsx', page)
    if not m:
        sys.exit(f"no link for hist{t} on the OMB page")
    get(m.group(0), f"hist{t}.xlsx")

# 2. Treasury historical debt outstanding, 1790 to the latest fiscal year.
get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_outstanding?page%5Bsize%5D=400&sort=record_date", "debt_outstanding.json")

# 3. MeasuringWorth GDP and population, 1790 to 2025.
get("https://www.measuringworth.com/datasets/usgdp/export.php?year_source=1790&year_result=2025&use[]=NOMINALGDP&use[]=REALGDP&use[]=GDPDEFLATION&use[]=POPULATION", "mw_gdp.csv")

# 4. NBER Macrohistory, monthly income tax receipts 1910-1953.
get("https://data.nber.org/databases/macrohistory/data/15/m15002a.db", "nber_m15002a.db")

# 5. Historical Statistics of the United States, chapter Y (scanned PDF), and the table pages at 300 dpi.
pdf = get("https://www2.census.gov/library/publications/1975/compendia/hist_stats_colonial-1970/hist_stats_colonial-1970p2-chY.pdf", "hsus_chY.pdf")
tab = RAW / "tab"; tab.mkdir(exist_ok=True)
for p in (38, 40, 41, 42, 48, 49):
    out = tab / f"h{p}-{p}.png"
    if not out.exists():
        subprocess.run(["pdftoppm", "-r", "300", "-f", str(p), "-l", str(p), "-png", str(pdf), str(tab / f"h{p}")], check=True)
        print("rendered page", p)
print("done")
