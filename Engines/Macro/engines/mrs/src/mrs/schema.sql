-- mrs store. Idempotent: safe to run on every start.
--
-- Tables use bare names and land in the engine's own schema, pinned by search_path.
-- Conventions as in honi: timestamps are ISO-8601 UTC TEXT, JSON is TEXT with a _json
-- suffix, floats are DOUBLE PRECISION (never REAL), and ids are content hashes with a prefix.
--
-- Calibrations and artefacts are append-only, enforced here rather than trusted to the
-- code: an UPDATE or DELETE raises.

CREATE TABLE IF NOT EXISTS calibration (
    version           TEXT PRIMARY KEY,                -- semantic version
    calibration_hash  TEXT NOT NULL,                   -- CAL-<16 hex> of the payload
    parent_version    TEXT REFERENCES calibration(version),
    created_at        TEXT NOT NULL,
    payload_json      TEXT NOT NULL
);
COMMENT ON TABLE calibration IS
    'Versioned, immutable mrs parameter sets: segment and indicator weights, kernels, grid, windows and thresholds.';

CREATE TABLE IF NOT EXISTS artefact (
    artefact_id          TEXT PRIMARY KEY,             -- MRS-<16 hex> of the payload
    idempotency_key      TEXT NOT NULL UNIQUE,         -- IDK-<16 hex>
    snapshot_id          TEXT NOT NULL,                -- the datafeed snapshot read
    calibration_version  TEXT NOT NULL REFERENCES calibration(version),
    contract_version     TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    payload_json         TEXT NOT NULL
);
COMMENT ON TABLE artefact IS
    'Published MarketRiskSignal artefacts (mrs-signal contract), one per idempotency key: sub-indicators, segments and the 25-state distribution per economy and month, zero optimism shift, regime_id null.';

CREATE TABLE IF NOT EXISTS run (
    run_id               TEXT PRIMARY KEY,             -- RUN-<16 hex>
    seq                  BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,  -- insertion order, for GET /runs
    idempotency_key      TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    snapshot_id          TEXT NOT NULL,
    calibration_version  TEXT NOT NULL,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    wall_clock_ms        DOUBLE PRECISION,
    request_json         TEXT NOT NULL,
    artefact_id          TEXT REFERENCES artefact(artefact_id),
    warnings_json        TEXT NOT NULL DEFAULT '[]',
    coverage_json        TEXT,
    provenance_json      TEXT,
    error                TEXT
);
COMMENT ON TABLE run IS
    'One row per mrs run attempt: status, timings, warnings, coverage and provenance.';

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

-- Reference data: recorded MATLAB output the port is reconciled against. Loaded by
-- `python -m mrs load-reference`, never written by a run, append-only like the artefacts.

CREATE TABLE IF NOT EXISTS reference_source (
    source_id         TEXT PRIMARY KEY,                -- REF-<16 hex> of the file's sha256
    kind              TEXT NOT NULL CHECK (kind IN ('signal')),
    url               TEXT NOT NULL,
    file_name         TEXT NOT NULL,
    sha256            TEXT NOT NULL UNIQUE,
    byte_size         BIGINT NOT NULL,
    produced_by       TEXT NOT NULL,                   -- the MATLAB script that wrote it
    optimism          TEXT NOT NULL,                   -- MATLAB Opti_Scale it ran with
    pairs_with        TEXT NOT NULL,                   -- the input it was computed from
    pairs_with_sha256 TEXT NOT NULL,
    first_date        TEXT NOT NULL,                   -- month end of month 1 (the file has no dates)
    months            INTEGER NOT NULL,
    loaded_at         TEXT NOT NULL,
    note              TEXT NOT NULL DEFAULT ''
);
COMMENT ON TABLE reference_source IS
    'One row per recorded MATLAB export mrs is reconciled against: where it came from, its checksum, the script and optimism that produced it, and the input it pairs with.';

CREATE TABLE IF NOT EXISTS reference_signal (
    source_id    TEXT NOT NULL REFERENCES reference_source(source_id),
    segment      TEXT NOT NULL CHECK (segment IN ('business_cycle', 'investment', 'market_behaviour', 'market_stress')),
    economy      TEXT NOT NULL,                        -- datafeed country code, or a blend code
    matlab_name  TEXT NOT NULL,                        -- the field name in the MATLAB struct
    is_blend     BOOLEAN NOT NULL,                     -- true for EMCN, a fixed mix of economies
    month_index  INTEGER NOT NULL CHECK (month_index >= 1),
    date         TEXT NOT NULL,                        -- month end, reconstructed from month_index
    probs        DOUBLE PRECISION[] NOT NULL CHECK (array_length(probs, 1) = 25),
    PRIMARY KEY (source_id, segment, economy, month_index)
);
COMMENT ON TABLE reference_signal IS
    'MATLAB WM from the CIO site signal export: per segment, economy and month the weighted kernel column (25 states, 1 cautious to 25 aggressive). Reference for the golden test; not a distribution.';

DROP TRIGGER IF EXISTS reference_source_append_only ON reference_source;
CREATE TRIGGER reference_source_append_only BEFORE UPDATE OR DELETE ON reference_source
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

DROP TRIGGER IF EXISTS reference_signal_append_only ON reference_signal;
CREATE TRIGGER reference_signal_append_only BEFORE UPDATE OR DELETE ON reference_signal
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
