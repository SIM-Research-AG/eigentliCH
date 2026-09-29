# datafeed: Data Feed engine

> **Notice.** Research data service for the sim-tech engines. Not investment advice.

The only component that touches stored source data. It keeps **immutable snapshots** of the
country series in PostgreSQL and serves them as aligned monthly panels over HTTP. Every
other engine (`honi`, and later `macrofield` and `cycle`) asks `GET /panel` for what it needs,
keyed on a `snapshot_id`, and checks `GET /coverage` before it runs.

| | |
|---|---|
| Module | `datafeed` |
| Default port | 8001 (`config.yaml`, or `DATAFEED_PORT`) |
| Consumes | the Bloomberg pull saved by MATLAB (`M_TS.mat` + ticker sheets); World Bank and IMF public APIs for gaps; Cboe and BIS for the market layer (DF-18) |
| Produces | `Snapshot`, `SeriesDefinition`, `Panel`, `CoverageReport` |
| Downstream | `honi` (now); `mrs`, `macrofield`, `cycle` (later; `mrs` needs 22 market series added to the registry) |

## What is in the store

Eight snapshots in the `datafeed` schema of `simtech`. Each consumer pins the snapshot it
reads in its own configuration; `GET /panel` without an id serves the newest.

| Snapshot | What it is | Cells | Checksum |
|---|---|---|---|
| `matlab-m_ts-2026-01-05.r3` | The Bloomberg pull as MATLAB saved it: 16 countries x 44 series (HoNI, mrs and the high-yield yield to worst), Jan 2006 to Jan 2026, placeholder tickers removed | 146,432 | `ea6379d07e28...` |
| `matlab-m_ts-2026-01-05.r3.public-21886dde` | Gaps filled where the fit holds, household consumption for BR, DE, EU, GB, IN, TH replaced (DF-16) | 147,086 | `bfa24e47f7aa...` |
| `matlab-m_ts-2026-01-05.r3.public-21886dde.market-690ff362` | **Newest.** The market layer on top (DF-18): implied volatility in one unit everywhere, Cboe SKEW and the BIS broad effective exchange rate as new series, China's implied volatility gaps filled from Cboe | 154,447 | `f9beaeb12b72...` |
| `matlab-m_ts-2026-01-05.r2`, `...r2.public-dc63bdd6` | The 43-series import and its filled child (DF-17). r3 carries the same 43 series cell for cell | 145,751 / 146,405 | |
| `matlab-m_ts-2026-01-05`, `...public-5af69fd5`, `...public-8e90be47` | The first import (21 HoNI series) and its children; `public-8e90be47` is still HoNI's production input | | |

Of 165,808 cells in the production snapshot: 144,547 observed, 1,858 carried (fills only),
19,403 missing, 2,035 from public sources. Series are addressed by name (`inflation.cpi_yoy`,
`volatility.implied`, ...). The **registry is in the database**: tables `country` (16) and
`series` (46, each with a plain-language description; `GET /countries`, `GET /registry/series`), seeded once from
`seed/registry.yaml`; each snapshot keeps its own definitions with the Bloomberg ticker,
field, scale and currency (`GET /series`), and the importer's counts per series
(`GET /snapshots/{id}/conversions`).

### How gaps are filled

For each candidate in `config.yaml` (`fills:`) the public series is fetched, stored whole
(`GET /public`), and **fitted against the Bloomberg series on the years both cover**:

- **level** series: scale `k = median(bloomberg / public)`; accepted if every overlap ratio
  is within 10% of `k`. Units, magnitude and a stable currency difference all show up as a
  constant `k`. A series with no Bloomberg values at all is fitted through an **anchor**
  (Bangladesh and Vietnam household consumption are scaled with the GDP fit, so they land
  in Bloomberg's GDP unit).
- **share** series: public share of an anchor times the primary anchor (household
  consumption % GDP x Bloomberg GDP), checked against the plausibility bounds. With
  `replace` the series' Bloomberg cells are removed first: used only for the six
  consumption series in the wrong unit (DF-16).
- **rate** series: offset `b = median(bloomberg - public)`; accepted if every residual is
  within 0.01 of `b` (an entry may set its own tolerance, with a reason).

An accepted fill goes into missing December cells only, carried at most 11 months into
missing cells and flagged `carried`. A Bloomberg value is never overwritten, and the fit
is always made against the raw snapshot. Every candidate's verdict is on the filled
snapshot's manifest.

| Country | Series | Source | Verdict |
|---|---|---|---|
| BD | production.gdp_nominal | World Bank NY.GDP.MKTP.CN | filled 2006-2015 (fit 0.7%) |
| BD | consumer.household_consumption | World Bank NE.CON.PRVT.CN, via GDP | filled 2006-2025 (anchor fit 0.7%) |
| VN | consumer.household_consumption | World Bank NE.CON.PRVT.CN, via GDP | filled 2006-2025 (anchor fit 6.9%) |
| BR | consumer.labour_force_participation | World Bank SL.TLF.CACT.ZS (ILO) | filled 2006-2011 (offset -1.45 pt, residual 1.4 pt, tolerance 1.5 pt) |
| JP | money.budget_balance_gdp | IMF GGXCNL_NGDP | filled 2006 (residual 0.3 pt) |
| BR, DE, EU, GB, IN, TH | consumer.household_consumption | World Bank NE.CON.PRVT.ZS x Bloomberg GDP (share, replace) | replaced 2006-2025 (Bloomberg cells removed: 241 each, IN 176) |
| IN | money.budget_balance_gdp | IMF GGXCNL_NGDP | refused: 4.5 pt residual (general vs central government) |
| CN, ID, BD | debt.external | World Bank DT.DOD.DECT.CD x FX | refused: 50%, 14.5%, 13.6% |
| BD | fx.trade_balance | World Bank NE.RSB.GNFS.CN | refused: 85% (goods vs goods and services) |
| VN | equity.market_cap_gdp | World Bank CM.MKT.LCAP.GD.ZS | refused: 12 pt level gap |

Gaps with no public candidate: wage growth (BR, CH, PH 2025; ID; BD 2006-2014; VN all
years), Swiss CPI December 2025, 10y yields for BR and ID in 2006, external debt for MY and
JP, corporate debt for PH and VN, terms of trade for BD.

**Placeholder tickers.** Four sheet rows hold their position with `USD BGN Curncy` ("blank
holding space"): BD terms of trade, PH corporate debt, VN wage growth and VN corporate
debt. MATLAB pulled them as the USD spot rate, a constant 1.0, and scored it (a 100% wage
growth, corporate debt of 100% of GDP). They are imported as no data (DF-13).

### The market layer (DF-18)

Several market inputs `mrs` reads were empty or unusable in the Bloomberg pull. The market
layer repairs them in a child of the filled snapshot, in three recorded steps
(`config.yaml`, `market:`; every step, applied or refused, is on the manifest's `market`):

| Step | Series | Countries | What | Source |
|---|---|---|---|---|
| correct | `volatility.implied` | BD, ID, MY, PH, TH, VN | x0.01: MSCI 90-day realised volatility (RK004) was pulled at scale 1, so it read 19.6 where every other economy reads 0.20 | Bloomberg, rescaled |
| correct | `volatility.implied` | JP | x100: the Nikkei VI (VNKY) was pulled at scale 0.0001 and read 0.002 | Bloomberg, rescaled |
| series | `volatility.skew` | all 16 | Cboe SKEW, month-end close: the price of S&P 500 tail-risk protection. Replaces the Credit Suisse Fear Barometer (`CSFB Index`), discontinued and empty for every economy; like CSFB, one global series | `cboe:SKEW` |
| series | `fx.neer_broad` | 14 (not BD, VN) | BIS nominal effective exchange rate, broad basket, monthly. Replaces `fx.beer` (`JBDN... Index`), which holds no data; the BIS does not cover BD or VN | `bis:M.N.B.{area}` |
| fill | `volatility.implied` | CN | Cboe VXFXI, the same index as the Bloomberg ticker, into missing months only: 131 months (Mar 2011 to Jan 2022), coverage 48 to 179 of 241 | `cboe:VXFXI` |
| fill | `volatility.implied` | BR | Cboe VXEWZ, the same index: accepted, nothing to fill (the index starts in March 2011 in both) | `cboe:VXEWZ` |

A fill from the same index only has to confirm the unit (median ratio within 2% of 1 over at
least 6 months); single months differ where the two sources close the month on different
days. Any other fill must keep every overlap month within 10% of the median ratio. Primary
cells are never overwritten.

`yields.high_yield_ytw` (M_TS Yields column 8) is the yield to worst of the same high-yield
index whose total-return level is `yields.high_yield_index`: the spread `MR_Bond.m` meant to
take. It holds data for US and EU (from 2006) and CN (from July 2009); nine economies are
placeholders and BR, CH, GB and IN returned nothing. A proper spread elsewhere needs
Bloomberg tickers (yield to worst or OAS on the existing index tickers) and a new pull.

Still without a public source: a local volatility index for BD (only realised volatility);
the effective exchange rate for BD and VN (candidate: Bruegel NEER, 120 partners); a
high-yield spread outside US, EU and CN.

### Plausibility findings

`GET /coverage` flags household consumption over GDP outside 0.2 to 0.9, which means the
two Bloomberg series are not in the same unit: **BR** (unstable), **DE** (about x2),
**EU** (about x0.12), **GB** (about x2 to x3), **IN** (quarterly), **TH** (about 10^8).
These findings are on the raw snapshot. The production snapshot replaces the six series
(DF-16) and `/coverage` finds nothing on it.

## Run it

From this folder, with PostgreSQL up (`docker compose up -d` in `Projects\PostgreSQL`) and
the local password in `config.local.yaml` (git-ignored):

```bash
..\..\.venv\Scripts\pip install -e .[dev]
python -m datafeed bootstrap --create-database   # import M_TS.mat, fetch public data, build both snapshots
start.cmd                                        # serve on 8001
```

Bootstrap options: `--frozen` (raw snapshot from `golden/`, no MATLAB folder), `--offline`
(public data from the store or `golden/public_2026-09-27.json`, no network), `--refresh`
(fetch every public series again), `--freeze-raw`, `--freeze-public`, `--freeze-market`. Rerunning against
unchanged inputs changes nothing.

```bash
python -m pytest        # 104 tests, against the real server
```

The suite follows the Instruments engine: a real PostgreSQL store in a throwaway schema,
built by the real bootstrap; the importer is tested against the real MATLAB files and the
public clients against the real internet, each skipping loudly when its source is absent.

## Endpoints

Standard: `GET /health`, `GET /meta`, `GET /contracts`, `POST /run` (materialise a panel as
an artefact, cached), `GET /runs/{id}`, `GET /artefacts/{id}`, `GET /calibration`,
`PUT /calibration`.

Engine specific: `GET /countries`, `GET /registry/series`, `GET /snapshots/{id}/conversions`,
`GET /snapshots`, `GET /snapshots/{id}`, `POST /snapshots` (admin: header
`X-Admin-Token` equal to `DATAFEED_ADMIN_TOKEN`; switched off when unset), `GET /series`
(filters `snapshot_id`, `country`, `category`, `index`), `GET /series/{series_id}`,
`GET /panel` (`snapshot_id`, repeatable `series` and `countries`, `freq`, `start`, `end`),
`GET /coverage`, `GET /public`, `GET /calibration/versions`.

## Layout

```
config.yaml           port, store, fill candidates, market layer, MATLAB import (configuration only)
seed/registry.yaml    first fill of the country and series tables (the database is the registry)
src/datafeed/
  api.py              routing only
  contracts.py        Panel (panel@1.1.0), Snapshot, SnapshotIn, SeriesDefinition, CoverageReport
  engine.py           pure rules: assembly, checksum, fits, fill application, coverage
  calibration.py      alignment, carry-forward and fill-acceptance rules (seed 1.0.0)
  clients.py          World Bank and IMF DataMapper callers; Cboe and BIS (market layer)
  store.py, schema.sql  PostgreSQL; every data table append-only in the database
  service.py          orchestration; HTTP ingest and bootstrap share one path
  settings.py         configuration
  etl/                offline importer (not deployed): matlab.py, public.py, market.py, bootstrap.py
golden/               frozen raw snapshot, public and market responses (see golden/README.md)
tests/                unit, property, fills, loaders, acceptance, API, store, concurrency
dev/make_deploy.py    builds ../../deploy/datafeed without etl, tests, golden or dev files
```
