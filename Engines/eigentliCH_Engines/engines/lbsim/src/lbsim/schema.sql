-- lbsim store (spec 3.10). Idempotent: safe to run on every start.
--
-- Tables use bare names and land in the engine's own schema, pinned by search_path.
-- Conventions of the family: timestamps are ISO-8601 UTC TEXT, JSON is TEXT with a _json suffix, floats are
-- DOUBLE PRECISION (never REAL), ids are content hashes with a prefix.
--
-- Calibrations, artefacts and run events are append-only, enforced here rather than trusted to the code: an
-- UPDATE or DELETE raises. A run is a state machine and is updated in place; every transition is also written
-- to run_event.
--
-- Client data: none is copied here. run.request_json holds ids and options only (the sheet's id, the allocation's
-- id, the scenarios, the horizon, the seed); the household lives in lbs. The artefacts carry figures derived for
-- an opaque client_ref; retention and access are the same open point as in lbs (README).

CREATE TABLE IF NOT EXISTS calibration (
    version           TEXT PRIMARY KEY,
    calibration_hash  TEXT NOT NULL,
    parent_version    TEXT REFERENCES calibration(version),
    created_at        TEXT NOT NULL,
    payload_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artefact (
    artefact_id            TEXT PRIMARY KEY,           -- LSF-, LSP- or LSO-<16 hex> of the payload
    kind                   TEXT NOT NULL CHECK (kind IN ('findings', 'paths', 'plan')),
    client_ref             TEXT NOT NULL,              -- opaque client reference, never a name
    life_balance_sheet_id  TEXT NOT NULL,              -- LBS-<16 hex>: the sheet it was computed on (LBSIM-04)
    idempotency_key        TEXT NOT NULL UNIQUE,       -- IDK-<16 hex> (section 3.9)
    contract_version       TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    payload_json           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS artefact_by_client ON artefact (client_ref, created_at);
CREATE INDEX IF NOT EXISTS artefact_by_sheet ON artefact (life_balance_sheet_id, kind);

CREATE TABLE IF NOT EXISTS run (
    run_id                 TEXT PRIMARY KEY,           -- RUN-<16 hex>
    kind                   TEXT NOT NULL CHECK (kind IN ('outlook', 'plan')),
    status                 TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    failure_kind           TEXT CHECK (failure_kind IN ('timed_out', 'superseded', 'cancelled', 'solver', 'upstream')),
    idempotency_key        TEXT NOT NULL,
    client_ref             TEXT NOT NULL,
    life_balance_sheet_id  TEXT NOT NULL,
    request_json           TEXT NOT NULL,              -- ids and options only, never client data
    requested_by_kind      TEXT NOT NULL CHECK (requested_by_kind IN ('client', 'curator', 'system')),
    requested_by_ref       TEXT,
    priority               INTEGER NOT NULL DEFAULT 0, -- curator 2, client 1, system 0: the queue takes the highest first
    budget_s               DOUBLE PRECISION,
    queued_at              TEXT NOT NULL,
    started_at             TEXT,
    finished_at            TEXT,
    heartbeat_at           TEXT,
    wall_clock_ms          DOUBLE PRECISION,
    attempts               INTEGER NOT NULL DEFAULT 0,
    worker                 TEXT,
    cancel_requested       TEXT CHECK (cancel_requested IN ('cancelled', 'superseded')),
    progress_json          TEXT,
    artefact_ids_json      TEXT NOT NULL DEFAULT '[]',
    error                  TEXT
);

CREATE INDEX IF NOT EXISTS run_queue ON run (status, priority DESC, queued_at);
CREATE INDEX IF NOT EXISTS run_by_client ON run (client_ref, kind, status);
CREATE INDEX IF NOT EXISTS run_by_key ON run (idempotency_key, status);

CREATE TABLE IF NOT EXISTS run_event (
    event_id     BIGSERIAL PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES run(run_id),
    at           TEXT NOT NULL,
    event        TEXT NOT NULL,                        -- queued, started, heartbeat_lost, requeued, superseded, ...
    detail_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS run_event_by_run ON run_event (run_id, event_id);

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

DROP TRIGGER IF EXISTS run_event_append_only ON run_event;
CREATE TRIGGER run_event_append_only BEFORE UPDATE OR DELETE ON run_event
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- Engine Building Guide 7.7: every table states its purpose, in the store, for the catalogue.
COMMENT ON TABLE calibration IS 'lbsim: versioned parameter sets (the draft Params overrides, the market and property models, the optimiser settings, the AHV/BVG, canton and findings-text records); append-only';
COMMENT ON TABLE artefact IS 'lbsim: published LifeBalanceFindings (LSF), LifeBalancePaths (LSP) and LifeBalancePlan (LSO) per opaque client_ref and Life Balance Sheet, keyed by content hash and unique on idempotency key; append-only';
COMMENT ON TABLE run IS 'lbsim: one row per outlook run (findings and paths, synchronous) and per plan run (the background optimiser queue: priority, heartbeat, attempts, cancel and supersede); ids and options only, no client data';
COMMENT ON TABLE run_event IS 'lbsim: every state transition of a run (queued, started, requeued, superseded, cancelled, finished); append-only';
