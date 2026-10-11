"""The built-in catalogue: written by the real publisher and harvester, read
back through the API the frontend calls."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from pipeline.harvest import ckan_harvester
from pipeline.harvest.ckan_harvester import harvest_portal
from pipeline.publisher import publish_indicator_to_ckan

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_catalog")]

WB_OPTIONS = {
    "publisher_id": "world-bank", "publisher_title": "World Bank",
    "source_name": "World Bank, World Development Indicators",
    "license_id": "cc-by", "license_title": "Creative Commons Attribution 4.0 (CC BY 4.0)",
}


@pytest.fixture
def clean_catalog(database, monkeypatch):
    from pipeline.db.warehouse import get_engine
    from pipeline.settings import settings
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE cdm.catalog_dataset, cdm.catalog_group CASCADE"))
        conn.execute(text("TRUNCATE cdm.indicator_observation"))
    monkeypatch.setattr(settings, "catalog_backend", "local")


@pytest.fixture
def api(clean_catalog):
    """The read API, mounted the way pipeline.api mounts it in local mode."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pipeline.catalog.api import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def load(indicator_id: str, name: str, domain: str, values: dict[str, float], **config) -> dict:
    """Put a series in the warehouse and publish it, as a flow run would."""
    from pipeline.db.warehouse import upsert_to_cdm
    from pipeline.transforms.cdm import CDMRecord
    upsert_to_cdm([
        CDMRecord(source_system="WorldBank", domain=domain, indicator_id=indicator_id,
                  indicator_name=name, geo_level="national", geo_name="Nigeria", geo_code="NG",
                  period_type="year", period=year, value=value, unit="%",
                  raw_source_url="https://data.worldbank.org/indicator/X?locations=NG")
        for year, value in values.items()
    ])
    indicator = {"id": indicator_id, "name": name, "domain": domain, "unit": "%", **config}
    assert publish_indicator_to_ckan("WorldBank", indicator, source_options=WB_OPTIONS) == "published"
    return indicator


def result(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body["result"]


def test_published_dataset_is_served_like_ckan_would(api):
    load("WB_GDP_GROWTH", "GDP growth (annual %)", "economy", {"2023": 2.9, "2024": 3.4, "2025": 4.0},
         description="Annual percentage growth rate of GDP.", featured=True)

    dataset = result(api.get("/api/3/action/package_show", params={"id": "ng-wb-gdp-growth"}))

    assert dataset["title"] == "Nigeria – GDP growth (annual %)"
    assert dataset["notes"].startswith("Annual percentage growth rate of GDP.")
    assert dataset["organization"]["title"] == "World Bank"
    assert dataset["groups"][0]["name"] == "economy" and dataset["groups"][0]["title"] == "Economy"
    assert dataset["license_id"] == "cc-by" and dataset["license_title"] == "Creative Commons Attribution"
    assert dataset["metadata_modified"] and dataset["num_resources"] == 1
    extras = {e["key"]: e["value"] for e in dataset["extras"]}
    assert extras["licence_name"].endswith("(CC BY 4.0)") and extras["temporal_end"] == "2025"

    [resource] = dataset["resources"]
    assert resource["format"] == "CSV" and resource["datastore_active"] is True
    assert resource["url"] == f"/datastore/dump/{resource['id']}"

    table = result(api.get("/api/3/action/datastore_search", params={"resource_id": resource["id"]}))
    assert table["total"] == 3
    assert [(r["period"], r["value"]) for r in table["records"]] == [("2023", 2.9), ("2024", 3.4), ("2025", 4.0)]
    assert [f["id"] for f in table["fields"]][:3] == ["period", "value", "unit"]

    download = api.get(resource["url"])
    assert download.status_code == 200 and download.headers["content-type"].startswith("text/csv")
    assert 'filename="ng-wb-gdp-growth.csv"' in download.headers["content-disposition"]
    lines = download.text.strip().splitlines()
    assert lines[0].startswith("period,value,unit,geo_name") and len(lines) == 4
    assert lines[1].startswith("2023,2.9,%,Nigeria,NG")


def test_republishing_revises_rows_without_duplicating_anything(api):
    load("WB_GDP_GROWTH", "GDP growth (annual %)", "economy", {"2024": 3.4})
    load("WB_GDP_GROWTH", "GDP growth (annual %)", "economy", {"2024": 3.6, "2025": 4.0})

    found = result(api.get("/api/3/action/package_search"))
    assert found["count"] == 1
    [resource] = found["results"][0]["resources"]
    table = result(api.get("/api/3/action/datastore_search", params={"resource_id": resource["id"]}))
    assert {r["period"]: r["value"] for r in table["records"]} == {"2024": 3.6, "2025": 4.0}


def test_search_filters_paging_and_ordering(api):
    load("WB_POP", "Population, total", "population", {"2024": 1.0})
    load("WB_MORT", "Mortality rate, under-5 (per 1,000 live births)", "health", {"2024": 1.0},
         description="Probability of a child dying before age five.")
    load("WB_LIFE", "Life expectancy at birth, total (years)", "health", {"2024": 1.0}, featured=True)
    load("WB_GDP", "GDP growth (annual %)", "economy", {"2024": 1.0})

    def names(**params):
        return [d["name"] for d in result(api.get("/api/3/action/package_search", params=params))["results"]]

    assert names(rows=50)[0] == "ng-wb-life"                                   # featured leads
    assert names(q="mortality") == ["ng-wb-mort"]                              # title word
    assert names(q="child dying") == ["ng-wb-mort"]                            # description words
    assert names(q="gdp") == ["ng-wb-gdp"]                                     # short token
    assert names(q="expect") == ["ng-wb-life"]                                 # partial word
    assert names(q="nothing matches this") == []
    assert sorted(names(fq="groups:health")) == ["ng-wb-life", "ng-wb-mort"]
    assert len(names(fq="organization:world-bank", rows=50)) == 4
    assert names(fq="organization:someone-else") == []
    assert len(names(fq="res_format:CSV", rows=50)) == 4 and names(fq="res_format:PDF") == []
    assert names(fq="res_format:CSV AND groups:economy") == ["ng-wb-gdp"]

    page = result(api.get("/api/3/action/package_search", params={"rows": 3, "start": 3}))
    assert page["count"] == 4 and len(page["results"]) == 1                     # total is not the page size


def test_topics_and_publishers_carry_dataset_counts(api):
    load("WB_MORT", "Mortality rate", "health", {"2024": 1.0})
    load("WB_LIFE", "Life expectancy", "health", {"2024": 1.0})
    load("WB_GDP", "GDP growth", "economy", {"2024": 1.0})

    topics = result(api.get("/api/3/action/group_list", params={"all_fields": "true"}))
    assert [(t["name"], t["title"], t["package_count"]) for t in topics] == [
        ("health", "Health", 2), ("economy", "Economy", 1)]
    assert result(api.get("/api/3/action/group_list")) == ["health", "economy"]

    publishers = result(api.get("/api/3/action/organization_list", params={"all_fields": "true"}))
    assert [(p["name"], p["title"], p["package_count"]) for p in publishers] == [("world-bank", "World Bank", 3)]


def test_unknown_ids_give_ckan_style_404(api):
    for path, params in [
        ("/api/3/action/package_show", {"id": "nope"}),
        ("/api/3/action/datastore_search", {"resource_id": "nope"}),
        ("/datastore/dump/nope", {}),
    ]:
        response = api.get(path, params=params)
        assert response.status_code == 404 and response.json()["success"] is False


def test_search_text_cannot_break_the_query(api):
    load("WB_GDP", "GDP growth (annual %)", "economy", {"2024": 1.0})
    for nasty in ["'; DROP TABLE cdm.catalog_dataset; --", '"unclosed', "a & | !", "%_%", "(((", "<script>"]:
        assert api.get("/api/3/action/package_search", params={"q": nasty}).status_code == 200
        assert api.get("/api/3/action/package_search", params={"fq": nasty}).status_code == 200
    assert result(api.get("/api/3/action/package_search"))["count"] == 1


def test_harvested_listings_land_in_the_same_catalogue(api, monkeypatch):
    portal = {"id": "hdx", "title": "Humanitarian Data Exchange (HDX)",
              "base_url": "https://data.humdata.org", "fq": "groups:nga", "q": "", "group": "humanitarian"}
    remote = {
        "id": "r1", "name": "nigeria-health-facilities", "title": "Nigeria Health Facilities",
        "notes": "Locations of health facilities.", "state": "active",
        "metadata_modified": "2026-09-01T10:00:00", "license_id": "cc-by",
        "license_title": "Creative Commons Attribution International",
        "organization": {"title": "GRID3"}, "tags": [{"name": "health"}],
        "resources": [{"name": "facilities.xlsx", "format": "xlsx", "url": "https://data.humdata.org/f.xlsx"}],
    }
    monkeypatch.setattr(ckan_harvester, "_search_page",
                        lambda portal, start, rows: {"count": 1, "results": [remote][start:start + rows]})

    first = harvest_portal(portal, track=False)
    second = harvest_portal(portal, track=False)
    assert (first.created, second.updated, second.created) == (1, 1, 0)

    dataset = result(api.get("/api/3/action/package_show", params={"id": "hdx-nigeria-health-facilities"}))
    assert dataset["organization"]["title"] == "Humanitarian Data Exchange (HDX)"
    assert dataset["resources"][0]["url"] == "https://data.humdata.org/f.xlsx"   # links out
    extras = {e["key"]: e["value"] for e in dataset["extras"]}
    assert extras["hosted"] == "external" and extras["source"] == "GRID3"

    found = result(api.get("/api/3/action/package_search", params={"fq": "res_format:XLSX"}))
    assert [d["name"] for d in found["results"]] == ["hdx-nigeria-health-facilities"]
    assert result(api.get("/api/3/action/package_search", params={"q": "health facilities"}))["count"] == 1
