"""Assemble the reduced NEXRAD scans into the room data files.

Run from the repository root after fetch.py:
    .venv/bin/python3 -I pipelines/bird-radar/process.py

Input:  data/raw/bird-radar/selection.json and data/raw/bird-radar/scans/*.npz
Output: rooms/bird-radar/data/frames.bin   (Uint8, one byte per polar bin)
        rooms/bird-radar/data/manifest.json
        rooms/bird-radar/preview.svg

Byte layout of one bin in frames.bin:
  bits 0-5 : reflectivity code q. 0 means no echo. 1..63 maps to -10..40 dBZ
             in equal steps. dBZ = (q - 1) / 62 * 50 - 10.
  bits 6-7 : class. 1 = biological echo (mean RHO below 0.95),
             2 = rain-like echo (mean RHO at or above 0.95), 0 = no echo.
Frame order: station, then night, then scan (baseline, takeoff, peak).
Each frame has 360 azimuth rows of 40 range bins (1 degree by 2.5 km).
"""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "raw" / "bird-radar"
OUT = ROOT / "rooms" / "bird-radar" / "data"
PREVIEW = ROOT / "rooms" / "bird-radar" / "preview.svg"

AZ_BINS, RNG_BINS, RNG_STEP_KM = 360, 40, 2.5
# A night is "weather" when any of its scans has at least this share of
# rain-like echo (RHO >= 0.95) inside the 5 to 80 km window.
WX_NIGHT = 0.35
TZ = {"KTLX": -5, "KLOT": -5, "KDOX": -4}  # UTC offsets in spring (CDT, CDT, EDT)


def encode(dbz, cls):
    q = np.zeros(dbz.shape, dtype=np.uint8)
    fin = np.isfinite(dbz)
    v = np.clip((np.where(fin, dbz, -10.0) + 10.0) / 50.0, 0.0, 1.0)
    q[fin] = (1 + np.round(v[fin] * 62.0)).astype(np.uint8)
    return (q | (cls.astype(np.uint8) << 6)).astype(np.uint8)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with open(RAW / "selection.json") as fh:
        sel = json.load(fh)
    frames = []
    manifest = {
        "az_bins": AZ_BINS, "rng_bins": RNG_BINS, "rng_step_km": RNG_STEP_KM,
        "dbz_min": -10, "dbz_max": 40, "wx_night": WX_NIGHT,
        "scan_labels": ["baseline", "takeoff", "peak"],
        "stations": [],
    }
    n_in = n_kept = 0
    for st in sel["stations"]:
        nights_out = []
        for night in st["nights"]:
            scans_out = []
            for s in night["scans"]:
                n_in += 1
                if not s["key"]:
                    continue
                p = RAW / "scans" / (s["key"].split("/")[-1] + ".npz")
                if not p.exists():
                    continue
                z = np.load(p, allow_pickle=False)
                idx, cov, wx, bio, el = [float(x) for x in z["scalars"]]
                scans_out.append({
                    "label": s["label"], "offset_h": s["offset_h"], "time": str(z["time"]),
                    "frame": len(frames), "idx": round(idx, 1), "cov": round(cov, 3),
                    "wx": round(wx, 3), "bio": round(bio, 1), "el": round(el, 2),
                })
                frames.append(encode(z["dbz"], z["cls"]))
                n_kept += 1
            if len(scans_out) != 3:
                # Drop the night when one scan is missing. Remove its frames.
                for s in scans_out:
                    frames[s["frame"]] = None
                print(f"drop {st['id']} {night['date']}: {len(scans_out)} of 3 scans")
                continue
            nights_out.append({
                "date": night["date"], "sunset": night["sunset"],
                "weather": bool(max(s["wx"] for s in scans_out) >= WX_NIGHT),
                "scans": scans_out,
            })
        manifest["stations"].append({
            "id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
            "tz": TZ[st["id"]], "nights": nights_out,
        })
    # Renumber frames after drops.
    keep = [i for i, f in enumerate(frames) if f is not None]
    remap = {old: new for new, old in enumerate(keep)}
    for st in manifest["stations"]:
        for n in st["nights"]:
            for s in n["scans"]:
                s["frame"] = remap[s["frame"]]
    buf = np.stack([frames[i] for i in keep]).astype(np.uint8)
    manifest["n_frames"] = int(buf.shape[0])
    buf.tofile(OUT / "frames.bin")
    with open(OUT / "manifest.json", "w") as fh:
        json.dump(manifest, fh, separators=(",", ":"))
    size = (OUT / "frames.bin").stat().st_size + (OUT / "manifest.json").stat().st_size
    print(f"scans selected {n_in}, reduced {n_kept}, frames written {buf.shape[0]}, {size/1e6:.2f} MB")
    for st in manifest["stations"]:
        wx = sum(1 for n in st["nights"] if n["weather"])
        print(f"  {st['id']}: {len(st['nights'])} nights, {wx} marked weather")
    write_preview(manifest, buf)


def write_preview(manifest, buf):
    """Draw an 800x500 radar scope still from the strongest clear KTLX night."""
    st = manifest["stations"][0]
    # Prefer a night with less than 12 percent rain-like echo in every scan.
    clear = [n for n in st["nights"] if max(x["wx"] for x in n["scans"]) < 0.12] or st["nights"]
    # Among those, take the strong night with the clearest ring: the largest
    # spread of the median reflectivity across range.
    def ring_contrast(n):
        f = buf[n["scans"][2]["frame"]].reshape(AZ_BINS, RNG_BINS)
        q = (f & 63).astype(float)
        q[q == 0] = np.nan
        prof = np.nanmedian(q, axis=0)
        return float(np.nanmax(prof) - np.nanmin(prof)) if n["scans"][2]["bio"] >= 12 else -1.0
    night = max(clear, key=ring_contrast)
    scan = night["scans"][2]
    fr = buf[scan["frame"]].reshape(AZ_BINS, RNG_BINS)
    sweep_deg = 118.0
    cx, cy, R = 240.0, 250.0, 205.0
    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">')
    parts.append('<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
                 '<stop offset="0" stop-color="#2a1a3a"/><stop offset="0.45" stop-color="#0d0f24"/>'
                 '<stop offset="1" stop-color="#03040a"/></linearGradient>'
                 '<radialGradient id="bez" cx="0.5" cy="0.5" r="0.5"><stop offset="0.86" stop-color="#1a1a1a"/>'
                 '<stop offset="0.93" stop-color="#4a4a48"/><stop offset="1" stop-color="#101010"/></radialGradient>'
                 '<radialGradient id="glass" cx="0.35" cy="0.3" r="0.7"><stop offset="0" stop-color="#ffffff" stop-opacity="0.08"/>'
                 '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></radialGradient></defs>')
    parts.append('<rect width="800" height="500" fill="url(#sky)"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{R+22}" fill="url(#bez)"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="#020603"/>')
    # Aggregate to 6 degree by 5 km wedges, mean of linear reflectivity.
    for a in range(0, 360, 6):
        for r in range(0, RNG_BINS, 2):
            block = fr[a:a + 6, r:r + 2]
            q = (block & 63).astype(float)
            cls = block >> 6
            has = q > 0
            if not has.any():
                continue
            dbz = (q[has] - 1) / 62 * 50 - 10
            lin = (10 ** (dbz / 10)).mean()
            val = max(0.0, min(1.0, (10 * math.log10(lin) + 5) / 35)) ** 0.9
            wx = (cls[has] == 2).mean() >= 0.5
            if val < 0.03:
                continue
            # Afterglow: bins far behind the sweep are dimmer, as on the live scope.
            behind = (sweep_deg - (a + 3)) % 360
            val *= 0.34 + 0.66 * math.exp(-behind / 75.0)
            r0, r1 = R * r / RNG_BINS, R * (r + 2) / RNG_BINS
            a0, a1 = math.radians(a - 90), math.radians(a + 6 - 90)
            x0, y0 = cx + r0 * math.cos(a0), cy + r0 * math.sin(a0)
            x1, y1 = cx + r1 * math.cos(a0), cy + r1 * math.sin(a0)
            x2, y2 = cx + r1 * math.cos(a1), cy + r1 * math.sin(a1)
            x3, y3 = cx + r0 * math.cos(a1), cy + r0 * math.sin(a1)
            col = ramp(WX_STOPS if wx else BIO_STOPS, val)
            parts.append(f'<path d="M{x0:.1f} {y0:.1f}L{x1:.1f} {y1:.1f}A{r1:.1f} {r1:.1f} 0 0 1 {x2:.1f} {y2:.1f}'
                         f'L{x3:.1f} {y3:.1f}A{r0:.1f} {r0:.1f} 0 0 0 {x0:.1f} {y0:.1f}Z" fill="{col}" stroke="{col}" stroke-width="0.4"/>')
    for k in range(1, 5):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{R*k/4:.1f}" fill="none" stroke="#2f7a45" stroke-opacity="0.7" stroke-width="1"/>')
    for d in range(0, 360, 30):
        a = math.radians(d - 90)
        parts.append(f'<line x1="{cx+(R-8)*math.cos(a):.1f}" y1="{cy+(R-8)*math.sin(a):.1f}" x2="{cx+R*math.cos(a):.1f}" y2="{cy+R*math.sin(a):.1f}" stroke="#4fd27a" stroke-width="1.5"/>')
    sweep = math.radians(sweep_deg - 90)
    parts.append(f'<path d="M{cx} {cy}L{cx+R*math.cos(sweep-0.9):.1f} {cy+R*math.sin(sweep-0.9):.1f}A{R} {R} 0 0 1 {cx+R*math.cos(sweep):.1f} {cy+R*math.sin(sweep):.1f}Z" fill="#6cff9a" fill-opacity="0.12"/>')
    parts.append(f'<line x1="{cx}" y1="{cy}" x2="{cx+R*math.cos(sweep):.1f}" y2="{cy+R*math.sin(sweep):.1f}" stroke="#c8ffd8" stroke-width="2"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="url(#glass)"/>')
    parts.append('<g font-family="Share Tech Mono, Menlo, Consolas, monospace" fill="#8ff2ae">')
    parts.append('<text x="490" y="88" font-size="25" fill="#d9ffe6">BIRDS ON THE RADAR</text>')
    parts.append('<text x="490" y="114" font-size="12" fill="#8ff2ae">NEXRAD LEVEL II · 0.5° REFLECTIVITY</text>')
    local = _local_time(scan["time"], st["tz"])
    parts.append(f'<text x="490" y="165" font-size="19" fill="#d9ffe6">{st["id"]} {st["name"].upper()}</text>')
    parts.append(f'<text x="490" y="193" font-size="14">NIGHT {night["date"]}</text>')
    parts.append(f'<text x="490" y="216" font-size="14">PEAK SCAN {local} LOCAL</text>')
    parts.append(f'<text x="490" y="239" font-size="14">BIO INDEX {scan["bio"]:.1f} dBZ · COVER {scan["cov"]*100:.0f}%</text>')
    parts.append('<text x="490" y="285" font-size="12" fill="#6fbf8a">Each clear spring night, millions of birds</text>')
    parts.append('<text x="490" y="304" font-size="12" fill="#6fbf8a">take off after sunset and bloom as a ring</text>')
    parts.append('<text x="490" y="323" font-size="12" fill="#6fbf8a">of green echo around the weather radar.</text>')
    # Strip chart of the peak bio index across all nights.
    nights = st["nights"]
    x0, x1, y0, y1 = 490, 770, 372, 452
    parts.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#e9e2c8"/>')
    for k in range(1, 5):
        yy = y0 + (y1 - y0) * k / 5
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="#c9a46a" stroke-width="0.6"/>')
    pts = []
    for i, n in enumerate(nights):
        v = n["scans"][2]["bio"]
        xx = x0 + (x1 - x0) * i / max(len(nights) - 1, 1)
        yy = y1 - (y1 - y0) * max(0.0, min(1.0, (v + 10) / 50))
        pts.append(f"{xx:.1f},{yy:.1f}")
        if n["weather"]:
            w = (x1 - x0) / max(len(nights) - 1, 1)
            parts.append(f'<rect x="{xx-w/2:.1f}" y="{y0}" width="{w:.1f}" height="{y1-y0}" fill="#b36b3a" fill-opacity="0.25"/>')
    parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#1b1b1b" stroke-width="1.5"/>')
    parts.append(f'<text x="{x0}" y="{y1+16}" font-size="11" fill="#8ff2ae">{nights[0]["date"]}</text>')
    parts.append(f'<text x="{x1}" y="{y1+16}" font-size="11" fill="#8ff2ae" text-anchor="end">{nights[-1]["date"]}</text>')
    parts.append(f'<text x="{x0}" y="{y0-6}" font-size="11" fill="#8ff2ae">PEAK BIO INDEX, dBZ, ALL NIGHTS</text>')
    parts.append('</g></svg>')
    PREVIEW.write_text("\n".join(parts))
    print(f"preview {PREVIEW.stat().st_size/1e3:.0f} kB from {st['id']} {night['date']}")


# Phosphor ramps. The room page uses the same stops.
BIO_STOPS = [(0.0, "#07220f"), (0.35, "#157d38"), (0.7, "#48ff80"), (1.0, "#e6fff0")]
WX_STOPS = [(0.0, "#2a1a06"), (0.5, "#9c6424"), (1.0, "#e2aa63")]


def ramp(stops, t):
    """Interpolate a hex color along the stops at position t in 0..1."""
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0)
            a = [int(c0[i:i + 2], 16) for i in (1, 3, 5)]
            b = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
            return "#" + "".join(f"{round(x + (y - x) * u):02x}" for x, y in zip(a, b))
    return stops[-1][1]


def _local_time(iso, tz):
    hh, mm = int(iso[11:13]), int(iso[14:16])
    hh = (hh + tz) % 24
    return f"{hh:02d}:{mm:02d}"


if __name__ == "__main__":
    main()
