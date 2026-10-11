"""Publishing indicator datasets to the CKAN open data catalogue.

One indicator becomes one CKAN dataset holding one DataStore resource with the
indicator's full table. Because the rows live in the DataStore, CKAN serves
them three ways without any extra code on our side:

    download   <ckan>/datastore/dump/<resource_id>          (CSV)
    query API  <ckan>/api/3/action/datastore_search?resource_id=...
    preview    CKAN's own table view, and the Next.js dataset page

Every dataset also carries where the numbers came from, the licence they are
shared under, the period they cover and when they were last refreshed.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from ckanapi import NotAuthorized, NotFound, RemoteCKAN, ValidationError

from pipeline.settings import settings

logger = logging.getLogger(__name__)

# Publish outcomes, stored in cdm.ingest_manifest.publish_state.
PUBLISHED = "published"
DISABLED = "disabled"     # no CKAN API key configured
FAILED = "failed"

DATA_RESOURCE_NAME = "Full data table"
_UPSERT_BATCH = 5000

# DataStore columns, in download order. (geo_code, period) identifies a row.
_FIELDS = [
    {"id": "period",         "type": "text"},
    {"id": "value",          "type": "numeric"},
    {"id": "unit",           "type": "text"},
    {"id": "geo_name",       "type": "text"},
    {"id": "geo_code",       "type": "text"},
    {"id": "geo_level",      "type": "text"},
    {"id": "period_type",    "type": "text"},
    {"id": "indicator_id",   "type": "text"},
    {"id": "indicator_name", "type": "text"},
    {"id": "source_system",  "type": "text"},
    {"id": "last_updated_at", "type": "timestamp"},
]
_PRIMARY_KEY = ["geo_code", "period"]


class PublishError(RuntimeError):
    """CKAN rejected or could not complete a publish."""


def ckan_enabled() -> bool:
    """True when a CKAN API key is configured, so publishing can happen."""
    return bool(settings.ckan_key())


def _get_ckan_client() -> RemoteCKAN | None:
    """Return an authenticated CKAN client, or None if no API key is configured."""
    key = settings.ckan_key()
    if not key:
        logger.warning("CKAN_API_KEY not set — CKAN publishing is disabled.")
        return None
    return RemoteCKAN(settings.ckan_url, apikey=key)


def slugify(text: str, max_length: int = 100) -> str:
    """Make a CKAN-safe name: lowercase letters, digits, '-' and '_' only."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(text).lower().replace("&", " and "))
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:max_length].rstrip("-") or "dataset"


def package_name_for(indicator_id: str) -> str:
    """'WB_NY_GDP_MKTP_CD' → 'ng-wb-ny-gdp-mktp-cd'."""
    return slugify(f"ng-{indicator_id.replace('_', '-')}")


def _clean_tag(text: str) -> str | None:
    """CKAN tags allow letters, digits, spaces and - _ . only (2–100 chars)."""
    tag = re.sub(r"[^\w .-]+", " ", str(text)).strip()
    tag = re.sub(r"\s{2,}", " ", tag)[:100]
    return tag if len(tag) >= 2 else None


def publish_indicator_to_ckan(
    source_id: str,
    indicator_config: dict,
    record_count: int | None = None,
    source_options: dict | None = None,
    ckan: RemoteCKAN | None = None,
) -> str:
    """Create or refresh the CKAN dataset for one indicator, with its full table.

    Args:
        source_id:        e.g. 'WorldBank', 'CBN'.
        indicator_config: The indicator dict (id, name, domain, unit, ...).
        record_count:     Unused; kept so older callers keep working. The
                          count shown to users is read from the database.
        source_options:   cdm.data_sources.options for the source (licence,
                          attribution, source URL).
        ckan:             A CKAN client to use. Tests pass a fake here.

    Returns:
        PUBLISHED, or DISABLED when no API key is configured.

    Raises:
        PublishError: when CKAN refuses or the call fails. The caller records
        the failure and the next run publishes again, so data that reached the
        warehouse is never silently left off the portal.
    """
    from pipeline.db.warehouse import fetch_observations

    ckan = ckan or _get_ckan_client()
    if ckan is None:
        return DISABLED

    options = source_options or {}
    indicator_id = indicator_config["id"]
    name = package_name_for(indicator_id)

    rows = fetch_observations(source_id, indicator_id)
    if not rows:
        logger.info("No stored observations for %s/%s — nothing to publish.", source_id, indicator_id)
        return PUBLISHED

    try:
        package = _upsert_package(ckan, name, source_id, indicator_config, options, rows)
        resource_id = _upsert_data_resource(ckan, package, indicator_config, rows)
        _remove_legacy_summary(ckan, package, indicator_config)
    except Exception as exc:
        raise PublishError(f"CKAN publish failed for {name}: {exc}") from exc

    logger.info("CKAN published: %s (%d rows, resource %s)", name, len(rows), resource_id)
    return PUBLISHED


# ── Dataset (package) ─────────────────────────────────────────────────────────

def _build_package_fields(
    source_id: str,
    indicator_config: dict,
    options: dict,
    rows: list[dict],
) -> dict:
    """Everything about the dataset except its name and resources."""
    indicator_name = indicator_config["name"]
    indicator_id = indicator_config["id"]
    domain = indicator_config.get("domain") or "general"
    unit = indicator_config.get("unit") or (rows[0].get("unit") if rows else "") or ""

    periods = sorted(r["period"] for r in rows if r.get("period"))
    first_period, last_period = (periods[0], periods[-1]) if periods else ("", "")
    geo_levels = sorted({r["geo_level"] for r in rows if r.get("geo_level")})

    source_name = options.get("source_name") or source_id
    source_url = (
        indicator_config.get("source_url")
        or _first(rows, "raw_source_url")
        or options.get("source_url")
        or ""
    )
    licence_title = options.get("license_title") or "Not specified by the source"

    parts: list[str] = []
    if indicator_config.get("description"):
        parts.append(indicator_config["description"].strip())
    parts.append(
        f"**Source:** {source_name}"
        + (f" ([original]({source_url}))" if source_url else "")
        + f"  \n**Licence:** {licence_title}"
        + (f"  \n**Unit:** {unit}" if unit else "")
        + (f"  \n**Coverage:** {first_period} to {last_period}" if first_period else "")
        + f"  \n**Observations:** {len(rows):,}"
    )
    if indicator_config.get("source_organization"):
        parts.append(f"**Original compiler:** {indicator_config['source_organization']}")
    parts.append(
        "Collected and republished by Naija Open Data, an independent open-source "
        "project. Figures are the source's own; check the original before citing."
    )

    tags = [
        {"name": t}
        for t in dict.fromkeys(  # keep order, drop duplicates
            filter(None, (_clean_tag(x) for x in ("nigeria", domain, source_id)))
        )
    ]

    extras = {
        "domain": domain,
        "indicator_id": indicator_id,
        "source": source_name,
        "source_system": source_id,
        "source_url": source_url,
        "source_code": indicator_config.get("dataset_id") or "",
        "unit": unit,
        "temporal_start": first_period,
        "temporal_end": last_period,
        "geographic_levels": ", ".join(geo_levels),
        "observation_count": str(len(rows)),
        # Named so they cannot clash with CKAN's own license_* dataset fields.
        "licence_name": licence_title,
        "licence_url": options.get("license_url") or "",
        "last_refreshed": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "featured": "true" if indicator_config.get("featured") else "false",
    }

    return {
        "title": f"Nigeria – {indicator_name}",
        "notes": "\n\n".join(parts),
        "url": source_url,
        "license_id": options.get("license_id") or "notspecified",
        "tags": tags,
        "extras": [{"key": k, "value": v} for k, v in extras.items() if v != ""],
    }


def _upsert_package(
    ckan: RemoteCKAN,
    name: str,
    source_id: str,
    indicator_config: dict,
    options: dict,
    rows: list[dict],
) -> dict:
    fields = _build_package_fields(source_id, indicator_config, options, rows)
    group = _ensure_group(ckan, indicator_config.get("domain"))
    if group:
        fields["groups"] = [{"name": group}]

    try:
        existing = ckan.action.package_show(id=name)
    except NotFound:
        existing = None

    def write(payload: dict) -> dict:
        if existing is None:
            logger.info("Creating CKAN dataset: %s", name)
            return ckan.action.package_create(name=name, owner_org=settings.ckan_org_id, **payload)
        # package_patch changes only the fields sent. package_update would
        # drop anything left out, including the data resource.
        ckan.action.package_patch(id=existing["id"], **payload)
        return existing

    try:
        return write(fields)
    except (NotAuthorized, ValidationError) as exc:
        if "groups" not in fields:
            raise
        # The API key may not be allowed to add datasets to this topic.
        # A dataset without a topic is better than no dataset.
        logger.warning("Publishing %s without a topic (group rejected: %s)", name, exc)
        return write({k: v for k, v in fields.items() if k != "groups"})


def _ensure_group(ckan: RemoteCKAN, domain: str | None) -> str | None:
    """Make sure a CKAN group (topic) exists for the domain. Best effort.

    Topics on the site are CKAN groups. If the group cannot be created (for
    example the API key is not a sysadmin), the dataset is still published,
    just without a topic.
    """
    if not domain:
        return None
    name = slugify(domain)
    try:
        ckan.action.group_show(id=name)
        return name
    except NotFound:
        pass
    except Exception as exc:
        logger.warning("Could not look up CKAN group '%s': %s", name, exc)
        return None
    try:
        ckan.action.group_create(name=name, title=domain.replace("-", " ").title())
        logger.info("Created CKAN group (topic): %s", name)
        return name
    except Exception as exc:
        logger.warning("Could not create CKAN group '%s': %s", name, exc)
        return None


# ── Data resource (DataStore table) ───────────────────────────────────────────

def _upsert_data_resource(
    ckan: RemoteCKAN,
    package: dict,
    indicator_config: dict,
    rows: list[dict],
) -> str:
    """Write the full table to the DataStore. Returns the resource id.

    Rows are upserted on (geo_code, period): revised values overwrite, new
    periods are added. A value the source later withdraws stays until the
    resource is rebuilt; sources in use so far revise values, not remove them.
    """
    records = [{f["id"]: row.get(f["id"]) for f in _FIELDS} for row in rows]

    existing = next(
        (r for r in package.get("resources", []) if r.get("name") == DATA_RESOURCE_NAME),
        None,
    )

    if existing:
        resource_id = existing["id"]
        ckan.action.datastore_create(
            resource_id=resource_id,
            fields=_FIELDS,
            primary_key=_PRIMARY_KEY,
            force=True,
        )
    else:
        # Passing `resource` makes CKAN create the resource and point its URL
        # at the DataStore CSV dump, so "Download" works straight away.
        created = ckan.action.datastore_create(
            resource={
                "package_id": package["id"],
                "name": DATA_RESOURCE_NAME,
                "format": "CSV",
                "description": (
                    f"All observations for {indicator_config['name']}. "
                    "One row per place and period."
                ),
            },
            fields=_FIELDS,
            primary_key=_PRIMARY_KEY,
            force=True,
        )
        resource_id = created["resource_id"]

    for start in range(0, len(records), _UPSERT_BATCH):
        ckan.action.datastore_upsert(
            resource_id=resource_id,
            records=records[start:start + _UPSERT_BATCH],
            method="upsert",
            force=True,
        )
    return resource_id


def _remove_legacy_summary(ckan: RemoteCKAN, package: dict, indicator_config: dict) -> None:
    """Delete the one-row '– Summary' resource earlier versions created."""
    legacy_name = f"{indicator_config['name']} – Summary"
    for res in package.get("resources", []):
        if res.get("name") == legacy_name:
            try:
                ckan.action.resource_delete(id=res["id"])
                logger.info("Removed legacy summary resource from %s", package.get("name"))
            except Exception as exc:
                logger.warning("Could not remove legacy summary resource: %s", exc)


def _first(rows: list[dict], key: str):
    for row in rows:
        if row.get(key):
            return row[key]
    return None
