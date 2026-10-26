"""Process the GCNS download into compact binary arrays for the room.

Input: data/raw/milky-way/gcns_*.csv and hip2_named.csv (from fetch.py).
Output: rooms/milky-way/data/ with
    pos.i16    Int16 x, y, z per star, galactic cartesian, 0.004 pc per unit
    vel.i8     Int8 vx, vy, vz per star, galactic cartesian, 1.5 km/s per unit
    color.u8   Uint8 BP-RP color code, 0..254 maps -1.0..5.0 mag, 255 = unknown
    mag.u8     Uint8 absolute G magnitude code, 0..255 maps -2.0..20.0 mag
    manifest.json  counts, scales, the color lookup table, the named stars
and rooms/milky-way/preview.svg, a still of the point cloud.

Rules:
  * The script keeps every GCNS row that has a G magnitude. Rows without a
    G magnitude cannot get a size on screen, so the script drops them.
  * Stars are sorted by distance from the Sun, nearest first. The room draws
    the first N stars to apply a radius filter.
  * The velocity is the full space velocity when the catalog has a radial
    velocity (about 25 percent of the stars). For the other stars the
    velocity is the tangential velocity from the proper motion only.
  * Velocity components beyond 190 km/s are clipped to 190 km/s.

Usage (from the repository root):
    .venv/bin/python3 -I pipelines/milky-way/process.py
"""
import glob
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "milky-way"
OUT = ROOT / "rooms" / "milky-way" / "data"
PREVIEW = ROOT / "rooms" / "milky-way" / "preview.svg"

POS_SCALE = 0.004      # pc per Int16 unit, so the range is about +-131 pc
VEL_SCALE = 1.5        # km/s per Int8 unit, so the range is about +-190 km/s
COLOR_MIN, COLOR_MAX = -1.0, 5.0   # BP-RP range of the Uint8 code
MAG_MIN, MAG_MAX = -2.0, 20.0      # absolute G range of the Uint8 code
K = 4.74047            # km/s per (mas/yr / mas), one AU per year in km/s

# Rotation from ICRS equatorial cartesian to galactic cartesian (Gaia DPAC).
A_G = np.array([
    [-0.0548755604162154, -0.8734370902348850, -0.4838350155487132],
    [0.4941094278755837, -0.4448296299600112, 0.7469822444972189],
    [-0.8676661490190047, -0.1980763734312015, 0.4559837761750669]])

# Common names of the Hipparcos stars that fetch.py downloads.
HIP_NAMES = {
    70890: "Proxima Centauri", 71683: "Alpha Centauri", 87937: "Barnard's Star",
    32349: "Sirius", 37279: "Procyon", 97649: "Altair", 91262: "Vega",
    54035: "Lalande 21185", 16537: "Epsilon Eridani", 8102: "Tau Ceti",
    104214: "61 Cygni", 24186: "Kapteyn's Star"}
HIP_EPOCH = 1991.25
GAIA_EPOCH = 2016.0

# Anchor points of the BP-RP to effective temperature relation for dwarf
# stars. The values follow the Mamajek "A Modern Mean Dwarf Stellar Color
# and Effective Temperature Sequence" table to about ten percent.
TEFF_ANCHORS = [(-0.4, 30000), (-0.3, 25000), (0.0, 10000), (0.3, 8000), (0.5, 7000),
                (0.75, 6000), (0.82, 5780), (1.0, 5300), (1.3, 4600), (1.6, 4100),
                (2.0, 3700), (2.5, 3400), (3.0, 3100), (3.5, 2900), (4.0, 2700),
                (4.5, 2500), (5.0, 2300)]


def bp_rp_to_teff(x):
    """Interpolate the effective temperature in log space between anchors."""
    xs = np.array([a[0] for a in TEFF_ANCHORS])
    ts = np.log10([a[1] for a in TEFF_ANCHORS])
    return 10 ** np.interp(x, xs, ts)


def cie_cmf(lam):
    """Analytic fit of the CIE 1931 color matching functions (Wyman 2013)."""
    def g(l, mu, s1, s2):
        s = np.where(l < mu, s1, s2)
        return np.exp(-0.5 * ((l - mu) / s) ** 2)
    x = 1.056 * g(lam, 599.8, 37.9, 31.0) + 0.362 * g(lam, 442.0, 16.0, 26.7) \
        - 0.065 * g(lam, 501.1, 20.4, 26.2)
    y = 0.821 * g(lam, 568.8, 46.9, 40.5) + 0.286 * g(lam, 530.9, 16.3, 31.1)
    z = 1.217 * g(lam, 437.0, 11.8, 36.0) + 0.681 * g(lam, 459.0, 26.0, 13.8)
    return x, y, z


def blackbody_rgb(teff):
    """Return the sRGB chromaticity (0..255) of a blackbody at teff kelvin."""
    lam = np.arange(380.0, 781.0, 2.0)
    h, c, kb = 6.62607e-34, 2.99792e8, 1.380649e-23
    l_m = lam * 1e-9
    planck = (2 * h * c ** 2 / l_m ** 5) / (np.exp(h * c / (l_m * kb * teff)) - 1)
    xb, yb, zb = cie_cmf(lam)
    X, Y, Z = (planck * xb).sum(), (planck * yb).sum(), (planck * zb).sum()
    s = X + Y + Z
    X, Y, Z = X / s, Y / s, Z / s
    m = np.array([[3.2406, -1.5372, -0.4986],
                  [-0.9689, 1.8758, 0.0415],
                  [0.0557, -0.2040, 1.0570]])
    rgb = m @ np.array([X, Y, Z])
    rgb = np.clip(rgb, 0, None)
    rgb = rgb / rgb.max()
    # Keep the colors a little closer to white than a pure blackbody, so the
    # faint red dwarfs stay visible on black. The hue stays the same.
    rgb = 0.85 * rgb + 0.15
    srgb = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)
    return [int(round(v * 255)) for v in srgb]


def color_lut():
    """256 sRGB triplets, one per BP-RP code. Code 255 is a neutral gray."""
    lut = []
    for code in range(255):
        x = COLOR_MIN + (COLOR_MAX - COLOR_MIN) * code / 254
        lut.append(blackbody_rgb(float(bp_rp_to_teff(x))))
    lut.append([200, 200, 205])
    return lut


def radec_to_galactic(ra_deg, de_deg):
    """Unit vectors in the galactic cartesian frame from ICRS angles."""
    ra, de = np.radians(ra_deg), np.radians(de_deg)
    rhat = np.stack([np.cos(de) * np.cos(ra), np.cos(de) * np.sin(ra), np.sin(de)], -1)
    return rhat @ A_G.T


def space_velocity(ra_deg, de_deg, plx, pm_ra, pm_de, rv):
    """Galactic cartesian velocity in km/s from parallax, motions and RV."""
    ra, de = np.radians(np.asarray(ra_deg, float)), np.radians(np.asarray(de_deg, float))
    plx, rv = np.asarray(plx, float), np.asarray(rv, float)
    va = K * np.asarray(pm_ra, float) / plx
    vd = K * np.asarray(pm_de, float) / plx
    rhat = np.stack([np.cos(de) * np.cos(ra), np.cos(de) * np.sin(ra), np.sin(de)], -1)
    ea = np.stack([-np.sin(ra), np.cos(ra), np.zeros_like(ra)], -1)
    ed = np.stack([-np.cos(ra) * np.sin(de), -np.sin(ra) * np.sin(de), np.cos(de)], -1)
    v_eq = rv[..., None] * rhat + va[..., None] * ea + vd[..., None] * ed
    return v_eq @ A_G.T


def load_gcns():
    files = sorted(glob.glob(str(RAW / "gcns_*.csv")))
    if not files:
        raise SystemExit("no raw files, run fetch.py first")
    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    return df


def named_stars(df, pos, order_index):
    """Match the Hipparcos stars to GCNS rows by position and parallax."""
    hip = pd.read_csv(RAW / "hip2_named.csv")
    out = [{"name": "Sun", "x": 0.0, "y": 0.0, "z": 0.0,
            "vx": 0.0, "vy": 0.0, "vz": 0.0, "source": "origin", "index": -1}]
    dt = GAIA_EPOCH - HIP_EPOCH
    gal_pos_by_id = {}
    for _, h in hip.iterrows():
        name = HIP_NAMES[int(h.HIP)]
        # Move the Hipparcos position to the Gaia epoch with its proper motion.
        ra = h.RArad + (h.pmRA / 3.6e6) / math.cos(math.radians(h.DErad)) * dt
        de = h.DErad + (h.pmDE / 3.6e6) * dt
        sep = np.hypot((df.RA_ICRS.values - ra) * math.cos(math.radians(de)),
                       df.DE_ICRS.values - de) * 3600
        cand = np.where((sep < 30) & (np.abs(df.Plx.values - h.Plx) < 20))[0]
        if len(cand):
            i = int(cand[np.argmin(sep[cand])])
            j = int(order_index[i])
            v = space_velocity(df.RA_ICRS.values[i], df.DE_ICRS.values[i], df.Plx.values[i],
                               df.pmRA.values[i], df.pmDE.values[i],
                               np.nan_to_num(df.RV.values[i]))
            entry = {"name": name, "x": float(pos[j, 0]), "y": float(pos[j, 1]),
                     "z": float(pos[j, 2]), "vx": float(v[0]), "vy": float(v[1]),
                     "vz": float(v[2]), "source": "gcns", "index": j,
                     "gaia": int(df.GaiaEDR3.values[i]),
                     "sep_arcsec": round(float(sep[i]), 1)}
            if int(h.HIP) == 32349:
                entry["note"] = "GCNS row is Sirius B. Sirius A is too bright for Gaia."
        else:
            d = 1000.0 / h.Plx
            u = radec_to_galactic(ra, de) * d
            v = space_velocity(ra, de, h.Plx, h.pmRA, h.pmDE, 0.0)
            entry = {"name": name, "x": float(u[0]), "y": float(u[1]), "z": float(u[2]),
                     "vx": float(v[0]), "vy": float(v[1]), "vz": float(v[2]),
                     "source": "hip2", "index": -1, "hip": int(h.HIP),
                     "note": "Not in the GCNS. Too bright for Gaia. Hipparcos position."}
        for k in ("x", "y", "z", "vx", "vy", "vz"):
            entry[k] = round(entry[k], 4)
        out.append(entry)
    return out


def write_preview(pos, color_code, absmag, lut, dist):
    """Write an 800x500 SVG: the room's view from a camera 45 pc from the Sun.

    The camera looks at the Sun. Size and opacity follow the apparent
    magnitude as seen from the camera, as in the room's shader. The file
    keeps the 2500 stars that look brightest from that camera.
    """
    w, h = 800, 500
    cam = np.array([26.0, -52.0, 24.0]) * 0.72
    fwd = -cam / np.linalg.norm(cam)
    right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    rel = pos - cam
    depth = rel @ fwd
    front = depth > 0.05
    f = (h / 2) / math.tan(math.radians(58) / 2)
    sx = w / 2 + f * (rel @ right) / np.where(front, depth, 1)
    sy = h / 2 - f * (rel @ up) / np.where(front, depth, 1)
    dcam = np.linalg.norm(rel, axis=1)
    m_app = absmag + 5 * np.log10(np.maximum(dcam, 0.01)) - 5
    ok = front & (sx > -10) & (sx < w + 10) & (sy > -10) & (sy < h + 10) & (dist < 120)
    idx = np.where(ok)[0]
    by_app = idx[np.argsort(m_app[idx])]
    rest = by_app[1200:]
    rng = np.random.default_rng(7)
    faint = rng.choice(rest, size=min(1800, len(rest)), replace=False)
    pick = np.concatenate([faint[np.argsort(-m_app[faint])], by_app[:1200][::-1]])
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
             '<defs><filter id="b" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2"/></filter></defs>',
             f'<rect width="{w}" height="{h}" fill="#000"/>']
    halos, cores = [], []
    for i in pick:
        m = m_app[i]
        r = min(5.0, max(0.3, 0.9 * 10 ** (-0.2 * (m - 8.0))))
        op = max(0.12, min(1.0, 10 ** (-0.4 * (m - 12.5))))
        c = lut[int(color_code[i])]
        col = f"rgb({c[0]},{c[1]},{c[2]})"
        if r > 1.4:
            halos.append(f'<circle cx="{sx[i]:.1f}" cy="{sy[i]:.1f}" r="{r*1.7:.1f}" fill="{col}" fill-opacity="0.55"/>')
            cores.append(f'<circle cx="{sx[i]:.1f}" cy="{sy[i]:.1f}" r="{r*0.5:.1f}" fill="{col}"/>')
        else:
            cores.append(f'<circle cx="{sx[i]:.1f}" cy="{sy[i]:.1f}" r="{r:.1f}" fill="{col}" fill-opacity="{op:.2f}"/>')
    parts.append('<g filter="url(#b)">' + "".join(halos) + '</g>')
    parts.extend(cores)
    # the Sun sits at the center of the view
    parts.append(f'<circle cx="{w/2:.0f}" cy="{h/2:.0f}" r="6" fill="none" stroke="#fff" stroke-opacity="0.35" stroke-width="0.8"/>')
    font = "Jost, Futura, 'Avenir Next', 'Helvetica Neue', Arial, sans-serif"
    parts.append(f'<rect x="20" y="20" width="330" height="74" fill="#000" fill-opacity="0.55"/>')
    parts.append(f'<g font-family="{font}" fill="#fff">')
    parts.append('<text x="34" y="46" font-size="12" letter-spacing="4" font-weight="300">A MILLION NEIGHBORS</text>')
    parts.append('<line x1="34" y1="56" x2="78" y2="56" stroke="#fff" stroke-opacity="0.3" stroke-width="1"/>')
    parts.append('<text x="34" y="76" font-size="10.5" fill-opacity="0.6" letter-spacing="0.5" font-weight="300">Gaia Catalogue of Nearby Stars, 45 parsecs from the Sun</text>')
    parts.append('</g></svg>')
    PREVIEW.write_text("\n".join(parts))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_gcns()
    n_raw = len(df)
    df = df[df.Gmag.notna()].reset_index(drop=True)
    n_kept = len(df)
    print(f"rows: {n_raw} raw, {n_kept} with a G magnitude")

    pos = df[["xcoord50", "ycoord50", "zcoord50"]].values.astype(np.float64)
    dist = np.sqrt((pos ** 2).sum(1))
    absmag = df.Gmag.values + 5 - 5 * np.log10(dist)
    bprp = (df.BPmag - df.RPmag).values
    rv = np.nan_to_num(df.RV.values, nan=0.0)
    vel = space_velocity(df.RA_ICRS.values, df.DE_ICRS.values, df.Plx.values,
                         df.pmRA.values, df.pmDE.values, rv)

    order = np.argsort(dist, kind="stable")
    order_index = np.empty_like(order)
    order_index[order] = np.arange(len(order))
    pos, dist, absmag, bprp, vel = pos[order], dist[order], absmag[order], bprp[order], vel[order]

    pos_i16 = np.clip(np.round(pos / POS_SCALE), -32767, 32767).astype("<i2")
    vel_i8 = np.clip(np.round(vel / VEL_SCALE), -127, 127).astype("i1")
    n_vclip = int((np.abs(vel) > 127 * VEL_SCALE).any(1).sum())
    code = np.round((bprp - COLOR_MIN) / (COLOR_MAX - COLOR_MIN) * 254)
    code = np.where(np.isnan(bprp), 255, np.clip(code, 0, 254)).astype(np.uint8)
    mag_u8 = np.clip(np.round((absmag - MAG_MIN) / (MAG_MAX - MAG_MIN) * 255), 0, 255).astype(np.uint8)

    (OUT / "pos.i16").write_bytes(pos_i16.tobytes())
    (OUT / "vel.i8").write_bytes(vel_i8.tobytes())
    (OUT / "color.u8").write_bytes(code.tobytes())
    (OUT / "mag.u8").write_bytes(mag_u8.tobytes())

    radii = np.arange(0, 131)
    counts = np.searchsorted(dist, radii, side="right").tolist()
    lut = color_lut()
    named = named_stars(df, pos, order_index)
    manifest = {
        "source": "Gaia Catalogue of Nearby Stars (Gaia Collaboration, Smart et al. 2021), VizieR J/A+A/649/A6/table1c",
        "fetched": date.today().isoformat(),
        "n_raw": n_raw, "n": n_kept,
        "n_no_color": int((code == 255).sum()),
        "n_with_rv": int(df.RV.notna().sum()),
        "n_velocity_clipped": n_vclip,
        "pos_scale_pc": POS_SCALE, "vel_scale_kms": VEL_SCALE,
        "color_min": COLOR_MIN, "color_max": COLOR_MAX,
        "mag_min": MAG_MIN, "mag_max": MAG_MAX,
        "counts_by_radius_pc": counts,
        "median_bprp": round(float(np.nanmedian(bprp)), 3),
        "median_absmag": round(float(np.median(absmag)), 3),
        "lut": lut,
        "named": named,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
    write_preview(pos, code, absmag, lut, dist)
    total = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"wrote {OUT} ({total/1e6:.2f} MB), velocity clipped on {n_vclip} stars, "
          f"{manifest['n_no_color']} stars without BP-RP")
    for s in named:
        print(f"  {s['name']:18s} {s['source']:6s} d={math.hypot(s['x'], s['y'], s['z']):6.2f} pc"
              + (f"  sep={s.get('sep_arcsec')}\"" if 'sep_arcsec' in s else ""))


if __name__ == "__main__":
    main()
