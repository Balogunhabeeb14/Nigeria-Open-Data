"""CKAN publishing: the full table and its provenance reach the portal."""
from __future__ import annotations

import pytest

from pipeline import publisher
from pipeline.publisher import (
    DATA_RESOURCE_NAME,
    DISABLED,
    PUBLISHED,
    PublishError,
    package_name_for,
    publish_indicator_to_ckan,
    slugify,
)
from pipeline.tests.fakes import FakeCKAN

INDICATOR = {
    "id": "WB_NY_GDP_MKTP_KD_ZG",
    "dataset_id": "NY.GDP.MKTP.KD.ZG",
    "name": "GDP growth (annual %)",
    "domain": "economy",
    "unit": "annual %",
    "description": "Annual percentage growth rate of GDP at market prices.",
    "featured": True,
}
OPTIONS = {
    "publisher_id": "world-bank",
    "publisher_title": "World Bank",
    "source_name": "World Bank, World Development Indicators",
    "source_url": "https://data.worldbank.org/country/nigeria",
    "license_id": "cc-by",
    "license_title": "Creative Commons Attribution 4.0 (CC BY 4.0)",
    "license_url": "https://datacatalog.worldbank.org/public-licenses",
}


def observations(values: dict[str, float]) -> list[dict]:
    return [
        {
            "period": year, "period_type": "year", "geo_level": "national",
            "geo_code": "NG", "geo_name": "Nigeria", "value": value, "unit": "annual %",
            "indicator_id": INDICATOR["id"], "indicator_name": INDICATOR["name"],
            "source_system": "WorldBank",
            "raw_source_url": "https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=NG",
            "last_updated_at": "2026-10-11T00:00:00+00:00",
        }
        for year, value in sorted(values.items())
    ]


@pytest.fixture
def stored(monkeypatch):
    """Control what the warehouse 'holds' for the indicator."""
    state = {"rows": observations({"2023": 2.9, "2024": 3.4, "2025": 4.0})}
    import pipeline.db.warehouse as warehouse
    monkeypatch.setattr(warehouse, "fetch_observations", lambda source, indicator: state["rows"])
    return state


def extras(package: dict) -> dict:
    return {e["key"]: e["value"] for e in package["extras"]}


def test_first_publish_creates_dataset_with_full_table_and_provenance(stored):
    ckan = FakeCKAN()
    state = publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS, ckan=ckan)

    assert state == PUBLISHED
    package = ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]
    assert package["title"] == "Nigeria – GDP growth (annual %)"
    assert package["license_id"] == "cc-by"
    assert package["url"].startswith("https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG")
    assert package["groups"] == [{"name": "economy"}] and "economy" in ckan.groups
    assert package["owner_org"] == "world-bank" and "world-bank" in ckan.orgs   # filed under its publisher

    meta = extras(package)
    assert meta["source"] == "World Bank, World Development Indicators"
    assert meta["licence_name"].startswith("Creative Commons Attribution 4.0")
    assert (meta["temporal_start"], meta["temporal_end"]) == ("2023", "2025")
    assert meta["observation_count"] == "3" and meta["featured"] == "true"
    assert "last_refreshed" in meta
    assert package["notes"].startswith("Annual percentage growth")      # description leads
    assert "Source: World Bank" in package["notes"]
    assert "*" not in package["notes"]                                  # plain text, shown as-is

    [resource] = package["resources"]
    assert resource["name"] == DATA_RESOURCE_NAME and resource["format"] == "CSV"
    assert "/datastore/dump/" in resource["url"]              # a working download link
    rows = ckan.rows(resource["id"])
    assert [(r["period"], r["value"]) for r in rows] == [("2023", 2.9), ("2024", 3.4), ("2025", 4.0)]
    assert ckan.datastore[resource["id"]]["primary_key"] == ["geo_code", "period"]
    assert "raw_source_url" not in rows[0]                    # only the declared columns


def test_republish_updates_in_place_and_picks_up_revisions(stored):
    ckan = FakeCKAN()
    publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS, ckan=ckan)
    stored["rows"] = observations({"2023": 2.9, "2024": 3.6, "2025": 4.0, "2026": 4.2})  # 2024 revised

    publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS, ckan=ckan)

    assert len(ckan.packages) == 1 and ckan.called("package_create") == 1
    assert ckan.called("package_patch") == 1 and ckan.called("package_update") == 0
    package = ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]
    [resource] = package["resources"]                         # still one resource
    values = {r["period"]: r["value"] for r in ckan.rows(resource["id"])}
    assert values == {"2023": 2.9, "2024": 3.6, "2025": 4.0, "2026": 4.2}
    assert extras(package)["temporal_end"] == "2026"


def test_legacy_summary_resource_is_removed(stored):
    ckan = FakeCKAN()
    ckan.action.package_create(
        name="ng-wb-ny-gdp-mktp-kd-zg",
        resources=[{"name": "GDP growth (annual %) – Summary", "format": "CSV"}],
    )
    publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS, ckan=ckan)
    names = [r["name"] for r in ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]["resources"]]
    assert names == [DATA_RESOURCE_NAME]


def test_dataset_is_published_without_topic_when_group_is_refused(stored):
    ckan = FakeCKAN()
    ckan.reject_groups = True
    assert publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS, ckan=ckan) == PUBLISHED
    assert "groups" not in ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]


def test_large_tables_are_sent_in_batches(stored, monkeypatch):
    monkeypatch.setattr(publisher, "_UPSERT_BATCH", 2)
    stored["rows"] = observations({str(y): float(y) for y in range(2000, 2005)})
    ckan = FakeCKAN()
    publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS, ckan=ckan)
    assert ckan.called("datastore_upsert") == 3
    [resource] = ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]["resources"]
    assert len(ckan.rows(resource["id"])) == 5


def test_ckan_failure_raises_so_the_flow_can_retry(stored):
    ckan = FakeCKAN()
    ckan.fail_actions.add("datastore_upsert")
    with pytest.raises(PublishError, match="ng-wb-ny-gdp-mktp-kd-zg"):
        publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS, ckan=ckan)


def test_no_api_key_means_disabled_not_an_error(stored):
    assert publish_indicator_to_ckan("WorldBank", INDICATOR, source_options=OPTIONS) == DISABLED


def test_missing_licence_is_stated_not_invented(stored):
    ckan = FakeCKAN()
    publish_indicator_to_ckan("CBN", {**INDICATOR, "id": "CBN_X"}, source_options={}, ckan=ckan)
    package = ckan.packages["ng-cbn-x"]
    assert package["license_id"] == "notspecified"
    assert extras(package)["licence_name"] == "Not specified by the source"


@pytest.mark.parametrize("raw,expected", [
    ("Agriculture & Rural Development", "agriculture-and-rural-development"),
    ("  Science/Technology!! ", "science-technology"),
    ("ng-WB_NY.GDP", "ng-wb_ny-gdp"),
])
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_package_name_for():
    assert package_name_for("WB_NY_GDP_MKTP_CD") == "ng-wb-ny-gdp-mktp-cd"
