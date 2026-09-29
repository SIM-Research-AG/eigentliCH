# Macro Field (macrofield): handover (updated 29.09.2026, TB-27)

Where the build stands, how to pick it up, and what is still open. The README is the reference
documentation; this file is the resume point.

## State

- **Engine 03, Macro Field, v0.6.0** (the three-body model; renamed from `threebody` on 27.09.2026,
  port 8003), calibration **1.5.0 active** (TB-27, activated by the owner 29.09.2026, TB-28; 1.4.0 stored)
  snapshot **SNP-41f60149296357f8** (106 files, 78,132 observations).
  116 tests pass (`python -m pytest`, about 6 minutes, needs the container).
- All **16 HoNI economies** available and projected. Last stored artefact: `MFS-6183873b127fcd58`
  (calibration 1.3.0, 27.09.2026; the Regime `RGM-e2658e8e9bbbc81e` was built from it). **No run
  has been made on 1.4.0 yet**: the next `POST /run` produces a new artefact id (engine version,
  contract versions and calibration all enter the key), and cycle, which reads macrofield's latest
  run, will then project to 2080 (its C-22).
- Calibration lineage (all seeded from `src/macrofield/calibration.py`, immutable):
  - **1.0.0** reproduces the eigentliCH prototype (Macro_Model) exactly (golden: BR, CH, CN, DE, GB, IN, US).
  - **1.1.0** Phase 4 latch over the full published history.
  - **1.2.0** Germany on Genreith's measure: Bundesbank bank balance sheet / GDP from 1950, no
    uplift, Phase IV when loans < 50 % of the balance sheet. DE reads Phase 4 since 2000.
  - **1.3.0** every economy projectable: IMF WEO fiscal (JP, ID, BD, VN), IMF private +
    government debt axis (PH, BD, VN), euro area from its 20 members' PWT capital, weak-evidence
    projections for fits that do not reproduce their window (BR, CH, TH, JP, DE, ES).
  - **1.4.0** review R-005: soft saturation ceiling around 5 (band 4.5 to 5.5, damped from 3.5,
    no clamp), the four Phase IV policies of `Scenario_SAA.m` (frozen in `golden/scenario_saa/`;
    run parameter `resolution_policy`, default stagflation), 60-month crisis, 35-year reset to the
    Foundation level, re-integration with early-phase parameters, model horizon 2080 (display 2039).
    Observed-period outputs identical to 1.3.0 in all 16 economies, hence active. TB-20 seeds
    (onset 3.5, turn levels 4.7, 4.9, 5.1, 5.4) confirmed by the owner on 29.09.2026.
  - **1.5.0** TB-08 integrability fixed (TB-27): investment share bounded at zero,
    r = max(0, 1 - K_R/Y), in fit and projection; parameters carried forward and after the reset
    held inside `parameter_ranges`. All 16 fits integrate at reporting tolerance, all 16
    projections to 2080 with no tail; no tail turns, no second turns. Not active (TB-28): the fits
    differ from 1.4.0, although everything aggregation and cycle read is identical. Hash
    `CAL-b00a9412c2aa6213`, seeded in the store on 29.09.2026.
- Contracts: `MacroState` deliberately stays `macrofield-state@1.2.0` (cycle and aggregation pin
  the literal); the new fields are optional and omitted while unset, so stored artefacts and the
  1.0.0 to 1.3.0 calibration hashes are unchanged (tested). Projection 1.2.0, ProjectionRequest
  1.1.0, MacroRunRequest 1.1.0, Calibration 1.5.0 (1.0.0 to 1.4.0 hash unchanged, tested).
- Notion: engine page "Engine 03: Macro Field (macrofield)" under the Engine Building Guide
  (https://app.notion.com/p/3e50ba72543f81d38916efb0c7cc5241);
  data need on its sub-page "Macro Field: data need (for datafeed)"
  (https://app.notion.com/p/3e80ba72543f81018f08ebcff50e118b); progress on the task page "Macro Engine:
  3-body model".
- **Scope (TB-19, decided 27.09.2026):** three-body core only. The five nested cycles sit in
  `cycle` (Engine 12), the 25-state distribution in `aggregation` (Engine 04); no HoNI input.

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\Macro\engines\macrofield
start.cmd                                   :: engine on 8003, test bench at http://127.0.0.1:8003/
```

The store (`simtech`, schema `macrofield`, role `macrofield`; migrated from `simtech_macro` on 27.09.2026) already holds the snapshot, the six calibrations
and the last run. From scratch: `python -m macrofield init-db`, `python -m macrofield load`, then
"Run all economies" in the test bench. Shared venv: `Projects\Engines\Macro\.venv` (macrofield is
installed editable there, alongside honi).

## Decisions to take (details in README, "Decisions and open points")

| Id | Question |
|---|---|
| TB-06 | ES, ID, MY, TH (and PH, BD, VN) economy settings are assumed; review |
| TB-07 | The Phase 4 latch holds GB, ES, MY, TH in Saturation below 3.5 since 2020; keep the rule? |
| TB-08 | Integrability fixed in 1.5.0 (TB-27). Still open: identity corrections 0.9 to 9.9 from one; the Paper 1 F/G/H form is not written down anywhere |
| TB-15 | Only Germany is on the bank balance-sheet axis; move all economies (needs ECB BSI, Fed, SNB and national sources)? |
| TB-16 | JST (German GDP before 1990) is CC BY-NC-SA, non-commercial: licence check |
| -- | "Germany above 3.5 in the book": not reproducible; peak 3.19 (2010) on current GDP, 3.4 in Genreith 2014 on pre-revision GDP. Needs the book page to check |
| TB-22 | Default policy stagflation (TB-20 confirmed 29.09.2026) |
| TB-26 | Under 1.5.0: no tail turns, no second turns; CH, ID, MY, PH, US, JP, BD do not turn by 2080 (fitted p_b above p_p), IN, DE, CN under some policies |
| TB-28 | Activate 1.5.0? Regime inputs unchanged; fit report, simulated path and projection change |
| TB-29 | First projected year drops saturation 24 to 41 % in CH, TH, US, JP (large r K_I at the observed end state) |

## Next steps, in order

1. Owner: activate 1.5.0 or not (TB-28). Then run all economies (`POST /run`) on the active
   calibration when cycle and aggregation are ready to move with it; tell cycle its horizon
   becomes 2080. Confirm TB-22.
2. Review TB-06 settings and TB-07 latch with the author; each change is a new calibration.
3. Source the two remaining series (`data_need.csv`, 2 missing rows): OECD consolidated financial
   assets (the book's K_I) and credit to the financial sector (would replace the 1.4 uplift).
4. Model: integrability is fixed (1.5.0); the identity corrections (TB-08) and the no-turn
   economies they cause (TB-26, TB-29) are now the weakest part; revisit with the book's
   chapters 7 to 8.
5. Deploy folder when signed off: `python dev/build_deploy.py --out <folder>`.
6. When `datafeed` exists: replace `snapshot.py` with a client; the series ids stay.

## Where things are

| Path | What |
|---|---|
| `README.md` | Reference: run, anatomy, data flow, contracts, calibrations, quality, data need, decisions |
| `src/macrofield/` | Engine (pure core: `engine`, `assembly`, `fitting`, `dynamics`, `phases`, `projection`) |
| `data/raw/` | Current snapshot; `data/archive/` the two earlier ones, unchanged |
| `golden/` | Frozen outputs of the eigentliCH prototype; `dev/reconcile.py` prints the comparison. `golden/scenario_saa/`: `Scenario_SAA.m` and its frozen policies (`dev/freeze_scenario_saa.py`) |
| `data_need.csv` | T5-format data need (`python -m macrofield data-need` regenerates it) |
| `dev/` | `freeze_sources.py` (new snapshot, `--base` to carry files over), `freeze_golden.py`, `build_deploy.py` |
| `testbench/index.html` | Development UI: overview, economy, projection levers, parameters, data |
