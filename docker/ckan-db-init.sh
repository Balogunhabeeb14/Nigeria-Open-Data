#!/bin/sh
set -eu

# Run on every Compose startup, including when the database volume already exists.
psql -v ON_ERROR_STOP=1 -v ro_password="$DS_RO_PASS" <<'SQL'
SELECT 'CREATE ROLE datastore_ro LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'datastore_ro') \gexec
ALTER ROLE datastore_ro PASSWORD :'ro_password';
SELECT 'CREATE DATABASE datastore OWNER ckan'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'datastore') \gexec
SQL

psql -d datastore -v ON_ERROR_STOP=1 <<'SQL'
GRANT CONNECT ON DATABASE datastore TO datastore_ro;
GRANT USAGE ON SCHEMA public TO datastore_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO datastore_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE ckan IN SCHEMA public
    GRANT SELECT ON TABLES TO datastore_ro;
SQL
