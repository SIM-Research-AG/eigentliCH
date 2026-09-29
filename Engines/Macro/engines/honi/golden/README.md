# golden/

> **MATLAB is retired as a reference (DECISIONS.md D-28).** The current build is the
> reference. The MATLAB layers below document how faithfully the port was made and stay
> as regression checks; they are not to be re-derived from MATLAB again.

Frozen reference inputs and outputs for `tests/test_golden.py`. Written by
`build_golden.py`: the MATLAB output from `SIM_Tech\Master_Controller\HoNI_Export.xlsx`,
the input fetched from datafeed. The tests read only these files. Tolerance for this
engine: **1e-12 absolute**.

Layers A to C use the **raw** snapshot, because that is what MATLAB saw. Production runs
use the filled snapshot; the difference is datafeed's public fills, reported on every run.

| File | What it is | Used by |
|---|---|---|
| `matlab_export_2025-11.json` | `HoNI_Export.xlsx` (2025-11-13): raw indicators, index, sector and national scores, capital saturation | layer A |
| `snapshot_2026-01-05/panel.json` | datafeed's raw snapshot `matlab-m_ts-2026-01-05` (`panel@1.1.0`): the data exactly as MATLAB saw it | layers B and C |
| `snapshot_2026-01-05/source.json` | the datafeed checksum `panel.json` must match | `test_golden.py` |
| `snapshot_2026-01-05/expected_1.0.0.json` | this build's output on that panel under calibration 1.0.0 | layer C |

## Why there is no single end-to-end MATLAB reference

The export and the panel do not belong together. `HoNI_Export.xlsx` was made in November
2025 from an `M_TS.mat` that the January 2026 pull then overwrote, and no copy survives.
The two are one year apart in coverage, and because MATLAB annualised by sampling every
12th month from the loader's run month (DECISIONS.md D-11), even unrevised monthly
series differ between them.

So each layer is reconciled against the strongest reference that exists for it:

- **A. Scoring and aggregation vs MATLAB.** The export publishes its raw indicator values,
  so they go in and MATLAB's own scores must come out. Agreement is about 2e-15.
- **B. Indicator formulas vs a transliteration.** `tests/matlab_reference.py` is the
  `HN_*.m` code line for line, defects included, run on the panel sampled the MATLAB way.
  The engine must agree on every cell no documented defect touches, and at least 75% of
  cells must be comparable (currently about 87%).
- **C. End to end vs this build.** Regression only.

**To close the gap:** run `HoNI_Exporter.m` in MATLAB against the current `M_TS.mat`,
copy the new `HoNI_Export.xlsx` over the old one, and rerun `build_golden.py`. The export
then matches the panel, and an end-to-end comparison becomes possible (expect the
divergences D-11, D-12 and 9.1 to 9.5, and nothing else).

## Rebuilding

```bash
python golden/build_golden.py                  # the fixtures (datafeed running on 8001)
python golden/build_golden.py --freeze-build   # and refreeze layer C
```

Refreeze layer C only with a reason, and record the reason in DECISIONS.md.
