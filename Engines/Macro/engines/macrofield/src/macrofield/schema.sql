-- macrofield store. Idempotent: safe to run on every start.
--
-- Tables use bare names and land in the engine's own schema, pinned by search_path.
-- Conventions shared with the honi and Instruments engines: timestamps are ISO-8601 UTC TEXT,
-- JSON is TEXT with a _json suffix, floats are DOUBLE PRECISION (never REAL), ids are content
-- hashes with a prefix.
--
-- Snapshots, their files and observations, calibrations and artefacts are append-only,
-- enforced here: an UPDATE or DELETE raises. New data is a new snapshot; a changed parameter set
-- is a new calibration version; a changed output is a new artefact.

-- The static data. A snapshot is the frozen raw folder, identified by the hash of its manifest.
CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id       TEXT PRIMARY KEY,                -- SNP-<16 hex> of (path, sha256) pairs
    frozen_on         TEXT NOT NULL,                   -- the snapshot's as_of
    loaded_at         TEXT NOT NULL,
    manifest_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_file (
    snapshot_id       TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    path              TEXT NOT NULL,                   -- relative to the raw folder
    sha256            TEXT NOT NULL,
    bytes             BIGINT NOT NULL,
    url               TEXT NOT NULL,
    retrieved_on      TEXT NOT NULL,
    origin            TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, path)
);

-- One published value. ``area`` is the source's own country code (World Bank ISO3, BIS
-- two-letter, PWT ISO3), so a snapshot does not depend on any calibration's economy registry.
-- A published gap is a row with a NULL value, not a missing row.
CREATE TABLE IF NOT EXISTS observation (
    snapshot_id       TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    series_id         TEXT NOT NULL,
    area              TEXT NOT NULL,
    year              INTEGER NOT NULL,
    value             DOUBLE PRECISION,
    source_path       TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, series_id, area, year)
);

CREATE TABLE IF NOT EXISTS calibration (
    version           TEXT PRIMARY KEY,                -- semantic version
    calibration_hash  TEXT NOT NULL,                   -- CAL-<16 hex> of the payload
    parent_version    TEXT REFERENCES calibration(version),
    created_at        TEXT NOT NULL,
    payload_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artefact (
    artefact_id       TEXT PRIMARY KEY,                -- MFS-<16 hex> of the payload
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

-- The source catalogue (sources.CATALOGUE) as a table, so the series this engine reads are
-- described where the data is (Guide section 7). Rewritten from the code on every start; the
-- code is the definition, this is its published copy. Not append-only.
CREATE TABLE IF NOT EXISTS series_registry (
    series_id         TEXT PRIMARY KEY,                -- e.g. bis.total_credit
    provider          TEXT NOT NULL,                   -- world_bank, bis, pwt, bundesbank, imf, jst
    code              TEXT NOT NULL,                   -- the provider's own code
    description       TEXT NOT NULL,                   -- the provider's name for the series
    units             TEXT NOT NULL,
    frequency         TEXT NOT NULL,                   -- A, Q or M
    model_role        TEXT NOT NULL,                   -- what the three-body model uses it for
    lead_lag          TEXT NOT NULL,                   -- leading, concurrent or lagging
    scale_critical    BOOLEAN NOT NULL,                -- a level error moves an economy against a threshold
    updated_at        TEXT NOT NULL
);

COMMENT ON TABLE snapshot IS 'Frozen static data snapshots: the raw source folder, identified by the hash of its manifest.';
COMMENT ON TABLE source_file IS 'Every raw file of a snapshot: path, SHA-256, size, URL and retrieval date.';
COMMENT ON TABLE observation IS 'The published annual values of every series, per snapshot and source area code. A published gap is a NULL value.';
COMMENT ON TABLE calibration IS 'Versioned, immutable calibrations of the three-body model, including the economy registry.';
COMMENT ON TABLE artefact IS 'Published MacroState artefacts, keyed by idempotency key.';
COMMENT ON TABLE run IS 'Every run: status, timings, warnings, coverage and provenance.';
COMMENT ON TABLE series_registry IS 'The series macrofield reads: provider, code, official name, units, frequency and the role each plays in the three-body model. Written from sources.CATALOGUE on every start.';

CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$;

DROP TRIGGER IF EXISTS snapshot_append_only ON snapshot;
CREATE TRIGGER snapshot_append_only BEFORE UPDATE OR DELETE ON snapshot
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

DROP TRIGGER IF EXISTS source_file_append_only ON source_file;
CREATE TRIGGER source_file_append_only BEFORE UPDATE OR DELETE ON source_file
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

DROP TRIGGER IF EXISTS observation_append_only ON observation;
CREATE TRIGGER observation_append_only BEFORE UPDATE OR DELETE ON observation
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

DROP TRIGGER IF EXISTS calibration_append_only ON calibration;
CREATE TRIGGER calibration_append_only BEFORE UPDATE OR DELETE ON calibration
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

DROP TRIGGER IF EXISTS artefact_append_only ON artefact;
CREATE TRIGGER artefact_append_only BEFORE UPDATE OR DELETE ON artefact
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
