import hashlib
from pathlib import Path

from sqlalchemy import text
from pipeline.db.migrate import migrate
from pipeline.db import warehouse
from pipeline.tests.conftest import guarded_url


def test_repeat_migration_is_noop_and_failure_keeps_watermark(portal):
    assert migrate(portal) == []
    warehouse.update_manifest("fixture-source", "fixture-key", "2024", 3)
    warehouse.update_manifest("fixture-source", "fixture-key", None, 0, "failed", "fixture error")
    assert warehouse.get_watermark("fixture-source", "fixture-key") == "2024"
    assert warehouse.get_manifest("fixture-source", "fixture-key")["row_count"] == 3


def test_existing_data_and_tokens_preserved_through_migration(portal):
    # Rebuild ONLY the disposable schema to exercise upgrading the old schema.
    with portal.begin() as conn:
        conn.execute(text("DROP SCHEMA cdm CASCADE"))
        conn.execute(text((Path(__file__).parents[1] / "db/schema.sql").read_text()))
        publisher = conn.execute(text("INSERT INTO cdm.publishers(name,api_key,contact_email) VALUES ('Existing fixture','old-fixture-key','old@example.org') RETURNING id")).scalar_one()
        conn.execute(text("INSERT INTO cdm.data_sources(publisher_id,source_id,connector,transform,domain,schedule,landing_dir,ingest_mode) VALUES (:p,'OldSource','old.Connector','old.transform','general','','old','file')"), {"p": publisher})
        conn.execute(text("INSERT INTO cdm.dataset_registry(source_system,dataset_id,display_name,domain,format,storage_url) VALUES ('OldSource','original-dataset-id','Original','general','csv','old-location')"))
        conn.execute(text("INSERT INTO cdm.ingest_manifest(source_system,source_key,last_period,row_count) VALUES ('OldSource','key','2020',8)"))
        conn.execute(text("INSERT INTO cdm.indicator_observation(source_system,domain,indicator_id,indicator_name,geo_level,geo_name,period_type,period,value) VALUES ('OldSource','general','original-indicator','Old indicator','country','Nigeria','annual','2020',8)"))
    assert migrate(portal) == ["0001_baseline", "0002_publisher_portal", "0003_catalog_and_publish_tracking"]
    with portal.connect() as conn:
        assert conn.execute(text("SELECT id FROM cdm.publishers")).scalar_one() == publisher
        assert conn.execute(text("SELECT dataset_id FROM cdm.dataset_registry")).scalar_one() == "original-dataset-id"
        assert conn.execute(text("SELECT last_period FROM cdm.ingest_manifest")).scalar_one() == "2020"
        assert conn.execute(text("SELECT value FROM cdm.indicator_observation")).scalar_one() == 8
        assert conn.execute(text("SELECT token_hash FROM cdm.portal_integration_tokens")).scalar_one() == hashlib.sha256(b"old-fixture-key").hexdigest()
        assert conn.execute(text("SELECT count(*) FROM cdm.portal_memberships")).scalar_one() == 0


def test_database_guard_refuses_application_database(monkeypatch):
    monkeypatch.setenv("NOD_TEST_DATABASE_URL", "postgresql://user:pass@localhost:5433/pipeline")
    import pytest
    with pytest.raises(RuntimeError, match="dedicated"): guarded_url()
