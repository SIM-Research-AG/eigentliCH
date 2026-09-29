# Model specification of record

This document records the model as implemented, and where each definition comes from. It exists
because the build brief (`CLAUDE_CODE_macro_field_model_program.md`) leaves several quantities
underspecified, and because in four places the brief and the primary sources disagree. Every
resolution below is recorded with its source and, where a decision was needed, who took it.

Nothing in this document is data. All numerical inputs to the model come from the data layer with
provenance, per section 2 of the brief.

## The edition problem, read this first

Two editions of the book are on disk and **they are not the same document**:

| | Pages | Location |
| --- | --- | --- |
| Abridged | 212 | `SIM_NAS\Knowledge_Center\To_Review\capital_saturation_book.pdf` |
| **Full** | **604** | `Projects\Macro_Model\capital-saturation-en.pdf` (added 2026-07-27) |

Everything in sections 1 to 12 below was derived from the **abridged** edition, before the full one was
supplied. The full edition contains at least two Parts that do not exist in the abridged version at all:

- **Part VI, The Personal Balance Sheet** (chapters 27 to 31), which takes the apparatus down to a single
  balance sheet, states goals as regions, and gives their dynamics. Nothing in this programme addresses it.
- An extended **Part VII**, whose chapter 32 lays out the forward scenarios.

It also contains material the abridged edition only alludes to:

- **Chapter 7** presents the quantity equation as the **continuity equation** of the monetary-and-price
  field, `K · V = P · H`, with the Lagrangian `L = K · V − H · P` and the price level as the *source* of
  money flows, `grad · (K, −P) = 0`. This is the derivation `macrofield/model/derived.py` rests on, and it
  was not available when the quantity module was written. Read in full on 2026-07-27; it confirms the
  quantity module and supplies nothing that changes it. See section 13.
- **Chapter 24** gives a field-theoretic derivation of gold's value. An earlier revision of this document
  read it as contradicting `macrofield/model/stock_gold.py` in three ways; on the author's authoritative
  equation, only **one** of the three was real, and it was driver 1's sign. Chapter 24 states the model in
  conceptual variables and explicitly declines to give the functional forms, so it does not supersede the
  German source note — it is the layer above it. Details in the next section, now resolved.
- **Chapter 16** defines **six dimensions of environment analysis**: political-legal, economic, social,
  technological, ecological and monetary, after the St Gallen tradition. This is the framework's own
  organising structure for indicators, and it is the natural structure for the dashboard. Of the six, the
  economic and monetary dimensions are quantitative and map onto what this programme computes; the other
  four are qualitative and are not derivable from the three-body state.

Chapter 16's economic dimension names five sub-elements, which is a useful audit of coverage:

| Sub-element | Status here |
| --- | --- |
| Cycle position | `model/phases.py`, `model/cycles.py` |
| Capital saturation | `model/honi.py`, the saturation axis |
| Debt dynamics, public, private and external | **partial**: BIS total credit only, not decomposed |
| Productive capacity | **partial**: real-capital intensity only, no demographics or innovation |
| Real-financial relationship | `model/derived.py`, the price-divergence indicator |

**Consequence for anyone reading the rest of this document:** every resolution recorded below was reached
against the abridged edition. Where the full edition covers the same ground it is the authority, and the
resolutions should be re-checked against it rather than trusted. That applies with most force to the gold
module (chapter 24) and to anything touching the Lagrangian formulation (chapter 7).

## RESOLVED 2026-07-27: the gold module, and what the alarm above it got wrong

This section previously read as an open finding claiming that `macrofield/model/stock_gold.py` was built on a
superseded source and needed rebuilding rather than patching. **That claim was largely wrong.** The author
supplied the authoritative equation on 2026-07-27:

```
R_DG_dot = + a1 (K_I_ddot / Y) - a2 (Y_dot / K_I) - a3 ((K_R_dot + K_I_dot - Y_dot) / K_I),   a_i >= 0
```

Against it, **all three driver terms were already correct as built**. The single defect was driver one's
sign. The rebuild was therefore a one-line config correction plus this retraction, not a rebuild.

How the earlier reading went wrong is worth recording, because it is the same failure mode twice: a
conceptual equation in the book was compared term-by-term against an operational equation in the source
note, and every difference of *representation* was scored as an error of *substance*. Book equation 24.1
states the model in conceptual variables:

```
d/dt (P_G / P_S) = f1(K_I_dot) - f2(kappa_bar_R_dot) + f3(delta_C)
```

and immediately declines to give the functional forms: "The functional forms f1, f2, f3 are specified in the
broader field-theoretic apparatus; we will not develop the full mathematical specification here." The
operational equation *is* that specification. Each `f` is linear in its driver term, and the correspondences
are these:

| | Chapter 24.1 | Operational form, as built | Verdict |
| --- | --- | --- | --- |
| Ratio orientation | `P_G / P_S`, gold over stocks | gold over equities | correct as built |
| Driver 1 quantity | `K_I_dot` | `K_I_ddot / Y` | correct as built: the *impulse*, not the level |
| Driver 1 sign | **positive** | was negative | **the one real defect, now fixed** |
| Driver 2 quantity | `kappa_bar_R_dot`, the saturation-level shift | `Y_dot / K_I` | correct as built: the operational proxy |
| Driver 2 sign | negative | negative | correct as built |
| Driver 3 quantity | `delta_C`, confidence change | unsecured-asset gap derivative | correct as built, orientation reversed |
| Driver 3 sign | `+` on `delta_C` | `-` on the gap | correct as built, and consistent |
| Combination | "**not** a simple weighted sum" | a signed weighted sum | a documented simplification |

Three of those rows deserve their reasoning stated, since the earlier revision scored all three as defects:

- **Driver 1's quantity.** Chapter 24.1 writes the first derivative `K_I_dot`; the operational form uses the
  acceleration over output, `K_I_ddot / Y`. The chapter's own prose is about an *impulse* ("monetary
  expansion creates additional financial-system capital that seeks deployment"), and an impulse is the
  acceleration, not the level of growth. The second derivative is the operational reading of the chapter's
  mechanism, not a contradiction of it.
- **Driver 2's quantity.** Chapter 24.1 writes the rate of change of the real-capital saturation level
  `kappa_bar_R`, which is not an observable. `Y_dot / K_I` is its proxy: output growth relative to financial
  capital. Note also that the earlier revision transcribed this as a *second* derivative
  (`kappa_R_doubledot`); the book prints a single dot.
- **Driver 3's orientation.** These look like opposite sign conventions and are not. `delta_C` is a change in
  *confidence*; the unsecured-asset gap `K_R_dot + K_I_dot - Y_dot` is a *loss of currency backing*, which is
  the negative of a confidence change. `+f3(delta_C)` and `-a3 * gap` are therefore the same driver pointing
  the same way. This is the row the earlier revision marked "needs checking", and it checks out.

**The one real defect: driver 1's sign.** Section 5 below resolved it to negative by preferring the note's
prose over its transcribed algebra. That resolution is retracted. Chapter 24.2 states the mechanism
directly: "Gold's price responds *positively* to liquidity impulses in the financial system... as `K_I`
grows, a portion of the growth seeks expression in gold positions, *supporting* gold's price." The note's
algebra was right and its prose was the error. The deeper mistake in the earlier reasoning was treating the
credit impulse as a *confidence* reading, which double-counted driver three: confidence is driver three's
job, and driver one is liquidity. `config/defaults.yaml` now sets
`stock_gold.driver_signs.liquidity_credit_impulse: 1`, and `SOURCE_DRIVER_SIGNS` in the module holds the
`+, -, -` triple so a config edit that reverses a driver shows up as a divergence from a named constant.

**On the combination.** Chapter 24 says the drivers' combination "is not a simple weighted sum; it involves
the specific interaction of the drivers under the conditions prevailing at any given time." The signed
weighted sum is nonetheless what the framework calibrates, and it is what the author's equation states. The
conditional interaction enters through the dominant-driver stance selection and the quantity-equation
validity check rather than through a cross term. That is recorded in the module as a documented
simplification, which is the honest status: the sentence is not implemented, and a cross term would need a
source before one could be invented.

**A validation target chapter 24.3.2 supplies, and its orientation.** For Weimar Germany the ratio falls
from approximately **20 in 1916 to near zero by 1923**, and the chapter states the three-driver model's
projections track the real data closely over that episode.

The orientation matters and the earlier revision of this document had it backwards, calling it the
gold-to-equity ratio. The chapter's own gloss identifies it: "The ratio falls from approximately 20 in 1916
to nearly zero by 1923: **a near-total destruction of equity value relative to gold.**" Equity relative to
gold is the *stock-to-gold* ratio, the reciprocal of the modelled `R_DG`. The chapter's forward statement
carries the same orientation, that the strategic implication is "increasing gold allocation as the projected
ratio decline unfolds" — a declining ratio calls for *more* gold only if the ratio is stocks over gold.

The German series are not on disk, so the target is recorded in `config/defaults.yaml` under
`validation.analogues.germany_1920s.target` with `data_available: false`, and it is a declared target rather
than a running backtest. Fabricating the episode to have something to pass would be worse than not running
it. What `tests/test_stock_gold.py` does assert without the data is that the orientation is recorded the
right way round, that an unrun target cannot read as a passing one, and that the implementation reproduces
the episode's shape from its own mechanism: driver three dominant, gold running away, and the stock-to-gold
ratio collapsing from 20 towards zero.

**One further usable figure, from chapter 24.6.** The chapter gives gold's regime-conditional return profile
against the same five regimes section 6 uses, "drawing on the historical record and the field-theoretic
derivation": Crisis +20 to +40 per cent annualised, Contraction +8 to +15, Stagnation +2 to +8, Expansion −3
to +5, Boom −5 to +5. It notes the profile is "precisely the inverse of equities". This is not implemented,
because the programme does not currently carry a role-return matrix, but it is the only regime-conditional
return profile the book states numerically and it is what Part VI's section 30.5 expects to inherit. See
section 14.

**What is still open.** Supplying a German 1916 to 1923 equity index and a Reichsmark gold price would turn
the declared target into a real backtest, and it is the best available test of the weights. Chapter 24 also
attributes the underlying series to SIM Research Institute, *Deriving the Value of Gold*, which is not among
the sources consulted below.

Other figures from chapter 24 worth keeping, since they bear on the derived-indicator work:

- Two inflation regimes. 1820 to 1920, commodity money: total price increase 215 per cent, but about
  **0.47 per cent a year** excluding the post-1914 spike, that is essentially price stability over a century.
  1920 to 2020, monetary money: about 1100 per cent total, **2.6 per cent a year**, exponential rather than
  mean-reverting.
- Gold across the same regimes: **0.52 per cent a year** to 1920 while it was the monetary base, then over
  4700 per cent from 1970 to 2020, about **4 per cent a year**, nearly double CPI.
- The regime transition is dated between 1914 (Federal Reserve founded, gold standard suspended) and 1971
  (dollar link severed). This matters for `model/derived.py`: an inflation series spanning the transition
  spans two structurally different regimes and should not be treated as one.

## Sources consulted

| Key | Document | Location |
| --- | --- | --- |
| BOOK | Steiner, N., and Bürkler, N. *Capital Saturation: A Field-Theoretic Framework for Investment and Socioeconomic Analysis*. SIM Research Institute AG. | `SIM_NAS\Knowledge_Center\To_Review\capital_saturation_book.pdf` |
| GENREITH | Genreith, H. *Makroökonomische Feldtheorie* (two-body foundation) | `SIM_NAS\Knowledge_Center\Maths\Genreith.pdf` |
| NOTE | Bürkler, N. "Feldtheoretische Beschreibung der Dynamiken von Volkswirtschaften", internal publication, SIM Research Institute AG, 2020, as cited and applied in "Treiber des Goldwertes" (with Degussa Goldhandel AG) | `SIM_NAS\Clients\1-Current\Degussa\Treiber_des_Goldwertes.docx` |
| HONI-MANUAL | *Health of Nations Index Scoring Model*, SIM Research Institute AG, July 2020 | `SIM_NAS\Knowledge_Center\In progress\Health of Nations 2023\Background\HoNI Manual.pdf` |
| HONI-METHOD | HoNI methodology workbook (83 indicators, scoring bands, per-country raw data, output) | `...\Background\HoNI_Methodology.xlsx` |
| TAA | `Team_TAA_Risk_Signal.m`, the operational 25-state market risk signal generator | `SIM_NAS\SIM_Tech\Master_Controller\Team_TAA_Risk_Signal.m` |
| PCP | Portfolio Creation Program, the downstream consumer, and its live regime input | `SIM_NAS\SIM_Tech\Master_Controller\convictions.json`, `PCP_Backtester_Dev.m`, `MeanVarianceOptimizer.m` |

## 1. State and equations of motion

Implemented verbatim from brief section 0.2, which matches BOOK chapters 7.5 to 8.1 (the extension
from Genreith's two equations to three).

```
Ẏ   = (p_b − p_s) Y + K̇_R − p_p K_R + S
K̇_R = (1 − α) p_s Y + p_p K_R + r K_I
K̇_I = α p_s Y + p_p K_I − r K_I + S
```

## 2. The two-body reduction is exact only for zero stimulus

Brief section 0.3 requires that the simulated `K̇_R + K̇_I` equal `p_s Y + p_p K` to numerical
tolerance at every step. Summing the two capital equations above gives, algebraically and exactly:

```
K̇_R + K̇_I = p_s Y + p_p K + S
```

The `α p_s Y` and `(1 − α) p_s Y` terms sum to `p_s Y`, the two `p_p` terms sum to `p_p K`, the
`r K_I` terms cancel, and the stimulus `S` survives because it enters `K̇_I` without an offsetting
term elsewhere in the capital block.

Consequently the reduction as written in the brief holds only where `S = 0`. This is a property of
the model, not a numerical tolerance question, and a test written as the brief states it would fail
by exactly `S` on any run with a live stimulus path. We therefore implement two checks:

1. **Runtime identity** (`edm.two_body_residual`): the residual of
   `K̇_R + K̇_I − (p_s Y + p_p K + S)`. This is zero by construction and detects implementation
   error or integrator drift. Asserted every step with a configurable tolerance, warning on breach.
2. **Strict Genreith reduction** (unit test): with `S = 0` the residual against Genreith's
   unmodified `K̇ = p_s Y + p_p K` must vanish. This is the consistency test the brief intends and
   it is the form that recovers GENREITH exactly.

Left for review: whether the intended reading is instead that Genreith's two-body equation should
carry the stimulus term, in which case the reduction is `K̇ = p_s Y + p_p K + S` and check 1 is the
only check needed.

## 3. Capital saturation threshold

BOOK section 8.5 derives the threshold as the total-capital-to-GDP ratio at which the determinant of
the Jacobian vanishes, a saddle-node bifurcation (full calculation in BOOK Appendix A.3). The result
is a range of 2.5 to 3.5, that is 250 to 350 percent of GDP. This is the same band the brief gives
for HoNI in section 0.6 and it is a derived quantity, not a stylised fact.

It lives in `config/defaults.yaml` as a derived threshold with its range, not as a magic constant.

## 4. Health of Nations Indicator

### Which HoNI is current

Three generations of HoNI exist on the NAS, and they are not variants of one model:

| Vintage | Artefact | Structure |
| --- | --- | --- |
| July 2020 | HONI-MANUAL | Scoring band types and the IFS formula chains |
| 2022-01-16 | HONI-METHOD | 83 indicators in four categories, each split into Level and Trend |
| **2026-04-27** | **HONI-2026** (`HoNI_Export 11-25.xlsx`) | **15 indicators in three groups of five, emitting exactly the three sub-indices the brief specifies** |

HONI-2026 is the current model and is authoritative for the indicator set. It is also the only one
whose structure matches the brief and book chapter 12: three sub-indices named Financial, International
and Real, which its own chart blocks label "Financial Economy", "International Resilience" and
"Real Economy". Its 15 indicators are `Budget_Balance`, `Monetary_Supply`, `Gov_Debt`, `Real_10y`,
`Market_Cap`, `Extdebt_afford`, `Extdebt_expo`, `Terms_Trade`, `Import_Res`, `Corruptopm` (misspelled
in the source), `Cons_Power`, `Pop_Growth`, `GDP_Growth_Capita`, `Depend_Cons`, `Labour_Force`, as
annual series from 2004 to 2024 for 16 economies.

The dimension mapping is inferred from the export's column ordering: the 15 indicators occupy three
contiguous blocks of five, aligned with the three sub-index columns. Recorded in
`config/honi_indicators.yaml` so it can be corrected in one place. **Left for review.**

The 2022 workbook is retained only as a band reference in `config/honi_bands.yaml`, and its extraction
found real defects in it, which is a further reason not to treat it as current:

- **Gold Reserves growth**: the score-4 interval is `[-1.0, -4.0]`, inverted, which opens two gaps so
  that no value between -4 and -1 can be scored at all.
- **Food Security (food import share)**: scores 2 and 3 overlap (`[8, 15]` and `[10, 15]`), so a value
  of 12 could take either score.
- Four indicators where the prose interval label contradicts the numeric cells (non-financial
  corporate debt, both capital-market size indicators, and inflation). The cells form a
  self-consistent contiguous chain and the labels do not, so the cells are used and each disagreement
  is recorded against the indicator.
- The sheet carries a second, older copy of the table below its notes block. It is not extracted, and
  its presence is reported.

### The composite is panel-relative in the current export

Every one of HONI-2026's 21 years contains exactly one score of 1.0 and exactly one of 5.0 across its
16 economies (2004: India 1.0, Switzerland 5.0; 2024: USA 1.0, Vietnam 5.0). That is the signature of
a cross-sectional min-max rescaling onto the 1 to 5 axis within each year. The composite is also not
the mean of the three sub-indices: for the USA in 2004 the sub-indices are 1.667, 2.389 and 3.320,
whose mean is 2.459, against a published composite of 2.901.

The consequences are structural, not cosmetic:

- The score is a relative ranking, so it is **not comparable across years**.
- It moves when panel membership changes, without any economy having changed.
- One economy always reads as perfectly healthy, even in a year when every economy in the panel is
  saturated.
- The four-stage taxonomy cannot be applied to it, because a rescaled score has no absolute level to
  band against.

Both readings are therefore implemented and selected by `honi.aggregation.strategy`:

- `absolute` (the default) takes a weighted mean on the fixed 1 to 5 axis. Comparable across years
  and panels, and required by the four-stage taxonomy and by any timeline reading.
- `panel_min_max` reproduces the export. The four-stage category is withheld under it rather than
  emitted meaninglessly.

**Left for review:** whether the panel rescaling is intended as the published methodology or is an
artefact of the export, and whether the direction survives it. Note that under "1 is healthiest" the
export puts the USA at exactly 1.0 in 2024, that is healthiest of the 16 economies, which is difficult
to reconcile with the framework's thesis of United States late saturation.

### Scale and direction

Brief section 0.6 specifies a 1.0 to 5.0 axis but does not state its direction. The direction is
**higher is healthier**, matching HONI-2026 and BOOK section 12.2, whose 0 to 100 axis also runs
higher-is-healthier.

The direction changed between vintages, and the headers cannot be trusted over the data. HONI-METHOD
(2022) states **"Key: 1 most healthy; 5 least healthy"** and its bands genuinely follow that: saving
rates take score level 1 at [40, 100], non-performing loans take score level 1 at [0, 2]. HONI-2026
runs the other way. This was established from HONI-2026's own values rather than from a header:

- USA `Gov_Debt` raw rises from 1.0875 to 1.2232 of GDP between 2019 and 2024 while its score falls
  from 1.844 to 1.000. Across the panel, `corr(raw, score) = -0.888`.
- Japan, which carries the heaviest government debt of the panel at roughly 250 percent of GDP, sits
  at `Gov_Debt = 1.000` throughout.
- 13 of the 15 indicators align with higher-is-healthier: government debt, financialised market
  capitalisation and external exposure all push towards 1, while labour-force participation
  (`corr +0.963`), GDP growth per capita (`+0.940`) and institutional quality (`+0.996`) push towards 5.

Under this direction HONI-2026's USA composite of 1.000 in 2024 reads as **least healthy of the 16
economies**, which is what the framework's thesis of United States late saturation predicts, with Japan
next at 1.245. Under the opposite direction the United States would read as the healthiest economy in
the panel, which the author identified as wrong on sight. An earlier revision of this document asserted
the opposite direction on the strength of the 2022 header; that was wrong and every score, band and
ranking has been corrected.

A band table declares its own native direction and `honi.to_canonical` converts into the canonical
one, so the two conventions can never be mixed silently. `load_bands` *requires* the declaration and
refuses to guess. `tests/test_honi_export_direction.py` validates the convention against the published
export and skips when the NAS is unreachable.

Every emitted score, chart axis and brief carries the direction label explicitly.

### Four-stage taxonomy on the 1 to 5 axis

BOOK section 12.3 gives the four stages against its 0 to 100 axis: Foundation 70 to 100, Build-up 50
to 70, Optimisation 30 to 50, Saturation 0 to 30. Because both axes run higher-is-healthier, the
mapping is the direct linear one, `score_1to5 = 1 + 4 * score_0to100 / 100`, which preserves the
ordering:

| Stage | BOOK band (0 to 100) | Implemented band (1 to 5, 5 healthiest) |
| --- | --- | --- |
| Saturation | 0 to 30 | 1.0 to 2.2 |
| Optimisation | 30 to 50 | 2.2 to 3.0 |
| Build-up | 50 to 70 | 3.0 to 3.8 |
| Foundation | 70 to 100 | 3.8 to 5.0 |

These bands are config, not constants in code. They are a derived mapping, and BOOK 12.3 itself
calls the ranges guidelines rather than sharp boundaries.

### Indicator scoring

From HONI-MANUAL and the band table in HONI-METHOD. Each indicator is scored 1 to 5 by the band its
value falls into. Three band types:

- **Positive**: higher raw value is healthier.
- **Negative**: lower raw value is healthier.
- **Union**: an ideal interval exists, and deviation in either direction worsens the score. The band
  table carries `Lower`, `Upper-lower union`, `Upper` and `Upper-upper union` columns per score level
  to express the two-sided bands. HONI-MANUAL names the variants encountered in practice
  (`Union3`, `Union4`, `Union23`, `Union234`, `Union35`, `Union2345`) according to which score levels
  carry double bands.

The band table is extracted from HONI-METHOD into `config/honi_bands.yaml` by
`tools/extract_honi_bands.py` rather than transcribed by hand, so it is reproducible and its
provenance is recorded.

### Dimensions

HONI-METHOD organises 83 indicators into four categories, each split into Level and Trend:
Financial Economy, Gesellschaftssystem (social system), Real Economy, International Vulnerability.

Brief section 0.6 and BOOK section 12.2 both specify three sub-indices: Financial, International
(resilience), and Real. BOOK 12.2's Real dimension explicitly includes demographic structure, which
is where HONI-METHOD's social indicators sit. We therefore map the four operational categories onto
the three specified dimensions in `config/honi_dimensions.yaml`, with every indicator's assignment
visible and editable. Default mapping:

- **Financial**: Financial Economy (Level and Trend), plus the monetary and fiscal members of
  Gesellschaftssystem (inflation, fiscal balance, M0 growth, gold reserves growth).
- **Real**: Real Economy (Level and Trend), plus the demographic and structural members of
  Gesellschaftssystem (working-age share, population growth, foreigner demographics, food security,
  healthcare costs), per BOOK 12.2.
- **International**: International Vulnerability (Level and Trend).

Left for review: the assignment of the Gesellschaftssystem indicators. It is a judgement call, it is
config, and it moves the sub-scores.

### Coverage

Many of the 83 indicators are sourced in HONI-METHOD from CEIC, which is authenticated and paid, and
several others (housing market size, mutual fund and pension assets, ETF flows, hot-money flows) have
no keyless published equivalent. Under the brief's rule that missing data is flagged and never
invented, the scorer:

- scores only indicators whose data actually loaded,
- reports coverage per dimension as a count and a share,
- refuses to emit a composite where coverage falls below a configurable floor, rather than emitting a
  composite computed from a thin subset,
- records which indicators were unavailable, per economy, in the output.

## 5. Stock-to-gold ratio, SWITCHED OFF 2026-07-28

**The model is switched off and is not part of the current output.** `stock_gold.enabled` is `false`, the
cockpit removes its panel rather than rendering one that fails, and its endpoint refuses with that reason.

It is switched off rather than deleted, and the distinction is deliberate. The equation was only settled on
2026-07-27, after a sign error had been carried through the config, the module docstring, this document and
the tests; deleting the module would throw that resolution away along with the Weimar validation target now
recorded under `validation.analogues`. Everything below therefore still holds, the module and its tests are
retained and correct, and setting `stock_gold.enabled` to `true` brings it back with no other change.

One dependency to keep in view: section 14 records that Part VI's section 30.5 expects the role returns and
covariances of the personal problem to come from "the three-driver construction of Chapter 24 mapped into
role space". If Part VI is ever built, this model is upstream of it.

The rest of this section is retained as the record of what the model is.

### The equation

NOTE gives the differential equation in three drivers arising from the three-body model. The
transcribed form is:

```
Ṙ_DG = α₁ (K̈_I / Y) − α₂ (Ẏ / K_I) − α₃ ((K̇_R + K̇_I − Ẏ) / K_I)
```

NOTE describes `R_DG` as the ratio of gold to an equity index, and describes the drivers as:

1. Liquidity impulse from credit dynamics. The gold-to-equity ratio moves reciprocally to system
   confidence, and confidence is approximated by the credit impulse. NOTE approximates the credit
   cycle by the acceleration of financial capital relative to productivity, which is the
   `K̈_I / Y` term.
2. Innovation-driven growth. Firms are value-creating, so under normal growth equities outperform
   gold over time.
3. Currency stability from the capital cycle, a derivative of the quantity equation. Above a
   threshold ratio of capital to output the quantity equation loses validity and currency stability
   is lost. This driver dominates in a hyperinflationary phase, where gold outperforms equities.
   Note that its numerator is the time derivative of the unsecured-asset gap of section 0.4.

**Sign resolution, settled 2026-07-27.** The signs are `+, −, −`. The author supplied the equation
directly and it is the transcribed algebra above, unchanged:

```
Ṙ_DG = + α₁ (K̈_I / Y) − α₂ (Ẏ / K_I) − α₃ ((K̇_R + K̇_I − Ẏ) / K_I),   α_i ≥ 0
```

An earlier revision of this section reversed driver 1 to a negative sign, on the argument that a
positive credit impulse means rising confidence and so must push a gold-over-equities ratio down. That
resolution is **retracted**, and the argument for it was wrong in a specific way worth keeping: it
treated the credit impulse as a reading of *confidence*, which is driver 3's quantity. Driver 1 is
liquidity. Chapter 24.2 states the mechanism directly, that gold "responds positively to liquidity
impulses in the financial system", so both the algebra and the book agree and it was NOTE's prose that
erred. See the resolved section at the top of this document for the full reconciliation against
chapter 24.

Driver 3 remains coherent as written for a gold-over-equities ratio, because the unsecured-asset
derivative turns negative in Phase IV and its negative coefficient then contributes positively to
gold. Chapter 24.1's `+f3(ΔC)` is the same driver: `ΔC` is a confidence change and the unsecured-asset
gap is its negative, so the two sign conventions agree once the quantities are oriented.

The brief asks for the stock-to-gold ratio, which is the reciprocal of the modelled quantity. We
model `R_DG` (gold over equities) as the primitive because that is the form the source derives, and
report the stock-to-gold ratio as its reciprocal, labelled in both directions on every output. Chapter
24.3.2's Weimar figure is stated in the *stock-to-gold* direction, so it is compared against the
reciprocal and not against the primitive.

The weights `α₁, α₂, α₃` are calibrated, with the anchor exposed in config (the framework's
calibration is anchored around 2019). The dominant driver at each date selects the asset stance:
driver 1 dominant implies participatory, driver 2 value-producing, driver 3 value-preserving.

**Not implemented as constants:** NOTE's dated conclusions (a 2022 ratio peak and a 2025 to 2028
hyperinflationary window) illustrate the method at its 2020 vintage. Per brief section 0.14 they are
excluded from the code and from config. Any dated statement the programme makes is recomputed.

## 6. Regime layer, 25 states

Three taxonomies exist across the sources:

- BOOK section 20.2 specifies five regimes: Crisis, Contraction, Stagnation, Expansion, Boom.
- BOOK section 20.3 extends to a seventeen-state classification for sensitivity analysis (3 Crisis
  variants, 3 Contraction, 3 Stagnation, 4 Expansion, 4 Boom).
- TAA implements a 25-bin state axis, and PCP's `convictions.json` holds live 25-length distributions
  per economy (CH, EU, US).

Brief section 0.8 specifies 25 states, which matches the operational implementation and the live
interface the downstream optimiser consumes. The 25-bin axis is therefore the object we produce, with
the BOOK five-regime and seventeen-state taxonomies available as aggregations of it.

### Construction

The axis is ordered **1 cautious to 25 aggressive**. Each of the four segments supplies a probability
vector over the **five regimes** of BOOK section 20.2, declared in cautious-to-aggressive order so no
reversal step is needed, and each regime's weight is spread over a contiguous run of bins by a kernel:

| Regime | Kernel | Bins |
| --- | --- | --- |
| Crisis | `CRISIS_KERNEL` (10 bins, piled at the cautious end) | 1 to 10 |
| Contraction | symmetric (14 bins) | 2 to 15 |
| Stagnation | symmetric (14 bins) | 6 to 19 |
| Expansion | symmetric (14 bins) | 11 to 24 |
| Boom | reverse of `CRISIS_KERNEL` (10 bins) | 16 to 25 |

The placements space the five kernel centres roughly evenly across the axis, with the two extremes
piled at their own ends. A test asserts that the centres increase monotonically across the regimes, so
"cautious to aggressive" is a property of the construction rather than a label on it.

**This supersedes a four-scenario version**, `[Boom, Recovery, Contraction, Bust]`, taken from TAA and
implemented in an earlier revision. The author directed the change on 2026-07-27. The four-scenario
vocabulary never matched the framework's own taxonomy, which forced the five-regime output to be
produced by aggregating bins rather than by naming what the segments had actually assessed. With five,
the segment assessment and the regime report share one vocabulary. "Recovery" is a transition rather
than a regime and gives way to BOOK's Stagnation and Expansion.

One consequence: the defect in TAA where the Recovery weight was never applied is now moot, since that
scenario no longer exists. The five-regime implementation uses all five weights, and a parametrised test
asserts that removing any one of them changes the distribution.

with

```
Binom      = [1.5, 2, 4.9, 6, 8.9, 13, 13.7, 13.7, 12, 8.9, 6, 4.9, 2, 1.5] / 100
Binom_Bust = [14.4, 21.9, 13.7, 13.7, 12, 8.9, 6, 4.9, 2, 1.5] / 100
Binom_Boom = reverse(Binom_Bust)
```

`Binom_Bust` is piled towards the cautious end, which is what keeps live weight on the crisis tail as
the brief requires. It is `Binom` with its left tail folded into two bins: `14.4 + 21.9 = 36.3`, which
is exactly the sum of the first six entries of `Binom`. The kernels are config, not constants in code,
and every kernel is normalised before use.

Two defects in the source kernel values, both left uncorrected so that the intended construction is
reproduced rather than guessed at, and both harmless because of the normalisation:

1. Both kernels sum to **99.0, not 100.0**.
2. `Binom` is described as binomial and is very nearly symmetric, but one mirror pair carries
   **13.0 against 12.0**.

These are almost certainly a single typo rather than two independent quirks: substituting 13.0 for the
12.0 makes the kernel exactly symmetric *and* makes it sum to exactly 100.0, and the same substitution
is consistent with how `Binom_Bust` folds this kernel's left tail. The corrected sequence is available
as `SYMMETRIC_KERNEL_CORRECTED`. **Adopted** on the author's decision, 2026-08-02 (DECISIONS.md M56):
shipped config sets `regime.kernels.symmetric` to the corrected sequence, so this is what runs. The
uncorrected original stays in code as `SYMMETRIC_KERNEL` for comparison only.

One consequence is still open. `CRISIS_KERNEL` is folded from the same transcribed source, carries the
same `12.0`, and sums to the same 99.0 — and was not corrected. The argument for the substitution was
that one changed value fixed both the asymmetry and the sum; that argument does not transfer unchanged,
because folding a tail into two bins can legitimately break symmetry. But the shared `12.0` is either a
transcription error in both places or in neither, and only one has been ruled on.

The four segments are those the brief names: the business cycle, the investment environment, market
behaviour, and market stress. Each produces its `[Crisis, Contraction, Stagnation, Expansion, Boom]`
assessment from leading, current and lagging indicators. The segment count is configurable; TAA runs
five assessors. Note that the four segments and the five scenarios are different axes — a segment is a
question asked of the data, a scenario is one of the answers, and the counts coinciding at five for the
TAA assessors is arithmetic accident rather than correspondence.

The 25-bin distribution is the interface the PCP consumes, matching the shape in
`convictions.json`.

## 7. Cycles

NOTE gives the cycle hierarchy from its frequency analysis of the eight-century real-return series,
corroborated in BOOK chapter 9 and chapter 6.4:

| Cycle | Period |
| --- | --- |
| Fundamental pulse | 3.6 years |
| Business cycle | 7 years |
| Credit cycle | 18 years (5 pulses) |
| Innovation cycle | 36 years nominal (2 credit cycles), observed as a 40 to 54 year band |
| Capital cycle | 90 years (5 credit cycles) |
| Hegemonic succession | 130 years (7 to 8 credit cycles) |

NOTE also records that state intervention synchronises the credit cycle with the capital cycle, which
raises crisis severity, and BOOK section 9.8 treats synchronisation and crisis severity directly.

### The two long cycles are anchored, not estimated. Directed 2026-07-28

Only the **business and credit** cycles are band-passed. `cycles.decompose` is `[business, credit]`.

The reason is arithmetic. A cycle needs a sample spanning about two of its periods to be identifiable, so
the innovation cycle needs roughly 94 years of annual data and the capital cycle roughly 180, against the 50
to 60 a national-accounts series provides. Before this change both were correctly reported as
unidentifiable, and the consequence was that they were **excluded from the synchrony analysis entirely**: the
United States run reported `excluded: ['capital', 'innovation']`, so the "synchronisation window" was a
statement about the business and credit cycles alone. That is a window over the two cycles the framework
cares least about.

Both are therefore anchored from author-supplied structure, in `cycles.anchored`:

| Cycle | Anchor | Period | Phase convention |
| --- | --- | --- | --- |
| Capital | saturation crossing **3.5** is **90 years into** the cycle | 90 years | phase 0 at the crossing |
| Innovation | a **low in 2032**, identically for every economy | 47 years | phase pi in 2032 |

- **The capital anchor reuses the existing 3.5.** It is the same number as
  `phases.optimisation_saturation_ceiling` and the upper bound of `saturation.balanced_band`, so the anchor
  and the phase boundary are one quantity rather than two that can drift apart.
- **The crossing is interpolated within the year**, since snapping to an annual observation would quantise
  the cycle position for no reason. Where the axis crosses several times the **last** crossing is used and
  the others are reported, because the position is a statement about the current cycle.
- **An economy that never reaches 3.5 is not anchored.** Germany at 2.76 and India at 2.50 return
  `anchored: false` with the peak they did reach, rather than an extrapolated position. Placing a 90-year
  cycle from a 50-year sample without the anchor is precisely what the anchoring exists to avoid.
- **The innovation cycle is the same in every economy**, because it is a global technological cycle rather
  than a national one.
- **Amplitudes are normalised to one.** The anchor says where in the cycle the economy sits, not how large
  the cycle is, and scaling to the data would invent an amplitude. This is why the dashboard draws the
  anchored cycles on their own chart: a band-passed component is a deviation in a growth rate of order 0.02
  and an anchored one runs to 1, so sharing an axis would flatten the former to nothing.
- **The phase convention matches the band-pass one**, phase 0 at the peak of the cycle's own variable, so an
  anchored phase and an estimated one are comparable. For capital that puts phase 0 at the 3.5 crossing,
  since that is where saturation peaks and the reordering occurs. A test asserts the two conventions agree,
  because if they did not, every synchrony verdict involving a long cycle would be wrong.

**Left for review: the innovation period.** The author supplied the trough and not the period. It is set to
**47.0**, the midpoint of the observed 40 to 54 band, which is what `bands_from_config` already used as
innovation's prior. The nominal alternative is 36.0, two credit cycles. Changing it moves the phase and
therefore the synchronisation window.

### This reverses the no-dates rule, and how

`macrofield/model/cycles.py` previously carried a docstring stating that "the synchronisation window is
computed, never asserted... so no date appears anywhere in this module or in config", and
`tests/test_cycles.py` asserted that no year between 2030 and 2033 appeared in the cycles section. Both are
gone, and the replacement is narrower rather than absent.

The rule that mattered was never "no digits that look like a year". It was that **the programme must not
encode a dated conclusion of its own and present it as computed**. An anchor the author supplies is an
input, with exactly the standing of `stock_gold.calibration_anchor_year: 2019`, which section 5 already
treats as "the one date that is legitimately configuration".

So the test now asserts three narrower things: every date in the cycles section sits under `anchored`, every
anchor carries a `source`, and moving an anchored phase still moves the detected window. The last is the
substantive one, because it is what distinguishes a supplied input from an asserted conclusion: the anchors
supply two phases, they do not supply the window, and the window remains a computation over all four.

**What this changes in output.** The United States now reports all four cycles as usable. Its capital cycle
is anchored on a 3.5 crossing in **2013.5**, which places it **100.5 years into a 90-year cycle**, that is
about 11 years past the reordering point, and its innovation cycle is 8 years short of the 2032 low. Those
two readings are the point of the change, and neither was available while the long cycles were reported as
unidentifiable.

The remaining priors are still priors for the two band-passed cycles, whose estimated frequencies and phases
are recomputed from data per economy.

### A limit worth stating

`detect_synchrony` runs over the **observed** window only, so a window in the 2030s cannot be detected: the
anchored cycles could be evaluated at any future date, but the band-passed short cycles cannot be
extrapolated, and a synchrony verdict computed from two extrapolated phases and two supplied ones would be
mostly assumption. The dashboard therefore reports the distance to each anchor instead, which is where the
2030s reading actually comes from.

## 8. Real capital, and the valuation trap

`K_R` comes from **Penn World Table 10.01** (DOI 10.34894/QT5BCC), a single keyless spreadsheet covering
183 countries from 1950 to 2019. It is the only source that covers every economy in the panel, including
China and India, with one consistent perpetual-inventory method, which is what makes cross-economy
capital ratios comparable at all. The **Maddison Project Database** (DOI 10.34894/INZBF2) is wired
alongside it for the long historical series the cycle hierarchy needs; it carries no capital stock.

PWT publishes the depreciation rate `delta` per country and per year. That is strictly better than a
configured prior, because it is the rate the source itself used to build the stock being extended, so
`loaders.resolve_depreciation_rate` prefers it, falls back to the last published value carried forward,
and reaches the configured prior only as a last resort. Observed 2019 values: United States 0.046,
Japan 0.0442, China 0.0523, Germany 0.0384, France 0.0379, United Kingdom 0.0397, India 0.0579.

### The scale problem, confirmed against data

PWT `cn / cgdpo` for 2019: United States 3.36, India 3.73, Germany 4.59, United Kingdom 4.72, Japan
4.75, China 4.94, France 5.66. Every one is far above the `K_R/Y < 1` threshold of brief section 0.5,
which confirms the resolution in section 3 empirically rather than by argument. Note also that these run
above BOOK section 10.3's stated 2.5 to 3.5 range, so the book's own figure understates what its
nominated source reports.

### PWT cannot extend itself

Every PWT column ends in 2019, including its investment share `csh_i`. Extending therefore requires an
external investment series, and that is where the trap lies.

**The trap.** PWT is converted at purchasing-power parities; World Bank dollar series are converted at
market exchange rates. Both are real US dollar series, so a currency check and a nominal-versus-real
check both pass, yet a ratio built from one of each is meaningless: PPP and market conversions differ by
well over a factor of two for some economies. A `Valuation` field was added to the provenance record for
exactly this, it is **required** on any series declaring a currency, and `check_consistency` refuses a
mixture. A test asserts that the offending pair is identical on every other axis, which is why the field
was needed.

### The ratio-space extension is the preferred route

Rather than manage the valuation problem, `loaders.extend_capital_ratio_by_perpetual_inventory` removes
it. Dividing the recursion through by output gives

```
k(t) = (1 - delta) k(t-1) / (1 + g(t)) + i(t),   k = K_R / Y,  i = I / Y
```

Every input is unitless, so the PPP against market-rate distinction cannot arise, the published ratio
and the extension sit on the same footing by construction, and nothing needs a PPP conversion factor
with its own vintage and price base. The ratio is also what the phase classifier and HoNI actually
consume, so no level ever has to be reconstructed. The currency-level extension is retained for callers
who genuinely have a consistent stock and flow pair.

Verified live: United States `K_R/Y` extends from a published 3.36 (2019) to 3.27 (2024), Germany 4.59
to 4.75, France 5.66 to 5.46, United Kingdom 4.72 to 4.48, India 3.73 to 3.27. All extended values are
marked `DERIVED` and the integrity check refuses them unless a caller opts in.

**Left for review:** two economies (China and Japan) returned World Bank HTTP 400 for the investment
share during the live run, so their extension could not complete. The connector reports the failing URL
rather than skipping silently. This looks like throttling after a burst of requests rather than a missing
indicator, and a retry with backoff is the likely fix.

## 9. The model forecasts

Recorded because an earlier revision of this document and of the training material said the opposite,
and the author corrected it on 2026-07-27.

**The model produces forecasts.** Anticipating where an economy sits in the capital cycle, and how that
position resolves, is the purpose of the apparatus. Describing the output as "not a forecast" is false
modesty and it makes the framework pointless.

What the output is not is a **dated point prediction**. The distinction is operational:

- A forecast from this model is conditional and structural. It states that an economy at a given
  saturation, with given cycle phases, resolves in one of a small number of ways, and it recomputes that
  from the current data vintage on every run.
- The synchronisation window is a genuine prediction of when constructive interference across the
  sub-cycles puts the system at peak fragility. It moves as the vintage moves.
- Phase IV admits two resolutions, debt deflation and hyperinflation, and the model does not choose
  between them. Both are run and both are presented. That is a real limit on the forecast, not a
  disclaimer about whether one is being made.

**What this does not change.** Two constraints stand, and they are the ones brief section 0.14 is
actually about:

1. No dated forecast is hard-coded anywhere in the programme or in config. Tests assert that the legacy
   dates from the older gold notes do not appear. Any date a briefing quotes came from a recomputation
   and must be reproducible from the vintage recorded beside it.
2. The not-investment-advice disclaimer remains on the README and on every generated brief, per brief
   sections 7 and 8.6. Being a forecast and being investment advice are different things.

**Left for review:** brief section 0.14 is worded "Model outputs are model-derived, not point
forecasts", and section 6 requires projected paths to be labelled "illustrative or model-derived". The
label is retained on projected paths, since it correctly signals that a path is a model consequence
rather than an observation. But the brief's wording invites the reading this section corrects, and the
author may want to amend it.

## 10. What counts as a successful calibration

Directed by the author on 2026-07-27: **the model does not have to fit perfectly, but it must get the
trend right, and especially the turning points.** This governs how every result is judged and it
supersedes an earlier framing that treated the level residual as the headline.

The criteria, in priority order, implemented in `calibration/validate.py`:

1. **Turning points.** Does the model turn when the economy turns, and how many periods early or late?
   `score_turning_points` matches simulated turns against observed ones by direction and proximity, and
   reports the hit rate, the misses, the spurious turns, and the signed lead or lag. Turning early is
   the useful direction, so the sign convention makes a lead positive. Matching is greedy on proximity
   and each simulated turn is consumed once, so a single spike cannot be credited with finding several
   nearby observed turns.
2. **Direction.** Share of periods in which the simulated path moves the same way as the observed one.
   A coin toss scores 0.5, so anything at or below that carries no directional information whatever the
   level residual says.
3. **Trend agreement.** Correlation of *growth rates*. Levels of two exponentially growing series
   correlate above 0.95 almost regardless of their dynamics, so a level correlation flatters the model
   badly and is not reported as though it meant something.

The level residual is reported as a **secondary** diagnostic. Both readings appear in every report so
that neither can be quoted alone: judged on level the model looks broken (about 6.5 mean relative
residual on a smooth trajectory), and judged on turning points it may not be.

Two consequences worth stating:

- Turning points are detected in **growth rates** by default, not levels. Y, K_R and K_I are close to
  monotonically increasing, and a series that only rises has no turning points in level at all. The
  turns this framework cares about are turns in the rate of accumulation.
- A **prominence floor** applies, relative to each series' own range. Counting wobbles as turns inflates
  the hit rate and the false-positive rate together until neither means anything.

A test asserts the property that matters here: a simulated path 50 per cent too high throughout still
scores a full turning-point hit rate and full directional accuracy, while its level residual is large.
That is precisely the case the author's guidance is about.

### Limits recorded rather than hidden

- The backtest compares over a holdout using parameters fitted to the full window, not the training
  window carried forward. A strict out-of-sample projection is unreliable over long horizons because of
  the finite-time singularity, and the report says so rather than presenting an in-sample comparison as
  out-of-sample.
- Sensitivity varies only the **observed inputs** (savings rate, stimulus proxy). The fitted identity
  corrections are calibration outputs, so varying them would produce a different model rather than a
  sensitivity test, and the function refuses.
- The historical analogue requires its reference periods to be **supplied**, not inferred. Choosing the
  alignment is the analytical claim, and inferring the alignment that maximises correlation would
  manufacture the resemblance the overlay exists to let a reader judge.
- `phase_four_scenarios` refuses to project a correction when the starting ratio is already inside the
  band, because projecting one would be inventing a crisis.

## 11. Standardising adjustments for poorly defined data

Directed by the author on 2026-07-27: the source data are poorly defined, so the programme should carry
a general adjustment term per series to standardise them, since the dynamics and the derived projections
matter more than exact values.

Implemented in `macrofield/data/adjustment.py`. The design turns on one property that makes the whole
approach safe, and it is asserted by test rather than claimed in prose:

**A multiplicative level adjustment is invisible to every criterion the model is judged on.** Scaling a
series by a constant leaves its growth rates identical, its direction identical, and its turning points
in exactly the same periods, because `d log(cX)/dt = d log(X)/dt`. Under the criteria of section 10 a
level adjustment therefore costs nothing. What it *does* change is the ratios between series, which is
where it does real work: `K_R/Y` and the saturation axis both move, and those are the quantities the
phase classifier and HoNI consume.

**Drift adjustment is not available.** An additive correction to the growth rate, which is what a
deflator-bias correction amounts to, would change the trend and could change whether a series is rising
at all. The author ruled it out on 2026-07-27, and it is therefore **not implemented**: not defaulted to
zero, not reachable behind a flag, and absent from the dataclass entirely. An option that must never be
used is better removed than guarded, because leaving it reachable would oblige every downstream reader to
check whether it had been applied.

The result is a guarantee rather than a discipline: no adjustment this programme can produce is capable of
altering a growth rate, a direction, or a turning point. `ADJUSTMENTS_ARE_DYNAMICS_NEUTRAL` states it,
a parametrised property test asserts it across scales from 0.5 to 10, and a further test asserts that
passing a drift parameter raises `TypeError`.

### Documented priors, applied to nothing by default

`ADJUSTMENT_PRIORS` records what could legitimately be adjusted, by how much, and on whose authority.
Every entry is **the identity by default**: the priors document ranges for the sensitivity sweep, they do
not quietly correct anything, because replacing one poorly defined number with another and not saying so
is worse than leaving it alone.

| Quantity | Prior range | Direction and reason |
| --- | --- | --- |
| `Y` | 0.80 to 1.00 | Downwards. Imputed components, hedonic adjustment and FISIM inflate measured output. BOOK 10.2 names all three; BOOK 10.6 records alternative estimates 10 to 20 per cent lower. |
| `K_R` | 1.00 to 1.30 | Upwards. The national-accounts definition excludes land and mineral resources even where productive, understating the stock. BOOK 10.3. |
| `K_I` | 0.80 to 1.20 | Both ways. Financial aggregates double count, but shadow banking is incompletely captured and pulls the other way. BOOK 10.4. |
| `saturation` | 1.00 to 1.25 | Upwards, implied by the output adjustment appearing in its denominator. |

A non-identity adjustment **cannot be constructed without a rationale and a source**. That is enforced in
`__post_init__`, on the grounds that an undocumented adjustment to published data is indistinguishable
from fabricating it. An adjusted series is marked `DERIVED`, so the integrity gate refuses it unless the
caller explicitly opts into derived inputs.

### The honest way to use it

`sweep_level_adjustment` varies a scale across its documented prior and reports the **spread** of the
conclusion rather than one number from one chosen scale. Where the conclusion is stable across the range
it is robust to the measurement problem; where it is not, the definitional uncertainty is the binding
constraint and the value should be quoted as a range. `standardise` rebases to an index for putting
quantities of different units on one chart, and is dynamics-neutral for the same reason.

## 12. Recorded corrections to source implementations

`Team_TAA_Risk_Signal.m` lines 16 and 75 to 79 apply `M(2)` to both the Contraction and the Recovery
kernel and never reference `M(3)`, so the Recovery weight is unused and the Contraction weight is
applied twice. This implementation uses all four segment weights as the construction intends. Output
will therefore differ from the current live `convictions.json` distributions.

## 12b. The projection reproduces the reordering, and that is the model working

Recorded because a revision of this document, written on 2026-07-27 while the projection chart was being
built, filed this behaviour as an **OPEN defect**. It is not one. The author corrected it the same day, and
the correction is worth keeping because the mistake was a failure to recognise the framework's central
prediction when the model produced it.

For the United States the projection reads:

| Period | Credit saturation | Phase |
| --- | --- | --- |
| 2024, observed, last | 3.48 | Saturation and reordering |
| 2025, first projected | 2.31 | Build-up |
| 2030, projected | 0.91 | Foundation |
| 2039, projected | 0.73 | Foundation |

The earlier revision objected that the run "concludes that the economy the framework's whole thesis
identifies as late-saturated becomes the healthiest on the axis inside fifteen years", and treated the decay
as a bug.

**That decay is the reordering.** BOOK section 20.3, Proposition 20.1, states it directly: the capital cycle
"is directional. It progresses through the phase structure of Chapter 12, terminates in saturation, and is
followed by a **reordering that resets the system at a lower capital base** rather than returning it to the
state it left." Chapter 8 gives the mechanism: once the claims of financial capital exceed what real output
can sustainably provide, "the system must either find a way to reset the claims (through inflation, default,
debt restructuring, or some other mechanism) or face the consequences of the unsustainable accumulation."

So an economy that begins in Phase IV and ends at Foundation has been **reset to a low capital base and
begun accumulating again**, which is exactly the trajectory the framework predicts for a saturated economy.
Reaching Foundation is not a contradiction of the thesis; it is the thesis. The two resolutions of section 9,
debt deflation and hyperinflation, are the two routes to that same reset.

Two consequences follow, and both turn out to be the code behaving correctly:

- **The empty `scenarios` set is right.** `project` offers the two Phase IV resolution paths only where the
  projection *ends* above the band. Here the main path corrects below the band inside the horizon, so the
  reset has already been projected and offering the resolution paths as well would double-count it. The
  scenarios exist for the case where the horizon ends with the correction still pending.
- **The level offset at the join is not a discontinuity in the economy.** The projection integrates forward
  from the calibrated model's own final state rather than from the last observation. `Y` in the first
  projected period sits 3.3 per cent above the **simulated** 2024 value and 28 per cent above the
  **observed** one, which is the calibration's level residual, recorded in section 10 as about 6.5 mean
  relative and explicitly held to be the secondary criterion. Continuing the model's own trajectory is
  self-consistent; rebasing onto the observation would silently discard the fit.

### Correction: the projection already starts from the observed state

A further claim in the retracted section was that the projection "integrates forward from the calibrated
model's own final state, not from the last observation". **That is also wrong.** `projection.py` starts from
`path.output[-1]`, `path.real_capital[-1]` and `path.financial_capital[-1]`, and its own comment explains
why, including that starting from the fit once put the United States on the wrong side of the Phase 4
boundary in the first projected period. The earlier revision inferred "starts from the simulated state" from
`Y` in 2025 landing within 3.3 per cent of the simulated 2024 value, which was a coincidence of the model's
fast first step.

So the step at the join is **one period of the model's own dynamics from the observed state**, not a level
offset. Under held-last parameters the first projected year moves `Y` by +28 per cent, `K_R` by +34.6 per
cent and `K_I` by -15.2 per cent, which is the reordering beginning immediately rather than after a delay.

### What the dashboard does

The projected trace is now **prepended with the last observed point**, so the observed and projected lines
join as one continuous path with the first step visible as a steep segment. Previously only the projected
periods were plotted, which left the last observation unconnected and made a genuine continuation read as a
separate series. The projected portion is dashed, so it stays distinguishable without the legend.

`/api/project/{code}` still returns a `join_break` object where the first projected saturation differs from
the last observed by more than a tenth, and the cockpit renders it above the chart as an explanation rather
than a warning: a reader who took the two portions for a single smooth series would otherwise read the first
step as a crash.

### The derived indicators are projected too

Directed 2026-07-28. Every derived indicator is a function of the state path, so a projected state yields a
projected indicator with no additional assumption, and the dashboard draws them as dashed continuations.

**One trap, and it is not obvious.** The price levels are indices rebased to the first period of whatever
series they are given, so computing the indicators over the *projected* state alone restarts the index at 100
in the first projected year. Against an observed index that has reached several thousand, the projected path
then plots as a collapse to zero, and the price-divergence ratio restarts at one. Both are artefacts of the
rebasing rather than anything the model said, and the first version of this shipped with exactly that defect
visible on the chart.

The endpoint therefore computes every indicator **once over the observed and projected state together** and
reports `projection_start_index`, so the two portions share one index base and the growth rate across the
join is right. The front end splits that single series rather than stitching two. A consequence worth stating
on the panel, and stated there: when a projection is shown the levels before the join differ from the
observed-only view, because the base is the joined series'. The growth rates and the divergence do not.

## 12c. The phase exit is latched. Directed 2026-07-28

`classify_period` is stateless, so on a *falling* saturation path it reclassified as soon as the ratio crossed
back under the Phase 3 ceiling. The United States projection read **Build-up at 2.31 in its first projected
period**, which is wrong about the framework: Phase 4 is the reordering, and an economy part-way through a
correction has not returned to Build-up.

The rule, in the author's words: **the phase changes to Foundation only when it reaches that level, otherwise
it sits in Saturation.** `phases.classify_sequence` implements it as a one-way latch. Once a path is in Phase 4
every later period stays there until saturation falls below `foundation_saturation_ceiling`, and only then does
ordinary classification resume. Entry into Phase 4 is unchanged.

It is a **sequence** property, so `project`, `project_resiliently` and the control board all classify the whole
path at once, with the observed end state included so the latch is seeded correctly. Classifying periods
separately cannot reproduce it.

**And the cycle restarts where the reordering ends.** `cycles.reordering_end` finds the first Foundation period
following a Saturation one and `cycles.years_into_capital_cycle` restarts the count there. Without it the
capital anchor stayed at the last observed crossing and went on reporting an economy decades late for a
correction already behind it. Reaching Foundation *without* having been in Saturation is not a restart, since
an unsaturated economy has been through no reordering.

The United States projection now reports one transition, 2030 Saturation and reordering to Foundation at
saturation 0.91, where it previously reported two. The capital tilt contributed +1.24 to crisis at 2029 and
nothing from 2030, taking the crisis weight from 0.300 to 0.229.

## 13. Chapter 7, read in full on 2026-07-27

Chapter 7 was one of the two chapters the abridged edition only alluded to. Read in full, it **confirms
`macrofield/model/derived.py` and changes nothing in it.** Recorded here so that nobody re-reads it looking
for a defect that is not there.

The chapter's substantive content, in its own order:

- **7.2, the quantity equation as a conservation law.** Written `K · V = P · H`, with `K` monetary capital in
  circulation (in place of `M`, "to be consistent with our later use of `K` as the capital variable") and `H`
  the transaction frequency (in place of `Q`). Rearranged to `K · V − P · H = 0` and then to
  `∇ · (K, −P) = 0` "in the appropriate one-dimensional sense". The reading is that the price level `P` is
  the **source** of money flows `K`: "whenever prices change with respect to time, `∂P/∂t`, there must be a
  corresponding change in the flows, `∂K/∂x`, with the divergence-free condition being maintained."
- **7.3, the Lagrangian.** `L = K · V − H · P`, following Genreith (2012), with the action `S = ∫ L dt`
  required to be stationary. `K · V` is the kinetic term and `H · P` the potential term, by analogy with
  `L = T − U`. The chapter is careful that the analogy is "structural rather than literal".
- **7.4 to 7.6, the extension.** Genreith's two equations `Ẏ = F(Y, K)` and `K̇ = G(Y, K)` become the
  three-body system `Ẏ = F(Y, K_R, K_I)`, `K̇_R = G(...)`, `K̇_I = H(...)`. The Lagrangian formulation, the
  stationary-action principle, the Euler-Lagrange apparatus and the conservation-law structure are credited
  to Genreith; the third state variable and the `K_R`-`K_I` coupling are the book's extension.
- **7.7** answers the methodological objection: the borrowing is "of mathematical structure", not of
  physical content, and the justification is "operational, not ontological".

Two things chapter 7 does **not** supply, both of which had been hoped for:

1. **The functional forms of `F`, `G`, `H` are not in chapter 7.** It defers them explicitly to chapter 8
   ("We give the functional specifications in full in Chapter 8"). Section 1 of this document already
   implements them from brief section 0.2 and book 7.5 to 8.1, so this is not a gap.
2. **It does not supply the shapes `f1, f2, f3` of the gold equation.** The resolved gold section above
   listed chapter 7 as a candidate source for them. It is not one. The shapes come from the author's
   operational equation instead, where each `f` is linear in its driver term.

One incidental confirmation: 7.6 states that the 250 to 350 per cent capital-saturation threshold "is derived
from the three-body model in Chapter 8 rather than asserted", and is explicit that this is what makes the
framework falsifiable: "If the bifurcation analysis yields a threshold of 250-350 percent and the empirical
data show that the predicted regime change occurs at substantially different values, the framework is in
trouble." That is the same claim section 3 records, from the other direction.

## 14. Part VI, the personal balance sheet, read in full on 2026-07-27

Part VI (chapters 27 to 31) takes the apparatus down to a single balance sheet. **It is out of scope for this
programme and nothing in it is implemented.** That is a scope statement rather than a judgement: the
programme's unit of analysis is an economy, and Part VI's is a person. This section records what Part VI
contains, and, more usefully, the four places where it reaches *back* into what this programme does build.

### What Part VI is

Chapter 27 argues the descent is an **instantiation rather than an analogy**, on the self-similarity claim of
chapter 5: a person is "another scale in the same hierarchy, and the smallest one at which the framework's
objects still have referents". The book goes further and treats it as a test: "if the framework could not be
instantiated at the scale of a single balance sheet, that would be evidence against the self-similarity
claim on which the rest of the book rests."

The apparatus, in brief. State `x = (W_L, W_R, D, E, N, H, κ)` conditioned on a regime pair `(π, m)`: liquid
wealth, real assets, debt, expertise, network, health, and a standard-of-living habit. Controls
`u = (τ, C, s_E, s_N, A_D, w)`, where `τ` is a time allocation on a budget normalised to one and `w` is a
portfolio in the four-role space of chapter 23. Wealth accumulates without a ceiling; expertise, network and
health follow logistic laws with ceilings, and the network ceiling is itself raised by expertise, net worth
and the habit (`N̄ = N_0 + λ_E E + λ_W Ω + λ_κ κ`). Goals are **regions** with a deadline and a required
confidence, not numbers on a line, so feasibility is a probability and is constrained through a CVaR
surrogate. The problem is a quasi-variational inequality solved by receding-horizon control.

### Where Part VI reaches back into this programme

1. **The gold module feeds it.** Section 30.5: "The role returns and covariances that Section 29.1 requires
   are supplied by the **three-driver construction of Chapter 24** mapped into role space, which is to say
   the personal problem inherits the institutional calibration rather than performing a separate
   estimation." Section 28.3 puts physical gold in the Protection role "for the reasons developed at length
   in Chapter 24". So `macrofield/model/stock_gold.py` is upstream of Part VI, which raises the cost of the
   sign defect the resolved section above records.
2. **It corroborates the five-regime taxonomy.** Section 30.5 states the market phase is "the recurrent
   five-state classification of Chapter 20: crisis, contraction, stagnation, expansion and boom", and that
   the market phase **genuinely recurs while the capital-cycle phase does not**. That is independent support
   for the choice recorded in section 6, and the recurrent-versus-not distinction is a property our phase and
   regime layers keep separate already.
3. **It names the phase-observability problem, which this programme has too.** Section 30.5: "The phase is
   not directly observable. What is observable are indicators: the credit impulse, the capital ratios, and
   the Health of Nations Indicator of Chapter 12." The book therefore writes a posterior
   `b_t(π, m) = Pr(π_t, m_t | indicators up to t)` and then says its own engine "conditions on the modal
   phase and treats it as known. That is a reduction, and it overstates confidence in the regime call."
   **`macrofield/model/phases.py` makes exactly the same reduction**, and the three observables the book
   names are three this programme computes. This is the most actionable thing in Part VI for us, and it is
   recorded as open below.
4. **It restates our missing-data rule in the book's own voice.** Section 31.7: "The role return matrix is an
   input rather than a result... Where they are not supplied, the regime layer should be switched off rather
   than run on invented numbers. We would rather report an acknowledged gap than a fabricated matrix,
   because every figure in every case would otherwise inherit invented returns while appearing to rest on a
   calibration." That is brief section 2's rule, and the coverage-floor behaviour of section 4 above.

### A nuance for section 9, on forecasting

Section 31.5.1 is the closest the book comes to using the synchronisation window operationally, and it is
careful in a way worth carrying into our reporting. It places the plan's horizon across the window of
section 9.8.1, notes that "a plan solved against a constant transition intensity therefore reports a
confidence that is too high", and then declines to make it a forecast: "The correct reading is comparative
rather than predictive: the encore lever is more valuable than a constant-regime solution makes it appear,
not less... **Neither conclusion depends on the window being right about any particular year.**"

That is compatible with section 9 rather than a correction to it. The model forecasts; the useful content of
the synchronisation window is a *comparative* statement about which lever is worth more, and a briefing that
leans on the specific year is leaning on the weakest part of it.

### A notation warning for anyone reading formulas across parts

Part VI deliberately reuses two symbols, and section 27.6 records both:

- **`Y`** is aggregate output in chapters 1 to 29 and **personal income** in Part VI.
- **`κ`** is the capital-saturation ratio in Parts I to V and the **standard-of-living habit** in Part VI.
  The book calls this collision "less comfortable than the first" and offers the parallel that each is "a
  stock that ratchets upward" whose accumulation "eventually forces an adjustment".

Since `config/defaults.yaml` and this document use `κ`/saturation in the Parts I to V sense throughout, a
reader who arrives from Part VI should not read our `saturation` keys as anything to do with a habit stock.

### Left for review

- **The phase posterior.** Whether `phases.py` should emit a distribution over phases from the three
  observables the book names, rather than a point classification. The book specifies the object
  (`b_t(π, m)`), declines to solve it, lists it as its own most valuable extension ("Regime filtering...
  This is the most valuable of the six"), and records it as an open question in its chapter 33. Adopting it
  here would be a genuine advance on the source rather than an implementation of it, and it is the author's
  call whether this programme is where that happens.
- **Whether Part VI is in scope at all.** It is a separate engine over a different state vector, and it
  would roughly double the programme. Recorded as out of scope until directed otherwise.

## 15. The long-term overlay: the macro state as a 25-bin signal. Directed 2026-07-28

The programme now produces the strategic half of the signal the downstream optimiser consumes:

```
  TAA (short-term, technical)  +  SAA (long-term, this programme)  ->  market risk signal  ->  PCP
       market_risk_signal.csv        model/saa_signal.py               25 bins, 50:50 by default
```

Design record in `docs/BATTLE_PLAN.md`; what belongs here is the modelling.

### The taxonomy is the book's five regimes, everywhere

Settled by the author on 2026-07-28. The operational `Scenario_SAA.m` spreads four weights (Boom, Recovery,
Contraction, Bust) at bin offsets 1, 3, 10, 16; this programme uses the five regimes of BOOK 20.2 at the
placements in `regime.placement`. The four-scenario layout is **superseded**, so scenario output does not
reproduce that file bin for bin. What it does reproduce is the file's scenario definitions and its
transformation mechanics.

Recovery has no five-regime equivalent, and section 6 above already settled why: it is a transition rather than
a regime. It is split between Stagnation and Expansion, evenly by default, at `saa.recovery_split`.

Worth holding in view: **Hyperinflation maps entirely to Boom**, because the source vector is in *nominal*
terms and a hyperinflation is a nominal boom. The author confirmed the nominal reading is the intended one. A
portfolio positioned for Boom in a hyperinflation is nonetheless positioned wrongly in real terms, which is
section 17's axis, not this one.

### The tilts have no source, so the spread is reported

Turning a macro state into regime weights is not in the book. What the book supplies is *which* quantities
matter: the phase and the rule that fired, saturation against the band, `K_R/K_I` against one, the
unsecured-asset gap, the two cycle positions, and the interference between the cycles. How much each should
move the weights is a modelling choice with no source.

The author settled the treatment on 2026-07-28: **leave the coefficients as a judgement call and report the
sweep.** `saa_signal.sweep_tilts` scales every tilt across `validation.sensitivity.range` and reports the range
the crisis weight moves over, so a range is quoted and never a point. `base` is deliberately excluded, because
scaling it alongside the others moves numerator and denominator together and would report a robustness the
signal does not have.

The sweep also varies each tilt *alone*, which is the more useful half, and on United States data the answer is
reassuring: the crisis weight runs 0.193 to 0.206, a spread of 0.013, and only three of the eight coefficients
do any work at all, led by `saturation_below_band` at 0.055 and `interference` at 0.050. **The unsourced
coefficients are not carrying the answer.** Every signal also reports its per-tilt contributions, so a
surprising reading can be taken apart rather than argued with.

### The merge is in bin space, and a bimodal result is a finding

Bins carry no vocabulary, so merging there keeps the four-against-five taxonomy question from propagating to
the PCP.

Mixing two unimodal distributions at different locations produces a bimodal one, which the Master Deck reads as
a **swing market**, where participants disagree on direction. The author settled on 2026-07-28 that this is a
finding rather than an artefact: the two horizons disagreeing genuinely *is* dispersion of view. So the shape is
measured and reported rather than smoothed away by blending in stance space.

Measuring it needed a correction. The first implementation counted any local maximum above a height floor,
which reported three to five modes on every merged signal, because the 25-bin axis is lumpy *by construction*:
it sums five overlapping kernels. `taa.dispersion` now uses true **topographic** prominence, a peak's height
above the saddle separating it from higher ground, and the floor is configuration at
`regime.shape.mode_prominence`. The correction changed the pure macro signal's reading from "swing" to "risky,
mass at the cautious end", so the swing had been an artefact.

### The technical signal decays rather than being held

`market_risk_signal.csv` ends at its last published month; the SAA projects fifteen years. Holding the last
reading flat would assert that today's technical signal describes 2039. `taa.decay_forward` decays it toward its
own long-run average on a configurable half-life, six months by default, so beyond roughly two years the merged
signal is the macro one alone. That is the intended division of labour between the horizons.

The merge covers only the overlap. The macro window begins decades before the technical signal does, 1972
against 2006 on United States data, and the earlier periods carry the macro signal alone rather than a
fabricated technical one.

## 16. Fallbacks, and the labels that make them acceptable

Directed by the author on 2026-07-28: where the programme cannot converge, fall back to a shorter horizon and
extrapolate; where there is no capital cycle, assume when it would hit the mark.

Both invent values, which is a reasonable thing for a control board to do and is only reasonable if the invented
values are labelled. `control.Provenance` is that label and it is **ordered** —
`OBSERVED, DERIVED, INTEGRATED, EXTRAPOLATED, ASSUMED` — so a series of mixed provenance takes the weakest of
its parts, and `is_invented` is true only for the last two.

**The horizon search is a binary search, not a ladder.** A descending ladder answered a request for 40 periods
with 12 integrated on United States data where 35 integrates, discarding most of the available model output. A
projection costs 30 to 300 milliseconds, so finding the true maximum in about six attempts is affordable and
strictly better. It assumes integrability is monotonic in the horizon, which holds because the obstacle is a
finite-time singularity at a fixed time. Every attempt is recorded.

**The extrapolation takes its level from the model and its slope from history**, and that correction matters more
than the search. Continuing the *integrated tail's* growth rate compounds the divergence that stopped the
integration: it took the saturation axis to 37 over a 40-period request and to 3.7e24 over a 200-period one.
Taking the slope from the economy's observed history gives 10.4 and 67.6. Where the two rates differ by more
than a factor of three the difference is reported, because it measures how hard the model was diverging.

**The assumed capital anchor refuses more often than it fires.** It fits the recent trend of the saturation axis
and solves for the year it would cross the anchor ratio, marked `ASSUMED`. It refuses a flat or falling trend, a
crossing more than 120 years out, and fewer than two observations. Both live cases refuse: Germany at 2.76 and
India at 2.50 are below the anchor *and* trending down, so they stay unanchored even with the assumption
enabled. Assuming *when* an economy reaches saturation extrapolates a rising trend; assuming *that* it will,
against a falling one, is a different and much weaker claim.

## 17. Nominal and real. Directed 2026-07-28

Both views are produced, the nominal reading is primary, and each real view is an **overlay** on it.

### The word "real" was already taken

`model/derived.py` uses `real_*` to mean **the real economy as against the financial economy**:
`real_price_level` is the real sector's price level from `P_R · H_R = Y`. That is a statement about *which
sector* and has nothing to do with inflation adjustment. Nominal against real is a statement about **basis**,
whether a quantity is deflated. The two axes are orthogonal, and a financial-sector price level can perfectly
well be expressed in real terms. `model/real_view.py` names them apart and never says "real" unqualified.

### Three bases, and output can only use two of them

| Basis | Deflator | Standing |
| --- | --- | --- |
| `NOMINAL` | none | primary, always present |
| `REAL_GOLD` | LBMA gold price | **the book's own**, BOOK chapter 11 |
| `REAL_CPI` | consumer prices, `FP.CPI.TOTL` | the conventional measured index |
| `REAL_MODEL` | the model's own real-economy price level | always available, but a model quantity |

Gold is not an alternative to CPI here. Chapter 11 computes its 172-year real-rate series with the gold price,
on chapter 24's argument that in a fiat regime gold is a price-of-money instrument whose nominal price reflects
the issuing currency's loss of purchasing power. The front end prefers gold, then CPI, then the model's own
level, and that order is the argument.

**Output has no view on the model's own basis, and the reason is not a detail.** Chapter 7 derives the
real-economy price level as proportional to output, so deflating output by it is *circular* and returns a flat
line: the first implementation reported exactly 1.0 times over 52 years, which would read as five decades
without real growth. The capital stocks are not in `P_R`'s definition, so their model-deflated view is genuine.
Output needed an independent deflator, which is why `consumer_prices` and `gold_price` are now fetched as
optional series in `pipeline.assemble`.

### What the two independent bases say

United States, 1972 to 2024, growth over the window:

| | nominal | real, gold | real, CPI | real, model |
| --- | --- | --- | --- | --- |
| Output | 22.9x | **0.57x** | 3.05x | circular, withheld |
| Real capital | 19.3x | 0.48x | 2.57x | 0.84x |
| Financial capital | 42.2x | **1.05x** | 5.62x | 1.84x |

They disagree about the level and agree about the divergence, and both facts are worth stating. On CPI the
economy roughly tripled in real terms; against gold it is at 0.57 times its 1972 size. That is the framework's
own argument about fiat measurement appearing in one table.

What both agree on is the ratio: financial capital grew about **2.2 times faster than real capital** on either
basis. The divergence is robust to the deflator even though the level is not, which is a stronger result than
either basis alone could give.

### Two guards

A deflator that does not cover the whole window is refused rather than used for part of it, since deflating some
periods and not others splices two bases into one series. And `real_view.check_regime_span` warns on any window
crossing **1914 to 1971**: chapter 24.3.1 measures inflation at about 0.47 per cent a year before it and 2.6
after, so a series deflated across it is two regimes spliced together.

`deflate_rate` uses `(1 + n) / (1 + d) - 1` rather than `n - d`. The difference is negligible at low rates and
the whole answer at high ones, which is the hyperinflationary case the framework cares about: at 200 per cent
nominal against 100 per cent inflation, subtraction says 100 per cent real when the truth is 50.
