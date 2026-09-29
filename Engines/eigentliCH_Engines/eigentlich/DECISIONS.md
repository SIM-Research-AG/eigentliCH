# eigentlich store: decisions

Each decision holds as written. Owner decisions from Build Instruction section 9.1 (28.09.2026) are cited
as such; the rest were taken in building the store and can be revisited.

### EIG-01 · One schema, two writers, no DELETE for the cockpit
Schema `eigentlich`, owned by role `eigentlich`; the backend writes as `eigentlich`, the cockpit directly as
`curator` (owner decision, the stated exception to the one-writer rule). The curator holds SELECT, INSERT,
UPDATE and never DELETE, so every cockpit action is designed as an insert or an allowed update: a new
version, a new event, a new message, a set-once column. No engine reads the schema.

### EIG-02 · No sign-in, so no credentials anywhere
Owner decision. `client` and `curator` hold no password, session or login fields; the prototype's
`credentials` and `sessions` are not migrated. The client picker is the view `client_overview`. The
cockpit names the acting curator in each write, and the database checks that curator is in service.
The prototype curator's `active` flag is not carried: "in service" is `revoked_at IS NULL` (A161), and the
migration fails on a source curator that is inactive but not revoked.

### EIG-03 · Text ids, kept on migration
Ids are 32-character uuid hex, as the prototype. Migrated rows keep their ids, so links need no mapping;
`client.source_member_id` and `curator.source_curator_id` name the source row as well, and a CHECK ties
them to `created_by_kind = 'migration'`.

### EIG-04 · The rules live in the database
Owner decision: psycopg and one `schema.sql`, no ORM, no alembic. Because the cockpit writes directly, the
rules cannot live in Python. Three generic trigger functions carry most of them: `refuse_change`
(append-only), `guard_update` (per table: set-once columns, freely editable columns, everything else
immutable, DELETE refused) and `check_actor` (a client ref names a client; a curator ref names a curator in
service). Every function is created with `SET search_path FROM CURRENT`, so a trigger fired from a cockpit
session with any search_path resolves this schema's tables and nothing else.

### EIG-05 · C-09 enforced by PostgreSQL
The prototype could hold C-09 only for writes through SQLAlchemy; PostgreSQL can hold it for every write.
`decision.txid` is forced to `txid_current()` on insert. Every INSERT or UPDATE of a plan row (`household`,
`household_member`, `position`, `goal`, `client_fact`) must name a decision written in the same
transaction, of the same client where the row has one (not for household rows: a partner's member row is
stated by the other client). The row is linked to its decision automatically (`decision_<table>`), a
decision can be linked only in its own transaction, and `id`, `created_at` and `client_id` of a plan row
cannot change. `goal_funding` and `goal_owner` have no decision column; a change to them needs a
`decision_goal` link from the current transaction. Two layers refuse a stale decision (the row guard and
the link guard); `dev/verify_regressions.py` reverts both to show the test guards.

### EIG-06 · A plan row names the decision that last wrote it
`decision_id` on a plan row is the latest decision; the link tables keep every decision that ever covered
it. The migration sets it to the latest decision (by `created_at`, then id) the source links the row to;
every source plan row is linked to at least one decision, so nothing is imputed.

### EIG-07 · Deactivate, close or supersede; never delete
Plan rows are never deleted. `goal`, `goal_funding` and `goal_owner` gained an `active` flag (`position`
had one); households close (`closed_on`), members leave (`left_on`), facts are superseded.

### EIG-08 · One versioned content table
`content_record (key, version)` holds questionnaires, scoring maps, reference content and knowledge notes,
with kind and key prefix tied by CHECK (`questionnaire/`, `scoring/`, `reference/`, `knowledge/`). A
trigger assigns max+1 under a per-key advisory lock (concurrent saves queue; tested with twelve at once),
refuses a caller-chosen version that is not next, a change of kind and repeated question keys. Every save
is a new version, identical or not, because the owner asked that every save be recorded with who and when.
`save_content()` is the documented call. The body-shape CHECK is wrapped in `coalesce(..., false)`: a
missing member made it NULL, and a NULL CHECK passes (found by test).

### EIG-09 · The intake form becomes a questionnaire like the onboarding
The onboarding file is stored verbatim. The intake is extracted from `intake.html`: its `FIELDS` and
`REPEATS` constants and its HTML (section titles and ledes, labels, why-texts, units, placeholders, select
options) must agree field for field or extraction fails. Types map as select `choice`, number `number`,
text `text`, textarea `text` with `multiline: true`; the property group is one `repeat` question with
`fields`. Section keys are the form's own numbers (`01` to `20`). Intake questions are `required: false`,
as the form requires nothing. Result: `intake@1.1`, 20 sections, 113 questions.

### EIG-10 · Scoring maps carry explicit binds, checked live
A scoring map is `{map, binds, source}` with the prototype file verbatim as `map`. Binds are declared in
`seed.py` (`BINDS`) using the question keys the prototype's services read each map with. A bind names the
map string and the option value it stands for, which are equal except where the map uses its own names
(`responsibility.tiers`, bound through each tier's `label.de`). The view `scoring_bind_check` checks every
bind against the current questionnaires, so a curator's questionnaire edit shows its effect at once. The
seed report lists every mismatch and every string-like key that no bind covers. Mismatches are reported,
never fixed silently: 19 of 169 today (section "Open points" in HANDOVER.md).

### EIG-11 · Knowledge notes as front matter plus Markdown
`knowledge/<id>`: `{front_matter, markdown, source}`, id checked against the file name, dates as ISO text.
`README.md` explains the format and is not a note. The approval gate stays where it was
(`front_matter.approved`).

### EIG-12 · The seed never overwrites an edit
Per key: same body as the latest seed version, nothing written; source changed and nobody edited since,
a new seed version; source changed after a client or curator saved, a conflict: reported, not written,
exit code 1.

### EIG-13 · Answers
One current answer per client, questionnaire and question (partial unique index); superseding is the only
update; `put_answer` serialises per client with a row lock, so concurrent answers leave exactly one
current (tested with eight). An answer names the version it answered and the question must exist there.
The row's class is raised to the question's declared class, which is how `health` answers are K3. Migrated
onboarding answers name `questionnaire/onboarding` version 1 (all 547 carry `onb2@0.1.0`), with
`answered_by_kind = 'migration'` and ref `onboarding_answers:<id>`, since the source does not record who
typed them; 60 health answers were raised from K2 to K3.

### EIG-14 · Approval only on request, one terminal event
Owner decision: approval only on the client's request, for reports, updates and AI-drafted answers.
`approval_request` is unique per item and its trigger checks the item exists, is the client's and has the
named kind (an `answer` must be a spark7 message). `approval_event` is unique per request because every
event (`approved`, `revision_sent`, `withdrawn`) is terminal; who may write which event is a CHECK plus a
trigger. A report revision is a new report row for the same request; an answer revision is a curator
message in the same thread.

### EIG-15 · Threads with a derived state
State (`awaiting_answer`, `answered`, `closed`) is derived in `thread_state`, not stored, so it cannot
disagree with the messages. Closing is set-once and terminal. A spark7 message must carry `model` and
`chatbot_artefact_id`; a human message may carry neither. A client writes only in their own threads.

### EIG-16 · Report requests
A request is withdrawn once, and only while no report exists; a withdrawn request takes no report. Reports
are append-only and carry the report, LBS and Allocation artefact ids.

### EIG-17 · Parameter sets as a linear chain
One root per client and engine and each set superseded at most once, both by unique index, so concurrent
finalisations cannot fork the chain; the current set is the one nobody supersedes. `finalised_by` must be
a curator in service.

### EIG-18 · Engine runs move forward only
`queued`, `running`, `succeeded` or `failed`; a finished run is immutable; only the outcome columns change.

### EIG-19 · Write order is an identity column
`seq` on `answer`, `decision`, `thread_message` and `report`. Rows written in one transaction share
`now()`, which made "the last message" ambiguous (found by test).

### EIG-20 · Data classes per row, with floors
Every table has `data_class smallint` with a CHECK floor: content and the migration record K0 and up;
client, curator, consent K1 and up; plan, decisions, threads, reports K2 and up; `client_fact` K1 to K3 per
row as the source classed each fact; `submission` exactly K3. Nothing logs values.

### EIG-21 · Erasure is the only deletion, bounded twice
R-231. The owning role may delete one client's rows while `eigentlich.erasure_client` names that client
in the transaction; the guards check both the client and that the current user owns the schema, so the
curator cannot erase. `store.erase_client` removes the client's rows, including their decisions; a
household shared with another client stays, with the erased member's row redacted and re-attributed to a
`system` decision of the remaining client (C-09 still holds); curator sessions keep their audit with the
client reference nulled; content the client saved keeps its versions with `saved_by_ref` redacted. This
deletes decisions where the prototype (A61) redacted them; see HANDOVER open points.

### EIG-22 · Migration in one transaction, with nothing stood down
All rows go in inside one transaction, so migrated decisions carry the migration's transaction id and the
C-09 trigger accepts the plan rows under them as it accepts any plan change; there is no bypass switch.
`decision.origin = 'migration'` and `migration_run.txid` record it. The run is idempotent (same file, all
ids present: "already migrated", nothing written) or refuses a target whose migrated tables hold any row.
Every source table is classified, migrated or skipped with a reason; an unknown table fails the run. The
source is opened read-only, its SHA-256 checked before and after, its alembic head (`b81f4c2e9a37`)
asserted and its foreign keys checked. Submission payloads must hash to their stored `content_hash` before
and after the round trip through jsonb. Values rename `member` to `client` (decision author, stated_by).
Source timestamps are naive UTC (the prototype's `DateTime` coerces to UTC) and are read as such.

### EIG-23 · What is not migrated
`credentials`, `sessions`, `access_grants` (sign-in removed), `action_items` (derived), `vault_items` and
`decision_vault_items` (vault out of scope), `plan_versions` (not in this store; 0 rows), `engine_runs`
(prototype calls; 0 rows), `assumption_sets` (published assumptions, not client data), learning, community
and market-place tables, `alembic_version` (recorded in `migration_run`). Each appears in the
reconciliation with its count and reason.

### EIG-24 · Submissions stored as jsonb
The owner asked for jsonb for JSON. The prototype's `content_hash` is SHA-256 of the canonical JSON of the
parsed payload, not of file bytes, so jsonb loses nothing the hash covers; the migration proves it per row.

### EIG-25 · Seed reads the prototype in place
The seed reads `Prototype/client/content`, `client/intake.html` and `content/knowledge` read-only rather
than vendoring copies, and records each file's SHA-256 in the version's `note`.

### EIG-26 · Tests run on throwaway schemas with the real grants
Each test module creates `t_<hex>` as role `eigentlich`, grants the curator there exactly what provisioning
grants on `eigentlich`, and drops it, asserting it dropped only that schema and its default privileges.
The real schema is read only by tests (ownership, REAL sweep, comments, curator privileges).
`dev/verify_regressions.py` reverts each database-level fix in a throwaway schema and shows its test fail.

### EIG-27 · Decisions carry their origin
`decision.origin` is `live` or `migration`; a live decision must name a client. The five prototype
decisions already redacted by erasure (client NULL) are migrated as they are.

### EIG-28 · Consent purposes are checked for shape only
`consent.purpose` must match `^[a-z0-9_]+$`; the prototype's registry of purposes (`consent.py`) is not
replicated here. All 60 migrated consents have purpose `datenbearbeitung`, document version `dsg@2026-01`.

## The client app (28.09.2026)

### EIG-29 · The app lives in the store's package, served on 8017
`api.py` (routing only), `service.py` (orchestration), `clients.py` (engine callers), `contracts.py` (the
engines' contracts, mirrored), `inputs.py` (the lbs request), `grounding.py` (note retrieval),
`questionnaires.py` (next question, answer checks, content edits), `appsettings.py` (the `app:` section of
`config.yaml`). The browser app is `client/`: plain ES modules, no build step, German first with an English
switch, `tokens.css` copied from the prototype verbatim, served by the app at `/`. `python -m eigentlich serve`;
port 8017, and `load_app` refuses 8000 to 8016. The package now depends on fastapi, uvicorn, pydantic, httpx
(the family venv already holds them).

### EIG-30 · No sign-in: the client travels in the path
Owner decision. The start page lists `client_overview` and offers "new client"; the picked client is kept in
`sessionStorage` for that browser window and named in every route (`/api/clients/{id}/...`). Every row reached
through a route is checked to be that client's (404 otherwise). No route reads a token, cookie or password;
the OpenAPI document has no security scheme (tested). `#/client/<id>/<page>` picks a client by link, so the
cockpit can link to a client's view.

### EIG-31 · Engine calls never hold a transaction, and never invent a result
Each call is an `engine_run` (queued, running, committed), then the HTTP call, then the outcome and the rows
it produces in a second transaction. Down, timed out or 5xx is `EngineUnavailable` (503 to the page); a 4xx
or a response that breaks its mirror is `EngineRefused` (502). Either way the run is `failed` with the
reason, the question or report request stays open and "try again" is offered. The mirrors in `contracts.py`
are strict outbound (a request the app builds is refused before it is sent) and partial inbound.

### EIG-32 · The lbs request from the store
`inputs.py` maps the client's current household, positions, active goals, facts and answers onto
`lbs-request@1.0.0` (the module docstring lists every field's source). `client_ref` is the client id, never
the name. The client is `p1` and principal; age is `age_at_registration` (no birth date is stored).
Precedence: a stated `client_fact`, then the onboarding answer, then the intake answer. `vessel` is
`position.tags.vessel` when the client stated it, else the prototype's label rule; a goal's kind comes from
its occupancy, template or name words (the rules lbs's golden builder applies). An answer that does not fit
the contract is left out and listed (`dropped`), never coerced. The mandate goal is the first active goal
with an amount and a date, preferring one that is not a retirement goal; the yearly contribution is asked
nowhere yet and is left for lbs to name as a gap. Checked on 28.09.2026: all 83 migrated clients produce a
request lbs accepts and a sheet it builds.

### EIG-33 · Grounding: approved notes by keyword overlap
Only `knowledge/*` with `front_matter.approved` true. The question is folded (umlauts, case), split into
words of three letters or more, stop words removed; each word scores 3 in the note's title or id, 2 in its
topic and 1 in its body (a prefix match of five letters or more counts). Notes scoring under 2 are dropped;
the best 4 are sent, ties broken by key, each cut at a paragraph boundary to 5800 characters (the chatbot
refuses above 6000). The grounding id is `<note id>.v<version>` (the chatbot's ids admit no slash). The
stored spark7 message's `sources` are the notes the answer cited, with key and version. Client facts sent:
age, canton and civil status, nothing else. History: the thread's last six turns, each cut to 2000 characters.

### EIG-34 · Drafts and reports run as jobs; the page polls
A spark7 draft or a report can take minutes. They run on a thread pool of eight; the job's state (running,
or failed with the reason) is kept in memory and shown, while the truth is the store's. `?wait=true` runs
inline (tests, the cockpit). Written once: a draft is dropped if a spark7 message already answers that
client message (checked under the thread's row lock); a report is dropped if the request got one meanwhile
(request row lock), unless it is a revision. After a restart a failed job's reason is gone; the request is
still open and can be retried.

### EIG-35 · Goal templates in code until they are content
The onboarding's `goal_template` question needs templates the store does not hold; the prototype's nine
(`services/goals.py`, names verbatim) are in `questionnaires.GOAL_TEMPLATES`. A `reference/goal-templates`
record (`{templates: [...]}`), when someone adds one, replaces them without a code change.

### EIG-36 · A client's content edit is a one-question patch on the current version
Owner decision: client and curator both edit the shared questionnaires. The edit mode sends one question's
`question`, `why`, `placeholder` ({de, en}) and, for a choice, `options`, with the version it was read from.
The app takes the key's advisory lock (the one the version trigger takes), refuses with 409 when a newer
version exists ("reload"), applies the patch and saves with `save_content` as `client` with the client id.
Key, type, order, section and `fills` are not editable from the app: answers and scoring binds refer to them.
Answers already given keep naming the version they answered; the next answer names the new one.

### EIG-37 · Fix: a message body is text
`store._adapt` adapted every column named `body` as JSON, which is right for `content_record` and
`parameter_set` and wrong for `thread_message.body` (text): every message was stored with JSON quotes. No
row was affected (the real schema holds no messages). `_adapt` now knows that `(thread_message, body)` is
text; regression test `test_a_message_body_is_stored_as_text`. The cockpit, writing SQL directly, was never
affected.

### EIG-38 · Completing the onboarding is the prototype's `complete`
One transaction: the household from `household_composition` (unless the client has one) under its own
decision, then the first position (`employment_*`), the first goal (`first_goal`, owned by the client's
member row) and every `member_fact` answer as a `client_fact` with the question's class, under a second
decision. Refused before `employment_position` is answered, and refused a second time (409).

### EIG-39 · A new household composition closes the old one
`PUT /household` closes the current household (`closed_on`) and writes a successor
(`succeeds_household_id`) under one decision; a member who is another client keeps their record when their
label is kept. Members are listed client first, then adults, then dependants, by label: rows written in one
transaction share `created_at` and the table has no write-order column.

### EIG-40 · A chatbot refusal is spark7's answer
When the chatbot refuses (no grounding, not covered) its fixed text is stored as the spark7 message, with
`model` `none (<refusal code>)` when no model was called (the column is required for spark7) and no sources.
Unverified numbers are stored and shown as a warning on the message.

### EIG-41 · Approval only on request, the kind derived by the app
The client says "answer" or "report"; for a report the app reads the kind (`report` or `update`) from its
request. A request exists only when the client pressed "ask the curator to approve"; one per item (a second
is 409). The cockpit writes `approved` or `revision_sent` as `curator`; for a report revision it asks the app
for a new report (`POST .../reports/{id}/produce?revision=true`) and names that row.

### EIG-42 · The report is shown, never run
The report engine's HTML is served from `/api/clients/{id}/report/{report}/html` with
`Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:` and shown in an
`<iframe sandbox>`: no script, no fetch, no same-origin access.

### EIG-43 · No change to the schema (superseded for one column by EIG-50)
The app needed no new table, view or function; `schema.sql` and SCHEMA.md are unchanged. Job state lives in
memory (EIG-34) rather than in a new table.

## Owner decisions of 29.09.2026

### EIG-44 · The questionnaires are aligned to the scoring maps, never the maps to them
Owner decision. The 19 binds that did not meet their question (EIG-10) are resolved by new content versions
of the questionnaires, saved by the owner's curator record (`Nicolas`, `saved_by_kind = 'curator'`) with the
note "aligned to scoring maps, owner 29.09.2026": `questionnaire/intake` version 2 (`intake@1.2`) and
`questionnaire/onboarding` version 2 (`onb2@0.2.0`, EIG-45). The maps stay at version 1. `scoring_bind_check`
now shows 169 of 169 ok, in the real store and in the test that seeds and aligns a throwaway schema.
`eigentlich.alignment` holds the changes as patches on the current version (a wording edit made since is
kept; a second run writes nothing); `python -m eigentlich align-content --curator <id or email>` applies them.
The changes:
* `goal_confidence` (3 binds): the four options the map scores, as the original questionnaire (onb 0.1.3)
  worded them: `70 % — ich kann nachjustieren`, `80 %`, `90 % — es muss halten`, `95 % — kein Spielraum`;
  the offline form's `fest` and `eine Idee` (which the map does not score) stay valid, not offered. The
  question is the original's: "Falls Sie später eine Risikoprüfung wünschen: wie sicher müsste Ihr
  wichtigstes Ziel dann erreicht werden?"
* `education_hours` (5): a new choice question in section 16 after `education_recent` (order 93.5), with the
  map's bands `kaum welche`, `1–2`, `3–5`, `5–10`, `mehr als 10`; wording carried from onb 0.1.3. It sits
  beside the number question `hours_learning`, which the map does not read.
* `esg_exclusions` (7): `multi_choice` over the seven exclusions the map offers, instead of free text; the
  why-text no longer asks for commas. An answer to version 1 (free text) is still read, split at commas.
* `health` (1): option `1` added, not offered: it is what the onboarding's numeric health answer gives for
  full health; `1 — sehr gut` stays the offered option.
* `rest_hours` (3): offered are the map's five non-overlapping bands `kaum welche`, `5–10`, `10–20`, `20–30`,
  `mehr als 30` (as onb 0.1.3); the offline form's `unter 10` and `über 30` stay valid, not offered.

Two additions to the content format carry this (SCHEMA.md section 6): the type `multi_choice` (the answer is
the list of chosen values) and `"offered": false` on an option (a valid answer and bind target that the app
does not offer, so two vocabularies the maps score need not show as overlapping bands). An edit through the
app keeps an option's `offered: false`.

### EIG-45 · The yearly contribution is asked, and is the mandate's
Owner decision. The onboarding (version 2) asks "Wie viel können Sie pro Jahr zur Seite legen?" / "How much
can you put aside each year?" (`annual_contribution`, number, `chf_per_year`, min 0, not required, after every
other question as the five_keys were). `inputs.py` sends it as `mandate.annual_contribution` of
`lbs-request@1.0.0` (a stated fact of that key would win, as everywhere; a stated 0 is 0; a negative answer is
dropped and named). Without a mandate goal (a goal with an amount and a date) it has nothing to attach to and
is named in `dropped`. lbs reads it as the household's yearly saving toward the goal (LBS-25), which gives a
required return and a target curve.

### EIG-46 · The mis-decoded texts of the migration are corrected
Owner decision. UTF-8 read as a code page during an earlier import (`├⌐` for `é`, `├╝` for `ü`, `├ñ` for `ä`)
is found and reversed by `eigentlich.encoding`: a group of characters is re-encoded with CP437, CP850 or
CP1252 and decoded as UTF-8, and accepted only when it gives exactly one Latin letter or punctuation mark, so
correct text is never touched. Found in the real store on 29.09.2026, all corrected (`python -m eigentlich
fix-encoding --apply`): `client.display_name` "C├⌐line B." to "Céline B." (a direct update by the owning
role); her `household_member.label` (through `store.plan_change` under a system decision "encoding
correction, owner 29.09.2026", C-09); and the `reasoning` of seven migrated decisions (CélineBornand,
ElsbethHürlimann, MonikaBrülhart, SilviaRüegg, SimonNäf, YvesDelacrétaz, ChristophLüthi), which are
append-only: each got a correcting decision (`corrects_id`) with the corrected text. Nothing was found in
positions, goals, facts, answers, thread texts or submissions. Thread messages and submissions have no
correction path (append-only, no `corrects_id`) and would be listed, not changed. A test guards the pattern
and a test reads the real store and fails on any hit.

### EIG-47 · lbs runs by itself after a change, and the cockpit's button names its curator
Owner decision: both, automatic in the app and a button in the cockpit (the cockpit's). Every change of a
client's plan or answers made through the app (an answer, the onboarding's completion, the household, a
position, a goal) schedules a balance-sheet run for that client, and a household change for every client of
the household (EIG-39). Debounced (`app.lbs_auto.debounce_s`, 5 s): a new change within the wait restarts
it. At most one run per client at a time: a change during a run makes one more run after it, not a second
run beside it. Each run is an `engine_run` as every other, `requested_by_kind = 'system'`,
`requested_by_ref = 'eigentlich-app:auto'`. Opening the home page schedules one run when the plan or the
answers changed after the client's last lbs run of any outcome (a change the app did not see, the
cockpit's), so a down lbs leaves one failed run, not a loop. The home page shows the latest sheet, its age
("vor 3 Minuten") and a note while a run is on its way, and fetches the new sheet when it is done.

`python -m eigentlich lbs-backfill` runs lbs once for every client without a successful run, one after the
other (`requested_by_ref = 'eigentlich-app:lbs-backfill'`); it refuses to start when lbs does not answer its
health probe, so nothing is written then.

`POST /api/clients/{id}/balance-sheet` takes an optional body `{"curator_id": ...}` (the cockpit's button):
the curator must exist and be in service (403 otherwise, and nothing runs), and the run is recorded as
`requested_by_kind = 'curator'` with that id; an empty body is the client's, as before. No schema change: the
`engine_run` columns already took all three kinds. The job state stays in memory (EIG-34): after a restart a
pending run is gone, and the next home visit schedules it again.

### EIG-48 · The AI is called MiniMind
Owner decision: spark7 is the server, MiniMind the AI. Everything the client reads says MiniMind: the author
of a drafted answer ("MiniMind (Entwurf)"), the notes on the threads page, the engine named in a refusal. The
store keeps `author_kind = 'spark7'` (the cockpit reads it): a display mapping in `client/app/i18n.js`, no
schema change, no configuration. The technical model name is no longer shown to the client (it stays in
`thread_message.model` for the cockpit).

### EIG-49 · What the balance sheet is missing, in the client's words and language
Owner feedback. lbs names a gap by section, input and reason, with ids (`property.<goal id>`,
`the_goal_does_not_say_whether_the_member_will_live_in_it`). `eigentlich.gaps` turns each into a key without
ids, the name of the object from the store (the goal's name, the position's label, the person's label), where
the client can supply it (plan, first conversation, questionnaire) and a group: "Was noch fehlt" (the client
can act, with a link) or "Was wir noch vorbereiten" (a table not yet released, another model's figure, an
assumption nobody has published). `gaps.KNOWN` covers every input lbs's `engine.py` can name on 29.09.2026
(45 keys); a test reads that file again and fails on a new one, and another checks a German and an English
sentence for each. An unknown key still reads, as its kind's sentence, never the key.

The same pass over the whole client UI: refusals from the server (English, for the cockpit and the logs) are
recognised in the browser and said in the chosen language, with a plain sentence per status for anything
else and the server's text in the browser console only; a failed draft or report names the engine in words;
no artefact id, lbs key or English engine notice reaches a page (the sheet's "as of" line, the report list,
the gap list, the footnote); the English table carries every key the German one does.

### EIG-50 · Schema, additive: `thread_message.basis`
The chatbot now answers from general knowledge when no note covers a question, marked as such, and says so in
the optional `basis` of `chat-answer@1.0.0` (grounded, general, mixed; CHB-18). The app stores it in a new
nullable column `thread_message.basis` with a CHECK (only on spark7 messages, only those three values), added
by `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and a guarded `ADD CONSTRAINT` in `schema.sql`; no existing
table, view or function changed; `init-db` applied it to the real schema on 29.09.2026. The thread shows it
under the answer ("Allgemeine Einschätzung: keine geprüfte Notiz deckt diese Frage ab."). The mirror in
`contracts.py` reads `basis` and `model_display_name`. This supersedes EIG-43 (no schema change) for this one
column.

### EIG-51 · Grounding reaches further, and a question about the asker carries the sheet
Owner request: "was muss ich machen so dass ich eine persönliche Wachstumsstrategie habe, also mehr
einkommen generieren kann" got no note and a refusal. `grounding.py` now stems German inflections, splits a
long compound where a part is a word of the notes, applies the synonym groups of `reference/search-aliases`
(one term per group, as that record requires), reads a note's topic tag and its «Fragen, die dieser Text
beantwortet» list at weight 2, and when no note reaches `min_score` sends the best `fallback_notes` (2) at or
above `floor` (1) rather than none; a question that matches nothing at all still gets none. When the question
is about the asker (a first-person word), the client facts sent include what the latest lbs sheet says: the
human-capital scores E, N and H, the household income and the household's size, each with its source. The
corpus holds no note on growing one's income; the question now gets the nearest notes (four on 29.09.2026)
and the chatbot's general assessment, marked as such.

### EIG-52 · Confirmed as built (owner, 29.09.2026)
* Answers with unverified numbers are shown, flagged (EIG-40), not withheld.
* All 83 migrated clients stay visible in the picker; none is archived.
* A household change applies to both partners (EIG-39).
* No consent step in the app for now.

## The fix round after the use cases (29.09.2026)

Found while building the 20 use cases (`docs/USE_CASES.md`, `dev/build_use_cases.py`), with two owner decisions.

### EIG-53 · The partner is stated to lbs
Thirteen of the twenty use-case households have two adults, and the app sent the partner with the kind only and
every position as the client's: lbs named the partner's E, N, H, age and income as gaps and left the household
income, affordability and the retirement verdict undetermined. Now:
* **The partner section.** `questionnaire/intake` version 3 (`intake@1.3`, saved by the owner's curator record
  `ac586536e6be42c68446c8f8f80e4242` with the note "partner section added, hours_learning dropped, owner
  29.09.2026"; `python -m eigentlich revise-content`) has section `21` after section 16: `partner_in_plan` (ja /
  nein) and, asked when it is `ja`, the partner's age, gross salary, working hours, missing AHV years,
  qualification and its year, years in the field, training, network and its reach, mandates, health (declared
  K3) and rest, on the scales of the client's own questions. The answers are the client's (no consent path for
  the partner exists; the health question says to answer only with the partner's agreement).
* **Whose position.** `position.owner` (`client`, `partner`, NULL = the client), an additive column with a CHECK.
  The plan page offers "Gehört zu" once the household names a partner; `POST` and `PATCH .../positions` take
  `owner`.
* **The mapping** (`inputs.py`): the partner is the first other adult of the household in `MEMBER_ORDER`; the
  partner section's answers become that person's age, `stated_gross_income`, human-capital answers and AHV
  years, unless `partner_in_plan` is `nein`. A position with owner `partner` is sent with the partner's person
  id, every other with `p1`. lbs reads the household income from income positions only, one per adult
  (LBS-14), so the partner's employment is a position the partner owns; the gross salary answer feeds the
  partner's pension projection. Nothing is read from another client's own record, not even for a couple with
  two records (Yasmin and Elio): each record states the other.
* **Where the client supplies it.** A gap about a person other than `p1` (E, N, H, age) points to the intake's
  partner section, not to the first conversation (`gaps.PARTNER_ACTIONS`).
* **The use cases.** Step `partners` of `dev/build_use_cases.py` answers the partner section and adds the
  partner's income and pension-fund balance (a stated 0 for the self-employed and for a pension drawn as an
  annuity) through the app's routes for the 13 clients; Peter's and Margrit's pensions, one position before,
  are split with the total kept. Each of the 20 sheets now names one gap only, earning power (lbsim's).

### EIG-54 · A fact is restated, by answering again or directly
A stated `client_fact` wins over an answer (EIG-32), and the app had no way to restate a fact, so a question
answered again after the first conversation never reached lbs (the use-case build wrote around it in the
store). Now `put_answer` restates the fact when the answered question fills one (`fills.entity =
member_fact`) and the client has a current fact of that key that says otherwise: a client decision "Die
festgehaltene Angabe «key» nachführen?" in the same transaction (C-09), the fact's class kept, the value kept
out of the decision's text (a K3 value stays out of a K2 row). Without a fact nothing is stated (the answer is
read anyway). `PUT /api/clients/{id}/facts/{key}` (`{value, reasoning}`) restates a fact directly: checked
against the onboarding question that fills the key when there is one (its options and range, its class), else
a plain key (`^[a-z0-9_]+$`, K2 unless the current fact says otherwise); the same value again changes nothing.
The plan page lists the stated facts ("Festgehaltene Angaben"), each with an edit button.

### EIG-55 · Grounding: numbers and stop words no longer score
The Vorsorgeauftrag and Erbrecht questions of the use cases got AHV notes: «000», «2030», «180» scored as terms,
so did inflected stop words («unseren», «müssen», «gehört») and words every note uses («Franken», «zwei»), and the
prefix rule let «vorsorgeauftrag» match every note that says «vorsorge». `grounding.words` now drops every
number and a German stop-word list with its inflected forms (pronouns, auxiliaries and modals in all persons,
number words, currency and time units); a note word that is a prefix of the question's word matches only when
what is left is an ending (three letters at most). The two questions now get «Vorsorgeauftrag und
Patientenverfügung» first and the two Erbrecht notes only. The growth question of EIG-51 still gets its
nearest notes.

### EIG-56 · The house's role names on every page
The home page's grid showed lbs's English names and definitions ("Growth", "A holding that pays a steady
distribution.") on a German page. The app now puts the names and definitions of `reference/roles` (the owner's
reviewed names: Wachstum and Wertsteigerung, Einkommen, Stabilisierung, Absicherung) into every grid cell it
serves, in the reader's language (`GET .../balance-sheet?language=`, the home page, the plan), never lbs's text
and never another language's; lbs's `gain` is the record's `growth`; a built-in copy of the house's names stands
in only when the record is missing. A role row names both kinds of capital's names once when they differ
("Wachstum · Wertsteigerung"). English appears only in the English UI.

### EIG-57 · A report revision is sent as one
`produce?revision=true` sent the same request again and the report engine answered from its cache: the revised
report was the first one's artefact. The report engine (1.2.0, REP-25) now takes `revision_of` (its id of the
report revised) and `revision_note` (the curator's remark, printed on the page, never read by the model), both
part of its request id. The app sends them on a revision: `revision_of` is the request's latest report, or the
one named by the body's `revision_of` (the app's report id), and the body's `revision_note` is the curator's
remark; a note without `revision=true` is refused. The two fields are left out of every other request, so a
report engine before 1.2.0 still takes those; a revision needs report 1.2.0 running.

### EIG-58 · `hours_learning` leaves the intake
Owner decision. The intake asked both `education_hours` (the band the scoring map reads) and `hours_learning` (a
number); `intake@1.3` keeps the band and drops the number. Answers given to earlier versions stay and are still
read (lbs's `hours_learning`); the onboarding still asks it.

### EIG-59 · Each goal's share of the yearly saving
Owner decision. With more than one goal with an amount and a date the plan asks each goal's share of the yearly
saving (0 to 100 % on the page), stored per goal as `goal.contribution_share` (0 to 1, an additive column with a
range CHECK) and sent as `goals[].contribution_share` (lbs@1.2.0, LBS-29; read from calibration 1.3.0 on). The
active goals' shares sum to at most 1: the app refuses a new goal, a change or a reactivation that would pass
it (422, naming the sum), under a row lock on the client; lbs refuses such a request too, so shares that pass 1
anyway (a direct write) are all left out and named in `dropped`. The mirror in `contracts.py` checks the owner
and the sum as lbs does. lbs's two new gap inputs (`contribution_share`, and `capital_type` for a human-capital
position funding a property goal) are in `gaps.KNOWN` with their sentences. The use cases' shares are in
`SHARES` of the build (retirement goals 0: they rest on the pension fund and the 3a); with them the required
returns rise where the saving is shared (docs/USE_CASES.md).
