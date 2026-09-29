# Session state, 29.09.2026 afternoon (owner: Nicolas): the resume point after compaction

Read this first. The real-view spec is `Engines/review/REAL_VIEW_INTERFACES.md`. The design note is Notion
`3ea0ba72543f81fcb0a4c47178754f4b`. The use-case catalogue is
`eigentliCH_Engines/eigentlich/docs/USE_CASES.md` and Notion `3ea0ba72543f81c0a1d5d4a263d14ce7`.

## Running at the time of compaction (agents, started from this session)

| Agent task | Folder | What it builds |
|---|---|---|
| fmre: bonds, cash β, role pass-through | `Engines/Instruments` | Bond price loss in log form, no cap; cash β = 0 with no price loss (new `ipt@1.1.0`); role profiles take a blended β of their blocks. Confirmed as mapped: infrastructure as real estate, credit duration 6, Private Debt short-dated |
| pcp: accept the hard-currency fallback | `Engines/Optimizer/engines/pcp` | Accept a set on the fallback only when `hard_currency_fallback.from` equals the mandate's currency; state it on the Allocation (PCP-23) |
| Background shell `bopc7gi99` | eigentlich | `build_use_cases.py reports --refresh --only simon,claudia,regula,kurt,esther`, then `check`. Its output lands in the task output file |

A temporary cockpit runs on port **8098** (pid 2844). `build_use_cases.py check` uses it. Stop it at the end.

## Next steps, in order, when the above is done

1. **Restart** 8006 fmre (the new β), 8007 pcp and 8013 lbs (calibration 1.5.0).
   - fmre: `python -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8006` in `Instruments`.
   - Others: `<family venv>\Scripts\python -X utf8 -m <module> serve` in the engine folder.
     `lbs` uses `eigentliCH_Engines\.venv`, pcp uses `Optimizer\.venv`, aggregation uses `Macro\.venv`.
   - Agents may not restart servers. The coordinator does it.
2. **Refresh the 20 use cases** (in `eigentliCH_Engines/eigentlich`, venv `..\.venv`):
   `dev/build_use_cases.py mandates --refresh` (all 20, since lbs 1.5.0 changes the CHF figures), then
   `reports --refresh`, then `check` until `all_ok: true`. `check` needs the cockpit on 8098. The scenario
   runs need `--refresh`, because β entered the scenario ReturnSet ids.
3. **Commit and push.** The repository is `Projects/` (allowlist `.gitignore`), remote
   https://github.com/SIM-Research/eigentliCH, branch `main`. Before pushing, run a secret scan: no
   `config.local.yaml`, `.env` or `config.toml` staged, and no spark7 token value in any staged file. Commit
   messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
4. **Notion documentation pass** (it is behind): fetch before editing, edit only the named parts, as is,
   British spelling, no em-dashes.
   - Build Instruction `3e90ba72543f819b9fa1ff13ecf5fb59` section 9.2 status, and section 5.
   - Engine pages with the real view, β, versions and test counts:
     - 04 aggregation `3e50ba72543f81e3815ce4aece6046ed`
     - 06 fmre `3e50ba72543f81f8ad09f996fd82db92`
     - 07 pcp `3e50ba72543f8156b3e7f074387d7cac`
     - 13 lbs `3e80ba72543f81cd8fc5c5a7279c1b0c`
     - 15 report `3e80ba72543f81279459c05a6644539a`
     - 16 chatbot `3e80ba72543f81ab9706e18e563646f8`
     - 03 macrofield (1.5.0) `3e50ba72543f81d38916efb0c7cc5241`
     - 12 cycle `3e80ba72543f81299187c34493263bba`
   - Guide `3e30ba72543f80549955d5029d2512cd` section 4 status cells.
   - Review dossier `3e90ba72543f8177a16ad5712c140bc4`:
     - R-001: Done (Income A built, FMRE-15ff).
     - R-002: Done (forward 12m plus smoothing as the default, FMRE-22).
     - R-003: Done (acceptance restated, per-type protection rule, FMRE-24).
     - Outcome texts are in the fmre DECISIONS.
   - The cockpit page (Engine 11) `3e50ba72543f8148a851e54a2b18750b`: the curator workflow, presets,
     the optimism level, the real switch, the β override.
5. Stop the temporary cockpit on 8098.

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
  - β pass-through under scenarios (`ipt@1.0.0` live; 1.1.0 being built).
  - `GET/PUT /v1/inflation-beta`, `GET /v1/inflation-beta/{id}/history`.
- **pcp 1.2.0:** currency, basis, a joint-feasibility check, the rescue path.
- **lbs 1.3.0:** calibration 1.4.0 live; 1.5.0 built, active after the restart. Real view, amount basis,
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
