"""End-to-end flow runs against a real Postgres, with HTTP and CKAN faked.

These cover the behaviour that only shows up across runs: change detection,
publish recovery, and the bugs that made sources load once and never again.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text

from pipeline.connectors.world_bank import WorldBankConnector
from pipeline.publisher import DATA_RESOURCE_NAME
from pipeline.tests.fakes import FakeResponse, wb_catalogue, wb_series

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db", "prefect_harness")]

GDP_CODE, MORT_CODE, EMPTY_CODE = "NY.GDP.MKTP.KD.ZG", "SH.DYN.MORT", "ZZ.NO.DATA"
NO_DATA = [{"page": 0, "pages": 0, "per_page": 0, "total": 0, "sourceid": None, "lastupdated": None}, None]


def query(sql: str, **params):
    from pipeline.db.warehouse import get_engine
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params).fetchall()


def execute(sql: str, **params):
    from pipeline.db.warehouse import get_engine
    with get_engine().begin() as conn:
        conn.execute(text(sql), params)


@pytest.fixture
def world_bank(monkeypatch):
    """A World Bank API holding two populated series and one empty one."""
    api = {
        "series": {
            GDP_CODE: {"2023": 2.9, "2024": 3.4, "2025": 4.0},
            MORT_CODE: {"2022": 107.2, "2023": 104.9},
        },
        "requests": [],
        "down": False,
    }
    catalogue = wb_catalogue([
        (GDP_CODE, "GDP growth (annual %)", "Economy & Growth"),
        (MORT_CODE, "Mortality rate, under-5 (per 1,000 live births)", "Health "),
        (EMPTY_CODE, "A series with no Nigeria data", "Health "),
    ])

    def fake_get(self, url, **_):
        api["requests"].append(url)
        if api["down"]:
            raise RuntimeError("World Bank API unreachable")
        if "/source/2/indicators" in url:
            return FakeResponse(catalogue)
        code = url.split("/indicator/")[1].split("?")[0]
        values = api["series"].get(code)
        return FakeResponse(wb_series(code, code, values) if values else NO_DATA)

    monkeypatch.setattr(WorldBankConnector, "_http_get", fake_get)
    # Only the three catalogue series, so the test does not walk the 22 featured ones.
    execute("""
        UPDATE cdm.data_sources
        SET indicators = '[]'::jsonb,
            options = options || '{"request_delay_seconds": 0, "discover": true}'::jsonb
        WHERE source_id = 'WorldBank'
    """)
    # Retries would only slow a failing test down.
    from pipeline.flows import ingest_flow as flow_module
    monkeypatch.setattr(flow_module.task_fetch, "retries", 0)
    monkeypatch.setattr(flow_module.task_publish, "retries", 0)
    return api


MODE = {"direct": False}


@pytest.fixture(params=["prefect", "direct"], autouse=True)
def run_mode(request):
    """Every scenario runs twice: as a Prefect flow, and directly without Prefect."""
    MODE["direct"] = request.param == "direct"
    yield request.param
    MODE["direct"] = False


def run(source_id: str = "WorldBank", **kwargs) -> dict:
    from pipeline.flows.ingest_flow import ingest_flow, run_ingest
    from pipeline.registry import source_registry
    source_registry._connector_cache.clear()
    return (run_ingest if MODE["direct"] else ingest_flow)(source_id, **kwargs)


@pytest.fixture(autouse=True)
def keep_test_source_config(monkeypatch):
    """Stop the flow's start-up seeding from overwriting the test's source rows."""
    import pipeline.db.seed_sources as seed
    monkeypatch.setattr(seed, "seed_default_sources", lambda: 0)


def test_world_bank_data_reaches_warehouse_and_portal(world_bank, fake_ckan):
    summary = run()

    assert summary["WB_NY_GDP_MKTP_KD_ZG"] == {"status": "success", "rows": 3, "publish": "published"}
    assert summary["WB_SH_DYN_MORT"]["rows"] == 2
    assert summary["WB_ZZ_NO_DATA"] == {"status": "skipped", "rows": 0}

    stored = query("""
        SELECT period, value, unit, domain, geo_code, period_type
        FROM cdm.indicator_observation
        WHERE source_system = 'WorldBank' AND indicator_id = 'WB_NY_GDP_MKTP_KD_ZG'
        ORDER BY period
    """)
    assert [(r[0], float(r[1])) for r in stored] == [("2023", 2.9), ("2024", 3.4), ("2025", 4.0)]
    assert stored[0][2:] == ("annual %", "economy", "NG", "year")

    assert set(fake_ckan.packages) == {"ng-wb-ny-gdp-mktp-kd-zg", "ng-wb-sh-dyn-mort"}
    health = fake_ckan.packages["ng-wb-sh-dyn-mort"]
    assert health["groups"] == [{"name": "health"}] and health["license_id"] == "cc-by"
    assert "Definition of Mortality rate" in health["notes"]
    [resource] = [r for r in health["resources"] if r["name"] == DATA_RESOURCE_NAME]
    assert [(r["period"], r["value"]) for r in fake_ckan.rows(resource["id"])] == [("2022", 107.2), ("2023", 104.9)]

    manifest = dict(query("SELECT source_key, publish_state FROM cdm.ingest_manifest WHERE source_system = 'WorldBank'"))
    assert manifest["WB_NY_GDP_MKTP_KD_ZG"] == "published"


def test_second_run_skips_unchanged_and_loads_only_what_moved(world_bank, fake_ckan):
    run()
    upserts_after_first = fake_ckan.called("datastore_upsert")
    staged_after_first = query("SELECT count(*) FROM cdm.stage_raw_observations")[0][0]

    world_bank["series"][GDP_CODE] = {"2023": 2.9, "2024": 3.6, "2025": 4.0, "2026": 4.2}   # revised + new year
    summary = run()

    assert summary["WB_SH_DYN_MORT"] == {"status": "unchanged", "rows": 0}
    assert summary["WB_NY_GDP_MKTP_KD_ZG"]["status"] == "success"
    assert fake_ckan.called("datastore_upsert") == upserts_after_first + 1        # GDP only
    assert query("SELECT count(*) FROM cdm.stage_raw_observations")[0][0] == staged_after_first + 4

    values = dict(query("""
        SELECT period, value::float FROM cdm.indicator_observation
        WHERE indicator_id = 'WB_NY_GDP_MKTP_KD_ZG'
    """))
    assert values == {"2023": 2.9, "2024": 3.6, "2025": 4.0, "2026": 4.2}          # no duplicates, revision applied


def test_failed_publish_is_retried_next_run_even_if_data_is_unchanged(world_bank, fake_ckan):
    fake_ckan.fail_actions.add("datastore_upsert")
    summary = run()
    assert summary["WB_NY_GDP_MKTP_KD_ZG"] == {"status": "success", "rows": 3, "publish": "failed"}
    assert query("SELECT count(*) FROM cdm.indicator_observation")[0][0] == 5      # data is safe in the warehouse

    fake_ckan.fail_actions.clear()
    summary = run()
    assert summary["WB_NY_GDP_MKTP_KD_ZG"] == {"status": "unchanged", "rows": 0, "publish": "published"}
    [resource] = fake_ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]["resources"]
    assert len(fake_ckan.rows(resource["id"])) == 3

    summary = run()                                                                # now nothing left to do
    assert summary["WB_NY_GDP_MKTP_KD_ZG"] == {"status": "unchanged", "rows": 0}


def test_data_loaded_before_ckan_was_configured_is_published_once_it_is(world_bank, monkeypatch):
    assert run()["WB_NY_GDP_MKTP_KD_ZG"]["publish"] == "disabled"

    from pydantic import SecretStr

    from pipeline import publisher
    from pipeline.settings import settings
    from pipeline.tests.fakes import FakeCKAN
    ckan = FakeCKAN()
    monkeypatch.setattr(settings, "ckan_api_key", SecretStr("now-configured"))
    monkeypatch.setattr(publisher, "_get_ckan_client", lambda: ckan)

    assert run()["WB_NY_GDP_MKTP_KD_ZG"]["publish"] == "published"
    assert "ng-wb-ny-gdp-mktp-kd-zg" in ckan.packages


def test_one_failing_indicator_does_not_stop_the_others(world_bank, monkeypatch):
    original = WorldBankConnector._http_get

    def flaky(self, url, **kwargs):
        if f"/indicator/{MORT_CODE}" in url:
            return FakeResponse([{"message": [{"id": "120", "key": "Invalid value", "value": "bad"}]}])
        return original(self, url, **kwargs)

    monkeypatch.setattr(WorldBankConnector, "_http_get", flaky)
    summary = run()

    assert summary["WB_SH_DYN_MORT"]["status"] == "failed"
    assert summary["WB_NY_GDP_MKTP_KD_ZG"]["status"] == "success"
    row = query("SELECT status, error_message FROM cdm.ingest_manifest WHERE source_key = 'WB_SH_DYN_MORT'")[0]
    assert row[0] == "failed" and "Invalid value" in row[1]
    assert query("SELECT status FROM cdm.pipeline_run_log ORDER BY id DESC LIMIT 1")[0][0] == "partial"


def test_catalogue_outage_still_loads_featured_indicators(world_bank):
    execute("""
        UPDATE cdm.data_sources SET indicators = CAST(:ind AS jsonb) WHERE source_id = 'WorldBank'
    """, ind='[{"id": "WB_NY_GDP_MKTP_KD_ZG", "dataset_id": "NY.GDP.MKTP.KD.ZG", "domain": "economy", "name": "GDP growth (annual %)"}]')
    original = WorldBankConnector._http_get

    def catalogue_down(self, url, **kwargs):
        if "/source/2/indicators" in url:
            raise RuntimeError("catalogue endpoint down")
        return original(self, url, **kwargs)

    import pytest as _pytest
    mp = _pytest.MonkeyPatch()
    mp.setattr(WorldBankConnector, "_http_get", catalogue_down)
    try:
        summary = run()
    finally:
        mp.undo()
    assert list(summary) == ["WB_NY_GDP_MKTP_KD_ZG"] and summary["WB_NY_GDP_MKTP_KD_ZG"]["rows"] == 3


def test_run_stops_early_when_the_source_is_down(world_bank):
    world_bank["down"] = True
    execute("""
        UPDATE cdm.data_sources
        SET options = options || '{"discover": false, "max_consecutive_failures": 3}'::jsonb,
            indicators = CAST(:ind AS jsonb)
        WHERE source_id = 'WorldBank'
    """, ind=str([{"id": f"WB_X{n}", "dataset_id": f"X.{n}", "name": f"Series {n}"} for n in range(10)]).replace("'", '"'))

    summary = run()

    assert len(summary) == 3 and all(v["status"] == "failed" for v in summary.values())
    status, message = query("SELECT status, error_message FROM cdm.pipeline_run_log ORDER BY id DESC LIMIT 1")[0]
    assert status == "failed" and "7 indicators not attempted" in message


def test_direct_mode_retries_a_step_like_prefect_would(world_bank, monkeypatch, run_mode):
    if run_mode != "direct":
        pytest.skip("retry behaviour under Prefect is Prefect's own")
    from pipeline.flows import ingest_flow as flow_module
    monkeypatch.setattr(flow_module.task_fetch, "retries", 2)
    monkeypatch.setattr(flow_module.task_fetch, "retry_delay_seconds", 0)
    original, calls = WorldBankConnector._http_get, {"n": 0}

    def fails_twice(self, url, **kwargs):
        if f"/indicator/{GDP_CODE}" in url:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("temporary glitch")
        return original(self, url, **kwargs)

    monkeypatch.setattr(WorldBankConnector, "_http_get", fails_twice)
    assert run()["WB_NY_GDP_MKTP_KD_ZG"]["status"] == "success" and calls["n"] == 3


def test_changed_description_is_republished_even_when_numbers_are_not(world_bank, fake_ckan):
    """First pass loads featured indicators without descriptions; the full
    pass that follows learns them from the catalogue and must publish them."""
    execute("""
        UPDATE cdm.data_sources SET indicators = CAST(:ind AS jsonb) WHERE source_id = 'WorldBank'
    """, ind='[{"id": "WB_NY_GDP_MKTP_KD_ZG", "dataset_id": "NY.GDP.MKTP.KD.ZG", "domain": "economy", "name": "GDP growth (annual %)"}]')

    run(featured_only=True)
    assert "Definition of" not in fake_ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]["notes"]

    summary = run()
    assert summary["WB_NY_GDP_MKTP_KD_ZG"]["status"] == "success"
    assert fake_ckan.packages["ng-wb-ny-gdp-mktp-kd-zg"]["notes"].startswith("Definition of GDP growth")
    assert run()["WB_NY_GDP_MKTP_KD_ZG"]["status"] == "unchanged"


def test_featured_only_skips_discovery(world_bank):
    execute("""
        UPDATE cdm.data_sources SET indicators = CAST(:ind AS jsonb) WHERE source_id = 'WorldBank'
    """, ind='[{"id": "WB_NY_GDP_MKTP_KD_ZG", "dataset_id": "NY.GDP.MKTP.KD.ZG", "domain": "economy", "name": "GDP growth (annual %)"}]')
    summary = run(featured_only=True)
    assert list(summary) == ["WB_NY_GDP_MKTP_KD_ZG"]
    assert not any("/source/2/indicators" in url for url in world_bank["requests"])


# ── Regressions for bugs found in review ──────────────────────────────────────

def _cbn_file(monkeypatch, frames: dict):
    """Make the CBN 'download' write whatever `frames['current']` holds."""
    from pipeline.connectors.cbn import CBNConnector

    def fake_download(self, url, dest):
        frames["current"].to_excel(dest, index=False)
        return dest

    monkeypatch.setattr(CBNConnector, "_download_file", fake_download)
    execute("""
        UPDATE cdm.data_sources SET indicators = CAST(:ind AS jsonb) WHERE source_id = 'CBN'
    """, ind='[{"id": "CBN_INTEREST_MPR", "name": "Monetary Policy Rate (MPR)", "excel_url": "https://example.invalid/MPR.xlsx", "sheet": 0, "domain": "economics", "unit": "%", "col_map": {"Date": "period", "MPR (%)": "value"}}]')


def test_cbn_keeps_loading_after_its_first_run(monkeypatch):
    """Was: the file hash was saved as the period watermark, and from the
    second run on the date filter compared dates with 'hash:...' and dropped
    every row. CBN loaded once and never again."""
    frames = {"current": pd.DataFrame({"Date": ["2024-01", "2024-02"], "MPR (%)": [18.75, 22.75]})}
    _cbn_file(monkeypatch, frames)

    assert run("CBN")["CBN_INTEREST_MPR"]["rows"] == 2
    watermark, content_hash = query(
        "SELECT last_period, content_hash FROM cdm.ingest_manifest WHERE source_key = 'CBN_INTEREST_MPR'")[0]
    assert watermark == "2024-02" and len(content_hash) == 64      # a period and a hash, each in its own column

    assert run("CBN")["CBN_INTEREST_MPR"]["status"] == "unchanged"  # same file: skipped

    frames["current"] = pd.DataFrame({"Date": ["2024-01", "2024-02", "2024-03"], "MPR (%)": [18.75, 22.75, 24.75]})
    assert run("CBN")["CBN_INTEREST_MPR"] == {"status": "success", "rows": 3, "publish": "disabled"}
    periods = [r[0] for r in query("SELECT period FROM cdm.indicator_observation WHERE source_system = 'CBN' ORDER BY period")]
    assert periods == ["2024-01", "2024-02", "2024-03"]


def test_legacy_hash_watermarks_are_migrated(database):
    execute("""
        INSERT INTO cdm.ingest_manifest (source_system, source_key, last_period, row_count, status)
        VALUES ('CBN', 'LEGACY', 'hash:abc123', 5, 'success')
    """)
    from pipeline.db.warehouse import get_manifest, get_watermark, run_schema_migrations
    run_schema_migrations()
    assert get_watermark("CBN", "LEGACY") is None
    assert get_manifest("CBN", "LEGACY")["content_hash"] == "abc123"


def test_uploaded_data_is_stored_under_its_own_source(monkeypatch):
    """Was: every uploaded dataset was stored as source 'generic_file'."""
    from pipeline.settings import settings
    folder = settings.landing_root / "state_budgets"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Year": ["2023", "2024"], "capital_spend": [10.5, 12.0]}).to_csv(folder / "budgets.csv", index=False)
    execute("""
        INSERT INTO cdm.data_sources (source_id, connector, transform, domain, schedule, landing_dir, ingest_mode, indicators)
        VALUES ('state_budgets', 'pipeline.connectors.generic.GenericFileConnector',
                'pipeline.transforms.generic_transform.generic_transform', 'government', '0 * * * *',
                'state_budgets', 'file', '[{"id": "capital_spend", "name": "Capital spending", "unit": "NGN bn"}]'::jsonb)
        ON CONFLICT (source_id) DO NOTHING
    """)
    try:
        assert run("state_budgets")["capital_spend"]["rows"] == 2
        sources = {r[0] for r in query("SELECT DISTINCT source_system FROM cdm.indicator_observation")}
        assert sources == {"state_budgets"}
    finally:
        execute("DELETE FROM cdm.data_sources WHERE source_id = 'state_budgets'")
        (folder / "budgets.csv").unlink()


def test_seeding_does_not_switch_a_disabled_source_back_on(database, monkeypatch):
    monkeypatch.undo()                                   # use the real seeding here
    from pipeline.db.seed_sources import seed_default_sources
    seed_default_sources()
    execute("UPDATE cdm.data_sources SET is_active = false WHERE source_id = 'NigeriaDataPortal'")
    execute("""
        UPDATE cdm.data_sources
        SET options = '{"discover": false, "max_indicators": 50}'::jsonb, indicators = '[]'::jsonb
        WHERE source_id = 'WorldBank'
    """)
    try:
        seed_default_sources()
        assert query("SELECT is_active FROM cdm.data_sources WHERE source_id = 'NigeriaDataPortal'")[0][0] is False
        options, indicators = query("SELECT options, indicators FROM cdm.data_sources WHERE source_id = 'WorldBank'")[0]
        assert options["discover"] is False and options["max_indicators"] == 50   # operator overrides kept
        assert options["license_id"] == "cc-by"                                   # defaults filled back in
        assert len(indicators) == 22                                              # code-owned list restored
    finally:
        execute("UPDATE cdm.data_sources SET is_active = true WHERE source_id = 'NigeriaDataPortal'")
        execute("UPDATE cdm.data_sources SET options = '{}'::jsonb WHERE source_id = 'WorldBank'")
        seed_default_sources()


def test_file_watcher_marks_every_changed_file(monkeypatch):
    """Was: only the first changed file per source was marked, so the rest
    re-triggered ingestion every 15 minutes for ever."""
    from pipeline.flows import file_watcher_flow as watcher
    from pipeline.settings import settings

    folder = settings.landing_root / "cbn"
    folder.mkdir(parents=True, exist_ok=True)
    for leftover in folder.iterdir():                    # files other tests downloaded here
        leftover.unlink()
    for name in ("a.csv", "b.csv", "c.csv"):
        (folder / name).write_text(f"Date,value\n2024-01,{name}\n")
    runs: list[str] = []
    import pipeline.flows.ingest_flow as flow_module
    monkeypatch.setattr(flow_module, "ingest_flow", lambda source_id, **_: runs.append(source_id) or {})
    try:
        first = watcher.file_watcher_flow()
        second = watcher.file_watcher_flow()
    finally:
        for name in ("a.csv", "b.csv", "c.csv"):
            (folder / name).unlink()

    assert first["files_processed"] == 3 and runs.count("CBN") == 1
    assert second == {"files_processed": 0, "triggered": 0, "failed": 0}
