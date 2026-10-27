import io
import json
import uuid

from sqlalchemy import text
from pipeline.portal import content, remote, processing
from pipeline.tests.conftest import metadata, upload


def process(result):
    value = result.json()
    return processing.process_job(value["source_id"], value["job_id"])


def test_upload_generates_ids_is_durable_and_idempotent(client, portal, owner):
    result = upload(client, owner)
    assert result.status_code == 202, result.text
    value = result.json()
    assert value["dataset_id"].startswith("dataset-") and value["source_id"].startswith("source-")
    assert upload(client, owner).json() == value
    assert upload(client, owner, data=b"state,value\nAbuja,22\n").status_code == 409
    assert process(result) == {"status": "completed", "rows": 2}
    assert process(result)["status"] == "already_claimed_or_finished"
    detail = client.get(f"/api/portal/datasets/{value['dataset_id']}").json()
    assert len(detail["files"]) == 2 and len(detail["preview"]) == 2
    assert detail["publication_state"] == "unpublished"
    original = next(f for f in detail["files"] if f["kind"] == "original")
    assert client.get(f"/api/portal/datasets/{value['dataset_id']}/files/{original['id']}").content == b"state,value\nLagos,12\nKano,15\n"
    assert client.get(f"/api/public/datasets/{value['dataset_id']}/files/{original['id']}").status_code == 404
    with portal.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM cdm.indicator_observation")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM cdm.portal_tabular_rows")).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM cdm.portal_jobs")).scalar() == 1


def test_failure_retry_preserves_attempts_and_publication_is_separate(client, portal, owner, monkeypatch):
    result = upload(client, owner)
    original_parse = content.parse
    monkeypatch.setattr(content, "parse", lambda *args: (_ for _ in ()).throw(ValueError("fixture failure")))
    assert process(result)["status"] == "failed"
    assert client.post(f"/api/portal/jobs/{result.json()['job_id']}/retry").status_code == 202
    monkeypatch.setattr(content, "parse", original_parse)
    assert process(result)["status"] == "completed"
    history = client.get(f"/api/portal/jobs/{result.json()['job_id']}").json()["history"]
    assert [row["status"] for row in history] == ["failed", "completed"]
    dataset = result.json()["dataset_id"]
    queued = client.post(f"/api/portal/datasets/{dataset}/publish", json={"reviewed": False})
    assert queued.status_code == 202
    from pipeline import publisher
    monkeypatch.setattr(publisher, "publish_dataset_to_ckan", lambda *args: (_ for _ in ()).throw(ValueError("catalog fixture outage")))
    assert process(queued)["error_code"] == "publication_failed"
    assert client.get(f"/api/portal/datasets/{dataset}").json()["publication_state"] == "unpublished"
    assert client.post(f"/api/portal/jobs/{queued.json()['job_id']}/retry").status_code == 202
    calls = []
    monkeypatch.setattr(publisher, "publish_dataset_to_ckan", lambda row, files, org: calls.append((row["dataset_id"], len(files))))
    assert process(queued)["status"] == "completed"
    assert calls == [(dataset, 2)]
    detail = client.get(f"/api/portal/datasets/{dataset}").json()
    assert detail["publication_state"] == "published"
    assert client.get(f"/api/public/datasets/{dataset}/files/{detail['files'][0]['id']}").status_code == 200
    with portal.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM cdm.portal_tabular_rows")).scalar() == 2


def test_api_preview_encryption_pagination_and_url_import(client, portal, owner, monkeypatch):
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    fetched = []
    def fake_get(url, credentials=None, **kwargs):
        fetched.append((url, credentials))
        if url.endswith("table.csv"):
            return b"state,value\nLagos,99\n", "text/csv"
        return b'{"data":[{"state":"Lagos","value":12,"api_token":"fixture-redacted"}]}', "application/json"
    monkeypatch.setattr(remote, "get", fake_get)
    connection = {"url": "https://public.example.org/data", "name": "Fixture API", "format": "json", "records_path": "data", "schedule": "daily", "credentials": {"kind": "bearer", "secret": "external-fixture-secret"}, "pagination": {"mode": "page", "page_parameter": "page", "first_page": 1, "max_pages": 2}}
    preview = client.post("/api/portal/connections/test", json={"organisation_id": owner, "connection": connection})
    assert preview.status_code == 200 and preview.json()["preview"][0]["api_token"] == "[redacted]"
    assert fetched[0][0].endswith("page=1")
    result = client.post("/api/portal/datasets", headers={"Idempotency-Key": "api-fixture-key"}, json={**metadata(owner), "access_method": "api", "connection": connection})
    assert result.status_code == 202, result.text
    assert process(result)["status"] == "needs_review"
    detail = client.get(f"/api/portal/datasets/{result.json()['dataset_id']}")
    assert "external-fixture-secret" not in detail.text and "ciphertext" not in detail.text
    with portal.connect() as conn:
        row = conn.execute(text("SELECT connection,credentials_ciphertext,next_due_at FROM cdm.dataset_registry WHERE dataset_id=:d"), {"d": result.json()["dataset_id"]}).one()
        assert "external-fixture-secret" not in json.dumps(row[0]) and "external-fixture-secret" not in row[1] and row[2]
    assert client.post(f"/api/portal/datasets/{result.json()['dataset_id']}/publish", json={"reviewed": False}).status_code == 409
    result = client.post("/api/portal/datasets", headers={"Idempotency-Key": "url-fixture-key"}, json={**metadata(owner), "access_method": "url", "connection": {"url": "https://public.example.org/table.csv", "format": "csv"}})
    assert result.status_code == 202
    assert process(result) == {"status": "completed", "rows": 1}


def test_xlsx_json_pdf_and_invalid_content(client, owner):
    import openpyxl
    book = openpyxl.Workbook(); book.active.append(["state", "value"]); book.active.append(["Lagos", 42])
    stream = io.BytesIO(); book.save(stream)
    result = upload(client, owner, "xlsx-fixture-key", stream.getvalue(), "table.xlsx")
    assert result.status_code == 202 and process(result)["rows"] == 1
    result = upload(client, owner, "json-fixture-key", b'[{"state":"Kano","value":23}]', "table.json")
    assert result.status_code == 202 and process(result)["rows"] == 1
    # Minimal real PDF containing no table: extraction honestly returns review/zero rows.
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << >> /Contents 4 0 R >>", b"<< /Length 0 >>\nstream\n\nendstream"]
    pdf = b"%PDF-1.4\n"; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf)); pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(pdf); pdf += b"xref\n0 5\n0000000000 65535 f \n" + b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:]) + f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    result = upload(client, owner, "pdf-fixture-key", pdf, "document.pdf")
    assert result.status_code == 202
    assert process(result) == {"status": "needs_review", "rows": 0}
    for filename, data in [("../table.csv", b"a,b\n1,2"), ("fake.pdf", b"<html>bad"), ("fake.xlsx", b"a,b\n1,2"), ("fake.json", b"not json"), ("index.csv", b"<script>alert(1)</script>"), ("voice.mp3", b"anything")]:
        assert upload(client, owner, uuid.uuid4().hex, data, filename).status_code == 422


def test_worker_checks_revoked_membership(client, portal, owner):
    result = upload(client, owner)
    with portal.begin() as conn:
        conn.execute(text("DELETE FROM cdm.portal_memberships"))
    assert process(result)["error_code"] == "authorisation_revoked"


def test_dispatch_outage_and_stable_idempotency(client, owner, monkeypatch, portal):
    from pipeline.flows import portal_dispatcher as dispatcher
    result = upload(client, owner)
    dispatch = dispatcher.dispatch
    monkeypatch.setattr(dispatcher, "dispatch", lambda _: (_ for _ in ()).throw(RuntimeError("fixture prefect outage")))
    assert dispatcher.tick() == {"dispatched": 0}
    assert client.get(f"/api/portal/jobs/{result.json()['job_id']}").json()["status"] == "queued"
    captured = []
    class Reply:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value
    def post(url, json, **kwargs):
        captured.append(json)
        return Reply([{"id": "fixture-deployment"}] if url.endswith("filter") else {"id": str(uuid.uuid4())})
    monkeypatch.setattr(dispatcher, "dispatch", dispatch)
    monkeypatch.setattr(dispatcher.requests, "post", post)
    with portal.connect() as conn:
        job = dict(conn.execute(text("SELECT * FROM cdm.portal_jobs WHERE id=:id"), {"id": result.json()["job_id"]}).mappings().one())
    dispatcher.dispatch(job); dispatcher.dispatch(job)
    assert captured[1]["idempotency_key"] == captured[3]["idempotency_key"]
