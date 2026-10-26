# What the County Worried About

A halftone map of the words that US newspapers printed, by state and by decade, from 1800 to 1963. The room is one of the Thirteen Rooms gallery.

## Source

- Library of Congress, Chronicling America: Historic American Newspapers. https://www.loc.gov/collections/chronicling-america/
- Access method: the loc.gov JSON API, facet index endpoint `https://www.loc.gov/collections/chronicling-america/index/location_state/?q=<term>&dates=<y1>/<y2>&dl=page&fo=json`. One response lists every state with the number of newspaper pages whose OCR text contains the term.
- Map shapes: us-atlas 3.0.1, `states-10m.json` (US Census Bureau cartographic boundaries, ISC license). https://github.com/topojson/us-atlas
- Terms of use: the newspapers in Chronicling America are in the public domain. The Library of Congress asks API users to stay under 20 requests per 10 seconds for this endpoint. The fetch script waits 3 seconds between requests.

The older endpoint `chroniclingamerica.loc.gov/search/pages/results/` now redirects to a 404 page. The room does not use it.

## What the pipeline does

`pipelines/local-news/fetch.py`

1. Downloads `states-10m.json` from jsdelivr.
2. For each of 17 decades (1800s to 1960s), requests the state facet with no search term and `dl=page`. The counts are the total number of digitized pages per state per decade.
3. For each of 19 topic keywords and each decade, requests the state facet with `q=<keyword>`. The counts are the pages per state whose OCR text contains the keyword.
4. Caches every response in `data/raw/local-news/<decade>_<term>.json`. A rerun only downloads the missing files. Retries on 429 and 5xx with exponential backoff.

The keywords are single words, because the search API treats `OR` as a word. The 19 topics are: war, slavery, cholera, influenza, railroad, telegraph, gold, cotton, drought, flood, strike, tariff, election, prohibition, suffrage, lynching, automobile, radio, atomic.

`pipelines/local-news/process.py`

1. Reads the cached facet files.
2. Keeps the 50 states and the District of Columbia. Drops the territories (Puerto Rico, Guam, American Samoa, Northern Mariana Islands, Virgin Islands) and one facet title that is not a US state ("Piedmont").
3. Computes `share = pages with the keyword / all pages` for each topic, decade and state. A cell with fewer than 300 pages becomes `null`.
4. Computes the national share per topic and decade, and the all-time national share per topic.
5. Computes `lift = share / all-time national share` and stores the top 3 topics per state and decade by share and by lift.
6. Writes `rooms/local-news/data/topics.json` and `rooms/local-news/data/states.json` (the us-atlas topology without the territories).
7. Draws `rooms/local-news/preview.svg`, a halftone grid of the national share per topic and decade.

## Sampling rule

There is no sampling. Every count is the full count that the Library of Congress search index returns for the whole collection. The only filter is the 300-page minimum per state and decade.

## Record counts

See the final report in the git history, and the `pages_national` array in `topics.json`, for the number of pages per decade. The collection holds about 21 million pages in total. The processed data has 19 topics x 17 decades x 51 states = 16,473 cells.

## What the room shows

- Each state is a halftone screen. The dot area is proportional to the share of pages in that state and decade that print the chosen word. The scale is fixed per topic, so decades compare with each other.
- The decade dial steps through 17 decades. The press runs on its own, or the visitor drags the dial.
- The topic column on the left is a stack of headlines. Each headline shows the national share for the current decade.
- The headline mode types one word over each state: the topic with the highest lift in that state and decade. States that are too small to carry a word appear in "Late dispatches".
- The strip under the dial shows all 17 decades for the chosen topic as small multiples.
- "By the numbers" lists the six states with the highest share, and the national share.

## What the sound maps to

All sound is synthesized in the browser. Every node routes through the gallery master gain.

- Typewriter key: one click per typed letter, in the masthead and in the headline mode. The stereo pan follows the position of the state on the map (west is left, east is right).
- Carriage return ding: the decade changes, or the masthead finishes.
- Page turn: a filtered noise sweep at each decade change.
- Press rumble: brown noise through a low-pass filter. The level and the filter cutoff follow the national share of the chosen topic in the current decade. The throb rate follows the fraction of states where the share exceeds 2 percent.
- Dot fill: during the halftone fill-in, soft ticks appear with a density that follows the number of dots on screen.
- A compressor, a 6.5 kHz low-pass filter and a generated noise reverb keep the mix soft.

## Known limitations

- OCR text is noisy. A short word such as "war" or "gold" can match OCR errors and unrelated uses (for example, "Gold Street"). Shares are an upper bound on true topic coverage.
- The collection is not a census of the press. Which titles are digitized depends on state partner programs, so the state coverage is uneven and changes by decade. The 1800s and 1810s have fewer than 50,000 pages each, and the 1960s have 27 states.
- A page is counted once per keyword. A page that mentions a word once counts the same as a page that mentions it fifty times.
- The all-time national share that defines lift is weighted by pages, so the 1880s to 1920s dominate it.
- Fonts (Anton and Special Elite) load from jsdelivr. Without network access the page falls back to system fonts.

## Rebuild

```
.venv/bin/python3 -I pipelines/local-news/fetch.py
.venv/bin/python3 -I pipelines/local-news/process.py
```

The fetch takes about one to two hours because of the 3-second throttle and slow facet queries. No extra pip packages are needed beyond `requests`, which the gallery already installs.
