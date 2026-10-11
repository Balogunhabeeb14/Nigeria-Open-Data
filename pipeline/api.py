from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import json
from sqlalchemy import text
from pipeline.db.warehouse import get_engine

app = FastAPI(
    title="Naija Open Data - Ingestion API",
    description=(
        "Read endpoints are open. Endpoints that change the platform need the "
        "X-Admin-Token header and are off until ADMIN_API_TOKEN is set."
    ),
    version="1.0.0"
)

from pipeline.settings import settings
from pipeline.scrape import router as scrape_router
from pipeline.security import (
    MAX_UPLOAD_BYTES,
    check_code_path,
    check_identifier,
    check_upload_name,
    require_admin,
)

# Add CORS middleware to allow requests from the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)

# Triggering ingestion is an admin action.
app.include_router(scrape_router, dependencies=[Depends(require_admin)])

# Built-in catalogue (read-only). Only when this app is the catalogue; with
# CATALOG_BACKEND=ckan those routes belong to the CKAN server.
if settings.catalog_backend == "local":
    from pipeline.catalog.api import router as catalog_router
    app.include_router(catalog_router)

# ─── Pydantic Models ──────────────────────────────────────────────────────────

class PublisherCreate(BaseModel):
    name: str = Field(..., description="Name of the publisher organization")
    api_key: str = Field(..., description="Unique API key for the publisher to use for updates")
    contact_email: Optional[str] = Field(None, description="Contact email for data governance")

class IndicatorConfig(BaseModel):
    id: str = Field(..., description="Unique indicator ID, e.g. GDP_REAL")
    name: str = Field(..., description="Human readable name of the indicator")
    domain: Optional[str] = Field(None, description="Health, Economics, or Agric")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    dataset_id: Optional[str] = None
    excel_url: Optional[str] = None
    sheet: Optional[str] = None
    geo_level: Optional[str] = "national"
    col_map: Optional[dict] = None
    value_range: Optional[List[float]] = None

class SourceCreate(BaseModel):
    publisher_api_key: str
    source_id: str
    connector: str
    transform: str
    domain: str
    schedule: str
    landing_dir: str
    ingest_mode: str
    indicators: List[IndicatorConfig]

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/api/publishers", dependencies=[Depends(require_admin)])
def create_publisher(pub: PublisherCreate):
    engine = get_engine()
    with engine.begin() as conn:
        try:
            result = conn.execute(
                text("""
                INSERT INTO cdm.publishers (name, api_key, contact_email)
                VALUES (:name, :api_key, :contact_email)
                ON CONFLICT (api_key) DO UPDATE SET 
                    name = EXCLUDED.name,
                    contact_email = COALESCE(EXCLUDED.contact_email, cdm.publishers.contact_email)
                RETURNING id;
                """),
                {"name": pub.name, "api_key": pub.api_key, "contact_email": pub.contact_email}
            )
            pub_id = result.scalar()
            return {"status": "success", "publisher_id": pub_id}
        except Exception as e:
            # We ensure we don't return raw SQL errors to the frontend
            print(f"Error creating publisher: {e}")
            raise HTTPException(status_code=400, detail="Could not register organization. Please check your details and try again.")

@app.post("/api/sources", dependencies=[Depends(require_admin)])
def register_source(src: SourceCreate):
    check_identifier(src.source_id, "source_id")
    check_identifier(src.landing_dir, "landing_dir")
    check_code_path(src.connector, "connector")
    check_code_path(src.transform, "transform")
    engine = get_engine()
    with engine.begin() as conn:
        # Validate publisher
        pub_result = conn.execute(
            text("SELECT id FROM cdm.publishers WHERE api_key = :api_key AND is_active = true"),
            {"api_key": src.publisher_api_key}
        ).fetchone()
        
        if not pub_result:
            raise HTTPException(status_code=401, detail="Invalid or inactive publisher API key")
            
        pub_id = pub_result[0]
        
        # Insert source
        indicators_json = json.dumps([i.model_dump() for i in src.indicators])
        
        try:
            saved = conn.execute(
                text("""
                INSERT INTO cdm.data_sources (
                    publisher_id, source_id, connector, transform, domain, 
                    schedule, landing_dir, ingest_mode, indicators
                )
                VALUES (
                    :pub_id, :source_id, :connector, :transform, :domain, 
                    :schedule, :landing_dir, :ingest_mode, :indicators
                )
                ON CONFLICT (source_id) DO UPDATE SET
                    connector = EXCLUDED.connector,
                    transform = EXCLUDED.transform,
                    domain = EXCLUDED.domain,
                    schedule = EXCLUDED.schedule,
                    landing_dir = EXCLUDED.landing_dir,
                    ingest_mode = EXCLUDED.ingest_mode,
                    indicators = EXCLUDED.indicators
                -- A publisher can update its own source, never someone else's
                -- or a built-in one (those have no publisher).
                WHERE cdm.data_sources.publisher_id = EXCLUDED.publisher_id
                RETURNING source_id;
                """),
                {
                    "pub_id": pub_id,
                    "source_id": src.source_id,
                    "connector": src.connector,
                    "transform": src.transform,
                    "domain": src.domain,
                    "schedule": src.schedule,
                    "landing_dir": src.landing_dir,
                    "ingest_mode": src.ingest_mode,
                    "indicators": indicators_json
                }
            )
            if saved.fetchone() is None:
                raise HTTPException(status_code=409, detail="A source with this id already exists and belongs to someone else.")
            return {"status": "success", "source_id": src.source_id}
        except HTTPException:
            raise
        except Exception as e:
            print(f"Error registering source: {e}")
            raise HTTPException(status_code=400, detail="Could not configure dataset. Please ensure the details are correct.")

@app.post("/api/upload", dependencies=[Depends(require_admin)])
async def upload_dataset(
    file: UploadFile = File(...),
    source_id: str = Form(...),
    publisher_api_key: str = Form(...)
):
    check_identifier(source_id, "source_id")
    filename = check_upload_name(file.filename)

    engine = get_engine()
    with engine.begin() as conn:
        # The file goes to the landing folder of a source this publisher owns.
        row = conn.execute(
            text("""
                SELECT s.landing_dir
                FROM cdm.data_sources s JOIN cdm.publishers p ON p.id = s.publisher_id
                WHERE p.api_key = :api_key AND p.is_active = true AND s.source_id = :source_id
            """),
            {"api_key": publisher_api_key, "source_id": source_id}
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Unknown source, or it does not belong to this publisher.")

    landing_dir = check_identifier(row[0], "landing_dir")
    folder = (settings.landing_root / landing_dir).resolve()
    file_path = (folder / filename).resolve()
    if folder not in file_path.parents:          # belt and braces against path tricks
        raise HTTPException(status_code=422, detail="Invalid file name.")
    folder.mkdir(parents=True, exist_ok=True)

    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        with open(file_path, "wb") as f:
            f.write(content)
        return {"status": "success", "file": filename, "source_id": source_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error uploading dataset: {e}")
        raise HTTPException(status_code=500, detail="Could not securely save the dataset file. Please try again.")

@app.get("/api/publishers", dependencies=[Depends(require_admin)])
def list_publishers():
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name, contact_email, created_at, is_active FROM cdm.publishers ORDER BY created_at DESC"))
        return [
            {
                "name": row[0],
                "contact_email": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
                "is_active": row[3]
            }
            for row in result.fetchall()
        ]

@app.get("/api/sources")
def list_sources():
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT source_id, connector, transform, domain, schedule, ingest_mode, is_active, created_at FROM cdm.data_sources ORDER BY created_at DESC"))
        return [
            {
                "source_id": row[0],
                "connector": row[1],
                "transform": row[2],
                "domain": row[3],
                "schedule": row[4],
                "ingest_mode": row[5],
                "is_active": row[6],
                "created_at": row[7].isoformat() if row[7] else None
            }
            for row in result.fetchall()
        ]

@app.get("/api/sources/{source_id}/observations")
def get_source_observations(source_id: str, limit: int = 1000, offset: int = 0):
    """Observations of one source, newest period first, a page at a time."""
    limit = max(1, min(limit, 10000))
    offset = max(0, offset)
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT indicator_id, indicator_name, geo_level, geo_name, period, value, unit, last_updated_at 
                FROM cdm.indicator_observation 
                WHERE source_system = :source_id 
                ORDER BY period DESC, indicator_id, geo_code
                LIMIT :limit OFFSET :offset
            """),
            {"source_id": source_id, "limit": limit, "offset": offset}
        )
        return [
            {
                "indicator_id": row[0],
                "indicator_name": row[1],
                "geo_level": row[2],
                "geo_name": row[3],
                "period": row[4],
                "value": float(row[5]) if row[5] is not None else None,
                "unit": row[6],
                "last_updated_at": row[7].isoformat() if row[7] else None
            }
            for row in result.fetchall()
        ]

@app.get("/api/status")
def data_status():
    """How fresh and complete the data is, per source. Public and read-only.

    Built from the pipeline's own records of what it loaded and when, so it
    describes what actually happened, not what was scheduled.
    """
    engine = get_engine()
    with engine.connect() as conn:
        loaded = conn.execute(text("""
            SELECT source_system,
                   count(*) FILTER (WHERE status = 'success' AND COALESCE(row_count, 0) > 0) AS with_data,
                   count(*) FILTER (WHERE status = 'success' AND COALESCE(row_count, 0) = 0) AS no_data,
                   count(*) FILTER (WHERE status = 'failed')                                AS failed,
                   count(*) FILTER (WHERE publish_state = 'failed')                         AS unpublished,
                   max(last_ingested) FILTER (WHERE status = 'success')                     AS last_success,
                   max(last_ingested)                                                       AS last_checked
            FROM cdm.ingest_manifest
            GROUP BY source_system
        """)).mappings().all()
        observations = dict(conn.execute(text(
            "SELECT source_system, count(*) FROM cdm.indicator_observation GROUP BY source_system"
        )).fetchall())
        names = {
            row[0]: (row[1] or {}).get("source_name") or row[0]
            for row in conn.execute(text("SELECT source_id, options FROM cdm.data_sources")).fetchall()
        }

    from pipeline.harvest.portals import HARVEST_PORTALS
    portal_titles = {f"harvest:{p['id']}": p["title"] for p in HARVEST_PORTALS}

    def iso(value):
        return value.isoformat() if value else None

    sources = []
    for row in loaded:
        key = row["source_system"]
        harvested = key.startswith("harvest:")
        sources.append({
            "id": key,
            "name": portal_titles.get(key) or names.get(key) or key,
            "kind": "listed from another portal" if harvested else "data held here",
            "datasets": row["with_data"],
            "checked_without_data": row["no_data"],
            "failed": row["failed"],
            "awaiting_publication": row["unpublished"],
            "observations": observations.get(key, 0),
            "last_successful_update": iso(row["last_success"]),
            "last_checked": iso(row["last_checked"]),
        })
    sources.sort(key=lambda item: (-item["datasets"], item["name"]))

    stamps = [s["last_successful_update"] for s in sources if s["last_successful_update"]]
    return {
        "sources": sources,
        "totals": {
            "datasets": sum(s["datasets"] for s in sources),
            "observations": sum(s["observations"] for s in sources),
            "sources": len(sources),
            "failed": sum(s["failed"] for s in sources),
            "last_successful_update": max(stamps) if stamps else None,
        },
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}
