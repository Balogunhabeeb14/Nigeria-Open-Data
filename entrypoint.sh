#!/bin/bash
set -e

echo "=== Waiting for Database to be ready ==="
# -u: print each attempt as it happens. The reason for a failed attempt is
# shown (without the password), so a wrong password or host is visible in the
# logs instead of looking like a slow start.
python -u -c "
import sys, time
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from pipeline.settings import settings

url = make_url(settings.db_url())
print(f'Connecting to {url.host}:{url.port or 5432}/{url.database} as {url.username}')
engine = create_engine(settings.db_url(), connect_args={'connect_timeout': 5})
reason = ''
for attempt in range(1, 31):
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('Database is ready!')
        sys.exit(0)
    except Exception as exc:
        reason = str(getattr(exc, 'orig', exc)).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        print(f'Not ready ({attempt}/30): {reason}')
        time.sleep(2)

print()
print('Could not connect to the database: ' + reason)
if 'password authentication failed' in reason:
    print('The database was first created with a different password than the one in use now')
    print('(PIPELINE_DB_PASSWORD, often from a .env file). Either set the original password again,')
    print('or, if the data can be reloaded, start afresh:')
    print('    docker compose -f docker-compose.lite.yml down -v')
    print('    docker compose -f docker-compose.lite.yml up -d')
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
