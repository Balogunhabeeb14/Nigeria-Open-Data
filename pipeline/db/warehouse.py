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
    if watermark and str(watermark).startswith("hash:"):
        # Legacy rows stored the file hash here. A hash is not a period.
        watermark = None
    logger.info(
        "Watermark [%s/%s]: %s",
        source_system, source_key, watermark or "none → full load",
    )
    return watermark


def get_manifest(source_system: str, source_key: str) -> dict | None:
    """Return the manifest row for (source, key) as a dict, or None if never run.

    Keys: last_period, content_hash, publish_state, status, row_count.
    """
    sql = text("""
        SELECT last_period, content_hash, publish_state, status, row_count
        FROM   cdm.ingest_manifest
        WHERE  source_system = :source
          AND  source_key    = :key
    """)
    with get_engine().connect() as conn:
        row = conn.execute(sql, {"source": source_system, "key": source_key}).fetchone()
    if not row:
        return None
    return {
        "last_period":   row[0],
        "content_hash":  row[1],
        "publish_state": row[2],
        "status":        row[3],
        "row_count":     row[4],
    }


def get_manifest_hashes(source_system: str) -> dict[str, str]:
    """Return {source_key: content_hash} for every successful row of a source.

    One query instead of one per key. Used by the catalogue harvester, which
    checks hundreds of remote datasets per run.
    """
    sql = text("""
        SELECT source_key, content_hash
        FROM   cdm.ingest_manifest
        WHERE  source_system = :source
          AND  status        = 'success'
          AND  content_hash IS NOT NULL
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"source": source_system}).fetchall()
    return {r[0]: r[1] for r in rows}


def update_manifest(
    source_system: str,
    source_key: str,
    last_period: str | None,
    row_count: int,
    status: str = "success",
    error_message: str | None = None,
    content_hash: str | None = None,
    publish_state: str | None = None,
) -> None:
    """Upsert the manifest row for (source, key) after each run.

    A failed run never erases what the last good run recorded: last_period,
    content_hash and publish_state keep their previous values unless this
    call supplies new ones. That keeps "what did we last load" answerable
    after a failure, and keeps the next run incremental.
    """
    sql = text("""
        INSERT INTO cdm.ingest_manifest
            (source_system, source_key, last_ingested, last_period, row_count,
             status, error_message, content_hash, publish_state, published_at)
        VALUES
            (:source, :key, NOW(), :period, :count,
             :status, :error, :content_hash, :publish_state,
             CASE WHEN :publish_state = 'published' THEN NOW() END)
        ON CONFLICT (source_system, source_key)
        DO UPDATE SET
            last_ingested  = EXCLUDED.last_ingested,
            last_period    = COALESCE(EXCLUDED.last_period,   cdm.ingest_manifest.last_period),
            row_count      = CASE WHEN EXCLUDED.status = 'success'
                                  THEN EXCLUDED.row_count
                                  ELSE cdm.ingest_manifest.row_count END,
            status         = EXCLUDED.status,
            error_message  = EXCLUDED.error_message,
            content_hash   = COALESCE(EXCLUDED.content_hash,  cdm.ingest_manifest.content_hash),
            publish_state  = COALESCE(EXCLUDED.publish_state, cdm.ingest_manifest.publish_state),
            published_at   = COALESCE(EXCLUDED.published_at,  cdm.ingest_manifest.published_at)
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "source":        source_system,
            "key":           source_key,
            "period":        last_period,
            "count":         row_count,
            "status":        status,
            "error":         error_message,
            "content_hash":  content_hash,
            "publish_state": publish_state,
        })
    logger.info(
        "Manifest updated [%s/%s]: status=%s period=%s rows=%d publish=%s",
        source_system, source_key, status, last_period, row_count, publish_state,
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
            (:source_system, :indicator_id, CAST(:raw_json AS jsonb), :file_or_url)
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


# ── CDM read (used by the CKAN publisher) ────────────────────────────────────

def fetch_observations(source_system: str, indicator_id: str) -> list[dict]:
    """Return every stored observation for one indicator, oldest first.

    The publisher sends this full table to CKAN, so what users download is
    the whole series and not only the rows that changed in the latest run.
    """
    sql = text("""
        SELECT period, period_type, geo_level, geo_code, geo_name,
               value, unit, indicator_id, indicator_name, source_system,
               raw_source_url, last_updated_at
        FROM   cdm.indicator_observation
        WHERE  source_system = :source
          AND  indicator_id  = :indicator
        ORDER  BY geo_code NULLS FIRST, period
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"source": source_system, "indicator": indicator_id}).mappings().all()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        d["value"] = float(d["value"]) if d["value"] is not None else None
        d["geo_code"] = d["geo_code"] or ""
        d["last_updated_at"] = d["last_updated_at"].isoformat() if d["last_updated_at"] else None
        out.append(d)
    return out


# ── Document Registration ─────────────────────────────────────────────────────

def register_document(source_system: str, file_meta: dict) -> None:
    """Upsert a document into cdm.dataset_registry.
    
    file_meta expects:
        - file_name, file_path, format, size_bytes, hash, status, error_message
    """
    import uuid
    # Create a deterministic dataset_id from the file hash to avoid duplicates
    dataset_id = f"doc_{file_meta.get('hash', uuid.uuid4().hex[:12])}"
    
    sql = text("""
        INSERT INTO cdm.dataset_registry (
            source_system, dataset_id, display_name, domain, format,
            storage_url, file_size_bytes, is_public
        ) VALUES (
            :source, :dataset_id, :name, 'economics', :format,
            :url, :size, true
        )
        ON CONFLICT (dataset_id) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            file_size_bytes = EXCLUDED.file_size_bytes,
            storage_url = EXCLUDED.storage_url
    """)
    
    # We might also want to log the extraction status to the manifest, 
    # but for now we'll just register the document here.
    
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "source": source_system,
            "dataset_id": dataset_id,
            "name": file_meta.get("file_name", "Unknown Document"),
            "format": file_meta.get("format", "document"),
            "url": file_meta.get("file_path", ""),
            "size": file_meta.get("size_bytes", 0)
        })
        
    # Let's also use update_manifest to track the file extraction success/failure
    # The source_key will be the dataset_id
    update_manifest(
        source_system=source_system,
        source_key=dataset_id,
        last_period=None,
        row_count=0,
        status=file_meta.get("status", "success"),
        error_message=file_meta.get("error_message")
    )
    
    logger.info("Registered document %s in dataset_registry", dataset_id)


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
