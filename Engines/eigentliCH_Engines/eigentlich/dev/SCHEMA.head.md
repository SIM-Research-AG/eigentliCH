# eigentlich store: the schema contract

The PostgreSQL schema `eigentlich` in database `simtech` is the consumer side's store: client records,
versioned questionnaire and knowledge content, answers, the plan and its decisions, question threads,
report requests and reports, approvals, finalised engine inputs and engine runs. This file is the contract
for the two sides that use it:

* **the backend** (the consumer web app), connecting as role **`eigentlich`**, which owns the schema;
* **the cockpit** (the curator pages), connecting as role **`curator`**, which reads and writes the tables
  directly (the stated exception to the one-writer rule, Build Instruction 9.1).

No engine reads this schema. There is no sign-in anywhere: no credentials, no sessions, no passwords. A
client picker lists client records (view `client_overview`); the cockpit chooses which curator record is
acting and names it in every write.

Everything described here is enforced by the database itself (constraints, triggers, grants), so it holds
for the cockpit's direct SQL exactly as for the backend's repository (`src/eigentlich/store.py`). The
catalogue at the end is generated from the live schema by `dev/schema_catalogue.py`.

## 1. Roles and grants

| | `eigentlich` (backend) | `curator` (cockpit) |
|---|---|---|
| Owns schema `eigentlich` | yes | no |
| SELECT on every table and view | yes | yes |
| INSERT, UPDATE on every table | yes | yes |
| USAGE, SELECT on sequences (identity columns) | yes | yes |
| DELETE, TRUNCATE | only under erasure (section 3.7) | **never** (no privilege) |
| CREATE, ALTER, DROP | yes (its schema only) | never |
| Any other schema | nothing (cannot create outside `eigentlich`) | nothing |
| Execute the functions (`save_content`, ...) | yes | yes |

The curator's grants come from provisioning (`Instruments/store/provision.py`): USAGE on the schema,
SELECT/INSERT/UPDATE on all tables, USAGE/SELECT on all sequences, and default privileges so tables that
`eigentlich` creates later get the same. The design never needs the curator to delete: everything the
cockpit does is an INSERT (a new version, a new event, a new message) or an UPDATE of a column that is
allowed to change.

**Connecting from the cockpit.** Either qualify every name (`eigentlich.answer`) or run
`SET search_path TO eigentlich` after connecting. Every function and trigger pins its own search_path, so
triggers work whatever the session's search_path is. Single statements may run in autocommit; a plan
change (decision plus plan rows) must be one transaction.

**Errors the cockpit will see.** Rules raised by triggers arrive as SQLSTATE `P0001` (psycopg
`RaiseException`) with a message naming the rule (`append-only`, `C-09: ...`, `set once`, `cannot be
changed`, `revoked and cannot act`, ...). CHECK failures are `23514`, uniqueness `23505`, foreign keys
`23503`, missing privilege `42501`. Show the message; never retry blindly.

## 2. Conventions

* **Ids** are text, 32 lowercase hex characters (uuid without dashes), defaulted by `new_id()`. Migrated
  rows keep their prototype ids.
* **Time** is `timestamptz` throughout; dates that are dates (`composition_as_of`, `stated_on`) are `date`.
* **JSON** is `jsonb`. **Floats** are `double precision` (only `position.magnitude`, `goal.target_amount`,
  `goal.contribution_share`); there is no `real` anywhere.
* **`data_class`** (C-04): every table carries `data_class smallint`, K0..K3 as 0..3, with a per-table
  floor enforced by CHECK. K0 published content; K1 identifying (client, curator, consent); K2 personal and
  substantive (plan, decisions, threads, reports); K3 documentary and health (submissions; answers and
  facts whose question declares K3). K3 values are never written to a log line.
* **`seq`** (identity) on `answer`, `decision`, `thread_message`, `report` gives the write order; rows
  written in one transaction share `now()`, so order by `seq`, not `created_at`.
* **Actors.** A `*_by_kind` / `*_by_ref` pair names who did something. Kinds: `client` (ref = client id),
  `curator` (ref = curator id), `spark7` (the ChatBot; ref free text, e.g. `chatbot`), `seed`, `migration`,
  `system`, `operator` (free text). A `client` ref must name a client; a `curator` ref must name a curator
  **in service** (`revoked_at IS NULL`, A161): a revoked curator cannot act (trigger `check_actor`).

## 3. The rules

### 3.1 Append-only (`refuse_change`)

UPDATE and DELETE raise `<table> is append-only` on: `content_record`, `submission`, `curator_session`,
`curator_session_event`, `decision`, the five `decision_*` link tables, `thread_message`, `report`,
`approval_request`, `approval_event`, `parameter_set`, `migration_run`. A correction is a new row
(`decision.corrects_id`, a new content version, a new parameter set with `supersedes_id`, a revision
report).

### 3.2 Mutable records (`guard_update`)

DELETE raises `never deleted`. UPDATE may change only the columns listed; a **set-once** column may change
only from NULL; every other column raises `cannot be changed`.

| table | set once | freely editable |
|---|---|---|
| `curator` | `revoked_at`, `revoked_reason` | `display_name`, `email`, `role_label` |
| `client` | `onboarding_completed_at` | `display_name`, `locale`, `stage_hint`, `archived_at` |
| `consent` | `withdrawn_at` | `notes` |
| `answer` | `superseded_at`, `superseded_by_id` | none |
| `thread` | `closed_at`, `closed_by_kind`, `closed_by_ref` | `subject` |
| `report_request` | `withdrawn_at` (only while no report exists) | none |

`engine_run` has its own guard (section 4.5). Plan tables are covered by C-09 (3.3).

### 3.3 C-09: every plan change is covered by a decision in the same transaction

Plan tables: `household`, `household_member`, `position`, `goal`, `client_fact` (each with `decision_id
NOT NULL`), and `goal_funding`, `goal_owner`.

* `decision.txid` is forced to `txid_current()` on insert (a caller cannot choose it).
* INSERT or UPDATE of a plan row must set `decision_id` to a decision **written in the current
  transaction**, else `C-09: every change to <table> must be covered by a decision written in the same
  transaction`. For `position`, `goal`, `client_fact` the decision's `client_id` must equal the row's.
  An UPDATE therefore always sets a new `decision_id`.
* `id`, `created_at` and `client_id` of a plan row cannot change.
* After each insert or update, the row is linked to its decision in `decision_<table>` automatically
  (history: every decision that ever covered the row).
* A decision can be linked (`decision_*` INSERT) only in the transaction that wrote it.
* `goal_funding` and `goal_owner` carry no decision column: a change to them needs a `decision_goal` row
  for that goal from the current transaction; only `active` may change.
* Plan rows are **never deleted**: deactivate (`position.active`, `goal.active`, `goal_funding.active`,
  `goal_owner.active`), close (`household.closed_on`, `household_member.left_on`) or supersede
  (`client_fact.superseded_on`, then a new fact).

### 3.4 Content versions (`content_record_version`)

Content is keyed (`questionnaire/onboarding`, `scoring/risk-profile`, `reference/ahv-pension`,
`knowledge/saeule-3a-grundlagen`, ...) and versioned 1, 2, 3, ... per key. On INSERT the trigger takes a
per-key advisory lock and sets `version` to max+1 (a caller-supplied version must equal max+1); concurrent
saves queue, none is lost, numbering has no gaps. The kind of a key never changes. A questionnaire's
question keys must be present and unique. Every save by anyone (`seed`, `client`, `curator`) is a new
version that records who (`saved_by_kind`, `saved_by_ref`) and when (`saved_at`). Use
`save_content(key, kind, body, saved_by_kind, saved_by_ref, note)`, which returns the new version.

### 3.5 Answers

One current answer per client, questionnaire and question (partial unique index `answer_one_current`).
An answer names the content version it answered (`questionnaire_key`, `content_version`, FK to
`content_record`) and the question must exist in that version. Superseding is the only update: set
`superseded_at` on the current row, insert the new one, then set `superseded_by_id` on the old row. The
row's `data_class` is raised to the question's declared class (`data_class` or `fills.data_class` in the
question, e.g. `health` is K3).

### 3.6 Approval only on the client's request

Nothing waits for a curator unless the client asked. A client may ask a curator to approve a report, an
update, or an answer drafted by spark7 (`approval_request`, one per item). The curator approves or sends a
revision; the client may withdraw. Each request gets at most one event, and every event is terminal.

### 3.7 Erasure (R-231), the only deletion

As role `eigentlich` only, with `SELECT set_config('eigentlich.erasure_client', '<client id>', true)` in
the transaction, the guards let the owner delete that client's rows and redact references to them
(`store.erase_client` does the whole procedure). The curator can set the setting but it has no effect: the
guards check that the current user owns the schema, and the curator has no DELETE privilege.

## 4. State machines

### 4.1 Approval (`approval_request` + `approval_event`, view `approval_state`)

```
            client inserts approval_request
                        |
                 awaiting_curator
            /           |            \
  curator: approved   curator: revision_sent   client: withdrawn
       |                  (revision_item_id)          |
   approved              revised                  withdrawn      (all terminal)
```

* `approved` and `revision_sent`: `actor_kind = 'curator'`, a curator in service.
* `withdrawn`: `actor_kind = 'client'`, `actor_ref` = the requesting client.
* `revision_sent` names `revision_item_id`: for a report or update, a **new** `report` row for the same
  `request_id`; for an answer, a `thread_message` by a curator in the same thread.
* `approval_request` checks the item: `item_kind` `report` or `update` needs a `report` of that client
  whose request has that kind; `answer` needs a `thread_message` with `author_kind = 'spark7'` in one of
  the client's threads.

### 4.2 Threads (`thread` + `thread_message`, view `thread_state`)

```
 opened --(client message)--> awaiting_answer --(spark7 or curator message)--> answered
                                   ^                                              |
                                   +---------------(client message)---------------+
 any state --(closed_at set, once)--> closed   (terminal: no further messages)
```

A new thread with no messages is `awaiting_answer`. A client writes only in their own threads
(`author_ref` = the thread's client). A spark7 message must carry `model` and `chatbot_artefact_id`, may
carry `sources` and `unverified_numbers`; a human message carries neither model nor artefact id.
`in_reply_to_id` must be a message of the same thread. `basis` (added 29.09.2026, EIG-50) says what a
spark7 answer rests on, as the chatbot's `chat-answer` reports it: `grounded` (the notes), `general`
(general knowledge, marked as such in the text) or `mixed`; NULL for a human message, a refusal and every
answer stored before that day. The client reads spark7 as "MiniMind" (EIG-48): `author_kind` keeps the
value `spark7`.

### 4.3 Report requests (`report_request` + `report`, view `report_request_state`)

```
 open --(report inserted)--> fulfilled   (further reports for the same request: revisions)
 open --(withdrawn_at set)--> withdrawn  (no report may follow; withdrawal refused once fulfilled)
```

`kind` is `report` or `update`. A report belongs to its request's client.

### 4.4 Parameter sets (`parameter_set`, view `parameter_set_current`)

A linear chain per client and engine: exactly one root (`supersedes_id IS NULL`), each set superseded at
most once (unique indexes), so the current set is the one nobody supersedes. `finalised_by` must be a
curator in service; `contract_version` names the engine contract (`pcp-mandate@1.0.0`).

### 4.5 Engine runs (`engine_run`)

`queued -> running -> succeeded | failed`, or `queued -> failed`. A finished run is immutable. Only
`status`, `run_id`, `artefact_id`, `error`, `started_at`, `finished_at` change. `succeeded` needs
`artefact_id`; `failed` needs `error`; `finished_at` is set exactly when the run is finished.

Who asked (29.09.2026, EIG-47): `requested_by_kind = 'client'` with the client id (the app's button),
`'curator'` with the curator id (the cockpit's button, `POST /api/clients/{id}/balance-sheet` with
`{"curator_id": ...}`), or `'system'` with `eigentlich-app:auto` (the app's automatic run after a change) or
`eigentlich-app:lbs-backfill` (`python -m eigentlich lbs-backfill`).

### 4.6 Content, answers, facts

Content: versions only grow. Answers: current, then superseded (never un-superseded). Facts: current,
then superseded (`superseded_on`), always under a decision. A stated fact wins over an answer of the same
key when the app builds an engine request, so a fact is restated rather than left behind (EIG-54): the app
restates it when the onboarding question that fills it is answered again, and `PUT /api/clients/{id}/facts/{key}`
restates it directly; the cockpit restates one by the plan change below ("State a fact anew").

### 4.7 Two columns added on 29.09.2026 (additive, EIG-53 and EIG-59)

* `position.owner` (`client`, `partner` or NULL): whose position it is. NULL reads as the client, as every
  position did before; `partner` is the first other adult of the client's current household (members in the
  order client, adults, dependants, then by label). The app sends it to lbs as the position's owner, so each
  adult's income and pension positions count for that person (lbs needs an income position for every adult to
  state a household income).
* `goal.contribution_share` (0 to 1, NULL not stated): the goal's share of the household's one yearly saving
  (the onboarding's `annual_contribution`), shown as 0 to 100 % in the app. The active goals' shares sum to at
  most 1: the app refuses more (and lbs refuses such a request), so a cockpit write should keep to it too;
  the database checks the range only.

## 5. Who writes what

| table | backend (`eigentlich`) | cockpit (`curator`) |
|---|---|---|
| `curator` | operator tooling | create, edit names, revoke |
| `client` | created by the client's own flow; edits | create on a client's behalf (`created_by_kind = 'curator'`), edits, archive |
| `consent` | grant, withdraw | read |
| `content_record` | seed; client edits (`saved_by_kind = 'client'`) | new versions (`saved_by_kind = 'curator'`) |
| `answer` | client answers | answers on a client's behalf (`answered_by_kind = 'curator'`) |
| `submission` | intake files received | read |
| `decision`, plan tables, `decision_*` | client plan changes | curator plan changes (same rules) |
| `thread`, `thread_message` | client messages; spark7 answers | curator answers; close |
| `report_request` | client requests, withdrawals | requests on a client's behalf |
| `report` | produced from the report engine | read (a revision is produced by the backend) |
| `approval_request` | client requests | read |
| `approval_event` | client withdrawals | approve, send revision |
| `parameter_set` | read | finalise |
| `engine_run` | start, progress, finish | read (or start, as `requested_by_kind = 'curator'`) |
| `curator_session`, `curator_session_event` | read | open sessions, append events (C-10 audit) |
| `migration_run` | `python -m eigentlich migrate` | read |

## 6. Content bodies

**Questionnaire** (`questionnaire/onboarding`, `questionnaire/intake`): `{"version", "questions": [...]}`
plus free members (`_about`, `sections`, `source`, `language`). A question:

```json
{"key": "crisis_behaviour", "order": 77, "section": "13", "type": "choice", "required": false,
 "question": {"de": "Was haben Sie 2008 oder 2022 getan"},
 "why": {"de": "Verhalten ist aussagekräftiger als jede Selbsteinschätzung."},
 "options": [{"value": "nichts, ich blieb investiert", "label": {"de": "nichts, ich blieb investiert"}}, "..."]}
```

`type` is `choice`, `multi_choice` (several options at once; the answer is the list of the chosen option
values, in the questionnaire's order), `number`, `text` (with `multiline: true` for long text), `household`,
`goal_template` (onboarding) or `repeat` (intake `properties`: `item_label` and `fields`, each a question).
Optional: `unit`, `min`, `max`, `placeholder`, `fills`, `data_class`, `asked_when`. An option may carry
`"offered": false`: it stays a valid answer (earlier answers, the offline intake form's files) and a bind
target, but the app does not offer it for a new answer (EIG-44). `order` may be fractional (a question
placed between two others without renumbering them). Version 1 of the onboarding is the
prototype file verbatim (`onb2@0.1.0`, 21 questions); version 1 of the intake is extracted from `intake.html`
(`intake@1.1`, 20 sections, 113 questions). Version 2 of each (29.09.2026, saved by the owner's curator
record with the note "aligned to scoring maps, owner 29.09.2026") is aligned to the scoring maps and adds
the yearly contribution: `onb2@0.2.0` (22 questions) and `intake@1.2` (114 questions); EIG-44 lists every
change. Version 3 of the intake (`intake@1.3`, 29.09.2026, saved by the same curator record with the note
"partner section added, hours_learning dropped, owner 29.09.2026") adds section `21`, the partner
(`partner_in_plan` and, asked when it is `ja`, thirteen `partner_*` questions: age, gross salary, working
hours, missing AHV years, qualification, its year, years in the field, training, network and its reach,
mandates, health (K3) and rest; EIG-53), and drops `hours_learning` (EIG-58; answers to earlier versions stay):
127 questions. The intake has `sections: [{key, order, title{de}, lede{de}}]`. An
answer's `value` is the option's `value` for a choice, a number, a string, or for `repeat` a list of
objects keyed by field.

**Scoring map** (`scoring/intake-scales`, `scoring/risk-profile`, `scoring/human-capital`):
`{"map": <the prototype file verbatim>, "binds": [...], "source"}`. Each bind ties one literal German
string of the map to a question and the option value it stands for:

```json
{"path": ["responsibility", "tiers", "topmanagement"], "string": "topmanagement",
 "option_value": "Oberste Führung", "questionnaire": "questionnaire/intake", "question": "kader"}
```

View `scoring_bind_check` checks every bind of the current maps against the current questionnaires
(`ok`, `not_an_option`, `question_has_no_options`, `no_question`, `no_questionnaire`); when a curator
edits a questionnaire the check follows at once.

**Reference** (`reference/<name>`): the prototype's `client/content/<name>.json` verbatim.

**Knowledge** (`knowledge/<id>`): `{"front_matter": {id, title_de, language, topic, approved,
reviewed_by, reviewed_on, sources, ...}, "markdown": "...", "source"}`. Only notes with
`front_matter.approved = true` may be shown to a client (the prototype's retrieval gate).

## 7. Curator SQL (the cockpit's writes)

All examples assume `SET search_path TO eigentlich` (or qualify each name). `:curator` is the acting
curator's id, `:client` the client's.

**State a fact anew** (EIG-54; the app's `PUT /api/clients/{id}/facts/{key}` does the same for the client).

```sql
BEGIN;
INSERT INTO decision (client_id, author, author_ref, question, choice)
     VALUES (:client, 'curator', :curator, 'Die Angabe «canton» festhalten?', 'Ja, so festhalten')
  RETURNING id;                                                      -- :decision
UPDATE client_fact SET superseded_on = current_date, decision_id = :decision
 WHERE client_id = :client AND stated_key = 'canton' AND superseded_on IS NULL;
INSERT INTO client_fact (client_id, stated_key, stated_value, stated_on, stated_by, decision_id, data_class)
     VALUES (:client, 'canton', '"Zürich"', current_date, 'curator', :decision, 1);
COMMIT;
```

**Answer a thread.**

```sql
INSERT INTO thread_message (thread_id, author_kind, author_ref, body, language, in_reply_to_id)
VALUES (:thread, 'curator', :curator, 'Die Antwort ...', 'de', :question_message);
-- close it when done (once):
UPDATE thread SET closed_at = now(), closed_by_kind = 'curator', closed_by_ref = :curator WHERE id = :thread;
```

**Finalise a parameter set** (superseding the current one, if any).

```sql
INSERT INTO parameter_set (client_id, engine, contract_version, body, finalised_by, supersedes_id, note)
SELECT :client, 'pcp', 'pcp-mandate@1.0.0', :body::jsonb, :curator,
       (SELECT id FROM parameter_set_current WHERE client_id = :client AND engine = 'pcp'),
       'Nach Gespräch vom 28.09.2026';
```

**Approve, or send a revision.**

```sql
SELECT * FROM approval_state WHERE state = 'awaiting_curator' ORDER BY created_at;

INSERT INTO approval_event (request_id, event, actor_kind, actor_ref, note)
VALUES (:request, 'approved', 'curator', :curator, 'Geprüft.');

-- a revision of an AI-drafted answer: write the corrected answer, then name it
WITH m AS (
  INSERT INTO thread_message (thread_id, author_kind, author_ref, body, language, in_reply_to_id)
  VALUES (:thread, 'curator', :curator, 'Korrigierte Antwort ...', 'de', :ai_message) RETURNING id)
INSERT INTO approval_event (request_id, event, actor_kind, actor_ref, revision_item_id, note)
SELECT :request, 'revision_sent', 'curator', :curator, m.id, 'Zahl korrigiert' FROM m;
-- a revision of a report: the backend produces the new report row for the same request;
-- then: INSERT INTO approval_event (..., 'revision_sent', ..., revision_item_id => that report id)
```

**Save a questionnaire version.**

```sql
SELECT save_content('questionnaire/intake', 'questionnaire', :edited_body::jsonb,
                    'curator', :curator, 'Option ergänzt');      -- returns the new version number
SELECT * FROM scoring_bind_check WHERE status <> 'ok';           -- what the edit did to the binds
```

**Answer on a client's behalf** (superseding the current answer).

```sql
BEGIN;
UPDATE answer SET superseded_at = now()
 WHERE client_id = :client AND questionnaire_key = 'questionnaire/intake' AND question_key = 'canton'
   AND superseded_at IS NULL
RETURNING id;                                                    -- :old
INSERT INTO answer (client_id, questionnaire_key, content_version, question_key, value,
                    answered_by_kind, answered_by_ref)
VALUES (:client, 'questionnaire/intake', 1, 'canton', '"Bern"', 'curator', :curator)
RETURNING id;                                                    -- :new
UPDATE answer SET superseded_by_id = :new WHERE id = :old;
COMMIT;
```

**Change the plan** (one transaction: decision first, then the rows naming it).

```sql
BEGIN;
INSERT INTO decision (client_id, author, author_ref, question, choice, reasoning)
VALUES (:client, 'curator', :curator, 'Lohn aktualisieren?', 'Ja, 96 000 CHF', 'Lohnausweis 2026')
RETURNING id;                                                    -- :decision
UPDATE position SET magnitude = 96000, decision_id = :decision WHERE id = :position;
COMMIT;
```

**Revoke a curator** (never delete).

```sql
UPDATE curator SET revoked_at = now(), revoked_reason = 'Nicht mehr im Team.' WHERE id = :other_curator;
```

## 8. Views

| view | what it gives |
|---|---|
| `content_current` | the latest version of every content key |
| `scoring_bind_check` | every bind of the current scoring maps with its status |
| `answer_current` | answers not superseded |
| `thread_state` | each thread with `state`, last author, last message time, message count |
| `report_request_state` | each request with `state` (open, fulfilled, withdrawn) and its latest report |
| `approval_state` | each approval request with its event and `state` |
| `parameter_set_current` | the current set per client and engine |
| `client_overview` | the client picker: every client with threads awaiting an answer, approvals awaiting a curator, open report requests |

## 9. Catalogue (generated from the live schema)

Nullable columns are marked `yes`. Generated by `dev/schema_catalogue.py`.

