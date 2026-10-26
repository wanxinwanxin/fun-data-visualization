# The Citation Galaxy

The citation network of United States Supreme Court opinions, drawn as a galaxy that grows year by year.

## Source

- Caselaw Access Project (CAP), United States Reports, volumes 1 to 572: https://static.case.law/us/
  The Free Law Project hosts this archive. Each volume has one `CasesMetadata.json` file.
  The file lists every case in the volume with its name, decision date, citations, and a `cites_to` list.
  The `cites_to` list gives the CAP case id of each cited case.
- Terms of use: CAP released the full data set for free public use in March 2024 (see https://case.law/).
  The opinions are works of the United States government and are in the public domain.
- The pipeline also downloads d3 7.9.0 (ISC license) from jsDelivr. The offline force layout uses `d3-force` in Node.

### Why not the CourtListener bulk files

The brief named the CourtListener bulk data as the primary source. The `citation-map` file keys its edges on opinion ids.
The only file that maps opinion ids to clusters, dates, and names is `opinions-*.csv.bz2`, which is 55 GB.
That file exceeds the raw download limit (2 GB) and the time budget of this room. The REST API needs an API token.
The named fallback, the Fowler and Jeon network at jhfowler.ucsd.edu, did not resolve in DNS.
CAP data is the same public record, and the Free Law Project (the CourtListener organization) hosts it.

### Supreme Court Database (SCDB) issue areas

`fetch.py` tries to download the SCDB case-centered files for the issue area of each case.
The SCDB server (scdb.wustl.edu) did not answer during the build. The room therefore shows no issue areas.
Each constellation gets the name of its brightest star instead. When the SCDB files are present in
`data/raw/court-galaxy/`, `process.py` adds the most common issue area to each constellation.

## Pipeline

Run from the repository root:

```
.venv/bin/python3 -I pipelines/court-galaxy/fetch.py
.venv/bin/python3 -I pipelines/court-galaxy/process.py
```

`fetch.py` downloads the 572 volume files (393 MB) and `d3.min.js`. `process.py` needs `node` on the PATH.

Extra pip package: `networkx` (Louvain communities and spanning trees). `requests` and `numpy` were already present.

### Processing steps

1. Read every volume file. Keep the cases that the Supreme Court of the United States decided (the early volumes also hold
   Pennsylvania cases). Collect every `cites_to` case id as a citation edge.
2. Clean the edges. Drop self citations, edges to cases outside the table, and edges that point forward in time.
3. Count the in-degree of each case on the full network. The in-degree in the room comes from this full count.
4. Trim the network to a drawable size (the exact rule is below).
5. Find communities with the Louvain method (seed 13) on the kept network. Up to twelve of the largest communities with at least
   150 members are the constellations.
6. Compute the layout with `d3-force` in Node (`layout.cjs`, 300 ticks). The radius of a star follows the rank of its
   decision year, with equal area per case, so old cases sit near the center and new cases near the rim. The initial angle
   follows the community. Many-body repulsion, link springs, and a radial spring shape the result. The 99.5th percentile
   radius becomes 1.
7. For each constellation, pick a compact set of up to 12 bright stars. Start at the brightest star of the community and add
   the brightest remaining member within 0.22 galaxy radii of the set. Join the set with a minimum spanning tree.
8. Write `data/nodes.json`, `data/edges.u16`, `data/meta.json`, and `preview.svg`.

### Sampling rule

- The archive holds 329,995 cases. 328,456 are Supreme Court cases. Most of them are short orders.
- 559,763 clean citation edges join 158,652 connected cases. 169,804 cases have no edge and are not drawn.
- Kept stars: every connected case with in-degree 10 or more (11,468 cases), plus a seeded random sample
  (`random.Random(13)`) of 532 other connected cases, for 12,000 stars in total.
- Kept edges: 149,363 edges join the kept stars. A seeded random sample of 40,000 of them is drawn.
  The in-degree of each star, and therefore its size and color, still comes from the full network.

### Output files

- `data/nodes.json`: columnar arrays for 12,000 stars: short name, official citation, year, in-degree, x, y,
  community id (-1 for dust), and SCDB issue area (0 when unknown).
- `data/edges.u16`: 40,000 pairs of Uint16 star indices (citing, cited), sorted by the citing year.
- `data/meta.json`: counts, the year range, and the constellations with their stars, lines, and labels.

Total size: about 1.0 MB.

## What the room shows

Every star is a Supreme Court opinion. Its radius follows the decision year: old opinions sit near the center and new opinions
near the rim. Its size follows the number of citations it received. Gold stars are the 300 most cited opinions. Pale blue stars
are the other opinions. A line is a citation. It flashes in the year of the citing opinion and then settles to a faint trace.
Constellation lines join the brightest stars of one citation community. The label gives the name of the leading case.
The outer dial is the timeline. Concentric rings mark the radius of 1800, 1850, 1900, 1950, and 2000.

The clock runs three times faster before 1850, where few drawn cases exist, and slows down to the selected speed by 1870.
Controls: play and pause, a year slider, a speed selector, and a search box. Hover or tap a star to read the case name,
its citation, its year, and its in-degree. A `?year=1990` URL parameter starts the clock at that year.

## Sound

- A drone with two detuned sawtooth voices, a fifth, and an octave moves its root with the century:
  A1 before 1800, C2 in the 1800s, D2 in the 1900s, and E2 after 2000. The number of citations that land per second
  opens the low-pass filter of the drone.
- Each citation that lands on a star with at least 20 citations plucks a string. The pluck is Karplus-Strong synthesis:
  a noise burst feeds a one-period delay line with low-pass feedback. The pitch is a note of a major pentatonic scale over
  three octaves. More citations give a deeper note. The stereo pan follows the horizontal position of the cited star.
  At most three plucks start per frame and at most one every 55 ms.
- A soft high sine ping marks the ignition of a gold star.
- All sound passes through a low-pass filter at 3.4 kHz and a convolver with a generated noise impulse response.
  Every node connects to the master gain, so the sound toggle mutes the room.

## Known limitations

- CAP resolves citations by reporter page. Citations that the extractor could not resolve are missing, so old cases cited
  only by nominative reporter in a free-text form may have a lower in-degree than the true count.
- The in-degree counts citations from every case in the United States Reports, including short orders. Orders that cite
  one procedural case many times (for example Martin v. District of Columbia Court of Appeals) make that case bright.
- The archive ends with volume 572 (2013). Later opinions are absent.
- The drawn lines are a 27 percent sample of the citations between the drawn stars.
- The communities come from the sampled network and from one Louvain run. They are a data-driven grouping, not a legal taxonomy.
