# Liquidity in Motion

Cross-chain bridge volume as an animated chord diagram. The room plays the last 24 months, one month at a time. Liquidity moves between Ethereum, its rollups, other networks, and a multi-chain hub.

## Source

- DefiLlama dimensions API, bridge volume. Endpoints:
  - `https://api.llama.fi/overview/bridges` gives the list of bridge protocols with category and chains.
  - `https://api.llama.fi/summary/bridges/<slug>?dataType=dailyOutgoingVolume` gives the daily USD value that leaves each chain through that bridge.
  - `https://api.llama.fi/summary/bridges/<slug>?dataType=dailyIncomingVolume` gives the daily USD value that arrives on each chain through that bridge.
- Methodology: https://defillama.com/docs/api and https://github.com/DefiLlama/dimension-adapters (the `bridges` adapters).
- Terms: the DefiLlama open API is free for non-commercial use. The data stays attributed to DefiLlama.

Note: the plan named the older `bridges.llama.fi` endpoints. Those endpoints now answer HTTP 402 (paid plan). The dimensions API above is open and has the same daily series, so the room uses it. The BigQuery fallback was not necessary.

## Pipeline

1. `pipelines/bridge-flows/fetch.py` downloads the overview and the two daily series for each bridge in the categories Bridge, Canonical Bridge, Cross Chain Bridge, and Decentralized BTC that had volume in the last year. Bridge aggregators are not included, because they route through other bridges. The script caches every response in `data/raw/bridge-flows/` (85 bridges, 170 summary files, 35 MB).
2. `pipelines/bridge-flows/process.py` reads 933,053 daily chain rows and builds the output.

### Processing steps

- Days are grouped into UTC months. The window is the 24 months up to the month of the last data point. The last month is partial, and the room says so.
- Three bridges that DefiLlama marks as double counted (Stargate V2, USDT0, Citrea Token Bridge) are removed. The output keeps 82 bridges.
- Node list: Ethereum, the 11 other chains with the largest total flow in the window, one "Other networks" node, and one "Multi-chain hub" node. The 11 chains are Arbitrum, Base, OP Mainnet, zkLighter, Hyperliquid L1, Polygon, Solana, BSC, Avalanche, Monad, and Berachain. Every chain outside that list goes into "Other networks", so no value is dropped.
- Pair bridges (exactly two chains, for example the Arbitrum canonical bridge): `flow[A -> B] = max(outgoing on A, incoming on B)`. The two numbers are equal when the adapter reports both sides. The max keeps the value when the adapter reports one side only. For a canonical bridge, Ethereum-side outgoing is Ethereum to the rollup (deposits), and Ethereum-side incoming is the rollup to Ethereum (withdrawals).
- Multi-chain bridges (three or more chains, for example Across, Relay, CCTP, LayerZero, Portal): the API gives value per chain and not per route. `flow[chain -> hub] = outgoing on the chain` and `flow[hub -> chain] = incoming on the chain`. The hub arc therefore counts each transfer twice, once on each end.
- Values are rounded to thousands of USD.
- The hero number is the sum of the outgoing volume of all bridges in the month. This is the same definition that DefiLlama uses for bridge volume.

### Sampling rule

There is no sampling. Every day and every bridge in the window is in the output. The only reduction is the grouping of chains into "Other networks" and of routes into the hub.

### Output

- `rooms/bridge-flows/data/flows.json` (32 KB): 24 months, a 14 x 14 matrix per month (986 non-zero cells), per-bridge monthly totals for 82 bridges (1,968 values), and the monthly totals.
- `rooms/bridge-flows/preview.svg`: a static chord still of the last complete month, drawn by `process.py`.

## What the room shows

- Each arc is a network. Its length is the volume that left plus the volume that arrived in the month.
- Each ribbon is a flow between two nodes. The arrow end points to the destination.
- The hero number is the total bridge volume of the month.
- The side list ranks the ten largest bridges of the month. Blue bars are pair bridges, violet bars are multi-chain bridges.
- The chips under the ring give the monthly volume of every node, also the ones too small for a label on the ring.
- The scrubber, the previous and next buttons, and play or pause control the month. The animation interpolates the matrices between two months.

Colors: Ethereum blue, Ethereum rollups orange, other networks aqua, multi-chain hub violet. The four colors passed the gallery palette validator in light mode.

## Sound

- Each node has a fixed note on a pentatonic scale (A3 upward), assigned by its position on the ring.
- When the month changes, the room ranks the nodes whose monthly volume grew by more than 3 percent and plays a bell for at most five of them. The bells are spread over the tween. The bell level grows with the absolute increase.
- A bell is a two-operator FM tone (carrier plus a modulator at 1.41 times the frequency) with a short attack, a long decay, and a reverb from a generated noise impulse response.
- The stereo pan of each bell follows the angle of its arc on the ring.
- A soft pad (two detuned triangle waves and a sine through a low-pass filter) plays all the time. Its level and its filter cutoff follow the total monthly volume.
- Every node goes through a low-pass filter and the master gain, so the sound toggle mutes everything.

## Limitations

- Multi-chain bridges have no route information in this API, so the room cannot show, for example, Arbitrum to Base through Across. The hub shows each chain's in and out value only.
- The hub arc counts each transfer twice (source side and destination side).
- USD values come from DefiLlama's price feeds at the time of the transfer. Large single transfers make visible spikes (DefiLlama lists them as genuine spikes).
- The last month is partial.
- The group of a chain (rollup or other network) is a fixed list in `process.py`.

## Packages

No extra pip packages. The pipeline uses the standard library only. Screenshots use the Playwright package that the repository already has.
