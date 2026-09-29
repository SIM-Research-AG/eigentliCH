# fmre — Fund Map and Return Estimation

Implementation of the *Fund Map and Return Estimation Programme* per [CLAUDE_CODE_fund_map_return_estimation_program.md](CLAUDE_CODE_fund_map_return_estimation_program.md). Version 0.1.0.

## What this is

Two modules on one compute path.

**Fund Map** — the instrument-universe register and the time-series ingestion layer. It defines the building blocks (id, ticker, role, region, currency, liquidity, seed `ret_distribution`), pulls their series via a source (Bloomberg / CSV / synthetic), harmonises them (magnitude, unit, periodicity, currency), and computes period returns.

**Return Estimation** — the engine. Given a Regime timeline produced by the macro field-model programme, it maps each block's return history onto the 25-state regime grid, estimates the per-state return distribution data-driven, falls back through a labelled cascade (PCHIP interpolation → role-and-region peer borrow → seed IC values), aggregates to 5 scenarios via a versioned partition, and emits a `ReturnSet` contract.

The contract carries per-block scenario profiles and role-level aggregates. It does **not** carry `mu`, `sigma`, or covariance — the downstream optimiser integrates the profile against a mandate through an asymmetric squared-shortfall objective, never through a frontier.

## Install

```bash
pip install -e ".[dev]"
```

That gives you the `fmre` CLI, all dependencies (pandas, numpy, scipy, jinja2, pyarrow), and pytest.

For Bloomberg support (currently a stub — see [decisions.md](decisions.md)):

```bash
pip install -e ".[dev,bloomberg]"
```

## Run the test suite

```bash
pytest
```

189 tests covering seed integrity, ingestion invariants, per-state estimation, mixture recomposition, coverage-and-resilience, contract schema, determinism, house-view superposition, JSON schema, and full-seed integration.

## Quick tour: build a ReturnSet and render the worked reading document

The synthetic source is wired in for testing; swap `--source csv` (with `--data-root PATH`) once real series files are on disk. If the `fmre` command isn't on `PATH` after `pip install`, use `python -m fmre.cli` instead — every example below works either way.

```bash
# 1. Estimate all 54 seed blocks against the synthetic regime timeline
#    (--source seed-aware-synthetic uses the seed ret_distribution as
#     state-conditional means, so role signatures are preserved — see D12)
python -m fmre.cli build-returnset \
    --source seed-aware-synthetic \
    --calibration 1998-01,2024-12 \
    --out artifacts/rs.json

# 2. Confirm the contract passes schema validation
python -m fmre.cli validate artifacts/rs.json

# 3. Print a human-readable summary (coverage histogram, role expectations,
#    reference-book resilience against the default mandate)
python -m fmre.cli stats artifacts/rs.json

# 4. Regenerate the worked reading document (SIM house style)
python -m fmre.cli doc artifacts/rs.json --out artifacts/fundmap.html
```

Open [artifacts/sample_fundmap.html](artifacts/sample_fundmap.html) in a browser. It carries the SIM house style (`.eyebrow`, `.masthead`, `.tiles`, `.callout`, `.fig`, `.chip`, `.hm-*` heatmap, `footer.doc`) with the same tokens as the macro programme's `schulung_us.html`, including dark-mode support.

## Source options

| `--source`              | What it does                                                                                                                 | Use for                                          |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------|
| `csv`                   | Reads `<data-root>/<safe_ticker>.csv` with columns `date,close`. `--data-root PATH` required.                               | Real market data via manual export.              |
| `synthetic`             | Uniform GBM per ticker (drift 5% pa, vol 10% pa). Deterministic via ticker + master seed.                                    | Fast smoke tests; ignores role differentiation.  |
| `seed-aware-synthetic`  | State-conditional GBM: each month's mean is set by the seed's `ret_distribution` for the active regime state. Deterministic.  | Role-aware end-to-end runs before Bloomberg is wired. |

Bloomberg (via `xbbg`/`blpapi`) is stubbed out in v0.1.0. See `BloombergSource` in [src/fmre/ingest/sources.py](src/fmre/ingest/sources.py) — raise-with-message until credentials + terminal are available.

## Repository layout

```
src/fmre/
  registers/
    building_blocks.py            # Fund Map register: typed enums, load_seed, invariants
    data_series.py                # ingestion register
    seed/
      fund_map_seed.csv           # 54-row bootstrap dataset
      state_to_scenario.json      # versioned 25 -> 5 partition
  ingest/
    sources.py                    # CsvSource, SyntheticSource, BloombergSource (stub)
    harmonise.py                  # magnitude, currency, resample
    returns.py                    # period returns
    pipeline.py                   # ingest_ticker end-to-end + Parquet writer
  regime/
    timeline.py                   # RegimeTimeline dataclass + load + validate
    synthetic.py                  # synthetic Markov timeline for testing
    state_to_scenario.py          # StateToScenario map loader + partition guards
  estimate/
    map_states.py                 # bucket returns by state (no drop, no double-count)
    per_state.py                  # per-state estimator + annualisation
    fallbacks.py                  # PCHIP interpolate, borrow, seed
    block.py                      # BlockEstimate orchestrator + coverage grade
    aggregate.py                  # 25 -> 5 scenarios + role classification
    coverage.py                   # coverage matrix P_{b,s} + resilience R
    mixture.py                    # spec 5.2 within/between variance identity
    house_view.py                 # re-export shim for spec section 7 layout
  contracts/
    returnset.py                  # ReturnSet dataclass, build, validate, canonical JSON
    schemas/returnset.schema.json # JSON Schema 2020-12 for downstream consumers
  cli.py                          # fmre ingest / build-returnset / validate / doc
  version.py

tools/
  build_fundmap.py                # HTML document generator
  templates/fundmap.html.j2       # SIM house-style Jinja2 template
  svg.py                          # dependency-free inline SVG builders

tests/                            # 13 test files, 189 tests total
```

## The contract in one screen

Emitted by `build-returnset`. Structural sketch (spec 3.5):

```json
{
  "return_set_id": "RS-3af94eba844395b9",
  "regime_id": "REG-SYNTHETIC-20260728",
  "as_of": "2024-12-31",
  "model_version": "re@0.1.0",
  "universe_version": "fm@0.1.0",
  "state_to_scenario_version": "sts@0.1.0",
  "horizon_years": 1.0,
  "state_grid": 25,
  "scenarios": ["crisis", "contraction", "stagnation", "expansion", "boom"],
  "state_to_scenario": { "0": "crisis", "5": "contraction", "24": "boom" },
  "house_view": { "crisis": 0.15, "contraction": 0.20, "stagnation": 0.25, "expansion": 0.30, "boom": 0.10 },
  "role_profiles": {
    "gain":          { "crisis": -0.19, "contraction": -0.03, "stagnation": 0.05, "expansion": 0.04, "boom": 0.12 },
    "income":        { ... },
    "stabilisation": { ... },
    "protection":    { ... }
  },
  "building_blocks": [
    {
      "bb_id": 5, "ticker": "MXUS Index", "role": "gain", "region": "Americas",
      "profile_by_state":    [-0.40, -0.30, ..., 0.13, 0.16],
      "profile_by_scenario": { "crisis": -0.24, "contraction": -0.04, ..., "boom": 0.12 },
      "estimation": {
        "methods_by_state": ["seed", "seed", ..., "data-driven", ..., "seed"],
        "n_obs_by_state":   [0, 0, ..., 42, ..., 0],
        "coverage": "seed",
        "label": "model-derived",
        "weighting_note": "pi_s"
      }
    }
  ],
  "provenance": {
    "data_vintage": "2024-12",
    "series_sources": ["synthetic"],
    "calibration_window": "1998-01 to 2024-12",
    "timeline_id": "RTL-SYNTHETIC-20260728",
    "current_state": 15
  },
  "values_unit": "annualised_decimal"
}
```

Rules the validator enforces (see [src/fmre/contracts/returnset.py](src/fmre/contracts/returnset.py)):
- `state_grid == 25`; `state_to_scenario` keys are exactly `"0".."24"`; ordering monotone in scenario rank.
- `house_view` sums to 1, all weights ≥ 0, crisis weight strictly positive (non-zero tail per spec 5.6).
- Every building-block entry: `profile_by_state` length 25, `profile_by_scenario` has all 5 scenarios, `estimation.label == "model-derived"`, `coverage ∈ {full, partial, borrowed, seed}`.
- **No `mu`, `sigma`, `cov`, `covariance`, or `variance` keys anywhere in the tree.** The validator walks the payload and refuses any that leak.

## Invariants the tests enforce

Mapped to spec section 8:

1. **Seed integrity** — 54 rows load; every `ret_distribution` has length 25; role-consistent shape (Growth ascends, Protection hedges descend, Cash stays low-bounded per D9); all enumerations valid. [tests/test_seed_load.py](tests/test_seed_load.py)
2. **Ingestion invariants** — magnitude scaling and constant-FX preserve period returns; non-positive levels rejected. [tests/test_ingest_invariants.py](tests/test_ingest_invariants.py)
3. **State mapping** — no dropped, no double-counted; bucket totals equal input length. [tests/test_per_state.py](tests/test_per_state.py)
4. **Mixture recomposition** — the frequency-weighted per-state moments recompose to the block's unconditional moments to `1e-12`. [tests/test_mixture_recompose.py](tests/test_mixture_recompose.py)
5. **Labelling** — every filled state carries a method label (`data-driven`/`trimmed`/`interpolated`/`borrowed`/`seed`) and `n_obs`. [tests/test_per_state.py](tests/test_per_state.py)
6. **Coverage and resilience** — 60/40 equities+credit book fails the crisis column; 30/20/30/20 diversified book clears every column. [tests/test_coverage_resilience.py](tests/test_coverage_resilience.py)
7. **Contract schema** — every emitted ReturnSet validates; no moment keys anywhere. [tests/test_contract_schema.py](tests/test_contract_schema.py)
8. **Determinism** — two runs of the same `(inputs, version)` produce byte-identical canonical JSON and identical `return_set_id`s. No wall-clock timestamps leak. [tests/test_determinism.py](tests/test_determinism.py)

Plus:
- **House-view superposition** — `E[R_role] = Σ_s ω_s · P_{role,s}` matches hand calculation. [tests/test_superpose.py](tests/test_superpose.py)
- **JSON Schema** — published contract at [src/fmre/contracts/schemas/returnset.schema.json](src/fmre/contracts/schemas/returnset.schema.json), drift-guarded against the runtime validator. [tests/test_json_schema.py](tests/test_json_schema.py)
- **Full-seed integration** — all 54 blocks estimated end-to-end, ReturnSet validates, cross-block peer borrow exercised. [tests/test_full_seed_integration.py](tests/test_full_seed_integration.py)

## Provisional decisions

Every open item in section 12 of the spec has a `PROVISIONAL` default in [decisions.md](decisions.md), ready to be replaced when the sponsor pins them:

- **D1** state-to-scenario partition — equal 5-per-bucket, crisis@0, boom@24.
- **D2** economic phase reconciliation — descriptive metadata only; `Maturing ≈ Build-up`.
- **D4** return horizon — annualised, `horizon_years = 1.0`.
- **D5** house view — `{crisis: 0.15, contraction: 0.20, stagnation: 0.25, expansion: 0.30, boom: 0.10}`.
- **D9** Cash-as-protection — Protection invariant admits descending hedges *or* low-volatility floors (confirmed).
- **D12** synthetic ingestion flattens role differentiation — accepted for the synthetic-only path; real market data doesn't hit this path.

## Contracts summary (producer → consumer)

| Contract           | Produced by                     | Consumed by                             | Scope           |
|--------------------|----------------------------------|-----------------------------------------|-----------------|
| Regime timeline    | Macro field-model programme      | Return Estimation                       | Shared (input)  |
| Harmonised series  | Fund Map ingestion               | Return Estimation                       | Shared          |
| ReturnSet          | Return Estimation                | Portfolio Optimiser, worked document    | Shared (output) |

## Out of scope for v0.1.0

Per the spec: the Portfolio Optimiser, the per-user Life Balance Sheet, the regulated wall, and the macro field-model itself. This programme consumes the Regime; it does not compute it.
