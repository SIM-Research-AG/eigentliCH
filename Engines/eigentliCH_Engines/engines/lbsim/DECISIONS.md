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

- **P-9 the draft's step integrates seven states.** `sim.montecarlo.step` adds only `dW_L, dW_R, dD, dE, dN, dH,
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
  reached capital goal pays its lump sum; a retirement goal is only judged. The year end is recorded before a goal
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
