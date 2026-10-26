"""Process raw data for the room "Ships at the Border".

Input (data/raw/ships-and-borders/):
  ais_2023_06_DD.csv       AIS rows inside the bounding box, one file per day
  cinms_py2.zip            Channel Islands NMS boundary (shapefile, NAD83)
  ca_mpas_bbox.geojson     California MPAs inside the box (CDFW BIOS ds582)
  noaa_lanes_bbox.geojson  NOAA chart traffic lanes and related areas
  ne_10m_land.zip, ne_10m_minor_islands.zip   Natural Earth coastline

Output (rooms/ships-and-borders/data/):
  tracks.i16      Int16 triplets [minute, x, y] for every kept track point
  vessels.json    one compact record per vessel: class, length, offset, count
  zones.json      sanctuary, MPA, lane and coast polygons (lon, lat, 4 decimals)
                  plus MPA groups: state and federal reserves of one name
  events.json     zone entry events: [minute, vessel, zone kind, zone index]
  stats.json      counts for the caption, the legend and the README
  ../preview.svg  a static chart still for the hub card

Sampling rule:
  1. Keep rows inside lon -121.2..-118.2, lat 33.3..34.6 (done in fetch.py).
  2. Keep the first row of each vessel in each 5-minute bin.
  3. Keep a binned point only when it is 50 m or more from the last kept
     point, or when 30 minutes or more passed since the last kept point.
  4. Drop vessels with fewer than 10 kept points.
  5. Drop vessels that never moved 1 km or more from their first point.

Run from the repository root:
  .venv/bin/python3 -I pipelines/ships-and-borders/process.py
"""
import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import shapefile

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ships-and-borders"
ROOM = ROOT / "rooms" / "ships-and-borders"
OUT = ROOM / "data"
OUT.mkdir(parents=True, exist_ok=True)

LON0, LON1, LAT0, LAT1 = -121.2, -118.2, 33.3, 34.6
T0 = pd.Timestamp("2023-06-15T00:00:00")
MINUTES = 4 * 24 * 60
CLASSES = ["other", "cargo", "tanker", "passenger", "fishing", "tug", "pleasure"]
# Validated ink palette, fixed order, light surface. Do not cycle.
COLORS = ["#6f8f1f", "#2b5ea8", "#a0522d", "#118f7c", "#b8860b", "#7b4fa8", "#c23b4b"]
KM_PER_DEG = 111.32
COS_LAT = math.cos(math.radians(34.0))


def classify(code):
    """Map the AIS VesselType code to a class index in CLASSES."""
    if code != code:  # NaN
        return 0
    v = int(code)
    if 70 <= v <= 79:
        return 1
    if 80 <= v <= 89:
        return 2
    if 60 <= v <= 69:
        return 3
    if v == 30:
        return 4
    if v in (31, 32, 52):
        return 5
    if v in (36, 37):
        return 6
    return 0


def dist_km(lon_a, lat_a, lon_b, lat_b):
    dx = (lon_b - lon_a) * KM_PER_DEG * COS_LAT
    dy = (lat_b - lat_a) * KM_PER_DEG
    return math.hypot(dx, dy)


# ---------------------------------------------------------------- geometry
def simplify(points, tol):
    """Douglas-Peucker simplification of a list of (x, y) tuples."""
    if len(points) < 3:
        return list(points)
    pts = np.asarray(points, dtype=float)
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[b] - pts[a]
        n = np.hypot(*seg)
        mid = pts[a + 1:b]
        if n == 0:
            d = np.hypot(*(mid - pts[a]).T)
        else:
            d = np.abs(seg[0] * (pts[a][1] - mid[:, 1]) - seg[1] * (pts[a][0] - mid[:, 0])) / n
        i = int(np.argmax(d))
        if d[i] > tol:
            keep[a + 1 + i] = True
            stack.append((a, a + 1 + i))
            stack.append((a + 1 + i, b))
    return [tuple(p) for p in pts[keep]]


def clip_ring(ring, lon0, lon1, lat0, lat1):
    """Sutherland-Hodgman clip of a closed ring against the box."""
    def clip(poly, inside, intersect):
        out = []
        if not poly:
            return out
        prev = poly[-1]
        for cur in poly:
            if inside(cur):
                if not inside(prev):
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(intersect(prev, cur))
            prev = cur
        return out

    def ix(p, q, x):
        t = (x - p[0]) / (q[0] - p[0])
        return (x, p[1] + t * (q[1] - p[1]))

    def iy(p, q, y):
        t = (y - p[1]) / (q[1] - p[1])
        return (p[0] + t * (q[0] - p[0]), y)

    poly = list(ring)
    poly = clip(poly, lambda p: p[0] >= lon0, lambda p, q: ix(p, q, lon0))
    poly = clip(poly, lambda p: p[0] <= lon1, lambda p, q: ix(p, q, lon1))
    poly = clip(poly, lambda p: p[1] >= lat0, lambda p, q: iy(p, q, lat0))
    poly = clip(poly, lambda p: p[1] <= lat1, lambda p, q: iy(p, q, lat1))
    return poly


def inside_rings(rings, lon, lat):
    """Even-odd point-in-polygon test, vectorized over points."""
    res = np.zeros(len(lon), dtype=bool)
    for ring in rings:
        r = np.asarray(ring, dtype=float)
        if len(r) < 3:
            continue
        x0, y0 = r[:, 0], r[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        for j in range(len(r)):
            if (y0[j] > y1[j]):
                ya, yb, xa, xb = y1[j], y0[j], x1[j], x0[j]
            else:
                ya, yb, xa, xb = y0[j], y1[j], x0[j], x1[j]
            if ya == yb:
                continue
            m = (lat >= ya) & (lat < yb)
            if not m.any():
                continue
            xcross = xa + (lat[m] - ya) * (xb - xa) / (yb - ya)
            hit = np.zeros(len(lon), dtype=bool)
            hit[m] = lon[m] < xcross
            res ^= hit
    return res


def ring_bbox(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return min(xs), max(xs), min(ys), max(ys)


def on_box_edge(a, b):
    """True when both points lie on the same edge of the bounding box."""
    for i, (lo, hi) in enumerate(((LON0, LON1), (LAT0, LAT1))):
        for v in (lo, hi):
            if abs(a[i] - v) < 1e-9 and abs(b[i] - v) < 1e-9:
                return True
    return False


def r4(v):
    return round(float(v), 4)


# ---------------------------------------------------------------- zones
def read_shapefile(zpath):
    z = zipfile.ZipFile(zpath)
    shp = [n for n in z.namelist() if n.lower().endswith(".shp")][0]
    base = shp[:-4]
    return shapefile.Reader(shp=io.BytesIO(z.read(shp)), dbf=io.BytesIO(z.read(base + ".dbf")),
                            shx=io.BytesIO(z.read(base + ".shx")))


def shape_rings(shape):
    parts = list(shape.parts) + [len(shape.points)]
    return [shape.points[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]


def geojson_rings(geom):
    if geom["type"] == "Polygon":
        return [[tuple(p) for p in r] for r in geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return [[tuple(p) for p in r] for poly in geom["coordinates"] for r in poly]
    return []


def build_zones():
    zones = {"sanctuary": [], "mpas": [], "lanes": [], "coast": [], "groups": []}
    # Sanctuary: two sections, each a polygon with island holes.
    r = read_shapefile(RAW / "cinms_py2.zip")
    for i, shape in enumerate(r.shapes()):
        rec = r.record(i)
        rings = [simplify(ring, 0.0012) for ring in shape_rings(shape)]
        rings = [rg for rg in rings if len(rg) >= 4]
        zones["sanctuary"].append({"name": rec["AREA_NAME"], "rings": rings})
    # State MPAs.
    gj = json.load(open(RAW / "ca_mpas_bbox.geojson"))
    for f in gj["features"]:
        p = f["properties"]
        rings = [simplify(rg, 0.0006) for rg in geojson_rings(f["geometry"])]
        rings = [rg for rg in rings if len(rg) >= 4]
        if not rings:
            continue
        zones["mpas"].append({"name": p["NAME"], "type": p["Type"], "rings": rings})
    zones["mpas"].sort(key=lambda m: m["name"])
    # State and federal reserves of the same name are one physical area in two
    # jurisdictions (for example Scorpion SMR and Scorpion FMR). Group them, so
    # that one visit counts as one entry.
    groups = []
    for m in zones["mpas"]:
        base = m["name"]
        for suffix in (" SMCA (No-Take)", " Special Closure", " SMCA", " SMR", " FMCA", " FMR"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        names = [g["name"] for g in groups]
        if base not in names:
            groups.append({"name": base, "types": []})
        g = groups[names.index(base) if base in names else len(groups) - 1]
        g["types"].append(m["type"])
        m["group"] = groups.index(g)
    zones["groups"] = groups
    # Chart traffic lanes and related areas.
    gj = json.load(open(RAW / "noaa_lanes_bbox.geojson"))
    for f in gj["features"]:
        p = f["properties"]
        rings = [simplify(rg, 0.0006) for rg in geojson_rings(f["geometry"])]
        rings = [clip_ring(rg, LON0 - 0.05, LON1 + 0.05, LAT0 - 0.05, LAT1 + 0.05) for rg in rings]
        rings = [rg for rg in rings if len(rg) >= 3]
        if rings:
            zones["lanes"].append({"type": p["THEMELAYER"], "rings": rings})
    # Coast: Natural Earth land and minor islands, clipped to the box.
    for name in ("ne_10m_land.zip", "ne_10m_minor_islands.zip"):
        r = read_shapefile(RAW / name)
        for shape in r.iterShapes():
            bx = shape.bbox
            if bx[2] < LON0 or bx[0] > LON1 or bx[3] < LAT0 or bx[1] > LAT1:
                continue
            for ring in shape_rings(shape):
                c = clip_ring(ring, LON0, LON1, LAT0, LAT1)
                if len(c) >= 3:
                    zones["coast"].append(simplify(c, 0.0003))
    return zones


# ---------------------------------------------------------------- tracks
def build_tracks():
    files = sorted(RAW.glob("ais_2023_06_*.csv"))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    n_bbox = len(df)
    n_vessels_bbox = df.MMSI.nunique()
    df["t"] = (pd.to_datetime(df.BaseDateTime) - T0).dt.total_seconds() / 60.0
    df = df[(df.t >= 0) & (df.t < MINUTES)]
    df = df.sort_values(["MMSI", "t"], kind="stable")
    vtype = df.groupby("MMSI").VesselType.agg(lambda s: s.mode().iloc[0] if s.notna().any() else np.nan)
    vlen = df.groupby("MMSI").Length.max()
    df["bin"] = (df.t // 5).astype(int)
    d = df.drop_duplicates(["MMSI", "bin"], keep="first")
    n_binned = len(d)

    vessels = []
    tri = []  # flat list of int16 triplets
    n_thinned = 0
    n_short = n_still = 0
    for mmsi, g in d.groupby("MMSI", sort=False):
        lon = g.LON.to_numpy()
        lat = g.LAT.to_numpy()
        t = g.t.to_numpy()
        kept = [0]
        for i in range(1, len(g)):
            k = kept[-1]
            if t[i] - t[k] >= 30 or dist_km(lon[k], lat[k], lon[i], lat[i]) >= 0.05:
                kept.append(i)
        n_thinned += len(kept)
        if len(kept) < 10:
            n_short += 1
            continue
        far = max(dist_km(lon[kept[0]], lat[kept[0]], lon[i], lat[i]) for i in kept)
        if far < 1.0:
            n_still += 1
            continue
        off = len(tri) // 3
        for i in kept:
            tri.append(int(round(t[i])))
            tri.append(int(round((lon[i] - LON0) * 1e4)))
            tri.append(int(round((lat[i] - LAT0) * 1e4)))
        L = vlen.get(mmsi, np.nan)
        vessels.append([classify(vtype.get(mmsi, np.nan)), int(L) if L == L else 0, off, len(kept)])

    arr = np.asarray(tri, dtype=np.int16)
    arr.tofile(OUT / "tracks.i16")
    meta = {"n_bbox_rows": n_bbox, "n_vessels_bbox": n_vessels_bbox, "n_binned": n_binned,
            "n_thinned": n_thinned, "n_short": n_short, "n_still": n_still,
            "n_vessels": len(vessels), "n_points": len(arr) // 3}
    return vessels, arr, meta


# ---------------------------------------------------------------- events
def build_events(vessels, arr, zones):
    t = arr[0::3].astype(np.int32)
    lon = arr[1::3].astype(np.float64) / 1e4 + LON0
    lat = arr[2::3].astype(np.float64) / 1e4 + LAT0
    vidx = np.zeros(len(t), dtype=np.int32)
    first = np.zeros(len(t), dtype=bool)
    for i, (_, _, off, n) in enumerate(vessels):
        vidx[off:off + n] = i
        first[off] = True

    def flags_for(rings_list):
        """Union of even-odd tests over a list of ring groups."""
        res = np.zeros(len(t), dtype=bool)
        for rings in rings_list:
            x0, x1, y0, y1 = ring_bbox(rings)
            m = (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1)
            if not m.any():
                continue
            sub = inside_rings(rings, lon[m], lat[m])
            tmp = np.zeros(len(t), dtype=bool)
            tmp[m] = sub
            res |= tmp
        return res

    events = []
    stats_zone = {}

    def add(kind, zidx, flags):
        entry = flags & ~np.roll(flags, 1) & ~first
        for i in np.nonzero(entry)[0]:
            events.append([int(t[i]), int(vidx[i]), kind, zidx])
        return int(entry.sum())

    sanct = flags_for([s["rings"] for s in zones["sanctuary"]])
    stats_zone["sanctuary"] = add(0, 0, sanct)
    mpa_counts = []
    for j, g in enumerate(zones["groups"]):
        fl = np.zeros(len(t), dtype=bool)
        for m in zones["mpas"]:
            if m["group"] == j:
                fl |= flags_for([m["rings"]])
        mpa_counts.append(add(1, j, fl))
    lane_types = ("Traffic Separation Schemes/Traffic Lanes", "Traffic Separation Schemes",
                  "Precautionary Areas")
    lanes = flags_for([l["rings"] for l in zones["lanes"] if l["type"] in lane_types])
    stats_zone["lanes"] = add(2, 0, lanes)
    stats_zone["mpa_total"] = int(sum(mpa_counts))
    events.sort()
    return events, stats_zone, mpa_counts, sanct, lanes


# ---------------------------------------------------------------- preview
def write_preview(vessels, arr, zones):
    W, H = 800, 500
    # Fit the box with equirectangular scaling, centered.
    sx = W / ((LON1 - LON0) * COS_LAT)
    sy = H / (LAT1 - LAT0)
    s = min(sx, sy)
    ox = (W - (LON1 - LON0) * COS_LAT * s) / 2
    oy = (H - (LAT1 - LAT0) * s) / 2

    def P(lon, lat):
        return (round(ox + (lon - LON0) * COS_LAT * s, 1), round(H - oy - (lat - LAT0) * s, 1))

    def path(rings):
        parts = []
        for rg in rings:
            parts.append("M" + " L".join(f"{x},{y}" for x, y in (P(*p) for p in rg)) + "Z")
        return "".join(parts)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           '<defs>',
           '<pattern id="h" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           '<line x1="0" y1="0" x2="0" y2="6" stroke="#7a5a3a" stroke-width="0.8" opacity="0.7"/></pattern>',
           '<radialGradient id="v" cx="50%" cy="50%" r="75%"><stop offset="0.6" stop-color="#f3e9d2" stop-opacity="0"/>'
           '<stop offset="1" stop-color="#c9b58f" stop-opacity="0.55"/></radialGradient>',
           '</defs>',
           f'<rect width="{W}" height="{H}" fill="#f3e9d2"/>']
    # Faint contour-like rings around land: wide strokes in paper color between ink strokes.
    coast = path(zones["coast"])
    for w in (34, 24, 14):
        out.append(f'<path d="{coast}" fill="none" stroke="#6f8fb0" stroke-opacity="0.35" stroke-width="{w}"/>')
        out.append(f'<path d="{coast}" fill="none" stroke="#f3e9d2" stroke-width="{w - 1.6}"/>')
    out.append(f'<path d="{coast}" fill="#e6d8b8"/>')
    edge = []
    for rg in zones["coast"]:
        for a, b in zip(rg, rg[1:] + rg[:1]):
            if on_box_edge(a, b):
                continue
            pa, pb = P(*a), P(*b)
            edge.append(f"M{pa[0]},{pa[1]} L{pb[0]},{pb[1]}")
    out.append(f'<path d="{"".join(edge)}" fill="none" stroke="#4a3a28" stroke-width="0.9" stroke-linecap="round"/>')
    out.append(f'<path d="{path([r for z in zones["sanctuary"] for r in z["rings"]])}" fill="#2b5ea8" '
               'fill-opacity="0.06" fill-rule="evenodd" stroke="#2b5ea8" stroke-width="1.1" stroke-dasharray="7 4"/>')
    lane = [r for z in zones["lanes"] if z["type"].startswith("Traffic Separation") for r in z["rings"]]
    out.append(f'<path d="{path(lane)}" fill="#a0522d" fill-opacity="0.08" stroke="#a0522d" stroke-width="0.6" stroke-dasharray="2 3"/>')
    out.append(f'<path d="{path([r for z in zones["mpas"] for r in z["rings"]])}" fill="url(#h)" '
               'fill-rule="evenodd" stroke="#7a5a3a" stroke-width="0.8"/>')
    # Tracks: every vessel, every second point, thin ink.
    t = arr[0::3]
    x = arr[1::3].astype(np.float64) / 1e4 + LON0
    y = arr[2::3].astype(np.float64) / 1e4 + LAT0
    by_class = {}
    for cls, L, off, n in vessels:
        seg = []
        segs = []
        for i in range(off, off + n, 2):
            if seg and (t[i] - t[i - 2] > 60 or
                        dist_km(x[i - 2], y[i - 2], x[i], y[i]) > 1.2 * max(1, t[i] - t[i - 2])):
                segs.append(seg)
                seg = []
            seg.append(P(x[i], y[i]))
        segs.append(seg)
        for sg in segs:
            if len(sg) > 1:
                by_class.setdefault(cls, []).append("M" + " L".join(f"{a},{b}" for a, b in sg))
    for cls, paths in by_class.items():
        out.append(f'<path d="{"".join(paths)}" fill="none" stroke="{COLORS[cls]}" stroke-opacity="0.33" '
                   'stroke-width="0.7" stroke-linejoin="round"/>')
    out.append(f'<rect width="{W}" height="{H}" fill="url(#v)"/>')
    # Compass rose.
    cx, cy = 700, 95
    out.append(f'<g stroke="#4a3a28" fill="none" stroke-width="0.8"><circle cx="{cx}" cy="{cy}" r="38"/>'
               f'<circle cx="{cx}" cy="{cy}" r="30"/>'
               f'<path d="M{cx},{cy - 46} L{cx + 7},{cy} L{cx},{cy + 46} L{cx - 7},{cy} Z" fill="#f3e9d2"/>'
               f'<path d="M{cx - 46},{cy} L{cx},{cy - 7} L{cx + 46},{cy} L{cx},{cy + 7} Z" fill="#f3e9d2"/>'
               f'<path d="M{cx},{cy - 46} L{cx + 7},{cy} L{cx},{cy} Z" fill="#4a3a28"/></g>')
    out.append(f'<text x="{cx}" y="{cy - 52}" text-anchor="middle" font-family="Georgia,serif" font-size="13" fill="#4a3a28">N</text>')
    out.append('<text x="28" y="44" font-family="Georgia,serif" font-size="26" fill="#2a2418" letter-spacing="1">SHIPS AT THE BORDER</text>')
    out.append('<text x="28" y="66" font-family="Georgia,serif" font-style="italic" font-size="13" fill="#4a3a28">'
               'Channel Islands National Marine Sanctuary · AIS tracks, 15 to 18 June 2023</text>')
    out.append('</svg>')
    (ROOM / "preview.svg").write_text("\n".join(out))


# ---------------------------------------------------------------- main
def main():
    zones = build_zones()
    print("zones:", {k: len(v) for k, v in zones.items()},
          "coast points", sum(len(r) for r in zones["coast"]))
    vessels, arr, meta = build_tracks()
    print("tracks:", meta)
    events, stats_zone, mpa_counts, sanct, lanes = build_events(vessels, arr, zones)
    print("events:", len(events), stats_zone)

    # Class statistics.
    cls_v = [0] * len(CLASSES)
    cls_p = [0] * len(CLASSES)
    for cls, L, off, n in vessels:
        cls_v[cls] += 1
        cls_p[cls] += n
    cls_entries = {"sanctuary": [0] * len(CLASSES), "mpa": [0] * len(CLASSES), "lanes": [0] * len(CLASSES)}
    for t, vi, kind, zi in events:
        key = ("sanctuary", "mpa", "lanes")[kind]
        cls_entries[key][vessels[vi][0]] += 1
    n_long = sum(1 for v in vessels if v[1] >= 200)

    # Share of track points inside the sanctuary and the lanes, by class.
    vidx = np.repeat(np.arange(len(vessels)), [v[3] for v in vessels])
    cls_of_pt = np.asarray([vessels[i][0] for i in vidx])
    share_sanct = [float(sanct[cls_of_pt == c].mean()) if cls_p[c] else 0.0 for c in range(len(CLASSES))]
    share_lanes = [float(lanes[cls_of_pt == c].mean()) if cls_p[c] else 0.0 for c in range(len(CLASSES))]

    # Write outputs.
    zj = {
        "bbox": [LON0, LON1, LAT0, LAT1],
        "sanctuary": [{"name": z["name"], "rings": [[[r4(x), r4(y)] for x, y in rg] for rg in z["rings"]]}
                      for z in zones["sanctuary"]],
        "mpas": [{"name": z["name"], "type": z["type"], "group": z["group"],
                  "rings": [[[r4(x), r4(y)] for x, y in rg] for rg in z["rings"]]}
                 for z in zones["mpas"]],
        "groups": [{"name": g["name"], "types": g["types"], "entries": mpa_counts[i]}
                   for i, g in enumerate(zones["groups"])],
        "lanes": [{"type": z["type"], "rings": [[[r4(x), r4(y)] for x, y in rg] for rg in z["rings"]]}
                  for z in zones["lanes"]],
        "coast": [[[r4(x), r4(y)] for x, y in rg] for rg in zones["coast"]],
    }
    json.dump(zj, open(OUT / "zones.json", "w"), separators=(",", ":"))
    json.dump({"classes": CLASSES, "colors": COLORS, "t0": "2023-06-15T00:00:00Z", "minutes": MINUTES,
               "origin": [LON0, LAT0], "scale": 1e4, "vessels": vessels},
              open(OUT / "vessels.json", "w"), separators=(",", ":"))
    json.dump(events, open(OUT / "events.json", "w"), separators=(",", ":"))
    raw_counts = [l.strip().split(",") for l in open(RAW / "counts.txt") if l.strip()]
    stats = {
        "days": [c[0] for c in raw_counts],
        "rows_read": sum(int(c[1]) for c in raw_counts),
        "rows_in_bbox": meta["n_bbox_rows"],
        "vessels_in_bbox": meta["n_vessels_bbox"],
        "points_after_5min": meta["n_binned"],
        "points_after_thinning": meta["n_thinned"],
        "vessels_dropped_short": meta["n_short"],
        "vessels_dropped_still": meta["n_still"],
        "vessels_kept": meta["n_vessels"],
        "points_kept": meta["n_points"],
        "vessels_200m_plus": n_long,
        "classes": CLASSES,
        "vessels_by_class": cls_v,
        "points_by_class": cls_p,
        "entries_by_class": cls_entries,
        "share_in_sanctuary_by_class": [round(v, 4) for v in share_sanct],
        "share_in_lanes_by_class": [round(v, 4) for v in share_lanes],
        "entries": stats_zone,
        "n_events": len(events),
        "n_mpas": len(zones["mpas"]),
        "n_mpa_groups": len(zones["groups"]),
    }
    json.dump(stats, open(OUT / "stats.json", "w"), indent=1)
    write_preview(vessels, arr, zones)
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:14s} {f.stat().st_size / 1e6:.3f} MB")
    print("preview.svg", (ROOM / "preview.svg").stat().st_size / 1e6, "MB")


if __name__ == "__main__":
    main()
