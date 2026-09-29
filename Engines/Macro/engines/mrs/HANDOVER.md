# Market Risk Signal (mrs): handover (28.09.2026)

Resume point for whoever picks this up, including a new Claude session. The design is on the
Notion page "Engine 05: Market Risk Signal (mrs)"; decisions in `DECISIONS.md`.

> Model-derived research output. Not investment advice.

## State

**The port is finished (v1.0.0).** `mrs` reads datafeed's panel, computes the whole of
`Market_Signal.m` (eleven sub-indicators, four segments, the 25-state distribution) and
publishes a `MarketRiskSignal` (`mrs-signal@1.0.0`) at zero optimism shift with
`regime_id: null`. The v0.1.0 inputs (MacroState, TAASignal), their clients, the Regime
output, optimism and the market blends are gone (MRS-13, MRS-18). 116 tests pass.

- **Calibrations:** `2.0.0` (production, active) and `2.0.0-matlab` (golden only). The
  v0.1.0 seeds are kept as the record in `calibration.RETIRED`.
- **Store:** schema `mrs` in `simtech`, rebuilt on 28.09.2026 with
  `python -m mrs init-db --rebuild` (drops only mrs's own tables; the v0.1.0 test payloads
  are gone). The CIO signal export is reloaded as reference rows (`REF-29ad0cf9c5c3411a`,
  16,388 rows, now dated from 2006-09).
- **Golden (MRS-20):** the CIO exports turned out to come from a later pull (September 2006
  to September 2026), not the local `M_TS.mat`. Their own input, the CIO `assets` export,
  is frozen in `golden/cio_assets_2026-09/`. On it every sub-indicator and segment value
  matches `stats` to 3e-14, and 15,423 of 15,424 kernel columns match `signal` (the one
  divergence is MRS-01, on an edge).

## Production snapshot

`config.yaml` pins `upstream.snapshot_id: bloomberg-2026-01-05`. The live datafeed was
reorganised on 28.09.2026 (not by mrs): it now holds only this snapshot, which replaces
`matlab-m_ts-2026-01-05.r3.public-21886dde.market-690ff362` (same cells, per the config
comment). Its coverage gate carries every series the production calibration reads.

**Production artefact of 28.09.2026:** `MRS-7e97c0cadb73be82` (run `RUN-602ba91543303943`,
idempotency key `IDK-e82efdc1aacf7fc1`), snapshot `bloomberg-2026-01-05`, calibration
`2.0.0`. 16 economies, 241 months (2006-01 to 2026-01), each assessed from 2009-10 (the
ruled warm-up) to 2026-01.

The test suite never reads the live datafeed. It bootstraps its own offline (raw r3, then
filled, then the market layer) and runs production on that market layer.

## Remaining open points

1. **Rulings of 28.09.2026:** MRS-17 (missing data), MRS-19 (senior loan relative threshold
   0.005), MRS-22 (trend/oscillation restarted after a gap) and MRS-23 (gold threshold 15 in
   local currency) were accepted by the owner as proposed.
2. **The stress tail is always on at zero shift** (DECISIONS open point 1): stress is
   non-negative, and a reading of 0 opens column 6. It is on in 100% of assessed months;
   the median modal state is 8. It was ruled "keep"; `aggregation` keeps it in place under optimism (AGG-15).
3. No MATLAB output exists for datafeed's own pull (05.01.2026). A MATLAB run on
   `M_TS.mat` would pin the `matlab` mode on it end to end.
4. Data quality: the Germany and Spain bank index are negative in the September pull;
   high-yield yield to worst only exists for US, EU and CN; there is no BIS NEER for BD and
   VN (all in coverage as `inputs_missing`).
5. Another session will add `GET /model` to mrs (not built here).

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\Macro\engines\mrs
..\..\.venv\Scripts\python -m pytest
start.cmd
curl -X POST localhost:8005/run -H "Content-Type: application/json" -d "{}"
curl "localhost:8005/runs?limit=1"
```
