"""
pipeline/config.py
==================
Source Configuration Helper

Fetches data source configurations from the PostgreSQL database dynamically.
"""
from __future__ import annotations
import json
from sqlalchemy import text

def _as_dict(value) -> dict:
    """JSONB comes back as a dict from psycopg2, as a string from some drivers."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    return json.loads(value)


def get_source_config(source_id: str) -> dict:
    try:
        from pipeline.db.warehouse import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT connector, transform, domain, schedule, landing_dir, ingest_mode, indicators, options FROM cdm.data_sources WHERE source_id = :source_id AND is_active = true"),
                {"source_id": source_id}
            ).fetchone()
            
            if result:
                indicators = result[6] if isinstance(result[6], list) else json.loads(result[6])
                return {
                    "source_id": source_id,
                    "connector": result[0],
                    "transform": result[1],
                    "domain": result[2],
                    "schedule": result[3],
                    "landing_dir": result[4],
                    "ingest_mode": result[5],
                    "indicators": indicators,
                    "options": _as_dict(result[7]),
                }
    except Exception as db_err:
        import logging
        logging.getLogger(__name__).warning("DB query failed for source '%s' (%s). Checking local code fallbacks...", source_id, db_err)

    try:
        from pipeline.db.seed_sources import DEFAULT_SOURCES
        for src in DEFAULT_SOURCES:
            if src["source_id"].lower() == source_id.lower():
                return {"options": {}, **src}
    except ImportError:
        pass

    raise KeyError(f"Source '{source_id}' not found or inactive in database or fallback configs.")

def list_source_ids() -> list[str]:
    try:
        from pipeline.db.warehouse import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT source_id FROM cdm.data_sources WHERE is_active = true")).fetchall()
            if result:
                return [row[0] for row in result]
    except Exception as db_err:
        import logging
        logging.getLogger(__name__).warning("DB query failed in list_source_ids (%s). Falling back to local default configs...", db_err)

    try:
        from pipeline.db.seed_sources import DEFAULT_SOURCES
        return [src["source_id"] for src in DEFAULT_SOURCES]
    except ImportError:
        return []

