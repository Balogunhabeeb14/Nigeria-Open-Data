"""Open data portals whose Nigeria datasets are listed in our catalogue.

Each of these runs CKAN, so one harvester covers all of them through the
standard CKAN Action API (`/api/3/action/package_search`).

Harvesting copies the catalogue entry only: title, description, licence,
publisher and links to the files. The files stay with the original portal,
which keeps their licence terms intact and means a dataset we list is never
an out-of-date copy.

To add a portal, append an entry. `fq` and `q` are passed to package_search
unchanged; use whichever the portal's own "Nigeria" page uses in its URL.
"""
from __future__ import annotations

HARVEST_PORTALS: list[dict] = [
    {
        "id": "hdx",
        "title": "Humanitarian Data Exchange (HDX)",
        "base_url": "https://data.humdata.org",
        "fq": "groups:nga",
        "q": "",
        "group": "humanitarian",
        "enabled": True,
    },
    {
        "id": "openafrica",
        "title": "openAFRICA",
        "base_url": "https://open.africa",
        "fq": "tags:Nigeria",
        "q": "",
        "group": None,
        "enabled": True,
    },
    {
        "id": "energydata",
        "title": "EnergyData.info",
        "base_url": "https://energydata.info",
        "fq": "vocab_country_names:NGA",
        "q": "",
        "group": "energy",
        "enabled": True,
    },
]


def get_portal(portal_id: str) -> dict:
    for portal in HARVEST_PORTALS:
        if portal["id"] == portal_id:
            return portal
    raise KeyError(f"Unknown harvest portal '{portal_id}'. Known: {[p['id'] for p in HARVEST_PORTALS]}")
