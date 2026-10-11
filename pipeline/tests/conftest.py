"""Shared test setup.

Environment is fixed before anything imports `pipeline.settings`, because the
settings object reads it once at import time.

Unit tests need nothing external. Integration tests (marked `integration`)
need a Postgres at PIPELINE_DB_URL and are skipped when it is not reachable:

    docker run -d -p 5433:5432 -e POSTGRES_USER=pipeline \
        -e POSTGRES_PASSWORD=pipeline -e POSTGRES_DB=pipeline postgres:15-alpine
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("PIPELINE_DB_URL", "postgresql://pipeline:pipeline@localhost:5433/pipeline")
os.environ.setdefault("LANDING_ROOT", tempfile.mkdtemp(prefix="naija_landing_"))
os.environ.pop("CKAN_API_KEY", None)          # tests never publish to a real CKAN
os.environ.setdefault("PREFECT_LOGGING_LEVEL", "WARNING")

import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: needs the pipeline Postgres database")


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from pipeline.db.warehouse import get_engine
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database():
    """Apply the schema once; skip integration tests if there is no database."""
    if not _db_available():
        pytest.skip("pipeline database not reachable (set PIPELINE_DB_URL)")
    from pipeline.db.warehouse import run_schema_migrations
    run_schema_migrations()


@pytest.fixture
def clean_db(database):
    """Empty the tables a flow run writes to, before each integration test."""
    from sqlalchemy import text

    from pipeline.db.warehouse import get_engine
    with get_engine().begin() as conn:
        conn.execute(text("""
            TRUNCATE cdm.indicator_observation, cdm.stage_raw_observations,
                     cdm.ingest_manifest, cdm.pipeline_run_log RESTART IDENTITY
        """))
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
