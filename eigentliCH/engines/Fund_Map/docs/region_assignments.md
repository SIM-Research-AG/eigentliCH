# Geographic region assignments

The Fund Map register carried no geography. What the estimator loaded as `region` came from the
seed's `Risk Signal` column over (Europe, Americas, Asia, Sino, Global), which is the regime signal
scope and not a place: block 1 is `MXWO0FD Index`, a World index, tagged Europe.

A `Region` column over the seven-value constraint vocabulary (Switzerland, Europe, East Asia, South
Asia, North America, South Pacific, Others) was therefore added, and is published on the ReturnSet as
`region_geo`. The signal scope is published separately as `region_scope`. The two are never derived
from one another.

Assignments come from each block's Bloomberg ticker, the only identifier in the register that states
where the exposure actually is. This file records the basis for every one, so an assignment that was
a judgement is not mistaken for one that was read.

Read from the ticker: 35. Inferred: 10. Flagged for review: 9.

## Flagged, needing Nicolas

These are cases where the ticker contradicts the block's name or scope, or where the vocabulary
cannot represent the exposure. The assignment follows the ticker, because the ticker is what the
return history was estimated from.

| id | block | region | issue |
|---|---|---|---|
| 14 | ASEAN Equities | East Asia | MXSO, MSCI ASEAN. Southeast Asia straddles the East and South Asia slots and the vocabulary cannot separate it |
| 17 | Global Real Estate indirect | North America | the block is named Global Real Estate indirect but the ticker IYR US Equity is a United States REIT ETF |
| 20 | Global Bonds | Others | BGAUTRCH is the global aggregate, but the block's signal scope reads Americas |
| 24 | Private Debt | Others | SPLGAL is a United States leveraged-loan index, but the block's signal scope reads Europe |
| 30 | Asia Pacific Arbitrage | East Asia | Asia Pacific arbitrage spans East Asia and South Pacific |
| 39 | Infrastructure | Switzerland | the block is named Infrastructure but the ticker SWIIT is the Swiss real-estate funds index, the same ticker as block 48 |
| 43 | APAC Equities | East Asia | MXAP, MSCI AC Asia Pacific, spans East Asia and South Pacific |
| 47 | Mining Equities | Others | the block is named Mining Equities but the ticker MXWO is plain MSCI World, which is not a mining exposure |
| 54 | Trend Following | Others | managed futures trade globally; the listing is United States and the signal scope reads Europe |

## Inferred

| id | block | region | basis |
|---|---|---|---|
| 1 | Fixed Holding | Others | a client strategic holding with no stated geography |
| 9 | EM Equities | Others | MXEF, MSCI Emerging Markets, spans every region |
| 10 | Private Equity | Europe | LPX50 listed private equity is Europe-domiciled, though its holdings are global |
| 11 | Structured Products | North America | a Bloomberg structured-product index on a United States basis |
| 15 | Asia ex Japan TR | East Asia | NDUECAXJ, Asia ex Japan, spans both Asian slots |
| 25 | Asian JACI Bond Index | East Asia | the JACI Asian bond index spans Asia broadly |
| 26 | Real Estate direct | Switzerland | WUPIIMM, Swiss direct property |
| 29 | Asia Multi Strategy HF | East Asia | an Asia multi-strategy hedge-fund index |
| 31 | Asia Long Short Equities | East Asia | an Asia long-short equity index |
| 49 | CS Long Vola | North America | CS Long Vola on VXTH, a United States volatility index |

## Read from the ticker

| id | block | region | ticker |
|---|---|---|---|
| 2 | CH Equities | Switzerland | MXCH, MSCI Switzerland |
| 3 | EU Equities | Europe | MXEU, MSCI Europe |
| 4 | UK Equities | Europe | MXGB, MSCI United Kingdom. The vocabulary has no UK slot, so the UK sits in Europe |
| 5 | US Equities | North America | MXUS, MSCI USA |
| 6 | Japan Equities | East Asia | MXJP, MSCI Japan |
| 7 | China Equities | East Asia | MXCN, MSCI China |
| 8 | AU NZ Equities | South Pacific | MXAU, MSCI Australia. The block also names New Zealand |
| 12 | China A Shares | East Asia | SHASHR, Shanghai A shares |
| 13 | India Equities | South Asia | MXIN, MSCI India |
| 16 | Global Equities | Others | MXWO, MSCI World, global |
| 18 | CHF Corporate Loans IG | Switzerland | SPCHICCT, CHF corporate bonds |
| 19 | EUR  Corporate Loans IG | Europe | LECPTRCH, EUR corporate bonds hedged to CHF |
| 21 | Global Governmental Bonds | Others | SBWGU, world government bonds |
| 22 | Global High Yields | Others | LG30TRUU, global high yield |
| 23 | EM Government Bonds LC | Others | GBIEMCOR, emerging-market government bonds |
| 27 | Bloomberg Market Neutral HF | Others | BHQEMN, a global market-neutral hedge-fund index |
| 28 | Global Macro | Others | HEDGGLMA, global macro |
| 32 | CHF Cash | Switzerland | a CHF money-market holding |
| 33 | Precious Metals | Others | XAU, gold, not a geographic exposure |
| 34 | Commodities | Others | SPGCSI, broad commodities, not a geographic exposure |
| 35 | USD Cash | North America | a USD cash index |
| 36 | US Treasury TR Index | North America | LUATTRUU, United States Treasuries |
| 37 | Long Volatility Index | North America | VXTH, a CBOE index on United States volatility |
| 38 | Bloomberg Hedge Fund | Others | BHEDGE, a global hedge-fund index |
| 40 | MSCI AC World IMI | Others | MIMUAWON, MSCI ACWI IMI, global |
| 41 | Bloomberg Multiverse (H-CHF) | Others | LF93TRCH, Bloomberg Multiverse hedged to CHF |
| 42 | Swiss Performance Index | Switzerland | SPI, Swiss Performance Index |
| 44 | Hang Seng Index | East Asia | MXHK, MSCI Hong Kong |
| 45 | Fundo World Equity | Others | MXWO, MSCI World, global |
| 46 | Aktien Europe aktiv | Europe | MXEU, MSCI Europe |
| 48 | SXI Real Estate | Switzerland | SWIIT, the Swiss real-estate funds index |
| 50 | Swiss Dividend Equity | Switzerland | CHDVD, Swiss dividend equities |
| 51 | EUR Cash | Europe | a EUR money-market holding |
| 52 | Digital Assets | Others | XBTUSD, bitcoin, not a geographic exposure |
| 53 | Short MSCI US | North America | M004US6$, short MSCI United States |
