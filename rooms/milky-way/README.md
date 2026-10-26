# A Million Neighbors

A 3D point cloud of the stars within about 100 parsecs of the Sun. The data comes from the Gaia Catalogue of Nearby Stars (GCNS). Each point is one real star at its measured position. The color follows the measured Gaia BP-RP color index. The time mode moves each star along its measured velocity.

## Sources

- Primary: Gaia Collaboration, Smart R.L., Sarro L.M., et al. (2021), "Gaia Early Data Release 3: The Gaia Catalogue of Nearby Stars", A&A 649, A6. VizieR catalog `J/A+A/649/A6`, table `table1c` (selected objects). The pipeline reads the table through the VizieR TAP service at `https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync`. Landing page: https://cdsarc.cds.unistra.fr/viz-bin/cat/J/A+A/649/A6
- Labels: Hipparcos, the New Reduction (van Leeuwen 2007), VizieR catalog `I/311/hip2`, 12 rows for well-known nearby stars.
- Terms of use: CDS VizieR data are free for scientific and educational use with a citation of the original paper (https://cds.unistra.fr/vizier-org/licences_vizier.html). Gaia data are released under the ESA Gaia Data Processing and Analysis Consortium terms (https://www.cosmos.esa.int/web/gaia-users/credits).

The fallback (ESA Gaia archive TAP) was not needed.

## Pipeline

Run both scripts from the repository root.

```
.venv/bin/python3 -I pipelines/milky-way/fetch.py
.venv/bin/python3 -I pipelines/milky-way/process.py
```

`fetch.py` pages through the GCNS table in blocks of 50,000 rows, ordered by the Gaia EDR3 source id. It writes seven CSV files (43 MB) into `data/raw/milky-way/`. It also writes `hip2_named.csv` with the 12 Hipparcos rows. The scripts use only the standard library, numpy and pandas. No new pip package was added.

`process.py` does these steps:

1. Load all GCNS rows (331,312).
2. Keep every row that has a G magnitude. This keeps 330,881 rows and drops 431 rows (0.13 percent). The room needs the G magnitude to size each star. This is the only row filter.
3. Take the galactic cartesian position (`xcoord50`, `ycoord50`, `zcoord50`, in parsecs) from the catalog. The catalog derives these from the median of the distance posterior.
4. Compute the absolute G magnitude from the G magnitude and the distance.
5. Compute the space velocity in the galactic cartesian frame from the parallax, the proper motion and the radial velocity. The catalog has a radial velocity for 82,353 stars (25 percent). For the other stars the radial velocity is set to zero, so those stars move with their tangential velocity only.
6. Sort the stars by distance from the Sun, nearest first. The room draws the first N stars to apply the radius slider. The manifest holds the star count for each whole parsec from 0 to 130.
7. Quantize and write the binary arrays listed below.
8. Match the 12 Hipparcos stars to GCNS rows. The script moves each Hipparcos position from epoch 1991.25 to 2016.0 with the Hipparcos proper motion, then looks for a GCNS star within 30 arcseconds with a parallax within 20 milliarcseconds. Eight stars match. Four stars have no GCNS row: Alpha Centauri, Procyon, Vega and Altair. They are too bright for Gaia. Sirius matches its white dwarf companion Sirius B, because Sirius A is also too bright for Gaia. For the four stars without a GCNS row the label uses the Hipparcos position and proper motion. The room shows those labels in a dimmer tone.
9. Write `preview.svg` from the same arrays: a perspective view from 45 parsecs, with the 1,200 stars that look brightest from that camera and a random sample (seed 7) of 1,800 of the other stars in the frame.

## Processed files (3.65 MB in total)

| File | Content |
| --- | --- |
| `data/pos.i16` | Int16 x, y, z per star. 0.004 parsec per unit. Galactic cartesian frame, Sun at the origin. |
| `data/vel.i8` | Int8 vx, vy, vz per star. 1.5 km/s per unit. Components beyond 190 km/s are clipped. This touches 653 stars (0.2 percent). |
| `data/color.u8` | Uint8 color code. Codes 0 to 254 map BP-RP from -1.0 to 5.0 magnitudes. Code 255 means no BP or RP magnitude (6,574 stars, 2 percent). |
| `data/mag.u8` | Uint8 absolute G magnitude code. Codes 0 to 255 map -2.0 to 20.0 magnitudes. |
| `data/manifest.json` | Counts, scales, the 256-entry color lookup table, and the named stars. |

## Color mapping

The color lookup table is physical. For each BP-RP value the script interpolates an effective temperature between anchor points of the dwarf star sequence (Mamajek's table, about ten percent accuracy). It then integrates the Planck spectrum of that temperature against an analytic fit of the CIE 1931 color matching functions (Wyman, Sloan and Shirley 2013), converts to sRGB, and normalizes the brightest channel to one. The result is one hue family: blue for hot stars, white near 1.0 magnitudes, orange red for cool red dwarfs. The script mixes in 15 percent white so that faint red stars stay visible on black. This is a sequential scale with a physical meaning, and the legend in the room shows it.

## What the room shows

- Every point is one star. The point size and the glow follow the apparent brightness as seen from the camera, so a star grows when the camera comes close. The count in the HUD is the number of stars within the radius slider.
- The camera orbits the Sun. When nobody touches the controls, the orbit breathes in and out between 60 and 5 parsecs over about four minutes. Drag to rotate, scroll or pinch to zoom.
- Labels appear for the Sun and 12 named stars when the camera is within 32 parsecs. A label in a dimmer tone marks a star that the GCNS does not hold (see step 8).
- The Time button starts the time mode. The stars move along their velocities at 1, 10 or 100 thousand years per second, from -500 to +500 thousand years around 2016. The time slider scrubs the same range. Stars without a radial velocity move in the sky plane only.
- The radius slider limits the view to the stars within 10 to 120 parsecs of the Sun.
- Reset returns the camera, the time and the radius to the start.

## Sound

All sound is synthesized from the data in the Web Audio API and goes through the gallery master gain.

- Drone: four low oscillators (55, 55.35, 82.4 and 110.2 Hz) through a low-pass filter. The filter cutoff falls from about 410 Hz to about 90 Hz as the number of stars in view rises from zero to the full catalog, so a fuller sky sounds deeper. A slow LFO moves the cutoff a little.
- Sparkles: the room keeps a small sphere around the camera (5.5 percent of the camera distance from the Sun, at least 0.35 parsecs). Every frame it checks 7,000 stars in a rolling window. When a star enters the sphere, it plays one short sine blip with a soft second harmonic. The pitch comes from the color code: blue stars ring about three octaves above red stars, snapped to a pentatonic scale from G3 upward. The stereo pan comes from the star's position on screen. The level comes from the absolute magnitude: bright stars ring louder. The room plays at most about 2.5 blips per second.
- Space: a convolver with a generated 3.2 second noise impulse response, a master low-pass at 3.8 kHz, and a gentle compressor.

## Known limitations

- The GCNS is complete to about G = 19 to 20 within 100 parsecs. The faintest red and brown dwarfs are missing. The catalog also holds 30,650 stars with a median distance between 100 and 120 parsecs. The radius slider can show them.
- Stars brighter than about G = 3 saturate in Gaia and are absent. Sirius A, Procyon, Vega, Altair and the two bright Alpha Centauri stars are therefore labels without points.
- The time mode moves stars on straight lines. Over 500 thousand years this ignores the galactic potential. Stars without a radial velocity (75 percent) move in the sky plane only.
- The color lookup assumes a dwarf star. Giants and white dwarfs get the color of a dwarf with the same BP-RP, which is a fair approximation of the hue.
- The position quantization of 0.004 parsecs (about 800 astronomical units) hides close binaries.
