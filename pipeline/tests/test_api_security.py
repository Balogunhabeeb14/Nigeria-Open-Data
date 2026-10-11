"""The pipeline API: reads are open, changes need the admin token."""
from __future__ import annotations

import io

import pytest
from pydantic import SecretStr
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

TOKEN = "s3cret-admin-token"
ADMIN = {"X-Admin-Token": TOKEN}
SOURCE = {
    "publisher_api_key": "pub-key-1",
    "source_id": "state_budgets",
    "connector": "pipeline.connectors.generic.GenericFileConnector",
    "transform": "pipeline.transforms.generic_transform.generic_transform",
    "domain": "government", "schedule": "0 * * * *", "landing_dir": "state_budgets",
    "ingest_mode": "file", "indicators": [{"id": "capital_spend", "name": "Capital spending"}],
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from pipeline.api import app
    from pipeline.db.warehouse import get_engine
    from pipeline.settings import settings
    monkeypatch.setattr(settings, "admin_api_token", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "landing_root", tmp_path)
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM cdm.data_sources WHERE publisher_id IS NOT NULL"))
        conn.execute(text("DELETE FROM cdm.publishers"))
    return TestClient(app)


def register(client, key="pub-key-1", name="Ministry of Budget"):
    return client.post("/api/publishers", headers=ADMIN, json={"name": name, "api_key": key})


WRITES = [
    ("post", "/api/publishers", {"json": {"name": "x", "api_key": "k"}}),
    ("post", "/api/sources", {"json": SOURCE}),
    ("post", "/api/upload", {"data": {"source_id": "x", "publisher_api_key": "k"}, "files": {"file": ("a.csv", b"a,b\n")}}),
    ("post", "/scrape/source/CBN", {}),
    ("post", "/scrape/batch", {}),
    ("get", "/api/publishers", {}),
]


@pytest.mark.parametrize("method,path,kwargs", WRITES)
def test_changes_are_refused_without_the_token(client, method, path, kwargs):
    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert getattr(client, method)(path, headers={"X-Admin-Token": "wrong"}, **kwargs).status_code == 401


@pytest.mark.parametrize("method,path,kwargs", WRITES)
def test_changes_are_switched_off_until_a_token_is_configured(client, monkeypatch, method, path, kwargs):
    from pipeline.settings import settings
    monkeypatch.setattr(settings, "admin_api_token", None)
    for headers in ({}, ADMIN, {"X-Admin-Token": ""}):
        assert getattr(client, method)(path, headers=headers, **kwargs).status_code == 503


def test_reading_needs_no_token(client):
    for path in ("/health", "/api/status", "/api/sources", "/api/sources/WorldBank/observations"):
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("field,value", [
    ("connector", "os.system"),
    ("connector", "subprocess.Popen"),
    ("transform", "builtins.eval"),
    ("transform", "pipeline.db.warehouse.get_engine"),      # ours, but not a transform
    ("connector", "pipeline.connectors.generic.GenericFileConnector; import os"),
    ("source_id", "../../etc"),
    ("landing_dir", "../outside"),
    ("landing_dir", "/absolute/path"),
])
def test_a_source_cannot_name_arbitrary_code_or_paths(client, field, value):
    register(client)
    response = client.post("/api/sources", headers=ADMIN, json={**SOURCE, field: value})
    assert response.status_code == 422, response.text


def test_a_publisher_cannot_take_over_another_source(client):
    register(client, "pub-key-1", "Ministry of Budget")
    register(client, "pub-key-2", "Someone Else")
    assert client.post("/api/sources", headers=ADMIN, json=SOURCE).status_code == 200
    assert client.post("/api/sources", headers=ADMIN, json={**SOURCE, "domain": "health"}).status_code == 200   # own update

    stolen = client.post("/api/sources", headers=ADMIN, json={**SOURCE, "publisher_api_key": "pub-key-2"})
    assert stolen.status_code == 409
    builtin = client.post("/api/sources", headers=ADMIN, json={**SOURCE, "source_id": "CBN"})
    assert builtin.status_code == 409

    from pipeline.config import get_source_config
    assert get_source_config("CBN")["connector"].endswith("CBNConnector")       # untouched


def upload(client, filename, content=b"Year,capital_spend\n2024,12.5\n", key="pub-key-1", source="state_budgets"):
    return client.post("/api/upload", headers=ADMIN,
                       data={"source_id": source, "publisher_api_key": key},
                       files={"file": (filename, io.BytesIO(content))})


def test_upload_lands_in_the_sources_own_folder(client, tmp_path):
    register(client)
    client.post("/api/sources", headers=ADMIN, json=SOURCE)
    assert upload(client, "budgets 2024.csv").status_code == 200
    assert (tmp_path / "state_budgets" / "budgets 2024.csv").read_bytes().startswith(b"Year,")


@pytest.mark.parametrize("filename", [
    "../../../etc/cron.d/evil.csv", "..\\..\\evil.csv", "/etc/passwd.csv", ".hidden.csv",
    "script.py", "page.html", "archive.zip", "noextension", "",
])
def test_upload_refuses_unsafe_names_and_types(client, tmp_path, filename):
    register(client)
    client.post("/api/sources", headers=ADMIN, json=SOURCE)
    response = upload(client, filename)
    assert response.status_code in (200, 422)
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    # Whatever the client called it, nothing may land outside the source's folder.
    assert all(p.parent == tmp_path / "state_budgets" for p in written), written
    if response.status_code == 200:      # a path was reduced to its harmless last part
        assert [p.name for p in written] in (["evil.csv"], ["passwd.csv"])


def test_upload_is_tied_to_the_publishers_own_source(client):
    register(client, "pub-key-1")
    register(client, "pub-key-2", "Someone Else")
    client.post("/api/sources", headers=ADMIN, json=SOURCE)
    assert upload(client, "a.csv", key="pub-key-2").status_code == 401
    assert upload(client, "a.csv", source="CBN").status_code == 401
    assert upload(client, "a.csv", source="../x").status_code == 422


def test_upload_size_is_capped(client, monkeypatch):
    import pipeline.api as api
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 100)
    register(client)
    client.post("/api/sources", headers=ADMIN, json=SOURCE)
    assert upload(client, "big.csv", content=b"x" * 500).status_code == 413


def test_status_reports_what_was_actually_loaded(client):
    from pipeline.db.warehouse import update_manifest, upsert_to_cdm
    from pipeline.transforms.cdm import CDMRecord
    upsert_to_cdm([CDMRecord(source_system="WorldBank", domain="economy", indicator_id="WB_X",
                             indicator_name="X", geo_level="national", geo_name="Nigeria", geo_code="NG",
                             period_type="year", period=str(y), value=1.0, unit=None) for y in (2023, 2024)])
    update_manifest("WorldBank", "WB_X", "2024", 2, publish_state="published")
    update_manifest("WorldBank", "WB_EMPTY", None, 0)
    update_manifest("WorldBank", "WB_BAD", None, 0, status="failed", error_message="boom")
    update_manifest("harvest:hdx", "some-dataset", None, 3, content_hash="t", publish_state="published")

    status = client.get("/api/status").json()
    wb = next(s for s in status["sources"] if s["id"] == "WorldBank")
    assert (wb["datasets"], wb["checked_without_data"], wb["failed"], wb["observations"]) == (1, 1, 1, 2)
    assert wb["name"] == "World Bank, World Development Indicators" and wb["last_successful_update"]
    hdx = next(s for s in status["sources"] if s["id"] == "harvest:hdx")
    assert hdx["name"].startswith("Humanitarian") and hdx["kind"] == "listed from another portal"
    assert status["totals"]["datasets"] == 2 and status["totals"]["failed"] == 1
    assert "error_message" not in str(status)      # internals stay internal


def test_observations_endpoint_is_paged(client):
    assert client.get("/api/sources/WorldBank/observations", params={"limit": 10**9}).status_code == 200
