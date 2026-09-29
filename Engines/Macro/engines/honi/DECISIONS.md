# honi: decisions index

Every place this build departs from `HoNI2.m`, from the HoNI Build Manual, or from a
convention, with the reason. The golden test classifies divergences against this list:
a difference that is not here is a bug.

## The nine known defects (Build Manual section 9)

| Defect | Status in 1.0.0 | Where it shows |
|---|---|---|
| 9.1 Missing data scores as worst | **Fixed.** A missing index is excluded and its sector re-weighted; a sector needs 3 of 5 indices (D-15). Coverage is recorded per country-year on `/runs/{id}`. Calibration `0.1.0-matlab` keeps the old behaviour for reconciliation only. | `test_golden.py::TestMatlabExport::test_default_calibration_departs_only_where_data_is_missing` |
| 9.2 NaN / zero round trip | **Fixed.** One convention end to end: missing is NaN (null on the wire), zero is a number. This includes a growth rate of exactly 0, which `HN_money_supply.m` discarded. | `matlab_reference.ZERO_GROWTH_IS_MISSING` |
| 9.3 Capital saturation units | **Checked, not closed.** On the 2026-01-05 snapshot the median is 3.15, a third of country-years fall in the 2.5 to 3.5 band, and 2025 spans 0.78 (Bangladesh) to 4.66 (Japan). Plausible, but the BIS financial-debt scale per country is a feed question. | `/saturation/{id}` |
| 9.4 Broad money is not one aggregate | **Documented, not fixed.** USA carries M3, China M2 (datafeed `GET /series/money.broad_money`). Harmonisation belongs to the datafeed registry. | |
| 9.5 Hard-coded country patches | **Removed.** India x3 and UK x0.3 on consumption dependency are not in the model. datafeed's plausibility check shows why they existed (India's series is quarterly, the UK's in another unit, and four more countries alike); calibration 1.1.0 drops the index there instead (D-23). | layer B excludes IN and GB consumption dependency |
| 9.6 Annualisation by sampling | **Fixed.** The annual value is the December observation (`annualisation: year_end`), or the calendar-year mean (`mean`). See D-11. | |
| 9.7 Fragile loop bound | **Gone.** Scoring is vectorised. | |
| 9.8 Stale `A_TS.mat` | **Gone.** Countries come from the request, `config.yaml` and the panel. | |
| 9.9 Empty placeholders | **Not ported.** `VitalStats`, `Stats` and `HN_gdp_growth.m`. | |

## Decisions taken in this build

**D-01 Anatomy.** The Guide's section 2 layout, plus four files it does not name:
`service.py` (orchestration, so `api.py` stays routing only and `engine.py` stays pure),
`settings.py` (configuration), `schema.sql` and `__main__.py` (`python -m honi`). From the
Instruments engine: the PostgreSQL store conventions, the configuration precedence, the
tests against a real server in throwaway schemas, the concurrency test, the test bench and
`start.cmd`.

**D-02 Where the Guide and the Instruments engine differ, the Guide wins.** `config.yaml`
rather than TOML; `numpy` rather than hand-written numerics; unversioned standard endpoints
rather than `/v1`; Plotly from CDN for the test bench; a deploy folder.

**D-03 Data comes from datafeed only.** honi reads no source file and no source table.
`contracts.Panel` and `contracts.UpstreamCoverage` mirror datafeed's `panel@1.1.0` and
`coverage@1.0.0`; if they disagree with datafeed, the mirror is the bug. Even honi's golden
input is fetched from datafeed (`golden/build_golden.py`) and checked against datafeed's
checksum.

**D-04 Identity.** `idempotency_key = IDK-hash(snapshot_id, countries, window,
calibration content hash, engine_version, contract_versions)`. An omitted window enters the
key as "last N years" with N from `config.yaml`. `artefact_id = HNS-hash(payload)`, so an
artefact id is also an integrity check. A repeated request is answered with the run that
made the artefact (`cached: true`); no new run is recorded.

**D-05 `psycopg` is outside the allowlist.** The Guide mandates PostgreSQL, and a driver is
unavoidable. `/meta` reports the check live.

**D-06 Calibration versions.** Seeds live in `calibration.py` and are immutable: a changed
seed with an old version number stops the engine at start-up. `PUT /calibration` adds a
version and never activates it; the active version is `calibration.active` in
`config.yaml`, changed deliberately. The database refuses UPDATE and DELETE on calibrations
and artefacts.

**D-07 Three seeds.** `1.1.0` (active: 1.0.0 plus the datafeed gate, D-23), `1.0.0`
(defects fixed) and `0.1.0-matlab` (reproduces `HoNI2.m`, defect 9.1 included). The last
exists to reconcile against MATLAB and to show the effect of the fix; runs under it carry a
"not for publication" warning.

**D-08 Transfer functions stay piecewise linear** (Build Manual open decision 1). Moving to
true curves would invalidate the calibration triples. They are named for what they are:
MATLAB "Sigmoid" is `ramp`, MATLAB "Poly" is `tent`.

**D-09 Double cross-sectional rescaling is kept** (open decision 2), as in MATLAB, so scores
remain relative: every year the best country scores 5 and the worst 1. It is switchable per
calibration (`rescale_sectors`, `rescale_national`) for the day an absolute scale is wanted.

**D-10 Golden tolerance 1e-12, reconciled in three layers.** No input matches the one
MATLAB export we hold (see `golden/README.md`). Layer A: scoring and aggregation against
the export itself (agrees to about 2e-15). Layer B: indicator formulas against a literal
transliteration of the `HN_*.m` functions on every cell no defect touches (about 87% of
cells). Layer C: end to end against the frozen output of this build (regression only).

**D-11 MATLAB's annual values depended on the month it ran.** `A_TS = M_TS(1:12:end,:)`
samples every 12th month from the first row, and the first row is the loader's run month:
the 2025-11 export sampled Novembers, the 2026-01 file samples Januaries. `timeHoNI =
2004:2024` is hard-coded, so on the current file the labels are also a year off. The
engine uses calendar years from the panel's dates.

**D-12 The first growth rate is missing, not zero.** `HN_pop_growth.m` and `HN_real_gdp.m`
wrote 0 for the first year, which imputes a value.

**D-13 One trailing-mean rule.** Five years, shrinking at the start of the series as MATLAB
`movmean(x,[4 0])` does, skipping missing years (`trailing_min_obs: 1`). MATLAB skipped
them in three indicators and propagated them in two (`real_rate_10y`, `terms_of_trade`).

**D-14 Exact anchors.** The ramp scores exactly 2.5 at its mid-point and the tent exactly 5
at its peak; MATLAB's arithmetic missed both by one ulp. Inside the tolerance.

**D-15 Aggregation thresholds.** A sector is scored from at least 3 of its 5 indices; the
national score needs all three sectors. Both are recorded in the coverage report.

**D-16 Corruption freedom is an International Resilience index,** as `HoNI2.m` computes it,
although the comment above its range in the same file lists it under Real Economy.

**D-17 Twenty-one input series.** The Build Manual says HoNI uses sixteen, and then lists
twenty-one. The engine reads twenty-one (`engine.REQUIRED_SERIES`).

**D-18 Default window: the last 20 complete calendar years** in the snapshot, matching the
MATLAB 21-point history less its partial year. Configurable (`run.default_window_years`).

**D-19 Turning MATLAB zeros back into gaps (golden snapshot only).** `M_TS` stores missing
values as 0. NaN, leading and trailing zeros become missing; interior zeros are kept in
rate and balance series (where 0.0 is a plausible print) and become missing elsewhere.
Counts per series are in the manifest.

**D-20 `regime_id` is null.** HoNI sits upstream of the Regime; the field exists so the
binding rule reads the same on every artefact.

**D-21 Peer statistics use linear percentiles** (`numpy.percentile`). There is no MATLAB
reference for them.

**D-22 Country codes** are ISO 3166 alpha-2, with `EU` for the European Union, the same
codes datafeed uses.

**D-23 The datafeed gate.** Before a run honi reads datafeed's `/coverage`. Calibration
1.1.0 maps datafeed's `consumption_share` finding to the index `consumption_dependency`:
for a flagged country that index is treated as missing and its sector re-weighted, and the
exclusion is listed in the run's coverage (`excluded`). Scoring an input known to be in the
wrong unit would put a number on noise; the tent would simply return 1.

**D-24 The first year of a snapshot has no growth rates.** Population growth and
GDP-per-capita growth need a prior year (D-12), so on the 2006-2025 snapshot 2006 cannot
carry a full real-economy sector. The default window is therefore 19 years, 2007-2025
(D-28). On the production snapshot the only missing national scores are Bangladesh
2007-2010, where external debt is missing and the terms of trade is a placeholder, leaving
International Resilience with 2 of 5 indices.

**D-25 Contract versions.** `honi-scores@1.1.0` adds `coverage.public_fills` and
`coverage.excluded`; `honi-calibration@1.1.0` adds `exclude_on_plausibility`. The seed
payloads changed with the contract version, so the development store's `honi` schema was
rebuilt once (2026-09-27); seeds are otherwise never edited.

**D-28 Decisions of 2026-09-27, in force:**
- Default window **19 years (2007-2025)**, so no published year lacks growth rates
  (`run.default_window_years`).
- **MATLAB is retired as a reference.** The current build is the reference; the
  MATLAB-based golden layers A and B stay only as regression checks.
- Scores **stay relative** (per-year rescaling kept, D-09 confirmed).
- datafeed now carries household consumption in GDP's unit for all 16 countries (DF-16),
  so on the production snapshot the 1.1.0 gate excludes nothing. The gate stays active as a
  guard; it still acts on snapshots that carry the old series (e.g. the raw one).

**D-27 One country registry.** honi keeps no country list of its own: valid codes and
display names come from datafeed (`GET /countries`, table `country`) at the start of every
run. `config.yaml` holds only the default peer set as codes. Without datafeed a run is
refused with 503 before anything is recorded.

**D-26 Layer C refrozen once** (2026-09-27): datafeed stopped importing placeholder tickers
as data (datafeed DF-13), which removed four constant-1.0 input series (BD terms of trade,
PH and VN corporate debt, VN wage growth). The frozen input and its expected output were
rebuilt from datafeed; layers A and B were unaffected.

**D-29 Trends are computed by honi, on read (2026-09-27).** `HoNI_Lite.xlsx` showed each
figure with its "Trend (10y)" and "Level*" (z-score over the last 10 years). The CIO
interface (the cockpit) may not compute, so `GET /trends/{id}` publishes them, like the peer
statistics: from a stored artefact, never stored separately (`honi-trends@1.0.0`). For every
series (national, the three sectors, capital saturation, each index score and raw value) and
country: the value in the chosen year, the value `window` years earlier, their difference,
the least-squares slope per year over the `window` years ending with the chosen year, and the
z-score of the latest value against those years (standard deviation with ddof 1). A slope or
z-score needs half the window (at least 3) years with a value; below that, with a missing
latest value, or on a flat window it is null. Nothing is interpolated. Scores are relative,
so a trend in a score is a trend in the country's position within the peer set.

**D-30 The model explains itself: `GET /model` (owner, 2026-09-28).** The owner wants every engine shown in one style on the cockpit's Models page: what comes in (plain names), what it looks like, what gets calculated (the functions with their maths, and charts) and what goes out. `GET /model?economy=` returns a `model-card@1.0.0`, the same shape in every engine (each keeps its own copy of the contract). The card is a view, not a result: it is not in `CONTRACT_VERSIONS`, which feeds every idempotency key and artefact id, so it never changes a published id. HoNI is relative, so the card runs the whole model on the default peer set and datafeed's current snapshot with the engine's own functions, and shows one economy step by step next to its peers: presence of the inputs, the fifteen indicators against the peer median, each transfer curve with the economy's point, the sector means, the rescaling across peers, the national score and ranking, capital saturation. A test checks its national and index scores against a normal run, cell for cell.

