# Golden: CIO site `assets` export (MATLAB `M_TS`)

| | |
|---|---|
| File | `assets.txt` (JSON, 2,287,845 bytes) |
| sha256 | `572999b311d9618cc89b37665bdb536ddb22f49e3e2282849692118308f6e13f` |
| Source | `https://sim-tech.ch/CIO/data/assets.txt`, last modified 03.09.2026 07:47 UTC, downloaded 28.09.2026 |
| Produced by | `SIM_Tech/Master_Controller/Functions/Market Risk/MRS_Tester/MRS_Tester.m`, the same run as `../cio_signal_2026-09/signal.txt` and `../cio_stats_2026-09/stats.txt` (all three written within the same minute) |
| Months | 241, **September 2006 to September 2026** |

## Why it is here

The `signal` and `stats` exports were first recorded as pairing with the local `M_TS.mat`
of 05.01.2026. They do not (MRS-20): the OIS flags of this file agree with datafeed's raw
snapshot of `M_TS.mat` exactly at an offset of 8 months and at no other, and other series
differ by revisions. The exports were computed from this `M_TS`, so the golden test runs the
`matlab` indicators on it.

It is a **test fixture only**. mrs reads its production input from datafeed alone (MRS-14);
nothing in `src/` reads this file.

## Shape

`{economy: {sheet: [[row] x 241]}}` for the 16 MATLAB economies, plus `Global` and the `EMCN`
blend (not used). Sheets and columns as `M_TS` (`src/mrs/series.py` gives the column of each
series). Gaps are 0 as MATLAB stored them, except a few cells that are `NaN` in this pull
(for example Vietnam M1 growth, Indonesia and Bangladesh wage growth); MATLAB's `normalize`
ignores them, and the port reproduces that.
