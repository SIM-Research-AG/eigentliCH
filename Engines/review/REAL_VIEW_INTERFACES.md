# Nominal and real view: the interfaces (fixed for the build of 29.09.2026)

The design note is the Notion page "Design note: nominal and real view" (`3ea0ba72543f81fcb0a4c47178754f4b`).
The owner's decisions of 29.09.2026 bind every part. Everything below is **additive and opt-in**: no
contract version string moves, every existing request without the new fields behaves exactly as today,
and stored artefacts read back unchanged.

## The owner's decisions

1. **Deflator:** the inflation measured in each regime state over the following 12 months (the same
   horizon as the returns, D-02). A state with too little data takes today's year-on-year inflation,
   labelled `fallback`.
2. **Scenario Regimes** use their policy's own inflation path from `Scenario_SAA.m`, never the historical
   per-state inflation.
3. **Index per currency:** CHF uses Swiss CPI. EUR uses the euro-area HICP from 1999 and German CPI
   before. USD uses US CPI-U. The index is always the reporting currency's.
4. **Ceiling:** real figures are computed for inflation from -20 % to +100 % a year. From -10 % to +20 %
   they are labelled `measured`; the rest of the band is labelled `extrapolated`.
5. **Above the ceiling** (or below -20 %): a hard-currency real view, first CHF, then USD, labelled.
   If neither is inside the band, the view is `not_computable` with the reason.
6. **The default view is nominal everywhere** (the app and the cockpit), with a switch. The basis is
   always shown next to the figures.
7. **Goal amounts:** the client says whether an amount is in today's francs or future francs. **The
   default is today's francs**, and lbs inflates the amount to the target date.
8. **Germany 1922-23** is a stress case only, never estimation data. It is not part of this build.
9. **Yearly contribution:** the client says whether it rises with prices. The default is fixed in francs.

Macrofield always stays nominal. Everything is stored nominal; real is derived at the point of use.
Log returns throughout: `real = nominal - ln(1 + inflation)`.

## fmre (Engine 06, `Projects/Engines/Instruments`), the source of the deflator

- `GET /v1/inflation?currency=CHF|EUR|USD[&regime_id=]` returns `{currency, index, method, states: [{state, inflation, log_inflation, label, n_obs}] x25, as_of, source}`.
  - `label` is `measured`, `extrapolated`, `fallback` or `not_computable`.
  - With a scenario `regime_id`, it returns the scenario's inflation for every state (decision 2).
- `GET /v1/return-set` and the instrument profile endpoints take an optional `basis=nominal|real`
  (default `nominal`, unchanged).
  - A real set subtracts the per-state log inflation of its currency, or of the scenario.
  - The basis enters the `return_set_id`.
  - `provenance` gains optional `basis` and `deflator` fields: `{currency, index, method, per-state labels, hard_currency_fallback}`.
  - A notes line names the basis.
  - `basis=real` without `currency=` uses the source currency, stated.
- Scenario inflation comes from the aggregation scenario Regime's `provenance.scenario.inflation_path`
  (see aggregation below). It is the average annual inflation over the final 12 months of the 60-month
  path, applied to every state.

## aggregation (Engine 04, `Projects/Engines/Macro/engines/aggregation`)

- Scenario Regimes gain an optional `provenance.scenario.inflation_path`: 60 monthly annualised rates,
  the policy's path from `Scenario_SAA.m`, identical to macrofield's TB-21 values.
- It also gains `provenance.scenario.inflation_final_12m`: the average over months 49 to 60.
- Base Regimes do not carry the field (it is left out of the JSON), so their bytes and ids stay unchanged.
- Existing scenario Regimes are re-issued only if their id must change. Prefer adding the field so the
  id does not move, and record the choice.

## pcp (Engine 07, `Projects/Engines/Optimizer/engines/pcp`)

- The Mandate gains an optional `basis: nominal|real` (default `nominal`). It is the basis of its
  `target_curve`.
- pcp asks fmre for the ReturnSet with `basis=` and refuses a served set whose `provenance.basis`
  differs, like currency and `regime_id`.
- The Allocation states `basis`. The basis enters the idempotency key.

## lbs (Engine 13, `eigentliCH_Engines/engines/lbs`)

- The request gains optional `goals[].amount_basis: today|future` and
  `mandate.contribution_indexed: bool`.
  - A missing `amount_basis` means `today` (decision 7). This changes today's figures on purpose, as a
    new calibration with the changed figures listed.
  - A missing `contribution_indexed` means fixed.
- Inflation assumption: a calibrated long-run expected inflation per currency, with its source (the fmre
  `/v1/inflation` mean or a stated house assumption). lbs does not call fmre at run time; its
  calibration is versioned.
- The sheet gains, additively, a real view of the goal figures and the required return: each figure
  carries a `basis`, and nominal and real sit side by side.

## report (Engine 15, `eigentliCH_Engines/engines/report`)

- `report-request@1.0.0` gains an optional `basis: nominal|real` (default nominal).
- The report shows its basis in the header and next to every return and goal figure.
- In real, it takes the real figures from the lbs sheet and the Allocation's basis. It refuses a mix.

## The consumer app (`eigentliCH_Engines/eigentlich`) and the cockpit (`Projects/Engines/cockpit`)

- **Questions:** each goal gets "in heutigen Franken?" (default ja), and the contribution gets "steigt
  der Betrag mit der Teuerung?" (default nein). Both are new content versions. They map to
  `amount_basis` and `contribution_indexed`.
- **Switch:** a nominal / real switch, default nominal, on the app's home, plan and reports, and on the
  cockpit's Parameters page and instrument views. The basis is always shown.
- Both pass `basis` to pcp, fmre and report.
