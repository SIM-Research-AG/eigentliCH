-- chatbot store. Idempotent: safe to run on every start.
--
-- Tables use bare names and land in the engine's own schema, pinned by search_path.
-- Conventions of the other engines: timestamps are ISO-8601 UTC TEXT, JSON is TEXT with a _json suffix,
-- floats are DOUBLE PRECISION (never REAL), ids are content hashes with a prefix.
--
-- Calibrations and answers are append-only, enforced here rather than trusted to the code: an UPDATE or
-- DELETE raises. The engine stores no client data beyond what a caller sent with a question and the
-- answer given to it.

CREATE TABLE IF NOT EXISTS calibration (
    version           TEXT PRIMARY KEY,                -- semantic version
    calibration_hash  TEXT NOT NULL,                   -- CAL-<16 hex> of the payload
    parent_version    TEXT REFERENCES calibration(version),
    created_at        TEXT NOT NULL,
    payload_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artefact (
    artefact_id       TEXT PRIMARY KEY,                -- CHB-<16 hex> of the payload
    idempotency_key   TEXT NOT NULL UNIQUE,            -- IDK-<16 hex>: one stored answer per key
    contract_version  TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    language          TEXT NOT NULL,
    model             TEXT,                            -- NULL when no model was called
    prompt_version    TEXT NOT NULL,
    refused           BOOLEAN NOT NULL,
    unverified_count  INTEGER NOT NULL,
    latency_ms        DOUBLE PRECISION NOT NULL,
    payload_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run (
    run_id            TEXT PRIMARY KEY,                -- RUN-<16 hex>
    idempotency_key   TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    wall_clock_ms     DOUBLE PRECISION,
    request_json      TEXT NOT NULL,
    artefact_id       TEXT REFERENCES artefact(artefact_id),
    warnings_json     TEXT NOT NULL DEFAULT '[]',
    provenance_json   TEXT,
    error             TEXT
);

CREATE INDEX IF NOT EXISTS run_by_key ON run (idempotency_key, status);

CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$;

DROP TRIGGER IF EXISTS calibration_append_only ON calibration;
CREATE TRIGGER calibration_append_only BEFORE UPDATE OR DELETE ON calibration
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

DROP TRIGGER IF EXISTS artefact_append_only ON artefact;
CREATE TRIGGER artefact_append_only BEFORE UPDATE OR DELETE ON artefact
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- Engine Building Guide 7.7: every table states its purpose, in the store, for the catalogue.
COMMENT ON TABLE calibration IS 'chatbot: versioned parameter sets (generation, limits, number check, client markers, fixed texts); append-only';
COMMENT ON TABLE artefact IS 'chatbot: published answers (chat-answer), one per idempotency key (inputs + model + prompt version), with cited grounding ids and the number check; append-only';
COMMENT ON TABLE run IS 'chatbot: one row per POST /run or POST /answer attempt, with status, warnings and provenance';
