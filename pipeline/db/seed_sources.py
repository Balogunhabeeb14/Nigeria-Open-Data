"""
pipeline/db/seed_sources.py
===========================
Idempotently seeds baseline data sources into cdm.data_sources.
Supports structured (API/CSV/Excel) and unstructured (PDF/Document) configs.
"""
from __future__ import annotations

import json
import logging
from sqlalchemy import text
from pipeline.db.warehouse import get_engine

logger = logging.getLogger(__name__)

# ── Default Source Registry Configurations ────────────────────────────────────
DEFAULT_SOURCES = [
    {
        "source_id": "NigeriaDataPortal",
        "connector": "pipeline.connectors.nigeria_data_portal.NigeriaDataPortalConnector",
        "transform": "pipeline.transforms.nigeria_data_portal_transform.transform",
        "domain": "economics",
        "schedule": "0 2 * * *",       # Daily @ 02:00 UTC
        "landing_dir": "nigeria_data_portal",
        "ingest_mode": "api",
        "indicators": [
            {
                "id": "GDP_REAL",
                "name": "Real Gross Domestic Product",
                "dataset_id": "NG_GDP_REAL",
                "domain": "economics",
                "unit": "Naira (Millions)",
            },
            {
                "id": "UNEMP_RATE",
                "name": "Unemployment Rate",
                "dataset_id": "NG_UNEMP_RATE",
                "domain": "economics",
                "unit": "%",
            },
        ],
    },
    {
        "source_id": "CBN",
        "connector": "pipeline.connectors.cbn.CBNConnector",
        "transform": "pipeline.transforms.cbn_transform.transform",
        "domain": "economics",
        "schedule": "0 3 * * 1",       # Weekly on Mondays @ 03:00 UTC
        "landing_dir": "cbn",
        "ingest_mode": "file",
        "indicators": [
            {
                "id": "CBN_INTEREST_MPR",
                "name": "Monetary Policy Rate (MPR)",
                "excel_url": "https://www.cbn.gov.ng/Out/2023/STATISTICS/MPR.xlsx",
                "sheet": 0,
                "domain": "economics",
                "unit": "%",
                "col_map": {"Date": "period", "MPR (%)": "value"},
            },
            {
                "id": "CBN_FX_RESERVES",
                "name": "External Reserves",
                "excel_url": "https://www.cbn.gov.ng/Out/2023/STATISTICS/Reserves.xlsx",
                "sheet": 0,
                "domain": "economics",
                "unit": "USD (Billions)",
                "col_map": {"Date": "period", "Reserves": "value"},
            },
        ],
    },
    # Unstructured Track 2 (PDF / Report extraction)
    {
        "source_id": "NBS_Reports",
        "connector": "pipeline.connectors.generic.GenericFileConnector",
        "transform": "pipeline.transforms.generic_transform.generic_transform",
        "domain": "economics",
        "schedule": "0 4 * * 1",
        "landing_dir": "nbs_reports",
        "ingest_mode": "document",
        "indicators": [
            {
                "id": "NBS_CPI_REPORT_PDF",
                "name": "CPI Monthly Report (PDF)",
                "dataset_id": "NBS_CPI_PDF",
                "domain": "economics",
                "format": "pdf",
                "extract_tables": True,
            }
        ],
    }
]


def seed_default_sources() -> int:
    """Insert or update baseline sources in cdm.data_sources.

    Returns:
        Number of sources seeded.
    """
    sql = text("""
        INSERT INTO cdm.data_sources (
            source_id, connector, transform, domain, schedule, 
            landing_dir, ingest_mode, indicators, is_active
        ) VALUES (
            :source_id, :connector, :transform, :domain, :schedule, 
            :landing_dir, :ingest_mode, CAST(:indicators AS JSONB), true
        )
        ON CONFLICT (source_id) DO UPDATE SET
            connector   = EXCLUDED.connector,
            transform   = EXCLUDED.transform,
            domain      = EXCLUDED.domain,
            schedule    = EXCLUDED.schedule,
            landing_dir = EXCLUDED.landing_dir,
            ingest_mode = EXCLUDED.ingest_mode,
            indicators  = EXCLUDED.indicators,
            is_active   = true;
    """)

    seeded_count = 0
    engine = get_engine()
    with engine.begin() as conn:
        for source in DEFAULT_SOURCES:
            conn.execute(sql, {
                "source_id":   source["source_id"],
                "connector":   source["connector"],
                "transform":   source["transform"],
                "domain":      source["domain"],
                "schedule":    source["schedule"],
                "landing_dir": source["landing_dir"],
                "ingest_mode": source["ingest_mode"],
                "indicators":  json.dumps(source["indicators"]),
            })
            seeded_count += 1
            logger.info("Seeded source configuration: %s", source["source_id"])

    logger.info("Successfully seeded %d baseline data sources.", seeded_count)
    return seeded_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_default_sources()
