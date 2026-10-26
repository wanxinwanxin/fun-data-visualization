"""Fetch NEXRAD Level II scans for the Birds on the Radar room.

Run from the repository root:
    .venv/bin/python3 -I pipelines/bird-radar/fetch.py

Steps:
  1. For each station and each night, compute the local sunset with a
     simple solar formula (no package needed).
  2. List the public S3 bucket for the two UTC days that cover the night.
  3. Pick three scans per night: 1 hour before sunset (baseline),
     1 hour after sunset (takeoff), and 2.5 hours after sunset (peak).
  4. Download each scan, reduce it to a small polar grid with MetPy,
     save the grid to data/raw/bird-radar/scans/, and delete the raw file.

The script is resumable. It skips scans that already have a reduced file.
The raw files are 5 to 15 MB each. Only one raw file exists at a time.

Source: NOAA NEXRAD Level II archive on AWS Open Data. The NOAA bucket
(noaa-nexrad-level2) refused anonymous requests on this machine, so the
script reads the Unidata mirror of the same archive (unidata-nexrad-level2).
Both buckets hold the same files under the same keys.
"""
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "raw" / "bird-radar"
SCANS = RAW / "scans"
SELECTION = RAW / "selection.json"
LOG = RAW / "fetch.log"

BUCKETS = [
    "https://noaa-nexrad-level2.s3.amazonaws.com",
    "https://unidata-nexrad-level2.s3.amazonaws.com",
]

STATIONS = [
    {"id": "KTLX", "name": "Oklahoma City", "lat": 35.3334, "lon": -97.2778},
    {"id": "KLOT", "name": "Chicago", "lat": 41.6045, "lon": -88.0846},
    {"id": "KDOX", "name": "Dover", "lat": 38.8256, "lon": -75.4400},
]

FIRST_NIGHT = date(2024, 4, 20)
LAST_NIGHT = date(2024, 5, 25)

# Scan offsets from local sunset, in hours. Three scans per night.
OFFSETS = [-1.0, 1.0, 2.5]
OFFSET_LABELS = ["baseline", "takeoff", "peak"]

# Polar grid: 360 azimuth bins of 1 degree, 40 range bins of 2.5 km (to 100 km).
AZ_BINS = 360
RNG_BINS = 40
RNG_STEP_KM = 2.5
MAX_KM = RNG_BINS * RNG_STEP_KM

# Range window for the migration index, in km.
IDX_MIN_KM = 5.0
IDX_MAX_KM = 80.0

# Dual-pol threshold. Echo gates with RHO below this value are biological.
RHO_BIO = 0.95


def log(msg):
    line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


def sunset_utc(day, lat, lon):
    """Return the sunset on the given date as a UTC datetime.

    The date is the local calendar date of the evening. The formula is the
    NOAA solar calculator formula with a zenith of 90.833 degrees. The result
    is good to about one minute, which is enough here.
    """
    n = day.timetuple().tm_yday
    lng_hour = lon / 15.0
    t = n + ((18 - lng_hour) / 24.0)
    m = (0.9856 * t) - 3.289
    l = m + (1.916 * math.sin(math.radians(m))) + (0.020 * math.sin(math.radians(2 * m))) + 282.634
    l = l % 360.0
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360.0
    lq = (math.floor(l / 90.0)) * 90.0
    raq = (math.floor(ra / 90.0)) * 90.0
    ra = (ra + (lq - raq)) / 15.0
    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    zenith = 90.833
    cos_h = (math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(lat)))) / (cos_dec * math.cos(math.radians(lat)))
    h = math.degrees(math.acos(cos_h)) / 15.0
    local_t = h + ra - (0.06571 * t) - 6.622
    ut = (local_t - lng_hour) % 24.0
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    # The day is the local calendar date of the evening. For stations in the
    # United States the sunset in UTC is always after 12:00 UTC. A UTC hour
    # below 12 means that the sunset falls on the next UTC date.
    if ut < 12.0:
        base += timedelta(days=1)
    return base + timedelta(hours=ut)


def http_get(url, retries=4):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def list_day(bucket, station, day):
    """Return the list of (key, datetime) for one station and one UTC day."""
    prefix = f"{day.strftime('%Y/%m/%d')}/{station}/"
    out = []
    marker = ""
    while True:
        url = f"{bucket}/?prefix={prefix}&max-keys=1000" + (f"&marker={marker}" if marker else "")
        xml = http_get(url).decode("utf-8", "replace")
        if "<Code>AccessDenied</Code>" in xml:
            raise PermissionError("AccessDenied")
        keys = re.findall(r"<Key>([^<]+)</Key>", xml)
        for k in keys:
            m = re.search(rf"{station}(\d{{8}})_(\d{{6}})_V06$", k)
            if not m:
                continue
            dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            out.append((k, dt))
        if "<IsTruncated>true</IsTruncated>" in xml and keys:
            marker = keys[-1]
        else:
            break
    return out


def pick_bucket():
    """Return the first bucket that answers a listing request."""
    for b in BUCKETS:
        try:
            list_day(b, "KTLX", date(2024, 5, 1))
            log(f"using bucket {b}")
            return b
        except Exception as e:  # noqa: BLE001
            log(f"bucket {b} not usable: {e}")
    raise SystemExit("No NEXRAD bucket is reachable.")


def build_selection(bucket):
    """Choose the scan keys for every station and night. Cache the result."""
    if SELECTION.exists():
        with open(SELECTION) as fh:
            return json.load(fh)
    sel = {"bucket": bucket, "stations": []}
    for st in STATIONS:
        nights = []
        day = FIRST_NIGHT
        listing_cache = {}
        while day <= LAST_NIGHT:
            ss = sunset_utc(day, st["lat"], st["lon"])
            keys = []
            for d in sorted({(ss + timedelta(hours=o)).date() for o in OFFSETS} | {ss.date()}):
                if d not in listing_cache:
                    listing_cache[d] = list_day(bucket, st["id"], d)
                keys += listing_cache[d]
            scans = []
            for off, lab in zip(OFFSETS, OFFSET_LABELS):
                target = ss + timedelta(hours=off)
                best = None
                for k, dt in keys:
                    gap = abs((dt - target).total_seconds())
                    if best is None or gap < best[0]:
                        best = (gap, k, dt)
                if best is None or best[0] > 25 * 60:
                    scans.append({"label": lab, "offset_h": off, "key": None})
                else:
                    scans.append({"label": lab, "offset_h": off, "key": best[1],
                                  "time": best[2].strftime("%Y-%m-%dT%H:%M:%SZ")})
            nights.append({"date": day.isoformat(), "sunset": ss.strftime("%Y-%m-%dT%H:%M:%SZ"), "scans": scans})
            log(f"{st['id']} {day} sunset {ss.strftime('%H:%M')}Z scans " +
                " ".join((s["key"] or "none").split("/")[-1][13:19] for s in scans))
            day += timedelta(days=1)
        sel["stations"].append({**st, "nights": nights})
    with open(SELECTION, "w") as fh:
        json.dump(sel, fh, indent=1)
    return sel


def reduce_scan(path):
    """Reduce one Level II file to a polar grid plus scalar indices.

    Returns a dict with:
      dbz: float32 (360, 40) mean reflectivity per bin in dBZ, NaN where no echo
      bio: uint8 (360, 40) 1 where the mean RHO of the echo gates is below RHO_BIO,
           2 where it is at or above (weather-like), 0 where there is no echo
      idx, cov, wx, bio_idx: scalar indices over the 5 to 80 km window
    """
    from metpy.io import Level2File

    f = Level2File(str(path))
    sweep = None
    for sw in f.sweeps:
        hdr = sw[0][0]
        if len(sw[0]) < 5 or b"REF" not in sw[0][4]:
            continue
        if hdr.el_angle < 1.2:
            sweep = sw
            break
    if sweep is None:
        raise ValueError("no low REF sweep")

    az_all, r_all, z_all, rho_all = [], [], [], []
    for radial in sweep:
        hdr = radial[0]
        blocks = radial[4]
        ref_hdr, ref = blocks[b"REF"]
        ng = ref_hdr.num_gates
        r = ref_hdr.first_gate + ref_hdr.gate_width * np.arange(ng)
        keep = r < MAX_KM
        r = r[keep]
        ref = np.asarray(ref, dtype=np.float32)[keep]
        rho = np.full(r.shape, np.nan, dtype=np.float32)
        if b"RHO" in blocks:
            rho_hdr, rho_raw = blocks[b"RHO"]
            rr = rho_hdr.first_gate + rho_hdr.gate_width * np.arange(rho_hdr.num_gates)
            rho_raw = np.asarray(rho_raw, dtype=np.float32)
            # Map RHO gates onto the REF gates by nearest range.
            idx = np.clip(np.round((r - rho_hdr.first_gate) / rho_hdr.gate_width).astype(int), 0, rho_hdr.num_gates - 1)
            rho = rho_raw[idx]
        az_all.append(np.full(r.shape, hdr.az_angle % 360.0, dtype=np.float32))
        r_all.append(r.astype(np.float32))
        z_all.append(ref)
        rho_all.append(rho)
    az = np.concatenate(az_all)
    r = np.concatenate(r_all)
    dbz = np.concatenate(z_all)
    rho = np.concatenate(rho_all)

    has = np.isfinite(dbz)
    dbz_c = np.clip(np.where(has, dbz, -10.0), -10.0, 40.0)
    zlin = np.where(has, 10.0 ** (dbz_c / 10.0), 0.0)

    ai = np.floor(az).astype(int) % AZ_BINS
    ri = np.floor(r / RNG_STEP_KM).astype(int)
    ok = (ri >= 0) & (ri < RNG_BINS)
    flat = ai[ok] * RNG_BINS + ri[ok]
    n_bins = AZ_BINS * RNG_BINS
    cnt = np.bincount(flat, minlength=n_bins).astype(np.float64)
    zsum = np.bincount(flat, weights=zlin[ok], minlength=n_bins)
    echo = has & (dbz > 0.0)
    rho_ok = echo & np.isfinite(rho) & ok
    flat_r = ai[rho_ok] * RNG_BINS + ri[rho_ok]
    rcnt = np.bincount(flat_r, minlength=n_bins).astype(np.float64)
    rsum = np.bincount(flat_r, weights=rho[rho_ok], minlength=n_bins)
    with np.errstate(divide="ignore", invalid="ignore"):
        zmean = zsum / np.maximum(cnt, 1)
        grid = np.where(zmean > 0, 10.0 * np.log10(np.maximum(zmean, 1e-9)), np.nan)
        rmean = np.where(rcnt > 0, rsum / np.maximum(rcnt, 1), np.nan)
    cls = np.zeros(n_bins, dtype=np.uint8)
    cls[np.isfinite(grid)] = 1
    cls[np.isfinite(rmean) & (rmean >= RHO_BIO)] = 2
    grid = grid.reshape(AZ_BINS, RNG_BINS).astype(np.float32)
    cls = cls.reshape(AZ_BINS, RNG_BINS)

    win = (r >= IDX_MIN_KM) & (r < IDX_MAX_KM)
    nwin = max(int(win.sum()), 1)
    idx = 10.0 * math.log10(max(float(zlin[win].mean()), 1e-9))
    cov = float((has & (dbz >= 5.0) & win).sum()) / nwin
    echo_win = echo & win & np.isfinite(rho)
    n_echo = max(int(echo_win.sum()), 1)
    wx = float((echo_win & (rho >= RHO_BIO)).sum()) / n_echo if echo_win.sum() > 0 else 0.0
    bio_gates = win & has & ((~np.isfinite(rho)) | (rho < RHO_BIO))
    bio_lin = np.where(bio_gates, zlin, 0.0)[win].mean()
    bio_idx = 10.0 * math.log10(max(float(bio_lin), 1e-9))
    return {
        "dbz": grid, "cls": cls,
        "idx": float(np.clip(idx, -10, 40)), "cov": cov, "wx": wx,
        "bio_idx": float(np.clip(bio_idx, -10, 40)),
        "el": float(sweep[0][0].el_angle),
        "time": f.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_gates": int(has.size),
    }


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    SCANS.mkdir(parents=True, exist_ok=True)
    bucket = pick_bucket()
    sel = build_selection(bucket)
    bucket = sel["bucket"]
    todo = [(st["id"], n["date"], s) for st in sel["stations"] for n in st["nights"] for s in n["scans"] if s["key"]]
    log(f"{len(todo)} scans selected")
    done = 0
    for st_id, night, s in todo:
        name = s["key"].split("/")[-1]
        out = SCANS / f"{name}.npz"
        if out.exists():
            done += 1
            continue
        tmp = RAW / name
        try:
            t0 = time.time()
            data = http_get(f"{bucket}/{s['key']}")
            with open(tmp, "wb") as fh:
                fh.write(data)
            size_mb = len(data) / 1e6
            red = reduce_scan(tmp)
            np.savez_compressed(out, dbz=red["dbz"], cls=red["cls"],
                                scalars=np.array([red["idx"], red["cov"], red["wx"], red["bio_idx"], red["el"]], dtype=np.float32),
                                time=np.array(red["time"]), n_gates=np.array(red["n_gates"]))
            done += 1
            log(f"{st_id} {night} {s['label']:8s} {name} {size_mb:5.1f} MB idx {red['idx']:5.1f} bio {red['bio_idx']:5.1f} wx {red['wx']:.2f} {time.time()-t0:4.1f}s [{done}/{len(todo)}]")
        except Exception as e:  # noqa: BLE001
            log(f"SKIP {st_id} {night} {s['label']} {name}: {e}")
        finally:
            if tmp.exists():
                tmp.unlink()
    log("fetch done")


if __name__ == "__main__":
    main()
