-- datafeed store. Idempotent: safe to run on every start.
--
-- Conventions as in every engine: bare table names in the engine's own schema, ISO-8601
-- UTC timestamps as TEXT, JSON as TEXT with a _json suffix, DOUBLE PRECISION (never REAL),
-- prefixed content-hash ids.
--
-- Everything that is data is append-only, enforced here: source files, public responses,
-- snapshots with their definitions, cells and import counts, calibrations and artefacts.
-- An UPDATE or a DELETE raises. A correction is a new snapshot.
--
-- The registry (`country`, `series`) is reference data and stays editable: it says what
-- may be ingested. Every snapshot keeps its own copy of the definitions it used, so editing
-- the registry never changes a published snapshot.

CREATE TABLE IF NOT EXISTS country (
    code          TEXT PRIMARY KEY,                 -- ISO 3166 alpha-2, EU for the Union
    name          TEXT NOT NULL,
    iso3          TEXT NOT NULL,                    -- used for the public sources
    matlab_field  TEXT,                             -- field name in M_TS.mat, if any
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS series (
    series_id        TEXT PRIMARY KEY,              -- e.g. inflation.cpi_yoy
    category         TEXT NOT NULL,
    unit             TEXT NOT NULL,                 -- level, ratio or index
    period           TEXT NOT NULL,                 -- native frequency of the source
    indices_json     TEXT NOT NULL DEFAULT '[]',    -- HoNI indices that read it
    matlab_sheet     TEXT,                          -- M_TS sheet (row-position contract)
    matlab_column    INTEGER,                       -- 1-based column in that sheet
    zero_is_a_value  INTEGER NOT NULL DEFAULT 0,    -- 1: an interior 0.0 is a real print
    updated_at       TEXT NOT NULL
);
-- What the series measures, in plain language. Added 27.09.2026; the bootstrap fills it from
-- seed/registry.yaml where it is empty (the database still wins where it holds text).
ALTER TABLE series ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

-- A file the importer read. A changed file under the same name is a second row.
CREATE TABLE IF NOT EXISTS source_file (
    name         TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    byte_size    BIGINT NOT NULL,
    loaded_at    TEXT NOT NULL,
    origin       TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (name, sha256)
);

-- One stored response from a public source (World Bank, IMF), kept so that a fill can be
-- re-derived without the network. The same bytes are stored once.
CREATE TABLE IF NOT EXISTS public_fetch (
    fetch_id         TEXT PRIMARY KEY,              -- PUB-<16 hex> of provider, code, country, bytes
    provider         TEXT NOT NULL,
    code             TEXT NOT NULL,
    country          TEXT NOT NULL,                 -- datafeed country code
    url              TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    response_sha256  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_fetch_by_code ON public_fetch (provider, code, country, fetched_at);

CREATE TABLE IF NOT EXISTS public_value (
    fetch_id  TEXT NOT NULL REFERENCES public_fetch(fetch_id),
    year      INTEGER NOT NULL,
    value     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (fetch_id, year)
);

CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id    TEXT PRIMARY KEY,
    parent_id      TEXT REFERENCES snapshot(snapshot_id),
    checksum       TEXT NOT NULL,
    built_at       TEXT NOT NULL,
    manifest_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS series_definition (
    snapshot_id   TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    country       TEXT NOT NULL,
    series_id     TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, country, series_id)
);

-- Present cells only. A cell with no row is missing: assembly never invents one.
CREATE TABLE IF NOT EXISTS observation (
    snapshot_id  TEXT NOT NULL,
    country      TEXT NOT NULL,
    series_id    TEXT NOT NULL,
    date         TEXT NOT NULL,                     -- month end, YYYY-MM-DD
    value        DOUBLE PRECISION NOT NULL,
    flag         TEXT NOT NULL CHECK (flag IN ('observed', 'carried')),
    source       TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, country, series_id, date),
    FOREIGN KEY (snapshot_id, country, series_id)
        REFERENCES series_definition (snapshot_id, country, series_id)
);

-- What the MATLAB importer did to each series: NaN, leading, trailing and interior zeros,
-- and placeholder cells dropped. One row per series of an imported snapshot.
CREATE TABLE IF NOT EXISTS series_conversion (
    snapshot_id    TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    country        TEXT NOT NULL,
    series_id      TEXT NOT NULL,
    nan            INTEGER NOT NULL,
    leading_zero   INTEGER NOT NULL,
    trailing_zero  INTEGER NOT NULL,
    interior_zero  INTEGER NOT NULL,
    placeholder    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, country, series_id)
);

CREATE TABLE IF NOT EXISTS calibration (
    version           TEXT PRIMARY KEY,
    calibration_hash  TEXT NOT NULL,
    parent_version    TEXT REFERENCES calibration(version),
    created_at        TEXT NOT NULL,
    payload_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artefact (
    artefact_id       TEXT PRIMARY KEY,             -- PNL-<16 hex> of the payload
    idempotency_key   TEXT NOT NULL UNIQUE,
    contract_version  TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    payload_json      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run (
    run_id            TEXT PRIMARY KEY,
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

-- DF-18: one stored monthly response from a market provider (Cboe, BIS), kept whole so the
-- market layer can be re-derived offline. Not per country: a global index serves them all.
CREATE TABLE IF NOT EXISTS market_fetch (
    fetch_id         TEXT PRIMARY KEY,              -- MKT-<16 hex> of provider, code, bytes
    provider         TEXT NOT NULL,
    code             TEXT NOT NULL,
    url              TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    response_sha256  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS market_fetch_by_code ON market_fetch (provider, code, fetched_at);

CREATE TABLE IF NOT EXISTS market_value (
    fetch_id  TEXT NOT NULL REFERENCES market_fetch(fetch_id),
    date      TEXT NOT NULL,                        -- month end, YYYY-MM-DD
    value     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (fetch_id, date)
);

COMMENT ON TABLE country IS 'The economies datafeed serves: ISO code, name, ISO3 for the public sources, and the M_TS field name.';
COMMENT ON TABLE series IS 'The series registry: id, category, unit, native period, a plain-language description, the HoNI indices that read it and its M_TS sheet and column. Seeded from seed/registry.yaml; the database is the registry.';
COMMENT ON TABLE source_file IS 'Every file the importer read (M_TS.mat, ticker sheets), with its SHA-256 and size.';
COMMENT ON TABLE public_fetch IS 'One stored annual response from a public source (World Bank, IMF), kept so a gap fill can be re-derived without the network.';
COMMENT ON TABLE public_value IS 'The annual values of each stored public response.';
COMMENT ON TABLE market_fetch IS 'One stored monthly response from a market provider (Cboe, BIS) for the market layer (DF-18).';
COMMENT ON TABLE market_value IS 'The month-end values of each stored market response.';
COMMENT ON TABLE snapshot IS 'Immutable snapshots: id, parent, panel checksum and the manifest with every fill and market step.';
COMMENT ON TABLE series_definition IS 'Each snapshot''s own definition of every series per country: ticker, field, currency, scale, source and label.';
COMMENT ON TABLE observation IS 'The cells of every snapshot, month end by month end, each flagged observed or carried and naming its source. A missing cell has no row.';
COMMENT ON TABLE series_conversion IS 'What the MATLAB importer did to each series: NaN, leading, trailing and interior zeros, and placeholder cells dropped.';
COMMENT ON TABLE calibration IS 'Versioned, immutable calibrations: alignment, carry-forward and fill-acceptance rules.';
COMMENT ON TABLE artefact IS 'Materialised panels (POST /run), keyed by idempotency key.';
COMMENT ON TABLE run IS 'Every run of POST /run: status, timings, warnings, coverage and provenance.';

CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['source_file', 'public_fetch', 'public_value', 'market_fetch', 'market_value', 'snapshot',
                             'series_definition', 'observation', 'series_conversion', 'calibration',
                             'artefact']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION refuse_change()', t || '_append_only', t);
    END LOOP;
END
$$;
