from __future__ import annotations

import hashlib
import json
import re
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field, ValidationError

from pipeline.settings import settings
from pipeline.portal import content, remote, store
from pipeline.portal.auth import Model
from pipeline.portal.models import Metadata, Submission, TestConnection
from pipeline.portal.security import membership, principal, recent, seal

router = APIRouter(prefix="/api/portal", tags=["Publisher datasets"])
public_router = APIRouter(prefix="/api/public", tags=["Public dataset downloads"])


def dataset(conn, who, identifier, write=False):
    row = store.one(conn, "SELECT * FROM cdm.dataset_registry WHERE dataset_id=:id", id=identifier)
    if not row or not row["publisher_id"]:
        raise HTTPException(404, "Dataset not found in the publisher dashboard.")
    membership(conn, who, row["publisher_id"], write=write)
    return row


def view(row):
    # Never serialize storage locations, sealed credentials or internal connector config.
    keys = ["dataset_id", "source_system", "display_name", "description", "domain", "format", "row_count",
            "publisher_id", "licence", "original_provider", "provenance", "access_method", "processing_state",
            "publication_state", "tabular_schema", "created_at", "updated_at"]
    result = {key: row.get(key) for key in keys}
    result["connection"] = {key: row.get("connection", {}).get(key) for key in ["name", "schedule", "format", "records_path", "pagination", "column_mapping"]}
    result["has_external_credentials"] = bool(row.get("credentials_ciphertext"))
    return result


def queue_job(conn, row, who, action="ingest"):
    if store.one(conn, "SELECT id FROM cdm.portal_jobs WHERE dataset_id=:d AND status IN ('queued','processing')", d=row["dataset_id"]):
        raise HTTPException(409, "This dataset already has an active job.")
    job = store.one(conn, """INSERT INTO cdm.portal_jobs(dataset_id,source_id,actor_id,integration_token_id,action,status)
        VALUES (:d,:s,:actor,:token,:action,'queued') RETURNING id,status,action""",
        d=row["dataset_id"], s=row["source_system"], actor=who.user_id, token=who.token_id, action=action)
    if action == "ingest":
        store.execute(conn, "UPDATE cdm.dataset_registry SET processing_state='queued',updated_at=NOW() WHERE dataset_id=:d", d=row["dataset_id"])
    return {"dataset_id": row["dataset_id"], "source_id": row["source_system"], "job_id": job["id"], "status": job["status"]}


def create(conn, who, metadata, method, key, file=None, connection=None, secret=None, legacy_source=None):
    membership(conn, who, metadata.organisation_id, write=True)
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        raise HTTPException(422, "Supply an Idempotency-Key for this submission.")
    # Serialize same-key requests before inserting any registry records.
    store.execute(conn, "SELECT pg_advisory_xact_lock(hashtext(:key))", key=f"{metadata.organisation_id}:{key}")
    fingerprint = submission_fingerprint(metadata, method, file["sha256"] if file else None, connection, secret)
    prior = store.one(conn, "SELECT * FROM cdm.portal_submissions WHERE publisher_id=:p AND idempotency_key=:k", p=metadata.organisation_id, k=key)
    if prior:
        if fingerprint != prior["fingerprint"]:
            raise HTTPException(409, "This submission key was already used for different data.")
        job = store.one(conn, "SELECT id,status FROM cdm.portal_jobs WHERE dataset_id=:d ORDER BY created_at LIMIT 1", d=prior["dataset_id"])
        source = store.one(conn, "SELECT source_system FROM cdm.dataset_registry WHERE dataset_id=:d", d=prior["dataset_id"])
        return {"dataset_id": prior["dataset_id"], "source_id": source["source_system"], "job_id": job["id"], "status": job["status"]}
    identifier = file["dataset_id"] if file else f"dataset-{uuid.uuid4().hex}"
    source_id = legacy_source or f"source-{uuid.uuid4().hex}"
    if not legacy_source:
        store.execute(conn, """INSERT INTO cdm.data_sources
            (publisher_id,source_id,connector,transform,domain,schedule,landing_dir,ingest_mode,indicators)
            VALUES (:p,:s,'pipeline.connectors.generic.GenericFileConnector',
            'pipeline.transforms.generic_transform.generic_transform',:topic,'',:landing,'publisher','[]')""",
            p=metadata.organisation_id, s=source_id, topic=metadata.topic, landing=f"portal/{identifier}")
    store.execute(conn, """INSERT INTO cdm.dataset_registry
        (dataset_id,source_system,display_name,description,domain,format,storage_url,is_public,publisher_id,
        created_by,licence,original_provider,provenance,access_method,connection,credentials_ciphertext,
        processing_state,publication_state)
        VALUES (:d,:s,:title,:description,:topic,:format,'',false,:p,:actor,:licence,:provider,:provenance,
        :method,CAST(:connection AS jsonb),:secret,'queued','unpublished')""",
        d=identifier, s=source_id, title=metadata.title, description=metadata.description, topic=metadata.topic,
        format=file["format"] if file else connection.get("format", "json"), p=metadata.organisation_id,
        actor=who.user_id, licence=metadata.licence, provider=metadata.original_provider, provenance=metadata.provenance,
        method=method, connection=json.dumps(connection or {}), secret=seal(json.dumps(secret)) if secret else None)
    if file:
        store.execute(conn, """INSERT INTO cdm.portal_files
            (dataset_id,kind,storage_key,original_name,format,sha256,size_bytes)
            VALUES (:d,'original',:key,:name,:fmt,:hash,:size)""",
            d=identifier, key=file["storage_key"], name=file["original_name"], fmt=file["format"], hash=file["sha256"], size=file["size_bytes"])
    row = store.one(conn, "SELECT * FROM cdm.dataset_registry WHERE dataset_id=:d", d=identifier)
    job = queue_job(conn, row, who)
    store.execute(conn, "INSERT INTO cdm.portal_submissions(publisher_id,idempotency_key,fingerprint,dataset_id) VALUES (:p,:k,:f,:d)", p=metadata.organisation_id, k=key, f=fingerprint, d=identifier)
    return job


async def read_upload(file):
    data = bytearray()
    while chunk := await file.read(65536):
        data.extend(chunk)
        if len(data) > remote.MAX_BYTES:
            raise HTTPException(413, "Uploads are limited to 50 MB.")
    return bytes(data)


def submission_fingerprint(metadata, method, file_hash=None, connection=None, secret=None):
    return hashlib.sha256(json.dumps({"metadata": metadata.model_dump(mode="json"), "method": method,
        "connection": connection, "file": file_hash,
        "credential_hash": hashlib.sha256(json.dumps(secret).encode()).hexdigest() if secret else None}, sort_keys=True).encode()).hexdigest()


@router.post("/datasets/upload", status_code=202)
async def upload(request: Request, metadata: str = Form(...), file: UploadFile = File(...)):
    who = await principal(request, "datasets:submit")
    try:
        values = Metadata.model_validate_json(metadata)
    except ValidationError:
        raise HTTPException(422, "Complete the title, description, topic, licence, provenance and organisation fields.") from None
    with store.engine().connect() as conn:
        membership(conn, who, values.organisation_id, write=True)
    try:
        fmt = content.filename(file.filename)
        data = await read_upload(file)
        content.validate(data, fmt)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    finally:
        await file.close()
    with store.engine().begin() as conn:
        return create_upload(conn, who, values, request.headers.get("idempotency-key"), data, fmt, file.filename)


def create_upload(conn, who, values, key, data, fmt, name, legacy_source=None):
    membership(conn, who, values.organisation_id, write=True)
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        raise HTTPException(422, "Supply an Idempotency-Key for this submission.")
    store.execute(conn, "SELECT pg_advisory_xact_lock(hashtext(:key))", key=f"{values.organisation_id}:{key}")
    prior = store.one(conn, "SELECT * FROM cdm.portal_submissions WHERE publisher_id=:p AND idempotency_key=:k", p=values.organisation_id, k=key)
    if prior and prior["fingerprint"] != submission_fingerprint(values, "file", hashlib.sha256(data).hexdigest()):
        raise HTTPException(409, "This submission key was already used for different data.")
    identifier = prior["dataset_id"] if prior else f"dataset-{uuid.uuid4().hex}"
    saved = content.save(settings.landing_root, identifier, data, fmt)
    saved.update({"dataset_id": identifier, "original_name": name})
    return create(conn, who, values, "file", key, file=saved, legacy_source=legacy_source)


@router.post("/datasets", status_code=202)
async def submit(body: Submission, request: Request):
    who = await principal(request, "datasets:submit")
    with store.engine().connect() as conn:
        membership(conn, who, body.organisation_id, write=True)
    if body.connection.credentials:
        recent(who)
    try:
        remote.validate_url(remote.with_params(body.connection.url, body.connection.parameters))
        if body.connection.credentials and not body.connection.url.startswith("https://"):
            raise ValueError("Authenticated APIs require HTTPS.")
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    with store.engine().begin() as conn:
        return create(conn, who, Metadata.model_validate(body.model_dump(include=set(Metadata.model_fields))),
            body.access_method, request.headers.get("idempotency-key"), connection=body.connection.public_config(), secret=body.connection.secret_config())


@router.post("/connections/test")
async def test_connection(body: TestConnection, request: Request):
    who = await principal(request, "datasets:submit")
    from pipeline.portal.security import rate_limit
    rate_limit(request, "connection-test", str(who.user_id or who.token_id), 10)
    with store.engine().connect() as conn:
        membership(conn, who, body.organisation_id, write=True)
    if body.connection.credentials:
        recent(who)
    try:
        endpoint = remote.with_params(body.connection.url, body.connection.parameters)
        if body.connection.pagination.mode == "page":
            endpoint = remote.with_params(endpoint, {body.connection.pagination.page_parameter: body.connection.pagination.first_page})
        data, _ = remote.get(endpoint, body.connection.secret_config(), max_bytes=1024 * 1024)
        rows = content.json_records(data, body.connection.records_path)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return {"supported": True, "record_count_in_response": len(rows), "preview": remote.redact(rows[:5]),
            "message": "GET JSON preview only. Page-number pagination is supported; cursor pagination, POST APIs and nested table cells require a connector."}


@router.get("/datasets")
async def datasets(request: Request, organisation_id: uuid.UUID):
    who = await principal(request, "datasets:read")
    with store.engine().connect() as conn:
        membership(conn, who, organisation_id)
        rows = store.all_rows(conn, "SELECT * FROM cdm.dataset_registry WHERE publisher_id=:p ORDER BY created_at DESC LIMIT 200", p=organisation_id)
        return [view(row) for row in rows]


@router.get("/datasets/{dataset_id}")
async def detail(dataset_id: str, request: Request):
    who = await principal(request, "datasets:read")
    with store.engine().connect() as conn:
        row = dataset(conn, who, dataset_id)
        result = view(row)
        result["files"] = store.all_rows(conn, "SELECT id,kind,original_name,format,size_bytes,sha256 FROM cdm.portal_files WHERE dataset_id=:d ORDER BY created_at", d=dataset_id)
        result["jobs"] = store.all_rows(conn, "SELECT id,action,status,progress,phase,attempts,error_code,created_at,updated_at FROM cdm.portal_jobs WHERE dataset_id=:d ORDER BY created_at DESC LIMIT 50", d=dataset_id)
        result["preview"] = remote.redact([item["record"] for item in store.all_rows(conn, "SELECT record FROM cdm.portal_tabular_rows WHERE dataset_id=:d AND job_id=:job ORDER BY row_number LIMIT 5", d=dataset_id, job=row["last_ingested_job"])])
        return result


class Edit(Model):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    licence: str = Field(min_length=3, max_length=2000)
    original_provider: str = Field(min_length=2, max_length=200)
    provenance: str = Field(min_length=3, max_length=2000)


@router.patch("/datasets/{dataset_id}")
async def edit(dataset_id: str, body: Edit, request: Request):
    who = await principal(request, "datasets:submit")
    with store.engine().begin() as conn:
        dataset(conn, who, dataset_id, write=True)
        store.execute(conn, "SELECT dataset_id FROM cdm.dataset_registry WHERE dataset_id=:d FOR UPDATE", d=dataset_id)
        if store.one(conn, "SELECT id FROM cdm.portal_jobs WHERE dataset_id=:d AND status IN ('queued','processing')", d=dataset_id):
            raise HTTPException(409, "Wait for the active job before editing metadata.")
        store.execute(conn, """UPDATE cdm.dataset_registry SET display_name=:title,description=:description,
            licence=:licence,original_provider=:provider,provenance=:provenance,updated_at=NOW() WHERE dataset_id=:d""",
            d=dataset_id, title=body.title, description=body.description, licence=body.licence, provider=body.original_provider, provenance=body.provenance)
    return {"message": "Metadata saved. Publish again to update the catalog."}


@router.post("/datasets/{dataset_id}/ingest", status_code=202)
async def ingest(dataset_id: str, request: Request):
    who = await principal(request, "ingest:trigger")
    with store.engine().begin() as conn:
        row = dataset(conn, who, dataset_id, write=True)
        store.execute(conn, "SELECT dataset_id FROM cdm.dataset_registry WHERE dataset_id=:d FOR UPDATE", d=dataset_id)
        return queue_job(conn, row, who)


class Publish(Model):
    reviewed: bool = False


@router.post("/datasets/{dataset_id}/publish", status_code=202)
async def publish(dataset_id: str, body: Publish, request: Request):
    who = await principal(request, "datasets:publish")
    recent(who)
    with store.engine().begin() as conn:
        row = dataset(conn, who, dataset_id, write=True)
        store.execute(conn, "SELECT dataset_id FROM cdm.dataset_registry WHERE dataset_id=:d FOR UPDATE", d=dataset_id)
        if row["processing_state"] not in {"completed", "needs_review"}:
            raise HTTPException(409, "Finish processing before publishing.")
        if row["processing_state"] == "needs_review" and not body.reviewed:
            raise HTTPException(409, "Review the original and extracted results before approving publication.")
        return queue_job(conn, row, who, "publish")


@router.get("/jobs/{job_id}")
async def job_detail(job_id: uuid.UUID, request: Request):
    who = await principal(request, "datasets:read")
    with store.engine().connect() as conn:
        row = store.one(conn, "SELECT * FROM cdm.portal_jobs WHERE id=:id", id=job_id)
        if not row:
            raise HTTPException(404, "Job not found.")
        dataset(conn, who, row["dataset_id"])
        result = {key: row[key] for key in ["id", "dataset_id", "action", "status", "progress", "phase", "attempts", "error_code", "created_at", "updated_at"]}
        result["history"] = store.all_rows(conn, "SELECT attempt,status,started_at,finished_at,error_code FROM cdm.portal_job_attempts WHERE job_id=:id ORDER BY attempt", id=job_id)
        return result


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry(job_id: uuid.UUID, request: Request):
    who = await principal(request, "ingest:trigger")
    with store.engine().begin() as conn:
        job = store.one(conn, "SELECT * FROM cdm.portal_jobs WHERE id=:id FOR UPDATE", id=job_id)
        if not job:
            raise HTTPException(404, "Job not found.")
        row = dataset(conn, who, job["dataset_id"], write=True)
        if who.token_id and job["action"] == "publish" and "datasets:publish" not in who.scopes:
            raise HTTPException(403, "Publication scope is required.")
        if job["action"] == "publish":
            recent(who)
        if job["status"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried.")
        store.execute(conn, "SELECT dataset_id FROM cdm.dataset_registry WHERE dataset_id=:d FOR UPDATE", d=row["dataset_id"])
        if store.one(conn, "SELECT id FROM cdm.portal_jobs WHERE dataset_id=:d AND status IN ('queued','processing')", d=row["dataset_id"]):
            raise HTTPException(409, "Another job is active for this dataset.")
        store.execute(conn, """UPDATE cdm.portal_jobs SET status='queued',progress=0,phase='Retry queued',
            error_code=NULL,prefect_run_id=NULL,actor_id=:actor,integration_token_id=:token,updated_at=NOW() WHERE id=:id""",
            id=job_id, actor=who.user_id, token=who.token_id)
        if job["action"] == "ingest":
            store.execute(conn, "UPDATE cdm.dataset_registry SET processing_state='queued' WHERE dataset_id=:d", d=row["dataset_id"])
    return {"job_id": job_id, "status": "queued"}


@router.get("/datasets/{dataset_id}/files/{file_id}")
async def private_file(dataset_id: str, file_id: uuid.UUID, request: Request):
    who = await principal(request, "datasets:read")
    with store.engine().connect() as conn:
        dataset(conn, who, dataset_id)
        file = store.one(conn, "SELECT * FROM cdm.portal_files WHERE id=:id AND dataset_id=:d", id=file_id, d=dataset_id)
    return download(file)


def download(file):
    if not file:
        raise HTTPException(404, "File not found.")
    try:
        path = content.file_path(settings.landing_root, file["storage_key"])
    except ValueError:
        raise HTTPException(404, "Stored file is unavailable.") from None
    return FileResponse(path, filename=f"dataset-{file['id']}.{file['format']}", media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@public_router.get("/datasets/{dataset_id}/files/{file_id}")
def public_file(dataset_id: str, file_id: uuid.UUID):
    with store.engine().connect() as conn:
        row = store.one(conn, "SELECT is_public,publication_state FROM cdm.dataset_registry WHERE dataset_id=:d", d=dataset_id)
        if not row or not row["is_public"] or row["publication_state"] != "published":
            raise HTTPException(404, "This file is not published.")
        file = store.one(conn, "SELECT * FROM cdm.portal_files WHERE dataset_id=:d AND id=:id AND published=true", d=dataset_id, id=file_id)
    return download(file)
