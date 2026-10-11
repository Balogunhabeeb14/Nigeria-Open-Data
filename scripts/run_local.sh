#!/usr/bin/env bash
# Run the whole app on this machine without Docker.
#
# Needs: Python 3.11+, Node 20+, and a Postgres database you can reach.
#
#   pip install -r pipeline/requirements.txt
#   npm ci
#   export PIPELINE_DB_URL=postgresql://user:password@localhost:5432/dbname
#   scripts/run_local.sh            # then open http://localhost:3000
#
# Starts three things and stops them all on Ctrl+C:
#   API + built-in catalogue   http://127.0.0.1:8000
#   loader                     fills the catalogue, then refreshes it
#   website                    http://localhost:3000
#
# Set SITE_MODE=build for a production build of the website (slower to start,
# faster to use). The default is the development server.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${PIPELINE_DB_URL:?Set PIPELINE_DB_URL to a Postgres database, e.g. postgresql://user:pass@localhost:5432/naija}"
export CATALOG_BACKEND=local
export CATALOG_INTERNAL_URL="${CATALOG_INTERNAL_URL:-http://127.0.0.1:8000}"
export LANDING_ROOT="${LANDING_ROOT:-$PWD/data/raw}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"
LOG_DIR="${LOG_DIR:-$PWD/.run-logs}"
mkdir -p "$LOG_DIR"

pids=()
cleanup() {
  echo; echo "Stopping..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Preparing the database"
"$PYTHON" -c "from pipeline.db.warehouse import run_schema_migrations; run_schema_migrations()"

echo "==> Starting the API on :8000          (log: $LOG_DIR/api.log)"
"$PYTHON" -m uvicorn pipeline.api:app --host 127.0.0.1 --port 8000 >"$LOG_DIR/api.log" 2>&1 &
pids+=($!)

echo "==> Starting the loader                (log: $LOG_DIR/loader.log)"
"$PYTHON" -m pipeline.bootstrap >"$LOG_DIR/loader.log" 2>&1 &
pids+=($!)

echo "==> Starting the website on :3000      (log: $LOG_DIR/web.log)"
if [ "${SITE_MODE:-dev}" = "build" ]; then
  npm run build >"$LOG_DIR/web.log" 2>&1
  npm run start -- --port 3000 >>"$LOG_DIR/web.log" 2>&1 &
else
  npm run dev -- --port 3000 >"$LOG_DIR/web.log" 2>&1 &
fi
pids+=($!)

echo
echo "Open http://localhost:3000"
echo "Datasets appear as the loader works through them; follow it with:"
echo "  tail -f $LOG_DIR/loader.log"
wait
