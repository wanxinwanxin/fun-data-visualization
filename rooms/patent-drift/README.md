# Where Ideas Come From

Room slug: `patent-drift`. A blueprint of which technology fields US patents borrow their ideas from, year by year, from patent citations.

## Sources

- Google Patents Public Data on BigQuery, table `patents-public-data.patents.publications`. The table holds publications, their CPC codes and their citation lists. Google and the patent offices give this data under the Creative Commons Attribution 4.0 license (CC BY 4.0). See https://console.cloud.google.com/marketplace/product/google_patents_public_datasets/google-patents-public-data.
- CPC titles from `patents-public-data.cpc.definition` (CPC scheme published by the EPO and the USPTO, CC BY 4.0).

The query is in `pipelines/patent-drift/query.sql`. The dry run reports 30.5 GB of processed bytes. The real run uses `--maximum_bytes_billed=250000000000` as a guard.

## Sampling rule

There is no sampling of patents. The query reads every US patent grant with a publication date from 1985-01-01 to 2024-12-31 and a kind code of A (grants before 2001), B1 or B2. For each citation in the grant's citation list, the query joins the cited publication by publication number. The cited publication can come from any country. A citation counts only when both sides have at least one CPC code. Each publication maps to one code: the CPC code with the `first` flag, or the first code in the list when no flag is set.

The query writes two levels:

- Level X: citing 4-character class, cited 3-character subclass, year, count. This level is complete. It has 1,286,106 rows after the filter below.
- Level C: citing 4-character class, cited 4-character class, year, count. This level keeps only pairs with 20 or more citations in that year. It has 510,398 rows.

Rows where the cited code is in CPC section Y (tagging codes such as Y02) are dropped. They are 0.28 percent of all citations and never occur on the citing side. The processed data holds 224,212,800 citations from 679 citing classes.

## Processing steps (`process.py`)

1. Map each cited subclass to one of eight fixed groups: A, B, C, DE (sections D and E together, the two smallest), F, G (section G without G06), G06 (computing), H. The citing side uses the same groups.
2. Build 49 citing entities: all US grants, the eight groups, and the 40 citing classes with the most citations. For each entity, store a 40 by 8 matrix of citation counts (year by cited group).
3. For each entity and year, keep the strongest class to class pairs from level C: 16 pairs for the all and group entities, 12 for a class entity. Pairs where the citing class and the cited class are the same are excluded. Those self-citations are the largest pairs everywhere and say nothing about borrowing. Only pairs with 20 or more citations exist at this level, so a class with few citations in early years can show fewer pairs.
4. Shorten CPC titles to the text before the first semicolon, in sentence case, 46 characters at most.
5. Write `data/flows.json` (573 KB) and draw `preview.svg` from the all-grants matrix.

## What the room shows

The stream chart shows, for the selected citing field, the share of each cited group per year. The shares add to 100 percent. The plotter draws each layer boundary with a pencil, then fills the layer with hatching. The year cursor moves through 1985 to 2024 at about one year per second. Two callouts give the largest cited group and the computing share in the current year. The ribbons on the right show the strongest citation flows between two different classes in the current year, colored by the cited group. The parts list selects the citing field: all grants, one group, or one of the 40 largest classes. The title block in the lower right follows the selection and the year.

The main finding: computing (G06) grows from 1.5 percent of cited patents in 1985 to about 14 percent in 2024, and it appears in the stream of almost every citing field. Human necessities (mostly medical technology, A61) grows from 13 percent to 30 percent of all citations.

## Sound

- Eight sine tones form an A major ninth chord (A2, E3, B3, C#4, E4, G#4, B4, F#5), one tone per cited group in legend order. The gain of each tone follows that group's share in the current year (gain = 0.055 times share to the power 0.75). The tones pan from left (A) to right (H).
- A pencil scratch (a short band-pass filtered noise burst, panned by the pen position) sounds every 95 milliseconds while the plotter draws a line.
- A page turn (a noise burst with a low-pass sweep from 3200 Hz to 260 Hz) sounds at each year change.
- All sound goes through a low-pass filter at 1500 Hz and a convolution reverb with a generated noise impulse response, then into the master gain.

## Rebuild

```
.venv/bin/python3 -I pipelines/patent-drift/fetch.py
.venv/bin/python3 -I pipelines/patent-drift/process.py
```

`fetch.py` needs the `bq` command line tool with an authenticated Google Cloud account. No extra pip packages are needed.

## Known limitations

- CPC codes are the current classification, applied to old patents too. Codes such as H10D and H10P come from the 2023 reclassification of semiconductor patents, so they appear in years before they existed.
- The primary CPC code is one label per patent. Patents with many fields count once, in one field.
- Citation lists in the table mix examiner and applicant citations. The count per patent grows strongly after 2000, mostly because applicants list more references.
- The ribbons use only pairs with 20 or more citations. Small classes in early years can show fewer than 16 ribbons.
- Sections D and E are folded together to keep the categorical palette at eight colors.
