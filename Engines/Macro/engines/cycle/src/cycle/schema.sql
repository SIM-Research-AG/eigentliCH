-- cycle store. Idempotent: safe to run on every start.
--
-- Tables use bare names and land in the engine's own schema, pinned by search_path.
-- Conventions carried over from the Instruments engine: timestamps are ISO-8601 UTC TEXT,
-- JSON is TEXT with a _json suffix, floats are DOUBLE PRECISION (never REAL), and ids are
-- content hashes with a prefix.
--
-- Calibrations and artefacts are append-only, enforced here rather than trusted to the
-- code: an UPDATE or DELETE raises. A changed parameter set is a new version; a changed
-- output is a new artefact with a new id.

CREATE TABLE IF NOT EXISTS calibration (
    version           TEXT PRIMARY KEY,                -- semantic version
    calibration_hash  TEXT NOT NULL,                   -- CAL-<16 hex> of the payload
    parent_version    TEXT REFERENCES calibration(version),
    created_at        TEXT NOT NULL,
    payload_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artefact (
    artefact_id       TEXT PRIMARY KEY,                -- CYS-<16 hex> of the payload
    idempotency_key   TEXT NOT NULL UNIQUE,            -- IDK-<16 hex>
    contract_version  TEXT NOT NULL,
    created_at        TEXT NOT NULL,
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
    coverage_json     TEXT,
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

-- Every table states its purpose (Engine Building Guide section 7.7); the SQL Metadata
-- catalogue reads these comments.
COMMENT ON TABLE calibration IS 'cycle: versioned parameter sets of the cycle model (periods, phase anchors, superposition weights, capital reset per economy), append-only';
COMMENT ON TABLE artefact IS 'cycle: published CycleState artefacts (five nested cycles per economy, their superposition, alignment and synchrony windows), keyed by content hash and unique on idempotency key, served in the contract version they were stored under, append-only';
COMMENT ON TABLE run IS 'cycle: one row per POST /run attempt, with status, timings, warnings, coverage and provenance';
