-- eigentlich store (Build Instruction section 9.1). Idempotent: safe to run on every start.
--
-- One schema, owned by the login role `eigentlich`. The backend writes as `eigentlich`; the cockpit
-- writes directly as `curator`, which holds SELECT, INSERT and UPDATE on these tables and never
-- DELETE. No engine reads this schema. SCHEMA.md is the contract and describes every object here.
--
-- Conventions: text ids (uuid hex, 32 characters, as the prototype); timestamptz; jsonb for JSON;
-- DOUBLE PRECISION for every float, never REAL; every table carries `data_class` (C-04, K0..K3) with
-- a per-table floor; every table and view carries a COMMENT.
--
-- Tables use bare names and land in the target schema, pinned by search_path when this file runs.
-- Every function is created with `SET search_path FROM CURRENT`, so a trigger fired by the cockpit
-- resolves the same tables whatever search_path the cockpit's session happens to have.
--
-- Rules enforced here rather than trusted to callers:
--   * append-only tables refuse UPDATE and DELETE (refuse_change);
--   * mutable records change only in named columns, and set-once columns change only from NULL
--     (guard_update);
--   * C-09: every write to a plan table names a decision written in the same transaction
--     (plan_guard); plan rows are never deleted, they are deactivated or superseded;
--   * content versions are numbered max+1 per key under an advisory lock (content_record_version);
--   * a curator who is revoked cannot act (check_actor, A161).
-- The single exception to "never delete" is erasure: the owning role, with the setting
-- `eigentlich.erasure_client` naming one client, may remove that client's rows (store.erase_client).

-- ============================================================================================
-- Helpers
-- ============================================================================================

CREATE OR REPLACE FUNCTION new_id() RETURNS text LANGUAGE sql VOLATILE
    SET search_path FROM CURRENT
    AS $$ SELECT replace(gen_random_uuid()::text, '-', '') $$;

-- True when an erasure of `p_client` is in progress in this transaction AND the current user owns
-- the schema. `p_client` NULL means "any erasure in progress" (rows that carry no client reference).
-- The curator role never owns the schema, so it can never erase, whatever it sets.
CREATE OR REPLACE FUNCTION erasure_allowed(p_schema text, p_client text) RETURNS boolean
    LANGUAGE sql STABLE SET search_path FROM CURRENT AS $$
    SELECT coalesce(current_setting('eigentlich.erasure_client', true), '') <> ''
       AND (p_client IS NULL OR current_setting('eigentlich.erasure_client', true) = p_client)
       AND EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                    WHERE n.nspname = p_schema
                      AND pg_catalog.pg_get_userbyid(n.nspowner) = current_user)
$$;

-- `p_client_col`: the column naming the row's client, '*' for rows with no client column, or ''
-- for rows erasure never touches.
CREATE OR REPLACE FUNCTION erasing_row(p_schema text, p_client_col text, p_row jsonb) RETURNS boolean
    LANGUAGE sql STABLE SET search_path FROM CURRENT AS $$
    SELECT CASE
        WHEN coalesce(p_client_col, '') = '' THEN false
        WHEN p_client_col = '*' THEN erasure_allowed(p_schema, NULL)
        WHEN p_row ->> p_client_col IS NULL THEN false
        ELSE erasure_allowed(p_schema, p_row ->> p_client_col)
    END
$$;

-- Append-only. TG_ARGV[0]: the client column erasure may act on ('client_id', '*', or none).
CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_NARGS > 0 AND erasing_row(TG_TABLE_SCHEMA, TG_ARGV[0], to_jsonb(OLD)) THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% is append-only: % refused; record a new row instead', TG_TABLE_NAME, TG_OP;
END
$$;

-- Mutable records. TG_ARGV[0]: erasure client column; TG_ARGV[1]: set-once columns (may change only
-- from NULL); TG_ARGV[2]: freely editable columns. Every other column is immutable. DELETE refused.
CREATE OR REPLACE FUNCTION guard_update() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    set_once text[] := string_to_array(coalesce(TG_ARGV[1], ''), ',');
    free text[] := string_to_array(coalesce(TG_ARGV[2], ''), ',');
    o jsonb := to_jsonb(OLD);
    n jsonb;
    k text;
BEGIN
    IF erasing_row(TG_TABLE_SCHEMA, TG_ARGV[0], o) THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '% rows are never deleted: DELETE refused', TG_TABLE_NAME;
    END IF;
    n := to_jsonb(NEW);
    FOR k IN SELECT jsonb_object_keys(n) LOOP
        CONTINUE WHEN (o -> k) IS NOT DISTINCT FROM (n -> k);
        CONTINUE WHEN k = ANY (free);
        IF k = ANY (set_once) THEN
            CONTINUE WHEN (o -> k) = 'null'::jsonb;
            RAISE EXCEPTION '%.% is set once and is already set', TG_TABLE_NAME, k;
        END IF;
        RAISE EXCEPTION '%.% cannot be changed', TG_TABLE_NAME, k;
    END LOOP;
    RETURN NEW;
END
$$;

-- Actor references. TG_ARGV holds pairs (kind column, ref column); a kind given as '=curator' is a
-- literal. A 'client' ref must name a client; a 'curator' ref must name a curator in service (A161).
-- Other kinds (seed, migration, spark7, system) carry free-text refs. On UPDATE only changed refs are
-- checked.
CREATE OR REPLACE FUNCTION check_actor() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    n jsonb := to_jsonb(NEW);
    o jsonb := CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) ELSE NULL END;
    i int := 0;
    kind text;
    ref text;
BEGIN
    WHILE i + 1 < TG_NARGS LOOP
        kind := CASE WHEN left(TG_ARGV[i], 1) = '=' THEN substr(TG_ARGV[i], 2) ELSE n ->> TG_ARGV[i] END;
        ref := n ->> TG_ARGV[i + 1];
        IF ref IS NOT NULL AND (o IS NULL OR (o -> TG_ARGV[i + 1]) IS DISTINCT FROM (n -> TG_ARGV[i + 1])) THEN
            IF kind = 'client' AND NOT EXISTS (SELECT 1 FROM client WHERE id = ref) THEN
                RAISE EXCEPTION '%.%: no client %', TG_TABLE_NAME, TG_ARGV[i + 1], ref;
            ELSIF kind = 'curator' THEN
                IF NOT EXISTS (SELECT 1 FROM curator WHERE id = ref) THEN
                    RAISE EXCEPTION '%.%: no curator %', TG_TABLE_NAME, TG_ARGV[i + 1], ref;
                ELSIF EXISTS (SELECT 1 FROM curator WHERE id = ref AND revoked_at IS NOT NULL) THEN
                    RAISE EXCEPTION '%.%: curator % is revoked and cannot act (A161)', TG_TABLE_NAME, TG_ARGV[i + 1], ref;
                END IF;
            END IF;
        END IF;
        i := i + 2;
    END LOOP;
    RETURN NEW;
END
$$;

-- ============================================================================================
-- People
-- ============================================================================================

CREATE TABLE IF NOT EXISTS curator (
    id                text PRIMARY KEY DEFAULT new_id(),
    display_name      text NOT NULL CHECK (btrim(display_name) <> ''),
    email             text UNIQUE,                         -- contact address; not a login
    role_label        text,
    fictional         boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    created_by_kind   text NOT NULL DEFAULT 'curator' CHECK (created_by_kind IN ('curator', 'operator', 'migration')),
    revoked_at        timestamptz,
    revoked_reason    text,
    source_curator_id text UNIQUE,                         -- prototype curators.id, for traceability
    data_class        smallint NOT NULL DEFAULT 1 CHECK (data_class BETWEEN 1 AND 3),
    CONSTRAINT curator_reason_needs_revocation CHECK (revoked_at IS NOT NULL OR revoked_reason IS NULL),
    CONSTRAINT curator_migration_traced CHECK ((created_by_kind = 'migration') = (source_curator_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS client (
    id                      text PRIMARY KEY DEFAULT new_id(),
    display_name            text NOT NULL CHECK (btrim(display_name) <> ''),
    locale                  text NOT NULL DEFAULT 'de-CH' CHECK (locale ~ '^[a-z]{2}-[A-Z]{2}$'),
    age_at_registration     integer NOT NULL CHECK (age_at_registration >= 18),
    stage_hint              text,
    onboarding_completed_at timestamptz,
    archived_at             timestamptz,                   -- hidden from the picker; never deleted
    created_at              timestamptz NOT NULL DEFAULT now(),
    created_by_kind         text NOT NULL CHECK (created_by_kind IN ('client', 'curator', 'migration')),
    created_by_ref          text,
    source_member_id        text UNIQUE,                   -- prototype members.id, for traceability
    data_class              smallint NOT NULL DEFAULT 1 CHECK (data_class BETWEEN 1 AND 3),
    CONSTRAINT client_migration_traced CHECK ((created_by_kind = 'migration') = (source_member_id IS NOT NULL)),
    CONSTRAINT client_curator_named CHECK (created_by_kind <> 'curator' OR created_by_ref IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS consent (
    id               text PRIMARY KEY DEFAULT new_id(),
    client_id        text NOT NULL REFERENCES client (id),
    purpose          text NOT NULL CHECK (purpose ~ '^[a-z0-9_]+$'),
    document_version text NOT NULL CHECK (btrim(document_version) <> ''),
    granted_at       timestamptz NOT NULL,
    withdrawn_at     timestamptz,
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    data_class       smallint NOT NULL DEFAULT 1 CHECK (data_class BETWEEN 1 AND 3),
    CONSTRAINT consent_withdrawn_after_granted CHECK (withdrawn_at IS NULL OR withdrawn_at >= granted_at)
);
CREATE INDEX IF NOT EXISTS consent_by_client ON consent (client_id);

-- ============================================================================================
-- Versioned content: questionnaires, scoring maps, reference content, knowledge notes
-- ============================================================================================

CREATE TABLE IF NOT EXISTS content_record (
    key           text NOT NULL CHECK (key ~ '^(questionnaire|scoring|reference|knowledge)/[a-z0-9][a-z0-9._-]*$'),
    version       integer NOT NULL CHECK (version >= 1),
    kind          text NOT NULL CHECK (kind IN ('questionnaire', 'scoring_map', 'reference', 'knowledge')),
    body          jsonb NOT NULL,
    saved_by_kind text NOT NULL CHECK (saved_by_kind IN ('seed', 'client', 'curator')),
    saved_by_ref  text NOT NULL CHECK (btrim(saved_by_ref) <> ''),
    saved_at      timestamptz NOT NULL DEFAULT now(),
    note          text,
    data_class    smallint NOT NULL DEFAULT 0 CHECK (data_class BETWEEN 0 AND 3),
    PRIMARY KEY (key, version),
    CONSTRAINT content_key_matches_kind CHECK (split_part(key, '/', 1) = CASE kind
        WHEN 'questionnaire' THEN 'questionnaire' WHEN 'scoring_map' THEN 'scoring'
        WHEN 'reference' THEN 'reference' WHEN 'knowledge' THEN 'knowledge' END),
    -- coalesce: a missing member makes jsonb_typeof NULL, and a CHECK that is NULL passes.
    CONSTRAINT content_body_shape CHECK (coalesce(CASE kind
        WHEN 'questionnaire' THEN jsonb_typeof(body -> 'questions') = 'array'
        WHEN 'scoring_map' THEN jsonb_typeof(body -> 'binds') = 'array' AND body ? 'map'
        WHEN 'knowledge' THEN jsonb_typeof(body -> 'markdown') = 'string' AND jsonb_typeof(body -> 'front_matter') = 'object'
        ELSE jsonb_typeof(body) IN ('object', 'array') END, false))
);

-- Numbers a new version max+1 under a per-key advisory lock, so concurrent saves queue rather than
-- collide; refuses a caller-chosen version that is not max+1, a change of kind, and a questionnaire
-- whose question keys repeat.
CREATE OR REPLACE FUNCTION content_record_version() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    latest integer;
    latest_kind text;
    dup text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(TG_TABLE_SCHEMA || '.content_record:' || NEW.key, 0));
    SELECT version, kind INTO latest, latest_kind FROM content_record
     WHERE key = NEW.key ORDER BY version DESC LIMIT 1;
    IF NEW.version IS NULL THEN
        NEW.version := coalesce(latest, 0) + 1;
    ELSIF NEW.version <> coalesce(latest, 0) + 1 THEN
        RAISE EXCEPTION 'content_record %: the next version is %, not %', NEW.key, coalesce(latest, 0) + 1, NEW.version;
    END IF;
    IF latest_kind IS NOT NULL AND latest_kind <> NEW.kind THEN
        RAISE EXCEPTION 'content_record %: kind is %, a new version cannot make it %', NEW.key, latest_kind, NEW.kind;
    END IF;
    IF NEW.kind = 'questionnaire' THEN
        SELECT q ->> 'key' INTO dup FROM jsonb_array_elements(NEW.body -> 'questions') q
         GROUP BY q ->> 'key' HAVING count(*) > 1 OR q ->> 'key' IS NULL LIMIT 1;
        IF FOUND THEN
            RAISE EXCEPTION 'content_record %: question key % is missing or repeated', NEW.key, coalesce(dup, 'NULL');
        END IF;
    END IF;
    NEW.saved_at := coalesce(NEW.saved_at, now());
    RETURN NEW;
END
$$;

-- The documented way to save a version: returns the new version number.
CREATE OR REPLACE FUNCTION save_content(p_key text, p_kind text, p_body jsonb, p_saved_by_kind text,
                                        p_saved_by_ref text, p_note text DEFAULT NULL)
    RETURNS integer LANGUAGE sql VOLATILE SET search_path FROM CURRENT AS $$
    INSERT INTO content_record (key, kind, body, saved_by_kind, saved_by_ref, note)
    VALUES (p_key, p_kind, p_body, p_saved_by_kind, p_saved_by_ref, p_note)
    RETURNING version
$$;

CREATE OR REPLACE VIEW content_current AS
    SELECT DISTINCT ON (key) key, version, kind, body, saved_by_kind, saved_by_ref, saved_at, note, data_class
      FROM content_record
     ORDER BY key, version DESC;

-- Every bind of every current scoring map, checked live against the current questionnaires: does the
-- bound option value exist as an option of the bound question? Anything but 'ok' is a mismatch.
CREATE OR REPLACE VIEW scoring_bind_check AS
    SELECT s.key AS scoring_key, s.version AS scoring_version, b.ord AS bind_index,
           b.bind -> 'path' AS path, b.bind ->> 'string' AS string,
           b.bind ->> 'questionnaire' AS questionnaire_key, b.bind ->> 'question' AS question_key,
           b.bind ->> 'option_value' AS option_value, q.version AS questionnaire_version,
           CASE WHEN q.key IS NULL THEN 'no_questionnaire'
                WHEN qq.question IS NULL THEN 'no_question'
                WHEN jsonb_typeof(qq.question -> 'options') IS DISTINCT FROM 'array' THEN 'question_has_no_options'
                WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(qq.question -> 'options') o
                              WHERE o ->> 'value' = b.bind ->> 'option_value') THEN 'ok'
                ELSE 'not_an_option' END AS status
      FROM content_current s
     CROSS JOIN LATERAL jsonb_array_elements(s.body -> 'binds') WITH ORDINALITY AS b (bind, ord)
      LEFT JOIN content_current q ON q.key = b.bind ->> 'questionnaire' AND q.kind = 'questionnaire'
      LEFT JOIN LATERAL (SELECT e AS question FROM jsonb_array_elements(q.body -> 'questions') e
                          WHERE e ->> 'key' = b.bind ->> 'question') qq ON true
     WHERE s.kind = 'scoring_map';

-- ============================================================================================
-- Answers
-- ============================================================================================

CREATE TABLE IF NOT EXISTS answer (
    id                text PRIMARY KEY DEFAULT new_id(),
    seq               bigint GENERATED ALWAYS AS IDENTITY UNIQUE,   -- write order; now() ties within a transaction
    client_id         text NOT NULL REFERENCES client (id),
    questionnaire_key text NOT NULL,
    content_version   integer NOT NULL,
    question_key      text NOT NULL,
    value             jsonb NOT NULL,
    answered_at       timestamptz NOT NULL DEFAULT now(),
    answered_by_kind  text NOT NULL CHECK (answered_by_kind IN ('client', 'curator', 'migration')),
    answered_by_ref   text NOT NULL CHECK (btrim(answered_by_ref) <> ''),
    superseded_at     timestamptz,
    superseded_by_id  text REFERENCES answer (id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    data_class        smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    FOREIGN KEY (questionnaire_key, content_version) REFERENCES content_record (key, version),
    CONSTRAINT answer_superseded_by_needs_time CHECK (superseded_by_id IS NULL OR superseded_at IS NOT NULL),
    CONSTRAINT answer_not_self_superseded CHECK (superseded_by_id IS NULL OR superseded_by_id <> id)
);
CREATE UNIQUE INDEX IF NOT EXISTS answer_one_current
    ON answer (client_id, questionnaire_key, question_key) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS answer_by_client ON answer (client_id, questionnaire_key);

-- The answered question must exist in the named version of a questionnaire; the row's class is
-- raised to the question's declared class (`data_class` or `fills.data_class`, e.g. "K3" for health).
CREATE OR REPLACE FUNCTION answer_check() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    c record;
    q jsonb;
    declared text;
BEGIN
    SELECT kind, body INTO c FROM content_record WHERE key = NEW.questionnaire_key AND version = NEW.content_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'answer: no content %@%', NEW.questionnaire_key, NEW.content_version;
    END IF;
    IF c.kind <> 'questionnaire' THEN
        RAISE EXCEPTION 'answer: % is a %, not a questionnaire', NEW.questionnaire_key, c.kind;
    END IF;
    SELECT e INTO q FROM jsonb_array_elements(c.body -> 'questions') e WHERE e ->> 'key' = NEW.question_key;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'answer: %@% has no question %', NEW.questionnaire_key, NEW.content_version, NEW.question_key;
    END IF;
    declared := coalesce(q ->> 'data_class', q -> 'fills' ->> 'data_class');
    IF declared ~ '^K[0-3]$' THEN
        NEW.data_class := greatest(NEW.data_class, substr(declared, 2)::smallint);
    END IF;
    RETURN NEW;
END
$$;

-- ============================================================================================
-- Submissions (intake files, kept whole: A154)
-- ============================================================================================

CREATE TABLE IF NOT EXISTS submission (
    id             text PRIMARY KEY DEFAULT new_id(),
    client_id      text NOT NULL REFERENCES client (id),
    schema_version text NOT NULL,
    source         text NOT NULL,
    collected_on   text,                                  -- as the file states it (YYYY-MM-DD)
    received_at    timestamptz NOT NULL,
    payload        jsonb NOT NULL,
    content_hash   text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    household_code text,
    mapping_report jsonb,
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    data_class     smallint NOT NULL DEFAULT 3 CHECK (data_class = 3),
    CONSTRAINT submission_once_per_client UNIQUE (client_id, content_hash)
);
CREATE INDEX IF NOT EXISTS submission_by_household_code ON submission (household_code);

-- ============================================================================================
-- Decisions (C-09, R-040) and the plan
-- ============================================================================================

CREATE TABLE IF NOT EXISTS curator_session (
    id             text PRIMARY KEY DEFAULT new_id(),
    client_id      text REFERENCES client (id),
    curator_id     text NOT NULL REFERENCES curator (id),
    opened_from    text NOT NULL,
    opened_at      timestamptz NOT NULL DEFAULT now(),
    liability_flag boolean,
    created_at     timestamptz NOT NULL DEFAULT now(),
    data_class     smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3)
);
CREATE INDEX IF NOT EXISTS curator_session_by_client ON curator_session (client_id);

CREATE TABLE IF NOT EXISTS curator_session_event (
    id         text PRIMARY KEY DEFAULT new_id(),
    session_id text NOT NULL REFERENCES curator_session (id),
    kind       text NOT NULL CHECK (kind IN ('opened', 'granted', 'revoked', 'note', 'closed')),
    at         timestamptz NOT NULL DEFAULT now(),
    actor      text NOT NULL CHECK (btrim(actor) <> ''),
    detail     jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    data_class smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3)
);
CREATE INDEX IF NOT EXISTS curator_session_event_by_session ON curator_session_event (session_id);

CREATE TABLE IF NOT EXISTS decision (
    id                 text PRIMARY KEY DEFAULT new_id(),
    seq                bigint GENERATED ALWAYS AS IDENTITY UNIQUE,  -- write order
    client_id          text REFERENCES client (id),
    author             text NOT NULL CHECK (author IN ('client', 'curator', 'system')),
    author_ref         text,
    question           text NOT NULL,
    options_considered jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(options_considered) = 'array'),
    choice             text NOT NULL,
    reasoning          text,
    curator_session_id text REFERENCES curator_session (id),
    corrects_id        text REFERENCES decision (id),
    origin             text NOT NULL DEFAULT 'live' CHECK (origin IN ('live', 'migration')),
    txid               bigint NOT NULL DEFAULT txid_current(),  -- forced by decision_stamp
    created_at         timestamptz NOT NULL DEFAULT now(),
    data_class         smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT decision_not_self_correcting CHECK (corrects_id IS NULL OR corrects_id <> id),
    CONSTRAINT decision_live_names_client CHECK (origin = 'migration' OR client_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS decision_by_client ON decision (client_id, created_at);
CREATE INDEX IF NOT EXISTS decision_by_txid ON decision (txid);

-- A caller cannot choose the transaction a decision claims: it is always the current one.
CREATE OR REPLACE FUNCTION decision_stamp() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    NEW.txid := txid_current();
    IF NEW.corrects_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM decision d WHERE d.id = NEW.corrects_id AND d.client_id IS NOT DISTINCT FROM NEW.client_id) THEN
        RAISE EXCEPTION 'decision: % corrects %, which is not a decision of the same client', NEW.id, NEW.corrects_id;
    END IF;
    RETURN NEW;
END
$$;

CREATE TABLE IF NOT EXISTS household (
    id                    text PRIMARY KEY DEFAULT new_id(),
    composition_as_of     date NOT NULL,
    stated_by             text NOT NULL CHECK (stated_by IN ('client', 'curator')),
    closed_on             date,
    succeeds_household_id text REFERENCES household (id),
    decision_id           text NOT NULL REFERENCES decision (id),
    created_at            timestamptz NOT NULL DEFAULT now(),
    data_class            smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT household_no_self_succession CHECK (succeeds_household_id IS NULL OR succeeds_household_id <> id)
);

CREATE TABLE IF NOT EXISTS household_member (
    id           text PRIMARY KEY DEFAULT new_id(),
    household_id text NOT NULL REFERENCES household (id),
    client_id    text REFERENCES client (id),              -- NULL: a person without a client record
    label        text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('adult', 'dependant')),
    joined_on    date,
    left_on      date,
    decision_id  text NOT NULL REFERENCES decision (id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    data_class   smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT household_member_client_once UNIQUE (household_id, client_id),
    CONSTRAINT household_member_left_after_joined CHECK (left_on IS NULL OR joined_on IS NULL OR left_on >= joined_on)
);
CREATE INDEX IF NOT EXISTS household_member_by_household ON household_member (household_id);
CREATE INDEX IF NOT EXISTS household_member_by_client ON household_member (client_id);

CREATE TABLE IF NOT EXISTS position (
    id             text PRIMARY KEY DEFAULT new_id(),
    client_id      text NOT NULL REFERENCES client (id),
    role           text NOT NULL CHECK (role IN ('growth', 'income', 'stabilisation', 'protection')),
    capital_type   text NOT NULL CHECK (capital_type IN ('human', 'financial')),
    label          text NOT NULL,
    description    text,
    magnitude      double precision,
    magnitude_unit text CHECK (magnitude_unit IN ('chf_per_year', 'share_of_total', 'chf')),
    tags           jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(tags) = 'object'),
    time_basis     text,
    started_on     date,
    active         boolean NOT NULL DEFAULT true,
    liquidity      text CHECK (liquidity IN ('immediate', 'within_months', 'within_years', 'illiquid')),
    stock_kind     text CHECK (stock_kind IN ('asset', 'liability')),
    decision_id    text NOT NULL REFERENCES decision (id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    data_class     smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT position_magnitude_has_unit CHECK ((magnitude IS NULL) = (magnitude_unit IS NULL)),
    CONSTRAINT position_stock_kind_iff_stock CHECK ((stock_kind IS NOT NULL) = (coalesce(magnitude_unit, '') = 'chf')),
    CONSTRAINT position_stock_is_not_negative CHECK (coalesce(magnitude_unit, '') <> 'chf' OR magnitude >= 0)
);
CREATE INDEX IF NOT EXISTS position_by_client ON position (client_id);

CREATE TABLE IF NOT EXISTS goal (
    id                   text PRIMARY KEY DEFAULT new_id(),
    client_id            text NOT NULL REFERENCES client (id),
    name                 text NOT NULL,
    target_amount        double precision,
    target_date          date,
    safety               text,
    liquidity_need       text,
    volatility_tolerance text,
    horizon              text,
    flexibility          text,
    template             text,
    frozen_at            date,
    occupancy            text,
    active               boolean NOT NULL DEFAULT true,
    decision_id          text NOT NULL REFERENCES decision (id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    data_class           smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3)
);
CREATE INDEX IF NOT EXISTS goal_by_client ON goal (client_id);

-- Added 29.09.2026 (EIG-53, EIG-59), additive. `position.owner`: whose position it is, the client or the
-- partner (the first other adult of the client's household); NULL reads as the client, as every position did
-- before. `goal.contribution_share`: the goal's share of the household's one yearly saving, 0 to 1; NULL is
-- not stated. The app refuses shares of a client's active goals that sum above 1 (lbs refuses them too).
ALTER TABLE position ADD COLUMN IF NOT EXISTS owner text;
ALTER TABLE goal ADD COLUMN IF NOT EXISTS contribution_share double precision;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'position_owner'
                    AND conrelid = 'position'::regclass) THEN
        ALTER TABLE position ADD CONSTRAINT position_owner CHECK (owner IS NULL OR owner IN ('client', 'partner'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'goal_contribution_share'
                    AND conrelid = 'goal'::regclass) THEN
        ALTER TABLE goal ADD CONSTRAINT goal_contribution_share
            CHECK (contribution_share IS NULL OR (contribution_share >= 0 AND contribution_share <= 1));
    END IF;
END
$$;

-- Added 29.09.2026 (EIG-60), additive. `goal.amount_basis`: whether the goal's amount is in today's francs
-- (`today`) or in the francs of its target date (`future`), as the client answered "Ist der Betrag in heutigen
-- Franken?". NULL is not stated, which lbs reads as today's francs (owner decision 7 of 29.09.2026).
ALTER TABLE goal ADD COLUMN IF NOT EXISTS amount_basis text;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'goal_amount_basis'
                    AND conrelid = 'goal'::regclass) THEN
        ALTER TABLE goal ADD CONSTRAINT goal_amount_basis
            CHECK (amount_basis IS NULL OR amount_basis IN ('today', 'future'));
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS goal_funding (
    goal_id     text NOT NULL REFERENCES goal (id),
    position_id text NOT NULL REFERENCES position (id),
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    data_class  smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    PRIMARY KEY (goal_id, position_id)
);

CREATE TABLE IF NOT EXISTS goal_owner (
    goal_id             text NOT NULL REFERENCES goal (id),
    household_member_id text NOT NULL REFERENCES household_member (id),
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    data_class          smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    PRIMARY KEY (goal_id, household_member_id)
);

CREATE TABLE IF NOT EXISTS client_fact (
    id            text PRIMARY KEY DEFAULT new_id(),
    client_id     text NOT NULL REFERENCES client (id),
    stated_key    text NOT NULL CHECK (stated_key ~ '^[a-z0-9_]+$'),
    stated_value  jsonb NOT NULL,
    stated_on     date NOT NULL,
    stated_by     text NOT NULL CHECK (stated_by IN ('client', 'curator')),
    superseded_on date,
    decision_id   text NOT NULL REFERENCES decision (id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    data_class    smallint NOT NULL DEFAULT 3 CHECK (data_class BETWEEN 1 AND 3),
    CONSTRAINT client_fact_superseded_after_stated CHECK (superseded_on IS NULL OR superseded_on >= stated_on)
);
CREATE UNIQUE INDEX IF NOT EXISTS client_fact_one_current ON client_fact (client_id, stated_key) WHERE superseded_on IS NULL;
CREATE INDEX IF NOT EXISTS client_fact_by_client ON client_fact (client_id);

-- Which plan rows each decision covered (many to many; history). Written automatically by
-- plan_link for every insert or update of a plan row, and directly for goal funding and owners.
CREATE TABLE IF NOT EXISTS decision_position (
    decision_id text NOT NULL REFERENCES decision (id),
    position_id text NOT NULL REFERENCES position (id),
    data_class  smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    PRIMARY KEY (decision_id, position_id)
);
CREATE TABLE IF NOT EXISTS decision_goal (
    decision_id text NOT NULL REFERENCES decision (id),
    goal_id     text NOT NULL REFERENCES goal (id),
    data_class  smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    PRIMARY KEY (decision_id, goal_id)
);
CREATE TABLE IF NOT EXISTS decision_household (
    decision_id  text NOT NULL REFERENCES decision (id),
    household_id text NOT NULL REFERENCES household (id),
    data_class   smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    PRIMARY KEY (decision_id, household_id)
);
CREATE TABLE IF NOT EXISTS decision_household_member (
    decision_id         text NOT NULL REFERENCES decision (id),
    household_member_id text NOT NULL REFERENCES household_member (id),
    data_class          smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    PRIMARY KEY (decision_id, household_member_id)
);
CREATE TABLE IF NOT EXISTS decision_client_fact (
    decision_id    text NOT NULL REFERENCES decision (id),
    client_fact_id text NOT NULL REFERENCES client_fact (id),
    data_class     smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    PRIMARY KEY (decision_id, client_fact_id)
);
CREATE INDEX IF NOT EXISTS decision_position_by_row ON decision_position (position_id);
CREATE INDEX IF NOT EXISTS decision_goal_by_row ON decision_goal (goal_id);
CREATE INDEX IF NOT EXISTS decision_household_by_row ON decision_household (household_id);
CREATE INDEX IF NOT EXISTS decision_household_member_by_row ON decision_household_member (household_member_id);
CREATE INDEX IF NOT EXISTS decision_client_fact_by_row ON decision_client_fact (client_fact_id);

-- C-09 in the database. TG_ARGV: link table, link column, client column ('' when the row's client
-- need not match the decision's, as for a household member stated by another client).
CREATE OR REPLACE FUNCTION plan_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    client_col text := nullif(TG_ARGV[2], '');
    erasure_col text := coalesce(nullif(TG_ARGV[2], ''), '*');
    d record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF erasing_row(TG_TABLE_SCHEMA, erasure_col, to_jsonb(OLD)) THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'C-09: % rows are never deleted; deactivate or supersede them under a new decision', TG_TABLE_NAME;
    END IF;
    IF TG_OP = 'UPDATE' AND erasing_row(TG_TABLE_SCHEMA, erasure_col, to_jsonb(OLD)) THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.id <> OLD.id OR NEW.created_at <> OLD.created_at
        OR (client_col IS NOT NULL AND (to_jsonb(NEW) ->> client_col) IS DISTINCT FROM (to_jsonb(OLD) ->> client_col))) THEN
        RAISE EXCEPTION '%: id, created_at and the client cannot be changed', TG_TABLE_NAME;
    END IF;
    SELECT txid, client_id INTO d FROM decision WHERE id = NEW.decision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'C-09: % % names decision %, which does not exist', TG_TABLE_NAME, NEW.id, NEW.decision_id;
    END IF;
    IF d.txid <> txid_current() THEN
        RAISE EXCEPTION 'C-09: every change to % must be covered by a decision written in the same transaction; decision % was not', TG_TABLE_NAME, NEW.decision_id;
    END IF;
    IF client_col IS NOT NULL AND (to_jsonb(NEW) ->> client_col) IS DISTINCT FROM d.client_id THEN
        RAISE EXCEPTION 'C-09: % % belongs to client %, decision % to client %', TG_TABLE_NAME, NEW.id,
            to_jsonb(NEW) ->> client_col, NEW.decision_id, d.client_id;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION plan_link() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    EXECUTE format('INSERT INTO %I.%I (decision_id, %I) VALUES ($1, $2) ON CONFLICT DO NOTHING',
                   TG_TABLE_SCHEMA, TG_ARGV[0], TG_ARGV[1])
        USING NEW.decision_id, NEW.id;
    RETURN NULL;
END
$$;

-- Goal funding and owners carry no decision column: a change to them is a change to the goal, covered
-- by a decision linked to that goal (decision_goal) in the same transaction. Only `active` may change.
CREATE OR REPLACE FUNCTION goal_link_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    gid text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF erasing_row(TG_TABLE_SCHEMA, '*', to_jsonb(OLD)) THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'C-09: % rows are never deleted; set active = false under a new decision', TG_TABLE_NAME;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF erasing_row(TG_TABLE_SCHEMA, '*', to_jsonb(OLD)) THEN RETURN NEW; END IF;
        IF (to_jsonb(NEW) - 'active') IS DISTINCT FROM (to_jsonb(OLD) - 'active') THEN
            RAISE EXCEPTION '%: only active may change', TG_TABLE_NAME;
        END IF;
    END IF;
    gid := NEW.goal_id;
    IF NOT EXISTS (SELECT 1 FROM decision_goal dg JOIN decision d ON d.id = dg.decision_id
                    WHERE dg.goal_id = gid AND d.txid = txid_current()) THEN
        RAISE EXCEPTION 'C-09: a change to % must be covered by a decision linked to goal % (decision_goal) in the same transaction', TG_TABLE_NAME, gid;
    END IF;
    RETURN NEW;
END
$$;

-- A decision can be linked to rows only in the transaction that wrote it: history is not rewritten.
CREATE OR REPLACE FUNCTION decision_link_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM decision WHERE id = NEW.decision_id AND txid = txid_current()) THEN
        RAISE EXCEPTION 'C-09: % may link only a decision written in the same transaction; % was not', TG_TABLE_NAME, NEW.decision_id;
    END IF;
    RETURN NEW;
END
$$;

-- ============================================================================================
-- Question threads
-- ============================================================================================

CREATE TABLE IF NOT EXISTS thread (
    id              text PRIMARY KEY DEFAULT new_id(),
    client_id       text NOT NULL REFERENCES client (id),
    subject         text,
    opened_by_kind  text NOT NULL CHECK (opened_by_kind IN ('client', 'curator')),
    opened_by_ref   text NOT NULL,
    closed_at       timestamptz,
    closed_by_kind  text CHECK (closed_by_kind IN ('client', 'curator')),
    closed_by_ref   text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    data_class      smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT thread_closed_complete CHECK ((closed_at IS NULL) = (closed_by_kind IS NULL)
                                             AND (closed_at IS NULL) = (closed_by_ref IS NULL)),
    CONSTRAINT thread_client_opens_own CHECK (opened_by_kind <> 'client' OR opened_by_ref = client_id),
    CONSTRAINT thread_client_closes_own CHECK (closed_by_kind IS DISTINCT FROM 'client' OR closed_by_ref = client_id)
);
CREATE INDEX IF NOT EXISTS thread_by_client ON thread (client_id);

CREATE TABLE IF NOT EXISTS thread_message (
    id                  text PRIMARY KEY DEFAULT new_id(),
    seq                 bigint GENERATED ALWAYS AS IDENTITY UNIQUE, -- write order; now() ties within a transaction
    thread_id           text NOT NULL REFERENCES thread (id),
    author_kind         text NOT NULL CHECK (author_kind IN ('client', 'curator', 'spark7')),
    author_ref          text NOT NULL CHECK (btrim(author_ref) <> ''),
    body                text NOT NULL CHECK (btrim(body) <> ''),
    language            text NOT NULL CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
    sources             jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(sources) = 'array'),
    model               text,
    chatbot_artefact_id text,
    unverified_numbers  jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(unverified_numbers) = 'array'),
    in_reply_to_id      text REFERENCES thread_message (id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    data_class          smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT thread_message_spark7_provenance CHECK (author_kind <> 'spark7' OR (model IS NOT NULL AND chatbot_artefact_id IS NOT NULL)),
    CONSTRAINT thread_message_human_no_model CHECK (author_kind = 'spark7' OR (model IS NULL AND chatbot_artefact_id IS NULL))
);
CREATE INDEX IF NOT EXISTS thread_message_by_thread ON thread_message (thread_id, seq);

-- Added 29.09.2026 (EIG-50), additive: what an AI-drafted answer rests on, as the chatbot's chat-answer
-- `basis` says (grounded: the notes; general: general knowledge, marked as such; mixed: both). NULL for a
-- human message, a refusal, and every message stored before the chatbot sent it.
ALTER TABLE thread_message ADD COLUMN IF NOT EXISTS basis text;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'thread_message_basis'
                    AND conrelid = 'thread_message'::regclass) THEN
        ALTER TABLE thread_message ADD CONSTRAINT thread_message_basis
            CHECK (basis IS NULL OR (author_kind = 'spark7' AND basis IN ('grounded', 'general', 'mixed')));
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION thread_message_check() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    t record;
BEGIN
    SELECT client_id, closed_at INTO t FROM thread WHERE id = NEW.thread_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'thread_message: no thread %', NEW.thread_id;
    END IF;
    IF t.closed_at IS NOT NULL THEN
        RAISE EXCEPTION 'thread_message: thread % is closed; open a new thread', NEW.thread_id;
    END IF;
    IF NEW.author_kind = 'client' AND NEW.author_ref <> t.client_id THEN
        RAISE EXCEPTION 'thread_message: a client writes only in their own thread';
    END IF;
    IF NEW.in_reply_to_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM thread_message WHERE id = NEW.in_reply_to_id AND thread_id = NEW.thread_id) THEN
        RAISE EXCEPTION 'thread_message: % is not a message of thread %', NEW.in_reply_to_id, NEW.thread_id;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE VIEW thread_state AS
    SELECT t.id, t.client_id, t.subject, t.created_at, t.closed_at,
           m.author_kind AS last_author_kind, m.created_at AS last_message_at,
           (SELECT count(*) FROM thread_message x WHERE x.thread_id = t.id) AS message_count,
           CASE WHEN t.closed_at IS NOT NULL THEN 'closed'
                WHEN m.author_kind IS NULL OR m.author_kind = 'client' THEN 'awaiting_answer'
                ELSE 'answered' END AS state
      FROM thread t
      LEFT JOIN LATERAL (SELECT author_kind, created_at FROM thread_message
                          WHERE thread_id = t.id ORDER BY seq DESC LIMIT 1) m ON true;

-- ============================================================================================
-- Report requests and reports
-- ============================================================================================

CREATE TABLE IF NOT EXISTS report_request (
    id                text PRIMARY KEY DEFAULT new_id(),
    client_id         text NOT NULL REFERENCES client (id),
    kind              text NOT NULL CHECK (kind IN ('report', 'update')),
    requested_by_kind text NOT NULL CHECK (requested_by_kind IN ('client', 'curator')),
    requested_by_ref  text NOT NULL,
    language          text NOT NULL CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
    note              text,
    withdrawn_at      timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    data_class        smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT report_request_client_own CHECK (requested_by_kind <> 'client' OR requested_by_ref = client_id)
);
CREATE INDEX IF NOT EXISTS report_request_by_client ON report_request (client_id);

-- Added 29.09.2026 (EIG-62, EIG-63), additive. `basis`: the basis the report was asked in, `nominal` or `real`
-- (in today's francs); NULL is nominal, as every request before. `scenario`: a scenario Regime asked for by
-- name (aggregation's policy, such as `stagflation`, or a scenario's regime id); NULL is the base Regime.
-- Both are set on insert and never change (the request's guard).
ALTER TABLE report_request ADD COLUMN IF NOT EXISTS basis text;
ALTER TABLE report_request ADD COLUMN IF NOT EXISTS scenario text;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'report_request_basis'
                    AND conrelid = 'report_request'::regclass) THEN
        ALTER TABLE report_request ADD CONSTRAINT report_request_basis
            CHECK (basis IS NULL OR basis IN ('nominal', 'real'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'report_request_scenario'
                    AND conrelid = 'report_request'::regclass) THEN
        ALTER TABLE report_request ADD CONSTRAINT report_request_scenario
            CHECK (scenario IS NULL OR scenario ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$');
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS report (
    id                     text PRIMARY KEY DEFAULT new_id(),
    seq                    bigint GENERATED ALWAYS AS IDENTITY UNIQUE,  -- write order
    request_id             text NOT NULL REFERENCES report_request (id),
    client_id              text NOT NULL REFERENCES client (id),
    report_artefact_id     text NOT NULL CHECK (btrim(report_artefact_id) <> ''),
    lbs_artefact_id        text,
    allocation_artefact_id text,
    body_html              text NOT NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    data_class             smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3)
);
CREATE INDEX IF NOT EXISTS report_by_request ON report (request_id);

CREATE OR REPLACE FUNCTION report_request_check() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.withdrawn_at IS NOT NULL AND OLD.withdrawn_at IS NULL
       AND EXISTS (SELECT 1 FROM report WHERE request_id = NEW.id) THEN
        RAISE EXCEPTION 'report_request %: already fulfilled, cannot be withdrawn', NEW.id;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION report_check() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    r record;
BEGIN
    SELECT client_id, withdrawn_at INTO r FROM report_request WHERE id = NEW.request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'report: no request %', NEW.request_id;
    END IF;
    IF r.client_id <> NEW.client_id THEN
        RAISE EXCEPTION 'report: request % belongs to another client', NEW.request_id;
    END IF;
    IF r.withdrawn_at IS NOT NULL THEN
        RAISE EXCEPTION 'report: request % was withdrawn', NEW.request_id;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE VIEW report_request_state AS
    SELECT q.id, q.client_id, q.kind, q.requested_by_kind, q.requested_by_ref, q.language, q.note,
           q.created_at, q.withdrawn_at, r.id AS latest_report_id, r.created_at AS latest_report_at,
           CASE WHEN q.withdrawn_at IS NOT NULL THEN 'withdrawn'
                WHEN r.id IS NULL THEN 'open'
                ELSE 'fulfilled' END AS state,
           q.basis, q.scenario
      FROM report_request q
      LEFT JOIN LATERAL (SELECT id, created_at FROM report WHERE request_id = q.id
                          ORDER BY seq DESC LIMIT 1) r ON true;

-- ============================================================================================
-- Approval, only on the client's request
-- ============================================================================================

CREATE TABLE IF NOT EXISTS approval_request (
    id           text PRIMARY KEY DEFAULT new_id(),
    client_id    text NOT NULL REFERENCES client (id),
    item_kind    text NOT NULL CHECK (item_kind IN ('report', 'update', 'answer')),
    item_id      text NOT NULL,
    requested_by text NOT NULL REFERENCES client (id),
    note         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    data_class   smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT approval_request_by_the_client CHECK (requested_by = client_id),
    CONSTRAINT approval_request_once_per_item UNIQUE (item_kind, item_id)
);
CREATE INDEX IF NOT EXISTS approval_request_by_client ON approval_request (client_id);

CREATE TABLE IF NOT EXISTS approval_event (
    id               text PRIMARY KEY DEFAULT new_id(),
    request_id       text NOT NULL REFERENCES approval_request (id),
    event            text NOT NULL CHECK (event IN ('approved', 'revision_sent', 'withdrawn')),
    actor_kind       text NOT NULL CHECK (actor_kind IN ('client', 'curator')),
    actor_ref        text NOT NULL,
    note             text,
    revision_item_id text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    data_class       smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    -- Every event is terminal, so a request has at most one.
    CONSTRAINT approval_event_one_per_request UNIQUE (request_id),
    CONSTRAINT approval_event_actor CHECK (CASE event WHEN 'withdrawn' THEN actor_kind = 'client' ELSE actor_kind = 'curator' END),
    CONSTRAINT approval_event_revision CHECK ((event = 'revision_sent') = (revision_item_id IS NOT NULL))
);

-- The item must exist, belong to the requesting client, and be of the named kind: a report row of a
-- request of that kind, or an answer drafted by spark7 in one of the client's threads.
CREATE OR REPLACE FUNCTION approval_request_check() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.item_kind IN ('report', 'update') THEN
        IF NOT EXISTS (SELECT 1 FROM report r JOIN report_request q ON q.id = r.request_id
                        WHERE r.id = NEW.item_id AND r.client_id = NEW.client_id AND q.kind = NEW.item_kind) THEN
            RAISE EXCEPTION 'approval_request: no % % of client %', NEW.item_kind, NEW.item_id, NEW.client_id;
        END IF;
    ELSE
        IF NOT EXISTS (SELECT 1 FROM thread_message m JOIN thread t ON t.id = m.thread_id
                        WHERE m.id = NEW.item_id AND t.client_id = NEW.client_id AND m.author_kind = 'spark7') THEN
            RAISE EXCEPTION 'approval_request: no AI-drafted answer % in a thread of client %', NEW.item_id, NEW.client_id;
        END IF;
    END IF;
    RETURN NEW;
END
$$;

-- Withdrawal is by the requesting client; approval and revision by a curator in service. A revision
-- names the revised item: a report for the same request, or a curator message in the same thread.
CREATE OR REPLACE FUNCTION approval_event_check() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
DECLARE
    q record;
BEGIN
    SELECT * INTO q FROM approval_request WHERE id = NEW.request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'approval_event: no request %', NEW.request_id;
    END IF;
    IF NEW.event = 'withdrawn' AND NEW.actor_ref <> q.client_id THEN
        RAISE EXCEPTION 'approval_event: only the requesting client withdraws a request';
    END IF;
    IF NEW.event = 'revision_sent' THEN
        IF q.item_kind IN ('report', 'update') THEN
            IF NOT EXISTS (SELECT 1 FROM report r JOIN report o ON o.request_id = r.request_id
                            WHERE r.id = NEW.revision_item_id AND o.id = q.item_id AND r.id <> o.id) THEN
                RAISE EXCEPTION 'approval_event: revision % is not a new report for the same request', NEW.revision_item_id;
            END IF;
        ELSE
            IF NOT EXISTS (SELECT 1 FROM thread_message r JOIN thread_message o ON o.thread_id = r.thread_id
                            WHERE r.id = NEW.revision_item_id AND o.id = q.item_id AND r.author_kind = 'curator') THEN
                RAISE EXCEPTION 'approval_event: revision % is not a curator message in the same thread', NEW.revision_item_id;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE VIEW approval_state AS
    SELECT q.id, q.client_id, q.item_kind, q.item_id, q.requested_by, q.note AS request_note, q.created_at,
           e.id AS event_id, e.event, e.actor_kind, e.actor_ref, e.note AS event_note, e.revision_item_id,
           e.created_at AS decided_at,
           CASE e.event WHEN 'approved' THEN 'approved' WHEN 'revision_sent' THEN 'revised'
                        WHEN 'withdrawn' THEN 'withdrawn' ELSE 'awaiting_curator' END AS state
      FROM approval_request q
      LEFT JOIN approval_event e ON e.request_id = q.id;

-- ============================================================================================
-- Engine inputs and runs
-- ============================================================================================

CREATE TABLE IF NOT EXISTS parameter_set (
    id               text PRIMARY KEY DEFAULT new_id(),
    client_id        text NOT NULL REFERENCES client (id),
    engine           text NOT NULL CHECK (engine ~ '^[a-z][a-z0-9_]*$'),
    contract_version text NOT NULL CHECK (contract_version ~ '^[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+$'),
    body             jsonb NOT NULL CHECK (jsonb_typeof(body) = 'object'),
    finalised_by     text NOT NULL REFERENCES curator (id),
    finalised_at     timestamptz NOT NULL DEFAULT now(),
    supersedes_id    text REFERENCES parameter_set (id),
    note             text,
    data_class       smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT parameter_set_not_self_superseding CHECK (supersedes_id IS NULL OR supersedes_id <> id)
);
-- A linear chain per client and engine: one root, and each set superseded at most once.
CREATE UNIQUE INDEX IF NOT EXISTS parameter_set_one_root ON parameter_set (client_id, engine) WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS parameter_set_superseded_once ON parameter_set (supersedes_id) WHERE supersedes_id IS NOT NULL;

CREATE OR REPLACE FUNCTION parameter_set_check() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM parameter_set WHERE id = NEW.supersedes_id AND client_id = NEW.client_id AND engine = NEW.engine) THEN
        RAISE EXCEPTION 'parameter_set: % supersedes %, which is not a set of the same client and engine', NEW.id, NEW.supersedes_id;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE VIEW parameter_set_current AS
    SELECT p.* FROM parameter_set p
     WHERE NOT EXISTS (SELECT 1 FROM parameter_set s WHERE s.supersedes_id = p.id);

CREATE TABLE IF NOT EXISTS engine_run (
    id                text PRIMARY KEY DEFAULT new_id(),
    client_id         text NOT NULL REFERENCES client (id),
    engine            text NOT NULL CHECK (engine ~ '^[a-z][a-z0-9_]*$'),
    parameter_set_id  text REFERENCES parameter_set (id),
    request           jsonb NOT NULL,
    requested_by_kind text NOT NULL CHECK (requested_by_kind IN ('client', 'curator', 'system')),
    requested_by_ref  text NOT NULL,
    run_id            text,
    artefact_id       text,
    status            text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    error             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    started_at        timestamptz,
    finished_at       timestamptz,
    data_class        smallint NOT NULL DEFAULT 2 CHECK (data_class BETWEEN 2 AND 3),
    CONSTRAINT engine_run_success_has_artefact CHECK (status <> 'succeeded' OR artefact_id IS NOT NULL),
    CONSTRAINT engine_run_failure_has_error CHECK (status <> 'failed' OR error IS NOT NULL),
    CONSTRAINT engine_run_finished_iff_terminal CHECK ((finished_at IS NOT NULL) = (status IN ('succeeded', 'failed')))
);
CREATE INDEX IF NOT EXISTS engine_run_by_client ON engine_run (client_id, engine, created_at);

-- Status moves forward only (queued -> running -> succeeded | failed, or queued -> failed); a
-- finished run is immutable; only the outcome columns change.
CREATE OR REPLACE FUNCTION engine_run_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path FROM CURRENT AS $$
BEGIN
    IF erasing_row(TG_TABLE_SCHEMA, 'client_id', to_jsonb(OLD)) THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'engine_run rows are never deleted: DELETE refused';
    END IF;
    IF OLD.status IN ('succeeded', 'failed') THEN
        RAISE EXCEPTION 'engine_run %: finished (%), immutable', OLD.id, OLD.status;
    END IF;
    IF NOT ((OLD.status = NEW.status)
            OR (OLD.status = 'queued' AND NEW.status IN ('running', 'failed'))
            OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed'))) THEN
        RAISE EXCEPTION 'engine_run %: % -> % is not a permitted transition', OLD.id, OLD.status, NEW.status;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['status', 'run_id', 'artefact_id', 'error', 'started_at', 'finished_at'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'run_id', 'artefact_id', 'error', 'started_at', 'finished_at']) THEN
        RAISE EXCEPTION 'engine_run %: only the outcome columns may change', OLD.id;
    END IF;
    RETURN NEW;
END
$$;

-- ============================================================================================
-- Migration record
-- ============================================================================================

CREATE TABLE IF NOT EXISTS migration_run (
    id             text PRIMARY KEY DEFAULT new_id(),
    source_path    text NOT NULL,
    source_sha256  text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    alembic_head   text NOT NULL,
    txid           bigint NOT NULL DEFAULT txid_current(),
    reconciliation jsonb NOT NULL,
    ran_at         timestamptz NOT NULL DEFAULT now(),
    data_class     smallint NOT NULL DEFAULT 0 CHECK (data_class BETWEEN 0 AND 3)
);

-- ============================================================================================
-- Triggers
-- ============================================================================================

DROP TRIGGER IF EXISTS curator_guard ON curator;
CREATE TRIGGER curator_guard BEFORE UPDATE OR DELETE ON curator
    FOR EACH ROW EXECUTE FUNCTION guard_update('', 'revoked_at,revoked_reason', 'display_name,email,role_label');

DROP TRIGGER IF EXISTS client_guard ON client;
CREATE TRIGGER client_guard BEFORE UPDATE OR DELETE ON client
    FOR EACH ROW EXECUTE FUNCTION guard_update('id', 'onboarding_completed_at', 'display_name,locale,stage_hint,archived_at');
DROP TRIGGER IF EXISTS client_actor ON client;
CREATE TRIGGER client_actor BEFORE INSERT ON client
    FOR EACH ROW EXECUTE FUNCTION check_actor('created_by_kind', 'created_by_ref');

DROP TRIGGER IF EXISTS consent_guard ON consent;
CREATE TRIGGER consent_guard BEFORE UPDATE OR DELETE ON consent
    FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'withdrawn_at', 'notes');

DROP TRIGGER IF EXISTS content_record_append_only ON content_record;
CREATE TRIGGER content_record_append_only BEFORE UPDATE OR DELETE ON content_record
    FOR EACH ROW EXECUTE FUNCTION refuse_change('saved_by_ref');
DROP TRIGGER IF EXISTS content_record_version ON content_record;
CREATE TRIGGER content_record_version BEFORE INSERT ON content_record
    FOR EACH ROW EXECUTE FUNCTION content_record_version();
DROP TRIGGER IF EXISTS content_record_actor ON content_record;
CREATE TRIGGER content_record_actor BEFORE INSERT ON content_record
    FOR EACH ROW EXECUTE FUNCTION check_actor('saved_by_kind', 'saved_by_ref');

DROP TRIGGER IF EXISTS answer_check ON answer;
CREATE TRIGGER answer_check BEFORE INSERT ON answer
    FOR EACH ROW EXECUTE FUNCTION answer_check();
DROP TRIGGER IF EXISTS answer_guard ON answer;
CREATE TRIGGER answer_guard BEFORE UPDATE OR DELETE ON answer
    FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'superseded_at,superseded_by_id', '');
DROP TRIGGER IF EXISTS answer_actor ON answer;
CREATE TRIGGER answer_actor BEFORE INSERT ON answer
    FOR EACH ROW EXECUTE FUNCTION check_actor('answered_by_kind', 'answered_by_ref');

DROP TRIGGER IF EXISTS submission_append_only ON submission;
CREATE TRIGGER submission_append_only BEFORE UPDATE OR DELETE ON submission
    FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id');

DROP TRIGGER IF EXISTS curator_session_append_only ON curator_session;
CREATE TRIGGER curator_session_append_only BEFORE UPDATE OR DELETE ON curator_session
    FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id');
DROP TRIGGER IF EXISTS curator_session_event_append_only ON curator_session_event;
CREATE TRIGGER curator_session_event_append_only BEFORE UPDATE OR DELETE ON curator_session_event
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

DROP TRIGGER IF EXISTS decision_stamp ON decision;
CREATE TRIGGER decision_stamp BEFORE INSERT ON decision
    FOR EACH ROW EXECUTE FUNCTION decision_stamp();
DROP TRIGGER IF EXISTS decision_append_only ON decision;
CREATE TRIGGER decision_append_only BEFORE UPDATE OR DELETE ON decision
    FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id');

DROP TRIGGER IF EXISTS household_c09 ON household;
CREATE TRIGGER household_c09 BEFORE INSERT OR UPDATE OR DELETE ON household
    FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_household', 'household_id', '');
DROP TRIGGER IF EXISTS household_link ON household;
CREATE TRIGGER household_link AFTER INSERT OR UPDATE ON household
    FOR EACH ROW EXECUTE FUNCTION plan_link('decision_household', 'household_id');

DROP TRIGGER IF EXISTS household_member_c09 ON household_member;
CREATE TRIGGER household_member_c09 BEFORE INSERT OR UPDATE OR DELETE ON household_member
    FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_household_member', 'household_member_id', '');
DROP TRIGGER IF EXISTS household_member_link ON household_member;
CREATE TRIGGER household_member_link AFTER INSERT OR UPDATE ON household_member
    FOR EACH ROW EXECUTE FUNCTION plan_link('decision_household_member', 'household_member_id');

DROP TRIGGER IF EXISTS position_c09 ON position;
CREATE TRIGGER position_c09 BEFORE INSERT OR UPDATE OR DELETE ON position
    FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_position', 'position_id', 'client_id');
DROP TRIGGER IF EXISTS position_link ON position;
CREATE TRIGGER position_link AFTER INSERT OR UPDATE ON position
    FOR EACH ROW EXECUTE FUNCTION plan_link('decision_position', 'position_id');

DROP TRIGGER IF EXISTS goal_c09 ON goal;
CREATE TRIGGER goal_c09 BEFORE INSERT OR UPDATE OR DELETE ON goal
    FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_goal', 'goal_id', 'client_id');
DROP TRIGGER IF EXISTS goal_link ON goal;
CREATE TRIGGER goal_link AFTER INSERT OR UPDATE ON goal
    FOR EACH ROW EXECUTE FUNCTION plan_link('decision_goal', 'goal_id');

DROP TRIGGER IF EXISTS client_fact_c09 ON client_fact;
CREATE TRIGGER client_fact_c09 BEFORE INSERT OR UPDATE OR DELETE ON client_fact
    FOR EACH ROW EXECUTE FUNCTION plan_guard('decision_client_fact', 'client_fact_id', 'client_id');
DROP TRIGGER IF EXISTS client_fact_link ON client_fact;
CREATE TRIGGER client_fact_link AFTER INSERT OR UPDATE ON client_fact
    FOR EACH ROW EXECUTE FUNCTION plan_link('decision_client_fact', 'client_fact_id');

DROP TRIGGER IF EXISTS goal_funding_c09 ON goal_funding;
CREATE TRIGGER goal_funding_c09 BEFORE INSERT OR UPDATE OR DELETE ON goal_funding
    FOR EACH ROW EXECUTE FUNCTION goal_link_guard();
DROP TRIGGER IF EXISTS goal_owner_c09 ON goal_owner;
CREATE TRIGGER goal_owner_c09 BEFORE INSERT OR UPDATE OR DELETE ON goal_owner
    FOR EACH ROW EXECUTE FUNCTION goal_link_guard();

DROP TRIGGER IF EXISTS decision_position_guard ON decision_position;
CREATE TRIGGER decision_position_guard BEFORE INSERT ON decision_position
    FOR EACH ROW EXECUTE FUNCTION decision_link_guard();
DROP TRIGGER IF EXISTS decision_position_append_only ON decision_position;
CREATE TRIGGER decision_position_append_only BEFORE UPDATE OR DELETE ON decision_position
    FOR EACH ROW EXECUTE FUNCTION refuse_change('*');
DROP TRIGGER IF EXISTS decision_goal_guard ON decision_goal;
CREATE TRIGGER decision_goal_guard BEFORE INSERT ON decision_goal
    FOR EACH ROW EXECUTE FUNCTION decision_link_guard();
DROP TRIGGER IF EXISTS decision_goal_append_only ON decision_goal;
CREATE TRIGGER decision_goal_append_only BEFORE UPDATE OR DELETE ON decision_goal
    FOR EACH ROW EXECUTE FUNCTION refuse_change('*');
DROP TRIGGER IF EXISTS decision_household_guard ON decision_household;
CREATE TRIGGER decision_household_guard BEFORE INSERT ON decision_household
    FOR EACH ROW EXECUTE FUNCTION decision_link_guard();
DROP TRIGGER IF EXISTS decision_household_append_only ON decision_household;
CREATE TRIGGER decision_household_append_only BEFORE UPDATE OR DELETE ON decision_household
    FOR EACH ROW EXECUTE FUNCTION refuse_change('*');
DROP TRIGGER IF EXISTS decision_household_member_guard ON decision_household_member;
CREATE TRIGGER decision_household_member_guard BEFORE INSERT ON decision_household_member
    FOR EACH ROW EXECUTE FUNCTION decision_link_guard();
DROP TRIGGER IF EXISTS decision_household_member_append_only ON decision_household_member;
CREATE TRIGGER decision_household_member_append_only BEFORE UPDATE OR DELETE ON decision_household_member
    FOR EACH ROW EXECUTE FUNCTION refuse_change('*');
DROP TRIGGER IF EXISTS decision_client_fact_guard ON decision_client_fact;
CREATE TRIGGER decision_client_fact_guard BEFORE INSERT ON decision_client_fact
    FOR EACH ROW EXECUTE FUNCTION decision_link_guard();
DROP TRIGGER IF EXISTS decision_client_fact_append_only ON decision_client_fact;
CREATE TRIGGER decision_client_fact_append_only BEFORE UPDATE OR DELETE ON decision_client_fact
    FOR EACH ROW EXECUTE FUNCTION refuse_change('*');

DROP TRIGGER IF EXISTS thread_guard ON thread;
CREATE TRIGGER thread_guard BEFORE UPDATE OR DELETE ON thread
    FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'closed_at,closed_by_kind,closed_by_ref', 'subject');
DROP TRIGGER IF EXISTS thread_actor ON thread;
CREATE TRIGGER thread_actor BEFORE INSERT OR UPDATE ON thread
    FOR EACH ROW EXECUTE FUNCTION check_actor('opened_by_kind', 'opened_by_ref', 'closed_by_kind', 'closed_by_ref');

DROP TRIGGER IF EXISTS thread_message_check ON thread_message;
CREATE TRIGGER thread_message_check BEFORE INSERT ON thread_message
    FOR EACH ROW EXECUTE FUNCTION thread_message_check();
DROP TRIGGER IF EXISTS thread_message_actor ON thread_message;
CREATE TRIGGER thread_message_actor BEFORE INSERT ON thread_message
    FOR EACH ROW EXECUTE FUNCTION check_actor('author_kind', 'author_ref');
DROP TRIGGER IF EXISTS thread_message_append_only ON thread_message;
CREATE TRIGGER thread_message_append_only BEFORE UPDATE OR DELETE ON thread_message
    FOR EACH ROW EXECUTE FUNCTION refuse_change('*');

DROP TRIGGER IF EXISTS report_request_guard ON report_request;
CREATE TRIGGER report_request_guard BEFORE UPDATE OR DELETE ON report_request
    FOR EACH ROW EXECUTE FUNCTION guard_update('client_id', 'withdrawn_at', '');
DROP TRIGGER IF EXISTS report_request_check ON report_request;
CREATE TRIGGER report_request_check BEFORE UPDATE ON report_request
    FOR EACH ROW EXECUTE FUNCTION report_request_check();
DROP TRIGGER IF EXISTS report_request_actor ON report_request;
CREATE TRIGGER report_request_actor BEFORE INSERT ON report_request
    FOR EACH ROW EXECUTE FUNCTION check_actor('requested_by_kind', 'requested_by_ref');

DROP TRIGGER IF EXISTS report_check ON report;
CREATE TRIGGER report_check BEFORE INSERT ON report
    FOR EACH ROW EXECUTE FUNCTION report_check();
DROP TRIGGER IF EXISTS report_append_only ON report;
CREATE TRIGGER report_append_only BEFORE UPDATE OR DELETE ON report
    FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id');

DROP TRIGGER IF EXISTS approval_request_check ON approval_request;
CREATE TRIGGER approval_request_check BEFORE INSERT ON approval_request
    FOR EACH ROW EXECUTE FUNCTION approval_request_check();
DROP TRIGGER IF EXISTS approval_request_append_only ON approval_request;
CREATE TRIGGER approval_request_append_only BEFORE UPDATE OR DELETE ON approval_request
    FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id');

DROP TRIGGER IF EXISTS approval_event_check ON approval_event;
CREATE TRIGGER approval_event_check BEFORE INSERT ON approval_event
    FOR EACH ROW EXECUTE FUNCTION approval_event_check();
DROP TRIGGER IF EXISTS approval_event_actor ON approval_event;
CREATE TRIGGER approval_event_actor BEFORE INSERT ON approval_event
    FOR EACH ROW EXECUTE FUNCTION check_actor('actor_kind', 'actor_ref');
DROP TRIGGER IF EXISTS approval_event_append_only ON approval_event;
CREATE TRIGGER approval_event_append_only BEFORE UPDATE OR DELETE ON approval_event
    FOR EACH ROW EXECUTE FUNCTION refuse_change('*');

DROP TRIGGER IF EXISTS parameter_set_check ON parameter_set;
CREATE TRIGGER parameter_set_check BEFORE INSERT ON parameter_set
    FOR EACH ROW EXECUTE FUNCTION parameter_set_check();
DROP TRIGGER IF EXISTS parameter_set_actor ON parameter_set;
CREATE TRIGGER parameter_set_actor BEFORE INSERT ON parameter_set
    FOR EACH ROW EXECUTE FUNCTION check_actor('=curator', 'finalised_by');
DROP TRIGGER IF EXISTS parameter_set_append_only ON parameter_set;
CREATE TRIGGER parameter_set_append_only BEFORE UPDATE OR DELETE ON parameter_set
    FOR EACH ROW EXECUTE FUNCTION refuse_change('client_id');

DROP TRIGGER IF EXISTS engine_run_guard ON engine_run;
CREATE TRIGGER engine_run_guard BEFORE UPDATE OR DELETE ON engine_run
    FOR EACH ROW EXECUTE FUNCTION engine_run_guard();
DROP TRIGGER IF EXISTS engine_run_actor ON engine_run;
CREATE TRIGGER engine_run_actor BEFORE INSERT ON engine_run
    FOR EACH ROW EXECUTE FUNCTION check_actor('requested_by_kind', 'requested_by_ref');

DROP TRIGGER IF EXISTS migration_run_append_only ON migration_run;
CREATE TRIGGER migration_run_append_only BEFORE UPDATE OR DELETE ON migration_run
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- ============================================================================================
-- Views for the picker and the cockpit
-- ============================================================================================

CREATE OR REPLACE VIEW answer_current AS
    SELECT * FROM answer WHERE superseded_at IS NULL;

CREATE OR REPLACE VIEW client_overview AS
    SELECT c.id, c.display_name, c.locale, c.age_at_registration, c.stage_hint, c.onboarding_completed_at,
           c.archived_at, c.created_at, c.created_by_kind,
           (SELECT count(*) FROM thread_state t WHERE t.client_id = c.id AND t.state = 'awaiting_answer') AS threads_awaiting_answer,
           (SELECT count(*) FROM approval_state a WHERE a.client_id = c.id AND a.state = 'awaiting_curator') AS approvals_awaiting_curator,
           (SELECT count(*) FROM report_request_state r WHERE r.client_id = c.id AND r.state = 'open') AS report_requests_open
      FROM client c;

-- ============================================================================================
-- Purpose of every table and view (Engine Building Guide 7.7), for the catalogue
-- ============================================================================================

COMMENT ON TABLE curator IS 'eigentlich: curators (cockpit users). No credentials: there is no sign-in. Revoked, never deleted (A161); a revoked curator cannot act. K1.';
COMMENT ON TABLE client IS 'eigentlich: client records, listed by the client picker (no sign-in). Age at registration >= 18. Never deleted except by erasure; archived instead. K1.';
COMMENT ON TABLE consent IS 'eigentlich: versioned consent records per client (R-103); withdrawal sets withdrawn_at once, the grant is never deleted. K1.';
COMMENT ON TABLE content_record IS 'eigentlich: versioned content (questionnaires, scoring maps with binds, reference content, knowledge notes), PK (key, version), version = max+1 per key; every save by seed, client or curator is a new version; append-only. K0.';
COMMENT ON VIEW content_current IS 'eigentlich: the latest version of every content key.';
COMMENT ON VIEW scoring_bind_check IS 'eigentlich: every bind of the current scoring maps checked against the current questionnaires; status ok, not_an_option, question_has_no_options, no_question or no_questionnaire.';
COMMENT ON TABLE answer IS 'eigentlich: a client''s answers to questionnaire questions, each naming the content version it answered; one current answer per client, questionnaire and question; superseding (superseded_at, superseded_by_id) is the only update. K2, K3 where the question declares it.';
COMMENT ON VIEW answer_current IS 'eigentlich: the current (not superseded) answers.';
COMMENT ON TABLE submission IS 'eigentlich: intake files as received, whole (A154), unique per client and content hash; append-only. K3.';
COMMENT ON TABLE curator_session IS 'eigentlich: a curator opening a client''s material (C-10 audit subject); append-only. K2.';
COMMENT ON TABLE curator_session_event IS 'eigentlich: the curator audit trail (C-10); append-only, never erased. K2.';
COMMENT ON TABLE decision IS 'eigentlich: decision records (C-09, R-040): every plan change is covered by a decision written in the same transaction (txid); corrections are new rows with corrects_id; append-only. K2.';
COMMENT ON TABLE household IS 'eigentlich: plan table (C-09). A household as stated, with composition_as_of; closed, never deleted. K2.';
COMMENT ON TABLE household_member IS 'eigentlich: plan table (C-09). A person in a household, with or without a client record; adult or dependant. K2.';
COMMENT ON TABLE position IS 'eigentlich: plan table (C-09). A position in the role grid (human or financial capital); deactivated, never deleted. K2.';
COMMENT ON TABLE goal IS 'eigentlich: plan table (C-09). A client goal; deactivated, never deleted. K2.';
COMMENT ON COLUMN position.owner IS 'eigentlich: whose position it is: client or partner (the first other adult of the client''s household); NULL reads as the client (EIG-53).';
COMMENT ON COLUMN goal.contribution_share IS 'eigentlich: the goal''s share of the household''s yearly saving, 0 to 1 (0 to 100 % in the app); NULL not stated; the active goals'' shares sum to at most 1, checked by the app (EIG-59).';
COMMENT ON COLUMN goal.amount_basis IS 'eigentlich: whether target_amount is in today''s francs (today) or in the francs of the target date (future), as the client answered; NULL not stated, read by lbs as today (owner decision 7, EIG-60).';
COMMENT ON TABLE goal_funding IS 'eigentlich: plan link (C-09): which positions fund a goal; a change needs a decision linked to the goal in the same transaction; deactivated, never deleted. K2.';
COMMENT ON TABLE goal_owner IS 'eigentlich: plan link (C-09): which household members own a goal; same rule as goal_funding. K2.';
COMMENT ON TABLE client_fact IS 'eigentlich: plan table (C-09). Stated facts per key (canton, civil status, health, ...); one current per client and key; superseded, never deleted. K1 to K3 per row.';
COMMENT ON TABLE decision_position IS 'eigentlich: which positions a decision covered; written by trigger; append-only. K2.';
COMMENT ON TABLE decision_goal IS 'eigentlich: which goals a decision covered; written by trigger or directly for funding and owner changes; append-only. K2.';
COMMENT ON TABLE decision_household IS 'eigentlich: which households a decision covered; written by trigger; append-only. K2.';
COMMENT ON TABLE decision_household_member IS 'eigentlich: which household members a decision covered; written by trigger; append-only. K2.';
COMMENT ON TABLE decision_client_fact IS 'eigentlich: which client facts a decision covered; written by trigger; append-only. K2.';
COMMENT ON TABLE thread IS 'eigentlich: a client''s question thread; closing (closed_at, set once) is the only update. K2.';
COMMENT ON TABLE thread_message IS 'eigentlich: messages in a thread by the client, a curator or spark7 (the ChatBot, with model, artefact id, sources and unverified numbers); append-only. K2.';
COMMENT ON COLUMN thread_message.basis IS 'eigentlich: what a spark7 (MiniMind) answer rests on, from chat-answer basis: grounded, general or mixed; NULL for human messages, refusals and answers stored before 29.09.2026 (EIG-50).';
COMMENT ON VIEW thread_state IS 'eigentlich: each thread with its state: awaiting_answer, answered or closed.';
COMMENT ON TABLE report_request IS 'eigentlich: a request for a report or an update; withdrawal (withdrawn_at, set once, only while unfulfilled) is the only update. K2.';
COMMENT ON COLUMN report_request.basis IS 'eigentlich: the basis the report was asked in: nominal or real (today''s francs); NULL is nominal (EIG-62).';
COMMENT ON COLUMN report_request.scenario IS 'eigentlich: a scenario Regime asked for (aggregation''s policy name or a scenario regime id); NULL is the base Regime of the current parameter set (EIG-63).';
COMMENT ON TABLE report IS 'eigentlich: a report produced for a request, with the report engine''s artefact id and the LBS and Allocation artefacts it rests on; append-only. K2.';
COMMENT ON VIEW report_request_state IS 'eigentlich: each report request with its state: open, fulfilled or withdrawn, and its latest report.';
COMMENT ON TABLE approval_request IS 'eigentlich: a client''s request that a curator approve a report, an update or an AI-drafted answer; one per item; without a request nothing waits; append-only. K2.';
COMMENT ON TABLE approval_event IS 'eigentlich: the one terminal event of an approval request: approved or revision_sent (curator) or withdrawn (client); append-only. K2.';
COMMENT ON VIEW approval_state IS 'eigentlich: each approval request with its state: awaiting_curator, approved, revised or withdrawn.';
COMMENT ON TABLE parameter_set IS 'eigentlich: engine inputs finalised by a curator per client and engine (e.g. pcp-mandate@1.0.0), a linear chain through supersedes_id; append-only. K2.';
COMMENT ON VIEW parameter_set_current IS 'eigentlich: the parameter sets not superseded, one per client and engine.';
COMMENT ON TABLE engine_run IS 'eigentlich: calls to engines (pcp, lbs, report, chatbot) on a client''s behalf, with request, run id, artefact id and status; status moves forward only; never deleted. K2.';
COMMENT ON TABLE migration_run IS 'eigentlich: each migration from the prototype SQLite file, with its source hash, alembic head, transaction id and per-table reconciliation; append-only. K0.';
COMMENT ON VIEW client_overview IS 'eigentlich: the client picker: every client with open thread, approval and report-request counts.';
