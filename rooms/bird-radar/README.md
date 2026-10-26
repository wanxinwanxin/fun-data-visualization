# Birds on the Radar

A radar scope that shows nocturnal bird migration in spring 2024. Weather radar sees birds. On a clear spring night, millions of birds take off after sunset. They show up as a ring of reflectivity around the radar site.

## Source

- NOAA NEXRAD Level II archive on AWS Open Data: https://registry.opendata.aws/noaa-nexrad/
- The NOAA bucket `noaa-nexrad-level2` refused anonymous requests from this machine (HTTP 403 on listing and on objects). The pipeline reads the Unidata mirror bucket `unidata-nexrad-level2` instead. Both buckets hold the same NOAA files under the same keys, for example `2024/05/01/KTLX/KTLX20240501_000055_V06`.
- Terms: NOAA data is in the public domain. The AWS Open Data program hosts it with no access fee. The MetPy reader is BSD-3 licensed.
- Stations: KTLX (Oklahoma City, 35.333 N, 97.278 W), KLOT (Chicago, 41.605 N, 88.085 W), KDOX (Dover, Delaware, 38.826 N, 75.440 W).
- Nights: 2024-04-20 to 2024-05-25, 36 nights per station.

## Sampling rule

The pipeline selects exactly three volume scans per station and per night:

1. The baseline scan, nearest to 1.0 hour before local sunset.
2. The takeoff scan, nearest to 1.0 hour after local sunset.
3. The peak scan, nearest to 2.5 hours after local sunset.

Sunset comes from the NOAA solar formula in `fetch.py` with a zenith of 90.833 degrees. The night date is the local calendar date of the evening. For example, the night 2024-04-20 at KTLX has its sunset at 01:06 UTC on 2024-04-21 and its peak scan at 03:33 UTC on 2024-04-21. The nearest scan must be within 25 minutes of the target time. A night is dropped for a station when one of its three scans is missing. The selection is stored in `data/raw/bird-radar/selection.json`.

From each volume scan the pipeline keeps only the lowest elevation sweep (about 0.5 degrees), with the reflectivity moment (REF) and the correlation coefficient moment (RHO). It keeps gates from 0 to 100 km.

## Processing steps

`pipelines/bird-radar/fetch.py` runs the download and the reduction together, because the raw files are large (3 to 15 MB each, about 2.4 GB in total) and the brief limits raw storage. The script:

1. Lists the bucket for the UTC days around each sunset and picks the scan keys.
2. Downloads one file, reads it with `metpy.io.Level2File`, and reduces it.
3. Saves the reduced scan to `data/raw/bird-radar/scans/<key>.npz` and deletes the raw file.

The reduction builds a polar grid of 360 azimuth bins (1 degree) by 40 range bins (2.5 km). For each bin it computes:

- The mean linear reflectivity of all gates in the bin (missing gates count as zero), converted back to dBZ and clamped to -10 to 40 dBZ.
- The mean RHO of the echo gates (REF above 0 dBZ) in the bin. A bin with mean RHO below 0.95 is biological. A bin with mean RHO at or above 0.95 is rain-like. The 0.95 threshold is the usual value in radar ornithology (Dokter et al., 2011).

It also computes four scalar indices over the gates from 5 to 80 km:

- `idx`: mean linear reflectivity of all gates in dBZ.
- `bio`: mean linear reflectivity of the biological gates (RHO below 0.95 or RHO missing) in dBZ. This is the biological index that the room shows.
- `cov`: the share of gates with REF at or above 5 dBZ.
- `wx`: the share of echo gates with RHO at or above 0.95.

`pipelines/bird-radar/process.py` assembles the reduced scans into `rooms/bird-radar/data/frames.bin` and `rooms/bird-radar/data/manifest.json`, and draws `preview.svg` from the clearest strong KTLX night.

Each bin is one byte. Bits 0 to 5 hold the reflectivity code: 0 means no echo, and 1 to 63 map -10 to 40 dBZ in equal steps. Bits 6 and 7 hold the class: 1 is biological, 2 is rain-like. A night is marked as weather when any of its three scans has `wx` at or above 0.35.

Record counts: 324 scans selected (3 stations x 36 nights x 3 scans), 324 scans reduced, 0 skipped, 0 nights dropped. Each raw scan holds about 720 radials x 1832 gates of reflectivity (about 1.3 million gates), and the pipeline keeps the 720 x 392 gates within 100 km (about 282,000 gates per scan). The reduced data has 14,400 bins per scan, 324 frames in total. The output is 4.67 MB for `frames.bin` and 51 kB for `manifest.json`. Weather nights: KTLX 5, KLOT 9, KDOX 11 of 36.

## What the room shows

- The scope paints one scan per sweep rotation. The sweep goes baseline, takeoff, peak, then the next night. The afterglow behind the sweep fades, so the viewer sees the ring of biological echo bloom after sunset.
- Green is biological echo. Amber is rain-like echo. The ramp runs from -5 to 30 dBZ.
- The readout gives the station, the night, the scan time in UTC and local time, the sunset, the biological index, the echo coverage, the rain-like share, and the bearing of the strongest biological echo.
- The rotary switch selects the station. The RUN/HOLD switch starts and stops the sweep. The slider and the arrow buttons select the night. The left and right arrow keys and the space bar also work.
- The pen recorder at the bottom plots the biological index of all scans of the selected station. Hatched bands mark weather nights. The red pen marks the current scan.
- The inset map shows the three stations.

## Sound

All sound goes through a low-pass filter at 5.2 kHz and a convolver with a generated noise impulse response, then into the gallery master gain.

- Chirps: short sine notes with a fast pitch slide (1.5 to 3.2 kHz, 130 ms). Their rate follows the biological index of the current scan: about 0.2 per second at -5 dBZ and about 9 per second at 23 dBZ. Each chirp pans toward the bearing of the strongest biological echo, with a random spread of 70 degrees.
- Sweep whoosh: a band-pass noise swell from 220 to 1400 Hz once per rotation, when the sweep passes north.
- Rain hiss: low-pass noise whose gain follows the rain-like share `wx` of the current scan. It is silent below 20 percent.
- Night chorus: a wind bed (low-pass noise with a slow filter sweep) and a cricket shimmer (band-pass noise at 3.9 kHz pulsed at 5.5 Hz). The cricket level follows the echo coverage.

## Known limitations

- Reflectivity after sunset mixes birds, bats, insects, and weather. The RHO threshold separates rain from biology, but it does not separate birds from insects. In late April and May at these stations, nocturnal echo at 0.5 degrees is mostly birds, with some insects at low altitude.
- Ground clutter near the radar and anomalous propagation can add echo close to the site. The indices start at 5 km to reduce this effect.
- The 0.5 degree beam rises with distance. At 100 km the beam center is about 1.5 km above ground, so distant bins sample higher altitudes than near bins.
- Three scans per night is a coarse sample of the night. The takeoff and peak times are fixed offsets from sunset, and the true peak varies by night.
- Nights with a missing scan are dropped for that station.

## Packages

- `metpy` (installed with `.venv/bin/pip install metpy`, pulls in `xarray`, `pint`, `pyproj`, `scipy`, `matplotlib`).

## Rebuild

```
.venv/bin/python3 -I pipelines/bird-radar/fetch.py
.venv/bin/python3 -I pipelines/bird-radar/process.py
```
