# Golden: CIO site `signal` export (MATLAB `WM`)

| | |
|---|---|
| File | `signal.txt` (JSON, 3,885,092 bytes) |
| sha256 | `29ad0cf9c5c3411acb97320a34d66f12f454c382cd808b7487c9be808f18fab9` |
| Source | `https://sim-tech.ch/CIO/data/signal.txt`, supplied by the owner and downloaded 27.09.2026 |
| Produced by | `SIM_Tech/Master_Controller/Functions/Market Risk/MRS_Tester/MRS_Tester.m` (optimism "Default", i.e. +0.4 shift; weights hardcoded, identical to `Controller_Test.xlsx` Market_Settings) |
| Input it pairs with | `../cio_assets_2026-09/assets.txt` (the CIO `assets` export of the same run), 241 months, Sep 2006 to Sep 2026. Corrected 28.09.2026: first recorded as the local `M_TS.mat` of 05.01.2026, which it does not match (MRS-20). |

## Shape

`{segment: [month_1 .. month_241]}`, each month `{economy: [25 floats]}`.

- Segments: `BusinessCycle`, `Investment`, `MarketBehaviour`, `MarketStress`.
- Economies: the 16 MATLAB economies (MATLAB names: Brazil, CH, China, EU, India, Indonesia,
  Malaysia, Philippines, Thailand, UK, USA, Japan, Bangladesh, Vietnam, Germany, Spain) plus
  `EMCN`.
- No dates: month k is the k-th month of its `M_TS` (month 1 = September 2006, MRS-20).
- Each vector is the **weighted kernel column** that segment selected for that economy and
  month (`weight * WM_<segment>(:, column)`), not a distribution. The regime row (`CRS`) is the
  sum of the four segments.

## What it already confirms (27.09.2026)

- Every one of the 16 economies' vectors, in all four segments and all 241 months (15,433
  vectors), equals a column of the kernel matrices `mrs` builds (`engine.kernel_matrix` times
  the segment weight), worst absolute error 1.1e-16. The `Weights.m` port is exact against the
  live output.
- `EMCN` is not an economy but a fixed blend (`MRS_Tester.m`, `w_em`): India 0.60, Brazil 0.20,
  Indonesia, Malaysia, Philippines, Thailand 0.05 each; residual about 1e-15. Blends belong to
  `aggregation` (MRS-05, MRS-13), so `mrs` does not reproduce `EMCN`.
- `tests/test_golden.py` (28.09.2026): with the indicators run on `../cio_assets_2026-09/`
  under the `matlab` calibration and MATLAB's +0.4 shift applied in the test only, 15,423 of the
  15,424 vectors match to 1e-16; the one divergence (Spain, market stress, month 170) is a
  reading exactly on a grid edge, MRS-01.
