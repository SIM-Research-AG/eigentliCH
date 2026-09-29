# sim-tech Instruments — Fund Map engine

Per-state return profiles for the instrument universe. Publishes a 25-state profile per
role and per instrument, every value carrying the method that produced it, and
deliberately publishes no mean, variance or covariance.

This is the first engine of the real system, built as a FastAPI module with a defined data
flow and a versioned HTTP contract. `System Build Manual` §11 is the specification;
Steiner (2021), *Dynamic Investment*, is the scientific basis.

---

## Run it

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp config.example.toml config.toml                      # then edit it
python -m store.etl.bootstrap --create-database         # first run only
python -m uvicorn api.main:app --port 8006 --reload
```

After the first run, `python -m store.etl.bootstrap` on its own rebuilds the store, and
**`start.cmd`** (double-clickable) starts the engine.

> **Docker running is not enough.** The container is the database and comes back by itself
> after a reboot (`restart: always`). The engine is a separate process and does not — if
> the test bench says it cannot reach `127.0.0.1:8006`, that is almost always why.

Then open <http://127.0.0.1:8006/> for the test bench, or `/docs` for the OpenAPI surface.

**The test bench can also be opened straight off disk** — double-click
`testbench/index.html`. It detects `file://`, calls `http://127.0.0.1:8006` instead of a
relative path, and shows an API field in the header so you can point it elsewhere
(`?api=http://host:port` works too). The engine still has to be running either way: the
page is a client, not a server. Serving it from the engine is simpler when you have the
choice, because everything is then same-origin.

CORS defaults to `*` so the disk-opened case works. **Narrow it before deployment** with
`INSTRUMENTS_CORS_ORIGINS=https://app.example`. It is acceptable as a default only because
the engine binds to localhost, holds no user data and has no session to steal.

```bash
python -m pytest -q                    # 478 tests, against a real server
```

### The store

**PostgreSQL, and only PostgreSQL.** There is no second backend and no in-memory
fallback: the engine has one store, so the tests exercise that store rather than a
stand-in that might behave differently. The suite needs the container up and says so
loudly rather than skipping — a run that goes green by quietly skipping the half that
matters is worse than one that fails.

Each test that needs a store gets **its own throwaway schema**, dropped afterwards, so a
test run can never touch the real one.

**The engine namespaces itself twice**, because the server is shared with other projects:
its own database `simtech_instruments`, *and* its own schema `instruments` inside it.
Either alone would do; both together mean that pointing this at the wrong database still
cannot put a table beside somebody else's. Prefer one database for everything? Set
`dbname` to it and the schema still keeps things apart.

Configuration is `config.toml` (git-ignored; copy `config.example.toml`). Precedence runs
**defaults < file < `DATABASE_URL` < `INSTRUMENTS_DB_*` < test overrides** — the file
describes the shape of the setup and is committed, the password comes from the environment
and is not.

For a hosted database, one variable is enough and it overrides the file entirely:

```bash
INSTRUMENTS_DATABASE_URL=postgresql://user:pass@host.provider.com:5432/db?sslmode=require
```

Two things to check there: `sslmode=require` at minimum (`prefer` silently accepts an
unencrypted connection), and whether the account may `CREATE DATABASE` — many managed
plans say no, in which case point `dbname` at the one they gave you and rely on `schema`.

The two sources are found by environment variable, defaulting to where they live on the
build machine:

| Variable | Default | What it is |
|---|---|---|
| `INSTRUMENTS_ECN_DIR` | `…/Knowledge_Center/Published/Dynamic Investment/Model/ecn_model` | The Steiner workbooks: the long annual record |
| `INSTRUMENTS_FEED_CSV` | `…/andersCH-prototype_old/data/feeds/2026-08-01_andersCH-report.csv` | The monthly andersCH report |

---

## The data flow

```
  Steiner workbooks (19 annual series, 1870–2020)
        │
        │  store/etl/long_record.py      header-guarded, hashed, never back-filled
        ▼
  ┌──────────────┐
  │ long_series  │ ── engines/fund_map/indicators.py ──▶ ec_cycle  (150 years, in σ)
  └──────────────┘                                          │
                                                            │  phases.py
                                                            ▼
                                            5 phases: crisis … boom
                                                            │
  8 block return series ────────────────────────────────────┤  calibrate.py
                                                            ▼
                             per phase: mean + n_obs  ──pchip──▶  25 states
                                                            │
                                                            │  roles.py
                                                            ▼
                             ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
                             ┃  4 ROLE PROFILES — the artefact     ┃
                             ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                                            ▲
  andersCH report (monthly) ─── market_signal.py ───┐       │ seed
        │                                            │       │
        ├─▶ Market Risk Signal, 25 cols × 240 months │       │
        │            │                               │       │
        │            │  state_map.py — QUANTILE bridge       │
        │            ▼                               │       │
        │     signal column ↦ calibration state ─────┤       │
        │                                            ▼       │
        └─▶ 10 instruments' monthly returns ──▶ estimate.py ─┘
             (contribution ÷ weight)                 │
                                                     ▼
                                       per-instrument 25-state profile
                                       cascade: own data → interpolate
                                                → borrow → seed
```

Everything above `store/` is pure computation with no knowledge of storage. Everything
below it is storage with no knowledge of the model. The API talks only to
`engines/fund_map/service.py`.

---

## The published default (29 September 2026)

| | |
|---|---|
| Calibration | `CAL-69d9d1ee5245ac71` (state map `MAP-eb4b581619a03147`) |
| Roles | Gain = equity · **Income = real estate 75 %, equity 25 %** (CIO override, review R-001) · Stabilisation = short rate, commodities, agriculture · Protection = government bonds, gold |
| Register | 54 instruments, **52 active** (Short MSCI US and CS Long Vola deactivated, kept) |
| Estimator | **`forward_12m_smoothed`**: the 12 month forward measurement with a light smoothing across neighbouring states (R-002 decided, FMRE-22), in each series' source currency unless `currency=` is given |
| ReturnSet | `RS-8b6a98484992c9d3` unstamped, `RS-59598b143ab78c56` stamped against `RGM-e2658e8e9bbbc81e` (CHF `RS-c472e411e39645f5`, EUR `RS-dd496e3d3e72affe`, USD `RS-76d1a29edc752997`), contract `rs@1.0.0`, `provenance.currency` null unless a currency is asked for |

The ids are pinned by `tests/test_default_pin.py` and move only by a recorded decision
(`DECISIONS.md` FMRE-15 to FMRE-23). Since FMRE-23 the estimator and the currency are part
of every `return_set_id`. The calibration before R-001, `CAL-092efd097adb0b26`
(Income = real estate alone), stays in the store for comparison and is reproduced from
`roles.ROLE_MAP_BEFORE_R001` by `tests/test_role_map.py`.

Register decisions (role overrides, deactivations, ticker and region corrections, country
exposure) live in `store/etl/universe.py` with their reason and date, and every bootstrap
re-applies them, so a decision reaches a store built before it. An instrument leaves the
universe by deactivation, never by deletion.

## Estimators and currencies (28 and 29 September 2026)

The published profiles are the **12 month forward measurement, lightly smoothed**
(`forward_12m_smoothed`, owner's decision on R-002, FMRE-22), in each series' **source
currency** (CHF for the andersCH recoveries, USD for the public proxies) unless a currency
is asked for. They are computed on request from the stored histories and the public
proxies and never stored. The stored `instrument_profile` rows stay the cascade's: they are
the cascade's peer basis for borrowing, and `profile_method=cascade` reads them back. Every
estimator and currency is its own `return_set_id` (`tests/test_default_pin.py`).

| estimator | what it does | select |
|---|---|---|
| `forward_12m_smoothed` (default) | `forward_12m`, then two passes of a (1/4, 1/2, 1/4) kernel over neighbouring states; no phase value moves by more than 1 point, no state changes sign; label `forward-12m-smoothed` | nothing |
| `forward_12m` | the 12 months after each tagged month (D-02), per phase, honest `n_obs`, pchip onto the 25 states | `profile_method=forward_12m` |
| `shape_scaled` (D2) | role shape, level and amplitude from the instrument's own returns | `profile_method=shape_scaled` |
| `cascade` (stored) | per-state monthly means, interpolate, borrow, seed | `profile_method=cascade` |

Measured on the live store (40 active instruments with history, source currency): mean
jump between neighbouring states 9.13 % cascade, 1.27 % D2, 1.64 % forward, **1.49 %**
forward smoothed; Precious Metals at the crisis knot -4.8 % cascade, **+12.2 %** default
(USD, GLD), +7.7 % in CHF, +10.2 % in EUR. Every forward view keeps the unsmoothed profile
and the five measured phase values beside the smoothed one (`unsmoothed`, `phases`,
`smoothing` on `/v1/instruments/{id}/profile`).

**Protection acceptance per type (FMRE-24):** a tail hedge (price proxy a volatility index)
must pay in the crisis months themselves; cash (asset class `Cash`) must never be negative;
every other protection instrument must be positive in every crisis state in CHF, EUR and
USD and highest in crisis in its source currency. `service.protection_check(view, kind)`;
what cannot hold is named with the reason in `tests/test_protection_forward.py`.

Currency (D-01): `currency=CHF|EUR|USD` converts the monthly returns before estimation
and is named in `provenance.currency` (null on the default);
the rates come from `python -m store.etl.fx` (Yahoo, month end, from 2003). The role curves
are the US long record and are not converted. Where it is on offer:

```
GET /v1/return-set?regime_id=...&currency=CHF                               # the default, in CHF
GET /v1/return-set?regime_id=...&profile_method=cascade                     # the stored cascade
GET /v1/instruments/{id}/profile?currency=EUR    # default, with phases, unsmoothed, smoothing
GET /v1/diagnostics/estimators?currency=USD      # all four side by side (R-002)
GET /v1/diagnostics/income-candidates            # R-001: the chosen Income (A) and its alternatives
```

The test bench shows both: **Estimators · R-002/3** (toggle, currency, the 12 month forward
return after every crisis and contraction month) and **Income · R-001**. Every choice made
here is in `DECISIONS.md`.

## Nominal and real view (29 September 2026)

Everything is stored and published **nominal**; real is derived at the point of use, on
request, and never stored. The owner's nine decisions and the fixed interfaces are in
`Projects/Engines/review/REAL_VIEW_INTERFACES.md`; the choices made here are FMRE-26 to
FMRE-32. Log returns throughout: `real = nominal - ln(1 + inflation)`, per state.

```
GET /v1/inflation?currency=CHF                          # the deflator, 25 states
GET /v1/inflation?currency=CHF&regime_id=RGM-...        # a scenario Regime's own inflation
GET /v1/return-set?regime_id=...&currency=CHF&basis=real
GET /v1/instruments/{id}/profile?currency=CHF&basis=real[&regime_id=...]
```

* **The deflator** is the inflation over the 12 months after each month in a state, from
  Engine 01's monthly `inflation.cpi_yoy` (CHF Swiss CPI, EUR euro-area HICP from 1999 and
  German CPI before, USD US CPI-U), per phase with the floor of six effective years, read
  onto the 25 states by pchip, not smoothed. A thin phase takes today's year-on-year
  inflation, labelled `fallback` (on the snapshot of January 2026: the boom phase, in all
  three currencies).
* **Labels** by the ceiling: `measured` from -10 % to +20 % a year, `extrapolated` to -20 %
  and +100 %, `not_computable` outside. Above the ceiling a real set is computed in CHF,
  then USD, and says so (`provenance.deflator.hard_currency_fallback`, `provenance.currency`);
  if neither qualifies the answer is 422 `not_computable` with the reason.
* **A scenario Regime** is deflated by its policy's inflation (the mean of months 49 to 60,
  `provenance.scenario.inflation_final_12m` from aggregation) in every state; one without
  the field is refused loudly (503), never deflated by history.
* **A real ReturnSet** has its own `return_set_id`, `provenance.basis: "real"` and
  `provenance.deflator`, and its second note names the basis. Role and block profiles are
  the US record in USD and are deflated by USD inflation. Without `currency=` each series
  is deflated in its own currency, stated. `basis=nominal` or no basis is the published
  set byte for byte, and carries neither field (`tests/test_default_pin.py`).

Since FMRE-26 `provenance.estimator` names the estimator that built the instrument
profiles (`forward_12m_smoothed` on the default); it said `plain_mean`, the calibration's.

### Inflation pass-through under a scenario (29 September 2026)

Deflating the historical nominal profiles by a scenario's own inflation treated every
instrument as if its nominal return did not rise with prices: under hyperinflation (63.6 % a
year) gold read -41.5 log points real at the crisis knot in CHF. Since FMRE-33 a scenario
Regime carries each instrument from its **historical real return** to the scenario's
inflation by its pass-through beta (`engines/fund_map/pass_through.py`):

```
r_real(i, s)      = nominal(i, s) - ln(1 + pi_hist(s))          historical per-state deflator
scenario nominal  = r_real(i, s) + beta_i * ln(1 + pi_s)        [+ bond price change]
scenario real     = r_real(i, s) + (beta_i - 1) * ln(1 + pi_s)  [+ bond price change]
bond price change = -D_i * (ln(1 + pi_s) - ln(1 + pi_hist(s)))  a log return, no cap
```

* **Where:** the ReturnSet and the instrument profile under a scenario `regime_id`, in
  `basis=nominal` and `basis=real`. Base Regimes, the nominal default and `/v1/inflation`
  are unchanged byte for byte.
* **House table** `ipt@1.1.0` (`IPT-585c7da4656ead2b`, stored in
  `inflation_beta_calibration` with its source line; `ipt@1.0.0` stays stored): gold and
  precious metals 1.0, commodities 1.0, inflation-linked bonds 1.0, real estate 0.8,
  equities 0.6, **cash 0.0** (it loses the full inflation, no duration), nominal bonds 0.0
  with duration (aggregate 6, government 7, short-dated 0.25), hedge funds and
  alternatives 0.5, digital assets 0.5, volatility 0.5. The register maps onto the types
  by asset class, refined by name and proxy; the full mapping is FMRE-34, its judgement
  calls confirmed by the owner (FMRE-41). The bond loss is a log return since
  `ipt@1.1.0`, so no cap (FMRE-38): under hyperinflation the price change alone is -94 %
  at duration 6 and -97 % at 7.
* **Role profiles** (FMRE-40) follow the same rule with a **blended beta**, the weighted
  beta of their long-record blocks (and the weighted duration of their bond blocks), from
  the historical USD deflator: gain 0.6, income 0.75, stabilisation 0.667, protection 0.5
  with duration 3.5. Block types: equity 0.6, real estate 0.8, government bonds 0 with
  duration 7, gold 1.0, commodities and agriculture 1.0, short rate as cash 0.
  `provenance.inflation_pass_through.roles` names each role's blend and composition.
  **Block profiles carry no pass-through.**
* **Override** by the CIO, append-only and versioned (`inflation_beta_override`):

```
GET /v1/inflation-beta                              # every active instrument: type, house, override, in force
GET /v1/inflation-beta/{instrument_id}/history      # the override versions, newest first
PUT /v1/inflation-beta/{instrument_id}              # {beta 0..1.5 | null, duration?, reason, set_by}
```

  `beta: null` reverts to the house beta, as a new version. The beta in force enters every
  scenario set's `return_set_id` and `provenance.inflation_pass_through` (per instrument
  the beta used and its source, house or override; per role the blend). A role has no
  override: its blocks' types change only by a new calibration version.
* A scenario Regime without `inflation_final_12m` is now refused in nominal as well (503).

---

## What the engine refuses to do

**No moments.** Not a mean, not a variance, not a covariance matrix. A moment is a summary
over states, and summarising over states destroys exactly the information everything
downstream runs on — fold crisis behaviour into a variance and no engine can price crisis
behaviour specifically. `contracts/return_set.py::reject_moments` walks every outgoing
payload and raises on a banned key, **in production, not only in the suite**.

The consumer that genuinely needs a moment computes one at the point of use, against a
regime distribution it chooses, where the choice is visible. `/v1/diagnostics/expected`
does exactly that, and says in its own response that it is not part of the contract.

**No silent fills.** Every one of the 25 values carries a method — `data-driven`,
`data-driven-trimmed`, `interpolated`, `extrapolated`, `borrowed`, `shape-scaled`,
`forward-12m-smoothed` (the default estimator since FMRE-22) or `seed` — and a filled
value reports `n_obs = 0`. The contract validator rejects a profile that violates either
rule. A profile's `coverage` is the *weakest* method it contains, so one seeded state
cannot hide inside an otherwise measured profile.

---

## Validation

The port reproduces Steiner's published 25-state profiles for all eight blocks to a worst
absolute error of **5 × 10⁻¹⁶** across 200 values (`tests/test_reference.py`, against a
frozen fixture so it runs anywhere). Agreement at that precision means the exponential fit,
the seven linear de-trends, the trailing volatility window, the N−1 standardisation, the
phase bounds and the pchip are all correct simultaneously.

All eight shape assertions from §11.3 pass on the live calibration — equity monotone in
the environment, gold peaking in crisis and negative in boom, commodities and agriculture
peaking in contraction, government bonds jumping into crisis, real estate worst in crisis,
the short rate rising with conditions. `/v1/diagnostics/shapes` runs them against the
stored calibration on demand. **If these ever stop passing, the state tagging and the
return series have come apart** — the failure this engine is most likely to ship silently.

**The store is tested directly** (`tests/test_store.py`): the round trip preserves the
reference to the same 5×10⁻¹⁶, re-running the bootstrap produces a byte-identical
calibration, and a test asserts that no column anywhere is single precision — checked by
reverting the column type and confirming it fails, naming all fourteen.

**Concurrency is tested explicitly** (`tests/test_concurrency.py`), because it has to be:
an early version of the store shipped two defects the rest of the suite passed straight
over. `TestClient` serialises requests onto one thread, so neither appeared until a
browser opened the test bench and issued six fetches at once.

Three independent checkpoints on the monthly loader: recovered Global Equities returns
match market history for 2008-10, 2020-02 and 2020-03; the five out-of-tolerance signal
months match the five the prototype's `taa.py` found independently; and the weight-filtered
census reproduces the M9 table exactly for all ten instruments.

---

## Three places this build knowingly departs from the manual

Each is recorded on the artefact rather than hidden, and each has a test asserting the
departure.

**1 · The calibration extrapolates four states.** §11.7 test 6 asks that extrapolation be
impossible by construction. The reference evaluates its interpolant on `0.6:0.2:5.4` over
knots at `1..5`, so states 1, 2, 24 and 25 fall outside the hull. Reproducing the published
figures means reproducing those values; they are labelled `extrapolated` instead of being
suppressed. Clamping them would flatten the crisis tail, and crisis drives CVaR downstream.
*The per-instrument estimator does not extrapolate* — it has no reference to reproduce.

**2 · The default estimator takes a plain mean at every count.** §11.2 specifies a
sufficiency floor of six and a 20 % trimmed mean at twenty. The reference takes a plain
mean throughout. Both are implemented; `Estimator.PLAIN_MEAN` is the default because it is
what the published figures were produced under, and the choice is stamped on every
calibration. Switch with `Estimator.MANUAL_FLOOR`.

**3 · The stored artefact is four role profiles, not eight blocks.** The eight block
profiles are computed on the way there and retained as a diagnostic, because the §11.3
shape assertions are statements about blocks and cannot be checked against roles. They are
served at `/v1/calibration/blocks` and excluded from the published `ReturnSet` by default.

---

## What is not yet true

- **The monthly instrument returns are selection-biased.** They are recovered as
  `contribution ÷ weight` from a tactically managed portfolio, so they describe *the asset
  when the manager chose to hold it*, not the asset in that state. Every such row is stored
  with `source = 'andersch-report:recovered'`. Unconditional index series would fix this;
  nothing else will.
- **The quantile bridge is many-to-one.** Six of the 25 calibration states cannot be
  reached from any signal column, and the grid spans only about ±1.6σ, so the extreme tails
  of the signal clamp. `/v1/state-map` reports both.
- **No feed adapter runs on its own.** `feeds/` holds the Yahoo and Cboe readers, run by
  separate commands (`store.etl.download`, `store.etl.fx`, `store.etl.cboe`); new
  instruments take returns through `POST /v1/instruments/{id}/returns`.

---

## Layout

```
contracts/          frozen, extra=forbid; depends on nothing
engines/fund_map/
  numerics.py       pchip, exp1, trimmed mean, MATLAB percentile — stdlib only
  indicators.py     8 economic indicators → ec_cycle
  phases.py         the five phases and their bounds
  calibrate.py      phase estimates → 25 states
  roles.py          the four role profiles — the stored artefact
  state_map.py      the quantile bridge
  estimate.py       per-instrument cascade (stored), D2, dispatch to forward.py
  forward.py        the 12 month forward measurement and its smoothing (the default, FMRE-22)
  currency.py       CHF / EUR / USD at the point of use (D-01)
  inflation.py      the deflator per regime state and currency; the ceiling (real view)
  pass_through.py   inflation pass-through beta under a scenario Regime (FMRE-33)
  service.py        orchestration; the only module the API talks to
store/
  config.py         where the store lives; file + env, password never in the file
  db.py             psycopg, no ORM, no migrations
  schema.sql        idempotent — DOUBLE PRECISION, never REAL
  etl/              the only place a spreadsheet or raw CSV is read;
                    etl/fx.py loads the two exchange rates, etl/cboe.py the Cboe
                    VXTH index (network, via feeds/)
api/main.py         the versioned /v1 surface
testbench/          a standalone dev front end — NOT part of the system
tests/              478 tests, incl. the frozen reference fixture
```

**Runtime dependencies are four**: `fastapi`, `pydantic`, `uvicorn`, `psycopg[binary]`.
All numerics are hand-written on the standard library — see `engines/fund_map/numerics.py`
for why. There is no ORM and no migration framework: the schema is one idempotent file and
the queries are visible at their call sites, with the little that needs wrapping handled
in `store/db.py`. The offline ETL additionally needs `openpyxl`, and it is never in the
client path.
