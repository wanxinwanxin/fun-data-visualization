# The Builder Market

A time-lapse of the Ethereum block builder market since the Merge. The room shows who builds the blocks, week by week, and how fast the market became concentrated.

## Source

- Data set: `bigquery-public-data.crypto_ethereum.blocks` on Google BigQuery. The data set is part of the Google Cloud public data set program and is maintained with the open source `blockchain-etl` tools (https://github.com/blockchain-etl/public-datasets, MIT license for the tools). Use of the data set is subject to the Google Cloud terms for public data sets. Attribution: Google Cloud, blockchain-etl.
- Columns used: `number`, `timestamp`, `miner` (the fee recipient), `extra_data`, `gas_used`, `base_fee_per_gas`, `transaction_count`.
- Range: from the Merge block (2022-09-15 06:42:42 UTC, block 15537394) to the latest block in the table at fetch time (block 26278070, 2026-10-26 16:30 UTC).
- Blocks in range: 10,740,675 (no sampling for the weekly and daily series).
- Fetch date: 2026-10-26.
- The fallback source (mevboost.pics or the Flashbots relay API) was not needed.

## Pipeline

`pipelines/builder-market/fetch.py` runs five queries with the `bq` command line tool. Each query runs as a dry run first. The largest query scans 2.4 GB. The script stops if a query scans more than 100 GB. The script writes CSV files to `data/raw/builder-market/`.

`pipelines/builder-market/process.py` reads the CSV files and writes:

- `rooms/builder-market/data/series.json` (211 kB): the fixed builder list, the weekly share matrix (215 weeks x 16 columns), weekly block counts, weekly HHI, weekly median base fee, the daily HHI (1503 days), daily shares, daily block counts, and daily median base fee.
- `rooms/builder-market/data/ticker.bin` (402 kB): one 8 byte record per block for the latest 7 days (50,240 blocks). Layout: Uint8 builder index, Uint8 slot gap, Uint16 transaction count, Float32 base fee in gwei, little endian.
- `rooms/builder-market/data/ticker.json`: the first and last block number, the count, and the record layout.
- `rooms/builder-market/data/mapping.md`: the raw tag table below.
- `rooms/builder-market/preview.svg`: the card image, drawn from every fourth week of the real weekly shares.

Total processed data: 0.62 MB. No extra pip packages are needed. The scripts use only the standard library.

## Sampling rule

- The weekly and daily series use every block in the range. There is no sampling.
- The ticker uses every block with a timestamp in the 7 days before the latest block in the table. That is 50,240 blocks and 50,401 slots. Missed slots are slots with no block, derived from the time gap between blocks (gap in seconds divided by 12, rounded).
- Weeks start on Thursday, so that the first week starts on the Merge day (2022-09-15). The last week is partial.
- At widths of 760 px or less, the page shows one ridge per calendar month instead of one ridge per week. Monthly shares are block-weighted means of the daily shares.

## Builder labels

The builder is read from the block `extra_data` field, decoded as UTF-8. The label rule is a list of case-insensitive substring matches. The first match wins. Blocks whose tag is empty or looks like a client default (`geth`, `Nethermind`, `besu`, `erigon`, `reth`) get the label `vanilla`. These blocks were most likely built locally by the validator and not through MEV-Boost. All other unmatched tags keep their raw text as a separate entity.

The 15 labels with the most blocks get their own column. All other labels fold into `other`. The fixed column order is: Titan, beaverbuild, vanilla, BuilderNet, rsync, Flashbots, Quasar, builder0x69, bloXroute, Eureka, Blocknative, Builder+ (BTCS), eth-builder, f1b.io, jetbldr, other.

Notes on the mapping:

- `BuilderNet (Flashbots)`, `BuilderNet (Nethermind)`, `BuilderNet (Beaver)` and `BuilderNet` share one fee recipient (`0xdadb0d...`) and are one TEE builder network, so they are one label. The classic Flashbots builder (`Illuminate Dmocratize Dstribute`) stays a separate label.
- `rsync-builder.xyz` and `@rsyncbuilder` share one fee recipient and are one label.
- `builder0x69`, `@builder0x69`, `by builder0x69` and `by @builder0x69` are one label.
- Some tags such as `Nethermind` and the empty tag come from thousands of fee recipients. This supports the `vanilla` reading.

The 40 most common raw tags (non-printable bytes shown as `?`):

| Raw extra_data tag | Blocks | Fee recipients | Label | Column |
|---|---:|---:|---|---|
| `Titan (titanbuilder.xyz)` | 3,224,954 | 7707 | Titan | Titan |
| `beaverbuild.org` | 2,354,535 | 3600 | beaverbuild | beaverbuild |
| `rsync-builder.xyz` | 577,450 | 4 | rsync | rsync |
| `Illuminate Dmocratize Dstribute` | 559,715 | 859 | Flashbots | Flashbots |
| `? Quasar (quasar.win) ?` | 493,120 | 3 | Quasar | Quasar |
| `(empty)` | 429,789 | 8526 | vanilla | vanilla |
| `BuilderNet (Flashbots)` | 366,015 | 14 | BuilderNet | BuilderNet |
| `@rsyncbuilder` | 229,203 | 4 | rsync | rsync |
| `BuilderNet (Nethermind)` | 204,057 | 3 | BuilderNet | BuilderNet |
| `BuilderNet (Beaver)` | 196,820 | 4 | BuilderNet | BuilderNet |
| `Powered by bloXroute` | 181,070 | 2483 | bloXroute | bloXroute |
| `@builder0x69` | 177,033 | 57 | builder0x69 | builder0x69 |
| `builder0x69` | 137,257 | 113 | builder0x69 | builder0x69 |
| `BuilderNet` | 112,978 | 3 | BuilderNet | BuilderNet |
| `by builder0x69` | 106,805 | 2263 | builder0x69 | builder0x69 |
| `Nethermind` | 103,993 | 3547 | vanilla | vanilla |
| `Eureka (eurekabuilder.xyz)` | 96,433 | 6 | Eureka | Eureka |
| `Made on the moon by Blocknative` | 69,891 | 642 | Blocknative | Blocknative |
| `by @builder0x69` | 66,307 | 33 | builder0x69 | builder0x69 |
| `?????geth?go1.20.2?linux` | 59,729 | 2909 | vanilla | vanilla |
| `Builder+ www.btcs.com/builder` | 55,930 | 11 | Builder+ (BTCS) | Builder+ (BTCS) |
| `https://eth-builder.com` | 50,971 | 28 | eth-builder | eth-builder |
| `f1b.io` | 42,485 | 4 | f1b.io | f1b.io |
| `jetbldr.xyz` | 42,055 | 34 | jetbldr | jetbldr |
| `?????geth?go1.19.1?linux` | 33,971 | 280 | vanilla | vanilla |
| `?????geth?go1.21.6?linux` | 31,014 | 1590 | vanilla | vanilla |
| `bobTheBuilder.xyz` | 29,503 | 11 | bobTheBuilder | other |
| `BuildAI (https://buildai.net)` | 28,616 | 1 | BuildAI | other |
| `?????geth?go1.20.3?linux` | 25,768 | 2326 | vanilla | vanilla |
| `bombora.build ?` | 25,382 | 319 | bombora | other |
| `?????geth?go1.24.2?linux` | 22,428 | 1604 | vanilla | vanilla |
| `Gambit Labs (https://gmbit.co)` | 20,776 | 459 | Gambit | other |
| `?????geth?go1.25.1?linux` | 20,686 | 936 | vanilla | vanilla |
| `manta-builder` | 20,178 | 1 | manta | other |
| `?????geth?go1.22.6?linux` | 16,541 | 654 | vanilla | vanilla |
| `@penguinbuild.org` | 16,511 | 144 | penguinbuild | other |
| `?????geth?go1.22.4?linux` | 16,139 | 679 | vanilla | vanilla |
| `?????geth?go1.20.7?linux` | 15,674 | 1820 | vanilla | vanilla |
| `?????geth?go1.21.7?linux` | 12,135 | 649 | vanilla | vanilla |
| `Nethermind v1.36.0` | 11,691 | 527 | vanilla | vanilla |

## HHI

The Herfindahl-Hirschman index (HHI) is the sum of the squared market shares, scaled to 0 to 10000. The room computes the HHI per day and per week over the fine labels (each builder label and each unmatched raw tag is one entity, `vanilla` is one entity). The thresholds on screen (1500 and 2500) are the usual antitrust guideline values.

## What the room shows

- One ridge per week since the Merge, printed from top to bottom like terminal output. The x position is the builder column in the fixed order above. The ridge height is the share of blocks in that week (100 percent equals the full amplitude). The current week glows in cyan with a marker in the series color for the top six builders. Older ridges fade.
- The `ridge --scale fee` command scales each ridge by the square root of the median base fee of its week, so that fee spikes become visible.
- Dashed magenta lines mark the Merge (2022-09-15), Shapella (2023-04-12), Dencun (2024-03-13), and Pectra (2025-05-07).
- The panel on the right shows the current frame, the block count, the HHI with a label, the median base fee, the top builder, a bar per builder column, and a strip chart of the daily HHI with a cursor.
- The ticker tape at the bottom scrolls through every slot of the last 7 days. Each cell is one block, colored by builder (six series colors for the top six builders, gray for the rest). A dark outlined cell is a missed slot. The readout above the tape shows the block number, time, builder, base fee, and transaction count at the head of the tape.
- Controls: `pause`/`play`, `speed 1x/4x/16x`, `ridge --scale share|fee`, `step +1`, the `seek` scrubber, and the keys Space, Left, and Right.

## Sound

The sound is a data-driven arpeggio on a soft sawtooth synth (two detuned sawtooth oscillators, a low-pass filter with an envelope, a gain envelope, a feedback delay, and a convolution reverb from generated noise).

- Each builder column has one note of a D minor pentatonic scale, from D3 for Titan up through three octaves to the `other` column.
- The arpeggiator picks the next builder with a smooth weighted round robin over the shares of the current frame. A builder with 50 percent share plays every second note. A concentrated market sounds like one or two repeated notes. A diverse market sounds like a run through the scale.
- The low-pass cutoff opens as the HHI falls, so a diverse market sounds brighter.
- The stereo pan follows the column position, from left for Titan to right for `other`.
- The low pulse is the ticker: one pulse per block as the tape advances. The pitch of the pulse rises with the base fee of the block (log scale, 42 Hz at 0.01 gwei to 64 Hz at 100 gwei), and the pulse level rises with the transaction count. At 4x and 16x speed, only every 4th or 16th block pulses.
- Every node routes through a compressor into the gallery master gain, so the mute button silences the room.

## Known limitations

- The builder label comes from a self-declared tag. A builder can change its tag or leave it empty, and a block with an empty tag may still come from a builder. The `vanilla` share is therefore an upper bound on locally built blocks.
- The tag mapping is a hand-written list. Small builders with tags that this list does not cover stay as their raw tag and fold into `other`.
- Slot gaps are derived from block timestamps and not from consensus layer data, so a long outage counts as many missed slots.
- The median base fee uses `APPROX_QUANTILES` in BigQuery, which is approximate.
- At phone width the ridges are monthly, so the time-lapse has 50 frames instead of 215.
