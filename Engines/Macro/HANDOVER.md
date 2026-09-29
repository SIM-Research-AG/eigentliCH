# Macro engines: handover (parked 2026-09-27)

State for whoever picks this up next, including a new Claude session. Everything here is
also on Notion (see "Notion" below); the code and the database are the ground truth.

## Status

Flow (decided 27.09.2026): `datafeed` feeds `mrs`, `cycle` and `macrofield`; the
aggregation layer (`aggregation`, Engine 04) combines those three into the Regime (issues
the `regime_id`, applies optimism) for `fmre`, `pcp` and `scenario`. `honi` also reads
`datafeed`, but its scores have no automated consumer: the CIO uses them to set the
optimiser's boundary conditions and for instrument selection, in the CIO pages of the
cockpit (`Projects/Engines/cockpit`, port 8000, desktop app "sim-tech Cockpit").

| Engine | Folder | Port | Tests | State |
|---|---|---|---|---|
| Data Feed | `engines/datafeed` | 8001 | 93 pass | Static adapter over PostgreSQL; MATLAB import + public fills. Parked before testing |
| Health of Nations | `engines/honi` | 8002 | 112 pass | Port of `HoNI2.m`; reads only from datafeed. Parked before testing |
| Macro Field | `engines/macrofield` | 8003 | 75 pass | v0.4.0, three-body core, own static snapshot for now. Parked; see its `HANDOVER.md` |
| Market Risk Signal | `engines/mrs` | 8005 | 116 pass | v1.0.0, built 28.09.2026: indicator layer (matlab and production modes), `MarketRiskSignal` output at zero shift, golden reconciled against the CIO export (3e-14). Artefact `MRS-7e97c0cadb73be82` on `bloomberg-2026-01-05`. See its `HANDOVER.md` |
| Cycle Model | `engines/cycle` | 8012 | 87 pass | Parked 27.09.2026, see its `HANDOVER.md`. v1.0.0, built 27.09.2026 (calibration 1.3.0: historical capital resets, capital peak at the reset and low at saturation, projection to macrofield's horizon, crisis-anchored credit, pulse and business from macrofield output): port of the first draft's `cycles.py` and `cycle_bins.py`, reproduces it to 1e-12 (calibration 1.0.0); reads datafeed and macrofield. Open points in its README |
| Aggregation layer | `engines/aggregation` | 8004 | 55 pass | Built 28.09.2026, calibration 1.2.0 active: the first draft's combination rule (1.0.0, reproduced to 0.0), optimism as a shift of the combined distribution with the crisis tail kept, `regime_id` issued, snapshot mismatch warned (AGG-04). First Regimes on mrs MRS-7e97c0cadb73be82. See its `HANDOVER.md` |

Open work is tracked as tasks on the Notion project **sim-tech Macro Engine** (see "Notion"
below). Besides the `mrs` tasks: testing against the live system, the **Data Feeder**
(writes directly into the `datafeed` schema). The honi, macrofield and fmre test benches now
also run inside the cockpit (Test benches), through its proxy.

## Start it

```bash
# 1. PostgreSQL (Docker container postgres_server, restart: always)
cd Projects/PostgreSQL && docker compose up -d
# 2. datafeed, then honi (each in its own window)
engines/datafeed/start.cmd
engines/honi/start.cmd
# test bench: http://127.0.0.1:8002/     API docs: /docs on 8001 and 8002
```

First time on a new machine (shared venv `Macro/.venv`):

```bash
python -m venv .venv
.venv/Scripts/pip install -e engines/datafeed[dev] -e engines/honi[dev]
# local password (git-ignored) in engines/datafeed/config.local.yaml and engines/honi/config.local.yaml:
#   database:
#     password: mysecretpassword
cd engines/datafeed && python -m datafeed bootstrap --create-database   # import + public fills
cd ../honi && python -m honi init-db
```

Run the suites: `python -m pytest` in each engine folder (PostgreSQL must be up; honi's
suite starts its own datafeed on a free port).

## Data (PostgreSQL database `simtech`, one schema and one login role per engine)

- Schema `datafeed`: registry (`country` 16, `series` 43: HoNI and mrs), snapshots, cells, public-source
  provenance, import counts. Schema `honi`: calibrations, published scores, runs. Schema
  `macrofield`: its own static snapshot, calibrations, artefacts, runs. Schema `mrs`:
  calibrations, artefacts, runs, and the reference tables `reference_source` and
  `reference_signal` (the CIO `signal` export). Schema `cycle` (role `cycle`, created
  27.09.2026 with honi's grants): calibrations, artefacts, runs. Tables are documented in the Notion
  **SQL Metadata** database.
- Migrated from `simtech_macro` on 27.09.2026 (Engine Building Guide section 8): each schema
  is owned by the login role of the same name (`datafeed`, `honi`, `macrofield`, `mrs`), which
  may read the shared `datafeed` schema and write nothing outside its own. `fmre` and
  `fmre_feed` live in the same database. `simtech_macro` is kept for rollback, with a dump in
  `Projects/PostgreSQL/backups/simtech_macro_2026-09-27.dump`; nothing reads it any more.
- **Current snapshot: `bloomberg-2026-01-05`** (written 28.09.2026): the same cells, fills and market layer
  as `matlab-m_ts-2026-01-05.r3.public-21886dde.market-690ff362`, as one self-contained snapshot under a
  meaningful id (verified identical panel and coverage). **The only snapshot in the store**: the
  eight older ones described below were deleted on 28.09.2026 on the owner's instruction (976,702
  cells; backup `Projects/PostgreSQL/backups/datafeed_2026-09-28_before_snapshot_cleanup.dump`,
  script `Projects/PostgreSQL/delete_old_snapshots_2026-09-28.sql`). Default of the cockpit and mrs;
  honi and cycle run on it. What the deleted ids were:
- **Newest of the old ids: `matlab-m_ts-2026-01-05.r3.public-21886dde.market-690ff362`** (DF-18): the Bloomberg pull of 2026-01-05 as MATLAB saved it,
  Jan 2006 to Jan 2026, 44 series (r3 adds the high-yield yield to worst), 11 public fills
  incl. the six household-consumption replacements, and the market layer (implied volatility
  in one unit, Cboe SKEW and the BIS broad effective exchange rate as new series, China's
  implied volatility filled from Cboe). Raw: `matlab-m_ts-2026-01-05.r3`; filled:
  `...r3.public-21886dde`. `mrs` pins the market layer in its config; HoNI takes the snapshot per run, its documented
  production input being `matlab-m_ts-2026-01-05.public-8e90be47`. Also kept: `...r2` and `...r2.public-dc63bdd6`
  (43 series, identical to r3's), and the 21-series import `matlab-m_ts-2026-01-05` and its children `...public-5af69fd5`,
  `...public-8e90be47` (HoNI output is identical on the old and new production snapshots).
- Snapshots are immutable (database triggers). A new pull is a new snapshot id. The
  registry tables are editable.
- Files that are not the data: `engines/datafeed/golden/` (frozen raw snapshot and public
  responses, used by tests and `bootstrap --frozen --offline`), `engines/honi/golden/`
  (MATLAB export and frozen input, regression only), `engines/datafeed/seed/registry.yaml`
  (first fill of the registry tables only).

## Decisions in force (details in each engine's DECISIONS.md)

- HoNI default window 19 years, 2007-2025 (D-28). Scores stay relative (per-year
  rescaling). **MATLAB is retired as a reference**; the current build is the reference.
- Active honi calibration `1.1.0` (datafeed plausibility gate; excludes nothing on the
  production snapshot).
- Household consumption for BR, DE, EU, GB, IN, TH = World Bank share of GDP x Bloomberg
  GDP (datafeed DF-16), because the Bloomberg series were in other units.
- Placeholder tickers (`USD BGN Curncy`: BD terms of trade, PH and VN corporate debt, VN
  wage growth) are no data (DF-13).
- Public fills are accepted only if they fit Bloomberg on the overlap (10% level, 0.01
  rate), and every fill cites its stored response.

## Known remaining gaps

Bangladesh 2007-2010 has no national score (external debt missing, terms of trade a
placeholder). No public source fits: external debt CN/ID/BD/MY/JP (early years), BD trade
balance 2006-2013, India budget balance 2006-2010, wage growth (several), Swiss CPI Dec
2025, BR/ID 10y yield 2006, PH/VN corporate debt, BD terms of trade. Per series and country:
datafeed's `GET /coverage` and each fill's verdict in the snapshot manifest (`GET /snapshots/{id}`).

## For the future Data Feeder

Write a new `snapshot` row, its `series_definition` rows and its present cells into
`observation` (a missing cell gets **no row**, never 0 or a placeholder). The checksum is
sha256 of the snapshot's full panel in canonical JSON (`datafeed.engine.panel_of` +
`checksum`); either reuse that code or ingest through `POST /snapshots` (header
`X-Admin-Token` = env `DATAFEED_ADMIN_TOKEN`). Add countries or series to the registry
tables first; ingest refuses anything unregistered.

## Notion (keep it current, written as is, never as a change log)

- Engine pages (under the Engine Building Guide `3e30ba72543f80549955d5029d2512cd`):
  Engine 01 Data Feed `3e50ba72543f8149a983fa9a8f69be97`, Engine 02 honi
  `3e50ba72543f81479716c3c448e0c520`, Engine 03 macrofield `3e50ba72543f81d38916efb0c7cc5241`,
  Engine 04 aggregation `3e50ba72543f81e3815ce4aece6046ed`, Engine 05 mrs
  `3e50ba72543f81f083f6ed5af51f21e4`, Engine 12 cycle `3e80ba72543f81299187c34493263bba`.
- SQL Metadata database `dec22fe9de2b4690ad6b186a46a6fcb1` (the id `3e80ba72543f8047b5b3dbf37ee6c4da` is an archived empty copy): one row per table, details in
  the row's page. Its schema (columns) cannot be edited through the Notion connection;
  rows can.
- Project page **sim-tech Macro Engine** `3e30ba72543f81c48c1dd029ff4f07a3`.
- Specs: HoNI Build Manual (task page `3e30ba72543f808696e0fccbfadc9eaf`), 3.Health of
  Nations theory page.

## Gotchas

- `engines/threebody` was renamed `engines/macrofield` on 27.09.2026.
- The honi test bench lists datafeed's snapshots itself; pick the production one.
- If a seed calibration or the contract version of a stored payload changes, the dev
  schema has to be rebuilt (seeds are immutable); this happened once for honi.
- MATLAB sources used for the import: `SIM_Tech/Master_Controller/M_TS.mat` and `Tickers/`.
