"""General dataset branch of the existing Prefect ingestion flow."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from pipeline.settings import settings
from pipeline.portal import content, remote, store
from pipeline.portal.security import Principal, membership, unseal


def authorise(conn, job, row):
    if job["integration_token_id"]:
        token = store.one(conn, """SELECT * FROM cdm.portal_integration_tokens WHERE id=:id
            AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>NOW())""", id=job["integration_token_id"])
        scope = "datasets:publish" if job["action"] == "publish" else "ingest:trigger"
        # Legacy upload tokens retain their original upload scope for queued uploads.
        if not token or (scope not in token["scopes"] and not (job["action"] == "ingest" and ({"uploads:write", "datasets:submit"} & set(token["scopes"])))):
            raise HTTPException(403, "Job authorisation was revoked.")
        who = Principal(None, None, True, None, token["id"], token["publisher_id"], frozenset(token["scopes"]))
    else:
        user = store.one(conn, "SELECT id,email,verified_at FROM cdm.portal_users WHERE id=:id AND is_active=true", id=job["actor_id"])
        if not user or not user["verified_at"]:
            raise HTTPException(403, "Job authorisation was revoked.")
        who = Principal(user["id"], user["email"], True, None)
    membership(conn, who, row["publisher_id"], write=True)
    return who


def claim(job_id):
    with store.engine().begin() as conn:
        row = store.one(conn, """UPDATE cdm.portal_jobs SET status='processing',attempts=attempts+1,
            progress=5,phase='Starting processing',lease_until=NOW()+INTERVAL '15 minutes',updated_at=NOW()
            WHERE id=:id AND status='queued' RETURNING *""", id=job_id)
        if row:
            store.execute(conn, "INSERT INTO cdm.portal_job_attempts(job_id,attempt,status) VALUES (:id,:attempt,'processing')", id=job_id, attempt=row["attempts"])
    return row


def phase(job, percent, message):
    with store.engine().begin() as conn:
        store.execute(conn, """UPDATE cdm.portal_jobs SET progress=:p,phase=:phase,updated_at=NOW(),lease_until=NOW()+INTERVAL '15 minutes'
            WHERE id=:id AND attempts=:a AND status='processing'""", id=job["id"], a=job["attempts"], p=percent, phase=message)


def read_data(row, credentials, job=None):
    config = row["connection"] or {}
    originals = []
    if row["access_method"] == "file":
        with store.engine().connect() as conn:
            file = store.one(conn, "SELECT * FROM cdm.portal_files WHERE dataset_id=:d AND kind='original' ORDER BY created_at DESC LIMIT 1", d=row["dataset_id"])
        if not file:
            raise ValueError("Original file unavailable")
        data = content.file_path(settings.landing_root, file["storage_key"]).read_bytes()
        return content.parse(data, file["format"]), [file]
    if row["access_method"] == "legacy":
        # Registered indicator sources still use their existing CDM transforms.
        from pipeline.flows.ingest_flow import ingest_flow
        result = ingest_flow(row["source_system"])
        if any(item.get("status") == "failed" for item in result.values()):
            raise ValueError("Legacy indicator ingestion failed")
        return {"rows": [], "needs_review": True, "legacy": True}, []
    url = remote.with_params(config["url"], config.get("parameters", {}))
    fmt = config["format"]
    pagination = config.get("pagination", {"mode": "none"})
    limit = pagination.get("max_pages", 1) if pagination["mode"] == "page" and row["access_method"] == "api" else 1
    rows, review = [], False
    for page in range(limit):
        if job:
            phase(job, 15 + page * 50 // limit, f"Fetching page {page + 1}")
        endpoint = (remote.with_params(url, {pagination["page_parameter"]: pagination["first_page"] + page})
                    if pagination["mode"] == "page" and row["access_method"] == "api" else url)
        data, _ = remote.get(endpoint, credentials)
        saved = content.save(settings.landing_root, row["dataset_id"], data, fmt)
        saved["original_name"] = f"download-page-{page + 1}.{fmt}"
        originals.append(saved)
        parsed = content.parse(data, fmt, config.get("records_path", ""), config.get("column_mapping", {}))
        rows.extend(parsed["rows"])
        content.normalise(rows)
        review |= parsed["needs_review"]
        if not parsed["rows"]:
            break
        if limit > 1 and page == limit - 1:
            # A non-empty final page means we cannot assert that history is complete.
            review = True
    return {"rows": rows, "needs_review": review}, originals


def attach_file(conn, dataset_id, job_id, kind, file):
    value = store.one(conn, """INSERT INTO cdm.portal_files
        (dataset_id,job_id,kind,storage_key,original_name,format,sha256,size_bytes)
        VALUES (:d,:job,:kind,:key,:name,:fmt,:hash,:size)
        ON CONFLICT(dataset_id,kind,sha256) DO UPDATE SET sha256=EXCLUDED.sha256 RETURNING id""",
        d=dataset_id, job=job_id, kind=kind, key=file["storage_key"], name=file["original_name"],
        fmt=file["format"], hash=file["sha256"], size=file["size_bytes"])
    store.execute(conn, "INSERT INTO cdm.portal_job_files(job_id,file_id) VALUES (:j,:f) ON CONFLICT DO NOTHING", j=job_id, f=value["id"])


def schema(rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    return [{"name": column, "types": sorted({type(row[column]).__name__ for row in rows if row.get(column) is not None})} for column in columns]


def finish(conn, job, status, error=None):
    store.execute(conn, """UPDATE cdm.portal_jobs SET status=:status,progress=:progress,phase=:phase,
        error_code=:error,lease_until=NULL,updated_at=NOW() WHERE id=:id AND attempts=:attempt""",
        status=status, progress=100 if status != "failed" else 0,
        phase={"completed": "Completed", "needs_review": "Review the original and extracted results", "failed": "Job failed; review details and retry"}[status],
        error=error, id=job["id"], attempt=job["attempts"])
    store.execute(conn, """UPDATE cdm.portal_job_attempts SET status=:status,error_code=:error,finished_at=NOW()
        WHERE job_id=:id AND attempt=:attempt""", status=status, error=error, id=job["id"], attempt=job["attempts"])


def process_job(source_id, job_id):
    job = claim(job_id)
    if not job:
        return {"status": "already_claimed_or_finished"}
    try:
        with store.engine().connect() as conn:
            row = store.one(conn, "SELECT * FROM cdm.dataset_registry WHERE dataset_id=:d", d=job["dataset_id"])
            if job["source_id"] != source_id or row["source_system"] != source_id:
                raise ValueError("Job source does not match dataset")
            authorise(conn, job, row)
        if job["action"] == "publish":
            phase(job, 30, "Updating the catalog")
            with store.engine().begin() as conn:
                # Hold the job/dataset lock through publication. A stale worker cannot
                # commit after its lease was reclaimed; membership is checked again.
                live = store.one(conn, "SELECT * FROM cdm.portal_jobs WHERE id=:id FOR UPDATE", id=job_id)
                if live["attempts"] != job["attempts"] or live["status"] != "processing":
                    return {"status": "superseded"}
                authorise(conn, live, row)
                from pipeline.publisher import publish_dataset_to_ckan
                files = store.all_rows(conn, """SELECT f.* FROM cdm.portal_files f JOIN cdm.portal_job_files j ON j.file_id=f.id
                    WHERE j.job_id=:job ORDER BY f.kind""", job=row["last_ingested_job"])
                if not files:
                    raise ValueError("No processed files available")
                for file in files:
                    content.file_path(settings.landing_root, file["storage_key"])
                publisher = store.one(conn, "SELECT * FROM cdm.publishers WHERE id=:id", id=row["publisher_id"])
                publish_dataset_to_ckan(row, files, publisher)
                store.execute(conn, "UPDATE cdm.dataset_registry SET publication_state='published',is_public=true,updated_at=NOW() WHERE dataset_id=:d", d=row["dataset_id"])
                for file in files:
                    store.execute(conn, "UPDATE cdm.portal_files SET published=true WHERE id=:id", id=file["id"])
                finish(conn, job, "completed")
            return {"status": "completed"}
        phase(job, 15, "Fetching and validating the original")
        credentials = json.loads(unseal(row["credentials_ciphertext"])) if row["credentials_ciphertext"] else None
        parsed, originals = read_data(row, credentials, job)
        phase(job, 70, "Saving validated records")
        rows = parsed["rows"]
        processed = None
        if rows:
            processed = content.save(settings.landing_root, row["dataset_id"], content.csv_export(rows), "csv")
            processed["original_name"] = "validated-data.csv"
        state = "needs_review" if parsed["needs_review"] else "completed"
        with store.engine().begin() as conn:
            live = store.one(conn, "SELECT * FROM cdm.portal_jobs WHERE id=:id FOR UPDATE", id=job_id)
            if live["attempts"] != job["attempts"] or live["status"] != "processing":
                return {"status": "superseded"}
            authorise(conn, live, row)
            for file in originals:
                attach_file(conn, row["dataset_id"], job_id, "original", file)
            if processed:
                attach_file(conn, row["dataset_id"], job_id, "processed", processed)
            for number, record in enumerate(rows):
                store.execute(conn, """INSERT INTO cdm.portal_tabular_rows(dataset_id,job_id,row_number,record)
                    VALUES (:d,:job,:number,CAST(:record AS jsonb)) ON CONFLICT DO NOTHING""",
                    d=row["dataset_id"], job=job_id, number=number, record=json.dumps(record, allow_nan=False))
            schedule = row["connection"].get("schedule", "manual")
            next_due = datetime.now(timezone.utc) + timedelta(days=1 if schedule == "daily" else 7) if schedule != "manual" else None
            store.execute(conn, """UPDATE cdm.dataset_registry SET processing_state=:state,row_count=:count,
                tabular_schema=CAST(:schema AS jsonb),last_ingested_job=:job,next_due_at=:due,updated_at=NOW()
                WHERE dataset_id=:d""", state=state, count=len(rows), schema=json.dumps(schema(rows)), job=job_id, due=next_due, d=row["dataset_id"])
            finish(conn, job, state)
        return {"status": state, "rows": len(rows)}
    except Exception as error:
        code = "authorisation_revoked" if isinstance(error, HTTPException) else "publication_failed" if job["action"] == "publish" else "processing_failed"
        with store.engine().begin() as conn:
            live = store.one(conn, "SELECT * FROM cdm.portal_jobs WHERE id=:id FOR UPDATE", id=job_id)
            if live["attempts"] == job["attempts"] and live["status"] == "processing":
                finish(conn, job, "failed", code)
                if job["action"] == "ingest":
                    store.execute(conn, "UPDATE cdm.dataset_registry SET processing_state='failed',updated_at=NOW() WHERE dataset_id=:d", d=job["dataset_id"])
        # No source URLs, raw parser input, credentials or SQL errors in Prefect logs.
        return {"status": "failed", "error_code": code}
