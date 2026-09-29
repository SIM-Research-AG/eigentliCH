# Engine 05: Market Risk Signal (`mrs`)

Reads the market series from `datafeed`, computes the whole of `Market_Signal.m` (MATLAB
Master Controller) and publishes a **`MarketRiskSignal`** to the aggregation layer
(`aggregation`, Engine 04): per economy and month, each once, the eleven sub-indicators, the
four segment signals and a 25-state distribution (state 1 most cautious, 25 most
aggressive), at **zero optimism shift**, with `regime_id: null`. Optimism, the market blends
and the `regime_id` belong to `aggregation` (MRS-13, MRS-18). Built to the Engine Building
Guide in the same shape as `honi`.

> Model-derived research output. The distribution is an assessment of the current
> environment, not a forecast. **Not investment advice.**

| | |
|---|---|
| Module | `mrs` |
| Default port | 8005 (configurable) |
| Status | v1.0.0 (28.09.2026). Indicator layer ported; golden against the CIO export reconciled to 3e-14; 116 tests |
| Consumes | `Panel` from `datafeed` (8001): the 29 `M_TS` series plus `volatility.skew` and `fx.neer_broad`, snapshot from `config.yaml` |
| Produces | `MarketRiskSignal` (`mrs-signal@1.0.0`) |
| Downstream | `aggregation` |

## Model

Two modes, chosen by the calibration (`src/mrs/indicators.py`, `src/mrs/engine.py`):

1. **Sub-indicators** (`MR_*.m`, with `ema`, `kst`, `macd2`, `momentum`, `roc`, `sar`):
   inflation, monetary, consumer, company (business cycle); bond, equity (investment);
   trend/oscillation, fear/greed (market behaviour); global stability, market stability,
   monetary uncertainty (market stress). Leading, concurrent and lagging parts weighted
   0.5 / 0.25 / 0.25.
2. **Segments**: business cycle, investment and market behaviour are z-scores of the
   weighted indicators; market stress is their weighted sum (flags and a clipped ratio).
3. **Distribution**: each segment reading is binned on `linspace(-2, 2, 11)`; business
   cycle, investment and behaviour contribute a `binopdf(0:8, 8, 0.5)` band that slides two
   states towards cautious per column; stress contributes a `binopdf(0:8, 8, 0.1)` tail on
   states 1 to 9, live from column 6. Weighted 0.25 each and summed (MATLAB's `CRS` row,
   kept as `raw_mass`), then normalised to 1. `state` is the mode, ties to the cautious side.

| | `2.0.0` (production, active) | `2.0.0-matlab` (reconciliation) |
|---|---|---|
| Input view | datafeed's panel, a gap stays a gap | MATLAB's `M_TS`: gaps 0, placeholder tickers 1.0 |
| Normalisation | data up to each month only: 24 months for an input, 12 for a combination | full sample (`normalize`, `detrend`) |
| Missing | a missing part reads as the average inside an indicator; an indicator (segment) with nothing to read is missing; a date needs 3 of 4 segments, the rest re-weighted (MRS-04, MRS-17) | NaN as MATLAB: 0 inside, column 1 in the distribution |
| Inputs | Cboe SKEW, BIS NEER, high-yield yield to worst (MRS-15) | Fear Barometer, JPM BEER, high-yield index level |
| Thresholds | data units: VIX 0.20 / 0.02, senior loan relative 0.005 (MRS-16, MRS-19) | MATLAB: 20 / 2, 0.10 on price |

Kept on the owner's rulings (27.09.2026) in both: central differences in `gradient`, the
gold-window overwrite, the `T./T + T` quirk, OIS as a level. See [DECISIONS.md](DECISIONS.md)
for every divergence and the open points.

## Run it

From this folder, with the Macro venv (`..\..\.venv`):

```bat
docker compose up -d                  :: in Projects\PostgreSQL, once
pip install -e .[dev]                 :: once
python -m mrs init-db                 :: once per server: database, schema, seed calibrations
python -m mrs init-db --rebuild       :: once, to leave a v0.1.0 store (drops mrs's own tables only)
python -m mrs load-reference          :: optional: the CIO signal export as reference rows
start.cmd                             :: or: python -m mrs serve
```

```bash
curl -X POST localhost:8005/run -H "Content-Type: application/json" -d '{}'   # config snapshot, active calibration
curl -X POST localhost:8005/run -H "Content-Type: application/json" \
     -d '{"snapshot_id": "bloomberg-2026-01-05", "calibration_version": "2.0.0"}'
curl "localhost:8005/runs?limit=5"                        # newest first: find the latest artefact
curl localhost:8005/artefacts/<artefact_id>               # the MarketRiskSignal
curl "localhost:8005/signal/<artefact_id>/distribution?date=2025-12-31&economy=US"
curl "localhost:8005/signal/<artefact_id>/segments?economy=US"
curl localhost:8005/signal/<artefact_id>/current
curl localhost:8005/input                                 # the datafeed input, checked
```

```bash
python -m pytest                          # 119 tests: real container, real datafeed (bootstrapped offline)
python golden/build_golden.py             # refreeze the golden input from a running datafeed
python dev/make_deploy.py <folder>        # deploy folder: src, config, README, DECISIONS only
```

## Endpoints

Standard (Guide section 2.1): `/health`, `/meta`, `/contracts`, `POST /run`, `/runs/{run_id}`,
`/artefacts/{artefact_id}`, `GET`/`PUT /calibration`. Engine-specific, additive:

| Method | Path | Notes |
|---|---|---|
| POST | `/run` | `MRSRunRequest` (`mrs-run@2.0.0`): `{snapshot_id?, calibration_version?}`, defaults from `config.yaml`. Answers `{run_id, status, artefact_id, idempotency_key, cached}`. 404 unknown snapshot; 422 unknown calibration or an old v0.1.0 body. |
| GET | `/runs?limit=` | Recent runs, newest first: `{run_id, status, artefact_id, snapshot_id, calibration_version, finished_at}`. |
| GET | `/signal/{artefact_id}/distribution` | 25-state distribution, modal state and raw mass at `date=` (default: last month), per economy (`economy=`, repeatable). |
| GET | `/signal/{artefact_id}/segments` | The four segment signals over time, per economy. |
| GET | `/signal/{artefact_id}/current` | Latest assessed month per economy: date, state, distribution, segments. |
| GET | `/model?economy=` | The model explained on one economy's data: inputs, every step with its formula, parameters and charts, outputs (`model-card@1.0.0`, the cockpit's Models page, MRS-25). |
| GET | `/input` | The datafeed snapshot mrs reads (`snapshot_id=`), read live and checked (`mrs-input@1.0.0`). |
| GET | `/calibration/versions` | Stored calibration versions, active flagged. |

## The output contract (`mrs-signal@1.0.0`)

```
contract_version "mrs-signal@1.0.0", artefact_id "MRS-<16 hex>" (content hash), n_states 25
dates             month-end ISO dates, consecutive
indicator_names   the eleven sub-indicators, fixed order
segment_names     business_cycle, investment, market_behaviour, market_stress
economies[]       code, name, indicators{name: [..]}, segments{name: [..]},
                  distribution[[25] | null], raw_mass[.. | null], state[1..25 | null]
coverage          per economy: dates assessed / unassessed, first and last assessed,
                  segment_gaps, indicator_gaps, inputs_missing; indicator_mode,
                  missing_policy, min_segments, inputs
provenance        snapshot_id, as_of, upstream {"datafeed": <panel sha256>}, engine_version,
                  contract_versions, calibration_version, calibration_hash,
                  idempotency_key, regime_id null, label "model-derived"
notice            "... Not investment advice."
```

No raw series (they are in datafeed), no market blends (aggregation), nothing else
derivable except `state`, kept on request.

## Calibration

Versioned, immutable, in the store; seeded from `src/mrs/calibration.py`: `2.0.0`
(production, active) and `2.0.0-matlab`. No optimism: `mrs` publishes at zero shift. The
v0.1.0 seeds (`0.1.0-matlab`, `1.0.0`, `1.1.0`, with optimism and market blends) are kept as
the record in `calibration.RETIRED` and cannot be run.

## Quality

* `tests/test_golden.py`: the CIO site exports of one MATLAB run (`assets` in, `stats` and
  `signal` out, `golden/cio_*_2026-09/`) under the `matlab` calibration. Every sub-indicator
  and segment value of 16 economies and 241 months matches `stats` to 3e-14 (tolerance
  1e-10); with MATLAB's "Default" +0.4 applied in the test only, 15,423 of 15,424 kernel
  columns match `signal` to 1e-16, the one divergence an on-edge reading (MRS-01). The
  export is a pull of September 2026, not the local `M_TS.mat` (MRS-20).
* `tests/test_indicators.py`: MATLAB semantics of the primitives; production properties
  (no look-ahead beyond the ruled central difference, a gap is never a number, warm-up).
* `tests/test_matlab.py`: kernels, grids, column selection and whole `CRS` rows against a
  literal transcription of `Weights.m` and `Market_Signal.m` (`tests/matlab_reference.py`).
* `tests/test_engine.py`: property tests on the distribution and the output contract.
* `tests/test_input.py`: the input, the frozen raw snapshot and MATLAB's view of it.
* `tests/test_api.py`: the HTTP surface on a bootstrapped datafeed, caching, run listing,
  failed runs, the store (append-only, no single precision, every table documented, the
  v0.1.0 store refused until rebuilt).

## Anatomy

```
engines/mrs/
  README.md  DECISIONS.md  HANDOVER.md  pyproject.toml  config.yaml  start.cmd
  src/mrs/
    api.py          FastAPI routing only
    contracts.py    Pydantic models: MRSRunRequest, MarketRiskSignal, Calibration, datafeed mirrors
    indicators.py   pure: the eleven sub-indicators and four segments, matlab and production
    engine.py       pure: kernels, binning, distribution, assembly
    calibration.py  seed calibrations (versioned, immutable) and the retired v0.1.0 ones
    clients.py      the typed datafeed client (coverage, panel, countries, conversions)
    inputs.py       pure: the panel as matrices; production view (gaps NaN) and MATLAB view
    series.py       the series mrs reads, by datafeed id
    reference.py    the CIO signal export as reference rows
    service.py      run lifecycle, idempotency, read views
    store.py        PostgreSQL persistence (schema mrs, append-only)
    settings.py     config.yaml < config.local.yaml < MRS_* env
  tests/            unit, property, MATLAB reconciliation, golden, API
  golden/           snapshot_2026-01-05/ (datafeed's raw snapshot, frozen by build_golden.py),
                    cio_assets_2026-09/, cio_stats_2026-09/, cio_signal_2026-09/ (one MATLAB run)
  dev/              deploy builder
```
