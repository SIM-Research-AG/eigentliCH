# Portfolio Creation Program (pcp): handover

Where the build stands, how to pick it up, and what is still open. The README is the reference; this file is
the resume point. Model-derived research output; not investment advice.

## State (29.09.2026)

- **Engine 07, v1.2.0**, calibration **1.1.0 active** (1.0.0 reproduces the draft). Built by Nicolas, taken over
  from Tino on 28.09.2026. 119 tests pass (`python -m pytest`, about 30 s, needs the PostgreSQL container).
- **Feasibility and convergence** (29.09.2026, PCP-21): all 18 failed runs in the store (11 mandates; 10 runs
  Income focus, 6 Growth global, 1 Swiss home bias, 1 Balanced CHF) were infeasible as stated and passed `/validate`: a bucket floor above what its
  instruments can hold under `max_single_position` (one Gain instrument under a derived Gain floor of 0.171, three
  CHF instruments under a CHF floor of 0.5), or rows in conflict across dimensions (an equity floor above the Gain
  ceiling). `/validate` and every run now refuse them before solving and name the rows (a per-bucket check and a
  phase-1 linear programme). When the calibrated solve does not settle on a feasible block, the engine restarts from
  the phase-1 point with the exact settings on the non-implied rows. Engine-level, no new calibration; layer A
  unchanged. **The running server on 8007 still has 1.1.0 until the owner restarts it.** All of these mandates started
  from cockpit presets that left a role thin or empty or set an equity floor above lbs's Gain ceiling (fixed in the
  cockpit, C-29).
- **Reporting currency** (owner, 29.09.2026, PCP-18 to PCP-20): the mandate's `currency` is CHF, EUR or USD
  (CHF by default); pcp asks fmre for the ReturnSet in it (`&currency=`), refuses a set in another currency or
  in none, and the Allocation states it (`currency`, `provenance.currency`). No contract version moved: CHF
  mandates written before still validate with the same `mandate_id`. The consumers must send the
  `return_set_id` fmre serves for the Regime **in the mandate's currency**: the currency is part of that id.
- **Nominal and real view** (owner, 29.09.2026, PCP-22, `review/REAL_VIEW_INTERFACES.md`): the mandate's optional
  `basis` (`nominal` by default, or `real`) is the basis of its target curve. pcp asks fmre for `&basis=real`,
  refuses a set on another basis (none counts as nominal) and fmre's `not_computable`, and the Allocation states
  `basis`. Nominal is untouched byte for byte: the same query to fmre, the same `mandate_id`, idempotency key and
  `artefact_id` (pinned in `tests/test_basis.py`). No version moved. Tested against the stand-in only: live fmre
  on 8006 serves `basis=real` once it is restarted with the real view. The consumers must send fmre's **real**
  `return_set_id` for a real mandate: the basis is part of that id. **8007 serves none of this until restarted.**
- **Hard-currency fallback accepted** (owner, 29.09.2026, PCP-23): a real set fmre measures in CHF (then USD)
  because the mandate's currency's inflation left the -20 % to +100 % band is accepted only when
  `deflator.hard_currency_fallback.from` is the mandate's currency and `to` the served one; any other currency
  mismatch stays refused. The Allocation's `currency` and `provenance.currency` are then the hard currency,
  `provenance.hard_currency_fallback` is fmre's `{from, to, states, reason}`, and a warning says it in plain words.
  `report` and the cockpit should show `currency`, `provenance.hard_currency_fallback` (from, to, states) and the
  warning that starts "real, measured in". Tested against the stand-in only.
- Store: database `simtech`, schema `pcp`, role `pcp` (provisioned by `Instruments/store/provision.py`,
  `pcp` in `ROSTER` and `OWNED_HERE`). Password in `config.local.yaml` (git-ignored).
- Golden layer A (the eigentliCH draft, 7 mandates) reproduced to 2e-14 on weights; layer C frozen.
- The owner's rulings of 28.09.2026, recorded in `DECISIONS.md`: the draft's per-instrument objective (PCP-03),
  identity of the state axes (PCP-05), the client's regime blended per client from economy weights (PCP-04),
  the strict `regime_id` rule (PCP-11).
- **Runs live**: pcp asks fmre for the ReturnSet stamped against the requested Regime in the mandate's currency
  (`/v1/return-set?regime_id=...&currency=CHF`); fmre confirms the Regime with aggregation, stamps it and converts
  the instrument series (29.09.2026: `RS-dced0b32e07034f9` CHF, `RS-9f2eab022c08c81a` EUR for the Default Regime).
  Checked in process against live fmre: both validate and solve (CHF `balanced_global` at 2024-12-31, objective
  26.864). Layer C (28.985) no longer reproduces live: it is the frozen source-currency set, read as CHF (PCP-20).

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\Macro\engines\aggregation && start.cmd
cd Projects\Engines\Instruments && start.cmd
cd Projects\Engines\Optimizer\engines\pcp && start.cmd       :: 8007, test bench at http://127.0.0.1:8007/
..\..\.venv\Scripts\python -m pytest
```

Refreeze the test inputs after an upstream change: `python dev/freeze_inputs.py` (aggregation and fmre running),
then `python dev/build_golden_production.py`, and check the layer C diff before committing it.

## Next steps, in order

1. **Restart 8007** (owner) to serve 1.2.0 (PCP-21), then rebuild the use cases whose runs failed from the
   cockpit's `mp@1.1.0` presets (C-29). A mandate whose bounds still conflict (a CHF floor above what its CHF
   instruments hold, a growth preset under a Gain ceiling of 29 %) is refused at `/validate` with the rows named.
2. **Real view live** (PCP-22, PCP-23): once fmre serves `basis=real`, validate a real `balanced_global` against
   it in process, and, where fmre falls back, check that live fmre's fallback set validates with its own
   `return_set_id` and that `report` and the cockpit show the hard currency and the warning.
3. **fmre to publish `provenance.currency`** on the ReturnSet (`CHF`, `EUR`, `USD`, or null for the source
   default). Until then pcp reads fmre's opt-in note `... in currency=CHF; ...` (PCP-19); the field replaces it
   with no change here. Then refreeze (`dev/freeze_inputs.py`, now CHF), rebuild layer C and update PCP-20.
4. **Weights barely move the objective** on 54 instruments (about 0.6%, PCP-03): decide whether that is
   accepted, or whether `profile_scale` (MATLAB's effective 100) or a smaller universe is the answer. Each is a
   new calibration.
5. fmre to publish economic phase, home scenario and a real ESG score per instrument (PCP-06); until then the
   calibration table carries them and row 57 is inert.
6. Golden layer B: the MATLAB Review workbooks (`SIM_Tech/Master_Controller/Review`), with their full bound
   blocks and classifications; compare objectives within a few per cent (PCP-17).
7. The cockpit's CIO decisions (optimiser bounds, HoNI per-country bounds) as a bound source: the Manual allows
   only `derived` and `policy` (cockpit decision C-06 waits for this Mandate contract).
8. Deploy folder when signed off: `python dev/make_deploy.py`.

## Where things are

| Path | What |
|---|---|
| `README.md` | Reference: model, contracts, endpoints, calibrations, quality |
| `DECISIONS.md` | PCP-01 to PCP-23 |
| `src/pcp/` | Engine; pure core in `engine.py`, `objective.py`, `constraints.py`, `solver.py` |
| `golden/draft/` | Layer A, frozen from the draft by `dev/build_golden_draft.py` (run it with the draft's `.venv`) |
| `golden/inputs/`, `golden/production/` | Layer C: frozen Regime, ReturnSet and register; this build's outputs |
| `testbench/index.html` | Development UI: the Manual's five charts and the portfolio map; a Currency select (CHF, EUR, USD) and a Basis select (nominal, real) |
