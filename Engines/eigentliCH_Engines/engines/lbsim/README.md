# Engine 14: LifeBalance Simulator (`lbsim`)

What a household's Life Balance Sheet means over time: the deterministic findings on the sheet, the Monte Carlo
paths of its wealth under the stated plan in every market Regime, and a background plan calculation. The engine
page is Notion `3e80ba72543f819abe14c30ca61942f5`; the binding interfaces are `Engines/review/LBSIM_INTERFACES.md`.

| | |
|---|---|
| Family | Client |
| Module | `lbsim`, installed editable in `eigentliCH_Engines/.venv` (`pip install --no-deps -e .`) |
| Port | 8014 (`config.yaml`) |
| Status | Built: contracts, model port, fast half, adapter, calibrations (B1); Monte Carlo, upstream clients, store, service, API, worker harness, test bench (B2); optimiser `lbsim.optim` (C); the capitals on the paths and the bench's client picker and graphs (F, engine 1.1.0). Active calibration 1.5.0. |
| Consumes | lbs 8013 (sheet, its request, calibration); pcp 8007 (Allocation); aggregation 8004 (Regimes); fmre 8006 (ReturnSets, inflation) |
| Produces | `LifeBalanceFindings` (`LSF-`), `LifeBalancePaths` (`LSP-`), `LifeBalancePlan` (`LSO-`) |
| Downstream | report 8015, the consumer app 8017, the cockpit 8000 |
| Store | PostgreSQL `simtech`, schema and role `lbsim` (tables `calibration`, `artefact`, `run`, `run_event`) |

## Running it

```text
..\..\.venv\Scripts\python -X utf8 -m lbsim serve        the API on 8014 and optimiser.workers (3) plan workers
..\..\.venv\Scripts\python -X utf8 -m lbsim serve --workers 0   the API alone
..\..\.venv\Scripts\python -X utf8 -m lbsim worker       one plan worker (--once: until the queue is empty)
..\..\.venv\Scripts\python -X utf8 -m lbsim init-db      tables and seed calibrations, then exit
```

`serve` prepares the store, puts plan runs whose worker died back on the queue, starts the workers as separate
processes and then the API; stopping it stops them. The test bench is served at `/` (development only): what
lbsim does in plain words, a picker of the clients lbsim has computed (no hand-typed ids), and the result as inline
SVG graphs (the wealth fan per Regime, nominal or real, with the goal line; the capitals over time; the chances per
Regime; the income paths; what the plan calculation assumes for this period). The
password of the `lbsim` role lives in `config.local.yaml` (git-ignored), as for lbs; `LBSIM_DB_PASSWORD` or
`LBSIM_DATABASE_URL` override it. `LBSIM_CONFIG` points at another configuration file.

## What a run does

`POST /run` (`lbsim-request@1.0.0`) is synchronous for the fast parts and queues the plan:

1. **Findings** (seconds). lbs's sheet, the request it was built from (`GET /artefacts/{id}/request`, its hash
   checked against the sheet) and the records of the sheet's lbs calibration; the adapter builds the draft's
   submission; `lbsim.fast.build` computes the findings. Keyed as in 3.9; a stored key is reused.
2. **Paths** (under a second of simulation; the upstream reads take most of the run). With an Allocation, pcp,
   aggregation and fmre are read and checked (below), the stated plan is resolved, and the Monte Carlo runs in
   the base Regime and every scenario aggregation lists for it. Keyed as in 3.9; a stored key is reused.
3. **Plan**. The outlook run is recorded, the client's older plan runs are superseded (a queued one fails
   `superseded` at once, a running one stops at its next checkpoint), and a plan run is queued unless `optimise`
   is `no`. `POST /optimise` queues one on demand (idempotent; a curator's goes first).

A client without an Allocation still gets findings (`not_made: no_allocation`). Calibration 1.0.0 reproduces the
draft and makes findings only (`not_made: draft_market`).

## The Monte Carlo (`lbsim.paths`)

- **The model.** One step is the draft's `sim.montecarlo.step` on `lbsim.model.dynamics.drift`, with every
  derivative integrated (the twelve states of the symbolic model: `W_L, W_R, D, E, N, H, age, W_res, W_hol, W_P,
  W_3a, kappa`). Monthly steps (`dt = 1/12`), vectorised over paths; the draft's clamps after each step.
- **The market (LBSIM-07).** Each simulated year is one state 1..25: the base Regime's year 1 is
  `Allocation.curves.regime`, reverting linearly to the long-run distribution over five years; a scenario uses its
  projected month `12k` for five years, then the base. One uniform per path and year from
  `SeedSequence(seed).spawn(3)[0]` goes through every Regime's CDF (common random numbers). Free wealth earns
  `W_L (exp(r_s dt) - 1)` with `r_s` the Allocation's renormalised weights on fmre's per-state log returns.
  Property grows at `ln 1.03 + 0.8 (log_infl_s - ln 1.01) - sigma^2/2 + sigma z`, `z` correlated 0.30 with the
  state's normal quantile, one draw a year.
- **Prices.** Each path carries its price level from the drawn states' log inflation (fmre, CHF). Wages,
  spending, child costs, the partner's income and the AHV rise with it; debt, amortisation, a fixed pillar-3a
  payment and the pillar credits are nominal; the income tax tariff is indexed. At zero inflation every term is
  the draft's.
- **The stated plan.** The findings' income path (`income_path`; default `education` when one is planned or in
  progress, else `today`) until the stop age, the stated spending (indexed), the path's hours on the draft's
  100-hour week, the stated direct amortisation. Without stated spending: the stated saving, else "spends what it
  earns after tax", and the artefact says which (`policy.fallback`).
- **Goals and chances (LBSIM-09).** Home (the deposit; measure `deposit_eligible` = free wealth + pillar 3a + half
  of pillar 2), retirement (the capital the flows from 65 leave open; measure `retirement_capital` = free wealth +
  pillar 3a, pillar 2 excluded because the target already nets its annuity), capital (measure `drawable`). A goal
  in today's francs is judged per path on deflated wealth, one in future francs nominally. A reached home goal
  buys the home (deposit from free wealth, then 3a, then the permitted half of pillar 2, the rest a mortgage at the
  sheet's rate). Under 1.4.0 a capital goal is judged, not paid out (an lbs `other` does not say whether its amount
  is spent or a level to hold), so every goal is judged on the same wealth, as the findings and the plan judge it.
- **Retirement (1.4.0).** The stated stop age as stated, above 65 too. From the later of the stop age and the
  reference age, pillar 2 is an annuity at the findings' 5.25 % (nominal income) and pillar 3a is paid out into free
  wealth. A stated salary pays the employee's half of the pillar-2 contribution. Up to 1.3.0 the draft's model
  household: both pillars only accrue, and the cash flow pays the whole contribution (DECISIONS P-21 to P-24).
- **Bands (LBSIM-10).** Year-end quantiles p05..p95 of `net_worth` and each goal measure, in both bases; the real
  bands are quantiles of each path's own deflated values. Recorded before any goal of that date is carried out,
  so the band at a goal's date is the value its chance is judged on.
- **Capitals (engine 1.1.0, DECISIONS P-26).** `regimes[].capitals`: the principal's expertise `E`, network `N` and
  health `H`, year-end quantiles p10..p90 from the same draws as the wealth bands, with their scales (`K_E` and
  `K_H` from the calibration; the network on lbs's 0 to 1, raised to the Regime's highest p90 of `N` where its
  paths go beyond it) and de/en labels. Model levels, never money. Optional in the contract: artefacts made before it read
  as they are and keep their bytes and ids. Under the stated plan expertise and health follow the plan alone, so
  their bands are narrow; the network also grows with real net worth.
- **Parity.** `lbsim.paths.reference` holds the draft's `simulate` verbatim (checked against the draft's own
  output, frozen under the draft's interpreter in `golden/mc`) and lbsim's step one path at a time on the draft's
  scalar functions; the vectorised engine equals both path by path to 1e-9 (sigma = 0, the draft's shocks, fixed
  state paths with inflation, both income modes, goal events).
- **Budget.** 2000 paths x 40 years x 5 Regimes, monthly: about 0.7 s (budget 20 s).

## What lbsim checks upstream (3.8, LBSIM-14, LBSIM-15)

| Check | Refusal |
|---|---|
| sheet, allocation or Regime unknown | 404 |
| sheet's `client_ref` or the Allocation's `client` is not the request's | 409 |
| lbs's stored request does not hash to the sheet's `request_hash` | 409 |
| fmre's base ReturnSet id is not the Allocation's, or the raw weights do not reproduce `curves.achieved` to 1e-9 | 409 "the return figures have moved since this allocation; run pcp again" |
| a scenario ReturnSet's `provenance.inflation_pass_through` is not in `upstream.accept_ipt` (the base set carries none) | 409 |
| Allocation without a `currency` (before PCP-18), not CHF, with `provenance.hard_currency_fallback`, on a scenario Regime | 422 |
| fmre cannot compute Swiss inflation in some state (`not_computable`) | 422 |
| an upstream engine does not answer | 503 |

Every refusal is one plain sentence (`detail`). `POST /validate` reports the same as `problems` without storing.

## Endpoints (3.7)

`GET /health`, `/meta` (allowlist: casadi admitted by LBSIM-02, psycopg as LBS-02), `/contracts`, `POST /run`,
`GET /runs[?client_ref=&kind=&status=]`, `/runs/{id}`, `POST /runs/{id}/cancel` (plan runs only),
`/artefacts/{id}` (typed by prefix), `GET`/`PUT /calibration`, `/calibration/versions`, `POST /validate`,
`GET /outlook?client_ref=&life_balance_sheet_id=`, `/findings/{id}`, `/paths/{id}`, `/plans/{id}`,
`/paths/{id}/fan?regime=base&basis=nominal&series=goal_measure`, `POST /optimise`. With the test bench only:
`GET /bench/candidates` (DECISIONS P-27), each client's newest sheet lbsim has run, with a valid request and a
label for people.

`GET /outlook` states the plan as `ready`, `calculating` (with `elapsed_s` and `budget_s`),
`waiting_for_allocation`, `not_possible` (with the reason) or `not_requested`; it never mixes sheets.

## The plan workers (section 5)

- A worker claims the next plan run with `SELECT ... FOR UPDATE SKIP LOCKED`: curator (2) ahead of client (1)
  ahead of system (0), then the oldest.
- It rebuilds the inputs from the paths artefact and the upstream engines (a moved sheet, Allocation or fmre set
  fails the run as `upstream`), builds `lbsim.optim.types.PlanProblem` and calls
  `lbsim.optim.solve(problem, simulate=lbsim.plan.simulate, deadline=..., should_cancel=..., progress=...)`.
  `simulate` is this Monte Carlo under the planned controls (the out-of-sample chance at `seed + 500 000`).
- A heartbeat every 30 s; `should_cancel` is true once the run is cancelled, superseded, taken away or past its
  budget. The budget is 120 minutes of wall clock: past it the run fails `timed_out` and no plan is written.
- A run whose heartbeat stopped for `stale_after_s` goes back to the queue at the next start of `serve` or
  `worker`, at most `max_attempts` (2) times in all, then fails.
- The API process never imports `lbsim.optim` or casadi (LBSIM-03); the worker imports it on its first plan.
  `LBSIM_TEST_SOLVER=module:function` replaces the solver in a worker process (the harness tests only).

## Golden files

| Folder | What | Built by |
|---|---|---|
| `golden/draft` | layer A: the draft's `gameplan.assemble` and `paths.ledger` on 48 cases | `dev/build_golden.py`, draft interpreter |
| `golden/mc` | the draft's own `sim.montecarlo.simulate` on three households, sigma = 0 and seeded | `dev/build_golden_mc.py`, draft interpreter |
| `golden/earning` | the prototype's `human_capital.earning_power` on lbs's golden households | `dev/build_golden_earning.py`, prototype interpreter |
| `golden/lbs_cases` | 21 lbs requests and the sheets lbs builds of them, with the records read | `dev/build_lbs_cases.py` |
| `golden/layer_b` | findings under 1.0.0 and 1.1.0, and `changes.json` | `dev/build_layer_b.py` |
| `golden/upstream` | pcp's bench Allocation, aggregation's base and four scenario Regimes (reduced to the fields lbsim reads), fmre's ReturnSets and inflation, read only on 29.09.2026 | `dev/build_upstream_snapshot.py` |
| `golden/samples` | the findings and paths samples (the engine's own) and the plan sample (hand-built) | `dev/build_samples.py` |
| `golden/legacy` | the paths sample as engine 1.0.0 made it, without `capitals`: an old artefact must still read with its bytes and id | copied on 03.10.2026 |

## Tests

From this folder: `timeout 900 ../../.venv/Scripts/python -X utf8 -m pytest -q -p no:warnings`. The store tests
create a throwaway schema `t_<hex>` as the `lbsim` role and drop it. Slow optimiser tests are marked `slow` and
deselected by default (`-m slow`). `tests/stub.py` stands in for lbs, pcp, aggregation and fmre on the frozen
payloads; `tests/standin.py` holds stand-in solvers built on `lbsim.optim.types`.

## Layout

```text
lbsim/
  config.yaml  config.local.yaml (git-ignored)
  src/lbsim/
    contracts.py calibration.py adapter.py layer_b.py ids.py engine.py errors.py
    model/          the numpy port of the draft's model (no casadi)
    fast/           the fast half: findings
    paths/          the Monte Carlo: market, engine, reference, household, build
    upstream.py     the checks of 3.8 on the upstream payloads
    clients.py      HTTP clients of lbs, pcp, aggregation, fmre
    settings.py store.py schema.sql service.py api.py
    plan.py         the PlanProblem, the Monte Carlo for the optimiser, the plan artefact
    worker.py       the plan workers
    optim/          the optimiser (agent C)
  dev/  golden/  testbench/  tests/
```

Model-derived research output. Not investment advice.
