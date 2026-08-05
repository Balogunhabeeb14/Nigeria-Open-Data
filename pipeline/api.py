from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import json
from sqlalchemy import text
from pipeline.db.warehouse import get_engine

app = FastAPI(
    title="Nigeria Open Data - Ingestion API",
    description="API for external publishers to register new data sources and indicators.",
    version="1.0.0"
)

from pipeline.settings import settings
from pipeline.scrape import router as scrape_router

# Add CORS middleware to allow requests from the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scrape_router)

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

@app.post("/api/publishers")
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

@app.post("/api/sources")
def register_source(src: SourceCreate):
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
            conn.execute(
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
                    indicators = EXCLUDED.indicators;
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
            return {"status": "success", "source_id": src.source_id}
        except Exception as e:
            print(f"Error registering source: {e}")
            raise HTTPException(status_code=400, detail="Could not configure dataset. Please ensure the details are correct.")

@app.post("/api/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    source_id: str = Form(...),
    publisher_api_key: str = Form(...)
):
    import os
    from pathlib import Path
    
    engine = get_engine()
    with engine.begin() as conn:
        pub_result = conn.execute(
            text("SELECT id FROM cdm.publishers WHERE api_key = :api_key AND is_active = true"),
            {"api_key": publisher_api_key}
        ).fetchone()
        
        if not pub_result:
            raise HTTPException(status_code=401, detail="Invalid Publisher Access Token. Please check your password.")
            
    # Save the file to landing zone
    # We use a lowercased source_id as the folder name
    landing_dir = source_id.lower().replace(" ", "_")
    landing_root = Path("data/raw") / landing_dir
    landing_root.mkdir(parents=True, exist_ok=True)
    
    file_path = landing_root / file.filename
    
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        return {"status": "success", "file_path": str(file_path)}
    except Exception as e:
        print(f"Error uploading dataset: {e}")
        raise HTTPException(status_code=500, detail="Could not securely save the dataset file. Please try again.")

@app.get("/api/publishers")
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
def get_source_observations(source_id: str):
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT indicator_id, indicator_name, geo_level, geo_name, period, value, unit, last_updated_at 
                FROM cdm.indicator_observation 
                WHERE source_system = :source_id 
                ORDER BY period DESC
            """),
            {"source_id": source_id}
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

@app.get("/health")
def health_check():
    return {"status": "ok"}
