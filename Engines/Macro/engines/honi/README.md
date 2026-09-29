# honi: Health of Nations Index engine

> **Notice.** Model-derived research output of the Health of Nations Index. Not investment
> advice.

HoNI rates the investment opportunity a country represents, relative to its peers.
Fifteen indices are scored 1 to 5, averaged into three sectors (Financial Economy,
International Resilience, Real Economy) and combined into one national score. Capital
saturation (total debt over GDP) is published beside it as the x axis of the primary
chart. Scores are **relative by construction**: in every year the best country in the peer
set scores 5 and the worst 1, so changing the peer set changes every country's history.

This is the Python port of `HoNI2.m` (Master_Controller, Version 2.0), built to the Engine
Building Guide and the engine page "Engine 02: Health of Nations (honi)". The HoNI Build
Manual is the model specification. `DECISIONS.md` lists every departure from MATLAB and
why.

| | |
|---|---|
| Module | `honi` |
| Default port | 8002 (`config.yaml`, or `HONI_PORT`) |
| Consumes | `Panel` and `CoverageReport` from `datafeed` (`GET /panel`, `GET /coverage`) |
| Produces | `HoNIScores`, `PeerStats` |
| Downstream | No automated consumer. The CIO uses the scores to set the optimiser's boundary conditions and for instrument selection, in the CIO pages of the cockpit (`Projects/Engines/cockpit`: boundary conditions, country dossier, Excel export covering the old `HoNI_Export.xlsx`) |

## Run it

From this folder, with PostgreSQL up (`docker compose up -d` in `Projects\PostgreSQL`):

```bash
python -m venv ..\..\.venv                  # once, shared by the Macro engines
..\..\.venv\Scripts\pip install -e .[dev]
python -m honi init-db                      # once per server: database, schema, seeds
```

Put the local container's password in `config.local.yaml` (git-ignored):

```yaml
database:
  password: mysecretpassword
```

Then start `..\datafeed\start.cmd` (the data, built with `python -m datafeed bootstrap`)
and `start.cmd`. Open <http://127.0.0.1:8002/> for the test bench or `/docs` for the API.
The test bench lists datafeed's snapshots; the one to use is
`matlab-m_ts-2026-01-05.r2.public-dc63bdd6` (Bloomberg plus public fills and the six
consumption replacements).
The test bench also works opened straight off disk (`testbench/index.html`); it then
calls `http://127.0.0.1:8002`, or whatever `?api=` says.

```bash
python -m pytest            # 125 tests, against the real server and a real datafeed
```

The suite follows the Instruments engine: PostgreSQL is required (it says so loudly rather
than skipping), every module gets its own throwaway schema, and datafeed is bootstrapped
once per session into its own throwaway schema (`--frozen --offline`) and served as a
separate process, so honi is tested over HTTP exactly as it runs.

## Endpoints

Standard (Guide section 2.1): `GET /health`, `GET /meta`, `GET /contracts`, `POST /run`,
`GET /runs/{run_id}`, `GET /artefacts/{artefact_id}`, `GET /calibration`,
`PUT /calibration`.

Engine specific, additive: `GET /scores/{id}`, `GET /scores/{id}/countries/{code}`,
`GET /saturation/{id}`, `GET /ranges`, `GET /peer-stats/{id}`, `GET /calibration/versions`,
`GET /trends/{id}?window=10&year=` (trend and level of every series over a trailing window, D-29),
`GET /model?economy=US` (the model explained on one economy's data, shown on the cockpit's Models page, D-30).

```bash
curl -X POST localhost:8002/run -H "content-type: application/json" \
     -d '{"snapshot_id": "matlab-m_ts-2026-01-05.r2.public-dc63bdd6"}'
# {"run_id":"RUN-...","status":"succeeded","artefact_id":"HNS-...","idempotency_key":"IDK-...","cached":false}
```

`POST /run` accepts `{snapshot_id, countries?, window?: {start_year, end_year},
calibration_version?}`. The same request twice is answered from the cache (`cached: true`).
A run that cannot finish is recorded as `failed` with the reason on `/runs/{run_id}`.

Before every run honi calls datafeed's `/coverage`. The run's coverage report lists the
input cells datafeed filled from public sources (`public_fills`) and the indices dropped on
datafeed's plausibility findings (`excluded`).

## Calibrations

| Version | Use |
|---|---|
| `1.1.0` | **Active.** 1.0.0 plus the datafeed gate: consumption dependency is dropped (and the sector re-weighted) for a country where datafeed finds consumption and GDP in different units. On the production snapshot it finds none. |
| `1.0.0` | HoNI2.m ranges; missing indices excluded and re-weighted, 3 of 5 per sector. |
| `0.1.0-matlab` | Reproduces HoNI2.m (a gap scores 1). Reconciliation only. |

## Layout

```
config.yaml            port, upstream, store, peer set (codes), active calibration. No password.
                       Country names come from datafeed's registry.
src/honi/
  api.py               FastAPI routing only
  contracts.py         Pydantic models, in and out; depends on nothing
  engine.py            the model: pure functions, no I/O, no clock
  calibration.py       the seed parameter sets (ranges, weights, policies)
  clients.py           typed caller for datafeed
  store.py, schema.sql PostgreSQL persistence; calibrations and artefacts append-only
  service.py           orchestration: the only module that touches store, client and model
  settings.py          configuration loading and precedence
tests/                 unit, property, golden, API, store and concurrency tests
golden/                frozen MATLAB references and the snapshot (see golden/README.md)
testbench/             development front end (Plotly). Not deployed.
dev/                   deploy builder. Not deployed.
```

## Model in one screen

| Sector | Index | Definition | Range (min, mid, max) | Function |
|---|---|---|---|---|
| Financial | budget_balance | budget balance, % GDP | -0.10, -0.035, 0 | ramp |
| | monetary_supply | 5y mean of (broad money growth - GDP growth) | -0.01, 0.02, 0.05 | tent |
| | government_debt | government debt, % GDP | 1.2, 1.0, 0.3 | ramp, descending |
| | real_rate_10y | 5y mean of (10y yield - CPI) | -0.01, 0, 0.03 | ramp |
| | market_cap | market capitalisation, % GDP | 0.3, 0.7, 1.2 | tent |
| International | external_debt_affordability | 5y mean of (trade balance / external debt) | -0.05, 0, 0.10 | ramp |
| | external_debt_exposure | external debt / GDP | 0.1, 0.5, 5.0 | tent |
| | terms_of_trade | 5y mean of the terms of trade | -25, -5, 5 | ramp |
| | import_reserves | reserves / imports | 0, 0.5, 2.0 | ramp |
| | corruption_freedom | freedom from corruption | 20, 40, 85 | ramp |
| Real | consumption_power | wage growth - CPI | -0.05, 0, 0.05 | ramp |
| | population_growth | population growth | 0, 0.008, 0.015 | tent |
| | gdp_per_capita_growth | 5y mean of (GDP per capita growth - CPI) | -0.01, 0.03, 0.05 | ramp |
| | consumption_dependency | household consumption / GDP | 0.40, 0.55, 0.70 | tent |
| | labour_force | labour force participation | 0.5, 0.7, 0.85 | ramp |

Ramp: 1 at min, 2.5 at mid, 5 at max. Tent: 5 at mid, 1 at and beyond either end.
Sector = weighted mean of present indices (at least 3 of 5), rescaled per year to [1, 5]
across the peer set; national = equal thirds of the sectors, rescaled again.

## Configuration

Precedence, lowest to highest: `config.yaml` < `config.local.yaml` <
`HONI_DATABASE_URL` / `DATABASE_URL` < `HONI_DB_*`, `HONI_HOST`, `HONI_PORT`,
`HONI_DATAFEED_URL`, `HONI_CORS_ORIGINS`. The engine has its own schema (`honi`)
and login role (`honi`) in the shared database `simtech` (Engine Building Guide section 8).

Before deployment: set the password through the environment, use `sslmode=require` for
anything over a network, and narrow `HONI_CORS_ORIGINS`.

## Deploy

```bash
python dev/make_deploy.py          # writes ..\..\deploy\honi
```

The deploy folder holds `src/honi`, `pyproject.toml`, `config.yaml`, this README,
`DECISIONS.md` and a start script: no tests, no golden files, no test bench, no dev tools,
no `config.local.yaml`.

## Open points

- The default window is 19 years (2007-2025): the snapshot's first year has no growth rates.
- A MATLAB rerun of `HoNI_Exporter.m` on the current `M_TS.mat` would give a true
  end-to-end golden pair (`golden/README.md`).
- Build Manual open decisions 3 to 5 (fixed or dynamic peer set, non-Bloomberg sources,
  target runtime) are unchanged; 1 and 2 are answered for now by D-08 and D-09.
