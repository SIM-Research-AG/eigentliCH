# Engine 11: Cockpit (`cockpit`)

> **Notice.** Model-derived research output. Not investment advice.

The one front end for the whole system: the **CIO workspace** (the production views the CIO
uses to set the optimiser's boundary conditions and to select instruments), the **curator
workflow** (clients, threads, approvals, each client's pcp mandate, questionnaires), the
**engine status** view, and **every engine's test bench**, behind one origin. It is not a model
engine and contains no maths: every figure it shows comes from an engine endpoint. No engine
depends on it. Specification: the Notion page "Engine 11: Cockpit"; decisions: `DECISIONS.md`.

| | |
|---|---|
| Module | `cockpit` |
| Default port | 8000 (`config.yaml`, or `COCKPIT_PORT`) |
| Status | Built 0.1.0: CIO views on honi and fmre (linked by country), curator workflow on schema `eigentlich` (C-16), status graph, benches, Excel exports, desktop app |
| Consumes | All engines, over their published HTTP endpoints only; schema `eigentlich` directly, as role `curator` (the stated exception, C-16) |
| Produces | Gateway and UI; the CIO's decision log (C-06); the curator's writes to `eigentlich` (answers, approval events, parameter sets, engine runs, content versions). No model artefact |
| Deployment | CIO pages only, in `cio` mode: `python dev/make_deploy.py` (C-03) |

## Run it

Once, into the shared Macro virtual environment:

```bash
..\Macro\.venv\Scripts\pip install -e .[dev]
python -m cockpit shortcut          # "sim-tech Cockpit" icon on the desktop (--start-menu for Start)
```

Then either:

- **Desktop app**: the desktop icon, or `sim-tech Cockpit.cmd`, or `python -m cockpit desktop`.
  Starts every engine that has a start command (datafeed, honi, macrofield, aggregation, mrs,
  the Fund Map engine, pcp, cycle, lbs, report, chatbot) and the consumer app if it is not
  running (`autostart` in `config.yaml`; lbs, report, chatbot and the app with the
  `eigentliCH_Engines/.venv` interpreter, C-17), opens the cockpit in its own window (Edge or
  Chrome in app mode), and stops what it started when the window closes. Log:
  `data/logs/cockpit-desktop.log`.
- **Server only**: `start.cmd` or `python -m cockpit serve`, then open <http://127.0.0.1:8000/>.
  Engines are started with their own `start.cmd`, or with Start on the System page.

PostgreSQL has to be up for the engines and the curator pages (`docker compose up -d` in
`Projects\PostgreSQL`). The curator pages need the `curator` role's password in
`config.local.yaml` (`curator_db: {password: ...}`, git-ignored) or `COCKPIT_CURATOR_DB_PASSWORD`.

```bash
python -m pytest        # 75 tests: 56 on fake engines, no database; 19 curator tests on a
                        # throwaway schema t_<hex> (skipped, with the reason, without PostgreSQL)
```

## What is in it

| Group | Page | Rests on | State |
|---|---|---|---|
| CIO | Overview | all | What is ready, latest HoNI ranking, engines up, last decisions |
| CIO | Boundary conditions | honi, fmre | Peer set ranked by HoNI with its 10-year change and level z, sectors, capital saturation, instruments exposed, coverage notes; per-country weight bounds saved to the decision log; saturation map; national heat map |
| CIO | Country dossier | honi, fmre | National and sector paths, capital saturation, trend and level of every series over 5, 10 or 15 years (honi `/trends`), instruments exposed to the country, index heat map, the fifteen indices with peer quartiles, peer box plot |
| CIO | Instrument selection | fmre, honi | Universe with the HoNI score and 10-year change of every economy an instrument is exposed to (filter by economy), track record, coverage, classification and ticker flags; role profiles over 25 states; instrument against its role; shortlist (include / watch / exclude) saved to the decision log; a **nominal / real switch** (default nominal): real shows fmre's real profiles (`basis=real`) in CHF, EUR or USD, with the per-state inflation fmre used (measured, extrapolated, fallback) and the hard-currency note (C-31); **inflation pass-through (scenarios)**: per instrument its type, house beta, the CIO's override and the effective beta, set (beta 0 to 1.5, optionally a duration) or reverted with a required reason, the acting curator as `set_by`, each instrument's override history; where a scenario ReturnSet is shown (here and on Parameters), the beta fmre used per instrument and its source (C-32) |
| CIO | Regime and signals | cycle; later aggregation, mrs, macrofield | Cycles live: position of every economy in its five cycles, the cycle layer on the 25-bin axis, one economy over time with the aggregate (solid, all members; dashed, anchored members only), alignment and synchrony windows (C-12, C-19). The Regime waits for aggregation |
| CIO | Optimiser hand-over | pcp | The CIO's bounds and shortlist, and where each client's mandate is finalised and run (Curator, Parameters) |
| CIO | Exports and decisions | cockpit | Excel workbooks and the decision log |
| Curator | Clients | `client_overview` | Every client, search, open items (threads awaiting an answer, approvals awaiting a curator, open report requests) |
| Curator | Client | `answer_current`, `thread_state`, `report_request_state`, `approval_state`, plan tables, `engine_run`, `parameter_set` | Answers with the content version answered, household, positions, goals, facts; threads with an answer box; reports and requests (report shown sandboxed); approval requests with approve or send revision; parameter sets and engine runs; **Compute balance sheet**: lbs run on demand through the consumer app, the run it recorded shown, the artefact linked and handed to Parameters (C-20). Opening it writes the C-10 audit session |
| Curator | Parameters | lbs, pcp, aggregation, fmre; `parameter_set_current`; presets in `content_current` | The pcp Mandate (`pcp-mandate@1.0.0`) as a form in percent (C-21): start from a **mandate preset** (8, C-22; every role held by at least two instruments, C-29), the current set or the lbs `mandate_proposal`; **Regime**: the **optimism level** (defensive, default, aggressive, rogue; default unless chosen), which takes the latest succeeded Regime of that level, then no scenario or a scenario (depression, hyperinflation, stagflation, deferral) aggregation derives from that Regime (C-30), the **currency** (CHF, EUR, USD) the ReturnSet is fetched in (C-23), and the **basis** (nominal by default, or real), which sets the Mandate's `basis` and fetches fmre's ReturnSet with `basis=real`, shown with the ReturnSet and on the allocation; the target-curve presets stay nominal data, read as real in real mode (C-31); **target curve** from 13 presets drawn as small charts, with level shift, slope tilt, match to lbs's required return and a live preview, in percent per year (stored as ln(1 + p/100)); the universe grouped by role with search and counts; fixed allocations as a table; bounds as a table per dimension with the fixed source; the regime blend as a market or economy weights adding up to 100 %; lbs-derived values marked and resettable; pcp's `/validate` problems next to the fields; Finalise, Run pcp (recorded as an `engine_run`), the allocation with the Regime ("Regime: default optimism, scenario stagflation"), policy and currency it was computed under |
| Curator | Approvals | `approval_state` | Everything awaiting a curator across clients, with approve or send revision |
| Curator | Questionnaires | `content_current`, `content_record`, `scoring_bind_check` | Every content key and its versions; questions, why-texts and options edited in a form (or any content in JSON) and saved as a new version with `save_content()`; the scoring binds that mismatch |
| Curator | Consumer app | roster `kind: app` | Status, start, and a link to the app on 8017 (C-18) |
| Models | Cycle Model, Health of Nations, Macro Field, Market Risk Signal, Aggregation (Regime) | each engine's `GET /model` | Per engine, for one economy: what comes in (plain names, the data), every calculation step with its formula, parameters and charts, what goes out. All five engines publish their card |
| System | Engine status | all | Flow graph, `/health` and `/meta` of every roster engine, allowlist check, start buttons, logs |
| System | API explorer | all | Any endpoint through the proxy (development mode) |
| Test benches | one per engine | each engine | honi, macrofield, fmre, cycle, aggregation, pcp, lbs: their own bench, unchanged, through the proxy (aggregation's: run a Regime on chosen mrs, cycle and macrofield artefacts, distribution, the four optimism levels, path, contributions, markets). datafeed: a basic bench (snapshots, coverage, registry). Others: a placeholder with the engine's state |

`service.mode: cio` (or `COCKPIT_MODE=cio`, or `--mode cio`) hides the benches and the API
explorer and makes the proxy read-only except for `cio.writable` (C-02): `honi:/run`, `cycle:/run`,
`aggregation:/run` and `aggregation:/scenario` (C-24), all answered from the engine's cache when unchanged, and
`pcp:/validate`, which stores nothing. The curator
routes and the decision log are allowed in both modes; in `cio` mode pcp runs only through the
curator route, which records each run (C-16). lbs on demand goes through the curator route too, which
calls the consumer app; a write to the app through the proxy is refused in `cio` mode (C-20). The CIO's inflation
beta override goes through the cockpit route `PUT /api/cio/inflation-beta/{id}` in both modes, because the proxy
matches exact paths only and fmre's carries the instrument id; `cio.writable` does not name it (C-32).

## Exports

| Workbook | Sheets |
|---|---|
| HoNI (`/api/export/honi/{artefact}.xlsx`) | Read me (provenance, notice, warnings), Overview of the latest year, HoNI Score (years by countries, as in `HoNI_Export.xlsx`), the three sectors, Capital saturation, one sheet per country (scores and raw values of the fifteen indices), Trends 10y (as `HoNI_Lite.xlsx` showed them), Exposed instruments, Peer stats, Coverage, Calibration |
| Instruments (`/api/export/instruments.xlsx?shortlist=&honi_artefact=`) | Read me, Universe (register with countries, track record, classification, CIO decision), HoNI exposure (every instrument and economy with its HoNI score, change and level z), Role profiles, Instrument profiles, Profile methods, Register integrity |
| Decision (`/api/export/decisions/{id}.xlsx`) | Decision (basis, author, note), Rows |

Written with the standard library (C-04). Every page can also be printed to PDF.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/` | The single page front end |
| GET | `/api/config` | Roster, mode, CIO defaults |
| GET | `/api/graph` | Every engine's `/health` and `/meta` (allowlist check), edges, engines started here |
| GET, POST | `/api/decisions`, `/api/decisions/{id}` | The CIO's decision log, append-only |
| GET | `/api/export/...` | The workbooks above |
| GET, POST | `/api/launcher`, `/api/launcher/{engine}/start`, `/api/launcher/{engine}/log` | Engine supervisor |
| GET | `/api/curator/status`, `/api/curator/curators` | Store reachable, role, counts; curators (in service flagged) |
| GET | `/api/curator/clients?q=&open_only=`, `/api/curator/clients/{id}` | The client picker; everything the Client page shows |
| POST | `/api/curator/clients/{id}/sessions` | C-10 audit: a curator opened the client's material |
| POST | `/api/curator/threads/{id}/messages`, `/api/curator/threads/{id}/close` | Curator answer (optionally closing), close |
| GET | `/api/curator/reports/{id}` | A report with its HTML |
| GET, POST | `/api/curator/approvals?state=`, `/api/curator/approvals/{id}/approve`, `.../revise` | The queue; the one terminal event |
| GET, POST | `/api/curator/clients/{id}/parameter-sets` | The client's parameter sets; finalise one (supersedes the current) |
| GET | `/api/curator/regime?optimism=&policy=` | The Regime a pcp run uses: the latest succeeded Regime of the optimism level (`default` when none is named), chosen by the Regime's own `optimism_scale`, and with `policy` the scenario derived from it; `levels` for the selector (C-30) |
| POST | `/api/curator/clients/{id}/runs`, `/api/curator/runs/{id}/refresh` | Run pcp on the current set, recorded as an `engine_run` (optional `currency`, `basis`, `regime_policy`, `base_regime_id`: checked and answered as `context`, never sent to pcp, C-23). With no `regime_id` the cockpit chooses as the page does: the latest Regime of `optimism` (`default` unless named), the scenario of `regime_policy` derived from it, and fmre's ReturnSet for it in the mandate's currency; `context.optimism` names the level (C-30). Ask again about a running one |
| POST | `/api/curator/clients/{id}/balance-sheet` | lbs on demand: calls the consumer app's `POST /api/clients/{id}/balance-sheet`, which builds the request and records the `engine_run`; answers with that run and the sheet (503 when the app is down, C-20) |
| GET, POST | `/api/curator/content?kind=`, `/api/curator/content/versions?key=`, `/api/curator/content/version?key=&version=`, `POST /api/curator/content` | Content keys, versions, a version's body; save a new version |
| GET | `/api/curator/binds?all=` | `scoring_bind_check` (mismatches only by default) |
| GET | `/api/curator/presets` | The current target-curve and mandate presets with their versions (C-22) |
| GET, POST | `/api/curator/mandate/vocabulary`, `POST /api/curator/mandate/assemble`, `POST /api/curator/mandate/form` | The form's dimensions, buckets and fixed sources; the form (percent) as pcp's Mandate, 422 naming each field it cannot convert; a Mandate back in the form's units (C-21) |
| PUT | `/api/cio/inflation-beta/{instrument_id}` | The CIO's inflation pass-through override, forwarded to fmre's `PUT /v1/inflation-beta/{id}` as `{beta (0 to 1.5, null reverts), duration? (0 to 30 years), reason (required), set_by}`; 422 before fmre for a missing reason or a value out of range; the acting curator checked in service first; fmre's answer unchanged (C-32) |

Every curator write carries `curator_id`, the acting curator; the database refuses a revoked one.
| any | `/api/{engine}/{path}` | Proxy to the engine, so the browser talks to one origin |
| GET | `/bench/{engine}/` | The engine's own test bench (development mode) |

## Configuration

`config.yaml` < `config.local.yaml` (git-ignored) < `COCKPIT_*` (`HOST`, `PORT`, `MODE`,
`DATA_DIR`, `CURATOR_DB_PASSWORD`). The roster lists twelve engines: 01 datafeed, 02 honi, 03 macrofield,
04 aggregation, 05 mrs, 06 fmre, 07 pcp, 12 cycle, 13 lbs, 14 lbsim, 15 report and 16 chatbot
(08 `mvopt` and 10 `review` are dropped, C-27; 09 `scenario` is merged into aggregation, C-28;
the cockpit is Engine 11 itself), each with its URL, status, test bench, start command and, where it differs, interpreter (C-17);
engine NN listens on 80NN. The consumer app is an entry of `kind: app` on 8017, with no engine
number (C-18). `curator_db` names the curator's connection (host, port, `simtech`, schema
`eigentlich`, user `curator`); its password is never in `config.yaml`. Nothing is hard coded.

## Layout

```text
cockpit/
  config.yaml            roster, ports, mode, CIO defaults, how to start each engine
  start.cmd              server only
  sim-tech Cockpit.cmd   desktop app
  src/cockpit/
    api.py               routing: front end, proxy, graph, decisions, exports, launcher, curator, the CIO's override route (C-32)
    clients.py           probes and proxy calls to the engines
    curator.py           the curator's SQL on schema eigentlich (psycopg, role curator, C-16)
    mandate.py           the Parameters form and pcp's Mandate: unit conversion and assembly, plain Python (C-21)
    decisions.py         the CIO's decision log (validated, append-only JSON lines)
    export.py            Excel workbooks, standard library only
    launcher.py          starts engines in the background, reads their logs
    desktop.py           the desktop app window and the shortcut
    settings.py          configuration loading and precedence
    static/              index.html (single page, Plotly from CDN), icon
  dev/make_icon.py       draws static/cockpit.ico
  dev/make_deploy.py     writes ../Macro/deploy/cockpit, CIO pages only (C-03)
  dev/build_presets.py   builds, validates (pcp) and saves the target-curve and mandate presets (C-22)
  dev/presets/           the copy of what build_presets.py saved; the tests read it
  data/                  decisions.jsonl and logs/ (local state, git-ignored)
  tests/test_api.py      fake engines, no database
  tests/test_curator.py  the curator workflow on a throwaway schema t_<hex>
```

## Open points

- Nominal and real (C-31): the macro views (cycle, aggregation, macrofield) stay nominal, with no switch.
  lbs's real figures (the real required return) are not used yet, so in real mode the curve's level is set by
  the shift, not matched to lbs. The Excel exports stay nominal.
- Inflation pass-through (C-32): Instrument selection shows the base ReturnSet, which carries no pass-through, so the
  beta a scenario used is seen on Parameters (the scenario sets) until the page offers a scenario view. The override
  history is read from fmre's `GET /v1/inflation-beta/{id}/history` (C-33).

- report and chatbot start from the roster (status built); neither has a test bench file in the
  roster yet (each serves its own at `/`).
- lbs runs automatically in the consumer app and on demand from the Client page (C-20). The run the
  cockpit sends the acting curator (`{"curator_id": ...}`), and the app records the run as requested by
  that curator.
- A report revision needs the revised report produced by the backend first; the cockpit only
  names it in the approval event.
- The Regime for a pcp run is the latest succeeded Regime of the chosen optimism level (default unless the
  curator or the caller names another), or a scenario derived from it (C-23, C-30), or typed; a per-client
  choice of Regime vintage is not modelled, and the level is not stored with the `engine_run` (no column; the
  result names it from aggregation's Regime). The scenario policy of a run is not stored
  with the `engine_run` (no column); the result names it from aggregation's Regime.
- The mandate presets (`mp@1.1.0`, v2 of `reference/mandate-presets`, C-29) hold at least two active instruments
  in every role and were validated with pcp 1.2.0 on 29.09.2026: all eight ok as they stand and with every role
  floor at 5, 10 and 15 %. Rebuild them with `python dev/build_presets.py --save --curator <id>` after an fmre
  recalibration or a pcp change (`--keys mandates` leaves the target-curve presets as saved). The saved
  validation came from a pcp 1.2.0 instance; the server on 8007 answers with 1.2.0's checks once restarted.
- The Regime view, once aggregation publishes (and mrs, cycle behind it).
- The instrument-to-country mapping (fmre `COUNTRY_EXPOSURE`) was proposed from names,
  tickers and regions and is for the CIO to confirm (C-10).
- Plotly comes from the CDN, so the charts need internet access (Guide section 3).
