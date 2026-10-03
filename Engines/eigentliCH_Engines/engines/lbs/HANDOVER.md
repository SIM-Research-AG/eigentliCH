# Life Balance Sheet (lbs): handover

Where the build stands, how to pick it up, and what is still open. The README is the reference; this file is the
resume point. Model-derived research output; not investment advice.

## State (03.10.2026)

- **The test bench shows what lbs does** (LBS-42, owner's decisions of 03.10.2026, `review/VISUALS_INTERFACES.md`):
  a plain explanation, a picker of real use-case clients that loads a stored sheet and its request (new read-only
  route `GET /bench/candidates`), and the sheet drawn as inline SVG graphs (the life balance sheet, the four capitals
  per adult, the BVG balance, the target curve) with a nominal and real switch. Plotly is gone from the bench. The
  sheet contract, its figures, the calibrations and the engine version (`lbs@1.4.0`) are unchanged, so every
  idempotency key and stored sheet stands. 475 tests pass. **The running server on 8013 needs a restart** to serve
  the new route (the page itself is read from disk on each request, so it already shows, with an empty picker).

## State (29.09.2026)

- **Engine 13, v1.4.0**, calibration **1.5.0 active**: the deterministic life balance sheet from the eigentliCH
  prototype's services (owner's ruling of 28.09.2026; `personal_alm` is left for `lbsim`), with the owner's
  decisions of 29.09.2026 built (LBS-23 to LBS-30), the nominal and real view (LBS-31 to LBS-35,
  `review/REAL_VIEW_INTERFACES.md`), the owner's decisions on its two assumptions (LBS-36 to LBS-38: CHF
  inflation 1.0 %, the plausibility table approved) and the lbs part of the lbsim build (LBS-39 to LBS-41,
  `review/LBSIM_INTERFACES.md` section 4): the answers lbsim reads carried in the request, validated and never
  computed from, and `GET /artefacts/{artefact_id}/request`. 473 tests pass (`python -m pytest`, needs the
  PostgreSQL container); forty-three guarded rules mutation-checked.
- Calibrations, append-only, each a child of the one before: **1.0.0** the prototype reproduced (records as
  shipped), **1.1.0** `ahv-pension` and `risk-profile` approved by Nicolas on 29.09.2026 (content unchanged, the
  prototype's behaviour otherwise), **1.2.0** the four LBS-17 quirks corrected, **1.3.0** three more corrections
  (LBS-28): a human-capital stock is never free wealth, a stated mortgage of 0 is a paid-off mortgage, and the
  yearly saving is split between goals by `goals[].contribution_share`, **1.4.0** the nominal and real view: goal
  amounts in today's francs unless stated (inflated to their date at CHF 0.50 % a year, the datafeed's 2006 to 2026
  mean), an indexed contribution when stated, both views on the sheet, the retirement comparison in today's
  francs, and a plausibility judgement of the required return, **1.5.0** the owner's decisions on 1.4.0's two
  assumptions: CHF inflation 1.0 % a year (the midpoint of the SNB's 0 to 2 % range, forward-looking; EUR 2.11 %
  and USD 2.54 % stay measured) and the plausibility table (2 %, 3.5 %, 5 % real at risk levels 0, 0.5, 1)
  approved unchanged. 1.0.0 to 1.4.0 stay selectable with `calibration_version`, unchanged, their hashes pinned
  (`CAL-2c0d67f4f820dfc9`, `CAL-e69eb8fc77af48a3`, `CAL-6e23bd89792ac4dc`, `CAL-2fa18ff0a38495b5`,
  `CAL-99a3654972f86773`); 1.5.0 is `CAL-fdf122697c7aa04b`.
- Store: database `simtech`, schema `lbs`, role `lbs`; 1.0.0 to 1.2.0 are in the real store. 1.3.0, 1.4.0 and
  1.5.0 are written by the service's startup (or `init-db`) the first time lbs@1.3.0 starts against it. Password in
  `config.local.yaml` (git-ignored).
- Golden layer A (the prototype, 15 cases under 1.0.0 and 1.1.0) reproduced exactly (659 figures, deviation 0).
  Golden layer B, step 1.2.0 (19 cases, against 1.1.0) unchanged, rebuilt byte for byte; step 1.3.0
  (`golden/corrected/1.3.0`, 23 cases, against 1.2.0) frozen: each new case moves by its own correction only,
  prototype cases only where they exercise one (`db-01`, `db-05`, `syn-couple`, and the share gap of every
  multi-goal household); step 1.4.0 (`golden/corrected/1.4.0`, 28 cases, against 1.3.0) frozen, each changed leaf
  attributed to one of four parts (LBS-35); step 1.5.0 (`golden/corrected/1.5.0`, the same 28 cases, against
  1.4.0) frozen with `changes.json` (832 leaves, each with its decision and kind of figure) and
  `required_returns.json` (LBS-38); the earlier steps rebuilt byte for byte (their manifests name the building
  engine, lbs@1.3.0, unchanged by 1.5.0).
- Contracts: `lbs-request@1.0.0` gains the optional `goals[].contribution_share`, `goals[].amount_basis`,
  `mandate.contribution_indexed`, `persons[].earning_power` and six `facts` (no version change); `lbs-balance-sheet@1.0.0` gains optional fields only, left
  out while unset; the calibration contract is `lbs-calibration@1.3.0`.
- Records still provisional and read ungated as in the prototype: `intake-scales`, `roles`.
- **The server on 8013 runs whatever code it was last started with.** This build did not restart it (the
  coordinator does); until it is restarted on lbs@1.4.0 it refuses `earning_power` and the six new `facts` as
  unknown fields and has no `/artefacts/{artefact_id}/request`, which lbsim needs.
- Store for lbsim: `Instruments/store/provision.py` lists `lbsim` as built and owned there; `python -m
  store.provision` created role `lbsim` and schema `lbsim` (owned by it, no tables yet) on 29.09.2026. Checked with
  the role's own login: it creates and writes in `lbsim`, reads `datafeed`, and is refused in `lbs`, `pcp`,
  `eigentlich`, `public` and `datafeed` writes.

## What the consumers must know (report, cockpit, consumer app)

lbs@1.4.0 (LBS-39 to LBS-41, calibration unchanged):

- Request, optional: `persons[].earning_power` (`expected_full_pensum_income`, `responsibility`, `sector`,
  `education_status` none / in_progress / planned, `education_end_year`, `education_hours`,
  `education_budget_per_year`, `health_work_capacity`) and `facts.stop_work_age`, `.legal_documents`,
  `.mortgage_fixed_until`, `.amortisation_mode` direct / indirect, `.own_use_share`,
  `.pillar3a_contribution_per_year`. Send each only when it is stated; ranges and checks in the README.
  `responsibility` is a tier of the calibration's `human-capital` record, by key or by its German or English
  label (the app's "Keine Führungsfunktion", "Oberes oder mittleres Kader", "Oberste Führung" are labels); anything
  else is a 422. `health_work_capacity` is K3: while `human_capital.health_withheld` is true it is refused, so the
  K3 filter must drop it together with `health`. `earning_power` on a dependant is refused.
- The sheet is unchanged: `human_capital[].earning_power` stays `not_available` with the gap
  `owned_by_another_engine`; lbsim computes it (LBS-41). A request with any new answer is a new request hash and so
  a new sheet, which is lbsim's trigger.
- New: `GET /artefacts/{artefact_id}/request` returns `{artefact_id, request_hash, contract_version:
  "lbs-request@1.0.0", request}` from the run that built the sheet; `request_hash` equals the sheet's
  `provenance.request_hash`; 404 for an unknown sheet.
- Values move: `provenance.engine_version` `lbs@1.4.0` and so new idempotency keys and new artefact ids for every
  request (a re-run under 1.4.0 is a new sheet). The request hash of a request without the new fields is unchanged
  (pinned on all 28 golden cases); no contract version changes.

Calibration 1.5.0 (lbs@1.3.0, no code or contract change):

- **Figures move on purpose** (LBS-36): at CHF 1.0 % a goal in today's francs has a higher target in francs of
  its date and, with a fixed saving, a higher required return, nominal +0.63 to +0.78 points and real +0.06 to
  +0.22 points on the golden cases (the worked example: 0.90 % to 1.60 % nominal, 0.39 % to 0.59 % real, the
  target 441,958.23 to 488,076.02). An indexed saving keeps its real required return; a goal in future francs its
  nominal one. The retirement comparison covers less (the BVG pension deflated at 1 %): shortfalls grow, and a
  verdict can flip (`v-retirement`: meets to does not meet). No plausibility judgement flips in the cases. The list
  is `golden/corrected/1.5.0/changes.json` and `required_returns.json`.
- Strings: `real_view.inflation.source` names the owner's decision; `mandate_proposal.plausibility.ceiling_source`
  says the table is approved. `real_view.inflation.label` stays `measured` (decision 4's band, not the method).
- Values move: `calibration_version` `1.5.0`, new idempotency keys; `engine_version` and every contract version
  unchanged.

The nominal and real view (lbs@1.3.0, calibration 1.4.0):

- Request, optional: `goals[].amount_basis` `today|future` (the app's "in heutigen Franken?", default ja, maps to
  `today`) and `mandate.contribution_indexed` bool ("steigt der Betrag mit der Teuerung?", default nein, maps to
  false). Not sending them is the owner's default: today's francs, fixed contribution.
- **Figures move under 1.4.0 on purpose** (decision 7): a mandate on a dated goal amount now has
  `target_chf` in francs of the target date and a higher nominal `required_return` and curve; the retirement
  finding compares in today's francs (the BVG pension deflated), so `covered_per_year` and `shortfall_per_year`
  move. The per-case list is `golden/corrected/1.4.0/changes.json`.
- Sheet, additive: `real_view` (inflation `{currency, index, annual_rate, log_rate, label, source}`,
  `contribution_indexed`, `goals[]` with `nominal` and `real` amounts), `mandate_proposal.basis` (`nominal`),
  `mandate_proposal.views.{nominal,real}` (`target_chf`, `required_return`, `required_return_log`, `basis`),
  `mandate_proposal.plausibility` (`judgement` realistic / not_realistic / could_not_be_determined, ceilings,
  `levers`), `retirement[].basis` (`real`) and `.views.{real,nominal}`, `property[].basis` (`real`). A mirror that
  forbids unknown fields must add them before reading a 1.4.0 sheet.
- **report** in `basis: real` takes `mandate_proposal.views.real` and the retirement finding (already real); in
  nominal, the top-level figures (`basis: nominal`) and `retirement[].views.nominal`. Show `plausibility` next to
  the required return; `feasible` alone no longer says the goal is reachable in practice.
- **pcp**: the proposal's curve is nominal; the Mandate's optional `basis` is `nominal` (pcp's default).
- Values move: `provenance.engine_version` `lbs@1.3.0`, `contract_versions.Calibration` `lbs-calibration@1.3.0`,
  `calibration_version` `1.4.0`, new idempotency keys; the request hash of a request without the new fields is
  unchanged.

Earlier (lbs@1.2.0, calibration 1.3.0):

- No request or balance-sheet field was removed or retyped. One request field was added, optional:
  `goals[].contribution_share` (0 to 1, the goal's share of `mandate.annual_contribution`; the stated shares sum
  to at most 1, more is a 422). A consumer that does not send it needs no change; a mirror that forbids unknown
  fields should add it before the app asks the share.
- Consumer app, when it asks the share per goal: send it on each goal. Without it, under 1.3.0 a household with
  more than one goal gets the required return at the most the designated goal can receive (a lower bound), a gap
  `mandate_proposal` / `contribution_share`, and a note; a household with one goal is read as before.
- `mandate_proposal.annual_contribution` is now the designated goal's part of the saving (equal to the saving
  when no share is stated); the notes name the household's saving and the share.
- Values move: `provenance.engine_version` `lbs@1.2.0`, `provenance.contract_versions.Calibration`
  `lbs-calibration@1.2.0`, `calibration_version` `1.3.0`, new idempotency keys (a re-run is a new artefact); the
  request hash of a request without the new field is unchanged. A stated mortgage of 0 now scores the capacity's
  debt-service component; a human-capital stock in chf no longer raises the free share or the reserve, and is
  not equity for a property goal.
- New strings: gap inputs `contribution_share` (section `mandate_proposal`) and `<position>.capital_type`
  (section `property.<goal>`); capacity sources naming the human-capital stocks left out and "a stated mortgage
  of 0 is a paid-off mortgage".
- Still true from lbs@1.1.0: the onboarding's "How much can you put aside each year?" goes into
  `mandate.annual_contribution` (CHF per year; 0 is a stated 0, leave it out when unanswered), inside `mandate`,
  so a request must designate a goal to carry it.

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\eigentliCH_Engines\engines\lbs && start.cmd       :: 8013, test bench at http://127.0.0.1:8013/
..\..\.venv\Scripts\python -m pytest
..\..\.venv\Scripts\python dev\mutation_check.py
```

Refreeze layer A after a change in the prototype (read-only use; the prototype's interpreter):
`C:\...\eigentliCH\Prototype\.venv\Scripts\python.exe -X utf8 dev/build_golden.py`, then check the diff.
Refreeze layer B only for a deliberate change in lbs: `..\..\.venv\Scripts\python -X utf8
dev/build_golden_corrected.py`, then read the diff of `golden/corrected/changes.json`.

The editable install's metadata (`src/lbs.egg-info`) still says 1.0.0 until the next
`pip install --no-deps -e .`; the engine reports its version from `lbs/__init__.py`.

## Next steps, in order

1. Restart the lbs server on 8013 so it serves lbs@1.4.0 (the coordinator's step); lbsim reads
   `/artefacts/{artefact_id}/request` from it.
2. Consumer app and report: ask and send `amount_basis` and `contribution_indexed`; read the real view and the
   plausibility judgement (above).
3. Curator and pcp: finalise the mandate proposal's hand-over (which derived dimensions pcp takes from lbs, how
   the curator fills universe, position cap and regime blend) and whether retirement goals get a withdrawal rate.
4. Consumer app: ask the share of the yearly saving per goal and send `goals[].contribution_share` (LBS-29).
5. Owner: approve (or not) `intake-scales` and `roles`, still provisional and read ungated.
6. Storage and access rules for client data (README open points).
7. Deploy folder when signed off: `python dev/make_deploy.py`.
