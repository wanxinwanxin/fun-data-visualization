# The Treasury Machine

Room 14 of Data Art Galleries. Federal receipts and outlays, fiscal years 1789 to 2025, drawn as a hydraulic machine. Income streams merge into six sources and fill a tank. The tank drains into seven functions, and each function splits into programs. Click a spending function to open it: its programs then split into a third layer of details. Every pipe width and the tank level are in percent of GDP. The tank level is federal debt held by the public.

## Sources

| Data | Source | Terms |
| --- | --- | --- |
| Receipts by source 1934-2025, composition of payroll and excise taxes 1940-2025, composition of other receipts 1940-2025 | OMB Historical Tables 2.1, 2.4, 2.5 (FY2027 edition), https://www.whitehouse.gov/omb/information-resources/budget/historical-tables/ | US government work, public domain |
| Outlays by function 1940-2025, by subfunction 1962-2025, and Department of Defense outlays by appropriation title 1962-2025 | OMB Historical Tables 3.1, 3.2 | public domain |
| Outlays for payments for individuals by major program 1940-2025 (Social Security OASI and DI, Medicare HI and SMI, Medicaid, SNAP, EITC, SSI, and others) | OMB Historical Table 11.3 | public domain |
| Federal debt, gross and held by the public, 1940-2025, and GDP 1940-2025 | OMB Historical Tables 7.1, 10.1 | public domain |
| Receipts by source 1789-1939 (customs, internal revenue, other, land sales, refunds) | Historical Statistics of the United States, Colonial Times to 1970, series Y 352-357, Census Bureau PDF chapter Y | public domain |
| Outlays 1789-1939 (Army, Navy, interest, veterans, other) | Historical Statistics, series Y 457-465 | public domain |
| Internal revenue collections by source 1863-1939 (individual and corporate income, estate, alcohol, tobacco, gasoline) | Historical Statistics, series Y 358-373 | public domain |
| Income tax receipts, monthly, 1910-1933 | NBER Macrohistory Database, series m15002a | free for research use |
| Nominal GDP and population 1790-1939 | Samuel H. Williamson, "What Was the U.S. GDP Then?", MeasuringWorth, 2026 | free with attribution |
| Debt outstanding 1790-1939 | Treasury Fiscal Data, Historical Debt Outstanding, https://fiscaldata.treasury.gov | public domain |

## Method

The Census tables exist only as a scanned PDF. `pipelines/treasury-machine/ocr_boxes.py` runs RapidOCR on the 300 dpi pages, and `ocr_table.py` rebuilds each table from the text boxes. Numbers are right-aligned in the scan, so a box belongs to the column whose right edge is nearest. Each row is checked against its printed total. A single-digit repair fixes the common 3/8 and 5/6 misreads when exactly one substitution makes the row add up. Eighteen cells and five rows (outlays 1936-1940) were entered by hand after a visual check of the scan. The rebuilt tables are in `data/raw/treasury-machine/tab/table*.json` after a run.

`parse_omb.py` reads the OMB spreadsheets. `process.py` joins everything into `data/ledger.json` in millions of current dollars by fiscal year.

Category rules before 1934:

- Customs is series Y 353. Individual and corporate income taxes come from Y 359 and Y 360 (1916-1939). For 1918-1925 the Census marks the split as not available, so the combined income tax comes from the NBER monthly series summed by fiscal year, and the individual share is interpolated between 1917 and 1926. For 1910-1915 the NBER series gives the total, with the corporation excise tax of 1909-1913 counted as corporate. The Civil War income tax of 1863-1873 comes from the annual reports of the Commissioner of Internal Revenue and is counted as individual.
- Excise is the rest of internal revenue after income and estate taxes. It includes stamp taxes, licenses and the capital stock tax.
- Other receipts are series Y 355 plus estate and gift taxes, which OMB also classes as other. Public land sales (Y 356) are a sub-stream.
- Refunds (Y 357) are netted against internal revenue from 1913, so the totals match OMB Table 1.1.
- Defense is Army plus Navy. Veterans is series Y 463. Everything else is the remaining outlays. New Deal relief sits in everything else until 1940, because the function split starts in 1940.

After 1934 the categories follow OMB. Health is function 550 plus Medicare (570). Everything else is total outlays minus the six named functions, so undistributed offsetting receipts and allowances are netted into it. Its programs are the positive functions, scaled proportionally to the netted total.

Third layer (1962 on, one rule for all details): a detail gets its share of the program outlay from Table 3.2. The shares come from Table 11.3 or from the subfunctions in Table 3.2. Negative source values are dropped, so the details always add up to the program.

- Social Security splits into OASI and DI by the Table 11.3 shares, from 1940. This split is the program layer.
- Medicare splits into Part A (HI) and Parts B and D (SMI). Table 11.3 gives gross benefit payments, and Table 3.2 gives outlays net of premiums, so the parts show the gross shares of the net total.
- Health care services (551) splits into Medicaid, ACA premium tax credits, CHIP, and the rest of 551.
- Food and nutrition (605) splits into SNAP, child nutrition, WIC, and commodities. Other income security (609) splits into SSI, EITC, child tax credits, TANF, foster care, child care, LIHEAP, pandemic payments, and the rest of 609. Federal employee retirement (602) splits into civil service, military, and other.
- Veterans income security (701) splits into service-connected compensation, pensions, and insurance and burial.
- Defense splits construction, family housing, and other DoD, and splits DOE atomic energy (053) from defense-related activities (054).
- Each function inside Everything else splits into its subfunctions. Examples of dropped negative items are deposit insurance, mortgage credit, and higher education (student loan reestimates) in some years.

When a function is open, its programs and details are magnified. The factor is fixed for each function, from its largest share of GDP since 1962, so growth over time stays visible. The canvas shows the factor.

## Seams

- GDP before 1940 is a calendar-year estimate. OMB fiscal-year GDP starts in 1940.
- The fiscal year ended June 30 until 1976 and September 30 after. The 1976 transition quarter is dropped.
- Debt before 1940 is gross debt from Treasury. Debt held by government accounts (the lighter band in the tank) starts in 1940.
- Programs appear when the data splits them: receipts sub-streams in 1940, outlay programs in 1962, and the third layer in 1962 (Medicare and Medicaid details in 1966).

## Sound

Each fiscal year plays one mallet note (a triangle wave with a short sine strike at four times the pitch). The pitch follows debt held by the public on a major pentatonic scale from F3 to A5. The note goes down one step for each 10% of GDP of debt. Thus the run from 1789 climbs to the top note by the 1830s, when the debt is paid off. The melody falls in the Civil War, in World War I, and in World War II (to the second-lowest note), and it climbs again from 1946 to 1974. Decade years are louder.

- A deficit adds a low splash with the note: a lowpass noise burst and a falling sine. The splash is heavier for a larger deficit (up to 12% of GDP).
- A surplus adds a chime one octave and one twelfth above the note.
- Two band-passed noise beds are the water. The receipts bed is on the left, and the outlays bed is on the right. Each bed is louder and brighter for a larger flow, up to 30% of GDP.
- A bell (inharmonic partials on C3) rings at each event on the timeline.
- When you drag the year slider, the notes play for each year that you pass.
- At higher speeds the notes are shorter and quieter. A compressor before the master gain keeps the peaks safe.
- When you open or close a function, a short valve click plays.

The notes, the chime, the beds, and the noise of the splash are all above 150 Hz, so that laptop speakers can play them. Only the falling sine of the splash is lower, and it adds weight on headphones. The previous design used a drone at 75-165 Hz, which laptop speakers do not play well.

## Rebuild

```
.venv/bin/python3 pipelines/treasury-machine/fetch.py
.venv/bin/python3 pipelines/treasury-machine/parse_omb.py
for p in 40 48 49 41 42; do .venv/bin/python3 pipelines/treasury-machine/ocr_boxes.py data/raw/treasury-machine/tab/h$p-$p.png data/raw/treasury-machine/tab/ocr$p.json; .venv/bin/python3 pipelines/treasury-machine/ocr_table.py $p; done
.venv/bin/python3 pipelines/treasury-machine/process.py
```
