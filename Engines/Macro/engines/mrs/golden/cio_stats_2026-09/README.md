# Golden: CIO site `stats` export (MATLAB `Indices`)

| | |
|---|---|
| File | `stats.txt` (JSON, 1,501,909 bytes) |
| sha256 | `01a39d1db3e066c21c728d82f127f26741a2a4f84331e0546630e8d94ecb56ee` |
| Source | `https://sim-tech.ch/CIO/data/stats.txt`, downloaded 27.09.2026 on the owner's ruling (fetch and freeze it) |
| Produced by | `SIM_Tech/Master_Controller/Functions/Market Risk/MRS_Tester/MRS_Tester.m`, the same run as `../cio_signal_2026-09/signal.txt` |
| Input it pairs with | `../cio_assets_2026-09/assets.txt` (the CIO `assets` export of the same run), 241 months, Sep 2006 to Sep 2026. Corrected 28.09.2026: first recorded as the local `M_TS.mat` of 05.01.2026, which it does not match (MRS-20). |

## Shape

`{economy: {segment: {sub_indicator: [241 floats]} | TS_segment: [241 floats]}}`, identical
keys for every economy.

- Economies: the 16 MATLAB economies (Brazil, CH, China, EU, India, Indonesia, Malaysia,
  Philippines, Thailand, UK, USA, Japan, Bangladesh, Vietnam, Germany, Spain) plus the `EMCN`
  blend.
- Sub-indicators (12): `BusinessCycle` {Inflation, Monetary, Consumer, Company}, `Investment`
  {Bond, Equity}, `MarketBehaviour` {Trend_Osc, Fear_Greed}, `MarketStress`
  {Global_Stability, Market_Stability, Monetary_Uncertainty}, `KeyStats` {KeyStats}.
- Segment series (5): `TS_BusinessCycle`, `TS_Investment`, `TS_MarketBehaviour`,
  `TS_MarketStress`, and the combined `TS_Riskcycle`.
- No dates: month k is the k-th month of its `M_TS` (month 1 = September 2006, MRS-20). No nulls: MATLAB
  set every gap to 0 before exporting (69,649 values, 6,748 zeros).

## What to know before comparing

- **`MarketBehaviour.Fear_Greed` is 0 in all 241 months for all 17 economies.** The Fear
  Barometer input (Volatility 2) is empty in `M_TS` for every country (see `HANDOVER.md`,
  findings), and the indicator sets NaN to 0. The golden test must reproduce the zero series
  under the `matlab` calibration; it is not evidence that the formula works.
- `EMCN` is a fixed blend (India 0.60, Brazil 0.20, the four ASEAN economies 0.05 each) and
  belongs to `aggregation`, as in the signal export.
- Tolerance ruled by the owner on 27.09.2026: **1e-10 absolute**. Divergences are classified
  (intentional fix, bug, floating point) in `DECISIONS.md`.
- `tests/test_golden.py` compares every sub-indicator and segment value of the 16 economies with it: worst absolute difference 3e-14.
