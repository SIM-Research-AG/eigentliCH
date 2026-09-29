# lbsim (Engine 14) and the allocation charts: the interfaces (for the build of 29.09.2026)

The engine page is Notion `3e80ba72543f819abe14c30ca61942f5`. The draft is
`Projects/eigentliCH/engines/Life_Balance_Sheet/personal_alm` (with `personal_alm_spec.md`); it is read only.
The owner's decisions of 29.09.2026 bind every part (memory `lbsim-decisions`, and section 10 below).

Everything outside lbsim is **additive and opt-in**: no existing contract version string changes, a request
without the new fields hashes exactly as today, and stored artefacts read back unchanged. Everything is stored
nominal; real is derived, log returns throughout: `real = nominal - ln(1 + inflation)`. The old Engine 10
`scenario` is not used anywhere.

## 1. Dependencies

- CasADi is needed for the optimiser only (`optim/problem.py`, `optim/symbolic.py`, `goals/spec.py`). IPOPT
  ships inside the CasADi wheel (`libcasadi_nlpsol_ipopt.dll`, `libipopt-3.dll`); no separate install.
- Hidden coupling in the draft: `app/gameplan.py` -> `app/onboarding.py` (`_PARAM_ALIASES`) -> `cases.py` ->
  `optim/problem.py` -> `casadi`. The port breaks this chain (LBSIM-03).
- numpy only otherwise. scipy is declared but never imported: not needed. matplotlib unused.
- Python: the draft venv and `eigentliCH_Engines/.venv` are both CPython 3.12.10. The family venv has no casadi.
  Install: `..\.venv\Scripts\python -m pip install casadi==3.7.2` (wheel `cp312-none-win_amd64`, depends on
  numpy only, about 200 MB). Acceptance: an IPOPT solve of `min x^2` runs in that venv.
- casadi is not on the Guide allowlist; admitted by LBSIM-02 (as psycopg by LBS-02), reported by `/meta`.
- Missing draft data: `model/bvg.py` and `model/canton.py` read `Projects/eigentliCH/data/social_insurance.json`
  and `canton_tax.json`; that folder does not exist. The only copies are in
  `Projects/andersCH-prototype_old/andersCH-prototype_old/data/` (BSV 2026, dated 2026-01-01). They become
  lbsim calibration seed records.

## 2. Decisions (LBSIM-01..19)

1. **LBSIM-01 anatomy:** Engine Building Guide, lbs as the template (settings, store, service, API);
   `eigentliCH_Engines/.venv`, port 8014, schema and role `lbsim`.
2. **LBSIM-02:** `casadi==3.7.2` admitted, imported only inside `lbsim.optim`.
3. **LBSIM-03 import boundary:** the API process never imports casadi. `lbsim.fast`, `lbsim.model`,
   `lbsim.paths` import without it (a test checks `sys.modules`). Only optimiser workers load it.
4. **LBSIM-04 lbs keeps no upstream engine (LBS-01):** lbs does not fill `earning_power` from lbsim (it would
   be a cycle; the sheet must be instant; its content id would depend on a stochastic engine; lbs reads no
   engine at run time, LBS-32). `human_capital[].earning_power` stays `not_available` with the existing gap
   `owned_by_another_engine` naming lbsim. The pointer runs the other way: every lbsim artefact names its
   `life_balance_sheet_id`; consumers find results through `GET /outlook`.
5. **LBSIM-05 the household is stated once, in lbs (LBS-04):** the new answers go into `lbs-request@1.0.0` as
   optional additive blocks, validated there, not computed there. lbsim reads the request back through a new
   lbs endpoint. A changed answer makes a new sheet, which is the trigger.
6. **LBSIM-06 three artefacts:** Findings `LSF-` (deterministic, lbs only, seconds); Paths `LSP-` (Monte Carlo
   under the stated plan per Regime; needs pcp, aggregation, fmre and a seed); Plan `LSO-` (the optimiser, in
   the background). A client without an Allocation still gets findings.
7. **LBSIM-07 the market:**
   - The portfolio is the pcp Allocation; lbsim never chooses one. The draft's tilt θ and Gaussian `μ_M/σ_M`
     are replaced; θ is fixed at 1 (its control slot and the costate layout survive). Market term
     `W_L·(exp(r_s·dt) − 1)`, `r_s = Σ_i w_i · profile_i(s)`: renormalised weights times fmre's 12-month
     annualised log-return profiles.
   - Each simulated year draws a state 1..25 from the client's blended distribution: year 1 is the Regime's
     latest (for the base Regime exactly `Allocation.curves.regime`), reverting linearly to the long-run
     distribution (mean over every assessed date, same economy weights) over `market.reversion_years` = 5.
   - A scenario Regime uses its projected months (year k takes month 12k) for `horizon_months`/12 = 5 years,
     then the base Regime's distribution, profiles and inflation ("shock, then normal").
   - Draws i.i.d. across years (`market.state_persistence` = 0, a calibration entry for later).
   - Inflation per state from fmre `/v1/inflation` (CHF); under a scenario the scenario's own; the ipt@1.1.0
     pass-through is already inside fmre's scenario ReturnSets.
   - Property: nominal log growth `ln(1.03) + 0.8·(log_infl_s − ln 1.01)` plus `σ_R` = 0.08 noise, correlated
     ρ = 0.30 with the market (market side = normal quantile of the drawn state's position in the Regime CDF).
   - Wages and spending pass inflation through at 1.0; debt, BVG credits and a fixed contribution are nominal.
8. **LBSIM-08 two inflation assumptions:** the deterministic findings use the sheet's own
   (`real_view.inflation`, CHF 1.0 %) so goal figures match lbs; the Monte Carlo draws inflation with the
   states from fmre. Each artefact states which.
9. **LBSIM-09 chance in the goal's own basis:** a goal in today's francs is judged per path in real terms
   (wealth deflated by that path's inflation); a goal in future francs nominally. In the other basis the goal
   line is dashed, converted at the median path's inflation, labelled. One chance per goal and Regime,
   independent of the view.
10. **LBSIM-10 fan quantiles stored in both bases:** a quantile of deflated paths is not a deflated quantile, so
    real bands are computed at simulation from the same draws, labelled `derived: true` with the deflator.
    Paths are not stored; the seed reproduces them.
11. **LBSIM-11 one earning-power computation:** the prototype's `human_capital.earning_power`: the draft's
    `dynamics.earning_power(E, N, age)` at lbs's `human-capital` record
    `earning_power.calibration.earning_power_at_unit` (0.7207), times the responsibility tier multiplier
    (kader, sector). E and N from lbs's sheet; the record from the lbs calibration in the sheet's provenance.
    Income paths use this `at_unit`, not the draft's 0.75 (calibration 1.1.0; 1.0.0 reproduces the draft).
12. **LBSIM-12 AHV and BVG:** port `bvg.py` and `canton.py` with the two tables as seed records
    (`social-insurance`, `canton-tax`). A test pins every figure overlapping lbs's `ahv-pension` and
    `bvg-projection` records to equality.
13. **LBSIM-13 calibrations mirror lbs:** 1.0.0 reproduces the draft (golden layer A: zero inflation, the
    draft's `Params()`, `run_case` solver settings). 1.1.0 is lbsim's behaviour (golden layer B with
    `changes.json`: sheet inflation, `at_unit` from the record, the market adapter, CHF only). 1.1.0 active.
14. **LBSIM-14 CHF only in v1:** an EUR/USD Allocation, a real Allocation on a hard-currency fallback
    (PCP-23), or an Allocation on a scenario Regime is refused 422 with a plain reason. Scenarios are simulated
    alongside the base, never as the base.
15. **LBSIM-15 strict upstream consistency:** fmre's ReturnSet for the Allocation's Regime and currency must
    carry the Allocation's `return_set_id`, else 409 "the return figures have moved since this allocation; run
    pcp again". `Σ raw_weight_i · profile_i(s)` must reproduce `Allocation.curves.achieved` to 1e-9.
16. **LBSIM-16 the optimiser does not choose the portfolio:** it chooses time shares, consumption, education and
    network spend, amortisation (the draft's controls less θ), for the lbs mandate proposal's designated goal
    plus every other dated goal as `extra_goals`.
17. **LBSIM-17 findings never say "buy":** `action_kind` is `ask`, `quantify` or `decide_between`. Wording is a
    versioned content record `findings-text` (`de`, `en`, `{figure}` placeholders). A test scans every template
    for a calibrated list of forbidden verbs (kaufen, verkaufen, investieren in, buy, sell, invest in, ...) and
    any instrument or product name.
18. **LBSIM-18 horizon:** findings and paths run to the latest goal date, else the principal's reference age
    (65), capped at `simulation.max_horizon_years` = 60. The optimiser's grid and cap are in section 5.
19. **LBSIM-19:** a lbs goal of kind `other` with an amount and a date maps to a new draft goal kind `capital`
    (a lump sum on drawable wealth).

## 3. lbsim contracts

All models frozen, `extra="forbid"`; upstream mirrors `extra="ignore"`, reading only needed fields. CHF amounts,
decimal rates a year, annualised log returns, chances in [0, 1], ages in years. Content-hash ids: Findings
`LSF-<16hex>`, Paths `LSP-`, Plan `LSO-`, Run `RUN-`, key `IDK-`, calibration hash `CAL-`.

`CONTRACT_VERSIONS`: `lbsim-request@1.0.0`, `lbsim-findings@1.0.0`, `lbsim-paths@1.0.0`, `lbsim-plan@1.0.0`,
`lbsim-optimise@1.0.0`, `lbsim-validation@1.0.0`, `lbsim-calibration@1.0.0`.

### 3.1 `LifeBalanceSimRequest` (`lbsim-request@1.0.0`), body of `POST /run` and `POST /validate`

| Field | Type | Meaning |
|---|---|---|
| `contract_version` | `"lbsim-request@1.0.0"` | |
| `client_ref` | opaque token (LBS-03) | must equal `sheet.client_ref` and `allocation.client`, else 409 |
| `life_balance_sheet_id` | `LBS-<16hex>` | required |
| `allocation_id` | `PCP-<16hex>` or null | pcp Allocation on the client's base Regime; null: no paths, no plan (reason `no_allocation`) |
| `scenarios` | list of `depression`, `hyperinflation`, `stagflation`, `deferral`, or null | null: all four that aggregation lists for the base Regime |
| `horizon_years` | float 1..60 or null | null applies LBSIM-18 |
| `income_path` | `today`, `education`, `full_pensum`, `network`, or null | null: `education` when an education is planned or in progress, else `today` |
| `n_paths` | int 200..20 000 or null | null: `simulation.n_paths` = 2000 |
| `seed` | int 0..2^31−1 or null | null: `simulation.default_seed`; the resolved seed is recorded and keyed |
| `optimise` | `"background"` or `"no"` | default `background` |
| `calibration_version` | str or null | null: active (1.1.0) |

### 3.2 `LifeBalanceFindings` (`lbsim-findings@1.0.0`), the fast deterministic half

Port of `gameplan.assemble`, `paths.ledger`, `findings.evaluate/schedule`, `plausibility`, `search.frontier`,
`asks.rank`, `workflow.open_items`, run on the submission the adapter (3.6) builds.

- Header: `artefact_id`, `contract_version`, `client_ref`, `life_balance_sheet_id`, `as_of` (the sheet's),
  `calibration_version`, `inflation {currency, annual_rate, log_rate, source}` (from the sheet's
  `real_view.inflation`), `basis: "nominal"`.
- `earning_power[]` per adult (`EarningPower`): `person_id`; `status` `available` or
  `{status: not_available, reason}`; `modelled {full_time_chf_per_year (BFS 40-hour week),
  at_full_productive_week_chf, monthly_standardised_chf, before_responsibility_chf, responsibility {tier,
  label {de, en}, multiplier, stated}, inputs {E, N, age, qualification, earning_power_at_unit}}`;
  `stated {expected_full_pensum_income_chf_per_year, from_age}`; `level_basis` `stated` | `modelled` (a
  missing answer means the model level, marked `modelled`); `current {gross_income_chf_per_year, pensum
  (hours/42), full_pensum_equivalent_chf}`; `education {status none | in_progress | planned | null, end_year,
  end_age, hours_per_week, budget_chf_per_year}`; `health {H, work_capacity, capacity_basis stated | modelled |
  withheld}`; `caveats [{de, en}]`.
- `income_paths[]` (`IncomePath`): `code`, `name {de, en}`, `note {de, en}`, `level_basis`, `pensum_now`,
  `pensum_after`, `education_end_age`, `learning_hours`, `network_hours`; `income [{year, age,
  gross_chf_per_year}]` nominal; `from_65 {ahv_chf_per_year, bvg_chf_per_year}`; `saving_need [{goal_id,
  target_chf, target_date, years, zero_return_saving_chf_per_year, free_cash_chf_per_year, holds}]`;
  `views.real` for `saving_need` at the sheet's inflation, labelled `derived`.
- `zero_return {rate: 0.0, note}`.
- `findings[]` (`Finding`): `code` (the draft's RULES: `goal_not_fundable`, `thin_liquidity`,
  `no_legal_documents`, `hours_above_threshold`, `undirected_surplus`, `debt_service_equals_spending`,
  `wealth_that_cannot_work`, `pension_too_small`, `empty_pillar3a`, `spending_doubling`,
  `positions_outside_model`, `rate_reset_near`, `rate_not_recorded`, `goal_not_computed`, `own_share_only`,
  `stop_age_missing`, `indirect_amortisation`, `unmarried_tax_overstated`); `severity` blocking | high | medium
  | note; `urgency` now | months | year | watch; `action_kind` ask | quantify | decide_between; `figures {name:
  {value, unit chf | chf_per_year | share | years | hours_per_week | count, basis nominal | real | null}}`;
  `text {de: {title, trigger, why, action}, en}` as templates with `{name}` placeholders and no numbers in the
  template; `answers` (the app's question keys that respond); `audience: both`.
- `schedule [{when, label {de, en}, codes}]`.
- `unchecked [{code, reason {de, en}, missing [question keys]}]`: a rule whose input the sheet lacks is listed,
  never passed.
- Also `input_checks`, `frontier` (smallest change per goal at 0 % and at the stated expectation),
  `next_questions [{question_key, spread_chf, headline}]`, `gate`, `assumptions`, `limits`.
- `provenance`: `engine_version`, `contract_versions`, `calibration_version`, `calibration_hash`,
  `idempotency_key`, `upstream {lbs: {artefact_id, request_hash, calibration_version, contract, sha256, url}}`,
  `records` (approval state, `read_without_gate`), `label: model-derived`. And `notice`.

### 3.3 `LifeBalancePaths` (`lbsim-paths@1.0.0`), the Monte Carlo under the stated plan

- Header: `artefact_id`, `client_ref`, `life_balance_sheet_id`, `findings_artefact_id`, `allocation_id`,
  `as_of`, `start_year`, `horizon_years`, `n_paths`, `seed`, `steps_per_year: 12`, `income_path`.
- `policy {kind: "stated_plan", spending_chf_per_year, spending_indexed: true, pensum, saving_source
  cash_flow | stated_contribution}` (the fallback when spending is not stated, and says so).
- `regimes[]` (`RegimePaths`): `key` base | depression | hyperinflation | stagflation | deferral; `label {de,
  en}` (base "Heutige Einschätzung" / "Current assessment"; scenarios aggregation's `label_de`/`label_en`);
  `regime_id`, `kind`, `scenario_years`, `return_set_id`, `inflation_pass_through` (ipt id, scenarios);
  `inflation {source, labels_summary}`; `bands {goal_measure | net_worth: {nominal: {p05, p10, p25, p50, p75,
  p90, p95}, real: {same, derived: true}}}`, each `horizon + 1` year-end values; `goals [{goal_id, kind,
  measure drawable | deposit_eligible | retirement_capital, target {nominal_chf, real_chf, amount_basis,
  date}, chance, chance_basis real | nominal, n_reached, median_shortfall_chf}]`.
- `allocation_view` (charts 1 and 2): `allocation_id`, `mandate_name`, `currency`, `allocation_basis`, `date`,
  `regime_id`, `instruments [{instrument_id, name, role, weight}]`, `by_role {Gain, Income, Stabilisation,
  Protection}`, `state_probability[25]` (`curves.regime`), `curves {nominal: {target[25], achieved[25]}, real:
  {target[25], achieved[25]}}` (the basis that is not the Allocation's derived with ± `log_inflation_s`,
  labelled `derived`, with `inflation_labels[25]`).
- `market_model`: the sampling rule in words, `reversion_years`, `weights: renormalised`, `check
  {achieved_reproduced, max_abs_diff}`, property and pass-through figures.
- `provenance`: `idempotency_key`, `seed`, `numpy_version`, `upstream` (lbs as 3.2; `pcp {artefact_id,
  contract, sha256}`; `aggregation {regime_id: sha256}`; `fmre {return_set_ids, inflation_sha256 per regime,
  ipt}`).

### 3.4 `LifeBalancePlan` (`lbsim-plan@1.0.0`), the optimiser result, stored only for a finished solve

- Header: `artefact_id`, `client_ref`, `life_balance_sheet_id`, `paths_artefact_id`.
- `outcome` solved | goal_not_fundable | undetermined; `goal {goal_id, kind, confidence}` (`1 − ε`, section 10).
- `action_now` (the draft's `u0` in plain units): `work_share`, `learning_hours_per_week`,
  `network_hours_per_week`, `rest_hours_per_week` (τ × 100-hour productive week), `consumption_chf_per_year`,
  `saving_chf_per_year`, `education_spend_chf_per_year`, `network_spend_chf_per_year`,
  `amortisation_chf_per_year`.
- `chance {in_sample, out_of_sample, n_out_of_sample, seed_out}` (out of sample from lbsim's own vectorised
  Monte Carlo under the planned controls); `shortfall_cvar_chf`; for `goal_not_fundable` `reachable
  {amount_chf, at_confidence}`.
- `exchange_rate {winner networking | overtime | undetermined, ratio, dominant}`; `costates {W, E, N, H}`;
  `control_path [{t_years, dt_years, controls}]`; `horizon {solved_years, total_years, beyond_cap_rule}`.
- `solver {return_status, iterations, wall_clock_s, seed, seed_attempt, M_opt, grid, casadi_version,
  ipopt_version}`; `basis: nominal`; `provenance`; `notice`.
- No figure from a non-converged or timed-out solve: such a run is `failed` with a `failure_kind`, and no LSO
  artefact is written.

### 3.5 Runs and the optimiser status

A plan is a run of kind `plan`, so the cockpit's `refresh` machinery works unchanged.

- `RunAccepted {run_id, kind outlook | plan, status, idempotency_key, cached, findings_artefact_id,
  paths_artefact_id, plan_run_id, not_made [{artefact, reason}]}`. `POST /run` computes findings and paths
  synchronously (budget 30 s) and queues the plan run.
- `RunStatus {run_id, kind, status queued | running | succeeded | failed, failure_kind timed_out | superseded |
  cancelled | solver | upstream | null, idempotency_key, requested_by {kind client | curator | system, ref},
  queued_at, started_at, finished_at, wall_clock_ms, budget_s, progress {phase restore | best_life, start, of,
  seed_attempt, elapsed_s}, request, artefact_ids, error}`.
- `LifeBalanceOutlook` (not stored, `GET /outlook`): `{client_ref, life_balance_sheet_id, findings, paths,
  plan: {state, run, artefact}}`; `state` ready | calculating | waiting_for_allocation | not_possible |
  not_requested, with `reason {de, en}`, and `elapsed_s`, `budget_s` while calculating. Never mixes sheets.

### 3.6 The adapter (`lbsim.adapter`): sheet and request to the draft's submission

| Draft input | From |
|---|---|
| `state.age`, `E`, `N`, `H` | the principal's age; `sheet.human_capital[p].E/N/H.value` |
| `W_L`, `W_P`, `W_3a`, `W_R` | `totals.by_vessel.free`, `.pillar_2`, `.pillar_3a`, `.real_asset` |
| `W_res` | `W_R` (residence share not stated; conservative, an assumption) |
| `D`, rate, amortisation | `totals.liabilities`, `risk.mortgage_rate_pct`, `risk.amortisation_per_year` |
| `income_gross`, `hours_per_week` | `person.stated_gross_income` or owned income positions; `human_capital.hours_per_week` |
| `spend_now` | `risk.spend_now_per_year` |
| canton, civil status, children | `facts.canton`, `facts.civil_status`, the dependants' ages |
| partner | the second adult: `has_partner`, `partner_income`, `partner_age_offset` |
| `income_expected_full`, education, health capacity, kader, sector | `persons[].earning_power` (new, section 4) |
| `stop_work_age`, `legal_docs`, `mortgage_fixed_until`, `amortisation_mode`, `own_use_pct`, `pillar3a_contribution` | `facts` (new, section 4); absent means the rule is unchecked, or the M73 default is used and listed in `assumptions` |
| goals | lbs goals: `property` -> `home` (the deposit, `property.mandate_target`); `retirement` -> `retirement`; `other` with amount and date -> `capital` (LBSIM-19). Nominal amounts from `real_view.goals[].nominal` |

### 3.7 Endpoints

Standard (Guide 2.1): `GET /health`, `/meta` (with the allowlist report), `/contracts`, `POST /run`,
`GET /runs[?client_ref=&kind=&status=]`, `/runs/{run_id}`, `/artefacts/{artefact_id}` (typed by prefix),
`GET`/`PUT /calibration`. Engine specific:

| Method | Path | |
|---|---|---|
| POST | `/validate` | what can be computed, blocked, assumed (`workflow.open_items`), without storing |
| GET | `/outlook?client_ref=&life_balance_sheet_id=` | latest findings, paths and plan state for a sheet (default the client's newest) |
| GET | `/findings/{id}`, `/paths/{id}`, `/plans/{id}` | typed aliases |
| GET | `/paths/{id}/fan?regime=base&basis=nominal&series=goal_measure` | one chart's series |
| POST | `/optimise` `{paths_artefact_id, seed?, requested_by}` (`lbsim-optimise@1.0.0`) | on demand; idempotent: a finished plan for the same key returns `cached: true`, a queued or running one as is |
| POST | `/runs/{run_id}/cancel` | plan runs only |
| GET | `/calibration/versions` | active one marked |

Errors: 404 unknown sheet or allocation; 409 client mismatch, fmre moved on, sheet and Allocation not matching;
422 invalid request, currency not CHF, hard-currency fallback, a scenario as base; 503 upstream down. Every
message a plain sentence.

### 3.8 What lbsim reads (pinned exactly by the mirrors)

| Engine | Call | Contract | Checks |
|---|---|---|---|
| lbs 8013 | `GET /artefacts/{id}` | `lbs-balance-sheet@1.0.0` | client_ref |
| lbs 8013 | `GET /artefacts/{id}/request` (new) | `lbs-request@1.0.0` | `request_hash == sheet.provenance.request_hash` |
| lbs 8013 | `GET /calibration?version=` | `lbs-calibration@1.3.0` | `human-capital`, `ahv-pension`, `bvg-projection` records with approval state |
| pcp 8007 | `GET /allocation/{id}` | `pcp-allocation@1.0.0` | `client`, `currency == CHF`, basis, not on a scenario |
| aggregation 8004 | `GET /regime/{id}`, `GET /scenarios` | `aggregation-regime@1.0.0`, `aggregation-scenario@1.0.0` | `regime_id` echoed; the scenarios of the base |
| fmre 8006 | `GET /v1/return-set?regime_id&currency=CHF&include_instruments=true&include_blocks=false` (nominal) | `rs@1.0.0` | base set id equals the Allocation's (LBSIM-15); `provenance.inflation_pass_through` is `ipt@1.1.0` (`config upstream.accept_ipt`) |
| fmre 8006 | `GET /v1/inflation?currency=CHF[&regime_id=]` | unversioned; field mirror, sha256 recorded | 25 states; `not_computable` gives 422 |

Live ids today: Default Regime `RGM-e2658e8e9bbbc81e`; depression `RGM-1af6968e287768c9`; hyperinflation
`RGM-59eebfaf7744d8ec`; stagflation `RGM-6bb531998bfefc4d`; deferral `RGM-c0ed086f1916984e`; fmre CHF default
set `RS-c472e411e39645f5`; ipt `IPT-585c7da4656ead2b`.

### 3.9 Seeds and idempotency keys

`IDK = content_id("IDK", ...)` over the resolved inputs:
- Findings: `{kind, life_balance_sheet_id, calibration_hash, engine_version, contract_versions}` (no seed).
- Paths: the findings key plus `{allocation_id, regimes [(key, regime_id)], return_set_ids, inflation_sha256
  per regime, ipt_id, horizon_years, n_paths, seed, income_path, numpy "major.minor"}`.
- Plan: the paths inputs less `n_paths`, plus `{optimiser block hash, seed, casadi_version}`. `requested_by`
  is not in the key.

Random streams: `SeedSequence(seed).spawn(3)` gives uniform state draws, property noise and a spare, in that
order. The same uniforms go through every Regime's CDF (common random numbers). Optimiser: in-sample seed
`seed`; redraws `seed + 1000·k` (M79: an unfundable goal is not redrawn); out-of-sample `seed + 500 000`.
Every seed used is recorded.

### 3.10 Storage (PostgreSQL `simtech`, schema and role `lbsim`)

- `calibration`: append-only.
- `artefact`: `artefact_id`, `kind` (findings | paths | plan), `client_ref`, `life_balance_sheet_id`,
  `idempotency_key` UNIQUE, `contract_version`, `created_at`, `payload_json`; append-only by trigger.
- `run`: state machine with `kind`, `status`, `failure_kind`, `request_json` (ids and options only, no copy
  of client data), `requested_by_*`, `priority` (curator ahead of system), `budget_s`, `heartbeat_at`,
  `progress_json`, `artefact_ids`, `error`.
- `run_event`: append-only.
- Every table commented, no REAL column. Retention: same open point as lbs.
- Provisioning: `Instruments/store/provision.py` already has `Engine("lbsim", 8014, ("lbsim",),
  built=False)`: set `built=True` with a note, add to `OWNED_HERE`, run `python -m store.provision`.

## 4. lbs changes (Engine 13, v1.4.0; contract strings unchanged)

1. `Person.earning_power` (optional `EarningPowerAnswers`, LBS-39), validated, not computed from:
   `expected_full_pensum_income` (float ≥ 0, CHF a year in today's francs, at 100 % once any education is
   done); `responsibility` (a tier label of `human-capital.responsibility.tiers`); `sector` (str);
   `education_status` none | in_progress | planned; `education_end_year` (int 2000..2100); `education_hours`
   (band string or hours); `education_budget_per_year` (float ≥ 0); `health_work_capacity` (float 0..1; K3
   data, `health_withheld` applies).
2. `StatedFacts` gains optional `stop_work_age` (40..75), `legal_documents` (tuple of str),
   `mortgage_fixed_until` (date), `amortisation_mode` direct | indirect, `own_use_share` (0..1),
   `pillar3a_contribution_per_year` (≥ 0).
3. `request_hash` drops each new field while None, so a request without them hashes as before. The
   idempotency key moves only through `engine_version` 1.4.0.
4. `GET /artefacts/{artefact_id}/request` returns `{artefact_id, request_hash, contract_version:
   "lbs-request@1.0.0", request}` from `run.request_json` (LBS-40).
5. The sheet is unchanged. `earning_power` stays `not_available`; LBS-10 is amended to say where lbsim takes over.

## 5. The background optimiser

**Who calls lbsim:**
- The app, as for lbs: after `run_balance_sheet` succeeds, if the sheet id differs from the sheet of the
  client's latest lbsim run (which also covers a new allocation), the app calls lbsim `POST /run` with that
  sheet and the base-Regime Allocation of the current parameter set (the `allocation_run` rule, EIG-63). No
  second debounce.
- The cockpit: after a succeeded pcp run on a base Regime it calls the app's new
  `POST /api/clients/{c}/outlook` (the C-20 pattern: lbsim requests are built only in the app). The cockpit's
  "Planrechnung neu starten" calls the same route with `{"curator_id", "optimise": "now"}`: a priority plan
  run recorded as that curator's.
- Backfill: `python -m eigentlich lbsim-backfill`, refusing to start when lbsim does not answer.

**Tracking:** each call is an `engine_run` in the app store with `engine = 'lbsim'`; the fast run finishes
`succeeded` with `artefact_id` = paths id (or findings id without paths). The plan is a second `engine_run`
with `run_id = plan_run_id`, `running` until refreshed from `GET /runs/{id}`; `/api/curator/runs/{id}/refresh`
works as is. Pages ask `GET /outlook` and show the fast parts at once and "Die Planrechnung läuft noch (seit N
Minuten, höchstens 2 Stunden)".

**Workers:** `python -m lbsim serve` starts the API and `optimiser.workers` processes (default 3; IPOPT/MUMPS
one core each); `python -m lbsim worker` starts one alone. `SELECT … FOR UPDATE SKIP LOCKED`, curator first,
heartbeat every 30 s; stale runs requeued at start-up (at most 2 attempts). A newer outlook run for the same
client supersedes a queued plan and cancels a running one at the next checkpoint (between IPOPT solves).

**Time budget:** findings ≤ 5 s; paths ≤ 20 s for 2000 paths × 40 years × 5 Regimes, monthly steps,
vectorised over paths (a parity test ties it to the draft's per-path simulate); plan hard wall clock
`optimiser.budget_minutes` = 120, enforced per IPOPT call (`ipopt.max_wall_time`) and between calls; past it
`failed`/`timed_out`, no figures.

**40-year horizon:** variable grid, 0.5-year steps for years 0-10, 1.0-year for 10-20, cap
`optimiser.max_solve_horizon_years` = 20 (30 steps, about 50 minutes). Goals beyond the cap become a terminal
requirement at the cap: the wealth from which the remaining years reach the goal at zero return at the
planned saving (the fast half's `saving_required`). The plan states `horizon {solved_years: 20, total_years:
40, beyond_cap_rule: "zero_return_terminal"}`. Findings and paths always cover the full horizon. Solver
settings verbatim from the draft's `cases.run_case` into calibration 1.0.0 (M_opt, n_starts, restore_starts,
max_iter, seed_retries, cvar_tol).

## 6. report (Engine 15, v1.4.0; `report-request@1.0.0` unchanged)

- `EngineName` gains `lbsim`; "at most one source per engine and artefact kind" (kind from the prefix LSF,
  LSP, LSO). Refused: lbsim artefacts on another sheet than the lbs source, paths on another Allocation than
  the pcp source, a plan on other paths. A request without lbsim sources keeps its id. While the plan runs:
  fact `lbsim.plan.state` "wird berechnet" / "being calculated"; a later update includes the plan.
- New sections (no prose slot in this build): `earning_power` "Die Erwerbskraft" / "Earning power" (after
  `human_capital`); `income_paths` "Einkommenspfade und Sparbedarf" / "Income paths and the saving they need";
  `findings` "Befunde und nächste Schritte" / "Findings and next steps" (with the schedule); `outlook` "Die
  Aussichten" / "The outlook" (chart 3, chances per Regime as numbers); `plan` "Was die Planrechnung ergibt" /
  "What the plan calculation shows".
- Facts: `lbsim.earning_power.<person>.{modelled,stated,level_basis}`; `lbsim.path.<code>.saving_need.<goal>`;
  `lbsim.finding.<code>.<figure>` (text from lbsim's templates in the report's language, each figure a
  `data-fact` span); `lbsim.chance.<regime>.<goal>`; `lbsim.fan.<regime>.<p10|p50|p90>.end`; the plan's
  `action_now` fields. A real report uses lbsim's real views (REP-27/28 hold).
- Charts (`report/charts.py`): pure functions returning inline SVG; no `<script>`, no external reference, no
  web font; `role="img"` with `<title>`/`<desc>` in words, a `viewBox`, the house colours. The page rule stays
  (no free number of two or more digits): no tick labels; every printed value is a `<tspan data-fact>`,
  labelled directly.

| Chart | Section | Contents | Source |
|---|---|---|---|
| (1) Weights | `roles` (by role), `positions` (by instrument) | horizontal bars, weights as facts | pcp Allocation |
| (2) Target vs reached per state | `fit` | 25 states, "Krise" to "Boom" as words at the ends; two lines; the 0 % line | pcp, on the Allocation's basis (REP-28) |
| (3) The fan | `outlook` | p05-p95 and p25-p75 bands, median, goal line (dashed in the other basis), chance as a fact | lbsim paths |

Expected return figures stay numbers.

## 7. The consumer app (`eigentliCH_Engines/eigentlich`, 8017)

- Intake content version 4 (onboarding stays 3), saved by the owner's curator record through a new
  `revise-content` step (the alignment.py pattern). Earlier answers stay and are read. For the client:

| Key | Question (de) | Type |
|---|---|---|
| `income_expected_full` | "Welchen Bruttolohn erwarten Sie bei vollem Pensum, sobald eine laufende oder geplante Ausbildung abgeschlossen ist?" (help: "Ohne Angabe rechnet das Modell mit seinem eigenen Niveau und sagt das.") | CHF per year |
| `education_status` | "Läuft eine Ausbildung, oder ist eine geplant?" | keine / läuft / geplant |
| `education_end_year` | the year it ends | year, shown when läuft or geplant |
| `health_work_capacity` | "Schränkt Ihre Gesundheit ein, wie viel Sie arbeiten können?" | nein 1.0 / leicht 0.8 / deutlich 0.5 / stark 0.2; data_class 3 |

  Existing `kader`, `sector`, `education_hours`, `education_budget` are reused and now reach lbs. The partner
  section (21) gains `partner_income_expected_full`, `partner_education_status`,
  `partner_education_end_year`, `partner_education_hours`, `partner_education_budget`, `partner_kader`,
  `partner_sector`, `partner_health_work_capacity`.
- Mapping: `inputs.py` fills `persons[].earning_power` and the new `facts` only when stated, and names what it
  dropped; the mirrored `LbsPerson` gains the block.
- `clients.py` gains `LbsimClient`; config `lbsim_url: http://127.0.0.1:8014`, `timeouts.lbsim_s: 60`,
  `lbsim_auto.enabled: true`. Routes `POST /api/clients/{c}/outlook` (optional `{curator_id, optimise}`) and
  `GET /api/clients/{c}/outlook?language=&basis=` (also refreshes the plan's `engine_run`).
- New surface "Aussichten" / "Outlook" (`#/outlook`, `surfaces/outlook.js`): earning power per adult ("Ihre
  Angabe" or "Modellwert"); the income-path table with the zero-return saving need; findings with actions,
  schedule and a link to the answering question; charts 1-3 with the nominal/real switch; a Regime selector
  (house labels) with chances as numbers; the plan block or "wird berechnet".
- Home gains a card: the designated goal's chance in words ("In 68 von 100 simulierten Verläufen …"), the top
  three actions, the plan state.
- Charts (`client/app/charts.js`): SVG built in the browser with the namespace-aware `h()`, no library, no
  external script. Chart 2 in the other basis from `allocation_view.curves`; chart 3 from `bands.real` or
  `bands.nominal`; the weights show the basis anyway.
- One language per page; no ids or keys for people; instruments by name, roles by house names, Regimes by labels.

## 8. The cockpit (`Engines/cockpit`, 8000)

- Roster: lbsim `status: built`, `produces: LifeBalanceFindings, LifeBalancePaths, LifeBalancePlan`,
  `consumes: [lbs, pcp, aggregation, fmre]`, `bench`, `start {cwd: ../eigentliCH_Engines/engines/lbsim, args:
  ["-X","utf8","-m","lbsim","serve"]}`, `python: ../eigentliCH_Engines/.venv/Scripts/python.exe`,
  `autostart: true`.
- The curator client page gains an "Aussichten" panel (same content as the app), charts with Plotly (the
  cockpit's existing convention, CDN, through the page's `plot()` helper), the plan's solver details (curator
  only) and "Planrechnung neu starten" (through the app).
- Parameters page: after a succeeded base-Regime pcp run, call the app's outlook route.
- The app's `desktop.cmd` adds `call :ensure 8014 "%~dp0..\engines\lbsim" lbsim`.

## 9. Build split (five agents, non-overlapping folders)

Order: A -> B1 (contracts, model port, frozen sample artefacts) -> {B2, C, D} in parallel -> E.

**A. lbs and provisioning** (`eigentliCH_Engines/engines/lbs/**`; `Instruments/store/provision.py`, the lbsim
entry only). Section 4, LBS-39, LBS-40, lbs 1.4.0, lbsim provisioned. Acceptance: a request without the new
fields keeps its `request_hash` (pinned on all 28 golden cases); validators refuse out-of-range values;
`/artefacts/{id}/request` hash equals `provenance.request_hash`, 404 for unknown; mutation check (dropping a
None field from the hash reverted once turns red); all 401 tests pass; the lbsim role owns its schema, cannot
write outside it, no REAL column.

**B. lbsim core** (`engines/lbsim/**` except `src/lbsim/optim/**`, `tests/optim/**`, `golden/optim/**`).
- B1: `contracts.py` (section 3); the numpy model port (`lbsim/model`: params, dynamics, state, controls, bvg,
  canton, fiscal); the fast half (`lbsim/fast`); the adapter; calibrations 1.0.0 and 1.1.0 with seed records;
  golden layer A built by `dev/build_golden.py` under the draft's own interpreter (draft read only, `bvg.TABLE`
  and `canton.TABLE` pointed at the seed copies). Publishes frozen sample artefacts to `golden/samples/`.
- B2: the vectorised Monte Carlo, upstream clients, store and schema, service and API, the worker harness
  (queue, heartbeat, supersede, cancel, budget) calling `lbsim.optim.solve(problem) -> PlanOutcome`, README,
  DECISIONS (LBSIM-01..19), HANDOVER.
- Acceptance: layer A reproduces `gameplan.assemble` and `paths.ledger` for the draft's cases and use-case-shaped
  submissions to 1e-9 (verdicts and finding codes exact); earning power reproduces the prototype's
  `hc.earning_power` on lbs's db cases; layer B `changes.json` attributes every changed leaf to LBSIM-08, 11
  or 07; the vectorised Monte Carlo equals the draft's `simulate` path by path at σ = 0 and at a fixed state
  path to 1e-9; the achieved curve reproduced (LBSIM-15); same seed same bytes, different seed different key;
  common random numbers (base draws identical across differing scenario lists); hypothesis properties (chances
  in [0, 1], bands ordered, real bands equal per-path deflated nominal bands, zero inflation makes them equal);
  the import boundary; the forbidden-verb scan; each unchecked rule names its missing question; the 3.7
  refusals; the section 5 budgets on a 40-year, 2000-path case; a killed worker requeued; a newer sheet
  supersedes a queued plan.

**C. lbsim optimiser** (`src/lbsim/optim/**`, `tests/optim/**`, `golden/optim/**`). Ports `symbolic.py`,
`problem.py`, `goals/spec.py`, `mpc.py` with the market adapter (θ fixed, per-state returns as parameters), the
variable grid, the terminal requirement, `max_wall_time`. Acceptance: symbolic-numpy parity against B's
`lbsim.model` on every step length; under 1.0.0 with the draft's market term restored, the draft's slow
`test_optim` cases reproduce `u0`, chance and outcome within the draft's tolerances; a 20-year case within 120
minutes; a forced timeout gives `timed_out` and no artefact; an unfundable goal not redrawn (M79); the
out-of-sample chance from B's Monte Carlo; `pytest -m slow --dist loadfile -n 4` documented, slow tests
deselected by default.

**D. report and cockpit** (`engines/report/**`, `Engines/cockpit/**`). Sections 6 and 8 without the app route
calls, on B's sample artefacts. Acceptance: the digit rule passes with all three charts; every `data-fact` in
an SVG is a fact; no `<script>` and no `http` inside `<svg>`; mixed sheets or allocations refused with a plain
sentence; a request without lbsim sources keeps its id and bytes (all 335 tests pass); golden pages frozen in
de and en, nominal and real; cockpit tests (75 plus new) cover the roster entry, the Aussichten panel against a
stand-in lbsim, and the button recording an `engine_run` through the app stand-in.

**E. app, then the use-case refresh** (`eigentliCH_Engines/eigentlich/**`). Section 7, `lbsim-backfill`,
`desktop.cmd`. `dev/build_use_cases.py` gains `earning` (plausible answers for the 20, about three left
unanswered to show "Modellwert") and `outlook`. `check` extended: every client has findings and paths on its
newest sheet; a plan run is queued, running or succeeded (`check --plans` waits); report pages carry the three
charts and no ids. `docs/USE_CASES.md` gains the lbsim columns. Run order: `earning` -> `mandates --refresh`
(lbs 1.4.0 makes new sheets, so lbsim runs by itself) -> `outlook` -> `reports --refresh` -> `check`. With 3
workers and about 50 minutes a plan, the 20 plans take about 6 hours; the fast parts take minutes.
Acceptance: mapping tests (stated answer sent, unstated absent); the auto-trigger fires only on a new sheet id;
the outlook page in one language with no ids; the switch re-renders all charts; the plan state reads "wird
berechnet" then the result; the live test against running engines.

## 10. Owner's decisions

Of 29.09.2026 (memory `lbsim-decisions`): earning power and simulation at once; the optimiser and the game
plan both in; the optimiser runs automatically in the background and on demand from the cockpit; findings for
client and curator; new questions per adult, a missing answer is the model level, marked; market source
aggregation plus fmre; results in the report, the app and the cockpit; charts: weights by instrument and role,
target vs reached curve, the wealth-path fan.

Settled by the owner on 29.09.2026 (the planner's three open questions):
1. **Withdrawal rate 3 % a year**, shown as an assumption: capital needed = yearly retirement need / 0.03. It is
   an lbsim calibration entry (`retirement.withdrawal_rate`), and every figure resting on it names it. The
   retirement chance is therefore available.
2. **Plan confidence 90 %** for everyone (`optimiser.confidence` = 0.90, ε = 0.10).
3. **The plan's "this period" figures are shown to the client and the curator at once**, framed as "what the
   calculation assumes" ("Was die Rechnung annimmt"), never as a recommendation. No release step. The report's
   `plan` section and the app's plan block carry that framing; the cockpit shows the same plus the solver details.
