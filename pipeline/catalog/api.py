"""Read API for the built-in catalogue, in the shape of CKAN's Action API.

The frontend was written against CKAN. Serving the same routes and response
shapes here means it runs unchanged against either backend:

    GET /api/3/action/package_search?q=&fq=&rows=&start=
    GET /api/3/action/package_show?id=
    GET /api/3/action/group_list?all_fields=true
    GET /api/3/action/organization_list?all_fields=true
    GET /api/3/action/datastore_search?resource_id=&limit=&offset=
    GET /datastore/dump/<resource_id>            (CSV download)

Everything here is read-only.
"""
from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text

from pipeline.db.warehouse import get_engine

router = APIRouter(tags=["Catalogue"])

_MAX_ROWS = 1000
_MAX_RECORDS = 32000
_DUMP_BATCH = 5000

# CKAN licence ids → titles, for the ids the pipeline writes.
_LICENCE_TITLES = {
    "cc-by": "Creative Commons Attribution",
    "cc-by-sa": "Creative Commons Attribution Share-Alike",
    "cc-zero": "Creative Commons CCZero",
    "odc-by": "Open Data Commons Attribution License",
    "odc-odbl": "Open Data Commons Open Database License (ODbL)",
    "odc-pddl": "Open Data Commons Public Domain Dedication and License (PDDL)",
    "other-open": "Other (Open)",
    "notspecified": "License not specified",
}


def _ok(result) -> dict:
    return {"success": True, "result": result}


def _not_found(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"success": False, "error": {"__type": "Not Found Error", "message": message}},
    )


def _parse_fq(fq: str) -> dict[str, str]:
    """'res_format:CSV AND groups:health' → {'res_format': 'CSV', 'groups': 'health'}.

    Only the simple field:value form the frontend sends is understood;
    anything else is ignored instead of being guessed at.
    """
    filters: dict[str, str] = {}
    for term in re.split(r"\s+AND\s+|\s+", fq.strip()):
        match = re.fullmatch(r'\+?([a-z_]+):"?([^"]+)"?', term)
        if match:
            filters[match.group(1)] = match.group(2)
    return filters


def _labels(conn, kind: str) -> dict[str, dict]:
    rows = conn.execute(
        text("SELECT name, title, description FROM cdm.catalog_group WHERE kind = :kind"), {"kind": kind}
    ).fetchall()
    return {r[0]: {"name": r[0], "title": r[1] or r[0], "description": r[2] or ""} for r in rows}


def _present(row, orgs: dict, groups: dict) -> dict:
    """Turn a stored dataset row into the dataset dict CKAN would return."""
    data = dict(row.data)
    org = orgs.get(row.owner_org) if row.owner_org else None
    data.update({
        "id": row.id,
        "name": row.name,
        "title": row.title,
        "notes": row.notes,
        "metadata_created": row.metadata_created.isoformat(),
        "metadata_modified": row.metadata_modified.isoformat(),
        "organization": ({"id": org["name"], **org} if org else None),
        "groups": [
            {"id": g, "name": g, "title": groups.get(g, {}).get("title", g),
             "display_name": groups.get(g, {}).get("title", g)}
            for g in row.groups
        ],
        "num_resources": len(data.get("resources") or []),
        "license_title": _LICENCE_TITLES.get(data.get("license_id") or "", data.get("license_id") or ""),
    })
    return data


_DATASET_COLUMNS = "id, name, title, notes, owner_org, groups, data, metadata_created, metadata_modified"


@router.get("/api/3/action/package_search")
def package_search(
    q: str = "",
    fq: str = "",
    rows: int = Query(10, ge=0, le=_MAX_ROWS),
    start: int = Query(0, ge=0),
):
    """Search datasets. Featured datasets lead when there is no search text."""
    where, params = ["true"], {"rows": rows, "start": start}

    query = q.strip()
    if query and query != "*:*":
        # Full-text match, plus a plain substring match on the title so short
        # or partial words ("gdp", "elect") still find something.
        where.append("(search @@ websearch_to_tsquery('english', :q) OR title ILIKE :like)")
        params.update({"q": query, "like": f"%{query}%"})
        order = "ts_rank(search, websearch_to_tsquery('english', :q)) DESC, featured DESC, title"
    else:
        order = "featured DESC, title"

    filters = _parse_fq(fq)
    if filters.get("groups"):
        where.append("groups @> ARRAY[:group]")
        params["group"] = filters["groups"]
    if filters.get("organization"):
        where.append("owner_org = :org")
        params["org"] = filters["organization"]
    if filters.get("res_format"):
        where.append("formats @> ARRAY[:format]")
        params["format"] = filters["res_format"].upper()

    clause = " AND ".join(where)
    with get_engine().connect() as conn:
        count = conn.execute(text(f"SELECT count(*) FROM cdm.catalog_dataset WHERE {clause}"), params).scalar()
        found = conn.execute(
            text(f"""
                SELECT {_DATASET_COLUMNS} FROM cdm.catalog_dataset
                WHERE {clause} ORDER BY {order} LIMIT :rows OFFSET :start
            """),
            params,
        ).fetchall()
        orgs, groups = _labels(conn, "organization"), _labels(conn, "group")
    return _ok({"count": count, "results": [_present(r, orgs, groups) for r in found]})


@router.get("/api/3/action/package_show")
def package_show(id: str):
    with get_engine().connect() as conn:
        row = conn.execute(
            text(f"SELECT {_DATASET_COLUMNS} FROM cdm.catalog_dataset WHERE id = :id OR name = :id"),
            {"id": id},
        ).fetchone()
        if not row:
            return _not_found("Dataset not found")
        orgs, groups = _labels(conn, "organization"), _labels(conn, "group")
    return _ok(_present(row, orgs, groups))


def _list_with_counts(kind: str, count_sql: str, all_fields: bool):
    with get_engine().connect() as conn:
        labels = _labels(conn, kind)
        counts = dict(conn.execute(text(count_sql)).fetchall())
    items = [
        {"id": name, **label, "display_name": label["title"], "package_count": counts.get(name, 0)}
        for name, label in labels.items()
    ]
    items.sort(key=lambda item: (-item["package_count"], item["title"].lower()))
    return _ok(items if all_fields else [item["name"] for item in items])


@router.get("/api/3/action/group_list")
def group_list(all_fields: bool = False):
    """Topics, busiest first."""
    return _list_with_counts(
        "group",
        "SELECT g, count(*) FROM cdm.catalog_dataset, unnest(groups) AS g GROUP BY g",
        all_fields,
    )


@router.get("/api/3/action/organization_list")
def organization_list(all_fields: bool = False):
    """Publishers, busiest first."""
    return _list_with_counts(
        "organization",
        "SELECT owner_org, count(*) FROM cdm.catalog_dataset WHERE owner_org IS NOT NULL GROUP BY owner_org",
        all_fields,
    )


def _table(conn, resource_id: str):
    return conn.execute(
        text("""
            SELECT t.fields, d.name
            FROM cdm.catalog_table t JOIN cdm.catalog_dataset d ON d.id = t.dataset_id
            WHERE t.resource_id = :rid
        """),
        {"rid": resource_id},
    ).fetchone()


@router.get("/api/3/action/datastore_search")
def datastore_search(
    resource_id: str,
    limit: int = Query(100, ge=0, le=_MAX_RECORDS),
    offset: int = Query(0, ge=0),
):
    """Rows of a data table, in key order (for a time series: oldest first)."""
    with get_engine().connect() as conn:
        table = _table(conn, resource_id)
        if not table:
            return _not_found(f'Resource "{resource_id}" was not found.')
        total = conn.execute(
            text("SELECT count(*) FROM cdm.catalog_row WHERE resource_id = :rid"), {"rid": resource_id}
        ).scalar()
        records = [
            r[0] for r in conn.execute(
                text("""
                    SELECT data FROM cdm.catalog_row WHERE resource_id = :rid
                    ORDER BY row_key LIMIT :limit OFFSET :offset
                """),
                {"rid": resource_id, "limit": limit, "offset": offset},
            )
        ]
    return _ok({
        "resource_id": resource_id,
        "fields": table[0],
        "records": records,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@router.get("/datastore/dump/{resource_id}")
def datastore_dump(resource_id: str):
    """Download a whole data table as CSV."""
    with get_engine().connect() as conn:
        table = _table(conn, resource_id)
    if not table:
        return _not_found(f'Resource "{resource_id}" was not found.')
    columns = [f["id"] for f in table[0]]

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        offset = 0
        while True:
            with get_engine().connect() as conn:
                batch = conn.execute(
                    text("""
                        SELECT data FROM cdm.catalog_row WHERE resource_id = :rid
                        ORDER BY row_key LIMIT :limit OFFSET :offset
                    """),
                    {"rid": resource_id, "limit": _DUMP_BATCH, "offset": offset},
                ).fetchall()
            for (record,) in batch:
                writer.writerow(["" if record.get(c) is None else record.get(c) for c in columns])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            if len(batch) < _DUMP_BATCH:
                return
            offset += _DUMP_BATCH

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{table[1]}.csv"'},
    )
