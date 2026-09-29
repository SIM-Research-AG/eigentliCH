# Battle plan: control board, and the SAA overlay into the 25-point signal

Target architecture, in one line:

```
  TAA (short-term, technical)  +  SAA (long-term, macrofield)  ->  Market Risk Signal  ->  PCP
       market_risk_signal.csv        this programme                 25 bins, 50:50            convictions.json
```

Written 2026-07-28, against seven items. Below: what already exists and can be reused, the phases in
dependency order, and the decisions that need an answer before the affected phase starts.

---

## What the reconnaissance found

This changes the plan materially, so it comes first.

| Source | What it is | Consequence |
| --- | --- | --- |
| `Master_Controller\Scenario_SAA.m` | **A working SAA scenario simulator.** 60 months, four scenarios (Depression, Hyperinflation, Stagflation, Deferral), a start MRS gradually transformed into a target MRS, and per-scenario `inflation` / `defaults` / `valuations` paths applied to per-asset 25-point return vectors. | This is the blueprint for items 1, 3 and 4. We port it, we do not invent it. |
| `market_risk_signal.csv` | The real TAA signal. Monthly **2006-Aug to 2026-Jul**, 25 columns in per cent, labelled Cautious / Careful / Neutral / Bold / Aggressive in blocks of five. | Item 4's input exists and is current. The bin partition is identical to our `regime.five_regime_bins`. |
| `Team_TAA_Risk_Signal.m` | The team-assessment generator. Confirms the `Binom` / `Binom_Bust` kernels we already carry. | Also confirms the `M(2)`-twice defect of MODEL_SPEC section 12. **`Scenario_SAA.m` is the un-bugged version of the same construction** and is the one to follow. |
| `Master_Controller\HoNI_Export.xlsx` | Readable. Sheets `HoNI`, `HoNI Score`, then one per country, with Financial / International / Real sub-indices. | **Item 7 is not blocked.** The "Health of Nations scorecard" can come off the unwired list. |
| SIM Master Deck, slides 15 and 28 | The *shape* of the distribution carries meaning: mass at the cautious end is "a risky market", at the aggressive end "an opportunistic market", and **dispersed or bimodal is "a swing market"**. | Bears directly on how TAA and SAA may be merged. See decision D3. |

### The placement discrepancy, which is the one real conflict

`Scenario_SAA.m` spreads **four** scenario weights onto the 25 bins at offsets `1, 3, 10, 16`:

```matlab
MRS = [Bust*Binom_Bust, 0(15)] + [0(2), Contr*Binom, 0(9)] + [0(9), Recov*Binom, 0(2)] + [0(15), Boom*Binom_Boom]
```

`config/defaults.yaml` spreads **five** book regimes at `1, 2, 6, 11, 16`. You directed the move to five on
2026-07-27 (MODEL_SPEC section 6). The two are not reconcilable by relabelling. See decision **D1**.

---

## Progress

| Phase | State | Where |
| --- | --- | --- |
| 0. Foundations | **done** | `macrofield/control.py`, `macrofield/data/taa.py` |
| 1. Control board | **done** | `POST /api/scenario/{code}`, cockpit Control board panel |
| 2. Fallbacks | **done** | `projection.project_resiliently`, `cycles.anchor_capital_cycle_by_projection` |
| 3. Superposition | **done** | `cycles.superpose` |
| 4. 25-bin translation | **done** | `model/saa_signal.py`, `signal_from_state` |
| 5. Merge | **done** | `model/saa_signal.py`, `merge` |
| 6. Nominal against real | **done**, on CPI and on the model's own basis | `macrofield/model/real_view.py`, `/api/derived`, Derived panel overlay |
| 7. HoNI | **done** | `macrofield/data/honi_export.py`, `/api/honi`, cockpit panel |

---

## Phase 0. Foundations (no decisions needed, start immediately)

**0.1 A path type for every control.** Controls have to vary over time, so a control is not a scalar. One
small dataclass:

```
ControlPath(mode = constant | step | ramp | pulse, base, target, start_period, end_period)
```

with `to_array(periods)`. Every lever below is one of these, and the board renders each as a sparkline so
the shape is visible rather than inferred. `/api/project` currently takes `stimulus_multiplier` and
`savings_multiplier` as scalars; they become paths, with the scalar form kept as `mode: constant`.

**0.2 A provenance label on every number the board produces.** The fallbacks of item 2 invent values by
design, so each series carries one of `OBSERVED | INTEGRATED | EXTRAPOLATED | ASSUMED`, and the front end
renders anything past `INTEGRATED` distinctly. Without this, item 2 quietly destroys the property the whole
programme is built on.

**0.3 The TAA loader.** Parse the `MARKET RISK SIGNAL` block of `market_risk_signal.csv` into a monthly
25-column frame, normalised to sum to one, with provenance `OBSERVED`. Refuse a row that does not sum to
100 within tolerance rather than silently renormalising.

---

## Phase 1. Item 1, the control board

Levers, grouped as they will appear:

| Group | Lever | Default | Type |
| --- | --- | --- | --- |
| Policy | Stimulus `S` multiplier | 1.0 | path |
| Policy | Savings rate `p_s` multiplier | 1.0 | path |
| Policy | Stimulus programme (size as share of GDP, start, duration, shape) | off | path |
| Structure | Credit uplift | 1.40 | scalar, sweepable |
| Structure | Level adjustments on `Y`, `K_R`, `K_I` | identity | scalar, sweepable |
| Horizon | Projection horizon | 15 | scalar |
| Horizon | Parameter carry mode | `hold_last` | choice |
| Cycles | Innovation trough year, period | 2032, 47 | scalar |
| Cycles | Capital anchor ratio, years into cycle | 3.5, 90 | scalar |
| Cycles | Per-cycle amplitude weights | equal | scalar x4 |
| Signal | Scenario | none / Depression / Hyperinflation / Stagflation / Deferral | choice |
| Signal | **TAA:SAA blend weight** | 0.50 | scalar |
| Signal | TAA extrapolation half-life | see D2 | scalar |

Every lever is a URL parameter, so a board state is a shareable link and a reproducible run. The board
shows the resulting paths, then the consequences: state trajectory, phase timeline, 25-bin signal.

**Deliverable:** a Controls panel at the top of the cockpit, and `POST /api/scenario/{code}` taking the
full control set and returning state, phases, signal and provenance in one response.

---

## Phase 2. Item 2, fallbacks instead of blockers

Two distinct blockers, two distinct fallbacks. Both must be visible in the output, never silent.

**2.1 The projection does not integrate.** DONE, `projection.project_resiliently`.

A **binary search**, not the fixed ladder this plan first proposed. The ladder was tried and discarded: a
descending (12, 10, 8, ...) answered a request for 40 with 12 integrated periods on United States data where
**35 integrates**, throwing away most of the available model output. A single projection costs 30 to 300
milliseconds, so searching for the true maximum in about six attempts is affordable and strictly better. It
assumes integrability is monotonic in the horizon, which holds because the obstacle is a singularity at a
fixed time. Every attempt is recorded so the descent is auditable.

**The extrapolation takes its level from the model and its slope from history**, and that correction matters
more than the search. Continuing the *integrated tail's* growth rate compounds the very divergence that
stopped the integration: on United States data it took the saturation axis to 37 over a 40-period request
and to 3.7e24 over a 200-period one. Taking the slope from the economy's observed history instead gives 10.4
and 67.6. Where the two rates differ by more than a factor of three the difference is reported, because it
measures how hard the model was diverging when it stopped.

**2.2 No capital-cycle anchor.** DONE, `cycles.anchor_capital_cycle_by_projection`, off unless a caller asks
for it via `assume_capital_crossing`.

Fits the recent trend of the saturation axis, solves for the year it would cross 3.5, and anchors
provisionally there with `Provenance.ASSUMED`. It refuses in three cases, and the first is the one that
fires in practice: a **flat or falling** trend, a crossing more than 120 years out, or fewer than two
observations. Assuming *when* an economy reaches saturation extrapolates a rising trend; assuming *that* it
will, against a falling one, is a different and much weaker claim.

Both live cases refuse. Germany at 2.76 and India at 2.50 are not only below the anchor, their ten-period
trends are **negative**, so they stay unanchored even with the assumption enabled. The reason the observed
anchor failed is carried alongside, so an assumption is always read against it.

---

## Phase 3. Item 6, cycle superposition (before item 3, which consumes it)

Sum the four cycle components into one interference series, and plot the parts against the sum with
constructive and destructive regions shaded.

The obstacle is that the amplitudes are incommensurable: the band-passed business and credit components are
deviations in a growth rate of order 0.02, and the anchored innovation and capital components are
normalised to unit amplitude because an anchor supplies a position and not a size. Summing them raw would
make the sum a picture of the two anchored cycles. See decision **D4**.

**Deliverable:** `cycles.superpose(...)`, a chart of the four components plus their sum, and a scalar
`interference` series that phase 4 uses as an input.

---

## Phase 4. Item 3, the macro state as a 25-bin distribution

The translation, in three steps:

1. **State to regime weights.** From what the model already computes: the phase and which rule fired;
   saturation against the band; `K_R/K_I` against one; the unsecured-gap direction; the capital-cycle
   position (years past the reordering point); the innovation-cycle position; and the interference series
   from phase 3. Each contributes a tilt to the regime weights.
2. **Regime weights to 25 bins.** The existing `regime.build_distribution` already does this, with the
   kernels and placements from config.
3. **Over time.** For each projected period, recompute the weights from the projected state, giving a
   25-bin distribution per period, which is the `T x 25` surface `Scenario_SAA.m` produces.

Two things to be honest about. The tilt weights in step 1 are **a judgement call with no source**; they will
be exposed in config, defaulted to something defensible, and stress-tested rather than presented as
derived. And `Scenario_SAA.m` reaches its target MRS by a *gradual transformation* from the current one
rather than by recomputing per period; we should do both and compare, because they answer different
questions.

**Deliverable:** `model/saa_signal.py`, a per-period 25-bin distribution, and a surface chart over the
horizon.

---

## Phase 5. Item 4, the merge

1. **Current TAA** is the latest CSV row, 2026-Jul, normalised.
2. **Future TAA** has to be extrapolated, and how is decision **D2**.
3. **Merge** in 25-bin space: `w * SAA + (1 - w) * TAA`, renormalised, `w` from the board, default 0.50.
   Merging in bin space rather than in regime space is deliberate: bins are vocabulary-free, so the
   four-against-five question of D1 does not propagate into the merge.
4. **Emit** in `convictions.json` shape so the PCP consumes it unchanged.

The merge must report the **dispersion** of the result alongside it, because per the deck a dispersed or
bimodal distribution is itself a reading ("a swing market"). See decision **D3**.

---

## Phase 6. Item 5, nominal against real

A reading pass over chapters 10 and 11 and the indicator definitions, producing a table of every indicator
and ratio with whether the book computes it nominal or real, and on which deflator. Two findings already in
hand:

- Chapter 11 computes the long real-rate series using **the gold price as the deflator**, not CPI. That is a
  framework commitment, not an implementation detail.
- Chapter 24 records two structurally different inflation regimes (0.47 per cent a year to 1920, 2.6 per
  cent after), so an indicator spanning 1914 to 1971 spans two regimes and should not be treated as one.

There is a terminology collision to resolve first: our `derived.py` uses `real_*` to mean **the real economy
as against the financial economy**, not "inflation-adjusted". See decision **D5**.

---

## Phase 7. Item 7, HoNI on the latest data

Now unblocked. Read `HoNI_Export.xlsx`, wire the fifteen indicators into the existing `honi.score_economy`,
and render the scorecard for the latest year only. The existing direction convention (higher is healthier,
established from the export's own values, MODEL_SPEC section 4) applies. Remove HoNI from the cockpit's
"computed but not charted" panel.

---

## Order and dependencies

```
Phase 0 (foundations)
  -> Phase 1 (control board) ----------------+
  -> Phase 2 (fallbacks) --------------------+
  -> Phase 3 (superposition) --> Phase 4 (25-bin) --> Phase 5 (merge) -> PCP
  -> Phase 7 (HoNI)                          |
     Phase 6 (nominal/real) ----------------+
```

As at 2026-07-28, D1 to D4 are settled, so **phases 0, 1, 2, 3, 4, 5 and 7 are all unblocked**. Only phase 6
waits, on D5.

Suggested order of work, given that:

1. **Phase 0**, foundations. Small, and everything else depends on it.
2. **Phase 7**, HoNI. Self-contained, newly unblocked, and the quickest visible win.
3. **Phase 2**, fallbacks. Needed before the control board is worth using, since a board whose every other
   setting fails to converge is not a board.
4. **Phase 1**, the control board itself.
5. **Phase 3**, superposition, then **phase 4**, the 25-bin translation, then **phase 5**, the merge. This is
   the long pole and the actual deliverable.
6. **Phase 6** whenever D5 lands.

---

## Decisions, settled 2026-07-28

**D1. Five regimes everywhere.** RESOLVED: five. The book's taxonomy governs throughout, at placements
1, 2, 6, 11, 16, and `Scenario_SAA.m`'s four-scenario layout at 1, 3, 10, 16 is **superseded**. There is one
mapping in the programme and one only.

Two consequences to accept deliberately:

- Scenario output will **not** reproduce `Scenario_SAA.m` line for line. That file becomes the source of the
  scenario *definitions* and of the transformation mechanics, not of the bin layout.
- The four scenario definitions have to be re-expressed in five-regime weights, and **"Recovery" has no
  five-regime equivalent**. MODEL_SPEC section 6 already settled why: "Recovery is a transition rather than a
  regime and gives way to BOOK's Stagnation and Expansion." So Recovery is split between Stagnation and
  Expansion. Proposed translation, with the split at 50:50 and exposed in config:

| Scenario | `Scenario_SAA.m` (Boom, Recovery, Contraction, Bust) | Re-expressed (Crisis, Contraction, Stagnation, Expansion, Boom) |
| --- | --- | --- |
| Depression | 0, 0, 0.25, 0.75 | 0.75, 0.25, 0, 0, 0 |
| Hyperinflation | 1, 0, 0, 0 | 0, 0, 0, 0, 1.00 |
| Stagflation | 0.5, 0.25, 0.25, 0 | 0, 0.25, 0.125, 0.125, 0.50 |
| Deferral | 0.5, 0, 0, 0.5 | 0.50, 0, 0, 0, 0.50 |

Worth a second look: Hyperinflation maps entirely to **Boom**, because the source vector is in *nominal*
terms and a hyperinflation is a nominal boom. That is faithful to `Scenario_SAA.m` and it is also exactly the
nominal-against-real problem of item 5 showing up in the signal layer. Flagged rather than silently carried.

**D2. TAA decays to its long-run average.** RESOLVED: exponential decay toward the trailing historical mean,
half-life a control variable, default six months. Beyond roughly two years the merge is effectively SAA
alone, which is the intended division of labour.

**D3. A bimodal merge is a finding.** RESOLVED: merge linearly in bin space and report the dispersion
explicitly. TAA and SAA disagreeing is dispersion of view, and per deck slide 15 that is what a swing market
means. The board reports a dispersion statistic beside every merged signal so the shape is never read by eye
alone.

**D4. All cycles at unit amplitude, equal weights.** RESOLVED: normalise all four so the superposition is
pure phase interference, with per-cycle weights in config defaulted to equal. No amplitude is invented.

**D5. Both a nominal and a real view.** RESOLVED 2026-07-28: build both. `derived.py`'s existing `real_*`
naming means the *real economy against the financial economy*, which is a different axis from
inflation-adjusted against nominal, so phase 6 has to disambiguate the vocabulary as its first act rather
than adding to the confusion. The deflator choice is still open in detail and the plan is to report the
book's own gold deflator (chapter 11) as the headline, since it is the framework's commitment, with CPI
alongside.

---

## Item 6 as built: two bases, and why output needed the second one

The nominal reading is primary and each real view is an overlay on it, per the author's instruction of
2026-07-28.

**The terminology had to be settled first.** `derived.py`'s `real_*` means the real economy *as against the
financial economy*, a statement about **sector**. Nominal against real is a statement about **basis**, whether
a quantity is deflated. The two are orthogonal and `real_view.py` never says "real" unqualified.

**Two bases are produced, and output can only use one of them.** Chapter 7 derives the real-economy price
level as `P_R . H_R = Y`, so `P_R` is proportional to output and deflating output by it is *circular*: the
first cut returned exactly 1.0 times over 52 years, which would have read as five decades without real
growth. The capital stocks are not in `P_R`'s definition, so their model-deflated view is genuine.

Output therefore needed an independent deflator, so **both** are now fetched as optional series alongside
equity: `consumer_prices` (`FP.CPI.TOTL`) and the LBMA `gold_price`, which covers 1968 to 2026 and so spans
every window in the panel. Gold is not an alternative to CPI, it is **the book's own basis**: chapter 11
computes its 172-year real-rate series with it, on chapter 24's argument that in a fiat regime gold is a
price-of-money instrument. The front end prefers gold, then CPI, then the model's own level, and that order is
the argument: the framework's basis, then a measured index, then a model quantity.

United States, 1972 to 2024, growth over the window:

| | nominal | real, gold | real, CPI | real, model |
| --- | --- | --- | --- | --- |
| Output | 22.9x | **0.57x** | 3.05x | circular, withheld |
| Real capital | 19.3x | 0.48x | 2.57x | 0.84x |
| Financial capital | 42.2x | **1.05x** | 5.62x | 1.84x |

**The two independent bases disagree about the level and agree about the divergence, and both facts matter.**

On CPI the American economy roughly tripled in real terms. Against gold it is at **0.57 times** its 1972 size,
and real capital at 0.48. That is not a rounding difference, it is the framework's whole argument about fiat
measurement showing up in one table: measured against the thing the book treats as money's own store of value,
half a century of growth largely disappears. Chapter 24's two-regime finding is the same claim from the other
direction.

What both bases agree on is the ratio. Financial capital grew about **2.2 times faster than real capital** in
CPI terms and about **2.2 times** faster against gold. The divergence is robust to the deflator even though the
level is not, which is a stronger result than either basis alone could give.

Two guards worth keeping: a deflator that does not cover the whole window is refused rather than used for part
of it, because deflating some periods and not others splices two bases into one series; and any window crossing
1914 to 1971 carries the chapter 24.3.1 warning, since inflation averaged 0.47 per cent a year before it and
2.6 after.

## The four remaining decisions, settled 2026-07-28

**The tilts stay a judgement call, and the spread is reported.** `saa_signal.sweep_tilts` scales every tilt
across `validation.sensitivity.range` and reports the range the crisis weight moves over, so the board quotes
a range and not a point. It also varies each tilt *alone*, which is the more useful half: it names the
coefficient the answer actually rests on. `base` is deliberately not swept, because scaling it alongside the
others moves numerator and denominator together and would report a robustness the signal does not have.

On the United States latest state the crisis weight runs **0.193 to 0.206**, a spread of 0.013 around 0.197 at
the configured tilts. That is a narrow band, and the per-tilt breakdown says why: only three coefficients do
any work at all, led by `saturation_below_band` at 0.055 and `interference` at 0.050, while four contribute
nothing because the state does not trip them. **The unsourced coefficients turn out not to be carrying the
answer**, which is the useful finding and is exactly what a sweep is for.

**Innovation period confirmed at 47 years**, the midpoint of the observed 40 to 54 band. The nominal 36 was
considered and not taken.

**The HoNI dimension mapping is confirmed**: three contiguous blocks of five, as the column ordering implied.
`config/honi_indicators.yaml` no longer records it as requiring confirmation.

**The stock-to-gold model stays switched off**, notwithstanding that the gold-deflated basis is now live.

## Notes from the build

**`docs/training.html` is gone.** It was present at the start of 2026-07-28 at 56,822 bytes and is now
absent from `docs/`, not moved anywhere under `SIM_NAS`, and not in the recycle bin. It was not deleted by
this programme. `tools/build_schulung.py` now links to it only when it is on disk, so the Schulung has no
dead link either way. Three things in it were stale and will need doing if it is restored or rewritten:

- it printed the gold equation with **driver one negative**, which is the sign error corrected on
  2026-07-27,
- its gold section teaches a model that is now switched off,
- its cycles section says all four cycles are re-estimated per economy, which two of them no longer are.

**The five incomplete TAA rows, diagnosed.** Traced on 2026-07-28, and the cause is specific enough to fix at
source.

First, the baseline: **a good row totals about 99.90, not 100.** That is the publisher's normal, the rounding
of a 25-way split to two decimals. The loader's tolerance of 0.25 accepts it and rejects the five below,
which is the right behaviour on both counts.

The excess in every one of the five is a spurious value in **bins 8 and 9**, and removing it lands each row
exactly on its neighbours' total:

| Row | published | bins 8+9 | without them | neighbours |
| --- | --- | --- | --- | --- |
| 2008-11 | 100.92 | 1.04 | 99.88 | 99.87 / 99.90 |
| 2009-04 | 103.32 | 3.58 | 99.74 | 99.88 / 99.90 |
| 2013-11 | 109.06 | 9.15 | 99.91 | 99.90 |
| 2013-12 | 109.06 | 9.15 | 99.91 | 99.89 |
| 2014-02 | 109.07 | 9.15 | 99.92 | 99.89 / 99.90 |

The three 2013 to 2014 rows share more than a total. Their **first nine cells are byte-identical**,
`0.48, 0.42, 0.16, 0.03, 0, 0, 0, 8.04, 1.11`, while bins 10 to 25 differ between them. That is a stuck or
pasted block: the head of the row was carried over and not recomputed while the tail was. The 8.04 at bin 8
sits between zeros at bins 5 to 7 and 1.11 at bin 9, which no kernel in the construction can produce.

Worth noting what is *not* the defect: 2009-08, 2011-01 and 2011-02 carry the same *shape*, a small isolated
value in bins 8 or 9 after a run of zeros, and total correctly. So the shape is legitimate and the magnitude
is the problem. A fix at source should look at whatever wrote bins 8 and 9 in those five months rather than
at the shape.

**The HoNI panel and this programme's panel do not coincide.** The export covers 16 economies but not
France, so `fr` has no HoNI reading and the scorer says so instead of substituting the euro area.

**The policy levers had to act forward, not on the observed window.** The first cut scaled
`path.stimulus_proxy` before calibration, matching the existing `/api/project` semantics. A stimulus dated
2027 then multiplied nothing at all, because the observed window ends in 2024, and the board produced output
identical to the base case. `project` now takes `forward_stimulus` and `forward_savings`, one multiplier per
projected period, and `project_resiliently` resolves the control per attempted horizon because the horizon
search changes how many periods there are. With that fixed the levers bite sensibly: stimulus off raises the
2039 crisis weight from 0.318 to 0.329, stimulus doubled lowers it to 0.314, and a savings ramp to 1.4 raises
it to 0.367 and flips the end phase from Foundation to Optimisation.

**The exit from Phase 4 is latched. Directed 2026-07-28.**

`classify_period` is stateless, so on a falling path it reclassified as soon as saturation crossed back under
the Phase 3 ceiling: the United States projection read **Build-up at 2.31 in its first projected period**.
That is wrong about the framework. Phase 4 is the reordering, and an economy part-way through a correction has
not returned to Build-up.

The rule, in the author's words: **the phase changes to Foundation only when it reaches that level, otherwise
it sits in Saturation.** Implemented as `phases.classify_sequence`, a one-way latch: once a path is in Phase 4
every later period stays there until saturation falls below `foundation_saturation_ceiling`, and only then does
ordinary classification resume. Entry into Phase 4 is unchanged. It is a *sequence* property, so `project`,
`project_resiliently` and the board all classify the whole path at once rather than period by period, and the
observed end state is included so the latch is seeded correctly.

The United States projection now reports **one** transition, 2030 Saturation and reordering to Foundation at
saturation 0.91, where it previously reported two.

**And the cycle restarts when the reordering completes. Settled 2026-07-28, and it follows from the same rule.**

The anchor was the last observed crossing, so "years past the reordering point" grew without bound. While the
economy is *held in Saturation* that is coherent, which is what the latch fixed. Past the Foundation crossing
it was not: the correction is finished, yet the anchor went on reporting the economy decades late for it and
that tilt kept pushing weight to crisis.

`cycles.reordering_end` finds the first Foundation period following a Saturation one, and
`cycles.years_into_capital_cycle` restarts the count there. Reaching Foundation without ever having been in
Saturation is *not* a restart, since an unsaturated economy has been through no reordering.

On United States data the reordering completes in **2030** and the capital tilt disappears from that period.
Its effect on the signal:

| | 2029, still reordering | 2030, restarted |
| --- | --- | --- |
| Capital tilt to crisis | +1.24 | none |
| Crisis weight | 0.300 | **0.229** |

The board reports the restart as `capital_reanchor` rather than warning about a contradiction, because there
is no longer one.
