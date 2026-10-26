"""Process raw data for the room "The Commute Bloodstream".

Input (from fetch.py, in data/raw/commute-bloodstream/):
  il_od_main_JT00_2022.csv.gz   LODES8 block-to-block job counts, Illinois, 2022
  gaz_tracts_national.zip       Census Gazetteer 2023 tract centroids
  acs_b08302_il.psv             ACS 2022 5-year B08302 rows for Illinois (optional)
  counties-10m.json             us-atlas county outlines (optional)

Output (in rooms/commute-bloodstream/data/):
  tracts.json   tract centroids, departure profiles, county outlines, metadata
  pairs.bin     Uint16 triples (home index, work index, jobs) for the kept pairs
  ../preview.svg  a static still drawn from the same data

Steps:
  1. Read the tract centroids and keep the tracts inside the Chicago box.
  2. Stream the LODES file. Cut each 15-digit block code to the 11-digit tract
     code. Sum jobs for each (home tract, work tract) pair inside the box.
  3. Keep pairs with at least MIN_JOBS jobs. Keep at most MAX_PAIRS pairs,
     the largest first.
  4. Build a departure-time profile for each home tract from B08302.
  5. Decode the county outlines that touch the box.
  6. Write the compact files and the preview.

Run from the repository root:
  .venv/bin/python3 -I pipelines/commute-bloodstream/process.py
"""
import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "commute-bloodstream"
OUT = ROOT / "rooms" / "commute-bloodstream" / "data"
OUT.mkdir(parents=True, exist_ok=True)

# Chicago box. Lake Michigan is east of about -87.52 at the Loop.
LON0, LON1, LAT0, LAT1 = -88.4, -87.5, 41.5, 42.2
STATE_FIPS = "17"
MIN_JOBS = 10
MAX_PAIRS = 300000
# Hour edges of the 14 B08302 time bins (E002 .. E015).
BIN_EDGES = [0, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 10, 11, 12, 16, 24]
PRIOR_WEIGHT = 300  # tract profile = (tract counts + PRIOR_WEIGHT * county share) / (total + PRIOR_WEIGHT)


def load_tracts():
    """Return a DataFrame of Illinois tracts inside the box: geoid, lon, lat."""
    with zipfile.ZipFile(RAW / "gaz_tracts_national.zip") as z:
        name = [n for n in z.namelist() if n.endswith(".txt")][0]
        raw = z.read(name).decode("utf-8", errors="replace")
    df = pd.read_csv(io.StringIO(raw), sep="\t", dtype={"GEOID": str})
    df.columns = [c.strip() for c in df.columns]
    df = df[df["GEOID"].str.startswith(STATE_FIPS)]
    df = df[(df["INTPTLONG"] >= LON0) & (df["INTPTLONG"] <= LON1)
            & (df["INTPTLAT"] >= LAT0) & (df["INTPTLAT"] <= LAT1)]
    df = df.rename(columns={"GEOID": "geoid", "INTPTLONG": "lon", "INTPTLAT": "lat"})
    return df[["geoid", "lon", "lat"]].reset_index(drop=True)


def aggregate_pairs(tract_ids):
    """Stream the LODES file and sum jobs by tract pair inside the box."""
    keep = set(tract_ids)
    total_rows = 0
    total_jobs = 0
    parts = []
    reader = pd.read_csv(RAW / "il_od_main_JT00_2022.csv.gz", usecols=["w_geocode", "h_geocode", "S000"],
                         dtype={"w_geocode": str, "h_geocode": str, "S000": np.int32}, chunksize=500000)
    for chunk in reader:
        total_rows += len(chunk)
        total_jobs += int(chunk["S000"].sum())
        chunk["w"] = chunk["w_geocode"].str.slice(0, 11)
        chunk["h"] = chunk["h_geocode"].str.slice(0, 11)
        chunk = chunk[chunk["w"].isin(keep) & chunk["h"].isin(keep)]
        parts.append(chunk.groupby(["h", "w"], as_index=False)["S000"].sum())
    pairs = pd.concat(parts).groupby(["h", "w"], as_index=False)["S000"].sum()
    return pairs, total_rows, total_jobs


def departure_profiles(tracts):
    """Return a (N, 14) array of departure shares for each tract, and the county share."""
    path = RAW / "acs_b08302_il.psv"
    n = len(tracts)
    if not path.exists():
        # Fallback: a bell curve centered at 07:45 with a 1-hour spread.
        mids = [(BIN_EDGES[i] + BIN_EDGES[i + 1]) / 2 for i in range(14)]
        w = np.array([math.exp(-0.5 * ((m - 7.75) / 1.0) ** 2) for m in mids])
        w /= w.sum()
        return np.tile(w, (n, 1)), w, "bell-curve fallback"
    df = pd.read_csv(path, sep="|", dtype={"GEO_ID": str})
    cols = [f"B08302_E{i:03d}" for i in range(2, 16)]
    county_rows = df[df["GEO_ID"].str.startswith("0500000US")]
    tract_rows = df[df["GEO_ID"].str.startswith("1400000US")]
    county_counts = {r["GEO_ID"][-5:]: r[cols].to_numpy(dtype=float) for _, r in county_rows.iterrows()}
    tract_counts = {r["GEO_ID"][-11:]: r[cols].to_numpy(dtype=float) for _, r in tract_rows.iterrows()}
    out = np.zeros((n, 14))
    metro_total = np.zeros(14)
    for i, g in enumerate(tracts["geoid"]):
        c = county_counts.get(g[:5])
        if c is None or c.sum() <= 0:
            c = np.ones(14)
        cshare = c / c.sum()
        t = tract_counts.get(g)
        if t is None or not np.isfinite(t).all():
            t = np.zeros(14)
        out[i] = (t + PRIOR_WEIGHT * cshare) / (t.sum() + PRIOR_WEIGHT)
        metro_total += t
    metro_share = metro_total / metro_total.sum()
    return out, metro_share, "ACS 2022 5-year B08302, tract counts smoothed toward the county share"


def county_outlines():
    """Decode us-atlas counties-10m.json and return polylines that touch the box."""
    path = RAW / "counties-10m.json"
    if not path.exists():
        return []
    topo = json.loads(path.read_text())
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((round(x * sx + tx, 4), round(y * sy + ty, 4)))
        arcs.append(pts)
    seen = set()
    lines = []
    pad = 0.2
    for g in topo["objects"]["counties"]["geometries"]:
        if g["id"][:2] not in ("17", "18", "55"):
            continue
        rings = g["arcs"] if g["type"] == "Polygon" else [r for poly in g["arcs"] for r in poly]
        for ring in rings:
            for a in ring:
                idx = a if a >= 0 else ~a
                if idx in seen:
                    continue
                pts = arcs[idx]
                if any(LON0 - pad <= p[0] <= LON1 + pad and LAT0 - pad <= p[1] <= LAT1 + pad for p in pts):
                    seen.add(idx)
                    lines.append(pts)
    return lines


def write_preview(tracts, pairs, core_idx):
    """Draw an 800x500 SVG still: faint tract dots, the top flows in the accent color."""
    W, H = 800, 500
    # Map the box to a plot area on the right, with a text column on the left.
    px0, px1, py0, py1 = 300, 780, 30, 480
    lat_mid = (LAT0 + LAT1) / 2
    kx = math.cos(math.radians(lat_mid))
    span_x = (LON1 - LON0) * kx
    span_y = LAT1 - LAT0
    s = min((px1 - px0) / span_x, (py1 - py0) / span_y)
    ox = px0 + ((px1 - px0) - span_x * s) / 2
    oy = py0 + ((py1 - py0) - span_y * s) / 2

    def P(lon, lat):
        return ox + (lon - LON0) * kx * s, oy + (LAT1 - lat) * s

    lons = tracts["lon"].to_numpy()
    lats = tracts["lat"].to_numpy()
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             '<rect width="100%" height="100%" fill="#fff"/>']
    top = pairs.sort_values("S000", ascending=False).head(900)
    for _, r in top.iterrows():
        x0, y0 = P(lons[r.hi], lats[r.hi])
        x1, y1 = P(lons[r.wi], lats[r.wi])
        if r.hi == r.wi:
            continue
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = x1 - x0, y1 - y0
        cx, cy = mx - dy * 0.18, my + dx * 0.18
        w = 0.4 + 1.6 * min(1.0, r.S000 / 800)
        parts.append(f'<path d="M{x0:.1f},{y0:.1f} Q{cx:.1f},{cy:.1f} {x1:.1f},{y1:.1f}" '
                     f'fill="none" stroke="#e30613" stroke-opacity="0.55" stroke-width="{w:.2f}"/>')
    dots = " ".join(f"M{P(lo, la)[0]:.1f},{P(lo, la)[1]:.1f}h0.01" for lo, la in zip(lons, lats))
    parts.append(f'<path d="{dots}" stroke="#000" stroke-opacity="0.35" stroke-width="1.6" stroke-linecap="round" fill="none"/>')
    cx, cy = P(lons[core_idx], lats[core_idx])
    parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="#000"/>')
    parts.append('<g font-family="Helvetica Neue, Helvetica, Arial, sans-serif" fill="#000">')
    parts.append('<text x="40" y="70" font-size="13" letter-spacing="2">THIRTEEN ROOMS — 03</text>')
    parts.append('<text x="40" y="130" font-size="34" font-weight="700">The Commute</text>')
    parts.append('<text x="40" y="168" font-size="34" font-weight="700">Bloodstream</text>')
    parts.append('<text x="40" y="215" font-size="12" fill="#555">Chicago, home to work and back.</text>')
    parts.append('<text x="40" y="232" font-size="12" fill="#555">Census LODES 2022, ACS B08302.</text>')
    jobs = int(pairs["S000"].sum())
    parts.append(f'<text x="40" y="330" font-size="56" font-weight="700" letter-spacing="-2">{jobs / 1e6:.2f}M</text>')
    parts.append('<text x="40" y="352" font-size="12" fill="#555">jobs in the kept tract pairs</text>')
    parts.append('<line x1="40" y1="440" x2="260" y2="440" stroke="#000" stroke-width="1"/>')
    parts.append('<line x1="105" y1="434" x2="105" y2="446" stroke="#e30613" stroke-width="2"/>')
    parts.append('<text x="40" y="462" font-size="10" fill="#555">00</text>')
    parts.append('<text x="250" y="462" font-size="10" fill="#555">24</text>')
    parts.append('</g></svg>')
    (OUT.parent / "preview.svg").write_text("\n".join(parts))


def main():
    tracts = load_tracts()
    print(f"tracts in box: {len(tracts)}")
    pairs, total_rows, total_jobs = aggregate_pairs(tracts["geoid"])
    print(f"LODES rows: {total_rows}, jobs in file: {total_jobs}")
    print(f"tract pairs in box: {len(pairs)}, jobs in box: {int(pairs['S000'].sum())}")
    pairs_in_box = int(len(pairs))
    jobs_in_box = int(pairs["S000"].sum())
    pairs = pairs[pairs["S000"] >= MIN_JOBS]
    print(f"pairs with >= {MIN_JOBS} jobs: {len(pairs)}, jobs: {int(pairs['S000'].sum())}")
    pairs = pairs.sort_values("S000", ascending=False).head(MAX_PAIRS).reset_index(drop=True)
    kept_jobs = int(pairs["S000"].sum())
    print(f"kept pairs: {len(pairs)}, jobs: {kept_jobs}")

    # Keep only tracts that appear in a kept pair.
    used = set(pairs["h"]) | set(pairs["w"])
    tracts = tracts[tracts["geoid"].isin(used)].reset_index(drop=True)
    index = {g: i for i, g in enumerate(tracts["geoid"])}
    pairs["hi"] = pairs["h"].map(index).astype(np.int32)
    pairs["wi"] = pairs["w"].map(index).astype(np.int32)
    inflow = pairs.groupby("wi")["S000"].sum()
    core_idx = int(inflow.idxmax())
    print(f"core tract: {tracts['geoid'][core_idx]} with {int(inflow.max())} inbound jobs")

    profiles, metro_share, profile_note = departure_profiles(tracts)
    outlines = county_outlines()
    print(f"county outline arcs: {len(outlines)}")

    # pairs.bin: Uint16 triples (home index, work index, jobs). Jobs cap at 65535.
    arr = np.zeros((len(pairs), 3), dtype=np.uint16)
    arr[:, 0] = pairs["hi"].to_numpy()
    arr[:, 1] = pairs["wi"].to_numpy()
    arr[:, 2] = np.minimum(pairs["S000"].to_numpy(), 65535)
    (OUT / "pairs.bin").write_bytes(arr.tobytes())

    # tracts.json: positions, departure profiles (0..255), outlines, metadata.
    q = np.rint(profiles * 255).astype(int).clip(0, 255)
    meta = {
        "metro": "Chicago, Illinois",
        "bbox": [LON0, LAT0, LON1, LAT1],
        "source_od": "LODES8 il_od_main_JT00_2022 (jobs 2022, all jobs, home and work in Illinois)",
        "source_centroids": "Census Gazetteer 2023 tracts",
        "source_departure": profile_note,
        "lodes_rows": total_rows,
        "lodes_jobs_state": total_jobs,
        "pairs_in_box": pairs_in_box,
        "jobs_in_box": jobs_in_box,
        "min_jobs": MIN_JOBS,
        "max_pairs": MAX_PAIRS,
        "pairs_kept": int(len(pairs)),
        "jobs_kept": kept_jobs,
        "tracts_kept": int(len(tracts)),
        "core_index": core_idx,
        "core_geoid": tracts["geoid"][core_idx],
        "bin_edges": BIN_EDGES,
        "metro_departure_share": [round(float(v), 4) for v in metro_share],
    }
    data = {
        "meta": meta,
        "tracts": [[g, round(float(lo), 5), round(float(la), 5)] for g, lo, la in
                   zip(tracts["geoid"], tracts["lon"], tracts["lat"])],
        "departure": q.flatten().tolist(),
        "counties": [[[p[0], p[1]] for p in line] for line in outlines],
    }
    (OUT / "tracts.json").write_text(json.dumps(data, separators=(",", ":")))
    write_preview(tracts, pairs, core_idx)
    for f in sorted(OUT.iterdir()):
        print(f"{f.name}: {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
