# golden/

Frozen reference inputs and outputs for `tests/test_golden.py`. Written by `build_golden.py`
(dev only: needs the `dev` extra for statsmodels, the first draft on disk, and datafeed on 8001).
The tests read only these files. Tolerance for this engine: **1e-12 absolute**.

| File | What it is | Used by |
|---|---|---|
| `snapshot_2026-01-05.public/panel.json` | datafeed's production snapshot `matlab-m_ts-2026-01-05.public-8e90be47` (`panel@1.1.0`), in full | every layer |
| `snapshot_2026-01-05.public/source.json` | the datafeed checksum `panel.json` must match | `test_golden.py` |
| `snapshot_2026-01-05.public/draft_1.0.0.json` | **the first draft's output**: `cycles.py` and `cycle_bins.py` (statsmodels filter), run on inputs this engine prepared from `panel.json`, under the settings calibration 1.0.0 carries | layer A |
| `snapshot_2026-01-05.public/expected_1.0.0.json` | this build's output on `panel.json` under calibration 1.0.0 | layer C |
| `macrofield_MFS-6183873b127fcd58.json` | macrofield's `MacroState` (run of 2026-09-27, snapshot `SNP-41f60149296357f8`, calibration 1.3.0), trimmed to the fields cycle reads, with its sha256 | calibration 1.1.0 tests, the API tests' mock macrofield |
| `snapshot_2026-01-05.public/expected_1.1.0.json` | this build's output on `panel.json` and that state under calibration 1.1.0 (active) | layer C |
| `cycle_state_1.1.0_CYS-c6a5185ec9c743a0.json` | a real `cycle-state@1.1.0` artefact from the `cycle` schema (28.09.2026), economies trimmed to US and CN, every other field as stored. Not written by `build_golden.py` | `test_api.py` (C-26: stored artefacts are served as published) |

**Layer A** is the engine page's golden: the first draft's output frozen on the production
snapshot. It covers the 15 economies whose inputs span the whole window (the draft refuses a gap
and needs every cycle on the same periods). CH is the one left out: its CPI for December 2025 is
missing, so its real output growth ends in 2024 (DECISIONS.md C-05).
Agreement is to 1e-12 on every component, phase, amplitude, period, anchor, superposition,
alignment, synchrony window and layer row, except the one divergence DECISIONS.md C-09 classifies.

The inputs themselves (annualisation, deflation, saturation) are this engine's, since the draft
read its own files; `tests/test_engine.py` checks that the input equals the draft's
`np.gradient(log real output)` on complete data.

**Layer C** is regression only.

## Rebuilding

```bash
..\..\.venv\Scripts\python golden\build_golden.py      # datafeed on 8001, macrofield on 8003
```

Refreeze only with a reason, and record the reason in DECISIONS.md.
