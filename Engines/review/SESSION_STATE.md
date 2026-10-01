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
- Paused 30.09.2026 05:15 (owner). Plans (latest per client, 18 CHF clients): 7 succeeded, 7 queued, 1 running,
  3 failed (Reto, Michele, Corinne: one solver non-convergence, one timed_out past 120 min, one fmre 500 which was
  transient; that one (Reto, 95c705f1...) was restarted with optimise "now" at 05:12). One of the two workers had
  died overnight; a second `python -m lbsim worker` was started at 05:09.
- Background shell `bncwglp8e` (`check --plans`, then the live app test) keeps waiting if the machine stays on.
- On resume: read its output; list the latest plan run per client (lbsim.run, kind plan); decide with the owner
  whether non-converging / timed-out plans need a setting change (500 iterations, 10-year cap, 120-min budget);
  stop the 8098 cockpit; fill USE_CASES.md "to fill" columns; push both remotes.
- For the owner in the morning: Esther's goal "Ab 2027 vom Vermögen leben" is an lbs `other` lump sum of
  CHF 200 000 dated 2031; it would read better as a retirement goal with a yearly need (use-case content,
  `dev/build_use_cases.py`). Miriam (EUR) and Lukas (USD) get no simulation in v1 (CHF only).
- Docker: `Engines/deploy/` built, tested (images, smoke test, real-dump restore). CTO takes over 30.09.2026 from
  https://github.com/SIM-Research-AG/eigentliCH. Dump for him: `PostgreSQL/backups/simtech_for_server_2026-09-29.dump`.
  Pending engine changes: `Engines/deploy/ENGINE_CHANGES.md` (cockpit items 2-5, 8; fmre/app init 6-7).

Hung pytest processes stopped and scratch schemas dropped (owner's go-ahead). The owner is judging FMRE-38 (a duration-6 bond
reads -97 % real in hyperinflation, not -94 %; -94 % is the price change alone).

Notion page ids:
- Build Instruction `3e90ba72543f819b9fa1ff13ecf5fb59`
- 03 macrofield `3e50ba72543f81d38916efb0c7cc5241`, 04 aggregation `3e50ba72543f81e3815ce4aece6046ed`
- 06 fmre `3e50ba72543f81f8ad09f996fd82db92`, 07 pcp `3e50ba72543f8156b3e7f074387d7cac`
- 11 cockpit `3e50ba72543f8148a851e54a2b18750b`, 12 cycle `3e80ba72543f81299187c34493263bba`
- 13 lbs `3e80ba72543f81cd8fc5c5a7279c1b0c`, 15 report `3e80ba72543f81279459c05a6644539a`
- 16 chatbot `3e80ba72543f81ab9706e18e563646f8`
- Guide `3e30ba72543f80549955d5029d2512cd`, review dossier `3e90ba72543f8177a16ad5712c140bc4`

## Live system (versions)

- **Macro:**
  - macrofield 1.5.0 (projection to 2080).
  - cycle: contract cycle-state@1.2.0.
  - aggregation: Default Regime `RGM-e2658e8e9bbbc81e`, optimism default. Scenario Regimes carry
    `inflation_path` and `inflation_final_12m` (computed at read time, AGG-24):
    - depression `RGM-1af6968e287768c9`
    - hyperinflation `RGM-59eebfaf7744d8ec` (63.6 %)
    - stagflation `RGM-6bb531998bfefc4d` (10 %)
    - deferral `RGM-c0ed086f1916984e` (2.6 %)
- **fmre:**
  - The default is forward 12m plus smoothing. Default stamped `RS-59598b143ab78c56`, CHF `RS-c472e411e39645f5`.
  - `/v1/inflation`, `basis=real`.
  - β pass-through under scenarios (`ipt@1.1.0` live, `IPT-585c7da4656ead2b`; 1.0.0 kept in the store).
  - `GET/PUT /v1/inflation-beta`, `GET /v1/inflation-beta/{id}/history`.
- **pcp 1.2.0:** currency, basis, a joint-feasibility check, the rescue path, the hard-currency fallback (PCP-23).
- **lbs 1.3.0:** calibration 1.5.0 live. Real view, amount basis,
  indexed contribution, the plausibility judgement.
- **report 1.3.0:** basis, revisions, no ids, house role names.
- **chatbot 1.2.0:** MiniMind, wider domain.
- **App 1.3.0:**
  - two-adult households, contribution shares, the nominal/real switch;
  - reports on the base run of the current parameter set;
  - readable decision history;
  - 20 use-case clients.
  - `desktop.cmd` (the target of `eigentliCH.lnk`) starts lbs, report, chatbot, aggregation, pcp and the app.
- **Cockpit:**
  - Curator pages; mandate presets v2; 13 target-curve presets;
  - Regime by optimism level (C-30); real switch (C-31); β override panel (C-32);
  - tests 75.
  - The owner must reopen the desktop app on 8000 to see it.

## Owner decisions of 29.09.2026 (all settled)

- **Real view:**
  - inflation per state over the following 12 months; scenarios use their own path;
  - index CH CPI / HICP / CPI-U;
  - ceiling -20 % to +100 %, with a hard-currency view above it;
  - **default nominal everywhere**;
  - goals in today's francs by default; contributions fixed by default;
  - Germany 1922-23 as a stress case only.
- **β pass-through:**
  - gold, commodities and inflation-linked 1.0; real estate and infrastructure 0.8; equities 0.6;
    hedge funds, digital assets and volatility 0.5; **cash 0**; nominal bonds 0 plus a log-form duration loss;
  - role profiles take a blended β;
  - the CIO can override β per instrument.
- **lbs:** CHF inflation 1.0 %; the plausibility table 2 / 3.5 / 5 % real.
- **pcp:** accept the hard-currency fallback, clearly marked.
- **Earlier:**
  - Income A; Global Bonds in Income; Short MSCI US and CS Long Vola deactivated; volatility on VXTH;
  - erasure deletes decisions; 20 use cases;
  - Engines 08, 09 and 10 dropped;
  - MiniMind is the name; the chatbot answers beyond the notes;
  - no raw ids or keys shown; one language per page;
  - knowledge notes approved (v2).

## With the owner

- Reopen the cockpit desktop app.
- Run the SQL Metadata "Merge with CSV" with `Engines/Instruments/docs/sql_metadata.csv`.
- Tell Tino (Engines 08, 09 and 10 dropped).
- A first click-through of the app and the cockpit.
