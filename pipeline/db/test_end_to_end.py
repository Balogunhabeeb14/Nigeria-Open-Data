import os
import tempfile
import pandas as pd
from pathlib import Path
from fastapi.testclient import TestClient
from pipeline.api import app
from pipeline.db.warehouse import get_engine, run_schema_migrations
from pipeline.db.seed_sources import seed_default_sources
from pipeline.settings import settings
from sqlalchemy import text

from unittest.mock import patch

client = TestClient(app)

def setup_mock_data(landing_root: Path):
    """Create some mock files in the landing zones."""
    # 1. NigeriaDataPortal - doesn't need a file for mock, but if it falls back it looks for CSV
    ndp_dir = landing_root / "nigeria_data_portal"
    ndp_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Year": ["2023", "2024"], "NG_GDP_REAL": [100, 110], "NG_UNEMP_RATE": [5.5, 5.0]}).to_csv(ndp_dir / "NG_GDP_REAL.csv", index=False)
    pd.DataFrame({"Year": ["2023", "2024"], "NG_GDP_REAL": [100, 110], "NG_UNEMP_RATE": [5.5, 5.0]}).to_csv(ndp_dir / "NG_UNEMP_RATE.csv", index=False)

    # 2. CBN Excel mock
    cbn_dir = landing_root / "cbn"
    cbn_dir.mkdir(parents=True, exist_ok=True)
    df_cbn = pd.DataFrame({"Date": ["2023-12", "2024-01"], "MPR (%)": [18.5, 18.75], "Reserves": [33.0, 34.0]})
    df_cbn.to_excel(cbn_dir / "CBN_INTEREST_MPR.xlsx", index=False)
    df_cbn.to_excel(cbn_dir / "CBN_FX_RESERVES.xlsx", index=False)

    # 3. NBS PDF mock (since we can't easily create a real PDF with table here, we'll just make a dummy PDF)
    # pdfplumber might fail to extract, which tests our fallback!
    nbs_dir = landing_root / "nbs_reports"
    nbs_dir.mkdir(parents=True, exist_ok=True)
    
    dummy_pdf = nbs_dir / "cpi_report_mock.pdf"
    with open(dummy_pdf, "wb") as f:
        f.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n%%EOF")


# We mock the _download_and_hash so CBN doesn't hit the real network, but just uses the mock file we placed.
def mock_download_and_hash(self, url, dest):
    import hashlib
    # Assume file is already in dest from setup_mock_data
    return hashlib.sha256(b"mock").hexdigest()

# Mock NDP json api to return None, forcing fallback to CSV (which we mocked above)
def mock_fetch_json_api(self, dataset_id, since):
    return None

def mock_download_file(self, url, dest):
    pass # Assume CSV is already placed by setup_mock_data


@patch("pipeline.connectors.cbn.CBNConnector._download_and_hash", new=mock_download_and_hash)
@patch("pipeline.connectors.nigeria_data_portal.NigeriaDataPortalConnector._fetch_json_api", new=mock_fetch_json_api)
@patch("pipeline.connectors.nigeria_data_portal.NigeriaDataPortalConnector._download_file", new=mock_download_file)
def test_fastapi_scraping_endpoints():
    """Test the orchestration endpoints."""
    # Ensure clean slate
    run_schema_migrations()
    seed_default_sources()
    
    # We create a temporary directory for the landing zone
    with tempfile.TemporaryDirectory() as tmpdir:
        # Override settings for tests
        settings.landing_root = Path(tmpdir)
        setup_mock_data(settings.landing_root)
        
        # Override PREFECT_API_URL to run flows locally without hitting the server
        os.environ["PREFECT_API_URL"] = ""
        
        # 1. Test Single Source Scrape
        response = client.post("/scrape/source/CBN")
        assert response.status_code == 200
        data = response.json()
        assert data["source_id"] == "CBN"
        assert data["status"] in ["success", "partial_success"]
        
        # 2. Test Batch Scrape
        batch_response = client.post("/scrape/batch")
        assert batch_response.status_code == 200
        batch_data = batch_response.json()
        assert batch_data["status"] == "completed"
        assert "CBN" in batch_data["details"]
        assert "NigeriaDataPortal" in batch_data["details"]
        assert "NBS_Reports" in batch_data["details"]

        # Verify DB changes
        engine = get_engine()
        with engine.connect() as conn:
            # Check CBN records
            cbn_obs = conn.execute(text("SELECT COUNT(*) FROM cdm.indicator_observation WHERE source_system = 'CBN'")).scalar()
            assert cbn_obs > 0
            
            # Check Document registration (NBS_Reports)
            docs = conn.execute(text("SELECT COUNT(*) FROM cdm.dataset_registry WHERE source_system = 'NBS_Reports'")).scalar()
            assert docs > 0

if __name__ == "__main__":
    test_fastapi_scraping_endpoints()
    print("End-to-end tests completed successfully.")
