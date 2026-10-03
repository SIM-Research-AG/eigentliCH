# eigentlich store: handover (29.09.2026)

## State

* **Built:** the package `eigentlich` (settings, store and repository, `schema.sql`, seed, intake
  extractor, migration, CLI), 275 tests, `dev/verify_regressions.py` (29 fixes, each shown to be guarded),
  `dev/schema_catalogue.py` (writes SCHEMA.md from `dev/SCHEMA.head.md` and the live schema).
* **Real schema `eigentlich`:** initialised, seeded and migrated.
  * 30 tables, 8 views, all commented; no `real` column; every function pins its search_path.
  * Content: 54 keys at version 1 (2 questionnaires, 3 scoring maps, 14 reference, 35 knowledge notes).
  * Migration of `Prototype/backend/eigentlich.db` (alembic head `b81f4c2e9a37`, sha256 `a10b6afa...`),
    one transaction, every migrated table reconciled: 6 curators, 83 clients, 60 consents, 7 curator
    sessions, 7 events, 518 decisions, 34 households, 38 household members, 297 positions, 128 goals,
    319 client facts, 306 + 198 + 34 + 39 + 323 decision links, 5 goal fundings, 0 goal owners, 547
    answers, 60 submissions. Skipped tables are listed with counts and reasons in the reconciliation
    (`dev/reports/migration-report-eigentlich.json`, and `migration_run.reconciliation` in the store).
  * The source file is unchanged (hash checked before and after).
* **Grants:** the curator's default privileges from provisioning reached every table `init-db` created
  (tested: SELECT, INSERT, UPDATE yes; DELETE, TRUNCATE no).

## The client app (28.09.2026)

* **Built:** the consumer app in this package (`api.py`, `service.py`, `clients.py`, `contracts.py`,
  `inputs.py`, `grounding.py`, `questionnaires.py`, `appsettings.py`), the browser app in `client/`,
  `start.cmd` (port 8017), `python -m eigentlich serve`. Decisions EIG-29 to EIG-43. README "The client app"
  lists the routes and screens.
* **Tests:** 300 passed, 3 skipped (the opt-in live tests), in about 35 s: the 275 store tests unchanged
  and green, plus 25 app tests (API on a seeded throwaway schema with stand-in engines; the lbs request
  builder; a concurrent burst against the app and three stand-in engines on real sockets).
  `dev/verify_regressions.py`: 29 of 29 still guarded.
* **Schema:** unchanged (EIG-43). One repository fix in `store.py` (EIG-37: message bodies were stored with
  JSON quotes; no real row affected).
* **Engines:** none was running on 28.09.2026, so the live tests were not run. Every mirror in
  `contracts.py` was checked against the engines' own `contracts.py` of that day, and all 83 migrated
  clients' lbs requests were built by lbs's own `build_sheet` without error.
* **Server:** left stopped.

## The owner's decisions of 29.09.2026 (EIG-44 to EIG-52)

* **Content aligned to the scoring maps** (EIG-44): `questionnaire/intake` v2 (`intake@1.2`, 114 questions) and
  `questionnaire/onboarding` v2 (`onb2@0.2.0`, 22 questions), saved by the curator `Nicolas` with the note
  "aligned to scoring maps, owner 29.09.2026". `scoring_bind_check`: 169 of 169 ok (was 150). Maps unchanged.
  New content format: `multi_choice`, and `"offered": false` on an option (SCHEMA.md section 6).
* **Yearly contribution** (EIG-45): onboarding `annual_contribution` -> `mandate.annual_contribution`.
* **Encoding** (EIG-46): "C├⌐line B." -> "Céline B." (client, direct update; her household member label,
  under a decision "encoding correction, owner 29.09.2026") and seven migrated decision texts (correcting
  decisions). Nothing else found. `python -m eigentlich fix-encoding` lists, `--apply` corrects.
* **lbs runs by itself** (EIG-47): debounced 5 s after every change in the app, one run per client at a time,
  `engine_run.requested_by_kind = 'system'`; the home page shows the sheet's age. `POST .../balance-sheet`
  takes `{"curator_id": ...}` for the cockpit's button (403 unless in service). **Backfill run on the real
  store** with lbs@1.1.0 up: 74 clients without a sheet, 74 sheets; every client now has one.
* **MiniMind** (EIG-48), **gaps in plain words** (EIG-49, all 45 keys lbs's engine can emit, German and
  English; the whole UI in one language), **`thread_message.basis`** (EIG-50, the one additive schema change,
  applied to the real schema by `init-db`), **wider grounding** plus the sheet's facts for questions about the
  asker (EIG-51), four decisions confirmed as built (EIG-52).
* **Tests:** 347 passed, 3 skipped (live, opt-in); with `EIGENTLICH_LIVE=1` against the running lbs, chatbot and report the 3 live tests passed too. `dev/verify_regressions.py` now also reverts Python-level
  fixes: 40 guards (30 database, 10 code), each shown to fail reverted and pass restored.
* **Mirrors re-read on 29.09.2026:** lbs `contracts.py` (calibration 1.1.0): `lbs-request@1.0.0` unchanged
  field for field; all 83 clients' requests validate against lbs's own model. chatbot: `basis` and
  `model_display_name` added to the `chat-answer` mirror.

### Open points from this day

17. **The app on 8017 was running version 1.0.0** (started outside this session) when the work ended; it
    must be restarted to serve 1.1.0 (automatic lbs runs, the new home page, MiniMind, basis). Not stopped
    here, since this session did not start it.
18. **The auto-run state is in memory** (as the jobs, EIG-34): a run scheduled but not yet started is lost on
    restart; the next home visit schedules it again.
19. **Resolved (EIG-58).** ~~`education_hours` and `hours_learning` both sit in intake section 16~~: the intake
    (version 3) keeps the band and no longer asks the number.
20. **Server refusals are recognised by pattern** in `client/app/api.js`; a new refusal text reads as the
    plain sentence for its status until a pattern is added.
21. **No note covers growing one's income**; the growth question now gets the nearest notes and a general
    assessment. A knowledge note on human capital would ground it.
22. **Parallel test runs** by other sessions can trip the throwaway-schema teardown check ("dropped
    something else") in `conftest.py`; a rerun passes.

## The fix round after the use cases (29.09.2026, EIG-53 to EIG-59)

* **Built:** the partner stated to lbs (intake v3 section 21, `position.owner`, the mapping in `inputs.py`,
  EIG-53); a re-answer restates its fact and `PUT /api/clients/{c}/facts/{key}` restates one directly (EIG-54);
  grounding without numbers and inflected stop words (EIG-55); the house's role names from `reference/roles` on
  every page, in the page's language (EIG-56); a report revision sent with `revision_of` and the curator's
  `revision_note` (report 1.2.0, REP-25; EIG-57); `hours_learning` dropped from the intake (EIG-58); each goal's
  share of the yearly saving, stored, checked (at most 100 % together) and sent (lbs@1.2.0, EIG-59). App
  version 1.2.0.
* **Schema, additive:** `position.owner` and `goal.contribution_share` with their CHECKs, applied to the real
  schema by `init-db`; SCHEMA.md regenerated (section 4.7, the curator SQL "State a fact anew").
* **Content:** `questionnaire/intake` version 3 (`intake@1.3`, 127 questions) saved on the real store by the
  owner's curator record (`revise-content`); `scoring_bind_check` 169 of 169 ok.
* **Use cases:** step `partners` of `dev/build_use_cases.py` run on the real store through a temporary app on
  port 8027 (new code, same store and engines; stopped afterwards; 8017 was not touched): the 13 partners' answers
  and their income and pension positions, Peter's and Margrit's pensions split, the shares for all 20. Every one
  of the 20 sheets now names one gap only (earning power, lbsim's). `enrich` run again afterwards wrote nothing.
  docs/USE_CASES.md carries the new lbs figures; its mandate lines are from the earlier sheets.
* **Tests:** 362 passed, 3 skipped (live, opt-in); with `EIGENTLICH_LIVE=1` the 3 live tests passed against lbs
  1.2.0, chatbot 1.1.0 and report 1.1.0. `dev/verify_regressions.py` has 10 more code guards (50 in all); the
  10 new ones were each shown to fail reverted and pass restored (`verify_regressions.py <name>` runs a subset).
* **Mirrors re-read:** lbs `contracts.py` (lbs@1.2.0: `goals[].contribution_share`, and its owner and share
  checks mirrored); report `contracts.py` (1.2.0: `revision_of`, `revision_note`, sent only on a revision).

### To restart (the owner's session)

* **The app on 8017** runs 1.1.0 and must be restarted to serve 1.2.0. Until then a German home page shows lbs's
  English role names, the plan has no partner, owner, share or fact fields, and a home visit there can schedule
  an lbs run with the old request (no partner, no shares), which would then be the latest sheet: after the
  restart, `build_use_cases.py partners` (it presses the curator's lbs button for each client) brings every
  sheet back.
* **The report engine on 8015** runs 1.1.0; its code is 1.2.0 (REP-25). A revision from the app needs 1.2.0
  running (1.1.0 refuses the two fields; every other request works on both).

### Open points from the fix round

23. **The parameter sets rest on the earlier sheets.** With the shares stated, the required returns rose (up to
    16 % for Elio's reserve, 12.5 % for Michele's); `build_use_cases.py mandates --refresh` (needs the cockpit on
    8098) derives and finalises them again.
24. **The partner's answers are the client's.** There is no consent or record of the partner's own agreement;
    the health question says to answer only with it. A couple with two records states each other twice.
25. **The partner is the first other adult** by label order; a household with an adult child and a partner
    should list the partner first alphabetically or the child as a dependant. A partner column on the member
    row would settle it (not built: the questionnaire carries the partner, the member row stays as it is).
26. **The intake's own `health` question declares no class** (the onboarding's fills K3; the intake's answer is
    stored K2). The partner's health question declares K3. A curator may want the same on the client's.
27. **The shares' sum is checked by the app, not the database** (the cockpit could write more); `inputs.py` then
    sends none and names it in `dropped`.

## The nominal and real view (29.09.2026, EIG-60 to EIG-64)

* **Built** to `review/REAL_VIEW_INTERFACES.md`: the two questions (EIG-60 per goal, EIG-61 for the yearly
  contribution) as the onboarding's version 3, stored as `goal.amount_basis` and the answer
  `contribution_indexed`, sent to lbs as `goals[].amount_basis` and `mandate.contribution_indexed` only when stated;
  the nominal / real switch on home, plan and reports (EIG-62, `client/app/basis.js`), lbs's real figures shown in
  real and a report asked with `basis=real`; **bug fixes**: the report's allocation is the current parameter set's
  run on its base Regime, a scenario only when asked (EIG-63, asks aggregation `GET /scenarios`); the decision list
  in plain German with the house's role names and 61’000 CHF (EIG-64, `decisions.py`). App version 1.3.0.
* **Schema, additive:** `goal.amount_basis`, `report_request.basis`, `report_request.scenario` with their CHECKs,
  and the two columns appended to the view `report_request_state`; applied to the real schema by `init-db`;
  SCHEMA.md regenerated (section 4.8).
* **Content:** `questionnaire/onboarding` version 3 (`onb2@0.3.0`) saved on the real store by the owner's curator
  record (`revise-content`); `scoring_bind_check` 169 of 169 ok.
* **Use cases:** step `basis` of `dev/build_use_cases.py` run on the real store through a temporary app on port 8027
  (new code, same store and engines; stopped afterwards; 8017 was not touched): every goal with an amount states its
  basis (five in future francs: Claudia's mortgage, Michele's amortisation, Isabelle's practice share, Regula's
  advance on inheritance, Elio's buy-in), the indexed question answered for all 20, then the curator's lbs button.
  All 20 sheets carry lbs's real view (lbs@1.3.0, calibration 1.4.0). A second run wrote nothing.
* **Tests:** 383 passed, 3 skipped (live, opt-in); with `EIGENTLICH_LIVE=1` the 3 live tests passed against lbs
  1.3.0, chatbot 1.2.0 and report 1.3.0; report 1.3.0 took the app's `basis: real` request. `tests/test_app_realview.py`
  (21 tests); `dev/verify_regressions.py` has 11 more code guards (61 in all), each shown to fail reverted and pass
  restored. The browser pages were checked by headless screenshots only.
* **Mirrors re-read:** lbs `contracts.py` (lbs@1.3.0, LBS-31: `goals[].amount_basis`, `mandate.contribution_indexed`,
  the sheet's `real_view` and the proposal's `views`); report `contracts.py` (1.3.0, REP-27: `basis`, sent only when
  real); aggregation `ScenarioListed`.

### To restart (the owner's session)

* **The app on 8017** runs 1.2.0 and must be restarted to serve 1.3.0 (the switch, the questions, the report fix,
  the plain decision list). Until then a German plan page still shows the raw decision texts, a report can still take
  a scenario's allocation, and a home visit there can make an lbs run without the two answers (lbs then reads today's
  francs and a fixed contribution, the defaults, so only the five future-francs goals read differently); after the
  restart, `build_use_cases.py basis` (it presses the curator's lbs button) brings every sheet back.
* **lbs (8013) and report (8015)** already run 1.3.0; nothing to restart there.
* **aggregation (8004)** must be up for a report with an allocation (EIG-63); `desktop.cmd` does not start it.

### Open points from this round

28. **A report with an allocation needs aggregation.** Down, the report waits (open, try again). If that is too strict
    for the desktop setup, `desktop.cmd` could start aggregation, or the cockpit could record the Regime's kind on the
    `engine_run` so the app needs no call.
29. **No real allocation exists yet**: every parameter set is nominal, so a real report has no allocation (a mix is
    refused). The cockpit's real mandate (pcp PCP-22) fills it.
30. **The switch shows lbs's figures only**; the plan's goal list shows lbs's figure from the latest sheet, which may be
    older than the goal's last change (the page says "Laut Bilanz").
31. **The scenario of a report** is asked through the API only (`scenario`); the client's page offers none.

## lbsim in the app (29.09.2026, EIG-65 to EIG-69)

* **Built** to `review/LBSIM_INTERFACES.md` section 7 and the app side of section 5 (agent E): the intake's version 4
  with lbsim's earning-power questions for the principal and the partner (`alignment.revise_earning`, run by
  `revise-content`); the mapping to lbs@1.4.0's `persons[].earning_power` and the six new `facts`, only when stated,
  with what is left out named (`inputs.py`); `clients.LbsimClient` and its mirrors (`contracts.py`); the settings
  `lbsim_url`, `timeouts.lbsim_s`, `lbsim_auto` (`EIGENTLICH_LBSIM_URL`); lbsim after a new sheet only; the routes
  `POST|GET /api/clients/{c}/outlook`; the plan's own `engine_run` and its refresh; `python -m eigentlich
  lbsim-backfill`; the "Aussichten" page (`client/surfaces/outlook.js`), the home card and `client/app/charts.js`
  (SVG through the namespace-aware `h()`); the report's lbsim sources and the update with the plan; `desktop.cmd`
  starts lbsim on 8014. App version 1.4.0.
* **Schema:** unchanged (no table, column or constraint; `engine_run.engine` already takes `lbsim`). SCHEMA.md and
  `dev/SCHEMA.head.md` describe the intake's version 4 and the wider `asked_when`.
* **Content on the real store:** not yet saved. `revise-content --curator Nicolas` saves the intake's version 4
  (the coordinator's first step below).
* **Tests:** 408 passed, 4 skipped (the opt-in live tests, now four with `test_live_lbsim`), in about 75 s.
  `tests/test_app_lbsim.py` (25) runs against a stand-in lbsim serving B1's frozen samples (copied to
  `tests/fixtures/lbsim/`). The live tests were not run here (they write to the engines' own stores); the
  coordinator runs them once lbsim is up. `dev/verify_regressions.py` has no new guard for this round.
* **Checked read-only against the running engines:** the 20 use cases' requests with the answers of step `earning`
  validate against lbs's own model and through lbs 1.4.0's `POST /validate` (stores nothing): no refusal, no
  unknown tier. The outlook page was run once in a stand-in DOM on the samples (German and English, plan ready and
  calculating; four SVGs, drawn again after the switch).
* **Docker:** the app reads `EIGENTLICH_LBSIM_URL`; `Engines/deploy/compose.yaml` should pass
  `EIGENTLICH_LBSIM_URL: http://lbsim:8014` to the `eigentlich` service (not edited here, that folder is not this
  agent's; `ENGINE_CHANGES.md`'s watch point for the app is then settled).

### The coordinator's live refresh, in order (lbsim live on 8014 with its workers)

```
cd eigentliCH_Engines\eigentlich
..\.venv\Scripts\python -m eigentlich revise-content --curator ac586536e6be42c68446c8f8f80e4242
:: restart the app on 8017 (it must serve 1.4.0), then:
..\.venv\Scripts\python -X utf8 dev\build_use_cases.py earning
..\.venv\Scripts\python -X utf8 dev\build_use_cases.py mandates --refresh     :: needs the cockpit on 8098 (USE_CASES_COCKPIT)
..\.venv\Scripts\python -X utf8 dev\build_use_cases.py outlook
..\.venv\Scripts\python -X utf8 dev\build_use_cases.py reports --refresh
..\.venv\Scripts\python -X utf8 dev\build_use_cases.py check
..\.venv\Scripts\python -X utf8 dev\build_use_cases.py check --plans          :: waits for the plans (hours)
set EIGENTLICH_LIVE=1 && ..\.venv\Scripts\python -m pytest -q tests\test_app_live.py
```

`python -m eigentlich lbsim-backfill` covers any client the steps above left without an outlook (it refuses to start
when lbsim does not answer). Once `check --plans` is through, `check` again confirms that the updates carrying the
plans were made (the app asks each when it first sees the plan there), and docs/USE_CASES.md's last three lbsim
columns are filled from `dev/reports/use-cases-outlook.json` and `use-cases-check.json`.

### Open points from this round

32. **The priority of a queued plan is not raised.** "Planrechnung neu starten" asks lbsim's `POST /optimise` as the
    curator; a plan already queued for the same key as a system run is answered as it is (lbsim's `_queue_plan`), so
    it keeps its place in the queue. A finished plan is answered from lbsim's cache. A real restart (a new seed, or
    raising the queued run's priority) is lbsim's to add.
33. **Nothing polls lbsim in the background.** A plan that finishes is recorded (and its report update asked) when the
    app next asks lbsim: the outlook page (which asks again every minute while it is open and the plan runs), the
    home page, a report, the cockpit's refresh. A client nobody looks at keeps a `running` row until then.
34. **The automatic report update is asked in the name of whoever asked the report it completes** (the client, or the
    curator), with a note saying so: `report_request` takes no `system` requester. `lbsim_auto.report_update: false`
    switches it off.
35. **The management tiers are mirrored** (`inputs.RESPONSIBILITY_TIERS`, from lbs's calibration 1.5.0): a tier added
    in a later lbs calibration is left out and named in `dropped` until the list follows.
36. **`own_use_share` and `mortgage_fixed_until` are read from the intake's property entries** (the self-occupied share
    of the stated values; the earliest fixed-rate end of a mortgaged property, as 31 December of that year); the plan
    has no fields of its own for them.
37. **The intake's new questions are drafted in English** (`en_draft`), as the partner section's; the intake is
    otherwise German only (open point 10).
38. **lbsim's reasons for "no allocation"** are the app's: without a parameter set, a run, a base run, or in another
    currency than CHF, the page says so itself and lbsim is sent no Allocation (it then waits for one).

## Rounding for display (03.10.2026, EIG-73)

* **Built** to the owner's rule (`review/ROUNDING.md`): `client/app/format.js`, the client's one number formatter
  (`amount`, `money`, `stated`, `rate`, `chance`, `share`, `level`, `ratio`, `count`, `year`), used by `home.js`,
  `outlook.js`, `plan.js` and `charts.js`; its Python twin `src/eigentlich/rounding.py`, used by `outlook.figure_text`
  (a finding's figures in its sentences). `dom.amount` and `basis.pct` removed. New words: `format.rounded` ("Beträge
  gerundet." / "Amounts rounded."), `outlook.in_share_of_paths` (replaces `outlook.in_n_of_100`); `outlook.of_100`
  removed. App version 1.5.1. No schema change, no contract change.
* **Tests:** 569 passed, 4 skipped (the opt-in live tests). `tests/test_app_rounding.py`: every row of the rule in both languages for the client (in Node) and the
  twin, with the edges (negatives, exactly 1 000, 100 000 and 1 000 000, 0, None, a chance below 1 % and above 99 %);
  no ad-hoc number formatting left in the client; the home page's figures, the balance sheet, the capitals, the
  weights, the fan and the outlook's sentences drawn in Node from the engines' unrounded floats, with a scan that no
  raw float and no figure with more digits than allowed reaches the page; a finding's sentence rounded on the server.
  `tests/test_app_pictures.py` scans its drawn pages the same way.
* **The running app on 8017 needs a restart** to serve 1.5.1 (the client files are read at start).

## The balance sheet and the four capitals as graphs (03.10.2026, EIG-70 to EIG-72)

* **Built** to `review/VISUALS_INTERFACES.md` (agent H): `src/eigentlich/pictures.py` (pure: the balance picture,
  today's capitals, lbsim's capitals over time, the K3 rule); `picture` and `capitals` on
  `GET /api/clients/{c}/balance-sheet` and the home payload; `capitals` on each Regime of the outlook's paths; the
  mirror `contracts.LbsimCapitals` (optional); three charts in `client/app/charts.js` (`balanceChart`,
  `capitalsChart`, `capitalPathChart`, SVG through `h()`); "Ihre Lebensbilanz" and "Ihre vier Kapitale" on the home
  page (`home.pictureBlock`, `home.capitalsBlock`), "Wissen, Netzwerk und Gesundheit über die Zeit" on the outlook
  (`outlook.capitalsOverTime`); the words in both languages; the chart styles in `client/style/app.css`. App version
  1.5.0. No schema change.
* **Where each graph sits:** the balance sheet and today's four capitals on the home page under "Ihr Raster", after the
  totals and before the goals' figures (EIG-70 says why the home page); the capitals over time on the outlook page
  after the wealth fan, for the Regime chosen there.
* **Tests:** 424 passed, 4 skipped (the opt-in live tests). `tests/test_app_pictures.py` (16): the pure pieces, the
  mirror (against a capitals block made from the spec, `tests/fixtures/lbsim/capitals.sample.json`, and against
  lbsim's own 1.1.0 sample when it is beside the package), the two routes with stand-in engines, and the three charts
  drawn in Node against a small DOM stand-in (skipped without Node). The stand-ins in `tests/appkit.py` gained
  `lbs.health_withheld`, `lbsim.capitals` and lbs's `totals.by_vessel`. `test_app_lbsim.py::
  test_lbsim_runs_only_on_a_new_sheet_id` failed once under the full suite's load and passed on every rerun (its
  background run timing; not touched by this round).
* **To see it:** restart the app on 8017 (it serves 1.4.0 until then). lbsim sends `capitals` from its 1.1.0 on
  (agent F; restart lbsim on 8014), and only on artefacts made after it: compute the outlook again (or
  `lbsim-backfill` after a new sheet) to see the capitals over time; older artefacts show the "not yet" note.

### Open points from this round

39. **Wealth today is the household's.** lbs states wealth for the household, not per adult; the per-adult view would
    need lbs to sum the positions by owner (`Position.owner` is in the request already).
40. **The app never sends `health_withheld: true` yet**: no question or setting withholds health; the K3 rule is in
    place for when one does (and for lbs stating `H` withheld after a K3 erasure).
41. **The level words are by thirds of the scale** (gering, mittel, hoch), a reading aid of the app's; lbs's record
    has words for the network's knee only. A published reading per capital would replace them.

## For the next agents

* **Cockpit:** link to a client's view with `http://127.0.0.1:8017/#/client/<id>/home`; for a report
  revision call `POST /api/clients/<id>/reports/<request>/produce?revision=true&wait=true` with
  `{"revision_note": "<the curator's remark>"}` (and `"revision_of": "<report id>"` for another than the
  latest), then write the `revision_sent` event naming the new report (EIG-41, EIG-57).
* **Backend (consumer web app):** built (above); it uses `eigentlich.store` (README "The repository"). The client picker is
  `store.list_clients` (view `client_overview`). Plan changes only through `store.plan_change`. Show a
  knowledge note only when `front_matter.approved` is true. Approval waits only where the client asked
  (`request_approval`).
* **Cockpit (curator pages):** SCHEMA.md sections 1, 3, 4 and 7. Connect as `curator`, qualify names or
  `SET search_path TO eigentlich`. Name the acting curator in every write; a revoked curator is refused.
  Plan changes are one transaction, decision first.

## Open points

1. **Resolved 29.09.2026 (EIG-44).** ~~Scoring maps and questionnaires disagree in 19 binds~~ (seed report, view `scoring_bind_check`),
   content for the owner or a curator to resolve, not code:
   * `scoring/intake-scales` `confidence.options`: `80 %`, `90 % ... es muss halten`, `95 % ... kein
     Spielraum` are not options of intake `goal_confidence` (which offers `fest`, `70 % ... ich kann
     nachjustieren`, `eine Idee`).
   * `learning_commitment.hours` (5 bands) reads `education_hours`, which neither questionnaire asks.
   * `risk-profile` `sustainability.exclusions.offered` (7 items): intake `esg_exclusions` is free text.
   * `human-capital` `health.levels` `1` (the intake offers `1 ... sehr gut`), and `rest_hours_bands`
     `kaum welche`, `5–10`, `mehr als 30` (the intake offers `unter 10`, `10–20`, `20–30`, `über 30`).
2. **Erasure deletes the client's decisions**, where the prototype (A61) redacted them and kept the
   shells. **Confirmed by the owner on 28.09.2026: deletion stays** (no redaction path).
3. **Schema changes after today** need explicit `ALTER` statements added to `schema.sql`: `CREATE TABLE IF
   NOT EXISTS` does not alter an existing table or constraint (functions, triggers and views are replaced
   on every `init-db`).
4. **Submissions are stored whole but not decomposed into answers.** The 60 migrated files are
   `onb@0.1.x` (onboarding chat), not `intake@1.1`; mapping them onto `questionnaire/intake` or
   `questionnaire/onboarding` answers is not done.
5. **The acting curator is chosen, not proven.** There is no sign-in (owner decision), so the database can
   check that a named curator exists and is in service, not that the person at the cockpit is that curator.
6. **Which content a client may edit** is not restricted by the database: the owner decided client and
   curator both edit shared content; the app decides which kinds it offers the client.
7. **A revised report** must be a new `report` row for the same request, produced by calling the report
   engine; the cockpit either asks the backend or inserts the row itself after the call (it may insert).
8. **Migrated test clients** ("Vorschau", "Onboarding Test", ...) are in the picker; archive them
   (`archived_at`) if the owner wants them hidden.
9. **Consent purposes** are checked for shape only; the prototype's registry is not replicated.
10. **English**: the onboarding carries draft English; the intake is German only.
11. **App: run the live tests** once lbs, chatbot and report are up (`EIGENTLICH_LIVE=1`); the chatbot and
    report contracts were mirrored while those engines were being finished (EIG-31).
12. **Resolved 29.09.2026 (EIG-45).** ~~App: the yearly contribution~~ toward the mandate goal is asked by no questionnaire, so lbs never
    computes a required return or a target curve from the app's requests (EIG-32). A question for the owner
    or a curator to add to the content.
13. **App: goal templates** are in code until a `reference/goal-templates` record exists (EIG-35).
14. **App: a household change closes a household shared with another client** for both (EIG-39); the
    partner's plan then has no current household until someone restates it.
15. **App: job state is in memory** (EIG-34): after a restart a failed draft or report shows as open,
    without the reason; retry works.
16. **App: an interactive browser check** was done by screenshots only (headless Chrome, every screen);
    nobody has clicked through it yet.


## Parked 28.09.2026 (owner's session)

- The app runs end to end: `EIGENTLICH_LIVE=1` live tests passed (3 of 3) against the real lbs, chatbot and
  report on spark7.
- `eigentliCH.lnk` on the desktop now starts `desktop.cmd` in this folder: it starts lbs (8013), report (8015),
  chatbot (8016) and the app (8017) if they do not answer, each in a minimised window, and opens the browser.
  The shortcut's previous target was `Projects/eigentliCH/Prototype/desktop/eigentlich.cmd`.
- The cockpit roster lists the app as `kind: app`, built, autostart.
- Next: a first click-through by a person; the open points above.
