"""Assemble the Treasury Machine data set: receipts and outlays by category and
program, GDP, population and debt, fiscal years 1789 to 2025.

Inputs (data/raw/treasury-machine/):
  omb.json              parse_omb.py output (1934/1940 onward)
  tab/table40.json      HSUS Y352-357 receipts by source 1789-1939 (OCR)
  tab/table48.json      HSUS Y457-465 outlays 1846-1935 (OCR)
  tab/table49.json      HSUS Y457-465 outlays 1789-1845 (OCR)
  tab/table41.json      HSUS Y358-372 internal revenue 1916-1937 (OCR)
  tab/table42.json      HSUS Y358-373 internal revenue 1863-1915 (OCR)
  nber_m15002a.db       NBER monthly income tax receipts 1910-1953
  mw_gdp.csv            MeasuringWorth nominal GDP and population 1790-2025
  debt_outstanding.json Treasury historical debt outstanding 1790-2026

Output: rooms/treasury-machine/data/ledger.json. All money in millions of
current dollars by fiscal year.
"""
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "treasury-machine"
OUT = ROOT / "rooms" / "treasury-machine" / "data"
Y0, Y1 = 1789, 2025
YEARS = list(range(Y0, Y1 + 1))
N = len(YEARS)
idx = {y: i for i, y in enumerate(YEARS)}

omb = json.load(open(RAW / "omb.json"))
omb = {k: {int(y): v for y, v in d.items()} for k, d in omb.items()}


def table(page):
    rows = {}
    for panel in json.load(open(RAW / "tab" / f"table{page}.json")):
        for r in panel["rows"]:
            if "period" in r:
                a, b = r["period"]
                for y in range(a, b + 1):
                    rows[y] = {k: (v / (b - a + 1) if isinstance(v, (int, float)) else v) for k, v in r.items() if not k.startswith("_")}
            else:
                rows[r["year"]] = {k: v for k, v in r.items() if not k.startswith("_")}
    return rows


T40, T48, T49, T41, T42 = table(40), table(48), table(49), table(41), table(42)
HS_OUT = {**T49, **T48}      # 1789-1935
K = 1 / 1000.0               # thousands -> millions


def series():
    return [0.0] * N


def v(d, y, k):
    x = d.get(y, {}).get(k)
    return 0.0 if x is None else float(x)


# ---------------- NBER income tax, monthly millions -> fiscal years
def nber_fiscal(name):
    lines = [l.strip().strip('"') for l in open(RAW / name) if not l.startswith('"c')]
    start = lines[1]; vals = lines[3:]
    y, m = int(start.split(".")[0]), int(start.split(".")[1])
    out = {}
    for val in vals:
        if val != "NA":
            fy = y + 1 if m >= 7 else y
            out[fy] = out.get(fy, 0.0) + float(val)
        m += 1
        if m > 12:
            m = 1; y += 1
    return out


income_fy = nber_fiscal("nber_m15002a.db")   # FY1911-1953, millions

# Civil War income tax (fiscal years, dollars), Annual Reports of the Commissioner of Internal Revenue
CIVIL_WAR_INCOME = {1863: 2.742, 1864: 20.295, 1865: 32.050, 1866: 72.982, 1867: 66.014, 1868: 41.456,
                    1869: 34.792, 1870: 37.776, 1871: 19.163, 1872: 14.437, 1873: 5.062}
# Individual share of income and profits taxes in the years HSUS marks NA (Treasury annual reports)
INDIV_SHARE_FIX = {1914: 28.3 / (28.3 + 43.1), 1915: 41.0 / (41.0 + 39.2)}

# ---------------- receipts
R = {k: series() for k in ["individual", "corporate", "payroll", "excise", "customs", "other"]}
RS = {  # sub-programs
    "individual": {},
    "payroll": {k: series() for k in ["Social Security (OASI)", "Disability insurance", "Medicare hospital insurance", "Railroad retirement", "Unemployment insurance", "Federal employee retirement"]},
    "corporate": {},
    "excise": {k: series() for k in ["Alcohol", "Tobacco", "Motor fuel and highway", "Airport and airway", "Telephone", "Crude oil windfall profit", "Other excise"]},
    "customs": {},
    "other": {k: series() for k in ["Public land sales", "Estate and gift taxes", "Federal Reserve deposits", "Fees, fines, interest, other"]},
}
basis_receipts = [""] * N

for y in YEARS:
    i = idx[y]
    if y >= 1934 and y in omb["receipts"]:
        o = omb["receipts"][y]
        R["individual"][i] = o["individual"]; R["corporate"][i] = o["corporate"]; R["payroll"][i] = o["payroll"]; R["excise"][i] = o["excise"]
        if y in omb["other_receipts"]:
            p = omb["other_receipts"][y]
            R["customs"][i] = p["customs"]; R["other"][i] = o["other"] - p["customs"]
            RS["other"]["Estate and gift taxes"][i] = p["estate_gift"]; RS["other"]["Federal Reserve deposits"][i] = p["fed_deposits"]
            RS["other"]["Fees, fines, interest, other"][i] = R["other"][i] - p["estate_gift"] - p["fed_deposits"]
        else:  # 1934-1939: customs from HSUS, estate and gift from IRS collections
            cu = v(T40, y, "customs") * K
            R["customs"][i] = cu; R["other"][i] = o["other"] - cu
            eg = v(T41, y, "estate") * K
            RS["other"]["Estate and gift taxes"][i] = eg; RS["other"]["Fees, fines, interest, other"][i] = R["other"][i] - eg
        basis_receipts[i] = "OMB 2.1"
        if y in omb["payroll_excise"]:
            q = omb["payroll_excise"][y]
            s = RS["payroll"]
            s["Social Security (OASI)"][i] = q["oasi_federal"] + q["oasi_trust"]; s["Disability insurance"][i] = q["di"]
            s["Medicare hospital insurance"][i] = q["hi"]; s["Railroad retirement"][i] = q["rr_federal"] + q["rr_trust"] + q["rr_equiv"]
            s["Unemployment insurance"][i] = q["ui_federal"] + q["ui_trust"]; s["Federal employee retirement"][i] = q["fed_employee"] + q["nonfed_employee"]
            e = RS["excise"]
            e["Alcohol"][i] = q["alcohol"]; e["Tobacco"][i] = q["tobacco"]; e["Motor fuel and highway"][i] = q["fuels_federal"] + q["highway_trust"]
            e["Airport and airway"][i] = q["airport_trust"]; e["Telephone"][i] = q["telephone"]; e["Crude oil windfall profit"][i] = q["windfall"]
            e["Other excise"][i] = max(0.0, o["excise"] - sum(e[k][i] for k in e if k != "Other excise"))
        else:  # 1934-1939 excise composition from IRS collections
            e = RS["excise"]
            e["Alcohol"][i] = v(T41, y, "alcohol") * K; e["Tobacco"][i] = v(T41, y, "tobacco") * K; e["Motor fuel and highway"][i] = v(T41, y, "gasoline") * K
            e["Other excise"][i] = max(0.0, o["excise"] - e["Alcohol"][i] - e["Tobacco"][i] - e["Motor fuel and highway"][i])
    else:
        h = T40.get(y, {})
        customs = v(T40, y, "customs") * K; internal = v(T40, y, "internal") * K
        other_tot = v(T40, y, "other") * K; land = v(T40, y, "land") * K
        # income taxes inside internal revenue
        ind = v(T41, y, "individual") * K if y >= 1916 else 0.0
        corp = v(T41, y, "corporate") * K if y >= 1916 else 0.0
        if y in CIVIL_WAR_INCOME:
            ind = CIVIL_WAR_INCOME[y]
        elif 1910 <= y <= 1913:
            corp = income_fy.get(y, 0.0)
        elif y in (1914, 1915):
            tot = income_fy.get(y, 0.0); ind = tot * INDIV_SHARE_FIX[y]; corp = tot - ind
        elif 1918 <= y <= 1925:
            tot = income_fy.get(y, 0.0)
            s17 = 180.108 / (180.108 + 207.274); s26 = 879.124 / (879.124 + 1094.980)
            share = s17 + (s26 - s17) * (y - 1917) / 9
            ind = tot * share; corp = tot - ind
        estate = v(T42, y, "estate") * K if y < 1916 else v(T41, y, "estate") * K
        # refunds (1913 on) are netted against internal revenue in the budget total
        refunds = v(T40, y, "refunds") * K
        if internal > 0 and refunds:
            scale = (internal + refunds) / internal
            internal *= scale; ind *= scale; corp *= scale; estate *= scale
        excise = max(0.0, internal - ind - corp - estate)
        R["individual"][i] = ind; R["corporate"][i] = corp; R["excise"][i] = excise; R["customs"][i] = customs
        R["payroll"][i] = v(T41, y, "employment") * K if y >= 1936 else 0.0
        R["other"][i] = other_tot + estate
        RS["other"]["Public land sales"][i] = land; RS["other"]["Estate and gift taxes"][i] = estate
        RS["other"]["Fees, fines, interest, other"][i] = max(0.0, other_tot - land)
        e = RS["excise"]
        src = T42 if y < 1916 else T41
        e["Alcohol"][i] = v(src, y, "alcohol") * K; e["Tobacco"][i] = v(src, y, "tobacco") * K
        e["Motor fuel and highway"][i] = v(T41, y, "gasoline") * K if y >= 1916 else 0.0
        e["Other excise"][i] = max(0.0, excise - e["Alcohol"][i] - e["Tobacco"][i] - e["Motor fuel and highway"][i])
        basis_receipts[i] = "HSUS Y352-357"

# ---------------- outlays
O = {k: series() for k in ["defense", "social_security", "health", "income_security", "interest", "veterans", "other"]}
OS = {
    "defense": {k: series() for k in ["War Department (Army)", "Navy Department", "Military personnel", "Operation and maintenance", "Procurement", "Research and development", "Construction, housing, other", "Atomic energy and defense-related"]},
    "social_security": {k: series() for k in ["Old-age and survivors insurance", "Disability insurance"]},
    "health": {k: series() for k in ["Medicare", "Medicaid and health care services", "Health research and training", "Health and safety regulation", "Health (no breakdown)"]},
    "income_security": {k: series() for k in ["Unemployment compensation", "Food and nutrition", "Housing assistance", "Federal employee retirement", "General retirement and disability", "Other income security"]},
    "interest": {},
    "veterans": {k: series() for k in ["Veterans income security", "Veterans medical care", "Veterans education (GI Bill)", "Veterans housing and other"]},
    "other": {k: series() for k in ["Education, training, social services", "Transportation", "International affairs", "Science, space, technology", "Agriculture", "Natural resources, environment", "Energy", "Commerce and housing credit", "Community and regional development", "Administration of justice", "General government"]},
}
basis_outlays = [""] * N
for y in YEARS:
    i = idx[y]
    if y >= 1940 and y in omb["functions"]:
        f = omb["functions"][y]
        O["defense"][i] = f["defense"]; O["social_security"][i] = f["social_security"]; O["health"][i] = f["health"] + f["medicare"]
        O["income_security"][i] = f["income_security"]; O["interest"][i] = f["net_interest"]; O["veterans"][i] = f["veterans"]
        named = O["defense"][i] + O["social_security"][i] + O["health"][i] + O["income_security"][i] + O["interest"][i] + O["veterans"][i]
        O["other"][i] = f["total"] - named
        basis_outlays[i] = "OMB 3.1"
        for key, name in [("education", "Education, training, social services"), ("transportation", "Transportation"), ("international", "International affairs"),
                          ("science", "Science, space, technology"), ("agriculture", "Agriculture"), ("natural_resources", "Natural resources, environment"),
                          ("energy", "Energy"), ("commerce", "Commerce and housing credit"), ("community", "Community and regional development"),
                          ("justice", "Administration of justice"), ("general_government", "General government")]:
            OS["other"][name][i] = max(0.0, f[key])
        if y in omb["subfunctions"]:
            s = omb["subfunctions"][y]
            d = OS["defense"]
            d["Military personnel"][i] = s["mil_personnel"]; d["Operation and maintenance"][i] = s["mil_om"]; d["Procurement"][i] = s["mil_procurement"]
            d["Research and development"][i] = s["mil_rdte"]; d["Construction, housing, other"][i] = s["mil_construction"] + s["mil_housing"] + s["mil_other"]
            d["Atomic energy and defense-related"][i] = s["atomic"] + s["defense_related"]
            h = OS["health"]
            h["Medicare"][i] = f["medicare"]; h["Medicaid and health care services"][i] = s["health_services"]; h["Health research and training"][i] = s["health_research"]
            h["Health and safety regulation"][i] = s["health_safety"]
            q = OS["income_security"]
            q["Unemployment compensation"][i] = s["is_unemployment"]; q["Food and nutrition"][i] = s["is_food"]; q["Housing assistance"][i] = s["is_housing"]
            q["Federal employee retirement"][i] = s["is_federal_retirement"]; q["General retirement and disability"][i] = s["is_general_retirement"]; q["Other income security"][i] = s["is_other"]
            w = OS["veterans"]
            w["Veterans income security"][i] = s["vet_income"]; w["Veterans medical care"][i] = s["vet_medical"]; w["Veterans education (GI Bill)"][i] = s["vet_education"]
            w["Veterans housing and other"][i] = s["vet_housing"] + s["vet_other"]
        else:
            OS["health"]["Medicare"][i] = f["medicare"]; OS["health"]["Health (no breakdown)"][i] = f["health"]
    else:
        h = HS_OUT.get(y, {})
        army = v(HS_OUT, y, "army") * K; navy = v(HS_OUT, y, "navy") * K
        O["defense"][i] = army + navy; O["interest"][i] = v(HS_OUT, y, "interest") * K; O["veterans"][i] = v(HS_OUT, y, "veterans") * K
        O["other"][i] = max(0.0, v(HS_OUT, y, "other") * K - O["veterans"][i])
        OS["defense"]["War Department (Army)"][i] = army; OS["defense"]["Navy Department"][i] = navy
        basis_outlays[i] = "HSUS Y457-465"

# ---------------- third layer: details under programs
# A detail gets its share of the program outlay. Shares come from Table 11.3 (payments
# for individuals) or Table 3.2 (subfunctions). Negative source values are dropped.
OD = {k: {} for k in O}   # {function: {program: {detail: series}}}


def split(func, prog, i, raw, total=None):
    total = OS[func][prog][i] if total is None else total
    pos = {n: max(0.0, x) for n, x in raw.items()}
    s = sum(pos.values())
    if total <= 0 or s <= 0:
        return
    d = OD[func].setdefault(prog, {})
    for n, x in pos.items():
        d.setdefault(n, series())[i] = total * x / s


OTHER_DETAILS = {
    "Education, training, social services": [("501", "Elementary, secondary, vocational"), ("502", "Higher education"), ("503", "Research and general aids"), ("504", "Training and employment"), ("505", "Other labor services"), ("506", "Social services")],
    "Transportation": [("401", "Ground: highways, transit, rail"), ("402", "Air"), ("403", "Water"), ("407", "Other transportation")],
    "International affairs": [("151", "Development and humanitarian aid"), ("152", "Security assistance"), ("153", "Conduct of foreign affairs"), ("154", "Foreign information and exchange"), ("155", "International financial programs")],
    "Science, space, technology": [("251", "General science and basic research"), ("252", "Space flight and research")],
    "Agriculture": [("351", "Farm income stabilization"), ("352", "Agricultural research and services")],
    "Natural resources, environment": [("301", "Water resources"), ("302", "Conservation and land management"), ("303", "Recreational resources"), ("304", "Pollution control"), ("306", "Other natural resources")],
    "Energy": [("271", "Energy supply"), ("272", "Energy conservation"), ("274", "Emergency energy preparedness"), ("276", "Energy information and regulation")],
    "Commerce and housing credit": [("371", "Mortgage credit"), ("372", "Postal Service"), ("373", "Deposit insurance"), ("376", "Other advancement of commerce")],
    "Community and regional development": [("451", "Community development"), ("452", "Area and regional development"), ("453", "Disaster relief and insurance")],
    "Administration of justice": [("751", "Federal law enforcement"), ("752", "Courts and litigation"), ("753", "Federal prisons"), ("754", "Criminal justice assistance")],
    "General government": [("801", "Legislative branch"), ("802", "Executive direction"), ("803", "Central fiscal operations (IRS)"), ("804", "Property and records"), ("805", "Central personnel management"), ("806", "General purpose fiscal assistance"), ("808", "Other general government")],
}

for y in YEARS:
    i = idx[y]
    p = omb["programs"].get(y) if y >= 1940 else None
    if p:
        ss = O["social_security"][i]; tot = p["oasi"] + p["di"]
        if ss > 0 and tot > 0:
            OS["social_security"]["Old-age and survivors insurance"][i] = ss * p["oasi"] / tot
            OS["social_security"]["Disability insurance"][i] = ss * p["di"] / tot
    s = omb["subfunctions"].get(y) if y >= 1962 else None
    c = omb["subfunction_codes"].get(y) if y >= 1962 else None
    if not (s and c and p):
        continue
    split("defense", "Construction, housing, other", i, {"Military construction": s["mil_construction"], "Family housing": s["mil_housing"], "Other DoD": s["mil_other"]})
    split("defense", "Atomic energy and defense-related", i, {"DOE nuclear weapons and cleanup": s["atomic"], "Defense-related activities": s["defense_related"]})
    split("health", "Medicare", i, {"Part A: hospital insurance": p["medicare_hi"], "Parts B and D: doctors, drugs": p["medicare_smi"]})
    named = p["medicaid"] + p["premium_credit"] + p["chip"]
    split("health", "Medicaid and health care services", i, {"Medicaid": p["medicaid"], "ACA premium tax credits": p["premium_credit"], "Children's health insurance": p["chip"],
                                                            "Other health care services": s["health_services"] - named})
    split("income_security", "Federal employee retirement", i, {"Civil service retirement": p["civil_retirement"], "Military retirement": p["military_retirement"], "Other federal retirement": p["fed_retirement_other"]})
    split("income_security", "Food and nutrition", i, {"SNAP (food stamps)": p["snap"], "School meals and child nutrition": p["child_nutrition"], "WIC and supplemental feeding": p["wic"], "Commodities and other": p["commodities"]})
    named = ["ssi", "eitc", "child_credit", "tanf", "foster_care", "child_care", "liheap", "covid_payments"]
    split("income_security", "Other income security", i, {"Supplemental Security Income": p["ssi"], "Earned income tax credit": p["eitc"], "Child tax credits": p["child_credit"],
                                                          "TANF and family support": p["tanf"], "Foster care and adoption": p["foster_care"], "Child care assistance": p["child_care"],
                                                          "Home energy aid (LIHEAP)": p["liheap"], "Pandemic payments and credits": p["covid_payments"],
                                                          "Other programs": s["is_other"] - sum(p[k] for k in named)})
    split("veterans", "Veterans income security", i, {"Disability compensation": p["vet_compensation"], "Pensions": p["vet_pensions"], "Insurance and burial": p["vet_insurance"]})
    for prog, codes in OTHER_DETAILS.items():
        split("other", prog, i, {name: c.get(code, 0.0) for code, name in codes})

# ---------------- GDP, population, debt
gdp = series(); pop = series()
mw = {}
for row in csv.reader(open(RAW / "mw_gdp.csv")):
    if row and row[0].isdigit():
        mw[int(row[0])] = (float(row[1].replace(",", "")), float(row[4].replace(",", "")))
for y in YEARS:
    i = idx[y]
    yy = max(1790, y)
    pop[i] = mw[yy][1] / 1e6
    gdp[i] = omb["gdp"][y]["gdp_billions"] * 1000 if y >= 1940 and y in omb["gdp"] else mw[yy][0]
gdp_basis = ["OMB 10.1 fiscal year" if y >= 1940 else "MeasuringWorth calendar year" for y in YEARS]

debt_gross = series(); debt_public = series(); debt_accounts = series()
tr = {int(d["record_fiscal_year"]): float(d["debt_outstanding_amt"]) / 1e6 for d in json.load(open(RAW / "debt_outstanding.json"))["data"]}
for y in YEARS:
    i = idx[y]
    if y >= 1940 and y in omb["debt"]:
        d = omb["debt"][y]; debt_gross[i] = d["gross"]; debt_public[i] = d["public"]; debt_accounts[i] = d["gov_accounts"]
    else:
        g = tr.get(max(1790, y), 0.0); debt_gross[i] = g; debt_public[i] = g; debt_accounts[i] = 0.0

# ---------------- totals and checks
rec_total = [sum(R[k][i] for k in R) for i in range(N)]
out_total = [sum(O[k][i] for k in O) for i in range(N)]
for y in (1800, 1865, 1901, 1920, 1933, 1934, 1939, 1940, 1945, 2000, 2025):
    i = idx[y]
    ref = omb["totals"].get(y)
    print(f"{y}: receipts {rec_total[i]:,.0f}  outlays {out_total[i]:,.0f}  GDP {gdp[i]:,.0f}  rec {100*rec_total[i]/gdp[i]:.1f}%  out {100*out_total[i]/gdp[i]:.1f}%  debt {100*debt_public[i]/gdp[i]:.0f}%"
          + (f"  | OMB 1.1 rec {ref['receipts']:,.0f} out {ref['outlays']:,.0f}" if ref else ""))

OUT.mkdir(parents=True, exist_ok=True)
rnd = lambda a: [round(x, 3) for x in a]
data = {
    "years": YEARS, "units": "millions of current dollars, fiscal years",
    "gdp": rnd(gdp), "population_millions": rnd(pop), "gdp_basis": gdp_basis,
    "receipts": {k: {"total": rnd(R[k]), "subs": {n: rnd(s) for n, s in RS[k].items()}} for k in R},
    "outlays": {k: {"total": rnd(O[k]), "subs": {n: rnd(s) for n, s in OS[k].items()},
                    "deep": {pn: {n: rnd(s) for n, s in dd.items()} for pn, dd in OD[k].items()}} for k in O},
    "debt": {"gross": rnd(debt_gross), "public": rnd(debt_public), "accounts": rnd(debt_accounts)},
    "basis": {"receipts": basis_receipts, "outlays": basis_outlays},
    "labels": {"receipts": {"individual": "Individual income tax", "corporate": "Corporate income tax", "payroll": "Payroll taxes", "excise": "Excise taxes", "customs": "Customs duties", "other": "Other receipts"},
               "outlays": {"defense": "National defense", "social_security": "Social Security", "health": "Health and Medicare", "income_security": "Income security", "interest": "Net interest", "veterans": "Veterans", "other": "Everything else"}},
}
json.dump(data, open(OUT / "ledger.json", "w"), separators=(",", ":"))
print("wrote", OUT / "ledger.json", (OUT / "ledger.json").stat().st_size, "bytes")
