"""Process the raw citation rows into compact JSON for the room, and draw preview.svg.

Run from the repository root:
    .venv/bin/python3 -I pipelines/patent-drift/process.py

Input:  data/raw/patent-drift/citations.csv  (level, yr, src, dst, n)
        data/raw/patent-drift/cpc_titles.csv (symbol, titleFull)
Output: rooms/patent-drift/data/flows.json
        rooms/patent-drift/preview.svg

Grouping rule. The eight cited groups are fixed and never change order:
    A   Human necessities
    B   Operations and transport
    C   Chemistry and metallurgy
    DE  Textiles, paper and construction (CPC sections D and E, the two smallest)
    F   Mechanical engineering
    G   Physics and instruments (section G without G06)
    G06 Computing and software (CPC subclass G06)
    H   Electricity and electronics
The citing side uses the same groups. A citing entity is one group or one 4-character class.
Rows where the cited code is in CPC section Y (tagging codes such as Y02) are dropped.
They are 0.28 percent of all citations and never appear on the citing side.
"""
import csv
import json
import math
import collections
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "patent-drift"
OUT = ROOT / "rooms" / "patent-drift"
YEARS = list(range(1985, 2025))
TOP_CLASSES = 40          # citing classes that the parts list offers
TOP_PAIRS_GROUP = 16      # class pairs kept per year for a group entity
TOP_PAIRS_CLASS = 12      # cited classes kept per year for a class entity
GROUPS = [
    ("A", "Human necessities", "Medicine, agriculture, food, household"),
    ("B", "Operations, transport", "Shaping, printing, vehicles, packaging"),
    ("C", "Chemistry, metallurgy", "Organic chemistry, biotech, materials"),
    ("DE", "Textiles, construction", "CPC sections D and E together"),
    ("F", "Mechanical engineering", "Engines, pumps, lighting, heating, weapons"),
    ("G", "Physics, instruments", "Section G without computing: optics, measuring, signals"),
    ("G06", "Computing, software", "CPC subclass G06: digital data processing, AI, business methods"),
    ("H", "Electricity, electronics", "Circuits, semiconductors, communication"),
]
GIDX = {g[0]: i for i, g in enumerate(GROUPS)}


def group_of(code):
    """Map a CPC code (3 or 4 characters) to one of the eight groups."""
    if code[:3] == "G06":
        return "G06"
    if code[0] in "DE":
        return "DE"
    return code[0]


def short_title(t):
    """Make a short sentence-case title from a CPC title string."""
    t = t.split(";")[0].strip()
    t = t.split(" (")[0].strip()
    t = t[:1].upper() + t[1:].lower()
    for a, b in (("Fertilising", "Fertilizing"), ("Colouring", "Coloring"), ("Vapour", "Vapor")):
        t = t.replace(a, b)
    if len(t) > 46:
        cut = t[:46].rsplit(" ", 1)[0]
        t = cut.rstrip(",") + "..."
    return t


def load_titles():
    titles = {}
    with open(RAW / "cpc_titles.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            titles[row["symbol"]] = short_title(row["titleFull"])
    return titles


def main():
    titles = load_titles()
    nyears = len(YEARS)
    yi = {y: i for i, y in enumerate(YEARS)}
    # flow[entity][year index][group index] = citations
    flow = collections.defaultdict(lambda: [[0] * 8 for _ in YEARS])
    class_total = collections.Counter()
    # pairs[year index] = list of (citing class, cited class, n) from level C
    pairs = [[] for _ in YEARS]
    rows_x = rows_c = 0
    with open(RAW / "citations.csv", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)
        for level, yr, src, dst, n in reader:
            y = yi.get(int(yr))
            if y is None:
                continue
            if dst[0] == "Y" or src[0] == "Y":
                continue
            n = int(n)
            if level == "X":
                rows_x += 1
                gi = GIDX[group_of(dst)]
                flow["ALL"][y][gi] += n
                flow[group_of(src)][y][gi] += n
                flow[src][y][gi] += n
                class_total[src] += n
            else:
                rows_c += 1
                pairs[y].append((src, dst, n))

    top = [c for c, _ in class_total.most_common(TOP_CLASSES)]
    entities = [{"id": "ALL", "kind": "all", "label": "All US patent grants", "flow": flow["ALL"]}]
    for code, label, _ in GROUPS:
        entities.append({"id": code, "kind": "group", "label": label, "flow": flow[code]})
    for code in top:
        entities.append({
            "id": code, "kind": "class", "group": group_of(code),
            "label": titles.get(code, code), "flow": flow[code],
        })

    # Alluvial rows per entity per year, from the thresholded class pairs.
    # Pairs where the citing class and the cited class are the same are excluded.
    # Those self-citations are the largest pairs everywhere and say nothing about borrowing.
    pairs = [[p for p in rows if p[0] != p[1]] for rows in pairs]
    alluvial = {}
    used_classes = set()
    for ent in entities:
        rows = []
        for y in range(nyears):
            if ent["kind"] == "all":
                cand = pairs[y]
                k = TOP_PAIRS_GROUP
            elif ent["kind"] == "group":
                cand = [p for p in pairs[y] if group_of(p[0]) == ent["id"]]
                k = TOP_PAIRS_GROUP
            else:
                cand = [p for p in pairs[y] if p[0] == ent["id"]]
                k = TOP_PAIRS_CLASS
            best = sorted(cand, key=lambda p: -p[2])[:k]
            for s, d, _ in best:
                used_classes.add(s)
                used_classes.add(d)
            rows.append([[s, d, n] for s, d, n in best])
        alluvial[ent["id"]] = rows

    titles_out = {c: titles.get(c, c) for c in sorted(used_classes)}
    totals = [sum(flow["ALL"][y]) for y in range(nyears)]
    data = {
        "meta": {
            "source": "patents-public-data.patents.publications (Google Patents Public Data on BigQuery)",
            "generated": date.today().isoformat(),
            "citing": "US grants 1985-2024, kind A, B1, B2, primary CPC code",
            "rows_level_x": rows_x, "rows_level_c": rows_c,
            "citations_total": sum(totals), "citing_classes": len(class_total),
            "pair_threshold": 20,
        },
        "years": YEARS,
        "groups": [{"code": c, "label": l, "note": n} for c, l, n in GROUPS],
        "totals": totals,
        "entities": entities,
        "titles": titles_out,
        "alluvial": alluvial,
    }
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    out = OUT / "data" / "flows.json"
    with open(out, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print("wrote", out, out.stat().st_size // 1024, "KB")
    print("citations", sum(totals), "entities", len(entities), "titles", len(titles_out))
    write_preview(flow["ALL"], totals)


PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#259b25", "#9085e9", "#e66767"]


def write_preview(all_flow, totals):
    """Draw an 800x500 blueprint still: a silhouette streamgraph of cited group shares."""
    W, H = 800, 500
    x0, x1, y0, y1 = 70, 690, 70, 356
    nyears = len(YEARS)
    xs = [x0 + (x1 - x0) * i / (nyears - 1) for i in range(nyears)]
    shares = [[v / totals[y] for v in all_flow[y]] for y in range(nyears)]
    mid = (y0 + y1) / 2
    scale = (y1 - y0)
    paths = []
    for g in range(8):
        tops, bots = [], []
        for y in range(nyears):
            base = -0.5 + sum(shares[y][:g])
            tops.append(mid - base * scale)
            bots.append(mid - (base + shares[y][g]) * scale)
        d = "M" + " L".join(f"{xs[i]:.1f},{tops[i]:.1f}" for i in range(nyears))
        d += " L" + " L".join(f"{xs[i]:.1f},{bots[i]:.1f}" for i in reversed(range(nyears))) + " Z"
        paths.append(f'<path d="{d}" fill="{PALETTE[g]}" fill-opacity="0.55" stroke="#eaf6ff" stroke-width="1"/>')
    grid = []
    for gx in range(0, W, 25):
        grid.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{H}" stroke="#ffffff" stroke-opacity="{0.10 if gx % 100 == 0 else 0.04}"/>')
    for gy in range(0, H, 25):
        grid.append(f'<line x1="0" y1="{gy}" x2="{W}" y2="{gy}" stroke="#ffffff" stroke-opacity="{0.10 if gy % 100 == 0 else 0.04}"/>')
    ticks = []
    for y in (1985, 1995, 2005, 2015, 2024):
        x = xs[YEARS.index(y)]
        ticks.append(f'<line x1="{x:.1f}" y1="{y1 + 4}" x2="{x:.1f}" y2="{y1 + 12}" stroke="#eaf6ff"/>'
                     f'<text x="{x:.1f}" y="{y1 + 28}" fill="#eaf6ff" font-size="13" text-anchor="middle">{y}</text>')
    legend = []
    for g, (code, label, _) in enumerate(GROUPS):
        ly = 80 + g * 22
        legend.append(f'<rect x="732" y="{ly - 9}" width="12" height="12" fill="{PALETTE[g]}" fill-opacity="0.8" stroke="#eaf6ff" stroke-width="0.6"/>'
                      f'<text x="750" y="{ly + 1}" fill="#eaf6ff" font-size="9">{code}</text>')
    last = shares[-1]
    g06 = last[GIDX["G06"]] * 100
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="'Architects Daughter','Courier New',monospace">
<rect width="{W}" height="{H}" fill="#0e2f66"/>
{"".join(grid)}
<rect x="12" y="12" width="{W - 24}" height="{H - 24}" fill="none" stroke="#eaf6ff" stroke-width="1.5"/>
<rect x="18" y="18" width="{W - 36}" height="{H - 36}" fill="none" stroke="#eaf6ff" stroke-width="0.6"/>
<text x="{x0}" y="48" fill="#eaf6ff" font-size="22" letter-spacing="2">WHERE IDEAS COME FROM</text>
<text x="{x1}" y="48" fill="#bfe3ff" font-size="11" text-anchor="end">CITED CPC GROUP SHARE, US GRANTS 1985-2024</text>
{"".join(paths)}
<line x1="{x0}" y1="{y1 + 8}" x2="{x1}" y2="{y1 + 8}" stroke="#eaf6ff" stroke-width="0.8"/>
{"".join(ticks)}
<line x1="{x0}" y1="{y1 + 44}" x2="{x1}" y2="{y1 + 44}" stroke="#bfe3ff" stroke-width="0.7" stroke-dasharray="6 4"/>
<text x="{(x0 + x1) / 2}" y="{y1 + 40}" fill="#bfe3ff" font-size="11" text-anchor="middle">40 YEARS, {sum(totals) / 1e6:.0f} M CITATIONS</text>
<line x1="{x1 + 8}" y1="{y0}" x2="{x1 + 8}" y2="{y1}" stroke="#bfe3ff" stroke-width="0.7" stroke-dasharray="6 4"/>
<text x="{x1 + 12}" y="{mid}" fill="#bfe3ff" font-size="9" transform="rotate(90 {x1 + 12},{mid})" text-anchor="middle">100 % OF CITATIONS</text>
{"".join(legend)}
<g transform="translate(560,414)">
<rect x="0" y="0" width="220" height="62" fill="#0e2f66" stroke="#eaf6ff" stroke-width="1"/>
<line x1="0" y1="20" x2="220" y2="20" stroke="#eaf6ff" stroke-width="0.6"/>
<line x1="0" y1="40" x2="220" y2="40" stroke="#eaf6ff" stroke-width="0.6"/>
<line x1="110" y1="20" x2="110" y2="62" stroke="#eaf6ff" stroke-width="0.6"/>
<text x="6" y="14" fill="#eaf6ff" font-size="10">DWG  PATENT CITATION DRIFT</text>
<text x="6" y="34" fill="#bfe3ff" font-size="9">SHEET 1 OF 1</text>
<text x="116" y="34" fill="#bfe3ff" font-size="9">SCALE  SHARE</text>
<text x="6" y="54" fill="#bfe3ff" font-size="9">G06 IN {YEARS[-1]}: {g06:.0f} %</text>
<text x="116" y="54" fill="#bfe3ff" font-size="9">REV  {YEARS[-1]}</text>
</g>
</svg>
'''
    (OUT / "preview.svg").write_text(svg)
    print("wrote", OUT / "preview.svg")


if __name__ == "__main__":
    main()
