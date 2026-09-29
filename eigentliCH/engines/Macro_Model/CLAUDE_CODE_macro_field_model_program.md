# Claude Code task: build a calibratable macroeconomic field-model program for the major economies

## Purpose and scope

Build a real, data-calibrated implementation of the macroeconomic field model set out in *Capital Saturation* (the field-theoretic foundation in Part II and the economic state model in Chapter 20, the Health of Nations Indicator in Chapter 12) and in the German source note "Feldtheoretische Beschreibung der Dynamiken von Volkswirtschaften." The programme must model the major world economies from actual published data, calibrate the model parameters to each economy, and produce the diagnostics the framework defines: the phase of the capital cycle, the Health of Nations score, the unsecured-asset gap, the stock-to-gold ratio trajectory, and the regime-state distribution.

This is an engineering task, not a writing task. The output is a working Python programme in this repository, with tests, a data manifest, and reproducible runs. It is a decision-support and research tool, not investment advice, and it must say so.

### House rules (hard constraints)

- **Use British spelling throughout** (optimise, stabilise, generalise, behaviour, financialisation, and so on).
- **Do not introduce em-dashes anywhere** in code comments, docstrings, or generated prose. Use commas or parentheses.
- **Use only verified, published data.** Never fabricate, interpolate silently, or synthesise figures to fill a series. Missing data is flagged, not invented. A run that would require an unavailable input fails loudly rather than guessing.
- **Model outputs are model-derived, not point forecasts.** Label projected paths as illustrative or model-derived. The 2032 synchronisation is a structural consequence of the cycle model, not a dated prediction, and must be presented that way. Do not hard-code the older dated forecasts that appear in legacy documents (for example the 2022 peak and 2025 to 2028 window in early gold notes); those illustrate the method and must not become constants.
- Attribute the model to *Capital Saturation* (Steiner and Bürkler) and its sources; the two-body foundation is Genreith's macroeconomic field theory. Do not attribute the work to any other individual.

---

## 0. The model of record

Implement exactly this. Keep the symbols and equations as written.

### 0.1 State (the three-body EDM)

Three coupled state variables for each economy:

- `Y`  gross domestic product (the real economy proxy, prices times volume of the real economy)
- `K_R`  real capital
- `K_I`  financial capital

Net capital `K = K_R + K_I`. The debt side and the capital side are identities in a fractional money system (one agent's asset and return claim is another's debt and interest), so the model treats them as interchangeable; document this where `K_I` is assembled from data.

### 0.2 Equations of motion

```
Ẏ   = (p_b − p_s) Y + K̇_R − p_p K_R + S
K̇_R = (1 − α) p_s Y + p_p K_R + r K_I
K̇_I = α p_s Y + p_p K_I − r K_I + S
```

with

```
r   = 1 − K_R / Y                     (investment share, financial into real)
α   = (1 / p_s) · (Ẏ / Y)             (share of the savings rate flowing to financial capital)
p_p = Ẏ / K_R + K̇_R / K_R            (achievable return on capital)
p_b = (Ẏ + K̇_R) / K̇_I               (approx. wage-vs-capital income, tracks population growth)
```

`p_s` is the savings rate. `S` is the exogenous stimulus injection, attributed to financial capital because it is normally financed by new debt (fiscal deficit, central-bank balance-sheet expansion, net new credit).

### 0.3 Consistency check (two-body reduction)

Summing the real and financial capital dynamics must reproduce Genreith's two-body equation. Implement this as a unit test:

```
K̇ = p_s Y + p_p K,   where K = K_R + K_I
```

The simulated `K̇_R + K̇_I` must equal `p_s Y + p_p K` to numerical tolerance at every step. If it does not, the parameterisation is inconsistent and the run should warn.

### 0.4 Extended quantity equation and the unsecured-asset gap

The quantity equation `M·V = P·H`, split into real (`R`) and financial (`I`) sectors, is `M_R V_R + M_I V_I = P_R H_R + P_I H_I`. Under the framework's simplifications (velocities approximated at one, money supply approximated by the relevant capital stock, real-economy price times volume set equal to `Y`), the fundamental relation is

```
K_R + K_I = Y + P_I · H_I
```

from which the financial value not covered by the productive economy is

```
Unsecured Assets = K_R + K_I − Y
```

Compute this as a core diagnostic. Its ideal-typical shape is slow growth, then acceleration from Phase III, then collapse in Phase IV. Also expose the stability-of-financial-prices check, where the `K_I` definition is expected to hold from full capitalisation until the "feeding" ends, and to diverge in Phase IV; surface that divergence as a fragility signal.

### 0.5 Phase model

Classify each economy each period. Production economy when `K_R / Y < 1`; financial economy when `K_R > Y`. The four phases:

- **Phase 1, Foundation:** `K / Y < 1`, GDP-driven.
- **Phase 2, Build-up:** `K_R / Y < 1`, real-investment and credit-driven.
- **Phase 3, Optimisation:** fully financialised, `K / Y < 3` and `K_R / Y < 1.5`.
- **Phase 4, Saturation and reordering:** `K_R / K_I < 1`. Here the capital-to-GDP ratio corrects not through growth but through capital destruction, by debt deflation or by hyperinflation.

Report the phase, the distance to each transition boundary, and the transition indicators (accelerating unsecured assets into Phase III, `K_R / K_I` crossing one into Phase IV).

### 0.6 Health of Nations Indicator (HoNI)

Capital saturation is total capital over GDP, `(K_R + K_I) / Y`, expressed as a percentage. The balanced band is 250 to 350 percent; below is under-financialised, above slips into the saturation zone of hyper-financialisation. Score each economy on the three sub-indices the HoNI uses, **Financial**, **International (resilience)**, and **Real**, each on a 1.0 to 5.0 scale, and produce the composite. Group economies into the four saturation categories. Make the scorer comparative across economies (the HoNI reports pairwise comparisons such as the United States against China).

### 0.7 Stock-to-gold ratio (three drivers)

Model the change in the stock-to-gold price ratio as a differential equation in three drivers arising from the three-body model, with weighting factors `ω_1, ω_2, ω_3`:

1. **Liquidity / credit impulse.** The gold-to-equity ratio moves reciprocally to system confidence, approximated by the credit impulse (a function of `K_I` and `S` dynamics).
2. **Innovation-driven growth.** Under normal growth, value-creating firms let equities outperform gold (a function of `Ẏ` and `p_p`).
3. **Capital-cycle currency stability.** A derivative of the quantity equation. Above a threshold of capital to output the quantity equation loses validity and currency stability is lost; this driver dominates in a hyperinflationary phase, where gold outperforms.

The dominant driver selects the asset stance (participatory, value-producing, or value-preserving). Calibrate the weights against a documented anchor (the framework's calibration is anchored around 2019); expose the anchor as configuration, do not bury it.

### 0.8 Regime-state layer (feeds the Optimizer)

Estimate a **distribution over 25 states**, not a point. Build the central state from leading, current, and lagging indicators across four segments: the business cycle, the investment environment, market behaviour, and market stress. Spread the central estimate across the 25 states with an explicit probability weighting, deliberately carrying weight on the tail (crisis) states so the crisis regime always has a live, non-zero probability. This distribution is the object a downstream optimiser integrates over. Provide a clean interface so the existing Portfolio Creation Program can consume it (per-regime returns feed the shortfall objective).

### 0.9 Cycles and synchronisation

Decompose and estimate the four sub-cycles, business, credit, innovation, and capital, by spectral and band-pass methods. Estimate their frequencies and relative phase. Detect windows where the cycles come into phase (constructive interference), which the framework identifies as the regime of peak fragility, and which currently points to the early 2030s (around 2032). Present this as a structural consequence of the estimated cycle phases, recomputed from data, not as a fixed date.

---

## 1. Repository layout

Create a self-contained package. Suggested structure, adapt to repo conventions:

```
macrofield/
  data/
    sources.py          # connectors: IMF, World Bank, OECD, BIS, FRED, Penn World Table, LBMA
    loaders.py          # tidy time series with provenance
    manifest.py         # records source, URL, retrieval date, units, transformations
    cache/              # cached raw pulls (checked for staleness)
  model/
    edm.py              # the three-body system, simulate(), consistency check
    quantity.py         # extended quantity equation, unsecured assets
    phases.py           # phase classifier and transition indicators
    honi.py             # capital saturation and the three sub-scores
    stock_gold.py       # three-driver ratio model
    regime.py           # 25-state estimator over four segments
    cycles.py           # spectral / band-pass cycle extraction and phase synchrony
  calibration/
    fit.py              # per-economy parameter fitting and identifiability report
    validate.py         # backtests, out-of-sample, sensitivity
  economies/
    us.yaml  cn.yaml  jp.yaml  de.yaml  fr.yaml  gb.yaml  in.yaml  eurozone.yaml  ...
  reporting/
    dashboards.py       # per-economy and comparative outputs
    charts.py           # matplotlib, book-quality rcParams optional
  cli.py                # command-line entry points
  tests/
config/
  defaults.yaml
```

Each economy YAML declares its data series, units, calibration window, and any economy-specific notes. Adding an economy is a config change, not a code change.

---

## 2. Data layer (real data only)

Map each model quantity to a documented, published series per economy, and record provenance for every value.

- `Y`  nominal and real GDP. Sources: IMF World Economic Outlook and IFS, World Bank, OECD, national statistics offices, FRED for the United States.
- `K_R`  real capital stock. Sources: IMF investment-and-capital-stock dataset, Penn World Table (perpetual-inventory capital stock), OECD. Document the vintage and method.
- `K_I`  financial capital. Assemble from total credit to the non-financial sector (BIS), plus market capitalisation of equities and debt securities outstanding, consistent with the debt-equals-capital identity in section 0.1. Document exactly which aggregates are summed and avoid double counting.
- `p_s`  gross national savings rate (IMF, World Bank).
- `S`  exogenous stimulus proxy. Candidates: general-government fiscal balance (deficit as injection), central-bank total assets change, net new credit. Make the proxy configurable per economy and record the choice.
- Auxiliary: population, CPI and asset-price indices, a broad equity total-return index, and the gold price (LBMA) for the stock-to-gold module.

Rules:

- Every loaded series carries a provenance record (source, identifier, URL, retrieval date, units, currency, any transformation). Write these to the data manifest.
- Currency and real-vs-nominal consistency is enforced; conversions are explicit and logged.
- Gaps are reported. If interpolation is unavoidable, it is explicit, method-labelled, bounded, and flagged in the output, never silent.
- Provide an offline mode that runs from cached, manifested data so results are reproducible without live network access.
- A test suite check fails the build if any placeholder, dummy, or obviously synthetic value reaches the model inputs.

---

## 3. Core model implementation

- Implement the EDM in `model/edm.py` as a function returning the derivative vector given state `(Y, K_R, K_I)`, parameters, and the stimulus path `S(t)`. Integrate with `scipy.integrate.solve_ivp` (stiff-capable method, for example Radau or BDF, since Phase IV dynamics can stiffen).
- Compute `r, α, p_p, p_b` from the definitions in 0.2. Where a definition uses a time derivative of an observed series (for example `Ẏ`), use a documented numerical derivative with smoothing, and expose the smoothing choice.
- Implement the two-body consistency check (0.3) as both a runtime assertion (with tolerance and a warning) and a unit test.
- Implement the quantity-equation diagnostics (0.4), the phase classifier (0.5), HoNI (0.6), the stock-to-gold model (0.7), the regime estimator (0.8), and the cycle analysis (0.9) as separate, individually testable modules that read the calibrated state.

---

## 4. Calibration (the point of the exercise)

For each economy, calibrate the model to its historical `(Y, K_R, K_I)` trajectory.

- Several parameters are identities from data (`r, α, p_p, p_b` per 0.2); compute them directly from the observed series and their smoothed derivatives.
- The free quantities are the savings rate path `p_s(t)` (if not taken directly from data), the stimulus path `S(t)`, and the initial state. Fit these by minimising the discrepancy between simulated and observed trajectories, using `scipy.optimize.least_squares` or maximum likelihood, over a configurable calibration window (default: the longest reliably documented span, with an option to anchor around 2019 for the stock-to-gold weights).
- Produce a calibration report per economy: fit quality (per-series residuals), parameter values with uncertainty, and an **identifiability assessment** flagging weakly identified parameters (hold those to plausible priors and stress-test them rather than over-fitting). The stimulus proxy choice and any weakly identified weight must be called out.
- Enforce the two-body consistency (0.3) as a calibration constraint, not only a post-hoc check.

---

## 5. Validation

- **Backtesting:** calibrate on an early window, simulate forward, and compare to the held-out later data. Report out-of-sample error per series and per economy.
- **Historical analogue:** the framework compares the present United States to Germany in the 1920s; provide a facility to overlay a historical episode against a current economy on the phase and unsecured-asset diagnostics, clearly labelled as an analogue, not a prediction.
- **Sensitivity:** vary the weakly identified parameters and the stimulus proxy across plausible ranges and report how phase classification, HoNI, and the stock-to-gold path move. Robustness of the qualitative conclusion (the phase, the direction of the ratio) matters more than any single number.
- **Scenario runs:** in Phase IV, run both resolution paths, debt deflation and hyperinflation, since the model says the capital-to-GDP ratio corrects through capital destruction one way or the other, and the two paths imply opposite asset outcomes. Present both, do not pick one.

---

## 6. Outputs and reporting

Per economy and comparative across the major economies:

- The three-body trajectory `(Y, K_R, K_I)` with the calibration fit shown against data.
- The phase timeline with transition boundaries and the current phase, plus distance to the next boundary.
- The unsecured-asset gap over time, with the acceleration and collapse signatures highlighted.
- The HoNI scorecard: capital saturation percentage against the 250 to 350 band, the three sub-scores, the saturation category, and comparative rankings.
- The stock-to-gold ratio path with the three driver contributions shown separately, and the currently dominant driver named.
- The 25-state regime distribution, with the tail weight visible.
- The cycle spectrum and phase-synchrony chart, with the current synchronisation window identified from the data.

Export machine-readable results (CSV and JSON) alongside charts. Every chart and table carries the calibration window, the data vintage, and an "illustrative / model-derived" label on any projected path. Charts use British spelling and no em-dashes.

Provide a short auto-generated per-economy brief in prose that states the phase, the saturation level, the dominant stock-to-gold driver, and the tail weight, in the first-person-plural analytical register, with no em-dashes and no fabricated figures. End each brief with the standard note that this is model-derived research, not investment advice.

---

## 7. Engineering standards

- Python, `numpy`, `scipy`, `pandas`, `statsmodels` (Hodrick-Prescott, Christiano-Fitzgerald band-pass, or a wavelet routine for cycle extraction), `matplotlib`. Pin dependencies.
- Config-driven (YAML per economy and a defaults file). No magic constants in code; thresholds (the phase cut-offs, the HoNI band, the calibration anchor) live in config with the values from section 0.
- Deterministic and reproducible: seed any stochastic step, cache raw data with a manifest, and make offline runs bit-reproducible.
- Tests: unit tests for each module, the two-body consistency test, limiting-case tests (for example, with `S = 0` and constant parameters the system should reduce to the analytic exponential solution the source derives), a data-integrity test that rejects synthetic inputs, and at least one end-to-end calibration-and-report test per economy on cached data.
- A CLI: `macrofield calibrate --economy us`, `macrofield report --economy us`, `macrofield compare us cn jp de`, `macrofield cycles --economy us`.
- A README that states the model provenance, the data sources with their licences, how to refresh data, how to add an economy, and the explicit disclaimer that the tool is research and decision support, not investment advice, and that projected paths are model-derived rather than forecasts.

---

## 8. Acceptance checks

Before you finish, verify:

1. The EDM matches section 0.2 exactly, and the two-body consistency test passes to tolerance.
2. Every model input traces to a real, manifested, published series; the synthetic-input test passes; no silent interpolation exists.
3. Phase classification, HoNI (with the 250 to 350 band), unsecured assets, the stock-to-gold three-driver model, the 25-state distribution, and the cycle-synchrony analysis are all implemented and individually tested.
4. Each major economy (at least the United States, China, Japan, Germany, France, the United Kingdom, India, and a Eurozone aggregate) calibrates, backtests, and reports.
5. No dated forecast is hard-coded; the 2032 synchronisation and any stock-to-gold path are recomputed from data and labelled model-derived.
6. British spelling throughout, no em-dashes anywhere, and the not-investment-advice disclaimer present in the README and every generated brief.

Deliver a change report: the modules built, the data sources wired with their identifiers, the per-economy calibration quality, the weakly identified parameters you flagged, and anything you were unsure of and left for review.

---

## 9. References (for grounding, not for reproduction)

- Steiner, N., and Bürkler, N. *Capital Saturation: A Field-Theoretic Framework for Investment and Socioeconomic Analysis*. SIM Research Institute AG. Part II (field-theoretic foundation), Chapter 12 (Health of Nations Indicator), Chapter 20 (economic state model and regime dynamics).
- "Feldtheoretische Beschreibung der Dynamiken von Volkswirtschaften" (the three-body EDM, the Lagrangian formulation, the phase model, and the extended quantity equation).
- Genreith, H. (2011). *Makroökonomische Feldtheorie* (the two-body foundation and the consistency reduction).
- Degussa Goldhandel AG. *Deriving the Value of Gold* (the three-driver stock-to-gold construction).
- SIM Research Institute AG. *Health of Nations Index*, 2025 edition (the HoNI scoring and country categories).
