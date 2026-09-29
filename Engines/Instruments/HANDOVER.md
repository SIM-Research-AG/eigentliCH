# Handover — Fund Map engine

**Written 27 September 2026, before a context reset; state as of 29 September 2026** (the
owner's decisions of that day are built, FMRE-15 to FMRE-24; R-002 is decided: the
default estimator is the 12 month forward measurement, lightly smoothed). What a new session needs to
pick this up without re-deriving it. `README.md` is the reference; this is the state of
play.

---

## 1. Start here

```bash
cd Projects/Engines/Instruments
start.cmd                      # or: python -m uvicorn api.main:app --port 8006
python -m pytest -q            # 332 tests, needs the Postgres container up
```

**The `regime_id` stamp (28.09.2026).** `GET /v1/return-set?regime_id=RGM-...` stamps the
set against that Regime: it first asks aggregation (`INSTRUMENTS_AGGREGATION_URL`, default
`http://127.0.0.1:8004`, `/regime/{id}/current`) and refuses an id aggregation does not
serve (422; 503 if aggregation cannot be reached). The id enters `return_set_id`, so the
stamped set is its own artefact (`RS-59598b143ab78c56` for the Default Regime with
instruments under the default estimator, FMRE-23); without the parameter the set carries
`regime_id: null` (`RS-8b6a98484992c9d3`). The estimator and the currency are in every id. pcp asks for the stamped set on every run and names the id fmre
serves. Standard library only (`urllib`). A converted set (`currency=`) names its currency
in `provenance.currency` (null on the default, FMRE-21), which pcp v1.1.0 reads.

Test bench at <http://127.0.0.1:8006/>, also openable straight off disk
(`testbench/index.html` — it detects `file://` and calls `127.0.0.1:8006`).

**Docker running is not enough.** The container is the database; the engine is a separate
process that does not come back after a reboot. This has caught us twice.

Store: PostgreSQL **`simtech`**, schema **`fmre`** (15 tables) plus **`fmre_feed`**
(7 tables), connecting as the role **`fmre`**. Config in `config.toml` (git-ignored, copy
`config.example.toml`). `python -m store.provision --show` prints the layout.

---

## 2. Numbers that must not move

If any of these changes without a recorded decision, something broke.

| | |
|---|---|
| Calibration id | `CAL-69d9d1ee5245ac71` (Income A, since 29.09.2026) |
| State map id | `MAP-eb4b581619a03147` |
| Default ReturnSet | `RS-8b6a98484992c9d3` unstamped, `RS-59598b143ab78c56` stamped (`RGM-e2658e8e9bbbc81e`); stamped in CHF `RS-c472e411e39645f5`, EUR `RS-dd496e3d3e72affe`, USD `RS-76d1a29edc752997` |
| Default estimator | `forward_12m_smoothed` (FMRE-22); stored profiles are the cascade's |
| Reference reproduction | **5 × 10⁻¹⁶** worst error over 200 published values |
| Phase counts | crisis 24 · contraction 16 · stagnation 25 · expansion 74 · boom 11 |
| Shape assertions | 8 of 8 pass |
| Register | 54 instruments, **52 active**; 42 with history (40 of them active), 12 without |

The calibration id is identical across backends and across rebuilds. It is the fastest
check that nothing has drifted. It moved once, on purpose: the owner's R-001 decision
(Income = real estate 75 %, equity 25 %) replaced `CAL-092efd097adb0b26` (Income = real
estate alone, state map `MAP-60b9811df4dc85fe`). That calibration is still in the live
store for comparison and `tests/test_role_map.py` reproduces it from
`roles.ROLE_MAP_BEFORE_R001`.

---

## 3. Where the data comes from

Four origins, and the distinction is enforced by a test.

| origin | what |
|---|---|
| `nas:house-research` (19 files) | `Knowledge_Center/Published/Dynamic Investment` — Steiner (2021): the thesis, four MATLAB `.mlx` scripts, 19 annual workbooks 1870–2020. **The scientific basis.** `Model/return_dist.xlsx` holds the published output the port reproduces. |
| `nas:prototype` (3 files) | The old build: the monthly andersCH report, and `legacy/pre-universe-cut/rs.json` (the 54-instrument register). |
| `internet:yahoo` (8.7k rows) | Public ETF proxies, downloaded 27 Sep. **New as of this session** — before it, nothing had been downloaded. |
| `internet:cboe` (245 rows) | The Cboe VIX Tail Hedge index (`cboe.VXTH`, month end 2006-04 to 2026-08), downloaded 29 Sep 2026 from Cboe's public daily file: the price proxy of Long Volatility Index. |

**The monthly report's dates are one month late** — a documented export bug, corrected on
load and re-checked against the 2008 crash on every run.

---

## 4. The open findings

### 4.1 The instrument estimator — D2 BUILT, SELECTABLE

**Built 27 September 2026.** `ProfileMethod.SHAPE_SCALED` in `engines/fund_map/estimate.py`,
selected with `profile_method=shape_scaled`. Not the default: the owner chose the 12 month
forward measurement, lightly smoothed (section 4.1b, FMRE-22).

```
profile_i(s) = level_i + k_i · ( roleshape(s) − mean(roleshape) ),   k_i = vol_i / vol_role
```

Both parameters come from the whole return series. `level_i` and `vol_i` are the
annualised mean and standard deviation of the instrument's own monthly log returns;
`vol_role` is the **median** annualised volatility of the instruments in the same role
that have history. The specification said "vol_role" without pinning it down and that is
the reading chosen: it keeps the ratio dimensionless and centred near one.

**Measured against the cascade on all 42 instruments with returns:**

| | cascade | D2 |
|---|---|---|
| mean jump between adjacent states | 9.66 % | **1.44 %** |
| Precious Metals, crisis state | −4.81 % | **+33.05 %** |
| coverage | 37 borrowed, 5 seed | 41 shape-scaled, 1 seed |

Both diagnosed faults go. The crisis sign is right because a protection asset now
inherits the protection role's shape instead of reading it from a handful of months.

**A wrong turn worth not repeating.** The first implementation fitted `k` by regressing
the state bucket means on the role shape. It reads better on paper and is wrong: the
bucket means are the noisy quantity D2 exists to stop trusting, so the slope inherited
their noise and returned **+26.46 for CS Long Vola and −2.83 for Precious Metals**. It
also failed to fix the crisis sign. Nothing swings twenty-six times as hard as its role.
`test_it_never_inverts_the_role_shape` guards against a return to it.

**Before switching the default, judge these:**

1. `level_i` inherits the selection bias of the recovered returns, which are conditional
   on the manager having held the instrument. D2 spreads that bias across all 25 states
   instead of only the states with data.
2. Amplitudes above 1 are common because `vol_role` is a median over a heterogeneous
   role — protection holds both CHF Cash and long volatility. A role split, or a
   different `vol_role`, would move every amplitude.
3. D2 never inverts the role shape by construction. An instrument that genuinely moves
   against its role will be wrong under D2, and that is a role-assignment question.

### 4.1a The 12 month forward measurement (R-003, D-02) — THE DEFAULT, SMOOTHED

**Built 28 September 2026; the default since 29 September 2026 with a smoothing step on
top** (`forward_12m_smoothed`, section 4.1b). Unsmoothed it stays selectable:
`profile_method=forward_12m` on `/v1/return-set`, `method=forward_12m` on the instrument
profile. Each month's state is credited with the log return over `t+1 .. t+12`; estimated
per phase with `n_obs` = distinct months covered / 12 (floor six applies to that); pchip
onto 25 states like the role curves; a thin phase is filled from D2's scaled role shape,
anchored on the measured phases, labelled `shape-scaled`. It reads the register proxy's
public series when that gives more complete windows (Precious Metals reads GLD, because
the andersCH recovery has 147 of 239 months). All choices: `DECISIONS.md` FMRE-01..05.

Precious Metals, crisis knot (state 3) against boom knot (state 23):

| | crisis | boom | highest in crisis | coverage |
|---|---|---|---|---|
| USD | **+12.06 %** | +9.1 % (fill) | yes | shape-scaled |
| CHF | **+7.83 %** | +8.42 % (fill) | no, contraction +11.9 % | shape-scaled |
| EUR | **+10.33 %** | +11.0 % (fill) | no, contraction +14.8 % | shape-scaled |

Positive in crisis in all three currencies and no longer seeded. In CHF and EUR it is not
highest in crisis: the dollar fell against the franc and the euro in the year after most
crisis months, which takes part of gold's dollar gain away. The owner accepted that
currency effect on 29.09.2026 and restated the acceptance (FMRE-19): **positive in crisis
in all three currencies; highest in the crisis states in the source currency.** Precious
Metals passes it in all three. The table above is the unsmoothed measurement; the served
default (smoothed, section 4.1b) moves each knot by at most one point. Since FMRE-24 each
protection instrument is judged by the rule of its type (tail hedge on the crisis months
themselves, cash on never being negative, the rest on this forward rule), and
`tests/test_protection_forward.py::CANNOT_HOLD` names what still cannot, with the reason:
USD Cash in CHF and EUR and CHF Cash in USD (the currency), and Global Governmental Bonds in
CHF and EUR (unhedged BWX, the currency). Short MSCI US and CS Long Vola are inactive and no
longer measured.

**Long Volatility Index proxy (FMRE-18).** VIXY (weak, short-term VIX futures roll, from
2011) was replaced by the Cboe VIX Tail Hedge index itself (VXTH, the register's own
index, graded close), 2006-04 to 2026-08, 245 months, from Cboe's public daily file via
`feeds/cboe.py`, loaded by `python -m store.etl.cboe` into `fmre_feed` as `cboe.VXTH`.
`datafeed` (Engine 01) holds only the VIX level and SKEW, no tradable volatility return;
Yahoo has no VXTH history. Crisis knot in USD: +6.5 % (VIXY: -124 % log).

**Currency (D-01), done for 2003 onwards.** `python -m store.etl.fx` loads `fx.USDCHF` and
`fx.EURCHF` (Yahoo month end) into `fmre_feed`; `currency=CHF|EUR|USD` converts monthly
returns before estimation, never after. The role curves stay the US long record in USD.
The long-history work in section 5 (JST, DM before 1999, 1922-23) is still open.

**Found on the way:** `feeds/yahoo.py` filed every bar by its UTC stamp, and Yahoo stamps
London-listed series (the FX rates) at 23:00 UTC on the last day of the previous month
all summer, so April to October landed a month early and October vanished. Fixed (+12 h
before reading the month, and a guard against two bars in a month); US-listed series,
stamped 04:00/05:00 UTC, are unchanged by it (verified on GLD, SPY, EWL).

### 4.1b Reviews R-001, R-002, R-003: the owner's decisions of 29 September 2026

* **R-001 (Income ≈ Stabilisation): decided, built.** Income = real estate 75 %, equity
  25 % (candidate A), a CIO override in `ROLE_MAP` (FMRE-15). Phase values crisis to boom:
  Income -3.21, +3.25, +3.03, +5.19, +5.45 %; Stabilisation +1.81, +6.76, +1.32, +3.44,
  +2.50 %. Above Stabilisation by 1.75 points in expansion and 2.95 in boom, 5.02 below in
  crisis; eight of eight shape checks. `/v1/diagnostics/income-candidates` and the bench
  tab *Income · R-001* still show the Income before R-001 and B and C beside A. The
  10-year Treasury (`long_rate`) is in no role by design: a yield, not a return.
* **Role review (FMRE-16, FMRE-25).** Bloomberg Market Neutral HF confirmed in
  Stabilisation (curve evidence under Income A, Stabilisation 0.78). Global Bonds was moved
  to Stabilisation and, the same day, back to Income by the owner (FMRE-25): only two of its
  five phases are measured, too thin for a move. Both steps are in its `ROLE_OVERRIDES` reason.
* **Deactivated (FMRE-17):** Short MSCI US ("a short index is not a hold-through-crisis
  instrument") and CS Long Vola (Long Volatility Index kept). Rows, histories and
  profiles stay; `active = 0`.
* **R-003 acceptance restated (FMRE-19)**, section 4.1a.
* **R-002 (estimator default): decided, built (FMRE-22).** The default for the ReturnSet,
  the instrument profile endpoint and the diagnostics, in every currency, is the 12 month
  forward measurement plus a light smoothing step (`forward.smooth_forward`): two passes
  of a (1/4, 1/2, 1/4) kernel over the 25 states, no phase value moved by more than
  1 point, no state carried across zero. Label `forward-12m-smoothed` (a filled band keeps
  `shape-scaled`); the unsmoothed profile and the measured phases stay on every view.
  Computed on request, never stored; the stored rows stay the cascade's (its peer basis),
  and `profile_method=cascade` reads them. Mean jump, 40 active instruments with history,
  source currency: cascade 9.13 %, D2 1.27 %, forward 1.64 %, **forward smoothed 1.49 %**
  (CHF 1.28, EUR 1.32, USD 1.51); largest move of a measured phase value 1.00 point.
  Precious Metals under the default, crisis knot against boom knot: USD +12.2 / +9.2 %
  (highest state: state 1, +15.7 %), CHF +7.7 / +8.5 %, EUR +10.2 / +11.1 %; positive in
  every crisis state in all three. Coverage: no instrument with history is `seed` (every
  one is `shape-scaled`, because the boom phase has too few windows and is filled).
* **Protection rule per type (FMRE-24).** Tail hedge (price proxy VXTH or VIXY): paid in
  the crisis months themselves; cash (asset class `Cash`): never negative; the rest: the
  forward rule of FMRE-19. Cannot hold, with the reason in `CANNOT_HOLD`: USD Cash in CHF
  and EUR, CHF Cash in USD (the currency), Global Governmental Bonds in CHF and EUR
  (unhedged BWX). Long Volatility Index passes in all three, thinly in USD (34 crisis
  months, mean +0.03 % a month); its published forward profile dips below zero at the
  edge of the crisis band in CHF and EUR (named in `NEGATIVE_IN_CRISIS_PROFILE`).

**The default ReturnSet is pinned** (`tests/test_default_pin.py`) and moved on purpose
twice on 29.09.2026. FMRE-20: `RS-b61c78223f520245` -> `RS-ca414ad663de0621` unstamped,
`RS-9cf5467a868babbe` -> `RS-101354ae344db5b3` stamped. FMRE-23 (the estimator and the
currency enter every id): -> `RS-8b6a98484992c9d3` unstamped, -> `RS-59598b143ab78c56`
stamped; CHF `RS-c472e411e39645f5`, EUR `RS-dd496e3d3e72affe`, USD `RS-76d1a29edc752997`
(stamped). 52 instruments, `rs@1.0.0`, key sets, five notes, labels; none of the previous
ids is served. The stored cascade is `RS-f040698f3e4c0d53` / `RS-7f9e617239897d7b`.
**The server on 8006 serves the new default only after a restart.**

**Open after 29.09.2026:**

1. Global Bonds back to Income (FMRE-25) is in the register and its tests; the **live
   store** takes it on the next bootstrap (`python -m store.etl.bootstrap`), which the owner's
   session runs once the use-case build is finished. The role is not in `return_set_id`.
2. The tail-hedge rule passes Long Volatility Index by a thin margin in USD (+0.03 % a
   month over 34 crisis months). Worth a look whether "the crisis months" should be the
   months a shock begins rather than every month tagged crisis.
3. The SQL Metadata catalogue in Notion does not yet list `cboe.VXTH` or the deactivations;
   regenerate it with `store/etl/notion_metadata.py --all` in a session allowed to write
   to Notion.

### 4.2 Register integrity

Both checks live at `/v1/data/overlap` and `/v1/data/classification`.

**Country exposure (27 September 2026).** The register names the economies each instrument
is exposed to: `instrument.countries_json`, served as `countries` on `/v1/instruments`, with
datafeed country codes, the registry honi's peer set uses. It links the universe to the
Health of Nations Index in the cockpit. The decision is `store/etl/universe.py::COUNTRY_EXPOSURE`:
one explicit entry per instrument, `()` for no single economy, re-applied by every bootstrap.
It was proposed from names, tickers and regions and still needs the CIO's confirmation. Two
tests guard it: every instrument has an entry, and the codes are well formed.

**Resolved** (CIO decisions, recorded in `store/etl/universe.py` with dates):

- `Mining Equities` pointed at MSCI World → re-pointed at a real mining index (XME).
- `Fundo World Equity` duplicated Global Equities → re-pointed at global min-vol (ACWV).
- `Digital Assets` was `stabilisation` with beta 1.67 and −68.9 % in crisis → now `gain`.
  Until 29.09.2026 this reached only freshly built stores: role overrides were written on
  first insert, so the live store still held it in Stabilisation. Every bootstrap now
  re-applies role overrides and deactivations (FMRE-17).
- 29.09.2026: `Global Bonds` → `stabilisation`, then back to `income` (FMRE-25); `Bloomberg Market Neutral HF` confirmed
  `stabilisation`; `Short MSCI US` and `CS Long Vola` deactivated; `Long Volatility
  Index` proxy VIXY → VXTH.

**Still open:** `EU Equities` ↔ `Aktien Europe aktiv` share `MXEU Index` (r = 1.0000) and
`Infrastructure` ↔ `SXI Real Estate` share `SWIIT Index`. Nobody has said what the
duplicates were meant to be.

Also unflagged but large: `Commodities` is `stabilisation` and loses **−45.7 %** in crisis.
Consistent with §11.4 (stabilisers peak in *contraction*), but worth a rule review.

---

## 5. In flight, not finished

*CHF / EUR / USD from 2003 is done (section 4.1a). What follows is the long-history
and real-return part, still open.*

**Real / nominal and the currency matrix.** Brief from the user: use data as far back as it
exists, Deutsche Mark as the EUR proxy before 1999, and **allow a hyperinflation set** —
Germany 1922–23. They accept that the profile becomes *a matrix rather than a vector*
(states × nominal|real × currency), needing more contract surface and more controls.

Design is already settled by the manual: §11.3 says profiles stay **nominal** and real is
obtained by subtracting current inflation **at the point of use**. So this is a consumption
layer, not a change to the stored `ReturnSet` — same reasoning that keeps moments out.

Data position:

- **US real: ready.** `cpi` is already in `long_series`, 1870–2020.
- **CHF / EUR: needs a source.** Yahoo FX only reaches 2003. World Bank CPI reaches 1960.
- **The right source is Jordà-Schularick-Taylor Macrohistory R6** — CPI and USD exchange
  rates for 18 countries including Switzerland and Germany, 1870–2020, free for research.

**Where I got to:** the file downloads from
`https://www.macrohistory.net/app/download/9834512469/JSTdatasetR6.xlsx` — but despite the
`.xlsx` extension and content-type it is a **Stata `.dta` file**, release 118, LSF,
59 variables × 2718 observations (18 countries × 151 years). Saved in the scratchpad as
`JST_R6.dta`.

Next step is a minimal dta-118 reader as ETL-only code (~150 lines; the format is
documented — header, map, variable_types, varnames, then fixed-width rows; type codes
65526=double 65527=float 65528=int32 65529=int16 65530=int8; numeric missing is any value
above the type's threshold). Adding pandas just to read one file is not worth it against
the dependency budget.

---

## 6. Things that cost time — do not rediscover them

- **A cleanup routine must never reach past what it was handed.** `db.drop_schema()` used
  to drop the engine schema *and* the feed schema, while the test fixture gave a throwaway
  name only to the engine one. Every test teardown therefore deleted the real `datafeed`
  schema: 117 series, 26,341 observations, twelve stitched chains and the snapshot. The
  suite reported **206 passed while doing it**, because nothing asserted on what teardown
  touched. Fixed: the feed is dropped only on `include_datafeed=True`, the fixture renames
  both schemas, and `tests/test_isolation.py` watches the teardown. Verified by reverting
  against a decoy feed schema, not the real one.
- **PostgreSQL's `REAL` is four bytes.** Loses ~1.7e-9 on a profile value and would silently
  destroy the 5e-16 claim. Everything is `DOUBLE PRECISION`; a test sweeps
  `information_schema` for `real` and fails.
- **`CREATE TABLE IF NOT EXISTS` cannot add a column.** `schema.sql` has an *Evolutions*
  section at the bottom with idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Add a
  column in both places.
- **A green suite does not mean a working app.** `TestClient` serialises onto one thread;
  a browser fires six requests at once. Two defects hid in that gap. `tests/test_concurrency.py`
  exists for this.
- **Always verify a regression test by reverting the fix.** One test here passed both
  before and after until it was rewritten against a database still in `delete` mode.
- **On Windows, `pkill -f` does not kill Python** started from Git Bash. Use `Stop-Process`,
  and check the log for a bind error before believing a restart happened.
- **Heredocs mangle backslashes in regex.** Write throwaway scripts to a file in the
  scratchpad instead. Cost three failed attempts this session.
- **JavaScript has no implicit string concatenation.** Python habits produce silent syntax
  errors in `testbench/index.html`; `node --check` catches them.
- **MATLAB conventions differ from numpy** — `std` is N−1, `prctile` places order
  statistics at `100·(i−0.5)/n`. Both reproduced in `numerics.py`; they disagree in the
  tails, which is where the interesting states are.

---

## 7. Layout

```
contracts/          frozen, extra=forbid; depends on nothing
engines/fund_map/   numerics · indicators · phases · calibrate · roles · state_map
                    · estimate · forward · currency · service
                    (pure functions; service is the only one the API uses)
store/              config · db (psycopg) · provision (database, roles, grants) · schema.sql
                    · etl/ (long_record, market_signal, universe, bootstrap, datafeed,
                    reference_sources, notion_metadata, fx, cboe, download)
feeds/              yahoo.py + cboe.py + proxy_map.py + security_meta.py: the ONLY
                    network code
api/                main · deps · data (the three-level tester) · integrity
testbench/          9 tabs; not part of the system
tests/              332 tests
```

Three data levels in the bench, as requested: **1 · Raw data** (provenance, raw series,
feed structure) · **2 · Macro & signal** (the nine-step transformation, trace a year, the
quantile bridge, trace a month) · **3 · Performance** (register, performance table, overlap,
classification, per-instrument detail with the estimator diagnostic).

---

## 8. Documentation

- Engine chapter → [sim-tech Instruments](https://app.notion.com/p/3e30ba72543f815a9293d3185db1ccb9)
- Estimator decision note → [the write-up](https://app.notion.com/p/3e80ba72543f816e8092e906dc53ed3f)
- **Full data catalogue** → [Engine 01: Data Feed](https://app.notion.com/p/3e50ba72543f8149a983fa9a8f69be97) §7
- Reusable template → [Engine Build Prompt](https://app.notion.com/p/3e40ba72543f81b89fa2f29da365d507)
- **Metadata rules (generic, all engines)** → [Engine Building Guide](https://app.notion.com/p/3e30ba72543f80549955d5029d2512cd) §7
- **SQL data dictionary** → [SQL Metadata](https://app.notion.com/p/66711547fb0c4a07a61d6f012c0a8830),
  generated by `store/etl/notion_metadata.py --all`. **235 rows**: `simtech` (117 series,
  54 instruments, 22 tables) and `simtech_macro` (21 series, 21 tables, read-only, another
  project). Views: Series, Instruments, Tables, By engine, By quality. Two earlier
  catalogues were trashed on 27 September; this is the only one.
- **A UI-created Notion database cannot be driven by the API.** The first SQL Metadata
  database was made in the Notion UI and its data source id shares the database's own
  prefix (`3e80ba72-543f-80...`); the schema endpoint returns `object_not_found` for it
  however it is shared, while page creation works. A database created *through* the API
  gets an independent data source id and is fully manageable. Not a permissions problem,
  so do not chase connections. Create the database via the API. To fill a UI-created one,
  generate `docs/sql_metadata.csv` with `python -m store.etl.notion_metadata --all --csv`
  and use Notion's **Merge with CSV**, which creates the columns from the headers.
- The `threebody` schema in `simtech_macro` was **renamed to `macrofield`** on 27 September
  2026, mid-session. It was not dropped; the six tables and 78,132 observations are
  intact. `SCHEMA_ENGINES` and the exporter follow the new name.
- **A series description must say what the series is, not how it was computed.** Fifty-one
  public series read "Adjusted close, month on month" until the descriptions were written
  in `feeds/security_meta.py`. Two tests guard it: every symbol in the proxy map and the
  stitch chains must have an entry, and each entry must carry a name, a region and more
  than a token of prose.
- The catalogue is **235 rows**: 117 feed series, 54 instruments, 22 tables in
  `simtech_instruments`, plus 21 series and 21 tables in `simtech_macro`. The 54
  instruments were missing until an audit on 27 September; the catalogue had covered what
  the engine reads but not what it tracks.
- Sections 7 and 8 of the datafeed page were deleted at the owner's request once the
  catalogue existed. They are archived verbatim at
  `docs/archive/datafeed_page_sections_7_8_2026-09-27.md`, because the per-country
  Bloomberg tickers, the public-source fill fits, the gap analysis and the
  still-unsourced list are **not** in the catalogue.

Convention: per-engine docs on the project page, cross-engine lessons in the Documentation
database. Write them when the engine is validated, not before.

---

## 9. Database architecture

**Settled 27 September 2026.** One database for the whole system, one schema per engine,
one login role per engine. The reasoning and the alternatives are in section 8 of the
Engine Building Guide; what matters here is the shape and what is still outstanding.

```
simtech
  fmre         owner fmre        the engine's own artefacts, 15 tables
  fmre_feed    owner fmre        interim private copy of the series it reads, 7 tables
  datafeed     owner datafeed    the shared feed, once Engine 01 moves in
  public       closed            REVOKE ALL FROM PUBLIC; nothing lives here
```

**The boundary is grants, not geography.** `fmre` owns its two schemas, may create schemas
(the tests need throwaway ones), and will hold `SELECT` and nothing more on `datafeed`. It
has no grant at all in `simtech_macro`. `tests/test_provision.py` opens connections as the
real roles and tries the forbidden thing rather than asserting the configuration looks
right; every negative case comes back `InsufficientPrivilege` from the server.

Two accounts exist beside the engine roles:

- **`catalogue`** — read-only, reads across every database, because the metadata export is
  the one tool that must see the whole server and that is exactly what an engine role must
  not do. `information_schema` hides what a role cannot see, so a missing grant would
  silently shrink the catalogue rather than fail; `export_all` raises instead.
- **admin** — `SIMTECH_ADMIN_USER` / `SIMTECH_ADMIN_PASSWORD`, defaulting to `myuser`. Only
  `store/provision.py` uses it. The engine's own credentials cannot create a role.

**Provisioning is code**, not a remembered psql session: `python -m store.provision` is
idempotent and repairs ownership and grants; `--show` prints what is there.

### The Macro repository moved too, 27 September

All four of its schemas -- `datafeed`, `honi`, `macrofield` and **`mrs`** -- are now in
`simtech`, each owned by a role of the same name. 24 tables, 317,050 rows, verified row by
row keyed on schema and table. Their configs read `dbname: simtech` and connect as the
per-engine role. **`simtech_macro` was dropped** once all four Macro suites passed against `simtech`; its
dump is in `Projects/PostgreSQL/backups/simtech_macro_2026-09-27.dump`. Before dropping it
I checked that `simtech` held every table with at least as many rows, and that nothing in
either repository still named it. Six `settings.py` files did: `dbname: str =
"simtech_macro"` as a dataclass default, overridden by `config.yaml` and therefore
invisible to a passing suite. A default pointing at a database that no longer exists is a
trap for the first run made without a config, so those now read `simtech` and default the
user to the engine's own role rather than `postgres`.

**Two things that session caught and I had missed**, both worth remembering:

* My inventory named only three schemas. `mrs` existed and I would have left it behind.
  The full-database `pg_dump` saved it. Enumerate from `pg_namespace`, not from memory.
* The catalogue role could see most of a schema but not tables an engine added later,
  because `ALTER DEFAULT PRIVILEGES` applies only to objects created by the role that set
  it. The export reported three `mrs` tables instead of five and raised nothing: the
  empty-list guard only catches total invisibility. `_check_nothing_hidden()` now compares
  the visible tables against an administrator's list and refuses to publish a short
  catalogue.
* `adopt()` swept `pg_class` and stopped, so every `refuse_change()` trigger function
  stayed owned by the superuser. Those engines re-run their schema on start, so
  `CREATE OR REPLACE FUNCTION` failed with "must be owner of function" on a real start --
  and **no suite could see it**, because the fixtures build throwaway schemas the role
  owns outright. `adopt()` now sweeps functions as well, `unowned()` checks relations,
  functions and types, and `test_every_object_is_owned_by_its_engine` fails if any object
  drifts. Verified by reverting one function's owner.

### Still outstanding
2. **`fmre_feed` should not exist.** It is Fund Map's private copy of series that Engine 01
   ought to serve. It is named for its owner rather than `datafeed` so that two schemas can
   never again answer to the same name, and it retires when this engine reads Engine 01's
   `Panel`. A test fails if anyone renames it back.

**`simtech_instruments` was dropped on 27 September** once the migration was verified.
A `pg_dump` of it is kept at `Projects/PostgreSQL/backups/simtech_instruments_2026-09-27.dump`
(640 KB). The copy had been checked table by table first: 22 tables, 47,616 rows, no
mismatch. The first version of that check keyed on the table name alone and silently
collapsed the two `source_file` tables into one, reporting 21 -- key a comparison on
schema **and** table, or it will report success while dropping a table.
