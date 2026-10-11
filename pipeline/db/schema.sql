-- pipeline/db/schema.sql
CREATE SCHEMA IF NOT EXISTS cdm;

CREATE TABLE IF NOT EXISTS cdm.publishers (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT            NOT NULL,
    api_key         TEXT            UNIQUE,
    contact_email   TEXT,
    is_active       BOOLEAN         DEFAULT true,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_publishers_api_key ON cdm.publishers (api_key);

CREATE TABLE IF NOT EXISTS cdm.data_sources (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    publisher_id    UUID            REFERENCES cdm.publishers(id),
    source_id       TEXT            UNIQUE NOT NULL,
    connector       TEXT            NOT NULL,
    transform       TEXT            NOT NULL,
    domain          TEXT            NOT NULL,
    schedule        TEXT            NOT NULL,
    landing_dir     TEXT            NOT NULL,
    ingest_mode     TEXT            NOT NULL,
    indicators      JSONB           NOT NULL DEFAULT '[]'::jsonb,
    is_active       BOOLEAN         DEFAULT true,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_data_sources_id ON cdm.data_sources (source_id);

CREATE TABLE IF NOT EXISTS cdm.ingest_manifest (
    id              SERIAL          PRIMARY KEY,
    source_system   TEXT            NOT NULL,
    source_key      TEXT            NOT NULL,
    last_ingested   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    last_period     TEXT,
    row_count       INTEGER,
    status          TEXT            NOT NULL DEFAULT 'success',
    error_message   TEXT,
    UNIQUE (source_system, source_key)
);
CREATE INDEX IF NOT EXISTS idx_manifest_lookup ON cdm.ingest_manifest (source_system, source_key);

CREATE TABLE IF NOT EXISTS cdm.stage_raw_observations (
    id              BIGSERIAL       PRIMARY KEY,
    source_system   TEXT            NOT NULL,
    indicator_id    TEXT,
    raw_json        JSONB           NOT NULL,
    file_or_url     TEXT,
    loaded_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stage_source ON cdm.stage_raw_observations (source_system, indicator_id);
CREATE INDEX IF NOT EXISTS idx_stage_file ON cdm.stage_raw_observations (file_or_url);

CREATE TABLE IF NOT EXISTS cdm.indicator_observation (
    id              BIGSERIAL       PRIMARY KEY,
    source_system   TEXT            NOT NULL,
    domain          TEXT            NOT NULL,
    indicator_id    TEXT            NOT NULL,
    indicator_name  TEXT            NOT NULL,
    geo_level       TEXT            NOT NULL,
    geo_code        TEXT,
    geo_name        TEXT            NOT NULL,
    period_type     TEXT            NOT NULL,
    period          TEXT            NOT NULL,
    value           NUMERIC(20, 6),
    unit            TEXT,
    notes           TEXT,
    raw_source_url  TEXT,
    last_updated_at TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (source_system, indicator_id, geo_code, period)
);

CREATE INDEX IF NOT EXISTS idx_obs_domain ON cdm.indicator_observation (domain);
CREATE INDEX IF NOT EXISTS idx_obs_indicator ON cdm.indicator_observation (indicator_id);
CREATE INDEX IF NOT EXISTS idx_obs_period ON cdm.indicator_observation (period);
CREATE INDEX IF NOT EXISTS idx_obs_geo ON cdm.indicator_observation (geo_code);
CREATE INDEX IF NOT EXISTS idx_obs_source ON cdm.indicator_observation (source_system);
CREATE INDEX IF NOT EXISTS idx_obs_composite ON cdm.indicator_observation (domain, period_type, geo_level);

CREATE TABLE IF NOT EXISTS cdm.pipeline_run_log (
    id              SERIAL          PRIMARY KEY,
    flow_name       TEXT            NOT NULL,
    source_system   TEXT            NOT NULL,
    indicator_id    TEXT,
    started_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT            NOT NULL DEFAULT 'running',
    rows_staged     INTEGER,
    rows_cdm        INTEGER,
    error_message   TEXT
);

-- Represents dataset registry pointing to object storage files (e.g. Parquet/Delta)
CREATE TABLE IF NOT EXISTS cdm.dataset_registry (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system   TEXT            NOT NULL,
    dataset_id      TEXT            UNIQUE NOT NULL,
    display_name    TEXT            NOT NULL,
    description     TEXT,
    domain          TEXT            NOT NULL, -- 'health' | 'economics' | 'agric'
    format          TEXT            NOT NULL, -- 'parquet' | 'csv' | 'media'
    storage_url     TEXT            NOT NULL, -- S3/R2 URI: s3://bucket/path/
    row_count       BIGINT,
    file_size_bytes BIGINT,
    is_public       BOOLEAN         DEFAULT true,
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    search_vector   tsvector                  -- For GIN full-text search indexing
);

-- Represents individual media file assets (Images, Voices)
CREATE TABLE IF NOT EXISTS cdm.media_assets (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id      TEXT            REFERENCES cdm.dataset_registry(dataset_id) ON DELETE CASCADE,
    asset_name      TEXT            NOT NULL,
    content_type    TEXT            NOT NULL, -- 'image/webp' | 'audio/mpeg'
    cdn_url         TEXT            NOT NULL, -- Public CDN endpoint
    raw_s3_url      TEXT            NOT NULL, -- Secure S3 URI
    file_size_bytes BIGINT          NOT NULL,
    audio_duration  INTERVAL,                 -- For voice assets
    voice_transcript TEXT,                    -- Automatic voice-to-text transcript
    last_updated_at TIMESTAMPTZ     DEFAULT NOW()
);

-- Indexing for speed and scale
CREATE INDEX IF NOT EXISTS idx_registry_search ON cdm.dataset_registry USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_media_dataset ON cdm.media_assets (dataset_id);

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
