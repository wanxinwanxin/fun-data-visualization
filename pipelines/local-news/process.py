"""Turn the cached facet files into the small JSON that the room loads.

Input: data/raw/local-news/<decade>_<term>.json and <decade>_TOTAL.json
from fetch.py, plus states-10m.json from us-atlas.

Output:
  rooms/local-news/data/topics.json   shares per topic, decade and state
  rooms/local-news/data/states.json   the us-atlas TopoJSON, territories removed
  rooms/local-news/preview.svg        a halftone grid of the national shares

Share = pages whose OCR text contains the keyword / all pages, for one
state and one decade. A cell with fewer than MIN_PAGES pages is null.
Lift = share / the national share of the same topic across all decades.
The headline mode in the room uses lift, so that a small state with a
local worry can beat the words that every paper prints.

Run from the repository root:
    .venv/bin/python3 -I pipelines/local-news/process.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "local-news"
OUT = ROOT / "rooms" / "local-news" / "data"
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import TOPICS, DECADES  # noqa: E402

MIN_PAGES = 300
TERRITORIES = {"American Samoa", "Guam", "Commonwealth of the Northern Mariana Islands",
               "Puerto Rico", "United States Virgin Islands"}
# The facet titles that do not match a us-atlas state name.
RENAME = {"Virgin Islands": "United States Virgin Islands",
          "Virgin Islands of the United States": "United States Virgin Islands",
          "Northern Mariana Islands": "Commonwealth of the Northern Mariana Islands"}


def load(decade, term):
    p = RAW / f"{decade}_{term or 'TOTAL'}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return {RENAME.get(k, k): v for k, v in d["states"].items()}, d.get("hits")


def main():
    atlas = json.loads((RAW / "states-10m.json").read_text())
    atlas_names = [g["properties"]["name"] for g in atlas["objects"]["states"]["geometries"]]
    totals = {}
    total_hits = {}
    for d in DECADES:
        r = load(d, None)
        if r is None:
            raise SystemExit(f"missing total for {d}s, run fetch.py first")
        totals[d], total_hits[d] = r

    # States: every facet title that is a us-atlas state (DC included) and
    # not a territory. The order is alphabetical and fixed.
    seen = set()
    for d in DECADES:
        seen.update(totals[d].keys())
    unknown = sorted(s for s in seen if s not in atlas_names)
    if unknown:
        print("facet titles not on the map (kept out):", unknown)
    states = sorted(s for s in seen if s in atlas_names and s not in TERRITORIES)
    si = {s: i for i, s in enumerate(states)}

    topic_ids = [t for t, _ in TOPICS]
    terms = {t: term for t, term in TOPICS}
    missing = []
    # share[t][d][s] with 4 decimals, or None when the cell is too small.
    share = {}
    counts = {}
    national = {}
    alltime = {}
    for t in topic_ids:
        share[t] = []
        counts[t] = []
        national[t] = []
        num_all = 0
        den_all = 0
        for d in DECADES:
            r = load(d, terms[t])
            if r is None:
                missing.append((d, t))
                share[t].append([None] * len(states))
                counts[t].append([0] * len(states))
                national[t].append(None)
                continue
            hits, nat_hits = r
            row = []
            crow = []
            for s in states:
                tot = totals[d].get(s, 0)
                n = hits.get(s, 0)
                crow.append(n)
                row.append(round(min(1.0, n / tot), 4) if tot >= MIN_PAGES else None)
            share[t].append(row)
            counts[t].append(crow)
            den = total_hits[d] or 0
            national[t].append(round(min(1.0, (nat_hits or 0) / den), 4) if den else None)
            num_all += nat_hits or 0
            den_all += den
        alltime[t] = (num_all / den_all) if den_all else 0.0
    if missing:
        print(f"warning: {len(missing)} topic files missing, cells are null:", missing[:10])

    # Top 3 by share and top 3 by lift, for each decade and state.
    top_share = []
    top_lift = []
    for di, d in enumerate(DECADES):
        ts_row = []
        tl_row = []
        for s in states:
            i = si[s]
            vals = []
            for ti, t in enumerate(topic_ids):
                v = share[t][di][i]
                if v is None:
                    continue
                lift = v / alltime[t] if alltime[t] > 0 else 0.0
                vals.append((ti, v, lift))
            if not vals:
                ts_row.append([])
                tl_row.append([])
                continue
            ts_row.append([ti for ti, v, l in sorted(vals, key=lambda x: -x[1])[:3]])
            tl_row.append([ti for ti, v, l in sorted(vals, key=lambda x: -x[2])[:3]])
        top_share.append(ts_row)
        top_lift.append(tl_row)

    page_totals = [[totals[d].get(s, 0) for s in states] for d in DECADES]
    out = {
        "source": "Library of Congress, Chronicling America, loc.gov JSON API location_state facet",
        "note": "share = pages with the keyword / all pages, per state and decade. "
                "null = fewer than %d pages. lift = share / all-time national share." % MIN_PAGES,
        "min_pages": MIN_PAGES,
        "decades": DECADES,
        "topics": [{"id": t, "term": terms[t], "alltime": round(alltime[t], 5)} for t in topic_ids],
        "states": states,
        "pages": page_totals,
        "pages_national": [total_hits[d] for d in DECADES],
        "share": share,
        "national": national,
        "top_share": top_share,
        "top_lift": top_lift,
    }
    (OUT / "topics.json").write_text(json.dumps(out, separators=(",", ":")))

    # The map: keep the us-atlas topology, drop the five territories.
    geoms = [g for g in atlas["objects"]["states"]["geometries"]
             if g["properties"]["name"] not in TERRITORIES]
    atlas["objects"]["states"]["geometries"] = geoms
    (OUT / "states.json").write_text(json.dumps(atlas, separators=(",", ":")))

    write_preview(out)
    n_cells = sum(1 for t in topic_ids for row in share[t] for v in row if v is not None)
    print(f"states={len(states)} topics={len(topic_ids)} decades={len(DECADES)} cells={n_cells}")
    for f in ("topics.json", "states.json"):
        print(f"  {f}: {(OUT / f).stat().st_size / 1024:.0f} KB")


def write_preview(out):
    """A halftone grid: rows are topics, columns are decades, dot = share."""
    W, H = 800, 500
    topics = out["topics"]
    decades = out["decades"]
    x0, y0 = 150, 118
    cw = (W - x0 - 30) / len(decades)
    rh = (H - y0 - 40) / len(topics)
    r_max = min(cw, rh) * 0.5
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             '<rect width="100%" height="100%" fill="#f1ecdf"/>',
             '<defs><pattern id="g" width="6" height="6" patternUnits="userSpaceOnUse">'
             '<circle cx="3" cy="3" r="0.7" fill="#1a1a1a" opacity="0.25"/></pattern></defs>',
             f'<rect width="{W}" height="{H}" fill="url(#g)"/>',
             '<rect x="30" y="18" width="740" height="3" fill="#1a1a1a"/>',
             '<text x="400" y="62" text-anchor="middle" font-family="Anton,Impact,\'Arial Narrow\',sans-serif" '
             'font-size="44" fill="#1a1a1a" textLength="700" lengthAdjust="spacingAndGlyphs">WHAT THE COUNTY WORRIED ABOUT</text>',
             '<rect x="30" y="74" width="740" height="1" fill="#1a1a1a"/>',
             '<text x="30" y="94" font-family="\'Special Elite\',\'Courier New\',monospace" font-size="12" fill="#1a1a1a">'
             'CHRONICLING AMERICA  *  SHARE OF NEWSPAPER PAGES THAT PRINT THE WORD  *  1800-1963</text>',
             '<text x="770" y="94" text-anchor="end" font-family="\'Special Elite\',\'Courier New\',monospace" font-size="12" fill="#b8151b">'
             'PRICE TWO CENTS</text>']
    for j, d in enumerate(decades):
        cx = x0 + (j + 0.5) * cw
        label = f"{d}s" if j % 5 == 0 else f"'{str(d)[2:]}s"
        parts.append(f'<text x="{cx:.1f}" y="{y0 - 8}" text-anchor="middle" font-family="\'Courier New\',monospace" '
                     f'font-size="{10 if j % 5 else 9}" fill="#1a1a1a">{label}</text>')
    for i, t in enumerate(topics):
        cy = y0 + (i + 0.5) * rh
        parts.append(f'<text x="{x0 - 12}" y="{cy + 4:.1f}" text-anchor="end" font-family="Anton,Impact,\'Arial Narrow\',sans-serif" '
                     f'font-size="13" fill="#1a1a1a">{t["id"].upper()}</text>')
        row = out["national"][t["id"]]
        vmax = max((v for v in row if v is not None), default=0) or 1
        for j, v in enumerate(row):
            if v is None:
                continue
            cx = x0 + (j + 0.5) * cw
            r = r_max * math.sqrt(v / vmax)
            fill = "#b8151b" if v == vmax else "#1a1a1a"
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.2f}" fill="{fill}"/>')
    parts.append(f'<rect x="30" y="{H - 24}" width="740" height="1" fill="#1a1a1a"/>')
    parts.append(f'<text x="30" y="{H - 9}" font-family="\'Courier New\',monospace" font-size="10" fill="#1a1a1a">'
                 'Each row is scaled to its own peak decade. The red dot is the peak.</text>')
    parts.append('</svg>')
    (ROOT / "rooms" / "local-news" / "preview.svg").write_text("\n".join(parts))


if __name__ == "__main__":
    main()
