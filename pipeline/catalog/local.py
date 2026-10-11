"""A catalogue kept in the pipeline database, driven like a CKAN client.

`LocalCatalog().action.package_create(...)` and friends accept the same
arguments as `ckanapi.RemoteCKAN`, for the actions the publisher and the
harvester use. That is the whole trick: neither of them knows or cares which
catalogue it is writing to, and switching is one setting (CATALOG_BACKEND).

Reading is done by pipeline/catalog/api.py.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from ckanapi import NotFound
from sqlalchemy import text

from pipeline.db.warehouse import get_engine

# Link written on a data table's resource. It is relative on purpose: the
# frontend proxies /datastore/* to this app, so the same link works on
# localhost, in a Codespace and behind a real domain.
DUMP_PATH = "/datastore/dump/{resource_id}"

_SEARCH_SQL = """
    setweight(to_tsvector('english', coalesce(:title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(:tags,  '')), 'B') ||
    setweight(to_tsvector('english', coalesce(:notes, '')), 'C')
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class LocalCatalog:
    """Drop-in for the subset of ckanapi.RemoteCKAN the pipeline uses."""

    def __init__(self) -> None:
        self.action = _Actions()


class _Actions:
    # ── Datasets ──────────────────────────────────────────────────────────────

    def package_show(self, id: str) -> dict:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT data FROM cdm.catalog_dataset WHERE id = :id OR name = :id"),
                {"id": id},
            ).fetchone()
        if not row:
            raise NotFound(f"Dataset not found: {id}")
        return row[0]

    def package_create(self, name: str, **fields) -> dict:
        resources = [
            {"id": str(uuid.uuid4()), **res} for res in (fields.pop("resources", None) or [])
        ]
        data = {"id": str(uuid.uuid4()), "name": name, "resources": resources, **fields}
        self._save(data, created=True)
        return data

    def package_patch(self, id: str, **fields) -> dict:
        data = dict(self.package_show(id=id))
        if "resources" in fields:
            # Keep ids of resources that are still listed (matched by URL), so
            # links to them stay valid across harvests.
            known = {r.get("url"): r["id"] for r in data.get("resources", []) if r.get("url")}
            fields["resources"] = [
                {"id": known.get(res.get("url")) or str(uuid.uuid4()), **res}
                for res in fields["resources"]
            ]
        data.update(fields)
        self._save(data, created=False)
        return data

    def _save(self, data: dict, created: bool) -> None:
        extras = {e["key"]: e["value"] for e in data.get("extras") or []}
        params = {
            "id": data["id"],
            "name": data["name"],
            "title": data.get("title") or data["name"],
            "notes": data.get("notes") or "",
            "owner_org": data.get("owner_org"),
            "groups": [g["name"] for g in data.get("groups") or []],
            "formats": sorted({(r.get("format") or "").upper() for r in data.get("resources") or []} - {""}),
            "featured": extras.get("featured") == "true",
            "data": json.dumps(data, default=str),
            "tags": " ".join(t["name"] for t in data.get("tags") or []),
        }
        if created:
            sql = f"""
                INSERT INTO cdm.catalog_dataset
                    (id, name, title, notes, owner_org, groups, formats, featured, data, search)
                VALUES
                    (:id, :name, :title, :notes, :owner_org, :groups, :formats, :featured,
                     CAST(:data AS jsonb), {_SEARCH_SQL})
            """
        else:
            sql = f"""
                UPDATE cdm.catalog_dataset SET
                    title = :title, notes = :notes, owner_org = :owner_org,
                    groups = :groups, formats = :formats, featured = :featured,
                    data = CAST(:data AS jsonb), search = {_SEARCH_SQL},
                    metadata_modified = NOW()
                WHERE id = :id
            """
        with get_engine().begin() as conn:
            conn.execute(text(sql), params)

    # ── Topics and publishers ─────────────────────────────────────────────────

    def group_show(self, id: str) -> dict:
        return self._group_show("group", id)

    def group_create(self, name: str, title: str = "", description: str = "", **_) -> dict:
        return self._group_create("group", name, title, description)

    def organization_show(self, id: str) -> dict:
        return self._group_show("organization", id)

    def organization_create(self, name: str, title: str = "", description: str = "", **_) -> dict:
        return self._group_create("organization", name, title, description)

    def _group_show(self, kind: str, name: str) -> dict:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT name, title, description FROM cdm.catalog_group WHERE kind = :kind AND name = :name"),
                {"kind": kind, "name": name},
            ).fetchone()
        if not row:
            raise NotFound(f"{kind} not found: {name}")
        return {"name": row[0], "title": row[1], "description": row[2]}

    def _group_create(self, kind: str, name: str, title: str, description: str) -> dict:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO cdm.catalog_group (kind, name, title, description)
                    VALUES (:kind, :name, :title, :description)
                    ON CONFLICT (kind, name) DO UPDATE SET
                        title = EXCLUDED.title, description = EXCLUDED.description
                """),
                {"kind": kind, "name": name, "title": title or name, "description": description or ""},
            )
        return {"name": name, "title": title or name, "description": description or ""}

    # ── Resources and data tables ─────────────────────────────────────────────

    def resource_delete(self, id: str) -> None:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT data FROM cdm.catalog_dataset
                    WHERE data->'resources' @> CAST(:probe AS jsonb)
                """),
                {"probe": json.dumps([{"id": id}])},
            ).fetchone()
        if not row:
            return
        data = dict(row[0])
        data["resources"] = [r for r in data.get("resources", []) if r["id"] != id]
        self._save(data, created=False)
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM cdm.catalog_table WHERE resource_id = :id"), {"id": id})

    def datastore_create(
        self,
        fields: list[dict],
        primary_key: list[str] | None = None,
        force: bool = False,
        resource: dict | None = None,
        resource_id: str | None = None,
        records: list[dict] | None = None,
    ) -> dict:
        if resource is not None:
            data = dict(self.package_show(id=resource["package_id"]))
            resource_id = str(uuid.uuid4())
            data.setdefault("resources", []).append({
                "id": resource_id,
                "url": DUMP_PATH.format(resource_id=resource_id),
                "url_type": "datastore",
                "datastore_active": True,
                "created": _now(),
                **{k: v for k, v in resource.items() if k != "package_id"},
            })
            self._save(data, created=False)
            dataset_id = data["id"]
        else:
            dataset_id = self._dataset_of(resource_id)

        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO cdm.catalog_table (resource_id, dataset_id, fields, primary_key)
                    VALUES (:rid, :did, CAST(:fields AS jsonb), CAST(:pk AS jsonb))
                    ON CONFLICT (resource_id) DO UPDATE SET
                        fields = EXCLUDED.fields, primary_key = EXCLUDED.primary_key
                """),
                {"rid": resource_id, "did": dataset_id,
                 "fields": json.dumps(fields), "pk": json.dumps(primary_key or [])},
            )
        if records:
            self.datastore_upsert(resource_id=resource_id, records=records, method="upsert")
        return {"resource_id": resource_id}

    def datastore_upsert(self, resource_id: str, records: list[dict], method: str = "upsert", force: bool = False) -> dict:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT primary_key FROM cdm.catalog_table WHERE resource_id = :rid"),
                {"rid": resource_id},
            ).fetchone()
        if not row:
            raise NotFound(f"No data table for resource {resource_id}")
        primary_key = row[0] or []

        rows = [
            {
                "rid": resource_id,
                # Without a declared key every record is its own row.
                "key": "|".join(str(rec.get(k, "")) for k in primary_key) if primary_key else str(uuid.uuid4()),
                "data": json.dumps(rec, default=str),
            }
            for rec in records
        ]
        if rows:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO cdm.catalog_row (resource_id, row_key, data)
                        VALUES (:rid, :key, CAST(:data AS jsonb))
                        ON CONFLICT (resource_id, row_key) DO UPDATE SET data = EXCLUDED.data
                    """),
                    rows,
                )
                conn.execute(
                    text("""
                        UPDATE cdm.catalog_dataset SET metadata_modified = NOW()
                        WHERE id = (SELECT dataset_id FROM cdm.catalog_table WHERE resource_id = :rid)
                    """),
                    {"rid": resource_id},
                )
        return {"resource_id": resource_id}

    def _dataset_of(self, resource_id: str | None) -> str:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT id FROM cdm.catalog_dataset WHERE data->'resources' @> CAST(:probe AS jsonb)"),
                {"probe": json.dumps([{"id": resource_id}])},
            ).fetchone()
        if not row:
            raise NotFound(f"Resource not found: {resource_id}")
        return row[0]
