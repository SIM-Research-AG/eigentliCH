-- The Instruments store.
--
-- **Every floating-point column is DOUBLE PRECISION, never REAL.** PostgreSQL's REAL is
-- four bytes and loses ~1.7e-9 on a calibrated profile value. This engine's central claim
-- is that it reproduces a published reference to 5e-16, and a single-precision column
-- would quietly end that. tests/test_store.py asserts that no such column exists.
--
-- No CREATE SCHEMA here: db.py creates the engine's schema and pins the search path on
-- connect, so this file names bare tables and lands wherever it is pointed.
--
-- Under PostgreSQL every table below lands in the engine's own schema (`instruments` by
-- default), because the server is shared with other projects. The search path is pinned
-- on connect, which is why the statements name bare tables.
--
-- No ORM, no migration framework. Every table that holds sourced data
-- carries the SHA-256 of the file it came from, because manual section 9 requires a
-- sourced table to refuse to load rather than fall back on an approximation, and a hash
-- is what makes "this figure came from that file" checkable rather than asserted.
--
-- The store is the boundary between the offline ETL and the engines. Nothing in
-- engines/ or api/ reads a spreadsheet; they read here.

-- ---------------------------------------------------------------------------
-- Provenance
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_file (
    name        TEXT PRIMARY KEY,
    sha256      TEXT NOT NULL,
    byte_size   INTEGER NOT NULL,
    loaded_at   TEXT NOT NULL,           -- ISO-8601 UTC
    origin      TEXT NOT NULL,           -- absolute path the bytes were read from
    note        TEXT NOT NULL DEFAULT ''
);

-- ---------------------------------------------------------------------------
-- The long annual record (Steiner 2021). Population-level, no user data.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS long_series (
    series_key  TEXT NOT NULL,
    year        INTEGER NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    source_file TEXT NOT NULL REFERENCES source_file(name),
    PRIMARY KEY (series_key, year)
);

-- The eight de-trended indicators and the economic cycle built from them.
CREATE TABLE IF NOT EXISTS market_environment (
    year        INTEGER PRIMARY KEY,
    cycle       DOUBLE PRECISION NOT NULL,           -- ec_cycle, in sigma
    phase       INTEGER NOT NULL,        -- 0 crisis .. 4 boom
    inflation   DOUBLE PRECISION NOT NULL            -- raw CPI rate, for the nominal -> real step
);

CREATE TABLE IF NOT EXISTS environment_indicator (
    year         INTEGER NOT NULL,
    name         TEXT NOT NULL,
    residual     DOUBLE PRECISION NOT NULL,          -- de-trended, unsigned
    standardised DOUBLE PRECISION NOT NULL,          -- signed and standardised, as averaged
    PRIMARY KEY (year, name)
);

-- ---------------------------------------------------------------------------
-- The monthly Market Risk Signal. Read by reference; never recomputed here.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS market_risk_signal (
    period      TEXT NOT NULL,           -- YYYY-MM
    state       INTEGER NOT NULL,        -- 1..25, 1 = most cautious
    probability DOUBLE PRECISION NOT NULL,           -- row-normalised to sum to 1
    PRIMARY KEY (period, state)
);

-- Each month's summary reading, so consumers need not re-reduce the distribution.
CREATE TABLE IF NOT EXISTS market_risk_month (
    period       TEXT PRIMARY KEY,
    modal_state  INTEGER NOT NULL,
    mean_state   DOUBLE PRECISION NOT NULL,
    raw_sum      DOUBLE PRECISION NOT NULL,          -- pre-normalisation; the feed is not exact
    in_tolerance INTEGER NOT NULL        -- 0 where |raw_sum - 100| > 0.5
);

-- ---------------------------------------------------------------------------
-- Calibration artefacts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS calibration (
    calibration_id TEXT PRIMARY KEY,     -- CAL-<16 hex>, a hash of the payload
    created_at     TEXT NOT NULL,
    estimator      TEXT NOT NULL,        -- plain_mean | manual_floor
    first_year     INTEGER NOT NULL,
    last_year      INTEGER NOT NULL,
    state_grid     INTEGER NOT NULL,
    params_json    TEXT NOT NULL,        -- every constant, so a run is reproducible
    sources_json   TEXT NOT NULL,        -- {series_key: sha256}
    phase_counts_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calibration_block (
    calibration_id TEXT NOT NULL REFERENCES calibration(calibration_id) ON DELETE CASCADE,
    block_key      TEXT NOT NULL,
    label          TEXT NOT NULL,
    role           TEXT,                 -- null for long_rate: a rate, not a holding
    first_year     INTEGER NOT NULL,
    last_year      INTEGER NOT NULL,
    n_obs_total    INTEGER NOT NULL,
    phase_json     TEXT NOT NULL,        -- [{phase, n_obs, mean, std, method}, ...]
    profile_json   TEXT NOT NULL,        -- 25 values
    methods_json   TEXT NOT NULL,        -- 25 labels
    n_obs_json     TEXT NOT NULL,        -- 25 counts
    PRIMARY KEY (calibration_id, block_key)
);

CREATE TABLE IF NOT EXISTS calibration_role (
    calibration_id   TEXT NOT NULL REFERENCES calibration(calibration_id) ON DELETE CASCADE,
    role             TEXT NOT NULL,
    basis            TEXT NOT NULL,
    members_json     TEXT NOT NULL,
    weights_json     TEXT NOT NULL,
    phase_means_json TEXT NOT NULL,
    profile_json     TEXT NOT NULL,
    methods_json     TEXT NOT NULL,
    n_obs_json       TEXT NOT NULL,
    n_obs_phase_json TEXT NOT NULL,
    PRIMARY KEY (calibration_id, role)
);

-- ---------------------------------------------------------------------------
-- The instrument register. Expandable by data change, not by code change.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS instrument (
    instrument_id TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    ticker        TEXT,
    role          TEXT NOT NULL,         -- gain | income | stabilisation | protection
    asset_class   TEXT NOT NULL,
    region_scope  TEXT NOT NULL DEFAULT 'Global',
    region_geo    TEXT,
    capital_type  TEXT NOT NULL DEFAULT 'Financial',
    currency      TEXT NOT NULL DEFAULT 'CHF',
    liquidity     TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    -- Where a downloaded history came from, and how well it stands in. A proxy is not
    -- the instrument, so the grade travels with the data rather than living in a README.
    -- close | proxy | weak | none  -- see feeds/proxy_map.py.
    proxy_symbol  TEXT,
    proxy_grade   TEXT,
    proxy_note    TEXT,
    -- Economies the instrument is exposed to, as a JSON list of datafeed country codes
    -- (ISO 3166 alpha-2, EU): the key to the Health of Nations Index. [] = no single economy.
    countries_json TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS instrument_return (
    instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id) ON DELETE CASCADE,
    period        TEXT NOT NULL,         -- YYYY-MM
    value         DOUBLE PRECISION NOT NULL,         -- simple monthly return, decimal
    source        TEXT NOT NULL,         -- feed adapter that produced it
    ingested_at   TEXT NOT NULL,
    PRIMARY KEY (instrument_id, period)
);

CREATE INDEX IF NOT EXISTS ix_instrument_return_period
    ON instrument_return(period);

-- The estimated per-instrument profile, one row per instrument per calibration.
CREATE TABLE IF NOT EXISTS instrument_profile (
    instrument_id  TEXT NOT NULL REFERENCES instrument(instrument_id) ON DELETE CASCADE,
    calibration_id TEXT NOT NULL REFERENCES calibration(calibration_id) ON DELETE CASCADE,
    return_set_id  TEXT NOT NULL,
    computed_at    TEXT NOT NULL,
    coverage       TEXT NOT NULL,        -- the weakest method present
    n_obs_total    INTEGER NOT NULL,
    borrowed_from  TEXT,                 -- instrument_id of the closest match, if used
    match_score    DOUBLE PRECISION,                 -- correlation with that match over the overlap
    profile_json   TEXT NOT NULL,
    methods_json   TEXT NOT NULL,
    n_obs_json     TEXT NOT NULL,
    -- Observations that existed but fell below the sufficiency floor. Diagnostic; a
    -- filled state's n_obs is zero, and this is where the discarded count goes.
    n_obs_discarded_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (instrument_id, calibration_id)
);

-- ---------------------------------------------------------------------------
-- The quantile bridge between the monthly signal and the annual calibration axis.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS state_map (
    map_id       TEXT NOT NULL,          -- MAP-<16 hex>
    signal_state INTEGER NOT NULL,       -- 1..25 on the Market Risk Signal axis
    centile      DOUBLE PRECISION NOT NULL,          -- where that column sits in the signal's own record
    cycle_value  DOUBLE PRECISION NOT NULL,          -- the ec_cycle sigma at the same centile
    axis_value   DOUBLE PRECISION NOT NULL,          -- position on the 1..5 phase axis
    calib_state  INTEGER NOT NULL,       -- nearest state on the calibration's 25-grid
    PRIMARY KEY (map_id, signal_state)
);

CREATE TABLE IF NOT EXISTS state_map_meta (
    map_id         TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    calibration_id TEXT NOT NULL REFERENCES calibration(calibration_id) ON DELETE CASCADE,
    signal_first   TEXT NOT NULL,
    signal_last    TEXT NOT NULL,
    method         TEXT NOT NULL,
    note           TEXT NOT NULL DEFAULT ''
);

-- ---------------------------------------------------------------------------
-- Run manifests. No figure leaves an engine without one.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS run_manifest (
    run_id          TEXT PRIMARY KEY,    -- RUN-<16 hex>
    engine          TEXT NOT NULL,
    engine_version  TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    wall_clock_ms   DOUBLE PRECISION NOT NULL,
    inputs_json     TEXT NOT NULL,
    params_hash     TEXT NOT NULL,
    outputs_json    TEXT NOT NULL,
    status          TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Inflation pass-through (beta) under a scenario Regime (owner, 29.09.2026; FMRE-33..37).
-- Both tables are append-only: a trigger refuses UPDATE and DELETE.
-- ---------------------------------------------------------------------------

-- The house table, one row per calibration version (engines/fund_map/pass_through.py).
CREATE TABLE IF NOT EXISTS inflation_beta_calibration (
    version        TEXT PRIMARY KEY,     -- ipt@<semver>
    calibration_id TEXT NOT NULL UNIQUE, -- IPT-<16 hex>, a hash of payload_json
    created_at     TEXT NOT NULL,
    source         TEXT NOT NULL,        -- the source line: who decided the table, when
    payload_json   TEXT NOT NULL         -- types (beta, duration), mapping rules, price floor, formula
);

-- The CIO's override of one instrument's beta (and duration), versioned per instrument.
-- The latest version is in force; beta NULL (or duration NULL) means the house value.
CREATE TABLE IF NOT EXISTS inflation_beta_override (
    instrument_id       TEXT NOT NULL REFERENCES instrument(instrument_id),
    version             INTEGER NOT NULL,           -- 1, 2, ... per instrument
    beta                DOUBLE PRECISION,           -- 0 .. 1.5; NULL reverts to the house beta
    duration            DOUBLE PRECISION,           -- years; NULL keeps the house duration
    reason              TEXT NOT NULL,
    set_by              TEXT NOT NULL,
    set_at              TEXT NOT NULL,              -- ISO-8601 UTC
    calibration_version TEXT NOT NULL,              -- the house table in force when set
    PRIMARY KEY (instrument_id, version)
);

COMMENT ON TABLE inflation_beta_calibration IS
    'Inflation pass-through house table (beta and duration per instrument type, register '
    'mapping rules), one append-only row per calibration version, with its source line. '
    'Read under a scenario Regime only (FMRE-33 to FMRE-37).';
COMMENT ON TABLE inflation_beta_override IS
    'The CIO''s per-instrument override of the inflation pass-through beta and duration, '
    'append-only and versioned; the latest version is in force, a NULL beta reverts to the '
    'house value. Written by PUT /v1/inflation-beta/{instrument_id}.';

CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % refused', TG_TABLE_NAME, TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS inflation_beta_calibration_append_only ON inflation_beta_calibration;
CREATE TRIGGER inflation_beta_calibration_append_only
    BEFORE UPDATE OR DELETE ON inflation_beta_calibration
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
DROP TRIGGER IF EXISTS inflation_beta_override_append_only ON inflation_beta_override;
CREATE TRIGGER inflation_beta_override_append_only
    BEFORE UPDATE OR DELETE ON inflation_beta_override
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- ---------------------------------------------------------------------------
-- Evolutions
--
-- This file is meant to be applied to an existing database as well as an empty one, and
-- CREATE TABLE IF NOT EXISTS silently does nothing when the table is already there -- so a
-- column added to a definition above never reaches a store that already exists. That is
-- the gap a migration framework normally fills. It does not need one: PostgreSQL's
-- ADD COLUMN IF NOT EXISTS is idempotent, so the same statement is safe on every run.
--
-- The rule is therefore: add the column to its table above *and* repeat it here. The
-- definition above stays the readable description of the schema; these lines are what
-- actually reach a database that already exists.
-- ---------------------------------------------------------------------------

ALTER TABLE instrument ADD COLUMN IF NOT EXISTS proxy_symbol TEXT;
ALTER TABLE instrument ADD COLUMN IF NOT EXISTS proxy_grade  TEXT;
ALTER TABLE instrument ADD COLUMN IF NOT EXISTS proxy_note   TEXT;
ALTER TABLE instrument ADD COLUMN IF NOT EXISTS countries_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE instrument_profile
    ADD COLUMN IF NOT EXISTS n_obs_discarded_json TEXT NOT NULL DEFAULT '[]';
