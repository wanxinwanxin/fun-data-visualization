# Ships at the Border

Vessel tracks at the edges of the Channel Islands National Marine Sanctuary, drawn as ink on a nautical chart. The room shows four days of AIS positions, 15 to 18 June 2023, off Southern California.

## Sources

| Data | Source | Terms |
| --- | --- | --- |
| Vessel positions | NOAA Marine Cadastre AIS daily files, `https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2023/AIS_2023_06_15.zip` and the three following days | US Government work, public domain |
| Sanctuary boundary | NOAA Office of National Marine Sanctuaries, `https://sanctuaries.noaa.gov/library/imast_gis.html` (file `cinms_py2.zip`) | US Government work, public domain |
| Marine protected areas | California Department of Fish and Wildlife, BIOS data set ds582 "California Marine Protected Areas", queried from the public ArcGIS feature service `services2.arcgis.com/Uq9r85Potqm3MfRV/.../biosds582_fpu/FeatureServer/0` | Open data, CDFW terms of use |
| Traffic lanes | NOAA Office of Coast Survey, Marine Transportation chart layer, `gis.charttools.noaa.gov/.../NavigationChartData/MarineTransportation/MapServer/0` | US Government work, public domain |
| Coastline | Natural Earth 10m land and minor islands, `https://naciscdn.org/naturalearth/10m/physical/` | Public domain |

The plan named the 2024 AIS files. The NOAA server lists them, but every 2024 file returned HTTP 404 at the time of the build. The 2023 files are present, so the room uses 15 to 18 June 2023. This is a deviation from the plan, and it is the only one in the data sources.

## Pipeline

`pipelines/ships-and-borders/fetch.py` downloads the files above into `data/raw/ships-and-borders/`. It streams each AIS zip, keeps only the rows inside the bounding box, writes a small CSV, and deletes the zip. The bounding box is longitude -121.2 to -118.2 and latitude 33.3 to 34.6.

`pipelines/ships-and-borders/process.py` reads the filtered CSVs and the boundary files and writes `rooms/ships-and-borders/data/` and `preview.svg`.

Extra Python packages: `pyshp` (3.1.6). `pandas`, `numpy` and `requests` were already in the environment.

## Sampling rule

The rule is applied in this order. All counts are for the four days together.

1. Keep AIS rows inside the bounding box: 34,634,406 rows read, 1,007,088 rows kept, 986 distinct MMSI.
2. Keep the first row of each vessel in each 5-minute bin: 466,215 points.
3. Keep a binned point only when it is 50 m or more from the last kept point, or when 30 minutes or more passed since the last kept point: 126,438 points. This step removes repeated positions of moored and anchored vessels.
4. Drop vessels with fewer than 10 kept points: 103 vessels dropped.
5. Drop vessels that never moved 1 km or more from their first point: 261 vessels dropped. These vessels stayed in a harbor or at anchor for the whole period.

Result: 622 vessels and 85,418 track points. Longitude and latitude are quantized to 4 decimals (about 10 m) and stored as Int16 offsets from the box origin. Time is stored as whole minutes after 2023-06-15 00:00 UTC.

The vessel class comes from the AIS `VesselType` code: cargo 70 to 79, tanker 80 to 89, passenger 60 to 69, fishing 30, tug and tow 31, 32 and 52, pleasure and sailing 36 and 37. All other codes, and missing codes, are "other". The length is the largest `Length` value reported by the vessel.

## Boundaries

The sanctuary boundary has two sections. The state and federal marine protected areas inside the box come from the CDFW data set (44 polygons). State and federal reserves of the same name, for example Scorpion SMR and Scorpion FMR, are one physical area in two jurisdictions. The pipeline groups them into 32 named areas, so that one visit counts as one entry. Polygons are simplified with the Douglas-Peucker method (tolerance 0.0012 degrees for the sanctuary, 0.0006 for the reserves and lanes). The coastline is clipped to the box and simplified with a tolerance of 0.0003 degrees.

The traffic lane region is the union of the chart polygons of type "Traffic Separation Schemes", "Traffic Separation Schemes/Traffic Lanes" and "Precautionary Areas". The chart also shows the "Area to be Avoided" and "Shipping Fairways" polygons with a lighter dotted line.

## Entry events

An entry event occurs when a track point is inside a zone and the previous point of the same vessel is outside. The first point of a vessel never makes an event. The pipeline found 651 reserve entries, 209 sanctuary entries and 818 lane entries. Entries by class are in `data/stats.json`.

## What the room shows

The chart is a canvas on cream paper. Land is filled in a darker paper tone. The thin blue rings around the land are decorative, in the manner of depth contours on a printed chart. They are not depth data. Hatched polygons are the marine reserves. The dashed blue line is the sanctuary boundary. The dotted sepia bands are the charted traffic lanes.

Time runs over the four days. Each vessel is a small ink mark that moves along its track. The track behind each vessel stays on the paper as thin ink at 42 percent opacity, so the ink darkens where ships repeat a path. A track breaks where the gap between two points is over 60 minutes or the implied speed is over 40 knots. The clock shows the UTC time and the number of vessels under way (implied speed over 1 knot).

Controls: a brass play and pause button, a rate dial (5, 12 or 30 minutes of data per second) and a brass knob on the time rule under the chart. The log of crossings counts reserve entries and sanctuary entries by class up to the current time.

Place names on the chart are hand-placed annotations. They are not part of the data.

## Sound

All sound is made from the data with the Web Audio API. Every node runs through a low-pass filter and the gallery master gain. A convolver with a generated noise impulse response adds space.

- Sonar ping: a vessel enters a marine reserve. The pitch depends on the class: other 660 Hz, cargo 392 Hz, tanker 330 Hz, passenger 523 Hz, fishing 587 Hz, tug 440 Hz, pleasure 784 Hz. The ping has a short attack and a 0.9 second decay.
- Lower ping: a vessel enters the sanctuary. The same pitch one octave lower, at half level.
- Foghorn: a vessel 200 m or longer enters the traffic lane region. Two oscillators at 62 Hz and 124 Hz through a 260 Hz low-pass filter, with a slow attack and release. At most one foghorn every 2.5 seconds.
- Stereo position: each ping and foghorn is panned by the longitude of the vessel. West is left.
- Wave bed: looped filtered noise with a slow swell. Its level follows the number of vessels under way, from near silence to a soft wash at 70 or more vessels.

At most 10 sounds fire per animation frame. When you drag the time knob, the room recounts the log and does not play the skipped sounds.

## Known limitations

- AIS coverage depends on shore receivers. Small craft without AIS are absent, and some tracks have gaps.
- The 2023 data replaces the planned 2024 data, because the 2024 files were not available on the server.
- The vessel class comes from the self-reported AIS code. About 8 percent of the vessels report no usable code and are "other".
- Natural Earth 10m is a coarse coastline. Anacapa Island and some small rocks are missing from it.
- The "under way" count uses the implied speed between two kept points, not the reported speed over ground.
- Entry counts depend on the 5-minute sampling. A vessel that crosses a small reserve between two samples makes no event.
