"""Public reads remain open; legacy writes require scoped publisher credentials."""
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pipeline.api import app
from pipeline.settings import settings


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
@pytest.mark.parametrize("path,payload", [
    ("/api/publishers", {"name": "x", "api_key": "k"}),
    ("/scrape/source/CBN", {}),
    ("/scrape/batch", {}),
])
def test_admin_header_does_not_replace_publisher_authentication(client, monkeypatch, path, payload):
    monkeypatch.setattr(settings, "admin_api_token", SecretStr("test-admin"))
    for headers in ({}, {"X-Admin-Token": "test-admin"}):
        assert client.post(path, json=payload, headers=headers).status_code == 401


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_reading_needs_no_token(client):
    for path in ("/health", "/api/status", "/api/sources", "/api/publishers", "/api/sources/WorldBank/observations"):
        assert client.get(path).status_code == 200, path


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
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


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_observations_endpoint_is_paged(client):
    assert client.get("/api/sources/WorldBank/observations", params={"limit": 10**9}).status_code == 200
