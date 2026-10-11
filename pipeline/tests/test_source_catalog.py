"""The source catalogue stays well formed and in step with the code."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CATALOG = Path(__file__).resolve().parents[2] / "data_sources" / "catalog.yaml"
REQUIRED = {"id", "name", "publisher", "url", "coverage", "topics", "geography",
            "access", "integration", "licence", "checked", "notes"}
ACCESS = {"api", "ckan-api", "sdmx", "bulk-download", "file-download", "pdf", "dashboard", "restricted"}
INTEGRATION = {"live", "harvested", "planned", "link-only", "excluded"}
GEOGRAPHY = {"national", "state", "lga", "point"}


@pytest.fixture(scope="module")
def sources() -> list[dict]:
    return yaml.safe_load(CATALOG.read_text())["sources"]


def test_every_entry_is_complete_and_uses_known_values(sources):
    for src in sources:
        missing = REQUIRED - src.keys()
        assert not missing, f"{src.get('id')}: missing {sorted(missing)}"
        assert src["access"] in ACCESS, src["id"]
        assert src["integration"] in INTEGRATION, src["id"]
        assert src["geography"] in GEOGRAPHY, src["id"]
        assert src["url"].startswith("https://"), src["id"]
        assert src["topics"], src["id"]
        if src["integration"] == "planned":
            assert src.get("priority") in (1, 2, 3), f"{src['id']}: planned sources need a priority"


def test_ids_are_unique(sources):
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids))


def test_harvested_entries_match_the_harvester(sources):
    from pipeline.harvest.portals import HARVEST_PORTALS
    harvested_hosts = {s["url"].split("/")[2] for s in sources if s["integration"] == "harvested"}
    portal_hosts = {p["base_url"].split("/")[2] for p in HARVEST_PORTALS}
    assert harvested_hosts == portal_hosts


def test_live_entries_have_a_connector(sources):
    from pipeline.db.seed_sources import DEFAULT_SOURCES
    live = [s for s in sources if s["integration"] == "live"]
    connectors = " ".join(src["connector"] for src in DEFAULT_SOURCES)
    assert len(live) == 4
    for module in ("world_bank", "dmo", "cbn", "nigeria_data_portal"):
        assert module in connectors
