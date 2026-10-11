#!/bin/bash
set -e

echo "=== Waiting for Database to be ready ==="
python -c "
import sys, time
from sqlalchemy import create_engine, text
from pipeline.settings import settings
engine = create_engine(settings.db_url())
for i in range(30):
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('Database is ready!')
        sys.exit(0)
    except Exception as e:
        print(f'Waiting... ({i}/30)')
        time.sleep(2)
sys.exit(1)
"

echo "=== Running Database Schema Migrations ==="
python -c "from pipeline.db.warehouse import run_schema_migrations; run_schema_migrations()"

if [ "${CATALOG_BACKEND:-ckan}" = "local" ]; then
    echo "=== Starting on its own: API + built-in catalogue, website, loader ==="
    exec /usr/bin/supervisord -c /app/pipeline/supervisord.local.conf
fi

echo "=== Starting Process Manager (supervisord) ==="
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
