"""Database storage operations for the CDM database."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from pipeline.settings import settings
from pipeline.transforms.cdm import CDMRecord

logger = logging.getLogger(__name__)

_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


# ── Engine ────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the pipeline database.

    The DB URL comes from settings (Pydantic-validated, password is SecretStr).
    The `**` in the log line is intentional — never log the real URL with credentials.
    """
    host = settings.pipeline_db_url.get_secret_value().split("@")[-1]
    logger.info("Connecting to pipeline DB @ %s", host)
    return create_engine(
        settings.db_url(),
        pool_pre_ping=True,     # detect and recycle stale connections
        pool_size=5,
        max_overflow=10,
        future=True,
    )


# ── Schema migrations ─────────────────────────────────────────────────────────

def run_schema_migrations() -> None:
    """Execute schema.sql against the pipeline database. Idempotent — safe to re-run."""
    sql = _SCHEMA_FILE.read_text()
    with get_engine().begin() as conn:
        conn.execute(text(sql))
    logger.info("Schema migrations applied.")

    try:
        from pipeline.db.seed_sources import seed_default_sources
        seed_default_sources()
    except Exception as exc:
        logger.warning("Could not auto-seed default sources: %s", exc)



# ── Watermark / Manifest ──────────────────────────────────────────────────────

def get_watermark(source_system: str, source_key: str) -> str | None:
    """Return the last successfully ingested period for (source, key), or None.

    None means this is a first-time full load.
    """
    sql = text("""
        SELECT last_period
        FROM   cdm.ingest_manifest
        WHERE  source_system = :source
          AND  source_key    = :key
          AND  status        = 'success'
    """)
    with get_engine().connect() as conn:
        row = conn.execute(sql, {"source": source_system, "key": source_key}).fetchone()
    watermark = row[0] if row else None
    logger.info(
        "Watermark [%s/%s]: %s",
        source_system, source_key, watermark or "none → full load",
    )
    return watermark


def update_manifest(
    source_system: str,
    source_key: str,
    last_period: str | None,
    row_count: int,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """Upsert the manifest row for (source, key) after each run.

    Uses ON CONFLICT so this is always a single SQL statement regardless
    of whether the row already exists.
    """
    sql = text("""
        INSERT INTO cdm.ingest_manifest
            (source_system, source_key, last_ingested, last_period, row_count, status, error_message)
        VALUES
            (:source, :key, NOW(), :period, :count, :status, :error)
        ON CONFLICT (source_system, source_key)
        DO UPDATE SET
            last_ingested  = EXCLUDED.last_ingested,
            last_period    = EXCLUDED.last_period,
            row_count      = EXCLUDED.row_count,
            status         = EXCLUDED.status,
            error_message  = EXCLUDED.error_message
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "source": source_system,
            "key":    source_key,
            "period": last_period,
            "count":  row_count,
            "status": status,
            "error":  error_message,
        })
    logger.info(
        "Manifest updated [%s/%s]: status=%s period=%s rows=%d",
        source_system, source_key, status, last_period, row_count,
    )


# ── Staging ───────────────────────────────────────────────────────────────────

def load_to_stage(
    df: pd.DataFrame,
    source_system: str,
    indicator_id: str,
    file_or_url: str | None = None,
) -> int:
    """Bulk-insert raw DataFrame rows into cdm.stage_raw_observations.

    Each row is stored as JSONB for maximum flexibility — the raw data is
    preserved exactly as received, enabling re-transformation without re-downloading.
    Returns the number of rows inserted.
    """
    if df.empty:
        return 0

    records = [
        {
            "source_system": source_system,
            "indicator_id":  indicator_id,
            "raw_json":      json.dumps(row, default=str),
            "file_or_url":   file_or_url,
        }
        for row in df.to_dict(orient="records")
    ]

    sql = text("""
        INSERT INTO cdm.stage_raw_observations
            (source_system, indicator_id, raw_json, file_or_url)
        VALUES
            (:source_system, :indicator_id, :raw_json::jsonb, :file_or_url)
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, records)

    logger.info("Staged %d rows [%s/%s]", len(records), source_system, indicator_id)
    return len(records)


# ── CDM upsert ────────────────────────────────────────────────────────────────

def upsert_to_cdm(cdm_records: list[CDMRecord]) -> int:
    """Upsert CDMRecord objects into cdm.indicator_observation.

    Uses INSERT ... ON CONFLICT DO UPDATE so this operation is fully
    idempotent — re-running a flow never creates duplicate rows.
    Returns the number of rows upserted.
    """
    if not cdm_records:
        return 0

    sql = text("""
        INSERT INTO cdm.indicator_observation (
            source_system, domain, indicator_id, indicator_name,
            geo_level, geo_code, geo_name,
            period_type, period, value, unit,
            notes, raw_source_url, last_updated_at
        ) VALUES (
            :source_system, :domain, :indicator_id, :indicator_name,
            :geo_level, :geo_code, :geo_name,
            :period_type, :period, :value, :unit,
            :notes, :raw_source_url, :last_updated_at
        )
        ON CONFLICT (source_system, indicator_id, geo_code, period)
        DO UPDATE SET
            value           = EXCLUDED.value,
            unit            = EXCLUDED.unit,
            indicator_name  = EXCLUDED.indicator_name,
            domain          = EXCLUDED.domain,
            notes           = EXCLUDED.notes,
            last_updated_at = EXCLUDED.last_updated_at
    """)
    rows = [r.to_dict() for r in cdm_records]
    with get_engine().begin() as conn:
        conn.execute(sql, rows)

    logger.info("Upserted %d CDM rows", len(rows))
    return len(rows)


# ── Run audit log ─────────────────────────────────────────────────────────────

def log_run_start(
    flow_name: str,
    source_system: str,
    indicator_id: str | None = None,
) -> int:
    """Insert a 'running' row into cdm.pipeline_run_log. Returns the new row id."""
    sql = text("""
        INSERT INTO cdm.pipeline_run_log (flow_name, source_system, indicator_id, status)
        VALUES (:flow, :source, :indicator, 'running')
        RETURNING id
    """)
    with get_engine().begin() as conn:
        result = conn.execute(sql, {
            "flow":      flow_name,
            "source":    source_system,
            "indicator": indicator_id,
        })
        return int(result.scalar() or 0)


def log_run_finish(
    run_id: int,
    status: str,
    rows_staged: int = 0,
    rows_cdm: int = 0,
    error_message: str | None = None,
) -> None:
    """Update a pipeline_run_log row with the final outcome."""
    sql = text("""
        UPDATE cdm.pipeline_run_log SET
            finished_at   = NOW(),
            status        = :status,
            rows_staged   = :staged,
            rows_cdm      = :cdm,
            error_message = :error
        WHERE id = :id
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "id":     run_id,
            "status": status,
            "staged": rows_staged,
            "cdm":    rows_cdm,
            "error":  error_message,
        })
