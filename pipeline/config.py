"""
pipeline/config.py
==================
Source Configuration Helper

Fetches data source configurations from the PostgreSQL database dynamically.
"""
from __future__ import annotations
import json
from sqlalchemy import text

def get_source_config(source_id: str) -> dict:
    from pipeline.db.warehouse import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT connector, transform, domain, schedule, landing_dir, ingest_mode, indicators FROM cdm.data_sources WHERE source_id = :source_id AND is_active = true"),
            {"source_id": source_id}
        ).fetchone()
        
        if not result:
            raise KeyError(f"Source '{source_id}' not found or inactive in database.")
            
        indicators = result[6] if isinstance(result[6], list) else json.loads(result[6])
        return {
            "source_id": source_id,
            "connector": result[0],
            "transform": result[1],
            "domain": result[2],
            "schedule": result[3],
            "landing_dir": result[4],
            "ingest_mode": result[5],
            "indicators": indicators
        }

def list_source_ids() -> list[str]:
    from pipeline.db.warehouse import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT source_id FROM cdm.data_sources WHERE is_active = true")).fetchall()
        return [row[0] for row in result]
