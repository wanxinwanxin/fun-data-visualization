"""Rebuild a scanned Census table from OCR boxes.

Usage: ocr_table.py <page> ; writes data/raw/treasury-machine/tab/table<page>.json
Each page has one or more panels. A panel is a block of rows with a year column at
the left and N numeric columns. Numbers are right-aligned in the scan, so a box
belongs to the column whose right edge is nearest to the box's right edge.
"""
import json, re, sys
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "treasury-machine" / "tab"

# Panel specs at 300 dpi: year column x-range, numeric x-range, y-range, column keys.
SPECS = {
    40: {"cols_note": "Y352-357 receipts 1789-1939, thousands of dollars",
         "panels": [
             {"year_x": (90, 230), "num_x": (230, 1310), "y": (680, 2900), "cols": ["total", "customs", "internal", "other", "land", "refunds"], "optional": ["refunds", "land"]},
             {"year_x": (1300, 1450), "num_x": (1450, 2400), "y": (680, 2900), "cols": ["total", "customs", "internal", "other", "land"], "optional": ["internal", "land"]}]},
    48: {"cols_note": "Y457-465 outlays 1846-1970, thousands of dollars",
         "panels": [
             {"year_x": (1160, 1300), "num_x": (1300, 2500), "y": (1170, 1325), "cols": ["total", "army", "navy", "airforce", "interest", "other", "veterans"], "optional": ["airforce"], "edges": [1412, 1566, 1713, 1860, 2005, 2158, 2298]},
             {"year_x": (40, 170), "num_x": (170, 1180), "y": (1640, 3060), "cols": ["total", "army", "navy", "interest", "other", "veterans"]},
             {"year_x": (1160, 1300), "num_x": (1300, 2500), "y": (1640, 3060), "cols": ["total", "army", "navy", "interest", "other", "veterans"]}]},
    49: {"cols_note": "Y457-465 outlays 1789-1845 and Y466-471 by function 1900-1939 (millions)",
         "panels": [
             {"year_x": (90, 230), "num_x": (230, 1250), "y": (690, 1580), "cols": ["total", "army", "navy", "interest", "other", "veterans"], "optional": ["interest", "navy", "veterans"]},
             {"year_x": (1230, 1370), "num_x": (1370, 2450), "y": (690, 1580), "cols": ["total", "army", "navy", "interest", "other", "veterans"], "optional": ["interest", "navy", "veterans"]},
]},
    38: {"cols_note": "Y335-338 summary 1789-1939, thousands of dollars",
         "panels": [
             {"year_x": (240, 330), "num_x": (330, 1080), "y": (1450, 2950), "cols": ["receipts", "outlays", "surplus", "debt"]},
             {"year_x": (1080, 1200), "num_x": (1200, 1900), "y": (1450, 2950), "cols": ["receipts", "outlays", "surplus", "debt"]},
             {"year_x": (1880, 2010), "num_x": (2010, 2600), "y": (1450, 2950), "cols": ["receipts", "outlays", "surplus", "debt"]}]},
    41: {"cols_note": "Y358-372 internal revenue 1916-1970, thousands of dollars",
         "panels": [
             {"year_x": (90, 230), "num_x": (230, 1400), "y": (1760, 2430), "cols": ["total", "individual", "corporate", "employment", "estate", "excise", "alcohol", "tobacco"], "optional": ["individual", "corporate", "employment", "estate", "excise"]},
             {"year_x": (90, 230), "num_x": (1770, 1950), "y": (1760, 2430), "cols": ["gasoline"], "optional": ["gasoline"]}]},
    42: {"cols_note": "Y358-373 internal revenue 1863-1915, thousands of dollars",
         "panels": [
             {"year_x": (90, 230), "num_x": (230, 1190), "y": (740, 1560), "cols": ["total", "estate", "alcohol", "tobacco", "manufacturers", "stamp"], "optional": ["estate", "manufacturers", "stamp", "tobacco"]},
             {"year_x": (1200, 1340), "num_x": (1340, 2400), "y": (740, 1560), "cols": ["total", "estate", "alcohol", "tobacco", "manufacturers", "stamp"], "optional": ["estate", "manufacturers", "stamp", "tobacco"]}]},
}

def tol(r, k="total"):
    return max(3, 0.0003 * abs(r.get(k) or 0))

CHECKS = {
    40: lambda r: r.get("total") is not None and abs(r["total"] - sum((r.get(k) or 0) for k in ("customs", "internal", "other", "refunds"))) <= tol(r),
    48: lambda r: r.get("total") is not None and abs(r["total"] - sum((r.get(k) or 0) for k in ("army", "navy", "airforce", "interest", "other"))) <= tol(r),
    49: lambda r: r.get("total") is not None and (abs(r["total"] - sum((r.get(k) or 0) for k in ("army", "navy", "interest", "other"))) <= tol(r) if "army" in r else True),
    38: lambda r: r.get("receipts") is not None and r.get("outlays") is not None and abs(r["receipts"] - r["outlays"] - (r.get("surplus") or 0)) <= 2,
}

# Manual corrections after a visual check of the scan: (page, panel, year, column) -> value
CORRECTIONS = {
    (40, 0, 1895, "internal"): 143422, (40, 0, 1892, "internal"): 153971, (40, 0, 1887, "other"): 35293, (40, 1, 1835, "total"): 35430,
    (48, 1, 1930, "total"): 3320211, (48, 1, 1922, "interest"): 991001, (48, 1, 1901, "navy"): 60507,
    (49, 0, 1831, "interest"): 1384, (49, 0, 1829, "interest"): 2543, (49, 0, 1824, "army"): 3341, (49, 0, 1823, "other"): 4183,
    (49, 1, 1811, "army"): 2033, (49, 1, 1801, "total"): 9395, (49, 1, 1801, "army"): 1673, (49, 1, 1801, "veterans"): 74,
    (49, 1, 1793, "navy"): 0, (49, 1, 1792, "navy"): 0,
    (41, 0, 1919, "individual"): None, (41, 0, 1919, "corporate"): None, (41, 0, 1918, "individual"): None, (41, 0, 1918, "corporate"): None,
    (42, 1, 1865, "manufacturers"): 73318, (42, 1, 1870, "stamp"): 15611, (42, 1, 1874, "stamp"): 5683,
}
# Panels transcribed by hand from the scan, where the OCR boxes ran together: (page, panel) -> rows
MANUAL = {(48, 0): [
    {"year": 1940, "total": 9055269, "army": 907160, "navy": 891485, "airforce": None, "interest": 1040936, "other": 6215689, "veterans": 429178},
    {"year": 1939, "total": 8841224, "army": 695256, "navy": 672722, "airforce": None, "interest": 940540, "other": 6532705, "veterans": 416721},
    {"year": 1938, "total": 6764628, "army": 644264, "navy": 596130, "airforce": None, "interest": 926281, "other": 4597954, "veterans": 402779},
    {"year": 1937, "total": 7733033, "army": 628104, "navy": 556674, "airforce": None, "interest": 866384, "other": 5681871, "veterans": 399047},
    {"year": 1936, "total": 8421608, "army": 618587, "navy": 528882, "airforce": None, "interest": 749397, "other": 6524742, "veterans": 399066}]}
# Rows to drop: OCR split one period label into two rows. (page, panel, year)
DROP = {(49, 1, 1791)}
# A row that stands for a period: (page, panel, year) -> (first, last)
PERIODS = {(49, 1, 1790): (1789, 1791), (40, 1, 1789): (1789, 1791)}

NUM = re.compile(r"^[-−]?[\d,]+$")


def clean(t):
    t = t.strip().replace("−", "-").replace(" ", "")
    t = t.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1").replace("S", "5").replace("B", "8")
    t = re.sub(r"[.…_]+$", "", t)
    return t


def parse_num(t):
    t = clean(t)
    if t in ("-", "--", "---") or t.startswith("(Z") or t == "(Z)":
        return 0.0
    if "NA" in t:
        return None
    t = t.replace("(", "").replace(")", "")
    if NUM.match(t):
        return float(t.replace(",", ""))
    return None


def year_of(t):
    t = t.strip()
    m = re.match(r"^(1[6-9]\d\d)(?:\D|$)", t)
    return int(m.group(1)) if m else None


def cluster_right_edges(xs, gap=55):
    xs = sorted(xs)
    groups = [[xs[0]]]
    for x in xs[1:]:
        if x - groups[-1][-1] > gap:
            groups.append([x])
        else:
            groups[-1].append(x)
    return [sum(g) / len(g) for g in groups]


def build(page):
    spec = SPECS[page]
    boxes = json.load(open(RAW / f"ocr{page}.json"))
    for b in boxes:
        b["cx"] = (b["x0"] + b["x1"]) / 2; b["cy"] = (b["y0"] + b["y1"]) / 2
    out = []
    for pi, p in enumerate(spec["panels"]):
        inp = lambda b, xr: xr[0] <= b["cx"] <= xr[1] and p["y"][0] <= b["cy"] <= p["y"][1]
        years = [b for b in boxes if inp(b, p["year_x"]) and year_of(b["text"])]
        nums = [b for b in boxes if inp(b, p["num_x"]) and parse_num(b["text"]) is not None]
        for yb in years:
            m = re.search(r"([\d,]{3,})\s*$", yb["text"][4:])
            if m and parse_num(m.group(1)) is not None:
                nums.append({**yb, "text": m.group(1), "cx": (yb["x0"] + yb["x1"]) / 2, "glued": True})
        # some year boxes carry the first number glued on; split by regex
        edges = p.get("edges") or cluster_right_edges([b["x1"] for b in nums])
        ncol = len(p["cols"])
        if len(edges) != ncol:
            print(f"page {page} panel {pi}: found {len(edges)} column edges {[int(e) for e in edges]} for {ncol} cols", file=sys.stderr)
            # keep the ncol largest groups by population
            pop = {}
            for b in nums:
                e = min(edges, key=lambda e: abs(e - b["x1"])); pop[e] = pop.get(e, 0) + 1
            edges = sorted(sorted(edges, key=lambda e: -pop[e])[:ncol])
        rows = []
        ybs = sorted(years, key=lambda b: b["cy"])
        # repair the year sequence: each panel runs downward one year per row
        for i in range(1, len(ybs)):
            prev = year_of(ybs[i - 1]["text"]); cur = year_of(ybs[i]["text"])
            gap = ybs[i]["cy"] - ybs[i - 1]["cy"]
            if cur != prev - 1 and gap < 40 and abs(cur - (prev - 1)) <= 10:
                ybs[i]["fixed"] = f'{ybs[i]["text"]}->{prev - 1}'
                ybs[i]["text"] = str(prev - 1)
        for yb in ybs:
            rows.append({"year": year_of(yb["text"]), "_y": int(yb["cy"]), "_cy": yb["cy"], "_src": {}, **({"_yearfix": yb["fixed"]} if "fixed" in yb else {})})
        def groups(items, key):
            items = sorted(items, key=key); out = [[items[0]]]
            for it in items[1:]:
                (out.append([it]) if key(it) - key(out[-1][-1]) > 34 else out[-1].append(it))
            return out
        ygroups = groups(rows, lambda r: r["_cy"]) if rows else []
        bycol = {}
        for b in nums:
            ci = min(range(ncol), key=lambda i: abs(edges[i] - b["x1"])); bycol.setdefault(ci, []).append(b)
        def put(r, key, b, src=""):
            if key in r:
                r.setdefault("_dup", []).append((key, r["_src"][key], b["text"]))
            r[key] = parse_num(b["text"]); r["_src"][key] = b["text"] + src
        pending = []; offsets = {}
        for ci, bs in bycol.items():
            key = p["cols"][ci]
            bgroups = groups(bs, lambda b: b["cy"])
            # pair box groups with year groups by vertical overlap, then match rows in order
            for bg in bgroups:
                top, bot = bg[0]["cy"], bg[-1]["cy"]
                yg = max(ygroups, key=lambda g: min(bot, g[-1]["_cy"]) - max(top, g[0]["_cy"]))
                if len(bg) == len(yg):
                    for b, r in zip(bg, yg):
                        put(r, key, b); offsets.setdefault(ci, []).append(b["cy"] - r["_cy"])
                else:
                    pending.append((ci, key, bg, yg))
        med = lambda v: sorted(v)[len(v) // 2]
        allofs = [o for v in offsets.values() for o in v]
        for ci, key, bg, yg in pending:
            off = med(offsets[ci]) if ci in offsets else (med(allofs) if allofs else 8)
            for b in bg:
                r = min(yg, key=lambda r: abs(r["_cy"] + off - b["cy"]))
                if abs(r["_cy"] + off - b["cy"]) <= 12:
                    put(r, key, b)
        # second look at empty cells: re-OCR the single cell from a 2x crop
        img = None
        for r in rows:
            for ci, key in enumerate(p["cols"]):
                if r.get(key) is not None:
                    continue
                if img is None:
                    from PIL import Image
                    from rapidocr_onnxruntime import RapidOCR
                    img = Image.open(RAW / f"h{page}-{page}.png"); ocr = RapidOCR()
                x1 = int(edges[ci]) + 12; x0 = x1 - 175; y0 = int(r["_cy"] - 6); y1 = int(r["_cy"] + 30)
                crop = img.crop((x0, y0, x1, y1)).resize(((x1 - x0) * 2, (y1 - y0) * 2), Image.LANCZOS)
                res, _ = ocr(crop)
                for box, text, score in (res or []):
                    if parse_num(text) is not None and max(q[0] for q in box) / 2 + x0 > x1 - 60:
                        r[key] = parse_num(text); r["_src"][key] = text + "*"; r["_reocr"] = True
        for r in rows:
            if "refunds" in p["cols"] and r.get("refunds"):
                r["refunds"] = -abs(r["refunds"])
        check = CHECKS.get(page)
        CONF = {"3": "8", "8": "3", "5": "6", "6": "5", "1": "7", "7": "1", "0": "9", "9": "0", "4": "1"}
        if check:
            for r in rows:
                if check(r) or any(r.get(c) is None for c in p["cols"]):
                    continue
                cands = []
                for c in p["cols"]:
                    txt = clean(r["_src"][c].rstrip("*")).replace(",", "")
                    for i, ch in enumerate(txt):
                        if ch in CONF:
                            alt = txt[:i] + CONF[ch] + txt[i + 1:]
                            try:
                                v = float(alt)
                            except ValueError:
                                continue
                            trial = dict(r); trial[c] = v
                            if check(trial):
                                cands.append((c, v, txt, alt))
                if len(cands) == 1:
                    c, v, txt, alt = cands[0]
                    r[c] = v; r["_fix"] = f"{c} {txt}->{alt}"
        for r in rows:
            del r["_cy"]
        rows = [r for r in rows if (page, pi, r["year"]) not in DROP]
        if (page, pi) in MANUAL:
            rows = [{**r, "_y": 0, "_src": {c: "manual" for c in p["cols"]}} for r in MANUAL[(page, pi)]]
        for r in rows:
            for c in p["cols"]:
                if (page, pi, r["year"], c) in CORRECTIONS:
                    r[c] = CORRECTIONS[(page, pi, r["year"], c)]; r["_src"][c] = "manual"
            if (page, pi, r["year"]) in PERIODS:
                r["period"] = PERIODS[(page, pi, r["year"])]
            # a lone "1" in an optional column is a dashed blank cell
            for c in p.get("optional", []):
                if r.get(c) == 1.0 and not r["_src"].get(c, "").startswith("manual"):
                    r[c] = None
        out.append({"panel": pi, "cols": p["cols"], "edges": [int(e) for e in edges], "rows": rows})
    json.dump(out, open(RAW / f"table{page}.json", "w"), indent=0)
    return out


if __name__ == "__main__":
    page = int(sys.argv[1])
    res = build(page)
    from PIL import Image
    img = Image.open(RAW / f"h{page}-{page}.png"); crops = []
    for panel in res:
        print(f"-- panel {panel['panel']} cols {panel['cols']} edges {panel['edges']} rows {len(panel['rows'])}")
        for r in panel["rows"]:
            vals = [r.get(c) for c in panel["cols"]]
            opt = SPECS[page]["panels"][panel["panel"]].get("optional", [])
            flag = "" if all(r.get(c) is not None for c in panel["cols"] if c not in opt) else "  <-- missing"
            if "_dup" in r: flag += f"  <-- dup {r['_dup']}"
            if "_yearfix" in r: flag += f"  <-- year {r['_yearfix']}"
            if "_reocr" in r: flag += "  (re-ocr)"
            if "_fix" in r: flag += f"  (fixed {r['_fix']})"
            if page in CHECKS and not CHECKS[page](r): flag += "  <-- SUM MISMATCH"
            if "MISMATCH" in flag or "missing" in flag or "dup" in flag:
                px = SPECS[page]["panels"][panel["panel"]]
                crops.append((r["year"], img.crop((px["year_x"][0], r["_y"] - 16, px["num_x"][1], r["_y"] + 20))))
            print(r["year"], vals, flag)
    if crops:
        w = max(c.size[0] for _, c in crops); h = sum(c.size[1] + 6 for _, c in crops)
        sheet = Image.new("RGB", (w, h), "white"); y = 0
        for yr, c in crops:
            sheet.paste(c, (0, y)); y += c.size[1] + 6
        sheet.save(RAW / f"review{page}.png"); print("review sheet", RAW / f"review{page}.png", len(crops), "rows")
