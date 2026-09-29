# Portfolio Creation Program (PCP)

The Portfolio Optimiser of the shared macro compute path. It chooses instrument weights whose blended
return profile best matches a client mandate's target return curve, under the mandate's allocation
constraints, integrated over the live macro Regime.

**This is decision-support and research tooling, not investment advice.** Every figure it produces is
model-derived, not a forecast. Read the binding condition before the number: an exposure sitting on its
ceiling was chosen by the constraint, not by the fit.

## The model of record

An asymmetric squared-shortfall curve fit. For weights `x`, profiles `BB` (instruments by 25 regime
states), the mandate target curve `C` and the regime distribution `M`:

```
y = sum over states i of ( sum over instruments j of max( C[i] - M[i] * x[j] * BB[j,i], 0 ) )^2
```

Minimise `y` subject to `sum(x) = 1`, the mandate's per-category bounds, and the per-instrument position
cap.

There is no expected-return vector, no variance and no covariance matrix in this objective. Three
properties carry the method:

- The shortfall is summed over instruments **before** squaring. Squaring per instrument first is a
  different objective with a different optimum.
- Only the downside is penalised. Exceeding the target in a state costs nothing.
- Each instrument's contribution is scaled by the regime probability of the state, so the live regime
  decides which states the fit is judged in. This is why the crisis tail must not be smoothed away
  upstream.

A mean-variance branch exists for comparison only and is labelled as such on every output it touches.

## What it consumes

Both by reference, read-only, never recomputed:

| Contract | Producer | What it carries |
|---|---|---|
| Regime timeline | `macrofield` (Macro_Model) | A 25-length probability vector per month, crisis-low to boom-high, plus a `regime_id` |
| ReturnSet | `fmre` (Fund_Map) | Per building block, a 25-point return profile plus its register classification |

**The binding rule.** A ReturnSet whose `regime_id` does not match the Regime being optimised against is
rejected, not reconciled. There is no override: the alignment is wired in the producers instead.

**Units.** Both the instrument profiles and the mandate curve are annualised decimal fractions, so `-0.35`
means -35 percent per annum. A ReturnSet that does not declare `annualised_decimal` on the mandate's
horizon is refused rather than rescaled.

## Getting a run

The three programmes have to be run in order, because each consumes the one before it.

```bash
# 1. Publish the Regime, per economy and per blended market scope.
cd ../Macro_Model
python -m macrofield.cli regime cn in us ch br gb de fr --scope Global

# 2. Estimate return profiles against the scope the mandate will use.
cd ../Fund_Map
python -m fmre.cli build-returnset \
    --timeline ../Macro_Model/output/regime/Global.json \
    --source seed-aware-synthetic --out artifacts/rs.json

# 3. Seed mandates once from the legacy workbook, then optimise.
cd ../PCP
python -m tools.seed_mandates
python -m pcp.cli optimise --mandate fixture_balanced
```

A mandate scoped to a blend needs that scope's file. Pointing the PCP at a per-economy Regime while the
ReturnSet was estimated against a blend is exactly what the `regime_id` rule refuses.

## Commands

```
pcp optimise --mandate <name> [--market <scope>] [--speed fast|exact] [--optimiser curve|mv]
pcp backtest --mandate <name> --months 240
pcp report   --mandate <name>          # writes JSON, CSV and the prose brief
pcp mandates                           # list what is configured
pcp cockpit                            # serve the dashboard on localhost
```

Exit codes: `0` success, `1` a handled failure (an infeasible mandate, a `regime_id` mismatch, an
unpublished Regime), `2` a usage error. An infeasible mandate is a failure, not a success with a caveat.

## The cockpit

`pcp cockpit` serves a local dashboard. It is a control surface over the same `pipeline` and `reporting`
modules the CLI uses, so a result seen there is the result the CLI would write. The server sends JSON and
the browser draws with Plotly from a CDN. Failures come back as `ok: false` results with a readable reason,
never as HTTP 500s, because a build-order problem is an ordinary answer rather than a crash.

Seven views: run panel, allocation with breakdowns, the role by scenario portfolio map, the target curve
against the achieved profile, the regime tilt with its crisis tail, the backtest path, and realised
exposures against the mandate bounds.

## Layout

```
pcp/
  config.py        # YAML config and the fixed, ordered vocabularies
  contracts.py     # typed contracts; the regime_id, unit and classifiability checks
  ingest/          # regime.py, returnset.py, mandate.py
  model/           # objective.py, constraints.py, optimiser_curve.py, pfmap.py, optimiser_mv.py
  pipeline.py      # ingest, check, solve, assemble
  reporting/       # export.py (the single write boundary), brief.py
  cockpit/         # FastAPI server and the single-page front end
  cli.py
  tests/
config/defaults.yaml
mandates/          # seeded from the legacy workbook, then maintained here
tools/seed_mandates.py
decisions.md       # every decision the spec left open, with its basis
```

## Determinism

A run is a pure function of `(inputs, version)`. The solver start point is fixed, there is no unseeded
randomness and no wall-clock dependence. Every result records an `idempotency_key` (a hash of the inputs
and versions) and a `trace_id` derived from it, so replaying the same inputs reproduces the same trace.

## Reading a result

The written JSON, CSV and brief all carry the same stamps, attached at the write boundary rather than by
the caller: the `regime_id`, the ReturnSet and universe versions, the engine version, the mandate identity,
the currency, the unit, the `idempotency_key`, the `trace_id`, the model-derived label and the disclaimer.

`conditions_met` is recorded from the solver's raw weights **before** renormalisation. Renormalised weights
always sum to one, so reading only those would hide an infeasible mandate. If it reads `no`, the weights
shown may satisfy no constraint set at all.

## What is not here

- Computing the Regime (the macro programme owns it) or the ReturnSet (the Fund Map owns it).
- Reconciliation against the legacy MATLAB. MATLAB is no longer in use and is not installed, so spec
  section 9 is withdrawn; the reference implementation was read to extract the algorithm and the
  vocabularies, and nothing in `SIM_Tech` is written to or depended on at runtime. Correctness rests on a
  hand-computed objective fixture, explicit constraint-order tests, a determinism test and end-to-end tests
  against the real published contracts. See `decisions.md` D0 for what that does and does not buy.
- The Life Balance Sheet, which is its own programme.

Reading `decisions.md` before changing anything here is worth the ten minutes: it records three constraint
blocks that were inert in the reference implementation, and the new build's numbers differ from the
legacy's for those reasons.
