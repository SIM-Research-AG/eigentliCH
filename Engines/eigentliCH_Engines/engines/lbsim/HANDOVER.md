# lbsim: handover after B1 (29.09.2026)

B1 built the parts everything else stands on. This note says what is there, what B2 and C take over, and what
to watch.

## What is there

- `lbsim.contracts`: every model of spec section 3 and the upstream mirrors. The paths contract keys `bands` by
  series: `net_worth` and each goal measure present (`drawable`, `deposit_eligible`, `retirement_capital`); the
  fan route's `series=goal_measure` means the designated goal's measure.
- `lbsim.engine.build_findings(sheet, request, lbs_records, calibration, sheet_sha256=..., lbs_url=...)`: the
  findings artefact, pure, about 10 ms a household. `lbs_records` are the lbs calibration's `human-capital` and
  `property-funding`.
- `lbsim.calibration`: `SEED` (1.0.0), `ACTIVE_SEED` (1.1.0), `calibration_hash`, `tables(cal)`.
- `lbsim.model`: the numpy model, the parity target for C's symbolic port.
- `golden/samples`: `findings.sample.json` (the engine's), `paths.sample.json` and `plan.sample.json`
  (hand-built, marked `made_by: sample`), and `upstream/` (the bench pcp Allocation `PCP-5304eca69cc0e867` on
  the Default Regime, fmre's five ReturnSets and inflation tables, aggregation's blended distributions, the
  scenario labels), read only from the running engines on 29.09.2026.
- 457 tests.

## B2 takes over

- The vectorised Monte Carlo (`lbsim.paths`, must import without casadi): monthly steps, the market rule of
  LBSIM-07 with the calibration's `market` and `property` blocks, `SeedSequence(seed).spawn(3)`, common random
  numbers across Regimes, chances in the goal's basis (LBSIM-09), real bands from the same draws (LBSIM-10), the
  parity test against the draft's `simulate`, the section 5 budget. `dev/build_samples.py` shows one reading of the
  rule on real figures; it is a sample, not the engine.
- Upstream clients on the mirrors in `contracts.py`, with the checks of section 3.8. Found on 29.09.2026: the base
  (nominal) ReturnSet carries no `provenance.inflation_pass_through`; only scenario sets do (`ipt@1.1.0`,
  `IPT-585c7da4656ead2b`). The `accept_ipt` check belongs to scenario sets only. An Allocation's `currency` can be
  absent (before PCP-18) and its fallback sits in `provenance.hard_currency_fallback`.
- Store and schema, service and API (section 3.7), `settings.py` reading `config.yaml`, the worker harness
  (queue, heartbeat, supersede, cancel, budget) calling `lbsim.optim.solve(problem) -> PlanOutcome`.
- Resolving the request: horizon (LBSIM-18), income path, n_paths and seed defaults from `config.yaml`, the
  idempotency keys of section 3.9 (the findings key is already `build_findings`'s).
- README and DECISIONS: extend the sections here rather than start new ones.

## C takes over

- `lbsim.optim` (`symbolic`, `problem`, `goals/spec`, `mpc`) with theta fixed at 1 and per-state returns as
  parameters, the variable grid in `ACTIVE_SEED.optimiser.grid` (0.5-year steps to 10 years, 1-year steps to 20),
  the terminal requirement beyond the cap (`paths.saving_required` at zero return), `max_wall_time`. The draft's
  solver settings are `SEED.optimiser`. The plan confidence is `optimiser.confidence` (0.90).
- Parity against `lbsim.model` on every step length; the draft's slow `test_optim` cases under 1.0.0.

## To watch

- The draft's frontier raises without a stated stop age (DECISIONS P-1); layer A keeps the error, the adapter's
  submissions do not.
- The findings-text record and the two tables are provisional (no named approver); findings are computed without
  a gate and `provenance.records` says so. An owner's approval is a new calibration version.
- The samples' Allocation belongs to client `bench`; a real run would refuse the mismatch (409).
