# The Commute Bloodstream

Room 03 of Data Art Galleries. The room shows the daily commute of the Chicago area as particle streams. Each particle is a group of 20 workers. The particles move from the tract where the workers live to the tract where they work in the morning. They move back in the evening. The page is white, the marks are black, and the accent color is red.

## Sources

| Data | Source | Terms |
| --- | --- | --- |
| Origin-destination job counts | US Census Bureau, LEHD, LODES8, `il_od_main_JT00_2022.csv.gz`. <https://lehd.ces.census.gov/data/lodes/LODES8/il/od/il_od_main_JT00_2022.csv.gz> | Public domain (US federal data). |
| Tract centroids | US Census Bureau, Gazetteer Files 2023, national tracts. <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_tracts_national.zip> | Public domain. |
| Time leaving home for work | US Census Bureau, ACS 2022 5-year, table B08302, table-based summary file. <https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/data/5YRData/acsdt5y2022-b08302.dat> | Public domain. |
| County outlines | us-atlas 3.0.1, `counties-10m.json`. <https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/counties-10m.json> | ISC license. The shapes come from the Census Bureau. |

The plan was to read B08302 from the Census API without a key. The API now redirects keyless requests to a "Missing Key" page. The pipeline detects that page and downloads the official summary file for the same table instead. The summary file holds the same ACS 2022 5-year estimates. The pipeline keeps only the Illinois county and tract rows and deletes the 72 MB file.

## Sampling rule

The pipeline applies these rules, in this order:

1. Keep the Illinois tracts with a centroid inside the box longitude -88.4 to -87.5 and latitude 41.5 to 42.2. This box holds 1,811 tracts.
2. Cut each 15-digit block code to its 11-digit tract code. Sum the jobs (`S000`) for each home tract and work tract pair. The LODES file has 5,152,046 block pairs and 5,532,686 jobs. The box holds 803,792 tract pairs and 3,059,190 jobs.
3. Keep the tract pairs with at least 10 jobs. This leaves 57,561 pairs and 1,452,569 jobs (47 percent of the jobs in the box). The cap of 300,000 pairs is not reached.
4. In the browser, each pair becomes `jobs / 20` particles. The fraction is rounded with a deterministic hash, so the expected particle count equals the job count divided by 20. The result is 72,662 particles. Pairs where home and work are the same tract (1,454 pairs, 75,678 jobs) do not move and are not drawn.

## Processing steps

`pipelines/commute-bloodstream/fetch.py` downloads the four files into `data/raw/commute-bloodstream/`. `pipelines/commute-bloodstream/process.py` streams the LODES file in chunks of 500,000 rows and aggregates the pairs. It then builds a departure profile for each home tract. The profile is the 14-bin B08302 count of the tract, smoothed toward the share of its county with a prior weight of 300 workers. This keeps the small-tract noise down. It decodes the county arcs from the TopoJSON file and keeps the arcs that touch the box. It writes:

- `rooms/commute-bloodstream/data/tracts.json` (133 KB): metadata, 1,810 tract centroids, the departure profiles (0 to 255 per bin), and the county arcs.
- `rooms/commute-bloodstream/data/pairs.bin` (345 KB): Uint16 triples of home index, work index, and jobs.
- `rooms/commute-bloodstream/preview.svg`: the 900 largest flows as red curves and all tract centroids as dots.

Total processed data: 0.48 MB.

## Time of day

LODES has no time of day. The room gives each particle a departure time from the B08302 profile of its home tract. The particle picks one of the 14 bins by a weighted draw, then a uniform time inside the bin. The travel time is 8 minutes plus the straight-line distance at 30 km/h, with a random factor from 0.8 to 1.2, and a cap of 90 minutes. The return trip starts 9 hours after the departure, plus or minus 30 minutes. Trips that cross midnight wrap to the next day. The pulse curve under the timeline is the number of workers in motion at each minute, computed from these times.

## What the room shows

- Red particles move from home to work. Black particles move from work to home.
- Faint dots are tract centroids. The larger black dot is the tract in the Loop with the most inbound jobs (tract 17031839100, 284,988 jobs).
- Thin gray lines are county outlines and the lake shore.
- The large number is the count of workers in motion. The clock shows the simulated time.
- The timeline is a thin 24-hour line with the pulse curve and a red marker. The marker is also a scrubber.
- Play or pause, and speed buttons from half speed to 4 times. At speed 1, one day takes 144 seconds.

## Sound

All sound passes through a low-pass filter at 2.6 kHz and a convolver with a generated noise impulse response, then through the master gain.

- Crowd texture: short filtered noise grains (120 ms buffer, 12 ms attack, 50 to 110 ms release). The grain rate is 3 per second plus 55 per second times the share of the daily peak that is in motion now. Each grain takes its stereo pan from the longitude of the home tract of a random particle in motion. The band-pass center rises with the travel time of that particle.
- Tick: a soft wooden tick (a short sine from 880 Hz to 520 Hz through a band-pass filter) every 15 simulated minutes.
- Low tone: two sines at 55 Hz and 110 Hz. The gain follows a bell window of 45 minutes around the morning peak and the evening peak of the pulse curve.

## Known limitations

- LODES counts jobs, not commuters. A person with two jobs appears twice. Some employers report a central address for all workers, which inflates the Loop.
- The main file holds only workers who live in Illinois. Workers from Indiana and Wisconsin are absent.
- The threshold of 10 jobs per pair drops 53 percent of the jobs in the box, mostly in long thin flows to small suburban workplaces.
- The departure times are a statistical spread, not records of real trips. The return time is an assumption of a 9-hour day.
- Tract-level B08302 estimates have large margins of error. The county prior reduces, but does not remove, that noise.
- The county outlines come from a 1:10m simplified file. The lake shore is coarse.

## Packages

No extra pip packages. The pipeline uses `requests`, `numpy`, and `pandas` from the shared environment.
