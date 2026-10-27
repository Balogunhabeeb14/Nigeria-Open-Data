"""Transactional job outbox delivered to the existing Prefect ingestion deployment."""
import requests
from prefect import flow

from pipeline.portal import mail, store
from pipeline.portal.datasets import queue_job
from pipeline.portal.processing import authorise
from pipeline.settings import settings


def dispatch(job):
    url = settings.prefect_api_url.rstrip("/")
    response = requests.post(f"{url}/deployments/filter", json={"deployments": {"name": {"any_": ["publisher-job"]}}}, timeout=10)
    response.raise_for_status()
    deployments = response.json()
    if len(deployments) != 1:
        raise RuntimeError("Publisher ingestion deployment unavailable")
    response = requests.post(f"{url}/deployments/{deployments[0]['id']}/create_flow_run", json={
        "parameters": {"source_id": job["source_id"], "job_id": str(job["id"])},
        "idempotency_key": f"publisher-job:{job['id']}:{job['attempts']+1}",
    }, timeout=10)
    response.raise_for_status()
    return response.json()["id"]


def tick():
    mail.drain()
    with store.engine().begin() as conn:
        expired = store.all_rows(conn, """SELECT id,attempts,dataset_id,action FROM cdm.portal_jobs
            WHERE status='processing' AND lease_until<NOW() FOR UPDATE SKIP LOCKED""")
        for job in expired:
            store.execute(conn, """UPDATE cdm.portal_job_attempts SET status='failed',finished_at=NOW(),error_code='worker_interrupted'
                WHERE job_id=:id AND attempt=:a""", id=job["id"], a=job["attempts"])
            state = "failed" if job["attempts"] >= 3 else "queued"
            store.execute(conn, """UPDATE cdm.portal_jobs SET status=:s,prefect_run_id=NULL,lease_until=NULL,
                error_code='worker_interrupted',phase='Worker interrupted',updated_at=NOW() WHERE id=:id""", s=state, id=job["id"])
            if job["action"] == "ingest":
                store.execute(conn, "UPDATE cdm.dataset_registry SET processing_state=:s WHERE dataset_id=:d", s=state, d=job["dataset_id"])
        # Scheduled sources enter the same outbox as interactive submissions.
        scheduled = store.all_rows(conn, """SELECT d.* FROM cdm.dataset_registry d
            WHERE d.next_due_at<=NOW() AND d.access_method IN ('api','url')
            AND NOT EXISTS(SELECT 1 FROM cdm.portal_jobs j WHERE j.dataset_id=d.dataset_id AND j.status IN ('queued','processing'))
            ORDER BY d.next_due_at LIMIT 20 FOR UPDATE SKIP LOCKED""")
        for row in scheduled:
            previous = store.one(conn, "SELECT * FROM cdm.portal_jobs WHERE dataset_id=:d AND action='ingest' ORDER BY created_at DESC LIMIT 1", d=row["dataset_id"])
            try:
                who = authorise(conn, previous, row)
            except Exception:
                store.execute(conn, "UPDATE cdm.dataset_registry SET next_due_at=NULL WHERE dataset_id=:d", d=row["dataset_id"])
                continue
            queue_job(conn, row, who)
            store.execute(conn, "UPDATE cdm.dataset_registry SET next_due_at=NULL WHERE dataset_id=:d", d=row["dataset_id"])
    delivered = 0
    with store.engine().begin() as conn:
        jobs = store.all_rows(conn, """SELECT * FROM cdm.portal_jobs WHERE status='queued' AND prefect_run_id IS NULL
            ORDER BY created_at LIMIT 10 FOR UPDATE SKIP LOCKED""")
        for job in jobs:
            try:
                run_id = dispatch(job)
                store.execute(conn, "UPDATE cdm.portal_jobs SET prefect_run_id=:run WHERE id=:id", run=run_id, id=job["id"])
                delivered += 1
            except Exception:
                # The durable queued row survives outages and is retried on the next tick.
                # The stable Prefect idempotency key prevents duplicate flow creation.
                continue
    return {"dispatched": delivered}


@flow(name="publisher_dispatcher", log_prints=False)
def portal_dispatcher():
    return tick()
