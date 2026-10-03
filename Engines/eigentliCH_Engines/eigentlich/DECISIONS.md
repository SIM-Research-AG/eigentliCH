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

## The nominal and real view (29.09.2026)

Built to `review/REAL_VIEW_INTERFACES.md` and the owner's decisions of 29.09.2026 (the design note "Design note:
nominal and real view"). Everything is additive and opt-in: no contract version moves, a request without the new
fields is byte for byte the request of before, and every stored row reads back unchanged. Everything is stored
nominal; the real figures are lbs's and the report engine's, derived at the point of use. App version 1.3.0.

### EIG-60 · A goal says whether its amount is in today's francs
Owner decision 7. "Ist der Betrag in heutigen Franken?" is a question of the onboarding's next version (`onb2@0.3.0`,
version 3 on the real store, saved by the owner's curator record `ac586536e6be42c68446c8f8f80e4242` with the note
"goal amount in today's francs and indexed contribution asked (nominal and real view), owner 29.09.2026";
`python -m eigentlich revise-content`, which now also runs `alignment.revise_basis`). It is `goal_amount_basis`, a
choice (`today`: "Ja, in heutigen Franken", the default; `future`: "Nein, in Franken des Zieldatums") with the new
content attribute `"scope": "goal"`: it is asked once per goal, on the plan page's goal form, which takes its
wording, options and default from the content, and never in the questionnaire's sequence (`questionnaires.ordered`
leaves it out; `PUT .../answers/goal_amount_basis` is refused, 422). The answer is stored on the goal, in the new
nullable column `goal.amount_basis` (`today`, `future`; a CHECK; NULL is not stated), a plan column changed under a
decision as every other, and sent as lbs's `goals[].amount_basis` (LBS-31) **only when stated**: unstated, lbs reads
today's francs, and the request keeps its bytes and lbs's cache. The plan page states a goal's basis once the goal
has an amount. lbs's two new gap inputs (a price or a need in future francs without a date to read it in today's
francs) are in `gaps.KNOWN` with their sentences.

### EIG-61 · The yearly contribution says whether it rises with prices
Owner decision 9. "Steigt der Betrag mit der Teuerung?" (`contribution_indexed`, `nein`, the default, or `ja`) is
an onboarding question right after `annual_contribution`, in the same content version as EIG-60. It is an answer,
not a column (the mandate is built from the answers, EIG-45): `inputs.py` sends it as `mandate.contribution_indexed`
(`ja` true, `nein` false), only when answered; any other value is left out and named in `dropped`.

### EIG-62 · The nominal / real switch, nominal by default, the basis always shown
Owner decision 6. Home, plan and reports carry a switch (`client/app/basis.js`): "Nominal" or "In heutigen
Franken", nominal by default, remembered per browser (`localStorage`, a private window starts nominal), and the
basis in words beside the figures ("Angezeigt: nominal", "in heutigen Franken", "nominal, in Franken vom
31.12.2040"). In real the pages show lbs's real figures and compute none: the home page lists each goal's amount
and the mandate's required return from the sheet's `real_view` and `mandate_proposal.views` (`GET
.../balance-sheet` and the home page now carry `views`), and the plan shows lbs's figure beside each goal's stated
amount (`goal_views`). Today's grid and totals are the same in both bases and say so. A sheet without a real view
(a calibration before lbs's 1.4.0) says so in real; nothing is put in its place. A report is asked in the switch's
basis: `POST .../reports` takes `basis` (`nominal` | `real`), stored in the new column `report_request.basis`, and
sent as report-request's `basis` (REP-27) only when `real`, so a report engine before 1.3.0 still takes a nominal
request. The report list shows each request's basis. Real reports never mix: an allocation whose parameter set is
nominal is left out of a real report (the report engine would refuse the mix).

### EIG-63 · Fix: the report takes the allocation of the current set on its base Regime
The report took the client's latest succeeded pcp run, whatever its Regime or parameter set, so a report asked
after the cockpit ran a scenario showed the scenario's allocation (the Ferienchalet case: the hyperinflation run
was the newest). Now `Service.allocation_run` takes the newest succeeded pcp run **of the client's current
finalised parameter set** (`parameter_set_current`; a superseded set's run is never taken, even when newer) **on its
base Regime**. Which Regimes are scenarios, aggregation says (`GET /scenarios`, mirrored as `ScenarioListed`;
`app.aggregation_url`, 8004): a run whose `regime_id` is listed is a scenario. A scenario is taken only when asked
for: `POST .../reports` takes `scenario` (a policy such as `stagflation`, or a scenario's regime id), stored in the
new column `report_request.scenario`; a named scenario without a run of the current set fails the job, naming it.
aggregation is asked only when the current set has a run; when it cannot answer, the report waits
(`EngineUnavailable`, the request stays open, "try again") rather than risk a scenario's allocation. That makes a
report with an allocation depend on aggregation being up (`desktop.cmd` does not start it; the cockpit's does).
On the real store on 29.09.2026 every one of the 20 use cases' latest run was already the base Regime's, so no
report changes; the tests reproduce the case.

### EIG-64 · Fix: the decision history in plain words
The plan's decision list showed the store's own words: field keys ("label: angestellt → Lohn …", "time_basis"),
role keys ("61,000 CHF, protection"), fact keys ("Ja: health, network_people"), `90000.0` and English thousands.
Decisions are append-only, so none is rewritten: `eigentlich.decisions.Renderer` reads each stored text and says it
again in the reader's language (`GET .../decisions?language=` adds `question_text` and `choice_text`; the stored
`question` and `choice` stay): each field by its name ("Bezeichnung", "Betrag", "Gefäss"), a role by the house's
name from `reference/roles` (by the position's kind of capital when the decision names one position, else both
names once), a template, a liquidity, a vessel or an occupancy in words, a date as 31.12.2055, an amount in the
Swiss format with the typographic apostrophe the page's other figures use (61’000 CHF), a share as 40 %, a fact key
in a question («health») by its name. A text in none of the store's formats is shown as it is. New change lists are
written in the same plain German from the start ("Betrag: neu 96’000, bisher 90’000").

## lbsim in the app (29.09.2026)

Built to `review/LBSIM_INTERFACES.md` section 7 and the app side of section 5, with the owner's decisions of
29.09.2026 (section 10: findings for client and curator; the plan's figures for this period shown to the client
at once, framed as "Was die Rechnung annimmt", never as a recommendation; the withdrawal rate of 3 % shown as an
assumption; a plan confidence of 90 %). Everything is additive: no contract version moves, an lbs request without
the new answers is byte for byte the request of before, no table or column is added, and every stored row reads
back unchanged. App version 1.4.0.

### EIG-65 · Intake version 4: lbsim's earning-power questions, per adult
Owner decision (new questions per adult; a missing answer is the model's level, marked). The intake's next version
(`intake@1.4`) is saved by the owner's curator record with the note "earning power questions for lbsim (principal
and partner), owner 29.09.2026" through `revise-content` (`alignment.revise_earning`, the pattern of EIG-53 and
EIG-60). Section 16 gains `income_expected_full` ("Welchen Bruttolohn erwarten Sie bei vollem Pensum, sobald eine
laufende oder geplante Ausbildung abgeschlossen ist?", help "Ohne Angabe rechnet das Modell mit seinem eigenen
Niveau und sagt das."), `education_status` (keine, läuft, geplant), `education_end_year` (asked when läuft or
geplant) and `health_work_capacity` (nein, leicht, deutlich, stark: 1.0, 0.8, 0.5, 0.2 of a full week; K3). The
partner section (21) gains `partner_income_expected_full`, `partner_education_status`,
`partner_education_end_year`, `partner_education_hours`, `partner_education_budget`, `partner_kader`,
`partner_sector` and `partner_health_work_capacity` (K3), on the options of the client's own questions. Nothing is
removed, so every earlier answer stays valid and is read; the existing `kader`, `sector`, `education_hours` and
`education_budget` now reach lbs. `asked_when` takes `{key, in: [...]}` and a list of conditions that must all hold
(the partner's end year is asked when the partner is in the plan and an education is under way or planned), in
`questionnaires.is_asked` and the browser alike.

**The mapping** (`inputs.py`): per adult `earning_power` (`expected_full_pensum_income`, `responsibility` as the
tier's German label, which lbs accepts, `sector`, `education_status`, `education_end_year`, `education_hours` as the
band, `education_budget_per_year`, `health_work_capacity`) and in `facts` `stop_work_age` (`work_until_age`),
`legal_documents` (the section 12 documents answered ja, by name; answered and none ja is a stated none),
`pillar3a_contribution_per_year`, and from the `properties` entries `mortgage_fixed_until` (the earliest "Fest bis"
of a property with a mortgage, as 31 December of that year), `amortisation_mode` and `own_use_share` (the
self-occupied share of the stated values, only when every entry states its value and use). Each only when stated;
`lbs_body` leaves out every unset one. Left out and named in `dropped`, because lbs refuses the whole request
otherwise: a management tier lbs does not know, an end year with no education, an education that ends before the
year of the sheet, a stop age outside 40 to 75. The work capacity is K3 data as health: while health is withheld it
is dropped with it (lbs refuses the two together; the app withholds nothing today, so this is a guard, mirrored in
`contracts.LbsPerson`). The 20 use cases' requests with their earning answers were validated against lbs's own
model and by the running lbs 1.4.0 (`POST /validate`, which stores nothing).

### EIG-66 · lbsim is called by the app alone; each call is an `engine_run`
`clients.LbsimClient` (`lbsim_url`, 8014, `EIGENTLICH_LBSIM_URL`; `timeouts.lbsim_s` 60) mirrors `lbsim-request@1.0.0`
and `lbsim-optimise@1.0.0` strictly and reads `RunAccepted`, `RunStatus` and the outlook partially (one client, one
sheet, the plan on these paths: `contracts.LbsimOutlook`). The request names the client, the newest sheet and the
Allocation of the current parameter set on its base Regime (`allocation_run`, EIG-63, on whatever basis the set is),
in CHF only (lbsim v1, LBSIM-14; another currency or no set sends none, and the page says why); lbsim resolves
everything else. The fast run is an `engine_run` (`engine = 'lbsim'`, the request's `contract_version`
`lbsim-request@1.0.0`, `artefact_id` the paths, else the findings, `run_id` lbsim's). The plan is a second
`engine_run` under lbsim's plan run id, `running` until `refresh_lbsim_runs` finds it finished in `GET /runs/{id}`:
succeeded with the plan (`LSO-`), or failed with its `failure_kind` before the error (as the cockpit's refresh does,
C-34), so `/api/curator/runs/{id}/refresh` works on it as it is.

**Routes**: `POST /api/clients/{c}/outlook` (`{curator_id?, optimise?: "now"}`; a curator in service or 403; no
sheet 409; lbsim down 503) and `GET /api/clients/{c}/outlook?language=&basis=` (refreshes the plan's row first). With
`optimise: "now"` the fast run asks `optimise: "no"` and the plan is asked through lbsim's `POST /optimise` with
`requested_by` the curator, so it goes ahead of the background plans; lbsim answers a plan already queued or
finished for the same key as it is (the priority of a queued system plan is not raised: a point for lbsim).
`python -m eigentlich lbsim-backfill [--limit N] [--dry-run]` runs lbsim for every client whose newest sheet has no
succeeded lbsim run, one at a time, and refuses to start when lbsim does not answer.

### EIG-67 · lbsim after a new sheet only
After an lbs run succeeds, the app asks lbsim when the sheet id differs from the sheet of the client's latest lbsim
run (whatever became of it), in the background and one at a time per client (a lock per client; the second call
finds the sheet done and asks nothing). The same sheet again (lbs's cache) asks nothing; a new pcp run on an
unchanged sheet is the cockpit's to announce (its Parameters page calls the outlook route after a base-Regime run,
C-34), so there is no second debounce. The automatic run is requested as `system` / `eigentlich-app:auto` after the
app's own lbs runs and as the curator after the cockpit's button. `lbsim_auto.enabled` (default on) switches it off;
a failed call stays failed until the next new sheet, the cockpit, or the backfill.

### EIG-68 · "Aussichten" / "Outlook" and the home card, in one language, without ids
`eigentlich.outlook.shape` turns lbsim's outlook into the page: earning power per adult ("Ihre Angabe" or
"Modellwert", the stated and the modelled full-pensum level, today's income and pensum, the management function,
lbsim's caveats), the income paths with the zero-return saving need, the free cash and whether it holds, per goal in
both bases (the real from lbsim's `views.real`), the findings with their templates filled with Swiss figures, the
severity, urgency and kind of step in words, a link to the question that answers each (`#/q/<name>/sections/<key>`,
which opens that question's section), the schedule, the rules not yet checked, lbsim's assumptions (the withdrawal
rate of 3 % among them), the Regimes by lbsim's labels with the chances as numbers ("68 von 100"), the allocation's
weights by the house's role names and by instrument name, both curves, the bands, and the plan block: "Die
Planrechnung läuft noch (seit N Minuten, höchstens 2 Stunden)" while it runs, then the figures for this period
under "Was die Rechnung annimmt" with lbsim's framing sentence. No artefact, run, question, finding or store id
reaches the page: a goal is tied to its fan by a key of the page alone (`goal1`, ...).

`client/app/charts.js` draws the three charts as SVG through the namespace-aware `h()` (`svg()` in `dom.js`), no
library, no external script: the weights by role and by building block, the target against the reached return over
the 25 states ("Krise" to "Boom", the line of zero return; marked "umgerechnet" in the basis lbsim derived), and the
fan (90 and 50 of 100 paths, the median, the goal's line solid in its own basis and dashed, marked converted, in the
other). The nominal / real switch (EIG-62) reloads the page's figures and redraws all three. The home page's card:
the designated goal's chance in words ("In 68 von 100 simulierten Verläufen wird «Eigenheim» erreicht."), the top
three steps, the plan's state; lbsim not there reads as not available and never fails the home page. The door
"Aussichten" is `#/outlook`.

### EIG-69 · The report draws on lbsim, and an update carries the plan
A report asks lbsim's outlook for its sheet (after waiting for an lbsim run on its way) and sends, one per kind
(report 1.4.0, REP-32): the findings; the paths when they rest on the report's allocation (a report on a scenario
takes the findings only); the plan once lbsim has it on those paths. A real report that carries lbsim's paths leaves
the pcp source out (REP-36, REP-38). The mirror of `report-request@1.0.0` admits `lbsim` and checks one source per
engine and kind. When a plan run turns out succeeded and the client's latest report drew on its paths without it,
the app asks the update that carries it, once, in the name of whoever asked that report, with the note "Ergänzt um
die Planrechnung, sobald sie vorlag." (`lbsim_auto.report_update`, default on). The app learns of the plan when it
asks lbsim (the outlook page, the home page, a report, the cockpit's refresh); nothing polls in the background.
### EIG-70 · "Ihre Lebensbilanz": the balance sheet as a graph on the home page (03.10.2026)
The owner's decision of 03.10.2026 (`review/VISUALS_INTERFACES.md`): the life balance sheet is shown as a graph. It
sits on the **home page**, under the role grid and the totals, and not on the plan page: the home page already holds
the client's newest lbs sheet with its age, its pending run, its staleness note and the nominal / real switch, so the
graph is drawn from exactly the sheet those words describe, and the plan page stays the place where things are
entered and changed. Three columns on one franc scale: the assets stacked by vessel (frei verfügbar, Pensionskasse /
Freizügigkeit, Säule 3a, Sachwerte, ohne Angabe des Gefässes) with the human capital on top; the debts with the net
worth above them; the goals' claims. Every part is listed under its column with its amount, so a thin part is never a
label lost on top of another. The figures are lbs's alone (`totals.by_vessel`, `human_assets`, `liabilities`,
`net_worth`, `real_view.goals`): the server shapes them (`pictures.balance`) with the goals' names instead of their
ids; a part lbs left open is listed as "offen" and never drawn as zero. Today's assets and debts are the same in both
bases; the goals' claims follow the switch (nominal: the francs of each goal's date; real: today's francs), and the
basis is named under the graph. A goal stated a year (retirement) is named under the graph, never stacked with the
stocks. A sheet without lbs's real view says it gives no claims yet. `GET /api/clients/{c}/balance-sheet` (and the
home payload) carries it as `picture`. Drawn by `charts.balanceChart` through the namespace-aware `h()`.

### EIG-71 · "Ihre vier Kapitale": today on the home page, over time on the outlook (03.10.2026)
Per adult, today (home page, `capitals` on the balance-sheet payload, `pictures.capitals_today`): wealth in francs as
words, and expertise ("Wissen und Ausbildung"), network and health as lbs's levels (`human_capital[].E/N/H.value`) on
lbs's scale of 0 to 1 (the human-capital record's ceiling), drawn as bars with the level in words (gering, mittel,
hoch, by thirds of the scale) and the number ("mittel (0.62 von 1.00)"). Never on a money axis. lbs states wealth for
the household, not per adult, so the wealth row says "gemeinsam im Haushalt" (net worth, else the financial assets)
rather than splitting it by a rule of the app's. Over time (the outlook page, after the fan, for the Regime chosen):
lbsim's `regimes[].capitals` for the principal (`outlook._regime` through `pictures.capitals_over_time`), the name
instead of the person id, lbsim's labels in the page's language, one chart per capital with the middle path and the
bands of 10 to 90 and 25 to 75 of 100 paths, on the scale lbsim gives for that Regime with words at both ends
("keine", "Skalenende") and the end value in words. The scale is read as given per Regime and never assumed to be 1:
the network has no fixed ceiling in the model, so lbsim raises its top to that Regime's highest p90 (lbsim P-26).
Wealth over time stays the existing fan. An artefact made before the field has no `capitals`; the page then says the
capitals over time are not yet there and that computing the outlook again brings them. Drawn by `charts.capitalsChart`
and `charts.capitalPathChart`; `charts.levelWord` gives the words.

### EIG-72 · K3: a withheld health is not drawn and the page says so (03.10.2026)
Health is K3 data. When an adult's health is withheld, either in the lbs request the app sent
(`human_capital.health_withheld`) or as lbs states it (`H.absent_because` "K3 data was filtered or erased"), the
server sends no health figure for that adult (`health: null`, `health_withheld: true`) and drops the health band
from lbsim's capitals over time for the principal; the figure lbs or lbsim computed never leaves the server. The page
does not draw the bar or the chart and says instead "von Ihnen zurückgehalten, darum nicht gezeigt" (today) and "Die
Gesundheit über die Zeit wird nicht gezeigt, weil Sie Ihre Gesundheitsangaben zurückgehalten haben" (over time). The
mirror of lbsim's field (`contracts.LbsimCapitals`, on `LbsimPaths.regimes[]`, optional) checks one value per year end
of the horizon for each quantile and a scale for each band, and takes a `health` left out. App version 1.5.0.

### EIG-73 · Every figure on a page is rounded for display (03.10.2026)
The owner's rule (`review/ROUNDING.md`): one formatter in the client, `client/app/format.js`, used by every surface and
chart (values, labels and the figures put into the i18n sentences), and its Python twin, `eigentlich.rounding`, for
the texts the server writes with a number in them (`outlook.figure_text`: a finding's figures in its title, trigger,
reason and action). `dom.amount` and `basis.pct` are gone; no `Intl.NumberFormat` is left outside `format.js`, and a
`toFixed` in `charts.js` only places a mark. CHF amounts: below 1 000 whole francs, 1 000 to 99 999 to the nearest 100,
100 000 to 999 999 to the nearest 1 000, from 1 000 000 millions with two decimals ("CHF 1.35 Mio." / "CHF 1.35 m").
Rates (a required return, inflation, an assumption's rate): one decimal. Chances (the outlook's chance per goal and
Regime, the plan's chance and the confidence asked): whole percent, "unter 1 %" / "über 99 %" at the ends, 0 % and
100 % only for exactly 0 and 1; the sentence is now "In 68 % der simulierten Verläufe" rather than "In 68 von 100".
Weights and shares (the Allocation's weights, a pensum, the work share): whole percent, below 1 % one decimal, 0 (and
an optimiser's 1e-16) as "–". Model levels: two decimals after their word ("mittel (0.62 von 1.00)", unchanged).
Hours, minutes and counts: whole; a year ungrouped. The client's own figures are shown as stated (`format.stated`: a
position's magnitude, a goal's target and share of the saving, an answer), and a field's value is never rounded.
Rounding is half up on the magnitude. The Swiss style is unchanged (the browser's de-CH and en-CH: an apostrophe
between thousands, a decimal point); the twin writes the same. Rounded parts next to a rounded total say so once: the
totals table and the life balance sheet carry "Beträge gerundet." / "Amounts rounded."; each total is lbs's own exact
figure rounded, never a sum of rounded parts. The store, the payloads and the decision log (the client's stated
figures, `decisions.number`) keep the exact values. App version 1.5.1.

### EIG-74 · The app applies its schema at start-up, under a lock (03.10.2026)
`Engines/deploy/ENGINE_CHANGES.md` items 6 and 3. The app's lifespan calls `Service.startup()`, which calls
`Store.initialise()`, as every engine does, so `/health` is ok on an empty database; `init-db` stays and does the
same. `initialise()` takes `pg_advisory_xact_lock(hashtext('eigentlich.schema'))` (`store.SCHEMA_LOCK`) as the first
statement of its transaction, so the app and an `init-db` (or a second app) never apply `schema.sql` at once: without
it PostgreSQL can deadlock on `pg_proc`, as lbsim's workers did on 01.10.2026. Unlike an engine, the app does not
stop when the store cannot be reached or prepared at start-up: it says why on stderr and starts, and `/health` says
`degraded` (as before this change) until the store is there; it is the client's front door, and a crash loop would
say less than `/health` does. Tests: `tests/test_app_startup.py` (an app started on a schema nobody created has every
table and `/health` ok; a second start on a used schema changes nothing; an unreachable store gives `degraded`) and
`tests/test_schema_lock.py` (4 threads with their own connections at once, 3 rounds, none fails; `initialise()` waits
for the lock). App version 1.5.2.

### EIG-75 · `/health` stays out of the access log (03.10.2026)
Item 10. `python -m eigentlich serve` puts a logging filter on `uvicorn.access` (`__main__.quiet_health_probes`)
that drops the records whose path is `/health`; every other request is still logged. The container's health check
calls it every 30 seconds. No new dependency, no setting.

### EIG-76 · `EIGENTLICH_REPORT_DIR` (03.10.2026)
Item 8. `seed` and `migrate` save their report in the folder `EIGENTLICH_REPORT_DIR` names (created when missing),
or in `ROOT/dev/reports` when it is unset or blank, as before. The container image has no `dev/` and runs as an
unprivileged user; the server itself never writes a report.
