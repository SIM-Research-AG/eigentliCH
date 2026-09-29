# cycle: Cycle Model engine

> **Notice.** Model-derived research output of the cycle model. Not investment advice.

> **Parked 27.09.2026.** Resume from [HANDOVER.md](HANDOVER.md).

Owns the cycles: the five nested cycles per economy and year, each with its current phase,
and the cycle layer on the 25-bin axis. They sit here, outside the three-body core of
`macrofield` (TB-19, decided 27.09.2026), and go to the aggregation layer.

This is the port of the first draft, `Projects/eigentliCH/engines/Macro_Model/macrofield/model/cycles.py`
and `cycle_bins.py`, onto datafeed's panel, built to the Engine Building Guide and the engine
page "Engine 12: Cycle Model (cycle)". It reproduces the draft to 1e-12 (golden layer A).
`DECISIONS.md` lists every departure and why.

| | |
|---|---|
| Family | Macro Engine |
| Module | `cycle` |
| Default port | 8012 (`config.yaml`, or `CYCLE_PORT`) |
| Consumes | `Panel` from `datafeed` (`GET /panel`, `GET /countries`); `MacroState` from `macrofield` (`GET /runs`, `GET /artefacts/{id}`, calibration 1.1.0) |
| Produces | `CycleState`, `CurrentPhases` |
| Downstream | `aggregation` (8004) |

## Run it

From this folder, with PostgreSQL up (`docker compose up -d` in `Projects\PostgreSQL`):

```bash
..\..\.venv\Scripts\pip install -e .[dev]    # shared venv of the Macro engines
python -m cycle init-db                      # once per server: schema, tables, seed calibration
```

Put the local container's password in `config.local.yaml` (git-ignored):

```yaml
database:
  password: mysecretpassword
```

Then start `..\datafeed\start.cmd`, `..\macrofield\start.cmd` (with at least one successful
macrofield run) and `start.cmd`. Open <http://127.0.0.1:8012/> for the test
bench or `/docs` for the API. The production snapshot is `bloomberg-2026-01-05`.

```bash
python -m pytest            # 109 tests, against the real server and a real datafeed
```

As in honi: PostgreSQL is required (the suite says so rather than skipping), every module gets
its own throwaway schema, and datafeed is bootstrapped once per session into its own throwaway
schema and served as a separate process.

The database role `cycle` owns the schema `cycle` in `simtech` and may read the `datafeed`
schema (Engine Building Guide section 8); it was created on 27.09.2026 with honi's grants.

## Endpoints

Standard (Guide section 2.1): `GET /health`, `GET /meta`, `GET /contracts`, `POST /run`,
`GET /runs/{run_id}`, `GET /artefacts/{artefact_id}`, `GET /calibration`, `PUT /calibration`.
New runs publish `cycle-state@1.2.0`; a stored artefact is served in the version it was published
in (1.1.0 or 1.2.0, C-26).

Engine specific, additive: `GET /cycles/{artefact_id}` (every cycle per economy per year: phase,
angle, level, confidence), `GET /cycles/{artefact_id}/current` (each cycle's phase in the last
year it has one), `GET /calibration/versions`, and `GET /model?economy=US` (the model explained on
one economy's data: inputs, every step with its formula, parameters and charts, outputs;
`model-card@1.0.0`, shown on the cockpit's Models page).

```bash
curl -X POST localhost:8012/run -H "content-type: application/json" \
     -d '{"snapshot_id": "bloomberg-2026-01-05"}'
# {"run_id":"RUN-...","status":"succeeded","artefact_id":"CYS-...","idempotency_key":"IDK-...","cached":false}
```

`POST /run` accepts `{snapshot_id, economies?, calibration_version?, macrofield_artefact_id?, project?}`.
With `project` (default from `config.yaml`, on) the anchored cycles are projected to macrofield's
horizon (2039 today); `observed_until` and `projected_until` on the artefact mark the split (C-22). The same request twice is
answered from the cache. The quality report is the run's `coverage` on `/runs/{run_id}`: cycles
without a position and why, input years not covered, public fills, and the warnings.

## Model in one screen

| Cycle | Kind | Period | Reads | Axis orientation |
|---|---|---|---|---|
| `fundamental_pulse` | band-passed, band 3.0 to 4.5 y | 3.6 y | macrofield output Y, current USD (1.1.0; 1.0.0: datafeed real output growth) | peak aggressive |
| `business` | band-passed, prior +/- 40% | 7 y | macrofield output Y, current USD (1.1.0; 1.0.0: datafeed real output growth) | peak aggressive |
| `credit` | anchored on each economy's credit crisis, its low (1.1.0; 1.0.0: band-passed, unidentified on 20 years) | 18 y | none (1.0.0: real output growth) | peak aggressive |
| `innovation` | anchored: low in 2032, every economy | 47 y | none | peak aggressive |
| `capital` | anchored on a historical reset per economy: low at the reset, peak 90 years later, next reset at 130 (1.1.0; 1.0.0: saturation crossing 3.5, 90-year cosine) | 130 y | none (1.0.0: capital saturation) | **peak cautious** |

* **Inputs.** Annual, December cells. Real output growth = `np.gradient(log(GDP / CPI index))`;
  capital saturation = total debt over GDP, as honi. Only the trailing contiguous span of an input
  is used; a gap is never filled.
* **Estimated cycles.** Christiano-Fitzgerald band-pass, analytic signal (Hilbert): phase and
  amplitude; dominant period by Welch's spectrum inside the band. A cycle needs a sample of two of
  its periods, or it is reported unidentified with the shortfall. On the 20-year window that rules
  the credit cycle out everywhere.
* **Phases.** From the phase angle, 0 at the peak: `recovery`, `expansion`, `slowdown`,
  `contraction`, in that order. Backward steps are listed in `order_breaks`.
* **Superposition and synchrony.** Unit-amplitude sum of the interference members and their
  alignment (0 cancel, 1 all agree); windows where three or more are within 0.5 rad. Both need
  every member, so they stop where pulse and business stop. `superposition_anchored` is the same
  weighted mean over the anchored members only (credit, innovation, capital; weights re-normalised
  to their sum), over every year including the projection (C-25).
* **Cycle layer.** Each cycle as a split-normal kernel on bins 1 (cautious) to 25 (aggressive):
  centre from `orientation * cos(phase)`, width from what the position is worth (measured,
  supplied, assumed, marginal), skewed 0.35 toward the direction of travel; mixed linearly.

## Calibrations

| Version | Use |
|---|---|
| `1.3.0` | **Active.** 1.2.0 with the capital shape inverted: peak at the reset, low at saturation 90 years later, next reset at 130; high level means aggressive for every cycle (C-21). |
| `1.2.0` | 1.1.0 with the capital peak read as aggressive on the 25-bin axis (orientation +1) (C-20). |
| `1.1.0` | 1.0.0 with the capital cycle anchored on historical resets (US 1933, TH 1932, CH 1936, ES 1939, EU/GB/JP 1945, PH 1946, IN 1947, CN/DE 1948, MY 1963, BR 1964, ID 1966, BD 1971, VN 1986), rising 90 years to its peak and falling 40 to the next reset at 130 (C-16); credit anchored on each economy's crisis low, 18 years (C-17); pulse and business band-passed from macrofield's output, current USD, axis back to 1972 (C-18). |
| `1.0.0` | The five nested cycles, the draft's figures unchanged. The golden reconciliation runs on it. |

## Layout

```
config.yaml            port, upstream, store, default economies, active calibration. No password.
src/cycle/
  api.py               FastAPI routing only
  contracts.py         Pydantic models, in and out; depends on nothing
  engine.py            the model: pure functions, no I/O, no clock
  calibration.py       the seed parameter set (cycles, bands, anchors, widths, thresholds)
  clients.py           typed caller for datafeed
  store.py, schema.sql PostgreSQL persistence; calibrations and artefacts append-only
  service.py           orchestration: the only module that touches store, client and model
  settings.py          configuration loading and precedence
tests/                 unit, property, golden, API, store and concurrency tests
golden/                the frozen production snapshot and the draft's output on it (golden/README.md)
testbench/             development front end (Plotly). Not deployed. "Over time": the five cycles,
                       the aggregate (superposition, solid; superposition_anchored, dashed, after
                       the data edge) and alignment below with the synchrony windows (R-004).
dev/                   deploy builder. Not deployed.
```

## Configuration

Precedence, lowest to highest: `config.yaml` < `config.local.yaml` < `CYCLE_DATABASE_URL` /
`DATABASE_URL` < `CYCLE_DB_*`, `CYCLE_HOST`, `CYCLE_PORT`, `CYCLE_DATAFEED_URL`, `CYCLE_MACROFIELD_URL`,
`CYCLE_CORS_ORIGINS`. Before deployment: password through the environment, `sslmode=require`
over a network, narrow `CYCLE_CORS_ORIGINS`.

```bash
python dev/make_deploy.py          # writes ..\..\deploy\cycle
```

## Open points

- **Credit cycle.** Anchored on crisis dates in 1.1.0 (C-17). Long BIS credit-to-GDP history in
  datafeed would let it be estimated from credit instead.
- **macrofield runs on its own static snapshot**, not datafeed, so the output the pulse and business
  cycles read can differ from datafeed's GDP. When macrofield reads datafeed, the two converge.
- macrofield ends in 2024 (IN 2022 with 2019-2021 dropped, VN 2022), so those two cycles' current
  phase lags the panel's final year by one year or more.
- **Data need.** The six series are all in datafeed already; nothing new is needed for 1.0.0.
- The test bench has not been checked in a browser (its script is syntax-checked and the
  aggregate helper was run under node on real output, 28.09.2026).
