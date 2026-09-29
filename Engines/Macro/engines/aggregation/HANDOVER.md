# Aggregation layer (aggregation): handover (29.09.2026)

Resume point for whoever picks this up, including a new Claude session. Specification: the Notion
page "Engine 04: Aggregation layer (aggregation)"; tasks "Aggregation layer for the Market Risk
Signal" and "Aggregation: optimism levels and the Rogue targets". Decisions: `DECISIONS.md`.

> Model-derived research output. Not investment advice.

## State

Built, v1.0.0 of the engine, **calibration 1.2.0 active**, with **scenario Regimes** (29.09.2026,
AGG-19 to AGG-22). 102 tests pass (including the cycle 1.1.0 and 1.2.0 mirror, AGG-18, the Manual 10.7 acceptance tests, the role boundary, the REAL sweep, a concurrent burst against a real socket, and the cockpit session's model card) (`python -m pytest`,
needs the PostgreSQL container and the `aggregation` role).

- **1.0.0** is the first draft's combination rule, reproduced to 0.0 on 3,333 monthly rows in 16
  economies (golden layer A: the draft's own `saa_signal.signal_from_state` and `merge`, run on
  this engine's readings).
- **1.1.0** adds the optimism levels as a shift of the combined distribution (targets 10 / 14 /
  19 / 24 at neutral readings) and a 24-month carry of the last macro reading.
- **1.2.0** keeps the crisis tail in place under optimism (AGG-15). Targets, carry and tail
  confirmed by the owner on 28.09.2026.
- Store: `simtech`, schema `aggregation`, role `aggregation`, provisioned 28.09.2026 by
  `Projects/Engines/Instruments/store/provision.py` (the roster now lists `aggregation` on 8004 in
  place of the unbuilt `taa`, and `cycle` on 8012, which had been created by hand).
- **Regimes, 28.09.2026**, on mrs `MRS-7e97c0cadb73be82` (datafeed `bloomberg-2026-01-05`,
  calibration 2.0.0), cycle `CYS-ae1207d818257915`, macrofield `MFS-6183873b127fcd58`, calibration
  1.2.0, as of 2026-01-31: Default `RGM-e2658e8e9bbbc81e` (`AGG-19e06ace80bd6cfb`), Defensive
  `RGM-3198a625d02278fa`, Aggressive `RGM-3004fe8134b20c86`, Rogue `RGM-84547bcbce44aaa0`. All
  carry the snapshot-mismatch warning (AGG-04). cycle and macrofield were not running, so their
  stored artefacts were served in-process; the golden inputs are frozen on the same three. The
  store was rebuilt once on 28.09.2026 (calibration contract 1.1.0); the earlier 1.1.0 Regimes are
  gone.

- **Scenario Regimes, 29.09.2026**, on the Default `RGM-e2658e8e9bbbc81e`, in the real store
  (history to 2026-01-31, projected 2026-02-28 to 2031-01-31, month 60 = 2031-01-31 represents the
  scenario): depression `RGM-1af6968e287768c9` (`AGG-451c8d2ee5fb0bac`), hyperinflation
  `RGM-59eebfaf7744d8ec` (`AGG-36fb373718f6ecbb`), stagflation `RGM-6bb531998bfefc4d`
  (`AGG-33dc16356adc24ff`), deferral `RGM-c0ed086f1916984e` (`AGG-bfad967a5be95d70`). Made in
  process against the real store (the `scenario` table was created by the usual start-up DDL); the
  Default Regime's stored bytes are unchanged. pcp's own `blend_regime` picks 2031-01-31 on them.
  The server on 8004 that was running on 29.09.2026 (started 06:28 from the system Python) predates
  the scenario endpoints: restart it (`start.cmd`) to serve them.

## Next steps

1. **Done (28.09.2026).** Test bench `testbench/index.html` (served at `/` and in the cockpit under
   Test benches: Run on chosen mrs, cycle and macrofield artefacts at an optimism level, the
   risk-state distribution with the crisis tail, the four optimism levels overlaid, the path with
   carried months, the contributions at a date with the tilts, the market blends). The cockpit
   registers the engine (bench, start command, autostart, `aggregation:/run` writable in `cio`
   mode) and shows its Model page (`GET /model`). Checked in Chrome through the cockpit: Default on
   `MRS-7e97c0cadb73be82` / `CYS-ae1207d818257915` / `MFS-6183873b127fcd58` returns
   `RGM-e2658e8e9bbbc81e`, cached. cycle has no `GET /runs`, so the bench offers the cycle artefacts
   earlier Regimes read, and any id typed in.
2. When macrofield reads datafeed: make the snapshot rule a refusal again (AGG-04).
3. Deploy folder: `python dev/make_deploy.py` (built 28.09.2026, engine files only; rebuild for
   the scenarios).
4. Equal-height modes: fixed in code (AGG-23). Still to do by the owner: replace the stored deferral
   scenario record `RGM-c0ed086f1916984e` (AGG-bfad967a5be95d70 -> AGG-91e2e05e126ae47d) as AGG-23
   describes, then restart the server on 8004.
5. SQL Metadata row for the `scenario` table (DECISIONS open point 5).
6. Test bench: the Scenarios tab (issue the four policies on the selected base, the state paths and
   the month-60 distributions overlaid; scenario Regimes appear in the Regime list) is built and
   syntax-checked, not yet checked in a browser.
The SQL Metadata rows for the three tables exist (28.09.2026).

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\Macro\engines\aggregation
..\..\.venv\Scripts\python -m pytest
start.cmd
```

Rebuild the golden files only with a reason recorded in DECISIONS.md (the scenario freeze:
`..\..\.venv\Scripts\python golden\build_scenario_golden.py`):
`..\..\.venv\Scripts\python golden\build_golden.py --cycle CYS.json --macrofield MFS.json [--mrs MRS.json]`
(each file an upstream `GET /artefacts/{id}` body).
