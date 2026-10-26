# The Grid Breathes

Hourly power flow between the balancing authorities (BAs) of the United States, drawn as a living body. The room shows four sample weeks of 2024, one per season. Each hour, the dots breathe with demand and particles carry the megawatts along the tie lines.

## Sources

| Data | Source | Terms |
| --- | --- | --- |
| Hourly interchange between BA pairs | EIA Form 930, Hourly Electric Grid Monitor, six-month bulk files: `EIA930_INTERCHANGE_2024_Jan_Jun.csv` and `EIA930_INTERCHANGE_2024_Jul_Dec.csv` from https://www.eia.gov/electricity/gridmonitor/ | US government work, public domain (https://www.eia.gov/about/copyrights_reuse.php) |
| Hourly demand, net generation, total interchange, and generation by fuel per BA | EIA Form 930, six-month bulk files: `EIA930_BALANCE_2024_Jan_Jun.csv` and `EIA930_BALANCE_2024_Jul_Dec.csv` | Public domain |
| BA locations | EIA Form 860, 2024 annual zip (`eia8602024.zip`, sheet `2___Plant_Y2024.xlsx`), columns Balancing Authority Code, Balancing Authority Name, Latitude, Longitude. https://www.eia.gov/electricity/data/eia860/ | Public domain |
| State outlines | `us-atlas@3.0.1/states-10m.json` from jsdelivr | ISC license |

The pipeline uses only the primary sources. It did not need the fallback (EIA-860M).

## Sampling rule

The pipeline keeps four full weeks of 2024, one per season. Each week runs from Monday 00:00 to Sunday 24:00 in the America/New_York time zone, which gives 168 hours:

| Season | Local dates | First hour (UTC, hour ending) |
| --- | --- | --- |
| Winter | 2024-01-15 to 2024-01-21 | 2024-01-15T06:00Z |
| Spring | 2024-04-15 to 2024-04-21 | 2024-04-15T05:00Z |
| Summer | 2024-07-15 to 2024-07-21 | 2024-07-15T05:00Z |
| Autumn | 2024-10-14 to 2024-10-20 | 2024-10-14T05:00Z |

Inside each week, the pipeline keeps every hour, every BA, and every BA pair. It does not subsample inside a week.

Record counts:

- Balance file: 535,824 rows read, 40,992 rows kept (61 reporting BAs x 672 hours).
- Interchange file: 2,591,280 rows read, 198,240 rows kept, folded into 153 undirected BA pairs x 672 hours.
- Plant file: 69 BAs with coordinates. 8 BAs outside the United States get a fixed location (see below).

## Processing steps

1. `fetch.py` streams the four EIA-930 files, the EIA-860 zip, and the us-atlas file into `data/raw/grid-flow/`. It extracts only the plant sheet from the zip and deletes the zip.
2. `process.py` reads the balance files in chunks and keeps the rows inside the four windows. It uses the `(Adjusted)` columns for demand, net generation, and total interchange. It groups the adjusted fuel columns into seven fuels: coal, gas, nuclear, hydro (including pumped storage), wind, solar, and other (petroleum, geothermal, batteries, other and unknown sources). The two half-year files use different fuel column names, and the script matches the columns by keyword.
3. It reads the interchange files in chunks and keeps the rows inside the four windows. Each BA pair appears twice in EIA-930, once from each side. The script folds the two reports into one undirected pair. The report of the alphabetically first BA wins. The report of the second BA, with the sign flipped, fills the hours that the first BA did not report. A positive value means flow from the first BA to the second BA.
4. It computes each BA location as the median latitude and longitude of the plants that list that BA code in EIA-860. The median resists plants that sit far from the service area. The plant file has no nameplate capacity, so the centroid has no weight.
5. BAs in Canada and Mexico (AESO, BCHA, CEN, HQT, IESO, MHEB, NBSO, SPC) have no plants in EIA-860. The script places each one at the point where its main tie lines cross the US border. The tooltip marks these BAs.
6. It rounds every MW value to an integer and writes `data/grid.json` (2.5 MB). Missing values stay `null`.
7. It draws `preview.svg` from the real summer data at Sunday 17:00 ET.

## What the visualization shows

- The map is a conic equal-area projection of the lower 48 states.
- Each dot is a BA. The dot area grows with demand at that hour.
- The dot tint shows net interchange. Green is a net exporter, amber is a net importer, and gray is balanced. The tint saturates when the net interchange reaches one quarter of demand.
- A ring around each dot beats faster when the BA runs near its weekly peak load.
- Each tie line is a curved arc. Particles run along the arc in the direction of the flow. The particle count grows with the square root of the MW. The particle speed grows with the MW up to 3,000 MW.
- The console shows the clock (UTC, Eastern, and Pacific), total demand, net generation, net import, the fuel mix of the lower 48 as a stacked bar and a list, and the five largest tie-line flows of the hour.
- Hover or tap a dot to read its demand, generation, interchange, and top three fuels.
- Controls: season rockers, RUN and HOLD, one-hour step buttons, a rate dial with three detents, and a time scrubber with day ticks. The space bar and the arrow keys also work.

## What each sound maps to

All sound is a sonification of the data at the current hour. There is no recorded track.

- Hum: three oscillators (sawtooth, sub sine, detuned triangle). The pitch follows total demand of the lower 48, from 44 Hz at the lowest hour of the four weeks to 94 Hz at the highest hour.
- Brightness: a resonant low-pass filter on the hum. The cutoff rises from 160 Hz to 2,560 Hz as solar generation rises toward its maximum across the four weeks.
- Wind: pink noise through a band-pass filter with a slow sweep. The level and the center frequency follow wind generation.
- Pings: at each hour change, every tie line above 2,500 MW triggers a soft sine note (at most six, the largest first). The pitch comes from a pentatonic scale, fixed per tie line. The note pans east or west by the longitude of the tie line. The level grows with the MW.
- Clock tick: a very soft tick at each hour change.
- All sources pass through a convolver with a generated 2.4 s noise impulse response, a 3.8 kHz low-pass filter, and a compressor, then into the gallery master gain.

## Known limitations

- EIA-930 values are as reported by the BAs. Single-hour glitches remain, for example the SPC to SWPP pair reports 9,967 MW for one hour in the summer week. Real values for that tie are a few hundred MW.
- The two reports of one BA pair often disagree by a small amount. The room shows only one of them.
- Foreign BAs have no demand data, so they appear as hollow gray dots at the border.
- The BA centroid is a plain median of plant locations. For large BAs, such as MISO or SWPP, the dot sits in the middle of a very wide area.
- Some BAs do not report a fuel breakdown. The fuel mix panel counts only the fuels that BAs report.
- The hour loops inside one week. The room does not animate across seasons.

## Rebuild

```
.venv/bin/pip install openpyxl
.venv/bin/python3 -I pipelines/grid-flow/fetch.py
.venv/bin/python3 -I pipelines/grid-flow/process.py
```

Extra package: `openpyxl` (reads the EIA-860 xlsx).
