# lbsim: decisions

LBSIM-01 to LBSIM-19 are the owner's and the planner's decisions of 29.09.2026, as `Engines/review/LBSIM_INTERFACES.md`
section 2 states them. Below each, what the build does with it (B1 the core, B2 the Monte Carlo, the clients, the
store, the service and the workers, C the optimiser). The port notes after them record what the port had to decide
against the draft or the spec.

## The nineteen

- **LBSIM-01 anatomy.** lbs is the template: settings, store, service, API; `eigentliCH_Engines/.venv`, port 8014,
  schema and role `lbsim`. B1 laid out `contracts`, `calibration`, `model`, `fast`, `adapter`, `config.yaml`,
  `pyproject.toml`. The schema and role are provisioned (agent A). `settings`, `store` (`schema.sql`:
  `calibration`, `artefact`, `run`, `run_event`; every table commented, no REAL column, append-only by trigger),
  `service`, `api`, `worker` and `python -m lbsim serve | worker | init-db` follow lbs; the password is read from
  `config.local.yaml` as lbs does.
- **LBSIM-02 casadi.** `casadi==3.7.2` is a declared dependency, imported only inside `lbsim.optim`; `/meta` reports
  it admitted. The plan key reads casadi's version from its metadata, so the API never imports it.
- **LBSIM-03 import boundary.** `lbsim.contracts`, `lbsim.calibration`, `lbsim.adapter`, `lbsim.fast` and
  `lbsim.model` import without casadi; a test runs them in a fresh interpreter and checks `sys.modules`. The draft's
  chain `gameplan -> onboarding -> cases -> optim -> casadi` is cut by restating the one alias `gameplan` read from
  `onboarding` (`{"mortgage_rate": "i"}`), held equal to the draft's by a test. `lbsim.paths`, `service` and `api` add
  to the list: a fresh interpreter creates the app, runs `POST /run` and `POST /optimise` and holds neither casadi
  nor `lbsim.optim` in `sys.modules`; only `worker.default_solver` imports `lbsim.optim`.
- **LBSIM-04 lbs keeps no upstream engine.** Every lbsim artefact names its `life_balance_sheet_id`; the findings
  record the sheet's id, request hash, calibration and sha256 in `provenance.upstream.lbs`.
- **LBSIM-05 the household is stated once, in lbs.** The adapter reads the sheet and the request lbs returns from
  `GET /artefacts/{id}/request`, and nothing else about the household.
- **LBSIM-06 three artefacts.** `LSF-`, `LSP-`, `LSO-`. `POST /run` stores the findings and, with an Allocation, the
  paths, synchronously; the plan is written by a worker only for a finished solve. A client without an Allocation
  still gets findings (`not_made: no_allocation`).
- **LBSIM-07 the market.** In the calibration as `behaviour.market` (`draft` in 1.0.0, `allocation` in 1.1.0) with
  `market` (reversion 5 years, persistence 0, five scenario years, pass-through 1.0) and `property` (ln 1.03,
  beta 0.8, anchor ln 1.01, sigma 0.08, rho 0.30). `lbsim.paths.market` applies it (README "The Monte Carlo");
  paths are made under `market: allocation` only, so calibration 1.0.0 gives findings alone (`draft_market`). It
  moves nothing in the findings (layer B confirms it).
- **LBSIM-08 two inflation assumptions.** The findings use the sheet's `real_view.inflation` under 1.1.0: wages and
  spending rise with it, goals are read in the francs of their date, the pillar-2 accrual is nominal (in today's
  francs, the draft's loop at the real credited rate), and the tax tariff is indexed. `inflation` in the artefact
  states the rate and its source.
- **LBSIM-09 chance in the goal's own basis.** A goal in today's francs is judged on each path's deflated measure, a
  goal in future francs nominally; `GoalTarget` carries the other basis converted at the median path's price level
  at the goal's date (the dashed line of chart 3).
- **LBSIM-10 fan quantiles in both bases.** The real bands are quantiles of each path's deflated values from the
  same draws (a property test recomputes them), labelled `derived: true` with the deflator; paths are not stored,
  the seed reproduces them.
- **LBSIM-11 one earning-power computation.** `lbsim.fast.earning` is the prototype's `human_capital.earning_power`
  (the draft's `dynamics.earning_power` at the record's 0.7207, times the responsibility tier), reproduced to 1e-9
  on lbs's golden households. Under 1.1.0 the income paths use that `earning_power_at_unit`, and a household with
  no income at all is levelled at the modelled full-time income (tier multiplier times the 40/100 BFS share).
- **LBSIM-12 AHV and BVG.** The two tables are seed records; a test pins every figure they share with lbs's
  `ahv-pension` and `bvg-projection` records (and the draft `Params` figures that rest on them) to equality.
- **LBSIM-13 calibrations mirror lbs.** 1.0.0 reproduces the draft (layer A); 1.1.0 is active (layer B with
  `changes.json`). Both hashes are pinned.
- **LBSIM-14 CHF only.** `behaviour.currencies = ("CHF",)`; the adapter refuses a sheet whose real view is not in
  CHF. `lbsim.upstream.check_allocation` refuses an Allocation without a currency (before PCP-18), in another
  currency, or with `provenance.hard_currency_fallback`, and `check_base_regime` one on a scenario Regime (422).
- **LBSIM-15 strict upstream consistency.** fmre's base set for the Allocation's Regime (on the Allocation's basis)
  must carry its `return_set_id`, and the raw weights must reproduce `curves.achieved` to 1e-9, else 409. On the
  live bench Allocation the difference is 5e-16; on the live check's Allocation 7e-17.
- **LBSIM-16 the optimiser does not choose the portfolio.** In the plan contract (`action_now` without theta); C's.
- **LBSIM-17 findings never say "buy".** Every finding's words are the versioned record `findings-text` (de and
  en, `{figure}` placeholders, no number in a template, `action_kind` ask, quantify or decide_between). A test scans
  every template for the calibrated forbidden verbs, the product words and the 52 instrument names of the pcp
  universe; a mutation check proves the scan catches a "Kaufen".
- **LBSIM-18 horizon.** The request's horizon, else the latest dated goal, else the reference age less the age,
  rounded up to whole years and capped at 60. A goal beyond the horizon is not judged.
- **LBSIM-19 capital goals.** A lbs goal of kind `other` with an amount and a date becomes the draft kind `capital`
  (added to the port's capital kinds; a draft submission never carries it).

## Port notes (B1, 29.09.2026)

- **P-1 the draft's frontier fails without a stop age.** `search._stop_age_values` formats a stop age nobody stated
  and raises, so the draft's frontier exists only for a household that named one (45 of 48 layer A cases carry
  `search.error`). Layer A reproduces the error. A submission from the adapter reads an unstated stop age as the
  reference age, as `paths._working_until` already does, under both calibrations.
- **P-2 the income level without a stated expectation.** The spec says a missing answer is "the model level,
  marked modelled". The draft already reads it so: without an expectation, today's income scaled to a full pensum
  anchors the path, else the model's own level, and both are marked `modelled`. lbsim keeps that rule; an adult's
  modelled earning power is reported beside it (`earning_power[].modelled`), not forced onto a path that would
  then contradict the stated current income in its first year.
- **P-3 goal amounts.** A property goal is its deposit (lbs's `property.mandate_target`: price times the
  occupancy's equity share, the strictest when the occupancy is unknown). A retirement goal is its yearly need in
  today's francs; the ledger turns the gap into capital at the withdrawal rate and reads it in the francs of the
  goal's date (LBSIM-08).
- **P-4 an unchecked rule is never passed.** The draft returns None for both "not triggered" and "not checkable".
  The adapter lists, per rule, the answers the sheet lacks; such a rule is reported unchecked with its question
  keys, and a finding that would fire on a default is withheld. `goal_not_fundable` is always unchecked in the
  findings and names the plan calculation as what answers it.
- **P-5 positions without a vessel.** A financial stock lbs carries without a vessel has no line in the draft; it
  enters `positions_outside_model` through an added key the draft never sees.
- **P-6 the partner.** The draft is single-subject: the second adult's income joins cash flow and tax as a fixed
  figure, and the income paths are the principal's. The findings name this limit when there is a partner.
- **P-7 two conversion rates.** The draft's 5.25 % on the whole pension capital is a declared assumption; lbs's
  6.8 % is the legal minimum on the mandatory part. They are different quantities; the findings name the 5.25 %.
- **P-8 model parameters live in the calibration.** The withdrawal rate (0.03), the plan confidence (0.90), the
  market, property and solver settings are calibration entries (they move the key through the calibration hash);
  `config.yaml` names them for reference and holds how the engine runs.

## Port notes (B2, 29.09.2026)

- **P-9a the draft's step integrates seven states.** `sim.montecarlo.step` adds only `dW_L, dW_R, dD, dE, dN, dH,
  dAge` and drops the other derivatives `drift` returns (`dW_res`, `dW_hol`, `dW_P`, `dW_3a`, `dKappa`), and
  `HouseholdWealth.copy` resets `W_P` and `W_3a` to zero after the first step. lbsim integrates all twelve states of
  the symbolic model. `reference.draft_simulate` keeps the draft's step verbatim and reproduces its frozen output
  (`golden/mc`, draft interpreter); the three golden households set `alpha_kappa = 0` and `y_R = 0`, under which
  the dropped states cannot feed back, so the vectorised engine must equal the draft on its seven states, and does.
- **P-10 property growth.** `ln 1.03 + 0.8 (log_infl_s - ln 1.01) - sigma^2 / 2 + sigma z`, one draw a year spread
  evenly over its twelve steps. The spec's words read as a median; the paths sample and the optimiser read it with
  the `- sigma^2 / 2`, so `ln 1.03` is the log of the expected growth factor. One reading across paths and plan.
- **P-11 the retirement measure.** `retirement_capital` is free wealth plus pillar 3a. Pillar 2 is not counted: the
  retirement target is the capital left open after the AHV and the pillar-2 annuity (P-3), so counting the pillar-2
  capital again would count it twice. The optimiser's `optim.market.MEASURES` counts `W_P` too; until the two agree
  the plan's in-sample and out-of-sample chances of a retirement goal rest on different measures (open point for
  the coordinator and agent C). `deposit_eligible` is free wealth, pillar 3a and half of pillar 2 in both.
- **P-12 prices in the simulation.** Nominal throughout, each path its own price level: wages, spending, child
  costs, the partner's income and the AHV indexed; debt, amortisation, a fixed pillar-3a payment and the pillar
  credits nominal; the income tax tariff indexed (`P tax(taxable / P)`); expertise, network, health real, the
  network ceiling on real net worth, the habit in today's francs. At `P = 1` each is the draft's expression.
- **P-13 goals are carried out.** A reached home goal buys the home at its date (the deposit from free wealth, then
  pillar 3a, then up to half of pillar 2; the rest a mortgage at the sheet's rate, amortised only as stated); a
  reached capital goal pays its lump sum (up to 1.3.0; from 1.4.0 a capital goal is judged only, P-24); a
  retirement goal is only judged. The year end is recorded before a goal
  of that date is carried out, so the band at the goal's date is the value its chance is judged on (agent D found
  the sample's band dropping below the target at the home goal's date).
- **P-14 the reversion.** Year `k` of the base Regime is `latest + (long_run - latest) min((k - 1) / 5, 1)`: year 1
  is the Allocation's own distribution, as the spec says. The hand-built sample used `k / 5`.
- **P-15 the stated plan.** The Monte Carlo of the paths takes labour income from the findings' income path (the
  model supplies the shape, the client the level, as the fast half does), not from `earning_power(E, N) tau_Y`; the
  optimiser's Monte Carlo (`plan.simulate`) takes the model's income under the planned controls, reading the
  household as `optim.run.household` does (the habit starts at `swr` times net worth). Hours are shares of the
  draft's 100-hour week; an education budget is read as part of the stated spending, as the ledger reads it.
- **P-16 who asks, and the queue.** `POST /run` records `requested_by: system/run`; `POST /optimise` records the
  caller. Priority curator 2, client 1, system 0. Every newer outlook run for a client supersedes that client's
  queued and running plans on another key. A run whose worker died twice fails with `failure_kind: solver` and says
  so (the contract has no kind for a lost worker).
- **P-17 the paths key.** As 3.9 states it: aggregation's Regime content is not in it (only the Regime ids are), so
  a Regime whose distributions moved under the same id returns the stored paths until the findings, the Allocation,
  a ReturnSet id or an inflation table changes. Open point for the planner if the Regimes update in place.
- **P-18 the scenarios.** `GET /scenarios` lists every base; lbsim takes those on the Allocation's Regime, the newest
  per policy. A named scenario that aggregation does not list for the base is refused (422).
- **P-19 refusals and the store.** A refusal (404, 409, 422, 503) is raised before anything is stored; the outlook
  run is recorded only for a run that computed.
- **P-20 the samples.** `golden/samples/paths.sample.json` is now the engine's own paths on the snapshot
  `golden/upstream` (pcp's bench Allocation served under the sample's client); the plan sample is rebuilt on it,
  still hand-built. Both files changed bytes on 29.09.2026 (the report's golden pages rest on the old ones).
- **P-9 the draft's income paths, corrected in calibration 1.2.0 (29.09.2026).** Found by B2's live check on a
  household on 56 000 at a 30-hour week with no stated expectation: the `today` path rose to 110 330 in five years,
  and `full_pensum` and `network` were byte-identical to it. The draft's own `paths.ledger`, run under its own
  interpreter on the same submission, does the same (56 000, 62 433, 70 156, 79 502, 90 913, 104 975 at zero
  inflation), so it is the draft's behaviour, not the port's or the adapter's. Three causes, three corrections, all
  behind one switch, `behaviour.income_paths: corrected`:
  1. `gameplan.expertise_after` compounds expertise at `beta_E` (15 % a year) with neither the model's ceiling
     `K_E` nor its depreciation, and every path, `today` included, was credited five years of it. A path is now
     credited only with what its own education and networking add against not doing them (the counterfactual
     the draft's `levers` already uses), so `today` moves only with the sheet's inflation and the age profile.
  2. A path's pensum applied only after an education's end; with no education planned, `full_pensum` and
     `network` equalled `today` exactly. It now applies from today when no education is planned.
  3. The ledger set the whole household's spending against the principal's income alone. The second adult's
     income (fixed in today's francs, the draft's exogenous partner) now joins what a year frees, taxed jointly
     with the splitting factor when married and separately when not, as `gameplan.cash_flow` already does.
  A network path that adds nothing (a network at or above the model's base ceiling) is left out, as the draft
  leaves out education paths without an education. 1.2.0 is a new version because stored seeds are immutable;
  1.0.0 and 1.1.0 keep their bytes and hashes (the switch is left out of the canonical form while unset), layer A
  is unchanged, and layer B's `changes.json` gains the step 1.1.0 to 1.2.0 with every changed leaf attributed to
  P-9. The regression case is `golden/lbs_cases/lbsim-reduced-pensum`, the live household's shape anonymised.


---

## Calibration 1.4.0: the paths' household retires (B2, 29.09.2026)

Found on the live use-case refresh, where several designated goals had a chance of exactly 0.0 (Kurt W., Esther W.,
Reto S., Regula A.; Corinne B. stays at 0.0 and is right, see below). Each is a switch in `behaviour.paths_household`
(`pensions`), read by the Monte Carlo of the paths only: the findings are 1.3.0's leaf for leaf (layer B
`step_1_4_0`), the optimiser's `plan.simulate` keeps the model household the NLP optimises, and 1.0.0 to 1.3.0 keep
their bytes and hashes. 1.4.0 is `CAL-95bbbd2c2f4e7576`, active.

- **P-21 the stated stop age as stated.** The draft's `_stop_age` keeps a stop age only below the reference age (it
  prices an early exit) and drops 68 as "no early stop", so a 67-year-old who works 20 hours until 68 had no
  income in the paths from the first month. The paths read `facts.stop_work_age` as stated.
- **P-22 the employee's half of the pillar-2 contribution.** The draft's model income is the whole cost of
  employment, so its cash flow pays the whole contribution (15 %). A stated gross salary excludes the employer's
  half; the paths' household pays the employee's half from cash, and the fund is credited with the whole.
- **P-23 retirement.** From the later of the stop age and the reference age, pillar 2 is an annuity at the findings'
  conversion rate (5.25 %, `gameplan.PILLAR2_CONVERSION_RATE`), paid as nominal, taxable income, and pillar 3a is
  paid out into free wealth; contributions to both stop. The findings' retirement target already assumes that
  annuity (P-3); without it a retired household lived from free wealth alone and ran it to zero. Net worth drops by
  the pillar-2 capital at that date: the annuity is income, not a stock. `retirement_capital` (free wealth plus
  3a) does not move with the payout.
- **P-24 a capital goal is judged, not paid out.** An lbs goal of kind `other` (LBSIM-19) does not say whether its
  amount is spent (an education) or a level to reach or hold ("Freies Vermögen bis 2034 auf 900 000 aufbauen", "...
  real erhalten"). Paying it out removed a level goal's whole amount on reaching it, and two goals of one date were
  judged on what the first left (Peter's two 2030 goals had chances 0.632 and 0.368, summing to one). Each goal is
  now judged on the same wealth, as the findings' ledger and the optimiser judge it; a home goal is still carried out.

Per client (base Regime, designated goal): Kurt W. "Freies Vermögen bis 2035 real erhalten" 0.0 to 0.997 (P-23);
Esther W. (the goal "Ab 2027 vom Vermögen leben" is an lbs `other` of CHF 200 000 at 2031-12-31) 0.0 to 0.993 (P-21,
P-23); Reto S. 0.0 to 0.803 and Regula A. 0.0 to 0.251 (P-22); Michele 0.287 to 1.0 and Peter 0.632 to 1.0 (P-22,
P-24). Corinne B. stays 0.0: the goal is an lbs `other` of CHF 90 000 in free wealth by 2028-08-31 (today CHF 94 000)
while the findings' own cash flow is CHF -6 800 a year before the stated 3a payment of CHF 7 258; free wealth is CHF
53 000 to 64 000 at the date on every path.

## The optimiser (agent C, 29.09.2026)

This section is agent C's, for `src/lbsim/optim/**`, `tests/optim/**` and `golden/optim/**`. Everything above it
is B1's and B2's.

- **O-1 the handshake.** `lbsim.optim.types` (no casadi) holds `PlanProblem`, `MarketInputs`, `GoalInput`,
  `ControlPath`, `ControlStep`, `PlanOutcome`, `PlanResult` and the result parts; `lbsim.optim.solve(problem, *,
  simulate, deadline, should_cancel, progress) -> PlanOutcome` imports the NLP (and casadi) only when called. A test
  runs `import lbsim.optim` in a fresh interpreter and finds no casadi in `sys.modules` (LBSIM-03). Field names are
  fixed; B2 builds against them.
- **O-2 the port.** `symbolic.py`, `goals.py`, `spec.py`, `problem.py` and `mpc.py` are the draft's, against
  `lbsim.model` (which is the draft's model line for line). Under calibration 1.0.0 with the draft's market the port
  reproduces the draft's three slow `test_optim` solves to the last printed digit (`u0`, in-sample chance, CVaR,
  outcome, costates, iteration count; the golden is `golden/optim/draft_test_optim.json`, built by the draft itself
  under its own interpreter). The draft's long measurement notes stay in the draft; each rule in the port names its
  M-number.
- **O-3 the NLP runs in today's francs (LBSIM-07, LBSIM-08).** Wages and spending pass inflation through at 1.0, so
  the draft's income law, consumption, habit, indexed tax tariff and AHV are real quantities and its drift is used
  unchanged. Per scenario and step: liquid wealth earns `exp((r_s - pi_s) dt)`, real assets `exp(g - pi_s dt)`, and
  debt and both pillars lose `exp(-pi_s dt)` (they are nominal; the drift keeps the nominal interest and the credited
  rates). The draft's market is taken out of the drift (`mu_M = r_f = mu_R = 0`); theta is fixed at 1 by an equality
  and keeps its slot. A calibration with another pass-through is refused (a failed run, `solver`). One state per
  simulated year, from that year's distribution; the property follows `dev/build_samples.py`'s reading (nominal log
  growth less `sigma^2 / 2`, noise correlated 0.30 with the state's normal quantile). The numpy twin is
  `market.numpy_allocation_step`.
- **O-4 the CVaR tolerance on a ratio.** The draft widens its tolerance to `1e-5 * G` for every goal kind, but only
  the FI slack is in francs; on the home, company and retirement ratios (and lbsim's measure slack) that is a
  tolerance of about 1. Measured on the sample household: a bound of 1.2 certified a plan whose in-sample chance was
  0. The port widens only the FI slack; a ratio keeps `optimiser.cvar_tol` (1e-3 of the target). The FI path, and so
  the reproduction, is untouched.
- **O-5 lbsim's goals are a target on a measure.** Home, retirement and capital (LBSIM-19) are tested at the deadline
  as `(level * measure + extra - target) / target`. **One measure for the engine** (the coordinator's decision of
  29.09.2026, following B2's P-11): the NLP evaluates B2's own `lbsim.paths.engine.measure_values` on its symbols for
  the linear measures, and `symbolic._drawable_real` (the exact twin) for `drawable`, so the in-sample and the
  out-of-sample chance judge one quantity; a test holds them equal for every goal kind, with and without haircuts.
  `deposit_eligible` is W_L + W_3a + `pension_deposit_share` W_P; `retirement_capital` is W_L + W_3a, without pillar
  2, because the retirement target is the gap its annuity leaves (counting the capital again would count it twice; the
  port first counted it, and that was corrected); `drawable` is `HouseholdWealth.drawable` with the Params haircuts. A
  goal in the francs of its date is compared nominally with each scenario's own price level; a goal in today's francs
  in real terms (LBSIM-09). The target is the paths artefact's (the retirement target is the capital the fast half
  derives at the withdrawal rate), so the draft's home serviceability test and annuity funding ratio are not used for
  lbsim's goals; they remain for the draft kinds. The normaliser does not move with the target, so the target
  reachable at the confidence is exactly `(1 - s*) * target`.
- **O-6 the grid and the cap.** `grid_rule = variable`: 0.5-year steps while t < 10, 1-year steps to the cap
  (`min(max_solve_horizon_years, last rung)` = 20), ending at the node nearest the latest goal; each goal at its
  nearest node. A goal beyond the last node is tested there against `max(0, target - planned saving x remaining
  years)` (the fast half's `free_cash` for the goal, carried in `GoalInput.planned_saving_chf_per_year`; a negative
  saving raises the requirement above the target), exactly B2's requirement, and the plan says `beyond_cap_rule:
  zero_return_terminal`. `draft_single_step` is the draft's `run_case` rule exactly. Discounting uses each node's own
  time.
- **O-7 the clock.** Each IPOPT call gets `ipopt.max_wall_time` = the time left before the run's deadline (at least 1
  s); the deadline and `should_cancel` are checked before and after every solve; `progress` hears `{phase, start, of,
  seed_attempt, elapsed_s}` before every solve. A stop raises through every layer, so a timed out or cancelled run is
  `failed` with no figures and no call to `simulate`. A cancel waits for the solve in progress (IPOPT is not
  interrupted).
- **O-8 seeds.** In-sample `seed`; redraws `seed + 1000 k` for a pathological draw only, never for a goal phase 1 has
  determined unfundable (M79); out-of-sample `seed + 500 000` with `n_out_of_sample` paths (default
  `optimiser.M_eval`). The allocation scenarios come from one `default_rng(seed)`: the state uniforms (paths x years),
  then the property noise (paths x steps). Every seed tried is in `seeds_used`, a stopped run's too.
- **O-9 outcomes.** `plan` is `solved`. `goal_not_fundable` (phase 1 converged, funding impossible) is a result with
  phase 1's action (what trying hardest assumes, the draft's reading) and `reachable`. The draft's `undetermined` (no
  converged, certified solve) is `failed` / `solver`: no figure from a non-converged solve.
- **O-10 the plan's figures.** `chance.out_of_sample` and `shortfall_cvar_chf` are the injected Monte Carlo's (B2's);
  the in-sample CVaR stays in `diagnostics`. `action_now`: hours are tau x 100 (the productive week), and
  `saving_chf_per_year` is the first period's drift of liquid wealth without the market. `exchange_rate.dominant`
  names the dominant control (`tau_N` or `tau_Y`) or is None. `control_path` is on the grid, `money_basis`
  `today_indexed` under the allocation market (1.1.0 and 1.2.0; C, m_E, m_N indexed by each path's own price level;
  p_A nominal) and `nominal` under 1.0.0, the last step held to the horizon. `ipopt_version` is None: CasADi does not
  report the IPOPT build it bundles; `casadi_version` pins it.
- **O-11 the household.** The state from the adapter's submission with the draft converter's mid-scale defaults (E
  0.5, N 0.5, H 0.8); `Params` through the fast half's own `_params_from` inside the calibration's tables, so the plan
  and the findings read one parameter set; epsilon is `1 - confidence`, clamped to 0.01..0.5 as the draft's converter
  does.
- **O-12 draft features carried unchanged (for the owner, not fixed).** (a) The retirement slack evaluates AHV at the
  deadline state's age plus the horizon again (age0 + 2h) on both the numpy and the symbolic side; harmless for a goal
  at 65 or later, wrong for an earlier one. lbsim's retirement goal is a measure (O-5), so it does not reach the plan.
  (b) The exchange rate's networking value uses `p.K_N0` and the retired multiplicative ceiling, so it can be negative
  (the draft's flagship gives -0.032); the winner is unaffected there. (c) The draft's parity helper set `W_P` and
  `W_3a` after its `return`, so its parity ran with both at zero; the port's parity sets them.
- **O-13 test lanes.** Default: `timeout 900 ../../.venv/Scripts/python -X utf8 -m pytest -q -p no:warnings
  tests/optim` (slow deselected by `pyproject.toml`). Slow: `pytest -m slow --dist loadfile -n 4 tests/optim`; `--dist
  loadfile` keeps the module-scoped `sol_90` solve on one worker. pytest-xdist is not in the family venv (29.09.2026)
  and was not installed; without it the slow lane runs serially with `-m slow`.
- **O-14 `run.reference_simulate`** is a per-path simulation of the NLP's own step, for tests and diagnosis only. The
  engine's out-of-sample chance is B2's Monte Carlo.
- **O-15 the calibrated iteration limit is the binding constraint (for the owner).** Every seed calibration (1.0.0,
  1.1.0, 1.2.0) carries the draft's `run_case` setting `max_iter = 400`. Measured on B2's regenerated sample household
  (29.09.2026, 3-year home goal, allocation market): every phase-2 solve reaches a funded point (CVaR about -0.01) and
  stops at 400 iterations on all three draws, so the run is `failed` / `solver`; at 3000 iterations (the draft's
  `test_optim` budget) the same rule certifies a plan in 2000 to 2700 iterations (in-sample chance 0.93, 459 s). Under
  1.0.0 the draft market fails the same way on this household. Raising the limit is a calibration change (a new
  version, a named approver) and was not made here; on the 20-year grid a 400-iteration solve takes 2 to 17 minutes,
  so 3000 iterations would not fit the 120-minute budget without fewer starts or draws.
- **O-16 the 20-year case.** The sample's 27-year horizon on the 30-step grid (20 half-year and 10 one-year steps, M =
  14, two restore and four best-life starts, three draws): 4077 s, 68 minutes (measured by
  `test_the_20_year_case_finishes_inside_the_budget`, record in `golden/optim/twenty_year_run.json`), inside the
  120-minute budget; a 400-iteration solve takes 2 to 17 minutes on this grid. The outcome is `failed` / `solver`:
  every solve on every draw stopped at 400 iterations (O-15), so no figures. The run finishes; it does not yet plan.
- **O-17 the solves are deterministic.** The same restore solve, five times with OpenBLAS on 20 threads and five times
  pinned to one, all concurrent, gave identical iterations and CVaR to the last bit. Differences seen during the build
  came from B2 regenerating the sample household while runs were starting.
- **O-18 calibration 1.3.0, the owner's plan settings (29.09.2026).** On O-15 the owner set at most 500 IPOPT
  iterations and a solve horizon of 10 years. 1.3.0 is 1.2.0 with the optimiser block changed only: `max_iter` 500,
  the new field `max_solve_horizon_years` 10 (left out of the canonical form while unset, so 1.0.0 to 1.2.0 keep their
  bytes and hashes), and the grid `((10.0, 0.5),)`: 0.5-year steps throughout, a goal beyond year 10 the zero-return
  terminal requirement at the cap. The optimiser takes the tighter of the calibration's cap and `config.yaml`'s (now
  10 as well). Active in `config.yaml`; hash pinned (`CAL-5f544bab06ed5f76`); layer B step 1.2.0 to 1.3.0 moves no
  leaf of the findings (`changes.json` `step_1_3_0`, attributed to O-18); the samples were rebuilt under 1.3.0
  (findings `LSF-11a3e8916675c033`, paths `LSP-7e00fcdca5cc7a83`, plan `LSO-6380a2c95e299202`, the hand-built plan on
  the 10-year grid). Measured on B2's sample household (27-year horizon, home goal at 3 years designated, retirement
  at 27 as extra goal): `solved` on the third draw (seed 20262929), the certified solve 160 iterations, the others of
  that draw stopping at 500; in-sample chance 1.0 (14 of 14), out-of-sample 1.0 from B2's `plan.simulate` (400 paths,
  seed 20760929); 1868 s (31 minutes), inside the 120-minute budget (`golden/optim/ten_year_run.json`). O-15 and O-16
  describe 1.2.0 and stay as the record of why.
- **P-25 each stated income where it belongs, calibration 1.5.0 (29.09.2026).** Found by B2's live refresh: the
  stated expectation at a full pensum ("once any education is done") was the level of every path from today, and
  was multiplied by today's pensum, so a principal working 55 hours who earns and expects 155 000 was shown
  200 846 in the first year of the education path (202 976 on `today`, 200 846 on `full_pensum` before the
  education's end). It is the draft's `paths.build_path` (the anchor levels every age, the share is today's
  pensum), kept by 1.0.0 to 1.4.0. Under `behaviour.income_levels: stated`:
  1. Until an education ends, and on `today` always, a path runs at today's stated income and pensum (today's
     income over today's pensum, moved only by the path's shape, P-9).
  2. From the education's end year (from today when none is stated) a path that changes something takes the stated
     expectation at the path's pensum; the amount is stated at a full pensum, so a pensum above 1 never raises it.
     Without an expectation, today's level carries on at the path's pensum.
  3. Without an education under way or planned there is no education path, whatever hours or budget the answers
     still hold (the draft's rule for a household with no study hours).
  `full_pensum` had the same fault before the end year (the expectation times a pensum above 1). 1.0.0 to 1.4.0 keep
  their hashes; layer B's `changes.json` gains the step 1.4.0 to 1.5.0 with every changed leaf attributed to
  P-25. The regression cases are `golden/lbs_cases/lbsim-overtime-a` and `-b`, the two live shapes anonymised.

## The capitals and the bench (agent F, 03.10.2026)

Under `Engines/review/VISUALS_INTERFACES.md` (the owner's decisions of 03.10.2026). Engine 1.0.0 to 1.1.0; no
calibration and no figure moved.

- **P-26 the principal's capitals on the paths.** `LifeBalancePaths.regimes[].capitals`, optional, for the principal
  (`findings.principal`; the partner enters as income only, P-6): `person_id`; `expertise`, `network`, `health`, each
  the year-end quantiles p10, p25, p50, p75, p90 (`horizon_years + 1` values) of the model's `E`, `N`, `H` over the
  same paths as the wealth bands; `scale` per capital `{min: 0, max}`; `labels` de/en as the spec gives them.
  1. **Scales.** Expertise and health: `K_E` and `K_H` of the calibration's model (`Params`, 1.0 each under 1.5.0).
     The network has no fixed ceiling: the model's `K_N = N_0 + lambda_E E + lambda_W Omega / W_scale + lambda_kappa
     kappa` moves with expertise, real net worth and the habit, and on a wealthy path reaches several times the
     level (4.2 at p90 on the sample, 8.0 at the maximum). Taken as the scale it pressed every band to the floor of
     the chart. So the network's scale is lbs's 0 to 1 (`identities.net_scale`), raised to the highest p90 of `N`
     at any year end of the Regime where its paths go beyond 1. Per Regime, not across them: a shared scale made
     the base Regime's block depend on which scenarios ran beside it, against common random numbers (B2's test
     `test_the_base_is_the_same_whatever_scenarios_run_beside_it` caught it). This is the one reading of the spec's
     "`K_N`" that is not a calibration figure.
  2. **Bytes.** A field that is absent is left out of the serialised artefact (a wrap serialiser on `RegimePaths`),
     so an artefact made before 1.1.0 reads, re-serialises to the same bytes and keeps its content id
     (`golden/legacy/paths.engine-1.0.0.json`). The contract version stays `lbsim-paths@1.0.0`: the change is additive.
  3. **Keys.** The findings key carries the engine version and the paths key carries the findings key, so 1.1.0
     makes new findings and paths under new keys; nothing stored under 1.0.0 is reused for a new run. Findings and
     paths differ from 1.0.0 only in `provenance.engine_version`, the keys and ids, and the new field (checked on the
     samples and on layer B, both rebuilt: findings sample `LSF-a60abb0fa0f37d52`, paths `LSP-85cfcfe62c138e2b`,
     plan `LSO-f6cbce667814155a`; `golden/layer_b/expected` moved in those three fields only, `changes.json` not
     at all).
  4. **Checks** (`tests/test_capitals.py`): same seed same bytes; ordered bands within `[0, max]`; the quantiles are
     the percentiles of the very states the wealth bands come from; at sigma 0 (one fixed state path in every Regime,
     no property noise) the median of each capital is `lbsim.paths.reference.simulate_path`'s scalar path to 1e-9;
     an old artefact reads with its bytes and id.
- **P-27 the bench's client picker.** `GET /bench/candidates` exists only where the test bench does (the route is
  registered with `/`). It lists each client's newest succeeded outlook run (at most 100, newest first) with the
  request it needs (`client_ref`, `life_balance_sheet_id`, the run's `allocation_id`, `optimise: no`) and a label for
  people: the designated goal's name and the sheet's date. lbsim stores no goal names; the name is the one pcp gave
  the mandate (`<template> (<currency>): <goal>`, in the paths' `allocation_view.mandate_name`), the date the
  findings' `as_of`. A sheet without an allocation is "A household without an allocation". Read only: it writes
  nothing. A "Run" from the bench asks for no plan, but `POST /run` still supersedes the client's other plan runs
  (section 5), and the bench says so.
