# Engine 13: Life Balance Sheet (`lbs`)

The client's deterministic life balance sheet. From one household's stated facts it publishes the
**LifeBalanceSheet**: financial and human capital by role and capital type, net worth, human capital per person
(E, N, H), the two pillars, the property, liquidity and retirement findings, the risk profile, every missing input
named as a gap, and a **mandate proposal** in the shape of the Optimizer's `pcp-mandate@1.0.0` for the curator to
finalise. Every figure is a port of the eigentliCH prototype's services, whose own outputs are the golden reference.

> Model-derived research output. Nothing here is a pension entitlement, a lending decision or a recommendation;
> a section resting on an unapproved record says "not available" rather than showing a number. **Not investment
> advice.**

| | |
|---|---|
| Family | Client (eigentliCH engines) |
| Module | `lbs` |
| Default port | 8013 (configurable in `config.yaml`) |
| Status | v1.3.0 (29.09.2026), calibration 1.5.0 active (the nominal and real view at the owner's CHF inflation of 1.0 %); the prototype reproduced exactly under 1.0.0 and 1.1.0 (659 figures, deviation 0); the corrected behaviour frozen as golden layer B (steps 1.2.0 to 1.5.0); 401 tests |
| Consumes | Client data only (`lbs-request@1.0.0`); no upstream engine |
| Produces | `LifeBalanceSheet` (`lbs-balance-sheet@1.0.0`) |
| Downstream | `lbsim` (8014), `report` (8015); the mandate proposal goes to the curator, then `pcp` (8007) |

## Run it

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\eigentliCH_Engines\engines\lbs
start.cmd                                    :: engine on 8013, test bench at http://127.0.0.1:8013/
```

First time: `..\..\.venv\Scripts\python -m pip install --no-deps -e .`, the role and schema from
`python -m store.provision` (in `Projects\Engines\Instruments`), the password in `config.local.yaml`
(`database: password: ...`, git-ignored), then `..\..\.venv\Scripts\python -m lbs init-db`.

```bash
..\..\.venv\Scripts\python -m pytest     # 401 tests, against the real PostgreSQL server
```

## What it computes, and from which prototype service

| Section | Port of | Record (approval in the active calibration 1.5.0) |
|---|---|---|
| Household, validity horizon | `household.py`, `currency.py` | currency-horizons (approved) |
| Grid: 4 roles by human/financial | `grid.py` | roles (provisional; display only) |
| Totals, net worth, drawable, household income | `engine_inputs.stated_stocks`, `goals._household_income` | none |
| E, N, H and the time budget per adult | `human_capital.py`, `identities.net_scale` | human-capital (approved), intake-scales (provisional, read ungated as in the prototype) |
| AHV per adult, couple cap | `ahv.py` | ahv-pension (approved by Nicolas, 29.09.2026; unapproved in 1.0.0) |
| BVG to the reference age per adult | `pension_projection.py`, `computations._retirement_provision` | bvg-projection (approved) |
| Property goals: equity, affordability, levers | `property.py`, `goals.property_finding` | property-funding (approved) |
| Blocking liquidity finding, one prepared lever | `liquidity.py` | liquidity-levers (approved) |
| Retirement goals: the two pillars against the need | `goals.retirement_finding` | ahv-pension, bvg-projection |
| Goal observations | `goals.observations` | none |
| Risk profile: willingness, capacity, anchors | `risk_profile.py`, `profile_inputs.py` | risk-profile (approved by Nicolas, 29.09.2026; unapproved in 1.0.0) |
| Mandate proposal | `engines/lbs/derive.py`, S-curve `required_return`, `property.mandate_target` | property-funding, risk-profile, `MandatePolicy` |
| Earning power | `personal_alm` | not available: the stochastic model belongs to `lbsim` (LBS-10) |

**The prototype's quirks, corrected (LBS-24, LBS-28).** Calibration 1.2.0 corrects the four behaviours LBS-17
kept for golden fidelity, and 1.3.0 three more; 1.0.0 and 1.1.0 still reproduce the prototype and 1.2.0 its own
behaviour, each selectable by `calibration_version`:

| Behaviour | Prototype (1.0.0, 1.1.0) | Corrected (from 1.2.0) |
|---|---|---|
| Required-return search | doubles 1, 2, 4, 8 and stops: no return above 800% | the last step is clamped to the stated ceiling and tested: up to 1000% |
| Capacity horizon without a dated goal | `plan_until_age` (an age) read as years | `plan_until_age` less the principal's age; no age is a gap |
| A zero income | unknown: no BVG projection, no AHV illustration, no household income | a stated zero: BVG on a salary of 0, the AHV minimum, household income 0 |
| A funding stock without a vessel | hard equity for a property goal, free wealth for the capacity | a named gap: the equity verdict is judged with and without it; not free wealth |

| Behaviour | Up to 1.2.0 | Corrected (1.3.0) |
|---|---|---|
| A human-capital stock in chf | free wealth for the capacity (and in 1.2.0 a stock without a vessel for a property goal) | human capital only: not free wealth, not in the capacity's wealth, not equity (a gap names it) |
| `risk.mortgage` 0 | no answer: the debt-service share unknown | a paid-off mortgage: a debt service of 0; only an unstated mortgage is unknown |
| One yearly saving, several goals | all of it to the designated goal | split by `goals[].contribution_share`; the designated goal's missing share is a gap and the most it can receive is used, so the required return is a lower bound |

**The nominal and real view (LBS-31 to LBS-35, calibration 1.4.0; its assumptions settled in 1.5.0, LBS-36 to
LBS-38).** The owner's decisions of 29.09.2026 (`review/REAL_VIEW_INTERFACES.md`): a goal amount is in today's
francs unless the request says future francs, and is inflated to its date at the currency's calibrated long-run
inflation, recorded with its source (lbs reads no engine at run time): CHF 1.0 % a year from 1.5.0, the owner's
forward-looking assumption, the midpoint of the SNB's 0 to 2 % price-stability range (0.50 % in 1.4.0, the
measured 2006 to 2026 mean); EUR 2.11 % and USD 2.54 %, the mean log inflation of the datafeed's CPI series 2006
to 2026. A contribution is fixed in francs unless stated as indexed, in which case it rises with
prices month by month. The mandate proposal stays nominal (`basis: nominal`: target in francs of the date,
required return and curve nominal) and carries `views.nominal` and `views.real` side by side; the sheet's
`real_view` has every goal's amount in both bases. The property tests stay ratio tests in today's terms; the
retirement comparison is made in today's francs, the nominal BVG pension deflated from its first year. And
`mandate_proposal.plausibility` judges the real required return against a calibrated ceiling by risk level (2 %,
3.5 % and 5 % real at levels 0, 0.5 and 1, approved by the owner in 1.5.0): `realistic`, `not_realistic`
with the levers computed (a longer horizon, a higher saving, a smaller goal) or `could_not_be_determined`;
`feasible` keeps its narrow meaning (a return below the 1000 % search ceiling exists). The design note's worked
example (CHF 400,000 in today's francs in 20 years, 150,000 now, 12,000 a year) is a test: 0.18 % read as future
francs, 2.96 % nominal and 0.94 % real at 2 % inflation, the target 594,378.96; at the owner's CHF 1 % (1.5.0)
1.60 % nominal and 0.59 % real, the target 488,076.02.

**The rules the prototype kept, kept here.** Nothing computes from an unapproved record (`_about.provisional`
false and `_about.published_by` set), which yields `status: not_available` with the reason. A missing input is a
gap, never zero: no liability stated leaves net worth open, an unstated household is not a single person, an
absent capital is dropped rather than scored. Assets and liabilities are never netted into one input, and a flow is
never a stock. Three verdicts: meets, does not meet, could not be determined.

## Contracts and endpoints

`LifeBalanceSheetRequest` (`lbs-request@1.0.0`): `client_ref` (opaque; names and e-mails are refused), `as_of`,
`calibration_version`, `household` (`composition_as_of`, `principal`, `persons`: `person_id`, `kind`
adult/dependant, `age`, `stated_gross_income`, `human_capital` answers, `ahv` facts), `positions` (`role`
gain/income/stabilisation/protection, `growth` accepted as gain; `capital_type` human/financial; `magnitude` with
`unit` chf/chf_per_year/share_of_total; `stock_kind` asset/liability exactly for chf; `liquidity`; `vessel`
free/pillar_2/pillar_3a/real_asset; `owner`; `active`; `funds_goals`), `goals` (`kind` property/retirement/other,
`target_amount`, `target_date`, `occupancy`, `owners`, `contribution_share`, `amount_basis` today/future), `facts` (`canton`, `civil_status`, `has_no_liabilities`),
`risk` (the capacity and willingness answers) and `mandate` (`goal_id`, `annual_contribution`, `name`,
`contribution_indexed`).

**The basis of an amount and of the contribution** (LBS-31): `goals[].amount_basis` (`today` or `future`) and
`mandate.contribution_indexed` (true or false), optional and additive (the contract stays `lbs-request@1.0.0`, a
request without them hashes as before). From calibration 1.4.0 a missing basis is today's francs (decision 7) and a
missing indexation is fixed (decision 9); before 1.4.0 neither is read, and a note says so when they are stated.
The consumer app's questions "in heutigen Franken?" (default ja) and "steigt der Betrag mit der Teuerung?"
(default nein) map to them.

**The yearly contribution** (LBS-25): the consumer app's onboarding question "How much can you put aside each year?"
(CHF per year) goes into `mandate.annual_contribution`, a field `lbs-request@1.0.0` already has. It is the
contribution to the designated goal in twelve monthly steps, so it sets the required return and the level of the
target curve; 0 is a stated 0; absent, it is a gap and the proposal has no required return and no curve. It can
only be sent inside `mandate`, whose `goal_id` is required.

**The split between goals** (LBS-29): `goals[].contribution_share`, optional and additive (the contract stays
`lbs-request@1.0.0`), is a goal's share of that one yearly saving, 0 to 1; the stated shares sum to at most 1
(more is a 422). From calibration 1.3.0 the designated goal receives its stated share of the saving; all of it
when it is the only goal and states no share; otherwise the most it can receive (what the other goals' stated
shares leave, all of it when none is stated), with a gap `mandate_proposal.contribution_share` and a note that
the required return and the curve's level are then lower bounds. `mandate_proposal.annual_contribution` is the
goal's part. Calibrations before 1.3.0 do not read the shares. A request that does not state the field hashes as
it did under lbs@1.1.0.

Where each field came from in the prototype: persons and kinds from `households`/`household_members`, age from
`members.age_at_registration`, human-capital and risk answers from the stored submission and member facts
(`computations._answers`, `profile_inputs`), positions and goals from `positions`/`goals`/`goal_funding`, the vessel
and the goal kind from the label and name keyword rules (LBS-06).

`LifeBalanceSheet` (`lbs-balance-sheet@1.0.0`): `household`, `grid` (8 cells), `totals` (with `identity_holds`),
`human_capital`, `pensions` (`ahv`, `bvg` per adult), `couple_cap`, `property`, `liquidity`, `retirement`,
`observations`, `risk_profile`, `mandate_proposal`, `gaps`, `provenance` (engine and contract versions, calibration
version and hash, idempotency key, request hash, `as_of`, every record read and its approval state) and `notice`.
From calibration 1.4.0, additively (left out of the sheet before, so older artefacts keep their bytes): `real_view`
(the inflation used with its source and label, the contribution's indexation, each goal in both bases),
`mandate_proposal.basis`, `.views` (`nominal`, `real`: target, required return, its log) and `.plausibility`,
`retirement[].basis` (`real`) and `.views`, and `property[].basis` (`real`).

`MandateProposal` mirrors `pcp-mandate@1.0.0` (never imported): `client`, `name`, `currency`, `horizon_years` 1,
`curve_unit` annualised_log_return, `target_curve` (25 states), `universe`, `max_single_position`, `esg_min`,
`fixed_allocations`, `bounds`, `bound_sources`, `regime_weights`, `regime_market`; plus what it rests on
(`target_basis`, `target_chf`, `goal_horizon_years`, `drawable_chf`, `annual_contribution`, `required_return`,
`feasible`, `curve_shape`) and `curator_to_fill`. lbs fills **currency** (a 50% CHF floor), **liquidity** (the
deadline ladder) and, with an approved risk profile (calibration 1.1.0 on), **role** and the ESG floor
`esg_min`, each bound with its reasoning; the universe, the position cap, the regime blend and the policy
dimensions (region, capital type, phase, asset class) are the curator's (LBS-12). The curve is the policy ramp of -2.5 to +2.5 points (or the risk profile's slope) levelled on
the goal's required return and published as log returns (LBS-11).

Standard (Guide 2.1): `GET /health`, `/meta`, `/contracts`, `POST /run` (`run_id`, `artefact_id`,
`idempotency_key`, `cached`), `GET /runs`, `/runs/{run_id}`, `/artefacts/{artefact_id}`, `GET` and `PUT
/calibration`. Engine specific:

| Method | Path | |
|---|---|---|
| POST | `/validate` | Every gap and every unavailable section, without storing |
| GET | `/sheet/{artefact_id}` | The LifeBalanceSheet |
| GET | `/sheet/{artefact_id}/{grid, human-capital, pensions, findings, mandate, gaps}` | One view of it |
| GET | `/records` | Each content record's approval state in a calibration |
| GET | `/calibration/versions` | Calibrations, the active one marked |

## Calibrations

| Version | Parent | What |
|---|---|---|
| 1.0.0 | | The prototype's nine content records of 28.09.2026 verbatim with their approval metadata, and the draft's mandate figures (derive.py, S-curve engine). The prototype reproduced, records as shipped |
| 1.1.0 | 1.0.0 | `ahv-pension` and `risk-profile` approved by Nicolas, 29.09.2026 (LBS-23): content unchanged, `_about` completed. The prototype's behaviour otherwise (golden layer A, approved variant) |
| 1.2.0 | 1.1.0 | 1.1.0 with the `corrections` block: the four LBS-17 quirks corrected (LBS-24) |
| 1.3.0 | 1.2.0 | 1.2.0 with three more corrections (LBS-28): human capital never free wealth, a stated mortgage of 0 paid off, the saving split by goal share |
| 1.4.0 | 1.3.0 | 1.3.0 with the `real_view` block (LBS-31 to LBS-35): the inflation assumption per currency with its source (CHF the measured 0.50 %), the plausibility table by risk level as a proposal |
| 1.5.0 (active) | 1.4.0 | 1.4.0 with the owner's decisions on its assumptions (LBS-36 to LBS-38): CHF inflation 1.0 %, the midpoint of the SNB's 0 to 2 % range (EUR and USD unchanged); the plausibility table approved unchanged. What `POST /run` uses when the request names no calibration |

Approving a record is the owner's act and always a new version, never an edit in place
(`calibration.with_approved` builds it; `PUT /calibration` accepts one). A calibration without a `corrections`
block reproduces the prototype, and one that does not name the three flags of LBS-28 (1.2.0) reads them as not
corrected, and one without a `real_view` block has no real view. The contract is `lbs-calibration@1.3.0`; 1.0.0
keeps its `lbs-calibration@1.0.0` payload, 1.1.0 and 1.2.0 their `lbs-calibration@1.1.0` payloads, 1.3.0 its
`lbs-calibration@1.2.0` payload, 1.4.0 and 1.5.0 `lbs-calibration@1.3.0` payloads, and all six their hashes
(pinned in the tests).

## Model quality

* **Golden layer A**, the reproduction mode (`golden/cases`, `golden/expected`, frozen by `dev/build_golden.py`
  under the prototype's own interpreter, database opened read-only, nothing personal copied): eight database
  members and seven constructed cases, under 1.0.0 (records as shipped) and 1.1.0 (both records approved).
  Tolerance 1e-9 relative, verdicts and reason keys exact; measured deviation 0 on 659 figures. Divergences are
  classified in DECISIONS (LBS-14, LBS-15, LBS-16).
* **Golden layer B**, the corrected behaviour (`golden/corrected`, frozen by `dev/build_golden_corrected.py`,
  LBS-26, LBS-30), in two steps. Step 1.2.0: the fifteen layer-A cases and four quirk cases under 1.2.0,
  flattened, and `changes.json`, every leaf that differs from 1.1.0 with the correction that moves it; no leaf of
  the fifteen prototype cases moves, each quirk case moves by its own correction only. Step 1.3.0
  (`golden/corrected/1.3.0`): the same cases and four new ones (`r-*`) under 1.3.0, and `changes.json` against
  1.2.0; each new case moves by its own correction only, and the prototype cases move only where they exercise
  one: `db-01` and `db-05` (a stated mortgage of 0), `syn-couple` (a human-capital stock), and every multi-goal
  household with a stated saving (the share gap and a note, no figure). Step 1.4.0 (`golden/corrected/1.4.0`,
  LBS-35): every earlier case and five new ones (`v-*`, the design note's worked example among them) under 1.4.0,
  and `changes.json` against 1.3.0, each changed leaf attributed to the real view (new leaves), the plausibility
  judgement, the retirement comparison in today's francs, or the amounts in today's francs (decision 7). Step
  1.5.0 (`golden/corrected/1.5.0`, LBS-38): the same 28 cases under 1.5.0, `changes.json` against 1.4.0 (each
  changed leaf with its decision, the CHF inflation of 1 % or the approved table, and the kind of figure) and
  `required_returns.json` (each designated goal's required return under both, nominal and real, and its move). A
  regression reference, not an outside one.
* **Property tests** (hypothesis): the net-worth identity and the grid sums for any positions; the required return
  funds the goal and falls as contributions rise; the AHV table is monotone and bounded; the BVG projection
  reconciles to its parts; the risk profile interpolates between its anchors and stays in [0, 1].
* **Boundary**: the role cannot write outside its schema, owns it, no `REAL` column, every table commented,
  append-only triggers on calibrations and artefacts, and a concurrent burst against a real socket.
* **Mutation-checked**: thirty-nine guarded rules each reverted once and their tests turned red (LBS-22,
  `dev/mutation_check.py`), the owner's decisions of 29.09.2026 among them (nine for LBS-28 to LBS-30, eight for
  the nominal and real view, two for its settled assumptions).

## Open points

* Client data is personal data: retention, access and erasure rules for `run.request_json` and the artefacts are
  not defined yet (the scaffold's open point; LBS-03 keeps names and e-mails out).
* `intake-scales` and `roles` stay provisional and read ungated, as in the prototype.
* The consumer app does not ask the share per goal yet: until it sends `goals[].contribution_share`, a
  multi-goal household's required return under 1.3.0 is a lower bound with a gap (LBS-29).
* The consumer app does not ask the basis of an amount or the contribution's indexation yet: until it sends them,
  every amount is read in today's francs and every contribution as fixed (the owner's defaults).
* The mandate proposal for the curator to finalise: which derived dimensions pcp should accept from lbs, and a
  withdrawal rate if retirement goals are to carry a curve.

## Layout

```
config.yaml            port, store, active calibration (1.5.0)
src/lbs/
  api.py               routing only
  contracts.py         request, sheet, mandate proposal, calibration; pcp-mandate mirrored
  engine.py            every prototype service, ported (pure: no I/O, no clock)
  calibration.py       seed calibrations 1.0.0 to 1.5.0; seed_records/ (the prototype's content records)
  clients.py           no upstream engine
  store.py, schema.sql PostgreSQL, schema lbs, append-only artefacts and calibrations
  service.py           orchestration
golden/                layer A: cases (requests), expected (the prototype's outputs), manifest
  corrected/           layer B step 1.2.0: quirk cases, expected (1.2.0), changes.json (against 1.1.0), manifest
    1.3.0/             layer B step 1.3.0: cases r-*, expected (1.3.0), changes.json (against 1.2.0), manifest
    1.4.0/             layer B step 1.4.0: cases v-*, expected (1.4.0), changes.json (against 1.3.0), manifest
    1.5.0/             layer B step 1.5.0: expected (1.5.0), changes.json (against 1.4.0), required_returns.json,
                       manifest
dev/                   build_golden.py (prototype interpreter), build_golden_corrected.py, mutation_check.py,
                       make_deploy.py
testbench/index.html   development only
tests/                 layer_b.py (flattening and the change list, shared with the layer-B builder)
```

Model-derived research output. Not investment advice.
