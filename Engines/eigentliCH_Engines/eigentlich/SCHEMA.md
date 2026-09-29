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

#### `curator`

eigentlich: curators (cockpit users). No credentials: there is no sign-in. Revoked, never deleted (A161); a revoked curator cannot act. K1.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| display_name | text |  |  |
| email | text | yes |  |
| role_label | text | yes |  |
| fictional | boolean |  | false |
| created_at | timestamp with time zone |  | now() |
| created_by_kind | text |  | 'curator'::text |
| revoked_at | timestamp with time zone | yes |  |
| revoked_reason | text | yes |  |
| source_curator_id | text | yes |  |
| data_class | smallint |  | 1 |

Constraints:

- `curator_created_by_kind_check`: `CHECK ((created_by_kind = ANY (ARRAY['curator'::text, 'operator'::text, 'migration'::text])))`
- `curator_data_class_check`: `CHECK (((data_class >= 1) AND (data_class <= 3)))`
- `curator_display_name_check`: `CHECK ((btrim(display_name) <> ''::text))`
- `curator_migration_traced`: `CHECK (((created_by_kind = 'migration'::text) = (source_curator_id IS NOT NULL)))`
- `curator_reason_needs_revocation`: `CHECK (((revoked_at IS NOT NULL) OR (revoked_reason IS NULL)))`
- `curator_pkey`: `PRIMARY KEY (id)`
- `curator_email_key`: `UNIQUE (email)`
- `curator_source_curator_id_key`: `UNIQUE (source_curator_id)`

Triggers:

- `CREATE TRIGGER curator_guard BEFORE DELETE OR UPDATE ON curator FOR EACH ROW EXECUTE FUNCTION guard_update('', 'revoked_at,revoked_reason', 'display_name,email,role_label')`

#### `client`

eigentlich: client records, listed by the client picker (no sign-in). Age at registration >= 18. Never deleted except by erasure; archived instead. K1.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| display_name | text |  |  |
| locale | text |  | 'de-CH'::text |
| age_at_registration | integer |  |  |
| stage_hint | text | yes |  |
| onboarding_completed_at | timestamp with time zone | yes |  |
| archived_at | timestamp with time zone | yes |  |
| created_at | timestamp with time zone |  | now() |
| created_by_kind | text |  |  |
| created_by_ref | text | yes |  |
| source_member_id | text | yes |  |
| data_class | smallint |  | 1 |

Constraints:

- `client_age_at_registration_check`: `CHECK ((age_at_registration >= 18))`
- `client_created_by_kind_check`: `CHECK ((created_by_kind = ANY (ARRAY['client'::text, 'curator'::text, 'migration'::text])))`
- `client_curator_named`: `CHECK (((created_by_kind <> 'curator'::text) OR (created_by_ref IS NOT NULL)))`
- `client_data_class_check`: `CHECK (((data_class >= 1) AND (data_class <= 3)))`
- `client_display_name_check`: `CHECK ((btrim(display_name) <> ''::text))`
- `client_locale_check`: `CHECK ((locale ~ '^[a-z]{2}-[A-Z]{2}$'::text))`
- `client_migration_traced`: `CHECK (((created_by_kind = 'migration'::text) = (source_member_id IS NOT NULL)))`
- `client_pkey`: `PRIMARY KEY (id)`
- `client_source_member_id_key`: `UNIQUE (source_member_id)`

Triggers:

- `CREATE TRIGGER client_actor BEFORE INSERT ON client FOR EACH ROW EXECUTE FUNCTION check_actor('created_by_kind', 'created_by_ref')`
- `CREATE TRIGGER client_guard BEFORE DELETE OR UPDATE ON client FOR EACH ROW EXECUTE FUNCTION guard_update('id', 'onboarding_completed_at', 'display_name,locale,stage_hint,archived_at')`

#### `consent`

eigentlich: versioned consent records per client (R-103); withdrawal sets withdrawn_at once, the grant is never deleted. K1.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| purpose | text |  |  |
| document_version | text |  |  |
| granted_at | timestamp with time zone |  |  |
| withdrawn_at | timestamp with time zone | yes |  |
| notes | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 1 |

Constraints:

- `consent_data_class_check`: `CHECK (((data_class >= 1) AND (data_class <= 3)))`
- `consent_document_version_check`: `CHECK ((btrim(document_version) <> ''::text))`
- `consent_purpose_check`: `CHECK ((purpose ~ '^[a-z0-9_]+$'::text))`
- `consent_withdrawn_after_granted`: `CHECK (((withdrawn_at IS NULL) OR (withdrawn_at >= granted_at)))`
- `consent_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `consent_pkey`: `PRIMARY KEY (id)`

Indexes:

- `consent_by_client`: `CREATE INDEX consent_by_client ON consent USING btree (client_id)`

Triggers:

- `CREATE TRIGGER consent_guard BEFORE DELETE OR UPDATE ON consent FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'withdrawn_at', 'notes')`

#### `content_record`

eigentlich: versioned content (questionnaires, scoring maps with binds, reference content, knowledge notes), PK (key, version), version = max+1 per key; every save by seed, client or curator is a new version; append-only. K0.

| column | type | null | default |
|---|---|---|---|
| key | text |  |  |
| version | integer |  |  |
| kind | text |  |  |
| body | jsonb |  |  |
| saved_by_kind | text |  |  |
| saved_by_ref | text |  |  |
| saved_at | timestamp with time zone |  | now() |
| note | text | yes |  |
| data_class | smallint |  | 0 |

Constraints:

- `content_body_shape`: `CHECK (COALESCE(
CASE kind
    WHEN 'questionnaire'::text THEN (jsonb_typeof((body -> 'questions'::text)) = 'array'::text)
    WHEN 'scoring_map'::text THEN ((jsonb_typeof((body -> 'binds'::text)) = 'array'::text) AND (body ? 'map'::text))
    WHEN 'knowledge'::text THEN ((jsonb_typeof((body -> 'markdown'::text)) = 'string'::text) AND (jsonb_typeof((body -> 'front_matter'::text)) = 'object'::text))
    ELSE (jsonb_typeof(body) = ANY (ARRAY['object'::text, 'array'::text]))
END, false))`
- `content_key_matches_kind`: `CHECK ((split_part(key, '/'::text, 1) =
CASE kind
    WHEN 'questionnaire'::text THEN 'questionnaire'::text
    WHEN 'scoring_map'::text THEN 'scoring'::text
    WHEN 'reference'::text THEN 'reference'::text
    WHEN 'knowledge'::text THEN 'knowledge'::text
    ELSE NULL::text
END))`
- `content_record_data_class_check`: `CHECK (((data_class >= 0) AND (data_class <= 3)))`
- `content_record_key_check`: `CHECK ((key ~ '^(questionnaire|scoring|reference|knowledge)/[a-z0-9][a-z0-9._-]*$'::text))`
- `content_record_kind_check`: `CHECK ((kind = ANY (ARRAY['questionnaire'::text, 'scoring_map'::text, 'reference'::text, 'knowledge'::text])))`
- `content_record_saved_by_kind_check`: `CHECK ((saved_by_kind = ANY (ARRAY['seed'::text, 'client'::text, 'curator'::text])))`
- `content_record_saved_by_ref_check`: `CHECK ((btrim(saved_by_ref) <> ''::text))`
- `content_record_version_check`: `CHECK ((version >= 1))`
- `content_record_pkey`: `PRIMARY KEY (key, version)`

Triggers:

- `CREATE TRIGGER content_record_actor BEFORE INSERT ON content_record FOR EACH ROW EXECUTE FUNCTION check_actor('saved_by_kind', 'saved_by_ref')`
- `CREATE TRIGGER content_record_append_only BEFORE DELETE OR UPDATE ON content_record FOR EACH ROW EXECUTE FUNCTION refuse_change('saved_by_ref')`
- `CREATE TRIGGER content_record_version BEFORE INSERT ON content_record FOR EACH ROW EXECUTE FUNCTION content_record_version()`

#### `answer`

eigentlich: a client's answers to questionnaire questions, each naming the content version it answered; one current answer per client, questionnaire and question; superseding (superseded_at, superseded_by_id) is the only update. K2, K3 where the question declares it.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| seq | bigint |  | identity |
| client_id | text |  |  |
| questionnaire_key | text |  |  |
| content_version | integer |  |  |
| question_key | text |  |  |
| value | jsonb |  |  |
| answered_at | timestamp with time zone |  | now() |
| answered_by_kind | text |  |  |
| answered_by_ref | text |  |  |
| superseded_at | timestamp with time zone | yes |  |
| superseded_by_id | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `answer_answered_by_kind_check`: `CHECK ((answered_by_kind = ANY (ARRAY['client'::text, 'curator'::text, 'migration'::text])))`
- `answer_answered_by_ref_check`: `CHECK ((btrim(answered_by_ref) <> ''::text))`
- `answer_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `answer_not_self_superseded`: `CHECK (((superseded_by_id IS NULL) OR (superseded_by_id <> id)))`
- `answer_superseded_by_needs_time`: `CHECK (((superseded_by_id IS NULL) OR (superseded_at IS NOT NULL)))`
- `answer_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `answer_questionnaire_key_content_version_fkey`: `FOREIGN KEY (questionnaire_key, content_version) REFERENCES content_record(key, version)`
- `answer_superseded_by_id_fkey`: `FOREIGN KEY (superseded_by_id) REFERENCES answer(id)`
- `answer_pkey`: `PRIMARY KEY (id)`
- `answer_seq_key`: `UNIQUE (seq)`

Indexes:

- `answer_by_client`: `CREATE INDEX answer_by_client ON answer USING btree (client_id, questionnaire_key)`
- `answer_one_current`: `CREATE UNIQUE INDEX answer_one_current ON answer USING btree (client_id, questionnaire_key, question_key) WHERE (superseded_at IS NULL)`

Triggers:

- `CREATE TRIGGER answer_actor BEFORE INSERT ON answer FOR EACH ROW EXECUTE FUNCTION check_actor('answered_by_kind', 'answered_by_ref')`
- `CREATE TRIGGER answer_check BEFORE INSERT ON answer FOR EACH ROW EXECUTE FUNCTION answer_check()`
- `CREATE TRIGGER answer_guard BEFORE DELETE OR UPDATE ON answer FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'superseded_at,superseded_by_id', '')`

#### `submission`

eigentlich: intake files as received, whole (A154), unique per client and content hash; append-only. K3.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| schema_version | text |  |  |
| source | text |  |  |
| collected_on | text | yes |  |
| received_at | timestamp with time zone |  |  |
| payload | jsonb |  |  |
| content_hash | text |  |  |
| household_code | text | yes |  |
| mapping_report | jsonb | yes |  |
| note | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 3 |

Constraints:

- `submission_content_hash_check`: `CHECK ((content_hash ~ '^[0-9a-f]{64}$'::text))`
- `submission_data_class_check`: `CHECK ((data_class = 3))`
- `submission_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `submission_pkey`: `PRIMARY KEY (id)`
- `submission_once_per_client`: `UNIQUE (client_id, content_hash)`

Indexes:

- `submission_by_household_code`: `CREATE INDEX submission_by_household_code ON submission USING btree (household_code)`

Triggers:

- `CREATE TRIGGER submission_append_only BEFORE DELETE OR UPDATE ON submission FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id')`

#### `curator_session`

eigentlich: a curator opening a client's material (C-10 audit subject); append-only. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text | yes |  |
| curator_id | text |  |  |
| opened_from | text |  |  |
| opened_at | timestamp with time zone |  | now() |
| liability_flag | boolean | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `curator_session_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `curator_session_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `curator_session_curator_id_fkey`: `FOREIGN KEY (curator_id) REFERENCES curator(id)`
- `curator_session_pkey`: `PRIMARY KEY (id)`

Indexes:

- `curator_session_by_client`: `CREATE INDEX curator_session_by_client ON curator_session USING btree (client_id)`

Triggers:

- `CREATE TRIGGER curator_session_append_only BEFORE DELETE OR UPDATE ON curator_session FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id')`

#### `curator_session_event`

eigentlich: the curator audit trail (C-10); append-only, never erased. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| session_id | text |  |  |
| kind | text |  |  |
| at | timestamp with time zone |  | now() |
| actor | text |  |  |
| detail | jsonb | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `curator_session_event_actor_check`: `CHECK ((btrim(actor) <> ''::text))`
- `curator_session_event_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `curator_session_event_kind_check`: `CHECK ((kind = ANY (ARRAY['opened'::text, 'granted'::text, 'revoked'::text, 'note'::text, 'closed'::text])))`
- `curator_session_event_session_id_fkey`: `FOREIGN KEY (session_id) REFERENCES curator_session(id)`
- `curator_session_event_pkey`: `PRIMARY KEY (id)`

Indexes:

- `curator_session_event_by_session`: `CREATE INDEX curator_session_event_by_session ON curator_session_event USING btree (session_id)`

Triggers:

- `CREATE TRIGGER curator_session_event_append_only BEFORE DELETE OR UPDATE ON curator_session_event FOR EACH ROW EXECUTE FUNCTION refuse_change()`

#### `decision`

eigentlich: decision records (C-09, R-040): every plan change is covered by a decision written in the same transaction (txid); corrections are new rows with corrects_id; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| seq | bigint |  | identity |
| client_id | text | yes |  |
| author | text |  |  |
| author_ref | text | yes |  |
| question | text |  |  |
| options_considered | jsonb |  | '[]'::jsonb |
| choice | text |  |  |
| reasoning | text | yes |  |
| curator_session_id | text | yes |  |
| corrects_id | text | yes |  |
| origin | text |  | 'live'::text |
| txid | bigint |  | txid_current() |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `decision_author_check`: `CHECK ((author = ANY (ARRAY['client'::text, 'curator'::text, 'system'::text])))`
- `decision_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `decision_live_names_client`: `CHECK (((origin = 'migration'::text) OR (client_id IS NOT NULL)))`
- `decision_not_self_correcting`: `CHECK (((corrects_id IS NULL) OR (corrects_id <> id)))`
- `decision_options_considered_check`: `CHECK ((jsonb_typeof(options_considered) = 'array'::text))`
- `decision_origin_check`: `CHECK ((origin = ANY (ARRAY['live'::text, 'migration'::text])))`
- `decision_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `decision_corrects_id_fkey`: `FOREIGN KEY (corrects_id) REFERENCES decision(id)`
- `decision_curator_session_id_fkey`: `FOREIGN KEY (curator_session_id) REFERENCES curator_session(id)`
- `decision_pkey`: `PRIMARY KEY (id)`
- `decision_seq_key`: `UNIQUE (seq)`

Indexes:

- `decision_by_client`: `CREATE INDEX decision_by_client ON decision USING btree (client_id, created_at)`
- `decision_by_txid`: `CREATE INDEX decision_by_txid ON decision USING btree (txid)`

Triggers:

- `CREATE TRIGGER decision_append_only BEFORE DELETE OR UPDATE ON decision FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id')`
- `CREATE TRIGGER decision_stamp BEFORE INSERT ON decision FOR EACH ROW EXECUTE FUNCTION decision_stamp()`

#### `household`

eigentlich: plan table (C-09). A household as stated, with composition_as_of; closed, never deleted. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| composition_as_of | date |  |  |
| stated_by | text |  |  |
| closed_on | date | yes |  |
| succeeds_household_id | text | yes |  |
| decision_id | text |  |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `household_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `household_no_self_succession`: `CHECK (((succeeds_household_id IS NULL) OR (succeeds_household_id <> id)))`
- `household_stated_by_check`: `CHECK ((stated_by = ANY (ARRAY['client'::text, 'curator'::text])))`
- `household_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `household_succeeds_household_id_fkey`: `FOREIGN KEY (succeeds_household_id) REFERENCES household(id)`
- `household_pkey`: `PRIMARY KEY (id)`

Triggers:

- `CREATE TRIGGER household_c09 BEFORE INSERT OR DELETE OR UPDATE ON household FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_household', 'household_id', '')`
- `CREATE TRIGGER household_link AFTER INSERT OR UPDATE ON household FOR EACH ROW EXECUTE FUNCTION plan_link('decision_household', 'household_id')`

#### `household_member`

eigentlich: plan table (C-09). A person in a household, with or without a client record; adult or dependant. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| household_id | text |  |  |
| client_id | text | yes |  |
| label | text |  |  |
| kind | text |  |  |
| joined_on | date | yes |  |
| left_on | date | yes |  |
| decision_id | text |  |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `household_member_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `household_member_kind_check`: `CHECK ((kind = ANY (ARRAY['adult'::text, 'dependant'::text])))`
- `household_member_left_after_joined`: `CHECK (((left_on IS NULL) OR (joined_on IS NULL) OR (left_on >= joined_on)))`
- `household_member_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `household_member_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `household_member_household_id_fkey`: `FOREIGN KEY (household_id) REFERENCES household(id)`
- `household_member_pkey`: `PRIMARY KEY (id)`
- `household_member_client_once`: `UNIQUE (household_id, client_id)`

Indexes:

- `household_member_by_client`: `CREATE INDEX household_member_by_client ON household_member USING btree (client_id)`
- `household_member_by_household`: `CREATE INDEX household_member_by_household ON household_member USING btree (household_id)`

Triggers:

- `CREATE TRIGGER household_member_c09 BEFORE INSERT OR DELETE OR UPDATE ON household_member FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_household_member', 'household_member_id', '')`
- `CREATE TRIGGER household_member_link AFTER INSERT OR UPDATE ON household_member FOR EACH ROW EXECUTE FUNCTION plan_link('decision_household_member', 'household_member_id')`

#### `position`

eigentlich: plan table (C-09). A position in the role grid (human or financial capital); deactivated, never deleted. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| role | text |  |  |
| capital_type | text |  |  |
| label | text |  |  |
| description | text | yes |  |
| magnitude | double precision | yes |  |
| magnitude_unit | text | yes |  |
| tags | jsonb |  | '{}'::jsonb |
| time_basis | text | yes |  |
| started_on | date | yes |  |
| active | boolean |  | true |
| liquidity | text | yes |  |
| stock_kind | text | yes |  |
| decision_id | text |  |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |
| owner | text | yes |  |

Constraints:

- `position_capital_type_check`: `CHECK ((capital_type = ANY (ARRAY['human'::text, 'financial'::text])))`
- `position_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `position_liquidity_check`: `CHECK ((liquidity = ANY (ARRAY['immediate'::text, 'within_months'::text, 'within_years'::text, 'illiquid'::text])))`
- `position_magnitude_has_unit`: `CHECK (((magnitude IS NULL) = (magnitude_unit IS NULL)))`
- `position_magnitude_unit_check`: `CHECK ((magnitude_unit = ANY (ARRAY['chf_per_year'::text, 'share_of_total'::text, 'chf'::text])))`
- `position_owner`: `CHECK (((owner IS NULL) OR (owner = ANY (ARRAY['client'::text, 'partner'::text]))))`
- `position_role_check`: `CHECK ((role = ANY (ARRAY['growth'::text, 'income'::text, 'stabilisation'::text, 'protection'::text])))`
- `position_stock_is_not_negative`: `CHECK (((COALESCE(magnitude_unit, ''::text) <> 'chf'::text) OR (magnitude >= (0)::double precision)))`
- `position_stock_kind_check`: `CHECK ((stock_kind = ANY (ARRAY['asset'::text, 'liability'::text])))`
- `position_stock_kind_iff_stock`: `CHECK (((stock_kind IS NOT NULL) = (COALESCE(magnitude_unit, ''::text) = 'chf'::text)))`
- `position_tags_check`: `CHECK ((jsonb_typeof(tags) = 'object'::text))`
- `position_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `position_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `position_pkey`: `PRIMARY KEY (id)`

Indexes:

- `position_by_client`: `CREATE INDEX position_by_client ON "position" USING btree (client_id)`

Triggers:

- `CREATE TRIGGER position_c09 BEFORE INSERT OR DELETE OR UPDATE ON "position" FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_position', 'position_id', 'client_id')`
- `CREATE TRIGGER position_link AFTER INSERT OR UPDATE ON "position" FOR EACH ROW EXECUTE FUNCTION plan_link('decision_position', 'position_id')`

#### `goal`

eigentlich: plan table (C-09). A client goal; deactivated, never deleted. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| name | text |  |  |
| target_amount | double precision | yes |  |
| target_date | date | yes |  |
| safety | text | yes |  |
| liquidity_need | text | yes |  |
| volatility_tolerance | text | yes |  |
| horizon | text | yes |  |
| flexibility | text | yes |  |
| template | text | yes |  |
| frozen_at | date | yes |  |
| occupancy | text | yes |  |
| active | boolean |  | true |
| decision_id | text |  |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |
| contribution_share | double precision | yes |  |

Constraints:

- `goal_contribution_share`: `CHECK (((contribution_share IS NULL) OR ((contribution_share >= (0)::double precision) AND (contribution_share <= (1)::double precision))))`
- `goal_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `goal_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `goal_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `goal_pkey`: `PRIMARY KEY (id)`

Indexes:

- `goal_by_client`: `CREATE INDEX goal_by_client ON goal USING btree (client_id)`

Triggers:

- `CREATE TRIGGER goal_c09 BEFORE INSERT OR DELETE OR UPDATE ON goal FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_goal', 'goal_id', 'client_id')`
- `CREATE TRIGGER goal_link AFTER INSERT OR UPDATE ON goal FOR EACH ROW EXECUTE FUNCTION plan_link('decision_goal', 'goal_id')`

#### `goal_funding`

eigentlich: plan link (C-09): which positions fund a goal; a change needs a decision linked to the goal in the same transaction; deactivated, never deleted. K2.

| column | type | null | default |
|---|---|---|---|
| goal_id | text |  |  |
| position_id | text |  |  |
| active | boolean |  | true |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `goal_funding_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `goal_funding_goal_id_fkey`: `FOREIGN KEY (goal_id) REFERENCES goal(id)`
- `goal_funding_position_id_fkey`: `FOREIGN KEY (position_id) REFERENCES "position"(id)`
- `goal_funding_pkey`: `PRIMARY KEY (goal_id, position_id)`

Triggers:

- `CREATE TRIGGER goal_funding_c09 BEFORE INSERT OR DELETE OR UPDATE ON goal_funding FOR EACH ROW EXECUTE FUNCTION goal_link_guard()`

#### `goal_owner`

eigentlich: plan link (C-09): which household members own a goal; same rule as goal_funding. K2.

| column | type | null | default |
|---|---|---|---|
| goal_id | text |  |  |
| household_member_id | text |  |  |
| active | boolean |  | true |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `goal_owner_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `goal_owner_goal_id_fkey`: `FOREIGN KEY (goal_id) REFERENCES goal(id)`
- `goal_owner_household_member_id_fkey`: `FOREIGN KEY (household_member_id) REFERENCES household_member(id)`
- `goal_owner_pkey`: `PRIMARY KEY (goal_id, household_member_id)`

Triggers:

- `CREATE TRIGGER goal_owner_c09 BEFORE INSERT OR DELETE OR UPDATE ON goal_owner FOR EACH ROW EXECUTE FUNCTION goal_link_guard()`

#### `client_fact`

eigentlich: plan table (C-09). Stated facts per key (canton, civil status, health, ...); one current per client and key; superseded, never deleted. K1 to K3 per row.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| stated_key | text |  |  |
| stated_value | jsonb |  |  |
| stated_on | date |  |  |
| stated_by | text |  |  |
| superseded_on | date | yes |  |
| decision_id | text |  |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 3 |

Constraints:

- `client_fact_data_class_check`: `CHECK (((data_class >= 1) AND (data_class <= 3)))`
- `client_fact_stated_by_check`: `CHECK ((stated_by = ANY (ARRAY['client'::text, 'curator'::text])))`
- `client_fact_stated_key_check`: `CHECK ((stated_key ~ '^[a-z0-9_]+$'::text))`
- `client_fact_superseded_after_stated`: `CHECK (((superseded_on IS NULL) OR (superseded_on >= stated_on)))`
- `client_fact_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `client_fact_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `client_fact_pkey`: `PRIMARY KEY (id)`

Indexes:

- `client_fact_by_client`: `CREATE INDEX client_fact_by_client ON client_fact USING btree (client_id)`
- `client_fact_one_current`: `CREATE UNIQUE INDEX client_fact_one_current ON client_fact USING btree (client_id, stated_key) WHERE (superseded_on IS NULL)`

Triggers:

- `CREATE TRIGGER client_fact_c09 BEFORE INSERT OR DELETE OR UPDATE ON client_fact FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_client_fact', 'client_fact_id', 'client_id')`
- `CREATE TRIGGER client_fact_link AFTER INSERT OR UPDATE ON client_fact FOR EACH ROW EXECUTE FUNCTION plan_link('decision_client_fact', 'client_fact_id')`

#### `decision_position`

eigentlich: which positions a decision covered; written by trigger; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| decision_id | text |  |  |
| position_id | text |  |  |
| data_class | smallint |  | 2 |

Constraints:

- `decision_position_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `decision_position_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `decision_position_position_id_fkey`: `FOREIGN KEY (position_id) REFERENCES "position"(id)`
- `decision_position_pkey`: `PRIMARY KEY (decision_id, position_id)`

Indexes:

- `decision_position_by_row`: `CREATE INDEX decision_position_by_row ON decision_position USING btree (position_id)`

Triggers:

- `CREATE TRIGGER decision_position_append_only BEFORE DELETE OR UPDATE ON decision_position FOR EACH ROW EXECUTE FUNCTION refuse_change('*')`
- `CREATE TRIGGER decision_position_guard BEFORE INSERT ON decision_position FOR EACH ROW EXECUTE FUNCTION decision_link_guard()`

#### `decision_goal`

eigentlich: which goals a decision covered; written by trigger or directly for funding and owner changes; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| decision_id | text |  |  |
| goal_id | text |  |  |
| data_class | smallint |  | 2 |

Constraints:

- `decision_goal_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `decision_goal_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `decision_goal_goal_id_fkey`: `FOREIGN KEY (goal_id) REFERENCES goal(id)`
- `decision_goal_pkey`: `PRIMARY KEY (decision_id, goal_id)`

Indexes:

- `decision_goal_by_row`: `CREATE INDEX decision_goal_by_row ON decision_goal USING btree (goal_id)`

Triggers:

- `CREATE TRIGGER decision_goal_append_only BEFORE DELETE OR UPDATE ON decision_goal FOR EACH ROW EXECUTE FUNCTION refuse_change('*')`
- `CREATE TRIGGER decision_goal_guard BEFORE INSERT ON decision_goal FOR EACH ROW EXECUTE FUNCTION decision_link_guard()`

#### `decision_household`

eigentlich: which households a decision covered; written by trigger; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| decision_id | text |  |  |
| household_id | text |  |  |
| data_class | smallint |  | 2 |

Constraints:

- `decision_household_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `decision_household_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `decision_household_household_id_fkey`: `FOREIGN KEY (household_id) REFERENCES household(id)`
- `decision_household_pkey`: `PRIMARY KEY (decision_id, household_id)`

Indexes:

- `decision_household_by_row`: `CREATE INDEX decision_household_by_row ON decision_household USING btree (household_id)`

Triggers:

- `CREATE TRIGGER decision_household_append_only BEFORE DELETE OR UPDATE ON decision_household FOR EACH ROW EXECUTE FUNCTION refuse_change('*')`
- `CREATE TRIGGER decision_household_guard BEFORE INSERT ON decision_household FOR EACH ROW EXECUTE FUNCTION decision_link_guard()`

#### `decision_household_member`

eigentlich: which household members a decision covered; written by trigger; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| decision_id | text |  |  |
| household_member_id | text |  |  |
| data_class | smallint |  | 2 |

Constraints:

- `decision_household_member_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `decision_household_member_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `decision_household_member_household_member_id_fkey`: `FOREIGN KEY (household_member_id) REFERENCES household_member(id)`
- `decision_household_member_pkey`: `PRIMARY KEY (decision_id, household_member_id)`

Indexes:

- `decision_household_member_by_row`: `CREATE INDEX decision_household_member_by_row ON decision_household_member USING btree (household_member_id)`

Triggers:

- `CREATE TRIGGER decision_household_member_append_only BEFORE DELETE OR UPDATE ON decision_household_member FOR EACH ROW EXECUTE FUNCTION refuse_change('*')`
- `CREATE TRIGGER decision_household_member_guard BEFORE INSERT ON decision_household_member FOR EACH ROW EXECUTE FUNCTION decision_link_guard()`

#### `decision_client_fact`

eigentlich: which client facts a decision covered; written by trigger; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| decision_id | text |  |  |
| client_fact_id | text |  |  |
| data_class | smallint |  | 2 |

Constraints:

- `decision_client_fact_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `decision_client_fact_client_fact_id_fkey`: `FOREIGN KEY (client_fact_id) REFERENCES client_fact(id)`
- `decision_client_fact_decision_id_fkey`: `FOREIGN KEY (decision_id) REFERENCES decision(id)`
- `decision_client_fact_pkey`: `PRIMARY KEY (decision_id, client_fact_id)`

Indexes:

- `decision_client_fact_by_row`: `CREATE INDEX decision_client_fact_by_row ON decision_client_fact USING btree (client_fact_id)`

Triggers:

- `CREATE TRIGGER decision_client_fact_append_only BEFORE DELETE OR UPDATE ON decision_client_fact FOR EACH ROW EXECUTE FUNCTION refuse_change('*')`
- `CREATE TRIGGER decision_client_fact_guard BEFORE INSERT ON decision_client_fact FOR EACH ROW EXECUTE FUNCTION decision_link_guard()`

#### `thread`

eigentlich: a client's question thread; closing (closed_at, set once) is the only update. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| subject | text | yes |  |
| opened_by_kind | text |  |  |
| opened_by_ref | text |  |  |
| closed_at | timestamp with time zone | yes |  |
| closed_by_kind | text | yes |  |
| closed_by_ref | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `thread_client_closes_own`: `CHECK (((closed_by_kind IS DISTINCT FROM 'client'::text) OR (closed_by_ref = client_id)))`
- `thread_client_opens_own`: `CHECK (((opened_by_kind <> 'client'::text) OR (opened_by_ref = client_id)))`
- `thread_closed_by_kind_check`: `CHECK ((closed_by_kind = ANY (ARRAY['client'::text, 'curator'::text])))`
- `thread_closed_complete`: `CHECK ((((closed_at IS NULL) = (closed_by_kind IS NULL)) AND ((closed_at IS NULL) = (closed_by_ref IS NULL))))`
- `thread_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `thread_opened_by_kind_check`: `CHECK ((opened_by_kind = ANY (ARRAY['client'::text, 'curator'::text])))`
- `thread_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `thread_pkey`: `PRIMARY KEY (id)`

Indexes:

- `thread_by_client`: `CREATE INDEX thread_by_client ON thread USING btree (client_id)`

Triggers:

- `CREATE TRIGGER thread_actor BEFORE INSERT OR UPDATE ON thread FOR EACH ROW EXECUTE FUNCTION check_actor('opened_by_kind', 'opened_by_ref', 'closed_by_kind', 'closed_by_ref')`
- `CREATE TRIGGER thread_guard BEFORE DELETE OR UPDATE ON thread FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'closed_at,closed_by_kind,closed_by_ref', 'subject')`

#### `thread_message`

eigentlich: messages in a thread by the client, a curator or spark7 (the ChatBot, with model, artefact id, sources and unverified numbers); append-only. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| seq | bigint |  | identity |
| thread_id | text |  |  |
| author_kind | text |  |  |
| author_ref | text |  |  |
| body | text |  |  |
| language | text |  |  |
| sources | jsonb |  | '[]'::jsonb |
| model | text | yes |  |
| chatbot_artefact_id | text | yes |  |
| unverified_numbers | jsonb |  | '[]'::jsonb |
| in_reply_to_id | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |
| basis | text | yes |  |

Constraints:

- `thread_message_author_kind_check`: `CHECK ((author_kind = ANY (ARRAY['client'::text, 'curator'::text, 'spark7'::text])))`
- `thread_message_author_ref_check`: `CHECK ((btrim(author_ref) <> ''::text))`
- `thread_message_basis`: `CHECK (((basis IS NULL) OR ((author_kind = 'spark7'::text) AND (basis = ANY (ARRAY['grounded'::text, 'general'::text, 'mixed'::text])))))`
- `thread_message_body_check`: `CHECK ((btrim(body) <> ''::text))`
- `thread_message_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `thread_message_human_no_model`: `CHECK (((author_kind = 'spark7'::text) OR ((model IS NULL) AND (chatbot_artefact_id IS NULL))))`
- `thread_message_language_check`: `CHECK ((language ~ '^[a-z]{2}(-[A-Z]{2})?$'::text))`
- `thread_message_sources_check`: `CHECK ((jsonb_typeof(sources) = 'array'::text))`
- `thread_message_spark7_provenance`: `CHECK (((author_kind <> 'spark7'::text) OR ((model IS NOT NULL) AND (chatbot_artefact_id IS NOT NULL))))`
- `thread_message_unverified_numbers_check`: `CHECK ((jsonb_typeof(unverified_numbers) = 'array'::text))`
- `thread_message_in_reply_to_id_fkey`: `FOREIGN KEY (in_reply_to_id) REFERENCES thread_message(id)`
- `thread_message_thread_id_fkey`: `FOREIGN KEY (thread_id) REFERENCES thread(id)`
- `thread_message_pkey`: `PRIMARY KEY (id)`
- `thread_message_seq_key`: `UNIQUE (seq)`

Indexes:

- `thread_message_by_thread`: `CREATE INDEX thread_message_by_thread ON thread_message USING btree (thread_id, seq)`

Triggers:

- `CREATE TRIGGER thread_message_actor BEFORE INSERT ON thread_message FOR EACH ROW EXECUTE FUNCTION check_actor('author_kind', 'author_ref')`
- `CREATE TRIGGER thread_message_append_only BEFORE DELETE OR UPDATE ON thread_message FOR EACH ROW EXECUTE FUNCTION refuse_change('*')`
- `CREATE TRIGGER thread_message_check BEFORE INSERT ON thread_message FOR EACH ROW EXECUTE FUNCTION thread_message_check()`

#### `report_request`

eigentlich: a request for a report or an update; withdrawal (withdrawn_at, set once, only while unfulfilled) is the only update. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| kind | text |  |  |
| requested_by_kind | text |  |  |
| requested_by_ref | text |  |  |
| language | text |  |  |
| note | text | yes |  |
| withdrawn_at | timestamp with time zone | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `report_request_client_own`: `CHECK (((requested_by_kind <> 'client'::text) OR (requested_by_ref = client_id)))`
- `report_request_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `report_request_kind_check`: `CHECK ((kind = ANY (ARRAY['report'::text, 'update'::text])))`
- `report_request_language_check`: `CHECK ((language ~ '^[a-z]{2}(-[A-Z]{2})?$'::text))`
- `report_request_requested_by_kind_check`: `CHECK ((requested_by_kind = ANY (ARRAY['client'::text, 'curator'::text])))`
- `report_request_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `report_request_pkey`: `PRIMARY KEY (id)`

Indexes:

- `report_request_by_client`: `CREATE INDEX report_request_by_client ON report_request USING btree (client_id)`

Triggers:

- `CREATE TRIGGER report_request_actor BEFORE INSERT ON report_request FOR EACH ROW EXECUTE FUNCTION check_actor('requested_by_kind', 'requested_by_ref')`
- `CREATE TRIGGER report_request_check BEFORE UPDATE ON report_request FOR EACH ROW EXECUTE FUNCTION report_request_check()`
- `CREATE TRIGGER report_request_guard BEFORE DELETE OR UPDATE ON report_request FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'withdrawn_at', '')`

#### `report`

eigentlich: a report produced for a request, with the report engine's artefact id and the LBS and Allocation artefacts it rests on; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| seq | bigint |  | identity |
| request_id | text |  |  |
| client_id | text |  |  |
| report_artefact_id | text |  |  |
| lbs_artefact_id | text | yes |  |
| allocation_artefact_id | text | yes |  |
| body_html | text |  |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `report_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `report_report_artefact_id_check`: `CHECK ((btrim(report_artefact_id) <> ''::text))`
- `report_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `report_request_id_fkey`: `FOREIGN KEY (request_id) REFERENCES report_request(id)`
- `report_pkey`: `PRIMARY KEY (id)`
- `report_seq_key`: `UNIQUE (seq)`

Indexes:

- `report_by_request`: `CREATE INDEX report_by_request ON report USING btree (request_id)`

Triggers:

- `CREATE TRIGGER report_append_only BEFORE DELETE OR UPDATE ON report FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id')`
- `CREATE TRIGGER report_check BEFORE INSERT ON report FOR EACH ROW EXECUTE FUNCTION report_check()`

#### `approval_request`

eigentlich: a client's request that a curator approve a report, an update or an AI-drafted answer; one per item; without a request nothing waits; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| item_kind | text |  |  |
| item_id | text |  |  |
| requested_by | text |  |  |
| note | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `approval_request_by_the_client`: `CHECK ((requested_by = client_id))`
- `approval_request_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `approval_request_item_kind_check`: `CHECK ((item_kind = ANY (ARRAY['report'::text, 'update'::text, 'answer'::text])))`
- `approval_request_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `approval_request_requested_by_fkey`: `FOREIGN KEY (requested_by) REFERENCES client(id)`
- `approval_request_pkey`: `PRIMARY KEY (id)`
- `approval_request_once_per_item`: `UNIQUE (item_kind, item_id)`

Indexes:

- `approval_request_by_client`: `CREATE INDEX approval_request_by_client ON approval_request USING btree (client_id)`

Triggers:

- `CREATE TRIGGER approval_request_append_only BEFORE DELETE OR UPDATE ON approval_request FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id')`
- `CREATE TRIGGER approval_request_check BEFORE INSERT ON approval_request FOR EACH ROW EXECUTE FUNCTION approval_request_check()`

#### `approval_event`

eigentlich: the one terminal event of an approval request: approved or revision_sent (curator) or withdrawn (client); append-only. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| request_id | text |  |  |
| event | text |  |  |
| actor_kind | text |  |  |
| actor_ref | text |  |  |
| note | text | yes |  |
| revision_item_id | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 2 |

Constraints:

- `approval_event_actor`: `CHECK (
CASE event
    WHEN 'withdrawn'::text THEN (actor_kind = 'client'::text)
    ELSE (actor_kind = 'curator'::text)
END)`
- `approval_event_actor_kind_check`: `CHECK ((actor_kind = ANY (ARRAY['client'::text, 'curator'::text])))`
- `approval_event_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `approval_event_event_check`: `CHECK ((event = ANY (ARRAY['approved'::text, 'revision_sent'::text, 'withdrawn'::text])))`
- `approval_event_revision`: `CHECK (((event = 'revision_sent'::text) = (revision_item_id IS NOT NULL)))`
- `approval_event_request_id_fkey`: `FOREIGN KEY (request_id) REFERENCES approval_request(id)`
- `approval_event_pkey`: `PRIMARY KEY (id)`
- `approval_event_one_per_request`: `UNIQUE (request_id)`

Triggers:

- `CREATE TRIGGER approval_event_actor BEFORE INSERT ON approval_event FOR EACH ROW EXECUTE FUNCTION check_actor('actor_kind', 'actor_ref')`
- `CREATE TRIGGER approval_event_append_only BEFORE DELETE OR UPDATE ON approval_event FOR EACH ROW EXECUTE FUNCTION refuse_change('*')`
- `CREATE TRIGGER approval_event_check BEFORE INSERT ON approval_event FOR EACH ROW EXECUTE FUNCTION approval_event_check()`

#### `parameter_set`

eigentlich: engine inputs finalised by a curator per client and engine (e.g. pcp-mandate@1.0.0), a linear chain through supersedes_id; append-only. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| engine | text |  |  |
| contract_version | text |  |  |
| body | jsonb |  |  |
| finalised_by | text |  |  |
| finalised_at | timestamp with time zone |  | now() |
| supersedes_id | text | yes |  |
| note | text | yes |  |
| data_class | smallint |  | 2 |

Constraints:

- `parameter_set_body_check`: `CHECK ((jsonb_typeof(body) = 'object'::text))`
- `parameter_set_contract_version_check`: `CHECK ((contract_version ~ '^[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+$'::text))`
- `parameter_set_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `parameter_set_engine_check`: `CHECK ((engine ~ '^[a-z][a-z0-9_]*$'::text))`
- `parameter_set_not_self_superseding`: `CHECK (((supersedes_id IS NULL) OR (supersedes_id <> id)))`
- `parameter_set_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `parameter_set_finalised_by_fkey`: `FOREIGN KEY (finalised_by) REFERENCES curator(id)`
- `parameter_set_supersedes_id_fkey`: `FOREIGN KEY (supersedes_id) REFERENCES parameter_set(id)`
- `parameter_set_pkey`: `PRIMARY KEY (id)`

Indexes:

- `parameter_set_one_root`: `CREATE UNIQUE INDEX parameter_set_one_root ON parameter_set USING btree (client_id, engine) WHERE (supersedes_id IS NULL)`
- `parameter_set_superseded_once`: `CREATE UNIQUE INDEX parameter_set_superseded_once ON parameter_set USING btree (supersedes_id) WHERE (supersedes_id IS NOT NULL)`

Triggers:

- `CREATE TRIGGER parameter_set_actor BEFORE INSERT ON parameter_set FOR EACH ROW EXECUTE FUNCTION check_actor('=curator', 'finalised_by')`
- `CREATE TRIGGER parameter_set_append_only BEFORE DELETE OR UPDATE ON parameter_set FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id')`
- `CREATE TRIGGER parameter_set_check BEFORE INSERT ON parameter_set FOR EACH ROW EXECUTE FUNCTION parameter_set_check()`

#### `engine_run`

eigentlich: calls to engines (pcp, lbs, report, chatbot) on a client's behalf, with request, run id, artefact id and status; status moves forward only; never deleted. K2.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| client_id | text |  |  |
| engine | text |  |  |
| parameter_set_id | text | yes |  |
| request | jsonb |  |  |
| requested_by_kind | text |  |  |
| requested_by_ref | text |  |  |
| run_id | text | yes |  |
| artefact_id | text | yes |  |
| status | text |  | 'queued'::text |
| error | text | yes |  |
| created_at | timestamp with time zone |  | now() |
| started_at | timestamp with time zone | yes |  |
| finished_at | timestamp with time zone | yes |  |
| data_class | smallint |  | 2 |

Constraints:

- `engine_run_data_class_check`: `CHECK (((data_class >= 2) AND (data_class <= 3)))`
- `engine_run_engine_check`: `CHECK ((engine ~ '^[a-z][a-z0-9_]*$'::text))`
- `engine_run_failure_has_error`: `CHECK (((status <> 'failed'::text) OR (error IS NOT NULL)))`
- `engine_run_finished_iff_terminal`: `CHECK (((finished_at IS NOT NULL) = (status = ANY (ARRAY['succeeded'::text, 'failed'::text]))))`
- `engine_run_requested_by_kind_check`: `CHECK ((requested_by_kind = ANY (ARRAY['client'::text, 'curator'::text, 'system'::text])))`
- `engine_run_status_check`: `CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'failed'::text])))`
- `engine_run_success_has_artefact`: `CHECK (((status <> 'succeeded'::text) OR (artefact_id IS NOT NULL)))`
- `engine_run_client_id_fkey`: `FOREIGN KEY (client_id) REFERENCES client(id)`
- `engine_run_parameter_set_id_fkey`: `FOREIGN KEY (parameter_set_id) REFERENCES parameter_set(id)`
- `engine_run_pkey`: `PRIMARY KEY (id)`

Indexes:

- `engine_run_by_client`: `CREATE INDEX engine_run_by_client ON engine_run USING btree (client_id, engine, created_at)`

Triggers:

- `CREATE TRIGGER engine_run_actor BEFORE INSERT ON engine_run FOR EACH ROW EXECUTE FUNCTION check_actor('requested_by_kind', 'requested_by_ref')`
- `CREATE TRIGGER engine_run_guard BEFORE DELETE OR UPDATE ON engine_run FOR EACH ROW EXECUTE FUNCTION engine_run_guard()`

#### `migration_run`

eigentlich: each migration from the prototype SQLite file, with its source hash, alembic head, transaction id and per-table reconciliation; append-only. K0.

| column | type | null | default |
|---|---|---|---|
| id | text |  | new_id() |
| source_path | text |  |  |
| source_sha256 | text |  |  |
| alembic_head | text |  |  |
| txid | bigint |  | txid_current() |
| reconciliation | jsonb |  |  |
| ran_at | timestamp with time zone |  | now() |
| data_class | smallint |  | 0 |

Constraints:

- `migration_run_data_class_check`: `CHECK (((data_class >= 0) AND (data_class <= 3)))`
- `migration_run_source_sha256_check`: `CHECK ((source_sha256 ~ '^[0-9a-f]{64}$'::text))`
- `migration_run_pkey`: `PRIMARY KEY (id)`

Triggers:

- `CREATE TRIGGER migration_run_append_only BEFORE DELETE OR UPDATE ON migration_run FOR EACH ROW EXECUTE FUNCTION refuse_change()`

#### view `scoring_bind_check`

eigentlich: every bind of the current scoring maps checked against the current questionnaires; status ok, not_an_option, question_has_no_options, no_question or no_questionnaire.

Columns: `scoring_key`, `scoring_version`, `bind_index`, `path`, `string`, `questionnaire_key`, `question_key`, `option_value`, `questionnaire_version`, `status`

#### view `content_current`

eigentlich: the latest version of every content key.

Columns: `key`, `version`, `kind`, `body`, `saved_by_kind`, `saved_by_ref`, `saved_at`, `note`, `data_class`

#### view `answer_current`

eigentlich: the current (not superseded) answers.

Columns: `id`, `seq`, `client_id`, `questionnaire_key`, `content_version`, `question_key`, `value`, `answered_at`, `answered_by_kind`, `answered_by_ref`, `superseded_at`, `superseded_by_id`, `created_at`, `data_class`

#### view `thread_state`

eigentlich: each thread with its state: awaiting_answer, answered or closed.

Columns: `id`, `client_id`, `subject`, `created_at`, `closed_at`, `last_author_kind`, `last_message_at`, `message_count`, `state`

#### view `report_request_state`

eigentlich: each report request with its state: open, fulfilled or withdrawn, and its latest report.

Columns: `id`, `client_id`, `kind`, `requested_by_kind`, `requested_by_ref`, `language`, `note`, `created_at`, `withdrawn_at`, `latest_report_id`, `latest_report_at`, `state`

#### view `approval_state`

eigentlich: each approval request with its state: awaiting_curator, approved, revised or withdrawn.

Columns: `id`, `client_id`, `item_kind`, `item_id`, `requested_by`, `request_note`, `created_at`, `event_id`, `event`, `actor_kind`, `actor_ref`, `event_note`, `revision_item_id`, `decided_at`, `state`

#### view `parameter_set_current`

eigentlich: the parameter sets not superseded, one per client and engine.

Columns: `id`, `client_id`, `engine`, `contract_version`, `body`, `finalised_by`, `finalised_at`, `supersedes_id`, `note`, `data_class`

#### view `client_overview`

eigentlich: the client picker: every client with open thread, approval and report-request counts.

Columns: `id`, `display_name`, `locale`, `age_at_registration`, `stage_hint`, `onboarding_completed_at`, `archived_at`, `created_at`, `created_by_kind`, `threads_awaiting_answer`, `approvals_awaiting_curator`, `report_requests_open`
