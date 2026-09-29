# Cycle Model (cycle): handover (parked 27.09.2026)

Resume point for whoever picks this up, including a new Claude session. The specification is the
Notion page "Engine 12: Cycle Model (cycle)"; every decision is in `DECISIONS.md` (C-01 to C-25).

> Model-derived research output. Not investment advice.

## State

Built and parked. v1.0.0 of the engine, **calibration 1.3.0 active** (capital: peak at the reset, low at saturation, C-21; anchored cycles projected to macrofield's horizon, C-22), contract `cycle-state@1.2.0` (aggregate over the anchored cycles, `superposition_anchored`, review R-004, C-25; stored 1.1.0 artefacts are still served as 1.1.0, C-26), 109 tests pass
(`python -m pytest`, needs the PostgreSQL container; datafeed is bootstrapped by the suite,
macrofield is served from a frozen state).

- **1.0.0** is the port of the first draft (`Macro_Model/macrofield/model/cycles.py`,
  `cycle_bins.py`), reproducing it to 1e-12 on the production snapshot (golden layer A). Kept for
  reconciliation only.
- **1.1.0** carries the author's model decisions of 27.09.2026:
  - capital: historical reset per economy, low at the reset, 90-year rise, 40-year fall, next
    reset at 130 years (C-16);
  - credit: anchored on each economy's crisis low, 18 years (C-17);
  - pulse and business: band-passed from macrofield's output Y in current US dollars, year axis
    back to 1972 (C-18); trailing gap-free span, else the longest (C-19);
  - innovation: low in 2032, 47 years (unchanged from the draft).
- On the production snapshot `bloomberg-2026-01-05` (same cells as the golden input
  `matlab-m_ts-2026-01-05.public-8e90be47` on every series cycle reads) with macrofield artefact
  `MFS-6183873b127fcd58`, every cycle has a position in every economy.

Store: `simtech`, schema `cycle`, role `cycle` (created 27.09.2026 with honi's grants). **Do not rebuild it any more:** aggregation's Default Regime
`RGM-e2658e8e9bbbc81e` (which pcp runs on) was built from the stored artefact `CYS-ae1207d818257915`
(`cycle-state@1.1.0`), whose lineage must stay readable (C-26). On 28.09.2026 it held two artefacts,
`CYS-c6a5185ec9c743a0` and `CYS-ae1207d818257915`, both 1.1.0, both read back identical.

## Open points

1. macrofield still runs on its own static snapshot, not datafeed; when it reads datafeed, check
   the pulse and business cycles again (C-18).
2. macrofield ends in 2024 (IN 2018 after its gap, VN 2022), so those two cycles' current phase
   lags the panel's final year.
3. Credit could later be estimated from long BIS credit-to-GDP history in datafeed instead of
   anchored (C-17).
4. `aggregation` (8004) does not exist yet; it will consume `CycleState` (the 25-bin layer per
   economy and year) and decide its blend weight (the draft used 0.20).
5. macrofield's README lists only `aggregation` as its consumer; `cycle` now reads it too.
6. The test bench (`testbench/index.html`) has never been looked at in a browser. Its "Over time"
   tab (R-004) draws the aggregate: `superposition` solid, `superposition_anchored` dashed after the
   data edge, `alignment` below with the synchrony windows shaded. The cockpit's own copy of that
   chart (`cockpit/src/cockpit/static/index.html`, "One economy over time") is not updated from here.
7. honi's tests pin the datafeed raw snapshot `.r2`; datafeed now bootstraps `.r3`. This engine's
   conftest reads the id from `datafeed/golden/snapshot_2026-01-05/manifest.json`.
8. **macrofield to 2080 (review R-005).** cycle projects to the last year of macrofield's
   `projection.years` (max over the requested economies, `service._execute`). When macrofield
   computes to 2080: (a) cycle pins `macrofield-state@1.2.0` (`UpstreamMacroState`); a contract
   bump there makes every cycle run fail until the pin is updated; (b) if macrofield keeps
   `projection.years` to 2039 and adds a separate computed horizon, cycle stays at 2039; if
   `projection.years` runs to 2080, cycle's axis runs to 2080 and the charts need to clip to the
   display horizon unless cycle is told it; (c) to 2080 the capital cycle passes the next reset
   (US 2063, EU/GB/JP 2075, CN/DE 2078) and starts a new 130-year turn, and innovation reaches its
   next low (2079): a model question, not a code one; (d) the API tests pin 2039 on the frozen
   macrofield state, and only change if that state is rebuilt. Observed figures do not move with
   the horizon, nor does `superposition_anchored` (tested with 2080).

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
engines\datafeed\start.cmd
engines\macrofield\start.cmd          :: needs one successful macrofield run
engines\cycle\start.cmd               :: http://127.0.0.1:8012/ (test bench), /docs
cd engines\cycle && ..\..\.venv\Scripts\python -m pytest
```

Rebuild the golden files only with a reason recorded in DECISIONS.md:
`..\..\.venv\Scripts\python golden\build_golden.py` (datafeed on 8001, macrofield on 8003).
