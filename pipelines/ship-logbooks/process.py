"""Process the ICOADS samples and the CLIWOC core records for the ship-logbooks room.

Input (from fetch.py) in data/raw/ship-logbooks/:
  sample_YYYY-MM.tsv, months.json, CLIWOC21CORE.zip

Output in rooms/ship-logbooks/data/:
  periods.json   one entry per period: year, months, true record totals, platform
                 classes, kept records, cell offsets, top country codes
  cells.bin      Uint32 little-endian, one value per occupied 0.5 degree cell per period:
                   bits 23-31  latitude index   (0..359, cell = index / 2 - 90)
                   bits 13-22  longitude index  (0..719, cell = index / 2 - 180)
                   bits  6-12  ship reports in the sample, capped at 127
                   bits  0-5   buoy and other reports in the sample, capped at 63
  voyages.json   CLIWOC voyages: {"nations": [...], "v": [[nation index, start, end, offset, count], ...]}
                 start and end are decimal years with two decimals, offset and count index routes.bin
  routes.bin     Int16 little-endian pairs (lat * 100, lon * 100) for every voyage point

Periods: every year before 1750 is one period that holds all its sampled months.
From 1750 on, each sampled month is one period.

CLIWOC voyages: records are grouped by ship ID and sorted by date. A gap of more
than 30 days, or a jump of more than 12 degrees between consecutive records, starts
a new voyage. Voyages with fewer than 8 positioned records are dropped. Each voyage
keeps its first and last point, and every point that is at least 0.75 degrees away
from the previous kept point.
"""
import collections
import datetime
import json
import math
import os
import struct
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, "data", "raw", "ship-logbooks")
OUT = os.path.join(ROOT, "rooms", "ship-logbooks", "data")
NATIONS = {"NL": "Dutch", "UK": "British", "ES": "Spanish", "FR": "French"}
NATION_LIST = ["Dutch", "British", "Spanish", "French", "Other"]


def decimal_year(d):
    """Return the date as a decimal year with two decimals."""
    start = datetime.date(d.year, 1, 1)
    days = 366 if (d.year % 4 == 0 and (d.year % 100 != 0 or d.year % 400 == 0)) else 365
    return round(d.year + (d - start).days / days, 2)


def load_months():
    with open(os.path.join(RAW, "months.json")) as f:
        return json.load(f)


def build_periods(meta):
    """Group sampled months into periods and aggregate the 0.5 degree cells."""
    groups = collections.OrderedDict()
    for key in sorted(meta):
        y = meta[key]["year"]
        pkey = str(y) if y < 1750 else key
        groups.setdefault(pkey, []).append(key)
    periods = []
    packed = []
    for pkey, keys in groups.items():
        cells = collections.defaultdict(lambda: [0, 0])
        countries = collections.Counter()
        total = 0
        kept = 0
        classes = collections.Counter()
        months = []
        for key in keys:
            info = meta[key]
            months.append(info["month"])
            total += info["total"]
            kept += info["kept"]
            for k, v in info["classes"].items():
                classes[k] += v
            with open(os.path.join(RAW, f"sample_{key}.tsv")) as f:
                for line in f:
                    p = line.rstrip("\n").split("\t")
                    lat = int(p[3]) / 100.0
                    lon = int(p[4]) / 100.0
                    if lon >= 180.0:
                        lon -= 360.0
                    li = min(359, int(math.floor((lat + 90.0) * 2)))
                    lo = min(719, int(math.floor((lon + 180.0) * 2)))
                    pt = p[5]
                    ship = pt == "" or pt in ("0", "1", "2", "3", "4", "5")
                    cells[(li, lo)][0 if ship else 1] += 1
                    if p[6]:
                        countries[p[6]] += 1
        start = len(packed)
        for (li, lo), (s, o) in sorted(cells.items()):
            packed.append((li << 23) | (lo << 13) | (min(s, 127) << 6) | min(o, 63))
        top = [[c, n] for c, n in countries.most_common(5)]
        periods.append({
            "year": meta[keys[0]]["year"],
            "months": months,
            "total": total,
            "ship": classes["ship"],
            "buoy": classes["buoy"],
            "other": classes["other"],
            "kept": kept,
            "offset": start,
            "count": len(packed) - start,
            "flagged": sum(countries.values()),
            "flags": top,
        })
    return periods, packed


def parse_cliwoc():
    """Read the CLIWOC core records and return voyages as point lists."""
    z = zipfile.ZipFile(os.path.join(RAW, "CLIWOC21CORE.zip"))
    name = [i.filename for i in z.infolist() if i.file_size > 1_000_000][0]
    by_ship = collections.defaultdict(list)
    n = 0
    for raw in z.read(name).split(b"\r\n"):
        if len(raw) < 50:
            continue
        n += 1
        try:
            y = int(raw[0:4]); m = int(raw[4:6]); d = int(raw[6:8])
            lat = int(raw[12:17]) / 100.0
            lon = int(raw[17:23]) / 100.0
            date = datetime.date(y, m, d)
        except ValueError:
            continue
        if lon >= 180.0:
            lon -= 360.0
        sid = raw[34:43].decode("ascii", "replace").strip()
        c1 = raw[43:45].decode("ascii", "replace").strip()
        by_ship[sid].append((date, lat, lon, c1))
    voyages = []
    for sid, recs in by_ship.items():
        recs.sort()
        cur = []
        def flush():
            if len(cur) >= 8:
                voyages.append((sid, list(cur)))
        for r in recs:
            if cur:
                prev = cur[-1]
                gap = (r[0] - prev[0]).days
                jump = max(abs(r[1] - prev[1]), abs(((r[2] - prev[2] + 180) % 360) - 180))
                if gap > 30 or jump > 12:
                    flush(); cur = []
            cur.append(r)
        flush()
    return n, voyages


def thin(points):
    """Keep the first point, the last point, and points 0.75 degrees apart."""
    out = [points[0]]
    for p in points[1:-1]:
        q = out[-1]
        if abs(p[1] - q[1]) >= 0.75 or abs(p[2] - q[2]) >= 0.75:
            out.append(p)
    out.append(points[-1])
    return out


def write_preview(periods, packed, voyages_pts):
    """Draw an 800x500 SVG still: 1985 ship cells as sepia dots, plus CLIWOC routes.

    To keep the file small, the still draws every second occupied cell, rounds the
    coordinates to whole pixels, and draws one voyage in eight.
    """
    w, h = 800, 500
    mx, my = 20, 20
    mw, mh = 760, 380
    def proj(lat, lon):
        return mx + (lon + 180) / 360 * mw, my + (90 - lat) / 180 * mh
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
             '<defs><filter id="fox"><feTurbulence type="fractalNoise" baseFrequency="0.012" numOctaves="3" seed="7"/>'
             '<feColorMatrix values="0 0 0 0 0.55  0 0 0 0 0.42  0 0 0 0 0.25  0 0 0 0.16 0"/></filter></defs>',
             f'<rect width="{w}" height="{h}" fill="#ede3c8"/>',
             f'<rect width="{w}" height="{h}" filter="url(#fox)"/>',
             f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" fill="none" stroke="#6b4e2a" stroke-width="1.2"/>']
    for lon in range(-150, 180, 30):
        x, _ = proj(0, lon)
        parts.append(f'<line x1="{x:.1f}" y1="{my}" x2="{x:.1f}" y2="{my+mh}" stroke="#8a6a3e" stroke-width="0.4" stroke-dasharray="2 4"/>')
    for lat in range(-60, 90, 30):
        _, y = proj(lat, 0)
        parts.append(f'<line x1="{mx}" y1="{y:.1f}" x2="{mx+mw}" y2="{y:.1f}" stroke="#8a6a3e" stroke-width="0.4" stroke-dasharray="2 4"/>')
    period = next(p for p in periods if p["year"] == 1985)
    buckets = {1: [], 2: [], 3: [], 4: []}
    for i, v in enumerate(packed[period["offset"]:period["offset"] + period["count"]]):
        li, lo, s = v >> 23, (v >> 13) & 1023, (v >> 6) & 127
        if s == 0 or i % 2:
            continue
        x, y = proj(li / 2 - 90 + 0.25, lo / 2 - 180 + 0.25)
        buckets[min(4, 1 + int(math.sqrt(s)))].append(f"M{x:.0f} {y:.0f}h.1")
    for k, segs in buckets.items():
        if segs:
            parts.append(f'<path d="{"".join(segs)}" stroke="#4a3012" stroke-width="{0.9 + 0.8 * k:.1f}" '
                         f'stroke-linecap="round" fill="none" opacity="{min(0.9, 0.35 + 0.14 * k):.2f}"/>')
    colors = {"Dutch": "#b8541e", "British": "#2f5f8a", "Spanish": "#8a7a1e", "French": "#7a3c7a"}
    parts.append('<g fill="none" stroke-width="0.7" stroke-opacity="0.5" stroke-linejoin="round">')
    for nation, pts in voyages_pts[::8]:
        segs = []
        prev_lon = None
        for a, b in pts:
            x, y = proj(a, b)
            # start a new sub-path when the voyage crosses the antimeridian
            cmd = "M" if prev_lon is None or abs(b - prev_lon) > 180 else "L"
            segs.append(f"{cmd}{x:.0f},{y:.0f}")
            prev_lon = b
        parts.append(f'<path d="{" ".join(segs)}" stroke="{colors.get(nation, "#5a5a5a")}"/>')
    parts.append('</g>')
    parts.append('<text x="40" y="455" font-family="Georgia, serif" font-size="30" fill="#3b2a14" font-style="italic">Four Centuries of Logbooks</text>')
    parts.append('<text x="40" y="482" font-family="Georgia, serif" font-size="13" fill="#5b4428">Ship weather reports, July 1985 (ICOADS R3.1) over CLIWOC voyages 1750 to 1855</text>')
    parts.append('<text x="760" y="470" font-family="Georgia, serif" font-size="44" fill="#3b2a14" text-anchor="end">1985</text>')
    parts.append('</svg>')
    with open(os.path.join(ROOT, "rooms", "ship-logbooks", "preview.svg"), "w") as f:
        f.write("\n".join(parts))


def main():
    os.makedirs(OUT, exist_ok=True)
    meta = load_months()
    periods, packed = build_periods(meta)
    with open(os.path.join(OUT, "cells.bin"), "wb") as f:
        f.write(struct.pack(f"<{len(packed)}I", *packed))
    n_cliwoc, voyages = parse_cliwoc()
    vindex = []
    pts = []
    voyages_pts = []
    for sid, recs in voyages:
        c1 = collections.Counter(r[3] for r in recs).most_common(1)[0][0]
        nation = NATIONS.get(c1, "Other")
        kept = thin(recs)
        vindex.append([NATION_LIST.index(nation), decimal_year(recs[0][0]), decimal_year(recs[-1][0]),
                       len(pts), len(kept)])
        voyages_pts.append((nation, [(p[1], p[2]) for p in kept]))
        for p in kept:
            pts.append((int(round(p[1] * 100)), int(round(p[2] * 100))))
    with open(os.path.join(OUT, "routes.bin"), "wb") as f:
        f.write(struct.pack(f"<{len(pts) * 2}h", *[v for p in pts for v in p]))
    with open(os.path.join(OUT, "voyages.json"), "w") as f:
        json.dump({"nations": NATION_LIST, "v": vindex}, f, separators=(",", ":"))
    summary = {
        "source_months": len(meta),
        "records_total": sum(m["total"] for m in meta.values()),
        "records_kept": sum(m["kept"] for m in meta.values()),
        "cells": len(packed),
        "cliwoc_records": n_cliwoc,
        "cliwoc_voyages": len(vindex),
        "cliwoc_points": len(pts),
        "periods": periods,
    }
    with open(os.path.join(OUT, "periods.json"), "w") as f:
        json.dump(summary, f, separators=(",", ":"))
    write_preview(periods, packed, voyages_pts)
    for k in ("source_months", "records_total", "records_kept", "cells", "cliwoc_records", "cliwoc_voyages", "cliwoc_points"):
        print(k, summary[k])
    for p in periods:
        print(p["year"], p["months"], "total", p["total"], "kept", p["kept"], "cells", p["count"], "flags", p["flags"][:3])
    for name in sorted(os.listdir(OUT)):
        print(name, os.path.getsize(os.path.join(OUT, name)))


if __name__ == "__main__":
    main()
