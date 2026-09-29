# Engine 07: Portfolio Creation Program (`pcp`)

The curve-fit optimiser. For a client's mandate it fits the target return curve across the 25 regime states
with the fmre instrument profiles, each state weighted by the client's blend of the Regime, under the mandate's
75-row constraint block, and publishes the **Allocation**: weights per instrument with the `regime_id` stamped,
in the mandate's reporting currency (CHF, EUR or USD), the same weights by role, the portfolio map, the curves
and the diagnostics. Unreleased: releasing advice is a person's act outside this engine.

> Model-derived research output. The allocation is the solution of a model, not a forecast and not a
> recommendation. **Not investment advice.**

| | |
|---|---|
| Module | `pcp` |
| Default port | 8007 (configurable) |
| Status | v1.2.0 (29.09.2026: joint feasibility check and solver rescue, PCP-21; reporting currency, PCP-18), calibration 1.1.0; the draft reproduced to 2e-14 (golden layer A); 100 tests |
| Consumes | `Regime` from `aggregation` (8004, `aggregation-regime@1.0.0`), `ReturnSet` in the mandate's currency and the instrument register from `fmre` (8006, `rs@1.0.0`), the client's `Mandate` |
| Produces | `Allocation` (`pcp-allocation@1.0.0`) |
| Downstream | `report` (the Allocation's facts), the cockpit's Parameters page |

## Run it

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\Optimizer\engines\pcp
start.cmd                                    :: engine on 8007, test bench at http://127.0.0.1:8007/
```

First time: `..\..\.venv\Scripts\pip install -e .[dev]`, the role and schema from
`python -m store.provision` (in `Projects\Engines\Instruments`), the password in `config.local.yaml`
(`database: password: ...`, git-ignored), then `python -m pcp init-db`.

A run needs `aggregation` and `fmre` running. pcp asks fmre for the ReturnSet stamped against the requested
Regime and measured in the mandate's currency (`/v1/return-set?regime_id=...&currency=CHF|EUR|USD`); fmre
confirms the Regime with aggregation first, and both the stamp and the currency enter the `return_set_id`, so
the request names the set fmre serves for that Regime in that currency (PCP-09, PCP-11, PCP-18). The tests run
on frozen inputs.

```bash
python -m pytest        # 100 tests, against the real PostgreSQL server
```

## The model

For weights `x` (n), profiles `BB` (n by 25, annualised log returns), the target curve `C` (25) and the client's
regime distribution `M` (25):

    minimise  sum over states i of ( sum over instruments j of max( C_i - M_i x_j BB_ji, 0 ) )^2
    subject to  A x <= b (75 rows),  sum(x) = 1,  0 <= x_j <= max_single_position (a fixed allocation pins x_j)

The draft's and MATLAB's objective (owner, 28.09.2026, PCP-03): the shortfall is summed over instruments before
squaring, only the downside counts, and each instrument's contribution is scaled by the regime weight of the
state. Its floor grows with the universe; `objective_floor` and `weight_leverage` say on every Allocation how
much of the objective the weights actually control (about 0.6% on fmre's 54 instruments). SLSQP with the exact
gradient, from every weight at 0.5, `trust-constr` as the fallback (the calibration's path, PCP-16). When that
path does not settle (unconverged, raw weights off the budget, or a row, the budget or a bound breached by more
than 1e-6), the engine restarts from the phase-1 point with the exact settings on the rows the budget and the
bounds do not already imply, SLSQP then `trust-constr` (PCP-21); the Allocation's notes say so. Layer A never
reaches the rescue.

**The client's regime** (PCP-04): `sum_e w_e * distribution_e(month)` over the mandate's economy weights, or a
market preset's published weights, at the requested month or the latest one in which all of them are assessed.

**The constraint block** (PCP-10), floor then ceiling per bucket:

| Rows | Dimension | Buckets |
|---|---|---|
| 1-20 | currency | CHF, USD, EUR, RMB, GBP, JPY, HKD, AUD, INR, Others |
| 21-34 | region | Switzerland, Europe, East Asia, South Asia, North America, South Pacific, Others |
| 35-42 | role | Gain, Income, Stabilisation, Protection |
| 43-48 | capital type | Financial, Real, Others |
| 49-56 | liquidity | Daily, Quarterly, Yearly, Decade |
| 57 | ESG | weighted-average floor, the only one-sided row |
| 58-65 | phase | Foundation, Build-up, Optimisation, Saturation |
| 66-75 | asset class | Cash, Fixed Income, Equity, Real Assets, Alternative |

Classification (PCP-06): fmre's register for what it carries; the calibration's table (the prototype's
54-instrument universe) for phase, home scenario and ESG, and for liquidity and region where the register has
none. Every ESG score is 1.0 today, so row 57 cannot discriminate.

**Refusals** (before any solve, each naming its reason): a `regime_id` on the ReturnSet other than the requested
one, or none (strict, PCP-11); a ReturnSet measured in another currency than the mandate's, or stating none
(strict, PCP-18, PCP-19); a `return_set_id` fmre does not serve; profiles in another unit than the curve, or
a horizon other than one year (PCP-13); a universe instrument fmre does not publish or that cannot be classified;
a weighted economy not assessed in the month; a mislabelled bound source (Manual 14.2); a structurally infeasible
mandate: per dimension, per bucket (a floor above what its instruments can hold under `max_single_position`), and as
a whole by a phase-1 linear programme, which names one smallest relaxation of the conflicting rows (PCP-21).
Nothing is published from an unconverged solve or from raw weights that miss the budget (PCP-15).

## Contracts and endpoints

`Mandate` (`pcp-mandate@1.0.0`): `client`, `name`, `currency` (`CHF`, `EUR` or `USD`, CHF by default: the
reporting currency, see below), `horizon_years` (1), `curve_unit`, `target_curve` (25), `universe` (fmre
instrument ids), `max_single_position`, `esg_min`, `fixed_allocations`, `bounds` (dimension to bucket to
`{lower, upper}`), `bound_sources` (dimension to `derived` or `policy`), and exactly one of `regime_weights` or
`regime_market`. `PCPRunRequest` (`pcp-run@1.0.0`): `regime_id`, `return_set_id` (the id fmre serves for that
Regime in the mandate's currency), `mandate`, `speed_mode` (fast or exact), `date`, `calibration_version`.

**Currency** (PCP-18, D-01). The mandate's `currency` is the currency of every return figure: fmre measures the
instrument profiles in it (the series are stored nominal in their source currency and converted at the point of
use), the `target_curve` is in it by definition (annualised log returns in that currency), and the curves in the
Allocation are in it. The Allocation says so in `currency` and `provenance.currency`; the served currency is also
in `provenance.upstream["fmre:currency"]`. It is not an exposure bound: the `currency` dimension of `bounds`
limits what the portfolio holds, whatever it is reported in. pcp reads the served currency from fmre's
`provenance.currency` when fmre publishes one, and from fmre's opt-in note (`... in currency=CHF; ...`) until then
(PCP-19). The contract versions are unchanged: every CHF mandate written before still validates with the same
`mandate_id`, and `currency` on the Allocation is an additional optional field (`None` only on Allocations
published before 1.1.0).

Standard (Guide 2.1): `GET /health`, `/meta`, `/contracts`, `POST /run`, `GET /runs`, `/runs/{run_id}`,
`/artefacts/{artefact_id}`, `GET` and `PUT /calibration`. Engine specific:

| Method | Path | |
|---|---|---|
| POST | `/validate` | Every check short of solving: plausibility, refusals, structural feasibility |
| GET | `/allocation/{artefact_id}` | The Allocation |
| GET | `/allocation/{artefact_id}/map` | Portfolio map, role by home scenario |
| GET | `/allocation/{artefact_id}/roles` | Weights by role, with the mandate's role bounds |
| GET | `/allocation/{artefact_id}/diagnostics` | Objective, floor, leverage, solver, binding rows, exposures, coverage |
| GET | `/constraints` | The 75-row block as the calibration lays it out |
| GET | `/calibration/versions` | Calibrations, the active one marked |

## Calibrations

| Version | What |
|---|---|
| 1.0.0 | The draft reproduced: vocabularies, ingest maps, SLSQP from 0.5, the legacy budget check `round(sum, 1) == 1` |
| 1.1.0 (active) | 1.0.0 with the budget read from the raw weights to 1e-6 (PCP-08) |

## Model quality

* **Golden layer A**: seven of the draft's own runs (`golden/draft`, frozen by `dev/build_golden_draft.py` in the
  draft's environment), reproduced to 1e-9 on weights and 1e-12 relative on the objective (measured 2e-14 and
  4e-16). **Layer C**: this build's production cases on frozen live inputs (`golden/inputs`, `golden/production`).
  Layer B (the MATLAB Review workbooks) is open (PCP-17).
* **Manual acceptance tests**, `tests/test_manual.py`: Step 25 (75 rows, row 57 one-sided, dimension starts) and
  section 15.7 tests 1 to 6, each named as the Manual numbers it.
* **Property tests** (hypothesis): objective non-negative; exact gradient against a central difference away from
  kinks; weights sum to one and respect every bound; blends sum to one; determinism.
* **Boundary**: the role cannot write outside its schema, owns it, no `REAL` column, every table commented,
  append-only triggers, and a concurrent burst against a real socket.
* **Mutation-checked**: each of the per-instrument sum, the layout check, the strict `regime_id` rule, the
  unreleased state, the raw budget check, the currency check, the currency passed to fmre and the currency
  on the Allocation was reverted once and its test turned red.
* **Feasibility and convergence**, `tests/test_convergence.py` (PCP-21): the 11 distinct mandates of the 18 failed
  runs of 29.09.2026, anonymised in `tests/fixtures/convergence.json`, each refused before solving with the rows
  named; two tight feasible variants on which the calibrated fast solve misses the budget, rescued; the rescue
  never engages on layer A. The capacity check, the joint check, the rescue and the reduced rows were each
  reverted once and their tests turned red.
* **Currency**, `tests/test_currency.py`: the mandate takes CHF, EUR or USD and defaults to CHF; the ReturnSet
  is requested in the mandate's currency; a set in another currency, in none or unconverted is refused; the
  Allocation names its currency, which enters the idempotency key. The frozen ReturnSet is fmre's
  source-currency default, read as the CHF case (PCP-20).

## Layout

```
config.yaml            port, upstream URLs, store, active calibration, default speed
src/pcp/
  api.py               routing only
  contracts.py         Mandate, PCPRunRequest, Allocation, Calibration; upstream mirrors
  engine.py            classification, the client's regime blend, one optimisation (pure)
  objective.py         objective, exact gradient, floor (pure)
  constraints.py       the 75-row block, layout check, binding rows, feasibility and phase 1 (pure)
  solver.py            SLSQP and the fallback; the rescue from the phase-1 point (pure)
  calibration.py       seed calibrations; seed_classification.json
  clients.py           aggregation and fmre callers
  store.py, schema.sql PostgreSQL, schema pcp, append-only artefacts and calibrations
  service.py           orchestration
golden/                draft (layer A), inputs and production (layer C)
dev/                   build_golden_draft.py, freeze_inputs.py, build_golden_production.py, make_deploy.py
testbench/index.html   development only; the Currency select sets the mandate's currency and fetches the matching set
tests/
```

Model-derived research output. Not investment advice.
