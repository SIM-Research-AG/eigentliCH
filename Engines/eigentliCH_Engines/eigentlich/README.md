# eigentlich: the consumer side's store and the client app

PostgreSQL schema `eigentlich` in database `simtech`, the Python package that creates, seeds and
migrates it and gives the backend its repository, and the **client app** (the consumer side of eigentliCH,
section "The client app" below) built on it. It holds client records, versioned questionnaire and
knowledge content, answers, the plan and its decisions, question threads, report requests and reports,
approvals, finalised engine inputs and engine runs (Build Instruction section 9).

* **Backend** (the consumer web app): imports `eigentlich.store`, connects as role `eigentlich`.
* **Cockpit** (curator pages): reads and writes the tables directly as role `curator`: SELECT, INSERT,
  UPDATE, never DELETE.
* **No engine reads this schema.** There is no sign-in: a client picker lists client records.

**[SCHEMA.md](SCHEMA.md) is the contract**: every table, column, constraint, trigger and view, who writes
it, the state machines, and example SQL for the cockpit. [DECISIONS.md](DECISIONS.md) records why
(`EIG-01` onward); [HANDOVER.md](HANDOVER.md) says where things stand.

Reports and answers built on this store are model-derived research output. Not investment advice.

## Use

From `eigentliCH_Engines` (the family venv):

```
.venv\Scripts\python -m pip install --no-deps -e eigentlich      # once
cd eigentlich
..\.venv\Scripts\python -m eigentlich init-db                     # tables, triggers, views (idempotent)
..\.venv\Scripts\python -m eigentlich seed                        # content from the prototype, seed report
..\.venv\Scripts\python -m eigentlich migrate                     # prototype SQLite, reconciliation
..\.venv\Scripts\python -m eigentlich migrate --from <file.db>
..\.venv\Scripts\python -m eigentlich show                        # counts, content keys, binds, migrations
..\.venv\Scripts\python -m eigentlich align-content --curator <id|email>   # questionnaires aligned to the maps (EIG-44/45)
..\.venv\Scripts\python -m eigentlich revise-content --curator <id|email>  # intake v3 (EIG-53/58) and v4 (EIG-65), onboarding v3 (EIG-60/61)
..\.venv\Scripts\python -m eigentlich fix-encoding [--apply]      # UTF-8 read as a code page: list, then correct (EIG-46)
..\.venv\Scripts\python -m eigentlich lbs-backfill [--dry-run]    # one lbs run per client without a sheet (EIG-47)
..\.venv\Scripts\python -m eigentlich lbsim-backfill [--dry-run]  # one lbsim run per client whose newest sheet has none (EIG-67)
```

`align-content`, `revise-content` and `fix-encoding --apply` were run on the real store on 29.09.2026 (the
onboarding is at version 3, the intake at version 3, both saved by the owner's curator record;
`scoring_bind_check` 169 of 169 ok); `lbs-backfill` too, with lbs running (74 clients, 74 sheets). `lbs-backfill` refuses to start, and writes nothing, when lbs does
not answer. `lbsim-backfill` likewise refuses to start when lbsim does not answer. The intake's version 4 (lbsim's
earning-power questions, EIG-65) is saved by `revise-content` on the real store when the coordinator runs it.

`seed` exits 1 on a conflict (a source changed after someone edited the content); `migrate` exits 1 on
any reconciliation mismatch and writes nothing, and exits 0 with "already migrated" when the same file is
in the store. Reports are also written to `dev/reports/` (git-ignored).

The roles and the empty schema come from provisioning (`Instruments/store/provision.py`); PostgreSQL runs
in Docker at 127.0.0.1:5432.

## Configuration

`config.yaml` (committed, no passwords) < `config.local.yaml` (git-ignored, the dev passwords) <
`EIGENTLICH_DATABASE_URL` / `DATABASE_URL` < `EIGENTLICH_DB_HOST`, `_PORT`, `_NAME`, `_SCHEMA`, `_USER`,
`_PASSWORD`, `_SSLMODE`. The curator connection the tests use: `EIGENTLICH_CURATOR_USER`,
`EIGENTLICH_CURATOR_PASSWORD`. Sources: `EIGENTLICH_PROTOTYPE_ROOT`, `EIGENTLICH_MIGRATE_FROM`.
`EIGENTLICH_CONFIG` points at another config file.

## The repository (for the backend)

```python
from eigentlich.settings import load
from eigentlich.store import Store, Decision
from eigentlich import store

st = Store(load().database)
with st.session() as conn:                        # commits on success, rolls back on error
    c = store.create_client(conn, display_name="Anna", age_at_registration=41)
    q = store.content_current(conn, "questionnaire/onboarding")
    store.put_answer(conn, client_id=c["id"], questionnaire_key=q["key"], content_version=q["version"],
                     question_key="canton", value="Bern", answered_by_kind="client", answered_by_ref=c["id"])
    with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client",
                                                   question="Lohn erfassen?", choice="Ja")) as change:
        change.insert("position", client_id=c["id"], role="income", capital_type="human",
                      label="Anstellung", magnitude=96000.0, magnitude_unit="chf_per_year")
```

Clients and curators (`create_client`, `list_clients`, `update_client`, `create_curator`,
`revoke_curator`), consent, content (`content_current`, `content_version`, `content_keys`,
`content_history`, `save_content`), answers (`put_answer`, `get_answers`), threads (`open_thread`,
`add_message`, `close_thread`, `list_threads`, `thread_messages`), reports (`request_report`,
`withdraw_report_request`, `add_report`, `report_requests`), approvals (`request_approval`,
`approval_event`, `approvals`), parameter sets (`finalise_parameter_set`, `current_parameter_set`), engine
runs (`start_engine_run`, `mark_engine_run_running`, `finish_engine_run`), the plan (`plan_change`,
`plan_of`, `decisions_of`) and erasure (`erase_client`). Repository functions take an open connection and
never commit.

## The client app

`start.cmd` (or `..\.venv\Scripts\python -m eigentlich serve`) serves it at **http://127.0.0.1:8017/**, API
docs at `/docs`. It connects as role `eigentlich` to the configured schema and calls five engines over HTTP
(`config.yaml` `app:`; `EIGENTLICH_LBS_URL`, `_LBSIM_URL`, `_CHATBOT_URL`, `_REPORT_URL`, `_AGGREGATION_URL`,
`_APP_PORT` override; in Docker `EIGENTLICH_LBSIM_URL=http://lbsim:8014`):

| engine | call | for |
|---|---|---|
| lbs 8013 | `POST /run` (`lbs-request@1.0.0`, with `goals[].contribution_share` from lbs@1.2.0; `goals[].amount_basis` and `mandate.contribution_indexed` from lbs@1.3.0, sent only when stated), `GET /artefacts/{id}` | the role grid and the goals in both bases; every report |
| lbsim 8014 | `POST /run` (`lbsim-request@1.0.0`), `GET /outlook`, `GET /runs/{id}`, `POST /optimise` (`lbsim-optimise@1.0.0`) | the outlook: earning power, income paths, findings, the paths per Regime, the plan calculation (EIG-66) |
| chatbot 8016 | `POST /answer` (`chat-request@1.0.0`) | spark7's draft answer in a thread |
| report 8015 | `POST /report` (`report-request@1.0.0`; a revision with `revision_of`, `revision_note`: report 1.2.0; `basis: real`: report 1.3.0; `lbsim` sources, one per kind: report 1.4.0) | reports, updates, revisions |
| aggregation 8004 | `GET /scenarios` | which pcp runs are on a scenario Regime, for a report with an allocation (EIG-63) |

Every call is an `engine_run`. An engine that is down is named on the page; the question or request stays
open and can be tried again. Nothing is made up in its place.

**No sign-in** (owner decision 9.1). The start page lists the clients (`client_overview`) and offers "new
client"; the chosen client is kept for the browser window and named in every route. Screens: the picker; the
client's home (what is open, the role grid from the lbs sheet with the balance sheet as a graph and the four
capitals per adult, EIG-70 and EIG-71, what is answered); the onboarding and the
intake, rendered from the database content, one question at a time or by section, each answer stored at once
naming its content version, resumable, and an edit mode that saves the client's wording change as a new
content version; the plan (household, positions in the role grid and whose they are, the client's or the
partner's, goals with their funding and their share of the yearly saving, the stated facts, the decision
list: every change through a decision, C-09); the outlook ("Aussichten", EIG-68: earning power per adult, the
income paths and the saving each goal needs at no return, the findings with their next steps and the question that
answers them, the three charts with the nominal / real switch, the Regimes' chances, the principal's expertise,
network and health over time (EIG-71), the plan calculation's figures for this period as "Was die Rechnung
annimmt"); questions (ask, spark7's draft with sources and unverified
numbers, curator answers, "ask the curator to approve"); reports (ask for a report or an update, read it,
ask for approval, see its state).

Every figure a page shows is rounded for display (EIG-73, the owner's rule of 03.10.2026 in `review/ROUNDING.md`) by
one formatter, `client/app/format.js`, and its Python twin `src/eigentlich/rounding.py` for the server's sentences (a
finding's figures): CHF amounts below 1 000 whole, to the nearest 100 below 100 000, to the nearest 1 000 below
1 000 000, then millions with two decimals ("CHF 1.35 Mio." / "CHF 1.35 m"); rates one decimal; chances whole
percent with "unter 1 %" and "über 99 %"; weights and shares whole percent, below 1 % one decimal, 0 as "–"; model
levels two decimals after their word; hours and counts whole. The client's own figures (a target, a position, an
answer) are shown as stated, and nothing typed into a field is rounded. The engines' values stay exact in the store
and in every payload.

Routes (JSON; `{c}` is the client id): `GET /health`, `GET /meta`; `GET|POST /api/clients`,
`GET|PATCH /api/clients/{c}`, `GET /api/clients/{c}/home`; `GET /api/clients/{c}/questionnaires/{onboarding|intake}`,
`PUT .../answers/{question}`, `POST .../edit`, `GET /api/questionnaires/{name}/history`,
`POST /api/clients/{c}/onboarding/complete`; `GET /api/clients/{c}/plan`, `GET .../decisions`,
`PUT .../household`, `PUT .../facts/{key}`, `POST .../positions`, `PATCH .../positions/{id}`, `POST .../positions/{id}/deactivate|reactivate`,
`POST .../goals`, `PATCH .../goals/{id}` (with `amount_basis`: `today` | `future`), `POST .../goals/{id}/deactivate|reactivate`;
`GET|POST /api/clients/{c}/outlook[?language=&basis=]` (POST takes `{"curator_id", "optimise": "now"}`, both
optional: the cockpit's buttons, EIG-66); `GET|POST /api/clients/{c}/balance-sheet[?language=de|en]` (POST takes an optional `{"curator_id": ...}`: the
cockpit's button, recorded as that curator's run, 403 unless the curator is in service); `GET|POST /api/clients/{c}/threads`, `GET .../threads/{id}`,
`POST .../threads/{id}/messages|draft|close`; `GET|POST /api/clients/{c}/approvals`,
`POST .../approvals/{id}/withdraw`; `GET|POST /api/clients/{c}/reports` (POST with `basis`: `nominal` | `real`, and `scenario` for a scenario Regime), `POST .../reports/{id}/produce[?revision=true]` (a revision takes `{"revision_note", "revision_of"}`), `POST .../withdraw`,
`GET /api/clients/{c}/report/{report}/html`. Slow calls run in the background; `?wait=true` runs them inline.

**lbs runs by itself** (EIG-47): every change of a client's plan or answers made in the app schedules a run,
debounced (`app.lbs_auto.debounce_s`, 5 s), one at a time per client; the home page shows the latest sheet,
its age, what is still missing in plain words with a link to where to add it (EIG-49), and a note while a
run is on its way. The AI is called MiniMind wherever the client reads (EIG-48); a drafted answer says
whether it rests on reviewed notes or is a general assessment (EIG-50). Everything on the page is in the
chosen language, including the server's refusals and the role names (the house's, from `reference/roles`,
EIG-56).

**lbsim runs after a new sheet** (EIG-66, EIG-67): when an lbs run makes a sheet the client's latest lbsim run is
not on, the app asks lbsim for it and the base-Regime Allocation of the current parameter set; the findings and
paths come back at once, the plan calculation runs in lbsim's background as its own `engine_run`, refreshed when
the app next asks. The home page shows the designated goal's chance in words, the top three steps and the plan's
state. A report draws on lbsim's findings and paths, and once the plan is there the app asks the update that carries
it (EIG-69).

**The household is stated whole** (EIG-53): the intake's partner section (section 21) gives lbs the partner's
age, salary, hours, AHV years and human capital; a position belongs to the client or the partner
(`position.owner`); each goal states its share of the yearly saving when more than one goal has an amount and a
date (`goal.contribution_share`, EIG-59). A stated fact wins over an answer, so answering a question that fills
a fact again restates the fact, and `PUT .../facts/{key}` restates one directly (EIG-54).

**The nominal and real view** (EIG-60 to EIG-64): each goal says whether its amount is in today's francs
("Ist der Betrag in heutigen Franken?", default ja, `goal.amount_basis`) and the yearly contribution whether it
rises with prices ("Steigt der Betrag mit der Teuerung?", default nein, an onboarding answer); both reach lbs only
when stated. Home, plan and reports carry a nominal / real switch, nominal by default, remembered per browser,
the basis always shown; in real the pages show lbs's real figures and a report is asked with `basis=real`. A
report takes the pcp run of the client's current parameter set on its base Regime, a scenario only when asked
for (EIG-63). The decision list reads in plain words, with the house's role names and Swiss figures (EIG-64).

**The balance sheet and the four capitals as graphs** (EIG-70 to EIG-72): on the home page "Ihre Lebensbilanz",
the assets by vessel and the human capital against the debts, the net worth and the goals' claims (the claims follow
the switch), and "Ihre vier Kapitale" per adult (wealth in francs, expertise, network and health as lbs's levels on
their own scale with words, never on a money axis); on the outlook the principal's capitals over time from lbsim's
`regimes[].capitals`. A withheld health (K3) never leaves the server and the page says so instead of drawing it.

The decisions behind the app are EIG-29 to EIG-72 in DECISIONS.md (the owner's of 29.09.2026: EIG-44 to
EIG-52; the fix round after the use cases: EIG-53 to EIG-59; the nominal and real view: EIG-60 to EIG-64; lbsim:
EIG-65 to EIG-69; the graphs: EIG-70 to EIG-72).

## Tests

```
..\.venv\Scripts\python -m pytest                 # against the real server, throwaway schemas t_<hex>
set EIGENTLICH_LIVE=1 && ..\.venv\Scripts\python -m pytest tests\test_app_live.py   # against the running engines
..\.venv\Scripts\python dev\verify_regressions.py  # each regression test fails with its fix reverted
..\.venv\Scripts\python dev\schema_catalogue.py    # regenerate SCHEMA.md from dev/SCHEMA.head.md + live schema
```

The suite needs the server; unreachable, it stops with the remedy rather than skipping. It never writes
the real schema; it reads it to check ownership, comments, the REAL sweep and the curator's privileges,
so run `init-db` once first.

## Layout

```
src/eigentlich/   settings.py  store.py  schema.sql  seed.py  intake.py  migrate.py  __main__.py
                  app: appsettings.py  api.py  service.py  clients.py  contracts.py  inputs.py
                       grounding.py  questionnaires.py  gaps.py
                  29.09.2026: alignment.py (content aligned to the maps, the intake's partner section, the
                              onboarding's two basis questions, the intake's earning-power questions)  encoding.py
                              (code-page repair)  decisions.py (a decision in plain words)  outlook.py (lbsim's
                              outlook as the page reads it)
                  03.10.2026: pictures.py (the balance sheet and the four capitals)  rounding.py (display rounding, the
                              twin of client/app/format.js)
client/           the browser app: index.html  app/ (api, basis, charts, dom, format, i18n, main)  surfaces/ (with outlook)  style/
start.cmd         the app on 8017
tests/            one module per concern; conftest.py (throwaway schemas, curator grants), world.py;
                  test_app_*.py and appkit.py (stand-in engines; lbsim on its frozen samples in fixtures/lbsim)
dev/              verify_regressions.py [name]  schema_catalogue.py  SCHEMA.head.md  build_use_cases.py
                  reports/ (git-ignored)
docs/             USE_CASES.md (the 20 demonstration clients)  knowledge-drafts/
```
