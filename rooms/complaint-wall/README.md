# The Complaint Wall

A brutalist heatmap wall of consumer complaints. Two public sources feed it: vehicle complaints to NHTSA, and financial complaints to the CFPB. Time advances month by month. A cell glitches when its complaint count spikes above its own history.

## Sources

| Source | URL | Terms |
| --- | --- | --- |
| NHTSA Office of Defects Investigation, vehicle owner complaints flat file | https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip | US Government work, public domain. Field list: https://static.nhtsa.gov/odi/ffdd/cmpl/CMPL.txt |
| CFPB Consumer Complaint Database | https://files.consumerfinance.gov/ccdb/complaints.csv.zip | CC0 public domain (the API metadata reports the license as CC0) |

The snapshot date is 2026-10-26. The pipeline drops the snapshot month because that month is incomplete.

## Record counts

| Source | Raw rows | Rows kept after the date cut | Notes |
| --- | --- | --- | --- |
| NHTSA | 2,259,830 complaint-component rows | 2,252,417 rows, 1,623,533 unique complaints (ODINO), 1995-01 to 2026-09 | 0 malformed rows. The rows dropped have a receipt date before 1995-01 or in 2026-10. |
| CFPB | 18,681,268 complaints | 18,175,432 complaints, 2012-01 to 2026-09 | The rows dropped have a receipt date in 2011 or in 2026-10. |

Processed output: `data/nhtsa.json` (0.44 MB) and `data/cfpb.json` (0.29 MB), 0.73 MB in total.

## Sampling rule

The pipeline does not sample rows. It aggregates every row by month and folds the long tail into an OTHER bucket:

- NHTSA rows: the 25 makes with the most complaint rows from 1995-01 to the last full month stay as rows. All other makes fold into ALL OTHER MAKES.
- NHTSA columns: the 14 top-level component groups with the most rows stay as columns. The group UNKNOWN OR OTHER and all other groups fold into ALL OTHER COMPONENTS. The top-level group is the text before the first colon in COMPDESC.
- NHTSA model years: 1990 to 2027. Rows with a model year outside that range, or with the code 9999, do not enter the model-year grid. They stay in the monthly grid.
- CFPB rows: the 25 companies with the most complaints from 2012-01 to the last full month stay as rows. All other companies fold into ALL OTHER COMPANIES. A second row set uses products. Product names that changed over time map to one label (for example the three credit reporting product names map to CREDIT REPORTING).
- CFPB columns: the 14 issues with the most complaints stay as columns. All other issues fold into ALL OTHER ISSUES. The CFPB renamed many issues in April 2017. The table ISSUE_MERGE in process.py maps the older label to the newer label for the same failure mode.
- CFPB clusters: the 60 sub-issues with the most complaints feed the side strip. When a complaint has no sub-issue, the pipeline uses the issue label. Each month lists its top 8.

NHTSA counts are complaint-component rows. One complaint with two components gives two rows, one in each column. The narrative keyword counts and the unique complaint totals count each ODINO once.

## Processing steps

1. `fetch.py` streams both archives into `data/raw/complaint-wall/`. It opens each zip to confirm that the download is complete. The NHTSA server sends the archive with gzip transfer encoding, so the script does not compare the Content-Length header with the file size.
2. `process.py` streams the NHTSA text file line by line without extracting it. It splits each line on tabs, reads the make, model year, component, receipt date and narrative, and accumulates counters. It runs the keyword lexicon on the lower-case narrative of each unique complaint.
3. `process.py` streams the CFPB CSV with pyarrow in 48 MB blocks and aggregates each block with pandas. It keeps three aggregates: month x company x issue, month x product x issue, and month x sub-issue.
4. The script writes `data/nhtsa.json` and `data/cfpb.json` with dense integer arrays in month, row, column order, and draws `preview.svg` from the NHTSA month with the most rows.

Run from the repository root:

```
.venv/bin/python3 -I pipelines/complaint-wall/fetch.py
.venv/bin/python3 -I pipelines/complaint-wall/process.py
```

The scripts use only packages that the repository already installs: requests, pyarrow, pandas, numpy.

## The lexicon

The NHTSA side strip is a text-processing layer. Each entry is a label and a regular expression. The expression runs on the lower-case narrative. One complaint counts at most once per label.

| Label | Pattern (Python regular expression on the lower-case narrative) |
| --- | --- |
| FIRE | `\bfire\b\|\bflames?\b\|caught on fire\|burn(ed\|ing) up` |
| SMOKE | `\bsmok(e\|ing)\b` |
| STALL | `\bstall(s\|ed\|ing)?\b` |
| BRAKE FAILURE | `brakes? (failed\|fail\|went out\|did not work\|didn't work\|do not work)\|no brakes\|brake failure\|loss of brak` |
| AIRBAG | `\bair ?bags?\b` |
| AIRBAG DID NOT DEPLOY | `air ?bags? (did not\|didn't\|never\|failed to) deploy` |
| STEERING | `\bsteering\b` |
| UNINTENDED ACCELERATION | `unintended acceleration\|sudden acceleration\|accelerat(ed\|es\|ing) on its own\|accelerat(ed\|es\|ing) by itself\|surge(d\|s)? forward` |
| LOSS OF POWER | `loss of power\|lost (all )?power\|lose(s)? power\|no power` |
| SHUT OFF | `shut(s)? (off\|down)\|turn(ed\|s)? off (while\|when) driving\|died while driving` |
| CHECK ENGINE LIGHT | `check engine` |
| WARNING LIGHT | `warning light\|light(s)? (came\|come) on\|dash(board)? light` |
| TRANSMISSION | `\btransmission\b` |
| FUEL LEAK | `fuel leak\|gas leak\|leak(ing\|ed\|s)? (gas\|fuel)\|smell(ed\|s)? (of )?(gas\|fuel)` |
| TIRE BLOWOUT | `blow ?out\|blew out\|tread separat` |
| CRASH | `\bcrash(ed\|es)?\b\|\baccident\b\|\bcollision\b` |
| INJURY | `\binjur(y\|ies\|ed)\b\|\bwhiplash\b\|\bhospital` |
| DEATH | `\bdeaths?\b\|\bfatalit(y\|ies)\b\|\b(killed\|died) (in\|when\|after\|during\|as)\b\|(person\|people\|driver\|passenger\|someone\|wife\|husband\|son\|daughter\|child\|he\|she\|they) (was \|were )?(died\|killed)\b` |
| RUST | `\brust(ed\|ing)?\b\|\bcorro(sion\|ded)\b` |
| RECALL | `\brecall(s\|ed)?\b` |
| DEALER REFUSED | `dealer(ship)? (refus\|would not\|won't\|will not\|said (it\|there) (is\|was) (nothing\|no))` |
| ROLLAWAY | `roll(ed\|s\|ing)? (away\|back\|down)\|rollaway` |
| WINDSHIELD CRACK | `windshield crack\|crack(ed\|s)? (in the )?windshield` |
| SOFTWARE | `\bsoftware\b\|\bfirmware\b\|\bglitch(es\|ed\|ing)?\b\|\bfroze\b\|\bfreezes\b\|\breboot` |
| BACKUP CAMERA | `back ?up camera\|rear ?view camera` |

## What the visualization shows

- Rows are makes (NHTSA) or companies or products (CFPB). Columns are components (NHTSA) or issues (CFPB).
- Each cell is the complaint count in the shown month. The ROW PEAK scale divides the count by the largest count that row reached in any month and any column, then applies a square root so early months stay visible. The ROW SHARE scale divides the count by the row total for the month.
- The color scale is one hue: dark gray to acid yellow.
- A cell glitches (offset slices, flicker) when the count is more than 2 standard deviations above the mean of the same cell over the previous 24 months, is at least 15 complaints, and is at least 1.5 times that mean. The first 12 months of each source have no test.
- The side strip lists the top narrative keywords (NHTSA) or the top sub-issues (CFPB) for the shown month, the cells that spike now, and the latest reference event. The reference events are editorial markers for well-known recalls and enforcement actions. They are not part of the data sets.
- The NHTSA source has a model-year view: rows are makes, columns are model years 1990 to 2027, and a selector picks one component or all components.
- Hover or click a cell to read its count, its share of the row, and its distance from the trailing mean in standard deviations.

## Sound

All sound is generated from the data in the browser with the Web Audio API.

- Industrial clicks: short white-noise bursts through a band-pass filter. The click rate is proportional to the square root of the month total relative to the largest month. Each click takes a column at random with probability proportional to that column's count in the month. The column sets the stereo pan (left column to right column) and the band-pass center frequency (about 500 Hz to 3000 Hz).
- Alarm: when a month starts with spiking cells, two detuned square-wave oscillators play through a 320 Hz low-pass filter with a slow envelope. The pitch is between 55 Hz and 110 Hz, deeper for lower rows. The pan follows the column. At most two alarms play per month step.
- Space: a convolver with a generated 1.6 second noise impulse response, mixed at 28 percent. A 5.2 kHz low-pass filter and a compressor sit before the master gain.

## Known limitations

- The CFPB file and the CFPB API no longer contain the consumer narrative text. The plan called for a phrase lexicon on CFPB narratives. The room therefore runs the lexicon only on NHTSA narratives and uses the consumer-selected sub-issue as the CFPB failure-mode cluster.
- The CFPB issue taxonomy changed in 2017 and again later. The merge table keeps the main columns stable, but some older issues fold into OTHER.
- NHTSA counts are rows, not complaints. A complaint that lists several components counts once per component.
- The CFPB monthly totals grow by more than 100 times from 2012 to 2026, mostly from credit reporting disputes. The ROW PEAK scale makes early years dark for the credit bureaus. The ROW SHARE scale shows the mix instead.
- The spike test is a simple trailing z-score. It flags fast growth as well as true anomalies.
- The glitch effect uses random offsets each frame. Viewers who are sensitive to flicker can pause the animation.
