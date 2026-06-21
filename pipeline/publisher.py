"""Publishing datasets and resources to the CKAN open data catalog."""
from __future__ import annotations

import logging

import pandas as pd
from ckanapi import NotFound, RemoteCKAN, ValidationError

from pipeline.settings import settings

logger = logging.getLogger(__name__)


def _get_ckan_client() -> RemoteCKAN | None:
    """Return an authenticated CKAN client, or None if no API key is configured."""
    key = settings.ckan_key()
    if not key:
        logger.warning("CKAN_API_KEY not set — CKAN publishing is disabled.")
        return None
    return RemoteCKAN(settings.ckan_url, apikey=key)


def _make_package_id(name: str) -> str:
    """Convert a human name to a CKAN-safe package ID."""
    return (
        name.lower()
        .strip()
        .replace(" ", "-")
        .replace("(", "")
        .replace(")", "")
        .replace("/", "-")
        .replace(",", "")
        .replace("&", "and")
        .replace(".", "")
        [:100]  # CKAN max package name length
    )


def publish_indicator_to_ckan(
    source_id: str,
    indicator_config: dict,
    record_count: int,
) -> bool:
    """Create or update a CKAN dataset entry for one indicator.

    Args:
        source_id:        e.g. 'CBN', 'NigeriaDataPortal'
        indicator_config: The indicator dict from SOURCE_REGISTRY.
        record_count:     Number of CDM rows for this indicator.

    Returns:
        True if published successfully, False if skipped (no API key or error).
    """
    ckan = _get_ckan_client()
    if ckan is None:
        return False

    indicator_name = indicator_config["name"]
    indicator_id   = indicator_config["id"]
    domain         = indicator_config.get("domain", "economics")
    unit           = indicator_config.get("unit", "")
    package_id     = _make_package_id(f"ng-{indicator_id.lower().replace('_', '-')}")

    description = (
        f"**Nigeria Open Data – {indicator_name}**\n\n"
        f"- **Source**: {source_id}\n"
        f"- **Domain**: {domain.title()}\n"
        f"- **Indicator ID**: {indicator_id}\n"
        f"- **Unit**: {unit}\n"
        f"- **Records**: {record_count:,}\n\n"
        f"Data automatically ingested by the Naija Open Data pipeline. "
        f"Values are stored in the CDM (Common Data Model) table "
        f"`cdm.indicator_observation` and updated on every pipeline run."
    )

    tags = [
        {"name": "nigeria"},
        {"name": domain},
        {"name": source_id.lower()},
        {"name": "automated-ingestion"},
    ]

    try:
        # ── Try to fetch existing package ────────────────────────────────────
        try:
            existing = ckan.action.package_show(id=package_id)
            logger.debug("Updating existing CKAN package: %s", package_id)
            ckan.action.package_update(
                id=package_id,
                notes=description,
                tags=tags,
            )
        except NotFound:
            # ── Create new package ───────────────────────────────────────────
            logger.info("Creating new CKAN package: %s", package_id)
            existing = ckan.action.package_create(
                name=package_id,
                title=f"Nigeria – {indicator_name}",
                notes=description,
                owner_org=settings.ckan_org_id,
                tags=tags,
                extras=[
                    {"key": "domain",       "value": domain},
                    {"key": "indicator_id", "value": indicator_id},
                    {"key": "source",       "value": source_id},
                    {"key": "unit",         "value": unit},
                ],
            )

        # ── Upsert a summary resource into the package ────────────────────────
        # We push a minimal metadata CSV; the real data is in the CDM DB.
        _upsert_summary_resource(ckan, existing["id"], package_id, indicator_config, record_count)

        logger.info("CKAN published: %s (%d records)", package_id, record_count)
        return True

    except ValidationError as exc:
        logger.error("CKAN validation error for %s: %s", package_id, exc)
        return False
    except Exception as exc:
        logger.error("CKAN publish failed for %s: %s", package_id, exc, exc_info=True)
        return False


def _upsert_summary_resource(
    ckan: RemoteCKAN,
    package_id: str,
    package_name: str,
    indicator_config: dict,
    record_count: int,
) -> None:
    """Push a small metadata summary to the CKAN DataStore for this indicator."""
    resource_name = f"{indicator_config['name']} – Summary"

    # Build a one-row summary DataFrame
    summary_df = pd.DataFrame([{
        "indicator_id":   indicator_config["id"],
        "indicator_name": indicator_config["name"],
        "source_system":  indicator_config.get("source_id", ""),
        "domain":         indicator_config.get("domain", ""),
        "unit":           indicator_config.get("unit", ""),
        "record_count":   record_count,
    }])

    fields   = [{"id": col, "type": "text"} for col in summary_df.columns]
    records  = summary_df.to_dict(orient="records")

    # Fetch existing resources for this package
    pkg      = ckan.action.package_show(id=package_id)
    existing_resource = next(
        (r for r in pkg.get("resources", []) if r["name"] == resource_name), None
    )

    try:
        if existing_resource:
            resource_id = existing_resource["id"]
        else:
            res = ckan.action.resource_create(
                package_id=package_id,
                name=resource_name,
                format="CSV",
            )
            resource_id = res["id"]

        ckan.action.datastore_create(
            resource_id=resource_id,
            force=True,
            fields=fields,
            records=records,
        )
    except Exception as exc:
        logger.warning("Could not upsert summary resource for %s: %s", package_name, exc)
