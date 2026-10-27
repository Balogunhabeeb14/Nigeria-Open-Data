"""Only explicitly named, loopback, disposable test databases are allowed."""
import json
import os
import tempfile

# Never inherit application credentials or landing files from the local .env.
os.environ["CKAN_API_KEY"] = ""
os.environ["PIPELINE_DB_URL"] = os.environ.get("NOD_TEST_DATABASE_URL", "postgresql://pipeline:pipeline@localhost:55434/portal_test")
os.environ["LANDING_ROOT"] = tempfile.mkdtemp(prefix="nod-test-landing-")
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from pipeline.api import app
from pipeline.db.migrate import migrate
from pipeline.db.seed_sources import seed_default_sources as seed_test_sources
from pipeline.db import warehouse
from pipeline.portal import mail, store
from pipeline.portal.security import unseal
from pipeline.settings import settings


def guarded_url():
    value = os.environ.get("NOD_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set NOD_TEST_DATABASE_URL to an isolated PostgreSQL test database")
    url = make_url(value)
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "portal_test" or url.port != 55434:
        raise RuntimeError("Tests require the dedicated loopback portal_test database on port 55434")
    return value


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: needs isolated PostgreSQL")


@pytest.fixture(scope="session")
def database():
    engine = create_engine(guarded_url())
    patch = pytest.MonkeyPatch()
    patch.setattr(warehouse, "get_engine", lambda: engine)
    patch.setattr(store, "engine", lambda: engine)
    migrate(engine)
    try:
        yield engine
    finally:
        patch.undo()
        engine.dispose()


@pytest.fixture
def portal(database, monkeypatch, tmp_path):
    # This schema is exclusively in the guarded disposable database, never production.
    with database.begin() as conn:
        names = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='cdm' AND tablename<>'schema_migrations'" )).scalars().all()
        conn.execute(text("TRUNCATE " + ",".join(f'cdm."{name}"' for name in names) + " RESTART IDENTITY CASCADE"))
    monkeypatch.setattr(store, "engine", lambda: database)
    monkeypatch.setattr(warehouse, "get_engine", lambda: database)
    monkeypatch.setattr(settings, "portal_secret_key", SecretStr(Fernet.generate_key().decode()))
    monkeypatch.setattr(settings, "portal_cookie_secure", False)
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")
    monkeypatch.setattr(settings, "smtp_host", "fixture.invalid")
    monkeypatch.setattr(settings, "landing_root", tmp_path)
    monkeypatch.setattr(mail, "send", lambda *args: None)
    return database


@pytest.fixture
def client(portal):
    with TestClient(app, base_url="http://localhost:3000", headers={"Origin": "http://localhost:3000"}) as client:
        yield client


def action_token(engine, email, purpose="verify"):
    with engine.connect() as conn:
        payload = conn.execute(text("SELECT payload_ciphertext FROM cdm.portal_mail_outbox WHERE recipient=:email ORDER BY next_attempt_at DESC LIMIT 1"), {"email": email}).scalar_one()
    link = json.loads(unseal(payload))["body"].split("\n\n")[1]
    values = parse_qs(urlsplit(link).fragment)
    assert values["action"] == [purpose]
    return values["token"][0]


def sign_in(client, engine, email="owner@example.org", verified=True):
    password = "Long-fixture-password-123"
    assert client.post("/api/auth/register", json={"email": email, "password": password}).status_code == 202
    if verified:
        assert client.post("/api/auth/verify", json={"token": action_token(engine, email)}).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies["nod_csrf"]
    return password


@pytest.fixture
def owner(client, portal):
    sign_in(client, portal)
    result = client.post("/api/portal/organisations", json={"name": "Fixture organisation"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def metadata(organisation):
    return {"organisation_id": organisation, "title": "Fixture dataset", "description": "A table for isolated testing.", "topic": "general", "licence": "CC BY 4.0", "original_provider": "Fixture provider", "provenance": "Generated test fixture; no live data"}


def upload(client, organisation, key="fixture-key-001", data=b"state,value\nLagos,12\nKano,15\n", filename="table.csv"):
    return client.post("/api/portal/datasets/upload", headers={"Idempotency-Key": key}, data={"metadata": json.dumps(metadata(organisation))}, files={"file": (filename, data)})


@pytest.fixture
def clean_db(database):
    seed_test_sources()
    with database.begin() as conn:
        conn.execute(text("TRUNCATE cdm.indicator_observation, cdm.stage_raw_observations, cdm.ingest_manifest, cdm.pipeline_run_log RESTART IDENTITY"))
        conn.execute(text("DROP TABLE IF EXISTS cdm.file_watcher_manifest"))
    yield


@pytest.fixture(scope="session")
def prefect_harness():
    """Run flows against a temporary Prefect database, not a real server."""
    from prefect.testing.utilities import prefect_test_harness
    with prefect_test_harness():
        yield


@pytest.fixture
def fake_ckan(monkeypatch):
    """A CKAN stand-in wired into the publisher, with publishing switched on."""
    from pydantic import SecretStr

    from pipeline import publisher
    from pipeline.settings import settings
    from pipeline.tests.fakes import FakeCKAN

    ckan = FakeCKAN()
    monkeypatch.setattr(settings, "ckan_api_key", SecretStr("test-key"))
    monkeypatch.setattr(publisher, "_get_ckan_client", lambda: ckan)
    return ckan
