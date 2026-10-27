"""Scoped compatibility for automated clients; interactive forms use sessions."""
import json
import re
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import Field, SecretStr
from pipeline.portal import content, remote, store
from pipeline.portal.auth import Model
from pipeline.portal.datasets import create, create_upload, queue_job, read_upload
from pipeline.portal.models import Metadata
from pipeline.portal.security import membership, principal
from pipeline.settings import settings

router = APIRouter(tags=["Legacy automated integrations"])
PAIRS = {
    "pipeline.connectors.cbn.CBNConnector": "pipeline.transforms.cbn_transform.transform",
    "pipeline.connectors.nigeria_data_portal.NigeriaDataPortalConnector": "pipeline.transforms.nigeria_data_portal_transform.transform",
    "pipeline.connectors.generic.GenericFileConnector": "pipeline.transforms.generic_transform.generic_transform",
}


class Source(Model):
    publisher_api_key: SecretStr | None = None
    organisation_id: uuid.UUID | None = None
    source_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,99}$")
    connector: str
    transform: str
    domain: str = Field(max_length=100)
    schedule: str = Field(max_length=100)
    landing_dir: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    ingest_mode: str
    indicators: list[dict] = Field(min_length=1, max_length=100)


def source_owned(conn, who, source_id):
    row = store.one(conn, "SELECT * FROM cdm.data_sources WHERE source_id=:id AND is_active=true", id=source_id)
    if not row or not row["publisher_id"]:
        raise HTTPException(403, "This source requires operator approval or belongs to another organisation.")
    membership(conn, who, row["publisher_id"], write=True)
    return row


@router.post("/api/publishers")
async def legacy_publisher(request: Request):
    await principal(request, legacy=True)
    raise HTTPException(410, "Use account registration and organisation onboarding. Manage tokens under Integrations.")


@router.post("/api/sources")
async def register(body: Source, request: Request):
    who = await principal(request, "sources:write", legacy=True)
    publisher = who.publisher_id if who.token_id else body.organisation_id
    if not publisher:
        raise HTTPException(422, "Select an authorised organisation.")
    from croniter import croniter
    if body.schedule and not croniter.is_valid(body.schedule):
        raise HTTPException(422, "Update schedule is invalid.")
    with store.engine().begin() as conn:
        membership(conn, who, publisher, write=True)
        existing = store.one(conn, "SELECT * FROM cdm.data_sources WHERE source_id=:id FOR UPDATE", id=body.source_id)
        if existing and str(existing["publisher_id"]) != str(publisher):
            raise HTTPException(403, "This source belongs to another organisation.")
        if existing and existing["ingest_mode"] == "publisher":
            raise HTTPException(409, "Managed publisher sources must be edited through the dataset API.")
        if PAIRS.get(body.connector) != body.transform and not (existing and existing["connector"] == body.connector and existing["transform"] == body.transform):
            raise HTTPException(422, "This connector must be installed and approved by the operator.")
        if body.ingest_mode not in {"api", "file", "document"}:
            raise HTTPException(422, "Unsupported legacy ingest mode.")
        for indicator in body.indicators:
            allowed = {"id", "name", "unit", "dataset_id", "excel_url", "sheet", "header", "col_map", "period_type", "geo_level", "geo_name", "geo_code", "notes"}
            if set(indicator) - allowed:
                raise HTTPException(422, "Custom indicator fields require operator approval.")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", indicator.get("id", "")) or not indicator.get("name"):
                raise HTTPException(422, "Indicators require safe identifiers and names.")
            if indicator.get("dataset_id") and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", indicator["dataset_id"]):
                raise HTTPException(422, "Dataset identifiers must be safe names.")
            if len(json.dumps(indicator)) > 10000:
                raise HTTPException(422, "Indicator configuration exceeds the size limit.")
            if indicator.get("excel_url"):
                try:
                    remote.validate_url(indicator["excel_url"])
                except ValueError as error:
                    raise HTTPException(422, str(error)) from None
        store.execute(conn, """INSERT INTO cdm.data_sources
            (publisher_id,source_id,connector,transform,domain,schedule,landing_dir,ingest_mode,indicators)
            VALUES (:p,:id,:connector,:transform,:domain,:schedule,:landing,:mode,CAST(:indicators AS jsonb))
            ON CONFLICT(source_id) DO UPDATE SET connector=EXCLUDED.connector,transform=EXCLUDED.transform,
            domain=EXCLUDED.domain,schedule=EXCLUDED.schedule,landing_dir=EXCLUDED.landing_dir,
            ingest_mode=EXCLUDED.ingest_mode,indicators=EXCLUDED.indicators""",
            p=publisher, id=body.source_id, connector=body.connector, transform=body.transform,
            domain=body.domain, schedule=body.schedule, landing=body.landing_dir, mode=body.ingest_mode,
            indicators=json.dumps([{key: value for key, value in indicator.items() if value is not None} for indicator in body.indicators]))
    return {"status": "success", "source_id": body.source_id}


@router.post("/api/upload", status_code=202)
async def upload(request: Request, source_id: str = Form(...), publisher_api_key: str = Form(default=""), file: UploadFile = File(...)):
    who = await principal(request, "uploads:write", legacy=True)
    with store.engine().connect() as conn:
        source = source_owned(conn, who, source_id)
    data = await read_upload(file)
    await file.close()
    try:
        fmt = content.filename(file.filename)
        content.validate(data, fmt)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    values = Metadata(organisation_id=source["publisher_id"], title=f"{source_id} upload",
        description="Uploaded through an existing authorised integration.", topic=source["domain"] if source["domain"] in {"health", "economics", "agric", "education"} else "general",
        licence="Unspecified; operator review required", original_provider=source_id, provenance="Existing publisher integration")
    with store.engine().begin() as conn:
        import hashlib
        result = create_upload(conn, who, values, request.headers.get("idempotency-key") or f"legacy-{hashlib.sha256(data).hexdigest()}", data, fmt, file.filename, legacy_source=source_id)
    return {"status": "queued", **result}


@router.post("/api/sources/{source_id}/trigger", status_code=202)
@router.post("/scrape/source/{source_id}", status_code=202)
async def trigger(source_id: str, request: Request):
    who = await principal(request, "ingest:trigger", legacy=True)
    with store.engine().begin() as conn:
        source = source_owned(conn, who, source_id)
        row = store.one(conn, "SELECT * FROM cdm.dataset_registry WHERE source_system=:s AND publisher_id=:p ORDER BY created_at DESC LIMIT 1 FOR UPDATE", s=source_id, p=source["publisher_id"])
        if row:
            return queue_job(conn, row, who)
        values = Metadata(organisation_id=source["publisher_id"], title=f"{source_id} indicators",
            description="Registered indicator ingestion through the existing Prefect flow.", topic=source["domain"] if source["domain"] in {"health", "economics", "agric", "education"} else "general",
            licence="Original provider's terms apply", original_provider=source_id, provenance="Existing source registry")
        return create(conn, who, values, "legacy", request.headers.get("idempotency-key") or f"initial-{source_id}", connection={"format": "json"}, legacy_source=source_id)


@router.post("/scrape/batch")
async def batch(request: Request):
    await principal(request, "ingest:trigger", legacy=True)
    raise HTTPException(410, "Trigger authorised sources individually. Unscoped batch ingestion is disabled.")


@router.get("/api/publishers")
def public_publishers():
    with store.engine().connect() as conn:
        return store.all_rows(conn, "SELECT id,name,is_active,created_at FROM cdm.publishers WHERE is_active=true ORDER BY name")


@router.get("/api/sources")
def public_sources():
    with store.engine().connect() as conn:
        return store.all_rows(conn, """SELECT source_id,domain,ingest_mode,is_active FROM cdm.data_sources s
            WHERE is_active=true AND (ingest_mode<>'publisher' OR EXISTS(SELECT 1 FROM cdm.dataset_registry d
                WHERE d.source_system=s.source_id AND d.is_public=true AND d.publication_state='published')) ORDER BY source_id""")


@router.get("/api/sources/{source_id}/observations")
def observations(source_id: str, limit: int = 1000, offset: int = 0):
    limit = max(1, min(limit, 10000))
    offset = max(0, offset)
    with store.engine().connect() as conn:
        return store.all_rows(conn, """SELECT indicator_id,indicator_name,geo_level,geo_name,period,value,unit,last_updated_at
            FROM cdm.indicator_observation WHERE source_system=:s ORDER BY period DESC,indicator_id,geo_code LIMIT :limit OFFSET :offset""",
            s=source_id, limit=limit, offset=offset)
