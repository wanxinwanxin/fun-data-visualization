# Where Curiosity Goes

A playful map of where English Wikipedia readers click next. The viewer picks a start article, and the room shows the eight articles that readers clicked on most from that page. Each click on a blob moves the center and opens the next hop. A random walk mode lets a simulated reader wander by the real click probabilities.

## Source

- Wikimedia Clickstream, English Wikipedia, month 2026-09.
  File: `https://dumps.wikimedia.org/other/clickstream/2026-09/clickstream-enwiki-2026-09.tsv.gz` (479 MB).
  Listing: `https://dumps.wikimedia.org/other/clickstream/`
- License: the Wikimedia clickstream dumps are released under CC0 1.0 (public domain dedication). See `https://dumps.wikimedia.org/other/clickstream/readme.html`.
- Columns: `prev`, `curr`, `type`, `n`. A row says that readers went from `prev` to `curr` `n` times in the month. Wikimedia only publishes pairs with `n >= 10`.

The fetch script reads the directory listing, picks the latest month that has an enwiki file, and streams it to `data/raw/wiki-attention/`. If the latest month fails, it tries the month before. The raw file is deleted after processing to save disk. Run `fetch.py` again to get it back.

## Sampling rule

The processing keeps only rows of `type = link`. These rows are clicks on a link inside an article. Rows of type `external` (search engines, other sites) and `other` are dropped. Pages in navigation namespaces are dropped as `prev` and as `curr`: `Main_Page`, `Special:`, `Wikipedia:`, `Portal:`, `Help:`, `File:`, `Category:`, `Template:`, `Talk:`, `User:`, `Draft:`, `Module:`, `Book:`, `MediaWiki:`, `TimedText:`, `Wikipedia_talk:`, `User_talk:`, and the redirect-only pages `Hyphen-minus`, `-`, `Wiki`.

Counts for the month 2026-09:

- Rows in the file: 33,553,254.
- Link rows after the namespace filter: 21,241,003, over 3,126,014 distinct destination articles.
- Nodes in the output: 3,041 articles. Edges in the output: 4,209. Expanded nodes (nodes with children): 539.

The script streams the gz file four times and never loads it whole:

1. Pass 1 sums incoming link clicks per article. This gives the top 300 articles and the top 50 overview list (`top50` in the output).
2. Pass 2 collects the outgoing link rows of the 22 seeds. Each seed keeps its top 8 destinations by `n` (depth 1).
3. Pass 3 collects the outgoing link rows of every depth-1 node. Each keeps its top 8 (depth 2).
4. Pass 4 collects the outgoing link rows of the top 3 depth-2 children of each depth-1 node. Each keeps its top 8 (depth 3).

Cap rule: every expanded node keeps at most 8 children, ranked by `n`. Every node carries its total incoming link clicks from pass 1. Every expanded node carries its total outgoing link clicks (`out`), so that the room can show the share of each link. The output is one shared adjacency list. A tree per seed is the walk from the seed through `edges`. Shared articles appear once.

## Seeds

The 22 seeds are a curated set from the top 300 articles by incoming link clicks in 2026-09. They cover history, news, sport, film and TV, people, science, and places. The list is in `pipelines/wiki-attention/seeds.json`:

September 11 attacks, World War II, 2026 Iran war, 2026 Swedish general election, Assassination of Charlie Kirk, Deaths in 2026, 2026 Asian Games, 2026 Formula One World Championship, FC Barcelona, List of highest-grossing films, The Odyssey (2026 film), Avengers: Doomsday, Monster: The Lizzie Borden Story, Elizabeth Holmes, Donald Trump, Charles III, Warren Beatty, Michael Jackson, ALS, Hydrocephalus, United States, China.

## Processed files

- `data/graph.json` (150 KB): `month`, `rule`, `seeds` (id and label), `nodes` (`[title, incoming]`), `edges` (`id -> [[childId, n], ...]`), `out` (`id -> outgoing total`), `top50`.
- `preview.svg`: the first seed and its eight destinations, drawn from the real data by `process.py`.

## What the room shows

- The coral blob in the center is the current article. Its speech bubble gives the arrivals through links in the month and the number of readers who clicked on to another article.
- The sky-blue blobs around it are the top 8 destinations. Rank 1 is at the top, and the ranks go clockwise.
- Ribbon width is the number of clicks on that link in the month, relative to the biggest link in the view.
- Blob size is the total number of clicks that arrived at that article from any link in the month (one scale for the whole room).
- Confetti bits ride the ribbons. The rate is tied to `n`: the biggest link in the view sends about six bits per second, the others fewer in proportion. One minute of confetti stands for the whole month of clicks from the center article. The counter in the caption adds the readers that the landed bits carried.
- The mustard blob is the article the viewer came from. A click on it goes back one hop. The breadcrumb trail under the chips does the same for any earlier hop.
- The candy chips at the top are the seeds. The dice button jumps to a random seed. The random walk button lets a simulated reader pick the next article with probability proportional to `n`, every 3.4 seconds. At the end of a trail (depth 3) the walk jumps to a new seed.
- The confetti colors are decoration only. They carry no meaning.

## What the sound means

The sound is a small marimba made with the Web Audio API. Every note is two slightly detuned sine partials plus a short triangle "tok" two octaves up, with a 5 ms attack and an exponential decay. The notes go through a low-pass filter at 3.4 kHz, a convolution reverb with a generated noise impulse response, and a compressor, then into the master gain of the gallery.

- A note plays each time a confetti bit lands on a blob. More clicks on a link means more notes from that ribbon.
- Pitch follows the rank of the destination: the top link plays the lowest note (C4), and the ranks 2 to 8 climb a pentatonic scale (D4, E4, G4, A4, C5, D5, E5).
- Stereo pan follows the screen position of the blob that the bit landed on.
- A soft low chord (C3, E3, G3) plays on each move to a new center. Going back plays the same chord in falling order.
- At most 9 notes per second play, with at least 45 ms between notes.

## Pip packages

None beyond the repository base. Both scripts use the standard library only.

## Known limitations

- The clickstream only lists pairs with at least 10 clicks, and only link clicks are used. Arrivals from search engines and from outside Wikipedia are not in the room.
- The map holds three hops from each seed. A trail ends at depth 3, and the random walk then restarts at a new seed.
- The `out` total of an article counts link clicks to all destinations with `n >= 10`, so the shares are shares of that total.
- Ribbon width is relative to the biggest link in the current view, so the widths change scale on each move. Blob size uses one scale for the whole room.
- Titles use the article titles from the dump, with underscores replaced by spaces. Long titles are cut with an ellipsis in the bubbles.
