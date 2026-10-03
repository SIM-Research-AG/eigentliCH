# cockpit: decisions index

Every place the cockpit departs from the Engine Building Guide, from the component page
"Engine 11: Cockpit", or from a convention, with the reason.

**C-01 One front end for the whole system (owner, 27.09.2026).** The CIO interface for HoNI
(Notion task "HoNI: CIO interface for boundary conditions and instrument selection") is not a
separate page beside honi. It lives in the cockpit, together with every engine's test bench,
so there is one place to look at the system. Two groups of pages:

- **CIO** (production views): Overview, Boundary conditions, Country dossier, Instrument
  selection, Regime and signals, Optimiser hand-over, Exports and decisions.
- **Curator** (production views, C-16): Clients, Client, Parameters, Approvals,
  Questionnaires, Consumer app.
- **System and test benches** (development views): engine status, API explorer, and one page
  per roster engine. An engine that has its own test bench (honi, macrofield, fmre) is shown
  in it unchanged, pointed at the cockpit's proxy through the bench's existing `?api=`
  parameter; an engine without one gets a placeholder that says what exists (parked,
  scaffold, planned), or for datafeed a basic bench over its registry and snapshots.

**C-02 Two modes instead of two applications.** `service.mode: development` shows everything;
`cio` shows the CIO pages and the engine status only, serves no test bench, and the proxy
refuses every write except those listed in `cio.writable` (default `honi:/run`, which is
idempotent). The same code serves both, so the CIO views are tested every time the benches are.
The cockpit's own write routes are not proxied and are allowed in both modes: the decision log
(C-06) and the curator workflow (C-16), both production work.

**C-03 The CIO pages are deployed, in `cio` mode (owner, 27.09.2026).** The Guide keeps the
cockpit and every UI out of deployment; the CIO pages are the recorded exception, because
they are a product view, not a development tool. `python dev/make_deploy.py` writes
`../Macro/deploy/cockpit` beside the engines' deploy folders: `src/cockpit`, `pyproject.toml`,
`README.md`, `DECISIONS.md`, a start script, and a `config.yaml` rewritten for production
(`mode: cio`; no test bench, start command, autostart or Python path, so a deployed cockpit
shows the engines and never starts them or reads their source folders). No tests, `dev/`,
`data/` or `config.local.yaml`. On the build machine the full development cockpit and the
desktop app (C-05) stay as they are.

**C-04 Excel written with the standard library.** The old `HoNI_Export.xlsx` is the bar for
the export. `openpyxl` is outside the allowlist, so the workbook is written directly (an
`.xlsx` is a zip of XML parts, `export.py`). Checked by reading the files back with openpyxl
and by opening them in LibreOffice Calc. Numbers are written exactly as the engines served
them; a missing value is an empty cell, never 0.

**C-05 The desktop app is a browser in app mode, not a GUI toolkit.** `python -m cockpit
desktop` (or the desktop shortcut from `python -m cockpit shortcut`) starts the `autostart`
engines that are not already running, serves the cockpit in-process and opens it in Edge or
Chrome with `--app` and a profile of its own under `%LOCALAPPDATA%\sim-tech\cockpit`. No new
dependency (pywebview, Qt, Electron would each be one). Closing the window stops the cockpit
and the engines the app started; engines that were already running are left alone. Without
an app-mode browser, or when the browser hands the window to another process, the app ends
45 s after the page's last heartbeat.

**C-06 The CIO's decisions are kept by the cockpit.** HoNI has no automated consumer; the CIO
reads it and sets the optimiser's boundary conditions and the instrument shortlist. They are
stored in `data/decisions.jsonl`: append-only, validated (bounds in percent, minimum not above
maximum), each stamped with the artefacts it was read off (HoNI artefact, run, snapshot,
calibration; Fund Map return set and calibration). pcp's Mandate (`pcp-mandate@1.0.0`) turned
out to be per client, not per house: it is finalised by a curator as a parameter set in schema
`eigentlich` (C-16), and the CIO's bounds and shortlist are what the curator draws the policy
fields of a mandate from (universe, position cap, policy bounds). So this log does not retire;
nothing posts it to pcp automatically. It is the one piece of state the cockpit holds in its own
folder; it is a record of human decisions, not a model artefact.

**C-07 No maths, enforced.** The cockpit computes no figure. Views sort, select and lay out
what engines return; chart geometry (bar length, axis ranges) is presentation. A test fails if
any cockpit module imports numpy, pandas, scipy or statistics. Figures that do not exist in an
engine are not produced here: the 10-year trend and level `HoNI_Lite.xlsx` showed were added
to honi instead (`GET /trends`, honi D-29), and the cockpit displays them.

**C-08 Engines are probed, never required.** Every page degrades to a message when an engine
is down; the status graph never fails. On Windows a refused localhost connection is retried
for about 2 s, so an empty port shows as "not answering" rather than "connection refused".

**C-09 The Fund Map engine predates the standard endpoints.** It speaks `/v1/health` and has
no `/meta`; the roster marks it `api: v1` and the status view shows its health payload
instead. Its allowlist check is therefore not visible in the cockpit.

**C-10 HoNI and the instruments are linked through the register (owner, 27.09.2026).** The
Fund Map register now names the economies each instrument is exposed to (`countries`,
datafeed country codes, fmre `store/etl/universe.py::COUNTRY_EXPOSURE`), the same registry
honi's peer set uses. The cockpit joins on that code only: Instrument selection shows each
exposed economy's HoNI score and 10-year change and filters by economy; the Country dossier
lists the instruments exposed to the country; Boundary conditions counts them per country;
both workbooks carry the link. A regional instrument lists each peer-set economy it holds,
without weights, and no score is blended across them (a blend would be maths, and the
weights a decision nobody has taken). The mapping itself was proposed from names, tickers and
regions and is for the CIO to confirm.

**C-11 A stored HoNI artefact is shown when honi cannot run.** honi refuses a run while
datafeed is down (it checks datafeed's coverage first, honi D-27), which used to blank every
HoNI page although the artefact is stored and immutable. The page now falls back to the last
artefact it read for the snapshot, and says so on the page and in a notice.

**C-12 The cycles are shown before the Regime exists (owner, 28.09.2026).** Regime and signals
no longer waits for aggregation to show anything: it runs the cycle engine on the selected
snapshot (`POST /run`, idempotent, so a repeat is answered from cycle's cache) and draws where
each economy stands in its five cycles (trough to peak, with the phase), the cycle layer on the
25-bin axis, and one economy's cycles over time. `cycle:/run` is added to `cio.writable` for
that. cycle's own test bench is wired in (`bench:`), so its page is no longer a placeholder.

**C-13 No disclaimer footer on the pages (owner, 28.09.2026).** The footer "Model-derived
research output. Not investment advice. Every figure on this page comes from an engine
endpoint; the cockpit computes nothing." is removed from every page. The rule behind it (the
cockpit computes nothing) still holds; the Excel exports keep their notice.

**C-14 CIO default snapshot `bloomberg-2026-01-05` (owner, 28.09.2026).** datafeed's current
snapshot under a meaningful id (the r3 import with public fills and the market layer, identical
cells); `cio.snapshot` points at it. The Cycles chart shades the projected years (cycle's
`observed_until` to `projected_until`) and the layer and matrix read the last observed year.

**C-15 Models: one page per engine, drawn from the engine's model card (owner, 28.09.2026).**
The owner wants each engine shown the same way: what comes in, what it looks like, what gets
calculated (functions with the maths, and charts) and what goes out. Each engine publishes
`GET /model?economy=` (`model-card@1.0.0`); the Models group has one page per engine (cycle,
honi, macrofield, mrs, aggregation, in that order) and one renderer for all of them. The page computes
nothing: every number, the intermediate steps included, comes from the card. Formulas are LaTeX
from the engine, typeset with KaTeX from the same CDN as Plotly, loaded on the first model page
only; without it the formula shows as source. An engine without a card shows a placeholder.

**C-16 The curator workflow writes schema `eigentlich` directly, as role `curator` (owner, Build
Instruction section 9.1, 28.09.2026).** The stated exception to the one-writer rule: the cockpit
connects to database `simtech` as the login role `curator` (USAGE on the schema; SELECT, INSERT,
UPDATE on its tables and sequences; no DELETE; nothing elsewhere) and issues the SQL the store's
contract documents (`eigentliCH_Engines/eigentlich/SCHEMA.md`, section 7). `curator.py` holds that
SQL and nothing else; every rule that matters (append-only tables, set-once columns, one terminal
approval event, content versions max+1, a linear parameter-set chain, engine runs forward only, a
revoked curator cannot act) is the database's, and a refusal comes back with the database's own
message (trigger rule 409, or 403 for a revoked curator or a missing privilege; check and key
failures 422). No sign-in: the header offers an **acting curator** selector (curators in service
from table `curator`), remembered in the browser, and every write names it; the database refuses
a revoked one. Opening a client's page with an acting curator chosen writes a `curator_session`
with an `opened` event (the C-10 audit), once per visit. Approval happens only on the client's
request (`approval_request`); an answer revision writes the corrected answer as a curator message
in the same thread and names it in the event (one transaction); a report revision names the new
report the backend produced. Questionnaire content is edited in place and saved through
`save_content()`, a new version per save, as the client can. The password is never in
`config.yaml`: `curator_db.password` in the git-ignored `config.local.yaml`, or
`COCKPIT_CURATOR_DB_PASSWORD`; the deployed config keeps the connection without it. psycopg is
declared in `pyproject.toml` (the allowlist exception admitted system-wide).
*Modes.* The curator routes (`/api/curator/...`, a reserved segment) are allowed in both modes,
as `/api/decisions` is: they are the curator's production work, and the deployed cockpit (cio
mode) is where it happens. `pcp:/validate` is added to `cio.writable` (it stores nothing).
`pcp:/run` is not: in cio mode pcp runs only through `POST /api/curator/clients/{id}/runs`, which
writes the `engine_run` row first (so a revoked curator is refused before pcp is called), calls
pcp with the current finalised parameter set and the chosen Regime and ReturnSet ids, and records
the outcome (succeeded with the artefact, failed with the error, or running under its run id,
refreshed later). A pcp run from the cockpit is therefore always recorded with the client.
*Tests* (`tests/test_curator.py`) run against a throwaway schema `t_<hex>` created by the owner
role from the store's own `schema.sql`, with the curator granted exactly what provisioning grants
(as the store's tests do, EIG-26), and dropped afterwards; they need the PostgreSQL server and are
skipped, with the reason, when it is unreachable. The rest of the suite needs no database.

**C-17 An engine may name its own interpreter.** lbs, report, chatbot and the consumer app live
in `eigentliCH_Engines/.venv`, not in the Macro venv the cockpit and the macro engines use. Rather
than installing them twice, a roster entry may carry `python:` (relative to the cockpit folder);
the launcher starts that engine with it and every other engine with the top-level `python`. A
named interpreter that does not exist is an error, never a fallback: the fallback would start the
engine without its packages. The deploy build drops the per-engine `python` with the rest of the
start configuration (C-03).

**C-18 The consumer app is in the roster as `kind: app`.** The eigentliCH consumer web app is not
an engine and has no engine number, but the cockpit starts it with the system (`autostart`),
probes it, and links to it (the Curator group's Consumer app page, and a button on the Clients,
Client and Parameters pages). A roster entry of `kind: app` carries no number and its own port
(8017); the "engine NN listens on 80NN" test applies to engines only and checks that an app takes
no engine's port. Its start command (`python -m eigentlich serve` in `eigentliCH_Engines/eigentlich`)
is the one the app's builders announced; until it exists the entry stays `scaffold` and a start
attempt ends in its log.

**C-19 The cycle chart shows the aggregate (review R-004).** Regime and signals, section "One
economy over time", draws what cycle's own bench now draws: the aggregate (`superposition`, solid,
thick) over the thinned five cycles, its continuation over the anchored members only
(`superposition_anchored`, dashed) after the last year the full aggregate covers, a bold label at
each line's end, and a lower panel with the alignment and the synchrony windows shaded. Both
aggregate lines are the engine's published fields, unaltered; the page picks the years to draw,
nothing more. Artefacts stored under `cycle-state@1.1.0` have no `superposition_anchored`: then no
continuation is drawn and the note says why. The note is built from the artefact: which cycles the
aggregate holds in each part of the timeline, and that the alignment and the windows cover the
full set and stop at the data edge.

**C-20 lbs on demand from the Client page, through the consumer app (owner, 29.09.2026).** lbs runs
automatically in the consumer app and on demand from the cockpit. The Client page's **Compute balance
sheet** button calls the cockpit route `POST /api/curator/clients/{id}/balance-sheet`, which calls the
app's own `POST /api/clients/{id}/balance-sheet` (the roster's `kind: app` entry, 8017). The cockpit
does not build the lbs request: the app gathers the client's data, builds the request, calls lbs and
records the `engine_run`, exactly as when it runs lbs itself; the cockpit writes nothing for this call.
It checks first that the client exists and the acting curator is in service (so a revoked curator never
reaches the app), then answers with the `engine_run` the app recorded (read from the store as role
curator: the client's newest lbs run, taken only if it is newer than the one before the call) and the
sheet the app returned. The page shows the run, links the LifeBalanceSheet artefact (`/api/lbs/artefacts/{id}`
through the proxy) and opens Parameters with `?lbs=<artefact>`, so the mandate is prefilled from it;
the engine runs table offers the same link on every succeeded lbs run. If lbs is down or refuses, the
app records a failed run and the page shows it with the app's message; if the app itself is down, the
route answers 503, says so plainly (the app's URL, start it on the Consumer app page) and nothing is
recorded.
*Why a cockpit route and not the proxy.* The browser could reach the app through `/api/eigentlich/...`
in development mode, but in cio mode the proxy forwards only the exact `engine:path` pairs in
`cio.writable`, and the app's path carries the client id, so no entry could name it. A curator route
is allowed in both modes, like every curator write (C-16), and gives one place for the curator check
and the plain message. `cio.writable` is unchanged: a write to the app through the proxy stays refused
in cio mode (tested). Nothing was added to the proxy for `kind: app` entries.
*Attribution.* The app's endpoint takes no body, so the run it records names the client as requester
(`requested_by_kind client`), not the acting curator. Which curator asked is not recorded yet; that
needs the app to accept a requester (open point).
*Parameters.* The lbs artefact the page starts from is now, in this order: the `lbs` in the link, the
client's latest succeeded lbs run, the one last entered in this browser. Before, the remembered one
came first and hid a newer run.
*Tests* (`tests/test_curator.py`): a stand-in app on a mock transport (8017) that records the run in
the throwaway schema as the app would; the success path, lbs down behind the app, the app down, a
revoked curator and an unknown client (neither reaches the app), and cio mode.

**C-21 The Parameters form is in percent; the cockpit converts, in plain Python (owner, 29.09.2026).** The
curator enters every weight and bound in percent of the portfolio and the target curve in percent per year.
`src/cockpit/mandate.py` turns the form into pcp's Mandate (`POST /api/curator/mandate/assemble`) and back
(`POST /api/curator/mandate/form`): `p / 100` for weights and bounds; a curve point of `p` percent per year is
stored as `ln(1 + p/100)` (`math.log1p`), curve_unit `annualised_log_return`, the unit lbs proposes in; the
page states the conversion next to the curve. A preset curve is adjusted by a level shift `s` and a slope tilt
`t` (percentage points): point `i` becomes `preset_i + s + t * (i - 13) / 12`, so the tilt adds `t` at state 25,
takes it off at state 1 and keeps the mean. Matching lbs's required return shifts by `required * 100 - preset
mean`, the mean being stored with the preset (lbs levels its own ramp the same way, on the equal-weighted mean).
*Why this does not break C-07.* These are unit conversions of numbers the curator typed or a preset stores, not
model figures: nothing is estimated, no engine output is recomputed, and `math` is the standard library (the
test still refuses numpy, pandas, scipy and statistics). The browser repeats the shift and tilt for the live
preview and adds up the economy weights to say whether they reach 100 %; the server's assembly is what is saved.
A bound row left empty, or 0 to 100 %, constrains nothing and is left out. `bound_sources` is not typed any more:
it is set per bounded dimension from pcp's fixed rule (currency, liquidity, role derived; region, capital type,
phase, asset class policy), so a mislabelled source cannot be entered. The form names each field it cannot
convert (422 with `problems`, field and message); pcp's `/validate` judges the rest, and its problems are shown
next to the field they concern (matched on the dimension or field named in pcp's message; anything unmatched
stays in the actions card).

**C-22 Presets are content, versioned in the store (owner, 29.09.2026).** Two keys of kind `reference` in schema
`eigentlich`, saved with `save_content()` as role curator, a new version per save, editable later like any
content (Questionnaires page): `reference/target-curve-presets` (13 named 25-state curves in percent per year,
each with its formula, mean, minimum, maximum and provenance) and `reference/mandate-presets` (8 ready mandates in
pcp's shape, each naming its curve preset, with the result of pcp's `/validate`). `dev/build_presets.py` builds
them once (numpy allowed there, not in the package), validates every mandate preset with pcp against the latest
Regime and the ReturnSet fmre serves for it in the preset's currency, and saves them with `--save --curator <id>`;
`dev/presets/*.json` is the copy of what was saved, and the tests read it. The role curves take the shape of fmre's
four role profiles (ReturnSet `role_profiles`, calibration named in the provenance) around a stated level; the
others are closed-form shapes. Universes use active register instruments only (not Short MSCI US or CS Long Vola,
which fmre deactivated). Saved 29.09.2026 as v1 of both keys by curator Nicolas; all eight validated `ok`
(Regime `RGM-84547bcbce44aaa0`, 75 constraint rows). The mandate presets are now v2 (`mp@1.1.0`, C-29). A preset that no longer validates after an fmre or pcp change
is shown with its recorded problems; rebuild with the script. *Names, not ids.* The curator pages show objects by
name (client, goal, instrument, mandate) with the id as a small chip that copies on click (owner, 29.09.2026);
lbs's field keys are shown as plain field names.

**C-23 The Regime is chosen on the Parameters page, and the ReturnSet follows the mandate's currency (owner,
29.09.2026).** The Regime is the latest succeeded one of the chosen optimism level (C-30); a scenario (depression, hyperinflation,
stagflation, deferral, or whatever `GET /scenarios/policies` names) is derived from it with `POST /scenario
{base_regime_id, policy}` and served like any Regime. The ReturnSet is fetched as `GET /v1/return-set?regime_id=
...&include_instruments=true&include_blocks=false&currency=<mandate currency>` (CHF, EUR, USD). The run route takes
the page's context beside the ids (`currency`, `regime_policy`, `base_regime_id`), never forwards it to pcp (its
request forbids extra fields), refuses with 409 before pcp is called when the ReturnSet's currency is not the
finalised mandate's, and answers the recorded run with a `context` block. The `engine_run` row keeps exactly what
pcp was sent; no store column holds the policy, so the result names it from aggregation (`GET /regime/{id}/current`
carries a `scenario` block with policy and base) or from what the page remembered. The allocation shows which Regime
(and policy) and which currency it was computed under.

**C-24 `aggregation:/scenario` is writable in cio mode.** A scenario Regime is derived from a base Regime and a
named policy, and a repeat is answered from aggregation's cache (`cached`); like `aggregation:/run` it creates no
client state, and the curator needs it in the deployed cockpit to choose a scenario. Added to `cio.writable`; pcp's
run stays off the list (C-16).

**C-25 The snapshot selector appears only when there is a choice (owner, 29.09.2026).** With one datafeed snapshot
(`bloomberg-2026-01-05`) the header selector added nothing, so it is hidden, not removed: the cockpit still reads
`cio.snapshot` and the selector's value as before, and shows it again as soon as datafeed offers more than one
snapshot. The System page names the snapshot in use in a plain line; exports and stamps keep it as before.

**C-26 The house's AI is shown as MiniMind (owner, 29.09.2026).** spark7 is only the server it runs on. Wherever
the cockpit names the author of a drafted answer (Client page threads, Approvals), it shows "MiniMind"; the stored
`thread_message.author_kind` stays `spark7`, and the model id is shown as a detail. A display mapping only.

**C-27 Engines 08 `mvopt` and 10 `review` are dropped (owner, 29.09.2026).** Their roster entries are
removed; engine numbers 8 and 10 no longer exist, and the port rule (Engine NN on 80NN) holds for the rest. Engine
09 `scenario` stays, with no downstream engine for now.

**C-28 Engine 09 `scenario` is merged into aggregation and dropped (owner, 29.09.2026).** aggregation issues
the scenario Regimes (the four `Scenario_SAA.m` policies) that the Parameters page offers; the roster entry is
removed.

**C-29 Every mandate preset holds every role (29.09.2026).** When a client's parameters are applied, lbs's derived
role bounds replace a preset's role bounds, so a preset with a role left empty is refused by pcp for every household.
Four of the eight `mp@1.0.0` presets did: Income focus (no Stabilisation, one Gain instrument), Crisis-resilient (no
Income), Swiss home bias (no Stabilisation) and Barbell CHF (neither Income nor Stabilisation); Growth global held one
Stabilisation instrument once fmre moved Global Bonds back into Income. The 18 failed pcp runs found building the 20 use cases
(pcp PCP-21) all started from presets: 10 from Income focus (one Gain instrument under a derived Gain floor of 17 %),
6 from Growth global (a CHF floor above what three CHF instruments hold, or the equity floor above the Gain ceiling),
one each from Swiss home bias and Balanced CHF (the equity floor above a derived Gain ceiling of 29 %). `mp@1.1.0` (v2 of `reference/mandate-presets`, saved with
`save_content()` by curator Nicolas, `ac586536e6be42c68446c8f8f80e4242`) holds at least two active register instruments
in each of the four roles (`MIN_PER_ROLE`, asserted by `dev/build_presets.py` against fmre's `/v1/instruments`, and by a
test on the saved copy), each preset keeping its character:
*Growth global* adds the Bloomberg hedge-fund index (Stabilisation) and its equity floor goes from 55 to 40 % (the
Gain role, 60 to 85 %, still leads). *Income focus* adds world equities (Gain) and the market-neutral and global-macro
funds (Stabilisation, at most 20 %); Income 45 to 80 %, Gain up to 25 %. *Crisis-resilient* adds CHF investment-grade
credit and Global Bonds (Income, at most 20 %); the Protection floor goes from 35 to 30 %. *Swiss home bias* adds the
CHF market-neutral and trend-following funds (Stabilisation, at most 25 %); its Gain and equity floors go from 30 to
25 % and its Swiss floor from 60 to 50 %. *Barbell CHF* adds CHF credit and Global Bonds (Income) and trend following
and global macro (Stabilisation), each role at most 20 %, so the middle is thin, not absent; Gain and Protection 30 to
60 % each, equity from 25 %. *Balanced CHF* and *Sustainable balanced* keep their universes; their equity floors go
from 30 to 25 %. Short MSCI US and CS Long Vola stay out (inactive in fmre).
*Why the equity floors moved.* An equity floor above lbs's derived Gain ceiling is infeasible whenever every equity
in the universe is a Gain instrument; the lbs role bounds seen in the use cases put the Gain ceiling between 29 and
52 %. *Validation.* All eight were validated with pcp 1.2.0 (the joint feasibility check of PCP-21; the server on 8007
still ran 1.1.0, so a separate 1.2.0 instance on a throwaway schema answered) against Regime `RGM-84547bcbce44aaa0` and
the ReturnSet fmre serves for it in each preset's currency: ok as they stand and with every role floor at 5, 10 and
15 % (the preset's role ceilings kept), recorded per preset in `validation.role_floor_checks`. Against the four lbs role
bound sets of the failed use-case runs, 31 of 32 validate and solve (fast and exact); Growth global under a household
whose Gain ceiling is 29 % does not, by design (a growth preset for a cautious household), and pcp names the Gain
ceiling and the equity floor. *Target curves.* Unchanged, not re-saved: fmre's calibration is still
`CAL-69d9d1ee5245ac71` and the four role profiles give the same points to the hundredth (checked 29.09.2026), so
`reference/target-curve-presets` stays at v1; `build_presets.py --keys mandates` saves the mandate key alone.

**C-30 The Regime is chosen by optimism level, default unless named (29.09.2026).** aggregation issues one Regime per
optimism level (defensive, default, aggressive, rogue) in one go, and its newest run is whichever level finished last.
The Parameters page took "the current Regime" as aggregation's latest succeeded run (C-23), which on 29.09.2026 was the
**rogue** one (`RGM-84547bcbce44aaa0`; aggressive `RGM-3004fe8134b20c86`, defensive `RGM-3198a625d02278fa`, default
`RGM-e2658e8e9bbbc81e`), so pcp runs from the cockpit used the rogue Regime, and the presets were validated against it
(C-22, C-29). The page now offers an **optimism level** selector, defaulting to **default**, and takes the latest
succeeded Regime of that level: `src/cockpit/regime.py` reads aggregation's `/runs` (the latest 200), keeps the succeeded
ones, orders them by time, and takes the newest whose Regime states that level itself (`optimism_scale` of `GET
/regime/{id}/current`), never a position in the list. A scenario is derived from the chosen base Regime (`POST /scenario
{base_regime_id, policy}`), so "stagflation" means stagflation from the chosen level; a scenario Regime keeps its base's
level. The page asks the cockpit route `GET /api/curator/regime?optimism=&policy=`, and the run route makes the same
choice server side when its caller names no `regime_id`: the default level unless `optimism` names another, the scenario
of `regime_policy`, and the ReturnSet fmre serves for that Regime in the finalised mandate's currency (the same query as
the page, whose `include_*` flags change the ReturnSet id). A caller naming a Regime keeps it; the cockpit asks
aggregation for its level and refuses with 409 a named `optimism` the Regime is not at. A `return_set_id` without a
`regime_id` is refused (422): a ReturnSet is stamped for one Regime. The acting curator is checked before any engine is
asked. The run's `context` names the level (`optimism`) whenever it is known; the page and the allocation show both
("Regime: default optimism, scenario stagflation"). *Labels.* aggregation's model card and calibration name no labels for
the levels, so the selector shows the level's name, with the calibration's target state as the hint. *Presets.*
`dev/build_presets.py` picks the Regime the same way (`--optimism`, default `default`); the saved mandate presets (v2)
were validated against the rogue Regime and are not re-validated here. *Tests.* `tests/test_api.py` (no database): the
route picks the default level's latest Regime although the rogue run is newer and an older default run is listed first,
each named level, and a scenario from the chosen level. `tests/test_curator.py`: a run naming no Regime is sent the
default Regime and its ReturnSet; a named level with a scenario, a named Regime's level, the 409 and 422 refusals, and a
revoked curator asking no engine. Both fail with the old choice (checked by reverting once).

**C-31 A nominal / real switch on the Parameters page and the instrument views; the macro views stay nominal
(owner, 29.09.2026).** The binding interfaces are `review/REAL_VIEW_INTERFACES.md` (design note "Design note:
nominal and real view"). The default is **nominal** everywhere, and the basis is always shown next to the
figures. The cockpit converts nothing (C-07): the switch only names the basis to the engines, and every real
figure and the inflation behind it is fmre's (`real = nominal - ln(1 + inflation)`, per state).
*Parameters.* Section 2 is now "Regime, currency and basis", with the switch beside the currency. It sets the
Mandate's `basis`, the basis of its `target_curve` (pcp PCP-22). `mandate.py` writes `basis` into the Mandate
**only when it is real**. pcp's Mandate leaves a nominal basis out of its JSON too, so a nominal mandate keeps
its bytes and its idempotency key, and the presets and the stored sets read back unchanged; `to_form` reads a
missing basis as nominal. The ReturnSet is fetched with `basis=real` when the mandate is real and **without
`basis=` when nominal**, the query pcp itself sends to fmre (`pcp/clients.py`), so both arrive at the same
`return_set_id`. The page shows the basis the set was served on (`provenance.basis`; a set that states none is
nominal), fmre's deflator (index, the scenario when there is one, the count of `deflator.labels` per state)
and the hard-currency note (`hard_currency_fallback {from, to, states, reason}`). It says plainly when fmre
served another basis than the mandate's, because pcp refuses that pair. Loading a stored mandate or the lbs
proposal takes that mandate's basis (the lbs proposal is nominal) and says so when the switch moves. A preset
or an empty mandate keeps the switch as it stands.
*Target curve.* The presets stay nominal data (C-22). In real mode the curve card says that the curve is read
as real, that the level shift and the tilt apply in real terms, and that nothing is converted. "Match the lbs
required return" is disabled in real mode, and a preset applied in real mode does not take its level from lbs,
because lbs's required return is nominal; lbs's real figures are for a later build.
*Run route.* `POST /api/curator/clients/{id}/runs` takes an optional context field `basis` (never forwarded to
pcp, like `currency`, C-23). It answers 409 before pcp is asked when that basis is not the finalised mandate's.
When the route fetches the ReturnSet itself, it asks with the mandate's basis (only when real) and answers 409
if fmre serves another basis (an fmre from before the real view ignores `basis=`). The run's `context` names
`basis`. The allocation shows the basis beside the currency: pcp's `Allocation.basis` (left out when nominal),
otherwise the run's. The history table shows each mandate's basis.
*Instrument selection.* A switch and a reporting currency (CHF, EUR, USD; real only) in the page's link
(`#/cio/instruments?basis=real&ccy=CHF`), so a reload opens nominal unless the link says real. Real asks fmre
for `GET /v1/return-set?basis=real&currency=` (role and instrument profiles, deflated by fmre) and for `GET
/v1/inflation?currency=`. The inflation used is drawn as a small bar chart per state, coloured by fmre's labels
(measured, extrapolated, fallback, not computable), with the counts, the index, `real_view` and the
hard-currency note. If fmre cannot serve the real set, or serves it on a nominal basis, the page says so and
shows nominal figures labelled nominal. A shortlist saved from a real view records `profiles_basis` and the
currency with the ReturnSet id. The Excel export stays nominal.
*The Client page.* Its outlook panel carries the same switch over lbsim's own real views (C-34).
*No switch.* Regime and signals (cycle, aggregation), the Models pages (macrofield and the rest), Country
dossier, Boundary conditions, Overview and Optimiser hand-over stay nominal (owner: macrofield always nominal).
*Tests.* `tests/test_api.py`: the form's basis is nominal by default, is left out of a nominal Mandate and
written for a real one, with the curve's numbers unchanged; the switch appears on exactly the Parameters,
Instrument selection and Client pages (the last for the outlook, C-34; no macro page, no Models page); nominal is the default and basis= reaches fmre and
the run. `tests/test_curator.py`: a real mandate's run asks fmre for basis=real and answers the basis; a nominal
run asks what it asked before; the page-basis mismatch and a nominal set served for a real mandate are refused
before pcp. All four fail with the behaviour reverted (checked once).

**C-32 The CIO's inflation pass-through override, on Instrument selection, written through a cockpit route (owner,
29.09.2026).** Under a scenario Regime fmre carries each instrument to the scenario's inflation with a pass-through beta:
real = historical real + (beta - 1) · ln(1 + scenario inflation), plus a duration loss for a nominal bond, so beta 1 is a
full inflation hedge and 0 none (fmre FMRE-33 to FMRE-37, `engines/fund_map/pass_through.py`). fmre holds the house table
(beta and duration per instrument type, calibration `ipt@...`) and the CIO's overrides, append-only and versioned per
instrument (`inflation_beta_override`; the latest version is in force, a null beta reverts to the house value). The
cockpit computes nothing (C-07): it lists what fmre serves, forwards the CIO's set or revert, and shows the beta a scenario
set used.
*Instrument selection.* A card "Inflation pass-through (scenarios)" lists `GET /v1/inflation-beta` through the proxy
(fmre's `api/main.py`: `{calibration, bounds, instruments}`, each instrument with `type`, `type_label`, `house_beta`,
`house_duration`, `override` (the latest version: `version`, `beta`, `duration`, `reason`, `set_by`, `set_at`) or null, and
the beta in force as `beta` with its `source`, and `duration` with `duration_source`): per active instrument its name, type,
house beta, the override (beta, duration, reason, who set it, when, version) and the effective beta and duration. "override" or "change or revert" opens a form: beta (0 to 1.5), an optional duration in years (0 to 30;
empty keeps the house duration) and the **required reason**; "Set override" and "Revert to house beta" (beta null, with its
reason; a version too). fmre keeps a revert as a version with a null beta (a null duration keeps the house duration),
so the page counts an override as in force only when it names a beta or a duration, and shows a reverted one as
"reverted" with its reason. `set_by` is the **acting curator** chosen in the header (C-16), sent as the curator's id and
shown by name. "History" lists the
instrument's versions newest first from `GET /v1/inflation-beta/{id}/history`. fmre serves no such endpoint yet (its list
carries the version in force only), so until it does the page shows the version in force with its number and says that the
earlier versions are not served (open point). The panel is
the same on the nominal and the real view; the beta acts under a scenario only.
*Which beta a scenario used.* A ReturnSet stamped for a scenario Regime carries `provenance.inflation_pass_through`
(scenario, policy, `inflation_final_12m`, calibration, and per instrument `beta`, `source` house or override, `duration`,
`override_version`, `deflator_currency`). Where a page shows such a set it lists it in a collapsed table: on Parameters
under the ReturnSet line (the scenario sets pcp runs on, with the real switch of C-31), and on Instrument selection under
the role profiles whenever the served set carries it (the base set it shows today carries none, so nothing is shown).
*Why a cockpit route and not the proxy.* The proxy forwards a write in cio mode only for an exact `engine:path` in
`cio.writable` (`Settings.writable`); it has no path prefix, and fmre's path carries the instrument id, so no entry could name
it (as for the app in C-20). Rather than adding prefixes to the proxy, one route forwards the one write: `PUT
/api/cio/inflation-beta/{instrument_id}` with fmre's own body `{beta, duration?, reason, set_by}`, allowed in both modes like
the decision log and the curator routes (C-02). `cio` is a new reserved segment (no engine may take it). The route refuses
with 422, before fmre is asked, a missing or blank reason, a beta outside 0 to 1.5 or missing (null reverts), a duration
outside 0 to 30, no `set_by`, or any other field; it checks the acting curator in the store (`CuratorStore.in_service`), so
a revoked or unknown curator is refused (403, 422) and never reaches fmre; it sends `duration` only when given; fmre's answer
(status and body) comes back unchanged, and an fmre that is down answers 502 saying no override was set. The cockpit keeps
nothing: fmre's versions are the record. `cio.writable` is unchanged: a PUT through the proxy stays refused in cio mode.
*Tests.* `tests/test_api.py`, on a stand-in fmre shaped as its `api/main.py` answers (list, append-only versions, the PUT's
`{written, ...}`) and a stand-in curator check: list through the proxy, set with a reason and a duration, a set without
duration, revert as the next version, fmre's 404 passed through, in
both modes; nine bodies refused with 422 before fmre (no reason, blank reason, a revert without reason, beta 1.6, -0.1,
no beta, duration 31, no set_by, an extra field); in cio mode the proxy PUT refused and never forwarded, `cio.writable`
naming no inflation-beta path, a revoked curator refused before fmre, fmre down, and `cio` reserved; the page's panel, its
PUT with `set_by: actingCurator()`, the revert, and the pass-through table on both pages. `tests/test_curator.py`: against
the throwaway schema, a revoked and an unknown curator never reach fmre, one in service is forwarded as `set_by`.

**C-33 fmre serves the override history (29.09.2026).** This corrects C-32, which says fmre serves no history
endpoint. fmre serves `GET /v1/inflation-beta/{instrument_id}/history` (`Instruments/api/main.py`): every override
version of one instrument, newest first (`version`, `beta`, `duration`, `reason`, `set_by`, `set_at`; a revert has
`beta: null`), `[]` for an instrument never overridden and 404 for an unknown one. "History" on Instrument selection
reads it through the proxy and lists every version; only when the call fails does the page fall back to the version
in force from the list, saying that the earlier versions were not served.

**C-34 lbsim in the cockpit: read through the proxy, run through the app (LBSIM_INTERFACES section 8, owner's
decisions of 29.09.2026).** lbsim (Engine 14, 8014) is in the roster as `built`: it produces LifeBalanceFindings,
LifeBalancePaths and LifeBalancePlan, reads lbs, pcp, aggregation and fmre, and starts with `python -m lbsim serve`
(the API and the optimiser workers) in `eigentliCH_Engines/engines/lbsim` with the `eigentliCH_Engines/.venv`
interpreter (C-17), `autostart` after its four upstream engines in roster order. report and the consumer app list
lbsim among what they read.
*Bench.* The roster declares `engines/lbsim/testbench/index.html`, the convention lbs follows. lbsim ships no bench
file yet, so its page is the placeholder until the file exists (`public()` reports the bench only when it is there);
the committed-config test accepts a declared bench that is missing only for an engine named in `ANNOUNCED_BENCHES`
(lbsim alone).
*Client page: Outlook.* A card shows what the consumer app's "Aussichten" surface shows, drawn from lbsim's
`GET /outlook?client_ref=&life_balance_sheet_id=` through the proxy for the client's newest sheet (the artefact of
the newest succeeded lbs `engine_run`; `client_ref` is the client id, as the app sends it to lbs). It lists the
earning power per adult (the level used: "stated by the client" or "model value", the stated full-pensum income
and the modelled full-time figure, today's income and pensum, the responsibility tier and lbsim's caveats); the
income paths with the zero-return saving need and the free cash per goal (nominal from `saving_need`, real from
`views.real.saving_need`); the findings, each template of `text` filled from its `figures` formatted by unit, with
severity and urgency in words, the schedule and the rules not checked; the chances per goal under the Regime chosen
by its house label, with every Regime's chances in one line; chart 1 (weights by role, house names, and by
instrument, by name, from `allocation_view`), chart 2 (target and reached per state from
`allocation_view.curves[basis]`, "Crisis" and "Boom" at the ends, the 0 % line; in the basis lbsim derived, the
heading is marked converted, as the report marks it, REP-38) and chart 3 (the fan: 5 to 95 and
25 to 75 of 100 paths and the median from `bands[series][basis]`, the series chosen among net worth and each goal
measure, the goal line solid in the goal's own basis and dashed, labelled converted, in the other). The charts are
Plotly through the page's `plot()` helper, and the panel carries a nominal / real switch as C-31's pages do (default
nominal); the real figures are lbsim's own derived views, the page converts nothing (C-07). The plan block follows
`plan.state`: ready shows `action_now` in plain units under "What the calculation assumes" with the plan's own
framing sentence (the owner's decision 3: the same figures the client sees, never a recommendation); calculating
says "The plan calculation is still running (for N minutes, at most 2 hours)" from `elapsed_s` and `budget_s`;
waiting for an allocation, not possible and not requested show lbsim's reason. Collapsed below: the solver details
for the curator (outcome, goal and confidence, chance in and out of sample, shortfall, horizon solved and total with
the rule beyond the cap, the exchange rate, the solver record and versions). Artefact ids appear only as id chips, as
elsewhere on the curator pages; findings, instruments, roles and Regimes are shown by their words.
*Runs through the app.* lbsim requests are built only in the app (the C-20 pattern). **Restart the plan calculation**
calls the cockpit route `POST /api/curator/clients/{id}/outlook` with `{"curator_id", "optimise": "now"}`, which
checks the client and the acting curator (a revoked one never reaches the app), sends the same body to the app's
`POST /api/clients/{id}/outlook` and answers with the lbsim `engine_run` rows the app recorded during the call (the
fast run, succeeded with the paths artefact, and the plan run under its own run id) and what the app returned; the
cockpit writes nothing. **Compute the outlook** sends `{"curator_id"}` alone. An app that refuses before recording
anything is passed on (404, 409, 422, else 502); an app that is down gives 503 and nothing is recorded. The proxy
stays read-only for lbsim and the app in cio mode: `cio.writable` is unchanged.
*Refresh.* A plan run is refreshed by the existing `POST /api/curator/runs/{id}/refresh`. lbsim's `RunStatus` lists
`artefact_ids` instead of naming one artefact, so the row keeps the plan (`LSO-`), else the paths (`LSP-`), else the
findings (`LSF-`); a failed run's error is prefixed with its `failure_kind` (for example `timed_out:`), and a run
that failed has no artefact.
*Parameters.* After a pcp run that succeeded on a base Regime (the run's context names no scenario policy) the page
calls the same cockpit route with `{"curator_id"}` and shows what the app recorded; after a scenario Regime's run it
asks nothing (lbsim refuses a scenario Allocation as its base, LBSIM-14). The Allocation shows chart 1 and chart 2
beside its tables, on the Allocation's own basis.
*Tests.* `tests/test_api.py`: the roster entry; the outlook read through the proxy unchanged in both modes against a
stand-in lbsim serving B1's frozen samples (copied to `tests/fixtures/lbsim/`); the samples carry every field the
panel reads; the page's panel pieces, the restart's body and that the page never posts to lbsim; the Parameters
call only inside the run handler and only for a succeeded run without a scenario policy; the charts' crisis and boom
ends and the 0 % line; the artefact chosen from `artefact_ids`. `tests/test_curator.py`, against the throwaway
schema and a stand-in app that records the two lbsim rows as the interfaces describe: the restart's body, the rows
answered, a revoked curator, an unknown client and a bad `optimise` never reaching the app; the plan run refreshed to
succeeded with the plan's artefact and to failed with `timed_out`; the call without `optimise`; the app refusing and
the app down; cio mode.

**C-35 The outlook panel reads one language: English (29.09.2026).** The cockpit's pages are English (`<html
lang="en-GB">`, every heading and button), so the panel reads the English side of every `{de, en}` pair lbsim sends
(`lw()`, with `OUTLOOK_LANG = "en"`) and its own words from the English side of `OW`, which holds both: "Aussichten"
is "Outlook", "Was die Rechnung annimmt" is "What the calculation assumes", "Planrechnung neu starten" is "Restart
the plan calculation", "Ihre Angabe" and "Modellwert" are "Stated by the client" and "Model value", "umgerechnet" is
"converted", the house roles are Gain, Income, Stabilisation and Protection. This keeps one language per page; the
German words are the app's and the report's. Changing `OUTLOOK_LANG` to `de` switches the whole panel and the chart
labels at once, for a German curator page if one is wanted.
**C-36 The life balance sheet and the four capitals on the Client page (03.10.2026).** The owner's decision of
03.10.2026 (`review/VISUALS_INTERFACES.md`): the balance sheet and the capitals are shown as graphs on the cockpit's
client page too. A new **Life balance sheet** panel, before the Outlook, reads the client's newest lbs sheet through
the proxy (`GET /api/lbs/artefacts/{id}`, the sheet of the newest succeeded lbs `engine_run`, as the Outlook finds its
sheet) and draws, through the page's `plot()` helper: the balance sheet as stacked bars in three columns (Assets by
vessel, Free, Pillar 2, Pillar 3a, Real assets, Vessel not stated, with the human capital on top; Debts and net worth;
the goals' claims, named by the client's goal names), with its own nominal / real switch (C-31's `basisSwitch`,
default nominal): today's assets and debts are the same on both bases, the goals' claims are lbs's `real_view` amounts
in the basis shown; a goal stated a year is named, not stacked; a sheet without a real view says the claims are not
drawn. Under it **The four capitals today** per adult: wealth in francs as words (the household's, as lbs states it,
not split per adult), expertise, network and health as lbs's levels on 0 to 1 in a grouped bar chart whose axis is
"model level, no currency", each bar labelled with its level in words (low, moderate, high by thirds of the scale)
and its number. The **Outlook** panel draws, after the fan, **Expertise, network and health over time** for the
Regime chosen: lbsim's `regimes[].capitals` for the principal, one chart per capital with the middle path and the
bands of 80 and 50 of 100 paths, the y axis the scale lbsim gives for that Regime with "none" and "top of scale" at
its ends, never francs. The scale is read as given per Regime (the network has no fixed model ceiling, so lbsim raises
its top to that Regime's highest p90, lbsim P-26). An artefact made before the field has no `capitals`, and the panel
says so. K3: a health withheld in the lbs request the app sent (`human_capital.health_withheld`) or as lbs states it
(`H.absent_because`) is drawn neither today nor over time, and the panel says "Health withheld (K3): not shown." The
panel shows no raw id; its words are in `OW` in both languages and the page reads English (C-35). The cockpit
computes no figure (C-07). *Tests.* `tests/test_api.py`: the panel's pieces in the page source; the capitals fixture
(`tests/fixtures/lbsim/capitals.sample.json`, made from the spec) has the spec's shape; the page's own chart functions
run in Node with `plot()` recording the traces (skipped without Node): the stacks, the claims following the basis,
the capitals off the money axis, a withheld health without a bar, a Regime's raised network scale.
