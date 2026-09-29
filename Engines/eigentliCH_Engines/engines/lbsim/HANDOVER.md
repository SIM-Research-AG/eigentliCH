# lbsim: handover after B2 (29.09.2026)

B1 built the core (contracts, model port, fast half, adapter, calibrations, golden layer A and B). B2 built what
runs it: the Monte Carlo, the upstream clients, the store, the service and API, the plan workers, the test bench.
C builds `lbsim.optim` in parallel. This note says what is there, what the next agents build on, and what to watch.

## What is there

- `lbsim.paths`: the vectorised Monte Carlo (`market`, `engine`, `reference`, `household`, `build`). Parity with the
  draft's own `simulate` path by path to 1e-9 (sigma = 0 and the draft's seeded shocks, `golden/mc`) and with
  lbsim's per-path step on fixed state paths. 2000 paths x 40 years x 5 Regimes in about 0.7 s.
- `lbsim.upstream` and `lbsim.clients`: the reads and checks of 3.8, LBSIM-14 and LBSIM-15.
- `settings`, `store` (`schema.sql`), `service`, `api`: every endpoint of 3.7, the idempotency keys of 3.9, the
  outlook states, supersede and cancel. `config.local.yaml` holds the role's development password (git-ignored).
- `lbsim.plan` and `lbsim.worker`: the `PlanProblem` on C's `lbsim.optim.types`, lbsim's Monte Carlo as `simulate`,
  the queue (`FOR UPDATE SKIP LOCKED`, curator first), heartbeat, stale requeue (two attempts), the 120-minute
  budget, the plan artefact. `python -m lbsim serve | worker | init-db`.
- `testbench/index.html`, served at `/`: health, validate and run on a request, the outlook with chart 3.
- `golden/upstream` (snapshot of pcp, aggregation, fmre for the tests), `golden/mc` (the draft's `simulate`),
  `golden/samples` (the paths sample is now the engine's own).
- 668 tests with C's (not slow); B2's own are `test_mc_parity`, `test_mc_paths`, `test_api`, `test_worker`.

## Live check (29.09.2026)

lbsim ran on 8014 for the test only, without workers, and was stopped afterwards. `POST /run` with
`optimise: "no"` for use-case client `3da6b118ace046f0b505cd2004f319c4` (sheet `LBS-12cd3d520300b535`, Allocation
`PCP-0ec347ff879ad640`, Balanced CHF on the Default Regime) made findings `LSF-65f6e3d0edbae695` and paths
`LSP-dbe83f54d10ba05a` in 15 s (9 s after the upstream reads were made parallel; the simulation is under a second,
the rest is fmre computing each ReturnSet on request). The achieved curve reproduced to 7e-17. Chances: every goal
1.0 in every Regime, except the home goal of 2032 under hyperinflation, 0.0 (median shortfall CHF 15 489 in today's
francs). The store `lbsim` keeps those artefacts and three outlook runs (one with seed 1, for the timing).

## E (the app) and the coordinator take over

- Start `python -m lbsim serve` (API on 8014 and three workers). The cockpit roster's `bench` now exists.
- The app calls `POST /run` with the sheet and the base-Regime Allocation (section 5); `plan_run_id` is the plan's
  `engine_run`, refreshed through `GET /runs/{id}`. The cockpit's "Planrechnung neu starten" is `POST /optimise`
  with `requested_by {kind: curator, ref}`.
- A request with `optimise: "background"` supersedes the client's older plans on another key; a repeated identical
  request returns the same artefacts (`cached: true`) and the same plan run.

## To watch

- **The retirement measure (P-11).** lbsim's `retirement_capital` is free wealth plus pillar 3a; C's
  `optim.market.MEASURES` also counts pillar 2. The target already nets the pillar-2 annuity, so C's reading counts
  it twice, and until they agree a retirement plan's in-sample and out-of-sample chances differ. Coordinator's call.
- **High chances on the Balanced allocations.** On the bench Allocation, fmre's per-state profiles give a long-run
  mean log return of 11.0 % a year against 0.6 % inflation, and the draft's income paths let skill grow for five
  years (the "today" path doubles a young earner's income). Most goals then reach a chance of 1.0; the paths do
  what their inputs say.
- **The paths key (P-17)** does not move with aggregation's Regime content under the same id, as 3.9 states.
- **The samples changed bytes** (`paths.sample.json`, `plan.sample.json`); the report's golden pages rest on the old.
- The plan sample stays hand-built until C's solver produces one; `tests/test_worker.py` has a slow end-to-end test
  of C's real solve (`-m slow`).
