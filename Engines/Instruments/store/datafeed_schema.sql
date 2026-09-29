-- The datafeed store: every series any engine reads, with its metadata attached.
--
-- **One shared schema for all engines.** Source data does not belong to whichever engine
-- happens to load it first -- `datafeed` owns it and the engines read it. Fund Map keeps
-- its own schema for the artefacts it *produces* (calibrations, profiles, run manifests)
-- and reads its inputs from here.
--
-- Three things this schema insists on that a plain table of numbers would not:
--
--   * **Metadata travels with the series, not in a README.** A number whose unit,
--     currency, magnitude and period are not recorded cannot be combined with another
--     number safely, and the mistake is silent. Every one of those is a column.
--   * **A stitched series carries its joints.** Manual section 9: every stitch and its
--     discrepancy is recorded, "because a joint is exactly where a spurious regime shift
--     gets manufactured". `series_segment` is that record.
--   * **Every value says how it got there.** `observed`, `carried` or `stitched` --
--     never all three blurred into one column of floats.
--
-- Floating point is DOUBLE PRECISION throughout, never REAL: PostgreSQL's REAL is four
-- bytes and loses ~1.7e-9, which would quietly end this project's claim to reproduce a
-- published reference to 5e-16.

-- ---------------------------------------------------------------------------
-- Provenance
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_file (
    name        TEXT PRIMARY KEY,
    sha256      TEXT NOT NULL,
    byte_size   BIGINT NOT NULL,
    loaded_at   TEXT NOT NULL,
    origin      TEXT NOT NULL,           -- absolute path the bytes were read from
    origin_kind TEXT NOT NULL,           -- nas:house-research | nas:prototype | internet:*
    note        TEXT NOT NULL DEFAULT ''
);

-- ---------------------------------------------------------------------------
-- The registry
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS series_definition (
    series_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',

    -- What the numbers mean. Getting any of these wrong combines two incompatible
    -- quantities without complaint, which is why they are columns and not documentation.
    unit          TEXT NOT NULL,   -- return_simple|return_log|rate|index_level|price|ratio|count
    currency      TEXT NOT NULL,   -- ISO 4217, or 'none' for a ratio or a rate
    magnitude     TEXT NOT NULL,   -- units|thousands|millions|billions|decimal|percent
    period        TEXT NOT NULL,   -- A | M | D
    country       TEXT NOT NULL,   -- ISO 3166-1 alpha-2, or WLD for a world aggregate

    category      TEXT NOT NULL,   -- macro|return|signal|fx|price|allocation
    index_family  TEXT,            -- MSCI, S&P, Bloomberg, ... where the series tracks one

    -- Where it came from and how far it can be trusted.
    pull_code     TEXT,            -- upstream identifier: Bloomberg ticker, Yahoo symbol, column
    source        TEXT NOT NULL,   -- human-readable origin
    source_file   TEXT REFERENCES source_file(name),
    origin_kind   TEXT NOT NULL,   -- nas:house-research | nas:prototype | internet:yahoo | derived:stitch
    quality_grade TEXT NOT NULL,   -- authoritative | close | proxy | weak

    is_stitched   BOOLEAN NOT NULL DEFAULT FALSE,
    first_period  TEXT,
    last_period   TEXT,
    observation_count INTEGER NOT NULL DEFAULT 0,

    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_series_category ON series_definition(category);
CREATE INDEX IF NOT EXISTS ix_series_country  ON series_definition(country);

-- ---------------------------------------------------------------------------
-- The data
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS observation (
    series_id TEXT NOT NULL REFERENCES series_definition(series_id) ON DELETE CASCADE,
    -- YYYY for annual, YYYY-MM for monthly, YYYY-MM-DD for daily. Sorts correctly as text
    -- within a frequency, and the frequency is on the series rather than guessed here.
    period    TEXT NOT NULL,
    value     DOUBLE PRECISION NOT NULL,
    -- observed: it was measured. carried: forward-filled from an earlier period.
    -- stitched: it came from a different underlying series joined onto this one.
    flag      TEXT NOT NULL DEFAULT 'observed',
    segment   INTEGER,           -- which series_segment produced it, when stitched
    PRIMARY KEY (series_id, period)
);

CREATE INDEX IF NOT EXISTS ix_observation_period ON observation(period);

-- ---------------------------------------------------------------------------
-- Stitching: the joints, and what they cost
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS series_segment (
    series_id        TEXT NOT NULL REFERENCES series_definition(series_id) ON DELETE CASCADE,
    -- 0 is the most recent segment. Series are joined working backwards from the present,
    -- so segment 0 is the one that needs no justification and each later index reaches
    -- further back on progressively weaker evidence.
    segment_index    INTEGER NOT NULL,
    source_series_id TEXT NOT NULL,
    from_period      TEXT NOT NULL,
    to_period        TEXT NOT NULL,

    -- The joint. Manual section 9: where several candidates exist the smallest average
    -- discrepancy over the overlap wins, and above 2 % the overlap is averaged to smooth
    -- the join. Both the winning discrepancy and whether smoothing fired are recorded,
    -- because a joint is exactly where a spurious regime shift gets manufactured.
    overlap_periods  INTEGER NOT NULL DEFAULT 0,
    mean_discrepancy DOUBLE PRECISION,
    smoothed         BOOLEAN NOT NULL DEFAULT FALSE,
    rejected_candidates TEXT NOT NULL DEFAULT '[]',  -- what lost, and by how much
    note             TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (series_id, segment_index)
);

-- ---------------------------------------------------------------------------
-- Snapshots: immutable, checksummed, the reference for every downstream golden test
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id       TEXT PRIMARY KEY,   -- SNAP-<16 hex>, a hash of the content
    created_at        TEXT NOT NULL,
    checksum          TEXT NOT NULL,
    series_count      INTEGER NOT NULL,
    observation_count INTEGER NOT NULL,
    note              TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS snapshot_series (
    snapshot_id       TEXT NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    series_id         TEXT NOT NULL,
    first_period      TEXT,
    last_period       TEXT,
    observation_count INTEGER NOT NULL,
    checksum          TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, series_id)
);

-- ---------------------------------------------------------------------------
-- Evolutions -- see the note in schema.sql. CREATE TABLE IF NOT EXISTS cannot add a
-- column to a table that already exists, so anything added above is repeated here.
-- ---------------------------------------------------------------------------

ALTER TABLE series_definition ADD COLUMN IF NOT EXISTS index_family TEXT;
ALTER TABLE observation       ADD COLUMN IF NOT EXISTS segment INTEGER;
ALTER TABLE series_segment    ADD COLUMN IF NOT EXISTS rejected_candidates TEXT NOT NULL DEFAULT '[]';

-- ---------------------------------------------------------------------------
-- The reference-source catalogue, mirrored from Notion.
--
-- Sixty-five sources catalogued by hand. What the catalogue could not say is which of
-- them an engine actually reads, and that is the column that matters: a research
-- bibliography and a production dependency list look identical until something breaks.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reference_source (
    source_key   TEXT PRIMARY KEY,        -- slug of the catalogue name
    name         TEXT NOT NULL,
    author       TEXT,
    quality      TEXT,                    -- the catalogue's own 1..3 grading
    comments     TEXT,
    notion_url   TEXT NOT NULL,

    -- active | candidate | unused. Curated from the evidence below, never inferred.
    usage_status TEXT NOT NULL DEFAULT 'unused',
    engines      TEXT NOT NULL DEFAULT '[]',   -- JSON array of engine names
    series       TEXT NOT NULL DEFAULT '[]',   -- JSON array of datafeed series_ids
    evidence     TEXT NOT NULL DEFAULT '',     -- why this source is marked as it is
    synced_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_reference_usage ON reference_source(usage_status);
