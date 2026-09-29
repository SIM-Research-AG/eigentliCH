# Engine 14: LifeBalance Simulator (`lbsim`)

What a household's Life Balance Sheet means over time: the deterministic findings on the sheet, the Monte Carlo
paths of its wealth under the stated plan in every market Regime, and a background plan calculation. The engine
page is Notion `3e80ba72543f819abe14c30ca61942f5`; the binding interfaces are `Engines/review/LBSIM_INTERFACES.md`.

| | |
|---|---|
| Family | Client |
| Module | `lbsim`, installed editable in `eigentliCH_Engines/.venv` (`pip install --no-deps -e .`) |
| Port | 8014 (`config.yaml`) |
| Status | Part B1 built (contracts, model port, fast half, adapter, calibrations, golden files, samples). Monte Carlo, clients, store, service, API and workers: B2. Optimiser: C. |
| Consumes | lbs 8013 (sheet, its request, calibration); pcp 8007 (Allocation); aggregation 8004 (Regimes); fmre 8006 (ReturnSets, inflation) |
| Produces | `LifeBalanceFindings` (`LSF-`), `LifeBalancePaths` (`LSP-`), `LifeBalancePlan` (`LSO-`) |
| Downstream | report 8015, the consumer app 8017, the cockpit 8000 |

## What is built (B1, 29.09.2026)

- `contracts.py`: every model of spec section 3 (request, findings, paths, plan, runs and outlook, validation,
  calibration) frozen with extra fields forbidden, and the upstream mirrors of lbs, pcp, aggregation and fmre,
  frozen with extra fields ignored.
- `lbsim.model`: the numpy port of the draft's `personal_alm/model` (params, dynamics, state, controls, bvg,
  canton, fiscal, and the expertise and venture types the state needs). The only change is where the two tables
  come from: the calibration's seed records `social-insurance` and `canton-tax`.
- `lbsim.fast`: the port of the draft's fast half (`gameplan`, `paths`, `findings`, `plausibility`, `search`,
  `asks`, `workflow`), the one earning-power computation (`earning`, LBSIM-11) and the findings artefact
  (`build`). The draft's hidden chain `gameplan -> onboarding -> cases -> optim -> casadi` is cut.
- `lbsim.adapter`: a Life Balance Sheet and its request to the draft's submission (spec 3.6).
- `calibration.py`: seeds 1.0.0 (reproduces the draft) and 1.1.0 (active), and the records in `seed_records/`.
- `layer_b.py`: golden layer B, lbsim's own behaviour against the draft's, every changed leaf attributed.

## Golden files

| Folder | What | Built by |
|---|---|---|
| `golden/draft` | layer A: the draft's `gameplan.assemble` and `paths.ledger` on 48 cases | `dev/build_golden.py`, draft interpreter |
| `golden/earning` | the prototype's `human_capital.earning_power` on lbs's golden households | `dev/build_golden_earning.py`, prototype interpreter |
| `golden/lbs_cases` | 21 lbs requests and the sheets lbs builds of them, with the records read | `dev/build_lbs_cases.py`, family interpreter |
| `golden/layer_b` | findings under 1.0.0 and 1.1.0, and `changes.json` | `dev/build_layer_b.py` |
| `golden/samples` | one findings, one paths and one plan artefact for agents B2, C, D and E, with the upstream snapshot they rest on | `dev/build_samples.py` |

The paths and plan samples are hand-built (`provenance.made_by: sample`, with a note); the findings sample is the
engine's own and a test rebuilds it byte for byte.

## Tests

From this folder: `timeout 900 ../../.venv/Scripts/python -X utf8 -m pytest -q -p no:warnings`. Slow optimiser
tests (C) are marked `slow` and deselected by default.

## Layout

```text
lbsim/
  config.yaml                how the engine runs; model parameters are in the calibrations
  src/lbsim/
    contracts.py calibration.py adapter.py layer_b.py ids.py engine.py
    model/                   the numpy port (no casadi)
    fast/                    the fast half (no casadi)
    seed_records/            social-insurance, canton-tax, findings-text
    optim/                   agent C
    api.py clients.py store.py   agent B2
  dev/                       the golden and sample builders
  golden/                    frozen references
  tests/
```

Model-derived research output. Not investment advice.
