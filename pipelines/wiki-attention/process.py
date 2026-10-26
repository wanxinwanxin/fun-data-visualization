"""Build the attention graph for the room "Where Curiosity Goes".

Stdlib only. Run from the repository root:
  .venv/bin/python3 -I pipelines/wiki-attention/process.py [--top-only] [--preview-only]

Input: data/raw/wiki-attention/clickstream-enwiki-YYYY-MM.tsv.gz
Columns: prev, curr, type, n. The script keeps only rows of type "link".
A link row means that readers clicked a link in article prev and arrived
at article curr, n times in the month. Wikimedia only publishes pairs with
n >= 10.

The script streams the gz file four times and never loads it whole:
  Pass 1: total incoming link clicks per article. This gives the top 300
          articles and the top 50 overview list.
  Pass 2: outgoing link rows for the seeds. Keep the top 8 per seed (depth 1).
  Pass 3: outgoing link rows for every depth-1 node. Keep the top 8 (depth 2).
  Pass 4: outgoing link rows for the top 3 depth-2 nodes of each depth-1
          node. Keep the top 8 (depth 3).
Cap rule: every expanded node keeps at most 8 children, ranked by n.

Output: rooms/wiki-attention/data/graph.json and rooms/wiki-attention/preview.svg
"""
import gzip
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "wiki-attention"
OUT = ROOT / "rooms" / "wiki-attention" / "data"
PREVIEW = ROOT / "rooms" / "wiki-attention" / "preview.svg"

CAP = 8          # children per expanded node
DEPTH3_TOP = 3   # depth-2 nodes that get children, per depth-1 node
TOP_N = 300      # size of the top incoming list that seeds come from
OVERVIEW_N = 50  # size of the overview list in the output

# Curated seeds. Each seed is a big entry point in the month. The seeds come
# from the top 300 list by incoming link clicks (pass 1). The label groups
# the chips in the room. A seed that is missing from the month is dropped.
SEEDS = []  # filled after pass 1 the first time, see seeds.json next to this file

# Pages in these namespaces are navigation, not articles. The script skips
# them as prev and as curr.
SKIP_PREFIX = ("Main_Page", "Special:", "Wikipedia:", "Portal:", "Help:", "File:",
               "Category:", "Template:", "Talk:", "User:", "Draft:", "Module:",
               "Book:", "MediaWiki:", "TimedText:", "Wikipedia_talk:", "User_talk:")
SKIP_EXACT = {"Main_Page", "Hyphen-minus", "-", "Wiki"}


def raw_file():
    month = (RAW / "MONTH").read_text().strip()
    return RAW / f"clickstream-enwiki-{month}.tsv.gz", month


def keep(title):
    return title not in SKIP_EXACT and not title.startswith(SKIP_PREFIX)


def link_rows(path):
    """Yield (prev, curr, n) for every link row. Skip navigation pages."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4 or parts[2] != "link":
                continue
            prev, curr = parts[0], parts[1]
            if keep(prev) and keep(curr):
                yield prev, curr, int(parts[3])


def pass_incoming(path):
    """Sum incoming link clicks per article. Keys are 64-bit hashes of the
    title, to keep memory low. Titles are kept only for articles that have
    at least one incoming row with n >= 500, which every top article has."""
    totals = defaultdict(int)
    names = {}
    t0 = time.time()
    rows = 0
    for prev, curr, n in link_rows(path):
        h = hash(curr)
        totals[h] += n
        if n >= 500 and h not in names:
            names[h] = curr
        rows += 1
    print(f"pass 1: {rows} link rows, {len(totals)} articles, {time.time() - t0:.0f}s")
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    top = []
    for h, total in ranked:
        if h in names:
            top.append((names[h], total))
        if len(top) >= TOP_N:
            break
    return totals, top, rows


def pass_outgoing(path, watch):
    """Collect every outgoing link row for prev in watch. Return
    children[prev] = [(curr, n), ...] and out[prev] = total outgoing n."""
    children = defaultdict(list)
    out = defaultdict(int)
    t0 = time.time()
    for prev, curr, n in link_rows(path):
        if prev in watch:
            children[prev].append((curr, n))
            out[prev] += n
    for prev in children:
        children[prev].sort(key=lambda cn: -cn[1])
    print(f"pass for {len(watch)} articles: {sum(len(v) for v in children.values())} rows, {time.time() - t0:.0f}s")
    return children, out


def load_seeds():
    p = Path(__file__).with_name("seeds.json")
    if p.exists():
        return json.loads(p.read_text())
    return []


def main():
    if "--preview-only" in sys.argv:
        write_preview(json.loads((OUT / "graph.json").read_text()))
        return
    path, month = raw_file()
    OUT.mkdir(parents=True, exist_ok=True)
    totals, top, link_count = pass_incoming(path)
    (RAW / "top300.json").write_text(json.dumps(top, indent=0))
    print("top 10:", top[:10])
    if "--top-only" in sys.argv:
        return

    seeds = load_seeds()
    top_titles = {t for t, _ in top}
    seeds = [s for s in seeds if s["title"] in top_titles] if seeds else [
        {"title": t, "label": "top"} for t, _ in top[:20]]
    print("seeds:", [s["title"] for s in seeds])

    # Pass 2: depth 1
    c1, out1 = pass_outgoing(path, {s["title"] for s in seeds})
    seeds = [s for s in seeds if s["title"] in c1]
    edges = {}
    outs = {}
    level1 = set()
    for s in seeds:
        kids = c1[s["title"]][:CAP]
        edges[s["title"]] = kids
        outs[s["title"]] = out1[s["title"]]
        level1.update(t for t, _ in kids)
    level1 -= set(edges)

    # Pass 3: depth 2
    c2, out2 = pass_outgoing(path, level1)
    level2_expand = set()
    for t in level1:
        kids = c2.get(t, [])[:CAP]
        edges[t] = kids
        outs[t] = out2.get(t, 0)
        level2_expand.update(k for k, _ in kids[:DEPTH3_TOP])
    level2_expand -= set(edges)

    # Pass 4: depth 3
    c3, out3 = pass_outgoing(path, level2_expand)
    for t in level2_expand:
        kids = c3.get(t, [])[:CAP]
        edges[t] = kids
        outs[t] = out3.get(t, 0)

    # Index the nodes. Every node carries its total incoming link clicks.
    titles = []
    index = {}

    def node(t):
        if t not in index:
            index[t] = len(titles)
            titles.append(t)
        return index[t]

    for s in seeds:
        node(s["title"])
    for t in list(edges):
        node(t)
        for k, _ in edges[t]:
            node(k)
    nodes = [[t, totals.get(hash(t), 0)] for t in titles]
    edge_out = {str(index[t]): [[index[k], n] for k, n in kids] for t, kids in edges.items()}
    out_map = {str(index[t]): v for t, v in outs.items()}

    graph = {
        "month": month,
        "source": "https://dumps.wikimedia.org/other/clickstream/",
        "rule": {
            "type": "link",
            "cap": CAP,
            "depth3_top": DEPTH3_TOP,
            "skip": list(SKIP_PREFIX) + sorted(SKIP_EXACT),
            "link_rows_total": link_count,
            "note": "Each expanded node keeps its top 8 destinations by n. Seeds and "
                    "depth-1 nodes are expanded. At depth 2 only the top 3 children of "
                    "each depth-1 node are expanded. Pairs with n < 10 are absent from "
                    "the source.",
        },
        "seeds": [{"id": index[s["title"]], "label": s["label"]} for s in seeds],
        "nodes": nodes,
        "edges": edge_out,
        "out": out_map,
        "top50": top[:OVERVIEW_N],
    }
    p = OUT / "graph.json"
    p.write_text(json.dumps(graph, separators=(",", ":"), ensure_ascii=False))
    print("wrote", p, p.stat().st_size, "bytes,", len(nodes), "nodes,",
          sum(len(v) for v in edge_out.values()), "edges")
    write_preview(graph)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_preview(graph):
    """Draw the first seed and its children as a static 800x500 SVG, in the
    style of the room: ink outlines, mint ribbons, pastel blobs, confetti."""
    seed = graph["seeds"][0]["id"]
    kids = graph["edges"][str(seed)]
    nodes = graph["nodes"]
    max_in = max(n[1] for n in nodes)
    cx, cy, rx, ry = 400, 272, 196, 142
    maxn = kids[0][1]
    confetti = ["#FF8A8E", "#6FB3FF", "#C9A227", "#D7C8FF", "#FFD1A3"]
    font = "Fredoka, Nunito, Arial Rounded MT Bold, Arial, sans-serif"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500" font-family="{font}">',
        '<rect width="800" height="500" fill="#FFF3B8"/>',
    ]
    for y in range(20, 500, 44):
        for x in range(20 + (y // 44 % 2) * 22, 800, 44):
            parts.append(f'<circle cx="{x}" cy="{y}" r="2.2" fill="#fff" opacity="0.35"/>')
    geo = []
    for i, (k, n) in enumerate(kids):
        a = -math.pi / 2 + i * 2 * math.pi / len(kids)
        x, y = cx + rx * math.cos(a), cy + ry * math.sin(a)
        w = 6 + 26 * math.sqrt(n / maxn)
        qx, qy = (cx + x) / 2 - (y - cy) * 0.22, (cy + y) / 2 + (x - cx) * 0.22
        geo.append((k, n, a, x, y, w, qx, qy))
    for pass_ in (0, 1, 2):
        for k, n, a, x, y, w, qx, qy in geo:
            d = f'M{cx},{cy} Q{qx:.0f},{qy:.0f} {x:.0f},{y:.0f}'
            if pass_ == 0:
                parts.append(f'<path d="{d}" stroke="#2B2350" stroke-width="{w + 5:.1f}" fill="none" stroke-linecap="round"/>')
            elif pass_ == 1:
                parts.append(f'<path d="{d}" stroke="#7FD8BE" stroke-width="{w:.1f}" fill="none" stroke-linecap="round"/>')
            elif w >= 9:
                parts.append(f'<path d="{d}" stroke="#fff" stroke-width="{w * 0.22:.1f}" fill="none" stroke-linecap="round" opacity="0.45"/>')
    ci = 0
    for k, n, a, x, y, w, qx, qy in geo:
        count = 1 + int(4 * n / maxn)
        for j in range(count):
            t = 0.22 + 0.6 * (j + 0.5) / count
            u = 1 - t
            bx = u * u * cx + 2 * u * t * qx + t * t * x
            by = u * u * cy + 2 * u * t * qy + t * t * y
            rot = (ci * 53) % 180
            col = confetti[ci % len(confetti)]
            ci += 1
            parts.append(f'<rect x="{bx - 4:.0f}" y="{by - 2.5:.0f}" width="8" height="5" rx="2" fill="{col}" stroke="#2B2350" stroke-width="1.2" transform="rotate({rot} {bx:.0f} {by:.0f})"/>')
    for k, n, a, x, y, w, qx, qy in geo:
        r = 11 + 25 * math.sqrt(nodes[k][1] / max_in)
        parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="#6FB3FF" stroke="#2B2350" stroke-width="3.5"/>')
        parts.append(f'<ellipse cx="{x - r * 0.35:.0f}" cy="{y - r * 0.38:.0f}" rx="{r * 0.28:.1f}" ry="{r * 0.17:.1f}" transform="rotate(-34 {x - r * 0.35:.0f} {y - r * 0.38:.0f})" fill="#fff" opacity="0.55"/>')
        t = nodes[k][0].replace("_", " ")
        if len(t) > 19:
            t = t[:18] + "…"
        sub = f'{n / 1000:.0f}k clicks'
        c, sn = math.cos(a), math.sin(a)
        if c > 0.35:
            anchor, tx = "start", x + r + 10
        elif c < -0.35:
            anchor, tx = "end", x - r - 10
        else:
            anchor, tx = "middle", x
        if abs(c) > 0.35:
            ty = y + 2
        elif sn < 0:
            ty = y - r - 22
        else:
            ty = y + r + 24
        parts.append(f'<text x="{tx:.0f}" y="{ty:.0f}" text-anchor="{anchor}" font-size="16" font-weight="600" fill="#2B2350">{esc(t)}</text>')
        parts.append(f'<text x="{tx:.0f}" y="{ty + 16:.0f}" text-anchor="{anchor}" font-size="12" fill="#2B2350" opacity="0.8">{sub}</text>')
    rc = (11 + 25 * math.sqrt(nodes[seed][1] / max_in)) * 1.9
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{rc:.0f}" fill="#FF8A8E" stroke="#2B2350" stroke-width="5"/>')
    parts.append(f'<ellipse cx="{cx - rc * 0.35:.0f}" cy="{cy - rc * 0.38:.0f}" rx="{rc * 0.28:.1f}" ry="{rc * 0.17:.1f}" transform="rotate(-34 {cx - rc * 0.35:.0f} {cy - rc * 0.38:.0f})" fill="#fff" opacity="0.55"/>')
    st = nodes[seed][0].replace("_", " ")
    bw = min(300, 24 + 11 * len(st))
    parts.append(f'<rect x="{cx - bw / 2:.0f}" y="{cy - rc - 62:.0f}" width="{bw:.0f}" height="44" rx="18" fill="#FFFDF4" stroke="#2B2350" stroke-width="3.5"/>')
    parts.append(f'<path d="M{cx - 7},{cy - rc - 18} L{cx},{cy - rc - 2} L{cx + 7},{cy - rc - 18} Z" fill="#2B2350"/>')
    parts.append(f'<text x="{cx}" y="{cy - rc - 33:.0f}" text-anchor="middle" font-size="21" font-weight="700" fill="#2B2350">{esc(st[:26])}</text>')
    parts.append('<text x="22" y="38" font-size="27" font-weight="700" fill="#2B2350">Where Curiosity Goes</text>')
    parts.append(f'<text x="22" y="60" font-size="14" fill="#2B2350">Where Wikipedia readers clicked next, {graph["month"]}</text>')
    parts.append('<text x="778" y="486" text-anchor="end" font-size="12" fill="#2B2350" opacity="0.8">Ribbon width = clicks on the link · blob size = all arrivals</text>')
    parts.append('</svg>')
    PREVIEW.write_text("\n".join(parts))
    print("wrote", PREVIEW)


if __name__ == "__main__":
    main()
