# PCP decisions register

Every decision that the build spec left open, or that reading the reference implementation forced,
recorded with its basis. Mirrors the convention of the Fund Map programme's `decisions.md`.

Settled with Nicolas on 2026-07-28 unless noted otherwise.

---

## Programme-level

### D0. The MATLAB reference is read-only source material, not a reconciliation target

MATLAB is no longer in use and is not installed. Spec section 9 (reconcile numerically against
`SIM_Master_Controller.m`) and the reconciliation half of acceptance check 2 are therefore not
achievable and are formally withdrawn. The MATLAB in `SIM_Tech/Master_Controller` was read to extract
the algorithm and the vocabularies; no legacy file is written to, and none is a runtime dependency.

In place of the golden run, correctness rests on:

- a hand-computed objective fixture (`tests/test_objective.py`), verified by arithmetic rather than
  by comparison against another implementation,
- constraint-assembly tests that pin block order and bound signs explicitly,
- a determinism test,
- end-to-end tests over the real upstream contracts.

**Consequence to accept:** there is no external oracle for the optimiser's numerical output. The
objective and the constraint assembly are verified; the specific weight vector a mandate produces is
not cross-checked against a second implementation.

### D1. Build new, do not port positionally

The Excel-positional ingest of `Dataloader.m` (row and column offsets in `Controller_Test.xlsx`) is
not reproduced as a runtime path. The workbook is read exactly once, read-only, by
`tools/seed_mandates.py`, to seed mandate YAML. Thereafter mandates are YAML.

---

## Units and vocabularies

### D2. Canonical unit: annualised decimal fraction

`profile_by_state` and the mandate target curve `C` are both annualised decimal fractions, so -0.35
means -35 percent per annum. Ingest rejects a ReturnSet whose `values_unit` is not
`annualised_decimal` or whose `horizon_years` differs from the mandate's stated horizon.

**Basis:** the live `rs.json` carries `values_unit: "annualised_decimal"` and `horizon_years: 1.0`.
Fund Map spec open question 4 named annualised as the assumed default.

**Legacy note (not reproduced):** in `Optimizer.m` the mandate curve was plotted as
`100*Client.ReturnDist` against an unscaled `ReturnDistFinal`, which means the workbook held the
mandate curve in decimals and the instrument profiles in percent, and the objective compared the two
directly. That unit inconsistency is not carried over.

### D3. Economic phase: four canonical values

Canonical: `Foundation`, `Build-up`, `Optimisation`, `Saturation`. Mapped on ingest:
`Maturing -> Build-up`, `Optimizing -> Optimisation`.

**Basis:** the macro Regime's set is authoritative. The Fund Map register's fifth label folds in.
Resolves Fund Map decisions D2 and PCP spec section 11 item 2.

### D4. Scenario order: crisis-low to boom-high in data, boom-first only in display

Every matrix, contract field, and export orders scenarios `Crisis, Contraction, Stagnation,
Expansion, Boom`, matching state index 0 (crisis) to 24 (boom). The portfolio map is emitted in that
order. Reversal to boom-first happens only in the cockpit heatmap's axis labels.

**Correction to the spec:** section 4.2 states that `pf_map.m`'s Boom-to-Crisis ordering is "a display
order only". It is not. `pf_map.m` lines 5 to 15 assign `Boom -> k=1 ... Crisis -> k=5`, so the legacy
matrix genuinely was boom-first in its column index. The spec's claim was wrong; the new build
standardises on the book order and does the reversal in the view layer.

### D5. Role labels

Canonical: `Gain`, `Income`, `Stabilisation`, `Protection`. Mapped on ingest: `Growth -> Gain`,
`Stabilization -> Stabilisation`.

### D6. Capital Type: LB then UB, like every other block

The legacy `Client` sheet had the Capital Type block header reading `UB | LB` while every other block
read `LB | UB`, and `Dataloader.m` read positionally regardless. The mandate YAML schema is explicit
(`lower` and `upper` keys per category), so the ambiguity cannot recur. `tools/seed_mandates.py`
reads the legacy block in its documented positional order and emits a warning naming the sheet, so a
seeded bound can be checked against intent.

Resolves spec section 11 item 1. The quirk is not reproduced.

### D7. Asset class: `Real Estate` maps to `Real Assets`

Canonical five: `Cash`, `Fixed Income`, `Equity`, `Real Assets`, `Alternative`. The Fund Map
register's `Real Estate` maps to `Real Assets`. A pure rename, no reclassification.

### D8. Capital type has an `Others` slot with no members today

The constraint vocabulary is `Financial`, `Real`, `Others` (3 rows). The Fund Map register only uses
`Financial` and `Real`, so the `Others` row is structurally present and carries zero weight. Not an
error, and the row is kept so the block width is stable if a third type appears.

### D9. The Boom column of the portfolio map is empty in the seed universe

The register's home-scenario vocabulary has four values (no `Boom`). The portfolio map is 4 by 5
regardless, so its Boom column is all zeros with today's universe. Recorded so an empty column is not
read as a bug. Carries Fund Map decision D3 forward.

---

## Regime and the country-weight adapter

### D10. `cw` is owned by the Regime producer, which publishes a timeline per market scope

**Superseded an earlier decision, and worth reading for why.** The first call put the country-weight
blend in this programme, reasoning that the weights are selected by the mandate's `market` scope and are
therefore mandate-side. That is true of the *selection* and false of the *blend*, and building it that way
produced a run that could never succeed.

The reason is the binding regime_id rule. A ReturnSet is estimated under exactly one Regime and stamps its
identifier. If the blend happens downstream, the optimiser integrates a distribution whose identifier no
ReturnSet can carry, so every blended mandate fails the check. The first end-to-end run failed exactly
there:

    regime_id mismatch. The ReturnSet was estimated under 'REG-02603f12b7873706';
    the Regime timeline carries 'REG-BLEND-1623bfbfe574c3e5'.

That is the rule doing its job, and the fix is not to weaken it. The information-flow blueprint's DAG
already showed the right shape: `BLEND -> REG -> RS`, with the market-risk blend upstream of the Regime
contract, not downstream of it.

So the macro programme publishes a Regime timeline per market scope, each with its own `regime_id`, built
by `macrofield regime <economies> --scope Global`. The Fund Map estimates against that same file, and the
PCP reads it. A blended scope is population-level (there are five, fixed, carrying no user data), so
publishing them keeps the regulated wall intact.

What remains on this side is the *selection*: a mandate names its scope, and the PCP looks up the timeline
published under that name. It never blends, and `pcp.ingest.regime.load_regime_for_market` fails with the
publishing command to run rather than computing a blend of its own.

Presets are config (`config/defaults.yaml`), reproducing the values of `Market_Signal.m` lines 173 to
185 over the vector order (China, EU, India, US, Switzerland, Brazil, UK):

| Market scope | China | EU | India | US | Switzerland | Brazil | UK |
|---|---|---|---|---|---|---|---|
| Americas | 0.10 | 0.20 | 0.00 | 0.60 | 0.00 | 0.05 | 0.05 |
| Europe | 0.10 | 0.40 | 0.00 | 0.20 | 0.15 | 0.00 | 0.15 |
| Asia | 0.55 | 0.05 | 0.25 | 0.15 | 0.00 | 0.00 | 0.00 |
| Sino | 0.70 | 0.10 | 0.00 | 0.20 | 0.00 | 0.00 | 0.00 |
| Global | 0.20 | 0.25 | 0.05 | 0.30 | 0.05 | 0.05 | 0.10 |
| (fallback) | 0.25 | 0.25 | 0.25 | 0.25 | 0.00 | 0.00 | 0.00 |

Resolves spec section 11 item 3. `Market_Signal.m` line 174's comment that the vector "should come in
as an input" is honoured: it is config, and overridable per run.

### D11. The Regime timeline is monthly, with the annual macro reading held as a step

The macro programme computes annually (a 1975 to 2024 annual panel) and the technical TAA signal is
monthly. The published Regime timeline is monthly: the TAA is used at full monthly resolution, and
each annual SAA reading is held flat across the twelve months of its year.

**Why this is a step-hold and not interpolation:** the macro state is an annual assessment, and
holding it constant within its year asserts nothing that was not assessed. No value between two
annual readings is manufactured. All intra-year variation in the published timeline comes from the
TAA, which genuinely is monthly. The hold is recorded in the timeline's provenance and notes.

Resolves spec section 11 item 4: a full per-period 25-length distribution is delivered, not only a
state path, so the objective never has to expand a path.

### D12. `opti_scale` belongs to the Regime producer, and the PCP selects a variant

`Opti_Scale` in the legacy reaches `Weights(Opti_Scale, Model_Weights)` inside `Market_Signal.m`, so
it reshapes the market-risk signal itself. That is Regime construction, which the binding DAG rule
puts upstream. The PCP's run panel therefore selects among Regime timeline variants that the macro
programme has already published; it never rescales a signal it consumed.

### D13. The seven-economy `cw` requires two new economies, not four

`cn.yaml` and `in.yaml` already exist in macrofield, and `eurozone.yaml` covers the EU slot. Only
Switzerland and Brazil were missing. Both are added as economy configs. The three JSON files that
happened to be in `Macro_Model/output` (us, de, gb) were the runs on disk, not the limit of what the
programme supports.

---

## The ReturnSet contract

### D14. Per-instrument metadata moves onto the ReturnSet

The constraint blocks need currency, asset class, economic phase, capital type, liquidity and ESG per
instrument, and the portfolio map needs the home scenario. All seven already exist in
`fund_map_seed.csv` and none was on the contract. They are added to the ReturnSet's `building_blocks`
entries, and the contract version is bumped.

**Why not read the seed CSV from the PCP:** that would take a file dependency on another programme's
internals with no version stamp, which the section 3 provenance rules forbid.

### D15. A geographic region column is added to the Fund Map register

The register had no geography. What `fmre` loaded as `region` came from the seed's `Risk Signal`
column over (Europe, Americas, Asia, Sino, Global), which is the regime signal scope. `rs.json` block
1 shows the consequence: `MXWO0FD Index`, a World index, tagged `"region": "Europe"`.

A `Region` column over the seven-value constraint vocabulary (Switzerland, Europe, East Asia, South
Asia, North America, South Pacific, Others) is added to the register and carried on the ReturnSet as
`region_geo`. The signal scope stays as `region_scope`, used only for regime selection. The two are
never conflated again.

Assignments were derived from each block's Bloomberg ticker. Those that the ticker does not settle are
flagged in `docs/region_assignments.md` for review rather than presented as read.

### D16. ESG becomes a real per-instrument constraint

The legacy ESG row was `ESG = ones(1, n)` (`curveoptimization.m` line 146), so the constraint
`-ESG . x <= -Client.ESG` reduced to `sum(x) >= ESG_min`, which is satisfied for any ESG minimum at or
below 1 given the budget equality. The constraint never referenced an instrument's ESG score and was
therefore inert.

The new build uses the register's per-instrument ESG scores, giving a genuine weighted-average floor
`-esg . x <= -esg_min`. This is a latent no-op being fixed, not a ported behaviour.

**Consequence to accept:** mandates whose ESG minimum was set against the inert constraint may now
bind or turn infeasible. That is the constraint doing what it was written to do.

---

## Optimiser

### D17. The objective is the asymmetric squared shortfall, exactly as `curveoptcalc.m` computes it

```
y = sum over states i of ( sum over instruments j of max( C[i] - M[i] * x[j] * BB[j,i], 0 ) )^2
```

Shortfall summed over instruments, then squared, then summed over states. Confirmed against
`curveoptcalc.m` line 18. The commented `sum((C-yhold).^2)` on line 17 is not the objective.

### D18. Constraint block order

`Currency (10), Region (7), Role (4), Capital Type (3), Liquidity (4), ESG (1), Phase (4),
Asset Class (5)`, each classification block appearing as `+block` for the upper bound then `-block`
for the negated lower bound, with ESG as a single negated row between Liquidity and Phase.

Confirmed against `curveoptimization.m` lines 32 to 34 and 148 to 150, which agree with each other
and with spec section 4.2.

### D19. Role allocation is the row sums of the portfolio map

Spec section 5 calls `role_allocation` the "column sums of the portfolio map". With roles as rows and
scenarios as columns, per-role totals are the **row** sums. `Optimizer.m` line 92 computes
`sum(Result(t).PortfolioMap')`, which is the row sums of `PF_Map`. The intent (per-role totals) is
implemented; the spec's wording is corrected here.

### D20. Solver

SLSQP with a fixed start `x0 = 0.5 * ones(n)`, falling back to `trust-constr` when SLSQP reports
failure. Tolerances per spec section 4.3 (`fast`: ftol 1e-3, maxiter 300; `exact`: ftol 1e-8, maxiter
3000). After solving, `conditions_met` is recorded from `round(sum(x), 1) == 1` before the weights are
renormalised, matching the order in `Optimizer.m` lines 37 to 44.

Note that `x0 = 0.5 * ones(n)` sums to `n/2`, so the start point violates the budget equality for any
`n != 2`. That is what the reference used, and it is deterministic, so it is kept.

### D21. The mean-variance branch is a labelled comparison, not a second model of record

Implemented behind the same `optimise(...)` interface, reintroducing a covariance matrix, and labelled
as a comparison optimiser on every output that carries it.

---

---

## What reading the legacy data revealed

Three constraint blocks in the reference implementation were wholly or partly inert. All three were
found by comparing `curveoptimization.m`'s classifier branches against the values the workbook actually
holds, not by reading the code alone. They are recorded because each one means the new build's numbers
will differ from the legacy's, and for a defensible reason.

### D22. The regional constraint distinguished only Europe from Others

`curveoptimization.m` lines 62 to 79 classify `Investment.Region.Var32` against the seven-region
vocabulary (Switzerland, Europe, East Asia, South Asia, North America, South Pacific, else Others). The
column's actual values across all 49 instruments are `Americas`, `Asia`, `Europe`, `Global`, `Sino`,
which is the five-value **regime signal scope**, not a geography.

Matching those against the branches:

| Value in the data | Row it reached |
|---|---|
| Europe | 2, Europe |
| Americas | 7, Others (fell through) |
| Asia | 7, Others (fell through) |
| Global | 7, Others (fell through) |
| Sino | 7, Others (fell through) |

So the Switzerland, East Asia, South Asia, North America and South Pacific rows were all-zero in every
run, and the regional block was effectively a two-way split. A mandate setting a North America ceiling
was constraining nothing.

This also settles the question behind D15: the workbook never held a geography either, so the Fund Map
register was faithfully carrying what existed. The `Region` column added in D15 is therefore new
information rather than a reconstruction of something lost, and the seven-region constraint works for the
first time.

### D23. `Maturing` instruments were classified as Saturation

`curveoptimization.m` lines 96 to 107 branch on `Foundation`, `Build up`, `Optimization`, else phase 4.
The `Investment` sheet's phase column holds `Foundation`, `Maturing`, `Optimization`, `Saturation`. There
is no `Build up` in the data, so every `Maturing` instrument fell to the else-branch and was counted
against the Saturation bound.

That `Maturing` belongs at position 2 rather than position 4 is not a guess: the instrument data uses
exactly four distinct values, and they map one-to-one onto the four phase positions only if `Maturing` is
the second. The `Client` sheet's label for position 4 is `Maturity`, an unrelated word that happens to
look like `Maturing`, and the two must not be conflated. This build maps `Maturing -> Build-up`
(position 2) per D3, so phase exposures will differ from the legacy's.

### D24. The ESG row was inert

Already recorded as D16, and it belongs in this list: `ESG = ones(1, n)` made the ESG constraint
`sum(x) >= esg_min`, which the budget equality satisfies for any minimum at or below one.

Note that all four workbook mandates set `ESG Rating = 0`, so the constraint would not have bound even
had it referenced the scores. The new per-instrument floor changes nothing for these four mandates and
becomes live only when a mandate sets a real minimum.

### D25. Two vocabularies inside one workbook

The `Client` sheet's phase constraint labels are `Foundation, Build up, Optimization, Maturity`, while
the `Investment` sheet's instrument phase values are `Foundation, Maturing, Optimization, Saturation`.
The same four positions, named differently in the two sheets of the same file. The canonical set of D3 is
used throughout, and the seeding tool maps the `Client` sheet's labels onto it positionally, warning as
it goes.

### D26. What the legacy mandates actually contain

Twelve, not four: the `Client` sheet carries mandate columns well past the first few, and every one has a
matching universe column in the `Investment` sheet. All twelve seed cleanly, and every bound block matched
the canonical vocabulary position for position, so the positional read is sound.

| Client | Mandate | Universe | Max position | ESG floor | Category bounds set |
|---|---|---|---|---|---|
| Beisheim | Beisheim_Mandate | 20 | 0.18 | 0 | 16 |
| PK_Post | PKPost_Mandate | 13 | 1.00 | 0.50 | 4 |
| SIM | Dynasty_Office | 11 | 0.30 | 0.50 | 0 |
| SIM | Swiss_Office | 11 | 1.00 | 0.50 | 0 |
| G7nesis | G7nesis_Mandate | 12 | 1.00 | 0.50 | 0 |
| Silverhorn | Belvedere_SI | 9 | 1.00 | 0 | 0 |
| SIM | Dynasty_Test | 8 | 0.30 | 0.50 | 0 |
| G7Nesis | TF | 5 | 1.00 | 0 | 0 |
| G7Nesis | MA | 5 | 1.00 | 0 | 0 |
| SIM | Global | 3 | 1.00 | 0 | 0 |
| SIM | Gold_Equity | 3 | 1.00 | 0 | 0 |
| G7Nesis | LS | 3 | 1.00 | 0 | 0 |

Beisheim is the mandate that exercises the constraint machinery: a 0.18 position cap, one pinned holding,
and sixteen currency bounds including a CHF floor of 0.50 and a USD band of [0.15, 0.19]. PK_Post sets
four currency bounds. That makes them the realistic end-to-end cases, and Beisheim is what the test suite
uses.

The remaining ten set every category bound to `[0, 1]`, so their allocations are shaped only by the budget
equality, the position cap where one is set, and the curve fit. Worth knowing before reading a SIM/Global
result as evidence that the constraint blocks work: for that mandate there is nothing for them to do.

The target curves are genuine step functions in annualised decimals. SIM/Global is -0.9 across states 1
to 8, +0.2 across 9 to 18, and +0.5 across 19 to 25.

Note the `market`, `currency` and `benchmark` fields of a seeded mandate are the configured run defaults,
not workbook values: those were `Main_Controller` cells chosen per run rather than properties of a
mandate. They are written so a mandate file is self-contained, and remain overridable per run.

### D27. The register and the workbook have diverged

Seed block 49 (`CS Long Vola`) carries ticker `VXTH Index` in the Fund Map register and `CSTSEREU Index`
in the workbook. Blocks 50 to 54 exist only in the register. The register is treated as authoritative,
being the maintained one, and the divergence is recorded rather than reconciled.

---

### D28. The objective's value depends on the size of the investable universe

A property of the specified form, not of this implementation, and it has consequences worth stating.

The shortfall is summed over instruments before squaring, so **an instrument at zero weight still adds its
full `C[i]` to every state's shortfall**: `max(C[i] - M[i] * 0 * BB[j,i], 0) = C[i]`. The objective
therefore carries a floor set by the universe size, `sum_i (n * C[i])^2` when nothing is allocated.

Measured on Beisheim (20 instruments, Global regime): the objective is 78.040 with every weight at zero,
and the very best achievable is 77.844. **The weights can move it by 0.25 percent of its level.**

Two consequences:

- Objective values are comparable only within one universe. Two mandates of different universe size cannot
  be ranked by objective value, and neither can one mandate before and after a universe change. The
  portfolio challenge therefore scores both sides on the union of the two universes, so its comparison
  stays valid.
- The optimiser cannot express "do not hold this". A zero weight still costs `C[i]` per state, so a wide
  universe is penalised against a narrow one holding the same positions.

This is faithful to `curveoptcalc.m` and is tested for. It is recorded because it is surprising, and
because reading a raw objective value as a quality score across mandates would be wrong.

### D29. The regime vector's scale changes what the objective prefers, and needs a decision

**Open. This affects every allocation, so it is the first thing to settle.**

The objective compares `C[i]` against `M[i] * x[j] * BB[j,i]`. `M` therefore sets how large an
instrument's contribution is relative to the target. This programme publishes `M` as a probability vector
summing to one, which makes each weight of order 0.04 and each contribution about **2.7 percent** of the
target's magnitude. Almost every state sits in near-full shortfall whatever the allocation.

The source data is in percent. `market_risk_signal.csv` publishes rows summing to 100, and the macro
programme normalises them to one. The legacy `Market.PFMapAllocation` was built from the `CRS.Signal_*`
matrices without that normalisation, so the operational `M` very likely summed to 100.

The difference is not cosmetic. Measured on the same mandate and regime:

| | `M` sums to 1 | `M` sums to 100 |
|---|---|---|
| objective, nothing allocated | 78.040 | 78.040 |
| objective, equal weight | 77.968 | **71.676** |
| objective, best single holding | **77.844** | 74.891 |
| range the weights control | 0.25% | 4.04% |

Read the middle two rows. With `M` summing to one, the best single holding **beats** equal weight, so the
objective prefers concentration. With `M` in percent, equal weight beats the best single holding, so it
prefers diversification. Those are opposite recommendations from the same mandate, universe and regime,
and only the second is economically sensible for a portfolio optimiser.

The mechanism is D28: with contributions small against `C`, each instrument's own shortfall term dominates
its contribution, so adding instruments costs more than it gains. Raising the scale of `M` reverses that.

Three ways out, none of which should be chosen quietly:

1. Publish `M` in percent, matching the source and probably the operational implementation. One-line change
   upstream, but it makes the Regime contract no longer a probability distribution, which the Fund Map
   estimator relies on for its state weighting.
2. Keep `M` a probability distribution and scale inside the objective, for example against `M[i] * n`
   or the state count, recording the factor as part of the model.
3. Keep both as they are and accept that the allocation is driven mainly by the constraints, with the
   curve fit acting as a weak tie-breaker.

**Decided on 2026-07-28: accepted as is for now.** `M` stays a probability vector, which is the honest
reading of the contract as published, and an allocation is understood as constraint-driven with the curve
fit acting as a tie-breaker between the portfolios the constraints already permit. That is a reasonable
basis for checking mandate compliance, which is the near-term use.

The condition attached to accepting it is that the caveat travels with the numbers rather than living only
in this file. So every run now **measures** its own leverage and reports it:

- `pcp.pipeline` computes the objective floor (the value with nothing allocated) and
  `weight_leverage = (floor - achieved) / floor`.
- Both appear in the diagnostics and are promoted into the exported header, so JSON and CSV carry them.
- Below 5 percent leverage the run adds a note naming the cause and pointing here, and the prose brief
  states the share and, when it is small, says in terms that the constraints settled the allocation.

A reader therefore cannot see one of these allocations without also seeing how much of it the fit actually
decided. Revisit by choosing option 1 or 2 above; the third option in the original list, establishing what
the operational `M` summed to by reading `Team_TAA_Risk_Signal.m` and the `CRS.Signal_*` construction,
remains the cheapest way to settle it on evidence rather than inference.

---

## Open items still requiring Nicolas

Recorded here rather than silently resolved.

1. **Block metadata that its ticker contradicts.** Block 17 "Global Real Estate indirect" carries
   `IYR US Equity`, a United States REIT ETF. Block 47 "Mining Equities" carries `MXWO Index`, plain
   MSCI World. Block 39 "Infrastructure" carries `SWIIT Index`, the Swiss real-estate funds index,
   which is also block 48's ticker. Block 54 "Trend Following" carries a United States listing but is
   scoped Europe. The geography column follows the ticker and flags each case.
2. **East Asia against South Asia for ASEAN and Asia Pacific.** Blocks 14 (`MXSO`, ASEAN), 30
   (`EHFI244`, Asia Pacific arbitrage) and 43 (`MXAP`, MSCI AC Asia Pacific) span the boundary. All
   three are assigned East Asia and flagged.
3. **Mandate horizon.** The mandate target curve is taken as annualised to match D2. Confirm that the
   curves seeded from `Controller_Test.xlsx` were authored on an annual horizon.
4. **ESG minimum recalibration.** See D16: existing ESG minimums were set against an inert
   constraint.
5. **PK_Post/PKPost_Mandate is infeasible as authored.** It sets a JPY currency floor of 0.025, but none
   of its thirteen instruments is denominated in JPY, so the floor can never be met. Eleven of the twelve
   seeded mandates are feasible against the published contracts; this is the one that is not. Either add a
   JPY instrument to its universe or drop the floor. The run reports it before solving, fails with exit
   code 1, and says so in the brief rather than quietly renormalising into a number that looks fine.

   Worth noting that the legacy implementation would not have caught this: with the currency block's
   bounds read but the ESG and region blocks inert, and no pre-solve feasibility check, an infeasible
   mandate surfaced only as weights that did not sum to one.
6. **A 240-month backtest is not currently available on a Global mandate.** The blended Global scope spans
   117 months (2010-01 to 2022-12), because India's Regime ends in 2022-12 and Brazil's begins in 2010-01.
   The window is the overlap of the contributing economies, and it is reported on every run. Extending it
   means extending those two economies' data coverage upstream.
