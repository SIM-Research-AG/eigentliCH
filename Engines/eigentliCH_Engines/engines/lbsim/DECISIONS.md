# lbsim: decisions

LBSIM-01 to LBSIM-19 are the owner's and the planner's decisions of 29.09.2026, as `Engines/review/LBSIM_INTERFACES.md`
section 2 states them. Below each, what the build does with it (B1) and what remains to B2 or C. The port notes
after them record what the port had to decide against the draft.

## The nineteen

- **LBSIM-01 anatomy.** lbs is the template: settings, store, service, API; `eigentliCH_Engines/.venv`, port 8014,
  schema and role `lbsim`. B1 laid out `contracts`, `calibration`, `model`, `fast`, `adapter`, `config.yaml`,
  `pyproject.toml`. The schema and role are provisioned (agent A); settings, store, service and API are B2's.
- **LBSIM-02 casadi.** `casadi==3.7.2` is a declared dependency, imported only inside `lbsim.optim`.
- **LBSIM-03 import boundary.** `lbsim.contracts`, `lbsim.calibration`, `lbsim.adapter`, `lbsim.fast` and
  `lbsim.model` import without casadi; a test runs them in a fresh interpreter and checks `sys.modules`. The draft's
  chain `gameplan -> onboarding -> cases -> optim -> casadi` is cut by restating the one alias `gameplan` read from
  `onboarding` (`{"mortgage_rate": "i"}`), held equal to the draft's by a test.
- **LBSIM-04 lbs keeps no upstream engine.** Every lbsim artefact names its `life_balance_sheet_id`; the findings
  record the sheet's id, request hash, calibration and sha256 in `provenance.upstream.lbs`.
- **LBSIM-05 the household is stated once, in lbs.** The adapter reads the sheet and the request lbs returns from
  `GET /artefacts/{id}/request`, and nothing else about the household.
- **LBSIM-06 three artefacts.** `LSF-`, `LSP-`, `LSO-` are in the contracts. Findings are built (B1). Paths are
  B2's, plan C's; a client without an Allocation still gets findings.
- **LBSIM-07 the market.** In the calibration as `behaviour.market` (`draft` in 1.0.0, `allocation` in 1.1.0) with
  `market` (reversion 5 years, persistence 0, five scenario years, pass-through 1.0) and `property` (ln 1.03,
  beta 0.8, anchor ln 1.01, sigma 0.08, rho 0.30). The Monte Carlo that applies it is B2's; the paths sample
  follows it on real upstream figures. It moves nothing in the findings (layer B confirms it).
- **LBSIM-08 two inflation assumptions.** The findings use the sheet's `real_view.inflation` under 1.1.0: wages and
  spending rise with it, goals are read in the francs of their date, the pillar-2 accrual is nominal (in today's
  francs, the draft's loop at the real credited rate), and the tax tariff is indexed. `inflation` in the artefact
  states the rate and its source.
- **LBSIM-09 chance in the goal's own basis.** In the paths contract (`chance_basis`) and the sample; B2 computes it.
- **LBSIM-10 fan quantiles in both bases.** `RealQuantiles` carries `derived: true` and the deflator; B2 computes
  them from the same draws.
- **LBSIM-11 one earning-power computation.** `lbsim.fast.earning` is the prototype's `human_capital.earning_power`
  (the draft's `dynamics.earning_power` at the record's 0.7207, times the responsibility tier), reproduced to 1e-9
  on lbs's golden households. Under 1.1.0 the income paths use that `earning_power_at_unit`, and a household with
  no income at all is levelled at the modelled full-time income (tier multiplier times the 40/100 BFS share).
- **LBSIM-12 AHV and BVG.** The two tables are seed records; a test pins every figure they share with lbs's
  `ahv-pension` and `bvg-projection` records (and the draft `Params` figures that rest on them) to equality.
- **LBSIM-13 calibrations mirror lbs.** 1.0.0 reproduces the draft (layer A); 1.1.0 is active (layer B with
  `changes.json`). Both hashes are pinned.
- **LBSIM-14 CHF only.** `behaviour.currencies = ("CHF",)`; the adapter refuses a sheet whose real view is not in
  CHF. The Allocation refusals (currency, hard-currency fallback, scenario base) are B2's, in the clients.
- **LBSIM-15 strict upstream consistency.** Checked on the live bench Allocation: the raw weights reproduce
  `curves.achieved` to 5e-16. The check itself is B2's.
- **LBSIM-16 the optimiser does not choose the portfolio.** In the plan contract (`action_now` without theta); C's.
- **LBSIM-17 findings never say "buy".** Every finding's words are the versioned record `findings-text` (de and
  en, `{figure}` placeholders, no number in a template, `action_kind` ask, quantify or decide_between). A test scans
  every template for the calibrated forbidden verbs, the product words and the 52 instrument names of the pcp
  universe; a mutation check proves the scan catches a "Kaufen".
- **LBSIM-18 horizon.** In the request contract (1 to 60 years); resolved by B2. The sample uses the latest goal.
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
