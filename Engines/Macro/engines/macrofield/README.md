# Engine 03: Macro Field (`macrofield`), the three-body capital-saturation model

Output (Y), real capital (K_R) and financial capital (K_I) as three coupled bodies. Per
economy the engine assembles the observed path from published data, calibrates the equations
of motion to it, and reports saturation, the four-phase position and the diagnostics the model
defines. Built to the Engine Building Guide; same shape and conventions as `honi`.

> Model-derived research output. Simulated paths are illustrative consequences of the
> calibrated model, not forecasts. **Not investment advice.**

| | |
|---|---|
| Module | `macrofield` |
| Default port | 8003 (Guide §4 roster; configurable) |
| Status | v0.6.0. Calibration 1.0.0 reproduces the eigentliCH prototype (Macro_Model) exactly; 1.3.0 covers and projects all 16 HoNI economies; 1.4.0 (stored) bounds the projection with a soft saturation ceiling, the four Phase IV resolution policies and a reset, to 2080 (R-005); 1.5.0 (active, TB-28) adds a bounded investment share so every fit and every projection integrates (TB-08, TB-27) |
| Consumes | A static data snapshot (106 frozen raw files: World Bank, BIS, PWT, Bundesbank, JST, IMF; loaded into PostgreSQL). Later: `Snapshot` from `datafeed` |
| Produces | `MacroState` |
| Downstream | `aggregation` (Engine 04, port 8004), which combines `mrs`, `cycle` and `macrofield` into the Regime |
| Scope | The three-body core only. The five nested cycles sit in `cycle` (Engine 12, port 8012) and the 25-state distribution in `aggregation` (Engine 04, port 8004); no HoNI input (TB-19) |

## Run it

From this folder, with the Macro venv (`..\..\.venv`):

```bat
docker compose up -d                  :: in Projects\PostgreSQL, once
pip install -e .[etl,dev]             :: once
python -m macrofield init-db           :: once per server: database, schema, seed calibration
python -m macrofield load              :: verify data/raw against its manifest, load it
start.cmd                             :: or: python -m macrofield serve
```

Then open <http://127.0.0.1:8003/> for the test bench, or `/docs`. A run of all sixteen
economies takes about 30 seconds on four worker processes:

```bash
curl -X POST localhost:8003/run -H "Content-Type: application/json" \
     -d '{"snapshot_id": "SNP-98ca1e0341dd1bdd"}'          # 202, {"run_id": ..., "status": "queued"}
curl localhost:8003/runs/<run_id>                           # queued, running, succeeded or failed
curl localhost:8003/state/<artefact_id>/current             # phase and saturation per economy
```

```bash
python -m pytest                    # 116 tests, about 6 minutes, against the real container
python -m pytest -m "not slow"      # without the golden reconciliation
python dev/reconcile.py             # golden comparison, printed per quantity
python dev/freeze_scenario_saa.py   # re-freeze Scenario_SAA.m into golden/scenario_saa/ (R-005)
python -m macrofield data-need       # write data_need.csv (T5 format)
python dev/build_deploy.py --out <folder>   # deploy folder: src, config, data, README only
```

The store tests use the real PostgreSQL container, each module in a throwaway schema, and the
suite fails rather than skips when the container is down. `config.local.yaml` (git-ignored)
holds the local container's password; nothing committed does.

## Anatomy

```
engines/macrofield/
  README.md  pyproject.toml  config.yaml  start.cmd  data_need.csv
  data/raw/                 frozen raw sources + MANIFEST.json (SHA-256 per file)
  src/macrofield/
    api.py                  FastAPI routing only
    contracts.py            Pydantic models, in and out
    engine.py               pure: observations + calibration -> EconomyState
      assembly.py           pure: published series -> observed (Y, K_R, K_I)
      fitting.py            pure: identities from data, least-squares calibration
      dynamics.py           pure: equations of motion, residuals, closed form
      phases.py             pure: phase classifier, unsecured-asset diagnostics
      projection.py         pure: forward projection, levers, soft ceiling, crisis and reset
      resolution.py         pure: the four Phase IV policies of Scenario_SAA.m (inflation, defaults, valuations)
    calibration.py          seed calibrations (versioned, immutable)
    sources.py              pure parsers: World Bank JSON, BIS zip, PWT xlsx
    snapshot.py             data/raw -> snapshot rows (stand-in for datafeed)
    data_need.py            the data-need specification
    service.py              orchestration, idempotency, background runs
    store.py  schema.sql    PostgreSQL persistence, append-only by trigger; series_registry publishes sources.CATALOGUE
    settings.py             config.yaml, config.local.yaml, MACROFIELD_* overrides
  tests/                    test_engine (unit, property), test_golden, test_api, test_resolution (R-005),
                            test_integrability (TB-27)
  golden/                   frozen outputs of the eigentliCH prototype, one JSON per economy;
                            scenario_saa/: Scenario_SAA.m and its frozen policies (R-005)
  dev/                      freeze_sources, freeze_golden, freeze_scenario_saa, reconcile, build_deploy
  testbench/                single-page test bench (Plotly from CDN), not deployed
```

Differences from the Guide's template, each deliberate: `engine.py` delegates to four pure
modules rather than holding 1,000 lines; there is no `clients.py` because nothing upstream is
called yet (`snapshot.py` stands in for `datafeed`); `openpyxl` is a load-time extra (`[etl]`)
because PWT is published as xlsx, and is never imported by a running engine.

## Data flow

```
 data/raw (98 files, SHA-256 manifest)
   World Bank WDI JSON   BIS WS_TC zip   Penn World Table 10.01 xlsx
        |                    |                  |
        +------ snapshot.py: verify, parse, key by (series id, source country) ------+
                                      |
                              PostgreSQL: observation
                                      |
                  service.py: POST /run -> background, one process per economy
                                      |
   assembly.py   Y = GDP (USD, market rates)
                 saturation = BIS credit/GDP x uplift          K_I = saturation x Y
                 K_R/Y = PWT cn/cgdpo, extended past 2019 in ratio space
                 K_R, K_I x common scale so max K_R/Y = 0.9    S = stimulus share x Y
                                      |
   fitting.py    identities r, alpha, p_p, p_b (Savitzky-Golay derivatives)
                 least squares, log space: 3 identity corrections, 2 scales, initial state
   dynamics.py   Radau / BDF integration, two-body and Genreith residuals
   phases.py     phase 1 to 4 with the Phase 4 latch, band, unsecured gap
                                      |
                        MacroState artefact (append-only)
```

The equations (brief section 0.2, *Capital Saturation* chapters 7.5 to 8.1):

```
Y_dot   = (p_b - p_s) Y + K_R_dot - p_p K_R + S
K_R_dot = (1 - alpha) p_s Y + p_p K_R + r K_I          r = 1 - K_R / Y
                                                       (1.5.0: r = max(0, 1 - K_R / Y), TB-27)
K_I_dot = alpha p_s Y + p_p K_I - r K_I + S
```

## Contracts and endpoints

Contracts (`GET /contracts` serves the JSON Schemas): `MacroRunRequest`
`{snapshot_id, economies?, calibration_version?, resolution_policy?}` in; `MacroState` out, one
`EconomyState` per economy with the years, the assembled inputs (published and adjusted),
the observed and simulated paths, the identities, the capital normalisation, the fit report,
per-year diagnostics and phases, the current state and notes, plus a coverage report and full
provenance (snapshot, SHA-256 of every source file, engine, contract and calibration versions,
idempotency key). Missing values are `null`, never `NaN`, never filled.

Versions (`CONTRACT_VERSIONS`): `macrofield-run@1.1.0`, `macrofield-state@1.2.0`,
`macrofield-calibration@1.5.0`, `macrofield-projection-request@1.1.0`,
`macrofield-projection@1.2.0`. **`MacroState` stays at 1.2.0 on purpose**: cycle
(`UpstreamMacroState`) and aggregation (`MacroState` mirror) pin that literal, so every field
R-005 added (in `Projection`, `ResolutionScenario`, `Provenance`, `ProjectionDefaults`) is
optional and omitted from the serialisation while unset. Stored artefacts and calibrations of
earlier versions read back and hash exactly as published (tested).

Standard endpoints per Guide 2.1: `/health`, `/meta` (with the live allowlist check),
`/contracts`, `POST /run`, `/runs/{id}`, `/artefacts/{id}`, `GET`/`PUT /calibration`.
Additive:

| Method | Path | |
|---|---|---|
| GET | `/state/{artefact_id}/current` | Phase, saturation, K_R/K_I per economy; the reason where unavailable |
| GET | `/state/{artefact_id}/economies/{code}` | One `EconomyState` |
| GET | `/snapshots` | Loaded static snapshots |
| GET | `/model?economy=` | The model explained on one economy, from the latest successful run: inputs, every step with its formula, parameters and charts, outputs (`model-card@1.0.0`, the cockpit's Models page). A view, not a result: it is not in `CONTRACT_VERSIONS` |
| POST | `/project` | What-if projection on a stored artefact: horizon (years, or `horizon_until` a calendar year), parameter mode, stimulus and savings levers (constant, step, ramp, pulse), `resolution_policy` (1.4.0 on), Phase IV rates (before 1.4.0). Recomputed, not stored |
| GET | `/data-need` | The data-need specification against a snapshot |
| GET | `/calibration/versions`, `/runs` | Listings for the test bench |

## Calibration 1.0.0

Reproduces the eigentliCH prototype (eigentliCH/engines/Macro_Model, state of 2026-08-03), fudge factors
included, by decision of 2026-09-27. Each judgement is a versioned parameter with its source in
`calibration.py`, so a later version can replace it with evidence knowingly:

* **Credit uplift 1.4** on BIS credit/GDP: author's assessment that the series omits credit to
  the financial sector, sized so the United States reads about 3.5. Level only.
* **Capital normalisation to 0.9**: PWT puts K_R/Y at 3 to 6, where r < 0 and the system does
  not integrate. One common scale on both stocks; K_R/K_I and the Phase 4 test are untouched.
* **Identity corrections**: the section 0.2 definitions over-determine the equations, so p_p,
  p_b and alpha carry fitted multiplicative corrections. Their distance from one is reported.
* **p_b from population growth**, not the section 0.2 flow ratio, which is of order one and
  explodes the path. The flow ratio is always reported beside it.
* **Phase 3 ceiling 3.5**, raised from 3.0 to coincide with the balanced band (book 8.5).

## Calibration 1.1.0

1.0.0 plus one rule, the author's of 2026-09-27: once an economy has hit saturation it stays in
Phase 4 until the reset is over (saturation back below the Foundation level), **wherever in its
history that happened**. `phases.latch_from_full_history` runs the latch over every year with a
saturation value and a real-capital ratio, not only the calibration window, and every
`EconomyState` publishes that `phase_history`. On snapshot `SNP-98ca1e0341dd1bdd` no phase
changes: no economy crossed a Phase 4 condition before its window begins. Germany in
particular: BIS break-adjusted total credit for DE starts in 1998, uplifted saturation peaks at
3.17 (2020) and K_R/K_I never falls below 1, so DE reads Build-up on the data held (TB-13).

## Calibration 1.2.0: Germany on Genreith's measure

Genreith (Field Theory of Macroeconomics, 2014, section 2) measures K for Germany as the
balance-sheet total of all banks (Bundesbank BBK01.OU0308, now `BBBK1.M.OU0308`), not credit to
the non-financial sector, and places Phase IV where loans to domestic non-banks (OU0115) fall
below 50 per cent of it. BIS credit times the 1.4 uplift understated that for Germany (2.8
against 3.0 to 3.3) and BIS starts only in 1998. From 1.2.0 Germany's saturation axis is the
Bundesbank balance sheet over nominal GDP from 1950, without uplift; GDP is JST (West Germany,
DM) before 1990 and the World Bank after, so numerator and denominator cover the same territory
(the World Bank backcasts unified Germany before 1991, 12 per cent above West Germany). The
Phase IV floor applies where the share is published. Result: Foundation to 1966, Build-up from
1967, Phase 4 from 2000 (loans 49 per cent of the balance sheet), latched since; K/Y peaks at 3.19
in 2010 on current GDP (Genreith's 3.4 used pre-2014-revision GDP). The 3.5 ceiling is unchanged.

## Calibration 1.3.0: every economy projectable

| Economy | Gap | Closed by |
|---|---|---|
| BR, CH, DE, ES, TH, JP | Fitted path does not reproduce the window | Projected from the observed end state anyway, `fit_reproduces_window: false`, notes open with WEAK EVIDENCE |
| JP | No World Bank fiscal balance | IMF WEO net lending (sign reversed like every fiscal proxy) |
| ID | World Bank fiscal ends 2009 | IMF WEO net lending |
| PH | No BIS credit | IMF Global Debt Database private debt plus government debt, times the uplift |
| BD, VN | No BIS credit; fiscal short or absent | IMF debt axis as PH; IMF WEO net lending |
| EU | No PWT capital stock | Euro area (BIS XM, World Bank EMU) with real capital from the sum of its 20 members' PWT capital and output |

The IMF debt axis was checked against BIS where both exist: TH and BR identical, MY, ID, CN, US
and DE within a few per cent, IN 8 per cent lower. WEO forecast years are cut at 2024. A
projected path is also cut where a state turns non-positive, as the fit treats it.

## Forward projection

Every artefact carries a projection per economy; `POST /project` recomputes it with other
settings. Ported from the prototype's `macrofield/projection.py`: parameters carried forward by
`hold_last` or `extend_trend` with the fitted corrections, levers multiplying the projected
stimulus and savings year by year, integration from the observed end state, a binary search for
the longest horizon that integrates with the rest a log-linear tail flagged `extrapolated`, and
one latched phase sequence continuing from the window's end. Up to 1.3.0 the horizon is 15 years
and both stylised Phase IV resolutions (debt deflation, hyperinflation) are shown when the path
ends above the band. An economy whose fit does not integrate is projected from its observed end
state and flagged as weak evidence (1.3.0, TB-18).

### Calibration 1.4.0 (stored): soft ceiling, crisis and reset (review R-005)

R-005 (decided by Nicolas, 28.09.2026): projected saturation ran far above its limit (CH:
observed 3.2 to 4.2, projected 9.2 by 2031 and 9.7 by 2039, TH and CN above 25). From 1.4.0:

1. **Soft ceiling** (`projection.saturation_ceiling`: centre 5.0, band 4.5 to 5.5, onset 3.5).
   Above the onset the year's log growth g of the unbounded path is damped,
   dx/dt = g sqrt(1 - u^2) with x = log saturation and u its position between the onset and the
   policy's turn level: a sine arc, so the path bends and meets the turn level with zero slope in
   finite time. Falling growth is not damped, there is no clamp, and a path whose growth fades
   first simply stays below. The turn level depends on the policy: depression 4.7 (early, low),
   stagflation 4.9, hyperinflation 5.1, deferral 5.4 (late, high).
2. **Policy switch** (`resolution_policy`: depression, hyperinflation, stagflation, deferral; a
   `POST /run` field in the idempotency key and in provenance, a `POST /project` field, a select
   in the test bench; default `stagflation`, the template's selected case). The policies are
   `SIM_Tech/Master_Controller/Scenario_SAA.m` v0.1 exactly (`resolution.py`, frozen in
   `golden/scenario_saa/`):

   | Policy | Target mix (B, R, C, Bust) | Inflation (annual, per month) | Defaults (claims surviving) | Valuations | Corrects through |
   |---|---|---|---|---|---|
   | depression | 0, 0, 0.25, 0.75 | sigmoid +2 % to -4 % (midpoint 0.5, steepness 20, flipped) | 1 to 0.6 | 1 to 0.5 in 30 months | numerator |
   | hyperinflation | 1, 0, 0, 0 | 0.2 exp(log 5 t^4), 20 % to 100 % | 1 | 1 | denominator |
   | stagflation | 0.5, 0.25, 0.25, 0 | sigmoid 2 % to 10 % (midpoint 0.3, steepness 15) | 1 to 0.8 | 1 to 0.7 in 20 months | both, moderately |
   | deferral | 0.5, 0, 0, 0.5 | two half Gaussians 2 % to 6 % and back (peak 0.5, sigma = distance / 2.5) | 1 to 0.9 | 1 to 0.8 in 50 months | little at first |

   Defaults follow the template's two legs: 30 % of the fall by month 30 on a root-shaped leg
   (exponent 1/2.5), the rest on a power-shaped one (exponent 2.5). In the model, over the crisis
   nominal output follows the price level the inflation path implies (monthly compounding, real
   output flat), K_R moves with prices, and financial claims are written down, K_I x defaults x
   valuations, so saturation = credit share x K_I / Y corrects as the table says. The target mix
   is carried for Engine 09 (`scenario`), not used here.
3. **Crisis, then reset.** At the turn the main path follows the selected policy through the
   60-month crisis, then declines to the reset target over the reset period (35 years, 30 to 40
   allowed) on a half cosine in logs. The target is the Foundation level, 0.95 x the Foundation
   ceiling, strictly inside Phase 1; `projection.crisis.reset.overrides` sets it per economy, and
   refuses one without a reason (none set). Over the reset output grows at its observed rate and
   K_R/Y returns to its early-phase level on the same curve. From the reset state the equations
   run again with early-phase parameters (the mean fitted parameters of the window's Phase 1 and 2
   years, else its first five), under the same ceiling. The phase is 4 through crisis and reset
   (the reordering is over when the reset is), then classified afresh: 4, the reset, then 1.
4. **Horizon.** The model runs to 2080 (`horizon_until`), for planning over that period; views
   show 2039 (`display_until`) with a switch to 2080, and later years carry `lower_confidence`.
   cycle projects to macrofield's last projected year (its C-22), so it sees 2080.
5. **Labels.** Each projected year has a `segment` (`model`, `extrapolated`, `crisis`, `reset`,
   `post_reset`, `post_reset_extrapolated`); years after the turn carry `segment_label`
   "crisis and reset (<policy>)", model-derived and distinct from `extrapolated`. The test bench
   shades extrapolated years grey and crisis and reset amber; the model card draws them as
   separate series, to 2039 and to 2080.
6. **Per-policy view.** `scenarios` holds one `ResolutionScenario` per policy, each with its own
   turn (year, level, crisis end, reset end), its path from the turn, and its monthly inflation,
   defaults, valuations and price level. `turns` on the projection documents every turn of the
   main path; `unbounded_saturation` keeps the path the model gives without the ceiling.

Turns on snapshot `SNP-41f60149296357f8` (turn year at turn level; x: in the extrapolated tail):

| Economy | Integrated | Depression | Hyperinflation | Stagflation | Deferral |
|---|---|---|---|---|---|
| BR | 5 of 56 | 2032 at 4.70 x | 2037 at 5.10 x | 2035 at 4.90 x | 2040 at 5.40 x |
| CH | 7 of 56 | 2031 at 4.70 | 2031 at 5.10 | 2031 at 4.90 | 2031 at 5.40 |
| CN | 10 of 56 | 2034 at 4.70 | 2034 at 5.10 | 2034 at 4.90 | 2034 at 5.40 |
| EU | 16 of 56 | 2037 at 4.70 | 2038 at 5.10 | 2037 at 4.90 | 2038 at 5.40 |
| IN | 58 of 58 | 2039 at 4.70 | 2040 at 5.10 | 2040 at 4.90 | 2040 at 5.40 |
| ID | 56 of 56 | none by 2080 | none | none | none |
| MY | 41 of 56 | 2064 at 4.70 | 2064 at 5.10 | 2064 at 4.90 | 2064 at 5.40 |
| PH | 39 of 56 | 2061 at 4.70 | 2062 at 5.10 | 2061 at 4.90 | 2062 at 5.40 |
| TH | 14 of 56 | 2038 at 4.70 | 2038 at 5.10 | 2038 at 4.90 | 2038 at 5.40 |
| GB | 11 of 56 | 2032 at 4.70 | 2033 at 5.10 | 2032 at 4.90 | 2033 at 5.40 |
| US | 36 of 56 | 2059 at 4.70 | 2060 at 5.10 | 2060 at 4.90 | 2060 at 5.40 |
| JP | 6 of 56 | none by 2080 | none | none | none |
| BD | 24 of 56 | none by 2080 | none | none | none |
| VN | 4 of 58 | 2026 at 4.70, again 2077 | 2026 at 5.10, again 2077 | 2026 at 4.90, again 2077 | 2026 at 5.40, again 2077 |
| DE | 25 of 56 | 2047 at 4.70 | 2047 at 5.10 | 2047 at 4.90 | 2047 at 5.40 |
| ES | 4 of 56 | 2028 at 4.70, again 2075 | 2036 at 5.10 x | 2032 at 4.90 x, again 2079 | 2042 at 5.40 x |

Maximum projected saturation in every economy under every policy: 5.40 (deferral's turn
level), below the band's upper bound. Crisis ends: depression 1.49, hyperinflation 1.36,
stagflation 1.91, deferral 3.20 (the turn level times the policy's correction). Still in the
extrapolation: BR (turn in the tail under every policy), ES (under hyperinflation, stagflation
and deferral), JP (no turn, tail 2031 to 2080) and BD (no turn, tail 2049 to 2080). Turn timing
is the weakest reading: near the singularity the unbounded path's growth dominates, so the four
policies mostly turn in the same year and differ in level.

Reset timing against cycle's capital cycle (C-16: reset, 90-year rise to the reordering, 40-year
fall to the next reset at 130): the crisis and reset together last 40 years, the same as cycle's
fall. Under stagflation the macrofield turn lands within five years of cycle's reordering
(reset + 90) in CH, ES, EU, GB, IN and CN, and later in US (+37), PH (+25), TH (+16), MY (+11) and
DE (+9); earlier in BR (-19) and VN (-50); JP, ID and BD have no turn by 2080.

Unchanged: 1.3.0 (and 1.0.0 to 1.2.0) project exactly as before, byte for byte, and the stored
artefacts read back unchanged.

### Calibration 1.5.0 (active): an integrable model (TB-08, TB-27)

Owner decision of 29.09.2026: fix the non-integrating fits and the exploding projections at the
model level rather than label the tail. 1.5.0 is 1.4.0 plus two changes; the soft ceiling, the
policies, crisis, reset and horizon are 1.4.0's (TB-20 confirmed).

**Diagnosis.** Every projection that stopped short of 2080 under 1.4.0, and every fit that did not
integrate its window (BR, CH, TH, JP, DE, ES), failed the same way. From the equations,
Y_dot - K_R_dot = (p_b - p_s) Y - p_p K_R + S, so real capital outgrows output whenever
p_p + p_s > p_b + S/Y, which holds in fourteen of the sixteen: K_R passes Y within 2 to 30 projected years (not in ID and BD).
Past that point the written investment share r = 1 - K_R/Y is negative and unbounded, the flow
r K_I drains output, a falling Y makes r more negative still, and Y reaches zero in finite time
while K_I explodes (K_R/Y above 1e5 and Y below 1e-5 of its start at the last step, in all twelve
economies that stopped). JP and BD failed differently: their last-year alpha (-3.0 and -0.46) is a
negative share of savings, which drains K_I through zero. The 1.4.0 turns were largely this
singularity: saturation first fell as r K_I moved financial into real capital, then shot up as Y
collapsed, which is why the four policies turned in the same year.

**Fix.** (1) The bounded investment share, r = max(0, 1 - K_R/Y), in the fit and the projection
alike: the written definition wherever K_R <= Y, and no reversal past it (financial capital stops
flowing into real capital once real capital has reached output). With 0 <= r <= 1 the right-hand
side grows at most linearly in the state, so no finite-time singularity exists for any parameter
value; with alpha in [0, 1] and S >= 0 the positive orthant is invariant too (dynamics.py,
property-tested). (2) Every parameter carried past the window, and every post-reset early-phase
parameter, is held inside `parameter_ranges` (`projection.parameters_within_ranges`), and the
notes name each one held. A regularised fit was not needed: with the bounded share all sixteen
windows integrate at reporting tolerance. Both fields are omitted from 1.0.0 to 1.4.0, which hash
and project exactly as before.

**Result** on snapshot `SNP-41f60149296357f8` (turn year, at the policy's turn level; no turn is in
an extrapolated tail and none repeats by 2080):

| Economy | Integrated | Fit | Depression 4.70 | Hyperinflation 5.10 | Stagflation 4.90 | Deferral 5.40 |
|---|---|---|---|---|---|---|
| BR | 56 of 56 | reporting (was none) | 2067 | 2072 | 2069 | 2075 |
| CH | 56 of 56 | reporting (was none) | none | none | none | none |
| CN | 56 of 56 | reporting | 2060 | 2076 | 2067 | none |
| EU | 56 of 56 | reporting | 2056 | 2059 | 2058 | 2062 |
| IN | 58 of 58 | reporting | 2072 | none | 2077 | none |
| ID | 56 of 56 | reporting | none | none | none | none |
| MY | 56 of 56 | reporting | none | none | none | none |
| PH | 56 of 56 | reporting | none | none | none | none |
| TH | 56 of 56 | reporting (was none) | 2070 | 2074 | 2072 | 2077 |
| GB | 56 of 56 | reporting | 2047 | 2050 | 2049 | 2052 |
| US | 56 of 56 | reporting | none | none | none | none |
| JP | 56 of 56 | reporting (was none) | none | none | none | none |
| BD | 56 of 56 | reporting | none | none | none | none |
| VN | 58 of 58 | reporting | 2043 | 2046 | 2045 | 2047 |
| DE | 56 of 56 | reporting (was none) | 2076 | none | none | none |
| ES | 56 of 56 | reporting (was none) | 2039 | 2041 | 2040 | 2042 |

TB-26 re-examined. Tail turns: none (were BR under every policy, ES under three). Second turns:
none by 2080 (were VN and ES): the earliest first turn is ES in 2039, whose reset ends in 2079.
Turns now differ by policy, by up to 16 years (CN). No turn by 2080, and why:

* ID and BD: the fitted population term is 3 to 4 times population growth (p_b 0.03 to 0.04)
  against a return p_p at its floor of 0.005, so output outgrows capital, K_R never reaches Y
  and saturation falls to about 0.05 by 2080.
* CH and US: p_b 0.05 (CH held at its upper bound, US p_b correction 5.2) above p_p 0.015 to
  0.020; saturation drains from 3.9 and 3.5 to about 0.9 by the mid-2030s and recovers only to
  1.2 and 2.7 by 2080.
* JP: saturation drains from 5.2 to about 2.0 by 2030 and stays there (p_p and alpha held at
  their floors, p_b 0.010).
* MY and PH: saturation bottoms at 1.0 and 0.7 in the 2030s and reaches 3.8 and 2.6 by 2080,
  still below the lowest turn level.
* IN (hyperinflation, deferral), DE (all but depression) and CN (deferral): the unbounded path
  reaches 5.9 to 6.5 by 2080, but under the soft ceiling it does not reach the higher turn levels
  in time.

The common cause is the other half of TB-08, still open: the identity corrections (largest
departure from one 0.9 to 9.9 across the sixteen) and, at the window end, a large r K_I flow that
lowers saturation by 24 to 41 per cent in the first projected year in CH, TH, US and JP.

**Activation.** Active since 29.09.2026 by the owner's decision (TB-28), although the fit changes in all
sixteen economies (six gain a simulated path, the other ten are refitted because their simulated path
already ran above K_R = Y in the window, where the bounded share differs). What aggregation
and cycle read is identical to 1.4.0 in all sixteen economies (years, inputs, diagnostics and
phases, current state, phase history, observed Y, projection years to 2080), so 1.5.0 does not
change the Regime for the observed years; it changes the fit report, the simulated
path and the projection (phases, transitions, turns and scenarios), which neither reads.


## Model quality

**Golden reconciliation.** `golden/` holds the old build's output for BR, CH, CN, DE, GB, IN
and US, frozen offline from its own cache (`dev/freeze_golden.py`); `data/raw` holds the same
files. Declared tolerance: inputs, identities, phases and diagnostics exact; fitted parameters
and simulated paths to a relative 1e-9. On the build machine everything reproduces exactly,
fitted parameters and simulated paths included. One intentional divergence: where the fitted
path integrates at no tolerance, the old build labelled it `search`; this engine says `none`.

**Property tests** (`hypothesis`): the two-body identity holds to 1e-12 and the Genreith
residual equals S for any state and parameters, in both closure modes; the balanced-growth
closed form is reproduced; the normalisation leaves K_R/K_I unchanged and puts max K_R/Y at the
target; the uplift is level only; every period gets exactly one phase with the documented
precedence; the latch only ever holds Phase 4 or releases to Foundation; a gap is dropped and
listed, never filled; a missing input names itself.

**Quality surfaced on every run** (`/runs/{id}`): unavailable economies with the reason, stale
current states, fits that did not converge or do not integrate, extended capital years; per
economy the fit report (standard errors, identifiability, residuals, identity corrections,
two-body residual) and notes naming the binding series of each window.

What the first run shows, snapshot `SNP-98ca1e0341dd1bdd`: 11 economies available, 5
unavailable. The identity corrections depart from one by 120 to 750 per cent everywhere, and 5
of the 11 fitted paths do not integrate at all (BR, CH, DE, ES, TH). The simulated dynamics
are therefore weak evidence; the phase and saturation readings rest on observed ratios, as they
did in the old build.

## Data need

The engine runs on a frozen snapshot, and says exactly what a live feed must supply:
`data_need.csv` (T5 format: `proposed_series_id | model | index_block | country_or_scope | ...`),
also `GET /data-need`. Ten series per economy: World Bank GDP, investment share, real growth,
savings rate, fiscal balance, population; BIS total credit to the non-financial sector; PWT
`cn`, `cgdpo`, `delta`. All required inputs are in snapshot `SNP-41f60149296357f8` for all 16 economies. Two
series the model's definitions call for are still unsourced:

| Series | Would replace | Candidate |
|---|---|---|
| OECD consolidated financial assets (book 10.4's primary K_I) | K_I from credit | OECD SDMX DF_T7PS1S2 |
| Credit to the financial sector | The 1.4 credit uplift | Fed Z.1, ECB QSA |

Frequencies are the sources' own (annual, BIS quarterly taken at Q4), not T5's monthly panel;
the model is annual.

## Decisions and open points

| Id | Point | Status |
|---|---|---|
| TB-01 | The three-body model is the Macro Field engine (Engine 03): module `macrofield`, port 8003, contracts `MacroRunRequest` / `MacroState` (renamed from `threebody` on 27.09.2026) | Taken |
| TB-19 | Engine 03 is the three-body core only: `MacroRunRequest` is `{snapshot_id, economies?, calibration_version?}` and `MacroState` carries no cycles and no 25-state distribution. The five nested cycles sit in `cycle` (Engine 12), the 25-state distribution in `aggregation` (Engine 04). No HoNI input: `aggregation` reads `mrs`, `cycle` and `macrofield` side by side, all from the same `snapshot_id`; HoNI is used by the CIO outside the automated flow | Decided 27.09.2026 (inputs of `aggregation` restated the same day) |
| TB-02 | Store is PostgreSQL (Guide) rather than the task page's local SQLite; the "static data" is the frozen snapshot | Taken |
| TB-03 | The old CLI `calibrate` omitted population growth (p_b flow ratio, path explodes); the cockpit path is the model of record | Taken |
| TB-04 | Japan: the old build's central-bank-assets proxy was never wired; reproduced as fiscal balance without sign reversal, which the World Bank does not publish, so JP is unavailable | Open: source a stimulus series |
| TB-05 | EU: no PWT capital stock. The old DE/FR proxy is not carried over | Open: AMECO |
| TB-06 | ES, ID, MY, TH settings are assumed (fiscal proxy, depreciation prior of their peer group) | Open: review |
| TB-07 | The Phase 4 latch holds GB, ES, MY and TH in Saturation at about 3.1, below the 3.5 ceiling, because their 2020 denominator spike crossed it | Open: author's rule, revisit |
| TB-08 | The identity corrections (1.2 to 7.5 away from one) and 5 non-integrating fits say the equations as written do not describe the data; the Paper 1 F/G/H form is not written down in Notion or code | Integrability fixed in 1.5.0 (TB-27, owner decision 29.09.2026): every fit and projection integrates. The identity corrections remain (0.9 to 9.9 from one in 1.5.0): open, book ch. 7 to 8 |
| TB-09 | Accuracy label `none` where the old build said `search` with no path | Taken, divergence recorded |
| TB-10 | `refuse_above = 6.0` is applied in the core (the old build applied it only in the regime timeline); nothing reaches it | Taken |
| TB-11 | K_I, not K_F, as in the build brief and the old code | Taken |
| TB-13 | Germany reads Build-up: no Phase 4 condition fires in the data held (credit from 1998 only). A longer history (e.g. BIS series before 1998, or an author-supplied reset anchor) is needed to show a saturation episode | Open |
| TB-14 | The projection seeds its latch from the window's last phase, where the old build classified the end state afresh | Taken |
| TB-15 | Germany on the bank balance-sheet axis, others on credit: Germany's saturation is not like for like with the rest of the panel. Moving everyone to bank balance sheets needs a source per country | Open |
| TB-16 | JST is licensed CC BY-NC-SA (non-commercial); used for German GDP before 1990 | Open: licence check |
| TB-17 | HoNI's "EU" is modelled as the euro area (20 members, 2023 composition) | Taken |
| TB-18 | Weak-evidence projections (fit not reproducing the window) are shown rather than refused | Taken, flagged |
| TB-12 | Raw files for the 8 old economies are the old cache (World Bank vintage of July 2026); the rest were fetched on 2026-09-27. Mixed vintages are recorded per file | Taken; a refreeze is a new snapshot |
| TB-20 | R-005 soft ceiling: centre 5.0, band 4.5 to 5.5, growth damped from 3.5 on a sine arc in logs (dx/dt = g sqrt(1 - u^2)), so the path bends and meets its turn level with zero slope; no clamp. Turn position per policy: depression 0.2 (4.7), stagflation 0.4 (4.9), hyperinflation 0.6 (5.1), deferral 0.9 (5.4) | Ceiling decided by Nicolas 28.09.2026; onset 3.5 and turn levels 4.7, 4.9, 5.1, 5.4 confirmed by the owner 29.09.2026 as calibration 1.4.0's values (carried unchanged into 1.5.0) |
| TB-21 | The four Phase IV policies are `Scenario_SAA.m` v0.1 exactly (target mix, inflation, defaults, valuations), frozen in `golden/scenario_saa/` with the file's SHA-256; Engine 09 `scenario` is to use the same ids and values. In the model: nominal output at the policy's price level (real output flat), K_I x defaults x valuations. The target mix is carried, not used here | Taken (R-005) |
| TB-22 | Default policy `stagflation`, the template's selected case (`s=3`) | Taken: confirmed by Nicolas 28.09.2026 (R-005) |
| TB-23 | Crisis 60 months, then a 35-year reset (30 to 40 allowed) to the Foundation level, 0.95 x the Foundation ceiling (strictly inside Phase 1, so the latch releases when the reset ends); per-economy overrides need a reason (none set). Over the reset output grows at its observed rate and K_R/Y returns to its early-phase level (held at the turn it stays above 1 in CH, CN, GB, ES, where r < 0 and nothing integrates). Phase 4 through crisis and reset, then classified afresh. Re-integration with the mean fitted parameters of the window's Phase 1 and 2 years | Taken (R-005); the reset shape (half cosine) and the K_R/Y return are this build's choice |
| TB-24 | The model computes to 2080, views show 2039; years after 2039 carry `lower_confidence`. cycle projects its anchored cycles to macrofield's last projected year (C-22), so it sees 2080 on its first run after a 1.4.0 macrofield run | Taken (R-005); cycle informed through the report |
| TB-25 | 1.4.0 made active: its observed-period outputs (inputs, diagnostics, current state, phase history, fit, simulated path) are identical to 1.3.0 and to the stored artefact `MFS-6183873b127fcd58` in all 16 economies. Every calibration's idempotency key changed (engine 0.5.0, contract versions), so the next `POST /run` of any version makes a new artefact id | Taken 28.09.2026 |
| TB-26 | After the reset, VN and ES (and CH, CN, GB before the K_R/Y return) turn a second time around 2075 to 2079: the re-integrated early-phase model still grows fast. BR, and ES under three policies, turn in the extrapolated tail; JP and BD never turn and run into the tail for 50 and 32 years | Re-examined under 1.5.0 (29.09.2026): no tail turns and no second turns by 2080; CH, ID, MY, PH, US, JP and BD do not turn by 2080 under any policy, IN, DE and CN under some, because of the fitted p_b against p_p (TB-08's identity half). Open with TB-08 |
| TB-27 | Calibration 1.5.0: investment share bounded at zero, r = max(0, 1 - K_R/Y), in fit and projection (identical where K_R <= Y; no finite-time singularity for any parameters), and parameters carried forward or re-integrated after the reset held inside `parameter_ranges`. New optional fields `investment_share` and `projection.parameters_within_ranges`, omitted while unset; Calibration contract 1.5.0, engine 0.6.0; `macrofield-state@1.2.0` unchanged | Taken 29.09.2026 (owner chose the fix over labelling TB-26) |
| TB-28 | 1.5.0 is the active calibration. Its fits differ from 1.4.0 in all sixteen economies; what aggregation and cycle read is identical, so the Regime's observed years are unchanged and only the fit report, simulated path and projection change | Taken: activated by the owner on 29.09.2026 (`active: "1.5.0"`); 1.4.0 stays stored |
| TB-29 | Under 1.5.0 the first projected year drops saturation by 24 to 41 per cent in CH, TH, US and JP: the projection starts from the observed end state, where r K_I moves 17 to 50 per cent of K_I into K_R a year | Open: with TB-08 |

British spelling. No em dashes. Not investment advice.
