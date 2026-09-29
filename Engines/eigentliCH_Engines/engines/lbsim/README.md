# Engine 14: Scenario Generator, LifeBalance Simulator (`lbsim`)

> **Scaffold only (27.09.2026).** The folders follow the Engine Building Guide, section 2; the files are empty and nothing runs yet. The engine page is the specification: https://app.notion.com/p/3e80ba72543f819abe14c30ca61942f5

Simulated paths of the life balance sheet over the horizon. The random seed is part of the idempotency key.

| | |
|---|---|
| Family | Client |
| Module | `lbsim` |
| Default port | 8014 (configurable in `config.yaml`) |
| Status | Scaffold. First draft exists; not yet built here |
| Consumes | `LifeBalanceSheet` from `lbs` (8013); market scenarios |
| Produces | `LifeBalancePaths` |
| Downstream | `report` (8015) |

## Contracts

As specified on the engine page; to be confirmed against the first draft.

| Contract | Direction | Content |
|---|---|---|
| `LifeBalanceSimRequest` | In | `{life_balance_sheet_id, horizon, scenario source}`; fields from the first draft. |
| `LifeBalancePaths` | Out | Simulated paths of the life balance sheet over the horizon. |

## Endpoints

The standard endpoints of Guide section 2.1 (`/health`, `/meta`, `/contracts`, `POST /run`, `/runs/{run_id}`, `/artefacts/{artefact_id}`, `GET`/`PUT /calibration`); engine specific endpoints follow from the first draft.

## First draft

- `Projects/eigentliCH/engines/Life_Balance_Sheet/personal_alm/sim/montecarlo.py` (Euler-Maruyama Monte Carlo)
- Related: `Projects/eigentliCH/engines/scenario_generator` (what a client's own change does to the household)

## Open points

- Decide which engine supplies the market scenarios (`scenario` or its own generator).

## Layout

```text
lbsim/
  README.md
  pyproject.toml
  config.yaml            # all parameters incl. port, no magic numbers in code
  src/lbsim/
    api.py               # FastAPI app, routing only, no maths
    contracts.py         # Pydantic models, in and out
    engine.py            # pure functions, no I/O, no HTTP
    calibration.py       # ranges, weights, thresholds
    clients.py           # typed callers for upstream engines
    store.py             # artefact persistence
  tests/
    test_engine.py       # unit and property tests
    test_golden.py       # reference reconciliation
  golden/                # frozen reference inputs and outputs
```

Model-derived research output. Not investment advice.
