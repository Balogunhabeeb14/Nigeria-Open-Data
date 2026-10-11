"""Catalogue harvesting from other CKAN portals."""
from __future__ import annotations

import pytest

from pipeline.harvest import ckan_harvester
from pipeline.harvest.ckan_harvester import harvest_portal, map_dataset
from pipeline.harvest.portals import HARVEST_PORTALS, get_portal
from pipeline.tests.fakes import FakeCKAN

PORTAL = {"id": "hdx", "title": "Humanitarian Data Exchange (HDX)",
          "base_url": "https://data.humdata.org", "fq": "groups:nga", "q": "",
          "group": "humanitarian", "enabled": True}


def remote(name: str, **overrides) -> dict:
    base = {
        "id": f"id-{name}", "name": name, "title": name.replace("-", " ").title(),
        "notes": "Health facility locations.", "state": "active", "private": False,
        "metadata_modified": "2026-09-01T10:00:00.000000",
        "license_id": "cc-by", "license_title": "Creative Commons Attribution International",
        "organization": {"name": "grid3", "title": "GRID3"},
        "tags": [{"name": "health facilities"}, {"name": "geodata/points"}],
        "resources": [{"name": "facilities.csv", "format": "csv",
                       "url": "https://data.humdata.org/dataset/x/resource/y/download/facilities.csv"}],
    }
    return {**base, **overrides}


@pytest.fixture
def remote_portal(monkeypatch):
    """Serve `datasets` through package_search, paged like the real API."""
    state = {"datasets": [], "requests": []}

    def fake_search(portal, start, rows):
        state["requests"].append((portal["id"], start, rows))
        return {"count": len(state["datasets"]), "results": state["datasets"][start:start + rows]}

    monkeypatch.setattr(ckan_harvester, "_search_page", fake_search)
    monkeypatch.setattr(ckan_harvester, "_PAGE_DELAY_SECONDS", 0)
    return state


def test_map_dataset_links_out_and_credits_the_source():
    mapped = map_dataset(PORTAL, remote("nigeria-health-facilities"))

    assert mapped["name"] == "hdx-nigeria-health-facilities"
    assert mapped["url"] == "https://data.humdata.org/dataset/nigeria-health-facilities"
    assert mapped["license_id"] == "cc-by"
    assert mapped["resources"] == [{
        "name": "facilities.csv", "format": "CSV", "description": "",
        "url": "https://data.humdata.org/dataset/x/resource/y/download/facilities.csv",
    }]
    for phrase in ("Health facility locations.", "Humanitarian Data Exchange", "GRID3",
                   "Creative Commons Attribution International", "does not hold a copy"):
        assert phrase in mapped["notes"]
    tag_names = [t["name"] for t in mapped["tags"]]
    assert tag_names[:2] == ["nigeria", "hdx"] and "geodata points" in tag_names  # '/' is not allowed in tags
    meta = {e["key"]: e["value"] for e in mapped["extras"]}
    assert meta["hosted"] == "external" and meta["source"] == "GRID3"
    assert meta["remote_metadata_modified"] == "2026-09-01T10:00:00.000000"


@pytest.mark.parametrize("overrides", [
    {"private": True},
    {"archived": True},
    {"state": "deleted"},
    {"resources": []},
    {"resources": [{"name": "no link"}]},
    {"resources": [{"name": "local path", "url": "/uploads/file.csv"}]},
])
def test_map_dataset_skips_what_should_not_be_listed(overrides):
    assert map_dataset(PORTAL, remote("x", **overrides)) is None


def test_harvest_creates_then_updates_without_duplicating(remote_portal):
    remote_portal["datasets"] = [remote("a"), remote("b"), remote("c", private=True)]
    ckan = FakeCKAN()

    first = harvest_portal(PORTAL, ckan=ckan, track=False)
    assert (first.seen, first.created, first.skipped, first.failed) == (3, 2, 1, 0)
    assert set(ckan.packages) == {"hdx-a", "hdx-b"}
    assert ckan.packages["hdx-a"]["owner_org"] == "hdx" and "hdx" in ckan.orgs
    assert ckan.packages["hdx-a"]["groups"] == [{"name": "humanitarian"}]

    remote_portal["datasets"][0] = remote("a", title="A, renamed")
    second = harvest_portal(PORTAL, ckan=ckan, track=False)
    assert (second.created, second.updated) == (0, 2)
    assert len(ckan.packages) == 2 and ckan.packages["hdx-a"]["title"] == "A, renamed"


def test_harvest_pages_through_all_results(remote_portal, monkeypatch):
    monkeypatch.setattr(ckan_harvester, "_PAGE_SIZE", 2)
    remote_portal["datasets"] = [remote(f"d{n}") for n in range(5)]
    report = harvest_portal(PORTAL, ckan=FakeCKAN(), track=False)
    assert report.created == 5
    assert [start for _, start, _ in remote_portal["requests"]] == [0, 2, 4]


def test_limit_and_dry_run(remote_portal):
    remote_portal["datasets"] = [remote(f"d{n}") for n in range(5)]
    ckan = FakeCKAN()
    report = harvest_portal(PORTAL, ckan=ckan, limit=3, dry_run=True)
    assert report.seen == 3 and report.created == 3
    assert ckan.packages == {} and ckan.calls == []           # nothing written


def test_one_bad_dataset_does_not_stop_the_rest(remote_portal):
    remote_portal["datasets"] = [remote("good-1"), {"name": "broken", "resources": "not-a-list", "state": "active"}, remote("good-2")]
    report = harvest_portal(PORTAL, ckan=FakeCKAN(), track=False)
    assert report.created == 2 and report.failed == 1
    assert report.errors and report.errors[0].startswith("broken:")


def test_portal_registry_is_well_formed():
    ids = [p["id"] for p in HARVEST_PORTALS]
    assert len(ids) == len(set(ids))
    for portal in HARVEST_PORTALS:
        assert portal["base_url"].startswith("https://")
        assert portal.get("fq") or portal.get("q"), "a portal must be filtered to Nigeria"
    assert get_portal("hdx")["title"].startswith("Humanitarian")
    with pytest.raises(KeyError):
        get_portal("nope")
