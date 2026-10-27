"""In-memory stand-ins for the services the pipeline talks to."""
from __future__ import annotations

import itertools

from ckanapi import NotAuthorized, NotFound


class FakeCKAN:
    """Behaves like ckanapi.RemoteCKAN for the actions the pipeline uses.

    Keeps datasets, resources and DataStore tables in dictionaries so tests
    can assert on what a real portal would end up holding.
    """

    def __init__(self) -> None:
        self.packages: dict[str, dict] = {}       # by name
        self.groups: set[str] = set()
        self.orgs: set[str] = set()
        self.datastore: dict[str, dict] = {}      # resource_id → {fields, primary_key, rows}
        self.calls: list[tuple[str, dict]] = []
        self.fail_actions: set[str] = set()       # action names that raise
        self.reject_groups = False                # refuse datasets that name a group
        self._ids = itertools.count(1)
        self.action = _Actions(self)

    # helpers for assertions
    def rows(self, resource_id: str) -> list[dict]:
        return list(self.datastore[resource_id]["rows"].values())

    def called(self, action: str) -> int:
        return sum(1 for name, _ in self.calls if name == action)

    def _by_id(self, ident: str) -> dict:
        for pkg in self.packages.values():
            if ident in (pkg["id"], pkg["name"]):
                return pkg
        raise NotFound(ident)


class _Actions:
    def __init__(self, ckan: FakeCKAN) -> None:
        self._c = ckan

    def __getattr__(self, name: str):
        impl = getattr(self, f"_{name}", None)
        if impl is None:
            raise AttributeError(f"FakeCKAN does not implement action '{name}'")

        def call(**kwargs):
            self._c.calls.append((name, kwargs))
            if name in self._c.fail_actions:
                raise RuntimeError(f"simulated CKAN failure in {name}")
            return impl(**kwargs)
        return call

    # datasets
    def _package_show(self, id):
        return self._c._by_id(id)

    def _package_create(self, name, **fields):
        if self._c.reject_groups and fields.get("groups"):
            raise NotAuthorized("not allowed to edit group")
        if name in self._c.packages:
            raise RuntimeError("name already in use")
        resources = []
        for res in fields.pop("resources", []) or []:
            resources.append({"id": f"res-{next(self._c._ids)}", **res})
        pkg = {"id": f"pkg-{next(self._c._ids)}", "name": name, "resources": resources, **fields}
        self._c.packages[name] = pkg
        return pkg

    def _package_patch(self, id, **fields):
        if self._c.reject_groups and fields.get("groups"):
            raise NotAuthorized("not allowed to edit group")
        pkg = self._c._by_id(id)
        if "resources" in fields:
            fields["resources"] = [
                {"id": f"res-{next(self._c._ids)}", **res} for res in fields["resources"]
            ]
        pkg.update(fields)
        return pkg

    # topics and publishers
    def _group_show(self, id):
        if id not in self._c.groups:
            raise NotFound(id)
        return {"name": id}

    def _group_create(self, name, **_):
        self._c.groups.add(name)
        return {"name": name}

    def _organization_show(self, id):
        if id not in self._c.orgs:
            raise NotFound(id)
        return {"name": id}

    def _organization_create(self, name, **_):
        self._c.orgs.add(name)
        return {"name": name}

    # resources and the DataStore
    def _resource_delete(self, id):
        for pkg in self._c.packages.values():
            pkg["resources"] = [r for r in pkg["resources"] if r["id"] != id]

    def _datastore_create(self, fields, primary_key, force=False, resource=None, resource_id=None, records=None):
        if resource is not None:
            pkg = self._c._by_id(resource["package_id"])
            resource_id = f"res-{next(self._c._ids)}"
            pkg["resources"].append({
                "id": resource_id,
                "url": f"http://ckan.test/datastore/dump/{resource_id}",
                "url_type": "datastore",
                **{k: v for k, v in resource.items() if k != "package_id"},
            })
        table = self._c.datastore.setdefault(resource_id, {"rows": {}})
        table["fields"] = fields
        table["primary_key"] = primary_key
        return {"resource_id": resource_id}

    def _datastore_upsert(self, resource_id, records, method, force=False):
        table = self._c.datastore[resource_id]
        for rec in records:
            key = tuple(rec[k] for k in table["primary_key"])
            table["rows"][key] = rec
        return {"resource_id": resource_id}


class FakeResponse:
    """Minimal `requests.Response` for connector tests."""

    def __init__(self, payload) -> None:
        self._payload = payload

    def json(self):
        return self._payload


def wb_series(code: str, name: str, values: dict[str, float | None], per_page: int = 1000) -> list:
    """Build a World Bank indicator response exactly as the API shapes it.

    Shape confirmed against the live API on 2026-10-11:
    [ {page, pages, per_page, total, sourceid, lastupdated}, [ {record}, ... ] ]
    """
    records = [
        {
            "indicator": {"id": code, "value": name},
            "country": {"id": "NG", "value": "Nigeria"},
            "countryiso3code": "NGA",
            "date": year,
            "value": value,
            "unit": "",
            "obs_status": "",
            "decimal": 1,
        }
        for year, value in sorted(values.items(), reverse=True)   # API returns newest first
    ]
    meta = {"page": 1, "pages": 1, "per_page": per_page, "total": len(records),
            "sourceid": "2", "lastupdated": "2026-10-08"}
    return [meta, records]


def wb_catalogue(entries: list[tuple[str, str, str]]) -> list:
    """Build a /source/2/indicators response. entries: (code, name, topic)."""
    records = [
        {
            "id": code,
            "name": name,
            "unit": "",
            "source": {"id": "2", "value": "World Development Indicators"},
            "sourceNote": f"Definition of {name}.",
            "sourceOrganization": "Test compiler",
            "topics": [{"id": "1", "value": topic}] if topic else [],
        }
        for code, name, topic in entries
    ]
    # per_page really does come back as a string from this endpoint
    return [{"page": 1, "pages": 1, "per_page": "500", "total": len(records)}, records]
