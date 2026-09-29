# Life Balance Sheet (lbs): handover

Where the build stands, how to pick it up, and what is still open. The README is the reference; this file is the
resume point. Model-derived research output; not investment advice.

## State (29.09.2026)

- **Engine 13, v1.2.0**, calibration **1.3.0 active**: the deterministic life balance sheet from the eigentliCH
  prototype's services (owner's ruling of 28.09.2026; `personal_alm` is left for `lbsim`), with the owner's
  decisions of 29.09.2026 built (LBS-23 to LBS-30). 268 tests pass (`python -m pytest`, needs the PostgreSQL
  container); twenty-nine guarded rules mutation-checked.
- Calibrations, append-only, each a child of the one before: **1.0.0** the prototype reproduced (records as
  shipped), **1.1.0** `ahv-pension` and `risk-profile` approved by Nicolas on 29.09.2026 (content unchanged, the
  prototype's behaviour otherwise), **1.2.0** the four LBS-17 quirks corrected, **1.3.0** three more corrections
  (LBS-28): a human-capital stock is never free wealth, a stated mortgage of 0 is a paid-off mortgage, and the
  yearly saving is split between goals by `goals[].contribution_share`. 1.0.0, 1.1.0 and 1.2.0 stay selectable
  with `calibration_version`, unchanged, their hashes pinned (`CAL-2c0d67f4f820dfc9`, `CAL-e69eb8fc77af48a3`,
  `CAL-6e23bd89792ac4dc`).
- Store: database `simtech`, schema `lbs`, role `lbs`; 1.0.0 to 1.2.0 are in the real store. 1.3.0 is written by
  the service's startup (or `init-db`) the first time lbs@1.2.0 starts against it. Password in
  `config.local.yaml` (git-ignored).
- Golden layer A (the prototype, 15 cases under 1.0.0 and 1.1.0) reproduced exactly (659 figures, deviation 0).
  Golden layer B, step 1.2.0 (19 cases, against 1.1.0) unchanged, rebuilt byte for byte; step 1.3.0
  (`golden/corrected/1.3.0`, 23 cases, against 1.2.0) frozen: each new case moves by its own correction only,
  prototype cases only where they exercise one (`db-01`, `db-05`, `syn-couple`, and the share gap of every
  multi-goal household).
- Contracts: `lbs-request@1.0.0` gains the optional `goals[].contribution_share` (no version change);
  `lbs-balance-sheet@1.0.0` unchanged in shape; the calibration contract is `lbs-calibration@1.2.0`.
- Records still provisional and read ungated as in the prototype: `intake-scales`, `roles`.
- **The server on 8013 still runs the old code.** It was not restarted in this build (another agent was using it
  for the use-case build); it must be restarted to serve lbs@1.2.0 with calibration 1.3.0. Until then it
  refuses `contribution_share` as an unknown field.

## What the consumers must know (report, cockpit, consumer app)

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

1. Restart the lbs server on 8013 so it serves lbs@1.2.0 with calibration 1.3.0 (and seeds 1.3.0 in the store).
2. Curator and pcp: finalise the mandate proposal's hand-over (which derived dimensions pcp takes from lbs, how
   the curator fills universe, position cap and regime blend) and whether retirement goals get a withdrawal rate.
3. Consumer app: ask the share of the yearly saving per goal and send `goals[].contribution_share` (LBS-29).
4. Owner: approve (or not) `intake-scales` and `roles`, still provisional and read ungated.
5. Storage and access rules for client data (README open points).
6. Deploy folder when signed off: `python dev/make_deploy.py`.
