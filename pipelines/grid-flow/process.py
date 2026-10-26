"""Process the EIA-930 and EIA-860 raw files for the room "The Grid Breathes".

Sampling rule:
  Keep four full weeks of 2024, one per season. Each week runs from Monday
  00:00 to Sunday 24:00 in the America/New_York time zone (168 hours):
    winter  2024-01-15 .. 2024-01-21
    spring  2024-04-15 .. 2024-04-21
    summer  2024-07-15 .. 2024-07-21
    autumn  2024-10-14 .. 2024-10-20
  Within each week the script keeps every hour and every balancing authority.

Output: rooms/grid-flow/data/grid.json and rooms/grid-flow/preview.svg.
Run from the repository root:
  .venv/bin/python3 -I pipelines/grid-flow/process.py
"""
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "grid-flow"
OUT = ROOT / "rooms" / "grid-flow" / "data"
OUT.mkdir(parents=True, exist_ok=True)
ET = ZoneInfo("America/New_York")
HOURS = 168

SEASONS = [
    ("winter", "Winter", "2024-01-15"),
    ("spring", "Spring", "2024-04-15"),
    ("summer", "Summer", "2024-07-15"),
    ("autumn", "Autumn", "2024-10-14"),
]
FUELS = ["coal", "gas", "nuclear", "hydro", "wind", "solar", "other"]

# Balancing authorities outside the United States that trade with US BAs.
# EIA-860 has no plants for them. The room draws each one at the point where
# its main tie lines cross the US border, so the arcs end at the border.
FOREIGN = {
    "AESO": ("Alberta Electric System Operator", 49.0, -112.0),
    "BCHA": ("British Columbia Hydro", 49.0, -119.5),
    "CEN": ("Centro Nacional de Control de Energia (Mexico)", 31.4, -110.9),
    "CFE": ("Comision Federal de Electricidad (Mexico)", 31.4, -110.9),
    "HQT": ("Hydro-Quebec TransEnergie", 45.1, -73.4),
    "IESO": ("Ontario Independent Electricity System Operator", 43.2, -79.1),
    "MHEB": ("Manitoba Hydro", 49.0, -97.2),
    "NBSO": ("New Brunswick System Operator", 45.6, -67.4),
    "SPC": ("Saskatchewan Power Corporation", 49.0, -104.0),
}


def season_windows():
    """Return [(key, label, start_utc_naive, end_utc_naive)]."""
    out = []
    for key, label, day in SEASONS:
        start = datetime.fromisoformat(day).replace(tzinfo=ET)
        end = start + timedelta(hours=HOURS)
        s = start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        e = end.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        out.append((key, label, s, e))
    return out


WINDOWS = season_windows()


def parse_utc(series):
    return pd.to_datetime(series, format="%m/%d/%Y %I:%M:%S %p")


def hour_index(utc_end):
    """Map a UTC hour-ending timestamp to (season index, hour index) or None."""
    for si, (_, _, s, e) in enumerate(WINDOWS):
        if s < utc_end <= e:
            return si, int((utc_end - s) / timedelta(hours=1)) - 1
    return None


def window_mask(utc):
    m = np.zeros(len(utc), dtype=bool)
    for _, _, s, e in WINDOWS:
        m |= (utc > s) & (utc <= e)
    return m


def fuel_columns(header):
    """Group the adjusted fuel columns of one balance file into FUELS."""
    groups = {f: [] for f in FUELS}
    for col in header:
        if "(Adjusted)" not in col or "from" not in col:
            continue
        name = col.split("from", 1)[1]
        if "Solar" in name:
            groups["solar"].append(col)
        elif "Wind" in name:
            groups["wind"].append(col)
        elif "Hydro" in name or "Pumped" in name:
            groups["hydro"].append(col)
        elif "Coal" in name:
            groups["coal"].append(col)
        elif "Natural Gas" in name:
            groups["gas"].append(col)
        elif "Nuclear" in name:
            groups["nuclear"].append(col)
        else:
            groups["other"].append(col)
    return groups


def read_balance():
    """Return dict ba -> dict field -> ndarray[4, 168] (NaN where missing)."""
    data = {}
    fields = ["demand", "gen", "ti"] + FUELS
    rows_in = 0
    rows_kept = 0
    for name in ["EIA930_BALANCE_2024_Jan_Jun.csv", "EIA930_BALANCE_2024_Jul_Dec.csv"]:
        path = RAW / name
        header = pd.read_csv(path, nrows=0).columns.tolist()
        groups = fuel_columns(header)
        use = ["Balancing Authority", "UTC Time at End of Hour",
               "Demand (MW) (Adjusted)", "Net Generation (MW) (Adjusted)",
               "Total Interchange (MW) (Adjusted)"]
        for f in FUELS:
            use += groups[f]
        for chunk in pd.read_csv(path, usecols=use, chunksize=200_000, thousands=","):
            rows_in += len(chunk)
            utc = parse_utc(chunk["UTC Time at End of Hour"])
            chunk = chunk[window_mask(utc)]
            utc = utc[chunk.index]
            rows_kept += len(chunk)
            for ba, t, row in zip(chunk["Balancing Authority"], utc, chunk.itertuples(index=False)):
                pos = hour_index(t)
                if pos is None:
                    continue
                si, hi = pos
                rec = data.get(ba)
                if rec is None:
                    rec = {f: np.full((4, HOURS), np.nan) for f in fields}
                    data[ba] = rec
                vals = dict(zip(chunk.columns, row))
                rec["demand"][si, hi] = vals["Demand (MW) (Adjusted)"]
                rec["gen"][si, hi] = vals["Net Generation (MW) (Adjusted)"]
                rec["ti"][si, hi] = vals["Total Interchange (MW) (Adjusted)"]
                for f in FUELS:
                    cols = groups[f]
                    if not cols:
                        continue
                    v = [vals[c] for c in cols]
                    v = [x for x in v if x == x]  # drop NaN
                    if v:
                        rec[f][si, hi] = sum(v)
    print(f"balance rows: {rows_in} read, {rows_kept} kept")
    return data


def read_interchange():
    """Return dict (ba, diba) -> ndarray[4, 168] of reported MW (NaN if missing)."""
    flows = {}
    rows_in = 0
    rows_kept = 0
    use = ["Balancing Authority", "Directly Interconnected Balancing Authority",
           "Interchange (MW)", "UTC Time at End of Hour"]
    for name in ["EIA930_INTERCHANGE_2024_Jan_Jun.csv", "EIA930_INTERCHANGE_2024_Jul_Dec.csv"]:
        path = RAW / name
        for chunk in pd.read_csv(path, usecols=use, chunksize=300_000, thousands=","):
            rows_in += len(chunk)
            utc = parse_utc(chunk["UTC Time at End of Hour"])
            chunk = chunk[window_mask(utc)]
            utc = utc[chunk.index]
            rows_kept += len(chunk)
            for ba, diba, mw, t in zip(chunk["Balancing Authority"],
                                       chunk["Directly Interconnected Balancing Authority"],
                                       chunk["Interchange (MW)"], utc):
                pos = hour_index(t)
                if pos is None or not isinstance(diba, str):
                    continue
                si, hi = pos
                arr = flows.get((ba, diba))
                if arr is None:
                    arr = np.full((4, HOURS), np.nan)
                    flows[(ba, diba)] = arr
                arr[si, hi] = mw
    print(f"interchange rows: {rows_in} read, {rows_kept} kept")
    return flows


def read_locations():
    """Return dict ba -> (name, lat, lon, plant_count) from the EIA-860 plant file."""
    wb = openpyxl.load_workbook(RAW / "2___Plant_Y2024.xlsx", read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # title line
    header = next(rows)
    ix = {h: i for i, h in enumerate(header)}
    pts = defaultdict(list)
    names = {}
    for row in rows:
        code = row[ix["Balancing Authority Code"]]
        lat = row[ix["Latitude"]]
        lon = row[ix["Longitude"]]
        if not code or lat is None or lon is None:
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        pts[code].append((lat, lon))
        if code not in names and row[ix["Balancing Authority Name"]]:
            names[code] = str(row[ix["Balancing Authority Name"]]).strip()
    out = {}
    for code, p in pts.items():
        a = np.array(p)
        # The median resists plants that sit far from the service area.
        out[code] = (names.get(code, code), float(np.median(a[:, 0])), float(np.median(a[:, 1])), len(p))
    print(f"plant file: {len(out)} balancing authorities with coordinates")
    return out


def to_int_list(arr):
    return [None if x != x else int(round(x)) for x in arr]


def main():
    balance = read_balance()
    flows = read_interchange()
    locs = read_locations()

    codes = set(balance)
    for a, b in flows:
        codes.add(a)
        codes.add(b)
    bas = []
    missing = []
    for code in sorted(codes):
        if code in locs:
            name, lat, lon, n = locs[code]
        elif code in FOREIGN:
            name, lat, lon = FOREIGN[code]
            n = 0
        else:
            missing.append(code)
            continue
        bas.append({"code": code, "name": name, "lat": round(lat, 3), "lon": round(lon, 3),
                    "plants": n, "foreign": code in FOREIGN})
    if missing:
        print("no location for:", ", ".join(missing))
    index = {b["code"]: i for i, b in enumerate(bas)}

    # Undirected pairs. Positive means flow from the first (alphabetical) BA
    # to the second. The first BA's report wins. The second BA's report, with
    # the sign flipped, fills the hours the first BA did not report.
    pairs = []
    flow_series = []
    for (a, b) in sorted({tuple(sorted(k)) for k in flows}):
        if a not in index or b not in index:
            continue
        ab = flows.get((a, b))
        ba = flows.get((b, a))
        arr = np.full((4, HOURS), np.nan)
        if ab is not None:
            arr = ab.copy()
        if ba is not None:
            fill = np.isnan(arr)
            arr[fill] = -ba[fill]
        if np.all(np.isnan(arr)):
            continue
        pairs.append([index[a], index[b]])
        flow_series.append(arr)

    seasons = []
    for (key, label, s, _), (_, _, day) in zip(WINDOWS, SEASONS):
        seasons.append({"key": key, "label": label, "start_local": day,
                        "start_utc": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": HOURS})

    series = {}
    fields = ["demand", "gen", "ti"] + FUELS
    for si, (key, _, _, _) in enumerate(WINDOWS):
        block = {f: [] for f in fields}
        for b in bas:
            rec = balance.get(b["code"])
            for f in fields:
                block[f].append(to_int_list(rec[f][si]) if rec is not None else [None] * HOURS)
        block["flow"] = [to_int_list(arr[si]) for arr in flow_series]
        series[key] = block

    # Peak flow per pair over all seasons, for the particle scale and the preview.
    peak = [float(np.nanmax(np.abs(arr))) for arr in flow_series]
    doc = {
        "source": "EIA-930 Hourly Electric Grid Monitor (2024) and EIA-860 (2024)",
        "seasons": seasons,
        "fuels": FUELS,
        "bas": bas,
        "pairs": pairs,
        "pair_peak_mw": [int(p) for p in peak],
        "series": series,
    }
    path = OUT / "grid.json"
    with open(path, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    size = path.stat().st_size
    print(f"wrote {path} ({size / 1e6:.2f} MB): {len(bas)} BAs, {len(pairs)} pairs, "
          f"{len(seasons)} seasons x {HOURS} hours")
    write_preview(doc, flow_series)


# ---------------------------------------------------------------- preview

def albers(lat, lon, scale, tx, ty):
    """Conic equal-area projection, same parameters as d3.geoAlbers()."""
    phi0, phi1, phi2 = math.radians(29.5), math.radians(29.5), math.radians(45.5)
    lam0 = math.radians(-96)
    phi = math.radians(lat)
    lam = math.radians(lon) - lam0
    n = (math.sin(phi1) + math.sin(phi2)) / 2
    c = math.cos(phi1) ** 2 + 2 * n * math.sin(phi1)
    r0 = math.sqrt(c - 2 * n * math.sin(math.radians(38.5))) / n
    r = math.sqrt(c - 2 * n * math.sin(phi)) / n
    theta = n * lam
    x = r * math.sin(theta)
    y = r0 - r * math.cos(theta)
    return tx + x * scale, ty - y * scale


def topo_paths(scale, tx, ty):
    """Return SVG path strings for the lower 48 states from the us-atlas file."""
    topo = json.load(open(RAW / "states-10m.json"))
    sx, sy = topo["transform"]["scale"]
    dx, dy = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for px, py in arc:
            x += px
            y += py
            pts.append((x * sx + dx, y * sy + dy))
        arcs.append(pts)
    paths = []
    for g in topo["objects"]["states"]["geometries"]:
        if g["id"] in ("02", "15", "72"):
            continue
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        d = []
        for poly in polys:
            for ring in poly:
                pts = []
                for ai in ring:
                    a = arcs[ai] if ai >= 0 else arcs[~ai][::-1]
                    pts.extend(a)
                d.append("M" + " ".join(f"{x:.1f},{y:.1f}" for x, y in
                                        (albers(lat, lon, scale, tx, ty) for lon, lat in pts)) + "Z")
        paths.append("".join(d))
    return paths


def write_preview(doc, flow_series):
    W, H = 800, 500
    scale, tx, ty = 1000, 400, 248
    bas = doc["bas"]
    pos = [albers(b["lat"], b["lon"], scale, tx, ty) for b in bas]
    # Summer week, hour 161 of the week (Sunday 17:00 ET), real values.
    si, hi = 2, 161
    s = doc["series"]["summer"]
    demand = [d[hi] or 0 for d in s["demand"]]
    ti = [t[hi] or 0 for t in s["ti"]]
    dmax = max(demand) or 1
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           '<defs><pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">'
           '<rect width="4" height="2" fill="#000" opacity="0.18"/></pattern>'
           '<filter id="glow"><feGaussianBlur stdDeviation="2.2" result="b"/>'
           '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>',
           f'<rect width="{W}" height="{H}" fill="#060907"/>']
    # Faint grid
    for x in range(0, W, 40):
        out.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" stroke="#1a2a1f" stroke-width="0.5"/>')
    for y in range(0, H, 40):
        out.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="#1a2a1f" stroke-width="0.5"/>')
    for p in topo_paths(scale, tx, ty):
        out.append(f'<path d="{p}" fill="#0b120e" stroke="#2a4a35" stroke-width="0.7"/>')
    # Arcs, brightness by flow at that hour.
    for (i, j), arr in zip(doc["pairs"], flow_series):
        v = arr[si, hi]
        if v != v:
            continue
        x1, y1 = pos[i]
        x2, y2 = pos[j]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        cx, cy = mx - dy * 0.18, my + dx * 0.18
        a = min(1, 0.15 + abs(v) / 4000)
        out.append(f'<path d="M{x1:.1f},{y1:.1f} Q{cx:.1f},{cy:.1f} {x2:.1f},{y2:.1f}" fill="none" '
                   f'stroke="#39ff8a" stroke-opacity="{a:.2f}" stroke-width="{0.6 + abs(v) / 2500:.2f}"/>')
    # Nodes
    for b, (x, y), d, t in zip(bas, pos, demand, ti):
        r = 2.5 + 16 * math.sqrt(d / dmax)
        col = "#ffb347" if t < -300 else ("#39ff8a" if t > 300 else "#9fb8a8")
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{col}" fill-opacity="0.85" '
                   f'filter="url(#glow)"/>')
        if d > 0.25 * dmax:
            out.append(f'<text x="{x + r + 3:.1f}" y="{y + 4:.1f}" font-family="ui-monospace,Menlo,monospace" '
                       f'font-size="11" fill="#c8f5d8">{b["code"]}</text>')
    total = sum(demand)
    out.append(f'<rect width="{W}" height="{H}" fill="url(#scan)"/>')
    out.append('<rect x="10" y="10" width="330" height="54" fill="#060907" fill-opacity="0.82"/>')
    out.append('<text x="20" y="34" font-family="ui-monospace,Menlo,monospace" font-size="20" fill="#39ff8a" '
               'letter-spacing="2">THE GRID BREATHES</text>')
    out.append('<text x="20" y="54" font-family="ui-monospace,Menlo,monospace" font-size="11" fill="#9fb8a8">'
               'EIA-930 HOURLY INTERCHANGE  /  SUMMER WEEK 2024</text>')
    out.append(f'<text x="780" y="470" text-anchor="end" font-family="ui-monospace,Menlo,monospace" '
               f'font-size="26" fill="#ffb347">{total:,} MW</text>')
    out.append('<text x="780" y="488" text-anchor="end" font-family="ui-monospace,Menlo,monospace" '
               'font-size="10" fill="#9fb8a8">TOTAL DEMAND  SUN 17:00 ET</text>')
    out.append("</svg>")
    path = ROOT / "rooms" / "grid-flow" / "preview.svg"
    path.write_text("\n".join(out))
    print(f"wrote {path} ({path.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
