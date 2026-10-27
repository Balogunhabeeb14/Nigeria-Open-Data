-- Additive migration: existing publisher/source/dataset IDs and rows are retained.
CREATE TABLE cdm.portal_users (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, verified_at TIMESTAMPTZ, is_active BOOLEAN NOT NULL DEFAULT true,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE cdm.portal_sessions (
 token_hash TEXT PRIMARY KEY, user_id UUID NOT NULL REFERENCES cdm.portal_users(id),
 csrf_hash TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, authenticated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON cdm.portal_sessions(user_id);
CREATE TABLE cdm.portal_email_actions (
 token_hash TEXT PRIMARY KEY, user_id UUID NOT NULL REFERENCES cdm.portal_users(id),
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')), expires_at TIMESTAMPTZ NOT NULL,
 used_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE cdm.portal_mail_outbox (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), recipient TEXT NOT NULL, payload_ciphertext TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, sent_at TIMESTAMPTZ, next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE cdm.publishers ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}';
ALTER TABLE cdm.publishers ADD COLUMN IF NOT EXISTS ckan_org_name TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS publishers_ckan_org ON cdm.publishers(ckan_org_name) WHERE ckan_org_name IS NOT NULL;
CREATE TABLE cdm.portal_memberships (
 user_id UUID NOT NULL REFERENCES cdm.portal_users(id), publisher_id UUID NOT NULL REFERENCES cdm.publishers(id),
 role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
 PRIMARY KEY(user_id,publisher_id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE cdm.portal_invitations (
 token_hash TEXT PRIMARY KEY, publisher_id UUID NOT NULL REFERENCES cdm.publishers(id),
 email TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('editor','viewer','owner')),
 created_by UUID NOT NULL REFERENCES cdm.portal_users(id), expires_at TIMESTAMPTZ NOT NULL,
 accepted_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ
);
CREATE TABLE cdm.portal_integration_tokens (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), publisher_id UUID NOT NULL REFERENCES cdm.publishers(id),
 name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, scopes JSONB NOT NULL,
 created_by UUID REFERENCES cdm.portal_users(id), expires_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ,
 legacy BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE cdm.portal_rate_limits (
 bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS publisher_id UUID REFERENCES cdm.publishers(id);
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES cdm.portal_users(id);
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS licence TEXT;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS original_provider TEXT;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS provenance TEXT;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS access_method TEXT;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS connection JSONB NOT NULL DEFAULT '{}';
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS credentials_ciphertext TEXT;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS processing_state TEXT;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS publication_state TEXT;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS tabular_schema JSONB;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS next_due_at TIMESTAMPTZ;
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE TABLE cdm.portal_jobs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id TEXT NOT NULL REFERENCES cdm.dataset_registry(dataset_id),
 source_id TEXT NOT NULL REFERENCES cdm.data_sources(source_id),
 actor_id UUID REFERENCES cdm.portal_users(id), integration_token_id UUID REFERENCES cdm.portal_integration_tokens(id),
 action TEXT NOT NULL CHECK(action IN ('ingest','publish')),
 status TEXT NOT NULL CHECK(status IN ('queued','processing','needs_review','completed','failed')),
 progress INTEGER NOT NULL DEFAULT 0, phase TEXT NOT NULL DEFAULT 'Waiting for worker',
 attempts INTEGER NOT NULL DEFAULT 0, error_code TEXT, prefect_run_id UUID, lease_until TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX portal_one_active_job ON cdm.portal_jobs(dataset_id) WHERE status IN ('queued','processing');
CREATE TABLE cdm.portal_job_attempts (
 job_id UUID NOT NULL REFERENCES cdm.portal_jobs(id), attempt INTEGER NOT NULL,
 status TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), finished_at TIMESTAMPTZ,
 error_code TEXT, PRIMARY KEY(job_id,attempt)
);
ALTER TABLE cdm.dataset_registry ADD COLUMN IF NOT EXISTS last_ingested_job UUID REFERENCES cdm.portal_jobs(id);
CREATE TABLE cdm.portal_submissions (
 publisher_id UUID NOT NULL REFERENCES cdm.publishers(id), idempotency_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, dataset_id TEXT NOT NULL REFERENCES cdm.dataset_registry(dataset_id),
 PRIMARY KEY(publisher_id,idempotency_key)
);
CREATE TABLE cdm.portal_files (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id TEXT NOT NULL REFERENCES cdm.dataset_registry(dataset_id),
 job_id UUID REFERENCES cdm.portal_jobs(id), kind TEXT NOT NULL CHECK(kind IN ('original','processed')),
 storage_key TEXT NOT NULL, original_name TEXT NOT NULL, format TEXT NOT NULL,
 sha256 TEXT NOT NULL, size_bytes BIGINT NOT NULL, published BOOLEAN NOT NULL DEFAULT false,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(dataset_id,kind,sha256)
);
CREATE TABLE cdm.portal_job_files (
 job_id UUID NOT NULL REFERENCES cdm.portal_jobs(id), file_id UUID NOT NULL REFERENCES cdm.portal_files(id),
 PRIMARY KEY(job_id,file_id)
);
CREATE TABLE cdm.portal_tabular_rows (
 dataset_id TEXT NOT NULL REFERENCES cdm.dataset_registry(dataset_id), job_id UUID NOT NULL REFERENCES cdm.portal_jobs(id),
 row_number INTEGER NOT NULL, record JSONB NOT NULL,
 PRIMARY KEY(dataset_id,job_id,row_number)
);
CREATE INDEX ON cdm.portal_jobs(status,created_at);
CREATE INDEX ON cdm.dataset_registry(publisher_id);
