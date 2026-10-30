"""Parse the OMB Historical Tables (FY2027 edition) into one JSON file.

Input:  data/raw/treasury-machine/hist*.xlsx  (downloaded by fetch.py)
Output: data/raw/treasury-machine/omb.json

All money values are millions of current dollars, by fiscal year. The transition
quarter (TQ, July to September 1976) is skipped. Estimate years are skipped.
"""
import json, re, sys
from pathlib import Path
import openpyxl

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "treasury-machine"
LAST = 2025  # last actual fiscal year in the FY2027 edition


def rows(name):
    wb = openpyxl.load_workbook(RAW / name, data_only=True)
    ws = wb[wb.sheetnames[0]]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def num(v):
    if v is None or isinstance(v, str):
        return 0.0
    return float(v)


def year_of(label):
    m = re.match(r"^(\d{4})$", str(label).strip())
    return int(m.group(1)) if m else None


def by_year_table(name, cols):
    """Tables with one row per fiscal year. cols: {key: column index}."""
    out = {}
    for r in rows(name):
        y = year_of(r[0])
        if y and y <= LAST:
            out[y] = {k: num(r[i]) for k, i in cols.items()}
    return out


def by_label_table(name, wanted, stop=None):
    """Tables with categories in rows and years in columns.
    wanted: {key: (label, nth occurrence)}. Returns {year: {key: value}}."""
    R = rows(name)
    header = None
    for r in R:
        if any(year_of(c) for c in r[1:4]):
            header = r
            break
    years = {i: year_of(c) for i, c in enumerate(header) if year_of(c)}
    seen = {}
    data = {y: {} for y in years.values() if y <= LAST}
    for r in R:
        lab = (r[0] or "").strip() if isinstance(r[0], str) else None
        if lab is None:
            continue
        if stop and lab.startswith(stop):
            break
        seen[lab] = seen.get(lab, 0) + 1
        for k, (want, nth) in wanted.items():
            if lab == want and seen[lab] == nth:
                for i, y in years.items():
                    if y <= LAST:
                        data[y][k] = num(r[i])
    missing = [k for k in wanted if k not in data[max(data)]]
    if missing:
        print("WARNING", name, "missing labels:", missing, file=sys.stderr)
    return data


def by_code_table(name):
    """Table 3.2: every row that starts with a three-digit subfunction code.
    Returns {year: {code: value}}. A subtotal row overwrites its header row."""
    R = rows(name)
    header = next(r for r in R if any(year_of(c) for c in r[1:4]))
    years = {i: year_of(c) for i, c in enumerate(header) if year_of(c)}
    data = {y: {} for y in years.values() if y <= LAST}
    for r in R:
        m = re.match(r"^(\d{3}) ", r[0].strip()) if isinstance(r[0], str) else None
        if m:
            for i, y in years.items():
                if y <= LAST:
                    data[y][m.group(1)] = num(r[i])
    return data


out = {}

# 1.1 totals 1901-2025
out["totals"] = by_year_table("hist01z1.xlsx", {"receipts": 1, "outlays": 2})

# 2.1 receipts by source 1934-
out["receipts"] = by_year_table("hist02z1.xlsx", {
    "individual": 1, "corporate": 2, "payroll": 3, "excise": 6, "other": 7, "total": 8})

# 2.5 composition of other receipts 1940-
out["other_receipts"] = by_year_table("hist02z5.xlsx", {
    "total": 1, "estate_gift": 2, "customs": 3, "misc": 4, "fed_deposits": 5, "misc_other": 6})

# 2.4 composition of payroll and excise 1940-  (rows x years)
out["payroll_excise"] = by_label_table("hist02z4.xlsx", {
    "oasi_federal": ("Federal funds", 1), "oasi_trust": ("Trust funds (Off-Budget)", 1),
    "di": ("Disability insurance (Off-Budget)", 1), "hi": ("Hospital insurance", 1),
    "rr_federal": ("Federal funds", 2), "rr_trust": ("Trust funds", 1), "rr_equiv": ("Railroad social security equivalent account", 1),
    "ui_federal": ("Federal funds", 3), "ui_trust": ("Trust funds", 2),
    "fed_employee": ("Federal employees retirement - employee share", 1), "nonfed_employee": ("Non-Federal employees retirement", 1),
    "payroll_total": ("Total, Social Insurance and Retirement Receipts (1)", 1),
    "alcohol": ("Alcohol", 1), "tobacco": ("Tobacco", 1), "windfall": ("Crude oil windfall profit", 1), "telephone": ("Telephone", 1),
    "fuels_federal": ("Transportation fuels", 1), "excise_fed_other": ("Other", 1),
    "excise_fed_total": ("Total", 1),
    "highway_trust": ("Transportation", 1), "airport_trust": ("Airport and airway", 1),
    "excise_trust_total": ("Total", 2), "excise_total": ("Total, Excise Taxes", 1)})

# 3.1 outlays by function 1940-  (rows x years), only the dollar block
out["functions"] = by_label_table("hist03z1.xlsx", {
    "defense": ("National Defense", 1), "education": ("Education, Training, Employment, and Social Services", 1),
    "health": ("Health", 1), "medicare": ("Medicare", 1), "income_security": ("Income Security", 1),
    "social_security": ("Social Security", 1), "veterans": ("Veterans Benefits and Services", 1),
    "energy": ("Energy", 1), "natural_resources": ("Natural Resources and Environment", 1),
    "commerce": ("Commerce and Housing Credit", 1), "transportation": ("Transportation", 1),
    "community": ("Community and Regional Development", 1), "net_interest": ("Net interest", 1),
    "international": ("International Affairs", 1), "science": ("General Science, Space, and Technology", 1),
    "agriculture": ("Agriculture", 1), "justice": ("Administration of Justice", 1),
    "general_government": ("General Government", 1), "allowances": ("Allowances", 1),
    "offsetting": ("Undistributed offsetting receipts", 1), "total": ("Total, Federal outlays", 1)},
    stop="As percentages of outlays")

# 3.2 subfunctions 1962-
out["subfunctions"] = by_label_table("hist03z2.xlsx", {
    "mil_personnel": ("Military Personnel", 1), "mil_om": ("Operation and Maintenance", 1), "mil_procurement": ("Procurement", 1),
    "mil_rdte": ("Research, Development, Test, and Evaluation", 1), "mil_construction": ("Military Construction", 1),
    "mil_housing": ("Family Housing", 1), "mil_other": ("Other", 1), "atomic": ("053 Atomic energy defense activities", 1),
    "defense_related": ("054 Defense-related activities", 1),
    "health_services": ("551 Health care services", 1), "health_research": ("552 Health research and training", 1),
    "health_safety": ("554 Consumer and occupational health and safety", 1), "medicare": ("571 Medicare", 1),
    "is_general_retirement": ("601 General retirement and disability insurance (excluding social security)", 1),
    "is_federal_retirement": ("602 Federal employee retirement and disability", 1),
    "is_unemployment": ("603 Unemployment compensation", 1), "is_housing": ("604 Housing assistance", 1),
    "is_food": ("605 Food and nutrition assistance", 1), "is_other": ("609 Other income security", 1),
    "vet_income": ("701 Income security for veterans", 1), "vet_education": ("702 Veterans education, training, and rehabilitation", 1),
    "vet_medical": ("703 Hospital and medical care for veterans", 1), "vet_housing": ("704 Veterans housing", 1),
    "vet_other": ("705 Other veterans benefits and services", 1),
    "interest_gross": ("901 Interest on Treasury debt securities (gross)", 1)})

# 3.2 again: all subfunctions by code, for the third layer under "Everything else"
out["subfunction_codes"] = by_code_table("hist03z2.xlsx")

# 11.3 payments for individuals by major program 1940-  (the year column is the "Total" column)
out["programs"] = by_label_table("hist11z3.xlsx", {
    "oasi": ("Social security: old age and survivors insurance", 1), "di": ("Social security: disability insurance", 1),
    "military_retirement": ("Military retirement", 1), "civil_retirement": ("Civil service retirement", 1),
    "fed_retirement_other": ("Other", 1), "vet_compensation": ("Veterans service-connected compensation", 1),
    "medicare_hi": ("Medicare: hospital insurance", 1), "medicare_smi": ("Medicare: supplementary medical insurance", 1),
    "chip": ("Children's health insurance", 1), "medicaid": ("Medicaid", 1),
    "premium_credit": ("Refundable Premium Tax Credit and Cost Sharing Reductions", 1),
    "snap": ("SNAP (formerly Food stamps)(including Puerto Rico)", 1), "child_nutrition": ("Child nutrition and special milk programs", 1),
    "wic": ("Supplemental feeding programs (WIC and CSFP)", 1), "commodities": ("Commodity donations and other", 1),
    "ssi": ("Supplemental security income program", 1), "tanf": ("Family support payments to States and TANF", 1),
    "liheap": ("Low income home energy assistance", 1), "eitc": ("Earned income tax credit", 1),
    "child_care": ("Child care assistance for low and middle income families", 1),
    "vet_pensions": ("Veterans non-service connected pensions", 1), "foster_care": ("Payments to States--Foster Care/Adoption Assist.", 1),
    "child_credit": ("Child Tax Credit and Child and Dependent Care Tax Credit", 1),
    "covid_payments": ("U.S. Coronavirus payments and credits", 1), "vet_insurance": ("Veterans insurance and burial benefits", 1)})

# 7.1 debt 1940-
out["debt"] = by_year_table("hist07z1.xlsx", {"gross": 1, "gov_accounts": 2, "public": 3, "fed_reserve": 4})

# 10.1 GDP 1940-
out["gdp"] = by_year_table("hist10z1.xlsx", {"gdp_billions": 1, "price_index": 2})

json.dump(out, open(RAW / "omb.json", "w"))
for k, v in out.items():
    ys = sorted(v)
    print(f"{k:16s} {ys[0]}-{ys[-1]}  {len(ys)} years  sample {ys[-1]}: {dict(list(v[ys[-1]].items())[:4])}")
