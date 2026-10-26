"""Process the raw builder data into compact files for the Builder Market room.

Input (data/raw/builder-market/): daily_builders.csv, daily_stats.csv,
weekly_stats.csv, ticker.csv, tags.csv (all from fetch.py).

Output (rooms/builder-market/data/):
  series.json   fixed builder list, weekly share matrix, daily HHI and shares,
                weekly and daily block counts and median base fee
  ticker.json   metadata for the ticker (first block, count, field layout)
  ticker.bin    one record per block for the latest 7 days:
                Uint8 builder index, Uint8 slot gap, Uint16 tx count,
                Float32 base fee in gwei (little endian, 8 bytes per block)
  mapping.md    the raw tag to builder label table for the README

The script also writes rooms/builder-market/preview.svg from the weekly data.

Run from the repository root:
  .venv/bin/python3 -I pipelines/builder-market/process.py
"""
import csv
import json
import struct
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "builder-market"
OUT = ROOT / "rooms" / "builder-market" / "data"
OUT.mkdir(parents=True, exist_ok=True)

TOP_N = 15
MERGE_DAY = date(2022, 9, 15)  # a Thursday, weeks start on this weekday
EVENTS = [
    {"date": "2022-09-15", "name": "Merge"},
    {"date": "2023-04-12", "name": "Shapella"},
    {"date": "2024-03-13", "name": "Dencun"},
    {"date": "2025-05-07", "name": "Pectra"},
]


def week_of(d):
    return d - timedelta(days=(d - MERGE_DAY).days % 7)


def main():
    # Daily counts per fine label.
    daily = defaultdict(Counter)
    total = Counter()
    for r in csv.DictReader(open(RAW / "daily_builders.csv", encoding="utf-8")):
        d = date.fromisoformat(r["day"])
        n = int(r["n"])
        daily[d][r["label"]] += n
        total[r["label"]] += n
    days = sorted(daily)
    print(f"{len(days)} days, {sum(total.values())} blocks, {len(total)} fine labels")

    # Fixed builder order: the top 15 labels by total blocks, then "other".
    builders = [k for k, _ in total.most_common(TOP_N)] + ["other"]
    idx = {b: i for i, b in enumerate(builders)}

    def fold(counter):
        row = [0] * len(builders)
        for k, v in counter.items():
            row[idx.get(k, len(builders) - 1)] += v
        return row

    # Daily HHI over fine labels (0 to 10000), daily share per column.
    day_hhi, day_share, day_blocks = [], [], []
    for d in days:
        c = daily[d]
        n = sum(c.values())
        day_hhi.append(round(sum((v / n) ** 2 for v in c.values()) * 10000))
        row = fold(c)
        day_share.append([round(v / n, 4) for v in row])
        day_blocks.append(n)

    # Weekly share per column.
    weekly = defaultdict(Counter)
    for d in days:
        weekly[week_of(d)].update(daily[d])
    weeks = sorted(weekly)
    week_share, week_blocks, week_hhi = [], [], []
    for w in weeks:
        c = weekly[w]
        n = sum(c.values())
        row = fold(c)
        week_share.append([round(v / n, 4) for v in row])
        week_blocks.append(n)
        week_hhi.append(round(sum((v / n) ** 2 for v in c.values()) * 10000))

    # Median base fee per day and per week.
    day_fee = {}
    for r in csv.DictReader(open(RAW / "daily_stats.csv")):
        day_fee[date.fromisoformat(r["day"])] = round(float(r["median_base_fee_gwei"]), 3)
    week_fee = {}
    for r in csv.DictReader(open(RAW / "weekly_stats.csv")):
        week_fee[date.fromisoformat(r["week"])] = round(float(r["median_base_fee_gwei"]), 3)

    series = {
        "builders": builders,
        "totals": [total[b] if b != "other" else sum(v for k, v in total.items() if k not in idx) for b in builders],
        "events": EVENTS,
        "weeks": [w.isoformat() for w in weeks],
        "week_share": week_share,
        "week_blocks": week_blocks,
        "week_hhi": week_hhi,
        "week_fee": [week_fee.get(w) for w in weeks],
        "days": [d.isoformat() for d in days],
        "day_hhi": day_hhi,
        "day_share": day_share,
        "day_blocks": day_blocks,
        "day_fee": [day_fee.get(d) for d in days],
    }
    (OUT / "series.json").write_text(json.dumps(series, separators=(",", ":")))

    # Ticker: one 8 byte record per block for the latest 7 days.
    rows = list(csv.DictReader(open(RAW / "ticker.csv", encoding="utf-8")))
    buf = bytearray()
    prev_ts = None
    first = rows[0]
    for r in rows:
        ts = int(r["ts"])
        gap = 1 if prev_ts is None else max(1, min(255, round((ts - prev_ts) / 12)))
        prev_ts = ts
        b = idx.get(r["label"], len(builders) - 1)
        tx = min(65535, int(r["tx"]))
        buf += struct.pack("<BBHf", b, gap, tx, float(r["base_fee_gwei"]))
    (OUT / "ticker.bin").write_bytes(bytes(buf))
    meta = {
        "first_number": int(first["number"]),
        "first_ts": int(first["ts"]),
        "last_number": int(rows[-1]["number"]),
        "last_ts": int(rows[-1]["ts"]),
        "count": len(rows),
        "record_bytes": 8,
        "layout": "Uint8 builder index, Uint8 slot gap (12 s slots since previous block), Uint16 tx count, Float32 base fee gwei, little endian",
        "builders": builders,
    }
    (OUT / "ticker.json").write_text(json.dumps(meta, indent=1))
    print(f"ticker: {len(rows)} blocks, {len(buf)/1e3:.0f} kB")

    # Mapping table for the README.
    lines = ["| Raw extra_data tag | Blocks | Fee recipients | Label | Column |", "|---|---:|---:|---|---|"]
    for r in list(csv.DictReader(open(RAW / "tags.csv", encoding="utf-8")))[:40]:
        tag = r["tag"].replace("|", "\\|").replace("`", "'")
        label = r["label"]
        col = label if label in idx else "other"
        lines.append(f"| `{tag or '(empty)'}` | {int(r['n']):,} | {r['fee_recipients']} | {label if len(label) < 30 else '(raw tag)'} | {col} |")
    (OUT / "mapping.md").write_text("\n".join(lines) + "\n")

    write_preview(series)
    size = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"processed data: {size/1e6:.2f} MB")


# Neon palette, fixed order for the first six builders, gray for the rest.
PALETTE = ["#00e5ff", "#ff3df0", "#b5ff3a", "#ff9a1f", "#8f7bff", "#ffe600"]


def write_preview(series):
    W, H = 800, 500
    weeks = series["weeks"]
    share = series["week_share"]
    builders = series["builders"]
    nb = len(builders)
    short = {"Titan": "Titan", "beaverbuild": "beaver", "vanilla": "vanilla", "BuilderNet": "BldrNet", "rsync": "rsync",
             "Flashbots": "Flashbt", "Quasar": "Quasar", "builder0x69": "0x69", "bloXroute": "bloXr", "Eureka": "Eureka",
             "Blocknative": "Blockn", "Builder+ (BTCS)": "BTCS", "eth-builder": "eth-b", "f1b.io": "f1b", "jetbldr": "jetbldr", "other": "other"}
    # One ridge per 4 weeks. The oldest week is at the top, like the room.
    step = 4
    sel = list(range(0, len(weeks), step))
    if sel[-1] != len(weeks) - 1:
        sel.append(len(weeks) - 1)
    left, right, top, bottom = 110, 780, 150, 450
    amp = 100
    gap = (bottom - top) / max(1, len(sel) - 1)
    mono = "ui-monospace,Menlo,Consolas,monospace"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             '<defs><filter id="g" x="-10%" y="-50%" width="120%" height="200%">'
             '<feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>',
             f'<rect width="{W}" height="{H}" fill="#000"/>']
    colw = (right - left) / (nb - 1)
    for k, wi in enumerate(sel):
        y0 = top + k * gap
        row = share[wi]
        pts = [(left + j * colw, y0 - v * amp) for j, v in enumerate(row)]
        d = f"M{left},{y0} "
        for j in range(len(pts) - 1):
            x0, y0p = pts[j]
            x1, y1 = pts[j + 1]
            cx = (x0 + x1) / 2
            d += f"C{cx},{y0p:.1f} {cx},{y1:.1f} {x1},{y1:.1f} "
        d += f"L{right},{y0} Z"
        last = (k == len(sel) - 1)
        age = 1 - k / max(1, len(sel) - 1)
        alpha = 1.0 if last else round(0.3 + 0.5 * (1 - age), 2)
        parts.append(f'<path d="{d}" fill="#000" stroke="{"#8ff6ff" if last else "#00e5ff"}" stroke-width="{1.8 if last else 1}" opacity="{alpha}"{" filter=\"url(#g)\"" if last else ""}/>')
        if k % 8 == 0 or last:
            parts.append(f'<text x="{left - 12}" y="{y0 + 4}" fill="{"#00e5ff" if last else "#5f8a90"}" font-family="{mono}" font-size="11" text-anchor="end">{"&gt; " if last else ""}{weeks[wi]}</text>')
    # dashed event lines
    for ev in series["events"]:
        k = max((i for i, wi in enumerate(sel) if weeks[wi] <= ev["date"]), default=0)
        y = top + k * gap
        parts.append(f'<line x1="{left - 6}" y1="{y:.1f}" x2="{right + 6}" y2="{y:.1f}" stroke="#ff3df0" stroke-opacity="0.7" stroke-dasharray="3 4"/>')
    for j, b in enumerate(builders):
        if j % 2 == 0 or j == nb - 1:
            parts.append(f'<text x="{left + j * colw:.1f}" y="{H - 14}" fill="#9fc4c8" font-family="{mono}" font-size="10" text-anchor="middle">{short[b]}</text>')
    parts.append(f'<text x="16" y="34" fill="#00e5ff" font-family="{mono}" font-size="20" font-weight="700">&gt; builder-market --since merge</text>')
    parts.append('<rect x="384" y="18" width="10" height="20" fill="#00e5ff"/>')
    parts.append(f'<text x="16" y="60" fill="#5f8a90" font-family="{mono}" font-size="12">one ridge per 4 weeks, oldest at the top, height = share of blocks per builder</text>')
    parts.append(f'<text x="16" y="78" fill="#ff3df0" font-family="{mono}" font-size="12">dashed lines: Merge, Shapella, Dencun, Pectra</text>')
    parts.append("</svg>")
    (ROOT / "rooms" / "builder-market" / "preview.svg").write_text("\n".join(parts))


if __name__ == "__main__":
    main()
