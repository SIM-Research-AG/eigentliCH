# Session state, 29.09.2026 late afternoon (owner: Nicolas): the resume point after compaction

Read this first. The real-view spec is `Engines/review/REAL_VIEW_INTERFACES.md`. The design note is Notion
`3ea0ba72543f81fcb0a4c47178754f4b`. The use-case catalogue is
`eigentliCH_Engines/eigentlich/docs/USE_CASES.md` and Notion `3ea0ba72543f81c0a1d5d4a263d14ce7`.

## State at 29.09.2026, 16:00

Done: fmre `ipt@1.1.0` (FMRE-38..41), pcp PCP-23, report indexed-contribution fix, cockpit role pass-through
note, `desktop.cmd` also starts fmre (8006). All servers restarted. All 20 use cases refreshed, `check`
all_ok. Database backup `PostgreSQL/backups/simtech_all_2026-09-29_before-refresh.dump`. Pushed as
commit f47319c. Temporary cockpit on 8098 stopped.

Notion pass done (all 12 pages), docs aligned, pushed as aa8237e.

**lbsim build (Engine 14), started 29.09.2026 ~16:30.** Spec: `Engines/review/LBSIM_INTERFACES.md` (binding,
with the owner's answers in section 10). casadi 3.7.2 installed in `eigentliCH_Engines/.venv` (IPOPT solve
checked). Order: A -> B1 -> {B2, C, D} in parallel -> E (spec section 9).
- Done: agent A (lbs 1.4.0 live on 8013, 473 tests; lbsim schema and role provisioned; pushed 7a58780).
  A's choices: responsibility accepts tier key or de/en label; health_work_capacity with health_withheld is
  refused (the app's K3 filter must drop it with health).
- Done: B1 (lbsim core, 457 tests, golden layer A 48 cases exact, earning power 192 rows exact, samples in
  `engines/lbsim/golden/samples/`; pushed 40e05a4).
- Done: B2 (Monte Carlo, store, API, workers, test bench), D (report 1.4.0 charts + lbsim sections, REP-38 real
  charts; cockpit Outlook panel), B1 fix (calibration 1.2.0: corrected income paths), C (optimiser; retirement
  measure without pillar 2). Pushed to both remotes up to 60f25a1.
- Done: C calibration 1.3.0 (500 iterations, 10-year horizon, certified on the sample in 31 min) and lbsim env
  URLs; E app 1.4.0 (intake v4 saved live, outlook page, charts, auto-trigger, backfill). Pushed 080464e.
- Live: lbsim 8014 (`python -m lbsim serve`, 2 workers), app 8017 restarted (1.4.0), cockpit 8000 restarted,
  temporary cockpit on 8098 for the use-case builder (stop it when the refresh is done).
- Refresh ran (21:22-21:36); check failed on ids in report markup and "Ihr Ziel" rows: fixed in report 1.4.1
  (restarted). Four 0.0 chances were Monte Carlo defects: fixed as lbsim calibration 1.4.0 (P-21..P-24; Kurt 0.997,
  Esther 0.993, Reto 0.803, Regula 0.251, Michele 1.0, Peter 1.0; Corinne 0.0 is right). Pushed d53e704.
- Done: B1 calibration 1.5.0 (income at today's level until an education ends; no pensum above 1 on a
  full-pensum amount). lbsim restarted on 1.5.0. Builder fixed (outlook --refresh; a report is current only on
  lbsim's newest paths; non-CHF clients accepted without a simulation). `check` all_ok TRUE at 22:40. Pushed 4e85d11.
- Base chances now: Simon 0.68, Noemi 0.997, Michele 0.016, Reto 0.0, Corinne 0.0, Regula 0.13, Kurt 0.997,
  Esther 0.993, Peter 1.0, the rest 1.0.
- **Parked 01.10.2026 by the owner.** Power cut on 30.09; the machine restarted, nothing lost. Docker deployment
  rebuilt to the CTO's real requirement: TWO containers (`simtech` with all engines, workers, app and cockpit under
  supervisord on 127.0.0.1; `db` PostgreSQL 18 with the nightly backup), tested incl. the real-dump restore, pushed
  b0b388f to both remotes. CTO handover text given to the owner (01.10.2026).
- Open when resuming:
  1. Start the engines here (eigentliCH desktop icon starts lbs, report, chatbot, aggregation, fmre, pcp, lbsim,
     app; the cockpit via its own shortcut). Queued and cut-off lbsim plan runs requeue on their own.
  2. Three plans failed on 30.09 (Reto, Michele, Corinne: solver non-convergence, a time-out past 120 min, and a
     transient fmre 500 that was retried). Ask the owner whether to change 500 iterations / 10-year cap / 120 min.
  3. Run `build_use_cases.py check --plans`, then the live app test (`EIGENTLICH_LIVE=1 pytest tests/test_app_live.py`).
  4. Fill the "to fill" columns in `eigentlich/docs/USE_CASES.md`; stop any temporary cockpit on 8098.
  5. Engine fixes in `Engines/deploy/ENGINE_CHANGES.md` (lbsim schema deadlock with parallel workers: advisory
     lock; cockpit curator-DB env vars and launcher switch; fmre/app create their tables at start-up).
  6. Notion pages for lbsim (14), report 1.4.1, the app, cockpit and the Docker deployment are not updated yet.
  7. Owner's morning item: Esther's goal "Ab 2027 vom Vermögen leben" would fit better as a retirement goal.

## 03.10.2026: graphs and benches (owner: graphs everywhere, today and over time)

- Spec `Engines/review/VISUALS_INTERFACES.md`. Built and pushed (63be96d): lbsim 1.1.0 (capitals over time, bench with
  client picker and graphs; network scale per Regime, P-26), lbs bench (picker, balance sheet, capitals), report 1.5.0
  (Lebensbilanz and vier Kapitale sections, report bench with gallery), app 1.5.0 and cockpit (balance sheet and capitals).
- Restarted: app 1.5.0, cockpit, lbs, report 1.5.0. **lbsim still runs 1.0.0** on purpose (owner: let the plans finish).
- Background shell `bb6vrbc7l` waits until no plan is queued or running (up to 8 h). Then: restart lbsim (all lbsim
  serve/worker processes), `build_use_cases.py outlook --refresh`, `reports --refresh`, `check`, then `check --plans`
  overnight and the live app test; push both remotes.
- Owner to check once in a real browser: the report bench's report frame (empty in a headless screenshot only).
- Still open: the two failed plans (solver, timed_out) and whether to change 500 iterations / 10 years / 120 min;
  USE_CASES.md "to fill" columns; ENGINE_CHANGES.md fixes; Notion pages; Esther's goal.

## 03.10.2026 afternoon: open items being closed (owner: "take care of the open items")

- Done today: lbsim restarted on 1.1.0 / calibration 1.6.0 (1000 iterations, 3 h); Esther's goals (retirement from
  07.2027; "Freies Vermögen bis 2031 bei 200 000 halten"); display rounding everywhere (ROUNDING.md, app/report
  1.5.1, cockpit, all benches; billions and exponent form); pushed 7e592ec.
- Running: `reports --force` (all 20 reports again, rounded); three agents applying ENGINE_CHANGES.md (cockpit 1,2,4,7,10;
  eigentliCH 3,6,8,10; fmre/Macro/pcp 5,9,10). 18 optimiser plans calculating on 3 workers (started ~08:40).
- Then: restart what the agents name (lbsim only after the plans, or accept a restart), a Docker agent removes the
  workarounds in deploy/ and retests (two containers, real-dump restore), `check --plans`, the live app test,
  USE_CASES.md "to fill" columns, push both remotes.
- Notion pages (lbsim, report, app, cockpit, Docker): the Notion connection is not available in this session; open.

## Stopped 03.10.2026 (battery)
- Done and pushed (91d1859): reports --force (20 rounded reports), cockpit fixes C-38..C-42 (restarted 8000/8098),
  eigentliCH fixes (schema lock, quiet health log, app 1.5.2; lbs/report/chatbot/app restarted).
- Stopped mid-work: the fmre/Macro/pcp agent (ENGINE_CHANGES items 5, 9, 10). Its uncommitted edits in Instruments,
  Macro/engines and Optimizer/engines/pcp are on disk, unreviewed: check `git status`, rerun those suites, then
  commit or revert.
- Not started: the Docker agent removing the deploy/ workarounds and retesting; lbsim restart (after plans);
  `check --plans`, live app test, USE_CASES.md "to fill"; Notion (connector unavailable).
- Plans: 18 were calculating on 3 workers; on power loss they requeue when lbsim starts again.

## Stopped again 03.10.2026 ~16:00 (owner)
- Done and pushed (d2af040): all ENGINE_CHANGES items in the engines (cockpit 4d6350c, eigentliCH 91d1859,
  fmre/Macro/pcp 810fd9f), every engine restarted on them; deploy/ without workarounds, retested (empty start,
  real-dump restore, 20 parallel worker starts, quiet logs). macrofield "hang" was a slow suite (124 tests, 18.5 min)
  plus Git's timeout.exe not killing the Windows python child: use `-o faulthandler_timeout=...`, not `timeout`.
- Plans under calibration 1.6.0: 12 succeeded; 6 failed "solver" (Corinne, Esther, Franziska, Kurt, Michele, Peter),
  each after 3 seed attempts in 5-38 min. Suspected: retired households with nothing to steer (Esther, Kurt, Peter),
  unreachable goals reported as solver failure instead of goal_not_fundable per M79 (Corinne, Michele); Franziska
  unclear. An agent was investigating and was STOPPED by the owner; check `git status` in engines/lbsim for partial
  edits before restarting that work.
- App live test: 4 passed (03.10.2026).
- Still open: the 6 plans; USE_CASES.md "to fill" columns (after the plans); Notion (connector unavailable).
