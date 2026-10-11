"""World Bank connector and transform, without touching the network."""
from __future__ import annotations

import pytest

from pipeline.connectors.world_bank import (
    WorldBankAPIError,
    WorldBankConnector,
    indicator_id_for,
    unit_from_name,
)
from pipeline.tests.fakes import FakeResponse, wb_catalogue, wb_series
from pipeline.transforms.world_bank_transform import transform

GDP = {"id": "WB_NY_GDP_MKTP_KD_ZG", "dataset_id": "NY.GDP.MKTP.KD.ZG",
       "domain": "economy", "name": "GDP growth (annual %)"}


def make_connector(monkeypatch, responses: dict, options: dict | None = None, indicators=None):
    """Connector whose HTTP layer answers from `responses` (URL fragment → payload)."""
    connector = WorldBankConnector(config={
        "indicators": indicators if indicators is not None else [GDP],
        "options": {"request_delay_seconds": 0, **(options or {})},
        "domain": "economy",
    })
    requested: list[str] = []

    def fake_get(url, **_):
        requested.append(url)
        for fragment, payload in responses.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(payload)
        raise AssertionError(f"unexpected request: {url}")

    monkeypatch.setattr(connector, "_http_get", fake_get)
    connector.requested = requested
    return connector


def test_fetch_returns_sorted_series_without_missing_years(monkeypatch):
    payload = wb_series("NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)",
                        {"2023": 2.9, "2024": 3.4, "2025": 4.0, "1960": None})
    connector = make_connector(monkeypatch, {"/indicator/NY.GDP.MKTP.KD.ZG": payload})

    df = connector.fetch(GDP)

    assert list(df.columns) == ["REF_AREA", "TIME_PERIOD", "OBS_VALUE", "INDICATOR"]
    assert df["TIME_PERIOD"].tolist() == ["2023", "2024", "2025"]     # 1960 had no value
    assert df["OBS_VALUE"].tolist() == [2.9, 3.4, 4.0]
    assert set(df["REF_AREA"]) == {"NG"}
    assert "/country/NGA/indicator/NY.GDP.MKTP.KD.ZG" in connector.requested[0]


def test_fetch_follows_pagination(monkeypatch):
    page1 = wb_series("X", "X", {"2025": 3.0, "2024": 2.0})
    page1[0].update({"pages": 2})
    page2 = wb_series("X", "X", {"2023": 1.0})
    page2[0].update({"page": 2, "pages": 2})
    connector = make_connector(monkeypatch, {"&page=1": page1, "&page=2": page2})

    df = connector.fetch({**GDP, "dataset_id": "X"})

    assert df["TIME_PERIOD"].tolist() == ["2023", "2024", "2025"]
    assert len(connector.requested) == 2


def test_indicator_with_no_nigeria_data_gives_empty_frame(monkeypatch):
    empty = [{"page": 0, "pages": 0, "per_page": 0, "total": 0, "sourceid": None, "lastupdated": None}, None]
    connector = make_connector(monkeypatch, {"/indicator/": empty})
    assert connector.fetch(GDP).empty


def test_error_payload_raises_instead_of_looking_like_no_data(monkeypatch):
    # The API reports a bad code with HTTP 200 and this body.
    error = [{"message": [{"id": "120", "key": "Invalid value",
                           "value": "The provided parameter value is not valid"}]}]
    connector = make_connector(monkeypatch, {"/indicator/": error})
    with pytest.raises(WorldBankAPIError, match="Invalid value"):
        connector.fetch(GDP)


def test_discovery_adds_catalogue_and_keeps_featured_domain(monkeypatch):
    catalogue = wb_catalogue([
        ("NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)", "Economy & Growth"),
        ("SH.DYN.MORT", "Mortality rate, under-5 (per 1,000 live births)", "Health "),
        ("AG.LND.ARBL.ZS", "Arable land (% of land area)", "Agriculture & Rural Development  "),
        ("XX.NO.TOPIC", "Something uncategorised", ""),
    ])
    featured = [{**GDP, "domain": "featured-domain", "name": "old name"}]
    connector = make_connector(monkeypatch, {"/source/2/indicators": catalogue},
                               options={"discover": True}, indicators=featured)

    indicators = connector.expand_indicators()
    by_code = {i["dataset_id"]: i for i in indicators}

    assert [i["dataset_id"] for i in indicators][0] == "NY.GDP.MKTP.KD.ZG"   # featured first
    assert len(indicators) == 4 and len(by_code) == 4                        # no duplicates
    gdp = by_code["NY.GDP.MKTP.KD.ZG"]
    assert gdp["domain"] == "featured-domain" and gdp["featured"] is True
    assert gdp["name"] == "GDP growth (annual %)"                            # official name wins
    assert gdp["description"].startswith("Definition of")
    assert by_code["SH.DYN.MORT"]["domain"] == "health"
    assert by_code["SH.DYN.MORT"]["id"] == "WB_SH_DYN_MORT"
    assert by_code["SH.DYN.MORT"]["unit"] == "per 1,000 live births"
    assert by_code["AG.LND.ARBL.ZS"]["domain"] == "agriculture"
    assert by_code["XX.NO.TOPIC"]["domain"] == "economy"                     # source default


def test_discovery_respects_cap_and_off_switch(monkeypatch):
    catalogue = wb_catalogue([(f"A.{n}", f"Series {n}", "Health") for n in range(10)])
    capped = make_connector(monkeypatch, {"/source/2/indicators": catalogue},
                            options={"discover": True, "max_indicators": 4})
    assert len(capped.expand_indicators()) == 4          # 1 featured + 3 discovered

    off = make_connector(monkeypatch, {}, options={"discover": False})
    assert off.expand_indicators() == [GDP]
    assert off.requested == []


def test_discovery_failure_falls_back_to_featured(monkeypatch):
    connector = make_connector(monkeypatch, {"/source/2/indicators": RuntimeError("api down")},
                               options={"discover": True})
    assert connector.expand_indicators() == [GDP]


def test_transform_builds_national_annual_records(monkeypatch):
    payload = wb_series("NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)", {"2024": 3.4, "2025": 4.0})
    connector = make_connector(monkeypatch, {"/indicator/": payload})
    records = transform(connector.fetch(GDP), GDP)

    assert len(records) == 2
    rec = records[-1]
    assert (rec.source_system, rec.indicator_id) == ("WorldBank", "WB_NY_GDP_MKTP_KD_ZG")
    assert (rec.geo_level, rec.geo_code, rec.geo_name) == ("national", "NG", "Nigeria")
    assert (rec.period_type, rec.period, rec.value) == ("year", "2025", 4.0)
    assert rec.unit == "annual %"
    assert rec.raw_source_url == "https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=NG"


@pytest.mark.parametrize("name,unit", [
    ("GDP growth (annual %)", "annual %"),
    ("Unemployment, total (% of total labor force) (modeled ILO estimate)", "% of total labor force"),
    ("Maternal mortality ratio (modeled estimate, per 100,000 live births)", "per 100,000 live births"),
    ("Literacy rate, adult total (% of people ages 15 and above)", "% of people ages 15 and above"),
    ("Some index (modeled estimate)", None),
    ("Population, total", None),
])
def test_unit_from_name(name, unit):
    assert unit_from_name(name) == unit


def test_indicator_id_for():
    assert indicator_id_for("NY.GDP.MKTP.CD") == "WB_NY_GDP_MKTP_CD"
