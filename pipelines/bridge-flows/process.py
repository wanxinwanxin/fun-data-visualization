"""Build the monthly bridge flow matrices for the Liquidity in Motion room.

Stdlib only. Run from the repository root after fetch.py:

    .venv/bin/python3 -I pipelines/bridge-flows/process.py

Input:  data/raw/bridge-flows/*.json (DefiLlama dimensions API responses)
Output: rooms/bridge-flows/data/flows.json
        rooms/bridge-flows/preview.svg

Direction convention
--------------------
DefiLlama gives two daily series per bridge and per chain:
  outgoing = USD value that leaves the chain through the bridge
  incoming = USD value that arrives on the chain through the bridge

Pair bridges (exactly two chains, for example Ethereum and Arbitrum):
  flow[A -> B] = max(outgoing on A, incoming on B)
  The two numbers are equal when the adapter reports both sides.
  The max keeps the value when the adapter reports one side only.

Multi-chain bridges (three or more chains):
  The API does not give the destination chain of each transfer. The room
  shows these bridges as a "multi-chain hub" node.
  flow[chain -> hub] = outgoing on the chain
  flow[hub -> chain] = incoming on the chain

Chains outside the fixed node list go into one "Other networks" node, so no
value is dropped. Values are rounded to thousands of USD.
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "bridge-flows"
OUT = ROOT / "rooms" / "bridge-flows" / "data"
OUT.mkdir(parents=True, exist_ok=True)

MONTHS_BACK = 24
NAMED_CHAINS = 12  # Ethereum plus eleven more, chosen by total flow

# Ethereum rollups and validiums. Every other network is "other".
ROLLUPS = {
    "Arbitrum", "OP Mainnet", "Base", "ZKsync Era", "Linea", "Scroll", "Starknet",
    "Mantle", "Unichain", "Blast", "Polygon zkEVM", "Ink", "World Chain", "Soneium",
    "Mode", "Zircuit", "Manta", "Lisk", "Robinhood Chain", "zkLighter", "Taiko",
    "Abstract", "Zora", "Mint", "Arbitrum Nova", "Metis", "Boba", "Katana", "X Layer",
    "Lens", "Redstone", "Fraxtal", "Swellchain", "Kinto", "Fuel Ignition", "Eclipse",
    "MegaETH", "Plume", "Plume Mainnet", "Hemi", "BOB", "Lighter",
}

CATEGORIES = {"Bridge", "Canonical Bridge", "Cross Chain Bridge", "Decentralized BTC"}


def month_key(ts):
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{d.year:04d}-{d.month:02d}"


def load(path):
    with open(path) as f:
        return json.load(f)


def series_by_chain(summary):
    """Return {chain: {month: usd}} from a summary totalDataChartBreakdown."""
    out = defaultdict(lambda: defaultdict(float))
    last_ts = 0
    for ts, per_chain in summary.get("totalDataChartBreakdown") or []:
        mk = month_key(ts)
        last_ts = max(last_ts, ts)
        for chain, versions in per_chain.items():
            v = sum(float(x or 0) for x in versions.values())
            out[chain][mk] += v
    return out, last_ts


def main():
    overview = load(RAW / "overview.json")
    protos = {p["slug"]: p for p in overview["protocols"]}

    bridges = []  # loaded bridge records
    last_ts = 0
    skipped = []
    for slug, p in sorted(protos.items()):
        if (p.get("category") or "") not in CATEGORIES:
            continue
        fo = RAW / f"{slug}__dailyOutgoingVolume.json"
        fi = RAW / f"{slug}__dailyIncomingVolume.json"
        if not (fo.exists() and fi.exists()):
            continue
        so, si = load(fo), load(fi)
        if so.get("doublecounted"):
            skipped.append(slug)
            continue
        out, t1 = series_by_chain(so)
        inc, t2 = series_by_chain(si)
        last_ts = max(last_ts, t1, t2)
        chains = sorted(set(out) | set(inc))
        bridges.append({
            "slug": slug, "name": p.get("displayName") or p["name"],
            "category": p.get("category"), "chains": chains,
            "kind": "pair" if len(chains) == 2 else "multi",
            "out": out, "inc": inc,
        })
    print(f"{len(bridges)} bridges loaded, {len(skipped)} skipped as double counted: {skipped}")

    # Month window: the last MONTHS_BACK months up to the month of the last data point.
    last = datetime.fromtimestamp(last_ts, tz=timezone.utc)
    months = []
    y, m = last.year, last.month
    for _ in range(MONTHS_BACK):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    mset = set(months)

    # Flow per chain, used to choose the named chains.
    chain_total = defaultdict(float)
    for b in bridges:
        for c in b["chains"]:
            chain_total[c] += sum(v for k, v in b["out"][c].items() if k in mset)
            chain_total[c] += sum(v for k, v in b["inc"][c].items() if k in mset)
    ranked = [c for c, _ in sorted(chain_total.items(), key=lambda kv: -kv[1]) if c != "Ethereum"]
    named = ["Ethereum"] + ranked[:NAMED_CHAINS - 1]
    l2 = [c for c in named if c in ROLLUPS]
    other = [c for c in named if c not in ROLLUPS and c != "Ethereum"]
    # Circle order: Ethereum, rollups, hub, other networks. Neighbor colors stay distinct.
    order = ["Ethereum"] + l2 + ["Multi-chain hub"] + other + ["Other networks"]
    nodes = []
    for c in order:
        g = "l1" if c == "Ethereum" else "l2" if c in ROLLUPS else "hub" if c == "Multi-chain hub" else "other"
        nodes.append({"id": c, "group": g})
    idx = {n["id"]: i for i, n in enumerate(nodes)}
    HUB, OTHER = idx["Multi-chain hub"], idx["Other networks"]

    def node_of(chain):
        return idx.get(chain, OTHER)

    n = len(nodes)
    matrix = [[[0.0] * n for _ in range(n)] for _ in months]
    bridge_rows = []
    for b in bridges:
        monthly = [0.0] * len(months)
        for mi, mk in enumerate(months):
            monthly[mi] = sum(b["out"][c].get(mk, 0.0) for c in b["chains"])
            if b["kind"] == "pair":
                a, c2 = b["chains"]
                ia, ic = node_of(a), node_of(c2)
                if ia == ic:
                    # Both ends fold into the same node. Keep the value on the diagonal.
                    matrix[mi][ia][ia] += monthly[mi]
                    continue
                matrix[mi][ia][ic] += max(b["out"][a].get(mk, 0.0), b["inc"][c2].get(mk, 0.0))
                matrix[mi][ic][ia] += max(b["out"][c2].get(mk, 0.0), b["inc"][a].get(mk, 0.0))
            else:
                for c in b["chains"]:
                    i = node_of(c)
                    matrix[mi][i][HUB] += b["out"][c].get(mk, 0.0)
                    matrix[mi][HUB][i] += b["inc"][c].get(mk, 0.0)
        if sum(monthly) <= 0:
            continue
        bridge_rows.append({
            "name": b["name"], "category": b["category"], "kind": b["kind"],
            "chains": len(b["chains"]),
            "monthly": [int(round(v / 1000.0)) for v in monthly],
        })
    bridge_rows.sort(key=lambda r: -sum(r["monthly"]))
    k_matrix = [[[int(round(v / 1000.0)) for v in row] for row in mat] for mat in matrix]
    totals = [sum(r["monthly"][mi] for r in bridge_rows) for mi in range(len(months))]

    last_day = last.strftime("%Y-%m-%d")
    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "DefiLlama dimensions API, https://api.llama.fi/overview/bridges and /summary/bridges/<slug>",
        "unit": "thousand USD",
        "months": months,
        "last_day": last_day,
        "last_month_partial": last_day[:7] == months[-1] and last.day < 28,
        "nodes": nodes,
        "matrix": k_matrix,
        "totals": totals,
        "bridges": bridge_rows,
        "bridge_count": len(bridge_rows),
    }
    path = OUT / "flows.json"
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"wrote {path} ({path.stat().st_size / 1024:.1f} KB)")
    print("months", months[0], "to", months[-1], "last day", last_day)
    print("nodes", [nd["id"] for nd in nodes])
    print("bridges in output", len(bridge_rows))
    for mi in (0, len(months) // 2, len(months) - 1):
        print(months[mi], "total", totals[mi], "k USD")
    write_preview(data)


def write_preview(data):
    """Draw a static chord still from the last complete month."""
    months = data["months"]
    mi = len(months) - 2 if data["last_month_partial"] and len(months) > 1 else len(months) - 1
    mat = data["matrix"][mi]
    nodes = data["nodes"]
    n = len(nodes)
    colors = {"l1": "#2a78d6", "l2": "#eb6834", "other": "#1baf7a", "hub": "#6250d6"}
    W, H, cx, cy, R = 800, 500, 400, 262, 178
    tot = [sum(mat[i]) + sum(mat[j][i] for j in range(n)) for i in range(n)]
    grand = sum(tot) or 1.0
    pad = 0.03
    span = 2 * math.pi - pad * n
    ang = []
    a = -math.pi / 2
    for i in range(n):
        w = span * tot[i] / grand
        ang.append((a, a + w))
        a += w + pad

    def pt(theta, r):
        return cx + r * math.cos(theta), cy + r * math.sin(theta)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        '<defs>',
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0" stop-color="#eef2ff"/><stop offset="0.5" stop-color="#fdf2f8"/><stop offset="1" stop-color="#ecfeff"/>',
        '</linearGradient>',
        '<filter id="blur"><feGaussianBlur stdDeviation="28"/></filter>',
        '<filter id="soft"><feGaussianBlur stdDeviation="0.6"/></filter>',
        '</defs>',
        f'<rect width="{W}" height="{H}" fill="url(#bg)"/>',
        '<circle cx="150" cy="90" r="140" fill="#c7d2fe" opacity="0.55" filter="url(#blur)"/>',
        '<circle cx="680" cy="420" r="150" fill="#fbcfe8" opacity="0.5" filter="url(#blur)"/>',
        '<circle cx="640" cy="60" r="110" fill="#a5f3fc" opacity="0.5" filter="url(#blur)"/>',
    ]
    # Ribbons: the largest flows.
    flows = []
    for i in range(n):
        for j in range(n):
            if i != j and mat[i][j] > 0:
                flows.append((mat[i][j], i, j))
    flows.sort(reverse=True)
    for v, i, j in flows[:40]:
        a0, a1 = ang[i]
        b0, b1 = ang[j]
        ta = (a0 + a1) / 2
        tb = (b0 + b1) / 2
        w = max(1.5, 26 * v / (flows[0][0] or 1))
        x1, y1 = pt(ta, R - 2)
        x2, y2 = pt(tb, R - 2)
        gid = f"g{i}_{j}"
        parts.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}">'
                     f'<stop offset="0" stop-color="{colors[nodes[i]["group"]]}"/><stop offset="1" stop-color="{colors[nodes[j]["group"]]}"/></linearGradient>')
        parts.append(f'<path d="M{x1:.1f},{y1:.1f} Q{cx},{cy} {x2:.1f},{y2:.1f}" fill="none" stroke="url(#{gid})" '
                     f'stroke-width="{w:.1f}" stroke-linecap="round" opacity="0.42"/>')
    # Arcs as glass tiles.
    for i, nd in enumerate(nodes):
        a0, a1 = ang[i]
        c = colors[nd["group"]]
        large = 1 if (a1 - a0) > math.pi else 0
        xo0, yo0 = pt(a0, R + 18)
        xo1, yo1 = pt(a1, R + 18)
        xi1, yi1 = pt(a1, R)
        xi0, yi0 = pt(a0, R)
        d = (f"M{xo0:.1f},{yo0:.1f} A{R + 18},{R + 18} 0 {large} 1 {xo1:.1f},{yo1:.1f} "
             f"L{xi1:.1f},{yi1:.1f} A{R},{R} 0 {large} 0 {xi0:.1f},{yi0:.1f} Z")
        parts.append(f'<path d="{d}" fill="{c}" opacity="0.78"/>')
        parts.append(f'<path d="{d}" fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="1.2"/>')
        if (a1 - a0) > 0.11:
            tm = (a0 + a1) / 2
            lx, ly = pt(tm, R + 34)
            anchor = "start" if math.cos(tm) > 0.15 else "end" if math.cos(tm) < -0.15 else "middle"
            label = nd["id"].replace("Multi-chain hub", "Hub")
            parts.append(f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="{anchor}" font-family="Outfit, Manrope, system-ui, sans-serif" '
                         f'font-size="13" fill="#2b2d42">{label}</text>')
    total = data["totals"][mi] / 1e6
    parts.append('<rect x="24" y="384" width="236" height="92" rx="20" fill="#ffffff" fill-opacity="0.6" stroke="#ffffff" stroke-opacity="0.9"/>')
    parts.append('<text x="44" y="412" font-family="Outfit, Manrope, system-ui, sans-serif" font-size="12" fill="#5a5d7a" letter-spacing="1.5">LIQUIDITY IN MOTION</text>')
    parts.append(f'<text x="44" y="446" font-family="Outfit, Manrope, system-ui, sans-serif" font-size="30" font-weight="600" fill="#1f2140">${total:,.1f}B</text>')
    parts.append(f'<text x="44" y="466" font-family="Outfit, Manrope, system-ui, sans-serif" font-size="12" fill="#5a5d7a">bridged in {months[mi]}</text>')
    parts.append('</svg>')
    svg = ROOT / "rooms" / "bridge-flows" / "preview.svg"
    svg.write_text("\n".join(parts))
    print(f"wrote {svg} ({svg.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
