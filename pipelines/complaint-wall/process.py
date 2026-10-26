"""Aggregate the raw complaint files into compact JSON for The Complaint Wall.

Run from the repository root after fetch.py:
  .venv/bin/python3 -I pipelines/complaint-wall/process.py

Inputs (data/raw/complaint-wall/):
  cfpb_complaints.csv.zip   CFPB Consumer Complaint Database, one row per complaint.
  nhtsa_FLAT_CMPL.zip       NHTSA vehicle complaints, one row per complaint-component pair.

Outputs (rooms/complaint-wall/data/):
  cfpb.json    monthly grid company x issue, product x issue, and sub-issue clusters.
  nhtsa.json   monthly grid make x component, make x model-year per component,
               and narrative keyword counts per month.
  ../preview.svg  a static still drawn from the NHTSA grid.

Set COMPLAINT_WALL_LIMIT=<rows> in the environment to run a quick smoke test
on the first rows of each file.
"""
import io
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pcsv

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "complaint-wall"
OUT = ROOT / "rooms" / "complaint-wall" / "data"
OUT.mkdir(parents=True, exist_ok=True)
LIMIT = int(os.environ.get("COMPLAINT_WALL_LIMIT", "0")) or None

# The file is a snapshot. The month of the snapshot is incomplete, so we drop it.
TODAY = date.today()
CUTOFF_MONTH = f"{TODAY.year:04d}-{TODAY.month:02d}"

N_ROWS = 25          # top entities (companies, makes) kept as rows
N_COLS = 14          # top sub-categories (issues, components) kept as columns
N_CLUSTERS = 60      # distinct cluster labels kept for the side strip
TOP_PER_MONTH = 8    # clusters listed per month


def month_range(first, last):
    """Return the list of YYYY-MM strings from first to last inclusive."""
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fold(series, keep, other="OTHER"):
    """Map values outside the keep list to OTHER and return integer codes."""
    index = {k: i for i, k in enumerate(keep)}
    codes = series.map(index)
    return codes.fillna(len(keep)).astype(np.int64).to_numpy()


def grid(df, months, row_keep, col_keep, row_field, col_field):
    """Build a dense [month][row][col] count array with OTHER folded in."""
    mi = {m: i for i, m in enumerate(months)}
    keep = df[row_field + "_code"].notna() if False else np.ones(len(df), bool)
    m = df["month"].map(mi)
    ok = m.notna().to_numpy()
    m = m.fillna(0).astype(np.int64).to_numpy()
    r = fold(df[row_field], row_keep)
    c = fold(df[col_field], col_keep)
    R, C = len(row_keep) + 1, len(col_keep) + 1
    flat = (m * R + r) * C + c
    counts = np.bincount(flat[ok], weights=df["n"].to_numpy()[ok], minlength=len(months) * R * C)
    return counts.astype(np.int64).reshape(len(months), R, C)


# ---------------------------------------------------------------- CFPB ----

# The CFPB issue taxonomy changed in April 2017. These older labels map onto
# the newer label that covers the same failure mode, so the columns stay
# stable across the whole period.
ISSUE_MERGE = {
    "Incorrect information on credit report": "Incorrect information on your report",
    "Credit reporting company's investigation": "Problem with a company's investigation into an existing problem",
    "Problem with a credit reporting company's investigation into an existing problem": "Problem with a company's investigation into an existing problem",
    "Cont'd attempts collect debt not owed": "Attempts to collect debt not owed",
    "Loan servicing, payments, escrow account": "Trouble during payment process",
    "Loan modification,collection,foreclosure": "Struggling to pay mortgage",
    "Disclosure verification of debt": "Written notification about debt",
    "Improper contact or sharing of info": "Communication tactics",
    "Taking/threatening an illegal action": "Took or threatened to take negative or legal action",
    "Account opening, closing, or management": "Managing an account",
    "Deposits and withdrawals": "Managing an account",
    "Unable to get credit report/credit score": "Unable to get your credit report or credit score",
    "Improper use of my credit report": "Improper use of your report",
    "Billing disputes": "Problem with a purchase shown on your statement",
    "Identity theft / Fraud / Embezzlement": "Fraud or scam",
    "Dealing with my lender or servicer": "Dealing with your lender or servicer",
    "Problems when you are unable to pay": "Struggling to pay your loan",
    "Can't repay my loan": "Struggling to pay your loan",
    "Can't contact lender": "Problem with the payoff process at the end of the loan",
}

# Short display labels for the wall. Keys are the full CFPB labels.
ISSUE_SHORT = {
    "Incorrect information on your report": "WRONG INFO ON REPORT",
    "Problem with a company's investigation into an existing problem": "BAD INVESTIGATION",
    "Improper use of your report": "IMPROPER USE OF REPORT",
    "Attempts to collect debt not owed": "DEBT NOT OWED",
    "Managing an account": "MANAGING ACCOUNT",
    "Trouble during payment process": "PAYMENT PROCESS",
    "Struggling to pay mortgage": "CAN'T PAY MORTGAGE",
    "Written notification about debt": "DEBT NOTIFICATION",
    "Communication tactics": "COMM. TACTICS",
    "Problem with a purchase shown on your statement": "PURCHASE DISPUTE",
    "Fraud or scam": "FRAUD OR SCAM",
    "Dealing with your lender or servicer": "LENDER / SERVICER",
    "Struggling to pay your loan": "CAN'T PAY LOAN",
    "Unable to get your credit report or credit score": "NO ACCESS TO REPORT",
    "Problem with a lender or other company charging your account": "UNAUTHORIZED CHARGE",
    "Closing an account": "CLOSING ACCOUNT",
    "Took or threatened to take negative or legal action": "THREATS / LEGAL ACTION",
    "False statements or representation": "FALSE STATEMENTS",
    "Applying for a mortgage or refinancing an existing mortgage": "MORTGAGE APPLICATION",
    "Problem with a credit report or credit score": "REPORT OR SCORE",
    "Credit monitoring or identity theft protection services": "ID THEFT SERVICES",
    "Problem when making payments": "MAKING PAYMENTS",
    "Opening an account": "OPENING ACCOUNT",
    "Other features, terms, or problems": "OTHER TERMS",
    "Getting a credit card": "GETTING A CARD",
    "Closing your account": "CLOSING ACCOUNT",
    "Problem with fraud alerts or security freezes": "FRAUD ALERT / FREEZE",
}

COMPANY_SHORT = {
    "EQUIFAX, INC.": "EQUIFAX",
    "TRANSUNION INTERMEDIATE HOLDINGS, INC.": "TRANSUNION",
    "Experian Information Solutions Inc.": "EXPERIAN",
    "BANK OF AMERICA, NATIONAL ASSOCIATION": "BANK OF AMERICA",
    "WELLS FARGO & COMPANY": "WELLS FARGO",
    "JPMORGAN CHASE & CO.": "JPMORGAN CHASE",
    "CAPITAL ONE FINANCIAL CORPORATION": "CAPITAL ONE",
    "CITIBANK, N.A.": "CITIBANK",
    "SYNCHRONY FINANCIAL": "SYNCHRONY",
    "Navient Solutions, LLC.": "NAVIENT",
    "Ocwen Financial Corporation": "OCWEN",
    "NATIONSTAR MORTGAGE LLC": "NATIONSTAR / MR. COOPER",
    "Nationstar Mortgage": "NATIONSTAR / MR. COOPER",
    "U.S. BANCORP": "U.S. BANK",
    "DISCOVER BANK": "DISCOVER",
    "AMERICAN EXPRESS COMPANY": "AMERICAN EXPRESS",
    "PNC Bank N.A.": "PNC BANK",
    "TD BANK US HOLDING COMPANY": "TD BANK",
    "Resurgent Capital Services L.P.": "RESURGENT CAPITAL",
    "ENCORE CAPITAL GROUP INC.": "ENCORE CAPITAL",
    "PORTFOLIO RECOVERY ASSOCIATES INC": "PORTFOLIO RECOVERY",
    "Portfolio Recovery Associates, LLC": "PORTFOLIO RECOVERY",
    "NAVY FEDERAL CREDIT UNION": "NAVY FEDERAL",
    "Bread Financial Holdings, Inc.": "BREAD FINANCIAL",
    "CBC COMPANIES, INC.": "CBC COMPANIES",
    "CL HOLDINGS LLC": "CL HOLDINGS",
    "Paypal Holdings, Inc": "PAYPAL",
    "Block, Inc.": "BLOCK (CASH APP)",
    "ALLY FINANCIAL INC.": "ALLY",
    "Santander Consumer USA Holdings Inc.": "SANTANDER CONSUMER",
    "AES/PHEAA": "AES / PHEAA",
    "Shellpoint Partners, LLC": "SHELLPOINT",
    "SELECT PORTFOLIO SERVICING, INC.": "SELECT PORTFOLIO",
    "Freedom Mortgage Company": "FREEDOM MORTGAGE",
    "Nelnet, Inc.": "NELNET",
    "GOLDMAN SACHS BANK USA": "GOLDMAN SACHS",
    "BARCLAYS BANK DELAWARE": "BARCLAYS",
    "CITIZENS FINANCIAL GROUP, INC.": "CITIZENS",
    "TRUIST FINANCIAL CORPORATION": "TRUIST",
    "CCS Financial Services, Inc.": "CCS FINANCIAL",
    "I.C. System, Inc.": "I.C. SYSTEM",
    "Mohela": "MOHELA",
    "MOHELA": "MOHELA",
    "Coinbase, Inc.": "COINBASE",
    "Comerica": "COMERICA",
}

PRODUCT_SHORT = {
    "Credit reporting or other personal consumer reports": "CREDIT REPORTING",
    "Credit reporting, credit repair services, or other personal consumer reports": "CREDIT REPORTING",
    "Credit reporting": "CREDIT REPORTING",
    "Debt collection": "DEBT COLLECTION",
    "Mortgage": "MORTGAGE",
    "Credit card or prepaid card": "CREDIT CARD",
    "Credit card": "CREDIT CARD",
    "Checking or savings account": "BANK ACCOUNT",
    "Bank account or service": "BANK ACCOUNT",
    "Student loan": "STUDENT LOAN",
    "Vehicle loan or lease": "VEHICLE LOAN",
    "Consumer Loan": "CONSUMER LOAN",
    "Money transfer, virtual currency, or money service": "MONEY TRANSFER",
    "Money transfers": "MONEY TRANSFER",
    "Payday loan, title loan, or personal loan": "PAYDAY / PERSONAL LOAN",
    "Payday loan, title loan, personal loan, or advance loan": "PAYDAY / PERSONAL LOAN",
    "Payday loan": "PAYDAY / PERSONAL LOAN",
    "Prepaid card": "PREPAID CARD",
    "Debt or credit management": "DEBT MANAGEMENT",
    "Other financial service": "OTHER SERVICE",
    "Virtual currency": "VIRTUAL CURRENCY",
}


def process_cfpb():
    """Stream the CFPB CSV once and aggregate it by month."""
    path = RAW / "cfpb_complaints.csv.zip"
    cols = ["Date received", "Product", "Issue", "Sub-issue", "Company"]
    agg_ci = []   # (month, company, issue) -> n
    agg_pi = []   # (month, product, issue) -> n
    agg_cl = []   # (month, cluster) -> n
    total_rows = 0
    with zipfile.ZipFile(path) as z, z.open("complaints.csv") as f:
        reader = pcsv.open_csv(
            f,
            read_options=pcsv.ReadOptions(block_size=48 << 20),
            convert_options=pcsv.ConvertOptions(
                include_columns=cols,
                column_types={c: pa.string() for c in cols},
            ),
        )
        for batch in reader:
            df = batch.to_pandas()
            total_rows += len(df)
            df["month"] = df["Date received"].str.slice(0, 7)
            df["Issue"] = df["Issue"].map(lambda v: ISSUE_MERGE.get(v, v))
            df["Product"] = df["Product"].map(lambda v: PRODUCT_SHORT.get(v, "OTHER PRODUCT"))
            sub = df["Sub-issue"].fillna("")
            df["cluster"] = sub.where(sub != "", df["Issue"])
            agg_ci.append(df.groupby(["month", "Company", "Issue"], dropna=False).size().rename("n").reset_index())
            agg_pi.append(df.groupby(["month", "Product", "Issue"], dropna=False).size().rename("n").reset_index())
            agg_cl.append(df.groupby(["month", "cluster"], dropna=False).size().rename("n").reset_index())
            if total_rows % 1_000_000 < len(df):
                print(f"  cfpb rows: {total_rows:,}", flush=True)
            if LIMIT and total_rows >= LIMIT:
                break
    ci = pd.concat(agg_ci).groupby(["month", "Company", "Issue"], dropna=False)["n"].sum().reset_index()
    pi = pd.concat(agg_pi).groupby(["month", "Product", "Issue"], dropna=False)["n"].sum().reset_index()
    cl = pd.concat(agg_cl).groupby(["month", "cluster"], dropna=False)["n"].sum().reset_index()
    del agg_ci, agg_pi, agg_cl

    first = "2012-01"
    last_full = max(m for m in ci["month"].unique() if m < CUTOFF_MONTH)
    months = month_range(first, last_full)
    ci = ci[(ci["month"] >= first) & (ci["month"] <= last_full)]
    pi = pi[(pi["month"] >= first) & (pi["month"] <= last_full)]
    cl = cl[(cl["month"] >= first) & (cl["month"] <= last_full)]
    kept_rows = int(ci["n"].sum())

    companies = ci.groupby("Company")["n"].sum().sort_values(ascending=False)
    top_companies = list(companies.index[:N_ROWS])
    issues = ci.groupby("Issue")["n"].sum().sort_values(ascending=False)
    top_issues = list(issues.index[:N_COLS])
    products = pi.groupby("Product")["n"].sum().sort_values(ascending=False)
    top_products = [p for p in products.index if p != "OTHER PRODUCT"]
    clusters = cl.groupby("cluster")["n"].sum().sort_values(ascending=False)
    top_clusters = list(clusters.index[:N_CLUSTERS])

    g_ci = grid(ci, months, top_companies, top_issues, "Company", "Issue")
    g_pi = grid(pi, months, top_products, top_issues, "Product", "Issue")

    # Side strip: the top clusters per month, as [cluster index, count] pairs.
    cidx = {c: i for i, c in enumerate(top_clusters)}
    per_month = defaultdict(list)
    for m, c, n in cl[["month", "cluster", "n"]].itertuples(index=False):
        if c in cidx:
            per_month[m].append((int(n), cidx[c]))
    month_clusters = []
    for m in months:
        top = sorted(per_month.get(m, []), reverse=True)[:TOP_PER_MONTH]
        month_clusters.append([[i, n] for n, i in top])
    month_totals = ci.groupby("month")["n"].sum().reindex(months).fillna(0).astype(int).tolist()

    out = {
        "source": "CFPB Consumer Complaint Database",
        "sourceUrl": "https://www.consumerfinance.gov/data-research/consumer-complaints/",
        "unit": "complaints received",
        "months": months,
        "rowSets": {
            "COMPANY": {
                "labels": [COMPANY_SHORT.get(c, c.upper()[:24]) for c in top_companies] + ["ALL OTHER COMPANIES"],
                "full": top_companies + ["OTHER"],
                "cells": g_ci.ravel().tolist(),
            },
            "PRODUCT": {
                "labels": top_products + ["OTHER PRODUCT"],
                "full": top_products + ["OTHER"],
                "cells": g_pi.ravel().tolist(),
            },
        },
        "cols": [ISSUE_SHORT.get(i, i.upper()[:22]) for i in top_issues] + ["ALL OTHER ISSUES"],
        "colsFull": top_issues + ["OTHER"],
        "monthTotals": month_totals,
        "clusterNames": [c.upper() for c in top_clusters],
        "clusterNote": "Sub-issue chosen by the consumer. When the sub-issue is empty the issue label is used.",
        "monthClusters": month_clusters,
        "events": [
            ["2013-07", "CFPB starts to take debt collection complaints"],
            ["2016-09", "Wells Fargo fake-accounts settlement"],
            ["2017-09", "Equifax data breach disclosed"],
            ["2020-03", "COVID-19 payment forbearance begins"],
            ["2022-01", "Credit-repair template flood begins"],
            ["2023-07", "CFPB sues credit bureaus' data furnishers"],
        ],
        "stats": {"rawRows": total_rows, "keptRows": kept_rows, "cutoffMonth": last_full},
    }
    with open(OUT / "cfpb.json", "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"cfpb: raw rows {total_rows:,}, kept {kept_rows:,}, months {months[0]}..{months[-1]}, "
          f"size {(OUT / 'cfpb.json').stat().st_size / 1e6:.2f} MB")
    return out


# --------------------------------------------------------------- NHTSA ----

# The narrative lexicon. Each entry is a label and a regular expression that
# runs on the lower-case complaint text. One complaint counts once per label.
LEXICON = [
    ("FIRE", r"\bfire\b|\bflames?\b|caught on fire|burn(ed|ing) up"),
    ("SMOKE", r"\bsmok(e|ing)\b"),
    ("STALL", r"\bstall(s|ed|ing)?\b"),
    ("BRAKE FAILURE", r"brakes? (failed|fail|went out|did not work|didn't work|do not work)|no brakes|brake failure|loss of brak"),
    ("AIRBAG", r"\bair ?bags?\b"),
    ("AIRBAG DID NOT DEPLOY", r"air ?bags? (did not|didn't|never|failed to) deploy"),
    ("STEERING", r"\bsteering\b"),
    ("UNINTENDED ACCELERATION", r"unintended acceleration|sudden acceleration|accelerat(ed|es|ing) on its own|accelerat(ed|es|ing) by itself|surge(d|s)? forward"),
    ("LOSS OF POWER", r"loss of power|lost (all )?power|lose(s)? power|no power"),
    ("SHUT OFF", r"shut(s)? (off|down)|turn(ed|s)? off (while|when) driving|died while driving"),
    ("CHECK ENGINE LIGHT", r"check engine"),
    ("WARNING LIGHT", r"warning light|light(s)? (came|come) on|dash(board)? light"),
    ("TRANSMISSION", r"\btransmission\b"),
    ("FUEL LEAK", r"fuel leak|gas leak|leak(ing|ed|s)? (gas|fuel)|smell(ed|s)? (of )?(gas|fuel)"),
    ("TIRE BLOWOUT", r"blow ?out|blew out|tread separat"),
    ("CRASH", r"\bcrash(ed|es)?\b|\baccident\b|\bcollision\b"),
    ("INJURY", r"\binjur(y|ies|ed)\b|\bwhiplash\b|\bhospital"),
    ("DEATH", r"\bdeaths?\b|\bfatalit(y|ies)\b|\b(killed|died) (in|when|after|during|as)\b|(person|people|driver|passenger|someone|wife|husband|son|daughter|child|he|she|they) (was |were )?(died|killed)\b"),
    ("RUST", r"\brust(ed|ing)?\b|\bcorro(sion|ded)\b"),
    ("RECALL", r"\brecall(s|ed)?\b"),
    ("DEALER REFUSED", r"dealer(ship)? (refus|would not|won't|will not|said (it|there) (is|was) (nothing|no))"),
    ("ROLLAWAY", r"roll(ed|s|ing)? (away|back|down)|rollaway"),
    ("WINDSHIELD CRACK", r"windshield crack|crack(ed|s)? (in the )?windshield"),
    ("SOFTWARE", r"\bsoftware\b|\bfirmware\b|\bglitch(es|ed|ing)?\b|\bfroze\b|\bfreezes\b|\breboot"),
    ("BACKUP CAMERA", r"back ?up camera|rear ?view camera"),
]

MAKE_SHORT = {"MERCEDES BENZ": "MERCEDES-BENZ", "MERCEDES-BENZ": "MERCEDES-BENZ"}


def process_nhtsa():
    """Stream the NHTSA flat file once and aggregate it by month."""
    path = RAW / "nhtsa_FLAT_CMPL.zip"
    lex = [(label, re.compile(rx)) for label, rx in LEXICON]
    grid_counter = Counter()      # (month, make, component)
    year_counter = Counter()      # (component, make, model year)
    kw_counter = Counter()        # (month, label)
    uniq_month = Counter()        # month -> unique complaints
    seen = set()
    rows = 0
    bad = 0
    with zipfile.ZipFile(path) as z, z.open("FLAT_CMPL.txt") as f:
        for raw in f:
            rows += 1
            parts = raw.decode("latin-1").rstrip("\r\n").split("\t")
            if len(parts) < 21:
                bad += 1
                continue
            ldate = parts[16]
            if len(ldate) != 8 or not ldate.isdigit():
                bad += 1
                continue
            month = ldate[:4] + "-" + ldate[4:6]
            make = parts[3].strip().upper() or "UNKNOWN"
            make = MAKE_SHORT.get(make, make)
            comp = parts[11].split(":")[0].strip().upper() or "UNKNOWN OR OTHER"
            year = parts[5].strip()
            grid_counter[(month, make, comp)] += 1
            if year.isdigit() and 1980 <= int(year) <= TODAY.year + 2:
                year_counter[(comp, make, int(year))] += 1
            odino = parts[1]
            if odino not in seen:
                seen.add(odino)
                uniq_month[month] += 1
                text = parts[19].lower()
                for label, rx in lex:
                    if rx.search(text):
                        kw_counter[(month, label)] += 1
            if rows % 500_000 == 0:
                print(f"  nhtsa rows: {rows:,}", flush=True)
            if LIMIT and rows >= LIMIT:
                break
    del seen

    g = pd.DataFrame([(m, mk, c, n) for (m, mk, c), n in grid_counter.items()],
                     columns=["month", "make", "comp", "n"])
    first = "1995-01"
    last_full = max(m for m in g["month"].unique() if m < CUTOFF_MONTH)
    months = month_range(first, last_full)
    g = g[(g["month"] >= first) & (g["month"] <= last_full)]
    kept_rows = int(g["n"].sum())

    makes = g.groupby("make")["n"].sum().sort_values(ascending=False)
    top_makes = list(makes.index[:N_ROWS])
    comps = g.groupby("comp")["n"].sum().sort_values(ascending=False)
    top_comps = [c for c in comps.index if c != "UNKNOWN OR OTHER"][:N_COLS]
    g_grid = grid(g, months, top_makes, top_comps, "make", "comp")

    # Make x model year, one plane per component plus an ALL plane.
    years = list(range(1990, TODAY.year + 2))
    yi = {y: i for i, y in enumerate(years)}
    mi = {m: i for i, m in enumerate(top_makes)}
    ci = {c: i for i, c in enumerate(top_comps)}
    C, R, Y = len(top_comps) + 2, len(top_makes) + 1, len(years)   # last plane = ALL
    yg = np.zeros((C, R, Y), np.int64)
    for (comp, make, year), n in year_counter.items():
        if year not in yi:
            continue
        r = mi.get(make, R - 1)
        c = ci.get(comp, C - 2)
        yg[c, r, yi[year]] += n
        yg[C - 1, r, yi[year]] += n

    labels = [l for l, _ in LEXICON]
    kw = np.zeros((len(months), len(labels)), np.int64)
    mi2 = {m: i for i, m in enumerate(months)}
    for (m, label), n in kw_counter.items():
        if m in mi2:
            kw[mi2[m], labels.index(label)] = n
    uniq = [int(uniq_month.get(m, 0)) for m in months]

    out = {
        "source": "NHTSA Office of Defects Investigation, vehicle owner complaints",
        "sourceUrl": "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
        "unit": "complaint-component rows",
        "months": months,
        "rowSets": {
            "MAKE": {
                "labels": top_makes + ["ALL OTHER MAKES"],
                "full": top_makes + ["OTHER"],
                "cells": g_grid.ravel().tolist(),
            }
        },
        "cols": [c.replace("FUEL/PROPULSION SYSTEM", "FUEL / PROPULSION") for c in top_comps] + ["ALL OTHER COMPONENTS"],
        "colsFull": top_comps + ["OTHER"],
        "monthTotals": g_grid.sum(axis=(1, 2)).tolist(),
        "uniqueComplaints": uniq,
        "lexicon": [[l, rx] for l, rx in LEXICON],
        "keywords": kw.ravel().tolist(),
        "modelYears": years,
        "yearPlanes": top_comps + ["OTHER", "ALL"],
        "yearGrid": yg.ravel().tolist(),
        "events": [
            ["2000-08", "Firestone tire recall"],
            ["2009-11", "Toyota floor-mat recall, unintended acceleration"],
            ["2014-02", "GM ignition switch recall"],
            ["2014-06", "Takata airbag inflator recalls expand"],
            ["2015-09", "Volkswagen diesel emissions disclosed"],
            ["2021-02", "Hyundai-Kia engine fire recalls"],
            ["2023-12", "Tesla Autopilot recall of 2 million cars"],
        ],
        "stats": {"rawRows": rows, "badRows": bad, "keptRows": kept_rows,
                  "uniqueComplaints": int(sum(uniq)), "cutoffMonth": last_full},
    }
    with open(OUT / "nhtsa.json", "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"nhtsa: raw rows {rows:,}, bad {bad:,}, kept {kept_rows:,}, unique complaints {sum(uniq):,}, "
          f"months {months[0]}..{months[-1]}, size {(OUT / 'nhtsa.json').stat().st_size / 1e6:.2f} MB")
    return out


# ------------------------------------------------------------- preview ----

def write_preview(nhtsa):
    """Draw an 800x500 still of one NHTSA month in the room style."""
    months = nhtsa["months"]
    rs = nhtsa["rowSets"]["MAKE"]
    R = len(rs["labels"])
    C = len(nhtsa["cols"])
    cells = np.array(rs["cells"]).reshape(len(months), R, C)
    # Pick the month with the largest total so the wall is bright.
    mi = int(np.argmax(nhtsa["monthTotals"]))
    plane = cells[mi]
    rowmax = np.maximum(cells.max(axis=(0, 2)), 1)
    acid = (0xE6, 0xFF, 0x00)
    base = (0x1A, 0x1A, 0x1A)
    x0, y0, w, h = 170, 150, 600, 302
    cw, ch = w / C, h / R
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">',
             '<rect width="800" height="500" fill="#2b2b2b"/>',
             '<rect x="0" y="0" width="800" height="70" fill="#111"/>',
             '<text x="16" y="52" font-family="Impact,Haettenschweiler,Arial Black,sans-serif" font-size="44" fill="#e6ff00" letter-spacing="2">THE COMPLAINT WALL</text>',
             f'<text x="784" y="52" text-anchor="end" font-family="monospace" font-size="30" fill="#fff">{months[mi]}</text>']
    # The three brightest cells get the glitch treatment: offset slices.
    flat = (plane / rowmax[:, None]).ravel()
    glitch = set(int(i) for i in np.argsort(flat)[-3:])
    for r in range(R):
        for c in range(C):
            v = (plane[r, c] / rowmax[r]) ** 0.5
            col = tuple(int(base[k] + (acid[k] - base[k]) * v) for k in range(3))
            x, y = x0 + c * cw, y0 + r * ch
            if r * C + c in glitch:
                sh = (ch - 1) / 3
                for k, off in enumerate((-5, 4, -2)):
                    parts.append(f'<rect x="{x + off:.1f}" y="{y + k * sh:.1f}" width="{cw - 1:.1f}" height="{sh - 1:.1f}" fill="{"#fff" if k == 1 else "#e6ff00"}"/>')
                parts.append(f'<rect x="{x + 6:.1f}" y="{y + sh + 1:.1f}" width="{(cw - 1) * 0.6:.1f}" height="2" fill="#000"/>')
            else:
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cw - 1:.1f}" height="{ch - 1:.1f}" fill="rgb({col[0]},{col[1]},{col[2]})"/>')
        parts.append(f'<text x="{x0 - 8}" y="{y0 + r * ch + ch * 0.75:.1f}" text-anchor="end" font-family="Arial Black,Arial,sans-serif" font-weight="900" font-size="9" fill="#fff">{rs["labels"][r][:16]}</text>')
    for c in range(C):
        label = nhtsa["cols"][c][:14]
        parts.append(f'<text transform="translate({x0 + c * cw + cw * 0.62:.1f},{y0 - 4}) rotate(-90)" font-family="Arial Black,Arial,sans-serif" font-weight="900" font-size="7" fill="#fff">{label}</text>')
    parts.append('<rect x="0" y="460" width="800" height="40" fill="#111"/>')
    parts.append('<text x="16" y="486" font-family="monospace" font-size="13" fill="#e6ff00">NHTSA VEHICLE COMPLAINTS. ROWS = MAKE. COLUMNS = COMPONENT. BRIGHT = HIGH RATE.</text>')
    parts.append("</svg>")
    with open(OUT.parent / "preview.svg", "w") as fh:
        fh.write("\n".join(parts))


if __name__ == "__main__":
    which = sys.argv[1:] or ["cfpb", "nhtsa"]
    nh = None
    if "preview" in which:
        with open(OUT / "nhtsa.json") as fh:
            write_preview(json.load(fh))
    if "nhtsa" in which:
        nh = process_nhtsa()
        write_preview(nh)
    if "cfpb" in which:
        process_cfpb()
    total = sum(p.stat().st_size for p in OUT.glob("*.json"))
    print(f"total processed size: {total / 1e6:.2f} MB")
