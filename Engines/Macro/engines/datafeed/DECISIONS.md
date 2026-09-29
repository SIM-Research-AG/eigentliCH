# datafeed: decisions index

**DF-01 Anatomy.** The Guide's section 2 layout plus `service.py`, `settings.py`,
`schema.sql`, `__main__.py` and the offline importer `etl/`, as in honi. Store, config
precedence and test logic follow the Instruments engine.

**DF-02 Snapshots are immutable and content-checked.** A snapshot's checksum is the sha256
of its full panel in canonical JSON. The same content again is a no-op; different content
under a used id is refused (409), and the database refuses UPDATE and DELETE on every data
table. A correction is a new snapshot.

**DF-03 Present cells only.** The store holds a row per present cell; a missing cell has no
row, so assembly cannot invent one. Each cell carries its flag and its source.

**DF-04 The MATLAB import.** `M_TS.mat` has no dates and stores NaN as 0. Dates are rebuilt
from the loader's window (first month 2006-01-31, 241 months). NaN, leading and trailing
zeros become missing; interior zeros are kept only in rate and balance series
(`zero_is_a_value`), missing elsewhere. Counts per series: `golden/snapshot_2026-01-05/zero_rule.json`.
Cells from M_TS are flagged `observed`: MATLAB did not record carry-forward, so it cannot be
reconstructed.

**DF-05 Public fills are fitted, never spliced blind.** Level candidates are fitted by a
scale, rate candidates by an offset, both on the overlap with the raw Bloomberg series,
and refused when the fit does not hold (10% / 0.01 by default). Fills go into missing
cells only. The raw response behind every fill is stored and cited on the manifest.

**DF-06 Carry-forward policy** (the open point on the engine page). datafeed carries only
its own public fills: an annual value sits at December and is carried at most 11 months,
into missing cells, flagged `carried`. The Bloomberg cells arrive already carried by the
terminal (`previous_value`) and are left as they are.

**DF-07 Admin ingest** (the open point on the engine page). `POST /snapshots` needs
`X-Admin-Token` equal to the environment variable named in `service.admin_token_env`; with
the variable unset, HTTP ingest is off. The bootstrap writes through the same service code.

**DF-08 `POST /run` materialises a panel.** For the standard endpoints to mean something
here, a run is a panel request; its artefact is the panel, cached on the request, the
snapshot checksum, the engine version and the contract versions.

**DF-09 Implausible units are reported, not fixed.** Household consumption over GDP is out
of range for BR, DE, EU, GB, IN and TH. Replacing those Bloomberg series (for instance with
the World Bank share times Bloomberg GDP) is a data decision not taken yet; `/coverage`
reports it and honi 1.1.0 drops the affected index.

**DF-10 Snapshot ids are URL-safe.** Letters, digits and `_ . : -` only, so an id survives a
query string unencoded. The filled snapshot is `<raw id>.public-<8 hex>`, the hex being a
hash of the fill verdicts and the calibration.

**DF-11 IMF WEO values** can be estimates or projections for recent years. They are only
used for missing December cells on the snapshot's axis (up to 2025) and only after the fit.

**DF-12 `psycopg` is outside the allowlist,** admitted as in every engine (D-05): the Guide
mandates PostgreSQL. `openpyxl` is a development extra used only by the importer.

**DF-13 Placeholder tickers are no data.** `import.matlab.placeholder_tickers` lists the
ticker the sheets use to hold a row position (`USD BGN Curncy`). Such a series is imported
with no cells and its definition says so. Four series were affected (BD terms of trade, PH
and VN corporate debt, VN wage growth); MATLAB had scored a constant 1.0 for all four.
Found while documenting the tickers; the raw snapshot was rebuilt before any consumer
outside development had read it (2026-09-27).

**DF-15 The registry is in the database.** Tables `country` (code, name, ISO3, MATLAB
field) and `series` (category, unit, period, HoNI indices, MATLAB sheet and column, whether
an interior zero is a value) are the one registry for every engine and for the future Data
Feeder; `GET /countries` and `GET /registry/series` serve them. `seed/registry.yaml` only
fills missing rows at bootstrap, and a database row that differs from it is kept. The
registry stays editable; every snapshot keeps its own `series_definition` copy, so an edit
never changes a published snapshot. The importer's per-series counts (NaN, zeros,
placeholders) are in the append-only table `series_conversion`
(`GET /snapshots/{id}/conversions`). `config.yaml` keeps configuration only: port, store,
MATLAB import settings and the fill candidates.

**DF-16 Household consumption replaced for six countries** (decided 2026-09-27). For BR, DE,
EU, GB, IN and TH the Bloomberg series is in another unit than GDP. Fill mode `share`
computes consumption as the World Bank share of GDP (`NE.CON.PRVT.ZS`) times Bloomberg GDP;
with `replace: true` the Bloomberg cells of that series are removed first (the only fill
allowed to displace primary data, and the count is on the manifest as `cells_replaced`).
Every share is checked against the plausibility bounds. The result is the snapshot
`matlab-m_ts-2026-01-05.public-8e90be47`; `/coverage` finds no unit problem on it. This
supersedes DF-09 for these six series.

**DF-17 The market series for mrs are in the registry** (27.09.2026). 22 series that
`Market_Signal.m` reads from `M_TS` (gold, unemployment, senior loan ETF, NPL, six MSCI
fundamentals, equity and bank total return, JPM BEER, 1y OIS, DXY, PPI, M1 growth,
manufacturing confidence, VIX, fear barometer, 2y yield, high-yield index) were added to
`series`, taking the registry to 43. The same `M_TS.mat` was imported again as
`matlab-m_ts-2026-01-05.r2` (the 21-series import stays: immutable); its 21 old series are
cell for cell the same, the fills are the same, and HoNI's output on the new production
snapshot `matlab-m_ts-2026-01-05.r2.public-dc63bdd6` is identical. Units map to datafeed's
vocabulary (price to `level`, index level to `index`, rate to `ratio`). The placeholder
rule (DF-13) found 24 more placeholder country-series in these columns (MATLAB read 1.0);
the fear barometer is empty for every country and JPM BEER is now empty everywhere. The
importer now also reads a one-series sheet saved as a vector (Commodity).

**DF-18 The market layer** (27.09.2026). Several market inputs `mrs` reads were empty or
unusable in the Bloomberg pull (Notion task "Data quality: market inputs that are empty or
cannot work"). They are repaired in a child of the filled snapshot,
`matlab-m_ts-2026-01-05.r3.public-21886dde.market-690ff362`, in three steps configured in
`config.yaml` (`market:`), each a `MarketRecord` on the manifest (`snapshot@1.2.0`):
(1) **corrections** multiply primary cells whose sheet scale factor is wrong, stated with a
reason (implied volatility x0.01 for BD, ID, MY, PH, TH, VN; x100 for JP), and the definition's
magnitude and description say so; (2) **public series** under new ids where Bloomberg has no
usable equivalent (`volatility.skew`, Cboe SKEW, for the discontinued CSFB Fear Barometer;
`fx.neer_broad`, BIS nominal broad effective exchange rate, for the empty `JBDN...` series);
existing ids never change meaning; (3) **fills** into missing primary cells only, from a
monthly public series, accepted only if every overlap month is within 10% of the median
ratio, or, for the same index from its publisher (`identical: true`), if the median ratio is
within 2% of 1 over at least 6 months (CN implied volatility from Cboe VXFXI, 131 months).
Responses are stored whole (`market_fetch`, `market_value`, append-only) and frozen in
`golden/market_2026-09-27.json` for offline builds. The raw import became
`matlab-m_ts-2026-01-05.r3` to add `yields.high_yield_ytw` (M_TS Yields column 8, the yield
to worst of the high-yield index, for the spread `MR_Bond.m` meant to take); its other 43
series equal r2 cell for cell. The MATLAB columns stay in the registry unchanged, so
`mrs`'s `matlab` mode still sees what MATLAB saw.

**DF-14 The filled snapshot id** hashes the raw snapshot's checksum together with the fill
verdicts and the calibration, so a changed raw snapshot can never share a child id.
