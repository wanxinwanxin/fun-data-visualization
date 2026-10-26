# Four Centuries of Logbooks

A time-lapse map of where ships wrote down the weather, from 1662 to 2014. The room draws each sampled month as pen dots on aged paper. From 1750 to 1855 it also draws single voyages from the CLIWOC logbooks, colored by nation.

## Sources

1. **ICOADS Release 3.1, final untrimmed monthly IMMA1 files.** NOAA National Centers for Environmental Information.
   Directory: `https://www.ncei.noaa.gov/data/international-comprehensive-ocean-atmosphere/v3/archive/final-untrim/`
   Files: `IMMA1_R3.1.0_YYYY-MM.gz`. The archive holds 3,232 monthly files from 1662-12 to 2014-12.
   Terms: ICOADS is a public NOAA data set. NOAA asks users to cite Freeman et al. (2017), *ICOADS Release 3.0: a major update to the historical marine climate record*, Int. J. Climatol. 37, 2211-2232.
2. **CLIWOC 2.1, core records in IMMA format.** García-Herrera, R. (2007), CLIWOC Database 2.1 (final release, original IMMA format). PANGAEA, `https://doi.org/10.1594/PANGAEA.743343`. File `CLIWOC21CORE.zip` (3.9 MB, 281,920 records, 1662 to 1855).
   License: Creative Commons Attribution 3.0 Unported (CC BY 3.0).
3. **Coastlines.** Natural Earth 110m land, from `world-atlas@2.0.2/land-110m.json` on jsDelivr (public domain). The page loads this file at run time.

The room also loads d3 7.9.0 and topojson-client 3.1.0 from jsDelivr, and the font IM Fell English from Google Fonts.

## Sampling rule

`pipelines/ship-logbooks/fetch.py` applies this rule:

- Before 1750 the archive holds only a few small months (1662-12 to 1749-07). The script takes every one of these 52 months.
- From 1750 to 2010 the script takes one month every 5 years. It takes July. All target years have a July file.
- The script also takes July 2014, the last month of Release 3.1.
- The script streams each gzip file from NCEI and never stores the gzip file on disk.
- The script keeps main records only. Release 3.1 holds linked subsidiary records that do not start with the year. The script skips them.
- The script counts every main record of the month. It keeps at most 20,000 records per month by reservoir sampling. The random seed is `year * 100 + month`, so a new run gives the same sample.

In total the 106 sampled months hold 9,491,638 main records. The samples hold 631,636 records.

Fields come from the IMMA1 core record and the first (ICOADS) attachment: YR (columns 1-4), MO (5-6), DY (7-8), LAT (13-17, hundredths of a degree), LON (18-23, hundredths of a degree, 0 to 360 east), ID (35-43), C1 country code (44-45), DCK deck (119-121), PT platform type (125-126).

Platform classes: PT blank or 0 to 5 is a ship. PT 6 to 8 is a buoy (moored, drifting, ice). All other PT values are "stations and other" (ice stations, oceanographic stations, bathythermographs, coastal stations, fixed platforms).

## Processing steps

`pipelines/ship-logbooks/process.py` does this:

1. It groups the sampled months into 63 periods. Every year before 1750 is one period that holds all its sampled months. From 1750 on, each sampled month is one period.
2. For each period it counts the sampled records in 0.5 degree cells, with a separate count for ships and for buoys and other platforms. It writes the cells to `data/cells.bin` as little-endian Uint32 values: latitude index (9 bits), longitude index (10 bits), ship count capped at 127 (7 bits), other count capped at 63 (6 bits). The 63 periods hold 289,238 occupied cells.
3. It writes `data/periods.json` with the true record totals of each period, the platform classes, the number of kept records, the cell offsets, and the five most common country codes in the sample.
4. It reads the CLIWOC core records, groups them by ship ID, and sorts them by date. A gap of more than 30 days, or a jump of more than 12 degrees between consecutive records, starts a new voyage. Voyages with fewer than 8 positioned records are dropped. Each voyage keeps its first point, its last point, and each point that is at least 0.75 degrees from the previous kept point. This gives 4,376 voyages and 217,886 points. `data/routes.bin` holds the points as little-endian Int16 pairs (latitude times 100, longitude times 100). `data/voyages.json` holds one entry per voyage: nation index, start as a decimal year, end as a decimal year, point offset, point count.
5. It writes `preview.svg` from the 1985 ship cells and one third of the CLIWOC voyages.

The nation of a voyage comes from the most common C1 code of its records: NL is Dutch, UK is British, ES is Spanish, FR is French, all other codes are "Other".

Processed data: 2.1 MB in total.

## What the room shows

- Each dot is one 0.5 degree cell of ocean where a ship wrote a weather report in the sampled month. The dot grows with the number of reports in the cell.
- Dark ink is the current period. The ink of earlier periods fades each frame, so the previous four periods stay visible as faint ink.
- From 1750 to 1855 the colored lines are single CLIWOC voyages. A line grows as the year counter advances through the voyage dates. Old lines fade like the dots.
- The platform switch adds buoys and automatic stations as open rings. In the ships-only view, these reports are hidden.
- The year counter turns like a ledger. The ledger lines give the true record totals of the month, the platform mix, and the nations that the alphabetic country codes name.
- The histogram draws the records of each sampled period as pen strokes on a logarithmic scale. A click on a stroke opens that period.
- Deep links: `#y=1985` opens the page at that year, `#mode=all` shows all platforms, `#pause` starts paused.

## What each sound maps to

- **Wind.** Filtered noise (a looping buffer of softened noise through a bandpass filter). Its gain follows the logarithm of the number of reports in the month, from 0.05 at 31 reports to 0.25 at 2.1 million. The bandpass center frequency moves from 260 Hz to about 1,160 Hz with the same value. A slow sine oscillator adds gusts.
- **Rope creaks.** Short noise bursts (80 to 200 ms) through a sharp bandpass resonance (Q 14 to 28) whose frequency slides down. The creak rate follows the number of occupied cells in the current period, from 0.25 to about 3.5 creaks per second. Each creak gets a random stereo pan.
- **Bell.** When the counter enters a new century, a soft ship bell rings twice. The bell is four sine partials with exponential decays. Its pitch changes with the century.
- All sources go through a low-pass filter at 3.8 kHz, a generated reverb (a convolver with 2.4 s of decaying noise), and a gentle compressor, and then into the master gain of the gallery.

## Known limitations

- One month every five years is a thin sample. July favors the summer routes of the Northern Hemisphere. The histogram shows the records of the sampled month, not of the whole year.
- Reservoir sampling caps a month at 20,000 records. From 1885 on, the dots show the shape of the traffic, not its full volume. The ledger line gives the true total.
- The cell counts in `cells.bin` are capped at 127 for ships and 63 for other platforms. This matters only for a few harbor cells and moored buoys.
- ICOADS also uses numeric country codes (for example 03, 17, 21, 25). The room does not decode these codes. The ledger names only the alphabetic codes. The numeric codes stay in `periods.json` as data.
- CLIWOC voyages are reconstructed from ship ID and date gaps. A ship that stayed in port for more than 30 days starts a new voyage in this room.
- The gaps between the early years (1663, 1677, 1699, 1700, 1745) make the year counter jump quickly in the first chapter.

## Python packages

The pipelines use the standard library only. No packages were added.

## Rebuild

```
.venv/bin/python3 -I pipelines/ship-logbooks/fetch.py
.venv/bin/python3 -I pipelines/ship-logbooks/process.py
```

The fetch streams about 1 GB from NCEI and takes a few minutes. It writes about 20 MB of samples to `data/raw/ship-logbooks/`.
