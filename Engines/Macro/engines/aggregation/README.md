# Engine 04: Aggregation layer (`aggregation`)

> **Notice.** Model-derived research output of the aggregation layer. Not investment advice.

> Resume from [HANDOVER.md](HANDOVER.md). Every decision is in [DECISIONS.md](DECISIONS.md)
> (AGG-01 to AGG-24). Specification: the Notion page "Engine 04: Aggregation layer (aggregation)".

Combines the three model engines into the **combined market risk signal, the Regime**: a 25-state
distribution per economy and month (1 cautious, 25 aggressive), used by `fmre`, `pcp` and
`scenario`. Listed as "TAA Signal" in the strategy meeting of 23.09.2026.

- It **issues the `regime_id`**: `RGM-` plus the hash of its idempotency key (the three input
  artefact ids, the optimism level, the calibration hash, engine and contract versions). Identical
  inputs always give the identical id. The inputs stamp `regime_id: null`.
- It **applies the optimism level** (Defensive, Default, Aggressive, Rogue) to the combined signal.
- It **checks** that the three inputs stem from one datafeed snapshot; a mismatch is warned and
  recorded, not refused (AGG-04).
- It holds the **market blends** (americas, europe, asia, sino, global, equal, EMCN).
- It issues **scenario Regimes**: an issued Regime projected 60 months under one of the four
  policies of `Scenario_SAA.m` (depression, hyperinflation, stagflation, deferral), so the Optimizer
  can run under simulated regimes (AGG-19 to AGG-22).

| | |
|---|---|
| Family | Macro Engine |
| Module | `aggregation` |
| Default port | 8004 (`config.yaml`, or `AGGREGATION_PORT`) |
| Consumes | `MarketRiskSignal` from `mrs` (8005, `mrs-signal@1.0.0`), `CycleState` from `cycle` (8012, `cycle-state@1.1.0` or `@1.2.0`, AGG-18), `MacroState` from `macrofield` (8003, `macrofield-state@1.2.0`), each by artefact id |
| Produces | `Regime` (`aggregation-regime@1.0.0`) |
| Downstream | `fmre` (8006), `pcp` (8007), `scenario` (8009) |

## Run it

From this folder, with PostgreSQL up (`docker compose up -d` in `Projects\PostgreSQL`) and the
`aggregation` role provisioned (`python -m store.provision` in `Projects\Engines\Instruments`):

```bash
..\..\.venv\Scripts\pip install -e .[dev]    # shared venv of the Macro engines
python -m aggregation init-db                # once per server: tables, seed calibrations
start.cmd                                    # http://127.0.0.1:8004/docs; test bench at http://127.0.0.1:8004/
```

The local password lives in `config.local.yaml` (git-ignored). Then, with `mrs`, `cycle` and
`macrofield` running and one artefact from each:

```bash
curl -X POST localhost:8004/run -H "content-type: application/json" -d \
  '{"mrs_artefact_id":"MRS-...","cycle_artefact_id":"CYS-...","macro_artefact_id":"MFS-...","optimism_scale":"default"}'
# {"run_id":"RUN-...","status":"succeeded","artefact_id":"AGG-...","regime_id":"RGM-...","idempotency_key":"IDK-...","cached":false}
```

`POST /run` also takes `calibration_version` and `economies`. The same request twice is answered
from the cache.

```bash
python -m pytest        # 121 tests: engine, golden, Manual 10.7 acceptance, API, store, boundary, cycle versions, scenarios
```

## Endpoints

Standard (Guide section 2.1): `GET /health`, `GET /meta`, `GET /contracts`, `POST /run`,
`GET /runs`, `GET /runs/{run_id}`, `GET /artefacts/{artefact_id}`, `GET /calibration`,
`PUT /calibration`.

Engine specific, additive:

| Method | Path | Notes |
|---|---|---|
| GET | `/regime/{regime_id}` | The Regime in full. |
| GET | `/regime/{regime_id}/path?economy=` | `date -> state` (mean-nearest, modal beside), economies and markets. |
| GET | `/regime/{regime_id}/distribution?date=&economy=` | 25-state distribution at a date (`YYYY-MM` or `YYYY-MM-DD`; default the last assessed). |
| GET | `/regime/{regime_id}/current` | `{state, modal_state, phase, saturation_pct, crisis_tail, five_regime, shape, ...}` per economy and market. |
| GET | `/regime/{regime_id}/contributions?economy=&date=` | Each input's weight, component and contribution per state; the macro regime weights and the tilts that moved them. |
| GET | `/calibration/versions` | Every stored calibration. |
| POST | `/scenario` | `{"base_regime_id": "RGM-...", "policy": "depression\|hyperinflation\|stagflation\|deferral"}` -> `{regime_id, cached, policy, base_regime_id}`. Idempotent. The scenario Regime is served by every `/regime/{id}` read and `/artefacts/{id}`. |
| GET | `/scenarios?base=RGM-...` | `[{regime_id, policy, base_regime_id, created_at}]`; without `base`, every scenario Regime. |
| GET | `/scenarios/policies` | The four policies: id, `case` of the .m file, English and German label and one-line description, target mix. |
| GET | `/model?economy=` | The aggregation layer explained on one economy, from the latest Regime and its three inputs: every step with its formula, parameters and charts (`model-card@1.0.0`, the cockpit's Models page, AGG-17). |

## Model in one screen

Per economy:

1. **Macro half (annual).** Five regime weights, crisis to boom, start even (`base`); tilts move
   weight to the cautious end (saturation above the 2.5 to 3.5 band, K_R/K_I below 1, a rising
   unsecured-asset ratio, negative cycle interference, years past the capital reordering point,
   the approach of the innovation trough) or to the aggressive end (the reverse of the first
   three, positive interference). Each weight is spread by its kernel (crisis piled at states 1
   to 10, boom its mirror at 16 to 25, three symmetric 14-state kernels between).
2. **Market half (monthly).** The market risk signal as `mrs` publishes it, at zero shift.
3. **Cycle layer (annual).** `cycle`'s own 25-state layer.
4. **Blend** per month: `0.8 * [0.5 * MACRO + 0.5 * MARKET] + 0.2 * CYCLE`, annual parts held
   flat across the year's months.
5. **Optimism**: states 1 to 5 stay; the rest of the combined distribution moves by Defensive
   -1.75, Default +2.37, Aggressive +7.52, Rogue +13.60 states, mass past the top piled on state
   25. A neutral market reading then reads 10 / 14 / 19 / 24.
6. **Markets**: country-weighted blends, published for a date only when every weighted economy
   is assessed.

## Scenario Regimes

`POST /scenario` takes an issued Regime and one policy of `Scenario_SAA.m` and returns a new
Regime of the same contract (`aggregation-regime@1.0.0`):

- **History**: the base Regime's dates and distributions up to its `as_of`, unchanged.
- **Projection**: 60 month-ends after it. Each economy starts from its latest distribution and moves
  towards the policy's target exactly as the .m file moves `MRS_start`: each month by
  `(target - current) / (months left)`, then renormalised.
- **Target**: the policy's mix over Boom, Recovery, Contraction, Bust spread by the .m file's
  kernels (Bust on states 1 to 10, Contraction 3 to 16, Recovery 10 to 23, Boom 16 to 25):

| Policy | Boom | Recovery | Contraction | Bust | Default Regime, US on month 60 |
|---|---|---|---|---|---|
| `depression` | 0 | 0 | 0.25 | 0.75 | state 5, crisis tail 0.59 |
| `hyperinflation` | 1 | 0 | 0 | 0 | state 22 |
| `stagflation` | 0.5 | 0.25 | 0.25 | 0 | state 18 |
| `deferral` | 0.5 | 0 | 0 | 0.5 | state 13 (Boom and Bust humps) |

- **The month that represents the scenario is month 60**, the target reached: the Regime's last
  date and `provenance.as_of`, the `current` of every economy and market, and the month pcp picks
  by default (the latest month where all weighted economies are assessed). On it every economy
  reads the policy's target.
- The optimism level of the base shifts the history only; the projection is not shifted.
- `provenance.scenario` names the policy, the base Regime, the horizon, the template's sha256 and
  the scenario date. It is absent (not `null`) on an issued base Regime, so stored Regimes read back
  byte for byte and pcp's mirror reads a scenario Regime unchanged.
- `provenance.scenario.inflation_path` is the policy's inflation path of the .m file (60 monthly
  annualised rates, macrofield's TB-21 values) and `inflation_final_12m` its average over months 49
  to 60, the rate fmre deflates a scenario by (nominal and real view): depression -4.00 %,
  hyperinflation 63.56 %, stagflation 10.00 %, deferral 2.57 %. Both are derived from the policy when
  the Regime is read, served in every response, and neither stored nor hashed, so no scenario id
  moves (AGG-24). A base Regime carries neither.

## Calibrations

| Version | Use |
|---|---|
| `1.2.0` | **Active.** 1.1.0 with the crisis tail (states 1 to 5) kept in place under optimism and the shifts solved so the neutral reading still lands on 10 / 14 / 19 / 24 (AGG-15). |
| `1.1.0` | 1.0.0 with the optimism levels (AGG-05) and the last macro reading carried up to 24 months, flagged (AGG-07). |
| `1.0.0` | The first draft's combination rule, unchanged; no shift, no carry. The golden reconciliation runs on it. |

## Layout

```text
config.yaml            port, upstream, store, active calibration, default optimism. No password.
src/aggregation/
  api.py               FastAPI routing only
  contracts.py         Pydantic models, in (partial mirrors) and out
  engine.py            the model: pure functions, no I/O, no clock
  scenario.py          the Scenario_SAA.m port: kernels, targets, stepping (pure)
  calibration.py       the seed parameter sets
  clients.py           typed callers for mrs, cycle and macrofield
  store.py, schema.sql PostgreSQL persistence; calibrations and artefacts append-only
  service.py           orchestration: the only module that touches store, clients and model
  settings.py          configuration loading and precedence
tests/                 unit, property, golden, API and store tests
golden/                frozen inputs, the first draft's output on them, regression outputs;
                       scenario_saa/: Scenario_SAA.m and its frozen targets and paths
testbench/             development front end (Plotly): Run, Distribution, Optimism, Path, Contributions,
                       Markets, Scenarios. Served at / and in the cockpit (Test benches, aggregation). Not deployed.
dev/                   deploy builder. Not deployed.
```

Configuration precedence, lowest to highest: `config.yaml` < `config.local.yaml` <
`AGGREGATION_DATABASE_URL` / `DATABASE_URL` < `AGGREGATION_DB_*`, `AGGREGATION_HOST`,
`AGGREGATION_PORT`, `AGGREGATION_MRS_URL`, `AGGREGATION_CYCLE_URL`, `AGGREGATION_MACROFIELD_URL`,
`AGGREGATION_CORS_ORIGINS`. `python dev/make_deploy.py` writes `..\..\deploy\aggregation`.

Model-derived research output. Not investment advice.
