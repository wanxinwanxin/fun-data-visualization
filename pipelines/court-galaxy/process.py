"""Build the Citation Galaxy data from the raw CAP volume files.

Steps:
  1. Read every volume file in data/raw/court-galaxy/us/. Keep the cases that
     the Supreme Court of the United States decided. Collect the citation
     edges that point to other Supreme Court cases.
  2. Clean the edges. Drop self citations, edges to unknown cases, and edges
     that point forward in time.
  3. Count the in-degree of each case on the full network.
  4. Trim the network to a drawable size. Keep every case with in-degree 10 or
     more. Add a seeded random sample of the other connected cases up to
     TARGET_NODES. Keep the edges between kept cases. When there are more than
     MAX_EDGES, keep a seeded random sample.
  5. Find communities with the Louvain method. The largest communities are the
     constellations. Each constellation gets the name of its brightest star.
     When the SCDB files are present, each constellation also gets the most
     common SCDB issue area of its members.
  6. Compute a force layout with d3-force in Node (layout.cjs). The radius
     of a star follows the decision year.
     Old cases sit near the center and new cases sit near the rim. The angle
     follows the community. Repulsion, link springs, and a radial spring
     shape the result.
  7. Write nodes.json, edges.u16, meta.json, and preview.svg.

Run from the repository root:
  .venv/bin/python3 -I pipelines/court-galaxy/process.py
"""
import csv
import io
import json
import math
import random
import subprocess
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "court-galaxy"
VOLS = RAW / "us"
OUT = ROOT / "rooms" / "court-galaxy" / "data"
ROOM = ROOT / "rooms" / "court-galaxy"

SCOTUS = "Supreme Court of the United States"
MIN_INDEG = 10
TARGET_NODES = 12000
MAX_EDGES = 40000
MAX_CONSTELLATIONS = 12
MIN_CONSTELLATION = 150
STARS_PER_CONSTELLATION = 12
CONSTELLATION_REACH = 0.22
SEED = 13
TICKS = 300

ISSUE_AREAS = {
    1: "Criminal Procedure", 2: "Civil Rights", 3: "First Amendment",
    4: "Due Process", 5: "Privacy", 6: "Attorneys", 7: "Unions",
    8: "Economic Activity", 9: "Judicial Power", 10: "Federalism",
    11: "Interstate Relations", 12: "Federal Taxation", 13: "Miscellaneous",
    14: "Private Action",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_cases():
    """Read the volume files. Return the case table and the raw edge list."""
    cases = {}
    raw_edges = []
    files = sorted(VOLS.glob("*.json"), key=lambda p: int(p.stem))
    total = 0
    for p in files:
        for c in json.loads(p.read_text()):
            total += 1
            if c["court"]["name"] != SCOTUS:
                continue
            try:
                year = int(c["decision_date"][:4])
            except (ValueError, TypeError):
                continue
            cite = next((x["cite"] for x in c["citations"] if x["type"] == "official"), "")
            scdb = next((x["cite"][5:].strip() for x in c["citations"]
                         if x["type"] == "vendor" and x["cite"].startswith("SCDB ")), None)
            name = (c.get("name_abbreviation") or c.get("name") or "").strip()
            cases[c["id"]] = {"name": name, "year": year, "cite": cite, "scdb": scdb}
            # Keep every cited case id. The reporter can be "U.S." or one of the
            # old nominative reporters (Dall., Cranch, Wheat., Pet., How., Black,
            # Wall.). The cited case must be a Supreme Court case: clean_edges
            # drops the rest.
            for ct in c.get("cites_to", []):
                for cid in ct.get("case_ids", []):
                    raw_edges.append((c["id"], cid))
    log(f"{len(files)} volumes, {total} cases in the archive, {len(cases)} Supreme Court cases, "
        f"{len(raw_edges)} raw citations")
    return cases, raw_edges


def load_scdb():
    """Return a map from SCDB case id to issue area. Empty when no file is present."""
    issue = {}
    for z in sorted(RAW.glob("SCDB_*caseCentered_Citation.csv.zip")):
        with zipfile.ZipFile(z) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                text = zf.read(name).decode("cp1252", "replace")
                for row in csv.DictReader(io.StringIO(text)):
                    try:
                        issue[row["caseId"]] = int(row["issueArea"])
                    except (ValueError, KeyError):
                        pass
    log(f"SCDB issue areas: {len(issue)} cases")
    return issue


def clean_edges(cases, raw_edges):
    edges = set()
    dropped = Counter()
    for s, t in raw_edges:
        if s == t:
            dropped["self"] += 1
            continue
        if s not in cases or t not in cases:
            dropped["unknown"] += 1
            continue
        if cases[t]["year"] > cases[s]["year"]:
            dropped["forward"] += 1
            continue
        edges.add((s, t))
    log(f"{len(edges)} clean edges, dropped {dict(dropped)}")
    return edges


def trim(cases, edges):
    rng = random.Random(SEED)
    indeg = Counter(t for _, t in edges)
    connected = set()
    for s, t in edges:
        connected.add(s)
        connected.add(t)
    bright = sorted(c for c in connected if indeg[c] >= MIN_INDEG)
    dim = sorted(c for c in connected if indeg[c] < MIN_INDEG)
    sample_n = max(0, min(len(dim), TARGET_NODES - len(bright)))
    sample = rng.sample(dim, sample_n)
    keep = set(bright) | set(sample)
    kept_edges = sorted(e for e in edges if e[0] in keep and e[1] in keep)
    edge_sampled = False
    if len(kept_edges) > MAX_EDGES:
        kept_edges = sorted(rng.sample(kept_edges, MAX_EDGES))
        edge_sampled = True
    stats = {
        "cases_connected": len(connected),
        "cases_isolated": len(cases) - len(connected),
        "bright_kept": len(bright),
        "dim_total": len(dim),
        "dim_sampled": sample_n,
        "edges_between_kept": sum(1 for e in edges if e[0] in keep and e[1] in keep),
        "edges_kept": len(kept_edges),
        "edges_sampled": edge_sampled,
    }
    log(f"trim: {stats}")
    return keep, kept_edges, indeg, stats


def communities(ids, edges):
    g = nx.Graph()
    g.add_nodes_from(ids)
    g.add_edges_from(edges)
    comms = nx.community.louvain_communities(g, seed=SEED, resolution=1.0)
    comms = sorted(comms, key=len, reverse=True)
    label = {}
    for i, c in enumerate(comms):
        for n in c:
            label[n] = i if i < MAX_CONSTELLATIONS and len(c) >= MIN_CONSTELLATION else -1
    log(f"{len(comms)} communities, largest {[len(c) for c in comms[:MAX_CONSTELLATIONS]]}")
    return label


def layout(n, src, dst, year, comm, ncomm):
    """Force layout with d3-force in Node. The radius of a star follows its year."""
    rng = np.random.default_rng(SEED)
    spacing = 12.0
    R = math.sqrt(n * spacing * spacing / math.pi)
    # Radius follows the rank of the decision year. Equal area per case.
    order = np.argsort(year, kind="stable")
    rank = np.empty(n)
    rank[order] = np.arange(n)
    # Cases from the same year share one radius: use the mean rank per year.
    yr_mean = {}
    for y in np.unique(year):
        yr_mean[y] = rank[year == y].mean()
    r_target = np.array([math.sqrt((yr_mean[y] + 0.5) / n) for y in year]) * R
    r_target = np.maximum(r_target, 0.06 * R)
    # Angle follows the community. Each community gets a wedge in proportion to
    # its size, so the disc has an even density. Dust gets a random angle.
    sizes = np.bincount(comm[comm >= 0], minlength=ncomm).astype(float)
    total = max(1.0, sizes.sum())
    starts = np.concatenate([[0.0], np.cumsum(sizes)[:-1]]) / total
    centers = (starts + sizes / total / 2) * 2 * math.pi
    widths = sizes / total * 2 * math.pi
    base = np.where(comm >= 0, centers[np.maximum(comm, 0)], rng.uniform(0, 2 * math.pi, n))
    spread = np.where(comm >= 0, widths[np.maximum(comm, 0)] * 0.28, 1.0)
    ang = base + rng.normal(0, 1.0, n) * spread
    x0 = r_target * np.cos(ang) + rng.normal(0, 2.0, n)
    y0 = r_target * np.sin(ang) + rng.normal(0, 2.0, n)
    payload = {
        "n": n, "x": x0.tolist(), "y": y0.tolist(),
        "src": src.tolist(), "dst": dst.tolist(), "rTarget": r_target.tolist(),
        "ticks": TICKS, "charge": -16.0, "linkDistance": 20.0, "radialStrength": 0.45,
    }
    d3_path = RAW / "d3.min.js"
    if not d3_path.exists():
        raise SystemExit("d3.min.js is missing. Run fetch.py first.")
    res = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "layout.cjs"), str(d3_path)],
        input=json.dumps(payload), capture_output=True, text=True, check=True)
    for line in res.stderr.strip().splitlines():
        log(line)
    out = json.loads(res.stdout)
    pos = np.stack([np.array(out["x"]), np.array(out["y"])], 1)
    # Normalize: the 99.5th percentile radius becomes 1. Outliers stay within 1.04.
    r = np.hypot(pos[:, 0], pos[:, 1])
    pos = pos / np.percentile(r, 99.5)
    r = np.hypot(pos[:, 0], pos[:, 1])
    over = r > 1.04
    pos[over] *= (1.04 / r[over])[:, None]
    return pos


def pick_stars(members, indeg, pos):
    """Grow a compact set of bright stars around the brightest star of a community.

    Start with the brightest star. Then add the brightest remaining member that
    lies within CONSTELLATION_REACH of a star that is already in the set.
    """
    ranked = sorted(members, key=lambda i: -indeg[i])
    stars = [ranked[0]]
    pool = ranked[1:300]
    while len(stars) < STARS_PER_CONSTELLATION:
        pick = None
        for cand in pool:
            if any(np.hypot(*(pos[cand] - pos[s])) <= CONSTELLATION_REACH for s in stars):
                pick = cand
                break
        if pick is None:
            break
        stars.append(pick)
        pool.remove(pick)
    return stars


def constellation_lines(ids_by_comm, indeg, pos):
    """For each community, join its compact bright stars with a minimum spanning tree."""
    out = []
    for cid, members in ids_by_comm.items():
        stars = pick_stars(members, indeg, pos)
        if len(stars) < 3:
            continue
        g = nx.Graph()
        for a in stars:
            for b in stars:
                if a < b:
                    g.add_edge(a, b, weight=float(np.hypot(*(pos[a] - pos[b]))))
        tree = nx.minimum_spanning_tree(g)
        lines = [[int(a), int(b)] for a, b in tree.edges()]
        cx = float(np.mean([pos[s][0] for s in stars]))
        cy = float(np.mean([pos[s][1] for s in stars]))
        out.append({"id": cid, "stars": [int(s) for s in stars], "lines": lines, "x": cx, "y": cy})
    return out


def short_name(name, limit=44):
    name = " ".join(name.split())
    if len(name) <= limit:
        return name
    return name[:limit - 1].rstrip() + "…"


def write_preview(nodes, edges, cons):
    W, H = 800, 500
    cx, cy, s = W / 2, H / 2, 225
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             '<defs><radialGradient id="g" cx="50%" cy="50%" r="70%"><stop offset="0" stop-color="#101c3a"/>'
             '<stop offset="1" stop-color="#03050d"/></radialGradient></defs>',
             f'<rect width="{W}" height="{H}" fill="url(#g)"/>']
    for rr in (0.35, 0.6, 0.85, 1.0):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{rr * s:.1f}" fill="none" stroke="#c9a85a" stroke-opacity="0.18" stroke-width="0.6"/>')
    rng = random.Random(SEED)
    sample_edges = rng.sample(edges, min(2000, len(edges)))
    parts.append('<g stroke="#7fa6d9" stroke-opacity="0.08" stroke-width="0.4">')
    for a, b in sample_edges:
        parts.append(f'<line x1="{cx + nodes["x"][a] * s:.0f}" y1="{cy + nodes["y"][a] * s:.0f}" '
                     f'x2="{cx + nodes["x"][b] * s:.0f}" y2="{cy + nodes["y"][b] * s:.0f}"/>')
    parts.append('</g>')
    parts.append('<g stroke="#e8d7a6" stroke-opacity="0.55" stroke-width="0.7">')
    for c in cons:
        for a, b in c["lines"]:
            parts.append(f'<line x1="{cx + nodes["x"][a] * s:.1f}" y1="{cy + nodes["y"][a] * s:.1f}" '
                         f'x2="{cx + nodes["x"][b] * s:.1f}" y2="{cy + nodes["y"][b] * s:.1f}"/>')
    parts.append('</g>')
    maxd = max(nodes["indeg"]) or 1
    gold_cut = sorted(nodes["indeg"], reverse=True)[min(299, nodes["n"] - 1)]
    # Three classes of stars keep the markup small: faint, bright, and gold.
    classes = [("#a9c4ef", 0.38, []), ("#c9dbf7", 0.8, []), ("#f3d78a", 0.95, [])]
    for i in range(nodes["n"]):
        d = nodes["indeg"][i]
        k = 2 if d >= gold_cut else (1 if d >= 40 else 0)
        rad = 0.5 + 2.6 * math.sqrt(d / maxd)
        classes[k][2].append(f'<circle cx="{cx + nodes["x"][i] * s:.0f}" cy="{cy + nodes["y"][i] * s:.0f}" r="{rad:.1f}"/>')
    for col, op, items in classes:
        parts.append(f'<g fill="{col}" fill-opacity="{op}">')
        parts.extend(items)
        parts.append('</g>')
    parts.append('<text x="24" y="40" font-family="Georgia, serif" font-size="22" fill="#f1e4bf" '
                 'style="letter-spacing:3px">THE CITATION GALAXY</text>')
    parts.append('<text x="24" y="62" font-family="Georgia, serif" font-size="11" fill="#9fb3d8" '
                 'style="letter-spacing:2px">SUPREME COURT OPINIONS · CITATIONS AS LIGHT</text>')
    parts.append(f'<text x="{W - 24}" y="{H - 20}" text-anchor="end" font-family="Georgia, serif" font-size="10" '
                 f'fill="#9fb3d8" style="letter-spacing:1.5px">{nodes["n"]:,} STARS · {len(edges):,} CITATIONS</text>')
    parts.append('</svg>')
    (ROOM / "preview.svg").write_text("\n".join(parts))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases, raw_edges = load_cases()
    issue_of_scdb = load_scdb()
    edges = clean_edges(cases, raw_edges)
    keep, kept_edges, indeg, stats = trim(cases, edges)
    comm_label = communities(sorted(keep), kept_edges)

    ids = sorted(keep, key=lambda c: (cases[c]["year"], cases[c]["cite"], c))
    index = {c: i for i, c in enumerate(ids)}
    n = len(ids)
    year = np.array([cases[c]["year"] for c in ids])
    comm = np.array([comm_label[c] for c in ids])
    src = np.array([index[s] for s, _ in kept_edges])
    dst = np.array([index[t] for _, t in kept_edges])
    log("layout start")
    pos = layout(n, src, dst, year, comm, MAX_CONSTELLATIONS)
    log("layout done")

    indeg_arr = [int(indeg[c]) for c in ids]
    issue_arr = []
    for c in ids:
        sc = cases[c]["scdb"]
        issue_arr.append(issue_of_scdb.get(sc, 0) if sc else 0)

    nodes = {
        "n": n,
        "name": [short_name(cases[c]["name"]) for c in ids],
        "cite": [cases[c]["cite"] for c in ids],
        "year": [int(y) for y in year],
        "indeg": indeg_arr,
        "x": [round(float(v), 4) for v in pos[:, 0]],
        "y": [round(float(v), 4) for v in pos[:, 1]],
        "comm": [int(v) for v in comm],
        "issue": issue_arr,
    }

    # Edges sorted by citing year, then shuffled inside the year.
    rng = random.Random(SEED)
    pairs = [(int(s), int(t)) for s, t in zip(src, dst)]
    rng.shuffle(pairs)
    pairs.sort(key=lambda e: year[e[0]])
    arr = np.array(pairs, dtype=np.uint16)
    (OUT / "edges.u16").write_bytes(arr.tobytes())

    by_comm = defaultdict(list)
    for i, c in enumerate(nodes["comm"]):
        if c >= 0:
            by_comm[c].append(i)
    cons = constellation_lines(by_comm, indeg_arr, pos)
    for c in cons:
        members = by_comm[c["id"]]
        brightest = max(members, key=lambda i: indeg_arr[i])
        c["name"] = nodes["name"][brightest]
        c["size"] = len(members)
        years = sorted(nodes["year"][i] for i in members)
        c["median_year"] = int(years[len(years) // 2])
        counted = Counter(nodes["issue"][i] for i in members if nodes["issue"][i])
        if counted:
            top, cnt = counted.most_common(1)[0]
            c["issue"] = ISSUE_AREAS.get(top, "")
            c["issue_share"] = round(cnt / sum(counted.values()), 3)
        else:
            c["issue"] = ""
            c["issue_share"] = 0

    meta = {
        "source": "Caselaw Access Project, United States Reports volumes, static.case.law/us/",
        "year_min": int(year.min()),
        "year_max": int(year.max()),
        "cases_total": len(cases),
        "edges_total": len(edges),
        "nodes": n,
        "edges": len(pairs),
        "min_indeg_kept": MIN_INDEG,
        "scdb_issue_areas": bool(issue_of_scdb),
        "issue_names": ISSUE_AREAS,
        "constellations": cons,
        "stats": stats,
    }
    (OUT / "nodes.json").write_text(json.dumps(nodes, separators=(",", ":"), ensure_ascii=False))
    (OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":"), ensure_ascii=False))
    write_preview(nodes, pairs, cons)
    sizes = {p.name: p.stat().st_size for p in OUT.iterdir()}
    log(f"written {sizes}, total {sum(sizes.values()) / 1e6:.2f} MB")
    top = sorted(range(n), key=lambda i: -indeg_arr[i])[:10]
    for i in top:
        log(f"  {indeg_arr[i]:5d}  {nodes['year'][i]}  {nodes['name'][i]}  {nodes['cite'][i]}")
    for c in cons:
        log(f"  constellation {c['id']}: {c['size']} stars, {c['name']} ({c['median_year']}) {c['issue']} {c['issue_share']}")


if __name__ == "__main__":
    main()
