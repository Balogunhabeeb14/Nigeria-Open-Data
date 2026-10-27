-- ─────────────────────────────────────────────────────────────────────────────
-- Additive migrations (idempotent: safe on both new and existing databases)
-- ─────────────────────────────────────────────────────────────────────────────

-- Per-source settings that are not columns: licence, attribution, discovery
-- switches, request pacing. See pipeline/db/seed_sources.py for the keys used.
ALTER TABLE cdm.data_sources
    ADD COLUMN IF NOT EXISTS options JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Change detection and publish tracking, kept apart from the period watermark.
--   content_hash  : SHA-256 of the last successfully loaded file or payload.
--   publish_state : 'published' | 'disabled' | 'failed' (last CKAN publish).
ALTER TABLE cdm.ingest_manifest
    ADD COLUMN IF NOT EXISTS content_hash  TEXT;
ALTER TABLE cdm.ingest_manifest
    ADD COLUMN IF NOT EXISTS publish_state TEXT;
ALTER TABLE cdm.ingest_manifest
    ADD COLUMN IF NOT EXISTS published_at  TIMESTAMPTZ;

-- Older runs stored the file hash in last_period as 'hash:<sha>'. Move it to
-- its own column so last_period only ever holds a period.
UPDATE cdm.ingest_manifest
SET    content_hash = substr(last_period, 6),
       last_period  = NULL
WHERE  last_period LIKE 'hash:%';

-- ─────────────────────────────────────────────────────────────────────────────
-- Built-in catalogue (CATALOG_BACKEND=local)
--
-- Lets the platform run without CKAN: the publisher and harvester write here
-- through pipeline/catalog/local.py, and pipeline/catalog/api.py serves it
-- back in the same shape as CKAN's Action API, so the frontend is unchanged.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cdm.catalog_dataset (
    id                TEXT        PRIMARY KEY,
    name              TEXT        UNIQUE NOT NULL,     -- URL slug
    title             TEXT        NOT NULL DEFAULT '',
    notes             TEXT        NOT NULL DEFAULT '',
    owner_org         TEXT,
    groups            TEXT[]      NOT NULL DEFAULT '{}',
    formats           TEXT[]      NOT NULL DEFAULT '{}', -- upper-cased resource formats
    featured          BOOLEAN     NOT NULL DEFAULT false,
    data              JSONB       NOT NULL,              -- the full dataset record
    metadata_created  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata_modified TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    search            tsvector
);
CREATE INDEX IF NOT EXISTS idx_catalog_dataset_search ON cdm.catalog_dataset USING gin(search);
CREATE INDEX IF NOT EXISTS idx_catalog_dataset_groups ON cdm.catalog_dataset USING gin(groups);
CREATE INDEX IF NOT EXISTS idx_catalog_dataset_org    ON cdm.catalog_dataset (owner_org);

-- Topics (kind='group') and publishers (kind='organization')
CREATE TABLE IF NOT EXISTS cdm.catalog_group (
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, name)
);

-- One row per data table attached to a dataset, and the rows themselves.
CREATE TABLE IF NOT EXISTS cdm.catalog_table (
    resource_id TEXT  PRIMARY KEY,
    dataset_id  TEXT  NOT NULL REFERENCES cdm.catalog_dataset(id) ON DELETE CASCADE,
    fields      JSONB NOT NULL,
    primary_key JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE IF NOT EXISTS cdm.catalog_row (
    resource_id TEXT  NOT NULL REFERENCES cdm.catalog_table(resource_id) ON DELETE CASCADE,
    row_key     TEXT  NOT NULL,
    data        JSONB NOT NULL,
    PRIMARY KEY (resource_id, row_key)
);

-- Values can be very large: Nigeria's GDP in current naira is in the hundreds
-- of trillions, more than NUMERIC(20,6) holds. Widen once; the check makes
-- this a no-op (and takes no table lock) on every later start.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'cdm' AND table_name = 'indicator_observation'
          AND column_name = 'value' AND numeric_precision < 30
    ) THEN
        ALTER TABLE cdm.indicator_observation ALTER COLUMN value TYPE NUMERIC(30, 6);
    END IF;
END $$;
