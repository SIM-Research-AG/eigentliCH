# Engine 15: eigentliCH Report Engine (`report`)

Renders reports in which every figure traces back to an artefact id. The code owns every figure: each one is a
fact read from a published artefact (pcp's Allocation, lbs's Life Balance Sheet, lbsim's findings, paths and
plan) with the engine, the artefact id and the JSON path it was read from. Three charts are inline SVG in which
every printed value is a fact as well (REP-34). MiniMind, the house's AI (served by spark7), writes the connecting
sentences, one section at a time, and every number in them is checked against that section's facts. Readers
see no internal id and no upstream key: every lbs and pcp reason is a plain sentence in the report's language,
and persons and goals are named, not identified (REP-19, REP-20). If spark7 cannot be reached the report is
still produced, without prose, with a warning. Engine page:
https://app.notion.com/p/3e80ba72543f81279459c05a6644539a

> Model-derived research output. A report sets out a position from model results; it is not a recommendation.
> **Not investment advice.**

| | |
|---|---|
| Family | Communication |
| Module | `report` |
| Default port | 8015 (configurable) |
| Status | v1.4.0 (29.09.2026), calibration 1.0.0, prompt `report-prompt@1.1.0`; 418 tests and one opt-in live test |
| Consumes | `pcp-allocation@1.0.0` from `pcp` (8007, `GET /allocation/{id}`), `lbs-balance-sheet@1.0.0` from `lbs` (8013, `GET /artefacts/{id}`), `lbsim-findings@1.0.0`, `lbsim-paths@1.0.0` and `lbsim-plan@1.0.0` from `lbsim` (8014, `GET /artefacts/{id}`, typed by the id's prefix), a `ReportRequest` from the caller |
| Produces | `Report` (`report@1.0.0`), with the rendered HTML |
| Model | MiniMind (display name), served by spark7 (`https://spark7.minimind.ch`, vLLM), `google/gemma-4-31B-it-qat-w4a16-ct` |

## Run it

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\eigentliCH_Engines\engines\report
start.cmd                                    :: engine on 8015, test bench at http://127.0.0.1:8015/
```

First time: `..\..\.venv\Scripts\pip install --no-deps -e .`, the role and schema `report` (provisioned by
`python -m store.provision` in `Projects\Engines\Instruments`), the database password in `config.local.yaml`
(git-ignored) and the spark7 token in the family `.env` (`eigentliCH_Engines\.env`, git-ignored). A report needs
the engines it draws on running (`pcp` on 8007, `lbs` on 8013, `lbsim` on 8014). `python -m report probe` checks the model service.

```bash
python -m pytest              # 418 tests, real PostgreSQL, upstream doubles on frozen artefacts, spark7 stand-in
python -m pytest -m live -s   # one report with prose against the real spark7
```

## How a report is made

1. **The key** (REP-11): the request's content hash (client, kind, language, the source artefact ids, the
   previous report, the display facts, whether prose is wanted, for a revision the revised report and the
   curator's note, REP-25, and the basis when it is `real`, REP-27), the calibration hash, and when prose is wanted
   the model's name and host and the prompt version and hash. Upstream artefacts are content-addressed and
   append-only, so their ids stand for their content; their sha256 as received is in the provenance. A key
   already answered by a **complete** report is served from the store (REP-07).
2. **The sources** are read from their engines and validated against this engine's mirrors of their contracts.
   Refused, each with its reason: an artefact the engine does not have, one that breaks its contract, one about
   another client (lbs carries `client_ref`), an update whose previous report is missing or another client's,
   a revision whose revised report is missing or another client's, and a mix of bases (REP-28): a pcp
   Allocation of another basis than the request's (one without `basis` is nominal), a real request on an lbs
   sheet without its real view, an lbs figure whose stated basis is not the one asked, an update across bases.
   And for lbsim (REP-32): lbsim artefacts on another balance sheet than the lbs source (or on two sheets among
   themselves), paths on another Allocation than the pcp source, paths on other findings than the findings source,
   a plan on other paths or without its paths. Each refusal is one plain sentence naming what to ask instead.
3. **The facts.** One extractor per engine (`engine.EXTRACTORS`: mirror, path, extraction) turns the artefact
   into facts. A section lbs could not compute (`not_available`) becomes a stated fact, "not available:
   <reason>", never a number (REP-09); the reason is printed as a plain sentence in the report's language
   (REP-19), the fact's value keeps lbs's text. Counts and changes are derived by the code and name their derivation and
   every source they rest on. Display facts from the caller (such as a name) are cited to the request and shown
   in the header only; the model never sees them (REP-06). Display facts `person.<person_id>` and
   `goal.<goal_id>` name a person or a goal on the page instead of "Person 1" or "Ihr Wohneigentumsziel"
   (REP-20). The four roles carry the house's names from the content record `reference/roles`:
   Wertsteigerung (Wachstum on the human side), Einkommen, Stabilisierung, Absicherung; Gain (Growth), Income,
   Stabilisation, Protection (REP-24). lbsim's three artefacts are read together (`engine.extract_lbsim`,
   REP-33): earning power per adult (the model's level, the person's own statement, and which one the calculation
   uses), the income paths with their saving need at zero return, the findings with lbsim's own templates in the
   report's language (each figure a fact inside the sentence), the schedule, the rules not checked and the next
   questions, the chance per goal and Regime, the fan's ends, and the plan's figures for this period. While the
   plan runs (paths without a plan among the sources), the fact `lbsim.plan.state` says "wird berechnet" / "being
   calculated"; an update with the plan among its sources then carries it. With lbsim's findings present, lbs's
   note that earning power is another engine's is left out.
4. **The sections**, in a fixed order, left out when empty and numbered at render time (after `dossier.py`):
   changes (an update only), household, balance sheet, the roles of the balance sheet, income, human capital,
   earning power, income paths and the saving they need, pensions, retirement, home ownership, liquidity, risk
   profile, mandate proposal, the allocation, weight by role, the building blocks, how the allocation came about,
   the outlook, what the plan calculation shows, findings and next steps, what the report cannot say, sources.
   The five lbsim sections have no prose slot in this build.
5. **The prose** (REP-05). For each section with a slot in the calibration (balance sheet, income, pensions,
   retirement, home ownership, mandate proposal, allocation, roles, fit, changes) the model is given that
   section's facts, labels and printed values only, and asked for two or three sentences. A draft that
   recommends, names another currency, repeats the instruction, shouts, leaves the language, or is shorter than
   12 or longer than 140 words is rejected; then every number in it must match one of the section's facts (the
   renderings of `chatbot`'s check, plus percentage points for a change in a share). Two drafts at most. Only
   **verified** prose is printed; flagged prose stays in the artefact with its unverified numbers, the page
   says it was withheld.
6. **spark7 unavailable** (REP-07): the first failure stops the prose for the rest of the report (one timeout,
   not ten), the report is produced without prose, with a warning, `complete: false`. It is stored, and never
   served as the answer to a repeat: asking again tries again.
7. **The basis** (REP-27): nominal by default, or real on request. The lede states it ("Alle Beträge nominal." /
   "Alle Beträge in heutigen Franken (real).") and the basis word stands next to every return and goal figure.
   In real, the figures are lbs's own real ones (`mandate_proposal.views.real`, the retirement and property
   figures lbs 1.4.0 states real, `real_view.goals[].real`), never deflated here; what lbs gives only in
   nominal (a liquidity gap, a fixed contribution, the BVG projection) is shown so and marked nominal. A real
   report also states lbs's inflation assumption and whether the contribution rises with prices. lbsim's real
   views are read likewise (the saving need's `views.real`, the real bands, a goal's `real_chf`); a chance is one
   per goal and Regime in either view; a finding's figure lbsim states nominal stays nominal and is marked so; the
   plan's figures for this period are the same amount in both views and carry no mark.
8. **The page** (REP-13): self-contained HTML in the house style of the dossiers (the stylesheet of
   `dossier.py` verbatim), every value printed as `<span data-fact="{fact_id}">`, the notice in the footer; no id of any kind:
   the sources are named in words with their dates (REP-23), the ids stay in the artefact. The tests hold every page to this: outside fact elements, identifiers, the section
   index and the engine's notes it carries no number of two or more digits. A revision prints the curator's
   remark under the lede, as written, in the report's language (REP-25).
9. **The charts** (`report/charts.py`, REP-34): pure functions returning inline SVG, with `role="img"`, a
   `<title>` and a `<desc>` in words, a `viewBox`, the house colours, no `<script>`, no external reference, no web
   font, no `xmlns`. (1) The weights as horizontal bars, by role (section `roles`, the house's role names) and by
   building block (`positions`); (2) the Mandate's target against the reached return per state (`fit`), the 25
   states with "Krise" and "Boom" as words at the ends, the line of zero return, on the Allocation's basis; (3) the
   fan (`outlook`): the p05 to p95 and p25 to p75 bands and the median of the designated goal's measure (the plan's
   goal, else the mandate proposal's, else the first) from today to the goal's date, and the goal line, dashed and
   marked "umgerechnet" when the goal is set in the other basis (LBSIM-09). No tick labels: every printed value is
   a `<tspan data-fact>`, labelled directly, so the page's figure rule holds inside a chart. The plan's figures
   stand in a box headed with lbsim's framing, "Was die Rechnung annimmt: ..., keine Empfehlung" (owner,
   29.09.2026).

## Contracts

`ReportRequest` (`report-request@1.0.0`): `client_ref` (opaque), `kind` (`report` or `update`), `language`
(`de` or `en`), `sources` [{`engine` pcp, lbs or lbsim, `artefact_id`}] (at most one per engine and artefact
kind: an lbsim source is a findings `LSF-`, paths `LSP-` or plan `LSO-` artefact, REP-32),
`previous_report_id` (for an update, and only for one), `display_facts` [{`key`, `label`, `value`, `source`}]
(`name` titles the page; `person.<id>` and `goal.<id>` name a subject),
`prose` (default true), `calibration_version`, and since 1.2.0, optional (REP-25): `revision_of` (the `REP-...` id
of the report revised, this client's) and `revision_note` (the curator's remark, 1 to 4 000 characters, only with
`revision_of`), and since 1.3.0, optional (REP-27): `basis` (`nominal`, the default, or `real`; in the request id
only when `real`, so a request without it keeps its id).

`Report` (`report@1.0.0`, version unchanged): `artefact_id` (`REP-...`, the content hash), `client_ref`, `kind`,
`language`, `title` (the kind and the display fact `name`, never the `client_ref`), `previous_report_id`, `revision_of` and `revision_note` (optional, since 1.2.0), `basis` (since 1.3.0, `nominal`
when absent), `as_of` (the newest source date), `facts` [{`fact_id`, `section`, `label`,
`value`, `unit` (chf, chf_per_year, share, count, number, text, date, flag), `display`, `basis` (a return or goal
figure's, since 1.3.0), `sources` [{`engine`,
`artefact_id`, `contract_version`, `path` (JSON pointer)}], `derivation`, `previous`}], `sections` [{`key`,
`title`, `fact_ids`, `prose`, `prose_status` (verified, flagged, rejected, unavailable, not_requested, no_slot),
`prose_model`, `unverified_numbers`, `prose_attempts`, `prose_note`}], `complete`, `warnings`, `html`,
`provenance` (engine and contract versions, calibration and hash, idempotency key, request id, each source with
contract, sha256 and URL, the previous report, the model: service, host, model, prompt version and hash),
`notice`.

## Endpoints

Standard (Guide 2.1): `GET /health`, `/meta`, `/contracts`, `POST /run`, `GET /runs`, `/runs/{run_id}`,
`/artefacts/{artefact_id}`, `GET` and `PUT /calibration`. Engine specific:

| Method | Path | |
|---|---|---|
| POST | `/report` | `POST /run` returning the `Report` itself; 422 when it cannot report on the request as asked, 503 when an upstream engine is not there |
| GET | `/reports` | Stored reports, newest first, `?client_ref=` for one client |
| GET | `/reports/{artefact_id}/html` | The rendered report as a page |
| GET | `/model` | Live probe of the model service |
| GET | `/calibration/versions` | Calibrations, the active one marked |

## spark7

MiniMind is the name readers see (`model.display_name`, REP-21); spark7 is the server. The same client as
`chatbot`'s, as this engine's own copy (`src/report/spark7.py`, httpx only): one config
block, OpenAI-compatible routes, every call streamed (SSE, first byte within 120 s, 300 s in all), the Cloudflare
Access headers from variables named in the config, `Cache-Control: no-cache`, external providers and non-house
hosts refused at start, the echoed model checked, a warm-up tick every 240 s (`REPORT_WARMUP=0` turns it off).

**Live, 29.09.2026:** the prose case re-frozen with the translated sentences and generic subjects: seven
prose sections verified on the first draft; the live test passes. Again for engine 1.2.0 with the house's role
names: seven sections verified on the first draft, 26.8 s. **28.09.2026:** a German report on the frozen pcp and lbs artefacts: seven prose sections, all verified on
the first draft, 28.4 s for the whole report (about 4 s a section), `/v1/models` 0.43 s. Frozen twice, the same
report id both times: at temperature 0 with a seed, spark7 returned the same text.

## Model quality

* **Golden** (`golden/inputs`, `golden/reports`): sixteen reports over frozen artefacts (German and English, a
  property case, a liquidity case, an update, a revision, three in the real view's inputs: real in German and
  English and nominal on a sheet with both views, one with spark7's real prose, and six on lbsim's frozen samples
  of 29.09.2026: the outlook with all three charts in German and English, real in German and English on lbs and
  lbsim alone, the plan still running, and the update that includes it), reproduced exactly; the
  prose-free ones byte for byte on a fresh store. On every frozen report, **every figure is traced to an artefact
  id**: each fact's path is resolved in the frozen artefact it cites and must give the value the report states;
  a change must resolve in the previous report; a display fact in the request.
* **Vocabulary** (`tests/test_vocabulary.py`): the lbs and pcp sources are read and every key and reason
  they can emit must have its German and English sentence; no page, frozen or built on UUID-like ids, shows a
  32-hex id, a UUID or a snake_case key, and a German page shows no upstream English.
* **Extractors**: every pcp and lbs fact is read back from the path it cites, on all three lbs sheets and a
  constructed one that fills what they leave empty; no label carries a figure; a not-available section is
  stated and never a number.
* **Property tests**: the printed display of any figure verifies against it.
* **lbsim and the charts** (`tests/test_lbsim.py`): the request rule per engine and kind, the id of a request
  without lbsim sources, every refusal of REP-32 with its sentence, all three charts on the outlook pages, every
  `data-fact` inside an SVG a fact printing its display, no digit outside those, no `<script>` and no `http` inside
  an SVG, the goal line dashed in the other basis only, lbsim's real views read in real, the finding templates in
  the page's language, the plan's framing, "wird berechnet" and the update that carries the plan.
* **Boundary**: the role cannot write outside its schema and cannot read another engine's tables, owns its
  schema, no `REAL` column, every table commented, append-only triggers, one complete report per key enforced by
  the store; a concurrent burst of six identical requests against a real socket writes one report and asks for
  each section's prose once; two engine instances producing one key store one complete report.
* **Regression tests verified by reverting**: each of these was broken once and its test turned red: a report
  without prose is not cached, never another client's artefact, not-available not doubled, a not-available
  section never a number, flagged prose not printed, labels carry no figure, the per-key lock, the scale-word
  rule, a change cites both reports, the house's role names, a revision's fields in the key; and for the basis
  (`tests/test_basis.py`): the mix checks, the basis in the key and not in a nominal request's id, the update
  across bases, the basis word on the page, the header line, lbs's real figures read in real, lbs's stated basis
  checked.

## Layout

```
config.yaml            port, upstream URLs, the model service, store, active calibration
src/report/
  api.py               routing only
  contracts.py         ReportRequest, Report, Calibration; mirrors of pcp-allocation, lbs-balance-sheet and
                       lbsim-findings, -paths, -plan
  engine.py            extractors, formatting, sections, changes, prose prompt and checks (pure)
  vocabulary.py        lbs and pcp keys and reasons as plain sentences (de, en), subjects, page notes (pure)
  render.py            the HTML page (pure)
  charts.py            the three inline SVG charts (pure)
  spark7.py            the model client and the warm-up tick
  clients.py           the upstream engines
  calibration.py       seed calibration 1.0.0
  store.py, schema.sql PostgreSQL, schema report, append-only reports and calibrations
  service.py           orchestration
golden/                inputs (frozen artefacts) and reports
dev/                   freeze_inputs.py, build_golden.py, make_deploy.py
testbench/index.html   development only
tests/
```

Model-derived research output. Not investment advice.
