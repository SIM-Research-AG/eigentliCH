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
- Running: agent A (lbs 1.4.0: earning-power answers, new facts, `GET /artefacts/{id}/request`; lbsim
  provisioning) and agent B1 (lbsim contracts, numpy model port, fast half, adapter, calibrations, golden layer
  A, sample artefacts in `engines/lbsim/golden/samples/`).
- Next: when both report, restart lbs 8013; start B2 (Monte Carlo, clients, store, service, API, workers), C
  (optimiser in `src/lbsim/optim`), D (report charts and lbsim sections; cockpit Aussichten panel and roster)
  in parallel; then E (app questions content v4, outlook page and charts, desktop.cmd 8014, use-case
  `earning` and `outlook`, then mandates/reports refresh and check; the 20 plans take about 6 hours).

Open: two hung pytest processes from the pcp agent (pids 4564 and 24748, started 15:25); the agent was
not allowed to stop them, so this is the owner's call. The owner is judging FMRE-38 (a duration-6 bond
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
